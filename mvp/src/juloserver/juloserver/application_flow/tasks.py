"""tasks.py"""

import operator
import time
import json

from datetime import timedelta, datetime

from celery import task

from django.conf import settings
from django.db import transaction, connection
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.db.utils import IntegrityError

from juloserver.ana_api.models import (
    PdApplicationFraudModelResult,
    SdBankAccount,
    SdBankStatementDetail,
)
from juloserver.apiv2.models import (
    PdWebModelResult,
    PdCreditModelResult,
    PdFraudModelResult,
    AutoDataCheck,
)
from juloserver.apiv2.services import (
    get_credit_score3,
    is_customer_has_good_payment_histories,
    remove_fdc_binary_check_that_is_not_in_fdc_threshold,
    checking_fraud_email_and_ktp,
    is_c_score_in_delay_period,
    get_experimental_probability_fpd,
    is_email_whitelisted_to_force_high_score,
)
from juloserver.application_flow.constants import (
    GooglePlayIntegrityConstants,
    JuloOneChangeReason,
    PartnerNameConstant,
    BankStatementConstant,
)
from juloserver.application_flow.services import (
    ApplicationTagTracking,
    JuloOneService,
    capture_suspicious_app_risk_check,
    check_liveness_detour_workflow_status_path,
    fraud_bank_scrape_and_bpjs_checking,
    is_experiment_application,
    run_bypass_eligibility_checks,
    reject_application_by_google_play_integrity,
    record_google_play_integrity_api_emulator_check_data,
    suspicious_hotspot_app_fraud_check,
    store_application_to_experiment_table,
    SpecialEventSettingHelper,
    check_bpjs_found,
    check_good_fdc_bypass,
    check_telco_pass,
    pass_binary_check_scoring,
    process_bad_history_customer,
    send_application_event_by_certain_pgood,
    send_application_event_base_on_mycroft,
    eligible_to_offline_activation_flow,
    process_anti_fraud_binary_check,
    process_eligibility_waitlist,
    check_waitlist,
    eligible_entry_level,
    is_entry_level_swapin,
)
from juloserver.application_flow.clients import get_google_play_integrity_client
from juloserver.boost.services import check_scrapped_bank
from juloserver.bpjs.services import (
    Bpjs,
    check_submitted_bpjs,
)
from juloserver.customer_module.models import BankAccountDestination
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.entry_limit.services import EntryLevelLimitProcess
from juloserver.face_recognition.services import CheckFaceSimilarity
from juloserver.fraud_score.tasks import (
    handle_fraud_score_post_application_credit_score,
)
from juloserver.fraud_security.binary_check import process_fraud_binary_check
from juloserver.fraud_security.tasks import check_high_risk_asn
from juloserver.google_analytics.constants import GAEvent
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    FeatureNameConst,
    FeatureSettingMockingProduct,
    MobileFeatureNameConst,
    ExperimentConst,
    OnboardingIdConst,
    WorkflowConst,
    ScoreTag,
)
from juloserver.julo.models import (
    Customer,
    CustomerRemoval,
    Application,
    CreditScoreExperiment,
    ExperimentSetting,
    MobileFeatureSetting,
    FeatureSetting,
    ApplicationNote,
    ApplicationHistory,
    FDCInquiry,
    CreditScore,
    Device,
    Bank,
    Mantri,
    ProductLine,
    Workflow,
    CreditMatrix,
    AffordabilityHistory,
    Experiment,
    Loan,
    FraudModelExperiment,
    ApplicationFieldChange,
    BankStatementSubmit,
    Image,
)
from juloserver.entry_limit.models import (
    EntryLevelLimitConfiguration,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.application_flow.models import (
    ApplicationRiskyCheck,
    MycroftResult,
    MycroftThreshold,
    LevenshteinLog,
    ApplicationPathTagStatus,
    ApplicationPathTag,
)
from juloserver.application_flow.models import (
    EmulatorCheck,
    ApplicationNameBankValidationChange,
)
from juloserver.julo.services import (
    is_allow_to_change_status,
    process_application_status_change,
)
from juloserver.julo.services2.fraud_check import check_suspicious_ip
from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import (
    get_data_from_ana_server,
    post_anaserver,
    execute_after_transaction_safely,
)
from juloserver.julo.workflows import WorkflowAction
from juloserver.julolog.julolog import JuloLog
from juloserver.liveness_detection.services import (
    check_application_liveness_detection_result,
    trigger_passive_liveness,
)
from juloserver.personal_data_verification.services import is_pass_dukcapil_verification_at_x105
from juloserver.application_flow.exceptions import PlayIntegrityDecodeError
from juloserver.application_flow.services2.bank_statement import (
    BankStatementClient,
)

from juloserver.bpjs.services.bpjs_direct import bypass_bpjs_scoring
from juloserver.account.services.credit_limit import (
    get_credit_matrix_type,
    is_inside_premium_area,
    store_related_data_for_generate_credit_limit,
    store_account_property,
    update_related_data_for_generate_credit_limit,
    store_credit_limit_generated,
)
from juloserver.application_form.constants import ApplicationReapplyFields
from juloserver.account.constants import CreditMatrixType
from juloserver.apiv1.exceptions import ResourceNotFound
from juloserver.application_form.models.idfy_models import IdfyVideoCall
from juloserver.monitors.notifications import get_slack_client
from juloserver.apiv2.credit_matrix2 import messages as cm2_messages

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.application_flow.constants import ApplicationStatusEventType
from juloserver.partnership.models import PartnershipApplicationFlag
from juloserver.partnership.crm.services import partnership_pre_check_application
from juloserver.fdc.constants import FDCStatus
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_deletion_email_format,
    get_deletion_nik_format,
    get_deletion_phone_format,
)
from bulk_update.helper import bulk_update
from juloserver.face_recognition.tasks import face_matching_task
from juloserver.customer_module.tasks.customer_related_tasks import (
    sync_customer_data_with_application,
)
from juloserver.julo.exceptions import JuloException

from juloserver.pn_delivery.models import PNBlast, PNDelivery

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.fdc.services import (
    get_and_save_fdc_data,
)
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.pre.services.pre_logger import create_log

juloLogger = JuloLog(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='application_normal')
def handle_iti_ready(application_id: int):
    """
    Run a series of fraud check process after getting ready response from ANA.

    Args:
        application_id (int): Application object id property.
    """
    from juloserver.tokopedia.services.common_service import is_success_revive_by_tokoscore

    change_reason = None
    juloLogger.info({'action': 'handle_iti_ready', 'data': {'application_id': application_id}})
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
            juloLogger.error(
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

    # partnership agent assisted flow
    agent_assisted_app_flag_name = None
    if application.partner:
        agent_assisted_app_flag_name = (
            PartnershipApplicationFlag.objects.filter(application_id=application_id)
            .values_list('name', flat=True)
            .last()
        )

    if agent_assisted_app_flag_name:
        # Stop the application process because need hold the application in x100 and completing data
        is_pre_check_stage = partnership_pre_check_application(
            application, agent_assisted_app_flag_name
        )
        juloLogger.info(
            {
                'action': 'agent_assisted_app_flag_name',
                'message': 'start partnership_pre_check_application',
                'application_status': str(application.status),
                'application': application.id,
                'application_flag_name': agent_assisted_app_flag_name,
                'is_pre_check_stage': is_pre_check_stage,
            }
        )
        if is_pre_check_stage:
            return

    is_bad_history_customer = process_bad_history_customer(application)
    if is_bad_history_customer:
        return

    is_application_detour_by_liveness = check_liveness_detour_workflow_status_path(
        application, ApplicationStatusCodes.FORM_PARTIAL
    )
    liveness_detection_result, liveness_change_reason = True, ''
    if not is_application_detour_by_liveness:
        # run before checking C score
        run_bypass_eligibility_checks(application)
        is_idfy_record = IdfyVideoCall.objects.filter(application_id=application.id).exists()
        if not is_idfy_record:
            trigger_passive_liveness(application)
            (
                liveness_detection_result,
                liveness_change_reason,
            ) = check_application_liveness_detection_result(application)
        else:
            juloLogger.info(
                'handle_iti_ready_skip_liveness|application_id={}'.format(application_id)
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
        # eligible to LBS flow
        submission = BankStatementSubmit.objects.filter(application_id=application.id).last()
        is_fraud = (submission.is_fraud or False) if submission else False

        if pass_binary_check_scoring(application) and not is_fraud:
            import semver
            from juloserver.moengage.services.use_cases import (
                send_user_attributes_to_moengage_for_submit_bank_statement,
            )

            is_available_bank_statement = BankStatementConstant.IS_AVAILABLE_BANK_STATEMENT_ALL
            if semver.match(application.app_version, "<=8.12.0"):
                is_available_bank_statement = (
                    BankStatementConstant.IS_AVAILABLE_BANK_STATEMENT_EMAIL
                )

            bank_statement_client = BankStatementClient(application)
            bank_statement_client.set_tag_to_pending()

            landing_url = bank_statement_client.generate_landing_url()

            send_user_attributes_to_moengage_for_submit_bank_statement.delay(
                application.id, landing_url, is_available_bank_statement
            )

            juloLogger.info(
                {
                    'message': 'handle_iti_ready: Eligible Leverage Bank',
                    'application': application_id,
                }
            )
            return

        # if is_application_detour_by_liveness:
        #     from juloserver.bpjs.services.providers import Brick
        #     from juloserver.bpjs.services.x105_revival import X105Revival
        #
        #     if Brick(application).has_profile:
        #         return X105Revival(application.id).run()

        # shadow score CDE
        from juloserver.application_flow.services2.cde import CDEClient

        CDEClient(application).hit_cde()

        juloLogger.error(
            {
                'message': 'handle_iti_ready: Application score is C',
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
    elif not application.has_suspicious_application_in_device():
        is_submitted_bpjs = check_submitted_bpjs(application)
        is_scrapped_bank = check_scrapped_bank(application)
        is_data_check_passed = False
        if is_scrapped_bank:
            sd_bank_account = SdBankAccount.objects.filter(application_id=application.id).last()
            if sd_bank_account:
                sd_bank_statement_detail = SdBankStatementDetail.objects.filter(
                    sd_bank_account=sd_bank_account
                ).last()
                if sd_bank_statement_detail:
                    is_data_check_passed = True
        if is_submitted_bpjs and not is_data_check_passed:
            is_data_check_passed = Bpjs(application=application).is_scraped

        if is_data_check_passed:
            if JuloOneService.is_high_c_score(application):
                allow_to_change_status = True
                change_reason = JuloOneChangeReason.HIGH_C_SCORE_BY_PASS
            else:
                allow_to_change_status = True
                change_reason = JuloOneChangeReason.MEDIUM_SCORE_BY_PASS
            ga_event = GAEvent.APPLICATION_MD

    # Sending events to Google Analytics
    if ga_event:
        if application.customer.app_instance_id:
            send_event_to_ga_task_async.apply_async(
                kwargs={'customer_id': application.customer.id, 'event': ga_event}
            )
        else:
            juloLogger.info(
                'handle_iti_ready|app_instance_id not found|'
                'application_id={}'.format(application_id)
            )

    if is_experiment_application(application.id, 'ExperimentUwOverhaul'):
        juloLogger.info(
            {
                "application_id": application.id,
                "message": "handle_iti_ready: Goes to experiment application check.",
            }
        )
        get_score = get_credit_score3(application.id, skip_delay_checking=True)
        if get_score.score.upper() != 'C':
            check_face_similarity = CheckFaceSimilarity(application)
            check_face_similarity.check_face_similarity()
            face_matching_task.delay(application.id)
            allow_to_change_status = True
            change_reason = FeatureNameConst.PASS_BINARY_AND_DECISION_CHECK

            # check is revive by tokoscore or not
            is_revive_by_tokoscore = is_success_revive_by_tokoscore(application)
            if is_revive_by_tokoscore:
                old_change_reason = change_reason
                change_reason = JuloOneChangeReason.REVIVE_BY_TOKOSCORE
                juloLogger.info(
                    {
                        'message': 'Tokoscore: Overwrite change_reason by tokoscore process',
                        'application': application_id,
                        'change_reason': change_reason,
                        'old_change_reason': old_change_reason,
                    }
                )

    # When email is whitelisted, then force to x121
    if application.is_julo_one() and is_email_whitelisted_to_force_high_score(application.email):
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            JuloOneChangeReason.FORCE_HIGH_SCORE,
        )
        return

    # Appearantly, shopee whitelist won't executed here. Because the Mycroft configuration
    # is turned off, and moved in ana. When the Mycroft configuration turned back on,
    # it will apply logic here.
    juloLogger.info(
        {
            "application_id": application.id,
            "message": "handle_iti_ready: will execute_shopee_whitelist_after_mycroft, 2nd place",
        }
    )
    mycroft_result, is_mycroft_holdout, whitelist_executed = execute_mycroft(
        application, allow_to_change_status
    )
    if whitelist_executed:
        juloLogger.info({"application_id": application.id, "message": "whitelist executed"})
        return

    if allow_to_change_status and not mycroft_result and not is_mycroft_holdout:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            JuloOneChangeReason.MYCROFT_FAIL,
        )
        return

    # TODO: remove this once 100% migrated, only using this for silent scoring
    process_fraud_binary_check(application, source='handle_iti_ready', use_monnai_handler=True)

    # All Fraud Binary Check.
    # By default, if the check is failed the application status is moved to x133.
    antifraud_api_onboarding_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.ANTIFRAUD_API_ONBOARDING,
        is_active=True,
    )
    if antifraud_api_onboarding_fs and antifraud_api_onboarding_fs.parameters.get('j1_x105', False):
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

            juloLogger.info(
                {
                    'action': 'handle_iti_ready: get_anti_fraud_binary_check_status',
                    'message': 'application failed fraud binary check or already tried',
                    'application': application_id,
                    'binary_check_result': binary_check_result,
                }
            )
            if binary_check_result in retry_binary_check_result:
                if (
                    application.status
                    == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
                ):
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
    if not eligible_to_offline_activation_flow(application):
        check_high_risk_asn(application_id)

    if eligible_to_offline_activation_flow(application):
        juloLogger.info(
            {
                'action': 'handle_iti_ready',
                'message': 'application eligible_to_offline_activation_flow',
                'application': application_id,
            }
        )
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            'pass binary & decision check',
        )
        return

    is_c_score = JuloOneService.is_c_score(application)

    # Waitlist Process
    if not is_c_score and not application.partner:
        process_eligibility_waitlist(application.id)

    # check waitlist status
    is_waitlist = check_waitlist(application)

    # bpjs bypass
    from juloserver.streamlined_communication.services import customer_have_upgrade_case

    mfs = MobileFeatureSetting.objects.get_or_none(feature_name="bpjs_direct", is_active=True)
    if (
        application.is_julo_one_product()
        and mfs
        and not customer_have_upgrade_case(application.customer, application)
    ):
        is_bpjs_found = check_bpjs_found(application)

        if is_bpjs_found and not is_waitlist:
            juloLogger.info(
                {
                    'action': 'handle_iti_ready',
                    'message': 'application bpjs no fdc eligible el',
                    'application': application_id,
                }
            )
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                'eligible no_fdc entrylevel',
            )
            return

        bpjs_bypass = bypass_bpjs_scoring(application, is_waitlist)

        if bpjs_bypass:
            juloLogger.info(
                {
                    'message': 'application have bpjs_bypass',
                    'bpjs_bypass': bpjs_bypass,
                    'application': application_id,
                }
            )
            return

    eligible_el = eligible_entry_level(application_id)
    if eligible_el or is_entry_level_swapin(application):
        change_reason = 'Eligible Entry Level'

    if not is_waitlist:
        if check_good_fdc_bypass(application) and not is_c_score:
            if not eligible_el:
                change_reason = 'Good FDC Bypass'

            juloLogger.info(
                {
                    'action': 'handle_iti_ready',
                    'message': 'application good fdc bypass',
                    'application': application_id,
                    'change_reason': change_reason,
                }
            )
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                change_reason,
            )
            return

        if check_telco_pass(application):
            juloLogger.info(
                {
                    'action': 'handle_iti_ready',
                    'message': 'application telco score',
                    'application': application_id,
                }
            )
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                'Pass Telco Swap In',
            )
            return

    if allow_to_change_status and is_mycroft_holdout:
        new_status_code = ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        if not is_application_detour_by_liveness:
            # if score is not C and failed liveness detection, we will move application to 134
            # status
            new_status_code = failed_liveness_status_code or new_status_code
            change_reason = liveness_change_reason or change_reason

        if is_waitlist:
            new_status_code = ApplicationStatusCodes.WAITING_LIST
            change_reason = 'eligible for waitlist'

        juloLogger.info(
            {
                'message': 'try to run process_application_status_change',
                'application': application_id,
                'allow_to_change_status': allow_to_change_status,
                'mycroft_result': mycroft_result,
                'new_status_code': new_status_code,
                'is_application_detour_by_liveness': is_application_detour_by_liveness,
                'is_waitlist': is_waitlist,
                'change_reason': change_reason if change_reason else None,
            }
        )
        is_moved = process_application_status_change(application.id, new_status_code, change_reason)

        juloLogger.info(
            {
                'message': 'handle_iti_ready process application status change',
                'application': application_id,
                'is_moved': is_moved,
                'change_reason': change_reason if change_reason else None,
                'allow_to_change_status': allow_to_change_status,
                'mycroft_result': mycroft_result,
                'new_status_code': new_status_code,
                'is_application_detour_by_liveness': is_application_detour_by_liveness,
                'is_waitlist': is_waitlist,
            }
        )

        # set session for waiting HSFBP Income Verification process
        if is_moved and new_status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
            from juloserver.application_flow.services import set_session_check_hsfbp

            set_session_check_hsfbp(application)

        # Trigger Optional task after the application status changed
        if new_status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
            handle_fraud_score_post_application_credit_score.delay(application.id)
    else:
        import traceback

        juloLogger.info(
            {
                'message': 'try to run application_tag_tracking_task',
                'allow_to_change_status': allow_to_change_status,
                'mycroft_result': mycroft_result,
                'application': application_id,
            }
        )
        application_tag_tracking_task.delay(
            application_id, None, None, None, 'is_hsfbp', 0, traceback.format_stack()
        )
        application_tag_tracking_task.delay(
            application_id, None, None, None, 'is_mandatory_docs', 1, traceback.format_stack()
        )


def mycroft_check(application, retry: int = 0) -> bool:
    """
    Mycroft fraud model check as optional requirement for passing x105.

    Args:
        application_id (int): Application.id.
        retry (int): Used as retry mechanism.

    Returns:
        (bool): True if passes threshold or fail to retrieve data.
                False if fail to pass threshold.
    """
    # Mycroft's results are ignored if too much retries so return True as if it passes
    if retry == 6:
        return True

    mycroft_score_ana = PdApplicationFraudModelResult.objects.filter(
        application_id=application.id
    ).last()
    if not mycroft_score_ana:
        time.sleep(5)
        return mycroft_check(application, retry + 1)

    mycroft_threshold = MycroftThreshold.objects.get(is_active=True)
    logical_operator = mycroft_threshold.logical_operator
    comparison_functions = {
        "<=": operator.le,
        "<": operator.lt,
        ">=": operator.ge,
        ">": operator.gt,
    }
    result = comparison_functions.get(logical_operator, lambda x, y: False)(
        mycroft_score_ana.pgood, mycroft_threshold.score
    )

    MycroftResult.objects.create(
        mycroft_threshold=mycroft_threshold,
        application=application,
        customer=application.customer,
        score=mycroft_score_ana.pgood,
        result=result,
    )

    return result


def check_mycroft_holdout(application_id):
    today = timezone.localtime(timezone.now()).date()
    mycroft_holdout_experiment = (
        ExperimentSetting.objects.filter(
            code=ExperimentConst.MYCROFT_HOLDOUT_EXPERIMENT, is_active=True
        )
        .filter(
            (Q(start_date__date__lte=today) & Q(end_date__date__gte=today)) | Q(is_permanent=True)
        )
        .last()
    )
    if mycroft_holdout_experiment:
        criteria = mycroft_holdout_experiment.criteria
        if int(str(application_id)[-1:]) in criteria.get('last_digit_app_ids', []):
            app_risky_check = ApplicationRiskyCheck.objects.filter(
                application_id=application_id
            ).last()
            if app_risky_check:
                app_risky_check.is_mycroft_holdout = True
                app_risky_check.save()
            return True
    return False


def execute_mycroft(application, allow_to_change_status: bool):
    juloLogger.info(
        {
            "application_id": application.id,
            "message": "begin execute_shopee_whitelist_after_mycroft",
        }
    )
    mycroft_is_active = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MYCROFT_SCORE_CHECK, is_active=True
    ).exists()

    mycroft_result = True
    is_mycroft_holdout = True
    if allow_to_change_status and mycroft_is_active:
        mycroft_result = mycroft_check(application)
        if not mycroft_result:
            is_mycroft_holdout = check_mycroft_holdout(application.id)

    juloLogger.info(
        {
            "application_id": application.id,
            "message": "end execute_shopee_whitelist_after_mycroft",
            "result": {
                "mycroft_result": mycroft_result,
                "is_mycroft_holdout": is_mycroft_holdout,
            },
        }
    )

    return mycroft_result, is_mycroft_holdout, False


@task(name='update_minimum_income_for_pre_long_form_pop_up')
def update_minimum_income_for_pre_long_form_pop_up():
    mobile_feature_pre_long_form_guidance_pop_up = MobileFeatureSetting.objects.filter(
        feature_name=MobileFeatureNameConst.PRE_LONG_FORM_GUIDANCE_POP_UP,
        is_active=True,
    ).last()
    if not mobile_feature_pre_long_form_guidance_pop_up:
        juloLogger.info(
            {
                'task': 'update_minimum_income_for_pre_long_form_pop_up',
                'info': 'mobile feature setting inactive',
            }
        )
        return
    params = mobile_feature_pre_long_form_guidance_pop_up.parameters
    mvp_side_minimum_salary = params.get('minimum_salary')
    if not mvp_side_minimum_salary:
        juloLogger.info(
            {
                'task': 'update_minimum_income_for_pre_long_form_pop_up',
                'info': 'mobile feature setting minimum_salary params not found',
            }
        )
        return

    data_from_ana = get_data_from_ana_server('/api/amp/v1/get-current-minimum-income/')
    if data_from_ana.status_code not in (200, 201):
        juloLogger.info(
            {
                'task': 'update_minimum_income_for_pre_long_form_pop_up',
                'info': 'not continue because response from ana is {}'.format(
                    data_from_ana.status_code
                ),
            }
        )
        return
    converted_response = data_from_ana.json()
    current_ana_minimum_salary = converted_response['minimum_income']
    if mvp_side_minimum_salary == current_ana_minimum_salary:
        juloLogger.info(
            {
                'task': 'update_minimum_income_for_pre_long_form_pop_up',
                'info': 'skip because minimum income threshold still same',
            }
        )
        return

    mobile_feature_pre_long_form_guidance_pop_up.parameters[
        'minimum_salary'
    ] = current_ana_minimum_salary
    mobile_feature_pre_long_form_guidance_pop_up.save()


@task(queue='application_normal')
def application_tag_tracking_task(
    application_id,
    old_status=None,
    new_status=None,
    change_reason=None,
    tag=None,
    tag_status=None,
    root_stack=None,
):
    if root_stack:
        juloLogger.info(
            {
                "message": "Trace root app tag update",
                "application": application_id,
                "to_tag_status": tag_status,
                "stack": root_stack,
            }
        )

    try:
        application = (
            Application.objects.select_related('customer')
            .select_related('application_status')
            .prefetch_related('applicationhistory_set')
            .get(pk=application_id)
        )
    except Application.objects.model.DoesNotExist:
        return

    # This condition to check that application that can be tagged is only
    # the latest application. We prevent old application to be tagged.
    if not is_allow_to_change_status(application, application.customer):
        return

    tag_tracer = ApplicationTagTracking(application, old_status, new_status, change_reason)
    if tag and tag_status is not None:
        tag_tracer.tracking(tag, tag_status, True)

        # This condition to prevent the latest application
        # status changed automatically when do face recognition check
        if not (tag == 'is_similar_face' and tag_status == 0):
            # re-check for entry level when there is new tag from async task
            entry_level_process = EntryLevelLimitProcess(application_id, application=application)
            entry_level_process.start(application.application_status_id)
    else:
        tag_tracer.tracking()


@task(name='handle_process_bypass_julo_one_at_122')
def handle_process_bypass_julo_one_at_122(application_id):
    from juloserver.application_flow.workflows import process_bypass_julo_one_at_122

    application = Application.objects.get(pk=application_id)
    process_bypass_julo_one_at_122(application)


@task(name='handle_process_bypass_julo_one_at_120')
def handle_process_bypass_julo_one_at_120(application_id):
    from juloserver.application_flow.workflows import process_bypass_julo_one_at_120

    application = Application.objects.get(pk=application_id)
    juloLogger.info(
        {
            "application_id": application_id,
            "application_status": application.status,
            "msg": "Begin task handle_process_bypass_julo_one_at_120",
        }
    )
    process_bypass_julo_one_at_120(application)


@task(queue='application_normal')
def fraud_bpjs_or_bank_scrape_checking(**kwargs):
    application_id = kwargs.get('application_id')
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        juloLogger.error(
            {
                'action': 'fraud_bpjs_or_bank_scrape_checking',
                'error': 'application not found with application id {}'.format(application_id),
            }
        )
        return

    task_retry = fraud_bpjs_or_bank_scrape_checking.request.retries
    retry_times = fraud_bank_scrape_and_bpjs_checking(application)
    if retry_times and not task_retry:
        fraud_bpjs_or_bank_scrape_checking.retry(
            countdown=600, max_retries=retry_times, kwargs={'application_id': application_id}
        )
    if task_retry and task_retry < fraud_bpjs_or_bank_scrape_checking.max_retries:
        fraud_bpjs_or_bank_scrape_checking.retry(
            countdown=600, kwargs={'application_id': application_id}
        )


@task(queue='high')
def suspicious_ip_app_fraud_check(application_id, ip_address, is_suspicious_ip=None):
    application = Application.objects.get(pk=application_id)
    if not is_suspicious_ip:
        if not ip_address:
            juloLogger.warning('can not find ip address|application={}'.format(application.id))
            return

        try:
            is_suspicious_ip = check_suspicious_ip(ip_address)
        except Exception:
            sentry_client.captureException()
            return

    app_risk_check = capture_suspicious_app_risk_check(
        application, 'is_vpn_detected', is_suspicious_ip
    )

    return app_risk_check


@task(queue='application_low')
def move_application_to_x133_for_blacklisted_device(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if application is None:
        juloLogger.warning(
            {
                "action": "move_application_to_x133_for_blacklisted_device, application not found",
                "application_id": application_id,
            }
        )
        return
    process_application_status_change(
        application.id,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        change_reason="Registration from Blacklisted Device",
    )
    return


@task(queue='application_normal')
def reject_application_by_google_play_integrity_task(emulator_check_id):
    emulator_check = EmulatorCheck.objects.filter(id=emulator_check_id).last()
    if emulator_check:
        reject_application_by_google_play_integrity(emulator_check)


@task(
    queue='application_normal',
    bind=True,
    retry_backoff=4,
    retry_jitter=False,
    autoretry_for=(PlayIntegrityDecodeError,),
    max_retries=GooglePlayIntegrityConstants.MAX_NO_OF_RETRIES,
    retry_backoff_max=GooglePlayIntegrityConstants.MAXIMUM_BACKOFF_TIME,
)
def handle_google_play_integrity_decode_request_task(self, application_id, validated_data):
    from juloserver.julo_starter.services.submission_process import check_affordability

    application = Application.objects.get(id=application_id)

    # Adding this check to look for existing entries to eliminate any further retries if
    # a success entry already recorded by any new fresh tries from the FE
    is_jstarter = application.is_julo_starter()
    if is_jstarter:
        existing_emulator_check = EmulatorCheck.objects.filter(application=application).last()
    else:
        existing_emulator_check = EmulatorCheck.objects.filter(
            application=application, error_msg__isnull=True
        ).last()
    if existing_emulator_check:
        return existing_emulator_check

    error_message = validated_data.get('error_message')
    integrity_token = validated_data.get('integrity_token')
    decoded_response = None

    if error_message:
        if not is_jstarter:
            emulator_check = record_google_play_integrity_api_emulator_check_data(
                application, error_message=error_message
            )
            return emulator_check

        # handle for j-starter
        with transaction.atomic():
            # prevent inconsistency data for second-check-status API
            application = Application.objects.select_for_update().get(id=application.id)
            emulator_check = record_google_play_integrity_api_emulator_check_data(
                application, error_message=error_message
            )
            # move to 108 for julo starter application
            if check_affordability(application):
                process_application_status_change(
                    application,
                    new_status_code=ApplicationStatusCodes.OFFER_REGULAR,
                    change_reason='emulator_detection_client_detect_error',
                )

            return emulator_check
    else:
        integrity_client = get_google_play_integrity_client(integrity_token)
        if application.is_julo_starter():
            # retry manual for julostarter application
            decoded_response, decode_error = decode_integrity_token_sync(
                application, integrity_client
            )
        else:
            decoded_response, decode_error = integrity_client.decode_integrity_token()

            # Exponential Backoff Retry as suggested by Google
            # https://cloud.google.com/iot/docs/how-tos/exponential-backoff
            if decode_error:
                juloLogger.warning(
                    {
                        'action': 'decode_integrity_token',
                        'error': str(decode_error),
                        'application_id': str(application_id),
                    }
                )
                error_msg = str(decode_error) + " | Decoding Error"
                emulator_check = record_google_play_integrity_api_emulator_check_data(
                    application, error_message=error_msg
                )
                raise PlayIntegrityDecodeError(error_msg)

        with transaction.atomic():
            emulator_check = record_google_play_integrity_api_emulator_check_data(
                application, decoded_response=decoded_response
            )
            if application.is_julo_starter():
                reject_application_by_google_play_integrity_task(emulator_check.id)
                return emulator_check

            reject_application_by_google_play_integrity_task.delay(emulator_check.id)

    return emulator_check


def decode_integrity_token_sync(application, integrity_client):
    from juloserver.julo_starter.services.services import (
        get_mock_feature_setting,
        mock_emulator_detection_response,
    )
    from juloserver.julo_starter.services.submission_process import check_affordability

    mock_feature = get_mock_feature_setting(
        FeatureNameConst.EMULATOR_DETECTION_MOCK, FeatureSettingMockingProduct.J_STARTER
    )

    max_retries = GooglePlayIntegrityConstants.JS_MAX_NO_OF_RETRIES
    retry_backoff = GooglePlayIntegrityConstants.JS_RETRY_BACKOFF
    retry_count = 0
    error_msg = ''
    emulator_check = None

    while max_retries:
        retry_count += 1
        if mock_feature:
            decoded_response, decode_error = mock_emulator_detection_response(mock_feature)
        else:
            decoded_response, decode_error = integrity_client.decode_integrity_token()

        # Exponential Backoff Retry as suggested by Google
        # https://cloud.google.com/iot/docs/how-tos/exponential-backoff
        if decode_error:
            juloLogger.warning(
                {
                    'action': 'decode_integrity_token',
                    'error': str(decode_error),
                    'application_id': str(application.id),
                }
            )
            error_msg = str(decode_error) + " | Decoding Error"
            emulator_check = record_google_play_integrity_api_emulator_check_data(
                application,
                error_message=error_msg,
                emulator_check=emulator_check,
                save_record=False,
            )
            delay_time = (retry_backoff * 2) ** retry_count
            max_retries -= 1
            if max_retries:
                time.sleep(delay_time)
        else:
            return decoded_response, decode_error

    with transaction.atomic():
        emulator_check.save()
        if check_affordability(application):
            juloLogger.info(
                {
                    "application_id": application.id,
                    "action": "move to 108 with reason sphinx_threshold_passed",
                    "function": "decode_integrity_token_sync",
                    "current_status": application.status,
                }
            )
            process_application_status_change(
                application,
                new_status_code=ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
                change_reason='sphinx_threshold_passed',
            )

    raise PlayIntegrityDecodeError(error_msg)


@task(queue="application_normal")
def revalidate_name_bank_validation(application_id, levenshtein_log_id=None):
    """
    After Levenshtein logic called, we should update the name bank validation to make disbursement
    succeed.
    """
    juloLogger.info(
        {
            "application_id": application_id,
            "levenshtein_log_id": levenshtein_log_id,
            "msg": "Begin task revalidate_name_bank_validation",
        }
    )
    log = None
    if levenshtein_log_id is not None:
        log = LevenshteinLog.objects.get_or_none(pk=levenshtein_log_id)
        if log is None:
            juloLogger.info(
                {
                    "msg": "Trying to get log, but not found",
                    "application_id": application_id,
                    "levenshtein_log_id": levenshtein_log_id,
                }
            )
    if log:
        log.start_async_at = timezone.now()

    application = Application.objects.get(pk=application_id)
    juloLogger.info(
        {
            "msg": "Application record found",
            "application_id": application.id,
        }
    )
    old_name_bank_validation = application.name_bank_validation
    if old_name_bank_validation.validation_status != NameBankValidationStatus.NAME_INVALID:
        juloLogger.info(
            {
                "msg": "Name bank validation status not invalid",
                "application_id": application.id,
                "name_bank_validation": old_name_bank_validation.id,
                "validation_status": old_name_bank_validation.validation_status,
            }
        )
        if log:
            log.end_async_at = timezone.now()
            log.save()
        return

    # call xfers and update the application name bank validation id if success
    workflow_action = WorkflowAction(
        application=application,
        new_status_code=application.application_status,
        old_status_code=application.application_status,
        change_reason='',
        note='',
    )
    new_name_bank_validation = workflow_action.process_validate_bank(
        force_validate=True,
        only_success=True,
        new_data={
            "name_in_bank": old_name_bank_validation.validated_name,
            "bank_name": application.bank_name,
            "bank_account_number": application.bank_account_number,
        },
    )
    juloLogger.info(
        {
            "msg": "process_validate_bank finished",
            "application_id": application.id,
            "name_bank_validation": new_name_bank_validation.id,
            "validation_status": new_name_bank_validation.validation_status,
        }
    )

    # if return succeed insert new record into tracking model changes
    ApplicationNameBankValidationChange.objects.create(
        application_id=application.id,
        old_name_bank_validation_id=old_name_bank_validation.id,
        new_name_bank_validation_id=new_name_bank_validation.id,
    )

    # Update bank account destination get with old old_name_bank_validation
    # and update new with new_name_bank_validation
    bank = BankAccountDestination.objects.filter(
        name_bank_validation=old_name_bank_validation
    ).last()
    if bank:
        bank.update_safely(name_bank_validation=new_name_bank_validation)
        juloLogger.info(
            {
                "application_id": application_id,
                "msg": "Updated bank account destination because Levenshtein",
                "old_bank_account_destination": old_name_bank_validation.id,
                "new_bank_account_destination": new_name_bank_validation.id,
            }
        )

    juloLogger.info(
        {"application_id": application_id, "msg": "End task revalidate_name_bank_validation"}
    )

    if log:
        log.end_async_at = timezone.now()
        log.save()


@task(queue='application_low')
def move_application_to_x133_for_suspicious_email(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if application is None:
        juloLogger.warning(
            {
                "action": "move_application_to_x133_for_suspicious_email, application not found",
                "application_id": application_id,
            }
        )
        return
    process_application_status_change(
        application.id,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        change_reason="Suspicious Email Domain",
    )
    return


@task(queue='application_low')
def run_auto_retrofix_task():
    from juloserver.pre.services.auto_retrofix import run_auto_retrofix

    run_auto_retrofix()


@task(queue='application_low')
def run_entry_level_with_good_fdc_task():
    juloLogger.info(
        {"message": "run_entry_level_with_good_fdc_task()", "status": "entering function"}
    )
    yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()
    juloLogger.info(
        {
            "message": "run_entry_level_with_good_fdc_task()",
            "status": "check yesterday",
            "data": str(yesterday),
        }
    )
    all_applications = ApplicationHistory.objects.filter(
        Q(
            status_new__in=[
                ApplicationStatusCodes.APPLICATION_DENIED,
                ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
            ],
            cdate__date__gte=yesterday,
        )
        | Q(
            status_new=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            status_old=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            cdate__date__gte=yesterday,
        )
    ).values_list('application_id', flat=True)

    applications_filter = (
        Application.objects.filter(
            pk__in=all_applications,
            application_status_id__in=[
                ApplicationStatusCodes.APPLICATION_DENIED,
                ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ],
            product_line_id=ProductLineCodes.J1,
        )
        .exclude(is_deleted=True)
        .values_list('id', flat=True)
    )

    application_fdc = FDCInquiry.objects.filter(
        application_id__in=list(applications_filter),
        status__iexact=FDCStatus.FOUND,
        inquiry_reason='1 - Applying loan via Platform',
    ).values_list('application_id', flat=True)

    application_pcmr = PdCreditModelResult.objects.filter(
        application_id__in=list(application_fdc),
        pgood__gte=0.55,
        pgood__lte=0.75,
    ).values_list('application_id', flat=True)

    if application_pcmr is None:
        juloLogger.warning(
            {
                "action": "run_entry_level_with_good_fdc_task()",
                "status": "application not found",
            }
        )
        return

    juloLogger.info(
        {
            "message": "run_entry_level_with_good_fdc_task()",
            "status": "check count variable application_pcmr",
            "data": len(application_pcmr),
        }
    )

    total_application_checked = 0
    for application_id in application_pcmr:
        try:
            app = Application.objects.get_or_none(pk=application_id)
            if not app:
                continue
            cust = app.customer
            if not cust:
                continue
            latest_app = Application.objects.filter(customer_id=cust.id).last()
            if latest_app.id != app.id:
                continue
            run_entry_level_with_good_fdc_subtask.delay(application_id)
            total_application_checked += 1
        except Exception as e:
            juloLogger.info(
                {
                    "message": "run_entry_level_with_good_fdc_task()",
                    "status": "error happen when lopping",
                    "application_id": application_id,
                    "error": str(e),
                }
            )

    # send result to slack
    send_entry_level_with_good_fdc_result_to_slack(total_application_checked)


def send_entry_level_with_good_fdc_result_to_slack(total_application_checked):
    text = ""
    slack_channel = "#retrofix-automation-onboarding"
    if settings.ENVIRONMENT != 'prod':
        text += " <--{settings.ENVIRONMENT}"
        slack_channel = "#retrofix-automation-onboarding-test"

    # prepare client
    slack_client = get_slack_client()

    # prepare text
    text = (
        '*=== Revive FDC Initiative '
        + timezone.localtime(timezone.now()).strftime("%A, %Y-%m-%d | %H:%M")
        + " ===*\n"
    )
    text += f"*Total Application Checked : {total_application_checked}*"

    # send to slack
    slack_client.api_call("chat.postMessage", channel=slack_channel, text=text)


@task(queue='application_low')
def run_entry_level_with_good_fdc_subtask(app_id: int):
    juloLogger.info(
        {
            "message": "run_entry_level_with_good_fdc_subtask()",
            "status": "start run el",
            "data": app_id,
        }
    )
    app = Application.objects.get_or_none(pk=app_id)
    if not app:
        return
    entry_limit_process = EntryLevelLimitProcess(app.id)
    custom_parameters = {"min_threshold__lte": 1}
    entry_limit_process.start(custom_parameters=custom_parameters, status=app.status)


@task(queue='application_low')
def suspicious_hotspot_app_fraud_check_task(application_id):
    application = Application.objects.get(pk=application_id)
    suspicious_hotspot_app_fraud_check(application)


@task(queue='application_normal')
def revive_mtl_to_j1():
    def construct_reapply_data(last_application, customer, reapply_data):
        # get device and app_version
        device = None
        if not reapply_data.web_version:
            device_id = reapply_data.device_id
            device = Device.objects.get_or_none(id=device_id, customer=customer)
            if device is None:
                raise ResourceNotFound(
                    'MTL revive device_id={} not found, '
                    'customer_id={}'.format(device_id, customer.id)
                )

        last_application_number = last_application.application_number
        if not last_application_number:
            last_application_number = 1
        application_number = last_application_number + 1
        workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
        product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.J1)

        constructed_data = {
            'application_number': application_number,
            'app_version': reapply_data.app_version,
            'web_version': reapply_data.web_version,
            'device': device,
            'customer_id': last_application.customer_id,
            'onboarding_id': OnboardingIdConst.LONGFORM_SHORTENED_ID,
            'product_line': product_line,
            'workflow': workflow,
            'monthly_income': reapply_data.monthly_income,
            'bank_name': reapply_data.bank_name,
            'name_in_bank': reapply_data.name_in_bank,
        }

        for field in ApplicationReapplyFields.JULO_ONE:
            if field == 'id':
                continue
            constructed_data[field] = getattr(reapply_data, field)

        bank_name = constructed_data['bank_name']
        if not Bank.objects.regular_bank().filter(bank_name=bank_name).last():
            constructed_data['bank_name'] = None
            constructed_data['bank_account_number'] = None

        # reapply referral code for mantri
        if last_application.mantri_id:
            referral_code = last_application.referral_code
            constructed_data['referral_code'] = referral_code

            # Set mantri id if referral code is a mantri id
            if referral_code:
                referral_code = referral_code.replace(' ', '')
                mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
                constructed_data['mantri'] = mantri_obj

        return constructed_data

    def generate_customer_pin(customer):
        import random
        from juloserver.pin.services import (
            CustomerPinService,
            does_user_have_pin,
        )

        user = customer.user

        if not does_user_have_pin(user):
            pin = random.randint(000000, 999999)
            user.set_password(pin)
            user.save()

            customer_pin_service = CustomerPinService()
            customer_pin_service.init_customer_pin(user)

    import json
    from juloserver.sdk.services import xls_to_dict
    from juloserver.julo.formulas.underwriting import compute_affordable_payment
    from juloserver.julo.tasks import create_application_checklist_async

    today = timezone.localtime(timezone.now()).date()
    filename = "revive_mtl_{}.csv".format(today)

    filepath = "misc_files/csv/revive_mtl/" + filename
    mtl_data = xls_to_dict(filepath)

    if not mtl_data:
        return

    for mtl in mtl_data[filename]:
        application_id = int(mtl['application_id'])
        mtl_app = Application.objects.filter(id=application_id).last()
        customer = mtl_app.customer

        generate_customer_pin(customer)

        app_version = mtl_app.app_version
        if not app_version:
            from juloserver.apiv2.services import get_latest_app_version

            mtl_app.app_version = get_latest_app_version()

        try:
            data_to_save = construct_reapply_data(mtl_app, customer, mtl_app)
        except ResourceNotFound as e:
            juloLogger.info(
                {
                    'action': 'Revive MTL to J1',
                    'error': str(e),
                    'application_id': mtl_app.id,
                    'customer_id': customer.id,
                }
            )
            continue

        try:
            with transaction.atomic():
                application = Application.objects.create(**data_to_save)
                application.change_status(ApplicationStatusCodes.NAME_VALIDATE_FAILED)
                application.save()
                application.refresh_from_db()
                application_tag_tracking_task(
                    application.id, None, None, 'revive_mtl', 'is_revive_mtl', 1
                )

                customer.update_safely(can_reapply=False, is_active=True)

                create_application_checklist_async.delay(application.id)
                application.refresh_from_db()

                store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

                CreditScore.objects.create(
                    application_id=application.id,
                    score='B-',
                    message='MTL to J1 Revival',
                    credit_matrix_id=int(mtl['credit_matrix_id']),
                    products_str='[1]',
                )

            url = '/api/amp/v1/revive-mtl/'
            post_anaserver(url, json={'application_id': application.id})

            with transaction.atomic():
                # affordability
                julo_one_service = JuloOneService()
                input_params = julo_one_service.construct_params_for_affordability(application)
                compute_affordable_payment(**input_params)

                max_limit, set_limit = 1000000, 1000000
                # Store related data
                account = customer.account_set.last()
                if not account:
                    juloLogger.info(
                        {
                            "message": "Credit limit does not have account",
                            "application_id": application.id,
                            "status": application.status,
                        }
                    )
                    store_related_data_for_generate_credit_limit(application, max_limit, set_limit)
                    application.refresh_from_db()

                    # generate account_property and history
                    store_account_property(application, set_limit)
                else:
                    juloLogger.info(
                        {
                            "message": "Credit limit have account",
                            "application_id": application.id,
                            "status": application.status,
                        }
                    )
                    update_related_data_for_generate_credit_limit(application, max_limit, set_limit)
                credit_matrix = CreditMatrix.objects.filter(id=int(mtl['credit_matrix_id'])).last()
                affordability_history = AffordabilityHistory.objects.filter(
                    application=application
                ).last()
                log_data = {
                    'set_limit': set_limit,
                    'max_limit': max_limit,
                }
                account = customer.account_set.last()

                store_credit_limit_generated(
                    application,
                    account,
                    credit_matrix,
                    affordability_history,
                    max_limit,
                    set_limit,
                    json.dumps(log_data),
                    "MTL to J1 Revival",
                )
        except Exception:
            sentry_client.captureException()
            continue


@task(queue='application_normal')
def run_retroload_bpjs_no_fdc_entry_level():
    from juloserver.julo.services2 import get_appsflyer_service
    from juloserver.account.services.credit_matrix import get_good_score_j1
    from juloserver.ana_api.utils import check_app_cs_v20b
    from juloserver.julo.services2 import get_advance_ai_service
    from juloserver.julo.clients.constants import BlacklistCheckStatus
    from juloserver.apiv2.credit_matrix2 import credit_score_rules2, get_good_score
    from juloserver.apiv2.constants import CreditMatrixV19
    from juloserver.julo.services import (
        is_credit_experiment,
    )

    def store_credit_score_to_db_manual(
        application,
        product_list,
        score,
        message,
        score_tag,
        credit_model_result,
        credit_matrix_version,
        credit_matrix_id=None,
        experimental=False,
        fdc_inquiry_check=None,
    ):
        # get inside premium area
        inside_premium_area = is_inside_premium_area(application)
        if credit_matrix_id:
            credit_matrix = CreditMatrix.objects.get_or_none(id=credit_matrix_id)
            inside_premium_area = (
                inside_premium_area if not credit_matrix else credit_matrix.is_premium_area
            )

        try:
            appsflyer_service = get_appsflyer_service()
            appsflyer_service.info_eligible_product(application, product_list)

            model_version = None
            if credit_model_result:
                model_version = credit_model_result.version

            credit_score = CreditScore.objects.create(
                application_id=application.id,
                score=score,
                products_str=json.dumps(product_list),
                message=message,
                inside_premium_area=inside_premium_area,
                score_tag=score_tag,
                credit_matrix_version=credit_matrix_version,
                model_version=model_version,
                fdc_inquiry_check=fdc_inquiry_check,
                credit_matrix_id=credit_matrix_id,
            )

            if experimental:
                CreditScoreExperiment.objects.create(
                    credit_score=credit_score, experiment=experimental
                )
            if fdc_inquiry_check is not None:
                url = '/api/amp/v1/update-auto-data-check/'
                post_anaserver(
                    url, json={'application_id': application.id, 'is_okay': fdc_inquiry_check}
                )

            return credit_score
        except IntegrityError:
            return CreditScore.objects.get(application_id=application.id)

    def check_get_credit_score3_manual(
        application, minimum_false_rejection=False, skip_delay_checking=False
    ):
        if not isinstance(application, Application):
            application = Application.objects.get(pk=application)

        def get_credit_model_result(application):
            credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
            credit_model_result = PdCreditModelResult.objects.filter(
                application_id=application.id, credit_score_type=credit_score_type
            ).last()

            # get model for web app
            if application.is_julo_one():
                credit_matrix_type = get_credit_matrix_type(application, is_proven=False)

            else:
                if not application.customer.is_repeated:
                    credit_matrix_type = CreditMatrixType.JULO
                else:
                    credit_matrix_type = CreditMatrixType.JULO_REPEAT

            if not credit_model_result:
                credit_model_webapp = PdWebModelResult.objects.filter(
                    application_id=application.id
                ).last()

                if credit_model_webapp:
                    credit_model_result = credit_model_webapp

                    leadgen_partners = dict()
                    feature_setting = FeatureSetting.objects.filter(
                        is_active=True,
                        feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION,
                    ).last()
                    if feature_setting:
                        leadgen_partners = feature_setting.parameters['partners']

                    if (
                        not application.is_partnership_app()
                        and application.partner_name not in leadgen_partners
                    ):
                        credit_matrix_type = CreditMatrixType.WEBAPP

            return credit_matrix_type, credit_model_result

        credit_matrix_type, credit_model_result = get_credit_model_result(application)

        have_experiment = {'is_experiment': False, 'experiment': None}
        partner_name = application.partner_name
        feature_setting = FeatureSetting.objects.filter(
            is_active=True, feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION
        ).last()
        if feature_setting:
            leadgen_partners = feature_setting.parameters['partners']
            if partner_name in leadgen_partners:
                partner_name = PartnerNameConstant.GENERIC
        if application.is_partnership_app():
            partner_name = None
        rules = credit_score_rules2[partner_name]
        bypass_checks = rules['bypass_checks']

        # experiment  remove own_phone binary check
        today = timezone.now().date()
        experiment = Experiment.objects.filter(
            is_active=True,
            date_start__lte=today,
            date_end__gte=today,
            code=ExperimentConst.IS_OWN_PHONE_EXPERIMENT,
        ).last()
        if experiment:
            bypass_checks += ['own_phone']

        bypass_checks += ['special_event']

        if is_customer_has_good_payment_histories(application.customer):
            bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
            bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
        failed_checks = AutoDataCheck.objects.filter(application_id=application.id, is_okay=False)
        failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
        failed_checks = failed_checks.values_list('data_to_check', flat=True)
        failed_checks, fdc_inquiry_check = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            credit_model_result, list(failed_checks), application
        )
        check_order = CreditMatrixV19.BINARY_CHECK_SHORT + CreditMatrixV19.BINARY_CHECK_LONG
        check_rules = rules['checks']
        first_failed_check = None
        score_tag = None
        credit_matrix_version = None

        skip_special_event = SpecialEventSettingHelper().is_no_bypass()

        checking_fraud_email_and_ktp(application, failed_checks)

        for check in check_order:
            if check in failed_checks:
                if check != 'special_event' or not skip_special_event:
                    first_failed_check = check
                    break

        # feature to force credit score to A-
        feature_high_score = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE, is_active=True
        ).last()
        is_premium_area = is_inside_premium_area(application)
        if is_premium_area is None:
            return None
        # force to A- event binary check failed
        if feature_high_score and application.email in feature_high_score.parameters:
            probability_fpd = 0.98
            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )
        elif first_failed_check and credit_model_result:
            if first_failed_check in CreditMatrixV19.BINARY_CHECK_LONG:
                if first_failed_check == 'monthly_income':
                    rule_to_apply = check_rules[first_failed_check]
                else:
                    rule_to_apply = check_rules['long_form_binary_checks']
            else:
                rule_to_apply = check_rules[first_failed_check]

            message = rule_to_apply['message']
            product_list = rule_to_apply['product_lines']
            score = rule_to_apply['score']
            score_tag = ScoreTag.C_FAILED_BINARY
            credit_matrix_version = CreditMatrix.objects.get_current_version(score, score_tag)
        else:
            if not credit_model_result:
                return None

            # check experiment or not
            have_experiment = is_credit_experiment(
                application=application, probability_fpd=credit_model_result.probability_fpd
            )
            if have_experiment['is_experiment']:
                probability_fpd = get_experimental_probability_fpd(
                    have_experiment['experiment'], default=credit_model_result.probability_fpd
                )
            else:
                # try to use pgood value instead of probability_fpd
                probability_fpd = (
                    getattr(credit_model_result, 'pgood', None)
                    or credit_model_result.probability_fpd
                )

            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )

        # add LOC product to product_list if score is 'A-'
        if score == 'A-':
            product_list.append(ProductLineCodes.LOC)

        if score in ['C', '--']:
            return score
        else:
            if application:
                advance_ai_service = get_advance_ai_service()
                blacklist_status = BlacklistCheckStatus.PASS
                blacklist_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.BLACKLIST_CHECK,
                    category="experiment",
                    is_active=True,
                ).last()

                if blacklist_feature:
                    blacklist_status = advance_ai_service.run_blacklist_check(application)

                date_now = timezone.localtime(timezone.now()).date()
                fraud_model_exp_active = Experiment.objects.filter(
                    is_active=True,
                    code=ExperimentConst.FRAUD_MODEL_105,
                    date_start__lte=date_now,
                    date_end__gte=date_now,
                ).last()

                fraud_model_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.FRAUD_MODEL_EXPERIMENT,
                    category="experiment",
                    is_active=True,
                ).last()

                pf_fraud = PdFraudModelResult.objects.filter(application_id=application.id).last()
                fraud_model_check = False
                if pf_fraud and fraud_model_feature:
                    low_probability_fpd = fraud_model_feature.parameters.get('low_probability_fpd')
                    high_probability_fpd = fraud_model_feature.parameters.get(
                        'high_probability_fpd'
                    )
                    if (
                        pf_fraud.probability_fpd
                        and pf_fraud.probability_fpd >= low_probability_fpd
                        and pf_fraud.probability_fpd <= high_probability_fpd
                    ):
                        fraud_model_check = True

                advance_ai_blacklist = False
                if blacklist_status != BlacklistCheckStatus.PASS:
                    advance_ai_blacklist = True

                probability_fpd = 0
                if pf_fraud and pf_fraud.probability_fpd:
                    probability_fpd = pf_fraud.probability_fpd
                fraud_model_exp = FraudModelExperiment.objects.create(
                    application=application,
                    fraud_model_check=not fraud_model_check,
                    advance_ai_blacklist=not advance_ai_blacklist,
                    fraud_model_value=probability_fpd,
                    customer=application.customer,
                )

                if (advance_ai_blacklist or fraud_model_check) and fraud_model_exp_active:
                    fraud_model_exp.is_fraud_experiment_period = True
                    fraud_model_exp.save()

                if (advance_ai_blacklist or fraud_model_check) and not fraud_model_exp_active:
                    score = 'C'
                    product_list = [ProductLineCodes.CTL1]
                    score_tag = ScoreTag.C_FAILED_BLACK_LIST
                return score

    from juloserver.entry_limit.services import EntryLevelLimitProcess

    def generate_get_credit_score3_manual(
        application, minimum_false_rejection=False, skip_delay_checking=False
    ):
        from juloserver.account.services.credit_limit import get_credit_matrix_type
        from juloserver.account.services.credit_matrix import get_good_score_j1
        from juloserver.julo.services import (
            experimentation_false_reject_min_exp,
            is_credit_experiment,
        )

        if not isinstance(application, Application):
            application = Application.objects.get(pk=application)

        def get_credit_model_result(application):
            credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
            credit_model_result = PdCreditModelResult.objects.filter(
                application_id=application.id, credit_score_type=credit_score_type
            ).last()

            # get model for web app
            if application.is_julo_one():
                credit_matrix_type = get_credit_matrix_type(application, is_proven=False)

            else:
                if not application.customer.is_repeated:
                    credit_matrix_type = CreditMatrixType.JULO
                else:
                    credit_matrix_type = CreditMatrixType.JULO_REPEAT

            if not credit_model_result:
                credit_model_webapp = PdWebModelResult.objects.filter(
                    application_id=application.id
                ).last()

                if credit_model_webapp:
                    credit_model_result = credit_model_webapp

                    leadgen_partners = dict()
                    feature_setting = FeatureSetting.objects.filter(
                        is_active=True,
                        feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION,
                    ).last()
                    if feature_setting:
                        leadgen_partners = feature_setting.parameters['partners']

                    if (
                        not application.is_partnership_app()
                        and application.partner_name not in leadgen_partners
                    ):
                        credit_matrix_type = CreditMatrixType.WEBAPP

            return credit_matrix_type, credit_model_result

        credit_score = CreditScore.objects.get_or_none(application_id=application.id)
        credit_matrix_id = None

        if credit_score:
            if not credit_score.model_version:
                _, credit_model_result = get_credit_model_result(application)
                if credit_model_result:
                    credit_score.model_version = credit_model_result.version
                    credit_score.save()
                    credit_score.refresh_from_db()

            if credit_score.score == 'C':
                if minimum_false_rejection:
                    experimentation_false_reject_min_exp(application)
                if is_c_score_in_delay_period(application) and not skip_delay_checking:
                    return None
            return credit_score

        credit_matrix_type, credit_model_result = get_credit_model_result(application)

        have_experiment = {'is_experiment': False, 'experiment': None}
        partner_name = application.partner_name
        feature_setting = FeatureSetting.objects.filter(
            is_active=True, feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION
        ).last()
        if feature_setting:
            leadgen_partners = feature_setting.parameters['partners']
            if partner_name in leadgen_partners:
                partner_name = PartnerNameConstant.GENERIC
        if application.is_partnership_app():
            partner_name = None
        rules = credit_score_rules2[partner_name]
        bypass_checks = rules['bypass_checks']

        # experiment  remove own_phone binary check
        today = timezone.now().date()
        experiment = Experiment.objects.filter(
            is_active=True,
            date_start__lte=today,
            date_end__gte=today,
            code=ExperimentConst.IS_OWN_PHONE_EXPERIMENT,
        ).last()
        if experiment:
            bypass_checks += ['own_phone']

        bypass_checks += ['special_event']

        if is_customer_has_good_payment_histories(application.customer):
            bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
            bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
        failed_checks = AutoDataCheck.objects.filter(application_id=application.id, is_okay=False)
        failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
        failed_checks = failed_checks.values_list('data_to_check', flat=True)
        failed_checks, fdc_inquiry_check = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            credit_model_result, list(failed_checks), application
        )
        check_order = CreditMatrixV19.BINARY_CHECK_SHORT + CreditMatrixV19.BINARY_CHECK_LONG
        check_rules = rules['checks']
        first_failed_check = None
        score_tag = None
        credit_matrix_version = None

        skip_special_event = SpecialEventSettingHelper().is_no_bypass()

        checking_fraud_email_and_ktp(application, failed_checks)

        for check in check_order:
            if check in failed_checks:
                if check != 'special_event' or not skip_special_event:
                    first_failed_check = check
                    break

        # feature to force credit score to A-
        feature_high_score = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE, is_active=True
        ).last()
        is_premium_area = is_inside_premium_area(application)
        if is_premium_area is None:
            return None
        # force to A- event binary check failed
        if feature_high_score and application.email in feature_high_score.parameters:
            probability_fpd = 0.98
            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )
        elif first_failed_check and credit_model_result:
            if first_failed_check in CreditMatrixV19.BINARY_CHECK_LONG:
                if first_failed_check == 'monthly_income':
                    rule_to_apply = check_rules[first_failed_check]
                else:
                    rule_to_apply = check_rules['long_form_binary_checks']
            else:
                rule_to_apply = check_rules[first_failed_check]

            message = rule_to_apply['message']
            product_list = rule_to_apply['product_lines']
            score = rule_to_apply['score']
            score_tag = ScoreTag.C_FAILED_BINARY
            credit_matrix_version = CreditMatrix.objects.get_current_version(score, score_tag)
        else:
            if not credit_model_result:
                return None

            # check experiment or not
            have_experiment = is_credit_experiment(
                application=application, probability_fpd=credit_model_result.probability_fpd
            )
            if have_experiment['is_experiment']:
                probability_fpd = get_experimental_probability_fpd(
                    have_experiment['experiment'], default=credit_model_result.probability_fpd
                )
            else:
                # try to use pgood value instead of probability_fpd
                probability_fpd = (
                    getattr(credit_model_result, 'pgood', None)
                    or credit_model_result.probability_fpd
                )

            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )

        # add LOC product to product_list if score is 'A-'
        if score == 'A-':
            product_list.append(ProductLineCodes.LOC)

        if score in ['C', '--']:
            credit_score = store_credit_score_to_db_manual(
                application,
                product_list,
                score,
                message,
                score_tag,
                credit_model_result,
                credit_matrix_version,
                credit_matrix_id,
                fdc_inquiry_check=fdc_inquiry_check,
            )

            # false reject minimization Experiment
            if minimum_false_rejection:
                experimentation_false_reject_min_exp(application)

            if is_c_score_in_delay_period(application) and not skip_delay_checking:
                return None

            return score
        else:
            if application:
                advance_ai_service = get_advance_ai_service()
                blacklist_status = BlacklistCheckStatus.PASS
                blacklist_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.BLACKLIST_CHECK,
                    category="experiment",
                    is_active=True,
                ).last()

                if blacklist_feature:
                    blacklist_status = advance_ai_service.run_blacklist_check(application)

                date_now = timezone.localtime(timezone.now()).date()
                fraud_model_exp_active = Experiment.objects.filter(
                    is_active=True,
                    code=ExperimentConst.FRAUD_MODEL_105,
                    date_start__lte=date_now,
                    date_end__gte=date_now,
                ).last()

                fraud_model_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.FRAUD_MODEL_EXPERIMENT,
                    category="experiment",
                    is_active=True,
                ).last()

                pf_fraud = PdFraudModelResult.objects.filter(application_id=application.id).last()
                fraud_model_check = False
                if pf_fraud and fraud_model_feature:
                    low_probability_fpd = fraud_model_feature.parameters.get('low_probability_fpd')
                    high_probability_fpd = fraud_model_feature.parameters.get(
                        'high_probability_fpd'
                    )
                    if (
                        pf_fraud.probability_fpd
                        and pf_fraud.probability_fpd >= low_probability_fpd
                        and pf_fraud.probability_fpd <= high_probability_fpd
                    ):
                        fraud_model_check = True

                advance_ai_blacklist = False
                if blacklist_status != BlacklistCheckStatus.PASS:
                    advance_ai_blacklist = True

                probability_fpd = 0
                if pf_fraud and pf_fraud.probability_fpd:
                    probability_fpd = pf_fraud.probability_fpd
                fraud_model_exp = FraudModelExperiment.objects.create(
                    application=application,
                    fraud_model_check=not fraud_model_check,
                    advance_ai_blacklist=not advance_ai_blacklist,
                    fraud_model_value=probability_fpd,
                    customer=application.customer,
                )

                if (advance_ai_blacklist or fraud_model_check) and fraud_model_exp_active:
                    fraud_model_exp.is_fraud_experiment_period = True
                    fraud_model_exp.save()

                if (advance_ai_blacklist or fraud_model_check) and not fraud_model_exp_active:
                    score = 'C'
                    message = cm2_messages['C_score_and_passed_binary_check']
                    product_list = [ProductLineCodes.CTL1]
                    score_tag = ScoreTag.C_FAILED_BLACK_LIST
                    credit_matrix_version = CreditMatrix.objects.get_current_version(
                        score, score_tag
                    )
                return store_credit_score_to_db_manual(
                    application,
                    product_list,
                    score,
                    message,
                    score_tag,
                    credit_model_result,
                    credit_matrix_version,
                    credit_matrix_id,
                    experimental=have_experiment['experiment'],
                    fdc_inquiry_check=fdc_inquiry_check,
                )
                return score

    def check_entry_level_limit_config_manual(pgood):
        low_pgood_id = 103195
        if settings.ENVIRONMENT == 'prod':
            low_pgood_id = 9297
        elif settings.ENVIRONMENT == 'uat':
            low_pgood_id = 137129
        if pgood >= 0.65 and pgood < 0.85:
            entry_level_data = EntryLevelLimitConfiguration.objects.get(pk=low_pgood_id)
        else:
            entry_level_data = None
        return entry_level_data

    def entry_level_limit_force_status_manual(application_id, status, pgood):
        entry_limit_process = EntryLevelLimitProcess(application_id)
        entry_level = check_entry_level_limit_config_manual(pgood)

        if entry_level:
            entry_limit_process.start(force_got_config_id=entry_level.id, status=status)
            return True
        return False

    from juloserver.sdk.services import xls_to_dict

    today = timezone.localtime(timezone.now()).date()
    filename = "revive_bpjs_el_{}.csv".format(today)
    filepath = "misc_files/csv/revive_bpjs_no_fdc/" + filename
    application_data = xls_to_dict(filepath)

    if not application_data:
        return

    juloLogger.info(
        {'action': 'start run_retroload_bpjs_no_fdc_entry_level', 'data': {'filename': filename}}
    )

    approved_application_status = [
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.APPLICATION_DENIED,
    ]

    for application_data in application_data[filename]:
        application_id = int(application_data['application_id'])

        if not application_id:
            continue

        try:
            application = Application.objects.get(pk=application_id)
            latest_application = Application.objects.filter(customer=application.customer).last()
            pcmr = PdCreditModelResult.objects.get(application_id=application.id)
            cs = CreditScore.objects.get_or_none(application=application)
            if not cs:
                get_credit_score3(application.id)
                cs = CreditScore.objects.get(application=application)
            score = cs.score

            if application.application_status_id not in approved_application_status:
                continue
            if pcmr.pgood < 0.65 or pcmr.pgood >= 0.85:
                continue
            if application.id != latest_application.id:
                continue
            if application.partner_id:
                continue

            # re generate score
            if score in ['C', '--']:
                score = check_get_credit_score3_manual(application)

            if score not in ['C', '--']:
                cs.delete()
                score = generate_get_credit_score3_manual(application)
                is_force = entry_level_limit_force_status_manual(
                    application.id, application.status, pcmr.pgood
                )
                if not is_force:
                    cs = CreditScore.objects.get(application=application)
                    cs.delete()
                    score = get_credit_score3(application.id)
                else:
                    ApplicationNote.objects.create(
                        note_text="Revive BPJS No FDC EL",
                        application_id=application.id,
                        application_history_id=None,
                    )

        except Exception:
            sentry_client.captureException()
            continue

        juloLogger.info(
            {
                'action': 'finish run_retroload_bpjs_no_fdc_entry_level',
                'data': {'filename': filename},
            }
        )


@task(queue='application_normal')
def revive_shopee_whitelist_el():
    def check_entry_level_limit_config_manual(pgood):
        low_pgood_id = 103195
        if settings.ENVIRONMENT == 'prod':
            low_pgood_id = 9297
        elif settings.ENVIRONMENT == 'uat':
            low_pgood_id = 137129
        if pgood > 0.65:
            entry_level_data = EntryLevelLimitConfiguration.objects.get(pk=low_pgood_id)
        else:
            entry_level_data = None
        return entry_level_data

    def entry_level_limit_force_status_manual(application_id, status, pgood):
        entry_limit_process = EntryLevelLimitProcess(application_id)
        entry_level = check_entry_level_limit_config_manual(pgood)

        if entry_level:
            entry_limit_process.start(force_got_config_id=entry_level.id, status=status)
            return True

        return False

    configuration = ExperimentSetting.objects.filter(
        code=ExperimentConst.SHOPEE_WHITELIST_EXPERIMENT, is_active=True
    ).last()
    if not configuration:
        return True

    tags = []
    criteria = configuration.criteria
    for criterion in criteria:
        if "tag" in criteria[criterion]:
            tags.append(criteria[criterion]["tag"])

    path_tags = ApplicationPathTagStatus.objects.filter(application_tag__in=tags, status=1)

    application_ids = ApplicationPathTag.objects.filter(
        application_path_tag_status__in=path_tags
    ).values_list('application_id', flat=True)

    applications = Application.objects.filter(
        id__in=application_ids,
        application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    ).order_by('id')[:2000]

    if len(applications) == 0:
        return

    juloLogger.info(
        {
            'action': 'start revive_shopee_whitelist_el',
            'data': {'total_applications': len(applications)},
        }
    )

    success_revived = 0
    for application in applications:
        try:
            latest_history = ApplicationHistory.objects.filter(application=application).last()
            if (
                latest_history.status_old != ApplicationStatusCodes.DOCUMENTS_SUBMITTED
                and latest_history.status_old != ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
            ):
                continue

            latest_application = Application.objects.filter(customer=application.customer).last()
            pcmr = PdCreditModelResult.objects.get(application_id=application.id)
            cs = CreditScore.objects.get_or_none(application=application)
            if not cs:
                get_credit_score3(application.id)
                cs = CreditScore.objects.get(application=application)
            score = cs.score

            if pcmr.pgood <= 0.65:
                continue
            if application.id != latest_application.id:
                continue
            if application.partner_id:
                continue

            if score not in ['C', '--']:
                is_force = entry_level_limit_force_status_manual(
                    application.id, application.status, pcmr.pgood
                )
                if is_force:
                    ApplicationNote.objects.create(
                        note_text="Revive Shopee Whitelist EL",
                        application_id=application.id,
                        application_history_id=None,
                    )
                    success_revived += 1

        except Exception:
            sentry_client.captureException()
            continue

        juloLogger.info(
            {
                'action': 'finish revive_shopee_whitelist_el',
                'data': {'total_revived': success_revived},
            }
        )


def _validate_product_line(app, list_product_line):
    for product_line in list_product_line:
        if type(product_line) == int:
            if app.product_line_id == product_line:
                return True
        if type(product_line) == str and product_line == "none":
            if app.product_line_id is None:
                return True
    return False


def _validate_workflow(app, list_workflow):
    for workflow_id in list_workflow:
        if type(workflow_id) == int:
            if app.workflow_id == workflow_id:
                return True
        if type(workflow_id) == str and workflow_id == "none":
            if app.workflow_id is None:
                return True
    return False


@task(queue='retrofix_normal')
def hit_fdc_for_rejected_customers():
    # get configuration
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.HIT_FDC_FOR_REJECTED_CUSTOMERS, is_active=True
    ).last()
    if not fs:
        return

    card_id = 20521

    # fetch data
    from juloserver.metabase.clients import get_metabase_client

    metabase_client = get_metabase_client()
    juloLogger.info({"task": "hit_fdc_for_rejected_customers", "action": "start hit metabase"})
    response, error = metabase_client.get_metabase_data_json(card_id)
    if error is not None:
        result_error = str(error)
        juloLogger.info(
            {
                "task": "hit_fdc_for_rejected_customers",
                "action": "getting data from metabase",
                "error": result_error,
            }
        )
        return

    # run proceed fdc
    for data in response:
        try:
            application_id = data['application_id']
            if not application_id:
                continue
            application = Application.objects.get_or_none(pk=application_id)

            if not application:
                juloLogger.info(
                    {
                        "task": "hit_fdc_for_rejected_customers",
                        "action": "validate before hit FDC",
                        "error": "application not found",
                        "application_id": application_id,
                    }
                )
                continue

            # validate image_ktp
            ktp_exists = Image.objects.filter(
                image_source=application_id,
                image_type__in=[
                    'raw_ktp_ocr',
                    'ktp_self',
                    'ktp_ocr',
                    'ktp_self_ops',
                    'ktp_self_preview',
                ],
            ).exists()
            if not ktp_exists:
                juloLogger.info(
                    {
                        "task": "hit_fdc_for_rejected_customers",
                        "action": "validate before hit FDC",
                        "error": "ktp image not exists",
                        "application_id": application_id,
                    }
                )
                continue

            already_hit_fdc_june_2025 = FDCInquiry.objects.filter(
                application_id=application_id, cdate__gt=datetime(2025, 6, 24)
            ).exists()
            if already_hit_fdc_june_2025:
                juloLogger.info(
                    {
                        "task": "hit_fdc_for_rejected_customers",
                        "action": "validate before hit FDC",
                        "error": "already hit FDC after 24 june 2025",
                        "application_id": application_id,
                    }
                )
                continue

            customer = application.customer
            with transaction.atomic(using='bureau_db'):
                fdc_inquiry = FDCInquiry.objects.create(
                    nik=customer.nik, customer_id=customer.id, application_id=application.id
                )
                fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': customer.nik}
                execute_after_transaction_safely(
                    lambda: do_hit_fdc_for_rejected_customer.apply_async(
                        (fdc_inquiry_data, 1), countdown=3
                    )
                )

        except JuloException as je:
            juloLogger.info(
                {
                    "task": "hit_fdc_for_rejected_customers",
                    "action": "proceed FDC",
                    "error": str(je),
                    "type_error": "JuloException",
                    "application_id": application_id,
                }
            )
        except Exception as e:
            juloLogger.info(
                {
                    "task": "hit_fdc_for_rejected_customers",
                    "action": "proceed FDC",
                    "error": str(e),
                    "type_error": "Exception",
                    "application_id": application_id,
                }
            )
            sentry_client.captureException()

    juloLogger.info(
        {
            "task": "hit_fdc_for_rejected_customers",
            "action": "Finish",
        }
    )


@task(queue='application_high')
def do_hit_fdc_for_rejected_customer(fdc_inquiry_data: dict, reason, retry_count=0, retry=False):
    try:
        juloLogger.info(
            {
                "function": "do_hit_fdc_for_rejected_customer",
                "action": "call get_and_save_fdc_data",
                "fdc_inquiry_data": fdc_inquiry_data,
                "reason": reason,
                "retry_count": retry_count,
                "retry": retry,
            }
        )
        response = get_and_save_fdc_data(fdc_inquiry_data, reason, retry)
        # save to django shell log
        executor = 'samuel.ricky@julofinance.com'
        create_log(executor, "do_hit_fdc_for_rejected_customer", fdc_inquiry_data, response)

        return True, retry_count
    except FDCServerUnavailableException:
        juloLogger.error(
            {
                "action": "do_hit_fdc_for_rejected_customer",
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

        juloLogger.info(
            {
                "action": "do_hit_fdc_for_rejected_customer",
                "error": "retry fdc request with error: %(e)s" % {'e': e},
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )

    fdc_retry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_FDC_INQUIRY, category="fdc"
    ).last()

    if not fdc_retry_feature or not fdc_retry_feature.is_active:
        juloLogger.info(
            {
                "action": "do_hit_fdc_for_rejected_customer",
                "error": "fdc_retry_feature is not active",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
        return False, retry_count

    params = fdc_retry_feature.parameters
    retry_interval_minutes = params['retry_interval_minutes']
    max_retries = params['max_retries']

    if retry_interval_minutes == 0:

        raise JuloException(
            "Parameter retry_interval_minutes: "
            "%(retry_interval_minutes)s can not be zero value "
            % {'retry_interval_minutes': retry_interval_minutes}
        )
    if not isinstance(retry_interval_minutes, int):
        raise JuloException("Parameter retry_interval_minutes should integer")

    if not isinstance(max_retries, int):
        raise JuloException("Parameter max_retries should integer")
    if max_retries <= 0:
        raise JuloException("Parameter max_retries should greater than zero")

    countdown_seconds = retry_interval_minutes * 60

    if retry_count > max_retries:
        juloLogger.info(
            {
                "action": "do_hit_fdc_for_rejected_customer",
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )

        return False, retry_count

    retry_count += 1

    juloLogger.info(
        {
            'action': 'do_hit_fdc_for_rejected_customer',
            "data": fdc_inquiry_data,
            "extra_data": "retry_count={}|count_down={}".format(retry_count, countdown_seconds),
        }
    )

    do_hit_fdc_for_rejected_customer.apply_async(
        (fdc_inquiry_data, reason, retry_count, retry), countdown=countdown_seconds
    )

    return True, retry_count


@task(queue='retrofix_normal')
def delete_old_customers():
    # get configuration
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SCHEDULER_DELETE_OLD_CUSTOMERS, is_active=True
    ).last()
    if not fs:
        return

    # determined max_delete, card_id, allowed product_line_code, allowed workflow_id, reason
    max_delete = 10
    card_id = 10617
    if settings.ENVIRONMENT == 'prod':
        card_id = 10577
    elif settings.ENVIRONMENT == 'uat':
        card_id = 10618
    allowed_product_line_code = None
    allowed_workflow_id = None
    reason = "delete old customer by sam"

    parameters = fs.parameters
    if parameters:
        if "max_delete" in parameters:
            max_delete = parameters['max_delete']
        if "card_id" in parameters:
            card_id = parameters['card_id']
        if "allowed_product_line_code" in parameters:
            allowed_product_line_code = parameters["allowed_product_line_code"]
        if "allowed_workflow_id" in parameters:
            allowed_workflow_id = parameters["allowed_workflow_id"]
        if "reason" in parameters:
            reason = parameters['reason']

    # fetch data
    from juloserver.metabase.clients import get_metabase_client

    metabase_client = get_metabase_client()

    response, error = metabase_client.get_metabase_data_json(card_id)
    if error is not None:
        result_error = str(error)
        send_delete_old_customers_result_to_slack(0, result_error)
        return

    # prepare the result, reason, executor
    deleted_count = 0

    executor = "samuel.ricky@julofinance.com"
    executor_user = User.objects.filter(email=executor).last()
    today = timezone.localtime(timezone.now()).date()

    # run the deletion
    for data in response:
        try:
            cust_id = data['customer_id']
            if not cust_id:
                continue
            cust = Customer.objects.get(pk=cust_id)
            last_app = cust.last_application
            if (
                last_app and cust.is_active is False and last_app.is_deleted is True
            ):  # if this app already deleted
                continue

            # validate product line code
            if allowed_product_line_code:
                if not _validate_product_line(last_app, allowed_product_line_code):
                    continue

            # validate workflow id
            if allowed_workflow_id:
                if not _validate_workflow(last_app, allowed_workflow_id):
                    continue

            do_new_delete_customer_based_on_api_logic(cust_id, reason, executor_user)
            deleted_count += 1

            if deleted_count >= max_delete:
                break
        except JuloException as je:
            juloLogger.info(
                {'action': 'failed delete on delete_old_customers scheduler', 'error': str(je)}
            )
        except Exception as e:
            juloLogger.info({'action': 'error on delete_old_customers', 'error': str(e)})
            sentry_client.captureException()

    juloLogger.info(
        {
            'action': 'finish delete_old_customers',
            'data': {'upload_date': str(today), 'total_revived': deleted_count},
        }
    )
    send_delete_old_customers_result_to_slack(deleted_count, None)


def do_new_delete_customer_based_on_api_logic(customer_id, reason, executor_user):
    from juloserver.customer_module.utils.utils_crm_v1 import (
        get_active_loan_ids,
    )

    from juloserver.moengage.services.use_cases import (
        send_user_attributes_to_moengage_for_realtime_basis,
    )
    from juloserver.customer_module.services.crm_v1 import (
        deactivate_user,
        update_customer_table_as_inactive,
    )
    from juloserver.account.services.account_related import process_change_account_status
    from juloserver.account.constants import AccountConstant

    customer = Customer.objects.filter(pk=customer_id).exclude(is_active=False, can_reapply=False)
    if not customer.exists():
        raise JuloException("account not found")

    customer = customer.last()

    if customer.is_active is False and customer.can_reapply is False:
        raise JuloException("customer id not found")

    applications = customer.application_set.all()
    application = applications.last()

    juloLogger.info(
        {
            'method': 'do_new_delete_customer_based_on_api_logic',
            "status": "start",
            'data': {
                'is_deleted': True,
                'customer_id': customer.pk,
                'application_id': application.pk,
            },
        }
    )

    loan_ids = get_active_loan_ids(customer)
    nik = customer.get_nik
    phone = customer.get_phone
    email = customer.get_email
    if loan_ids:
        raise JuloException("have active loan")

    juloLogger.info(
        {
            'method': 'do_new_delete_customer_based_on_api_logic',
            "status": "ready to delete",
            'data': {
                'is_deleted': True,
                'customer_id': customer.pk,
                'application_id': application.pk,
            },
        }
    )
    current_cr = CustomerRemoval.objects.filter(user_id=customer.user_id).last()
    with transaction.atomic():
        if current_cr:
            current_cr.delete()
        update_customer_table_as_inactive(
            executor_user,
            customer,
            application,
        )
        deactivate_applications(
            executor_user,
            applications,
        )
        CustomerRemoval.objects.create(
            customer=customer,
            application=application,
            user=customer.user,
            reason=reason,
            added_by=executor_user,
            nik=nik,
            email=email,
            phone=phone,
        )

        deactivate_user(executor_user, customer, nik, phone)
    send_user_attributes_to_moengage_for_realtime_basis.delay(customer.id, 'is_deleted')
    if customer.account:
        process_change_account_status(
            account=customer.account,
            new_status_code=AccountConstant.STATUS_CODE.deactivated,
            change_reason=reason,
        )
    juloLogger.info(
        {
            'method': 'do_new_delete_customer_based_on_api_logic',
            "status": "done",
            'data': {
                'is_deleted': True,
                'customer_id': customer.pk,
                'application_id': application.pk,
            },
        }
    )


def deactivate_applications(agent, applications):
    field_changes = []
    history_changes = []
    for application in applications:
        field_changes.append(
            ApplicationFieldChange(
                application=application,
                field_name='is_deleted',
                old_value=application.is_deleted,
                new_value=True,
                agent=agent,
            )
        )
        application.is_deleted = True

        if application.ktp:
            edited_ktp = get_deletion_nik_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='ktp',
                    old_value=application.ktp,
                    new_value=edited_ktp,
                    agent=agent,
                )
            )
            application.ktp = edited_ktp

        if application.email:
            edited_email = get_deletion_email_format(application.email, application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='email',
                    old_value=application.email,
                    new_value=edited_email,
                    agent=agent,
                )
            )
            application.email = edited_email

        if application.mobile_phone_1:
            edited_phone = get_deletion_phone_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='mobile_phone_1',
                    old_value=application.mobile_phone_1,
                    new_value=edited_phone,
                    agent=agent,
                )
            )
            application.mobile_phone_1 = edited_phone

        history_changes.append(
            ApplicationHistory(
                application=application,
                status_old=application.application_status_id,
                status_new=ApplicationStatusCodes.CUSTOMER_DELETED,
                changed_by=agent,
                change_reason='manual delete by script',
            )
        )
        application.application_status_id = ApplicationStatusCodes.CUSTOMER_DELETED

    ApplicationFieldChange.objects.bulk_create(field_changes)
    ApplicationHistory.objects.bulk_create(history_changes)
    bulk_update(
        applications,
        update_fields=['ktp', 'is_deleted', 'email', 'mobile_phone_1', 'application_status_id'],
    )


def send_delete_old_customers_result_to_slack(total_deleted, error):
    text = ""
    slack_channel = "#retrofix-automation-onboarding"
    if settings.ENVIRONMENT != 'prod':
        text += " <--{settings.ENVIRONMENT}"
        slack_channel = "#retrofix-automation-onboarding-test"

    # prepare client
    slack_client = get_slack_client()

    # prepare text
    text = (
        '*=== Delete Old Customers '
        + timezone.localtime(timezone.now()).strftime("%A, %Y-%m-%d | %H:%M")
        + " ===*\n"
    )
    text += f"*Total Deleted : {total_deleted}*"
    if error is not None:
        text += f"*, Error : {error}*"

    # send to slack
    slack_client.api_call("chat.postMessage", channel=slack_channel, text=text)


@task(queue='application_normal')
def run_task_dynamic_entry_level():
    from juloserver.julo.services2 import get_appsflyer_service
    from juloserver.account.services.credit_matrix import get_good_score_j1
    from juloserver.ana_api.utils import check_app_cs_v20b
    from juloserver.julo.services2 import get_advance_ai_service
    from juloserver.julo.clients.constants import BlacklistCheckStatus
    from juloserver.apiv2.credit_matrix2 import credit_score_rules2, get_good_score
    from juloserver.apiv2.constants import CreditMatrixV19
    from juloserver.julo.services import (
        is_credit_experiment,
    )

    def store_credit_score_to_db_manual(
        application,
        product_list,
        score,
        message,
        score_tag,
        credit_model_result,
        credit_matrix_version,
        credit_matrix_id=None,
        experimental=False,
        fdc_inquiry_check=None,
    ):
        # get inside premium area
        inside_premium_area = is_inside_premium_area(application)
        if credit_matrix_id:
            credit_matrix = CreditMatrix.objects.get_or_none(id=credit_matrix_id)
            inside_premium_area = (
                inside_premium_area if not credit_matrix else credit_matrix.is_premium_area
            )

        try:
            appsflyer_service = get_appsflyer_service()
            appsflyer_service.info_eligible_product(application, product_list)

            model_version = None
            if credit_model_result:
                model_version = credit_model_result.version

            credit_score = CreditScore.objects.create(
                application_id=application.id,
                score=score,
                products_str=json.dumps(product_list),
                message=message,
                inside_premium_area=inside_premium_area,
                score_tag=score_tag,
                credit_matrix_version=credit_matrix_version,
                model_version=model_version,
                fdc_inquiry_check=fdc_inquiry_check,
                credit_matrix_id=credit_matrix_id,
            )

            if experimental:
                CreditScoreExperiment.objects.create(
                    credit_score=credit_score, experiment=experimental
                )
            if fdc_inquiry_check is not None:
                url = '/api/amp/v1/update-auto-data-check/'
                post_anaserver(
                    url, json={'application_id': application.id, 'is_okay': fdc_inquiry_check}
                )

            return credit_score
        except IntegrityError:
            return CreditScore.objects.get(application_id=application.id)

    def check_get_credit_score3_manual(
        application, minimum_false_rejection=False, skip_delay_checking=False
    ):
        if not isinstance(application, Application):
            application = Application.objects.get(pk=application)

        def get_credit_model_result(application):
            credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
            credit_model_result = PdCreditModelResult.objects.filter(
                application_id=application.id, credit_score_type=credit_score_type
            ).last()

            # get model for web app
            if application.is_julo_one():
                credit_matrix_type = get_credit_matrix_type(application, is_proven=False)

            else:
                if not application.customer.is_repeated:
                    credit_matrix_type = CreditMatrixType.JULO
                else:
                    credit_matrix_type = CreditMatrixType.JULO_REPEAT

            if not credit_model_result:
                credit_model_webapp = PdWebModelResult.objects.filter(
                    application_id=application.id
                ).last()

                if credit_model_webapp:
                    credit_model_result = credit_model_webapp

                    leadgen_partners = dict()
                    feature_setting = FeatureSetting.objects.filter(
                        is_active=True,
                        feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION,
                    ).last()
                    if feature_setting:
                        leadgen_partners = feature_setting.parameters['partners']

                    if (
                        not application.is_partnership_app()
                        and application.partner_name not in leadgen_partners
                    ):
                        credit_matrix_type = CreditMatrixType.WEBAPP

            return credit_matrix_type, credit_model_result

        credit_matrix_type, credit_model_result = get_credit_model_result(application)

        have_experiment = {'is_experiment': False, 'experiment': None}
        partner_name = application.partner_name
        feature_setting = FeatureSetting.objects.filter(
            is_active=True, feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION
        ).last()
        if feature_setting:
            leadgen_partners = feature_setting.parameters['partners']
            if partner_name in leadgen_partners:
                partner_name = PartnerNameConstant.GENERIC
        if application.is_partnership_app():
            partner_name = None
        rules = credit_score_rules2[partner_name]
        bypass_checks = rules['bypass_checks']

        # experiment  remove own_phone binary check
        today = timezone.now().date()
        experiment = Experiment.objects.filter(
            is_active=True,
            date_start__lte=today,
            date_end__gte=today,
            code=ExperimentConst.IS_OWN_PHONE_EXPERIMENT,
        ).last()
        if experiment:
            bypass_checks += ['own_phone']

        bypass_checks += ['special_event']

        if is_customer_has_good_payment_histories(application.customer):
            bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
            bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
        failed_checks = AutoDataCheck.objects.filter(application_id=application.id, is_okay=False)
        failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
        failed_checks = failed_checks.values_list('data_to_check', flat=True)
        failed_checks, fdc_inquiry_check = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            credit_model_result, list(failed_checks), application
        )
        check_order = CreditMatrixV19.BINARY_CHECK_SHORT + CreditMatrixV19.BINARY_CHECK_LONG
        check_rules = rules['checks']
        first_failed_check = None
        score_tag = None
        credit_matrix_version = None

        skip_special_event = SpecialEventSettingHelper().is_no_bypass()

        checking_fraud_email_and_ktp(application, failed_checks)

        for check in check_order:
            if check in failed_checks:
                if check != 'special_event' or not skip_special_event:
                    first_failed_check = check
                    break

        # feature to force credit score to A-
        feature_high_score = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE, is_active=True
        ).last()
        is_premium_area = is_inside_premium_area(application)
        if is_premium_area is None:
            return None
        # force to A- event binary check failed
        if feature_high_score and application.email in feature_high_score.parameters:
            probability_fpd = 0.98
            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )
        elif first_failed_check and credit_model_result:
            if first_failed_check in CreditMatrixV19.BINARY_CHECK_LONG:
                if first_failed_check == 'monthly_income':
                    rule_to_apply = check_rules[first_failed_check]
                else:
                    rule_to_apply = check_rules['long_form_binary_checks']
            else:
                rule_to_apply = check_rules[first_failed_check]

            message = rule_to_apply['message']
            product_list = rule_to_apply['product_lines']
            score = rule_to_apply['score']
            score_tag = ScoreTag.C_FAILED_BINARY
            credit_matrix_version = CreditMatrix.objects.get_current_version(score, score_tag)
        else:
            if not credit_model_result:
                return None

            # check experiment or not
            have_experiment = is_credit_experiment(
                application=application, probability_fpd=credit_model_result.probability_fpd
            )
            if have_experiment['is_experiment']:
                probability_fpd = get_experimental_probability_fpd(
                    have_experiment['experiment'], default=credit_model_result.probability_fpd
                )
            else:
                # try to use pgood value instead of probability_fpd
                probability_fpd = (
                    getattr(credit_model_result, 'pgood', None)
                    or credit_model_result.probability_fpd
                )

            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )

        # add LOC product to product_list if score is 'A-'
        if score == 'A-':
            product_list.append(ProductLineCodes.LOC)

        if score in ['C', '--']:
            return score
        else:
            if application:
                advance_ai_service = get_advance_ai_service()
                blacklist_status = BlacklistCheckStatus.PASS
                blacklist_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.BLACKLIST_CHECK,
                    category="experiment",
                    is_active=True,
                ).last()

                if blacklist_feature:
                    blacklist_status = advance_ai_service.run_blacklist_check(application)

                date_now = timezone.localtime(timezone.now()).date()
                fraud_model_exp_active = Experiment.objects.filter(
                    is_active=True,
                    code=ExperimentConst.FRAUD_MODEL_105,
                    date_start__lte=date_now,
                    date_end__gte=date_now,
                ).last()

                fraud_model_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.FRAUD_MODEL_EXPERIMENT,
                    category="experiment",
                    is_active=True,
                ).last()

                pf_fraud = PdFraudModelResult.objects.filter(application_id=application.id).last()
                fraud_model_check = False
                if pf_fraud and fraud_model_feature:
                    low_probability_fpd = fraud_model_feature.parameters.get('low_probability_fpd')
                    high_probability_fpd = fraud_model_feature.parameters.get(
                        'high_probability_fpd'
                    )
                    if (
                        pf_fraud.probability_fpd
                        and pf_fraud.probability_fpd >= low_probability_fpd
                        and pf_fraud.probability_fpd <= high_probability_fpd
                    ):
                        fraud_model_check = True

                advance_ai_blacklist = False
                if blacklist_status != BlacklistCheckStatus.PASS:
                    advance_ai_blacklist = True

                probability_fpd = 0
                if pf_fraud and pf_fraud.probability_fpd:
                    probability_fpd = pf_fraud.probability_fpd
                fraud_model_exp = FraudModelExperiment.objects.create(
                    application=application,
                    fraud_model_check=not fraud_model_check,
                    advance_ai_blacklist=not advance_ai_blacklist,
                    fraud_model_value=probability_fpd,
                    customer=application.customer,
                )

                if (advance_ai_blacklist or fraud_model_check) and fraud_model_exp_active:
                    fraud_model_exp.is_fraud_experiment_period = True
                    fraud_model_exp.save()

                if (advance_ai_blacklist or fraud_model_check) and not fraud_model_exp_active:
                    score = 'C'
                    product_list = [ProductLineCodes.CTL1]
                    score_tag = ScoreTag.C_FAILED_BLACK_LIST
                return score

    from juloserver.entry_limit.services import EntryLevelLimitProcess

    def generate_get_credit_score3_manual(
        application, minimum_false_rejection=False, skip_delay_checking=False
    ):
        from juloserver.account.services.credit_limit import get_credit_matrix_type
        from juloserver.account.services.credit_matrix import get_good_score_j1
        from juloserver.julo.services import (
            experimentation_false_reject_min_exp,
            is_credit_experiment,
        )

        if not isinstance(application, Application):
            application = Application.objects.get(pk=application)

        def get_credit_model_result(application):
            credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
            credit_model_result = PdCreditModelResult.objects.filter(
                application_id=application.id, credit_score_type=credit_score_type
            ).last()

            # get model for web app
            if application.is_julo_one():
                credit_matrix_type = get_credit_matrix_type(application, is_proven=False)

            else:
                if not application.customer.is_repeated:
                    credit_matrix_type = CreditMatrixType.JULO
                else:
                    credit_matrix_type = CreditMatrixType.JULO_REPEAT

            if not credit_model_result:
                credit_model_webapp = PdWebModelResult.objects.filter(
                    application_id=application.id
                ).last()

                if credit_model_webapp:
                    credit_model_result = credit_model_webapp

                    leadgen_partners = dict()
                    feature_setting = FeatureSetting.objects.filter(
                        is_active=True,
                        feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION,
                    ).last()
                    if feature_setting:
                        leadgen_partners = feature_setting.parameters['partners']

                    if (
                        not application.is_partnership_app()
                        and application.partner_name not in leadgen_partners
                    ):
                        credit_matrix_type = CreditMatrixType.WEBAPP

            return credit_matrix_type, credit_model_result

        credit_score = CreditScore.objects.get_or_none(application_id=application.id)
        credit_matrix_id = None

        if credit_score:
            if not credit_score.model_version:
                _, credit_model_result = get_credit_model_result(application)
                if credit_model_result:
                    credit_score.model_version = credit_model_result.version
                    credit_score.save()
                    credit_score.refresh_from_db()

            if credit_score.score == 'C':
                if minimum_false_rejection:
                    experimentation_false_reject_min_exp(application)
                if is_c_score_in_delay_period(application) and not skip_delay_checking:
                    return None
            return credit_score

        credit_matrix_type, credit_model_result = get_credit_model_result(application)

        have_experiment = {'is_experiment': False, 'experiment': None}
        partner_name = application.partner_name
        feature_setting = FeatureSetting.objects.filter(
            is_active=True, feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION
        ).last()
        if feature_setting:
            leadgen_partners = feature_setting.parameters['partners']
            if partner_name in leadgen_partners:
                partner_name = PartnerNameConstant.GENERIC
        if application.is_partnership_app():
            partner_name = None
        rules = credit_score_rules2[partner_name]
        bypass_checks = rules['bypass_checks']

        # experiment  remove own_phone binary check
        today = timezone.now().date()
        experiment = Experiment.objects.filter(
            is_active=True,
            date_start__lte=today,
            date_end__gte=today,
            code=ExperimentConst.IS_OWN_PHONE_EXPERIMENT,
        ).last()
        if experiment:
            bypass_checks += ['own_phone']

        bypass_checks += ['special_event']

        if is_customer_has_good_payment_histories(application.customer):
            bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
            bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
        failed_checks = AutoDataCheck.objects.filter(application_id=application.id, is_okay=False)
        failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
        failed_checks = failed_checks.values_list('data_to_check', flat=True)
        failed_checks, fdc_inquiry_check = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            credit_model_result, list(failed_checks), application
        )
        check_order = CreditMatrixV19.BINARY_CHECK_SHORT + CreditMatrixV19.BINARY_CHECK_LONG
        check_rules = rules['checks']
        first_failed_check = None
        score_tag = None
        credit_matrix_version = None

        skip_special_event = SpecialEventSettingHelper().is_no_bypass()

        checking_fraud_email_and_ktp(application, failed_checks)

        for check in check_order:
            if check in failed_checks:
                if check != 'special_event' or not skip_special_event:
                    first_failed_check = check
                    break

        # feature to force credit score to A-
        feature_high_score = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE, is_active=True
        ).last()
        is_premium_area = is_inside_premium_area(application)
        if is_premium_area is None:
            return None
        # force to A- event binary check failed
        if feature_high_score and application.email in feature_high_score.parameters:
            probability_fpd = 0.98
            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )
        elif first_failed_check and credit_model_result:
            if first_failed_check in CreditMatrixV19.BINARY_CHECK_LONG:
                if first_failed_check == 'monthly_income':
                    rule_to_apply = check_rules[first_failed_check]
                else:
                    rule_to_apply = check_rules['long_form_binary_checks']
            else:
                rule_to_apply = check_rules[first_failed_check]

            message = rule_to_apply['message']
            product_list = rule_to_apply['product_lines']
            score = rule_to_apply['score']
            score_tag = ScoreTag.C_FAILED_BINARY
            credit_matrix_version = CreditMatrix.objects.get_current_version(score, score_tag)
        else:
            if not credit_model_result:
                return None

            # check experiment or not
            have_experiment = is_credit_experiment(
                application=application, probability_fpd=credit_model_result.probability_fpd
            )
            if have_experiment['is_experiment']:
                probability_fpd = get_experimental_probability_fpd(
                    have_experiment['experiment'], default=credit_model_result.probability_fpd
                )
            else:
                # try to use pgood value instead of probability_fpd
                probability_fpd = (
                    getattr(credit_model_result, 'pgood', None)
                    or credit_model_result.probability_fpd
                )

            repeat_time = (
                Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
            )
            custom_matrix_parameters = {'repeat_time': repeat_time}
            if application.job_industry:
                custom_matrix_parameters['job_industry'] = application.job_industry
            if application.is_julo_one():
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score_j1(
                    probability_fpd, application.job_type, is_premium_area, credit_matrix_type
                )
            else:
                (
                    score,
                    product_list,
                    message,
                    score_tag,
                    credit_matrix_version,
                    credit_matrix_id,
                ) = get_good_score(
                    probability_fpd,
                    application.job_type,
                    custom_matrix_parameters,
                    is_premium_area,
                    credit_matrix_type,
                )

        # add LOC product to product_list if score is 'A-'
        if score == 'A-':
            product_list.append(ProductLineCodes.LOC)

        if score in ['C', '--']:
            credit_score = store_credit_score_to_db_manual(
                application,
                product_list,
                score,
                message,
                score_tag,
                credit_model_result,
                credit_matrix_version,
                credit_matrix_id,
                fdc_inquiry_check=fdc_inquiry_check,
            )

            # false reject minimization Experiment
            if minimum_false_rejection:
                experimentation_false_reject_min_exp(application)

            if is_c_score_in_delay_period(application) and not skip_delay_checking:
                return None

            return score
        else:
            if application:
                advance_ai_service = get_advance_ai_service()
                blacklist_status = BlacklistCheckStatus.PASS
                blacklist_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.BLACKLIST_CHECK,
                    category="experiment",
                    is_active=True,
                ).last()

                if blacklist_feature:
                    blacklist_status = advance_ai_service.run_blacklist_check(application)

                date_now = timezone.localtime(timezone.now()).date()
                fraud_model_exp_active = Experiment.objects.filter(
                    is_active=True,
                    code=ExperimentConst.FRAUD_MODEL_105,
                    date_start__lte=date_now,
                    date_end__gte=date_now,
                ).last()

                fraud_model_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.FRAUD_MODEL_EXPERIMENT,
                    category="experiment",
                    is_active=True,
                ).last()

                pf_fraud = PdFraudModelResult.objects.filter(application_id=application.id).last()
                fraud_model_check = False
                if pf_fraud and fraud_model_feature:
                    low_probability_fpd = fraud_model_feature.parameters.get('low_probability_fpd')
                    high_probability_fpd = fraud_model_feature.parameters.get(
                        'high_probability_fpd'
                    )
                    if (
                        pf_fraud.probability_fpd
                        and pf_fraud.probability_fpd >= low_probability_fpd
                        and pf_fraud.probability_fpd <= high_probability_fpd
                    ):
                        fraud_model_check = True

                advance_ai_blacklist = False
                if blacklist_status != BlacklistCheckStatus.PASS:
                    advance_ai_blacklist = True

                probability_fpd = 0
                if pf_fraud and pf_fraud.probability_fpd:
                    probability_fpd = pf_fraud.probability_fpd
                fraud_model_exp = FraudModelExperiment.objects.create(
                    application=application,
                    fraud_model_check=not fraud_model_check,
                    advance_ai_blacklist=not advance_ai_blacklist,
                    fraud_model_value=probability_fpd,
                    customer=application.customer,
                )

                if (advance_ai_blacklist or fraud_model_check) and fraud_model_exp_active:
                    fraud_model_exp.is_fraud_experiment_period = True
                    fraud_model_exp.save()

                if (advance_ai_blacklist or fraud_model_check) and not fraud_model_exp_active:
                    score = 'C'
                    message = cm2_messages['C_score_and_passed_binary_check']
                    product_list = [ProductLineCodes.CTL1]
                    score_tag = ScoreTag.C_FAILED_BLACK_LIST
                    credit_matrix_version = CreditMatrix.objects.get_current_version(
                        score, score_tag
                    )
                return store_credit_score_to_db_manual(
                    application,
                    product_list,
                    score,
                    message,
                    score_tag,
                    credit_model_result,
                    credit_matrix_version,
                    credit_matrix_id,
                    experimental=have_experiment['experiment'],
                    fdc_inquiry_check=fdc_inquiry_check,
                )
                return score

    def check_entry_level_limit_config_manual(pgood):
        low_pgood_id = 103195
        high_pgood_id = 103196
        if settings.ENVIRONMENT == 'prod':
            low_pgood_id = 9297
            high_pgood_id = 9298
        elif settings.ENVIRONMENT == 'uat':
            low_pgood_id = 137129
            high_pgood_id = 137130
        if pgood >= 0.90:
            entry_level_data = EntryLevelLimitConfiguration.objects.get(pk=high_pgood_id)
        elif pgood >= 0.65:
            entry_level_data = EntryLevelLimitConfiguration.objects.get(pk=low_pgood_id)
        else:
            entry_level_data = None
        return entry_level_data

    def entry_level_limit_force_status_manual(application_id, status, pgood):
        entry_limit_process = EntryLevelLimitProcess(application_id)
        entry_level = check_entry_level_limit_config_manual(pgood)

        if entry_level:
            entry_limit_process.start(force_got_config_id=entry_level.id, status=status)
            return True
        return False

    from juloserver.metabase.clients import get_metabase_client
    from juloserver.application_form.services.application_service import (
        get_main_application_after_submit_form,
    )

    metabase_client = get_metabase_client()
    card_id = 9950
    if settings.ENVIRONMENT == 'prod':
        card_id = 9993
    elif settings.ENVIRONMENT == 'uat':
        card_id = 10000

    response, error = metabase_client.get_metabase_data_json(card_id)
    today = timezone.localtime(timezone.now()).date()

    juloLogger.info(
        {'action': 'start run_task_dynamic_entry_level', 'data': {'upload_date': str(today)}}
    )

    if error:
        juloLogger.info(
            {'action': 'error run_task_dynamic_entry_level', 'data': {'error_message': error}}
        )
        return

    result = []
    for data in response:
        try:
            if data['upload_date'] != str(today):
                continue

            application = Application.objects.get(pk=data['application_id'])
            latest_application = get_main_application_after_submit_form(application.customer)
            pcmr = PdCreditModelResult.objects.get(application_id=application.id)
            cs = CreditScore.objects.get(application=application)
            fdc = FDCInquiry.objects.filter(
                application_id=application.id, status__iexact=FDCStatus.FOUND
            ).last()
            if not fdc and pcmr.pgood <= 0.75 and pcmr.pgood >= 0.65:
                continue
            if application.id != latest_application[0].id:
                continue
            if cs.score not in ['C', '--']:
                continue
            if application.partner_id:
                continue

            score = cs.score
            approved_application_status = [
                ApplicationStatusCodes.FORM_PARTIAL,
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ]
            if (
                application.application_status_id in approved_application_status
                and pcmr.pgood >= 0.65
            ):
                is_from_105 = True
                if application.application_status_id == 106:
                    latest_history = ApplicationHistory.objects.filter(
                        application_id=application.id
                    ).last()
                    is_from_105 = False
                    if latest_history.status_old == 105:
                        is_from_105 = True
                if is_from_105:
                    score = check_get_credit_score3_manual(application.id)

            if score not in ['C', '--']:
                cs.delete()
                score = generate_get_credit_score3_manual(application.id, True)
                is_force = entry_level_limit_force_status_manual(
                    application.id, application.status, pcmr.pgood
                )
                if not is_force:
                    cs = CreditScore.objects.get(application=application)
                    cs.delete()
                    score = get_credit_score3(application.id)
                result.append(application.id)
                ApplicationNote.objects.create(
                    note_text="EL Recession Mitigation Revive",
                    application_id=application.id,
                    application_history_id=None,
                )

        except Exception as e:
            sentry_client.captureException()
            juloLogger.info({'action': 'error on run_task_dynamic_entry_level', 'error': str(e)})

    juloLogger.info(
        {
            'action': 'finish run_task_dynamic_entry_level',
            'data': {'upload_date': str(today), 'total_revived': len(result)},
        }
    )

    send_el_recession_mitigation_result_to_slack(len(result))


def send_el_recession_mitigation_result_to_slack(total_revived):
    text = ""
    slack_channel = "#retrofix-automation-onboarding"
    if settings.ENVIRONMENT != 'prod':
        text += " <--{settings.ENVIRONMENT}"
        slack_channel = "#retrofix-automation-onboarding-test"

    # prepare client
    slack_client = get_slack_client()

    # prepare text
    text = (
        '*=== EL Recession Mitigation Revive '
        + timezone.localtime(timezone.now()).strftime("%A, %Y-%m-%d | %H:%M")
        + " ===*\n"
    )
    text += f"*Total Revived : {total_revived}*"

    # send to slack
    slack_client.api_call("chat.postMessage", channel=slack_channel, text=text)


@task(queue='application_normal')
def task_daily_bank_statement_process():
    application_path_tag_status = ApplicationPathTagStatus.objects.filter(
        application_tag=BankStatementClient.APPLICATION_TAG,
        status=BankStatementClient.TAG_STATUS_PENDING,
    ).last()
    applications = ApplicationPathTag.objects.filter(
        application_path_tag_status=application_path_tag_status
    ).values('application_id')
    for application in applications:
        try:
            if Application.objects.filter(
                id=application['application_id'],
                application_status=ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
            ).exists():
                process_application_status_change(
                    application['application_id'],
                    ApplicationStatusCodes.APPLICATION_DENIED,
                    'bank statement not submitted',
                )
        except Exception as e:
            juloLogger.error(
                {
                    'message': 'task_daily_bank_statement_process_not_submitted_error',
                    'error': str(e),
                    'application_id': application['application_id'],
                }
            )

    application_ids = Customer.objects.filter(
        application_status=135, workflow_id=7, partner_id__isnull=True
    ).values_list('current_application_id', flat=True)
    chunk_size = 1000
    for i in range(0, len(application_ids), chunk_size):
        last_id = i + chunk_size
        chunk_ids = application_ids[i:last_id]
        applications = Application.objects.filter(id__in=chunk_ids)

        for application in applications:
            if not application.is_regular_julo_one():
                continue

            try:
                action = JuloOneWorkflowAction(application, None, None, None, None)
                is_available_bank_statement = action.need_check_bank_statement()
                if is_available_bank_statement:
                    action.process_bank_statement_revival(is_available_bank_statement)
            except Exception as e:
                juloLogger.error(
                    {
                        'message': 'task_daily_bank_statement_process_revive_error',
                        'error': str(e),
                        'application_id': application.id,
                    }
                )


@task(queue='application_low')
def extract_perfios_report(application_id, transaction_id: str):
    from juloserver.application_flow.services2.bank_statement import Perfios

    perfios = Perfios(Application.objects.get(pk=application_id))
    perfios.extract_zip_and_decide(transaction_id)


@task(queue='initial_retroload_dragon_ball')
def initial_retroload_dragon_ball():
    # fetch data
    from juloserver.metabase.clients import get_metabase_client

    metabase_client = get_metabase_client()

    card_id = 12832
    if settings.ENVIRONMENT == 'staging':
        card_id = 13415
    elif settings.ENVIRONMENT == 'uat':
        card_id = 13436

    response, error = metabase_client.get_metabase_data_json(card_id, 3600)
    if error is not None:
        result_error = str(error)
        send_initial_retroload_dragon_ball_to_slack(0, result_error)
        return

    # prepare the result, reason, executor
    result = []
    today = timezone.localtime(timezone.now())
    batch_datetime = "Env: " + settings.ENVIRONMENT + ", Time: " + str(today)
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.TECH_INITIAL_RETROLOAD_DRAGON_BALL, is_active=True
    ).last()

    if not fs:
        return

    # run the initial retroload
    send_initial_retroload_dragon_ball_to_slack(
        len(result), None, "Start initial_retroload_dragon_ball for batch: " + batch_datetime
    )
    for data in response:
        try:
            cust_id = data['customer_id']
            sync_customer_data_with_application.delay(cust_id)
            result.append(cust_id)
            time.sleep(0.05)  # 50 milliseconds

            if len(result) % 100 == 0:
                send_initial_retroload_dragon_ball_to_slack(
                    len(result),
                    None,
                    "Batch: "
                    + batch_datetime
                    + "; Iteration No: "
                    + str(len(result) / 100)
                    + "; Total: "
                    + str(len(result)),
                )
        except Exception as e:
            juloLogger.info({'action': 'error on initial_retroload_dragon_ball', 'error': str(e)})
            send_initial_retroload_dragon_ball_to_slack(
                len(result),
                None,
                "Error for batch: " + batch_datetime + "; Error message: " + str(e),
            )
            send_initial_retroload_dragon_ball_to_slack(len(result), e)
            sentry_client.captureException()

    juloLogger.info(
        {
            'action': 'finish initial_retroload_dragon_ball',
            'data': {'retroload_date': batch_datetime, 'total_retroloaded': len(result)},
        }
    )
    send_initial_retroload_dragon_ball_to_slack(
        len(result), None, "finish initial_retroload_dragon_ball: " + batch_datetime
    )


def send_initial_retroload_dragon_ball_to_slack(total_customer, error, additional_text=None):
    text = ""
    slack_channel = "#initial_retroload_dragon_ball_prod"
    if settings.ENVIRONMENT != 'prod':
        text += " <--{settings.ENVIRONMENT}"
        slack_channel = "#initial_retroload_dragon_ball_test"

    # prepare client
    slack_client = get_slack_client()

    # prepare text
    text = (
        '*=== initial_retroload_dragon_ball_project'
        + timezone.localtime(timezone.now()).strftime("%A, %Y-%m-%d | %H:%M")
        + " ===*\n"
    )
    text += f"*Total Retroloaded : {total_customer}*"
    if error is not None:
        text += f"*, Error : {error}*"

    if additional_text is not None:
        text = additional_text

    # send to slack
    slack_client.api_call("chat.postMessage", channel=slack_channel, text=text)


@task(queue='application_normal')
def async_telco_score_in_130_task(application_id: int):
    from juloserver.application_flow.services2.telco_scoring import TelcoScore

    juloLogger.info(
        {
            'message': 'async_telco_score_in_130_task async triggered',
            'application_id': application_id,
        }
    )
    application = Application.objects.get(pk=application_id)
    TelcoScore(application).run_in_130_swapout()


@task(queue='application_normal')
def retry_anti_fraud_binary_checks():
    q = """
    SELECT
        a.application_id
    FROM ops.application a
    JOIN LATERAL (
        SELECT
            ah.change_reason,
            ah.status_new
        FROM ops.application_history ah
        WHERE ah.application_id = a.application_id
        ORDER BY ah.cdate DESC
        LIMIT 1
    ) ah ON TRUE
    WHERE a.application_status_code = {status_code}
        AND ah.change_reason = 'anti_fraud_api_unavailable'
        AND ah.status_new = {status_code}
    """.format(
        status_code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
    )
    with connection.cursor() as cursor:
        cursor.execute(q)
        eligible_application_ids = set([c[0] for c in cursor.fetchall()])

    juloLogger.info(
        {
            'message': 'retry_anti_fraud_binary_checks async triggered',
            'total applications': len(eligible_application_ids),
        }
    )

    for application_id in eligible_application_ids:
        application = Application.objects.get(id=application_id)
        if application.is_julo_one_ios():
            from juloserver.ios.tasks import handle_iti_ready_ios

            handle_iti_ready_ios(application_id)
        else:
            handle_iti_ready(application_id)
        juloLogger.info(
            {
                'message': 'retry anti fraud: handle_iti_ready',
                'application_id': application_id,
            }
        )


def send_pn_finish_result_to_slack(pn_blast_id, attempt, total_count, error):
    text = ""
    slack_channel = "#alerts-comms-prod-pn"

    # prepare client
    slack_client = get_slack_client()

    # prepare text
    text = (
        f"*=== {attempt} (pn_blast_id - {pn_blast_id}) "
        + timezone.localtime(timezone.now()).strftime("%A, %Y-%m-%d | %H:%M")
        + " ===*\n"
    )
    text += f"*Total Count: {total_count}*\n"
    if error is not None:
        text += f"*, Error : {error}*"

    # send to slack
    slack_client.api_call("chat.postMessage", channel=slack_channel, text=text)


@task(queue='retrofix_normal')
def pn_blast_scheduler_for_product_picker_issue():
    """
    This function used to Blast automation PN to product picker impacted customer
    so that we can try to push them to re-login to our App.
    """

    card_id = 15009
    title = 'Yuk login JULO sekarang!'
    body = 'Raih diskon bunga 40% dengan transaksi min 500rb tenor 2 bulan (kode: ISIDMPT).'
    destination_page = 'Home'

    from juloserver.metabase.clients import get_metabase_client
    from juloserver.customer_module.services.device_related import get_device_repository
    from juloserver.julo.clients import get_julo_nemesys_client

    metabase_client = get_metabase_client()

    response, error = metabase_client.get_metabase_data_json(card_id)
    juloLogger.info(
        {
            "method": "pn_blast_scheduler_for_product_picker_issue",
            "metabase_first_response": response[0],
            "metabase_len_response": len(response),
            "error": error,
        }
    )
    if error is not None:
        result_error = str(error)
        send_pn_finish_result_to_slack(0, None, 0, result_error)
        return
    now = timezone.localtime(timezone.now())
    current_hour = now.hour
    current_date = now.date().strftime('%Y%m%d')
    attempt_hours = {10: 'attempt_1', 14: 'attempt_2', 19: 'attempt_3'}  # 2 PM  # 7 PM
    template_code = None
    for data in response:
        try:
            original_customer_id = data['original_customer_id']
            repo = get_device_repository()
            client = get_julo_nemesys_client()
            if Loan.objects.filter(
                customer_id=original_customer_id, loan_status__gt=219, loan_status__lt=250
            ).last() and current_hour in [10, 14]:
                template_code = (
                    f"pn_for_refresh_token_{current_hour}_"
                    f"{attempt_hours[current_hour]}_{current_date}"
                )
                juloLogger.info(
                    {
                        "method": "pn_blast_scheduler_for_product_picker_issue",
                        "customer_id": original_customer_id,
                        "template_code": template_code,
                    }
                )
                client.push_notification_api(
                    {
                        "registration_id": repo.get_active_fcm_id(original_customer_id),
                        "template_code": template_code,
                        "data": {
                            "title": title,
                            "body": body,
                            "destination_page": destination_page,
                            "customer_id": original_customer_id,
                        },
                    }
                )
                time.sleep(0.010)
            elif current_hour == 19:
                template_code = (
                    f"pn_for_refresh_token_{current_hour}-"
                    f"{attempt_hours[current_hour]}_{current_date}"
                )
                juloLogger.info(
                    {
                        "method": "pn_blast_scheduler_for_product_picker_issue",
                        "customer_id": original_customer_id,
                        "template_code": template_code,
                    }
                )
                client.push_notification_api(
                    {
                        "registration_id": repo.get_active_fcm_id(original_customer_id),
                        "template_code": template_code,
                        "data": {
                            "title": title,
                            "body": body,
                            "destination_page": destination_page,
                            "customer_id": original_customer_id,
                        },
                    }
                )
                time.sleep(0.010)
        except Exception as e:
            sentry_client.captureException()
            juloLogger.info(
                {'action': 'error on pn_blast_scheduler_for_product_picker_issue', 'error': str(e)}
            )
            return


@task(queue='application_normal')
def process_clik_model(application_id):
    """
    Task to call CLIK on x105
    Card RUS1-3324
    """
    from juloserver.application_flow.services2.clik import CLIKClient
    from juloserver.ana_api.services import run_ana_clik_model

    application = Application.objects.filter(id=application_id).first()
    if not application:
        return

    try:
        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': application.customer.customer_xid,
                    'object': application,
                }
            ],
            force_get_local_data=True,
        )
        application = detokenized_applications[0]
    except Exception as e:
        juloLogger.warning(
            {
                "action": "detokenization error on process_clik_model",
                "application_id": application_id,
                "error": str(e),
            }
        )
        return

    # initialize CLIK client
    clik = CLIKClient(application)

    # call CLIK function
    if clik.process_clik_model_on_submission():
        # put application path tag
        tag_tracer = ApplicationTagTracking(application=application)
        tag_tracer.adding_application_path_tag('is_clik_model', 1)

        # call ANA
        run_ana_clik_model(application)


@task(queue='application_high')
def expiration_hsfbp_income_verification_task(application_id):
    from juloserver.application_flow.services import JuloOneByPass
    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.application_flow.constants import HSFBPIncomeConst

    application = Application.objects.get(id=application_id)

    bypass = JuloOneByPass()
    accept_hsfbp = bypass.check_accept_hsfbp_income_verification(application)
    decline_hsfbp = bypass.check_decline_hsfbp_tag(application)

    juloLogger.info(
        {
            'message': 'expiration_hsfbp_income_verification_task',
            'application_id': application_id,
            'application_status': application.status,
            'accept_hsfbp': accept_hsfbp,
            'decline_hsfbp': decline_hsfbp,
        }
    )

    if accept_hsfbp or decline_hsfbp:
        return

    if application.status != ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        return

    application_tag_tracking_task(
        application.id,
        None,
        None,
        None,
        HSFBPIncomeConst.EXPIRED_TAG,
        1,
    )

    process_application_status_change(
        application.id,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        change_reason=FeatureNameConst.HIGH_SCORE_FULL_BYPASS,
    )

    juloLogger.info(
        {'action': 'expiration_hsfbp_income_verification_task', 'application_id': application.id}
    )
