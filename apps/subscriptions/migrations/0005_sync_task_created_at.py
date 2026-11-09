"""Record when each sync task was enqueued.

Existing rows get the time the migration runs; the column is NOT NULL.
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0004_alias_member"),
    ]

    operations = [
        migrations.AddField(
            model_name="synctask",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
