from builtins import range
from django.db import transaction
from juloserver.julo.models import Device
from juloserver.pn_delivery.models import PNBlast, PNDelivery, PNTracks
from juloserver.pn_delivery.models import PNBlastEvent, PNDeliveryEvent
from juloserver.moengage.constants import PnNotificationTypes, PnNotificationStreams


def update_pn_details(data, is_stream=False):
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
        update_pn(data, is_stream, account_payment_id)
    if not flag_account_payment:
        update_pn(data, is_stream)


def update_pn(data, is_stream, account_payment_id=None):
    event_source = data['event_source']
    event_code = data['event_code']
    campaign_id = data['campaign_id']
    campaign_name = data['campaign_name']
    customer_id = data['customer_id']
    extra_data = data['gcm_action_id']
    application_id = data['application_id']
    loan_status_code = data['loan_status_code']
    payment_id = data['payment_id']
    title = data['title']
    content = data['content']
    account_payment_id = data['account_payment_id'] or account_payment_id
    fcm_id = ''
    device = None

    template_code = data['template_code'] if 'template_code' in data else campaign_name
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
    pn_track_data = dict()
    pn_track_data['application_id'] = application_id
    pn_track_data['loan_status_code'] = loan_status_code
    pn_track_data['payment_id'] = payment_id
    pn_track_data['account_payment_id'] = account_payment_id
    if not is_stream:
        if event_code not in list(PnNotificationTypes.keys()):
            return
        status = PnNotificationTypes[event_code]
    else:
        if event_code not in list(PnNotificationStreams.keys()):
            return
        status = PnNotificationStreams[event_code]
    pn_delivery_data['status'] = status
    pn_blast = PNBlast.objects.filter(name=template_code).last()
    if not pn_blast:
        pn_blast = PNBlast.objects.create(
            name=template_code,
            is_active=True,
            redirect_page=1,
            status=status,
            title=title,
            content=content,
        )
        pn_blast_id = pn_blast.pn_blast_id
        PNBlastEvent.objects.create(pn_blast_id=pn_blast_id, status=status)
    else:
        pn_blast_id = pn_blast.pn_blast_id

    pn_delivery = PNDelivery.objects.filter(customer_id=customer_id, campaign_id=campaign_id)
    if data['campaign_type'] == PnNotificationTypes['SMART_TRIGGER_CAMPAIGN_TYPE']:
        pn_delivery_data['is_smart_trigger_campaign'] = True

    if pn_delivery:
        pn_delivery.update(**pn_delivery_data)
        pn_delivery_id = pn_delivery.last().pn_delivery_id
        PNDeliveryEvent.objects.filter(pn_delivery_id=pn_delivery_id).update(status=status)

        if data['campaign_type'] != PnNotificationTypes['SMART_TRIGGER_CAMPAIGN_TYPE']:
            if not account_payment_id:
                pn_track = PNTracks.objects.filter(
                    pn_id=pn_delivery_id, account_payment_id__isnull=True
                )
            else:
                pn_track = PNTracks.objects.filter(
                    pn_id=pn_delivery_id, account_payment_id=account_payment_id
                )

            if not pn_track:
                pn_track_data['pn_id'] = pn_delivery.last()
                PNTracks.objects.create(**pn_track_data)
            else:
                pn_track.update(**pn_track_data)
    else:
        pn_delivery_data['pn_blast_id'] = pn_blast_id
        pn_delivery = PNDelivery.objects.create(**pn_delivery_data)
        pn_delivery_id = pn_delivery.pn_delivery_id
        PNDeliveryEvent.objects.create(pn_delivery_id=pn_delivery_id, status=status)
        pn_track_data['pn_id'] = pn_delivery
        if data['campaign_type'] != PnNotificationTypes['SMART_TRIGGER_CAMPAIGN_TYPE']:
            PNTracks.objects.create(**pn_track_data)


def update_pn_details_from_moengage_streams(data):
    with transaction.atomic():
        pn_delivery = PNDelivery.objects.filter(
            customer_id=data['pn_data']['customer_id'], campaign_id=data['pn_data']['campaign_id']
        ).first()

        if pn_delivery:
            pn_delivery_id = pn_delivery.pn_delivery_id
            pn_delivery.status = data['pn_delivery_data']['status']
            pn_delivery.moe_rsp_android = data['pn_delivery_data'].get('moe_rsp_android', None)
            pn_delivery.save()

            PNDeliveryEvent.objects.create(
                pn_delivery_id=pn_delivery_id, status=data['pn_delivery_data']['status']
            )
        else:
            pn_blast = PNBlast.objects.filter(name=data['template_code']).last()
            if not pn_blast:
                pn_blast = PNBlast.objects.create(
                    name=data['template_code'],
                    is_active=True,
                    redirect_page=1,
                    status="complete",
                    title=data['pn_data']['title'],
                    content=data['pn_data']['content'],
                )
                pn_blast_id = pn_blast.pn_blast_id
                PNBlastEvent.objects.create(pn_blast_id=pn_blast_id, status="complete")
            else:
                pn_blast_id = pn_blast.pn_blast_id

            data['pn_delivery_data']['pn_blast_id'] = pn_blast_id
            if data['campaign_type'] == PnNotificationTypes['SMART_TRIGGER_CAMPAIGN_TYPE']:
                data['pn_delivery_data']['is_smart_trigger_campaign'] = True

            pn_delivery = PNDelivery.objects.create(**data['pn_delivery_data'])
            pn_delivery_id = pn_delivery.pn_delivery_id
            PNDeliveryEvent.objects.create(
                pn_delivery_id=pn_delivery_id, status=data['pn_delivery_data']['status']
            )
            data['pn_track_data']['pn_id'] = pn_delivery
            if data['campaign_type'] != PnNotificationTypes['SMART_TRIGGER_CAMPAIGN_TYPE']:
                PNTracks.objects.create(**data['pn_track_data'])
