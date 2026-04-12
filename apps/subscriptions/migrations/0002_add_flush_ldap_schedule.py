from django.db import migrations


def add_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.get_or_create(
        func="apps.subscriptions.tasks.flush_ldap_tasks",
        defaults={
            "name": "Flush LDAP Tasks",
            "schedule_type": "I",  # Minutes
            "minutes": 3,
        },
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func="apps.subscriptions.tasks.flush_ldap_tasks").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
        ("django_q", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_schedule, remove_schedule),
    ]
