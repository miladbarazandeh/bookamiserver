from django.core.management.base import BaseCommand
from django.db import connection


SQL = """
UPDATE books
SET reading_ease_level = CASE (regexp_match(reading_ease, '\\)\\. (.+).$'))[1]
    WHEN 'Very easy to read'                    THEN 'very_easy'
    WHEN 'Easy to read'                         THEN 'easy'
    WHEN 'Fairly easy to read'                  THEN 'fairly_easy'
    WHEN 'Neither easy nor difficult to read'   THEN 'neither_easy_nor_difficult'
    WHEN 'Somewhat difficult to read'           THEN 'somewhat_difficult'
    WHEN 'Difficult to read'                    THEN 'difficult'
    WHEN 'Very difficult to read'               THEN 'very_difficult'
    WHEN 'Extremely difficult to read'          THEN 'extremely_difficult'
    ELSE ''
END
WHERE reading_ease <> '';
"""


class Command(BaseCommand):
    help = "Backfill reading_ease_level from the reading_ease text field"

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(SQL)
            self.stdout.write(
                self.style.SUCCESS(f"Updated {cursor.rowcount} books")
            )
