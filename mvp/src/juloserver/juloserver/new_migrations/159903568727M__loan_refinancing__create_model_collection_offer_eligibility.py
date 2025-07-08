from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE collection_offer_eligibility ALTER COLUMN loan_id TYPE bigint;"
        ),
        migrations.RunSQL(
            "ALTER TABLE collection_offer_eligibility ALTER COLUMN application_id TYPE bigint;"
        )
    ]
