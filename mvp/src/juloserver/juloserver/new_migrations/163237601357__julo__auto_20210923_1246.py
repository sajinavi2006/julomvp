# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-09-23 05:46
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='SiteMapJuloWeb',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='julo_article_id', primary_key=True, serialize=False)),
                ('label_name', models.TextField()),
                ('label_url', models.TextField()),
            ],
            options={
                'verbose_name_plural': 'Sitemap Julo Web',
                'db_table': 'sitemap_julo_web',
            },
        ),
    ]
