# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-01-10 04:50
from django.db import migrations, models, connection
import django.db.models.deletion


def inquiry_id_bigint(apps, schema_editor):
    cursor = connection.cursor()
    cursor.execute("""ALTER TABLE ops.fdc_inquiry ALTER COLUMN fdc_inquiry_id TYPE bigint""")
    cursor.execute("""ALTER TABLE ops.fdc_inquiry_loan ALTER COLUMN fdc_inquiry_loan_id TYPE bigint""")
    cursor.execute("""ALTER SEQUENCE ops.fdc_inquiry_fdc_inquiry_id_seq AS bigint""")
    cursor.execute("""ALTER SEQUENCE ops.fdc_inquiry_loan_fdc_inquiry_loan_id_seq AS bigint""")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(inquiry_id_bigint),
    ]
