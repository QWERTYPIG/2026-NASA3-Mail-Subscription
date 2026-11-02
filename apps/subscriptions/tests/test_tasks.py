"""Tests for apps/subscriptions/tasks.py (LDAP sync side).

Moved unchanged from tests.py. tasks.py still imports the old queue models
(AliasTaskQueue, UserTaskQueue) and Alias.user_id, so this module fails to
import until the LDAP sync is ported to the sync interface. Owned by the LDAP
sync side; see the interface plan.
"""

import json
import logging
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from ldap3.core.exceptions import LDAPException
from rest_framework.test import APIClient

from ..models import Alias, AliasTaskQueue, UserTaskQueue
from ..serializers import UserSubscriptionUpdateSerializer
from ..tasks import flush_alias_tasks, flush_user_tasks, log_event, run_consistency_check




class TaskLoggingTest(SimpleTestCase):
    def test_log_event_outputs_json(self):
        logger = logging.getLogger("mailsub-worker")

        with self.assertLogs(logger, level="ERROR") as captured:
            log_event(
                logging.ERROR,
                "ldap_connect_failed",
                "failed to connect to LDAP",
                ldap_uri="ldaps://ldap.example:636",
                error="timeout",
                empty=None,
            )

        payload = json.loads(captured.output[0].split(":", 2)[-1].strip())
        self.assertEqual(payload["level"], "ERROR")
        self.assertEqual(payload["logger"], "mailsub-worker")
        self.assertEqual(payload["event"], "ldap_connect_failed")
        self.assertEqual(payload["message"], "failed to connect to LDAP")
        self.assertEqual(payload["ldap_uri"], "ldaps://ldap.example:636")
        self.assertEqual(payload["error"], "timeout")
        self.assertNotIn("empty", payload)

    @patch.dict("os.environ", {"LDAP_CA_CERT_FILE": "test-ca.pem"})
    @patch("apps.subscriptions.tasks.Connection")
    @patch("apps.subscriptions.tasks.Server")
    @patch("apps.subscriptions.tasks.Tls")
    def test_connect_failure_logs_structured_error(
        self, mock_tls, mock_server, mock_connection
    ):
        from ..tasks import _connect

        mock_connection.side_effect = LDAPException("timeout")
        logger = logging.getLogger("mailsub-worker")

        with self.assertLogs(logger, level="ERROR") as captured:
            with self.assertRaises(LDAPException):
                _connect()

        payload = json.loads(captured.output[0].split(":", 2)[-1].strip())
        self.assertEqual(payload["event"], "ldap_connect_failed")
        self.assertEqual(payload["error"], "timeout")


class FlushAliasTasksTest(TestCase):
    def _make_conn(self):
        conn = MagicMock()
        conn.add.return_value = True
        conn.delete.return_value = True
        return conn

    def test_add_alias_calls_ldap_add(self):
        AliasTaskQueue.objects.create(alias_name="test-list", action="add")
        conn = self._make_conn()
        flush_alias_tasks(conn)
        conn.add.assert_called_once()
        # Task 應被刪除
        self.assertEqual(AliasTaskQueue.objects.count(), 0)

    def test_remove_alias_calls_ldap_delete(self):
        AliasTaskQueue.objects.create(alias_name="test-list", action="remove")
        conn = self._make_conn()
        flush_alias_tasks(conn)
        conn.delete.assert_called_once()
        self.assertEqual(AliasTaskQueue.objects.count(), 0)

    def test_remove_alias_cleans_dangling_user_tasks(self):
        AliasTaskQueue.objects.create(alias_name="test-list", action="remove")
        UserTaskQueue.objects.create(
            alias_name="test-list", user_uid="b12345", action="add"
        )
        conn = self._make_conn()
        flush_alias_tasks(conn)
        # 關聯的 user task 也要一起清掉
        self.assertEqual(UserTaskQueue.objects.count(), 0)

    def test_ldap_failure_leaves_task_in_queue(self):
        AliasTaskQueue.objects.create(alias_name="bad-alias", action="add")
        conn = self._make_conn()
        conn.add.side_effect = LDAPException("timeout")
        with patch("apps.subscriptions.tasks.time.sleep"):  # 跳過 retry sleep
            flush_alias_tasks(conn)
        # Task 應該留在 queue 等下次重試
        self.assertEqual(AliasTaskQueue.objects.count(), 1)


class ConsistencyCheckTest(TestCase):
    def test_updates_alias_user_ids_from_ldap(self):
        Alias.objects.create(alias_name="faculty", user_id=[])

        # 模擬 LDAP entry 格式
        entry = MagicMock()
        entry.cn.value = "faculty"
        entry.uniqueMember.values = [
            "uid=b12902000,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw",
            "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw",  # bind DN（placeholder）
        ]

        conn = MagicMock()
        conn.entries = [entry]

        run_consistency_check(conn)

        alias = Alias.objects.get(alias_name="faculty")
        # bind DN 應被過濾掉
        self.assertEqual(alias.user_id, ["b12902000"])


class FlushLdapTasksTest(TestCase):
    @patch("apps.subscriptions.tasks._connect")
    @patch("apps.subscriptions.tasks.cache")
    def test_skips_if_lock_not_acquired(self, mock_cache, mock_connect):
        mock_cache.add.return_value = False  # 模擬 lock 已被佔用
        from ..tasks import flush_ldap_tasks

        flush_ldap_tasks()
        mock_connect.assert_not_called()

    @patch("apps.subscriptions.tasks._connect")
    @patch("apps.subscriptions.tasks.cache")
    def test_releases_lock_on_success(self, mock_cache, mock_connect):
        mock_cache.add.return_value = True
        mock_connect.return_value = MagicMock()
        from ..tasks import flush_ldap_tasks

        flush_ldap_tasks()
        mock_cache.delete.assert_called_once()

    @patch.dict("os.environ", {"FLUSH_ENABLED": "0"})
    @patch("apps.subscriptions.tasks._connect")
    def test_skips_when_flush_disabled(self, mock_connect):
        from ..tasks import flush_ldap_tasks

        flush_ldap_tasks()
        mock_connect.assert_not_called()

    @patch.dict("os.environ", {"FLUSH_ENABLED": "1"})
    @patch("apps.subscriptions.tasks._connect")
    @patch("apps.subscriptions.tasks.cache")
    def test_runs_when_flush_enabled(self, mock_cache, mock_connect):
        mock_cache.add.return_value = True
        mock_connect.return_value = MagicMock()
        from ..tasks import flush_ldap_tasks

        flush_ldap_tasks()
        mock_connect.assert_called_once()


class ConnectLoggingTest(SimpleTestCase):
    @patch("apps.subscriptions.tasks.Connection")
    @patch("apps.subscriptions.tasks.Server")
    @patch("apps.subscriptions.tasks.Tls")
    def test_logs_on_ldap_connection_failure(
        self, mock_tls, mock_server, mock_conn_cls
    ):
        mock_conn_cls.side_effect = LDAPException("connection refused")

        from apps.subscriptions.tasks import _connect

        logger = logging.getLogger("mailsub-worker")

        with self.assertLogs(logger, level="ERROR") as captured:
            with self.assertRaises(LDAPException):
                _connect()

        payload = json.loads(captured.output[0].split(":", 2)[-1].strip())
        self.assertEqual(payload["event"], "ldap_connect_failed")
        self.assertEqual(payload["error"], "connection refused")

    @patch("apps.subscriptions.tasks.Connection")
    @patch("apps.subscriptions.tasks.Server")
    @patch("apps.subscriptions.tasks.Tls")
    def test_no_error_log_on_successful_connection(
        self, mock_tls, mock_server, mock_conn_cls
    ):
        from apps.subscriptions.tasks import _connect

        logger = logging.getLogger("mailsub-worker")

        with patch.object(logger, "log") as mock_log:
            _connect()

        error_calls = [
            call_args
            for call_args in mock_log.call_args_list
            if call_args.args and call_args.args[0] >= logging.ERROR
        ]
        self.assertEqual(error_calls, [])
