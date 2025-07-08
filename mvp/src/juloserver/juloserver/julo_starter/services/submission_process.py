import copy
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    FeatureNameConst,
    FeatureSettingMockingProduct,
    OnboardingIdConst,
)
from juloserver.julo.models import Mantri, Application
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.tasks2.application_tasks import send_deprecated_apps_push_notif
from juloserver.employee_financing.utils import verify_nik
from juloserver.julolog.julolog import JuloLog
from juloserver.application_form.constants import (
    JuloStarterFormResponseCode,
    JuloStarterFormResponseMessage,
)
from juloserver.application_flow.services import (
    suspicious_hotspot_app_fraud_check,
    eligible_to_offline_activation_flow,
    run_bypass_eligibility_checks,
)
from juloserver.apiv2.tasks import populate_zipcode
from juloserver.apiv3.views import ApplicationUpdateV3
from juloserver.application_form.services.julo_starter_service import (
    is_verify_phone_number,
)
from juloserver.julo_starter.exceptions import JuloStarterException
from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.application_flow.tasks import move_application_to_x133_for_blacklisted_device

from juloserver.liveness_detection.services import (
    check_application_liveness_detection_result,
    trigger_passive_liveness,
)
from juloserver.face_recognition.services import CheckFaceSimilarity
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

from juloserver.pin.services import is_blacklist_android
from juloserver.fraud_score.serializers import fetch_android_id
from juloserver.julo_starter.services.credit_limit import check_is_good_score
from juloserver.julo_starter.exceptions import PDCreditModelNotFound, SettingNotFound
from juloserver.julo_starter.constants import BinaryCheckFields
from juloserver.apiv2.models import AutoDataCheck
from juloserver.application_form.services.application_service import (
    is_user_offline_activation_booth,
)

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def process_to_update(application: Application, validated_data):
    from juloserver.application_form.views.view_v1 import ApplicationUpdate as ApplicationUpdateV1

    # Detokenize because it used ktp and email
    detokenized_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'object': application, "customer_id": application.customer_id}],
        force_get_local_data=True,
    )
    application = detokenized_applications[0]

    ktp = application.ktp
    email = application.email

    if validated_data.get('onboarding_id') not in OnboardingIdConst.JULO_360_IDS and not email:
        raise JuloStarterException(JuloStarterFormResponseMessage.INVALID_EMAIL)

    if not ktp or not verify_nik(ktp):
        raise JuloStarterException(JuloStarterFormResponseMessage.INVALID_NIK)

    if application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
        return (
            JuloStarterFormResponseCode.APPLICATION_NOT_ALLOW,
            JuloStarterFormResponseMessage.APPLICATION_NOT_ALLOW,
        )
    selfie_service = ApplicationUpdateV3()
    if not selfie_service.check_liveness(
        application=application
    ) or not selfie_service.check_selfie_submission(application=application):
        return (
            JuloStarterFormResponseCode.NOT_FINISH_LIVENESS_DETECTION,
            JuloStarterFormResponseMessage.NOT_FINISH_LIVENESS_DETECTION,
        )

    phone_number = validated_data.get('mobile_phone_1')
    if (
        not application.is_julo_360()
        and phone_number
        and not is_verify_phone_number(phone_number, application.customer_id)
    ):
        return (
            JuloStarterFormResponseCode.INVALID_PHONE_NUMBER,
            JuloStarterFormResponseMessage.INVALID_PHONE_NUMBER,
        )

    ApplicationUpdateV1.claim_customer(application, validated_data)
    application_update_data = copy.deepcopy(validated_data)
    validated_data.pop('app_version')

    onboarding_id = validated_data.get('onboarding_id')
    application_update_data['onboarding_id'] = onboarding_id

    if validated_data.get('referral_code'):
        referral_code = validated_data['referral_code'].replace(' ', '')

        # offline activation booth condition
        # check if have referral code and set path tag
        is_user_offline_activation_booth(referral_code, application.id)

        mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
        if mantri_obj:
            application_update_data['mantri_id'] = mantri_obj.id

    application_update_data['name_in_bank'] = application_update_data.get('fullname')

    application_update_data['device_id'] = validated_data.get('device')
    application_update_data.pop('device')

    # update this application data
    application.update_safely(**application_update_data)

    # modify populate_zipcode to sync since it became intermitent delay
    # between ana server and application table when generate score
    populate_zipcode(application)
    process_application_status_change(
        application.id,
        ApplicationStatusCodes.FORM_PARTIAL,
        change_reason='customer_triggered',
    )
    application.refresh_from_db()
    suspicious_hotspot_app_fraud_check(application)
    send_deprecated_apps_push_notif.delay(application.id, application.app_version)

    validated_data['mobile_phone_1'] = application.mobile_phone_1

    application.refresh_from_db()
    validated_data['status'] = ApplicationStatusCodes.FORM_PARTIAL

    # No need to detokenize application here,
    # because is only check the existence and use `id`.
    # Do more detokenize if used PII attribute!
    other_app = Application.objects.filter(
        application_status=ApplicationStatusCodes.FORM_CREATED, customer_id=application.customer
    ).last()

    if other_app:
        process_application_status_change(
            other_app.id,
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
            change_reason='JTurbo_App_Submitted',
        )

    logger.info(
        {
            "message": "success update application",
            "onboarding_id": onboarding_id,
            "application_id": application.id,
            "data": str(validated_data),
        }
    )

    return JuloStarterFormResponseCode.SUCCESS, validated_data


@sentry.capture_exceptions
def check_app_authentication(request, param, available_onboarding_ids=None):
    if available_onboarding_ids:
        application = (
            request.user.customer.application_set.regular_not_deletes()
            .filter(
                application_status_id=ApplicationStatusCodes.FORM_CREATED,
                onboarding_id__in=available_onboarding_ids,
            )
            .last()
        )
    else:
        application = request.user.customer.application_set.regular_not_deletes().last()

    # No need to detokenize applications here,
    # because it only use 'id'.
    # Do more detokenize if the used PII attribute!
    if not application:
        raise JuloStarterException(JuloStarterFormResponseMessage.APPLICATION_NOT_FOUND)

    if str(application.id) != str(param):
        raise JuloStarterException("Token invalid")

    return application


def check_black_list_android(application: Application, auto_move_status=True):
    """
    No need to detokenize application here, because it passed to another function.
    Do more detokenization if used PII attribute!
    """

    android_id = fetch_android_id(application.customer)
    is_fraudster = is_blacklist_android(android_id)
    if is_fraudster:
        if auto_move_status:
            move_application_to_x133_for_blacklisted_device(application.id)
        return True

    return False


def check_fraud_result(application: Application, check_video_injection=False):
    """
    No need to detokenize application here, because it passed to another function.
    Do more detokenization if used PII attribute!
    """

    from juloserver.julo_starter.services.services import (
        get_mock_feature_setting,
        mock_app_risky_response,
    )

    change_reason = ''
    # check liveness detection result
    (
        liveness_detection_result,
        liveness_change_reason,
    ) = check_application_liveness_detection_result(application)
    if not liveness_detection_result:
        if (
            check_video_injection
            and liveness_change_reason
            and 'failed video injection' in liveness_change_reason
        ):
            return True, liveness_change_reason
        logger.info(
            'bypass_liveness_failed|'
            'application_id={}, reason={}'.format(application.id, liveness_change_reason)
        )

    # check application risky check
    mock_feature = get_mock_feature_setting(
        FeatureNameConst.APP_RISKY_CHECK_MOCK, FeatureSettingMockingProduct.J_STARTER
    )
    if mock_feature:
        return mock_app_risky_response(mock_feature)

    # check application risky check
    risky_checklist = ApplicationRiskyCheck.objects.filter(application=application).last()
    if not risky_checklist:
        logger.warning('application_risky_check_not_found|application_id={}'.format(application.id))
        return False, change_reason

    is_not_risky_app = application.eligible_for_hsfbp(risky_checklist)
    if not is_not_risky_app:
        logger.info('bypass_app_risky_found|application_id={}'.format(application.id))

    return False, change_reason


def process_fraud_check(application: Application):

    # WARNING: override section
    from juloserver.julo_starter.services.onboarding_check import is_email_for_whitelists

    # No need to detokenize application and customer here,
    # because it only uses application relationships, `application.id`, and pass to another function
    # And only uses customer 'id', and pass it to another function.
    # Do more detokenize if the used PII attribute!
    customer = application.customer

    is_target_whitelist = is_email_for_whitelists(customer)
    if is_target_whitelist:
        logger.info(
            {
                'message': '[FRAUD_CHECK] override result for email whitelist',
                'override_to': 'no_fraud',
                'customer': customer.id if customer else None,
            }
        )
        return False

    is_fraud, reason = check_fraud_result(application, check_video_injection=True)
    if is_fraud:
        logger.warning(
            {'julo starter fraud check failed': reason, 'application_id': application.id}
        )
        process_application_status_change(
            application, ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD, reason
        )
        return True

    return False


def run_fraud_check(application: Application):
    """
    Run these fraud checks after dukcapil

    No need to detokenize application here, because it passed to another function.
    Do more detokenization if used PII attribute!
    """

    # check passive liveness detection
    # trigger passive liveness detection and check the result
    trigger_passive_liveness(application)
    (
        liveness_detection_result,
        liveness_change_reason,
    ) = check_application_liveness_detection_result(application)
    if not liveness_detection_result:
        logger.info(
            'liveness_detection_failed|result={}, reason={}'.format(
                liveness_detection_result, liveness_change_reason
            )
        )
        return

    is_risky_app, err_msg = check_application_risky(application)
    if is_risky_app:
        logger.info(
            'application_risky_check_foun|result={}, reason={}'.format(
                liveness_detection_result, liveness_change_reason
            )
        )


def check_application_risky(application: Application):
    """
    No need to detokenize application here, because it passed to another function.
    Do more detokenization if used PII attribute!
    """

    face_similarity_service = CheckFaceSimilarity(application)
    face_similarity_service.check_face_similarity()

    is_eligibility = run_bypass_eligibility_checks(application)
    if not is_eligibility:
        return True, 'Found risky check'

    return False, ''


def check_affordability(application: Application):
    """
    No need to detokenize application here, because it passed to another function.
    and uses id, status,
    Do more detokenization if used PII attribute!
    """

    from juloserver.application_flow.tasks import application_tag_tracking_task

    if application.status != ApplicationStatusCodes.FORM_PARTIAL:
        logger.warning(
            'check_affordability_wrong_application_status|'
            'application_status={}, application_id={}'.format(application.status, application.id)
        )
        return False

    if check_black_list_android(application, auto_move_status=False):
        logger.info(
            'check_affordability_application_is_blacklist|'
            'application_id={}'.format(application.id)
        )
        return False

    binary_result = binary_check_result(application)
    offline_activation_flow = eligible_to_offline_activation_flow(application)

    if not binary_result and not offline_activation_flow:
        logger.info(
            {
                "msg": "check_affordability_application_binary_result",
                "application_id": application.id,
            }
        )
        return False

    try:
        is_good_score = check_is_good_score(application)
    except PDCreditModelNotFound:
        logger.warning(
            'check_affordability_pd_credit_model_not_found|'
            'application_id={}'.format(application.id)
        )
        return False
    except SettingNotFound:
        logger.warning(
            'credit_limit_generation_check_good_score_setting_not_found|'
            'application_id={}'.format(application.id)
        )
        is_good_score = True

    if not is_good_score and not offline_activation_flow:
        logger.info(
            'check_affordability_application_is_not_good_score|'
            'application_id={}'.format(application.id)
        )
        return False

    if not is_good_score and offline_activation_flow:
        application_tag_tracking_task(
            application.id, None, None, None, 'is_offline_activation_low_pgood', 1
        )

    fraud_result, fraud_reason = check_fraud_result(application)
    if fraud_result:
        logger.info(
            'check_affordability_application_is_fraud|' 'application_id={}'.format(application.id)
        )
        return False

    return True


def binary_check_result(
    application: Application, first_check=True, bypass_check_list=BinaryCheckFields.bypass
):

    # WARNING: override section
    from juloserver.julo_starter.services.onboarding_check import is_email_for_whitelists

    # No need to detokenize application and customer here, because is passed to another function.
    # Do more detokenization if used PII attribute!
    customer = application.customer

    is_target_whitelist = is_email_for_whitelists(customer)
    if is_target_whitelist:
        return True

    from juloserver.julo_starter.services.services import (
        get_mock_feature_setting,
        mock_binary_check_response,
    )

    mock_feature = get_mock_feature_setting(
        FeatureNameConst.BINARY_CHECK_MOCK, FeatureSettingMockingProduct.J_STARTER
    )
    if mock_feature:
        return mock_binary_check_response(mock_feature)

    failed_checks = AutoDataCheck.objects.filter(application_id=application.id, is_okay=False)
    if first_check:
        failed_checks = failed_checks.exclude(data_to_check__in=bypass_check_list)
    else:
        failed_checks = failed_checks.filter(data_to_check__in=bypass_check_list)
        failed_checks = failed_checks.exclude(data_to_check__in=BinaryCheckFields.exclude)
    failed_checks = failed_checks.values_list('data_to_check', flat=True)
    if failed_checks:
        return False

    return True
