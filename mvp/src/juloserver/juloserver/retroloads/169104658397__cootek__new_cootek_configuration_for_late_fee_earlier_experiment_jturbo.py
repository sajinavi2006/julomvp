# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-03 07:09
from __future__ import unicode_literals

from django.db import migrations
from juloserver.cootek.constants import CootekProductLineCodeName, CriteriaChoices
from juloserver.cootek.models import (
    CootekRobot,
    CootekConfiguration,
)


def add_cootek_configuration_for_late_fee_earlier_experiment_jturbo(apps, schema_editor):
    robot_t0, _ = CootekRobot.objects.get_or_create(
        robot_identifier='561c912350fcd62a806ffadd9ccd5876',
        robot_name='M0_L4_ID_BA_Ang_Julo_1Cashbk_DM2',
    )
    robot_t_1, _ = CootekRobot.objects.get_or_create(
        robot_identifier='3068b587d9f5f07c549833dc68372168',
        robot_name='M0_L2_ID_BA_Gar_Julo_1Cashbk_DM2'
    )
    robot_t_2, _ = CootekRobot.objects.get_or_create(
        robot_identifier='75d0a450dd953375af880eeb3ef72df3',
        robot_name='M0_L2_ID_BA_Ang_Julo_2Cashbk_DM2',
    )
    product = CootekProductLineCodeName.JTURBO

    cootek_configs = [
        {
            'strategy_name': 'JTurbo_JULO_T0', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T0',
            'time_to_start': '08:00:00', 'time_to_query_result': '09:10:00', 'time_to_prepare': '07:50:00',
            'robot': robot_t0, 'repeat_number': 3, 'called_at': 0,
            'intention_filter': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', '--'],
            'from_previous_cootek_result': False, 'dpd_condition': 'Exactly',
            'product': product, 'time_to_end': '09:00:00',
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T0', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T0',
            'time_to_start': '10:00:00', 'time_to_query_result': '11:10:00', 'time_to_prepare': '09:50:00',
            'robot': robot_t0, 'repeat_number': 3, 'called_at': 0,
            'intention_filter': ['B', 'D', 'E', 'F', 'G', 'H', 'I'], 'from_previous_cootek_result': True,
            'dpd_condition': 'Exactly', 'product': product, 'time_to_end': '11:00:00',
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-1', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-1',
            'robot': robot_t_1, 'repeat_number': 3, 'called_at': -1,
            'intention_filter': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', '--'],
            'from_previous_cootek_result': False, 'time_to_start': '08:00:00',
            'time_to_query_result': '09:10:00', 'time_to_prepare': '07:50:00',
            'dpd_condition': 'Exactly', 'product': product, 'time_to_end': '09:00:00',
            'exclude_risky_customer': True,
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-1', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-1',
            'robot': robot_t_1, 'repeat_number': 3, 'called_at': -1,
            'intention_filter': ['B', 'D', 'F', 'G'], 'from_previous_cootek_result': True,
            'time_to_start': '10:00:00', 'time_to_query_result': '11:10:00', 'time_to_prepare': '09:50:00',
            'dpd_condition': 'Exactly',
            'product': product, 'time_to_end': '11:00:00', 'exclude_risky_customer': True,
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-1', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-1',
            'robot': robot_t_1, 'repeat_number': 3, 'called_at': -1,
            'intention_filter': ['B', 'D', 'F', 'G'], 'from_previous_cootek_result': True,
            'time_to_start': '12:00:00', 'time_to_query_result': '13:10:00',
            'time_to_prepare': '11:50:00', 'dpd_condition': 'Exactly',
            'product': product, 'time_to_end': '13:00:00', 'exclude_risky_customer': True,
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-1', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-1',
            'robot': robot_t_1, 'repeat_number': 2, 'called_at': -1,
            'intention_filter': ['E', 'H', 'I'], 'from_previous_cootek_result': True,
            'time_to_start': '14:00:00', 'time_to_query_result': '15:10:00',
            'time_to_prepare': '13:50:00', 'dpd_condition': 'Exactly',
            'product': product, 'time_to_end': '15:00:00', 'exclude_risky_customer': True,
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-2', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-2',
            'robot': robot_t_2, 'repeat_number': 3, 'called_at': -2,
            'intention_filter': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', '--'],
            'from_previous_cootek_result': False,
            'time_to_start': '08:00:00', 'time_to_query_result': '09:10:00',
            'time_to_prepare': '07:50:00', 'time_to_end': '09:00:00',
            'dpd_condition': 'Exactly', 'product': product,
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-2', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-2',
            'robot': robot_t_2, 'repeat_number': 3, 'called_at': -2,
            'intention_filter': ['B', 'D', 'F', 'G'], 'from_previous_cootek_result': True,
            'time_to_start': '10:00:00', 'time_to_query_result': '11:10:00',
            'time_to_prepare': '09:50:00', 'time_to_end': '11:00:00',
            'dpd_condition': 'Exactly',
            'product': product,
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-2', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-2',
            'robot': robot_t_2, 'repeat_number': 3, 'called_at': -2,
            'intention_filter': ['B', 'D', 'F', 'G'], 'from_previous_cootek_result': True,
            'time_to_start': '12:00:00', 'time_to_query_result': '13:10:00',
            'time_to_prepare': '11:50:00', 'dpd_condition': 'Exactly',
            'product': product, 'time_to_end': '13:00:00',
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
        {
            'strategy_name': 'JTurbo_JULO_T-2', 'task_type': 'LATE_FEE_EARLIER_JTurbo_JULO_T-2',
            'robot': robot_t_2, 'repeat_number': 2, 'called_at': -2,
            'intention_filter': ['E', 'H', 'I'], 'from_previous_cootek_result': True,
            'time_to_start': '14:00:00', 'time_to_query_result': '15:10:00',
            'time_to_prepare': '13:50:00', 'dpd_condition': 'Exactly',
            'product': product, 'time_to_end': '15:00:00',
            'criteria': CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT ,
        },
    ]

    for config in cootek_configs:
        CootekConfiguration.objects.create(
            time_to_start=config['time_to_start'],
            time_to_query_result=config['time_to_query_result'],
            time_to_prepare=config['time_to_prepare'],
            time_to_end=config['time_to_end'],
            dpd_condition=config['dpd_condition'],
            product=config['product'],
            strategy_name=config['strategy_name'],
            task_type=config['task_type'],
            called_at=config['called_at'],
            number_of_attempts=config['repeat_number'],
            tag_status=config['intention_filter'],
            from_previous_cootek_result=config['from_previous_cootek_result'],
            cootek_robot=config['robot'], exclude_autodebet=True,
            exclude_risky_customer=True if config.get('exclude_risky_customer') else False,
            criteria=config['criteria'],
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            add_cootek_configuration_for_late_fee_earlier_experiment_jturbo,
            migrations.RunPython.noop
        )
    ]
