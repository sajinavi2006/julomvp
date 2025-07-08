import logging
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    CreditScore,
    AffordabilityHistory,
    ApplicationNote,
)
from juloserver.account.models import (
    AccountLimit,
)
from juloserver.apiv2.models import AutoDataCheck, PdWebModelResult
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.services import check_application_version, JuloOneService
from juloserver.account.services.credit_limit import get_credit_limit_reject_affordability_value
from juloserver.ana_api.services import check_positive_processed_income
from juloserver.julo.formulas.underwriting import compute_affordable_payment
from django.db import transaction
from juloserver.application_flow.workflows import JuloOneWorkflowAction

logger = logging.getLogger(__name__)


def update_moneydeck_app_status_in_100_and_105_to_135(batch_number: int = 10):
    applications = Application.objects.filter(partner__name='moneyduck',
                                              workflow__name=WorkflowConst.JULO_ONE,
                                              application_status__in=['100', '105'])[:batch_number]

    for application in applications.iterator():
        process_application_status_change(
            application.id, ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='under performing partner'
        )


def run_bulk_linkaja_190_bypass(application_xids):
    for application_xid in application_xids:
        message = linkaja_190_bypass(application_xid)
        logger.info(
            {
                'action': 'run_linkaja_190_bypass',
                'application_xid': application_xid,
                'message': message,
            }
        )


def linkaja_190_bypass(application_xid):
    application = Application.objects.get_or_none(application_xid=application_xid)
    if not application:
        err_message = "application {} not found".format(application_xid)
        return err_message

    if application.application_status.status_code == ApplicationStatusCodes.LOC_APPROVED:
        err_message = "application {} already 190".format(application.id)
        return err_message

    if application.partner and application.partner.name != PartnerNameConstant.LINKAJA:
        err_message = "application {} is not linkaja".format(application.id)
        return err_message

    if not application.web_version:
        err_message = "web version is none for application {}".format(application.id)
        return err_message

    applications = Application.objects.filter(customer_id=application.customer_id)

    latest_application = applications.last()
    if latest_application != application:
        err_message = "latest application {} is not the same with {}".format(
            latest_application.id, application.id
        )
        return err_message

    # check fraud application
    fraud_check = applications.filter(
        application_status=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
    )
    if fraud_check:
        err_message = "fraud detected {}".format(application.id)
        return err_message

    # check binary
    auto_data_checks = AutoDataCheck.objects.filter(
        application_id=application.id, is_okay=False
    ).values_list("data_to_check", flat=True)
    cannot_approved_reasons = {
        'fdc_inquiry_check',
        'fraud_form_partial_hp_own',
        'fraud_form_partial_hp_kin',
        'loan_purpose_description_black_list',
        'job_not_black_listed',
        'fraud_form_full',
        'blacklist_customer_check',
        'fraud_form_full_bank_account_number',
    }
    set_auto_data_checks = set(auto_data_checks)
    binary_check = set_auto_data_checks.intersection(cannot_approved_reasons)
    if binary_check:
        err_message = "binary check not passed {}".format(binary_check)
        return err_message

    # check pgood web
    credit_model_result = PdWebModelResult.objects.filter(application_id=application.id).last()
    if not credit_model_result or (credit_model_result and not credit_model_result.pgood):
        err_message = "pgood is not available customer need to logout login {}".format(
            application.id
        )
        return err_message

    # check credit score
    credit_score = CreditScore.objects.filter(application_id=application.id).last()
    approved_credit_score_list = {"B-", "B+", "A-", "A"}
    if not credit_score:
        err_message = "credit score not found on application {}".format(application.id)
        return err_message

    if credit_score and credit_score.score not in approved_credit_score_list:
        err_message = "credit score {} is {} ,not passed".format(application.id, credit_score.score)
        return err_message

    with transaction.atomic():
        if application.application_status.status_code == ApplicationStatusCodes.FORM_PARTIAL:
            linkaja_application_status_change(
                application, ApplicationStatusCodes.DOCUMENTS_SUBMITTED
            )

        # check affordability and shopee scoring
        err_message = check_linkaja_affordability_and_shopee_scoring(application)
        if err_message:
            return err_message

        # check name_bank_validation
        if not application.name_bank_validation_id:
            juloworkflow = JuloOneWorkflowAction(application, None, None, None, None)
            juloworkflow.process_validate_bank()

        if application.application_status.status_code == ApplicationStatusCodes.APPLICATION_DENIED:
            linkaja_force_application_status_to_124(application)

        if application.application_status.status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
            linkaja_application_status_change(
                application, ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            )

        if application.application_status.status_code in (
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ):
            linkaja_application_status_change(
                application, ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
            )

        if (
            application.application_status.status_code
            == ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
        ):
            linkaja_application_status_change(
                application, ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
            )

        if application.account_id:
            account_limit = AccountLimit.objects.get(account_id=application.account_id)
            max_limit = 1000000

        if account_limit and (
            account_limit.max_limit != max_limit
            or account_limit.set_limit != max_limit
            or account_limit.available_limit != max_limit
        ):
            account_limit.update_safely(
                max_limit=max_limit, set_limit=max_limit, available_limit=max_limit
            )

        if (
            application.application_status.status_code
            == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        ):
            linkaja_application_status_change(
                application,
                ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            )

    return "successfull"


def check_linkaja_affordability_and_shopee_scoring(application):
    application_history_130 = ApplicationHistory.objects.filter(
        application=application, status_new=130
    ).last()
    if application_history_130:
        affordability_history = AffordabilityHistory.objects.filter(application=application).last()
        affordability_value = affordability_history.affordability_value

        is_sonic_shortform = check_application_version(application)
        credit_limit_reject_value = get_credit_limit_reject_affordability_value(
            application, is_sonic_shortform
        )
        is_affordable = True
        julo_one_service = JuloOneService()
        input_params = julo_one_service.construct_params_for_affordability(application)

        sonic_affordability_value = affordability_value
        is_monthly_income_changed = ApplicationNote.objects.filter(
            application_id=application.id, note_text='change monthly income by bank scrape model'
        ).last()
        if is_monthly_income_changed and check_positive_processed_income(application.id):
            affordability_result = compute_affordable_payment(**input_params)
            affordability_value = affordability_result['affordable_payment']

        if affordability_value < credit_limit_reject_value or (
            sonic_affordability_value and sonic_affordability_value < credit_limit_reject_value
        ):
            is_affordable = False

        application_history_shopee = ApplicationHistory.objects.filter(
            application=application, change_reason='shopee score not pass by system'
        )
        if application_history_shopee:
            err_message = 'application {} shopee scoring not passed'.format(application.id)
            return err_message

        if not is_affordable:
            err_message = 'application {} affordability minus'.format(application.id)
            return err_message

    return None


def linkaja_application_status_change(application, status_new):
    process_application_status_change(
        application.id, status_new, "pre-approved linkaja KBUMN web application"
    )
    application.refresh_from_db()


def linkaja_force_application_status_to_124(application):
    old_status_code = application.application_status_id
    application.update_safely(application_status_id=124)
    application_history_data = {
        'application': application,
        'status_old': old_status_code,
        'status_new': application.application_status_id,
        'change_reason': "pre-approved linkaja KBUMN web application",
    }

    ApplicationHistory.objects.create(**application_history_data)
    application.refresh_from_db()
