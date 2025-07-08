from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='FDCCheckManualApproval',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='fdc_check_manual_approval_id', primary_key=True, serialize=False
                    ),
                ),
                ('application_id', models.BigIntegerField(blank=True, null=True)),
                (
                    'status',
                    models.CharField(
                        choices=[('approve', 'approve'), ('reject', 'reject')], max_length=25
                    ),
                ),
            ],
            options={
                'db_table': 'fdc_check_manual_approval',
                'managed': False,
            },
        ),
    ]
