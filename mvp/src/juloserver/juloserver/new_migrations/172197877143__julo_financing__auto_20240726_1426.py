# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-26 07:26
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AlterField(
            model_name='jfinancingverification',
            name='validation_status',
            field=models.CharField(
                choices=[
                    ('on_review', 'Menunggu Konfirmasi'),
                    ('confirmed', 'Sedang Diproses'),
                    ('on_delivery', 'Pesanan Dikirim'),
                    ('completed', 'Selesai'),
                    ('canceled', 'Dibatalkan'),
                ],
                default='on_review',
                max_length=50,
            ),
        ),
    ]
