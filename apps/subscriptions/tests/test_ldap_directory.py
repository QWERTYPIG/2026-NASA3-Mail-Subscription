"""Tests for the LDAP Directory (apps/subscriptions/ldap_directory.py).

Seam: the ``ldap3`` Connection. ``Connection``, ``Server`` and ``Tls`` are
replaced with mocks and ``time.sleep`` is patched, so nothing reaches a real
LDAP server. Failures are real ``ldap3`` exceptions.
"""

import json
import os
import socket
import ssl
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase
from ldap3 import LEVEL, MODIFY_ADD, MODIFY_DELETE
from ldap3.core.exceptions import (
    LDAPAttributeOrValueExistsResult,
    LDAPBindError,
    LDAPBusyResult,
    LDAPEntryAlreadyExistsResult,
    LDAPInsufficientAccessRightsResult,
    LDAPInvalidDnError,
    LDAPInvalidDNSyntaxResult,
    LDAPNoSuchAttributeResult,
    LDAPNoSuchObjectResult,
    LDAPNotAllowedOnNotLeafResult,
    LDAPObjectClassViolationResult,
    LDAPResponseTimeoutError,
    LDAPSessionTerminatedByServerError,
    LDAPSizeLimitExceededResult,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPUnavailableResult,
    LDAPUnwillingToPerformResult,
)

from ..ldap_directory import LdapConfig, LdapDirectory
from ..sync import DirectoryUnavailable, Outcome, Task

MODULE = "apps.subscriptions.ldap_directory"
URI = "ldaps://ldap.test:636"
BIND_DN = "uid=mailbot,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw"
ALIASES_DN = "ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw"
PEOPLE_DN = "ou=people,dc=csie,dc=ntu,dc=edu,dc=tw"


def alias_task(action, alias_name="nasa", id=1):
    return Task(id=id, kind=Task.KIND_ALIAS, action=action, alias_name=alias_name, user_uid=None)


def member_task(action, user_uid="alice", alias_name="nasa", id=1):
    return Task(
        id=id, kind=Task.KIND_MEMBER, action=action, alias_name=alias_name, user_uid=user_uid
    )


class LdapDirectoryTestCase(SimpleTestCase):
    """Builds an LdapDirectory over a mocked ``ldap3`` Connection."""

    def setUp(self):
        self.Connection = self._patch("Connection")
        self.Server = self._patch("Server")
        self.Tls = self._patch("Tls")
        self.sleep = self._patch("time.sleep")
        self.conn = self.Connection.return_value
        self.now = 0.0  # the Directory's fake clock; waits advance it
        self.sleep.side_effect = self.advance
        self.directory = self.make_directory()

    def _patch(self, name):
        patcher = patch(f"{MODULE}.{name}")
        self.addCleanup(patcher.stop)
        return patcher.start()

    def make_directory(self, **overrides):
        config = LdapConfig(
            uri=URI, bind_dn=BIND_DN, bind_password="secret", ca_cert_file="/etc/ldap/ca.pem"
        )
        return LdapDirectory(replace(config, **overrides), clock=lambda: self.now)

    def advance(self, seconds):
        self.now += seconds

    def takes(self, seconds, then):
        """A side effect that spends ``seconds`` of fake time, then returns or raises ``then``."""

        def effect(*args, **kwargs):
            self.advance(seconds)
            if isinstance(then, BaseException):
                raise then
            return then

        return effect

    @staticmethod
    def in_turn(*effects):
        """A side effect running ``effects`` one per call."""
        remaining = iter(effects)
        return lambda *args, **kwargs: next(remaining)(*args, **kwargs)

    def log_events(self, captured):
        return [json.loads(record.getMessage()) for record in captured.records]


class ApplyRequestTest(LdapDirectoryTestCase):
    def test_create_alias_adds_entry_with_placeholder_member(self):
        self.directory.apply(alias_task("add"))

        self.conn.add.assert_called_once_with(
            f"cn=nasa,{ALIASES_DN}",
            object_class=["groupOfUniqueNames"],
            attributes={"cn": "nasa", "uniqueMember": [BIND_DN]},
        )

    def test_delete_alias_deletes_entry(self):
        self.directory.apply(alias_task("remove"))

        self.conn.delete.assert_called_once_with(f"cn=nasa,{ALIASES_DN}")

    def test_add_member_adds_unique_member_value(self):
        self.directory.apply(member_task("add"))

        self.conn.modify.assert_called_once_with(
            f"cn=nasa,{ALIASES_DN}",
            {"uniqueMember": [(MODIFY_ADD, [f"uid=alice,{PEOPLE_DN}"])]},
        )

    def test_remove_member_deletes_unique_member_value(self):
        self.directory.apply(member_task("remove"))

        self.conn.modify.assert_called_once_with(
            f"cn=nasa,{ALIASES_DN}",
            {"uniqueMember": [(MODIFY_DELETE, [f"uid=alice,{PEOPLE_DN}"])]},
        )

    def test_successful_request_is_done(self):
        for task in (alias_task("add"), alias_task("remove"), member_task("add"), member_task("remove")):
            with self.subTest(task=task):
                self.assertIs(self.directory.apply(task), Outcome.DONE)


def request_for(conn, task):
    """The mocked ``ldap3`` request method a Task is written with."""
    if task.kind == Task.KIND_MEMBER:
        return conn.modify
    return conn.add if task.action == Task.ACTION_ADD else conn.delete


class OutcomeTableTest(LdapDirectoryTestCase):
    """Every cell of the LDAP reply to Outcome table in the spec."""

    def test_already_in_wanted_state_is_done(self):
        cases = [
            (alias_task("add"), LDAPEntryAlreadyExistsResult()),
            (member_task("add"), LDAPAttributeOrValueExistsResult()),
            (member_task("remove"), LDAPNoSuchAttributeResult()),
        ]
        for task, exc in cases:
            with self.subTest(task=task):
                request_for(self.conn, task).side_effect = exc
                self.assertIs(self.directory.apply(task), Outcome.DONE)

    def test_missing_alias_entry_is_done_for_delete_alias(self):
        self.conn.delete.side_effect = LDAPNoSuchObjectResult()

        self.assertIs(self.directory.apply(alias_task("remove")), Outcome.DONE)

    def test_missing_alias_entry_is_obsolete_for_member_tasks(self):
        self.conn.modify.side_effect = LDAPNoSuchObjectResult()

        for task in (member_task("add"), member_task("remove")):
            with self.subTest(task=task):
                self.assertIs(self.directory.apply(task), Outcome.OBSOLETE)

    def test_any_other_result_error_is_retry_with_error_logged(self):
        cases = [
            (alias_task("add"), LDAPNoSuchObjectResult(description="noSuchObject")),
            (alias_task("add"), LDAPInsufficientAccessRightsResult(description="insufficientAccessRights")),
            (alias_task("remove"), LDAPNotAllowedOnNotLeafResult(description="notAllowedOnNonLeaf")),
            (member_task("add"), LDAPInvalidDNSyntaxResult(description="invalidDNSyntax")),
            (member_task("remove"), LDAPInsufficientAccessRightsResult(description="insufficientAccessRights")),
        ]
        for task, exc in cases:
            with self.subTest(task=task, exc=exc):
                request_for(self.conn, task).side_effect = exc
                with self.assertLogs("mailsub-worker", level="ERROR") as captured:
                    outcome = self.directory.apply(task)

                self.assertIs(outcome, Outcome.RETRY)
                [event] = self.log_events(captured)
                self.assertEqual(event["alias_name"], "nasa")
                self.assertEqual(event["action"], task.action)
                self.assertIn(exc.description, event["error"])
        self.sleep.assert_not_called()


class LastMemberRemovalTest(LdapDirectoryTestCase):
    """Removing the last Member falls back to keeping the Placeholder member."""

    def test_object_class_violation_adds_placeholder_and_deletes_member_in_one_modify(self):
        self.conn.modify.side_effect = [LDAPObjectClassViolationResult(), True]

        outcome = self.directory.apply(member_task("remove"))

        self.assertIs(outcome, Outcome.DONE)
        self.assertEqual(self.conn.modify.call_count, 2)
        self.assertEqual(
            self.conn.modify.call_args.args,
            (
                f"cn=nasa,{ALIASES_DN}",
                {
                    "uniqueMember": [
                        (MODIFY_ADD, [BIND_DN]),
                        (MODIFY_DELETE, [f"uid=alice,{PEOPLE_DN}"]),
                    ]
                },
            ),
        )

    def test_fallback_reply_is_classified_by_the_same_table(self):
        cases = [
            (LDAPNoSuchAttributeResult(), Outcome.DONE),
            (LDAPNoSuchObjectResult(), Outcome.OBSOLETE),
            (LDAPObjectClassViolationResult(), Outcome.RETRY),
        ]
        for reply, expected in cases:
            with self.subTest(reply=reply):
                self.conn.modify.reset_mock()
                self.conn.modify.side_effect = [LDAPObjectClassViolationResult(), reply]

                if expected is Outcome.RETRY:
                    with self.assertLogs("mailsub-worker", level="ERROR") as captured:
                        outcome = self.directory.apply(member_task("remove"))
                    [event] = self.log_events(captured)
                    self.assertEqual(event["event"], "user_task_failed")
                else:
                    outcome = self.directory.apply(member_task("remove"))

                self.assertIs(outcome, expected)
                self.assertEqual(self.conn.modify.call_count, 2)


RETRY_WAITS = [0.5, 1, 2, 4, 8]


def unavailable_failures():
    """Failures that mean LDAP itself cannot be used, once the waits run out."""
    return [
        LDAPSocketOpenError("connection refused"),
        LDAPSocketReceiveError("connection reset"),
        LDAPSessionTerminatedByServerError("session terminated"),
        LDAPResponseTimeoutError("no response"),
        socket.timeout("timed out"),
        LDAPBusyResult(description="busy"),
        LDAPUnavailableResult(description="unavailable"),
        LDAPUnwillingToPerformResult(description="unwillingToPerform"),
    ]


class RetryTest(LdapDirectoryTestCase):
    def waits(self):
        return [c.args[0] for c in self.sleep.call_args_list]

    def test_transient_failure_is_retried_after_a_wait(self):
        for failure in (LDAPSocketReceiveError("reset"), LDAPBusyResult(description="busy")):
            with self.subTest(failure=failure):
                self.sleep.reset_mock()
                self.conn.add.side_effect = [failure, True]
                with self.assertLogs("mailsub-worker", level="WARNING") as captured:
                    outcome = self.directory.apply(alias_task("add"))

                self.assertIs(outcome, Outcome.DONE)
                self.assertEqual(self.waits(), [0.5])
                [event] = self.log_events(captured)
                self.assertEqual(event["event"], "ldap_retry")
                self.assertEqual(event["delay_seconds"], 0.5)

    def test_unavailable_failure_after_all_waits_raises_directory_unavailable(self):
        for failure in unavailable_failures():
            with self.subTest(failure=failure):
                self.sleep.reset_mock()
                self.conn.modify.reset_mock()
                self.conn.modify.side_effect = failure
                with self.assertLogs("mailsub-worker", level="WARNING"):
                    with self.assertRaises(DirectoryUnavailable):
                        self.directory.apply(member_task("add"))

                self.assertEqual(self.waits(), RETRY_WAITS)
                self.assertEqual(self.conn.modify.call_count, 6)

    def test_failure_to_connect_or_bind_raises_directory_unavailable(self):
        for failure in (LDAPBindError("invalidCredentials"), LDAPSocketOpenError("refused")):
            with self.subTest(failure=failure):
                self.sleep.reset_mock()
                self.Connection.reset_mock()
                self.Connection.side_effect = failure
                with self.assertLogs("mailsub-worker", level="ERROR") as captured:
                    with self.assertRaises(DirectoryUnavailable):
                        self.directory.apply(alias_task("add"))

                self.assertEqual(self.waits(), RETRY_WAITS)
                self.assertEqual(self.Connection.call_count, 6)
                events = [e["event"] for e in self.log_events(captured)]
                self.assertIn("ldap_connect_failed", events)

    def test_connection_is_reopened_after_a_connection_failure(self):
        self.conn.add.side_effect = [LDAPSessionTerminatedByServerError("bye"), True]

        with self.assertLogs("mailsub-worker", level="WARNING"):
            self.assertIs(self.directory.apply(alias_task("add")), Outcome.DONE)

        self.assertEqual(self.Connection.call_count, 2)

    def test_other_non_result_error_after_all_waits_is_retry_with_error_logged(self):
        self.conn.delete.side_effect = LDAPInvalidDnError("bad dn")

        with self.assertLogs("mailsub-worker", level="WARNING") as captured:
            outcome = self.directory.apply(alias_task("remove"))

        self.assertIs(outcome, Outcome.RETRY)
        self.assertEqual(self.waits(), RETRY_WAITS)
        final = self.log_events(captured)[-1]
        self.assertEqual(final["event"], "alias_task_failed")
        self.assertIn("bad dn", final["error"])


class ApplyDeadlineTest(LdapDirectoryTestCase):
    """apply stops retrying 16 s after it started, so one Task is bounded."""

    def test_slow_failures_stop_retrying_at_the_deadline(self):
        # Each attempt times out after 10 s: attempts start at 0 s and 10.5 s;
        # a third would start after the 16 s deadline.
        self.conn.modify.side_effect = self.takes(10, LDAPSocketReceiveError("timed out"))

        with self.assertLogs("mailsub-worker", level="WARNING"):
            with self.assertRaises(DirectoryUnavailable):
                self.directory.apply(member_task("add"))

        self.assertEqual(self.conn.modify.call_count, 2)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [0.5])
        self.assertEqual(self.now, 20.5)

    def test_slow_other_error_at_the_deadline_is_retry(self):
        self.conn.delete.side_effect = self.takes(10, LDAPInvalidDnError("bad dn"))

        with self.assertLogs("mailsub-worker", level="WARNING") as captured:
            outcome = self.directory.apply(alias_task("remove"))

        self.assertIs(outcome, Outcome.RETRY)
        self.assertEqual(self.conn.delete.call_count, 2)
        self.assertEqual(self.log_events(captured)[-1]["event"], "alias_task_failed")

    def test_each_apply_gets_its_own_deadline(self):
        self.now = 1000.0
        self.conn.modify.side_effect = LDAPSocketReceiveError("reset")

        with self.assertLogs("mailsub-worker", level="WARNING"):
            with self.assertRaises(DirectoryUnavailable):
                self.directory.apply(member_task("add"))

        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], RETRY_WAITS)

    def test_worst_case_apply_takes_65_5_seconds(self):
        # Five fast connection failures use up all waits (15.5 s). The sixth
        # attempt starts just inside the deadline and takes as long as an
        # attempt can: connect 10 s, TLS handshake 10 s, bind 10 s, the
        # remove 10 s and the last-Member fallback modify 10 s.
        self.Connection.side_effect = self.in_turn(
            *[self.takes(0, LDAPSocketOpenError("refused"))] * 5,
            self.takes(30, self.conn),
        )
        self.conn.modify.side_effect = self.in_turn(
            self.takes(10, LDAPObjectClassViolationResult()),
            self.takes(10, LDAPInsufficientAccessRightsResult()),
        )

        with self.assertLogs("mailsub-worker", level="WARNING"):
            outcome = self.directory.apply(member_task("remove"))

        self.assertIs(outcome, Outcome.RETRY)
        self.assertEqual(self.now, 65.5)


PAGED_RESULTS_OID = "1.2.840.113556.1.4.319"


def entry(alias_name, *member_dns):
    attributes = {"cn": [alias_name], "uniqueMember": list(member_dns)}
    return {"type": "searchResEntry", "dn": f"cn={alias_name},{ALIASES_DN}", "attributes": attributes}


def page(entries, cookie=b"", result=0, description="success"):
    """One search reply: its entries and its result, with the paged cookie."""
    return (
        entries,
        {
            "result": result,
            "description": description,
            "controls": {PAGED_RESULTS_OID: {"value": {"size": 0, "cookie": cookie}}},
        },
    )


class SnapshotTestCase(LdapDirectoryTestCase):
    def durations(self, *seconds):
        """An ``on_search`` hook: each search spends the next of ``seconds``."""
        remaining = iter(seconds)
        return lambda: self.advance(next(remaining))

    def serve_pages(self, *pages, on_search=None):
        """Make ``conn.search`` return ``pages`` in turn via response/result."""
        replies = iter(pages)

        def search(*args, **kwargs):
            if on_search is not None:
                on_search()
            reply = next(replies)
            if isinstance(reply, BaseException):
                raise reply
            self.conn.response, self.conn.result = reply
            return reply[1]["result"] == 0

        self.conn.search.side_effect = search


class SnapshotPagingTest(SnapshotTestCase):
    def test_reads_every_page_until_the_server_reports_no_more(self):
        self.serve_pages(
            page([entry("nasa", f"uid=alice,{PEOPLE_DN}")], cookie=b"p2"),
            page([entry("ntu", f"uid=bob,{PEOPLE_DN}")], cookie=b"p3"),
            page([entry("csie", f"uid=carol,{PEOPLE_DN}", f"uid=dave,{PEOPLE_DN}")]),
        )

        snapshot = self.directory.snapshot()

        self.assertEqual(
            dict(snapshot), {"nasa": {"alice"}, "ntu": {"bob"}, "csie": {"carol", "dave"}}
        )
        self.assertEqual(self.conn.search.call_count, 3)
        first = self.conn.search.call_args_list[0]
        self.assertEqual(first.args, (ALIASES_DN, "(objectClass=groupOfUniqueNames)"))
        self.assertEqual(first.kwargs["search_scope"], LEVEL)
        self.assertEqual(set(first.kwargs["attributes"]), {"cn", "uniqueMember"})
        self.assertGreater(first.kwargs["paged_size"], 0)
        cookies = [c.kwargs.get("paged_cookie") for c in self.conn.search.call_args_list]
        self.assertEqual(cookies, [None, b"p2", b"p3"])

    def test_alias_without_members_maps_to_empty_set(self):
        self.serve_pages(page([entry("placeholder-only", BIND_DN), entry("bare")]))

        self.assertEqual(
            dict(self.directory.snapshot()), {"placeholder-only": set(), "bare": set()}
        )

    def test_entry_without_cn_is_skipped_with_a_warning(self):
        dn = f"cn=odd,{ALIASES_DN}"
        for attributes in ({"uniqueMember": [f"uid=bob,{PEOPLE_DN}"]}, {"cn": []}, {"cn": [""]}):
            with self.subTest(attributes=attributes):
                nameless = {"type": "searchResEntry", "dn": dn, "attributes": attributes}
                self.serve_pages(page([nameless, entry("nasa")]))

                with self.assertLogs("mailsub-worker", level="WARNING") as captured:
                    snapshot = self.directory.snapshot()

                self.assertEqual(dict(snapshot), {"nasa": set()})
                [event] = self.log_events(captured)
                self.assertEqual(event["level"], "WARNING")
                self.assertEqual(event["event"], "alias_entry_skipped")
                self.assertEqual(event["dn"], dn)

    def test_snapshot_retries_transient_failures(self):
        self.serve_pages(LDAPSocketReceiveError("reset"), page([entry("nasa")]))

        with self.assertLogs("mailsub-worker", level="WARNING"):
            self.assertEqual(dict(self.directory.snapshot()), {"nasa": set()})

        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [0.5])


class SnapshotFailureTest(SnapshotTestCase):
    def test_budget_exceeded_before_a_page_raises_directory_unavailable(self):
        def advance():
            self.now += 31

        self.serve_pages(
            page([entry("a")], cookie=b"p2"),
            page([entry("b")], cookie=b"p3"),
            page([entry("c")]),
            on_search=advance,
        )

        with self.assertLogs("mailsub-worker", level="WARNING"):
            with self.assertRaises(DirectoryUnavailable):
                self.directory.snapshot()

        self.assertEqual(self.conn.search.call_count, 2)

    def test_page_retries_stop_once_the_snapshot_deadline_passes(self):
        # Page 1 ends at 55 s. Page 2 fails after 4 s (59 s), is retried at
        # 59.5 s, fails again at 63.5 s, and the 60 s deadline has passed.
        self.serve_pages(
            page([entry("a")], cookie=b"p2"),
            *[LDAPSocketReceiveError("reset")] * 6,
            on_search=self.durations(55, 4, 4, 4, 4, 4, 4),
        )

        with self.assertLogs("mailsub-worker", level="WARNING"):
            with self.assertRaises(DirectoryUnavailable):
                self.directory.snapshot()

        self.assertEqual(self.conn.search.call_count, 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [0.5])

    def test_worst_case_snapshot_takes_99_9_seconds(self):
        # Page 1 ends at 59.4 s; page 2 fails at once and its retry starts at
        # 59.9 s on a new connection: connect, TLS handshake, bind (30 s),
        # then the search (10 s).
        self.serve_pages(
            page([entry("a")], cookie=b"p2"),
            LDAPSocketReceiveError("reset"),
            page([entry("b")]),
            on_search=self.durations(59.4, 0, 10),
        )
        self.Connection.side_effect = self.in_turn(
            self.takes(0, self.conn), self.takes(30, self.conn)
        )

        with self.assertLogs("mailsub-worker", level="WARNING"):
            snapshot = self.directory.snapshot()

        self.assertEqual(dict(snapshot), {"a": set(), "b": set()})
        self.assertAlmostEqual(self.now, 99.9)

    def test_non_success_search_result_raises_directory_unavailable(self):
        self.serve_pages(
            page([entry("a")], cookie=b"p2"),
            page([entry("b")], result=4, description="sizeLimitExceeded"),
        )

        with self.assertLogs("mailsub-worker", level="WARNING"):
            with self.assertRaises(DirectoryUnavailable):
                self.directory.snapshot()

    def test_any_search_error_raises_directory_unavailable(self):
        failures = [
            LDAPSizeLimitExceededResult(description="sizeLimitExceeded"),
            LDAPInsufficientAccessRightsResult(description="insufficientAccessRights"),
            LDAPInvalidDnError("bad dn"),
            *unavailable_failures(),
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                self.conn.search.side_effect = failure
                with self.assertLogs("mailsub-worker", level="WARNING"):
                    with self.assertRaises(DirectoryUnavailable):
                        self.directory.snapshot()

    def test_failure_on_a_later_page_returns_no_partial_snapshot(self):
        self.serve_pages(
            page([entry("a")], cookie=b"p2"),
            *[LDAPSocketReceiveError("reset")] * 6,
        )

        with self.assertLogs("mailsub-worker", level="WARNING"):
            with self.assertRaises(DirectoryUnavailable):
                self.directory.snapshot()


class SnapshotMemberDnTest(SnapshotTestCase):
    def snapshot_of(self, *member_dns):
        self.serve_pages(page([entry("nasa", *member_dns)]))
        return self.directory.snapshot()["nasa"]

    def test_exact_people_dn_maps_to_uid(self):
        self.assertEqual(self.snapshot_of(f"uid=alice,{PEOPLE_DN}"), {"alice"})

    def test_people_dn_is_compared_case_insensitively(self):
        self.assertEqual(
            self.snapshot_of("UID=Alice,OU=People,DC=csie,DC=ntu,DC=edu,DC=tw"), {"alice"}
        )

    def test_placeholder_member_is_dropped_silently(self):
        with self.assertNoLogs("mailsub-worker"):
            members = self.snapshot_of(BIND_DN.upper(), f"uid=alice,{PEOPLE_DN}")

        self.assertEqual(members, {"alice"})

    def test_other_dn_is_skipped_with_a_warning_naming_alias_and_dn(self):
        foreign = "uid=mallory,ou=guests,dc=csie,dc=ntu,dc=edu,dc=tw"
        cases = [
            foreign,
            "uid=alice,ou=people,dc=example,dc=org",
            f"cn=alice,{PEOPLE_DN}",
            f"uid=alice+cn=x,{PEOPLE_DN}",
            f"uid=,{PEOPLE_DN}",
        ]
        for dn in cases:
            with self.subTest(dn=dn):
                with self.assertLogs("mailsub-worker", level="WARNING") as captured:
                    members = self.snapshot_of(dn, f"uid=bob,{PEOPLE_DN}")

                self.assertEqual(members, {"bob"})
                [event] = self.log_events(captured)
                self.assertEqual(event["alias_name"], "nasa")
                self.assertEqual(event["member_dn"], dn)


class ConnectionTest(LdapDirectoryTestCase):
    def test_building_the_directory_opens_no_connection(self):
        self.Connection.assert_not_called()
        self.Server.assert_not_called()

    def test_first_request_connects_with_timeouts_and_later_requests_reuse_it(self):
        self.directory.apply(alias_task("add"))
        self.directory.apply(member_task("add"))

        self.Tls.assert_called_once_with(ca_certs_file="/etc/ldap/ca.pem", validate=ssl.CERT_REQUIRED)
        self.Server.assert_called_once_with(
            URI, use_ssl=True, tls=self.Tls.return_value, connect_timeout=10
        )
        self.Connection.assert_called_once_with(
            self.Server.return_value,
            user=BIND_DN,
            password="secret",
            auto_bind=True,
            raise_exceptions=True,
            receive_timeout=10,
        )

    def test_close_disconnects(self):
        self.directory.apply(alias_task("add"))

        self.directory.close()

        self.conn.unbind.assert_called_once_with()

    def test_close_without_a_request_opens_nothing(self):
        self.directory.close()

        self.Connection.assert_not_called()

    def test_refuses_to_connect_without_ca_certificate(self):
        directory = self.make_directory(ca_cert_file="")

        with self.assertRaisesRegex(RuntimeError, "LDAP_CA_CERT_FILE"):
            directory.apply(alias_task("add"))

        self.Connection.assert_not_called()
        self.Server.assert_not_called()

    def test_built_from_environment_configuration(self):
        env = {
            "LDAP_URI": "ldaps://env.test:636",
            "LDAP_BIND_DN": "uid=envbot,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw",
            "LDAP_BIND_PASSWORD": "env-secret",
            "LDAP_CA_CERT_FILE": "/env/ca.pem",
        }
        with patch.dict(os.environ, env):
            directory = LdapDirectory()

        directory.apply(alias_task("add"))

        self.Tls.assert_called_once_with(ca_certs_file="/env/ca.pem", validate=ssl.CERT_REQUIRED)
        self.assertEqual(self.Server.call_args.args, ("ldaps://env.test:636",))
        self.assertEqual(self.Connection.call_args.kwargs["user"], env["LDAP_BIND_DN"])
        self.assertEqual(self.Connection.call_args.kwargs["password"], "env-secret")
        self.assertEqual(
            self.conn.add.call_args.kwargs["attributes"]["uniqueMember"], [env["LDAP_BIND_DN"]]
        )
