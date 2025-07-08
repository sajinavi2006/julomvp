from django.db import transaction
from django.db.models import Q

from juloserver.income_check.clients import get_julo_izidata_client
from juloserver.income_check.constants import IziDataConstant
from juloserver.income_check.models import IncomeCheckAPILog, IncomeCheckLog
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object


def request_izi_data(url, data):
    izi_data_client = get_julo_izidata_client()
    return izi_data_client.request(url, data)


def check_salary_izi_data(application):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    relative_url = 'salary'

    detokenized_application = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'customer_xid': application.customer.customer_xid, 'object': application}],
        force_get_local_data=True,
    )
    application = detokenized_application[0]
    data = {"id": application.ktp}

    check_income_log = IncomeCheckLog.objects.filter(application_id=application.id).last()
    if check_income_log:
        return check_income_log.is_found

    check_salary = request_izi_data(relative_url, data)

    headers = check_salary['headers'] if 'headers' in check_salary else None

    response = None
    status_code = IziDataConstant.FAILED_STATUS_CODE
    latency = 0
    if 'response' in check_salary:
        response = check_salary['response'].json()
        latency = check_salary['response'].elapsed.total_seconds() * 1000

        if check_salary['response'].status_code is not None:
            status_code = check_salary['response'].status_code

    url = check_salary['url'] if 'url' in check_salary else ''

    is_found = False
    status = 'Empty Response'
    if response and 'status' in response:
        status = response['status']
        is_found = response['status'] == 'OK'

    salary_amount = None
    message = None
    if response and 'message' in response:
        if not is_found:
            message = response['message']

        if is_found and 'salary' in response['message']:
            salary_amount = int(response['message']['salary'])

    with transaction.atomic(using='onboarding_db'):
        income_check_log = IncomeCheckLog.objects.create(
            is_found=is_found,
            status=status,
            message=message,
            salary_amount=salary_amount,
            currency='USD',
            service_provider='izidata',
            application_id=application.id,
        )

        log_api_call(
            headers,
            response,
            'check_salary',
            url,
            income_check_log.pk,
            latency,
            status_code,
            status,
        )

    application_tag_status = -1
    if status_code == 500 or status == 'RETRY_LATER':
        application_tag_status = 0
    elif is_found:
        application_tag_status = 1

    application_tag_tracking_task(
        application.id, None, None, None, 'is_income_check', application_tag_status
    )

    return is_found


def log_api_call(
    headers, response, api_type, uri_path, income_check_log_id, latency, status_code, status
):
    IncomeCheckAPILog.objects.create(
        request=str(headers),
        response=str(response),
        http_status_code=status_code,
        api_type=api_type,
        income_check_log_id=income_check_log_id,
        query_params=uri_path,
        latency=latency,
        status=status,
    )


def is_income_in_range(application):
    from juloserver.apiv2.services import (
        get_customer_category,
        get_latest_iti_configuration,
    )
    from juloserver.julo.models import CreditScore, ITIConfiguration, JobType

    is_salaried = JobType.objects.get_or_none(job_type=application.job_type).is_salaried
    customer_category = get_customer_category(application)
    latest_iti_config = get_latest_iti_configuration(customer_category)
    credit_score = CreditScore.objects.filter(application=application).last()

    return (
        ITIConfiguration.objects.filter(
            is_active=True,
            is_salaried=is_salaried,
            is_premium_area=credit_score.inside_premium_area,
            customer_category=customer_category,
            iti_version=latest_iti_config['iti_version'],
            min_income__lte=application.monthly_income,
            max_income__gt=application.monthly_income,
        )
        .filter(
            Q(parameters__partner_ids__isnull=True) | Q(parameters__partner_ids__exact=[]),
            Q(parameters__agent_assisted_partner_ids__isnull=True)
            | Q(parameters__agent_assisted_partner_ids__exact=[]),
        )
        .exists()
    )
