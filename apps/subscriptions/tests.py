from django.test import TestCase
from django.core.exceptions import ValidationError
from .models import Alias, AliasTaskQueue, UserTaskQueue

class SubscriptionModelsTest(TestCase):
    def test_create_valid_alias(self):
        """測試建立合法的 Alias"""
        alias = Alias.objects.create(
            alias_name="valid-alias-123",
            display_name="合法群組",
            description="測試用的 alias群組",
            user_id=["b12902000", "b12902001"]
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
        task = AliasTaskQueue.objects.create(
            alias_name="new-group",
            action="add"
        )
        self.assertEqual(task.alias_name, "new-group")
        self.assertEqual(task.action, "add")

    def test_create_user_task_queue(self):
        """測試新增單一 User 操作排入 Queue (One Row, One Action)"""
        task = UserTaskQueue.objects.create(
            alias_name="existing-group",
            user_uid="b12902000",
            action="add"
        )
        self.assertEqual(task.alias_name, "existing-group")
        self.assertEqual(task.user_uid, "b12902000")
        self.assertEqual(task.action, "add")