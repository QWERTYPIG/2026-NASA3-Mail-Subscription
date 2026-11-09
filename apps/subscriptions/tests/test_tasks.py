"""Tests for the scheduled Flush entry point (apps/subscriptions/tasks.py).

The LDAP Directory constructor is replaced by the shared ``FakeDirectory``,
so the real sync module and test database run a whole Flush with no LDAP.
"""

import json
import logging
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from .. import ldap_directory, sync, tasks, writes
from ..log import log_event
from ..models import SyncTask
from ..sync import Outcome
from .fakes import FakeDirectory
from .support import hold_flush_lock, other_connection

LOGGER = "mailsub-worker"


def events(captured):
    return [json.loads(record.getMessage()) for record in captured.records]


class LogEventTest(SimpleTestCase):
    def test_log_event_outputs_json(self):
        with self.assertLogs(LOGGER, level="ERROR") as captured:
            log_event(
                logging.ERROR,
                "ldap_connect_failed",
                "failed to connect to LDAP",
                ldap_uri="ldaps://ldap.example:636",
                error="timeout",
                empty=None,
            )

        [payload] = events(captured)
        self.assertEqual(payload["level"], "ERROR")
        self.assertEqual(payload["logger"], LOGGER)
        self.assertEqual(payload["event"], "ldap_connect_failed")
        self.assertEqual(payload["message"], "failed to connect to LDAP")
        self.assertEqual(payload["ldap_uri"], "ldaps://ldap.example:636")
        self.assertEqual(payload["error"], "timeout")
        self.assertNotIn("empty", payload)


    def test_fields_named_in_keep_null_are_emitted_as_null(self):
        with self.assertLogs(LOGGER, level="INFO") as captured:
            log_event(logging.INFO, "e", "m", kept=None, dropped=None, keep_null=("kept",))

        [payload] = events(captured)
        self.assertIsNone(payload["kept"])
        self.assertNotIn("dropped", payload)
        self.assertNotIn("keep_null", payload)


class ScheduledFlushTest(TestCase):
    def run_flush(self, directory, *, enabled="1", level="INFO"):
        """Run the entry point with ``directory`` as the LDAP Directory."""
        with patch.dict("os.environ", {"FLUSH_ENABLED": enabled}):
            with patch.object(tasks, "LdapDirectory", return_value=directory) as built:
                with self.assertLogs(LOGGER, level=level) as captured:
                    tasks.flush_ldap_tasks()
        return built, events(captured)

    def test_flush_disabled_builds_no_directory(self):
        directory = FakeDirectory()

        built, logged = self.run_flush(directory, enabled="0")

        built.assert_not_called()
        self.assertEqual([e["event"] for e in logged], ["flush_disabled"])
        self.assertEqual(directory.applied, [])
        self.assertEqual(directory.snapshot_calls, 0)

    def test_busy_flush_logs_busy_event(self):
        writes.create_alias("a")
        hold_flush_lock(other_connection(self))
        directory = FakeDirectory()

        _, logged = self.run_flush(directory)

        self.assertEqual([e["event"] for e in logged], ["flush_lock_busy"])
        self.assertEqual(directory.applied, [])
        self.assertEqual(directory.close_calls, 1)

    def test_normal_flush_logs_one_summary_event_with_report_fields(self):
        writes.create_alias("a")
        writes.add_member("a", "x")
        writes.create_alias("b")
        writes.add_member("b", "y")
        writes.create_alias("c")
        writes.add_member("c", "z")
        obsolete_id = SyncTask.objects.get(alias_name="c", kind="member").id
        directory = FakeDirectory(
            outcomes={"b": Outcome.RETRY, obsolete_id: Outcome.OBSOLETE},
            snapshot={"a": {"x"}, "c": set()},
        )

        _, logged = self.run_flush(directory)

        [summary] = [e for e in logged if e["event"] == "flush_summary"]
        self.assertEqual(summary["level"], "INFO")
        self.assertEqual(summary["done_count"], 3)
        self.assertEqual(summary["retry_count"], 1)
        self.assertEqual(summary["obsolete_count"], 1)
        self.assertEqual(summary["stop_reason"], "none")
        self.assertEqual(summary["snapshot_status"], "applied")
        self.assertEqual(summary["snapshot_updated"], ["c"])  # "a" already matched
        self.assertEqual(summary["snapshot_skipped"], ["b"])
        self.assertIsInstance(summary["elapsed_seconds"], float)
        self.assertGreaterEqual(summary["oldest_task_age_seconds"], 0)
        self.assertEqual(directory.close_calls, 1)

    def test_summary_has_null_oldest_task_age_when_queue_is_empty(self):
        writes.create_alias("a")

        _, logged = self.run_flush(FakeDirectory(snapshot={"a": set()}))

        [summary] = [e for e in logged if e["event"] == "flush_summary"]
        self.assertIn("oldest_task_age_seconds", summary)
        self.assertIsNone(summary["oldest_task_age_seconds"])

    def test_each_obsolete_task_logs_its_own_info_event(self):
        writes.create_alias("c")
        writes.add_member("c", "z")
        writes.add_member("c", "w")
        directory = FakeDirectory(
            outcomes={"c": Outcome.OBSOLETE}, snapshot={}
        )

        _, logged = self.run_flush(directory)

        obsolete = [e for e in logged if e["event"] == "task_obsolete"]
        self.assertEqual(
            [(e["level"], e["alias_name"], e["kind"], e["action"], e.get("user_uid")) for e in obsolete],
            [
                ("INFO", "c", "alias", "add", None),
                ("INFO", "c", "member", "add", "z"),
                ("INFO", "c", "member", "add", "w"),
            ],
        )
        self.assertTrue(all(isinstance(e["task_id"], int) for e in obsolete))

    def test_unexpected_exception_logs_unexpected_error_event(self):
        writes.create_alias("a")
        directory = FakeDirectory(outcomes={"a": RuntimeError("LDAP_CA_CERT_FILE is not set")})

        _, logged = self.run_flush(directory)

        self.assertEqual([e["event"] for e in logged], ["flush_unexpected_error"])
        self.assertEqual(logged[0]["level"], "ERROR")
        self.assertEqual(logged[0]["error"], "LDAP_CA_CERT_FILE is not set")
        self.assertTrue(logged[0]["traceback"].startswith("Traceback"))
        self.assertIn("RuntimeError: LDAP_CA_CERT_FILE is not set", logged[0]["traceback"])
        self.assertEqual(directory.close_calls, 1)
        self.assertEqual(SyncTask.objects.filter(alias_name="a").count(), 1)


class DjangoQTimeoutTest(SimpleTestCase):
    def test_kill_timeout_is_above_the_worst_case_flush(self):
        # Task budget, then the Task in progress, then the Snapshot.
        worst_flush = (
            sync.DEFAULT_TASK_BUDGET + ldap_directory.APPLY_WORST + ldap_directory.SNAPSHOT_WORST
        )
        timeout = settings.Q_CLUSTER["timeout"]

        self.assertEqual(worst_flush, 466)
        self.assertGreaterEqual(timeout - worst_flush, 10)  # room for database work
        self.assertGreater(settings.Q_CLUSTER["retry"], timeout)
