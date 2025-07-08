import operator
import time
from functools import wraps
from math import ceil

from dateutil.relativedelta import relativedelta
from django.conf import settings as dj_settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from juloserver.ana_api.models import PdApplicationFraudModelResult
from juloserver.antifraud.client import get_anti_fraud_http_client
from juloserver.antifraud.constant.binary_checks import BinaryCheckType, StatusEnum
from juloserver.antifraud.constant.transport import Path
from juloserver.application_flow.constants import CacheKey
from juloserver.application_flow.services import (
    ApplicationTagTracking,
    increment_counter,
)
from juloserver.application_form.constants import ApplicationUpgradeConst
from juloserver.customer_module.services.customer_related import (
    master_agreement_created,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst, OnboardingIdConst
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    ApplicationUpgrade,
    Customer,
    FeatureSetting,
    OnboardingEligibilityChecking,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import post_anaserver
from juloserver.julo_starter.constants import (
    JuloStarterFieldExtraForm,
    JuloStarterFlow,
    JuloStarterFormExtraResponseCode,
    JuloStarterFormExtraResponseMessage,
    JuloStarterSecondCheckConsts,
    JuloStarterSecondCheckResponseCode,
    NotificationSetJStarter,
)
from juloserver.julo_starter.exceptions import JuloStarterException
from juloserver.julo_starter.serializers.application_serializer import (
    ApplicationExtraFormSerializer,
)
from juloserver.julo_starter.services.submission_process import check_affordability
from juloserver.julo_starter.tasks.app_tasks import trigger_push_notif_check_scoring
from juloserver.julolog.julolog import JuloLog
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_jstarter_limit_approved,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()
anti_fraud_http_client = get_anti_fraud_http_client()


def determine_js_workflow(application: Application):
    """
    No need to detokenize application here, because is only check the relationship.
    Do more detokenization if used PII attribute!
    """

    application_history = (
        ApplicationHistory.objects.filter(application=application)
        .filter(
            Q(status_old=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)
            | Q(status_new=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)
        )
        .first()
    )
    if application_history:
        return JuloStarterFlow.PARTIAL_LIMIT

    return JuloStarterFlow.FULL_DV


def submit_form_extra(user, application_id, data, need_update_application=True):
    application = Application.objects.get_or_none(id=application_id)

    if not application or not application.is_julo_starter():
        return (
            JuloStarterFormExtraResponseCode.APPLICATION_NOT_FOUND,
            JuloStarterFormExtraResponseMessage.APPLICATION_NOT_FOUND,
        )

    if user.id != application.customer.user.id:
        return (
            JuloStarterFormExtraResponseCode.USER_NOT_ALLOW,
            JuloStarterFormExtraResponseMessage.USER_NOT_ALLOW,
        )

    all_phone_numbers = ("spouse_mobile_phone", "close_kin_mobile_phone", "kin_mobile_phone")

    # Detokenize because it used mobile_phone_1
    detokenized_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'object': application, "customer_id": application.customer_id}],
        force_get_local_data=True,
    )
    application = detokenized_applications[0]

    if application.mobile_phone_1:
        for phone in all_phone_numbers:
            if data.get(phone) == application.mobile_phone_1:
                return (
                    JuloStarterFormExtraResponseCode.DUPLICATE_PHONE,
                    JuloStarterFormExtraResponseMessage.DUPLICATE_PHONE,
                )

    jstarter_workflow = determine_js_workflow(application)
    if (
        jstarter_workflow == JuloStarterFlow.PARTIAL_LIMIT
        and application.status != ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
    ) or (
        jstarter_workflow == JuloStarterFlow.FULL_DV
        and application.status != ApplicationStatusCodes.LOC_APPROVED
    ):
        return (
            JuloStarterFormExtraResponseCode.APPLICATION_NOT_ALLOW,
            JuloStarterFormExtraResponseMessage.APPLICATION_NOT_ALLOW,
        )

    ma_setting_active = FeatureSetting.objects.get_or_none(
        is_active=True,
        feature_name="master_agreement_setting",
    )
    if ma_setting_active:
        has_sign_ma = application.has_master_agreement()
        if has_sign_ma:
            return JuloStarterFormExtraResponseCode.FAILED, 'Master Agreement already signed'

        master_agreement = master_agreement_created(application_id)

        if not master_agreement:
            return JuloStarterFormExtraResponseCode.FAILED, 'Failed Create Master Agreement'

    application_path_tag = None
    if 'application_path_tag' in data:
        application_path_tag = data.pop('application_path_tag')

    # submit extra form
    if need_update_application:
        application.update_safely(**data, refresh=False)

    if application_path_tag:
        tag_tracer = ApplicationTagTracking(application=application)
        tag_tracer.adding_application_path_tag(application_path_tag, 0)

    # trigger binary check
    binary_check_form_extra(application_id)

    if jstarter_workflow == JuloStarterFlow.FULL_DV:
        send_user_attributes_to_moengage_for_jstarter_limit_approved.delay(
            application.id, JuloStarterFlow.FULL_DV
        )

    return JuloStarterFormExtraResponseCode.SUCCESS, JuloStarterFormExtraResponseMessage.SUCCESS


@sentry.capture_exceptions
def second_check_status(user, application_id):
    with transaction.atomic():

        # No need to detokenize application here,
        # because is only check the relationship and use `id`, status, onboarding_id, customer_id.
        # Do more detokenization if used PII attribute!
        application = Application.objects.select_for_update().filter(pk=application_id).last()

        if not application or not application.is_julo_starter():
            return (
                JuloStarterSecondCheckResponseCode.APPLICATION_NOT_FOUND,
                'Application not found',
            )
        if user.id != application.customer.user.id:
            return (
                JuloStarterSecondCheckResponseCode.USER_NOT_ALLOWED,
                'User is not allowed',
            )

        if application.status in JuloStarterSecondCheckConsts.NOT_YET_STATUSES:
            return (
                JuloStarterSecondCheckResponseCode.NOT_YET_SECOND_CHECK,
                JuloStarterSecondCheckConsts.KEY_NOT_YET,
            )

        elif application.status in JuloStarterSecondCheckConsts.ON_PROGRESS_STATUSES:
            if application.status == ApplicationStatusCodes.FORM_PARTIAL and check_affordability(
                application
            ):
                if application.onboarding_id == OnboardingIdConst.JULO_360_TURBO_ID:
                    # check the fdc still in progress
                    on_check = OnboardingEligibilityChecking.objects.filter(
                        customer_id=application.customer_id
                    ).last()
                    if on_check and not on_check.fdc_inquiry:
                        return (
                            JuloStarterSecondCheckResponseCode.ON_SECOND_CHECK,
                            JuloStarterSecondCheckConsts.KEY_ON_PROGRESS,
                        )

                return (
                    JuloStarterSecondCheckResponseCode.ON_SECOND_CHECK,
                    JuloStarterSecondCheckConsts.KEY_SPHINX_PASSED,
                )

            return (
                JuloStarterSecondCheckResponseCode.ON_SECOND_CHECK,
                JuloStarterSecondCheckConsts.KEY_ON_PROGRESS,
            )

        elif application.status in JuloStarterSecondCheckConsts.REJECTED_STATUSES:
            return (
                JuloStarterSecondCheckResponseCode.DUKCAPIL_FAILED,
                JuloStarterSecondCheckConsts.KEY_NOT_PASSED,
            )

        elif user_have_history_affordability(application):
            from juloserver.julo_starter.services.flow_dv_check import (
                is_active_full_dv,
                is_active_partial_limit,
            )

            if is_active_partial_limit():
                return (
                    JuloStarterSecondCheckResponseCode.FINISHED_SECOND_CHECK,
                    JuloStarterSecondCheckConsts.KEY_FINISHED,  # Finished partial limit
                )
            elif is_active_full_dv():
                return (
                    JuloStarterSecondCheckResponseCode.FINISHED_SECOND_CHECK,
                    JuloStarterSecondCheckConsts.KEY_FINISHED_FULL_DV,
                )
            else:
                error_message = (
                    "Application {} has affordability but has no Turbo flow matched.".format(
                        application.id
                    )
                )
                logger.error(
                    {
                        "message": error_message,
                        "status": application.status,
                        "application": application.id,
                    }
                )
                raise JuloStarterException(error_message)

        elif application.status == ApplicationStatusCodes.OFFER_REGULAR:
            return (
                JuloStarterSecondCheckResponseCode.HEIMDALL_FAILED,
                JuloStarterSecondCheckConsts.KEY_OFFER_REGULAR,
            )

        else:
            error_message = "Not match for application status {}".format(application.status)
            logger.error(
                {
                    "message": error_message,
                    "status": application.status,
                    "application": application.id,
                }
            )
            raise JuloStarterException(error_message)


def binary_check_form_extra(application_id):
    """
    Binary Check #2
    """

    url = '/api/amp/v1/julo-turbo-part2/'
    post_anaserver(url, json={'application_id': application_id})


def user_have_history_affordability(application: Application):
    """
    To check user have application history for affordability
    status_old = 108

    No need to detokenize application here, because is only check the relationship.
    Do more detokenization if used PII attribute!
    """

    have_history_check = ApplicationHistory.objects.filter(
        application=application, status_old=ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
    ).first()

    if not have_history_check:
        return False

    return True


def user_have_upgrade_application(customer: Customer, return_instance=False):
    """
    This function to check customer have application upgrade
    from JTurbo to J1
    """

    from juloserver.application_form.services.application_service import (
        get_main_application_after_submit_form,
    )

    list_applications = customer.application_set.regular_not_deletes().order_by('-cdate')
    # case if not have application
    if not list_applications:
        return None, None

    ids_check = [app.id for app in list_applications]
    application_upgrade = ApplicationUpgrade.objects.filter(
        application_id__in=ids_check,
        is_upgrade=1,
    )

    if return_instance:
        app_upgrade_result = application_upgrade.last()
    else:
        app_upgrade_result = application_upgrade.exists()

    # get the application after submit the form
    temp_main_app = get_main_application_after_submit_form(customer)
    if temp_main_app:
        for app in temp_main_app:
            if app.id in ids_check:
                return temp_main_app, app_upgrade_result

    return list_applications, app_upgrade_result


def determine_application_for_credit_info(customer: Customer):
    from juloserver.application_form.services.application_service import (
        determine_active_application,
    )

    list_applications, application_upgrade = user_have_upgrade_application(customer, True)

    # case if not have applications
    if not list_applications:
        return None

    # not have case upgrade
    if not application_upgrade:
        # check for x100 case
        return determine_active_application(
            customer,
            list_applications.first(),
        )

    # Have case upgrade!
    # No need to detokenize application here,
    # because it only uses `application_status_id`.
    # Do more detokenization if used PII attribute!
    application_j1 = Application.objects.filter(pk=application_upgrade.application_id).last()

    # check application J1 already approve or not
    if application_j1.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        return application_j1

    # return application JTurbo as main application
    # No need to detokenize application here,
    # Do more detokenization if used PII attribute!
    return Application.objects.filter(pk=application_upgrade.application_id_first_approval).last()


def get_mock_feature_setting(feature_name, product):
    if dj_settings.ENVIRONMENT != 'prod':
        setting = FeatureSetting.objects.filter(feature_name=feature_name, is_active=True).last()
        if setting and setting.parameters and setting.parameters.get('product'):
            if product not in setting.parameters.get('product'):
                return

            return setting.parameters


def return_with_delay(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        time.sleep(args[0].get('latency') / 1000)
        return function(*args, **kwargs)

    return wrapper


@return_with_delay
def mock_app_risky_response(setting):
    return setting['response_value'], 'Found application risky'


@return_with_delay
def mock_binary_check_response(setting):
    return setting['response_value']


@return_with_delay
def mock_emulator_detection_response(setting):
    return setting['response_value']['decoded_response'], setting['response_value']['decode_error']


def is_customer_have_pgood(application: Application):
    """
    # No need to detokenize application here, because is only use the id.
    # Do more detokenization if used PII attribute!
    """

    from juloserver.apiv2.models import PdCreditModelResult
    from juloserver.julo_starter.services.credit_limit import check_is_good_score

    if not application:
        return False

    credit_model = PdCreditModelResult.objects.filter(application_id=application.id).last()
    if credit_model is None:
        return False

    return check_is_good_score(application, credit_model)


@sentry.capture_exceptions
def determine_eligibility_by_pgood(application: Application, setting):
    """
    Determine by pgood to check use flow middle and high threshold or not
    This configuration setting by Feature Settings

    From card: https://juloprojects.atlassian.net/browse/RUS1-2849
    This function is moved at the end of x105,
    so emulator check will be replaced with move to x108

    No need to detokenize application here, because is only use the id.
    and pass to another function.
    Do more detokenization if used PII attribute!
    """

    if not setting:
        process_offer_to_j1(application, 'sphinx_no_bpjs_threshold not active')
        return

    from juloserver.apiv2.models import PdCreditModelResult
    from juloserver.julo_starter.constants import BpjsHoldoutConst
    from juloserver.julo_starter.services.onboarding_check import (
        get_threshold_attributes_no_bpjs,
    )

    bpjs_holdout_log = {
        BpjsHoldoutConst.KEY_COUNTER: None,
        BpjsHoldoutConst.KEY_PROCEED: None,
    }

    # get pgood
    credit_model = PdCreditModelResult.objects.filter(application_id=application.id).last()
    if not credit_model:
        logger.warning({'message': 'Credit model is empty', 'application': application.id})
        return

    pgood = credit_model.pgood
    operators = {
        ">=": operator.ge,
        ">": operator.gt,
    }

    hs_threshold, hs_operator = get_threshold_attributes_no_bpjs(setting=setting)
    if not hs_threshold and not hs_operator:
        return

    if operators[hs_operator](pgood, hs_threshold):
        # move to 108
        logger.info(
            {
                "application_id": application.id,
                "action": "move to 108 with reason sphinx_threshold_passed",
                "function": "determine_eligibility_by_pgood",
                "condition": "not is_emulator",
                "current_status": application.status,
            }
        )
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
            'sphinx_threshold_passed',
        )
        return 'success'

    ms_threshold, ms_operator = get_threshold_attributes_no_bpjs(
        high_threshold=False,
        setting=setting,
    )

    reason_move_status = 'medium_threshold'
    if operators[ms_operator](pgood, ms_threshold):
        # logic Holdout 50% in here
        try:
            limit_binary_counter = get_value_for_holdout(setting)
            if limit_binary_counter:
                current_counter = increment_counter(
                    redis_key=CacheKey.BPJS_NO_FOUND_HOLDOUT_COUNTER,
                    default_counter=1,
                    limit_counter=10,
                )

                reason_move_status = 'holdout_offer_to_j1'
                bpjs_holdout_log[BpjsHoldoutConst.KEY_COUNTER] = int(current_counter)

                if int(current_counter) <= int(limit_binary_counter):
                    # move to 108
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
                        'sphinx_threshold_passed',
                    )
                    return 'success'
                else:
                    bpjs_holdout_log[BpjsHoldoutConst.KEY_PROCEED] = 'offer_to_j1'
                    record_bpjs_holdout_log(application, bpjs_holdout_log)

        except ValueError as error:
            raise JuloStarterException(str(error))

    logger.info(
        {
            'message': 'offering to j1',
            'reason': reason_move_status,
            'application': application.id,
        }
    )
    print('this from after holdout')
    # moving application to x107 and trigger_push_notif_check_scoring
    process_offer_to_j1(application, reason_move_status)

    return 'success'


def process_offer_to_j1(application: Application, offer_regular_reason):
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """

    logger.info(
        {
            'message': 'Moving application to {}'.format(ApplicationStatusCodes.OFFER_REGULAR),
            'application': application.id,
            'change_reason': offer_regular_reason,
        }
    )

    process_application_status_change(
        application,
        ApplicationStatusCodes.OFFER_REGULAR,
        change_reason=offer_regular_reason,
    )

    template_code_for_notif = NotificationSetJStarter.KEY_MESSAGE_OFFER
    print('before trigger push notif')
    # Call task notif to customer
    trigger_push_notif_check_scoring.delay(application.id, template_code_for_notif)


def get_value_for_holdout(setting):
    from juloserver.julo_starter.services.onboarding_check import (
        get_threshold_attributes_no_bpjs,
    )

    # this percentage for proceed to binary check
    holdout = get_threshold_attributes_no_bpjs(setting=setting, return_holdout=True)
    if not holdout:
        logger.warning(
            {
                'message': 'holdout is not running',
                'holdout_value': str(holdout),
            }
        )
        return

    return round(holdout / 10)


def record_bpjs_holdout_log(application: Application, bpjs_holdout_log):
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """

    # stored log holdout
    eligibility_data = OnboardingEligibilityChecking.objects.filter(application=application).last()

    if eligibility_data:
        eligibility_data.update_safely(bpjs_holdout_log=bpjs_holdout_log)


def check_is_j1_upgraded(application: Application):
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """

    if application.is_julo_one_product():
        if ApplicationUpgrade.objects.filter(
            application_id=application.id, is_upgrade=ApplicationUpgradeConst.MARK_UPGRADED
        ).exists():
            return True

    return False


def is_eligible_bypass_to_x121(application_id):
    """
    This function to bypass from x109 to x121
    if condition data are completed in extra form.
    """

    allowed_for_status = ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED

    # No need to detokenize application here,
    # because is only check the relationship and use `application_status_id`.
    # Do more detokenization if used PII attribute!
    application = Application.objects.filter(pk=application_id).last()

    logger.info(
        {
            'message': 'Execute for bypass application to x121',
            'application': application_id,
            'current_status': application.application_status_id,
        }
    )

    if application.status != allowed_for_status or not application.is_julo_starter():
        logger.warning(
            {
                'message': 'Application not allowed',
                'application': application_id,
                'application_status_code': application.application_status_id,
            }
        )
        return False

    # get the data from db
    source_data_application = Application.objects.filter(pk=application_id).last()

    # Detokenize because it used mobile phones
    detokenized_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'object': source_data_application, "customer_id": source_data_application.customer_id}],
        force_get_local_data=True,
    )
    source_data_application = detokenized_applications[0]
    data = {}

    for field in JuloStarterFieldExtraForm.FIELDS:
        data[field] = getattr(source_data_application, field)

    # validate by serializer
    serializer = ApplicationExtraFormSerializer(data=data)
    if not serializer.is_valid():
        logger.warning(
            {
                'message': 'Failed to bypass serializers error',
                'application': application_id,
                'serializer': str(serializer.errors),
            }
        )
        return False

    # try to check same flow or process when submit extra form
    validated_data = serializer.validated_data
    try:
        user = application.customer.user
        code, message = submit_form_extra(
            user=user,
            application_id=application_id,
            data=validated_data,
            need_update_application=False,
        )
    except Exception as error:
        logger.error({'message': str(error), 'application': application_id})
        return False

    if code == JuloStarterFormExtraResponseCode.SUCCESS:
        logger.info(
            {
                'message': 'Bypass is success and execute Binary Checking #2 Form',
                'application': application_id,
            }
        )
        return True

    logger.info({'message': 'failure to bypass {}'.format(message), 'application': application_id})
    return False


def process_dukcapil_fr_turbo(application: Application):
    from juloserver.account.constants import AccountConstant
    from juloserver.account.services.account_related import (
        process_change_account_status,
    )
    from juloserver.personal_data_verification.services import (
        dukcapil_fr_turbo_threshold,
        get_dukcapil_fr_setting,
    )
    from juloserver.personal_data_verification.tasks import face_recogniton

    # Detokenize because it used ktp
    detokenized_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'object': application, 'customer_id': application.customer_id}],
        force_get_local_data=True,
    )
    application = detokenized_applications[0]

    dukcapil_fr_setting = get_dukcapil_fr_setting()

    if dukcapil_fr_setting and dukcapil_fr_setting.is_active:
        is_turbo = dukcapil_fr_setting.parameters['turbo']

        if is_turbo and is_turbo['is_active']:
            face_recogniton(application.id, application.ktp)
            threshold = dukcapil_fr_turbo_threshold(application.id)
            account = application.account

            if threshold == 'very_high':
                process_change_account_status(
                    account,
                    AccountConstant.STATUS_CODE.deactivated,
                    change_reason='rejected by Dukcapil FR too high',
                )
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.LOC_APPROVED,
                    'rejected by Dukcapil FR too high',
                )
                return False
            elif threshold == 'high':
                check_face_similarity_result_with_x121_jturbo_threshold(application)
            elif threshold == 'medium':
                process_change_account_status(
                    account,
                    AccountConstant.STATUS_CODE.inactive,
                    change_reason='accepted by Dukcapil FR Medium',
                )
            elif threshold == 'low':
                process_change_account_status(
                    account,
                    AccountConstant.STATUS_CODE.deactivated,
                    change_reason='rejected by Dukcapil FR too low',
                )
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.LOC_APPROVED,
                    'rejected by Dukcapil FR too low',
                )
                return False
            elif threshold == 'zero':
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.OFFER_REGULAR,
                    'reject_from_dukcapil_face_recognition',
                )
                process_change_account_status(
                    account,
                    AccountConstant.STATUS_CODE.inactive,
                    change_reason='dukcapil FR got matchScore = 0',
                )
                return False

    return True


def check_face_similarity_jturbo(application: Application, threshold: float) -> bool:
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """

    from juloserver.face_recognition.constants import FaceSearchProcessConst
    from juloserver.face_recognition.models import FaceSearchProcess, FaceSearchResult

    is_face_trusted = False
    face_search_process = FaceSearchProcess.objects.filter(application=application).last()
    if face_search_process:
        if face_search_process.status == FaceSearchProcessConst.NOT_FOUND:
            is_face_trusted = True
        else:
            face_search_result = FaceSearchResult.objects.filter(
                similarity__lt=threshold,
                face_search_process=face_search_process,
            ).exists()

            if face_search_result:
                is_face_trusted = True

    logger.info(
        {
            "action": "face checking jturbo",
            "function": "check_face_similarity_jturbo",
            "application_id": application.id,
            "is_face_trusted": is_face_trusted,
        }
    )
    return is_face_trusted


def check_fraud_face_similarity_jturbo(application: Application, threshold: float) -> bool:
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """
    from juloserver.face_recognition.constants import FraudFaceSearchProcessConst
    from juloserver.face_recognition.models import (
        FraudFaceSearchProcess,
        FraudFaceSearchResult,
    )

    is_face_trusted = False
    fraud_face_search_process = FraudFaceSearchProcess.objects.filter(
        application=application
    ).last()
    if fraud_face_search_process:
        if fraud_face_search_process.status == FraudFaceSearchProcessConst.NOT_FOUND:
            is_face_trusted = True
        else:
            fraud_face_search_result = FraudFaceSearchResult.objects.filter(
                similarity__lt=threshold,
                face_search_process=fraud_face_search_process,
            ).exists()

            if fraud_face_search_result:
                is_face_trusted = True

    logger.info(
        {
            "action": "face checking jturbo",
            "function": "check_fraud_face_similarity_jturbo",
            "application_id": application.id,
            "is_face_trusted": is_face_trusted,
        }
    )
    return is_face_trusted


def check_selfie_x_ktp_similarity_jturbo(application: Application, threshold: float) -> bool:
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """

    from juloserver.face_recognition.constants import FaceMatchingCheckConst
    from juloserver.face_recognition.models import FaceMatchingCheck

    is_face_trusted = False
    face_matching = FaceMatchingCheck.objects.filter(
        application=application,
        process=FaceMatchingCheckConst.Process.selfie_x_ktp.value,
        metadata__isnull=False,
    ).last()
    similarity_score = face_matching.metadata.get('similarity_score') if face_matching else None
    if similarity_score and similarity_score >= threshold:
        is_face_trusted = True

    logger.info(
        {
            "action": "face checking jturbo",
            "function": "check_selfie_x_ktp_similarity_jturbo",
            "application_id": application.id,
            "is_face_trusted": is_face_trusted,
        }
    )
    return is_face_trusted


def check_selfie_x_liveness_similarity_jturbo(application: Application, threshold: float) -> bool:
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """
    from juloserver.face_recognition.constants import FaceMatchingCheckConst
    from juloserver.face_recognition.models import FaceMatchingCheck

    is_face_trusted = False
    face_matching = FaceMatchingCheck.objects.filter(
        application=application,
        process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
        metadata__isnull=False,
    ).last()
    similarity_score = face_matching.metadata.get('similarity_score') if face_matching else None
    if similarity_score and similarity_score >= threshold:
        is_face_trusted = True

    logger.info(
        {
            "action": "face checking jturbo",
            "function": "check_selfie_x_liveness_similarity_jturbo",
            "application_id": application.id,
            "is_face_trusted": is_face_trusted,
        }
    )
    return is_face_trusted


def verify_face_checks_and_update_status_jturbo(application: Application):
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """

    from juloserver.account.constants import AccountConstant
    from juloserver.account.services.account_related import (
        process_change_account_status,
    )

    # List functions to be performed sequentially
    face_checks_list = []

    face_similarity_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FACE_SIMILARITY_THRESHOLD_JTURBO, is_active=True
    )
    similar_face_threshold = 'similar_face_threshold'
    fraud_face_threshold = 'fraud_face_threshold'
    if face_similarity_fs and similar_face_threshold in face_similarity_fs.parameters:
        face_similarity_check = (
            check_face_similarity_jturbo,
            face_similarity_fs.parameters[similar_face_threshold],
            'face similarity',
        )
        face_checks_list.append(face_similarity_check)
    if face_similarity_fs and fraud_face_threshold in face_similarity_fs.parameters:
        fraud_face_similarity_check = (
            check_fraud_face_similarity_jturbo,
            face_similarity_fs.parameters[fraud_face_threshold],
            'fraud face similarity',
        )
        face_checks_list.append(fraud_face_similarity_check)

    face_matching_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FACE_MATCHING_SIMILARITY_THRESHOLD_JTURBO,
        is_active=True
    )
    selfie_x_ktp_threshold = 'selfie_x_ktp_threshold'
    selfie_x_liveness_threshold = 'selfie_x_liveness_threshold'
    delay = 'delay'
    delay_time = 0
    if face_matching_fs and delay in face_matching_fs.parameters:
        delay_time = face_matching_fs.parameters[delay]
        logger.info(
            {
                "action": "face checking jturbo",
                "function": "verify_face_checks_and_update_status_jturbo",
                "application_id": application.id,
                "message": "checking will delay for {} second".format(delay_time),
            }
        )
        # Waiting for data face matching stored
        time.sleep(delay_time)

    if face_matching_fs and selfie_x_ktp_threshold in face_matching_fs.parameters:
        selfie_x_ktp_check = (
            check_selfie_x_ktp_similarity_jturbo,
            face_matching_fs.parameters[selfie_x_ktp_threshold],
            'selfie x ktp',
        )
        face_checks_list.append(selfie_x_ktp_check)
    if face_matching_fs and selfie_x_liveness_threshold in face_matching_fs.parameters:
        selfie_x_liveness = (
            check_selfie_x_liveness_similarity_jturbo,
            face_matching_fs.parameters[selfie_x_liveness_threshold],
            'selfie x liveness',
        )
        face_checks_list.append(selfie_x_liveness)

    account = application.account

    if not face_checks_list:
        logger.info(
            {
                "action": "face checking jturbo",
                "function": "verify_face_checks_and_update_status_jturbo",
                "application_id": application.id,
                "message": "checking pass due to all feature setting off",
            }
        )
        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.active,
            change_reason='accepted by Dukcapil FR High',
        )
        return

    # Iterate through each check function in the list
    for face_check_function, threshold, name_check in face_checks_list:
        # Call the face check function with application & threshold parameter
        # If the check returns False, exit the function early
        is_face_trusted = face_check_function(application, threshold)
        if not is_face_trusted:
            process_change_account_status(
                account,
                AccountConstant.STATUS_CODE.inactive,
                change_reason='rejected by {} x121 JTurbo'.format(name_check),
            )
            return

    logger.info(
        {
            "action": "face checking jturbo",
            "function": "verify_face_checks_and_update_status_jturbo",
            "application_id": application.id,
            "message": "checking pass due to all checks pass",
        }
    )
    # If all checks pass/no check returned False, update account status to x420
    process_change_account_status(
        account,
        AccountConstant.STATUS_CODE.active,
        change_reason='accepted by Dukcapil FR High',
    )


def check_face_similarity_result_with_x121_jturbo_threshold(application: Application):
    """
    # No need to detokenize application here, because is only use the id & relationship.
    # Do more detokenization if used PII attribute!
    """

    from juloserver.account.services.account_related import process_change_account_status
    from juloserver.account.constants import AccountConstant

    try:
        verify_face_checks_and_update_status_jturbo(application)
    except Exception as e:
        sentry.captureException()
        logger.error(
            {
                "action": "face checking jturbo",
                "function": "check_face_similarity_result_with_x121_jturbo_threshold",
                "application_id": application.id,
                "message": "checking pass due to exception",
                "error": str(e),
            }
        )
        account = application.account
        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.active,
            change_reason='accepted by Dukcapil FR High',
        )


def is_last_application_shortform(customer: Customer):

    # No need to detokenize because has no pii fields used.
    application = customer.application_set.regular_not_deletes().last()
    if not application:
        return False

    return True if application.onboarding_id == OnboardingIdConst.SHORTFORM_ID else False


def has_good_score_mycroft_turbo(application: Application):
    """
    No need to detokenize application here, because is only use the id.
    Do more detokenization if used PII attribute!
    """
    mycroft_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MYCROFT_TURBO_THRESHOLD, is_active=True
    ).last()

    if not mycroft_setting:
        return True

    mycroft_score_ana = PdApplicationFraudModelResult.objects.filter(
        application_id=application.id
    ).last()
    mycroft_score = None
    if mycroft_score_ana:
        mycroft_score = ceil(mycroft_score_ana.pgood * 100) / 100

    if mycroft_score:
        if mycroft_score >= mycroft_setting.parameters['threshold']:
            return True

    return False


def process_anti_fraud_api_turbo(application, retry: int = 0):

    if retry == 3:
        return (
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            'anti_fraud_api_unavailable',
        )

    antifraud_api_onboarding_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.ANTIFRAUD_API_ONBOARDING,
        is_active=True,
    )

    if not antifraud_api_onboarding_fs or not antifraud_api_onboarding_fs.parameters.get(
        'turbo_109', False
    ):
        logger.info(
            {
                "action": "process_anti_fraud_api_turbo",
                "message": "feature setting for antifraud is not active",
                "application_id": application.id,
            },
        )
        return ApplicationStatusCodes.SCRAPED_DATA_VERIFIED, 'Julo Starter Verified'

    params = {
        "status": application.status,
        "type": BinaryCheckType.APPLICATION,
        "application_id": application.id,
    }

    try:
        response = anti_fraud_http_client.get(
            path=Path.ANTI_FRAUD_BINARY_CHECK,
            params=params,
        )
    except Exception as e:
        logger.error(
            {
                "action": "process_anti_fraud_api_turbo",
                "error": e,
            }
        )
        sentry.captureException()
        return process_anti_fraud_api_turbo(application, retry=retry + 1)

    try:
        binary_check_status = StatusEnum(response.json().get("data", {}).get("status", None))
    except Exception as e:
        logger.error(
            {
                "action": "process_anti_fraud_api_turbo",
                "error": e,
                "response": response,
            }
        )
        sentry.captureException()
        return ApplicationStatusCodes.SCRAPED_DATA_VERIFIED, 'Prompted by the Anti Fraud API'

    logger.info(
        {
            "action": "process_anti_fraud_api_turbo",
            "application_id": application.id,
            "binary_check_status": binary_check_status,
        }
    )

    if binary_check_status is None or binary_check_status in (
        StatusEnum.ERROR,
        StatusEnum.BYPASSED_HOLDOUT,
        StatusEnum.DO_NOTHING,
    ):
        return ApplicationStatusCodes.SCRAPED_DATA_VERIFIED, 'Prompted by the Anti Fraud API'

    if binary_check_status == StatusEnum.MOVE_APPLICATION_TO133:
        return (
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            'Prompted by the Anti Fraud API',
        )
    elif binary_check_status == StatusEnum.MOVE_APPLICATION_TO135:
        can_reapply_date = timezone.localtime(timezone.now()) + relativedelta(days=31)
        application.customer.update_safely(can_reapply=False, can_reapply_date=can_reapply_date)
        return ApplicationStatusCodes.APPLICATION_DENIED, 'Prompted by the Anti Fraud API'
    elif binary_check_status == StatusEnum.MOVE_APPLICATION_TO115:
        return (
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            'Prompted by the Anti Fraud API',
        )
    else:
        error_message = "Unhandled status: {}".format(binary_check_status)
        logger.error(
            {
                "action": "process_anti_fraud_api_turbo",
                "error": error_message,
                "application_id": application.id,
                "binary_check_status": binary_check_status,
            }
        )
        sentry.capture_exception(
            error=Exception(error_message),
            extra={"application_id": application.id, "binary_check_status": binary_check_status},
        )
        return ApplicationStatusCodes.SCRAPED_DATA_VERIFIED, 'Prompted by the Anti Fraud API'
