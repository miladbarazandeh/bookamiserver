from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0006_highlight"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="reading_ease_level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("very_easy", "Very easy to read"),
                    ("easy", "Easy to read"),
                    ("fairly_easy", "Fairly easy to read"),
                    ("neither_easy_nor_difficult", "Neither easy nor difficult to read"),
                    ("somewhat_difficult", "Somewhat difficult to read"),
                    ("difficult", "Difficult to read"),
                    ("very_difficult", "Very difficult to read"),
                    ("extremely_difficult", "Extremely difficult to read"),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
    ]
