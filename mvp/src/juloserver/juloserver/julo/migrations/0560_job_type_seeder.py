# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def seeder_job_type(apps, schema_editor):
    JobType = apps.get_model("julo", "JobType")
    job_type_collections = (
        JobType(is_salaried=True, job_type='Pegawai swasta',),
        JobType(is_salaried=True, job_type='Pegawai negeri',),
        JobType(is_salaried=False, job_type='Pengusaha',),
        JobType(is_salaried=False, job_type='Freelance',),
        JobType(is_salaried=False, job_type='Staf rumah tangga',),
        JobType(is_salaried=False, job_type='Pekerja rumah tangga',),
        JobType(is_salaried=False, job_type='Ibu rumah tangga',),
        JobType(is_salaried=False, job_type='Mahasiswa',),
        JobType(is_salaried=False, job_type='Tidak bekerja',),
    )
    JobType.objects.bulk_create(job_type_collections)


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0559_add_is_salaried_to_credit_matrix'),
    ]

    operations = [
        migrations.RunPython(seeder_job_type),
    ]
