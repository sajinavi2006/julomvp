from typing import Dict

from juloserver.moengage.exceptions import MoengageCallbackError


def parse_stream_data(data: Dict, comms_type: str) -> Dict:
    """
    Parses MoEngageStream single data to be processed by other functions.

    Args:
        data (Dict): A dictionary of data sent by MoEngage.
        comms_type (str): To identify data belongs to what comms.

    Returns:
        (Dict): Final processed data.
    """
    parse = dict()
    user_attributes = data['user_attributes']
    event_attributes = data['event_attributes']

    parse['event_code'] = data['event_code']
    parse['event_source'] = data['event_source']

    if 'uid' not in data or not data['uid']:
        return {}

    parse['customer_id'] = None

    if 'anon' not in data['uid']:
        parse['customer_id'] = data['uid']

    if comms_type == 'EMAIL':
        # When it is bounced event. MoEngageStream provides reason in their response that we record.
        if parse['event_code'] in ('MOE_EMAIL_HARD_BOUNCE', 'MOE_EMAIL_SOFT_BOUNCE'):
            parse['reason'] = event_attributes.get('reason')

        parse['to_email'] = data['email_id']

        email_user_attributes = ['application_id', 'payment_id',
                                 'account_payment_id', 'account1_payment_id',
                                 'account2_payment_id', 'account3_payment_id',
                                 'account4_payment_id', 'account5_payment_id']
        email_event_attributes = ['campaign_name', 'campaign_id', 'email_subject']

        for attr in email_user_attributes:
            if attr not in list(user_attributes.keys()):
                user_attributes[attr] = None
            if user_attributes[attr]:
                parse[attr] = user_attributes[attr]
            else:
                parse[attr] = None

        for attr in list(email_event_attributes):
            if attr not in list(event_attributes.keys()):
                event_attributes[attr] = None
            if attr == 'campaign_name':
                parse['template_code'] = event_attributes[attr]
            else:
                parse[attr] = event_attributes[attr]

    elif comms_type == 'PN':
        pn_user_attributes = ['application_id', 'payment_id',
                              'loan_status_code', 'account_payment_id', 'account1_payment_id',
                              'account2_payment_id', 'account3_payment_id',
                              'account4_payment_id', 'account5_payment_id']
        pn_event_attributes = ['campaign_id', 'campaign_name', 'title', 'content',
                               'gcm_action_id', 'campaign_type']
        for attr in list(pn_user_attributes):
            if attr not in list(user_attributes.keys()):
                user_attributes[attr] = None
            if attr == 'application_id':
                if not user_attributes[attr]:
                    user_attributes[attr] = None
            parse[attr] = user_attributes[attr]
        for attr in list(pn_event_attributes):
            if attr not in list(event_attributes.keys()):
                event_attributes[attr] = None
                if attr in ('title', 'content'):
                    event_attributes[attr] = ''
            parse[attr] = event_attributes[attr]
            if attr == 'campaign_name':
                parse['template_code'] = event_attributes[attr]
        parse['moe_rsp_android'] = user_attributes.get('moe_rsp_android', None)

    elif comms_type == 'INAPP':
        inapp_user_attributes = ['application_id']
        inapp_event_attributes = ['campaign_id', 'campaign_name']
        for attr in list(inapp_user_attributes):
            if attr not in list(user_attributes.keys()):
                user_attributes[attr] = None
            parse[attr] = user_attributes[attr]
        for attr in list(inapp_event_attributes):
            if attr not in list(event_attributes.keys()):
                event_attributes[attr] = None
            if attr == 'campaign_name':
                parse['template_code'] = event_attributes[attr]
            else:
                parse[attr] = event_attributes[attr]

    elif comms_type == 'SMS':
        if 'mobile_number' in list(data.keys()):
            parse['to_mobile_phone'] = data['mobile_number']
        else:
            parse['to_mobile_phone'] = None
        sms_user_attributes = ['application_id', 'payment_id',
                               'account_payment_id', 'account1_payment_id',
                               'account2_payment_id', 'account3_payment_id',
                               'account4_payment_id', 'account5_payment_id']
        sms_event_attributes = ['campaign_id', 'campaign_name']
        for attr in list(sms_user_attributes):
            if attr not in list(user_attributes.keys()):
                user_attributes[attr] = None
            parse[attr] = user_attributes[attr]
        for attr in list(sms_event_attributes):
            if attr not in list(event_attributes.keys()):
                event_attributes[attr] = None
            if attr == 'campaign_name':
                parse['template_code'] = event_attributes[attr]
            else:
                parse[attr] = event_attributes[attr]

    # remove post fix data in template_code
    if 'template_code' in parse:
        template_code = parse['template_code']
        if '@' in template_code:
            partition_code_list = template_code.partition("@")
            parse['template_code'] = partition_code_list[0].strip()

    return parse
