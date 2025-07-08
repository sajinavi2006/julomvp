import logging

from juloserver.account.services.credit_limit import (
    get_credit_matrix,
    get_salaried,
    get_transaction_type,
)
from juloserver.apiv2.credit_matrix2 import messages
from juloserver.julo.constants import ScoreTag
from juloserver.julo.models import CreditMatrix

logger = logging.getLogger(__name__)


def get_good_score_j1(
    probability,
    job_type,
    is_premium_area,
    is_fdc,
    credit_matrix_type="julo1",
):
    is_salaried = get_salaried(job_type)

    credit_matrix_parameters = dict(
        min_threshold__lte=probability,
        max_threshold__gte=probability,
        credit_matrix_type=credit_matrix_type,
        is_salaried=is_salaried,
        is_premium_area=is_premium_area,
        is_fdc=is_fdc,
    )

    transaction_type = get_transaction_type()
    credit_matrix = get_credit_matrix(credit_matrix_parameters, transaction_type)

    if credit_matrix:
        return (
            credit_matrix.score,
            credit_matrix.list_product_lines,
            credit_matrix.message,
            credit_matrix.score_tag,
            credit_matrix.version,
            credit_matrix.id,
        )

    logger.error(
        {
            'action_view': 'get_good_score_j1',
            'probabilty': probability,
            'errors': "get good score from hard-code",
        }
    )

    credit_matrix_low_score = CreditMatrix.objects.get_current_matrix_for_matrix_type(
        'C', ScoreTag.C_LOW_CREDIT_SCORE, credit_matrix_type
    )
    matrix_id, version = (
        (credit_matrix_low_score.id, credit_matrix_low_score.version)
        if credit_matrix_low_score
        else (None, None)
    )

    return (
        'C',
        'credit_matrix_low_score.list_product_lines',
        messages['C_score_and_passed_binary_check'],
        ScoreTag.C_LOW_CREDIT_SCORE,
        version,
        matrix_id,
    )
