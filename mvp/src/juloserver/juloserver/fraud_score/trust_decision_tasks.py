import logging
from typing import (
    Dict,
    Tuple,
    Union,
)

from celery.task import task

from juloserver.fraud_score.clients import (
    get_finscore_client,
    get_trust_decision_client,
)
from juloserver.fraud_score.constants import TrustGuardConst
from juloserver.fraud_score.models import (
    FinscoreApiRawResult,
    FinscoreApiRequest,
    FinscoreApiResult,
    TrustGuardApiRawResult,
    TrustGuardApiRequest,
    TrustGuardApiResult,
)
from juloserver.fraud_score.trust_decision_services import (
    parse_data_for_finscore_payload,
    parse_data_for_trust_decision_payload,
    is_eligible_for_trust_decision,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    FeatureSetting,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='fraud')
def execute_finscore_result(application_id: str, event_type: str, device_id: str = None):
    """
    Handles logic for Finscore integration.

    Args:
        application_id (int): Application object 'id' property.
        device_id (str): String from Trust Guard API Result.
    """
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.TRUST_GUARD_SCORING,
    )
    if not feature_setting or not feature_setting.parameters.get('finscore'):
        logger.info({
            'action': 'execute_finscore_result',
            'message': 'Feature setting is turned off.',
            'application_id': application_id,
        })
        return

    if event_type != TrustGuardConst.EventType.APPLICATION[0]:
        logger.info({
            'action': 'execute_finscore_result',
            'message': 'Event type is not APPLICATION.',
            'application_id': application_id,
        })
        return

    application = Application.objects.get(id=application_id)

    try:
        finscore_api_request = FinscoreApiRequest.objects.create(
            application=application,
            device_id=device_id,
        )

        finscore_client = get_finscore_client()
        finscore_data = parse_data_for_finscore_payload(application, device_id)
        response, is_error = finscore_client.fetch_finscore_result(finscore_data)
        if not is_error:
            result = response.json()

            finscore_api_raw_result = FinscoreApiRawResult.objects.create(
                finscore_api_request=finscore_api_request,
                http_code=response.status_code,
                response_json=result,
            )

            if result['code'] == 0:
                FinscoreApiResult.objects.create(
                    finscore_api_request=finscore_api_request,
                    request_duration=response.elapsed,
                    code=result['code'],
                    reason_code=result['data'][0]['reasonCode'],
                    value=result['data'][0]['value'],
                )
            else:
                logger.info({
                    'action': 'execute_finscore_result',
                    'message': 'Non 0 API status code received.',
                    'application_id': finscore_data['application_id'],
                    'trust_guard_api_raw_result': finscore_api_raw_result.id,
                })
        else:
            response_json = None
            if 'application/json' in response.headers.get('content_type', ''):
                response_json = response.json()

            finscore_api_raw_result = FinscoreApiRawResult.objects.create(
                finscore_api_request=finscore_api_request,
                http_code=response.status_code,
                response_json=response_json,
            )
            logger.info({
                'action': 'execute_finscore_result',
                'message': 'Unexpected error detected.',
                'application_id': finscore_data['application_id'],
                'trust_guard_api_raw_result': finscore_api_raw_result.id,
                'response': response_json,
            })

    except Exception as e:
        sentry_client.captureException()
        logger.exception({
            'action': 'execute_finscore_result',
            'message': 'Finscore execution process fails.',
            'error': e,
        })


@task(queue='fraud')
def execute_trust_guard_for_loan_event(
    application_id: int,
    black_box_string: str,
    event_type: str,
    device_type: str = TrustGuardConst.DeviceType.ANDROID,
) -> Tuple[Dict, bool, Union[None, str]]:
    """
    Executes Trust Guard loan event scoring.

    Args:
        application_id (int): Application object 'id' property.
        black_box_string (str): black_box payload string provided by Android SDK.

    Returns:
        Dict: Scoring result from Trust Guard Decision API. Empty dict if fails.
        bool: True if fail to retrieve Trust Guard score.
        str: Error message to be returned if fail to retrieve score.
    """
    logger.info(
        {
            'function': 'TrustGuardScoreView execute_trust_guard_for_loan_event',
            'application_id': application_id,
            'black_box': black_box_string,
            'device_type': device_type,
        }
    )
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        logger.info({
            'action': 'execute_trust_guard_for_loan_event',
            'message': 'Application is not valid.',
            'application_id': application_id
        })
        return {}, True, 'Application is not valid'

    if not is_eligible_for_trust_decision(application):
        logger.info({
            'action': 'execute_trust_guard_for_loan_event',
            'message': 'Application is not eligible for trust decision.',
            'application_id': application.id
        })
        return {}, True, 'Application is not eligible for trust decision'

    try:
        abc_feature_name = FeatureNameConst.ABC_TRUST_GUARD_IOS
        if device_type == TrustGuardConst.DeviceType.ANDROID:
            abc_feature_name = FeatureNameConst.ABC_TRUST_GUARD

        abc_feature_setting = FeatureSetting.objects.filter(
            feature_name=abc_feature_name,
            is_active=True,
        ).last()

        feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.TRUST_GUARD_SCORING,
        )

        trust_guard_api_request = None

        if abc_feature_setting or (
            feature_setting.is_active and feature_setting.parameters.get('trust_guard')
        ):
            trust_guard_api_request = TrustGuardApiRequest.objects.create(
                application=application,
                black_box=black_box_string,
                device_type=device_type,
            )

        if abc_feature_setting:
            if (
                event_type == TrustGuardConst.EventType.APPLICATION[0]
                or event_type == TrustGuardConst.EventType.TRANSACTION[0]
            ):
                logger.info(
                    {
                        'action': 'execute_trust_guard_for_loan_event',
                        'message': 'Skip trust guard score for application and transaction event',
                        'application_id': application.id,
                    }
                )
                return {}, True, 'Skip trust guard score for application and transaction event type'

        if not feature_setting or not feature_setting.parameters.get('trust_guard'):
            logger.info(
                {
                    'action': 'execute_trust_guard_for_loan_event',
                    'message': 'Feature setting is turned off.',
                    'application_id': application_id,
                }
            )

            execute_finscore_result.delay(application_id, event_type)
            return (
                {},
                True,
                (
                    "Feature setting {} for Trust Guard is inactive.".format(
                        FeatureNameConst.TRUST_GUARD_SCORING
                    )
                ),
            )

        trust_decision_client = get_trust_decision_client()
        trust_decision_data = parse_data_for_trust_decision_payload(
            application, black_box_string, event_type
        )
        response, is_error = trust_decision_client.fetch_trust_guard_loan_event(
            trust_decision_data, trust_guard_api_request
        )

        if not is_error:
            result = response.json()

            TrustGuardApiRawResult.objects.create(
                trust_guard_api_request=trust_guard_api_request,
                http_code=response.status_code,
                response_json=result,
            )

            if result['code'] == 200:
                TrustGuardApiResult.objects.create(
                    trust_guard_api_request=trust_guard_api_request,
                    request_duration=response.elapsed,
                    code=result['code'],
                    score=result['score'],
                    result=result['result'],
                    sequence_id=result['sequence_id'],
                    event_type=event_type
                )

                device_id = result['device_info'].get('device_id')
                if not device_id:
                    logger.info({
                        'action': 'execute_trust_guard_for_loan_event',
                        'message': 'no device_id in response',
                        'application_id': application_id,
                    })

                execute_finscore_result.delay(
                    application_id, event_type, device_id
                )
                return result, False, None
            else:
                execute_finscore_result.delay(application_id, event_type)
                return result, True, 'Trust Guard Non-200 API Status Code Received'
        else:
            err_resp = getattr(response, "response", None)
            if err_resp is None:
                err_resp = response
            headers = getattr(err_resp, "headers", None)

            content_type_raw = ""
            if isinstance(headers, dict):
                content_type_raw = headers.get("Content-Type")
            elif hasattr(headers, "get"):
                try:
                    content_type_raw = headers.get("Content-Type")
                except Exception:
                    pass

            content_type = str(content_type_raw or "").lower()

            if "application/json" in content_type:
                try:
                    response_json = err_resp.json()
                except ValueError:
                    response_json = {"raw_body": getattr(err_resp, "text", str(err_resp))}
            else:
                response_json = {
                    "error": (
                        getattr(err_resp, "text", None)
                        or getattr(err_resp, "reason", "")
                        or str(err_resp)
                    )
                }

            status_code = getattr(err_resp, "status_code", 0)

            TrustGuardApiRawResult.objects.create(
                trust_guard_api_request=trust_guard_api_request,
                http_code=status_code,
                response_json=response_json,
            )

            execute_finscore_result.delay(application_id, event_type)

            return {}, True, 'An unexpected error has occurred.'
    except Exception as e:
        sentry_client.captureException()
        logger.exception({
            'action': 'execute_trust_guard_for_loan_event',
            'message': 'Trust Guard execution process fails.',
            'error': e,
        })

        execute_finscore_result.delay(application_id, event_type)

        return {}, True, 'An unexpected error has occurred.'
