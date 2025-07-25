# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-02-27 07:33
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst, DialerSystemConst


def add_call_list_for_copy_task_configuration(apps, schema_editor):
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG
    ).last()
    if not fs:
        return

    parameters = fs.parameters
    for bucket_name, configuration in parameters.items():
        bucket_name_lower = bucket_name.lower()
        if 'bttc' in bucket_name_lower:
            timeFrameStatus = "off"
            timeFrames = []
        elif 'grab' in bucket_name_lower:
            timeFrameStatus = "on"
            timeFrames = [
                {
                    "callList": ["mobile_phone_1", "mobile_phone_2"],
                    "callResultCondition": ["all"],
                    "repeatTimes": 4,
                },
                {
                    "callList": ["mobile_phone_1", "mobile_phone_2"],
                    "callResultCondition": ["all"],
                    "repeatTimes": 5,
                },
            ]
        elif 'dana_bucket_airudder' in bucket_name_lower:
            timeFrameStatus = "on"
            timeFrames = [
                {
                    "callList": ["mobile_phone_1", "mobile_phone_2"],
                    "callResultCondition": ["all"],
                    "repeatTimes": 4,
                },
                {
                    "callList": ["mobile_phone_1", "mobile_phone_2"],
                    "callResultCondition": ["all"],
                    "repeatTimes": 5,
                },
                {
                    "callList": ["mobile_phone_1", "mobile_phone_2"],
                    "callResultCondition": ["all"],
                    "repeatTimes": 5,
                },
                {
                    "callList": ["mobile_phone_1", "mobile_phone_2"],
                    "callResultCondition": ["all"],
                    "repeatTimes": 5,
                },
                {
                    "callList": ["mobile_phone_1", "mobile_phone_2"],
                    "callResultCondition": ["all"],
                    "repeatTimes": 5,
                },
            ]
        else:
            bucket_currents = DialerSystemConst.DIALER_T_MINUS_BUCKET_LIST + [
                DialerSystemConst.DIALER_BUCKET_0,
                DialerSystemConst.DIALER_JTURBO_T0,
            ]
            if bucket_name in bucket_currents:
                timeFrameStatus = "on"
                timeFrames = [
                    {
                        "callList": ["mobile_phone_1", "mobile_phone_2"],
                        "callResultCondition": [
                            'WPC',
                            'WPC - Regular',
                            'WPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 3,
                    },
                    {
                        "callList": ["mobile_phone_1", "mobile_phone_2"],
                        "callResultCondition": [
                            'WPC',
                            'WPC - Regular',
                            'WPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 4,
                    },
                ]
            elif 'B1' in bucket_name:
                timeFrameStatus = "on"
                timeFrames = [
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 4,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'RPC - Call Back',
                            'RPC - Left Message',
                        ],
                        "repeatTimes": 5,
                    },
                ]
            elif 'B2' in bucket_name:
                timeFrameStatus = "on"
                timeFrames = [
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 4,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                        ],
                        "callResultCondition": [
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                ]
            elif 'B3' in bucket_name:
                timeFrameStatus = "on"
                timeFrames = [
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 4,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                        ],
                        "callResultCondition": [
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                ]
            elif 'B4' in bucket_name:
                timeFrameStatus = "on"
                timeFrames = [
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 4,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                        ],
                        "callResultCondition": [
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                ]
            elif 'B5' in bucket_name:
                timeFrameStatus = "on"
                timeFrames = [
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 3,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 4,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                ]
            elif 'B6' in bucket_name:
                timeFrameStatus = "on"
                timeFrames = [
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 3,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'WPC',
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 4,
                    },
                    {
                        "callList": [
                            "mobile_phone_1",
                            "mobile_phone_2",
                            "spouse_mobile_phone",
                            "company_phone_number",
                        ],
                        "callResultCondition": [
                            'RPC - Call Back',
                            'RPC - Left Message',
                            'Busy',
                            'NULL',
                            'Ringing',
                            'Dead call',
                            'Busy tone',
                            'Short Call',
                            'Unreachable',
                            'Tidak Diangkat',
                            'Answering Machine',
                            'Abandoned by System',
                            'Abandoned by Customer',
                            'Disconnect By network',
                        ],
                        "repeatTimes": 5,
                    },
                ]
            else:
                continue
        configuration.update(
            timeFrameStatus=timeFrameStatus,
            timeFrames=timeFrames,
        )
        parameters.update({bucket_name: configuration})

    fs.parameters = parameters
    fs.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_call_list_for_copy_task_configuration, migrations.RunPython.noop),
    ]
