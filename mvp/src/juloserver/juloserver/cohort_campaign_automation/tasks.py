import logging
from celery import task
from juloserver.cohort_campaign_automation.models import (
    CollectionCohortCampaignAutomation,
    CollectionCohortCampaignEmailTemplate,
)
from juloserver.cohort_campaign_automation.constants import CohortCampaignAutomationStatus
from juloserver.cohort_campaign_automation.services.services import (
    process_cohort_campaign_automation,
    validation_csv_file,
)
from juloserver.cohort_campaign_automation.utils import upload_file_to_oss
from django.utils import timezone
from juloserver.cohort_campaign_automation.utils import download_cohort_campaign_csv
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst
from juloserver.loan_refinancing.constants import CovidRefinancingConst

import math
import numpy as np
from typing import Any
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.cohort_campaign_automation.services.notification_related import (
    CohortCampaignAutomationEmail,
)
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
)

logger = logging.getLogger(__name__)


@task(queue='collection_low')
def upload_file_cohort_campaign_automation(model_id, binner_bytes, remote_name, csv_file=None):
    logger.info(
        {
            "action": "upload_file_cohort_campaign_automation",
            "info": "task begin",
        }
    )
    try:
        # define this id csv file or banner email
        # example: remote_name = 'cohort_campaign_automation/banner_email/test_4.png'
        # and file_type will be 'banner_email'
        file_type = remote_name.split('/')[1]
        model_related = CollectionCohortCampaignEmailTemplate
        is_csv_valid = False
        is_csv_file = False
        err_msg = ''
        if file_type != 'banner_email':
            is_csv_valid, err_msg, offer = validation_csv_file(binner_bytes)
            is_csv_file = True
            model_related = CollectionCohortCampaignAutomation

        model = model_related.objects.filter(pk=model_id)
        if not model:
            logger.error(
                {
                    "action": "upload_file_cohort_campaign_automation",
                    "file": file_type,
                    "model_id": str(model_id),
                    "message": "not found",
                }
            )
            return
        if not is_csv_valid and is_csv_file:
            model.update(
                status=CohortCampaignAutomationStatus.FAILED,
                error_message=err_msg,
            )
            return
        url = upload_file_to_oss(binner_bytes, remote_name)
        if is_csv_file:
            model.update(csv_url=url, program_type=offer)
        else:
            model.update(banner_url=url)
    except Exception as e:
        logger.error(
            {
                "action": "upload_file_cohort_campaign_automation",
                "file": file_type,
                "model_id": str(model_id),
                "message": str(e),
            }
        )


@task(queue="collection_high")
def trigger_update_cohort_campaign_to_be_done():
    """
    this function will check campaign with status running,
    and if exceed the end date will set as Done
    """
    fn_name = 'trigger_update_cohort_campaign_to_be_done'
    logger.info({'action': fn_name, 'message': 'task begin'})
    today = timezone.localtime(timezone.now()).date()
    CollectionCohortCampaignAutomation.objects.filter(
        status=CohortCampaignAutomationStatus.RUNNING, end_date__lt=today
    ).update(status=CohortCampaignAutomationStatus.DONE)
    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue="collection_high")
def trigger_blast_cohort_campaign_automation():
    """
    this task will collect all campaign need to run today
    and throw it to subtask per campaign
    """
    fn_name = 'trigger_blast_cohort_campaign_automation'
    logger.info({'action': fn_name, 'message': 'task begin'})
    today = timezone.localtime(timezone.now()).date()
    list_cohort_campaign_today = CollectionCohortCampaignAutomation.objects.filter(
        status=CohortCampaignAutomationStatus.SCHEDULED, start_date=today
    )
    if not list_cohort_campaign_today:
        logger.info({'action': fn_name, 'message': "there's no cohort campaign to blast today"})
        return

    is_lender_validation = False
    allowed_lender = []
    is_dpd_validation = False
    dpd_start = 0
    dpd_end = 0
    csv_split_data = 5000
    parameters = {}
    api_key = ''
    queue = 'retrofix_normal'
    time_to_blast_refinancing = '08:00'

    promo_blast_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
    ).last()
    if promo_blast_fs:
        parameters = promo_blast_fs.parameters
        validation_settings = parameters.get('validation_settings')
        csv_split_data = parameters.get('campaign_automation', {}).get('csv_split_data', 5000)
        api_key = parameters.get('email_settings').get('api_key')
        queue = parameters.get('campaign_automation', {}).get('queue', 'retrofix_normal')
        time_to_blast_refinancing = parameters.get('campaign_automation', {}).get(
            'time_to_blast_refinancing', '08:00'
        )
        if validation_settings:
            lender_validation_settings = validation_settings.get('lender')
            dpd_validation_settings = validation_settings.get('dpd')
            if lender_validation_settings:
                is_lender_validation = lender_validation_settings.get('is_lender_validation', False)
                allowed_lender = lender_validation_settings.get('allowed_lender')
            if dpd_validation_settings:
                is_dpd_validation = dpd_validation_settings.get('is_dpd_validation', False)
                dpd_start = dpd_validation_settings.get('dpd_start')
                dpd_end = dpd_validation_settings.get('dpd_end')

    campaign_rules = dict(
        is_lender_validation=is_lender_validation,
        allowed_lender=allowed_lender,
        is_dpd_validation=is_dpd_validation,
        dpd_start=dpd_start,
        dpd_end=dpd_end,
        csv_split_data=csv_split_data,
        api_key=api_key,
        queue=queue,
    )

    now = timezone.localtime(timezone.now())
    time_execute = time_to_blast_refinancing.split(':')
    delay_in_hour = int(time_execute[0])
    delay_in_minutes = int(time_execute[1])
    execution_time = now.replace(hour=delay_in_hour, minute=delay_in_minutes, second=0)
    for cohort_campaign in list_cohort_campaign_today.iterator():
        campaign_rules.update(
            campaign_id=cohort_campaign.id,
        )
        trigger_blast_cohort_campaign_automation_subtask.apply_async(
            kwargs=campaign_rules, eta=execution_time
        )

        # update list of cohort campaign name, for exclude from email reminder refinancing
        existing_campaign_name = parameters.get('campaign_name_list', [])
        existing_campaign_name.append(cohort_campaign.campaign_name)
        parameters.update(campaign_name_list=existing_campaign_name)
        promo_blast_fs.update_safely(parameters=parameters)

        # update cohort campaign status to Running, since it's processing
        cohort_campaign.update_safely(status=CohortCampaignAutomationStatus.RUNNING)

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue="collection_high")
def trigger_blast_cohort_campaign_automation_subtask(**kwargs: Any):
    """
    this task will process campaign per one campaign
    """
    fn_name = 'trigger_blast_cohort_campaign_automation_subtask'
    logger.info({'action': fn_name, 'message': 'task begin'})
    campaign_id = kwargs.get('campaign_id', None)
    csv_split_data = kwargs.get('csv_split_data', 5000)
    campaign_rules = kwargs
    cohort_campaign = CollectionCohortCampaignAutomation.objects.filter(pk=campaign_id).last()
    if not cohort_campaign.csv_url:
        logger.info({'action': fn_name, 'message': 'csv url is null'})
        return

    csv_datas = download_cohort_campaign_csv(cohort_campaign.csv_url)
    if not csv_datas:
        logger.info({'action': fn_name, 'message': 'csv data is null'})
        return

    # split data csv, so can run paralel instead of loop one by one
    split_into = math.ceil(len(csv_datas) / csv_split_data)
    csv_data_per_batch = np.array_split(csv_datas, split_into)

    for csv_datas in csv_data_per_batch:
        refinancing_process_cohort_campaign_automation(csv_datas, campaign_rules)

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue="collection_high")
def refinancing_process_cohort_campaign_automation(csv_datas: Any, campaign_rules: dict):
    fn_name = 'refinancing_process_cohort_campaign_automation'
    logger.info({'action': fn_name, 'message': 'task begin'})
    process_cohort_campaign_automation(csv_datas, campaign_rules)
    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue='retrofix_normal')
def send_cohort_campaign_email(**kwargs):
    fn_name = 'send_cohort_campaign_email'
    logger.info({'action': fn_name, 'message': 'task begin'})

    loan_refinancing_request_id = kwargs.get('loan_refinancing_request_id', None)
    cohort_campaign_email_id = kwargs.get('cohort_campaign_email_id', None)
    api_key = kwargs.get('api_key', None)
    template_raw_email = ''
    curr_retries_attempt = send_cohort_campaign_email.request.retries
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        pk=loan_refinancing_request_id,
        status=CovidRefinancingConst.STATUSES.approved,
    ).last()
    if not loan_refinancing_request:
        logger.warning(
            {
                'function_name': fn_name,
                'message': 'loan refinancing request is not found',
                'loan_refinancing_request_id': loan_refinancing_request_id,
            }
        )
        return
    cohort_campaign_email = CollectionCohortCampaignEmailTemplate.objects.filter(
        pk=cohort_campaign_email_id
    ).last()
    promo_blast_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
    ).last()
    if promo_blast_fs:
        parameters = promo_blast_fs.parameters
        template_raw_email = parameters.get('campaign_automation', {}).get('email_html')
    try:
        expiry_at = cohort_campaign_email.campaign_automation.end_date
        campaign_email = CohortCampaignAutomationEmail(
            loan_refinancing_request, cohort_campaign_email, template_raw_email, expiry_at, api_key
        )
        campaign_email.send_email()
    except Exception as e:
        if curr_retries_attempt >= send_cohort_campaign_email.max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'Maximum retry for send_cohort_campaign_email',
                    'error': str(e),
                }
            )
            get_julo_sentry_client().captureException()
            return
        raise send_cohort_campaign_email.retry(
            countdown=600,
            exc=e,
            max_retries=3,
            kwargs={
                'loan_refinancing_request_id': loan_refinancing_request_id,
                'cohort_campaign_email_id': cohort_campaign_email_id,
                'api_key': api_key,
            },
        )
    logger.info({'action': fn_name, 'message': 'task finished'})
    return
