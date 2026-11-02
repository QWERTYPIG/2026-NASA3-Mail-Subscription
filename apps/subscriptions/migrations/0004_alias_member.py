"""Move alias.user_id (varchar[]) into the 3NF alias_member table.

Forward copies each array element into one row, keeping array order as id
order and dropping duplicates. Reverse rebuilds the arrays in id order.
"""

import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations, models


def copy_arrays_to_members(apps, schema_editor):
    Alias = apps.get_model("subscriptions", "Alias")
    AliasMember = apps.get_model("subscriptions", "AliasMember")
    rows = []
    for alias in Alias.objects.order_by("alias_name"):
        seen = set()
        for uid in alias.user_id or []:
            if uid in seen:
                continue
            seen.add(uid)
            rows.append(AliasMember(alias_id=alias.alias_name, user_uid=uid))
    AliasMember.objects.bulk_create(rows, batch_size=1000)


def copy_members_to_arrays(apps, schema_editor):
    Alias = apps.get_model("subscriptions", "Alias")
    AliasMember = apps.get_model("subscriptions", "AliasMember")
    members: dict[str, list[str]] = {}
    for alias_id, uid in AliasMember.objects.order_by("id").values_list("alias_id", "user_uid"):
        members.setdefault(alias_id, []).append(uid)
    for alias in Alias.objects.all():
        alias.user_id = members.get(alias.alias_name, [])
        alias.save(update_fields=["user_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0003_sync_task"),
    ]

    operations = [
        migrations.CreateModel(
            name="AliasMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_uid", models.CharField(max_length=255)),
                ("alias", models.ForeignKey(db_column="alias_name", on_delete=django.db.models.deletion.CASCADE, related_name="members", to="subscriptions.alias")),
            ],
            options={
                "db_table": "alias_member",
                "ordering": ["id"],
                "indexes": [models.Index(fields=["user_uid"], name="alias_member_user_uid_idx")],
                "constraints": [models.UniqueConstraint(fields=("alias", "user_uid"), name="alias_member_unique_alias_user")],
            },
        ),
        migrations.RunPython(copy_arrays_to_members, copy_members_to_arrays),
        migrations.RemoveField(
            model_name="alias",
            name="user_id",
        ),
    ]
