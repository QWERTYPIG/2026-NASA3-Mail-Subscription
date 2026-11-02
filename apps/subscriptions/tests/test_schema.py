"""Tests for the sync_task / alias_member schema (migrations 0003, 0004).

LDAP is never contacted: the member-add serializer's LDAP lookup is mocked.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from ..models import Alias, AliasMember, SyncTask

APP = "subscriptions"
LATEST = "0004_alias_member"


def _ldap_user(gid="400"):
    """A populate_user() result whose gidNumber passes the serializer check."""
    user = MagicMock()
    user.ldap_user.attrs = {"gidNumber": [gid]}
    return user


class SyncTaskConstraintTest(TestCase):
    def _assert_rejected(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyncTask.objects.create(**fields)

    def test_alias_task_must_not_carry_user(self):
        self._assert_rejected(kind="alias", action="add", alias_name="a", user_uid="x")

    def test_member_task_must_carry_user(self):
        self._assert_rejected(kind="member", action="add", alias_name="a")

    def test_unknown_kind_rejected(self):
        self._assert_rejected(kind="group", action="add", alias_name="a")

    def test_unknown_action_rejected(self):
        self._assert_rejected(kind="alias", action="rename", alias_name="a")

    def test_id_orders_both_kinds_in_one_sequence(self):
        created = [
            SyncTask.objects.create(kind="alias", action="remove", alias_name="a"),
            SyncTask.objects.create(kind="member", action="add", alias_name="a", user_uid="x"),
            SyncTask.objects.create(kind="alias", action="add", alias_name="a"),
            SyncTask.objects.create(kind="member", action="add", alias_name="a", user_uid="y"),
        ]
        self.assertEqual(list(SyncTask.objects.all()), created)


class AliasMemberConstraintTest(TestCase):
    def setUp(self):
        self.alias = Alias.objects.create(alias_name="faculty")

    def test_duplicate_member_rejected(self):
        AliasMember.objects.create(alias=self.alias, user_uid="b1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AliasMember.objects.create(alias=self.alias, user_uid="b1")

    def test_same_user_in_two_aliases_allowed(self):
        other = Alias.objects.create(alias_name="staff")
        AliasMember.objects.create(alias=self.alias, user_uid="b1")
        AliasMember.objects.create(alias=other, user_uid="b1")
        self.assertEqual(AliasMember.objects.filter(user_uid="b1").count(), 2)

    def test_deleting_alias_deletes_members(self):
        AliasMember.objects.create(alias=self.alias, user_uid="b1")
        self.alias.delete()
        self.assertFalse(AliasMember.objects.exists())


@patch("apps.subscriptions.serializers.LDAPBackend")
class MemberApiSchemaTest(TestCase):
    """Member endpoints against alias_member + sync_task, LDAP lookup mocked."""

    def setUp(self):
        self.client = APIClient()
        admin = get_user_model().objects.create_user(
            username="admin1", password="pass", is_staff=True
        )
        self.client.force_authenticate(user=admin)
        self.alias = Alias.objects.create(alias_name="alias-a")

    def test_add_creates_member_and_member_task(self, mock_backend):
        mock_backend.return_value.populate_user.return_value = _ldap_user()
        resp = self.client.post(
            "/api/v1/manage/aliases/alias-a/users/", {"uid": "B00000001"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            AliasMember.objects.filter(alias=self.alias, user_uid="b00000001").exists()
        )
        task = SyncTask.objects.get()
        self.assertEqual(
            (task.kind, task.action, task.alias_name, task.user_uid),
            ("member", "add", "alias-a", "b00000001"),
        )

    def test_duplicate_add_is_conflict_without_task(self, mock_backend):
        mock_backend.return_value.populate_user.return_value = _ldap_user()
        AliasMember.objects.create(alias=self.alias, user_uid="b00000001")
        resp = self.client.post(
            "/api/v1/manage/aliases/alias-a/users/", {"uid": "b00000001"}, format="json"
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(AliasMember.objects.count(), 1)
        self.assertFalse(SyncTask.objects.exists())

    def test_member_list_keeps_insertion_order(self, mock_backend):
        for uid in ["b3", "b1", "b2"]:
            AliasMember.objects.create(alias=self.alias, user_uid=uid)
        resp = self.client.get("/api/v1/manage/aliases/alias-a/users/")
        self.assertEqual(resp.data, ["b3", "b1", "b2"])

    def test_delete_create_add_sequence_is_queued_in_order(self, mock_backend):
        """The motivating scenario, as the API records it.

        delete A -> add x to A -> create A -> add y to A. "add x" is rejected
        (A does not exist), and the remaining three tasks keep their order in
        one id sequence, so the worker can no longer lose "add y".
        """
        mock_backend.return_value.populate_user.return_value = _ldap_user()
        AliasMember.objects.create(alias=self.alias, user_uid="old")

        self.assertEqual(self.client.delete("/api/v1/manage/aliases/alias-a/").status_code, 204)
        self.assertFalse(AliasMember.objects.exists())  # cascade
        resp_x = self.client.post(
            "/api/v1/manage/aliases/alias-a/users/", {"uid": "x"}, format="json"
        )
        self.assertEqual(resp_x.status_code, 404)
        resp_create = self.client.post(
            "/api/v1/manage/aliases/",
            {"alias_name": "alias-a", "display_name": "A", "description": "A"},
            format="json",
        )
        self.assertEqual(resp_create.status_code, 201)
        resp_y = self.client.post(
            "/api/v1/manage/aliases/alias-a/users/", {"uid": "y"}, format="json"
        )
        self.assertEqual(resp_y.status_code, 200)

        self.assertEqual(
            list(SyncTask.objects.values_list("kind", "action", "user_uid")),
            [("alias", "remove", None), ("alias", "add", None), ("member", "add", "y")],
        )
        self.assertEqual(
            list(AliasMember.objects.values_list("user_uid", flat=True)), ["y"]
        )


class MigrationTestBase(TransactionTestCase):
    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([(APP, target)])
        return executor.loader.project_state([(APP, target)]).apps

    def tearDown(self):
        self.migrate(LATEST)


class SyncTaskMigrationTest(MigrationTestBase):
    def test_refuses_when_old_queues_have_rows(self):
        old = self.migrate("0002_add_flush_ldap_schedule")
        old.get_model(APP, "UserTaskQueue").objects.create(
            alias_name="a", user_uid="x", action="add"
        )
        with self.assertRaisesMessage(RuntimeError, "Refusing to migrate"):
            self.migrate("0003_sync_task")
        old.get_model(APP, "UserTaskQueue").objects.all().delete()

    def test_forward_with_empty_queues(self):
        self.migrate("0002_add_flush_ldap_schedule")
        new = self.migrate("0003_sync_task")
        task = new.get_model(APP, "SyncTask").objects.create(
            kind="alias", action="add", alias_name="a"
        )
        self.assertIsNotNone(task.id)

    def test_reverse_refuses_when_sync_task_has_rows(self):
        new = self.migrate("0003_sync_task")
        new.get_model(APP, "SyncTask").objects.create(
            kind="alias", action="add", alias_name="a"
        )
        with self.assertRaisesMessage(RuntimeError, "Refusing to reverse"):
            self.migrate("0002_add_flush_ldap_schedule")


class AliasMemberMigrationTest(MigrationTestBase):
    def test_forward_copies_arrays_in_order_without_duplicates(self):
        old = self.migrate("0003_sync_task")
        OldAlias = old.get_model(APP, "Alias")
        OldAlias.objects.create(alias_name="a", user_id=["b2", "b1", "b2"])
        OldAlias.objects.create(alias_name="empty", user_id=[])

        new = self.migrate(LATEST)
        Member = new.get_model(APP, "AliasMember")
        self.assertEqual(
            list(Member.objects.filter(alias_id="a").order_by("id").values_list("user_uid", flat=True)),
            ["b2", "b1"],
        )
        self.assertFalse(Member.objects.filter(alias_id="empty").exists())

    def test_reverse_rebuilds_arrays(self):
        new = self.migrate(LATEST)
        NewAlias = new.get_model(APP, "Alias")
        Member = new.get_model(APP, "AliasMember")
        a = NewAlias.objects.create(alias_name="a")
        NewAlias.objects.create(alias_name="empty")
        for uid in ["b3", "b1"]:
            Member.objects.create(alias=a, user_uid=uid)

        old = self.migrate("0003_sync_task")
        OldAlias = old.get_model(APP, "Alias")
        self.assertEqual(OldAlias.objects.get(alias_name="a").user_id, ["b3", "b1"])
        self.assertEqual(OldAlias.objects.get(alias_name="empty").user_id, [])
