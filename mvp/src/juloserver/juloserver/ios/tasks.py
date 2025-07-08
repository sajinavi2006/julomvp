import logging
from celery import task
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.julo.models import (
    Application,
    ApplicationHistory,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.application_flow.services import (
    JuloOneService,
    check_liveness_detour_workflow_status_path,
    is_experiment_application,
    run_bypass_eligibility_checks,
    send_application_event_by_certain_pgood,
    send_application_event_base_on_mycroft,
    process_anti_fraud_binary_check,
)
from juloserver.application_flow.constants import ApplicationStatusEventType
from juloserver.julo.services import process_application_status_change
from juloserver.ios.services import get_credit_score_ios
from juloserver.personal_data_verification.services import is_pass_dukcapil_verification_at_x105
from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.constants import (
    FeatureNameConst,
)
from juloserver.face_recognition.tasks import face_matching_task
from juloserver.face_recognition.services import CheckFaceSimilarity
from juloserver.fraud_security.tasks import check_high_risk_asn
from juloserver.fraud_score.tasks import (
    handle_fraud_score_post_application_credit_score,
)

logger = logging.getLogger(__name__)


@task(queue='application_normal')
def handle_iti_ready_ios(application_id: int):
    """
    Run a series of fraud check process after getting ready response from ANA.

    Args:
        application_id (int): Application object id property.
    """
    change_reason = None
    logger.info({'action': 'handle_iti_ready_ios', 'data': {'application_id': application_id}})
    application = Application.objects.get(pk=application_id)

    if application.status != ApplicationStatusCodes.FORM_PARTIAL:
        anti_fraud_retry = ApplicationHistory.objects.filter(
            application_id=application_id,
            change_reason="anti_fraud_api_unavailable",
        ).last()
        if (
            application.status != ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
            and not anti_fraud_retry
        ):
            logger.error(
                {
                    'message': 'Application not allowed to run function',
                    'application_status': str(application.status),
                    'application': application_id,
                }
            )
            return

    if application.is_julo_one_or_starter():
        send_application_event_by_certain_pgood(
            application,
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusEventType.APPSFLYER_AND_GA,
        )
        send_application_event_base_on_mycroft(
            application,
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusEventType.APPSFLYER_AND_GA,
        )

    is_application_detour_by_liveness = check_liveness_detour_workflow_status_path(
        application, ApplicationStatusCodes.FORM_PARTIAL
    )
    liveness_detection_result, liveness_change_reason = True, ''
    if not is_application_detour_by_liveness:
        # run before checking C score
        run_bypass_eligibility_checks(application)
        logger.info(
            'handle_iti_ready_ios_skip_liveness|application_id={}'.format(application_id)
        )

    allow_to_change_status = False
    if liveness_change_reason and 'failed video injection' in liveness_change_reason:
        allow_to_change_status = True
        video_injected_status_code = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        process_application_status_change(
            application.id, video_injected_status_code, liveness_change_reason
        )
        return

    if JuloOneService.is_c_score(application):
        logger.error(
            {
                'message': 'handle_iti_ready_ios: Application score is C',
                'application': application_id,
            }
        )
        return

    # Dukcapil Direct
    is_pass_dukcapil_verification_at_x105(application)

    ga_event = None
    failed_liveness_status_code = None
    if not liveness_detection_result:
        allow_to_change_status = True
        failed_liveness_status_code = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR
    elif feature_high_score_full_bypass(application, ignore_fraud=True):
        allow_to_change_status = True
        change_reason = FeatureNameConst.HIGH_SCORE_FULL_BYPASS

    # Sending events to Google Analytics
    if ga_event:
        if application.customer.app_instance_id:
            send_event_to_ga_task_async.apply_async(
                kwargs={'customer_id': application.customer.id, 'event': ga_event}
            )
        else:
            logger.info(
                'handle_iti_ready_ios|app_instance_id not found|'
                'application_id={}'.format(application_id)
            )

    if is_experiment_application(application.id, 'ExperimentUwOverhaul'):
        logger.info(
            {
                "application_id": application.id,
                "message": "handle_iti_ready_ios: Goes to experiment application check.",
            }
        )
        get_score = get_credit_score_ios(application.id, skip_delay_checking=True)
        if get_score.score.upper() != 'C':
            check_face_similarity = CheckFaceSimilarity(application)
            check_face_similarity.check_face_similarity()
            face_matching_task.delay(application.id)
            allow_to_change_status = True
            change_reason = FeatureNameConst.PASS_BINARY_AND_DECISION_CHECK

    # All Fraud Binary Check.
    # By default, if the check is failed the application status is moved to x133.
    # is_pass_fraud_check, fail_fraud_check_handler = process_fraud_binary_check(application)
    from juloserver.antifraud.constant.binary_checks import StatusEnum

    binary_check_result = process_anti_fraud_binary_check(application.status, application.id)
    allowed_binary_check_result = [
        StatusEnum.BYPASSED_HOLDOUT,
        StatusEnum.DO_NOTHING,
    ]
    retry_binary_check_result = [
        StatusEnum.ERROR,
        StatusEnum.RETRYING,
    ]

    if binary_check_result not in allowed_binary_check_result:
        new_status_fraud = None
        fraud_change_reason = "Prompted by the Anti Fraud API"

        logger.info(
            {
                'action': 'handle_iti_ready_ios: get_anti_fraud_binary_check_status',
                'message': 'application failed fraud binary check',
                'application': application_id,
                'binary_check_result': binary_check_result,
            }
        )
        if binary_check_result in retry_binary_check_result:
            fraud_status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
            if application.status == fraud_status:
                return

            fraud_change_reason = 'anti_fraud_api_unavailable'
            new_status_fraud = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
        elif binary_check_result == StatusEnum.MOVE_APPLICATION_TO115:
            new_status_fraud = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
        elif binary_check_result == StatusEnum.MOVE_APPLICATION_TO133:
            new_status_fraud = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        elif binary_check_result == StatusEnum.MOVE_APPLICATION_TO135:
            new_status_fraud = ApplicationStatusCodes.APPLICATION_DENIED
            can_reapply_date = timezone.localtime(timezone.now()) + relativedelta(days=90)
            application.customer.update_safely(can_reapply_date=can_reapply_date)

        if new_status_fraud:
            process_application_status_change(
                application_id=application_id,
                new_status_code=new_status_fraud,
                change_reason=fraud_change_reason,
            )
            return

    # High Risk ASN check
    check_high_risk_asn(application_id)

    if allow_to_change_status:
        new_status_code = ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        if not is_application_detour_by_liveness:
            # if score is not C and failed liveness detection, we will move application to 134
            # status
            new_status_code = failed_liveness_status_code or new_status_code
            change_reason = liveness_change_reason or change_reason

        logger.info(
            {
                'message': 'try to run process_application_status_change',
                'application': application_id,
                'allow_to_change_status': allow_to_change_status,
                'new_status_code': new_status_code,
                'is_application_detour_by_liveness': is_application_detour_by_liveness,
                'change_reason': change_reason if change_reason else None,
            }
        )
        is_moved = process_application_status_change(application.id, new_status_code, change_reason)

        logger.info(
            {
                'message': 'handle_iti_ready_ios process application status change',
                'application': application_id,
                'is_moved': is_moved,
                'allow_to_change_status': allow_to_change_status,
                'new_status_code': new_status_code,
                'is_application_detour_by_liveness': is_application_detour_by_liveness,
                'change_reason': change_reason if change_reason else None,
            }
        )

        # Trigger Optional task after the application status changed
        if new_status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
            handle_fraud_score_post_application_credit_score.delay(application.id)
    else:
        logger.info(
            {
                'message': 'handle_iti_ready_ios stuck x105',
                'allow_to_change_status': allow_to_change_status,
                'application': application_id,
            }
        )
