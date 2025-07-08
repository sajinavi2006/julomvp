from enum import Enum


class CommChannelEnum(Enum):
    EMAIL = 'email'
    SMS = 'sms'
    PN = 'pn'
    ONE_WAY_ROBOCALL = 'one-way-robocall'
    TWO_WAY_ROBOCALL = 'two-way-robocall'
    PDS = 'pds'


COLUMN_TO_CHANNEL = {
    'is_rollout_pds': CommChannelEnum.PDS.value,
    'is_rollout_pn': CommChannelEnum.PN.value,
    'is_rollout_sms': CommChannelEnum.SMS.value,
    'is_rollout_email': CommChannelEnum.EMAIL.value,
    'is_rollout_one_way_robocall': CommChannelEnum.ONE_WAY_ROBOCALL.value,
    'is_rollout_two_way_robocall': CommChannelEnum.TWO_WAY_ROBOCALL.value,
}

BULK_PROCESS_GUIDELINE_URL = 'https://juloprojects.atlassian.net/l/cp/oKbkAe3j'
PRE_CRM_ID = 'S07QNHU283C'
PRE_CRM_FORMATTED = '<!subteam^{}>'.format(PRE_CRM_ID)
CRM_OMNI_MONITORING_CHANNEL = 'C07RA4X8F4Y'
CRM_OMNI_MONITORING_USERNAME = 'CRM - Omnichannel Monitoring'
ACTION_CHOICES = (('insert', 'Add'), ('upsert', 'Add/Replace'))
ACTION_TO_MEANING = {'insert': 'Add', 'upsert': 'Add/Replace'}
