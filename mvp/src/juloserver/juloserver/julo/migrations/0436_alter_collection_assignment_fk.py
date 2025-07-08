from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0435_collection-agent_assignment'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE collection_agent_assignment ALTER COLUMN payment_id TYPE bigint;"),
        migrations.RunSQL(
            "ALTER TABLE collection_agent_assignment ALTER COLUMN loan_id TYPE bigint;"),
    ]