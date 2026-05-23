from unittest.mock import MagicMock, call, patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth import get_user_model
from ldap3.core.exceptions import LDAPException
from rest_framework.test import APIClient

from .models import Alias, AliasTaskQueue, UserTaskQueue
from .serializers import UserSubscriptionUpdateSerializer
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

    @patch.dict("os.environ", {"FLUSH_ENABLED": "0"})
    @patch("apps.subscriptions.tasks._connect")
    def test_skips_when_flush_disabled(self, mock_connect):
        from .tasks import flush_ldap_tasks
        flush_ldap_tasks()
        mock_connect.assert_not_called()

    @patch.dict("os.environ", {"FLUSH_ENABLED": "1"})
    @patch("apps.subscriptions.tasks._connect")
    @patch("apps.subscriptions.tasks.cache")
    def test_runs_when_flush_enabled(self, mock_cache, mock_connect):
        mock_cache.add.return_value = True
        mock_connect.return_value = MagicMock()
        from .tasks import flush_ldap_tasks
        flush_ldap_tasks()
        mock_connect.assert_called_once()


class AliasListApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.normal_user = self.user_model.objects.create_user(
            username="user1",
            password="pass",
            is_staff=False,
        )
        self.admin_user = self.user_model.objects.create_user(
            username="admin1",
            password="pass",
            is_staff=True,
        )

        Alias.objects.create(
            alias_name="activities",
            display_name="Activities",
            description="Dept events",
            user_id=["user1"],
        )
        Alias.objects.create(
            alias_name="workstation",
            display_name="Workstation",
            description="Lab announcements",
            user_id=[],
        )

    def test_admin_aliases_requires_admin_permission(self):
        self.client.force_authenticate(user=self.normal_user)
        resp = self.client.get("/api/v1/admin/aliases/")
        self.assertEqual(resp.status_code, 403)

    def test_admin_aliases_requires_auth(self):
        resp = self.client.get("/api/v1/admin/aliases/")
        self.assertEqual(resp.status_code, 403)

    def test_admin_aliases_returns_alias_list(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.get("/api/v1/admin/aliases/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)
        self.assertIn("alias_name", resp.data[0])
        self.assertNotIn("is_subscribed", resp.data[0])

    def test_user_subscriptions_requires_auth(self):
        resp = self.client.get("/api/v1/user/subscriptions/")
        self.assertEqual(resp.status_code, 403)

    def test_user_subscriptions_includes_is_subscribed(self):
        self.client.force_authenticate(user=self.normal_user)
        resp = self.client.get("/api/v1/user/subscriptions/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)

        activities_item = next(item for item in resp.data if item["alias_name"] == "activities")
        workstation_item = next(item for item in resp.data if item["alias_name"] == "workstation")

        self.assertTrue(activities_item["is_subscribed"])
        self.assertFalse(workstation_item["is_subscribed"])


class AdminAliasCreateApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.normal_user = self.user_model.objects.create_user(
            username="user1", password="pass", is_staff=False
        )
        self.admin_user = self.user_model.objects.create_user(
            username="admin1", password="pass", is_staff=True
        )

        Alias.objects.create(
            alias_name="existing-alias",
            display_name="Existing Alias",
            description="An alias that already exists.",
        )

    def test_create_alias_requires_admin(self):
        """Only admin users can create aliases."""
        self.client.force_authenticate(user=self.normal_user)
        payload = {
            "alias_name": "new-alias",
            "display_name": "New Alias",
            "description": "A new alias.",
        }
        resp = self.client.post("/api/v1/admin/aliases/", payload, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_create_alias_requires_auth(self):
        """Unauthenticated request should be rejected."""
        payload = {
            "alias_name": "new-alias",
            "display_name": "New Alias",
            "description": "A new alias.",
        }
        resp = self.client.post("/api/v1/admin/aliases/", payload, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_create_alias_success(self):
        """Admin can create a new alias."""
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "alias_name": "new-alias",
            "display_name": "New Alias",
            "description": "A new alias for testing.",
        }
        resp = self.client.post("/api/v1/admin/aliases/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["alias_name"], "new-alias")
        self.assertEqual(resp.data["display_name"], "New Alias")
        self.assertEqual(resp.data["description"], "A new alias for testing.")
        self.assertTrue(Alias.objects.filter(alias_name="new-alias").exists())

        # Verify that a task has been created in the queue
        self.assertTrue(
            AliasTaskQueue.objects.filter(
                alias_name="new-alias", action="add"
            ).exists()
        )

    def test_create_alias_missing_fields(self):
        """Request fails if required fields are missing."""
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "alias_name": "another-alias",
            # display_name is missing
            "description": "A new alias.",
        }
        resp = self.client.post("/api/v1/admin/aliases/", payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("display_name", resp.data)

    def test_create_alias_duplicate_name(self):
        """Request fails if alias_name already exists."""
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "alias_name": "existing-alias",
            "display_name": "Trying to create a duplicate",
            "description": "This should fail.",
        }
        resp = self.client.post("/api/v1/admin/aliases/", payload, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "CONFLICT")

    def test_create_alias_invalid_name_format(self):
        """Request fails if alias_name has invalid characters."""
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "alias_name": "Invalid Name",
            "display_name": "Invalid Alias",
            "description": "This should fail due to invalid name format.",
        }
        resp = self.client.post("/api/v1/admin/aliases/", payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("alias_name", resp.data)

    @patch("apps.subscriptions.views.AliasTaskQueue.objects.create")
    def test_create_alias_rolls_back_when_queue_insert_fails(self, mock_queue_create):
        """Alias creation and queue insert should be atomic."""
        mock_queue_create.side_effect = Exception("queue insert failed")

        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "alias_name": "atomic-alias",
            "display_name": "Atomic Alias",
            "description": "Should rollback on queue failure",
        }

        resp = self.client.post("/api/v1/admin/aliases/", payload, format="json")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data["code"], "INTERNAL_SERVER_ERROR")
        self.assertFalse(Alias.objects.filter(alias_name="atomic-alias").exists())


class AdminAliasPatchApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.admin_user = self.user_model.objects.create_user(
            username="admin1", password="pass", is_staff=True
        )

        Alias.objects.create(
            alias_name="workstation",
            display_name="Workstation",
            description="Lab announcements",
        )

    def test_patch_alias_not_found(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {"display_name": "New Name"}
        resp = self.client.patch(
            "/api/v1/admin/aliases/not-exist/",
            payload,
            format="json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data.get("code"), "NOT_FOUND")

    def test_patch_alias_success(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "display_name": "New Workstation",
            "description": "Updated announcements",
        }
        resp = self.client.patch(
            "/api/v1/admin/aliases/workstation/",
            payload,
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["display_name"], "New Workstation")
        self.assertEqual(resp.data["description"], "Updated announcements")

        alias = Alias.objects.get(alias_name="workstation")
        self.assertEqual(alias.display_name, "New Workstation")
        self.assertEqual(alias.description, "Updated announcements")

    def test_patch_alias_single_field(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {"display_name": "Workstation Lite"}
        resp = self.client.patch(
            "/api/v1/admin/aliases/workstation/",
            payload,
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["display_name"], "Workstation Lite")

        alias = Alias.objects.get(alias_name="workstation")
        self.assertEqual(alias.display_name, "Workstation Lite")
        self.assertEqual(alias.description, "Lab announcements")
        

class UserSubscriptionUpdateSerializerTest(TestCase):
    def setUp(self):
        Alias.objects.create(alias_name="activities", display_name="Activities")
        Alias.objects.create(alias_name="workstation", display_name="Workstation")

    def test_accepts_full_alias_state_map(self):
        payload = {
            "activities": True,
            "workstation": False,
        }
        serializer = UserSubscriptionUpdateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, payload)

    def test_rejects_missing_aliases(self):
        payload = {
            "activities": True,
        }
        serializer = UserSubscriptionUpdateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("Payload must include all aliases", str(serializer.errors))

    def test_rejects_non_boolean_value(self):
        payload = {
            "activities": "yes",
            "workstation": False,
        }
        serializer = UserSubscriptionUpdateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("must be a boolean", str(serializer.errors))

    def test_rejects_unknown_alias_key(self):
        payload = {
            "activities": True,
            "workstation": False,
            "not-exist-alias": True,
        }
        serializer = UserSubscriptionUpdateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("unknown aliases", str(serializer.errors))


class UserSubscriptionUpdateApiTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()

        self.user = self.user_model.objects.create_user(
            username="user-put",
            password="pass",
            is_staff=False,
        )

        Alias.objects.create(
            alias_name="activities",
            display_name="Activities",
            user_id=[],
        )
        Alias.objects.create(
            alias_name="workstation",
            display_name="Workstation",
            user_id=["user-put"],
        )

    def test_put_requires_auth(self):
        payload = {
            "activities": True,
            "workstation": False,
        }
        resp = self.client.put("/api/v1/user/subscriptions/", payload, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_put_updates_alias_cache_and_creates_user_tasks(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "activities": True,
            "workstation": False,
        }

        resp = self.client.put("/api/v1/user/subscriptions/", payload, format="json")
        self.assertEqual(resp.status_code, 202)

        tasks = UserTaskQueue.objects.all().order_by("alias_name")
        self.assertEqual(tasks.count(), 2)
        self.assertEqual(tasks[0].alias_name, "activities")
        self.assertEqual(tasks[0].action, "add")
        self.assertEqual(tasks[0].user_uid, "user-put")
        self.assertEqual(tasks[1].alias_name, "workstation")
        self.assertEqual(tasks[1].action, "remove")
        self.assertEqual(tasks[1].user_uid, "user-put")

        activities = Alias.objects.get(alias_name="activities")
        workstation = Alias.objects.get(alias_name="workstation")
        self.assertIn("user-put", activities.user_id)
        self.assertNotIn("user-put", workstation.user_id)

    def test_put_rejects_invalid_payload(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "activities": True,
        }
        resp = self.client.put("/api/v1/user/subscriptions/", payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_put_is_throttled_on_second_request(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "activities": True,
            "workstation": False,
        }

        first = self.client.put("/api/v1/user/subscriptions/", payload, format="json")
        second = self.client.put("/api/v1/user/subscriptions/", payload, format="json")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)

class ConnectAlertTest(TestCase):
    @patch("apps.subscriptions.tasks.send_alert_email")
    @patch("apps.subscriptions.tasks.Connection")
    def test_sends_alert_on_ldap_connection_failure(self, mock_conn_cls, mock_alert):
        mock_conn_cls.side_effect = LDAPException("connection refused")

        from apps.subscriptions.tasks import _connect
        with self.assertRaises(LDAPException):
            _connect()

        mock_alert.assert_called_once()
        call_kwargs = mock_alert.call_args[1]
        self.assertEqual(call_kwargs["subject"], "LDAP Connection Failure")
        self.assertIn("chilfox@csie.ntu.edu.tw", call_kwargs["recipients"])

    @patch("apps.subscriptions.tasks.send_alert_email")
    @patch("apps.subscriptions.tasks.Connection")
    def test_no_alert_on_successful_connection(self, mock_conn_cls, mock_alert):
        # 正常連線不該寄信
        from apps.subscriptions.tasks import _connect
        _connect()
        mock_alert.assert_not_called()

class AdminAliasDeleteApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.normal_user = self.user_model.objects.create_user(
            username="user1", password="pass", is_staff=False
        )
        self.admin_user = self.user_model.objects.create_user(
            username="admin1", password="pass", is_staff=True
        )

        Alias.objects.create(
            alias_name="todelete",
            display_name="To Delete",
            description="Will be deleted",
        )

    def test_delete_requires_admin(self):
        self.client.force_authenticate(user=self.normal_user)
        resp = self.client.delete("/api/v1/admin/aliases/todelete/")
        self.assertEqual(resp.status_code, 403)

    def test_delete_alias_not_found(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/not-exist/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data.get("code"), "NOT_FOUND")

    def test_delete_alias_success(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/todelete/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Alias.objects.filter(alias_name="todelete").exists())
        self.assertTrue(AliasTaskQueue.objects.filter(alias_name="todelete", action="remove").exists())

    @patch("apps.subscriptions.views.AliasTaskQueue.objects.create")
    def test_delete_alias_atomic(self, mock_queue_create):
        mock_queue_create.side_effect = Exception("queue insert failed")
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/todelete/")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data.get("code"), "INTERNAL_SERVER_ERROR")
        # Ensure rollback happened
        self.assertTrue(Alias.objects.filter(alias_name="todelete").exists())

class AdminAliasUserListApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.normal_user = self.user_model.objects.create_user(
            username="user1", password="pass", is_staff=False
        )
        self.admin_user = self.user_model.objects.create_user(
            username="admin1", password="pass", is_staff=True
        )

        Alias.objects.create(
            alias_name="toview",
            display_name="To View",
            user_id=["b12345678", "b00000000"],
        )

    def test_requires_auth(self):
        resp = self.client.get("/api/v1/admin/aliases/toview/users/")
        self.assertEqual(resp.status_code, 403)

    def test_requires_admin(self):
        self.client.force_authenticate(user=self.normal_user)
        resp = self.client.get("/api/v1/admin/aliases/toview/users/")
        self.assertEqual(resp.status_code, 403)

    def test_success_returns_user_ids(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.get("/api/v1/admin/aliases/toview/users/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, ["b12345678", "b00000000"])

    def test_alias_not_found(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.get("/api/v1/admin/aliases/not-exist/users/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data.get("code"), "NOT_FOUND")

    @patch("apps.subscriptions.views.Alias.objects.get")
    def test_internal_error(self, mock_get):
        mock_get.side_effect = Exception("DB error")
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.get("/api/v1/admin/aliases/toview/users/")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data.get("code"), "INTERNAL_SERVER_ERROR")

class AdminAliasUserAddApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.normal_user = self.user_model.objects.create_user(
            username="user1", password="pass", is_staff=False
        )
        self.admin_user = self.user_model.objects.create_user(
            username="admin1", password="pass", is_staff=True
        )

        Alias.objects.create(
            alias_name="toadd",
            display_name="To Add",
            user_id=["b12345678"],
        )

    def test_add_requires_auth(self):
        resp = self.client.post("/api/v1/admin/aliases/toadd/users/", {"uid": "b00000000"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_add_requires_admin(self):
        self.client.force_authenticate(user=self.normal_user)
        resp = self.client.post("/api/v1/admin/aliases/toadd/users/", {"uid": "b00000000"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_add_success(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post("/api/v1/admin/aliases/toadd/users/", {"uid": "b00000000"}, format="json")
        self.assertEqual(resp.status_code, 200)

        alias = Alias.objects.get(alias_name="toadd")
        self.assertIn("b00000000", alias.user_id)

        task = UserTaskQueue.objects.filter(alias_name="toadd", user_uid="b00000000", action="add").exists()
        self.assertTrue(task)

    def test_add_duplicate(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post("/api/v1/admin/aliases/toadd/users/", {"uid": "b12345678"}, format="json")
        self.assertEqual(resp.status_code, 200)

        alias = Alias.objects.get(alias_name="toadd")
        self.assertEqual(alias.user_id.count("b12345678"), 1)

        task = UserTaskQueue.objects.filter(alias_name="toadd", user_uid="b12345678", action="add").exists()
        self.assertFalse(task)  # Shouldn't create task if already exists

    def test_invalid_uid_format(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post("/api/v1/admin/aliases/toadd/users/", {"uid": "invalid"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "VALIDATION_ERROR")
        self.assertIn("uid", resp.data["details"])

    def test_missing_alias(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post("/api/v1/admin/aliases/notexist/users/", {"uid": "b00000000"}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["code"], "NOT_FOUND")

    @patch("apps.subscriptions.views.Alias.objects.select_for_update")
    def test_internal_error(self, mock_select):
        mock_select.side_effect = Exception("DB error")
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.post("/api/v1/admin/aliases/toadd/users/", {"uid": "b00000000"}, format="json")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data["code"], "INTERNAL_SERVER_ERROR")

class AdminAliasUserDeleteApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.normal_user = self.user_model.objects.create_user(
            username="user1", password="pass", is_staff=False
        )
        self.admin_user = self.user_model.objects.create_user(
            username="admin1", password="pass", is_staff=True
        )

        Alias.objects.create(
            alias_name="toremove",
            display_name="To Remove",
            user_id=["b12345678", "b98765432"],
        )

    def test_delete_requires_auth(self):
        resp = self.client.delete("/api/v1/admin/aliases/toremove/users/b12345678/")
        self.assertEqual(resp.status_code, 403)

    def test_delete_requires_admin(self):
        self.client.force_authenticate(user=self.normal_user)
        resp = self.client.delete("/api/v1/admin/aliases/toremove/users/b12345678/")
        self.assertEqual(resp.status_code, 403)

    def test_delete_success(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/toremove/users/b12345678/")
        self.assertEqual(resp.status_code, 204)

        alias = Alias.objects.get(alias_name="toremove")
        self.assertNotIn("b12345678", alias.user_id)
        self.assertIn("b98765432", alias.user_id)

        task = UserTaskQueue.objects.filter(alias_name="toremove", user_uid="b12345678", action="remove").exists()
        self.assertTrue(task)

    def test_delete_not_in_alias(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/toremove/users/b00000000/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["code"], "NOT_FOUND")

        alias = Alias.objects.get(alias_name="toremove")
        self.assertEqual(len(alias.user_id), 2)  # Remains unchanged

        task = UserTaskQueue.objects.filter(alias_name="toremove", user_uid="b00000000", action="remove").exists()
        self.assertFalse(task)  # Shouldn't create task if user wasn't subscribed

    def test_invalid_uid_format(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/toremove/users/invalid/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "VALIDATION_ERROR")

    def test_missing_alias(self):
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/notexist/users/b00000000/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["code"], "NOT_FOUND")

    @patch("apps.subscriptions.views.Alias.objects.select_for_update")
    def test_internal_error(self, mock_select):
        mock_select.side_effect = Exception("DB error")
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.delete("/api/v1/admin/aliases/toremove/users/b12345678/")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data["code"], "INTERNAL_SERVER_ERROR")