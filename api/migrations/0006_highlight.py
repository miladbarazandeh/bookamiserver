import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_bookshelf_is_primary_bookshelf_parent"),
    ]

    operations = [
        migrations.CreateModel(
            name="Highlight",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("start_xpath", models.TextField()),
                ("start_offset", models.IntegerField()),
                ("end_xpath", models.TextField()),
                ("end_offset", models.IntegerField()),
                ("selected_text", models.TextField()),
                ("note", models.TextField(blank=True, null=True)),
                ("color", models.CharField(max_length=50)),
                ("scroll_percent", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="highlights",
                        to="api.book",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="highlights",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "highlights",
            },
        ),
    ]
