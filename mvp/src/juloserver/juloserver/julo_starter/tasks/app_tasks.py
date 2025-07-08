from juloserver.fraud_security.services import blacklisted_asn_check
from django.utils import timezone
from django.db import transaction
from dateutil.relativedelta import relativedelta
from celery import task

from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    OnboardingEligibilityChecking,
    Workflow,
    CustomerFieldChange,
    Device,
    FeatureSetting,
    ApplicationUpgrade,
    FDCInquiry,
)
from juloserver.application_flow.constants import JuloOne135Related, JuloOneChangeReason
from juloserver.account.services.account_related import process_change_account_status
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo_starter.constants import ApplicationExpiredJStarter
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.utils import have_pn_device

from juloserver.application_flow.services import (
    is_referral_blocked,
    eligible_to_offline_activation_flow,
)

from juloserver.fraud_security.binary_check import process_fraud_binary_check

logger = JuloLog(__name__)


@task(queue="application_normal")
def trigger_form_partial_expired_julo_starter():
    """
    This task to purpose move x105 application,
    if stay in x105 during from current date - 3 days.
    """

    # No need to detokenization application here,
    # because it only uses 'id', 'udate', and 'application_status_id'.
    # Do more detokenization if the used PII attribute!
    applications_ids = Application.objects.filter(
        application_status_id__lte=ApplicationStatusCodes.FORM_PARTIAL,
        workflow__name=WorkflowConst.JULO_STARTER,
    ).values_list('id', 'udate', 'application_status_id')

    for application_id, update_date, application_status_id in applications_ids:
        logger.info(
            {
                "message": "[Expired Task] called trigger process expired",
                "application_id": application_id,
            }
        )
        run_application_expired_subtask.delay(application_id, update_date, application_status_id)


@task(queue="application_normal")
def run_application_expired_subtask(application_id, update_date, application_status_id):
    """
    Run the function to moved to Form Partial Expired
    """

    target_time = timezone.now() - relativedelta(
        days=ApplicationExpiredJStarter.TARGET_EXPIRED_DAYS
    )
    app_history = ApplicationHistory.objects.filter(
        application_id=application_id,
        status_new=application_status_id,
    ).last()

    if app_history:
        update_date = app_history.cdate
    if update_date < target_time:  # use udate of application if cdate is not found in history
        logger.info(
            {
                "message": "[Expired Task] Application moved to x106",
                "application_id": application_id,
                "target_time": target_time,
                "last_update_application": update_date,
            }
        )
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ApplicationExpiredJStarter.MESSAGE_FOR_REASON,
        )


@task(queue="application_low")
def enable_reapply_for_rejected_external_check():
    from django.db.models import Q
    from django.utils import timezone
    from datetime import timedelta

    logger.info(
        {
            'message': 'Start execute function enable_reapply_for_rejected_external_check',
        }
    )

    jstar_workflow = Workflow.objects.filter(name=WorkflowConst.JULO_STARTER).last()

    month_ago = timezone.now() - timedelta(days=31)
    start = month_ago - timedelta(days=2)

    # No need to detokenization fdc inquiry here,
    # because it only uses `id`.
    # Do more detokenization if used PII attribute!
    fdc_inquiry_records = FDCInquiry.objects.filter(cdate__range=[start, month_ago]).values_list(
        'id', flat=True
    )

    # Check for BPJS and FDC
    checks = (
        OnboardingEligibilityChecking.objects.select_related(
            'bpjs_api_log',
            'dukcapil_response__application',
            'customer',
        )
        .filter(
            Q(fdc_check__in=[2, 3], fdc_inquiry_id__in=list(fdc_inquiry_records))
            | Q(bpjs_check__in=[2, 3], bpjs_api_log__cdate__range=[start, month_ago])
            | Q(dukcapil_check__in=[3], dukcapil_response__cdate__range=[start, month_ago])
        )
        .filter(customer__can_reapply=False)
        .all()
    )

    for check in checks:
        if not _set_reapply(check, workflow=jstar_workflow):
            continue

    logger.info(
        {
            'message': 'Finish execute function enable_reapply_for_rejected_external_check',
        }
    )


def _set_reapply(check, workflow):

    # No need to detokenization customer here,
    # because it only check the relationships and uses `can_reapply`.
    # Do more detokenization if used PII attribute!
    customer = check.customer
    customer_can_reapply = True
    logger_data = {}
    if check.dukcapil_response:

        # No need to detokenize application here,
        # because is passed to another function and use `workflow_id`, `application_number`.
        # Do more detokenization if used PII attribute!
        application = check.dukcapil_response.application

        # No need to detokenize application here,
        # because is only use `id`, `application_number`, `application_status_id`.
        # Do more detokenization if used PII attribute!
        last_app = customer.application_set.order_by('-application_number')[0]

        if application.workflow_id != workflow.id:
            return False

        if (
            check.dukcapil_check in (3,)
            and last_app.application_number != application.application_number
        ):
            return False

        if is_referral_blocked(application):
            return False
        elif last_app.application_number != application.application_number:
            return False

        if last_app.application_status_id in (
            ApplicationStatusCodes.OFFER_REGULAR,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ):
            customer_can_reapply = False

        logger_data = {
            "application": last_app.id,
            "status": last_app.application_status_id,
        }

    logger.info(
        {
            "message": "set reapply for JULO Turbo",
            "customer_can_reapply": customer_can_reapply,
            **logger_data,
        }
    )

    with transaction.atomic():
        old_value = customer.can_reapply

        customer.can_reapply = customer_can_reapply
        customer.save()

        if old_value != customer_can_reapply:
            CustomerFieldChange.objects.create(
                customer=customer,
                field_name="can_reapply",
                old_value=old_value,
                new_value=customer_can_reapply,
            )


@task(queue='application_normal')
def trigger_master_agreement_pn_subtask(application_id):
    # No need to detokenize application here, because is only use `customer_id`,
    # `status` and some methods. The methods not related to PII data.
    # Do more detokenization if used PII attribute!

    application = Application.objects.filter(id=application_id).last()
    valid_status = [
        ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
        ApplicationStatusCodes.LOC_APPROVED,
    ]
    ma_setting_active = FeatureSetting.objects.get_or_none(
        is_active=True,
        feature_name="master_agreement_setting",
    )
    device = Device.objects.filter(customer_id=application.customer_id).last()
    if (
        not have_pn_device(device)
        or application.has_master_agreement()
        or not application.is_julo_starter()
        or application.status not in valid_status
        or not ma_setting_active
    ):
        return
    logger.info(
        {
            'action': 'JULO Starter Master Agreement Notification',
            'application_id': application_id,
        }
    )
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_julo_starter_master_agreement(device.gcm_reg_id)


@task(queue="application_normal")
def trigger_push_notif_check_scoring(application_id, template_code):

    if not application_id:
        error_message = "Application invalid"
        logger.error(
            {
                "message": error_message,
                "application": application_id,
            }
        )
        return False

    # No need to detokenize application here,
    # because is only use `id`, `application_status_id`, `customer_id`.
    # Do more detokenization if used PII attribute!
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        error_message = "Application not found"
        logger.error(
            {
                "message": error_message,
                "application": application_id,
            }
        )
        return False

    # reversion from x191 to x190 should not trigger PN
    last_application = ApplicationHistory.objects.filter(application_id=application.id).last()
    if (
        last_application
        and application.application_status_id == ApplicationStatusCodes.LOC_APPROVED
        and last_application.status_old == ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
    ):
        return False

    customer_id = application.customer_id
    device = Device.objects.filter(customer_id=customer_id).last()
    if not have_pn_device(device):
        error_message = "Application invalid"
        logger.error({"message": error_message, "customer": customer_id, "device": str(device)})
        return False

    logger.info(
        {
            "message": "Sending notification for Julo Starter customers",
            "template_code": template_code,
            "customer_id": customer_id,
            "gcm_reg_id": device.gcm_reg_id,
        }
    )

    push_notif = get_julo_pn_client()
    push_notif.checks_and_scoring_notification_jstarter(
        device.gcm_reg_id,
        template_code,
        customer_id,
    )

    return True


@task(queue='application_high')
def trigger_pn_emulator_detection(application_id):
    from juloserver.julo.utils import have_pn_device

    # No need to detokenize application here,
    # because is only use `status`, `customer_id`, `workflow`.
    # Do more detokenization if used PII attribute!
    application = Application.objects.filter(id=application_id).last()

    device = Device.objects.filter(customer_id=application.customer_id).last()
    if (
        not have_pn_device(device)
        or not application.is_julo_starter()
        or application.status != ApplicationStatusCodes.FORM_PARTIAL
    ):
        return

    logger.info(
        {
            'action': 'JULO Starter Emulator Check ready Notification',
            'application_id': application_id,
        }
    )

    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_julo_starter_emulator_detection(device.gcm_reg_id, application.customer_id)


@task(queue='application_high')
def handle_julo_starter_binary_check_result(application_id):
    from juloserver.account.constants import AccountConstant
    from juloserver.julo_starter.workflow import JuloStarterWorkflowAction
    from juloserver.julo_starter.services.services import (
        determine_js_workflow,
        process_anti_fraud_api_turbo,
    )
    from juloserver.julo_starter.services.submission_process import binary_check_result
    from juloserver.face_recognition.tasks import face_matching_task
    from juloserver.julo_starter.services.onboarding_check import is_email_for_whitelists

    # No need to detokenize application here,
    # because is check relationships and use `status`, `id`.
    # Do more detokenization if used PII attribute!
    application = Application.objects.get_or_none(pk=application_id)

    is_partial_limit = determine_js_workflow(application)
    account = application.customer.account_set.last()
    result = binary_check_result(application, first_check=False)
    offline_activation_flow = eligible_to_offline_activation_flow(application)
    fail_dynamic_check = False

    # No need to detokenize customer here,
    # because it passes to another function as object.
    # Do more detokenization if used PII attribute!
    customer = application.customer

    is_target_whitelist = is_email_for_whitelists(customer)

    julo_starter_config = FeatureSetting.objects.filter(
        feature_name='julo_starter_config',
        is_active=True,
    ).last()

    if julo_starter_config and julo_starter_config.parameters.get('dynamic_check', None):

        from juloserver.apiv2.models import AutoDataCheck

        if AutoDataCheck.objects.filter(
            application_id=application_id, is_okay=False, data_to_check='dynamic_check', latest=True
        ).exists():
            fail_dynamic_check = True

    logger.info(
        {
            'message': 'execute process callback from ana binary check#2',
            'application': application_id,
            'is_partial_limit': is_partial_limit,
            'result_binary_check': result,
        }
    )

    if (
        (not result or fail_dynamic_check)
        and not offline_activation_flow
        and not is_target_whitelist
    ):
        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.deactivated,
            change_reason="failed binary or dynamic check ",
        )

        if (
            is_partial_limit
            and application.status == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
        ):
            new_status = ApplicationStatusCodes.LOC_APPROVED
            change_reason = 'LOC Rejected'
            process_application_status_change(
                application_id, new_status, change_reason=change_reason
            )

        return

    # recalculate affordability limit
    workflow = JuloStarterWorkflowAction(
        application,
        application.status,
        '',
        '',
        application.status,
    )
    workflow.affordability_calculation()
    if application.status == ApplicationStatusCodes.LOC_APPROVED:
        workflow.credit_limit_generation()
    elif application.status == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED:
        # Blacklisted ASN check, if the application is found to have blacklisted ASN
        # will be moved to x133
        # Executing ASN blacklisted check after mycroft check
        if blacklisted_asn_check(application) and not is_target_whitelist:
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                JuloOneChangeReason.BLACKLISTED_ASN_DETECTED,
            )
            return

        # Blacklisted company binary check for JTurbo.
        # By default, if the check is failed the application status is moved to x133 and
        # in turn moved to x190 LOC reject.
        is_pass_fraud_check, fail_fraud_check_handler = process_fraud_binary_check(
            application, source='handle_julo_starter_binary_check_result'
        )
        if not is_pass_fraud_check and not is_target_whitelist:
            logger.info(
                {
                    'action': 'handle_julo_starter_binary_check_result',
                    'message': 'application failed fraud check',
                    'application': application_id,
                    'handler': fail_fraud_check_handler.__class__.__name__,
                }
            )
            process_application_status_change(
                application_id=application_id,
                new_status_code=fail_fraud_check_handler.fail_status_code,
                change_reason=fail_fraud_check_handler.fail_change_reason,
            )
            return

        # Trigger face matching task
        face_matching_task.delay(application_id)

        antifraud_api_onboarding_fs = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.ANTIFRAUD_API_ONBOARDING,
            is_active=True,
        )
        new_status = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        change_reason = 'Julo Starter Verified'
        if (
            not is_target_whitelist
            and antifraud_api_onboarding_fs
            and antifraud_api_onboarding_fs.parameters.get('turbo_109', False)
        ):
            new_status, change_reason = process_anti_fraud_api_turbo(application)

        process_application_status_change(application_id, new_status, change_reason=change_reason)
        if new_status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD:
            process_change_account_status(
                application.account,
                AccountConstant.STATUS_CODE.deactivated,
                change_reason,
            )
        elif new_status in [
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            ApplicationStatusCodes.APPLICATION_DENIED,
        ]:
            process_change_account_status(
                application.account,
                AccountConstant.STATUS_CODE.inactive,
                change_reason,
            )


@task(queue='application_normal')
def trigger_revert_application_upgrade():
    application_upgrade_ids = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
        workflow__name=WorkflowConst.JULO_STARTER,
    ).values_list('id', flat=True)

    application_upgrade_objects = (
        ApplicationUpgrade.objects.filter(
            application_id_first_approval__in=list(application_upgrade_ids),
        )
        .values_list('application_id', 'application_id_first_approval')
        .distinct('application_id_first_approval')
        .order_by('application_id_first_approval', '-id')
    )

    application_upgrade_object_dicts = {}
    for application_upgrade_object in application_upgrade_objects:
        application_upgrade_object_dicts[
            application_upgrade_object[0]
        ] = application_upgrade_object[1]

    j1_applications = Application.objects.filter(
        pk__in=application_upgrade_object_dicts.keys(),
        workflow__name=WorkflowConst.JULO_ONE,
    )

    for j1_application in j1_applications.iterator():
        expired_date = None
        today = timezone.localtime(timezone.now())
        last_status = ApplicationHistory.objects.filter(application_id=j1_application.id).last()
        if not last_status:
            continue

        if last_status.status_new == ApplicationStatusCodes.APPLICATION_DENIED:
            change_reason = last_status.change_reason.lower()

            if not last_status:
                return

            if any(
                word in change_reason
                for word in JuloOne135Related.REAPPLY_AFTER_ONE_MONTHS_REASON_J1
            ):
                expired_date = last_status.cdate + relativedelta(days=30)

            if any(
                word in change_reason
                for word in JuloOne135Related.REAPPLY_AFTER_THREE_MONTHS_REASON_J1
            ):
                expired_date = last_status.cdate + relativedelta(days=90)

            if any(
                word in change_reason
                for word in JuloOne135Related.REAPPLY_AFTER_HALF_A_YEAR_REASON_J1
            ):
                expired_date = last_status.cdate + relativedelta(days=180)

            if any(
                word in change_reason for word in JuloOne135Related.REAPPLY_AFTER_ONE_YEAR_REASON_J1
            ):
                expired_date = last_status.cdate + relativedelta(days=365)
        elif last_status.status_new == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
            expired_date = last_status.cdate + relativedelta(days=14)

        if expired_date and today.date() > expired_date.date():
            application_upgrade_id = application_upgrade_object_dicts.get(j1_application.id)
            if application_upgrade_id:
                logger.info(
                    {
                        'message': 'Moved application from x191 to x190',
                        'application': application_upgrade_id,
                        'expired_date': str(expired_date),
                    }
                )
                process_application_status_change(
                    application_upgrade_id,
                    ApplicationStatusCodes.LOC_APPROVED,
                    change_reason='upgrade_grace_period_end',
                )
            else:
                logger.warning(
                    'trigger_revert_application_upgrade_app_upgrade_id_not_found|'
                    'j1_application_id={}'.format(j1_application.id)
                )


@task(queue='application_high')
def trigger_is_eligible_bypass_to_x121(application_id):
    """
    This function to bypass from x109 to x121
    if condition data are completed in extra form.
    """
    from juloserver.julo_starter.services.services import is_eligible_bypass_to_x121

    is_eligible_bypass_to_x121(application_id)
