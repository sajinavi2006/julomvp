import traceback
import phonenumbers
import json

from rest_framework.status import HTTP_200_OK

from juloserver.tokopedia.models import TokoScoreResult
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.models import (
    Application,
    ExperimentSetting,
)
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.tokopedia.services.clients import get_request_tokoscore
from juloserver.tokopedia.constants import (
    TokoScoreConst,
    TokoScoreCriteriaConst,
)
from juloserver.tokopedia.exceptions import (
    TokoScoreException,
    TokoScoreCreditMatrixException,
)
from juloserver.julo.services import process_application_status_change
from juloserver.application_flow.tasks import application_tag_tracking_task
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.tokopedia.services.match_criteria_service import process_match_criteria
from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagStatus,
)
from juloserver.application_flow.services import still_in_experiment
from juloserver.apiv2.models import SdDeviceApp

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def update_or_stored_response_to_table(
    init=True,
    application_id=None,
    toko_score_id=None,
    score_type=TokoScoreConst.REVIVE_SCORE_TYPE,
    response_data=None,
):
    # check this for init request
    if init:
        toko_score = TokoScoreResult.objects.create(
            application_id=application_id,
            score_type=score_type,
        )
        logger.info(
            {
                'message': 'creating data init for tokoscore by application',
                'application': application_id,
                'score_type': score_type,
            }
        )
        return toko_score.id

    # do update the process
    toko_score = TokoScoreResult.objects.filter(id=toko_score_id).last()
    if toko_score:
        toko_score.update_safely(**response_data)

    logger.info(
        {
            'message': 'success update tokoscore response',
            'application': application_id,
        }
    )

    return toko_score


def reformat_phone_number(mobile_phone_number):

    if not mobile_phone_number:
        return mobile_phone_number

    try:
        parse_phone_number = phonenumbers.parse(number=mobile_phone_number, region='ID')
    except phonenumbers.NumberParseException:
        customer_mobile_phone = mobile_phone_number.replace('+', '')
        parse_phone_number = phonenumbers.parse(number=customer_mobile_phone, region='ID')
    phone_number = phonenumbers.format_number(
        parse_phone_number, phonenumbers.PhoneNumberFormat.E164
    ).replace('+', '')

    return phone_number


def is_active_configuration(is_need_to_active=True, code=ExperimentConst.TOKO_SCORE_EXPERIMENT):
    """
    Configuration TokoScore is_active or not
    """

    configuration = ExperimentSetting.objects.filter(
        code=code,
    ).last()
    if not configuration:
        logger.info(
            {
                'message': 'Configuration is empty',
                'process_name': 'Configuration TokoScore',
                'experiment_code': code,
            }
        )
        return

    if not configuration.is_active and is_need_to_active:
        logger.info(
            {
                'message': 'Configuration return even is_need_to_active is True',
                'process_name': 'Configuration TokoScore',
                'experiment_code': code,
            }
        )
        return

    logger.info(
        {
            'message': 'Configuration return',
            'process_name': 'Configuration TokoScore',
            'experiment_code': code,
        }
    )

    return configuration


@sentry.capture_exceptions
def is_passed_tokoscore(application, is_available_fdc_check=None):
    """
    To check is passed or not from tokoscore
    """

    # allowed for application_id odd
    if application.status != ApplicationStatusCodes.FORM_PARTIAL:
        logger.info(
            {
                'message': 'Tokoscore: Application is not allowed',
                'application': application.id,
                'application_status_code': application.application_status_id,
            }
        )
        return False

    key_from_result = TokoScoreConst.KEY_NOT_PASSED
    configuration = is_active_configuration()
    if configuration is None:
        logger.warning(
            {
                'message': 'Configuration toko score is not active or empty',
                'application': application.id,
            }
        )
        return False

    # check range date for experiment
    is_in_range_experiment = still_in_experiment(
        experiment_type=ExperimentConst.TOKO_SCORE_EXPERIMENT,
        experiment=configuration,
    )
    if not is_in_range_experiment:
        logger.warning(
            {
                'message': 'Tokoscore: Non active - Experiment is expired',
                'application': application.id,
            }
        )
        return False

    # only allowed for user have tokopedia apps
    is_have_apps = is_have_tokopedia_apps(application.id)
    if not is_have_apps:
        return False

    # check total of application before running check tokoscore
    is_allowed_to_check = is_allowed_to_check_by_limit(application.id)
    if not is_allowed_to_check:
        logger.info(
            {
                'message': 'skip process check by tokoscore',
                'reason': 'out of limit',
                'application': application.id,
                'is_allowed_to_check_by_limit': is_allowed_to_check,
            }
        )
        return False

    is_passed_criteria_checking = is_passed_criteria(
        application,
        configuration,
        is_available_fdc_check=is_available_fdc_check,
    )
    if not is_passed_criteria_checking:
        set_path_tag_status_to_application(application, key_from_result)
        return False

    # Tokoscore service
    toko_score_data = get_score(application.id)

    # parse criteria
    criteria = configuration.criteria
    threshold = criteria.get(TokoScoreConst.KEY_THRESHOLD, None)
    require_match = criteria.get(TokoScoreConst.KEY_REQUIRE_MATCH, None)
    require_active = criteria.get(TokoScoreConst.KEY_REQUIRE_ACTIVE, None)

    is_passed_threshold = False
    is_require_match = determine_match_criteria(require_match, toko_score_data.score)
    is_require_active = True if toko_score_data.is_active else False

    # override if configuration is not active for that criteria
    if str(require_active).lower() == 'false':
        is_require_active = True

    if not toko_score_data or not toko_score_data.score:
        message_error = 'Invalid score value or tokoscore data'
        logger.error(
            {
                'message': message_error,
                'application': application.id,
                'process_name': 'Tokoscore checking',
            }
        )
        set_path_tag_status_to_application(application, key_from_result)
        return False

    # compare the threshold value
    try:
        score_source = int(float(toko_score_data.score))
        if score_source >= int(threshold):
            logger.info(
                {
                    'message': 'passed for score',
                    'threshold': threshold,
                    'score_data': toko_score_data.score,
                }
            )
            is_passed_threshold = True
    except ValueError as error:
        logger.error(
            {
                'message': str(error),
                'application': application.id,
                'process_name': 'Tokoscore checking',
            }
        )
        set_path_tag_status_to_application(application, key_from_result)
        raise TokoScoreException(str(error))

    if is_passed_threshold and is_require_active and is_require_match:
        key_from_result = TokoScoreConst.KEY_PASSED
        # increase total of passed
        current_total = increase_total_of_passed(application)
        logger.info(
            {
                'message': 'Tokoscore: success increasing total of passed',
                'current_total': current_total,
                'application': application.id,
            }
        )

    logger.info(
        {
            'message': 'Done determine from tokoscore data',
            'is_passed_threshold': is_passed_threshold,
            'is_require_match': is_require_match,
            'is_require_active': is_require_active,
            'key_from_result': key_from_result,
            'application': application.id,
        }
    )

    # set application path tag
    set_path_tag_status_to_application(application, key_from_result)

    return key_from_result


def set_path_tag_status_to_application(application, key):

    logger.info(
        {
            'message': 'Tokoscore: set path tag status as {}'.format(key),
            'application': application.id,
        }
    )

    result = 0
    if key == TokoScoreConst.KEY_PASSED:
        result = 1

    application_tag_tracking_task.delay(
        application.id,
        None,
        None,
        None,
        TokoScoreConst.TAG_NAME,
        result,
        traceback.format_stack(),
    )


def determine_match_criteria(require_match_config, value):

    if str(require_match_config).lower() == 'false':
        return True

    if value:
        return True

    return False


def is_passed_criteria(application: Application, configuration, is_available_fdc_check=None):
    """
    Use checking criteria by ShopeeWhitelist
    """

    logger.info(
        {
            'message': 'Execute criteria checking',
            'application': application.id,
            'process_name': 'Tokoscore checking',
        }
    )

    try:
        is_passed = process_match_criteria(
            application_id=application.id,
            configuration=configuration,
            is_available_fdc_check=is_available_fdc_check,
        )
        if is_passed:
            logger.info(
                {
                    'message': 'Have passed criteria',
                    'process_name': 'TokoScore checking criteria',
                    'application': application.id,
                    'result_criteria': str(is_passed),
                }
            )

            # set path tag for this application
            set_path_tag_criteria_to_application(application=application, criteria_passed=is_passed)

            return True

    except TokoScoreException as error:
        logger.error(
            {
                'message': 'Tokoscore: Execute check criteria by TokoScore Process',
                'application': application.id,
                'result': str(error),
            }
        )
        return False

    return False


@sentry.capture_exceptions
def get_score(application_id, score_type=TokoScoreConst.REVIVE_SCORE_TYPE):
    """
    Get score from tokoscore and stored it to table
    """

    from juloserver.pii_vault.services import detokenize_for_model_object
    from juloserver.pii_vault.constants import PiiSource

    logger.info(
        {
            'message': 'Tokoscore: Execute process from scoring tokoscore',
            'application': application_id,
            'process_name': 'TokoScore Checking',
        }
    )

    # get detail application data
    application = Application.objects.filter(pk=application_id).last()
    detokenized_application = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'object': application, "customer_id": application.customer_id}],
        force_get_local_data=True,
    )
    application = detokenized_application[0]

    if (
        not application.is_julo_one()
        or application.status in TokoScoreConst.NOT_ALLOWED_STATUSES_FOR_REQUESTS
    ):
        logger.info(
            {
                'message': 'Application denied in not allowed status or not J1 Application',
                'application': application_id,
                'process_name': 'TokoScore Checking',
            }
        )
        return

    # check if application already have data on table
    last_request = TokoScoreResult.objects.filter(application_id=application_id).last()
    if last_request:
        logger.info(
            {
                'message': '[Tokoscore] Return from last request',
                'application_id': application_id,
                'tokoscore_data_id': last_request.id,
            }
        )
        return last_request

    mobile_phone_number = application.mobile_phone_1
    email = application.email

    # create init data
    toko_score_id = update_or_stored_response_to_table(
        init=True,
        application_id=application_id,
        score_type=score_type,
    )

    # start call client tokoscore
    toko_score_client = get_request_tokoscore()
    response = toko_score_client.get_request_score(
        mobile_phone_number=mobile_phone_number,
        email=email,
    )

    response_json = response.json()
    data_stored = {
        'response_code': response.status_code if response else None,
        'latency': response_json.get('latency', None),
    }

    # init some data variable
    error_code = response_json
    is_match = False
    score = None
    is_active = None
    request_status = None
    message_id = None
    score_id = None
    response_time = None
    if response.status_code == HTTP_200_OK:
        logger.info(
            {
                'message': 'Raw response from Tokoscore',
                'application_id': application_id,
                'response': str(response_json),
            }
        )

        error_code = None
        data = response.json().get('data', None)
        request_status = TokoScoreConst.FLAG_REQUEST_IS_SUCCESS
        is_active = toko_score_client.determine_for_is_active_user(data.get('no_pg_dg', None))

        if not data:
            logger.error(
                {
                    'message': 'Response data is empty',
                    'application': application_id,
                    'process_name': 'TokoScore Checking',
                }
            )
            raise TokoScoreException('Response data is empty even success response')

        is_match = True
        score_encrypted = data.get('score', None)
        score = toko_score_client.do_decrypt(score_encrypted)
        message_id = data.get('message_id', None)
        score_id = data.get('score_id', None)
        response_time = data.get('response_timestamp', None)

    data_stored.update(
        {
            'error_code': error_code,
            'request_message_id': message_id,
            'request_score_id': score_id,
            'is_active': is_active,
            'response_time': response_time,
            'score': score,
            'is_match': is_match,
            'request_status': request_status,
        }
    )

    toko_score_data = update_or_stored_response_to_table(
        init=False,
        application_id=application_id,
        toko_score_id=toko_score_id,
        response_data=data_stored,
    )

    logger.info(
        {
            'message': 'success process scoring tokoscore',
            'application': application_id,
            'process_name': 'TokoScore Checking',
        }
    )

    return toko_score_data


def is_allowed_to_check_by_limit(application_id):

    configuration = is_active_configuration(is_need_to_active=False)
    if not configuration:
        logger.info({'message': 'configuration is not valid', 'application': application_id})
        return False

    logger.info(
        {
            'message': 'Tokoscore: init check limit and get init config',
            'action': str(configuration.action),
            'application': application_id,
        }
    )

    criteria = configuration.criteria
    action = configuration.action
    limit_of_application = criteria.get(TokoScoreConst.KEY_LIMIT_TOTAL_APP, None)
    if not limit_of_application:
        logger.info(
            {
                'message': 'Configuration limit of application is not valid',
                'application': application_id,
            }
        )
        return False

    total_of_passed = 0
    if action:
        action = json.loads(action)
        total_of_passed = action.get(TokoScoreConst.KEY_TOTAL_OF_PASSED, 0)

    if total_of_passed >= limit_of_application:
        logger.info(
            {
                'message': 'Configuration out of limit',
                'application': application_id,
                'total_of_passed': total_of_passed,
                'limit_set': limit_of_application,
            }
        )
        return False

    logger.info(
        {
            'message': 'Available limit to process check by tokoscore',
            'application': application_id,
            'total_of_passed': total_of_passed,
            'limit_set': limit_of_application,
        }
    )

    return True


def increase_total_of_passed(application):

    is_success = is_success_revive_by_tokoscore(application)
    if is_success:
        logger.info(
            {
                'message': 'Tokoscore: skip to increase',
                'is_success_revive': is_success,
                'application': application.id,
            }
        )
        return None

    configuration = is_active_configuration(is_need_to_active=False)
    logger.info(
        {
            'message': 'Tokoscore: init increase and get init config',
            'action': str(configuration.action),
        }
    )

    action = configuration.action
    total_of_passed = 0
    if action:
        action = json.loads(action)
        total_of_passed = action.get(TokoScoreConst.KEY_TOTAL_OF_PASSED, 0)
    current_total = total_of_passed + 1
    default_structure = {TokoScoreConst.KEY_TOTAL_OF_PASSED: current_total}
    structure_action = json.dumps(default_structure)

    logger.info(
        {
            'message': 'Tokoscore: increase total of passed',
            'action_data': str(action),
            'default_structure': str(default_structure),
            'structure_action': str(structure_action),
            'total_of_passed': total_of_passed,
            'current_total': current_total,
        }
    )

    if current_total != 0 and total_of_passed < current_total:
        logger.info(
            {
                'message': 'Tokoscore: accept condition to update counter',
                'current_total': current_total,
                'total_of_passed': total_of_passed,
                'application': application.id,
            }
        )
        configuration.update_safely(action=structure_action)

    return current_total


def get_application_path_tag_tokoscore(application, is_success=True):

    key_to_check = TokoScoreConst.IS_PASSED if is_success else TokoScoreConst.IS_NOT_PASSED
    statuses = ApplicationPathTagStatus.objects.filter(
        application_tag=TokoScoreConst.TAG_NAME, status=key_to_check
    )
    return ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=statuses
    ).exists()


def is_success_revive_by_tokoscore(application):

    result = get_application_path_tag_tokoscore(application)
    logger.info(
        {
            'message': 'is_success_revive_by_tokoscore',
            'application': application.id,
            'result': result,
        }
    )

    return result


def fetch_credit_matrix_and_move_application(
    application, key_for_passed, origin_credit_matrix, move_status=False
):
    """
    Fetch credit matrix and move application to x120
    We need make sure credit matrix should be match and sync with configuration tokoscore
    """

    from juloserver.tokopedia.services.credit_matrix_service import (
        fetch_credit_matrix_with_parameter,
    )

    if key_for_passed != TokoScoreConst.KEY_PASSED:
        logger.info(
            {
                'message': 'Tokoscore credit_matrix: '
                'Invalid case not passed but execute credit_matrix',
                'application': application.id,
                'key_for_passed': key_for_passed,
                'move_status': move_status,
            }
        )
        return None

    # will raise if any problem and stopped the process, so the application will not moved
    try:
        credit_matrix = fetch_credit_matrix_with_parameter(application)
    except TokoScoreCreditMatrixException:
        logger.error(
            {
                'message': 'Tokoscore: credit matrix is not match',
                'application': application.id,
                'action': 'return original credit matrix',
                'credit_matrix': str(origin_credit_matrix),
            }
        )
        return origin_credit_matrix

    if credit_matrix and move_status:
        logger.info(
            {
                'message': 'Tokoscore credit_matrix: Trigger to move application to x120',
                'change_reason': JuloOneChangeReason.REVIVE_BY_TOKOSCORE,
                'application': application.id,
                'move_status': move_status,
                'key_for_passed': key_for_passed,
            }
        )
        # move application to x120 status
        process_application_status_change(
            application_id=application.id,
            new_status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            change_reason=JuloOneChangeReason.REVIVE_BY_TOKOSCORE,
        )

    return credit_matrix


def is_have_tokopedia_apps(application_id):
    """
    function to check have Apps tokopedia or not
    """

    is_exist = SdDeviceApp.objects.filter(
        application_id=application_id,
        app_package_name=TokoScoreCriteriaConst.KEY_PACKAGE_NAME_TOKOPEDIA,
    ).exists()

    logger.info(
        {
            'message': 'Tokoscore: is have tokopedia application on device',
            'application': application_id,
            'result': is_exist,
        }
    )

    return is_exist


@sentry.capture_exceptions
def set_path_tag_criteria_to_application(application, criteria_passed):

    if not criteria_passed:
        logger.info(
            {
                'message': 'Tokoscore: invalid case when set path tag',
                'application': application.id,
                'criteria_passed': criteria_passed,
            }
        )
        return False

    logger.info(
        {
            'message': 'Tokoscore: set path tag criteria',
            'application': application.id,
            'criteria_passed': criteria_passed,
        }
    )

    tag_name = None
    criteria_list = TokoScoreCriteriaConst.CRITERIA_TAG_NAME
    for criteria in criteria_list:
        if criteria == criteria_passed:
            tag_name = criteria_list[criteria_passed]

    if not tag_name:
        logger.error(
            {
                'message': 'Tokoscore: not match when set path tag',
                'application': application.id,
                'criteria_passed': criteria_passed,
            }
        )
        raise TokoScoreException('Tokoscore: Not match path tag between criteria')

    logger.info(
        {
            'message': 'Tokoscore: trigger set path tag criteria',
            'application': application.id,
            'criteria_passed': criteria_passed,
            'tag_name': tag_name,
        }
    )

    application_tag_tracking_task.delay(
        application.id,
        None,
        None,
        None,
        tag_name,
        TokoScoreCriteriaConst.IS_PASSED_CRITERIA,
        traceback.format_stack(),
    )

    return tag_name


def get_and_stored_toko_score_data(application, score_type):
    """
    Get and stored data tokoscore
    """

    # Tokoscore service called
    toko_score_data = get_score(application.id, score_type)

    return toko_score_data


@sentry.capture_exceptions
def run_shadow_score_with_toko_score(application_id):
    """
    Run shadow score when application is J1 and x190
    """

    logger.info(
        {
            'message': 'Tokoscore: execute run_shadow_score',
            'application': application_id,
        }
    )

    application = Application.objects.filter(pk=application_id).last()
    if (
        not application.is_julo_one()
        or application.application_status_id != ApplicationStatusCodes.LOC_APPROVED
    ):
        logger.info(
            {
                'message': 'Tokoscore: Invalid case shadow score not J1 app and Not in x190',
                'application': application_id,
            }
        )
        return False

    if is_success_revive_by_tokoscore(application):
        logger.info(
            {
                'message': 'Tokoscore: Skip process because already success revive process',
                'application': application_id,
            }
        )
        return False

    # only allowed for user have tokopedia apps
    is_have_apps = is_have_tokopedia_apps(application.id)
    if not is_have_apps:
        logger.info(
            {
                'message': 'Tokoscore: empty record in sd_device_app',
                'application': application_id,
            }
        )
        return False

    # tokoscore called
    try:
        toko_score_result = get_and_stored_toko_score_data(
            application=application,
            score_type=TokoScoreConst.SHADOW_SCORE_TYPE,
        )
    except Exception as error:
        logger.info(
            {
                'message': 'Tokoscore: failed to shadow score',
                'application_id': application_id,
            }
        )
        raise TokoScoreException(str(error))

    logger.info(
        {
            'message': 'Tokoscore: called shadow score process in x190 J1',
            'application_id': application_id,
            'toko_score_result_id': toko_score_result.id if toko_score_result else None,
        }
    )

    return True


def is_allowed_to_run_shadow_score():

    configuration = is_active_configuration(
        is_need_to_active=True,
        code=ExperimentConst.SHADOW_SCORE_EXPERIMENT,
    )

    if configuration:
        return still_in_experiment(
            experiment_type=ExperimentConst.SHADOW_SCORE_EXPERIMENT,
            experiment=configuration,
        )

    return False
