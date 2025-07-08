import logging

from celery import task
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.db import transaction

from juloserver.julo.models import (EmailHistory,
                                    Partner,
                                    PartnerReferral, FeatureSetting, Application)
from juloserver.julo.partners import (PartnerConstant,
                                      get_partners_for_partner_sms,
                                      )
from juloserver.julo.clients import get_julo_email_client
from juloserver.streamlined_communication.models import (StreamlinedCommunication, StreamlinedMessage, )
from juloserver.streamlined_communication.constant import (CommunicationPlatform, )
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.exceptions import (SmsNotSent, JuloException, )
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.streamlined_communication.services import (process_partner_sms_message)
from juloserver.julo.clients import get_julo_sms_client

logger = logging.getLogger(__name__)


@task(name='tokopedia_auto_reminder_30days')
def tokopedia_auto_reminder_30days():
    partner = Partner.objects.get_or_none(name=PartnerConstant.TOKOPEDIA_PARTNER)
    partner_referrals = partner.partnerreferral_set.filter(
        udate__lt=(timezone.now() - relativedelta(days=30)),
        customer__isnull=True,
        reminder_email_sent=False
    ).order_by('-udate')
    for partner_referral in partner_referrals:
        data = {'obj_id': partner_referral.id,
                'email': partner_referral.cust_email,
                'fullname': partner_referral.cust_fullname,
                'shorturl': 'https://go.onelink.me/app/FUTokopedia',
                'subject': 'Kesempatan Mendapatkan Dana Tunai 8 Juta'
                }
        send_email_partner_referral_reminder.delay(data)


@task(queue='partnership_global')
def send_email_partner_referral_reminder(data):
    with transaction.atomic():
        partner_referral = PartnerReferral.objects.select_for_update().filter(pk=data['obj_id']).first()
        if partner_referral and (partner_referral.reminder_email_sent == False):
            client = get_julo_email_client()
            status, headers, msg = client.partner_reminder_email(
                data['email'],
                data['fullname'],
                data['shorturl'],
                data['subject']
            )

            logger.info({
                'action': 'send_email_partner_referral_reminder',
                'email': data['email']
            })
            if status == 202:
                partner_referral.update_safely(reminder_email_sent=True)
                message_id = headers['X-Message-Id']
                EmailHistory.objects.create(
                    sg_message_id=message_id,
                    to_email=data['email'],
                    subject=data['subject'],
                    message_content=msg
                )

@task
def send_sms_to_specific_partner_customers(application_id):
    application_status_list = [ApplicationStatusCodes.FORM_PARTIAL,
                               ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED]
    application = Application.objects.get(id=application_id)

    if application:
        current_status = application.application_status_id
        if current_status in application_status_list and application.partner_id:
            partner_ids = get_partners_for_partner_sms()
            if application.partner_id in partner_ids:
                if not application.mobile_phone_1:
                    logger.error({
                        'status': 'Failed Mobile phone empty',
                        'action': 'send_sms_to_specific_partner_customers',
                        'application': application.id,
                    })
                    return

                streamlined_partner_sms = StreamlinedCommunication.objects.filter(
                    communication_platform=CommunicationPlatform.SMS,
                    extra_conditions__isnull=True,
                    dpd__isnull=True,
                    ptp__isnull=True,
                    partner=application.partner,
                    status_code_id=current_status).last()

                if streamlined_partner_sms:
                    processed_message = process_partner_sms_message(
                        streamlined_partner_sms.message.message_content, application)

                    julo_sms_client = get_julo_sms_client()
                    phone_number = format_e164_indo_phone_number(application.mobile_phone_1)

                    text_message, response = julo_sms_client.send_sms(phone_number, processed_message)
                    response = response['messages'][0]
                    if response['status'] == '0':
                        create_sms_history(response=response,
                                           customer=application.customer,
                                           application=application,
                                           template_code=streamlined_partner_sms.template_code,
                                           message_content=processed_message,
                                           to_mobile_phone=phone_number,
                                           phone_number_type='phone'
                                           )

                        logger.info({
                            'status': 'SMS sent',
                            'action': 'send_sms_to_specific_partner_customers',
                            'application': application,
                            'template_code': streamlined_partner_sms.template_code
                        })
                    else:
                        logger.info({
                            'status': 'SMS not sent',
                            'action': 'send_sms_to_specific_partner_customers',
                            'application': application,
                            'template_code': streamlined_partner_sms.template_code,
                            'response': response
                        })
                else:
                    logger.error({
                        'status': 'No streamline data',
                        'action': 'send_sms_to_specific_partner_customers',
                        'application': application.id,
                        'partner_id': application.partner_id
                    })
