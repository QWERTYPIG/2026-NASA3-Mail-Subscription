"""Tests for the Flush (``sync.flush`` given a Directory). No LDAP, no mocks."""

from datetime import timedelta
from unittest.mock import patch

from django.db import OperationalError, connection
from django.test import TestCase
from django.utils import timezone

from .. import sync, writes
from ..models import Alias, AliasMember, SyncTask
from ..sync import DirectoryUnavailable, Outcome, SnapshotStatus, StopReason
from .fakes import FakeDirectory
from .support import flush_lock_is_free, hold_flush_lock, other_connection


def queue():
    return list(SyncTask.objects.values_list("kind", "action", "alias_name", "user_uid"))


def members(alias_name):
    return set(
        AliasMember.objects.filter(alias_id=alias_name).values_list("user_uid", flat=True)
    )


def described(tasks):
    return [(t.alias_name, t.kind, t.action, t.user_uid) for t in tasks]


class TaskOrderTest(TestCase):
    def test_tasks_are_applied_in_id_order_across_kinds(self):
        writes.create_alias("a")
        writes.add_member("a", "x")
        writes.create_alias("b")
        writes.remove_member("a", "x")
        directory = FakeDirectory(snapshot={"a": set(), "b": set()})

        sync.flush(directory)

        self.assertEqual(
            described(directory.applied),
            [
                ("a", "alias", "add", None),
                ("a", "member", "add", "x"),
                ("b", "alias", "add", None),
                ("a", "member", "remove", "x"),
            ],
        )
        self.assertEqual(queue(), [])

    def test_delete_recreate_add_member_keeps_order(self):
        writes.create_alias("a")
        writes.delete_alias("a")
        writes.create_alias("a")
        writes.add_member("a", "y")
        directory = FakeDirectory(snapshot={"a": {"y"}})

        sync.flush(directory)

        self.assertEqual(
            described(directory.applied),
            [
                ("a", "alias", "add", None),
                ("a", "alias", "remove", None),
                ("a", "alias", "add", None),
                ("a", "member", "add", "y"),
            ],
        )
        self.assertEqual(members("a"), {"y"})

    def test_tasks_enqueued_during_flush_wait_for_next_flush(self):
        writes.create_alias("a")
        late = []

        def enqueue_during_flush(task):
            if not late:
                late.append(writes.add_member("a", "late"))

        directory = FakeDirectory(on_apply=enqueue_during_flush, snapshot={"a": set()})

        report = sync.flush(directory)

        self.assertEqual(described(directory.applied), [("a", "alias", "add", None)])
        self.assertEqual(queue(), [("member", "add", "a", "late")])
        self.assertEqual(report.stop_reason, StopReason.NONE)


class OutcomeTest(TestCase):
    def test_done_and_obsolete_leave_the_queue(self):
        writes.create_alias("a")
        obsolete = writes.add_member("a", "x")
        directory = FakeDirectory(outcomes={obsolete.id: Outcome.OBSOLETE}, snapshot={"a": set()})

        report = sync.flush(directory)

        self.assertEqual(queue(), [])
        self.assertEqual(report.done_count, 1)
        self.assertEqual(report.obsolete_count, 1)
        self.assertEqual(described(report.obsoleted), [("a", "member", "add", "x")])

    def test_retry_stays_queued_and_blocks_only_its_alias(self):
        writes.create_alias("a")
        writes.add_member("a", "x")
        writes.create_alias("b")
        writes.add_member("b", "y")
        directory = FakeDirectory(outcomes={"a": Outcome.RETRY}, snapshot={"b": {"y"}})

        report = sync.flush(directory)

        self.assertEqual(
            described(directory.applied),
            [
                ("a", "alias", "add", None),
                ("b", "alias", "add", None),
                ("b", "member", "add", "y"),
            ],
        )
        self.assertEqual(queue(), [("alias", "add", "a", None), ("member", "add", "a", "x")])
        self.assertEqual(report.retry_count, 1)
        self.assertEqual(described(report.retried), [("a", "alias", "add", None)])
        self.assertEqual(report.done_count, 2)

    def test_directory_unavailable_stops_flush_and_skips_snapshot(self):
        writes.create_alias("a")
        writes.create_alias("b")
        directory = FakeDirectory(outcomes={"a": DirectoryUnavailable()}, snapshot={})

        report = sync.flush(directory)

        self.assertEqual(described(directory.applied), [("a", "alias", "add", None)])
        self.assertEqual(queue(), [("alias", "add", "a", None), ("alias", "add", "b", None)])
        self.assertEqual(directory.snapshot_calls, 0)
        self.assertEqual(report.stop_reason, StopReason.DIRECTORY_UNAVAILABLE)
        self.assertEqual(report.snapshot_status, SnapshotStatus.NOT_TAKEN)
        self.assertEqual(set(Alias.objects.values_list("alias_name", flat=True)), {"a", "b"})

    def test_unexpected_error_propagates_and_keeps_task(self):
        writes.create_alias("a")
        directory = FakeDirectory(outcomes={"a": RuntimeError("bug")})

        with self.assertRaises(RuntimeError):
            sync.flush(directory)

        self.assertEqual(queue(), [("alias", "add", "a", None)])


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TaskBudgetTest(TestCase):
    def test_budget_stops_handing_out_tasks_but_snapshot_still_runs(self):
        for name in ("a", "b", "c"):
            writes.create_alias(name)
        clock = FakeClock()

        def slow_apply(task):
            clock.now += 100

        directory = FakeDirectory(on_apply=slow_apply, snapshot={"a": {"m"}, "b": set()})

        report = sync.flush(directory, task_budget=150, clock=clock)

        # a starts at 0s; b starts at 100s, inside the budget, and finishes
        # at 200s; c is never handed out.
        self.assertEqual([t.alias_name for t in directory.applied], ["a", "b"])
        self.assertEqual(queue(), [("alias", "add", "c", None)])
        self.assertEqual(report.done_count, 2)
        self.assertEqual(report.stop_reason, StopReason.BUDGET)
        self.assertEqual(report.snapshot_status, SnapshotStatus.APPLIED)
        self.assertEqual(members("a"), {"m"})
        self.assertEqual(report.snapshot_skipped, ["c"])
        self.assertEqual(report.elapsed, 200)

    def test_default_budget_is_300_seconds(self):
        writes.create_alias("a")
        writes.create_alias("b")
        clock = FakeClock()

        def slow_apply(task):
            clock.now += 300

        directory = FakeDirectory(on_apply=slow_apply, snapshot={"a": set()})

        report = sync.flush(directory, clock=clock)

        self.assertEqual([t.alias_name for t in directory.applied], ["a"])
        self.assertEqual(report.stop_reason, StopReason.BUDGET)


class FlushLockTest(TestCase):
    def test_busy_when_lock_held_by_another_connection(self):
        writes.create_alias("a")
        hold_flush_lock(other_connection(self))
        directory = FakeDirectory()

        report = sync.flush(directory)

        self.assertTrue(report.busy)
        self.assertEqual(directory.applied, [])
        self.assertEqual(directory.snapshot_calls, 0)
        self.assertEqual(report.snapshot_status, SnapshotStatus.NOT_TAKEN)
        self.assertEqual(queue(), [("alias", "add", "a", None)])

    def test_busy_flush_only_tries_the_lock(self):
        writes.create_alias("a")
        hold_flush_lock(other_connection(self))

        with self.assertNumQueries(1):  # pg_try_advisory_lock, nothing else
            report = sync.flush(FakeDirectory())

        self.assertTrue(report.busy)
        self.assertIsNone(report.oldest_task_age)  # not computed when busy

    def test_lock_released_after_normal_return(self):
        report = sync.flush(FakeDirectory())

        self.assertFalse(report.busy)
        self.assertTrue(flush_lock_is_free(other_connection(self)))

    def test_lock_released_after_exception(self):
        writes.create_alias("a")

        with self.assertRaises(RuntimeError):
            sync.flush(FakeDirectory(outcomes={"a": RuntimeError("bug")}))

        self.assertTrue(flush_lock_is_free(other_connection(self)))

    def test_original_exception_wins_when_releasing_the_lock_also_fails(self):
        writes.create_alias("a")
        release = sync._unlock
        self.addCleanup(release)  # the failed release left the lock held

        with patch.object(sync, "_unlock", side_effect=OperationalError("connection lost")):
            with self.assertRaisesRegex(RuntimeError, "bug") as raised:
                sync.flush(FakeDirectory(outcomes={"a": RuntimeError("bug")}))

        self.assertIn("connection lost", "\n".join(raised.exception.__notes__))

    def test_alias_write_lock_does_not_block_flush_lock(self):
        writes.create_alias("a")
        sync.flush(FakeDirectory(snapshot={"a": set()}))
        other = other_connection(self)
        with other.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_lock(%s, %s)", [writes.ALIAS_LOCK_NAMESPACE, sync.FLUSH_LOCK_KEY]
            )

        self.assertFalse(sync.flush(FakeDirectory(snapshot={"a": set()})).busy)


class SnapshotTest(TestCase):
    def test_snapshot_makes_members_match_directory(self):
        writes.create_alias("a")
        writes.add_member("a", "keep")
        writes.add_member("a", "gone")
        directory = FakeDirectory(snapshot={"a": {"keep", "new"}})

        report = sync.flush(directory)

        self.assertEqual(members("a"), {"keep", "new"})
        self.assertEqual(report.snapshot_status, SnapshotStatus.APPLIED)
        self.assertEqual(report.snapshot_updated, ["a"])
        self.assertEqual(report.snapshot_skipped, [])

    def test_snapshot_adds_directory_aliases_and_deletes_missing_ones(self):
        writes.create_alias("cache-only")
        writes.add_member("cache-only", "x")
        directory = FakeDirectory(snapshot={"ldap-only": {"y"}, "empty": set()})

        report = sync.flush(directory)

        self.assertEqual(
            set(Alias.objects.values_list("alias_name", flat=True)), {"ldap-only", "empty"}
        )
        self.assertEqual(members("ldap-only"), {"y"})
        self.assertEqual(members("cache-only"), set())
        self.assertEqual(report.snapshot_updated, ["cache-only", "empty", "ldap-only"])

    def test_alias_already_matching_snapshot_is_neither_updated_nor_skipped(self):
        writes.create_alias("same")
        writes.add_member("same", "x")
        writes.create_alias("changed")
        directory = FakeDirectory(snapshot={"same": {"x"}, "changed": {"y"}})

        report = sync.flush(directory)

        self.assertEqual(report.snapshot_updated, ["changed"])
        self.assertEqual(report.snapshot_skipped, [])
        self.assertEqual(members("same"), {"x"})

    def test_snapshot_keeps_display_fields(self):
        writes.create_alias("a", display_name="A", description="d")

        sync.flush(FakeDirectory(snapshot={"a": set()}))

        alias = Alias.objects.get(alias_name="a")
        self.assertEqual((alias.display_name, alias.description), ("A", "d"))

    def test_snapshot_skips_aliases_with_queued_tasks(self):
        writes.create_alias("pending")
        writes.add_member("pending", "y")
        writes.create_alias("clean")
        directory = FakeDirectory(outcomes={"pending": Outcome.RETRY}, snapshot={"clean": {"z"}})

        report = sync.flush(directory)

        self.assertEqual(report.snapshot_skipped, ["pending"])
        self.assertEqual(report.snapshot_updated, ["clean"])
        self.assertEqual(members("pending"), {"y"})
        self.assertEqual(members("clean"), {"z"})

    def test_failed_snapshot_leaves_cache_untouched(self):
        writes.create_alias("a")
        writes.add_member("a", "x")
        directory = FakeDirectory(snapshot=DirectoryUnavailable())

        report = sync.flush(directory)

        self.assertEqual(report.snapshot_status, SnapshotStatus.FAILED)
        self.assertEqual(report.stop_reason, StopReason.NONE)
        self.assertEqual(report.snapshot_updated, [])
        self.assertEqual(members("a"), {"x"})

    def test_snapshot_waits_for_the_alias_write_lock(self):
        # Another connection is in the middle of a write to "a". (Nothing on
        # this test's connection may touch "a": its transaction-level alias
        # locks last until the test ends.)
        with other_connection(self).cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_lock(%s, hashtext(%s))", [writes.ALIAS_LOCK_NAMESPACE, "a"]
            )
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '500ms'")
        self.addCleanup(lambda: connection.cursor().execute("RESET statement_timeout"))

        with self.assertRaises(OperationalError):  # gave up waiting for the lock
            sync.flush(FakeDirectory(snapshot={"a": {"m"}}))

        self.assertFalse(Alias.objects.filter(alias_name="a").exists())


class ReportTest(TestCase):
    def test_oldest_waiting_task_age(self):
        writes.create_alias("a")
        writes.create_alias("b")
        SyncTask.objects.filter(alias_name="a").update(
            created_at=timezone.now() - timedelta(days=2)
        )
        directory = FakeDirectory(outcomes={"a": Outcome.RETRY}, snapshot={})

        report = sync.flush(directory)

        self.assertAlmostEqual(
            report.oldest_task_age, timedelta(days=2).total_seconds(), delta=60
        )

    def test_oldest_waiting_task_age_is_none_when_queue_empty(self):
        writes.create_alias("a")

        report = sync.flush(FakeDirectory(snapshot={"a": set()}))

        self.assertIsNone(report.oldest_task_age)
        self.assertFalse(report.busy)
        self.assertEqual(report.stop_reason, StopReason.NONE)
        self.assertEqual(report.snapshot_status, SnapshotStatus.APPLIED)
