from builtins import range
from juloserver.pn_delivery.services import update_pn_details_from_moengage_streams
from juloserver.julo.models import Device
from juloserver.moengage.constants import PnNotificationTypes, PnNotificationStreams


def send_pn_details_from_moengage_streams(data, is_stream=False):
    if not data:
        return

    list_account_payment_id = [data['account_payment_id']]
    if data['account_payment_id']:
        flag_account_payment = True
    else:
        flag_account_payment = False
    for i in range(1, 6):
        list_account_payment_id.append(data['account{}_payment_id'.format(i)])
        if data['account{}_payment_id'.format(i)]:
            flag_account_payment = True

    for account_payment_id in list_account_payment_id:
        if not account_payment_id:
            continue
        refactored_data = set_data_format_for_pn_streams(
            data, account_payment_id, is_stream)
        update_pn_details_from_moengage_streams(refactored_data)
    if not flag_account_payment:
        refactored_data = set_data_format_for_pn_streams(
            data, None, is_stream)
        update_pn_details_from_moengage_streams(refactored_data)


def set_data_format_for_pn_streams(data, account_payment_id, is_stream=False):
    return_data = dict()
    event_source = data['event_source']
    event_code = data['event_code']
    campaign_name = data['campaign_name']
    template_code = data['template_code']
    campaign_type = data['campaign_type']
    customer_id = data['customer_id']
    extra_data = data['gcm_action_id']
    application_id = data['application_id']
    loan_status_code = data['loan_status_code']
    payment_id = data['payment_id']
    title = data['title']
    content = data['content']
    fcm_id = ''
    device = None
    campaign_id = data['campaign_id']
    moe_rsp_android = data.get('moe_rsp_android', None)
    if customer_id:
        device = Device.objects.filter(customer=customer_id).last()

    if device:
        fcm_id = device.gcm_reg_id

    pn_delivery_data = dict()
    pn_delivery_data['fcm_id'] = fcm_id
    pn_delivery_data['extra_data'] = extra_data
    pn_delivery_data['campaign_id'] = campaign_id
    pn_delivery_data['customer_id'] = customer_id
    pn_delivery_data['source'] = event_source
    pn_delivery_data['moe_rsp_android'] = moe_rsp_android
    pn_track_data = dict()
    pn_track_data['application_id'] = application_id
    pn_track_data['loan_status_code'] = loan_status_code
    pn_track_data['payment_id'] = payment_id
    pn_track_data['account_payment_id'] = account_payment_id
    pn_data = dict()
    pn_data['campaign_id'] = campaign_id
    pn_data['customer_id'] = customer_id
    pn_data['campaign_name'] = campaign_name
    pn_data['title'] = title
    pn_data['content'] = content

    if not is_stream:
        if event_code not in list(PnNotificationTypes.keys()):
            return
        status = PnNotificationTypes[event_code]
    else:
        if event_code not in list(PnNotificationStreams.keys()):
            return
        status = PnNotificationStreams[event_code]
    pn_delivery_data['status'] = status

    return_data['pn_delivery_data'] = pn_delivery_data
    return_data['pn_track_data'] = pn_track_data
    return_data['pn_data'] = pn_data
    return_data['account_payment_id'] = account_payment_id
    return_data['campaign_type'] = campaign_type
    return_data['template_code'] = template_code
    return return_data
