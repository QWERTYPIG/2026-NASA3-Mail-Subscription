"""Tests for the write side (``apps.subscriptions.writes``). No LDAP access."""

import threading
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from .. import views, writes
from ..models import Alias, AliasMember, SyncTask


def tasks():
    return list(SyncTask.objects.values_list("kind", "action", "alias_name", "user_uid"))


def members(alias_name):
    return list(
        AliasMember.objects.filter(alias_id=alias_name).values_list("user_uid", flat=True)
    )


class WriteFunctionTest(TestCase):
    def test_create_alias(self):
        writes.create_alias("a", "A", "desc")
        self.assertTrue(Alias.objects.filter(alias_name="a", display_name="A").exists())
        self.assertEqual(tasks(), [("alias", "add", "a", None)])

    def test_create_existing_alias_raises_without_task(self):
        Alias.objects.create(alias_name="a")
        with self.assertRaises(writes.AliasExists):
            writes.create_alias("a")
        self.assertEqual(tasks(), [])

    def test_delete_alias_cascades_members(self):
        writes.create_alias("a")
        writes.add_member("a", "x")
        writes.delete_alias("a")
        self.assertFalse(Alias.objects.exists())
        self.assertFalse(AliasMember.objects.exists())
        self.assertEqual(tasks()[-1], ("alias", "remove", "a", None))

    def test_delete_missing_alias_raises(self):
        with self.assertRaises(writes.AliasNotFound):
            writes.delete_alias("nope")
        self.assertEqual(tasks(), [])

    def test_add_and_remove_member(self):
        Alias.objects.create(alias_name="a")
        writes.add_member("a", "x")
        self.assertEqual(members("a"), ["x"])
        writes.remove_member("a", "x")
        self.assertEqual(members("a"), [])
        self.assertEqual(
            tasks(), [("member", "add", "a", "x"), ("member", "remove", "a", "x")]
        )

    def test_member_errors_raise_without_task(self):
        Alias.objects.create(alias_name="a")
        AliasMember.objects.create(alias_id="a", user_uid="x")
        with self.assertRaises(writes.AliasNotFound):
            writes.add_member("nope", "x")
        with self.assertRaises(writes.MemberExists):
            writes.add_member("a", "x")
        with self.assertRaises(writes.MemberNotFound):
            writes.remove_member("a", "y")
        self.assertEqual(tasks(), [])

    def test_set_subscriptions_only_enqueues_changes(self):
        for name in ["a", "b", "c"]:
            Alias.objects.create(alias_name=name)
        AliasMember.objects.create(alias_id="b", user_uid="u")
        AliasMember.objects.create(alias_id="c", user_uid="u")

        changed, task_ids = writes.set_subscriptions(
            "u", {"c": True, "b": False, "a": True, "gone": True}
        )

        self.assertEqual(changed, ["a", "b"])
        self.assertEqual(task_ids, list(SyncTask.objects.values_list("id", flat=True)))
        self.assertEqual(
            tasks(), [("member", "add", "a", "u"), ("member", "remove", "b", "u")]
        )
        self.assertEqual(members("a"), ["u"])
        self.assertEqual(members("b"), [])

    def test_four_step_scenario_keeps_add_y(self):
        """delete A -> (add x rejected) -> create A -> add y, in one id order."""
        writes.create_alias("A")
        writes.add_member("A", "old")
        SyncTask.objects.all().delete()

        writes.delete_alias("A")
        with self.assertRaises(writes.AliasNotFound):
            writes.add_member("A", "x")
        writes.create_alias("A")
        writes.add_member("A", "y")

        self.assertEqual(
            tasks(),
            [
                ("alias", "remove", "A", None),
                ("alias", "add", "A", None),
                ("member", "add", "A", "y"),
            ],
        )
        self.assertEqual(members("A"), ["y"])


class WriteAtomicityTest(TestCase):
    """A failed enqueue must leave the cache untouched."""

    def _failing_enqueue(self):
        return patch.object(writes, "_enqueue", side_effect=RuntimeError("queue down"))

    def test_create_alias_rolls_back(self):
        with self._failing_enqueue(), self.assertRaises(RuntimeError):
            writes.create_alias("a")
        self.assertFalse(Alias.objects.exists())

    def test_delete_alias_rolls_back(self):
        Alias.objects.create(alias_name="a")
        AliasMember.objects.create(alias_id="a", user_uid="x")
        with self._failing_enqueue(), self.assertRaises(RuntimeError):
            writes.delete_alias("a")
        self.assertEqual(members("a"), ["x"])

    def test_add_member_rolls_back(self):
        Alias.objects.create(alias_name="a")
        with self._failing_enqueue(), self.assertRaises(RuntimeError):
            writes.add_member("a", "x")
        self.assertEqual(members("a"), [])

    def test_set_subscriptions_rolls_back_all(self):
        Alias.objects.create(alias_name="a")
        Alias.objects.create(alias_name="b")
        with self._failing_enqueue(), self.assertRaises(RuntimeError):
            writes.set_subscriptions("u", {"a": True, "b": True})
        self.assertFalse(AliasMember.objects.exists())


class WriteLockTest(TestCase):
    def test_every_write_takes_the_alias_lock(self):
        Alias.objects.create(alias_name="a")
        AliasMember.objects.create(alias_id="a", user_uid="m")
        calls = [
            lambda: writes.create_alias("new"),
            lambda: writes.add_member("a", "x"),
            lambda: writes.remove_member("a", "m"),
            lambda: writes.set_subscriptions("u", {"a": True}),
            lambda: writes.delete_alias("a"),
        ]
        expected = [["new"], ["a"], ["a"], ["a"], ["a"]]
        with patch.object(writes, "_lock_aliases", wraps=writes._lock_aliases) as lock:
            for call in calls:
                call()
        self.assertEqual([sorted(c.args[0]) for c in lock.call_args_list], expected)

    def test_views_do_not_write_queue_or_members_directly(self):
        self.assertFalse(hasattr(views, "SyncTask"))
        self.assertFalse(hasattr(views, "transaction"))


class AdvisoryLockTest(TransactionTestCase):
    """The lock is real: another connection cannot take it until commit."""

    def _other_connection_can_lock(self, alias_name):
        result = {}

        def probe():
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_try_advisory_xact_lock(%s, hashtext(%s))",
                        [writes.ALIAS_LOCK_NAMESPACE, alias_name],
                    )
                    result["got"] = cursor.fetchone()[0]
            finally:
                connections.close_all()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join()
        return result["got"]

    def test_lock_held_until_commit(self):
        Alias.objects.create(alias_name="a")
        with transaction.atomic():
            writes.add_member("a", "x")
            self.assertFalse(self._other_connection_can_lock("a"))
            self.assertTrue(self._other_connection_can_lock("b"))
        self.assertTrue(self._other_connection_can_lock("a"))
