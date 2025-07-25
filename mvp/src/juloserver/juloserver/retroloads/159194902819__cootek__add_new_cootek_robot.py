# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-04-24 06:41
from __future__ import unicode_literals

from django.db import migrations


from juloserver.cootek.models import CootekRobot



def new_cootek_robot(apps, schema_editor):
    

    cootek_robots = [
        {'id': 'df3a8e170b9bf3cb64f35ad95f574cbb', 'name': 'M1_Level1_ID_Garry_Julo'},
        {'id': '172ced845f9c65237d3fd61d6f513b62', 'name': 'M1_Level2_ID_Garry_Julo'},
    ]

    for robot in cootek_robots:
        CootekRobot.objects.create(
            robot_identifier=robot['id'],
            robot_name=robot['name'])

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(new_cootek_robot, migrations.RunPython.noop)
    ]
