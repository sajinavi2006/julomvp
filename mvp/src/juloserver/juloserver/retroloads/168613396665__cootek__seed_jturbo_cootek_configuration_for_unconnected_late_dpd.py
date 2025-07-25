# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-07 10:32
from __future__ import unicode_literals

from django.db import migrations

from juloserver.cootek.constants import CootekProductLineCodeName
from juloserver.cootek.models import (
    CootekRobot,
    CootekConfiguration,
)


def add_cootek_configuration_for_jturbo(apps, schema_editor):
    robot_t1_4, _ = CootekRobot.objects.get_or_create(
        robot_identifier='27f9bbbe40e4b67bf2cd85e3be976e5b',
        robot_name='robot_unconnected_late_dpd_1-4_group_DM2',
        is_group_method=True,
    )
    robot_t5_10, _ = CootekRobot.objects.get_or_create(
        robot_identifier='e6293ff21426dd939edfbc16f7f0c51f',
        robot_name='robot_unconnected_late_dpd_5-10_group_DM2',
        is_group_method=True,
    )

    cootek_configs = [
        {
            'strategy_name': 'jturbo_unconnected_late_dpd_1-4_afternoon',
            'task_type': 'jturbo_unconnected_late_dpd_1-4_afternoon',
            'time_to_start': '12:00:00', 'time_to_query_result': '13:10:00',
            'time_to_prepare': '11:50:00', 'time_to_end': '13:00:00',
            'robot': robot_t1_4, 'repeat_number': 3, 'called_at': 1, 'called_to': 4,
            'from_previous_cootek_result': False,
        },
        {
            'strategy_name': 'jturbo_unconnected_late_dpd_1-4_evening',
            'task_type': 'jturbo_unconnected_late_dpd_1-4_evening',
            'time_to_start': '18:00:00', 'time_to_query_result': '19:10:00',
            'time_to_prepare': '17:50:00', 'robot': robot_t1_4, 'time_to_end': '19:00:00',
            'repeat_number': 3, 'called_at': 1, 'called_to': 4,
            'from_previous_cootek_result': False,
        },
        {
            'strategy_name': 'jturbo_unconnected_late_dpd_5-10_afternoon',
            'task_type': 'jturbo_unconnected_late_dpd_5-10_afternoon',
            'time_to_start': '12:00:00', 'time_to_query_result': '13:10:00',
            'time_to_prepare': '11:50:00', 'time_to_end': '13:00:00',
            'robot': robot_t5_10, 'repeat_number': 3, 'called_at': 5, 'called_to': 10,
            'from_previous_cootek_result': False,
        },
        {
            'strategy_name': 'jturbo_unconnected_late_dpd_5-10_evening',
            'task_type': 'jturbo_unconnected_late_dpd_5-10_evening',
            'time_to_start': '18:00:00', 'time_to_query_result': '19:10:00',
            'time_to_prepare': '17:50:00', 'robot': robot_t5_10, 'time_to_end': '19:00:00',
            'repeat_number': 3, 'called_at': 5, 'called_to': 10,
            'from_previous_cootek_result': False,
        },
    ]

    for config in cootek_configs:
        CootekConfiguration.objects.create(
            time_to_start=config['time_to_start'],
            time_to_query_result=config['time_to_query_result'],
            time_to_prepare=config['time_to_prepare'],
            time_to_end=config['time_to_end'],
            dpd_condition='Range',
            criteria='Unconnected_Late_dpd',
            product=CootekProductLineCodeName.JTURBO,
            strategy_name=config['strategy_name'],
            task_type=config['task_type'],
            called_at=config['called_at'],
            called_to=config['called_to'],
            number_of_attempts=3,
            from_previous_cootek_result=False,
            cootek_robot=config['robot'],
            is_exclude_b3_vendor=True,
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_cootek_configuration_for_jturbo, migrations.RunPython.noop)
    ]
