# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-04-06 13:53
from __future__ import unicode_literals

from django.db import migrations


from juloserver.collection_vendor.models import SubBucket



def seed_subbucket(apps, schema_editor):
    
    data_to_seeds = [
        SubBucket(
            bucket=5,
            sub_bucket=1,
            start_dpd=91,
            end_dpd=180
        ),
        SubBucket(
            bucket=5,
            sub_bucket=2,
            start_dpd=181,
            end_dpd=270
        ),
        SubBucket(
            bucket=5,
            sub_bucket=3,
            start_dpd=271,
            end_dpd=360
        ),
        SubBucket(
            bucket=5,
            sub_bucket=4,
            start_dpd=361,
            end_dpd=720
        ),
        SubBucket(
            bucket=5,
            sub_bucket=5,
            start_dpd=721,
        ),
    ]
    SubBucket.objects.bulk_create(data_to_seeds)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(seed_subbucket, migrations.RunPython.noop),
    ]
