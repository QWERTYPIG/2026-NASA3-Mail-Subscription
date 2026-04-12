from unittest.mock import MagicMock, call, patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from ldap3.core.exceptions import LDAPException

from .models import Alias, AliasTaskQueue, UserTaskQueue
from .tasks import flush_alias_tasks, flush_user_tasks, run_consistency_check


class SubscriptionModelsTest(TestCase):
    def test_create_valid_alias(self):
        """測試建立合法的 Alias"""
        alias = Alias.objects.create(
            alias_name="valid-alias-123",
            display_name="合法群組",
            description="測試用的 alias群組",
            user_id=["b12902000", "b12902001"],
        )
        self.assertEqual(alias.alias_name, "valid-alias-123")
        self.assertEqual(alias.display_name, "合法群組")
        self.assertEqual(alias.user_id, ["b12902000", "b12902001"])

    def test_invalid_alias_name(self):
        """測試不合法的 alias_name 會觸發 ValidationError (被 RegexValidator 阻擋)"""
        alias = Alias(
            alias_name="invalid*alias!",
            display_name="不合法的 alias",
        )
        with self.assertRaises(ValidationError):
            alias.full_clean()

    def test_create_alias_task_queue(self):
        """測試新增 Alias 操作排入 Queue"""
        task = AliasTaskQueue.objects.create(alias_name="new-group", action="add")
        self.assertEqual(task.alias_name, "new-group")
        self.assertEqual(task.action, "add")

    def test_create_user_task_queue(self):
        """測試新增單一 User 操作排入 Queue (One Row, One Action)"""
        task = UserTaskQueue.objects.create(
            alias_name="existing-group", user_uid="b12902000", action="add"
        )
        self.assertEqual(task.alias_name, "existing-group")
        self.assertEqual(task.user_uid, "b12902000")
        self.assertEqual(task.action, "add")


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
        from .tasks import flush_ldap_tasks
        flush_ldap_tasks()
        mock_connect.assert_not_called()

    @patch("apps.subscriptions.tasks._connect")
    @patch("apps.subscriptions.tasks.cache")
    def test_releases_lock_on_success(self, mock_cache, mock_connect):
        mock_cache.add.return_value = True
        mock_connect.return_value = MagicMock()
        from .tasks import flush_ldap_tasks
        flush_ldap_tasks()
        mock_cache.delete.assert_called_once()