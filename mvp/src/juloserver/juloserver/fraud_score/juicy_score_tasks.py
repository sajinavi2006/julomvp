import logging

from celery.task import task
from typing import Union

from juloserver.fraud_score.juicy_score_services import (
    is_eligible_for_juicy_score,
    get_juicy_score_repository,
    check_api_limit_exceeded,
)
from juloserver.julo.models import (
    Application,
    Customer,
    FeatureSetting,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='juicy_score_queue')
def execute_juicy_score_result(
    request_data: dict,
    application_id: int,
    customer_id: int,
) -> Union[dict, str]:
    logger.info({
        'action': 'juicy_score task start execute_juicy_score_result',
        'application_id': application_id,
        'customer_id': customer_id
    })

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JUICY_SCORE_FRAUD_SCORE,
        is_active=True,
    ).last()
    if not feature_setting:
        logger.warning({
            'action': 'juicy_score task feature setting check',
            'message': 'Api reach max threshold'
        })
        return False, 'Juicy Score feature is not found or inactive'

    try:
        application = Application.objects.get(pk=application_id)
        customer = Customer.objects.get(pk=customer_id)
        if check_api_limit_exceeded(feature_setting):
            logger.warning({
                'action': 'juicy_score task check_api_limit_exceeded',
                'message': 'Api reach max threshold'
            })
            return False, 'Api reach max limit threshold'

        if not is_eligible_for_juicy_score(application):
            logger.info({
                'action': 'juicy_score task is_eligible_for_juicy_score',
                'application_id': application.id,
                'message': 'Application is not eligible for juicy score'
            })
            return False, 'Application is not eligible for juicy score'

        request_data.update({"customer_xid": customer.customer_xid})

        juicy_score_repository = get_juicy_score_repository()
        juicy_score_repository.fetch_get_score_api_result(request_data, application)

        return True, None

    except Exception as e:
        sentry_client.captureException()
        logger.exception(
            {
                'action': 'juicy_score task execute_juicy_score_result',
                'message': 'juicy score execution process fails.',
                'error': str(e),
            }
        )
