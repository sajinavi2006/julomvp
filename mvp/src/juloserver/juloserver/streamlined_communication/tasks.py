"""tasks.py"""
import logging
import math
from typing import List

import numpy as np
import pandas as pd

from celery import task
from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from babel.numbers import format_currency
from django.utils import timezone
from datetime import timedelta, datetime

from requests import RequestException

from juloserver.account.constants import AccountConstant
from juloserver.account.models import ExperimentGroup, Account
from juloserver.account_payment.models import AccountPayment, OldestUnpaidAccountPayment
from juloserver.email_delivery.constants import EmailBounceType
from juloserver.julo.clients import (
    get_julo_email_client,
    get_nsq_producer,
)
from juloserver.julo.constants import ExperimentConst, WorkflowConst, FeatureNameConst
from juloserver.julocore.utils import get_minimum_model_id
from juloserver.minisquad.constants import ExperimentConst as MinisSquadExperimentConst
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.sms import create_sms_history
from juloserver.minisquad.services2.growthbook import get_experiment_group_data_on_growthbook, \
    get_experiment_setting_data_on_growthbook
from juloserver.monitors.notifications import send_slack_bot_message
from juloserver.minisquad.utils import validate_activate_experiment
from juloserver.omnichannel.services.construct import construct_collection_sms_remove_experiment
from juloserver.omnichannel.services.settings import get_omnichannel_integration_setting
from juloserver.streamlined_communication.constant import (
    CardProperty,
    CommunicationPlatform,
    NsqTopic,
    RedisKey,
    SmsMapping,
    StreamlinedCommCampaignConstants,
    TemplateCode,
)
from juloserver.streamlined_communication.models import (
    StreamlinedCommunication,
    CommsCampaignSmsHistory,
    StreamlinedCommunicationCampaign,
)
from juloserver.streamlined_communication.services import (
    get_push_notification_service,
    render_kaliedoscope_image_as_bytes,
    render_kaliedoscope22_image_as_bytes, process_sms_message_j1,
)
from juloserver.julo.utils import (
    format_valid_e164_indo_phone_number,
    upload_file_as_bytes_to_oss,
    get_oss_public_url,
)
from juloserver.julo.models import (
    Application,
    EmailHistory,
    ExperimentSetting,
    Customer,
    FeatureSetting,
    SmsHistory,
)
from juloserver.streamlined_communication.utils import format_name
from juloserver.julo.clients import get_julo_sms_client
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.omnichannel.tasks import send_omnichannel_customer_attributes

logger = logging.getLogger(__name__)


@task(queue='loan_low')
def upload_kaleidoscope_images_to_oss_bucket(data):
    try:
        customer_id = data.get('customer_id')
        if customer_id:
            image_bytes = render_kaliedoscope_image_as_bytes(data)
            remote_filepath = 'kaleidoscope/{}/{}.png'.format(str(settings.ENVIRONMENT) , str(customer_id))
            upload_file_as_bytes_to_oss(
                'julocampaign',
                image_bytes,
                remote_filepath)
    except Exception as e:
        logger.error({
            'method': 'upload_kaleidoscope_images_to_oss_bucket',
            'data': data,
            'exception': str(e)})

@task(queue='loan_low')
def kaliedoscope_generate_and_upload_to_oss(row_data):
    try:
        customer_id = row_data.get('customer_id')
        fullname = row_data.get('fullname')
        first_name = row_data.get('first_name')
        if not customer_id or not fullname:
            logger.warning({
                'method': 'kaliedoscope_generate_and_upload_to_oss',
                'row_data': row_data,
                'reason': 'customer_id or fullname is not found'})
            return
        if len(fullname) < 23 or not first_name:
            name = fullname
        else:
            name = first_name
        repayment_rate =  row_data.get('repayment_rate')
        on_time_image = False
        if repayment_rate.lower() == 'si tepat waktu':
            on_time_image = True
        data = {
            'customer_id': customer_id,
            'on_time_image': on_time_image,
            'name_with_title': format_name(name),
            'referral_code': row_data.get('referral_code'),
            'total_amount_paid': format_currency(
                row_data.get('total_amount_paid'), 'Rp', locale='id_ID').replace('Rp', 'Rp '),
            'most_used_transaction_method': row_data.get('feature_andalan'),
            'customer_referred_count': row_data.get('count_new_customer_referred')}
        upload_kaleidoscope_images_to_oss_bucket(data)
    except Exception as e:
        logger.error({
            'method': 'kaliedoscope_blast_emails',
            'exception': str(e),
            'row_data': row_data})


@task(queue='loan_low')
def blast_emails_for_kaliedoscope_customers(row_data, envrionment=None):
    template_name = 'email_kaleidoscope_2021'
    try:
        customer_id = row_data.get('customer_id')
        to_email = row_data.get('email')
        if not customer_id or not to_email:
            logger.warning({
                'method': 'blast_emails_for_kaliedoscope_customers',
                'row_data': row_data,
                'reason': 'customer_id or email is not found'})
            return
        if not envrionment:
            envrionment = str(settings.ENVIRONMENT)
        remote_filepath = 'kaleidoscope/{}/{}.png'.format(envrionment ,str(customer_id))
        image_path = get_oss_public_url('julocampaign', remote_filepath)
        if not image_path:
            logger.warning({
                'method': 'blast_emails_for_kaliedoscope_customers',
                'row_data': row_data,
                'remote_filepath': remote_filepath,
                'reason': 'image url is not found from OSS for given remote path'})
            return
        message = render_to_string(template_name + '.html', {'image_url': image_path})
        email_client = get_julo_email_client()
        subject = 'Ini dia prestasi ter-sakti kamu dari JULO. Intip, yuk!'
        status, body, headers = email_client.send_email(
            subject=subject,
            content=message,
            email_to=to_email,
            email_from=settings.EMAIL_FROM,
            name_from='JULO',
            reply_to=settings.EMAIL_FROM,
            content_type="text/html")
        message_id = headers['X-Message-Id']
        if status == 202:
            EmailHistory.objects.create(
                customer_id=customer_id,
                sg_message_id=message_id,
                to_email=row_data.get('email'),
                subject=subject,
                message_content=message,
                template_code=template_name)
        else:
            logger.warning({
                'method': 'blast_emails_for_kaliedoscope_customers',
                'email_status': status,
                'row_data': row_data,
                'reason': 'Email message not sent'})
    except Exception as e:
        logger.error({
            'method': 'blast_emails_for_kaliedoscope_customers',
            'exception': str(e),
            'row_data': row_data})

@task(queue='partnership_global')
def send_sms_for_webapp_dropoff_customers_x100(application_id, retry=False):
    try:
        application = Application.objects.get_or_none(id=application_id)
        if not application:
            raise Exception(('Application with application_id = {} is not found').format(str(application_id)))
        if not application.web_version or not application.partner or \
                not application.product_line_code == ProductLineCodes.J1:
            return
        if application and application.status in [ApplicationStatusCodes.FORM_CREATED]:
            sms_client = get_julo_sms_client()
            sms_client.sms_webapp_customers_dropoff(application, template_code='j1_webapp_sms_x100_dropoff')
            if retry:
                day_later = timezone.localtime(timezone.now()) + timedelta(hours=24)
                send_sms_for_webapp_dropoff_customers_x100.apply_async((application_id,), eta=day_later)
    except Exception as e:
        logger.error({
            'method': 'send_sms_for_webapp_dropoff_customers_x100',
            'exception': str(e),
            'application_id': application_id,
            'retry': retry})


@task(queue="collection_low")
def record_customer_excellent_experiment(robocall_type):
    today_date = timezone.localtime(timezone.now()).date()
    excellent_customer_experiment = ExperimentSetting.objects.filter(
        is_active=True, code=ExperimentConst.EXCELLENT_CUSTOMER_EXPERIMENT
    ).filter(
        (Q(start_date__date__lte=today_date) & Q(end_date__date__gte=today_date))
        | Q(is_permanent=True)
    ).last()
    if not excellent_customer_experiment:
        return

    experiment_groups = {
        'experiment': RedisKey.EXCELLENT_CUSTOMER_ACCOUNT_IDS_TEST_GROUP.format(robocall_type),
        'control': RedisKey.EXCELLENT_CUSTOMER_ACCOUNT_IDS_CONTROL_GROUP.format(robocall_type)
    }
    redis_client = get_redis_client()
    account_experiment_data = []
    for experiment_group, redis_key in experiment_groups.items():
        cached_test_group_account_ids = redis_client.get_list(redis_key)
        if not cached_test_group_account_ids:
            continue
        experiment_excellent_account_ids = list(map(int, cached_test_group_account_ids))
        # remove duplicate account id if exist
        experiment_excellent_account_ids = list(dict.fromkeys(experiment_excellent_account_ids))

        for account_id in experiment_excellent_account_ids:
            account_experiment_data.append(ExperimentGroup(
                account_id=account_id,
                experiment_setting=excellent_customer_experiment,
                group=experiment_group
            ))
        redis_client.delete_key(redis_key)

    ExperimentGroup.objects.bulk_create(account_experiment_data)


@task(queue='low')
def upload_kaleidoscope22_images_to_oss_bucket(data):
    customer_id = data.get('customer_id')
    if customer_id:
        image_bytes = render_kaliedoscope22_image_as_bytes(data)
        remote_filepath = 'kaleidoscope22/{}/{}.png'.format(str(settings.ENVIRONMENT) , str(customer_id))
        upload_file_as_bytes_to_oss(
            'julocampaign',
            image_bytes,
            remote_filepath)


@task(queue='low')
def kaliedoscope22_generate_and_upload_to_oss(row_data):
    customer_id = row_data.get('customer_id')
    fullname = row_data.get('fullname')
    first_name = row_data.get('first_name')
    if not customer_id or not fullname:
        logger.warning({
            'method': 'kaliedoscope22_generate_and_upload_to_oss',
            'row_data': row_data,
            'reason': 'customer_id or fullname is not found'})
        return
    name = first_name
    repayment_rate =  row_data.get('repayment_rate')
    on_time_image = False
    if repayment_rate.lower() == 'si tepat waktu':
        on_time_image = True
    feature_andalan = row_data.get('feature_andalan')
    data = {
        'customer_id': customer_id,
        'on_time_image': on_time_image,
        'name_with_title': format_name(name),
        'referral_code': row_data.get('referral_code'),
        'total_amount_paid': format_currency(
            row_data.get('total_amount_paid'), 'Rp', locale='id_ID').replace('Rp', 'Rp '),
        'most_used_transaction_method': feature_andalan.lower() if feature_andalan else '',
        'customer_referred_count': row_data.get('count_new_customer_referred')}
    upload_kaleidoscope22_images_to_oss_bucket(data)


@task(queue='low')
def blast_emails_for_kaliedoscope22_customers(row_data, environment=None):
    template_name = 'email_kaleidoscope_2022'
    customer_id = row_data.get('customer_id')
    to_email = row_data.get('email')
    if not customer_id or not to_email:
        logger.warning({
            'method': 'blast_emails_for_kaliedoscope22_customers',
            'row_data': row_data,
            'reason': 'customer_id or email is not found'})
        return
    if not environment:
        environment = str(settings.ENVIRONMENT)
    remote_filepath = 'kaleidoscope22/{}/{}.png'.format(environment ,str(customer_id))
    image_path = get_oss_public_url('julocampaign', remote_filepath)
    if not image_path:
        logger.warning({
            'method': 'blast_emails_for_kaliedoscope22_customers',
            'row_data': row_data,
            'remote_filepath': remote_filepath,
            'reason': 'image url is not found from OSS for given remote path'})
        return
    context = {
        'image_url': image_path,
        'facebook': settings.SPHP_STATIC_FILE_PATH + 'facebook.png',
        'instagram': settings.SPHP_STATIC_FILE_PATH + 'instagram.png',
        'linkedin': settings.SPHP_STATIC_FILE_PATH + 'linkedin.png',
        'youtube': settings.SPHP_STATIC_FILE_PATH + 'youtube.png',
        'mail': settings.SPHP_STATIC_FILE_PATH + 'mail2.png',
        'customer_service': settings.SPHP_STATIC_FILE_PATH + 'cs2.png',
    }
    message = render_to_string(template_name + '.html', context=context)
    email_client = get_julo_email_client()
    subject = 'Ini dia prestasi ter-sakti kamu dari JULO. Intip, yuk!'
    status, body, headers = email_client.send_email(
        subject=subject,
        content=message,
        email_to=to_email,
        email_from='cs@julo.co.id',
        name_from='JULO',
        reply_to='cs@julo.co.id',
        content_type="text/html")
    message_id = headers['X-Message-Id']
    EmailHistory.objects.create(
            customer_id=customer_id,
            sg_message_id=message_id,
            to_email=row_data.get('email'),
            subject=subject,
            message_content=message,
            template_code=template_name)
    if status != 202:
        logger.warning({
            'method': 'blast_emails_for_kaliedoscope22_customers',
            'email_status': status,
            'row_data': row_data,
            'reason': 'Email message not sent'})


@task(queue='normal')
def send_pn_fraud_ato_device_change(customer_id):
    streamlined_communication = (
        StreamlinedCommunication.objects.filter(
            status_code_id=LoanStatusCodes.INACTIVE,
            template_code=TemplateCode.FRAUD_ATO_DEVICE_CHANGE_BLOCK,
            communication_platform=CommunicationPlatform.PN,
            is_active=True,
            is_automated=True,
        ).last()
    )

    if not streamlined_communication:
        return

    pn_service = get_push_notification_service()
    pn_service.send_pn(streamlined_communication, customer_id)


@task(queue='collection_high')
def sms_after_robocall_experiment_trigger(account_payment_id: int):
    from juloserver.julo.tasks import send_automated_comm_sms_j1_subtask
    fn_name = 'sms_after_robocall_experiment_trigger'
    redis_client = get_redis_client()
    # since this tasks triggered by different API this block code is for prevent double send
    lock_key = "sms_after_robocall_lock:{}".format(account_payment_id)
    now = datetime.now()
    midnight = datetime.combine(now.date(), datetime.max.time())
    time_remaining = midnight - now
    eod_redis_duration = int(time_remaining.total_seconds())
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=eod_redis_duration)

    if not lock_acquired:
        # Lock couldn't be acquired, meaning another instance is already processing for the
        # same account_payment_id
        logger.info({
            'fn_name': fn_name,
            'identifier': account_payment_id,
            'msg': 'Task already in progress for this account_payment_id'
        })
        return

    if not get_experiment_setting_data_on_growthbook(MinisSquadExperimentConst.SMS_AFTER_ROBOCALL):
        logger.info({
            'fn_name': fn_name,
            'identifier': account_payment_id,
            'msg': 'growthbook experiment not active'
        })
        return

    account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
    if not account_payment:
        logger.info({
            'fn_name': fn_name,
            'identifier': account_payment_id,
            'msg': 'AccountPayment not exists'
        })
        return

    account = account_payment.account
    if not account.is_julo_one_account():
        logger.info({
            'fn_name': fn_name,
            'identifier': account_payment_id,
            'msg': 'Account is not julo one'
        })
        return

    experiment = get_experiment_group_data_on_growthbook(
        MinisSquadExperimentConst.SMS_AFTER_ROBOCALL, account.id)
    if not experiment or experiment.group not in {'experiment_group_1', 'experiment_group_2'}:
        logger.info({
            'fn_name': fn_name,
            'identifier': account_payment_id,
            'msg': 'control group'
        })
        return

    streamlined_communication = StreamlinedCommunication.objects.filter(
        dpd=account_payment.dpd, communication_platform=CommunicationPlatform.SMS, is_active=True,
        extra_conditions=CardProperty.SMS_AFTER_ROBOCALL_EXPERIMENT).last()
    if not streamlined_communication:
        logger.info({
            'fn_name': fn_name,
            'identifier': account_payment_id,
            'msg': 'streamlined not activate'
        })
        return

    processed_message = process_sms_message_j1(
        streamlined_communication.message.message_content, account_payment,
        is_have_account_payment=True
    )
    send_automated_comm_sms_j1_subtask.delay(
        account_payment_id, processed_message, streamlined_communication.template_code,
        streamlined_communication.type
    )


@task(queue='platform_campaign_sms_send')
def send_sms_campaign_async(phone_number, msg, template_code, csv_item_id, column_header, campaign):
    julo_sms_client = get_julo_sms_client()
    try:
        message, response = julo_sms_client.send_sms(phone_number, msg)
        if response is None:
            logger.exception(
                {
                    "message": "Response is None",
                    "sms_client_method_name": "send_sms_campaign_async",
                }
            )
            return
        response['messages'][0]['is_comms_campaign_sms'] = True
        response = response['messages'][0]

        if response["status"] != "0":
            logger.exception(
                {
                    "message": "Failed to send SMS",
                    "send_status": response["status"],
                    "message_id": response.get("message-id"),
                    "sms_client_method_name": "send_sms_campaign_async",
                    "error_text": response.get("error-text"),
                }
            )

        application = None
        customer = None
        account = None
        if column_header == 'account_id':
            account = Account.objects.get_or_none(id=csv_item_id)
        elif column_header == 'application_id':
            application = Application.objects.get_or_none(id=csv_item_id)
        elif column_header == 'customer_id':
            customer = Customer.objects.get_or_none(id=csv_item_id)

        campaign_sms_history_obj = create_sms_history(
            response=response,
            message_content=msg,
            to_mobile_phone=phone_number,
            phone_number_type="mobile_phone_1",
            template_code=template_code,
            application=application,
            account=account,
            customer=customer,
        )
        if campaign_sms_history_obj:
            with transaction.atomic():
                history_obj = CommsCampaignSmsHistory.objects.select_for_update().get(
                    pk=campaign_sms_history_obj.id
                )
                campaign_obj = StreamlinedCommunicationCampaign.objects.select_for_update().get(
                    pk=campaign.id
                )
                history_obj.campaign = campaign_obj
                history_obj.save()

        if not campaign_sms_history_obj:
            logger.exception(
                {
                    "message": "Failed to create SMS history",
                    "send_status": response["status"],
                    "message_id": response.get("message-id"),
                    "sms_client_method_name": "send_sms_campaign_async",
                    "error_text": response.get("error-text"),
                }
            )

        logger.exception(
            {
                "message": "SMS sent successfully",
                "send_status": response["status"],
                "message_id": campaign_sms_history_obj.message_id,
                "sms_client_method_name": "send_sms_campaign_async",
                "sms_history_id": campaign_sms_history_obj.id,
            }
        )
    except Exception as e:
        logger.exception(
            {
                "error": str(e),
                "sms_client_method_name": "send_sms_campaign_async",
            }
        )


@task(queue='platform_campaign_sms_send')
def handle_failed_campaign_and_notify_slack(campaign):
    """
    Marks a campaign as failed if there are no associated SMS history records
    and sends a notification to Slack.

    Args:
        campaign (StreamlinedCommunicationCampaign): The campaign instance to check.

    """
    comms_campaign_sms_history_obj = CommsCampaignSmsHistory.objects.filter(campaign=campaign)
    if comms_campaign_sms_history_obj.count() == 0:
        StreamlinedCommunicationCampaign.objects.filter(pk=campaign.id).update(
            status=StreamlinedCommCampaignConstants.CampaignStatus.FAILED
        )
        slack_message = "*SMS Campaign Dashboard:* - *Process {} (campaign_id - {})".format(
            str(StreamlinedCommCampaignConstants.CampaignStatus.FAILED), str(campaign.id)
        )
        send_slack_bot_message('alerts-comms-campaign-prod-sms', slack_message)


@task(queue='platform_campaign_sms_send')
def set_campaign_status_partial_or_done(campaign):
    """
    Updates the status of a campaign to either DONE or PARTIAL_SENT
    based on the comparison of user segment count and SMS history records.

    Args:
        campaign (StreamlinedCommunicationCampaign): The campaign instance to update.
    """
    segment_count = campaign.user_segment.segment_count
    comms_campaign_sms_history_obj = CommsCampaignSmsHistory.objects.filter(campaign=campaign)
    if comms_campaign_sms_history_obj.count() > 0:
        if segment_count == comms_campaign_sms_history_obj.count():
            StreamlinedCommunicationCampaign.objects.filter(pk=campaign.id).update(
                status=StreamlinedCommCampaignConstants.CampaignStatus.SENT
            )
        else:
            StreamlinedCommunicationCampaign.objects.filter(pk=campaign.id).update(
                status=StreamlinedCommCampaignConstants.CampaignStatus.PARTIAL_SENT
            )


@task(queue='collection_high')
@validate_activate_experiment(MinisSquadExperimentConst.SMS_REMINDER_OMNICHANNEL_EXPERIMENT)
def send_sms_reminder_user_attribute_to_omnichannel(*args, **kwargs):
    fn_name = 'send_sms_reminder_user_attribute_to_omnichannel'
    logger.info(
        {
            'action': fn_name,
            'message': 'start',
        }
    )
    '''
        Because we need data from oldest unpaid account payment and latest update data is 14PM
        we need to trigger the update before we run this experiment
    '''
    from juloserver.moengage.tasks import get_and_store_oldest_unpaid_account_payment

    get_and_store_oldest_unpaid_account_payment()
    remove_sms_experiment = kwargs['experiment']
    criteria = remove_sms_experiment.criteria
    omnichannel_sending_threshold = criteria.get('omnichannel_sending_threshold', 50000)
    for experiment_key, experiment_criteria in criteria.get('experiment_group').items():
        customer_tail_ids = experiment_criteria.get('customer_id_tail')
        sent_to_omnichannel_dpd = experiment_criteria.get('dpd_list')
        subtask_send_sms_reminder_user_attribute_to_omnichannel.delay(
            experiment_key,
            customer_tail_ids,
            sent_to_omnichannel_dpd,
            remove_sms_experiment.id,
            sending_threshold=omnichannel_sending_threshold,
        )
        logger.info(
            {
                'action': fn_name,
                'message': 'send {} to async'.format(experiment_key),
            }
        )

    logger.info(
        {
            'action': fn_name,
            'message': 'finish',
        }
    )


@task(queue='collection_high')
def subtask_send_sms_reminder_user_attribute_to_omnichannel(
    segment, customer_id_tail_eligible, dpd_list, experiment_setting_id, sending_threshold=50000
):
    fn_name = 'subtask_send_sms_reminder_user_attribute_to_omnichannel_{}'.format(segment)
    logger.info(
        {
            'action': fn_name,
            'message': 'start',
        }
    )
    eligible_due_date = [
        timezone.localtime(timezone.now()).date() - timedelta(days=dpd) for dpd in dpd_list
    ]
    account_payment_query_filter = {
        'account__customer__can_notify': True,
        'account__application__product_line__product_line_code__in': ProductLineCodes.julo_one(),
        'account__account_lookup__workflow__name': WorkflowConst.JULO_ONE,
        'due_date__in': eligible_due_date,
    }
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM, is_active=True
    ).last()
    today = timezone.localtime(timezone.now())
    date_of_day = today.date()
    exclude_partner_end = dict()
    if feature_setting:
        partner_blacklist_config = feature_setting.parameters
        partner_config_end = []
        for partner_id in list(partner_blacklist_config.keys()):
            if partner_blacklist_config[partner_id] != 'end':
                continue
            partner_config_end.append(partner_id)
            partner_blacklist_config.pop(partner_id)
        if partner_config_end:
            exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)
    exclude_experiment_query = """NOT EXISTS ( SELECT "experiment_group"."experiment_group_id"
                                FROM "experiment_group"
                                WHERE "experiment_group"."account_id" = "account"."account_id"
                                AND "experiment_group"."experiment_setting_id" = %s)"""
    logger.info(
        {
            'action': fn_name,
            'message': 'querying',
        }
    )
    minimum_oldest_unpaid_account_payment_id = get_minimum_model_id(
        OldestUnpaidAccountPayment, date_of_day, 500000
    )
    # Get the start of the day (midnight)
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    # Get the end of the day (just before midnight)
    end_of_day = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    account_payments = (
        AccountPayment.objects.not_paid_active()
        .filter(**account_payment_query_filter)
        .exclude(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS,
        )
        .extra(
            where=[
                """EXISTS ( SELECT 1 FROM "oldest_unpaid_account_payment" U0
                WHERE U0."oldest_unpaid_account_payment_id" >= %s
                AND (U0."cdate" BETWEEN %s AND %s)
                AND U0."dpd" in %s
                AND U0."account_payment_id" = "account_payment"."account_payment_id")"""
            ],
            params=[
                minimum_oldest_unpaid_account_payment_id,
                start_of_day,
                end_of_day,
                tuple(dpd_list),
            ],
        )
        .extra(
            where=[
                """NOT EXISTS ( SELECT 1 FROM "ptp" U0
                WHERE U0."ptp_date" >= %s
                AND U0."account_payment_id" = "account_payment"."account_payment_id")"""
            ],
            params=[date_of_day],
        )
        .extra(where=[exclude_experiment_query], params=[experiment_setting_id])
        .extra(
            where=["RIGHT(account.customer_id::text, 2) IN %s"],
            params=[tuple(customer_id_tail_eligible)],
        )
        .exclude(**exclude_partner_end)
        .values_list('account_id', 'account__customer_id')
    )
    # bathing data creation prevent full memory
    batch_size = 500
    counter = 0
    processed_data_count = 0
    formated_experiment_group = []
    customer_ids_sent_to_omni = []
    for data in account_payments:
        formated_experiment_group.append(
            ExperimentGroup(
                experiment_setting_id=experiment_setting_id,
                account_id=data[0],
                customer_id=data[1],
                group=segment,
            )
        )
        customer_ids_sent_to_omni.append(data[1])

        counter += 1
        # Check if the batch size is reached, then perform the bulk_create
        if counter >= batch_size:
            logger.info(
                {
                    'action': fn_name,
                    'state': 'bulk_create',
                    'counter': counter,
                }
            )
            ExperimentGroup.objects.bulk_create(formated_experiment_group)
            processed_data_count += counter
            # Reset the counter and the list for the next batch
            counter = 0
            formated_experiment_group = []

    logger.info(
        {
            'action': fn_name,
            'message': 'queried',
        }
    )
    if formated_experiment_group:
        processed_data_count += counter
        ExperimentGroup.objects.bulk_create(formated_experiment_group)

    # Send to Omni channel
    if not customer_ids_sent_to_omni:
        logger.info(
            {
                'action': fn_name,
                'message': 'finish but data not exists for omnichannel',
            }
        )
        return

    # split data for processing into several part
    total_data = len(customer_ids_sent_to_omni)
    split_into = math.ceil(total_data / sending_threshold)
    customer_ids = np.array_split(customer_ids_sent_to_omni, split_into)
    index_page_number = 1
    for customer_ids_per_part in customer_ids:
        customer_ids_per_part = list(customer_ids_per_part)
        send_sms_remove_experiment_omnichannel_customer_attribute.delay(
            customer_ids_per_part, segment
        )
        index_page_number += 1

    logger.info(
        {
            'action': fn_name,
            'message': 'finish',
        }
    )
    return


@task(bind=True, queue="omnichannel", max_retry=5)
def send_sms_remove_experiment_omnichannel_customer_attribute(
    self, customer_ids: List[int], segment
):
    """
    Send customer data to Omnichannel by leveraging the Credgenics data.
    """
    fn_name = 'send_sms_remove_experiment_omnichannel_customer_attribute'
    logger.info(
        {
            'action': fn_name,
            'message': 'start',
        }
    )
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    # Construct Credgenics data
    omnichannel_customers = construct_collection_sms_remove_experiment(customer_ids, segment)

    logger.info(
        {
            'action': fn_name,
            'message': 'sending',
        }
    )
    # Send Customer Attribute
    send_omnichannel_customer_attributes(omnichannel_customers, self)
    logger.info(
        {
            'action': fn_name,
            'message': 'finish',
        }
    )


@task(queue='comms')
def evaluate_sms_reachability(phone_number: str, vendor_name: str, customer_id: int):
    """
    Calculates the reachability status of SMS based on phone's SMS records.

    Args:
        phone_number (string): The phone number to be evaluated.
        vendor_name (string): The name of vendor to determine correct status comparison.
            Expected values: `"alicloud", "infobip", "monty", "nexmo"`.
        customer_id (int): The id of the customer that currently evaluated
    """
    ## TODO: Temporarily disable this task until the issue with SMS reachability is resolved.
    return
    if not phone_number.startswith('+62'):
        phone_number = format_valid_e164_indo_phone_number(phone_number)

    today = timezone.localtime(timezone.now())
    start_of_tracking = today - relativedelta(months=6)
    start_of_tracking = start_of_tracking.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    minimum_sms_history_id = get_minimum_model_id(SmsHistory, start_of_tracking, 6750000)

    recent_count = 3
    recent_records = (
        SmsHistory.objects.filter(
            to_mobile_phone=phone_number,
            pk__gte=minimum_sms_history_id,
            cdate__range=(start_of_tracking, end_of_day),
        )
        .exclude(status=SmsMapping.DEFAULT)
        .order_by('-cdate')[:recent_count]
    )

    if not recent_records.exists():
        return

    nsq_producer = get_nsq_producer()
    # Reachability is marked as False if:
    # - SMS have not been delivered three times consecutively.
    if len(recent_records) == recent_count and all(
        record.status != SmsMapping.STATUS[vendor_name]['DELIVERED'] for record in recent_records
    ):
        nsq_message = {'phone': phone_number, 'status': False, 'customer_id': customer_id}
        nsq_producer.publish_message(NsqTopic().sms_reachability_status, nsq_message)
        logger.info(
            {
                'action': 'evaluate_sms_reachability',
                'message': 'Phone number marked as unreachable.',
                'phone': phone_number,
                'customer_id': customer_id,
            }
        )
    else:
        nsq_message = {'phone': phone_number, 'status': True, 'customer_id': customer_id}
        nsq_producer.publish_message(NsqTopic().sms_reachability_status, nsq_message)
        logger.info(
            {
                'action': 'evaluate_sms_reachability',
                'message': 'Phone number marked as reachable.',
                'phone': phone_number,
                'customer_id': customer_id,
            }
        )


@task(queue='comms')
def save_status_detail_for_vonage_outbound_call(voice_call_record_id: int, detail: str):
    """
    Saves 'detail' data from Vonage outbound call callback payload.

    Args:
        detail (str): The string of 'detail' found in payload with 'status': failed, rejected, unanswered.
            https://developer.vonage.com/en/voice/voice-api/webhook-reference#failed
            https://developer.vonage.com/en/voice/voice-api/webhook-reference#rejected
            https://developer.vonage.com/en/voice/voice-api/webhook-reference#unanswered
    """
    nsq_message = {'voice_call_record_id': voice_call_record_id, 'detail': detail}

    nsq_producer = get_nsq_producer()

    logger.info(
        {
            'action': 'save_status_detail_for_vonage_outbound_call',
            'message': 'VoiceCallRecord with failed, unanswered, or rejected status detected.',
            'voice_call_record_id': voice_call_record_id,
            'detail': detail,
        }
    )
    nsq_producer.publish_message(NsqTopic().vonage_outbound_call_detail, nsq_message)


@task(queue='comms')
def evaluate_email_reachability(
    email: str, customer_id: int, status: str, message_id: str, event_timestamp: int
):
    """
    Preprocess data required for email reachability evaluation.

    Args:
        email (str): The email address to be evaluated.
        customer_id (int): Customer.pk for master reachability.
        status (str): The email status to pass for evaluation.
        message_id (str): A unique identifier for the email. E.g. Sendgrid Message ID.
        event_timestamp (int): Timestamp from SendGrid.
    """
    nsq_message = {
        'email': email,
        'customer_id': customer_id,
        'status': status,
        'message_id': message_id,
        'event_timestamp': event_timestamp,
    }

    nsq_producer = get_nsq_producer()
    nsq_producer.publish_message(NsqTopic().email_reachability_status, nsq_message)

    logger.info(
        {
            'action': 'evaluate_email_reachability',
            'message': 'Successfully pushed data for reachability.',
            'data': nsq_message,
        }
    )
