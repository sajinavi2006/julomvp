import json
from json import JSONDecodeError
import operator

from django.db.models import Q
from django.utils import timezone

from juloserver.application_flow.models import BankStatementProviderLog
from juloserver.application_flow.services2.bank_statement import BankStatementClient, Perfios
from juloserver.cfs.constants import CfsMissionWebStatus
from juloserver.cfs.models import EasyIncomeEligible
from juloserver.julo.models import Customer, Application
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.cfs.services.core_services import (
    get_available_action_codes,
    get_available_mission_eligible_and_status
)


sentry_client = get_julo_sentry_client()


def get_data_for_easy_income_eligible_and_status(customer: Customer) -> dict:
    customer_id = customer.id
    if not check_whitelist_easy_income_eligible(customer_id):
        return {'is_eligible': False, 'status': None}

    action_codes = get_available_action_codes(customer_id)
    available_missions = get_available_mission_eligible_and_status(customer, action_codes)
    missions = []
    for action_code in action_codes:
        is_eligible, status = available_missions.get(action_code, (None, None))
        missions.append({
            'mission': action_code, 'is_eligible': is_eligible, 'status': status
        })
    response = combine_easy_income_eligible_and_status(missions)
    return response


def combine_easy_income_eligible_and_status(missions):
    is_eligible = all(map(operator.itemgetter('is_eligible'), missions))

    if not is_eligible:
        return {'is_eligible': False, 'status': CfsMissionWebStatus.APPROVED}

    if all(
        status in (CfsMissionWebStatus.START, CfsMissionWebStatus.REJECTED)
        for status in map(operator.itemgetter('status'), missions)
    ):
        return {'is_eligible': True, 'status': CfsMissionWebStatus.START}
    else:
        return {'is_eligible': True, 'status': CfsMissionWebStatus.IN_PROGRESS}


def check_whitelist_easy_income_eligible(customer_id: int) -> bool:
    today = timezone.localtime(timezone.now()).date()
    return EasyIncomeEligible.objects.filter(
        Q(customer_id=customer_id) &
        Q(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
        ),
    ).exists()


def get_perfios_url(application: Application):
    provider_log = BankStatementProviderLog.objects.filter(
        application_id=application.id,
        provider=BankStatementClient.PERFIOS,
    ).last()

    redirect_url = ''
    if provider_log:
        try:
            log = json.loads(provider_log.log.replace('\'', '\"'))
        except (TypeError, JSONDecodeError):
            return ''

        if log.get('status', '').lower() == 'success' and log.get('redirectUrl'):
            redirect_url = log['redirectUrl']
    else:
        provider = Perfios(application)
        redirect_url, _ = provider.get_token()

    return redirect_url
