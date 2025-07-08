import logging

from celery import task
from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.utils import timezone
from requests import (
    ConnectTimeout,
    ConnectionError,
)

from juloserver.account.models import Account
from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.fraud_score import monnai_services
from juloserver.fraud_score import seon_services
from juloserver.fraud_score.clients import get_bonza_client
from juloserver.fraud_score.constants import SeonConstant, MonnaiConstants
from juloserver.fraud_score.exceptions import IncompleteRequestData
from juloserver.fraud_score.models import (
    BonzaScoringResult,
    SeonFingerprint,
    TelcoLocationResult,
    MaidResult,
)
from juloserver.fraud_score.services import (
    eligible_for_bonza,
    account_under_bonza_reverse_experiment,
)
from juloserver.fraud_score.utils import check_application_experiment_monnai_eligibility
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    Loan,
    PaymentEvent,
)
from juloserver.julo.models import FeatureSetting
from juloserver.pii_vault.constants import PiiSource
from juloserver.streamlined_communication.constant import SmsTspVendorConstants
from juloserver.streamlined_communication.utils import get_telco_code_and_tsp_name

logger = logging.getLogger(__name__)


@task(queue='loan_low')
def hit_bonza_storing_api(method_name, model_name, object_id):
    model = apps.get_model(app_label='julo', model_name=model_name)
    model_object = model.objects.get(id=object_id)
    if eligible_for_bonza(model_object, model_name) is True:
        bonza_client = get_bonza_client()
        getattr(bonza_client, method_name)(model_object)
    logger.info({
        'task': 'hit_bonza_storing_api',
        'method_name': method_name,
        'object_id': model_object.id
    })


@task(queue='loan_low')
def hit_bonza_loan_scoring_asynchronous(loan_id, inhouse=False):
    loan = Loan.objects.get(id=loan_id)
    bonza_client = get_bonza_client()
    if inhouse:
        response = bonza_client.get_loan_transaction_scoring_inhouse(loan, timeout_on=False)
    else:
        response = bonza_client.get_loan_transaction_scoring(loan, timeout_on=False)
    logger.info({
        'task': 'hit_bonza_loan_scoring_asynchronous',
        'method_name': 'get_loan_transaction_scoring',
        'object_id': loan_id,
        'success': True if response and response.get('score') else False
    })


@task(queue='loan_low')
def send_payment_events_and_expire_old_accounts_from_holdout(account_id):
    account = Account.objects.get_or_none(pk=account_id)
    if account:
        under_experiement, in_control_performance_grp = account_under_bonza_reverse_experiment(
            account.id, True)
        act_loans = account.loan_set.order_by('cdate')
        loan_count, unsent_payment_ids = act_loans.count(), []
        if under_experiement:
            if loan_count in range(2, 5):
                if in_control_performance_grp:
                    last_loan, second_last_loan = act_loans.last(), act_loans[loan_count - 2]
                    unsent_payment_ids = PaymentEvent.objects.filter(
                        cdate__gte=second_last_loan.cdate, cdate__lte=last_loan.cdate,
                        event_type='payment',
                        payment__loan__account=account).values_list('payment_id', flat=True)
                else:
                    if loan_count == 4:
                        unsent_payment_ids = PaymentEvent.objects.filter(
                            event_type='payment',
                            payment__loan__account=account).values_list('payment_id', flat=True)
            for payment_id in unsent_payment_ids:
                hit_bonza_storing_api.apply_async(
                    ('post_loan_payment_data', 'Payment', payment_id), countdown=60)


@task(queue='loan_low')
def bonza_rescore_5xx_hit_asynchronously(initial_rescore=False):
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BONZA_LOAN_SCORING, is_active=True
    ).exists():
        return

    if initial_rescore:
        latest_5xx_hits = BonzaScoringResult.objects.filter(
            status__contains='5').distinct('loan_id')
    else:
        yesterday = timezone.localtime(timezone.now()).date() - relativedelta(days=1)
        latest_5xx_hits = BonzaScoringResult.objects.filter(
            cdate__date=yesterday, status__contains='5').distinct('loan_id')
    loan_ids = latest_5xx_hits.values_list('loan_id', flat=True)
    already_rescored_loan_ids = BonzaScoringResult.objects.filter(
        status__contains='async-rehit', loan_id__in=loan_ids).values_list('loan_id', flat=True)
    to_rescore_loan_ids = list(set(loan_ids) - set(already_rescored_loan_ids))
    for loan_id in to_rescore_loan_ids:
        hit_bonza_loan_scoring_asynchronous.apply_async((loan_id, True), countdown=30)


@task(queue='loan_low')
def hit_bonza_storing_api_inhouse(loan_id):
    loan = Loan.objects.get(id=loan_id)
    bonza_client = get_bonza_client()
    bonza_client.hit_inhouse_storing_api(loan)
    logger.info({
        'task': 'hit_bonza_storing_api_inhouse',
        'object_id': str(loan_id)
    })


def execute_hit_bonza_storing_api_inhouse(loan_id):
    if FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BONZA_LOAN_SCORING, is_active=True
    ).exists():
        hit_bonza_storing_api_inhouse.apply_async((loan_id,), countdown=30)


@task(queue='application_low')
@seon_services.seon_enabled_wrapper
def handle_post_user_submit_application(
    customer_id,
    application_id,
    ip_address: str,
    request_data: dict,
) -> None:
    """
    This task is called when a user submits an application via ApplicationUpdateV3.
    """

    # Store SEON fingerprint data.
    seon_services.store_seon_fingerprint({
        'customer_id': customer_id,
        'trigger': SeonConstant.Trigger.APPLICATION_SUBMIT,
        'ip_address': ip_address,
        'sdk_fingerprint_hash': request_data.get('seon_sdk_fingerprint', None),
        'target_type': SeonConstant.Target.APPLICATION,
        'target_id': application_id,
    })


@task(queue='application_low')
def handle_fraud_score_post_application_credit_score(application_id):
    """
    This task triggers all fraud score related function.

    This task is called when the credit score has been generated and not move to graveyard.
    see: handle_iti_ready()
    """
    fetch_seon_application_submit_result.delay(application_id=application_id)


@task(queue='seon_global_queue')
@seon_services.seon_enabled_wrapper
def fetch_seon_application_submit_result(application_id):
    """
    Send and store the SEON fraud API to DB.
    """
    seon_fingerprint = SeonFingerprint.objects.filter(
        target_type=SeonConstant.Target.APPLICATION,
        target_id=application_id,
        trigger=SeonConstant.Trigger.APPLICATION_SUBMIT,

    ).last()

    if not seon_fingerprint:
        logger.info({
            'action': 'fetch_seon_application_submit_result',
            'application_id': application_id,
            'message': 'No seon fingerprint found.',
        })
        return

    fetch_seon_fraud_api_result.delay(seon_fingerprint.id)


@task(queue='seon_global_queue', rate_limit='2/s')
@seon_services.seon_enabled_wrapper
def fetch_seon_fraud_api_result(seon_fingerprint_id):
    seon_fingerprint = SeonFingerprint.objects.get(id=seon_fingerprint_id)

    seon_repository = seon_services.get_seon_repository()
    seon_repository.fetch_fraud_api_result(seon_fingerprint)


@task(
    queue='monnai_global_queue',
    rate_limit='5/s',
    autoretry_for=(ConnectTimeout, ConnectionError,),
    max_retries=5,
    retry_backoff=5,
)
@monnai_services.monnai_enabled_wrapper
def fetch_monnai_application_submit_result(application_id: str):
    """
    Args:
        application_id (str): ID property of an Application object.
    """
    feature_setting = FeatureSetting.objects.get(feature_name=FeatureNameConst.MONNAI_FRAUD_SCORE)
    test_group = feature_setting.parameters.get('test_group')
    packages = [
        MonnaiConstants.ADDRESS_VERIFICATION,
        MonnaiConstants.DEVICE_DETAILS
    ]
    application = Application.objects.get(id=application_id)

    telco_location_result_exist = TelcoLocationResult.objects.filter(
        application_id=application.id
    ).last()
    maid_result_exist = MaidResult.objects.filter(
        application_id=application.id
    ).last()
    if telco_location_result_exist and MonnaiConstants.ADDRESS_VERIFICATION in packages:
        packages.remove(MonnaiConstants.ADDRESS_VERIFICATION)
        logger.error({
            'action': 'fetch_monnai_application_submit_result',
            'message': 'telco location result exist in database',
            'application_id': application_id,
        })
        return
    if maid_result_exist and MonnaiConstants.DEVICE_DETAILS in packages:
        packages.remove(MonnaiConstants.DEVICE_DETAILS)
        logger.error({
            'action': 'fetch_monnai_application_submit_result',
            'message': 'maid result exist in database',
            'application_id': application_id,
        })
        return

    if not packages:
        return

    # beside indosat users and tri users, won't hit telco API's
    detokenized_application = detokenize_pii_antifraud_data(
        PiiSource.APPLICATION, [application], ['mobile_phone_1']
    )[0]
    application_phone_number = detokenized_application.mobile_phone_1
    _, application_tsp_name = get_telco_code_and_tsp_name(application_phone_number)
    if (
        application_tsp_name != SmsTspVendorConstants.INDOSAT_OOREDO
        and application_tsp_name != SmsTspVendorConstants.HUTCHISON_TRI
        and MonnaiConstants.ADDRESS_VERIFICATION in packages
    ):
        packages.remove(MonnaiConstants.ADDRESS_VERIFICATION)

    if not packages:
        return

    if not check_application_experiment_monnai_eligibility(int(application_id), test_group):
        return

    monnai_repository = monnai_services.get_monnai_repository()
    try:
        (
            monnai_repository.fetch_insight_for_address_verification_and_device_detail(
                application, packages, application_tsp_name, application_phone_number
            )
        )
    except IncompleteRequestData as exception:
        logger.error({
            'action': 'fetch_monnai_application_submit_result',
            'message': str(exception),
            'application_id': application_id,
            'payload': exception.request_data,
        })
        raise
