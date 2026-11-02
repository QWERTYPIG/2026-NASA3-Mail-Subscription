"""Tests for the sync interface (``apps.subscriptions.sync``). No LDAP access."""

from unittest.mock import patch

from django.test import TestCase

from .. import sync, writes
from ..models import Alias, AliasMember, SyncTask
from ..sync import Outcome


def queue():
    return list(SyncTask.objects.values_list("kind", "action", "alias_name", "user_uid"))


def members(alias_name):
    return set(
        AliasMember.objects.filter(alias_id=alias_name).values_list("user_uid", flat=True)
    )


def drain(session, outcome=Outcome.DONE):
    """Take every task the session gives, report ``outcome``, return them."""
    seen = []
    while (task := session.next_task()) is not None:
        seen.append(task)
        session.report(task, outcome)
    return seen


def enqueue(alias_name, kind="member", action="add", user_uid="u", **extra):
    if kind == "alias":
        user_uid = None
    return SyncTask.objects.create(
        kind=kind, action=action, alias_name=alias_name, user_uid=user_uid, **extra
    )


class TaskOrderTest(TestCase):
    def test_tasks_come_in_id_order_across_kinds(self):
        writes.create_alias("a")
        writes.add_member("a", "x")
        writes.create_alias("b")
        writes.remove_member("a", "x")
        expected = list(SyncTask.objects.values_list("id", flat=True))

        with sync.flush_session() as session:
            seen = drain(session)

        self.assertEqual([t.id for t in seen], expected)
        self.assertEqual(queue(), [])

    def test_task_format(self):
        enqueue("a", kind="alias", action="remove")
        enqueue("a", user_uid="x")
        with sync.flush_session() as session:
            alias_task = session.next_task()
            session.report(alias_task, Outcome.DONE)
            member_task = session.next_task()

        self.assertEqual(
            (alias_task.kind, alias_task.action, alias_task.alias_name, alias_task.user_uid),
            ("alias", "remove", "a", None),
        )
        self.assertEqual(
            (member_task.kind, member_task.action, member_task.user_uid),
            ("member", "add", "x"),
        )
        self.assertIsInstance(member_task, sync.Task)

    def test_four_step_scenario_keeps_add_y(self):
        """delete A -> (add x rejected) -> create A -> add y reaches LDAP."""
        writes.create_alias("A")
        SyncTask.objects.all().delete()

        writes.delete_alias("A")
        with self.assertRaises(writes.AliasNotFound):
            writes.add_member("A", "x")
        writes.create_alias("A")
        writes.add_member("A", "y")

        with sync.flush_session() as session:
            seen = drain(session)

        self.assertEqual(
            [(t.kind, t.action, t.user_uid) for t in seen],
            [("alias", "remove", None), ("alias", "add", None), ("member", "add", "y")],
        )
        self.assertEqual(queue(), [])

    def test_late_commit_with_lower_id_is_still_given(self):
        """No cursor: a lower id that shows up later is not skipped."""
        enqueue("b", id=5)
        with sync.flush_session() as session:
            first = session.next_task()
            session.report(first, Outcome.DONE)
            enqueue("a", id=3)  # committed after id 5 was handed out
            second = session.next_task()
        self.assertEqual((first.id, second.id), (5, 3))

    def test_session_only_gives_tasks_that_existed_at_open(self):
        enqueue("a")
        with sync.flush_session() as session:
            enqueue("a", user_uid="later")
            seen = drain(session)
        self.assertEqual([t.user_uid for t in seen], ["u"])
        self.assertEqual(queue(), [("member", "add", "a", "later")])


class OutcomeTest(TestCase):
    def test_done_and_obsolete_leave_the_queue(self):
        enqueue("a", user_uid="x")
        enqueue("a", user_uid="y")
        with sync.flush_session() as session:
            session.report(session.next_task(), Outcome.DONE)
            session.report(session.next_task(), "obsolete")  # plain string ok
        self.assertEqual(queue(), [])

    def test_retry_blocks_that_alias_only(self):
        a1 = enqueue("a", user_uid="1")
        enqueue("b", user_uid="2")
        a3 = enqueue("a", user_uid="3")
        enqueue("b", user_uid="4")

        with sync.flush_session() as session:
            first = session.next_task()
            session.report(first, Outcome.RETRY)
            rest = drain(session)

        self.assertEqual(first.id, a1.id)
        self.assertEqual([t.user_uid for t in rest], ["2", "4"])
        self.assertEqual(
            list(SyncTask.objects.values_list("id", flat=True)), [a1.id, a3.id]
        )

    def test_retried_task_comes_first_next_session(self):
        a1 = enqueue("a", user_uid="1")
        enqueue("a", user_uid="2")
        with sync.flush_session() as session:
            session.report(session.next_task(), Outcome.RETRY)
        with sync.flush_session() as session:
            self.assertEqual(session.next_task().id, a1.id)

    def test_unreported_task_counts_as_retry(self):
        a1 = enqueue("a", user_uid="1")
        enqueue("a", user_uid="2")
        b = enqueue("b")
        with sync.flush_session() as session:
            session.next_task()  # a1, never reported
            nxt = session.next_task()
        self.assertEqual(nxt.id, b.id)  # a is blocked
        self.assertEqual(SyncTask.objects.filter(id=a1.id).count(), 1)

    def test_unreported_task_at_session_end_stays(self):
        a1 = enqueue("a")
        with sync.flush_session() as session:
            session.next_task()
        self.assertEqual(list(SyncTask.objects.values_list("id", flat=True)), [a1.id])

    def test_reporting_wrong_task_raises(self):
        enqueue("a", user_uid="1")
        enqueue("b", user_uid="2")
        with sync.flush_session() as session:
            first = session.next_task()
            session.report(first, Outcome.DONE)
            with self.assertRaises(sync.SessionError):
                session.report(first, Outcome.DONE)  # already reported
            session.next_task()
            with self.assertRaises(sync.SessionError):
                session.report(first, Outcome.DONE)  # not the outstanding one

    def test_unknown_outcome_raises(self):
        enqueue("a")
        with sync.flush_session() as session:
            task = session.next_task()
            with self.assertRaises(ValueError):
                session.report(task, "maybe")

    def test_closed_session_raises(self):
        with sync.flush_session() as session:
            pass
        with self.assertRaises(sync.SessionError):
            session.next_task()


class SnapshotTest(TestCase):
    def test_snapshot_overwrites_members(self):
        Alias.objects.create(alias_name="a")
        AliasMember.objects.create(alias_id="a", user_uid="keep")
        AliasMember.objects.create(alias_id="a", user_uid="gone")

        with sync.flush_session() as session:
            result = session.apply_snapshot({"a": {"keep", "new"}})

        self.assertEqual(members("a"), {"keep", "new"})
        self.assertEqual(result.updated, ["a"])
        self.assertEqual(result.skipped, [])

    def test_snapshot_creates_and_deletes_aliases(self):
        Alias.objects.create(alias_name="cache-only")
        AliasMember.objects.create(alias_id="cache-only", user_uid="x")

        with sync.flush_session() as session:
            session.apply_snapshot({"ldap-only": {"y"}, "empty": set()})

        self.assertEqual(
            set(Alias.objects.values_list("alias_name", flat=True)), {"ldap-only", "empty"}
        )
        self.assertEqual(members("ldap-only"), {"y"})
        self.assertFalse(AliasMember.objects.filter(alias_id="cache-only").exists())

    def test_snapshot_keeps_display_fields(self):
        Alias.objects.create(alias_name="a", display_name="A", description="d")
        with sync.flush_session() as session:
            session.apply_snapshot({"a": set()})
        alias = Alias.objects.get(alias_name="a")
        self.assertEqual((alias.display_name, alias.description), ("A", "d"))

    def test_snapshot_skips_aliases_with_queued_tasks(self):
        writes.create_alias("pending")
        writes.add_member("pending", "y")  # queued, not yet in LDAP
        Alias.objects.create(alias_name="clean")

        with sync.flush_session() as session:
            result = session.apply_snapshot({"clean": {"z"}})

        self.assertEqual(result.skipped, ["pending"])
        self.assertEqual(members("pending"), {"y"})
        self.assertEqual(members("clean"), {"z"})

    def test_snapshot_skips_alias_left_on_retry(self):
        writes.create_alias("a")
        writes.add_member("a", "y")
        with sync.flush_session() as session:
            session.report(session.next_task(), Outcome.RETRY)
            result = session.apply_snapshot({})
        self.assertEqual(result.skipped, ["a"])
        self.assertTrue(Alias.objects.filter(alias_name="a").exists())

    def test_snapshot_does_not_skip_pending_delete_of_other_alias(self):
        """A queued alias/remove protects only that alias."""
        enqueue("old", kind="alias", action="remove")
        Alias.objects.create(alias_name="a")
        with sync.flush_session() as session:
            result = session.apply_snapshot({"old": {"x"}, "a": {"m"}})
        self.assertEqual(result.skipped, ["old"])
        self.assertFalse(Alias.objects.filter(alias_name="old").exists())
        self.assertEqual(members("a"), {"m"})

    def test_snapshot_takes_alias_lock_per_alias(self):
        Alias.objects.create(alias_name="b")
        with patch.object(sync, "_lock_aliases", wraps=sync._lock_aliases) as lock:
            with sync.flush_session() as session:
                session.apply_snapshot({"a": set(), "c": set()})
        self.assertEqual([c.args[0] for c in lock.call_args_list], [["a"], ["b"], ["c"]])
