# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models

from juloserver.streamlined_communication.constant import CommunicationPlatform


class Migration(migrations.Migration):

    dependencies = [
        ('streamlined_communication', '0041_deactivate_pending_refinancing_comms'),
    ]

    operations = [
        migrations.AddField(
            model_name='StreamlinedCommunicationParameterList',
            name='platform',
            field=models.CharField(
                max_length=50,
                blank=True,
                null=True,
                choices=CommunicationPlatform.CHOICES),
        ),
        migrations.AddField(
            model_name='StreamlinedCommunicationParameterList',
            name='example',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='streamlinedcommunication',
            name='is_active',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='streamlinedcommunication',
            name='is_automated',
            field=models.BooleanField(default=True),
        ),
    ]
