import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from django.conf import settings
from requests.exceptions import ReadTimeout, ConnectionError
import requests

from juloserver.ana_api.constants import MINIMUM_INCOME
from juloserver.ana_api.models import PdBankScrapeModelResult
from juloserver.apiv2.models import EtlJob
from juloserver.cfs.constants import CfsEtlJobStatus
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Application
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import post_anaserver
from juloserver.application_flow.services import send_application_event_for_x100_device_info
from juloserver.application_flow.constants import ApplicationStatusEventType
from juloserver.loan.services.feature_settings import AnaTransactionModelSetting

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def check_positive_processed_income(application_id):
    pd_bank_scrape_model_result = PdBankScrapeModelResult.objects.filter(
        application_id=application_id
    ).last()
    if not pd_bank_scrape_model_result:
        return False

    if not pd_bank_scrape_model_result.processed_income or (
        pd_bank_scrape_model_result.processed_income <= MINIMUM_INCOME
    ):
        return False

    return True


def run_sonic_model(application):
    # triggering sonic between certain pgood
    ana_data = {'application_id': application.id}
    url = '/api/amp/v1/sonic-model/'
    response = post_anaserver(url, json=ana_data)
    logger.info({'Sonic overhaul response: ': response.status_code})


def run_ana_clik_model(application):
    ana_data = {'application_id': application.id}
    url = '/api/amp/v1/clik/'
    response = post_anaserver(url, json=ana_data)
    logger.info({'ANA clik model response: ': response.status_code})


def predict_bank_scrape(application):
    application_status_id = application.application_status_id
    if application_status_id < ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        return False
    url = '/api/amp/v1/bank-scrape-model'
    is_success = True
    try:
        post_anaserver(url, json={'application_id': application.id})
    except JuloException as e:
        logger.error('error predict bank scrap data, error=%s' % str(e))
        is_success = False
    return is_success


def process_etl_push_notification_update_status(etl_job_id):
    import traceback
    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.cfs.services.core_services import process_post_connect_bank

    etl_job = EtlJob.objects.get(pk=etl_job_id)
    application_id = etl_job.application_id
    application = Application.objects.get(pk=application_id)
    cfs_available_etl_statuses = CfsEtlJobStatus.AVAILABLE_FOR_BANK
    etl_job_status = etl_job.status

    if etl_job_status in cfs_available_etl_statuses:
        process_post_connect_bank(application, etl_job)

    if etl_job_status == EtlJob.LOAD_SUCCESS:
        predict_bank_scrape(application)

        if application.status in [100, 105, 120, 121]:
            application_tag_tracking_task.delay(
                application_id, None, None, None, 'is_bank_scrape', 1, traceback.format_stack()
            )


def process_dsd_completion(application, is_completed):
    if not is_completed:
        logger.info('dsd_is_not_completed|application_id={}'.format(application.id))
        return

    send_application_event_for_x100_device_info(
        application, ApplicationStatusEventType.APPSFLYER_AND_GA
    )


@dataclass(frozen=True)
class LoanSelectionAnaAPIPayload:
    """
    Request Payload for ana api: /api/amp/v1/loan-selection
    """

    customer_id: int
    min_loan_duration: int
    max_loan_duration: int
    available_limit: int
    set_limit: int
    transaction_method_id: int


@dataclass
class TransactionModelResult:
    """
    Response structure received from ANA model
    allowed_loan_duration_amount: {
        max_cashloan_amount: int
        loan_duration_range: List[int]
    }
    """

    prediction_time: str
    is_mercury: bool
    allowed_loan_duration_amount: dict


def predict_loan_selection(
    payload: LoanSelectionAnaAPIPayload,
) -> Tuple[bool, Optional[TransactionModelResult]]:
    """ "
    Returns: (is_success, Dict)
    """
    logger.info(
        {
            "action": "juloserver.ana_api.services.predict_loan_selection",
            "message": "About to hit ana loan duration prediction API",
            "payload": payload.__dict__,
            "customer_id": payload.customer_id,
        }
    )

    url = '/api/amp/v1/loan-selection'
    dict_data = payload.__dict__

    # hit anaserver, no retry
    headers = {'Authorization': 'Token %s' % settings.ANASERVER_TOKEN}
    url = settings.ANASERVER_BASE_URL + url

    # make request & handle case read time out
    max_timeout_secs = AnaTransactionModelSetting().request_timeout
    try:
        response = requests.post(
            url=url,
            json=dict_data,
            headers=headers,
            timeout=max_timeout_secs,
        )
    except (ReadTimeout, ConnectionError):
        logger.info(
            {
                "action": "juloserver.ana_api.services.predict_loan_selection",
                "message": "Request timeout/Connection Error when predicting ANA loan selection",
                "payload": payload.__dict__,
                "customer_id": payload.customer_id,
                "timeout_seconds": max_timeout_secs,
            }
        )
        return False, None

    # logging after requests
    logger.info(
        {
            "action": "juloserver.ana_api.services.predict_loan_selection",
            "message": "Finished hitting ana loan duration prediction API",
            "payload": payload.__dict__,
            "customer_id": payload.customer_id,
            "response_status": response.status_code,
            "response": response.json() if response.status_code in [200, 201] else {},
        }
    )

    # handle status code
    if response.status_code in [200, 201]:
        result_json = response.json()
        response = TransactionModelResult(**result_json)
        return True, response
    elif response.status_code in [204]:
        # success but no prediction data
        return True, None
    else:
        sentry_client.captureMessage(
            {
                "message": "Bad response status from Ana Predict Loan Selection API",
                "action": "juloserver.ana_api.services.predict_loan_selection",
                "response_text": response.text,
                "response_status_code": response.status_code,
                "customer_id": payload.customer_id,
            }
        )
        return False, None
