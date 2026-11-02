"""Merge alias_task_queue and user_task_queue into one ordered sync_task table.

Pending rows cannot be converted: the two old tables had independent ids, so
their relative order is unknown. The migration refuses to run unless both old
queues are empty; drain them on the ACTIVE node first (see docs/05-migration.md).
The reverse direction likewise refuses while sync_task has rows.
"""

import django.core.validators
from django.db import migrations, models


def require_old_queues_empty(apps, schema_editor):
    AliasTaskQueue = apps.get_model("subscriptions", "AliasTaskQueue")
    UserTaskQueue = apps.get_model("subscriptions", "UserTaskQueue")
    alias_count = AliasTaskQueue.objects.count()
    user_count = UserTaskQueue.objects.count()
    if alias_count or user_count:
        raise RuntimeError(
            "Refusing to migrate: alias_task_queue has "
            f"{alias_count} row(s) and user_task_queue has {user_count} row(s). "
            "Their cross-table order cannot be recovered. Drain both queues on "
            "the ACTIVE node before running this migration."
        )


def require_sync_task_empty(apps, schema_editor):
    SyncTask = apps.get_model("subscriptions", "SyncTask")
    count = SyncTask.objects.count()
    if count:
        raise RuntimeError(
            f"Refusing to reverse: sync_task has {count} row(s). Drain the queue "
            "on the ACTIVE node before rolling back."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0002_add_flush_ldap_schedule"),
    ]

    operations = [
        migrations.RunPython(require_old_queues_empty, migrations.RunPython.noop),
        migrations.CreateModel(
            name="SyncTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("alias", "Alias"), ("member", "Member")], max_length=10)),
                ("action", models.CharField(choices=[("add", "Add"), ("remove", "Remove")], max_length=10)),
                ("alias_name", models.CharField(max_length=255, validators=[django.core.validators.RegexValidator(message="Alias name can only contain letters, numbers, and hyphens.", regex="^[a-zA-Z0-9-]+$")])),
                ("user_uid", models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                "db_table": "sync_task",
                "ordering": ["id"],
                "indexes": [models.Index(fields=["alias_name", "id"], name="sync_task_alias_id_idx")],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("kind__in", ["alias", "member"])), name="sync_task_kind_valid"),
                    models.CheckConstraint(condition=models.Q(("action__in", ["add", "remove"])), name="sync_task_action_valid"),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("kind", "alias"), ("user_uid__isnull", True)),
                            models.Q(("kind", "member"), ("user_uid__isnull", False)),
                            _connector="OR",
                        ),
                        name="sync_task_user_uid_matches_kind",
                    ),
                ],
            },
        ),
        # Runs before SyncTask is dropped when migrating backwards.
        migrations.RunPython(migrations.RunPython.noop, require_sync_task_empty),
        migrations.DeleteModel(name="AliasTaskQueue"),
        migrations.DeleteModel(name="UserTaskQueue"),
    ]
