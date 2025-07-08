from juloserver.apiv2.models import (
    AutoDataCheck,
    PdCreditModelResult,
    PdWebModelResult,
)

from juloserver.tokopedia.constants import TokoScoreCriteriaConst
from juloserver.tokopedia.exceptions import TokoScoreException
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def process_match_criteria(application_id, configuration, is_available_fdc_check=None):

    if not configuration:
        return None

    criteria = configuration.criteria
    results = {}

    for key in criteria:
        if key in ('criteria_1', 'criteria_2', 'criteria_3'):
            results[key] = is_pass_criteria(
                application_id,
                criteria[key],
                is_available_fdc_check=is_available_fdc_check,
            )

    total_matched = sum(results.values())
    if total_matched == 0:
        logger.warning(
            {
                'message': 'Tokoscore: No match criteria',
                'application': application_id,
                'result': str(results),
            }
        )
        raise TokoScoreException('No match criteria')

    if total_matched > 1:
        logger.warning(
            {
                'message': 'Tokoscore: Have more than one match criteria',
                'application': application_id,
                'result': str(results),
            }
        )

    final_result = [key for key, value in results.items() if value is True][0]

    logger.warning(
        {
            'message': 'Tokoscore: Final result from match criteria',
            'application': application_id,
            'result': str(results),
            'final_result': final_result,
        }
    )

    return final_result


def is_pass_criteria(application_id, criteria, is_available_fdc_check=None):

    fdc_criteria = criteria["fdc"]
    heimdall_criteria = criteria["heimdall"]
    mycroft_criteria = criteria["mycroft"]

    fdc, heimdall, mycroft = fetch_all_data_to_process_check(
        application_id=application_id,
        is_available_fdc_check=is_available_fdc_check,
    )

    fdc_result = is_passed_fdc(fdc, fdc_criteria, application_id)
    heimdall_result = is_passed_heimdall_score(heimdall, heimdall_criteria, application_id)
    mycroft_result = is_passed_mycroft_score(mycroft, mycroft_criteria, application_id)

    logger.info(
        {
            'message': 'Tokoscore: checking all criteria data',
            'application': application_id,
            'fdc_result': fdc_result,
            'heimdall_result': heimdall_result,
            'mycroft_result': mycroft_result,
        }
    )

    return fdc_result and heimdall_result and mycroft_result


def is_passed_fdc(value, fdc_criteria, application_id):

    logger.info(
        {
            'message': 'Tokoscore: comparison data FDC',
            'application': application_id,
            'fdc_criteria': fdc_criteria,
            'value': value,
        }
    )

    return value == fdc_criteria


def is_passed_heimdall_score(value, criteria, application_id):

    try:
        bottom_threshold = float(criteria[TokoScoreCriteriaConst.KEY_BOTTOM_THRESHOLD])
        value = float(value)
        if TokoScoreCriteriaConst.KEY_UPPER_THRESHOLD in criteria:
            upper_threshold = float(criteria[TokoScoreCriteriaConst.KEY_UPPER_THRESHOLD])
            in_threshold = upper_threshold >= value >= bottom_threshold
        else:
            in_threshold = value >= bottom_threshold

        logger.info(
            {
                'message': 'Tokoscore: checking heimdall condition criteria',
                'application': application_id,
                'criteria': str(criteria),
                'value': value,
                'in_threshold': in_threshold,
            }
        )

        return in_threshold
    except Exception as e:
        logger.info(
            {
                'application_id': application_id,
                'message': 'Tokoscore: Failed check heimdall condition',
                'value': value,
                'criteria': str(criteria),
                'error_message': str(e),
            }
        )
        return False


def is_passed_mycroft_score(value, criteria, application_id):

    try:
        bottom_threshold = float(criteria[TokoScoreCriteriaConst.KEY_BOTTOM_THRESHOLD])
        value = float(value)
        if TokoScoreCriteriaConst.KEY_UPPER_THRESHOLD in criteria:
            upper_threshold = float(criteria[TokoScoreCriteriaConst.KEY_UPPER_THRESHOLD])
            in_threshold = upper_threshold >= value >= bottom_threshold
        else:
            in_threshold = value >= bottom_threshold

        logger.info(
            {
                'message': 'Tokoscore: checking mycroft condition criteria',
                'application': application_id,
                'criteria': str(criteria),
                'value': value,
                'in_threshold': in_threshold,
            }
        )

        return in_threshold
    except Exception as e:
        logger.info(
            {
                'application_id': application_id,
                'message': 'Tokoscore: Failed check mycroft condition',
                'error_message': str(e),
            }
        )
        return False


@sentry.capture_exceptions
def fetch_all_data_to_process_check(application_id, is_available_fdc_check=None):
    """
    Fetching all data to check based on criteria
    """

    try:
        fdc = fetch_fdc_data(application_id, is_available_fdc_check=is_available_fdc_check)
        heimdall = fetch_heimdall_score(application_id)
        mycroft = fetch_mycroft_score(application_id)
    except Exception as error:
        logger.error(
            {
                'message': 'Error when fetching data: {}'.format(str(error)),
                'application': application_id,
            }
        )
        raise TokoScoreException(str(error))

    return fdc, heimdall, mycroft


def fetch_fdc_data(application_id, is_available_fdc_check=None):

    logger.info({'message': 'Tokoscore: execute to fetch FDC', 'application': application_id})

    fdc_binary = AutoDataCheck.objects.filter(
        application_id=application_id, data_to_check='fdc_inquiry_check'
    ).last()

    is_okay = fdc_binary.is_okay
    # check if available fdc check not same with result on auto_data_check
    if fdc_binary.is_okay != is_available_fdc_check:

        # need to switch value if is_available_fdc_check is False or True.
        if is_available_fdc_check is not None:
            is_okay = is_available_fdc_check
            logger.info(
                {
                    'message': 'Tokoscore: Switch value to is_available_fdc_check',
                    'application_id': application_id,
                    'is_available_fdc_check': is_available_fdc_check,
                    'auto_data_check_value_is_okay': fdc_binary.is_okay,
                }
            )

    if is_okay is False:
        logger.warning(
            {
                'message': 'Tokoscore: Fetch FDC is fail',
                'application_id': application_id,
            }
        )
        return TokoScoreCriteriaConst.KEY_FDC_FETCH_FAIL

    # check credit model data
    credit_model = PdCreditModelResult.objects.filter(application_id=application_id).last()

    if not credit_model:
        credit_model = PdWebModelResult.objects.filter(application_id=application_id).last()

    has_fdc = credit_model.has_fdc if credit_model else False

    if has_fdc:
        logger.info(
            {
                'message': 'Tokoscore: Has FDC is True',
                'application': application_id,
                'result': TokoScoreCriteriaConst.KEY_FDC_FETCH_PASS,
            }
        )
        return TokoScoreCriteriaConst.KEY_FDC_FETCH_PASS

    logger.info(
        {
            'message': 'Tokoscore: Fetch FDC is not found',
            'application': application_id,
            'result': TokoScoreCriteriaConst.KEY_FDC_FETCH_PASS,
        }
    )

    return TokoScoreCriteriaConst.KEY_FDC_FETCH_NOT_FOUND


def fetch_heimdall_score(application_id):
    from juloserver.apiv2.models import PdCreditModelResult

    logger.info(
        {
            'message': 'Tokoscore: execute fetch Heimdall Score',
            'application': application_id,
        }
    )

    credit_model = PdCreditModelResult.objects.filter(application_id=application_id).last()
    score = credit_model.pgood if credit_model else None
    logger.info(
        {
            'message': 'Tokoscore: got result from credit model Heimdall',
            'application': application_id,
            'pgood_score': score,
        }
    )

    return score


def fetch_mycroft_score(application_id):
    from juloserver.ana_api.models import PdApplicationFraudModelResult

    logger.info(
        {
            'message': 'Tokoscore: execute fetch MyCroft Score',
            'application': application_id,
        }
    )

    mycroft = PdApplicationFraudModelResult.objects.filter(application_id=application_id).last()
    score = mycroft.pgood if mycroft else None

    logger.info(
        {
            'message': 'Tokoscore: got result from credit model Heimdall',
            'application': application_id,
            'pgood_score': score,
        }
    )
    return score
