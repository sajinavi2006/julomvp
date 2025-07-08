from django.db.models import Q

from juloserver.tokopedia.services.common_service import is_active_configuration
from juloserver.tokopedia.services.match_criteria_service import process_match_criteria
from juloserver.tokopedia.exceptions import (
    TokoScoreException,
    TokoScoreCreditMatrixException,
)
from juloserver.tokopedia.services.match_criteria_service import fetch_heimdall_score
from juloserver.account.services.credit_limit import (
    get_salaried,
    get_credit_matrix,
    get_transaction_type,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.account.services.credit_limit import is_inside_premium_area
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.tokopedia.constants import TokoScoreConst


logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def build_credit_matrix_parameters(application_id):

    configuration = is_active_configuration(is_need_to_active=False)
    match_criteria = process_match_criteria(application_id, configuration)
    criteria_config = configuration.criteria.get(match_criteria)

    try:
        params = {'min_threshold': criteria_config['heimdall']['bottom_threshold']}
        if 'upper_threshold' in criteria_config['heimdall']:
            params['max_threshold'] = criteria_config['heimdall']['upper_threshold']
    except KeyError as error:
        raise TokoScoreException(str(error))

    logger.info(
        {
            'message': 'Tokoscore: build credit matrix parameters',
            'application': application_id,
            'params': str(params),
            'matched_criteria': str(criteria_config),
        }
    )

    return params


@sentry.capture_exceptions
def fetch_credit_matrix_with_parameter(application):
    """
    Fetch credit matrix with parameter (Criteria Tokoscore)
    """

    additional_params = build_credit_matrix_parameters(application.id)
    heimdall = fetch_heimdall_score(application.id)

    params = {
        "min_threshold__lte": heimdall,
        "max_threshold__gte": heimdall,
        "credit_matrix_type": "julo1",
        "is_salaried": get_salaried(application.job_type),
        "is_premium_area": is_inside_premium_area(application),
    }

    params = {**params, **additional_params}

    logger.info(
        {
            'message': 'Tokoscore: fetch credit matrix process',
            'params': str(params),
            'application': application.id,
            'heimdall': heimdall,
        }
    )

    credit_matrix = get_credit_matrix(
        params,
        get_transaction_type(),
        parameter=Q(parameter=TokoScoreConst.CREDIT_MATRIX_PARAMETER),
    )

    if credit_matrix is None:
        logger.error(
            {
                'message': 'Tokoscore: Configuration value criteria '
                'is different with credit matrix',
                'application': application.id,
            }
        )
        raise TokoScoreCreditMatrixException('Tokoscore criteria is different with Credit Matrix')

    return credit_matrix
