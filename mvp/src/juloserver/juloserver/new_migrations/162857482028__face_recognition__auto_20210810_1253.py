# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-10 05:53
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RenameField(
            model_name='indexedface',
            old_name='status',
            new_name='application_status_code',
        ),
        migrations.RemoveField(
            model_name='indexedface',
            name='external_image_id',
        ),
        migrations.AddField(
            model_name='indexedface',
            name='collection_face_id',
            field=models.TextField(default='-'),
        ),
        migrations.AddField(
            model_name='indexedface',
            name='collection_image_id',
            field=models.TextField(default='-'),
        ),
        migrations.AddField(
            model_name='indexedface',
            name='collection_image_url',
            field=models.CharField(default='/', max_length=200),
        ),
        migrations.AddField(
            model_name='indexedface',
            name='image',
            field=models.ForeignKey(db_column='julo_image_id', default=0, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Image'),
        ),
        migrations.AddField(
            model_name='indexedface',
            name='match_status',
            field=models.TextField(default='active'),
        ),
        migrations.AlterField(
            model_name='facerecommenderresult',
            name='device',
            field=models.ForeignKey(blank=True, db_column='device_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Device'),
        ),
        migrations.AlterField(
            model_name='facesearchresult',
            name='matched_face_image_id',
            field=models.ForeignKey(db_column='image_id', default=0, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Image'),
        ),
    ]
