from builtins import str
from builtins import range
from builtins import object
import logging
from datetime import timedelta

import semver
import re
from functools import wraps
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.db.utils import IntegrityError
from gcm.gcm import GCMAuthenticationException
from rest_framework.status import HTTP_200_OK
from juloserver.account.constants import AccountConstant
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag

try:
    import services # noft
    import banks # noft
except ImportError:
    from . import services
    from . import banks

from juloserver.application_flow.constants import PartnerNameConstant, FraudBankAccountConst
from juloserver.application_flow.services import check_liveness_detour_workflow_status_path
from juloserver.disbursement.constants import (
    NameBankValidationStatus,
    XfersDisbursementStep,
    DisbursementVendors,
    NameBankValidationVendors,
)
from juloserver.disbursement.services import trigger_disburse, create_disbursement_new_flow_history
from juloserver.disbursement.services import trigger_name_in_bank_validation
from .banks import BankCodes
from .banks import BankManager
from .clients import get_julo_pn_client
from .clients import get_julo_sentry_client
from .clients import get_julo_xendit_client
from .clients import get_primo_client
from .constants import BypassITIExperimentConst
from .constants import DisbursementMethod
from .constants import DisbursementStatus
from .constants import FeatureNameConst
from .constants import ADVANCE_AI_ID_CHECK_APP_STATUS, AXIATA_FEE_RATE
from .constants import ScoreTag
from .constants import ExperimentConst
from juloserver.sdk.constants import PARTNER_PEDE
from .exceptions import JuloException, InvalidBankAccount
from .formulas import compute_adjusted_payment_installment, compute_weekly_payment_installment
from .formulas import compute_cashback, next_grab_food_payment_date
from .formulas import get_available_due_dates_weekday_daily
from .formulas import get_start_date_in_business_day
from .formulas import determine_first_due_dates_by_payday
from .formulas import compute_payment_installment
from .formulas.experiment import calculation_affordability, calculation_affordability_based_on_affordability_model
from .models import (AdditionalExpense,
                     AwsFaceRecogLog, CustomerFieldChange,
                     FaceRecognition,
                     FDCInquiry,
                     ReferralSystem,
                     )
from .models import AdditionalExpenseHistory
from .models import Application
from .models import ApplicationExperiment
from .models import ApplicationFieldChange
from .models import ApplicationNote
from .models import ApplicationOriginal
from .models import Customer
from .models import Disbursement
from .models import FeatureSetting
from .models import Image
from .models import Offer
from .models import Partner, Loan, StatusLookup, Payment
from .models import LoanDisburseInvoices
from .models import PartnerReferral
from .models import PartnerBankAccount
from .models import PaymentMethod
from .models import ProductLookup
from .models import PrimoDialerRecord
from .models import VirtualAccountSuffix
from .models import VoiceRecord
from .models import WorkflowFailureAction, ApplicationWorkflowSwitchHistory, Workflow
from .models import CreditScore
from .models import ProductLine
from .models import Experiment
from .models import ExperimentSetting
from .models import AffordabilityHistory
from .models import ITIConfiguration
from juloserver.disbursement.models import NameBankValidation, BankNameValidationLog
from juloserver.disbursement.models import Disbursement as Disbursement2
from juloserver.sdk.models import AxiataCustomerData

from .partners import PartnerConstant
from .payment_methods import PaymentMethodCodes, PaymentMethodManager
from .product_lines import ProductLineCodes
from .services2 import get_bypass_iti_experiment_service
from .services2.primo import PrimoLeadStatus
from .statuses import ApplicationStatusCodes
from .statuses import LoanStatusCodes
from .statuses import PaymentStatusCodes
from .utils import (
    execute_after_transaction_safely,
    post_anaserver,
    have_pn_device,
    experiment_check_criteria,
    remove_current_user,
    generate_product_name,
)

from .workflows2.tasks import (create_application_original_task, set_google_calender_task,
                               reminder_push_notif_application_status_105,
                               send_email_status_change_task,
                               process_documents_verified_action_task,
                               send_sms_status_change_task,
                               update_status_apps_flyer_task,
                               send_sms_status_change_131_task,
                               send_sms_status_change_172pede_task,
                               do_advance_ai_id_check_task,
                               sending_reconfirmation_email_175_task,
                               send_registration_and_document_digisign_task,
                               download_sphp_from_digisign_task,
                               send_back_to_170_for_disbursement_auto_retry_task,
                               create_lender_sphp_task,
                               create_sphp_task,
                               lender_auto_approval_task,
                               lender_auto_expired_task,
                               process_after_digisign_failed,
                               run_index_faces,
                               signature_method_history_task,
                               process_validate_bank_task,
                               process_pg_validate_bank_task,
                               )

from juloserver.followthemoney.models import LenderApproval, LenderCurrent, LenderSignature
from dateutil.relativedelta import relativedelta

from juloserver.fdc.services import get_fdc_timeout_config

from ..apiv2.models import PdIncomeTrustModelResult, AutoDataCheck, SdDeviceApp, PdCreditModelResult
from ..apiv2.models import PdWebModelResult
from juloserver.julo.banks import BankManager
from ..apiv2.services import get_credit_score3, get_latest_app_version
from juloserver.ana_api.utils import check_app_cs_v20b
from juloserver.sdk.constants import ProductMatrixPartner, LIST_PARTNER
from juloserver.sdk.services import (
    get_credit_score_partner,
    send_partner_notify,
    get_pede_offer_recommendations,
    update_axiata_offer
    )

from .services2.payment_method import generate_customer_va
from juloserver.ocr.services import ProcessVerifyKTP
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.face_recognition.services import CheckFaceSimilarity
from juloserver.followthemoney.models import LenderTransactionMapping

from juloserver.apiv2.services import is_customer_has_good_payment_histories
from juloserver.apiv2.services import (
    check_iti_repeat,
    get_eta_time_for_c_score_delay)
from juloserver.julo.utils import get_file_from_oss, format_mobile_phone
from juloserver.julo.clients import get_julo_face_rekognition
from ..application_flow.constants import JuloOne135Related
from juloserver.application_flow.services import (
    send_application_event_by_certain_pgood as send_event_by_pgood_from_app_flow_services,
    send_application_event_for_x105_bank_name_info as send_event_by_x105_from_app_flow_services,
    send_application_event_base_on_mycroft as send_event_by_mycroft_from_app_flow_services,
)
from juloserver.application_flow.constants import ApplicationStatusEventType
from juloserver.julo.constants import WorkflowConst
from juloserver.google_analytics.constants import GAEvent
from juloserver.merchant_financing.models import MerchantHistoricalTransactionTask
from juloserver.merchant_financing.constants import MerchantHistoricalTransactionTaskStatuses
from juloserver.julo.tasks2.partner_tasks import send_sms_to_specific_partner_customers
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner
from juloserver.customer_module.services.customer_related import update_customer_data_by_application
from juloserver.liveness_detection.constants import LivenessCheckStatus
from juloserver.liveness_detection.smile_liveness_services import (
    get_liveness_detection_result,
    get_smile_liveness_config,
    get_liveness_info,
)
from juloserver.face_recognition.tasks import face_matching_task
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pii_vault.constants import PiiSource
from juloserver.application_flow.constants import AnaServerFormAPI


logger = logging.getLogger(__name__)
client = get_julo_sentry_client()

CRITERIA_EXPERIMENT_GENERAL = BypassITIExperimentConst.CRITERIA_EXPERIMENT_GENERAL
CRITERIA_EXPERIMENT_ITI_123 = BypassITIExperimentConst.CRITERIA_EXPERIMENT_ITI_123
CRITERIA_EXPERIMENT_ITI_172 = BypassITIExperimentConst.CRITERIA_EXPERIMENT_ITI_172
CRITERIA_EXPERIMENT_FT_172 = BypassITIExperimentConst.CRITERIA_EXPERIMENT_FT_172
CRITERIA_EXPERIMENT_ITIV5_THRESHOLD = BypassITIExperimentConst.CRITERIA_EXPERIMENT_ITIV5_THRESHOLD
VERSION_CREDIT_SCORE_FAST_TRACK_122 = BypassITIExperimentConst.VERSION_CREDIT_SCORE_FAST_TRACK_122
MIN_SCORE_TRESHOLD_MTL = BypassITIExperimentConst.MIN_SCORE_TRESHOLD_MTL
MIN_SCORE_TRESHOLD_STL = BypassITIExperimentConst.MIN_SCORE_TRESHOLD_STL
BYPASS_FAST_TRACK_122 = FeatureNameConst.BYPASS_FAST_TRACK_122
BYPASS_ITI_EXPERIMENT_122 = FeatureNameConst.BYPASS_ITI_EXPERIMENT_122
BYPASS_ITI_EXPERIMENT_125 = FeatureNameConst.BYPASS_ITI_EXPERIMENT_125
AUTO_POPULATE_EXPENSES = FeatureNameConst.AUTO_POPULATE_EXPENSES
MIN_CREDIT_SCORE_ITIV5 = BypassITIExperimentConst.MIN_CREDIT_SCORE_ITIV5
MAX_ITI_MONTHLY_INCOME = BypassITIExperimentConst.MAX_ITI_MONTHLY_INCOME
ACBYPASS_141 = ExperimentConst.ACBYPASS141
ITI_LOW_THRESHOLD = ExperimentConst.ITI_LOW_THRESHOLD


def record_failure(func):
    @wraps(func)
    def wrapper(*args):
        try:
            return func(*args)
        except Exception as exc:
            tuppled_args = args[0].get_tuppled_arguments()
            logger.exception(exc)
            logger.error('%s failed to executed' % func.__name__)
            logger.error('with arguments = %s' % str(tuppled_args))
            application = Application.objects.get_or_none(pk=int(tuppled_args[0]))
            if application:
                WorkflowFailureAction.objects.create(
                    application_id=application.id,
                    action_name=func.__name__,
                    action_type='post',
                    arguments=tuppled_args,
                    error_message=str(exc),
                )
            raise exc

    return wrapper


class WorkflowAction(object):
    def __init__(self, application, new_status_code, change_reason, note, old_status_code):
        self.application = application
        self.new_status_code = new_status_code
        self.change_reason = change_reason
        self.note = note
        self.old_status_code = old_status_code
        super(WorkflowAction, self).__init__()

    def get_tuppled_arguments(self):
        return (self.application.id, self.new_status_code,
                self.change_reason, self.note, self.old_status_code)

    ########################################################
    # Post Run Actions
    # only user decorator on post run action

    def send_pn_playstore_rating(self):
        services.send_pn_playstore_rating(self.application)

    @record_failure
    def start_loan(self):
        from juloserver.partnership.tasks import email_notification_for_partner_loan

        application = self.application
        with transaction.atomic():
            application.change_status(ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
            application.save()

            loan = application.loan
            if loan.product.has_cashback_loan_init:
                loan.initial_cashback = compute_cashback(
                    loan.loan_amount, loan.product.cashback_initial_pct)
                loan.customer.change_wallet_balance(
                    change_accruing=loan.initial_cashback,
                    change_available=0,
                    reason='loan_initial')
                loan.update_cashback_earned_total(loan.initial_cashback)
            loan.set_fund_transfer_time()
            loan.change_status(LoanStatusCodes.CURRENT)
            loan.save()
            customer = loan.customer
            #customer.generate_referral_code()
            customer.save()

        if have_pn_device(loan.application.device) and not application.is_julo_one():
            julo_pn_client = get_julo_pn_client()
            julo_pn_client.inform_loan_has_started(
                loan.application.device.gcm_reg_id, loan.application.id
            )

        if application.partner and application.partner.name == PartnerConstant.AXIATA_PARTNER:
            # generate skrtp
            services.create_mf_axiata_skrtp(loan, application)
            # trigger send email notification
            email_notification_for_partner_loan.delay(loan.id, application.product_line_code)

    @record_failure
    def create_grab_offer(self):
        partner_referral = PartnerReferral.objects.get(cust_nik=self.application.ktp)

        if not partner_referral.product:
            raise JuloException("Product not assigned from refferal")

        offered_product = partner_referral.product

        today = timezone.localtime(timezone.now()).date()
        loan_amount_offer = offered_product.eligible_amount
        loan_duration_offer = offered_product.eligible_duration
        start_date = get_start_date_in_business_day(today, 3)
        range_due_date = get_available_due_dates_weekday_daily(\
            start_date, loan_duration_offer)
        first_payment_date = range_due_date[0]
        last_payment_date = range_due_date[-1]
        _, _, installment = compute_adjusted_payment_installment(
            loan_amount_offer, loan_duration_offer, offered_product.monthly_interest_rate,
            first_payment_date, last_payment_date)
        installment_amount_offer = installment
        first_installment_amount = installment

        Offer.objects.create(
            application=self.application,
            product=offered_product,
            loan_amount_offer=loan_amount_offer,
            loan_duration_offer=loan_duration_offer,
            installment_amount_offer=installment_amount_offer,
            is_accepted=False,
            is_approved=True,
            offer_number=1,
            first_payment_date=first_payment_date,
            first_installment_amount=first_installment_amount)

        logger.info(
            "Offers for product_code=%s has been made "
            "for application_id=%s" % (
                offered_product.product_code, self.application.id))

    # only user decorator on post run action
    @record_failure
    def process_documents_resubmission_action(self):
        self.application.is_document_submitted = False
        self.application.save()
        if have_pn_device(self.application.device):
            try:
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.inform_docs_resubmission(self.application.device.gcm_reg_id, self.application.id)
            except GCMAuthenticationException:
                pass

    # only user decorator on post run action
    @record_failure
    def process_documents_resubmitted_action(self):
        self.application.is_document_submitted = True
        self.application.save()

    # only user decorator on post run action
    @record_failure
    def process_customer_may_not_reapply_action(self):
        self.application.customer.can_reapply = False
        self.application.customer.save()

    # only user decorator on post run action
    @record_failure
    def process_customer_may_reapply_action(self):
        self.application.customer.can_reapply = True
        self.application.customer.save()

    # only user decorator on post run action
    @record_failure
    def process_application_reapply_status_action(self):

        application = self.application
        customer = application.customer
        customer.can_reapply = False

        if self._set_reapply_for_ignored_doc_resubmission(customer):
            return

        change_reason = self.change_reason.lower()
        banned_reasons = (
            Customer.REAPPLY_CUSTOM
            + Customer.REAPPLY_THREE_MONTHS_REASON
            + Customer.REAPPLY_HALF_A_YEAR_REASON
            + Customer.REAPPLY_ONE_YEAR_REASON
            + Customer.REAPPLY_NOT_ALLOWED_REASON
        )
        auto_data_checks = AutoDataCheck.objects.filter(
            application_id=application.id, is_okay=False
        ).values_list("data_to_check", flat=True)
        auto_data_check = next(
            (reason for reason in reversed(banned_reasons) if reason in auto_data_checks), None
        )

        if any(
            word in change_reason
            for word in JuloOne135Related.ALL_BANNED_REASON_J1 + banned_reasons
        ):
            customer.set_scheduling_reapply(application, change_reason)
        elif auto_data_check:
            customer.set_scheduling_reapply(application, auto_data_check)
        else:
            customer.can_reapply = True
        customer.save()

    def _set_reapply_for_ignored_doc_resubmission(self, customer) -> bool:
        if self.old_status_code not in {
            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        }:
            logger.info(
                {
                    "application": self.application.id,
                    "message": "_set_reapply_for_ignored_doc_resubmission: old status not match",
                }
            )
            return False

        today = timezone.localtime(timezone.now())
        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS, is_active=True
        ).last()
        if setting is None:
            logger.info(
                {
                    "application": self.application.id,
                    "message": "_set_reapply_for_ignored_doc_resubmission: setting not found",
                }
            )
            return False

        parameters = setting.parameters

        if (
            self.old_status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED
            and self.new_status_code == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        ):
            if "x106_to_reapply" not in parameters:
                logger.warning(
                    {
                        "application": self.application.id,
                        "message": "_set_reapply_for_ignored_doc_resubmission: x106_to_reapply not in parameters",
                    }
                )
                return False

            range_days = int(parameters["x106_to_reapply"])
        elif (
            self.old_status_code == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
            and self.new_status_code == ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED
        ):
            if "x136_to_reapply" not in parameters:
                logger.warning(
                    {
                        "application": self.application.id,
                        "message": "_set_reapply_for_ignored_doc_resubmission: x136_to_reapply not in parameters",
                    }
                )
                return False

            range_days = int(parameters["x136_to_reapply"])
        else:
            logger.warning(
                {
                    "application": self.application.id,
                    "message": "_set_reapply_for_ignored_doc_resubmission: custom reapply date range not implemented",
                    "old_status_code": self.old_status_code,
                    "new_status_code": self.new_status_code,
                }
            )
            return False

        field_change_data = []
        if range_days == 0:
            fields_data = {"customer": customer, "application": self.application}
            fields_data["field_name"] = "can_reapply"
            fields_data["old_value"] = customer.can_reapply
            customer.can_reapply = True
            fields_data["new_value"] = customer.can_reapply
            field_change_data.append(fields_data)

            logger.info(
                {
                    "application": self.application.id,
                    "message": "_set_reapply_for_ignored_doc_resubmission: range_days 0",
                }
            )
        else:
            expired_date = today + relativedelta(days=range_days)
            fields_data_1 = {"customer": customer, "application": self.application}
            fields_data_1["field_name"] = "disabled_reapply_date"
            fields_data_1["old_value"] = customer.disabled_reapply_date
            customer.disabled_reapply_date = today
            fields_data_1["new_value"] = customer.disabled_reapply_date
            field_change_data.append(fields_data_1)

            fields_data_2 = {"customer": customer, "application": self.application}
            fields_data_2["field_name"] = "can_reapply_date"
            fields_data_2["old_value"] = customer.can_reapply_date
            customer.can_reapply_date = expired_date
            fields_data_2["new_value"] = customer.can_reapply_date
            field_change_data.append(fields_data_2)

            logger.info(
                {
                    "application": self.application.id,
                    "message": "_set_reapply_for_ignored_doc_resubmission: range_days non zero",
                    "range_days": range_days,
                }
            )

        customer.save()

        for data in field_change_data:
            if data["old_value"] != data["new_value"]:
                CustomerFieldChange.objects.create(**data)
        return True

    @record_failure
    def revert_lender_counter(self):
        # handler from status 141, 172, 160
        # in 139, 137, 135, 134, 133, 174, 171
        if self.application.account:
            loan = self.application.account.loan_set.last()
        else:
            loan = self.application.loan

        if loan and loan.lender:
            services.update_lender_disbursement_counter(loan.lender, False)

    # only user decorator on post run action
    @record_failure
    def trigger_anaserver_status105(self):
        ana_data = {'application_id': self.application.id}

        url = AnaServerFormAPI.COMBINED_FORM
        if self.application.company:
            url = '/api/amp/v1/ef-pilot-application-upload/'
            post_anaserver(url, json=ana_data)
            return
        if (
            self.application.partner
            and self.application.partner.name in LIST_PARTNER
        ):
            if self.application.partner.is_csv_upload_applicable:
                url = '/api/amp/v1/partner-pilot-upload-form/'
                post_anaserver(url, json=ana_data)
                return
            else:
                url = '/api/amp/v1/partner/'
        elif self.application.workflow.name == WorkflowConst.GRAB:
            url = '/api/amp/v1/partner/grab/'
        elif self.application.is_julo_one_ios():
            url = AnaServerFormAPI.IOS_FORM

        if ((self.application.is_regular_julo_one() or self.application.is_julo_starter())
                and self.application.ktp):
            fdc_inquiry = FDCInquiry.objects.filter(
                application_id=self.application.id).last()

            if not fdc_inquiry:
                return

            pending_statuses = ['error', 'inquiry_disabled', 'pending']
            fdc_inquiry_pending = fdc_inquiry.inquiry_status in pending_statuses
            time_now = timezone.localtime(timezone.now())
            fdc_timeout = get_fdc_timeout_config()
            fdc_timeout_mins = timedelta(minutes=fdc_timeout)

            fdc_timeouted = time_now - fdc_inquiry.cdate >= fdc_timeout_mins
            if fdc_inquiry_pending and not fdc_timeouted:
                return

        if self.application.is_web_app() or (
            self.application.is_partnership_app()
            and not self.application.is_merchant_flow()
            and not self.application.is_force_filled_partner_app()
        ):

            if not FDCInquiry.objects.filter(application_id=self.application.id).exists():
                return

            fdc_inquiry_failed = FDCInquiry.objects.filter(
                application_id=self.application.id,
                inquiry_status__in=['error', 'inquiry_disabled', 'pending']).exists()
            if fdc_inquiry_failed:
                return
            url = '/api/amp/v1/web-form/'
        if self.application.is_merchant_flow():
            merchant_historial_transaction_task = MerchantHistoricalTransactionTask.objects.filter(
                application=self.application,
            ).select_related('merchanthistoricaltransactiontaskstatus').order_by('id').last()
            status =\
                merchant_historial_transaction_task.merchanthistoricaltransactiontaskstatus.status
            if status == MerchantHistoricalTransactionTaskStatuses.INVALID:
                services.process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.MERCHANT_HISTORICAL_TRANSACTION_INVALID,
                    change_reason='invalid_historical_transaction'
                )
                return
            elif status != MerchantHistoricalTransactionTaskStatuses.VALID:
                return

            url = '/api/amp/v1/merchant-form/'

        if url == AnaServerFormAPI.COMBINED_FORM:
            # If call combined form to generate credit score run it inside queue task.
            # User has time to wait.
            from juloserver.julo.tasks import call_ana_server
            call_ana_server.apply_async(
                queue='application_high',
                kwargs={'url': url, 'data': ana_data}
            )
            logger.info({
                'action': 'trigger_anaserver_status105 -> call_ana_server',
                'application_id': self.application.id
            })
        else:
            post_anaserver(url, json=ana_data)

    # only user decorator on post run action
    @record_failure
    def trigger_anaserver_status120(self):
        ana_data = {'application_id': self.application.id}

        url = '/api/amp/v1/long-form/'
        if self.application.partner and self.application.partner.name in LIST_PARTNER:
            url = '/api/amp/v1/long-form-partner/'
        post_anaserver(url, json=ana_data)

    # for triggering sonic trigger at 122
    @record_failure
    def trigger_anaserver_status_122(self):
        ana_data = {'application_id': self.application.id}
        if self.application.is_web_app() or self.application.is_partnership_app():
            url = '/api/amp/v1/sonic-web-model/'
        else:
            url = '/api/amp/v1/sonic-model/'

        post_anaserver(url, json=ana_data)

    # for updating advance-score using advance-ai
    @record_failure
    def trigger_anaserver_status122(self):
        if self.application.partner and self.application.partner.name in LIST_PARTNER:
            ana_data = {'application_id': self.application.id}
            url = '/api/amp/v1/process-obp-partner/'
            post_anaserver(url, json=ana_data)

    # only user decorator on post run action
    @record_failure
    def trigger_anaserver_short_form_timeout(self):
        ana_data = {'application_id': self.application.id}
        post_anaserver('/api/amp/v1/short-form-timeout/', json=ana_data)

    # only user decorator on post run action
    @record_failure
    def disbursement_entry_and_xendit_name_validate(self):
        application = self.application
        loan = application.loan
        is_julo = self.is_julo_email(application.email)

        # assiggn partner type lender in loan by product
        if not is_julo:
            if application.product_line.product_line_code in ProductLineCodes.lended_by_bri():
                loan.partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
            elif application.product_line.product_line_code in ProductLineCodes.lended_by_grab():
                loan.partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)
            elif application.product_line.product_line_code in ProductLineCodes.lended_axiata():
                loan.partner = Partner.objects.get(name=PartnerConstant.AXIATA_PARTNER)
            else:
                lender = services.assign_lender_to_disburse(application)
                loan.lender = lender
                # this only for handle FTM
                loan.partner = lender.user.partner
            loan.save()

        if application.product_line.product_line_code in ProductLineCodes.bri():
            if not application.bank_account_number:
                # break process validate to kyc process 176
                return

        bank_entry = banks.BankManager.get_by_name_or_none(application.bank_name)
        if bank_entry is None:
            raise JuloException('bank name not found')

        disbursement = Disbursement.objects.get_or_none(loan=application.loan)
        if disbursement is None:
            disbursement = Disbursement.objects.create(
                loan=application.loan,
                bank_code=bank_entry.xendit_bank_code,
                bank_number=application.bank_account_number,
                external_id=application.application_xid)

        if disbursement.disburse_status in ['PENDING', 'DISBURSING', 'COMPLETED']:
            logger.warning({
                'status': "already_processed",
                'disburse_status': disbursement.disburse_status,
                'application_id': application.id
            })
            return

        if bank_entry.xendit_bank_code != disbursement.bank_code:
            disbursement.bank_code = bank_entry.xendit_bank_code
            disbursement.save()
        if application.bank_account_number != disbursement.bank_number:
            disbursement.bank_number = application.bank_account_number
            disbursement.save()

        xendit_client = get_julo_xendit_client()
        response_validate = xendit_client.validate_name(
            disbursement.bank_number, disbursement.bank_code)

        if response_validate['status'] != 'SUCCESS':
            disbursement.validation_id = response_validate['id']
            disbursement.validation_status = response_validate['status']
            disbursement.save()
            return

        if response_validate['bank_account_holder_name'].lower() != application.name_in_bank.lower():
            disbursement.validation_id = response_validate['id']
            disbursement.validation_status = 'NAME_INVALID'
            disbursement.validated_name = response_validate['bank_account_holder_name']
            disbursement.save()
            application.change_status(ApplicationStatusCodes.NAME_VALIDATE_FAILED)
            application.save()
            return

        disbursement.validation_id = response_validate['id']
        disbursement.validation_status = response_validate['status']
        disbursement.validated_name = response_validate['bank_account_holder_name']
        disbursement.save()

        disbursement.refresh_from_db()
        if disbursement.disburse_status in ['PENDING', 'DISBURSING', 'COMPLETED']:
            logger.warning({
                'status': "already_processed",
                'disburse_status': disbursement.disburse_status,
                'application_id': application.id
            })
            return

        response_disburse = xendit_client.disburse(
            application.loan, disbursement,
            'JULO Disbursement for %s, %s' % (application.email, application.loan.id))
        disbursement.disburse_id = response_disburse['id']
        disbursement.disburse_status = response_disburse['status']
        disbursement.disburse_amount = response_disburse['amount']
        disbursement.save()

    # only user decorator on post run action
    @record_failure
    def process_loan_disbursement(self):
        from .services2.xfers import XfersService
        application = self.application
        loan = application.loan
        is_julo = self.is_julo_email(application.email)

        # assiggn partner type lender in loan by product
        if not is_julo:
            if application.product_line.product_line_code in ProductLineCodes.lended_by_bri():
                loan.partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
            elif application.product_line.product_line_code in ProductLineCodes.lended_by_grab():
                loan.partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)
            else:
                lender = services.assign_lender_to_disburse(application)
                loan.lender = lender
                # this only for handle FTM
                loan.partner = lender.user.partner
            loan.save()

        if application.product_line.product_line_code in ProductLineCodes.bri():
            if not application.bank_account_number:
                # break process validate to kyc process 176
                return

        bank_entry = banks.BankManager.get_by_name_or_none(application.bank_name)
        if bank_entry is None:
            raise JuloException('bank name not found')

        disbursement = Disbursement.objects.get_or_none(loan=application.loan)
        if disbursement is None:
            disbursement = Disbursement.objects.create(
                loan=application.loan,
                bank_code=bank_entry.xfers_bank_code,
                bank_number=application.bank_account_number,
                external_id=application.application_xid)

        skip_disburse_status = [DisbursementStatus.PROCESSING,
                                DisbursementStatus.PENDING,
                                DisbursementStatus.COMPLETED]
        if disbursement.disburse_status in skip_disburse_status:
            logger.warning({
                'status': "already_processed",
                'disburse_status': disbursement.disburse_status,
                'application_id': application.id
            })
            return True

        if application.bank_account_number != disbursement.bank_number:
            disbursement.bank_number = application.bank_account_number
            disbursement.save()

        # Start Bank Name Validation Using Xfers
        #####################################################################################
        xfers_service = XfersService()
        disbursement, bank_id = xfers_service.validate_bank(disbursement,
                                                            bank_entry)

        if disbursement.validation_status == DisbursementStatus.INVALID_NAME_IN_BANK:
            application.change_status(ApplicationStatusCodes.NAME_VALIDATE_FAILED)
            application.save()
            return

        #####################################################################################
        # end of validation bakn Name

        # check if disbursement is already process
        disbursement.refresh_from_db()
        if disbursement.disburse_status in ['PENDING', 'DISBURSING', 'COMPLETED']:
            logger.warning({
                'status': "already_processed",
                'disburse_status': disbursement.disburse_status,
                'application_id': application.id
            })
            return

        # if application Bank is BCA
        if bank_entry.bank_code == BankCodes.BCA:
            if disbursement.disburse_status in ['PENDING', 'DISBURSING', 'COMPLETED']:
                logger.warning({
                    'status': "already_processed",
                    'disburse_status': disbursement.disburse_status,
                    'application_id': application.id
                })
                return

            from .services2.bca import BCAService
            loan.loan_disbursement_method = DisbursementMethod.METHOD_BCA
            loan.save()
            BCAService().process_disburse(disbursement)

        else:
            loan.loan_disbursement_method = DisbursementMethod.METHOD_XFERS
            loan.save()
            xfers_service.process_disburse(disbursement,
                                           bank_id,
                                           bank_entry.xfers_bank_code)

    # # only user decorator on post run action
    # @record_failure
    # def send_lead_data_to_primo(self):
    #     application = self.application
    #     if application.status not in MAPPING_LIST.keys():
    #         return
    #     primo_record = PrimoDialerRecord.objects.filter(application=application,\
    #         application_status=application.status).last()
    #     skiptrace = get_recomendation_skiptrace(application)
    #     if not primo_record:
    #         primo_record = PrimoDialerRecord.objects.create(
    #                             application=application,
    #                             application_status=application.application_status,
    #                             list_id=MAPPING_LIST[application.status],
    #                             lead_status=PrimoLeadStatus.INITIATED,
    #                             phone_number=format_national_phone_number(str(skiptrace.phone_number)),
    #                             skiptrace=skiptrace
    #                         )
    #     primo_record = PrimoDialerRecord.objects.get(pk=primo_record.id)
    #     primo_client = get_primo_client()
    #     response = primo_client.upload_primo_data([construct_primo_data(primo_record)])
    #     if response.status_code == HTTP_200_OK:
    #         result = json.loads(response.content)[0]
    #         if result['status']:
    #             primo_record.lead_id=result['lead_id']
    #             primo_record.lead_status=PrimoLeadStatus.SENT
    #             primo_record.save()
    #         else:
    #             primo_record.lead_status=PrimoLeadStatus.FAILED
    #             primo_record.save()
    #         logger.info({
    #             'action': 'send_lead_data_to_primo',
    #             'primo_record': primo_record,
    #             'status': result['status'],
    #             'message': result['message']
    #         })

    # only user decorator on post run action
    @record_failure
    def send_lead_data_to_primo(self):

        application = self.application

        # NOTE: Agents were reporting that the change status action was returning 404.
        # Since status was actually changed before timing out, we suspect this
        # code of making API calls to primo is timing out the process. Commenting out.

        # primo_list_mapping = PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT]
        # if application.status not in primo_list_mapping.keys():
        #     return
        #
        # if application.product_line_id in ProductLineCodes.loc():
        #     return
        #
        # primo_record = PrimoDialerRecord.objects.filter(
        #     application=application, application_status=application.status
        # ).last()
        #
        # skiptrace = get_recomendation_skiptrace(application)
        # phone_number = format_national_phone_number(str(skiptrace.phone_number))
        # if not primo_record:
        #     primo_record = PrimoDialerRecord.objects.create(
        #         application=application,
        #         application_status=application.application_status,
        #         list_id=primo_list_mapping[application.status],
        #         lead_status=PrimoLeadStatus.INITIATED,
        #         phone_number=phone_number,
        #         skiptrace=skiptrace
        #     )
        #
        # primo_record = PrimoDialerRecord.objects.get(pk=primo_record.id)
        # primo_client = get_primo_client()
        # response = primo_client.upload_primo_data(
        #     [construct_primo_data(application, phone_number)])
        # if response.status_code == HTTP_200_OK:
        #     result = json.loads(response.content)[0]
        #     if result['status']:
        #         primo_record.lead_id = result['lead_id']
        #         primo_record.lead_status = PrimoLeadStatus.SENT
        #         primo_record.save()
        #     else:
        #         primo_record.lead_status = PrimoLeadStatus.FAILED
        #         primo_record.save()
        #     logger.info({
        #         'action': 'send_lead_data_to_primo',
        #         'primo_record': primo_record,
        #         'status': result['status'],
        #         'message': result['message']
        #     })


    def trigger_process_validate_bank(self):
        process_validate_bank_task.apply_async(
            args=(self.application.id,)
        )


    def trigger_pg_validate_bank(self):   
        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ONBOARDING_BANK_VALIDATION_PG
        ).last()

        if not setting or not setting.is_active:
            logger.info({
                'action': 'trigger_pg_validate_bank: pg setting not active',
                'application_id': self.application.id
            })

            process_validate_bank_task(self.application.id)
            return

        process_pg_validate_bank_task(self.application.id)


    def process_validate_bank(
            self, is_experiment=None, force_validate=False, new_data=None, only_success=False):
        application = self.application
        is_julo_one = application.is_julo_one()
        is_grab = application.is_grab()
        is_julo_starter = application.is_julo_starter()
        is_julo_one_ios = application.is_julo_one_ios()
        is_old_version = True
        loan = None
        if application.app_version:
            is_old_version = semver.match(application.app_version,
                                          NameBankValidationStatus.OLD_VERSION_APPS)

        if is_julo_one or application.is_grab() or is_julo_starter or is_julo_one_ios:
            name_bank_validation_id = application.name_bank_validation_id
        else:
            loan = application.loan
            name_bank_validation_id = loan.name_bank_validation_id

        data_to_validate = {'name_bank_validation_id': name_bank_validation_id,
                            'bank_name': application.bank_name,
                            'account_number': application.bank_account_number,
                            'name_in_bank': application.name_in_bank,
                            'mobile_phone': application.mobile_phone_1,
                            'application': application
                            }

        if new_data:
            data_to_validate['name_in_bank'] = new_data['name_in_bank']
            data_to_validate['bank_name'] = new_data['bank_name']
            data_to_validate['account_number'] = new_data['bank_account_number']
            data_to_validate['name_bank_validation_id'] = None
            if is_grab:
                data_to_validate['mobile_phone'] = format_mobile_phone(application.mobile_phone_1)
        name_bank_validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
        # checking is validation is not success already
        if name_bank_validation is None or name_bank_validation.validation_status != NameBankValidationStatus.SUCCESS \
                or force_validate:
            try:
                validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
            except Exception as e:
                logger.error({
                    'action': 'process_validate_bank',
                    'error': str(e)
                })
                return

            validation_id = validation.get_id()
            if loan and (
                not is_julo_one and not is_grab and not is_julo_starter and not is_julo_one_ios
            ):
                loan.name_bank_validation_id = validation_id
                loan.save(update_fields=['name_bank_validation_id'])

            if (
                is_grab
                and validation.name_bank_validation.method
                == NameBankValidationVendors.PAYMENT_GATEWAY
            ):
                validation.validate_grab()
            else:
                validation.validate()

            name_bank_validation = NameBankValidation.objects.get_or_none(pk=validation_id)
            if (name_bank_validation.validation_status == NameBankValidationStatus.SUCCESS and only_success) or name_bank_validation:
                application.update_safely(name_bank_validation_id=validation_id)

            logger.info({
                'action': 'process_validate_bank',
                'validation_data': validation.get_data(),
            })
            validation_data = validation.get_data()
            if not validation.is_success():
                if (is_old_version and not is_experiment) or validation_data['attempt'] >= 3 or \
                        PARTNER_PEDE == application.partner_name:
                    validation_data['go_to_175'] = True
                if (
                    (is_grab and application.status == ApplicationStatusCodes.LOC_APPROVED)
                    or is_julo_one
                    or is_julo_starter
                    or is_julo_one_ios
                ):
                    logger.warning(
                        'Julo one name bank validation error | application_id=%s, '
                        'validation_data=%s' % (application.id, validation_data)
                    )
                    return

                if is_grab:
                    services.process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                        'name_bank_validation_failed'
                    )
                    return

                raise InvalidBankAccount(validation_data)
            else:
                logger.info({
                    'action': 'process_validate_bank',
                    'success': True,
                })
                # update table with new verified BA
                application.update_safely(
                    bank_account_number=validation_data['account_number'],
                    name_in_bank=validation_data['validated_name'],
                )
                if is_grab and application.status != ApplicationStatusCodes.LOC_APPROVED:
                    services.process_application_status_change(
                        self.application.id,
                        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                        "system_triggered"
                    )
        else:
            # update table with new verified BA
            logger.info({
                'action': 'process_validate_bank',
                'success': True,
            })
            application.update_safely(
                bank_account_number=name_bank_validation.account_number,
                name_in_bank=name_bank_validation.validated_name,
            )
            if is_grab and application.status != ApplicationStatusCodes.LOC_APPROVED:
                services.process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    "system_triggered"
                )

        return name_bank_validation

    @record_failure
    def process_name_bank_validate(self):
        application = self.application
        loan = self.application.loan
        is_julo = self.is_julo_email(application.email)

        if not is_julo:
            if application.product_line.product_line_code in ProductLineCodes.lended_by_bri():
                loan.partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
            elif application.product_line.product_line_code in ProductLineCodes.lended_by_grab():
                loan.partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)
            else:
                lender = services.assign_lender_to_disburse(application)
                loan.lender = lender
                # this only for handle FTM
                loan.partner = lender.user.partner
            loan.save()

        # prepare data to validate
        data_to_validate = {'name_bank_validation_id': loan.name_bank_validation_id,
                            'bank_name': application.bank_name,
                            'account_number': application.bank_account_number,
                            'name_in_bank': application.name_in_bank,
                            'mobile_phone': application.mobile_phone_1,
                            'application': application
                           }
        validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        # assign validation_id to loan
        validation_id = validation.get_id()
        loan.name_bank_validation_id = validation_id
        loan.save(update_fields=['name_bank_validation_id'])
        validation.validate()
        validation_data = validation.get_data()
        # check validation_status
        if validation.is_success():
            new_status_code = ApplicationStatusCodes.LENDER_APPROVAL
            change_reason = 'Lender approval'
            note = 'Name in Bank Validation Success via %s' % (validation_data['method'])
            services.process_application_status_change(application.id,
                                                       new_status_code,
                                                       change_reason,
                                                       note)
        elif validation.is_failed():
            new_status_code = ApplicationStatusCodes.NAME_VALIDATE_FAILED
            change_reason = 'Name validation failed'
            note = 'Name in Bank Validation Failed via %s' % (validation_data['method'])
            services.process_application_status_change(application.id,
                                                       new_status_code,
                                                       change_reason,
                                                       note)

    @record_failure
    #early bank validation in status code 120
    def process_name_bank_validate_earlier(self):
        application = self.application
        # prepare data to validate
        data_to_validate = {'name_bank_validation_id': None,
                            'bank_name': application.bank_name,
                            'account_number': application.bank_account_number,
                            'name_in_bank': application.name_in_bank,
                            'mobile_phone': application.mobile_phone_1,
                            'application': application
                            }
        validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        validation.validate()

        if validation.is_success():
            logger.info({
                'action': "process_name_bank_validate_earlier",
                'result': "success",
                'data': data_to_validate
            })
        elif validation.is_failed():
            logger.info({
                'action': "process_name_bank_validate_earlier",
                'result': "failed",
                'data': data_to_validate
            })

    @record_failure
    def process_partner_bank_validate(self):
        application = self.application
        loan = self.application.loan
        is_julo = self.is_julo_email(application.email)

        if not is_julo:
            if application.product_line.product_line_code in ProductLineCodes.lended_by_bri():
                loan.partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
            elif application.product_line.product_line_code in ProductLineCodes.lended_by_grab():
                loan.partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)
            else:
                lender = services.assign_lender_to_disburse(application)
                loan.lender = lender
                # this only for handle FTM
                loan.partner = lender.user.partner
            loan.save()

        partner_bank_accounts = PartnerBankAccount.objects.filter(partner=application.partner).all()

        validations = list()
        is_false = False
        for bank_account in partner_bank_accounts:
            # prepare data to validate
            data_to_validate = {'name_bank_validation_id': bank_account.name_bank_validation_id,
                                'bank_name': bank_account.bank_name,
                                'account_number': bank_account.bank_account_number,
                                'name_in_bank': bank_account.name_in_bank,
                                'mobile_phone': str(bank_account.phone_number),
                                'application': application
                                }
            validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
            # assign validation_id to partner bank account
            validation_id = validation.get_id()
            bank_account.name_bank_validation_id = validation_id
            bank_account.save(update_fields=['name_bank_validation_id'])

            if not LoanDisburseInvoices.objects.filter(loan=loan, name_bank_validation_id=validation_id).first():
                LoanDisburseInvoices.objects.create(loan=loan,
                                                    name_bank_validation_id=validation_id)
            if not validation.is_success():
                validation.validate()

            validation_data = validation.get_data()
            validations.append(validation_data)

            if validation.is_failed():
                is_false = True
                new_status_code = ApplicationStatusCodes.NAME_VALIDATE_FAILED
                change_reason = 'Name validation failed'
                note = 'Name in Bank Validation {0} Failed via {1}'.format(validation_data['name_in_bank'],
                                                                           validation_data['method'])
                services.process_application_status_change(application.id,
                                                           new_status_code,
                                                           change_reason,
                                                           note)

        if is_false:
            return

        # check validation_status
        new_status_code = ApplicationStatusCodes.LENDER_APPROVAL
        change_reason = 'Lender approval'
        note = 'Name in Bank Validation {0} Success via {1}'.format(", ".join(v['name_in_bank'] for v in validations),
                                                                    ", ".join(v['method'] for v in validations))
        services.process_application_status_change(application.id,
                                                   new_status_code,
                                                   change_reason,
                                                   note)

    def validate_bank_name_in_160(self):
        from juloserver.disbursement.services import get_validation_method
        from juloserver.disbursement.utils import bank_name_similarity_check
        # don't record agent_id on bypass
        remove_current_user()
        application = self.application
        new_status_code = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
        note = 'bank name validation triggered by system'
        reason = 'Name Validation Success'

        if application.partner_name == PARTNER_PEDE:
            new_status_code = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER

        # name in form match checking
        if self.old_status_code != ApplicationStatusCodes.NAME_VALIDATE_FAILED:
            is_bank_account_va = services.suspect_account_number_is_va(application.bank_account_number,
                                                                       application.bank_name)

            lowered_name_in_form = application.fullname.lower()
            name_bank_validation = NameBankValidation.objects.get_or_none(
                pk=application.loan.name_bank_validation_id
            )
            if not name_bank_validation:
                name_in_bank = application.name_in_bank
            else:
                name_in_bank = name_bank_validation.name_in_bank
            is_name_similar = bank_name_similarity_check(lowered_name_in_form, name_in_bank.lower())

            if is_bank_account_va or not is_name_similar:
                # we need to create NameBankValidation record for agent updating
                if not name_bank_validation:
                    bank_entry = BankManager.get_by_name_or_none(application.bank_name)
                    method = get_validation_method(application)
                    bank_code = getattr(bank_entry, '{}_bank_code'.format(method.lower()))

                    name_bank_validation = NameBankValidation.objects.create(
                        bank_code=bank_code,
                        account_number=application.bank_account_number,
                        name_in_bank=application.name_in_bank,
                        mobile_phone=application.mobile_phone_1,
                        method=method)
                    loan = application.loan
                    loan.update_safely(name_bank_validation_id=name_bank_validation.id)
                    update_fields = ['bank_code', 'account_number', 'name_in_bank',
                                     'mobile_phone', 'method']
                    name_bank_validation.create_history('create', update_fields)

                new_status_code = ApplicationStatusCodes.NAME_VALIDATE_FAILED
                if is_bank_account_va:
                    note = "account_number length suspect as virtual account"
                    reason = 'bank account suspect as virtual account'
                elif not is_name_similar:
                    if name_bank_validation.attempt < 3 and PARTNER_PEDE != application.partner_name:
                        return
                    note = "name_in_bank doesn't match with fullname in form"
                    reason = 'Name validation failed'

        try:
            from juloserver.julo_privyid.services import get_privy_feature
            privy_feature = get_privy_feature()
            if not privy_feature or (privy_feature and new_status_code !=
                                     ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL):
                services.process_application_status_change(application.id,
                                                           new_status_code,
                                                           reason,
                                                           note)
        #this exception handler only triggered if new_status_code=160 with bank validation failed
        except InvalidBankAccount as e:
                if 'go_to_175' in str(e):
                    services.process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                        'Name validation failed',
                        NameBankValidationStatus.INVALID_NOTE.format(application.app_version))

    @record_failure
    def process_disbursement(self):
        from juloserver.followthemoney.services import (
            update_committed_amount_for_lender_balance,
            update_lender_balance_current_for_disbursement)
        application = self.application
        loan = self.application.loan
        data_to_disburse = {'disbursement_id': loan.disbursement_id,
                            'name_bank_validation_id': loan.name_bank_validation_id,
                            'amount': loan.loan_disbursement_amount,
                            'external_id': application.application_xid,
                            'type': 'loan',
                            'original_amount': loan.loan_amount
                           }
        disbursement = trigger_disburse(data_to_disburse, application=application)

        disbursement_id = disbursement.get_id()
        loan.disbursement_id = disbursement_id
        loan.save(update_fields=['disbursement_id'])

        #follow the money block
        ltm = LenderTransactionMapping.objects.filter(
            disbursement_id=disbursement.disbursement.id,
            lender_transaction_id__isnull=True
        )

        if not ltm:
            try:
                with transaction.atomic():
                    update_committed_amount_for_lender_balance(disbursement.disbursement, loan.id)
            except JuloException:
                new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
                change_reason = 'Fund disbursal failed'
                note = 'Disbursement failed because of insufficient balance of lender: {} \
                    application_id: {}'.format(loan.lender, application.id)
                # change status for disbursement to failed when insufficient balance
                # for handle disbursement_status = INITIATED in 181
                disbursement_obj = disbursement.disbursement
                disbursement_obj.disburse_status = DisbursementStatus.FAILED
                disbursement_obj.reason = "Insufficient {} Balance".format(loan.lender)
                disbursement_obj.save(update_fields=['disburse_status', 'reason'])
                # create history of disbursement
                create_disbursement_new_flow_history(disbursement_obj)
                services.process_application_status_change(application.id,
                                                        new_status_code,
                                                        change_reason,
                                                        note)

                return True
        # end of follow the money block

        disbursement.disburse()

        disbursement_data = disbursement.get_data()
        # check disbursement status
        if disbursement.is_success():
            # process partner transaction record
            if loan.partner and loan.partner.is_active_lender:
                services.record_disbursement_transaction(loan)

            # process change status to 180
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s account number %s via %s' % (
                application.email, disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['method'])
            services.process_application_status_change(application.id,
                                                       new_status_code,
                                                       change_reason,
                                                       note)
            if disbursement.disbursement.method == DisbursementVendors.BCA:
                try:

                    update_lender_balance_current_for_disbursement(loan.id)
                except JuloException:
                    sentry_client = get_julo_sentry_client()
                    sentry_client.capture_exceptions()
        elif disbursement.is_failed():
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
            change_reason = 'Fund disbursal failed'
            note = 'Disbursement failed to %s Bank %s account number %s via %s' % (
                application.email, disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['method'])
            services.process_application_status_change(application.id,
                                                       new_status_code,
                                                       change_reason,
                                                       note)

    @record_failure
    def trigger_update_lender_balance_current_for_disbursement(self):
        from juloserver.followthemoney.services import (
            update_lender_balance_current_for_disbursement)
        loan = self.application.loan
        update_lender_balance_current_for_disbursement(loan.id)

    @record_failure
    def process_partner_disbursement(self):
        application = self.application
        loan = self.application.loan
        partner_bank_accounts = PartnerBankAccount.objects.filter(partner=application.partner).all()

        disbursements = list()
        is_false = False
        is_pending = False
        for bank_account in partner_bank_accounts:
            invoices = LoanDisburseInvoices.objects.filter(loan=loan,
                                                           name_bank_validation_id=
                                                           bank_account.name_bank_validation_id).first()

            # erase erafone_fee and insurance for disbursement amount
            disburse_amount = loan.loan_amount - ProductMatrixPartner.ERAFONE_FEE - ProductMatrixPartner.insurance(
                self.application.loan_amount_request)
            loan.loan_disbursement_amount = disburse_amount
            loan.save()

            data_to_disburse = {'disbursement_id': invoices.disbursement_id,
                                'name_bank_validation_id': bank_account.name_bank_validation_id,
                                'amount': disburse_amount,
                                'external_id': application.application_xid,
                                'type': 'loan',
                                'original_amount': loan.loan_amount
                                }
            disbursement = trigger_disburse(data_to_disburse, application=application)
            disbursement_id = disbursement.get_id()
            # assign disbursement_id to loan
            invoices.disbursement_id = disbursement_id
            invoices.save(update_fields=['disbursement_id'])
            disbursement.disburse()

            disbursement_data = disbursement.get_data()
            disbursements.append(disbursement_data)

            if disbursement.is_failed():
                is_false = True

            elif disbursement.is_pending():
                is_pending = True

        if is_false:
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
            change_reason = 'Fund disbursal failed'
            note = 'Disbursement failed to %s Bank %s account number %s via %s' % (
                application.email, ", ".join(d['bank_info']['bank_code'] for d in disbursements),
                ", ".join(d['bank_info']['account_number'] for d in disbursements),
                ", ".join(d['method'] for d in disbursements)
            )
            services.process_application_status_change(application.id,
                                                       new_status_code,
                                                       change_reason,
                                                       note)

        elif not is_pending:
            # check disbursement status
            # process partner transaction record
            if loan.partner and loan.partner.is_active_lender:
                services.record_disbursement_transaction(loan)

            # process change status to 180
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s account number %s via %s' % (
                application.email, ", ".join(d['bank_info']['bank_code'] for d in disbursements),
                ", ".join(d['bank_info']['account_number'] for d in disbursements),
                ", ".join(d['method'] for d in disbursements)
            )
            services.process_application_status_change(application.id,
                                                       new_status_code,
                                                       change_reason,
                                                       note)

    @record_failure
    def switch_back_to_100_and_update_app_version(self):
        application = self.application
        credit_score = get_credit_score3(application)
        if not credit_score:
            backward_status_code = ApplicationStatusCodes.FORM_CREATED
            change_reason = 'app v3 transition'
            note = 'send back application to status 100 during app v3 transition'
            status_changed = services.process_application_status_change(application.id,
                                                       backward_status_code,
                                                       change_reason,
                                                       note)
            application.refresh_from_db()
            if status_changed:
                old_app_version = application.app_version
                application.app_version = get_latest_app_version()
                application.save()

                ApplicationFieldChange.objects.create(
                    application=application,
                    field_name='app_version',
                    old_value=old_app_version,
                    new_value=application.app_version)

                logger.info({
                    'status': 'send back app to 100 and update app_version',
                    'old_app_version': old_app_version,
                    'new_app_version': application.app_version,
                    'application_id': application.id
                })

    def update_customer_data(self):
        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': self.application.customer.customer_xid,
                    'object': self.application,
                }
            ],
            force_get_local_data=True,
        )
        self.application = detokenized_applications[0]

        customer = self.application.customer
        if self.application.is_onboarding_form or self.application.is_julo_one_ios():
            data = {
                'fullname': self.application.fullname,
                'gender': self.application.gender,
                'dob': self.application.dob,
            }
            if not Customer.objects.filter(nik=self.application.ktp).exists():
                data['nik'] = self.application.ktp
            if not Customer.objects.filter(email=self.application.email).exists():
                data['email'] = self.application.email

            if customer.phone != self.application.mobile_phone_1:
                data['phone'] = self.application.mobile_phone_1

            return update_customer_data_by_application(customer, self.application, data)

        if customer.fullname != self.application.fullname:
            CustomerFieldChange.objects.create(
                customer=customer,
                field_name='fullname',
                old_value=customer.fullname,
                new_value=self.application.fullname,
                application=self.application,
            )
        if customer.phone != self.application.mobile_phone_1:
            CustomerFieldChange.objects.create(
                customer=customer,
                field_name='phone',
                old_value=customer.phone,
                new_value=self.application.mobile_phone_1,
                application=self.application,
            )
        return customer.update_safely(
            fullname=self.application.fullname,
            phone=self.application.mobile_phone_1
        )

    ########################################################
    # Post Run Actions for Merchant Financing Section

    def assign_product_lookup_to_merchant(self):
        from juloserver.partnership.services.services import get_product_lookup_by_merchant

        if not self.application.is_merchant_flow():
            raise JuloException("Application workflow must be merchant financing")
        elif not self.application.merchant:
            raise JuloException("Application does not have merchant")
        merchant = self.application.merchant

        historical_partner_cpl = get_product_lookup_by_merchant(merchant=merchant,
                                                                application_id=self.application.id,
                                                                is_work_flow_check=True)
        # assigning process
        with transaction.atomic():
            merchant.historical_partner_config_product_lookup = historical_partner_cpl
            merchant.save()
            next_status_code_121 = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            change_reason = "Passed business rules check"
            services.process_application_status_change(
                self.application.id, next_status_code_121, change_reason
            )

    ########################################################
    # Async Run Actions, sent it to the background

    def send_sms_status_change(self):
        send_sms_status_change_task.delay(self.application.id, self.change_reason)

    def send_sms_status_change_172(self):
        send_sms_status_change_172pede_task.delay(self.application.id)

    def send_sms_status_change_131(self):
        send_sms_status_change_131_task.delay(self.application.id)


    def process_documents_verified_action(self):
        process_documents_verified_action_task.delay(self.application.id)

    def run_fdc_task(self):
        from juloserver.julo.tasks import trigger_fdc_inquiry
        from juloserver.fdc.tasks import monitor_fdc_inquiry_job
        from juloserver.dana.tasks import trigger_dana_fdc_inquiry
        from juloserver.pii_vault.services import detokenize_for_model_object
        from juloserver.pii_vault.constants import PiiSource

        fdc_feature = FeatureSetting.objects.filter(feature_name="fdc_configuration",
                                                    is_active=True).last()
        if fdc_feature and not fdc_feature.parameters.get('application_process'):
            return

        # Handle request from DANA flow
        # Because KTP in application for dana is masking not a true nik
        if hasattr(self.application, 'dana_customer_data'):
            ktp = self.application.dana_customer_data.nik
        elif (
            self.application.workflow
            and self.application.workflow.name == WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW
            and hasattr(self.application, 'partnership_customer_data')
        ):
            ktp = self.application.partnership_customer_data.nik
        else:
            detokenized_applications = detokenize_for_model_object(
                PiiSource.APPLICATION,
                [
                    {
                        'customer_xid': self.application.customer.customer_xid,
                        'object': self.application,
                    }
                ],
                force_get_local_data=True,
            )
            self.application = detokenized_applications[0]
            ktp = self.application.ktp            

        fdc_inquiry = FDCInquiry(
            application_id=self.application.id, nik=ktp,
            application_status_code=self.application.status,
            customer_id=self.application.customer.id
        )
        fdc_inquiry.save()
        if self.application.is_dana_flow():
            config_data = (
                PartnershipFlowFlag.objects.filter(
                    partner_id=self.application.partner_id,
                    name=PartnershipFlag.DANA_COUNTDOWN_PROCESS_NOTIFY_CONFIG,
                )
                .values_list('configs', flat=True)
                .last()
            )
            countdown = None
            custom_queue = ""
            default_trigger = False
            if config_data:
                countdown = config_data.get('fdc_countdown', None)
                if countdown and not isinstance(countdown, int):
                    raise JuloException(
                        'countdown {} is not a number , application_id = {}'.format(
                            countdown, self.application.id
                        )
                    )
                default_trigger = config_data.get('default_trigger', False)
                custom_queue = config_data.get('fdc_queue', custom_queue)

            if custom_queue and countdown:
                trigger_dana_fdc_inquiry.apply_async(
                    kwargs={
                        'fdc_inquiry_id': fdc_inquiry.id,
                        'application_ktp': ktp,
                        'custom_queue': custom_queue,
                    },
                    countdown=countdown,
                    queue=custom_queue,
                )
            elif custom_queue:
                trigger_dana_fdc_inquiry.apply_async(
                    kwargs={
                        'fdc_inquiry_id': fdc_inquiry.id,
                        'application_ktp': ktp,
                        'custom_queue': custom_queue,
                    },
                    queue=custom_queue,
                )
            elif countdown:
                trigger_dana_fdc_inquiry.apply_async(
                    kwargs={'fdc_inquiry_id': fdc_inquiry.id, 'application_ktp': ktp},
                    countdown=countdown,
                )
            elif default_trigger:
                trigger_fdc_inquiry.apply_async(
                    kwargs={'fdc_inquiry_id': fdc_inquiry.id, 'application_ktp': ktp},
                    queue='high',
                    routing_key='high',
                )
            else:
                trigger_dana_fdc_inquiry.apply_async(
                    kwargs={'fdc_inquiry_id': fdc_inquiry.id, 'application_ktp': ktp}
                )

        else:
            trigger_fdc_inquiry.apply_async(
                (fdc_inquiry.id, ktp, self.application.status),
                countdown=30, queue='high', routing_key='high'
            )
        if self.application.is_regular_julo_one():
            monitor_fdc_inquiry_job.apply_async(
                [self.application.id],
                countdown=get_fdc_timeout_config() * 60 # X mins after fdc trigger
            )

    def update_status_apps_flyer(self):
        advance_ai_id_check = False
        if self.application.application_status.status_code == ADVANCE_AI_ID_CHECK_APP_STATUS:
            advance_ai_id_check = True
        logger.info(
            {
                "message": "update_status_apps_flyer_task triggered",
                "application_id": self.application.id,
                "advance_ai_id_check": advance_ai_id_check,
            }
        )
        update_status_apps_flyer_task.apply_async(
            (self.application.id, self.application.status, advance_ai_id_check,
             self.old_status_code, self.new_status_code), countdown=30
        )

    def run_advance_ai_task(self):
        # auto reject application if got score C
        if getattr(self.application, 'creditscore', None):
            if self.application.creditscore.score == "C":
                services.process_application_status_change(
                        self.application.id,
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        "auto_failed_in_credit_score")
            else:
                do_advance_ai_id_check_task.delay(self.application.id)

    def send_email_status_change(self):
        from juloserver.julo.services import get_email_setting_options
        email_setting = None
        if self.application.partner_name == PartnerConstant.LAKU6_PARTNER:
            email_setting = get_email_setting_options(self.application)

        have_partner_email = False
        have_customer_email = True

        if email_setting:
            if self.application.partner:
                have_customer_email = True if email_setting['send_to_partner_customer'] else False
                have_partner_email = True if email_setting['send_to_partner'] else False
            else:
                have_customer_email = True if email_setting['send_to_julo_customer'] else False

        if have_customer_email:
            send_email_status_change_task.delay(
                    self.application.id, self.new_status_code, self.change_reason,
                    to_partner=False, email_setting=email_setting)

        if have_partner_email:
            send_email_status_change_task.delay(
                    self.application.id, self.new_status_code, self.change_reason,
                    to_partner=True, email_setting=email_setting)



    def send_pn_reminder_six_hour_later(self):
        later = timezone.localtime(timezone.now()) + timedelta(hours=6)
        reminder_push_notif_application_status_105.apply_async((self.application.id,), eta=later)

    # since application v3 moved to product submission api
    def create_application_original(self):
        create_application_original_task.delay(self.application.id)

    def set_google_calender(self):
        set_google_calender_task.delay(self.application.id)

    def automate_sending_reconfirmation_email_175(self):
        sending_reconfirmation_email_175_task.delay(self.application.id)

    def send_registration_and_document_digisign(self):
        send_registration_and_document_digisign_task.delay(self.application.id)

    def register_or_update_customer_to_privy(self):
        # import here, because circular import
        from juloserver.julo_privyid.services import get_privy_feature
        from juloserver.julo_privyid.tasks import (create_new_privy_user,
                                                   update_existing_privy_customer)

        privy_feature = get_privy_feature()
        if privy_feature:
            reupload_image_type = ['selfie_ops', 'ktp_self_ops']
            reuploaded_images = Image.objects.filter(image_source=self.application.id,
                                                     image_type__in=reupload_image_type,
                                                     image_status__in=[Image.CURRENT,
                                                                       Image.RESUBMISSION_REQ])
            if not reuploaded_images:
                create_new_privy_user.delay(self.application.id)
            # else:
            #     update_existing_privy_customer.delay(self.application.id)
        elif (
            self.application.is_julo_one()
            or self.application.is_julo_one_ios()
            or self.application.is_grab()
        ):
            services.process_application_status_change(
                self.application.id,
                ApplicationStatusCodes.LOC_APPROVED,
                'Credit limit activated')

    def update_data_customer_to_privy(self):
        # import here, because circular import
        from juloserver.julo_privyid.services import get_privy_feature
        from juloserver.julo_privyid.tasks import update_data_privy_user

        privy_feature = get_privy_feature()
        if privy_feature:
            update_data_privy_user.delay(self.application.id)

    def download_sphp_from_digisign(self):
        download_sphp_from_digisign_task.delay(self.application.id)

    def create_lender_sphp(self):
        create_lender_sphp_task.delay(self.application.id)

    def create_sphp(self):
        create_sphp_task.delay(self.application.id)

    def send_back_to_170_for_disbursement_auto_retry(self):
        feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
            category="disbursement",
            is_active=True).first()
        if not feature:
            logger.info({'task': 'send_back_to_170_for_disbursement_auto_retry_task',
                         'application_id': self.application.id,
                         'status': 'feature inactive'})
            return
        params = feature.parameters
        later = timezone.localtime(timezone.now()) + timedelta(hours=params['waiting_hours'])
        send_back_to_170_for_disbursement_auto_retry_task.apply_async(
            (self.application.id, params['max_retries']), eta=later)

    def lender_auto_approval(self):
        loan = self.application.loan
        today = timezone.now()
        lender_approval = LenderApproval.objects.get_or_none(partner=loan.partner)

        if lender_approval:
            in_range = False
            if lender_approval.end_date:
                in_range = (lender_approval.start_date <= today <= lender_approval.end_date)

            in_endless = (today >= lender_approval.start_date and lender_approval.is_endless)
            if lender_approval.is_auto and ( in_range or in_endless ):
                if lender_approval.delay:
                    gaps = relativedelta(hours=lender_approval.delay.hour,
                        minutes=lender_approval.delay.minute,
                        seconds=lender_approval.delay.second)
                    if loan.is_qris_product:
                        gaps = relativedelta(seconds=15)

                    lender_auto_approval_task.apply_async((self.application.id, gaps,),
                        eta=timezone.localtime(timezone.now()) + gaps)

                else:
                    if lender_approval.is_auto:
                        lender_approval.update_safely(is_auto=False)
            else:
                if lender_approval.is_auto and today >= lender_approval.start_date:
                    lender_approval.update_safely(is_auto=False)

    def lender_auto_expired(self):
        loan = self.application.loan
        default_lender_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
            category="followthemoney",
            is_active=True).first()

        default_lender = None
        if default_lender_setting and default_lender_setting.parameters['lender_name']:
            lender_name = default_lender_setting.parameters['lender_name']
            default_lender = LenderCurrent.objects.filter(lender_name=lender_name).last()

        if default_lender == loan.lender:
            logger.info({'task': 'lender_auto_expired',
                         'application_id': self.application.id,
                         'status': 'default lender for matchkaming'})
            return

        lender_approval = LenderApproval.objects.get_or_none(partner=loan.partner)

        if not lender_approval:
            logger.info({'task': 'lender_auto_expired',
                         'application_id': self.application.id,
                         'status': 'lender_approval not found'})
            return

        gaps = timedelta(hours=lender_approval.expired_in.hour,
            minutes=lender_approval.expired_in.minute,
            seconds=lender_approval.expired_in.second)

        lender_auto_expired_task.apply_async((self.application.id, loan.lender.id,),
            eta=timezone.localtime(timezone.now()) + gaps)


    def assign_lender_signature(self):
        loan = self.application.loan

        LenderSignature.objects.get_or_create(loan=loan)
        logger.info({
            'action': 'assign_lender_signature',
            'loan': loan.id,
            'signed_ts': False
        })

    def run_index_faces(self):
        from juloserver.julo.services2.experiment import (parallel_bypass_experiment,
                                                          is_high_score_parallel_bypassed)
        from juloserver.julo.services2.high_score import (feature_high_score_full_bypass,
                                                          do_high_score_full_bypass)
        from .services2 import get_customer_service

        face_recognition = FaceRecognition.objects.get_or_none(
            feature_name='face_recognition',
            is_active=True
        )
        customer_service = get_customer_service()
        skip_pv_dv = customer_service.is_application_skip_pv_dv(self.application.id)
        if face_recognition:
            run_index_faces.delay(self.application.id, skip_pv_dv=skip_pv_dv)
        else:
            new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            change_reason = 'Passed KTP Check'
            if self.application.status == ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT:
                if skip_pv_dv:
                    change_reason = "Repeat_Bypass_DV_PV"
                    new_status_code = ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
                    # check for new parallel high score bypass experiment
                    feature = feature_high_score_full_bypass(self.application)
                    if feature:
                        do_high_score_full_bypass(self.application)
                        return

                    active_setting = parallel_bypass_experiment()
                    if active_setting:
                        parameter = active_setting.criteria
                        is_bypassed = is_high_score_parallel_bypassed(self.application, parameter)

                        if self.application.product_line_id in parameter['product_line_codes']:
                            if is_bypassed == ExperimentConst.REPEATED_HIGH_SCORE_ITI_BYPASS:
                                change_reason = ExperimentConst.REPEATED_HIGH_SCORE_ITI_BYPASS
                                new_status_code = ApplicationStatusCodes.DOCUMENTS_VERIFIED

            elif self.application.status == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
                signature_method_history_task.delay(self.application.id, 'JULO')
                new_status_code = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
                change_reason = 'face_resubmission_for_digisign_registration'
            services.process_application_status_change(
                self.application.id,
                new_status_code,
                change_reason)



    ########################################################
    # Pre Run Actions Always raise exception when fail

    def assign_loan_to_virtual_account(self):
        loan = self.application.loan
        generate_customer_va(loan)


    def process_sphp_resubmission_action(self):
        application = self.application
        images = Image.objects.filter(
            image_source=application.id,
            image_type='signature',
            image_status=Image.RESUBMISSION_REQ)
        voices = VoiceRecord.objects.filter(
            application=application, status=VoiceRecord.RESUBMISSION_REQ)
        if not images and not voices:
            raise JuloException('image and voice not found')

        if application.product_line.product_line_code not in ProductLineCodes.loc():
            loan = application.loan
            loan.sphp_accepted_ts = None
            loan.save()
        application.is_sphp_signed = False
        logger.info({
            'action': 'process_sphp_resubmission_action',
            'application': application.id,
            'is_sphp_signed': application.is_sphp_signed
        })
        application.save()
        if have_pn_device(application.device) and not application.is_julo_one():
            try:
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.inform_legal_document_resubmission(application.fullname_with_title,
                                                                application.device.gcm_reg_id, application.id)
            except GCMAuthenticationException:
                ApplicationNote.objects.create(
                    note_text='ERROR pn gagal terkirim', application_id=application.id
                )

    def process_sphp_signed_action(self):
        application = self.application
        if application.product_line.product_line_code not in ProductLineCodes.loc():
            loan = application.loan
            loan.sphp_accepted_ts = timezone.localtime(timezone.now())
            loan.save()
        logger.info({
            'action': 'process_sphp_signed_action',
            'application': application.id,
            'is_sphp_signed': application.is_sphp_signed
        })
        application.save()
        if have_pn_device(application.device) and not application.is_julo_one():
            try:
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.inform_legal_document_signed(application.device.gcm_reg_id, application.id)
            except GCMAuthenticationException:
                pass

    def disbursement_validate_bank(self):
        bank_entry = banks.BankManager.get_by_name_or_none(self.application.bank_name)
        if bank_entry is None:
            raise JuloException('bank name not found')

    def assigning_optional_field(self):
        application = self.application
        if application.product_line.product_line_code in ProductLineCodes.bri():
            bank_bri = BankManager.get_by_code_or_none(BankCodes.BRI)
            application.bank_name = bank_bri.bank_name
            if not application.payday:
                application.payday = 1
        if application.partner:
            if application.partner.is_grab:
                application.payday = 1

    def auto_populate_expenses(self):
        application = self.application
        feature_setting = FeatureSetting.objects.filter(feature_name=AUTO_POPULATE_EXPENSES, is_active=True).last()
        if not feature_setting:
            return
        app_names = feature_setting.parameters['app_names']
        sd_device_apps = SdDeviceApp.objects.filter(application_id=application.id,
                                                    app_name__in=app_names)
        for sd_device_app in sd_device_apps:
            with transaction.atomic():
                add_expense = AdditionalExpense.objects.create(
                    application=application,
                    field_name='total_current_debt',
                    description= sd_device_app.app_name,
                    amount= 1,
                    group= 'sd'
                )
                # create add history
                AdditionalExpenseHistory.objects.create(
                    application=application,
                    additional_expense=add_expense,
                    field_name='total_current_debt',
                    old_description='',
                    old_amount=0,
                    new_description= sd_device_app.app_name,
                    new_amount= 1,
                    group= 'sd'
                )

    def show_offers(self):
        application = self.application
        offers = list(Offer.objects.filter(application=application))
        if not offers:
            raise JuloException("No offer is created")

        with transaction.atomic():
            approved_offer = 0
            for offer in offers:
                # Installment amount is re-calculated since credit analyst may
                # adjust the numbers initially generated.
                if application.product_line.product_line_code not in ProductLineCodes.stl():
                    offer.set_installment_amount_offer()

                offer.set_expiration_date()
                offer.save()
                if offer.is_approved:
                    approved_offer += 1

            if approved_offer < len(offers):
                raise JuloException('offer_is_not_approved')
        if have_pn_device(application.device) and not application.is_julo_one():
            julo_pn_client = get_julo_pn_client()
            julo_pn_client.inform_offers_made(
                application.customer.fullname, application.device.gcm_reg_id, application.id)

    def accept_default_offer(self):
        application = self.application
        offer = Offer.objects.filter(application=application).order_by('offer_number').first()
        if not offer:
            raise JuloException("No offer is created")
        if not offer or offer.is_accepted:
            raise JuloException("Offer is already accepted")
        if not offer.is_approved:
            raise JuloException("Agent must edit and approve the offer first")

        with transaction.atomic():

            # Installment amount is re-calculated since credit analyst may
            # adjust the numbers initially generated.
            if application.product_line.product_line_code not in (ProductLineCodes.stl() + ProductLineCodes.grab()):
                if application.product_line.product_line_code in ProductLineCodes.axiata():
                    update_axiata_offer(offer)
                else:
                    offer.set_installment_amount_offer()

            offer.set_expiration_date()
            offer.mark_accepted()
            offer.save()

            loan_and_payments_created = services.create_loan_and_payments(offer)
        if not loan_and_payments_created:
            raise JuloException('failed when reate loan and payment')

        application = offer.application
        logger.info({
            'application_status': application.application_status.status,
            'action': 'creating_loan_and_payments',
            'status': 'offer_just_accepted'
        })

    def accept_partner_offer(self):
        application = self.application
        offer = Offer.objects.filter(application=application).order_by('offer_number').first()
        if not offer:
            raise JuloException("No offer is created")
        if not offer or offer.is_accepted:
            raise JuloException("Offer is already accepted")
        if not offer.is_approved:
            raise JuloException("Agent must edit and approve the offer first")

        with transaction.atomic():

            # Installment amount is re-calculated since credit analyst may
            # adjust the numbers initially generated.
            if application.product_line.product_line_code not in (
                    ProductLineCodes.stl() + ProductLineCodes.grab() + ProductLineCodes.pedestl()):
                offer.set_installment_amount_offer()

            offer.set_expiration_date()
            offer.mark_accepted()
            offer.save()

        application = offer.application
        logger.info({
            'application_status': application.application_status.status,
            'action': 'update_offer',
            'status': 'offer_just_accepted'
        })

    def create_loan_payment_partner(self):
        application = self.application
        offer = Offer.objects.filter(application=application).order_by('offer_number').first()
        partner_name = application.partner.name
        loan_and_payments_created = None
        with transaction.atomic():
            if partner_name == PartnerConstant.PEDE_PARTNER:
                loan_and_payments_created = services.create_loan_and_payments(offer)
            else:
                loan_and_payments_created = services.create_loan_and_payments_laku6(offer)

        if not loan_and_payments_created:
            raise JuloException('failed when reate loan and payment')

        application = offer.application
        logger.info({
            'application_status': application.application_status.status,
            'action': 'creating_loan_and_payments',
            'status': 'created_loan_and_payments'
        })

    def show_legal_document(self):
        """This is after activation call is successful"""
        application = self.application
        if application.product_line.product_line_code not in ProductLineCodes.loc()\
            + ProductLineCodes.grabfood() + ProductLineCodes.laku6() + ProductLineCodes.pede():
            loan = application.loan
            loan.sphp_sent_ts = timezone.localtime(timezone.now())
            services.update_loan_and_payments(loan)

        if application.product_line.product_line_code in ProductLineCodes.grabfood():
            loan = application.loan
            loan.sphp_sent_ts = timezone.localtime(timezone.now())

        application.set_sphp_expiration_date()
        application.save()
        if have_pn_device(application.device) and not application.is_julo_one():
            julo_pn_client = get_julo_pn_client()
            julo_pn_client.inform_legal_document(
                application.customer.fullname, application.device.gcm_reg_id, application.id)

    def accept_selected_offer(self):
        application = self.application

        offer = Offer.objects.filter(application=application).accepted().first()
        if offer is None:
            logger.warn({
                'status': 'no_offer_accepted',
                'application': application
            })
            raise JuloException('no_offer_accepted')

        if not offer.just_accepted:
            logger.warn({
                'status': 'loan_already_created',
                'application': application
            })
            raise JuloException('loan_already_created')

        loan_and_payments_created = services.create_loan_and_payments(offer)
        if not loan_and_payments_created:
            logger.warn({
                'status': 'loan_payments_not_created',
                'application': application
            })
            raise JuloException('loan_payments_not_created')

        application = offer.application
        application.change_status(ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER)
        application.save()
        logger.info({
            'application_status': application.application_status.status,
            'status': 'offer_just_accepted_by_customer'
        })

    def process_sphp_resubmitted_action(self):
        application = self.application
        if application.product_line.product_line_code not in ProductLineCodes.loc():
            loan = application.loan
            loan.sphp_accepted_ts = timezone.localtime(timezone.now())
            loan.save()

        logger.info({
            'action': 'process_sphp_resubmission_action',
            'application': application.id,
            'is_sphp_signed': application.is_sphp_signed
        })
        application.save()
        if have_pn_device(application.device):
            try:
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.inform_legal_document_resubmitted(
                    application.device.gcm_reg_id, application.id)
            except GCMAuthenticationException:
                ApplicationNote.objects.create(
                    note_text='ERROR pn gagal terkirim', application_id=application.id
                )

    # set application workflow by product for application v2 (for v3 moved to product_submission api)
    def switch_to_product_default_workflow(self):
        product = self.application.product_line
        old_workflow = self.application.workflow
        if not old_workflow:
            return
        if product.default_workflow:
            product_workflow = product.default_workflow
        else:
            product_workflow = Workflow.objects.get(name='CashLoanWorkflow')
        with transaction.atomic(using='onboarding_db'):
            self.application.workflow = product_workflow
            self.application.save()
            ApplicationWorkflowSwitchHistory.objects.create(
                application_id=self.application.id,
                workflow_old=old_workflow.name,
                workflow_new=product_workflow.name,
            )

        # send pn to reinstall new version
        if have_pn_device(self.application.device):
            try:
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.inform_old_version_reinstall(
                    self.application.device.gcm_reg_id, self.application.id)
            except GCMAuthenticationException:
                ApplicationNote.objects.create(
                    note_text='ERROR pn 110 handler', application_id=self.application.id
                )

        # force application to be rejected
        services.process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            "using old version")

    def create_and_assign_loc(self):
        from ..line_of_credit.services import LineOfCreditService
        app = self.application
        with transaction.atomic():
            loc = LineOfCreditService.create(self.application.customer.id)
            app.line_of_credit = loc
            app.save()

    def activate_loc(self):
        from ..line_of_credit.services import LineOfCreditService
        app = self.application
        LineOfCreditService.set_active(app.line_of_credit.id, app.payday)

    def adjust_monthly_income_by_iti_score(self):
        """
        Logic as specified here: https://trello.com/c/FZ3Kb3Ul/
        """
        application = self.application

        if application.product_line_code in ProductLineCodes.grab():
            return

        iti_experiment_code = "PVXITI"
        application_experiment = ApplicationExperiment.objects.filter(
            application=application, experiment__code__contains=iti_experiment_code).first()
        if not application_experiment:
            return

        iti_result = PdIncomeTrustModelResult.objects.filter(
            application_id=application.id).last()

        if not iti_result:
            return

        if iti_result.predicted_income > application.monthly_income:
            return

        stated_income = application.monthly_income
        predicted_income = iti_result.predicted_income
        application.monthly_income = predicted_income
        application.save()

        ApplicationFieldChange.objects.create(
            application=application, field_name='monthly_income',
            old_value=stated_income, new_value=predicted_income)

        logger.info({
            'status': 'monthly_income_adjusted',
            'stated_income': stated_income,
            'predicted_income': predicted_income,
            'application_id': application.id
        })


    def grab_food_generate_loan_and_payment(self):
        application = self.application
        offer = Offer.objects.filter(application=application).order_by('offer_number').first()
        if not offer:
            raise JuloException("No offer is created")
        if offer.is_accepted:
            raise JuloException("Offer is already accepted")
        if not offer.is_approved:
            raise JuloException("Agent must edit and approve the offer first")

        with transaction.atomic():
            offer.set_expiration_date()
            offer.mark_accepted()
            offer.save()

            today_date = timezone.localtime(timezone.now()).date()

            principal, interest, installment = compute_weekly_payment_installment(
                offer.loan_amount_offer, offer.loan_duration_offer, offer.product.interest_rate)

            loan = Loan.objects.create(
                customer=offer.application.customer,
                application=offer.application,
                offer=offer,
                loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
                product=offer.product,
                loan_amount=offer.loan_amount_offer,
                loan_duration=offer.loan_duration_offer,
                first_installment_amount=installment,
                installment_amount=installment)

            loan.cycle_day = offer.first_payment_date.day
            loan.set_disbursement_amount()
            loan.save()
            payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
            due_date = today_date
            for payment_number in range(loan.loan_duration):
                due_date = next_grab_food_payment_date(due_date)
                payment = Payment.objects.create(
                    loan=loan,
                    payment_status=payment_status,
                    payment_number=payment_number + 1,
                    due_date=due_date,
                    due_amount=installment,
                    installment_principal=principal,
                    installment_interest=interest)

                logger.info({
                    'loan': loan,
                    'payment_number': payment_number,
                    'payment_amount': payment.due_amount,
                    'due_date': due_date,
                    'payment_status': payment.payment_status.status,
                    'status': 'payment_created'
                })

        logger.info({
            'application_status': application.application_status.status,
            'action': 'creating_loan_and_payments',
            'status': 'offer_just_accepted'
        })

    def check_is_credit_score_ready(self):
        application = self.application
        is_credit_score_ready = getattr(application, 'creditscore', False)
        if not is_credit_score_ready:
            raise JuloException("Credit Score is not available, please contact engineer!")

    def assign_lender_to_loan(self):
        application = self.application
        loan = self.application.loan
        is_julo = self.is_julo_email(application.email)

        if not is_julo:
            if application.product_line.product_line_code in ProductLineCodes.lended_by_bri():
                loan.partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
            elif application.product_line.product_line_code in ProductLineCodes.lended_by_grab():
                loan.partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)
            else:
                lender = services.assign_lender_to_disburse(application)
                loan.lender = lender
                # this only for handle FTM
                loan.partner = lender.user.partner
            loan.save()


    def is_julo_email(self, app_email):
        return app_email is not None and 'julofinance.com' in app_email

    def bulk_disbursement_assignment(self):
        from juloserver.paylater.services import process_bank_validation

        application = self.application
        partner = application.partner
        product_line = application.product_line
        loan = self.application.loan
        lender = loan.lender
        method = "Xfers"
        loan_partner = loan.partner

        today = timezone.localtime(timezone.now())
        external_id = "{}{}{}".format(str(loan_partner.id), today.date(), str(product_line.product_line_code))
        external_id = external_id.replace("-", "")

        with transaction.atomic():
            disbursement_obj = Disbursement2.objects.select_for_update().filter(external_id=external_id).first()

            if not disbursement_obj:
                name_bank_validation_id, msg = process_bank_validation(partner, method)
                if not name_bank_validation_id:
                    raise JuloException('image and voice not found')
                    return {
                        "status": "failed",
                        "message": "failed disbursement",
                        "reason": msg
                    }

                data_to_disburse = {'disbursement_id': None,
                                    'name_bank_validation_id': name_bank_validation_id,
                                    'amount': loan.loan_disbursement_amount,
                                    'original_amount': loan.loan_amount,
                                    'external_id': external_id,
                                    'type': "bulk"
                                    }
                disbursement = trigger_disburse(data_to_disburse, method=method)
                disbursement_obj = disbursement.disbursement

            else:
                disbursement_obj.original_amount = disbursement_obj.original_amount + loan.loan_amount
                disbursement_obj.amount = disbursement_obj.amount + loan.loan_disbursement_amount
                disbursement_obj.save(update_fields=['original_amount', 'amount'])
                disbursement_obj.refresh_from_db()

            loan.disbursement_id = disbursement_obj.id
            loan.save(update_fields=['disbursement_id'])

            #follow the money block
            try:
                with transaction.atomic():
                    update_committed_amount_for_lender_balance(disbursement_obj, loan.id)
            except JuloException as exception:
                raise exception
            # end of follow the money block


################################################################################
# After : function run After change status

    def delete_lead_data_from_primo(self):
        application = self.application
        if application.product_line_id in ProductLineCodes.loc():
            return
        primo_record = PrimoDialerRecord.objects.filter(application=application,
            lead_status__in=[PrimoLeadStatus.SENT, PrimoLeadStatus.COMPLETED]).last()
        primo_client = get_primo_client()
        if primo_record:
            response = primo_client.delete_primo_lead_data(primo_record.lead_id)
            if response.status_code != HTTP_200_OK:
                logger.warn({
                    'application': application,
                    'primo_record': primo_record,
                    'action': 'delete_lead_data',
                    'status': 'delete_lead_data_failed',
                    'response': response.content
                })
            else:
                if primo_record.lead_status == PrimoLeadStatus.SENT:
                    primo_record.lead_status = PrimoLeadStatus.DELETED
                    primo_record.save()
                logger.info({
                    'application': application,
                    'primo_record': primo_record,
                    'action': 'delete_lead_data',
                    'status': 'delete_lead_data_success',
                    'response': response.content
                })

    def process_experiment_bypass(self):
        application = self.application

        # experiment criteria new itiv5
        if not application.product_line or\
            application.product_line.product_line_code not in (ProductLineCodes.stl()+ProductLineCodes.mtl()):
                return

        # check feature active
        today = timezone.now()

        feature_iti_122 = ExperimentSetting.objects.get_or_none(
            code=BYPASS_ITI_EXPERIMENT_122,
            is_active=True)
        if feature_iti_122:
            if feature_iti_122.is_permanent or (feature_iti_122.start_date <= today <= feature_iti_122.end_date):
                pass_criteria = experiment_check_criteria(
                    'application_id',
                    feature_iti_122.criteria,
                    application.id)

                if not pass_criteria:
                    return

                if not check_iti_repeat(application.id):
                    return

                # ner check sms and email
                data_check = AutoDataCheck.objects.filter(
                                application_id=application.id,
                                data_to_check='experiment_iti_ner_sms_email',
                                is_okay=True).last()
                if not data_check:
                    return

                # replaced by this card ENH-122 Improve ITI affordability calculation to use Affordability Model
                affordability_status, affordability = calculation_affordability_based_on_affordability_model(
                    application, is_with_affordability_value=True)

                if not affordability_status:
                    return

                # do bypass
                experiment_service = get_bypass_iti_experiment_service()

                bypass_loan_duration_iti = experiment_service.bypass_loan_duration_iti_122_to_172(
                    application, affordability, application.loan_amount_request,
                    application.loan_duration_request
                )

                if not bypass_loan_duration_iti:
                    experiment_service.bypass_mae_iti_122_to_172(
                        application, affordability, application.loan_amount_request,
                        application.loan_duration_request, BYPASS_ITI_EXPERIMENT_122
                    )

    def process_experiment_iti_low_threshold(self):
        application = self.application
        application.refresh_from_db()

        if not application.product_line or\
            application.product_line.product_line_code not in (ProductLineCodes.stl()+ProductLineCodes.mtl()) or \
            application.application_status_id != ApplicationStatusCodes.DOCUMENTS_VERIFIED:
                return

        # do bypass
        experiment_service = get_bypass_iti_experiment_service()
        is_experiment_iti_low = experiment_service.bypass_iti_low_122_to_124(application)

        if is_experiment_iti_low:
            experiment_service.set_default_skiptrace(application.customer_id)
            services.process_application_status_change(
                application.id,
                ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                ITI_LOW_THRESHOLD)

    def process_offer_experiment_iti_low_threshold(self):
        application = self.application

        app_iti_low = application.applicationhistory_set.filter(
            change_reason=ITI_LOW_THRESHOLD
        )
        if app_iti_low:
            experiment_service = get_bypass_iti_experiment_service()
            experiment_service.bypass_iti_low_130_to_172(application)

    def process_experiment_repeat_high_score_ITI_bypass(self):
        from .services2.experiment import parallel_bypass_experiment

        application = self.application

        # is the application is repeat high score ITI bypass?
        last_history = application.applicationhistory_set.last()
        if last_history.change_reason == ExperimentConst.REPEATED_HIGH_SCORE_ITI_BYPASS:
            # Calcuation affordability experiment
            affordability_status, affordability = calculation_affordability_based_on_affordability_model(
                application, is_with_affordability_value=True)

            # get amount and duration by affordability
            recomendation_offers = services.get_offer_recommendations(
                application.product_line_id,
                application.loan_amount_request,
                application.loan_duration_request,
                affordability,
                application.payday,
                application.ktp,
                application.id,
                application.partner
            )

            if affordability <= 0 or not recomendation_offers['offers']:
                services.process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                    ExperimentConst.REPEATED_HIGH_SCORE_ITI_BYPASS)
                return

            experiment_service = get_bypass_iti_experiment_service()
            # do bypass
            experiment_service.bypass_iti_122_to_172(
                application, affordability, application.loan_amount_request,
                application.loan_duration_request, BYPASS_ITI_EXPERIMENT_122
            )
            return


    def process_experiment_bypass_iti_125(self):
        application = self.application
        # experiment criteria second last digit from app_xid in 1, 2, 3
        if str(application.application_xid)[-1] not in CRITERIA_EXPERIMENT_ITI_123 or\
            not application.product_line or\
            application.product_line.product_line_code not in (ProductLineCodes.stl()+ProductLineCodes.mtl()):
                return
        # check feature active
        feature = FeatureSetting.objects.filter(feature_name=BYPASS_ITI_EXPERIMENT_125, is_active=True).last()
        if not feature:
            return
        # get application original
        application_original =  ApplicationOriginal.objects.filter(current_application=application.id).last()
        if not application_original:
            return
        # replaced by this card ENH-122 Improve ITI affordability calculation to use Affordability Model
        affordability_status, affordability = calculation_affordability_based_on_affordability_model(
            application, is_with_affordability_value=True)
        if not affordability_status:
            return
        # Exclusion experiment to 135
        experiment_service = get_bypass_iti_experiment_service()
        exclusion_status = experiment_service.exclusion_bypass_iti_experiment(application, affordability, application.monthly_income)
        if exclusion_status:
            experiment_service.bypass_iti_125_to_135(application)
            return
        skip_compared = False
        if application.product_line != application_original.product_line:
            skip_compared = True
        # process experiment bypass 125 to 141
        experiment_service.bypass_iti_125_to_141(application, affordability, application.loan_amount_request,
                                                 application.loan_duration_request, skip_compared=skip_compared)

    def app122queue_set_called(self):
        application = self.application
        if hasattr(application, "autodialer122queue"):
            autodialer122queue = application.autodialer122queue
            autodialer122queue.is_agent_called = True
            autodialer122queue.save()

    def create_icare_axiata_offer(self):
        from juloserver.merchant_financing.utils import get_partner_product_line
        today = timezone.localtime(timezone.now()).date()
        product_line = self.application.product_line
        interest_rate = product_line.max_interest_rate
        loan_duration = self.application.loan_duration_request

        if loan_duration > product_line.max_duration:
            loan_duration = product_line.max_duration

        if self.application.partner.name == PartnerConstant.ICARE_PARTNER:
            product_lookup = ProductLookup.objects.filter(
                interest_rate=interest_rate,
                product_line=product_line).first()
        elif self.application.partner.name == PartnerConstant.AXIATA_PARTNER:
            axiata_customer_data = AxiataCustomerData.objects.filter(
                application=self.application.id).last()

            _product_line, product_lookup = get_partner_product_line(
                axiata_customer_data.interest_rate,
                axiata_customer_data.origination_fee,
                axiata_customer_data.admin_fee,
                product_line.product_line_code
            )

            if not product_lookup:
                raise JuloException("product lookup doesn't exist")


        if self.application.partner.name == 'icare':
            # get first_payment_date
            first_payment_date_requested = determine_first_due_dates_by_payday(
                self.application.payday, today, product_line.product_line_code, loan_duration)
            # get first_installment_requested
            _, _, first_installment_requested = compute_adjusted_payment_installment(
                self.application.loan_amount_request, loan_duration,
                product_lookup.monthly_interest_rate,
                today, first_payment_date_requested)

            _, _, installment_requested = compute_payment_installment(
                self.application.loan_amount_request, loan_duration,
                product_lookup.monthly_interest_rate)
        elif self.application.partner.name == 'axiata':
            axiata_customer_data = AxiataCustomerData.objects.filter(
                application=self.application).last()

            first_payment_date_requested = axiata_customer_data.first_payment_date

            _, _, installment = compute_adjusted_payment_installment(
                self.application.loan_amount_request, loan_duration,
                product_lookup.monthly_interest_rate, today,
                first_payment_date_requested)
            installment_requested = installment
            first_installment_requested = installment

        offer = Offer.objects.create(
            offer_number=1,
            loan_amount_offer=self.application.loan_amount_request,
            loan_duration_offer=loan_duration,
            installment_amount_offer=installment_requested,
            first_installment_amount=first_installment_requested,
            is_accepted=False,
            application=self.application,
            product=product_lookup,
            is_approved=True,
            first_payment_date=first_payment_date_requested)
        logger.info({
            'action': 'calculation_experiment_offer',
            'application_id': self.application.id,
            'accepted_amount': self.application.loan_amount_request,
            'accepted_duration': self.application.loan_duration_request,
            'first_installment_requested': first_installment_requested,
            'first_payment_date_requested': first_payment_date_requested,
            'installment_requested': installment_requested,
            'product': str(product_lookup)
        })
        return offer

    def score_partner_notify(self):
        application = self.application
        score = get_credit_score_partner(application.id)

        send_partner_notify(application, score)
        return score

    def get_failed_reason(self, credit_score):
        failed_reason = ""
        if credit_score.score_tag == ScoreTag.C_LOW_CREDIT_SCORE:
            failed_reason = "failed_in_credit_score"
        elif credit_score.score_tag == ScoreTag.C_FAILED_BINARY:
            failed_reason = "failed_in_binary_check"
            if credit_score.failed_checks:
                # get the highest penalty fit failed_reason
                high_failed_reason = services.get_highest_reapply_reason(credit_score.failed_checks)
                failed_reason = high_failed_reason if high_failed_reason else failed_reason
        return failed_reason

    def handle_line_partner_document_verified_post_action(self):
        application = self.application
        is_reject = False
        next_status_code = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        if self.application.partner_name == PartnerConstant.PEDE_PARTNER:
            # do recalculate offer with affordability
            if application.loan_duration_request > 1:
                product_codes = ProductLineCodes.pedemtl()
            else:
                product_codes = ProductLineCodes.pedestl()
            queryset = ProductLine.objects.filter(product_line_code__in=product_codes)
            loan = Loan.objects.filter(customer=application.customer).paid_off().first()

            product_line_list = queryset.repeat_lines() if loan else queryset.first_time_lines()
            application.product_line = product_line_list.first()
            application.save()

            affordability, monthly_income = calculation_affordability(
                application.id, application.monthly_income, application.monthly_housing_cost,
                application.monthly_expenses, application.total_current_debt)

            experiment_service = get_bypass_iti_experiment_service()
            # get amount and duration by affordability
            loan_amount_offer, loan_duration_offer = experiment_service.get_amount_and_duration_by_affordability(
                application, affordability, application.loan_amount_request,
                application.loan_duration_request)

            is_reject = True
            if affordability <= 0 or loan_amount_offer is None:
                services.process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.APPLICATION_DENIED,
                    "failed_in_ITI")
            else:
                next_status_code = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING

                recomendation_offers = get_pede_offer_recommendations(
                    application.product_line_code,
                    loan_amount_offer,
                    loan_duration_offer,
                    affordability,
                    application.payday,
                    application.id)

                offer_data = recomendation_offers['requested_offer']
                product = ProductLookup.objects.get(pk=offer_data['product'])
                offer_data['application'] = application
                offer_data['offer_number'] = 1
                offer_data['is_approved'] = True
                offer_data['is_accepted'] = False
                offer_data['product'] = product
                offer_data.pop('can_afford')

                Offer.objects.create(**offer_data)

        if not is_reject:
            credit_score = self.score_partner_notify()
            services.process_application_status_change(
                application.id,
                next_status_code,
                "auto_triggered")

    def change_status_130_to_172(self):
        credit_score = self.score_partner_notify()  # noqa
        next_status_code = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING
        services.process_application_status_change(
            self.application.id,
            next_status_code,
            "auto_triggered")

    def callback_to_partner(self):
        """callback to Laku6 for customer that rejected 135 by Agent"""
        score = "C"
        message = "Anda belum dapat mengajukan pinjaman "+\
                  "PRIO RENTAL karena belum memenuhi kriteria pinjaman yang ada."
        credit_limit = 0
        score_obj = CreditScore(score=score, message=message, credit_limit=credit_limit)
        send_partner_notify(self.application, score_obj)

        logger.info({
            'action': 'callback_to_partner',
            'application_id': self.application.id,
        })

    def ac_bypass_experiment(self):
        skip_validation = False
        application = self.application
        customer = application.customer
        good_customer = False

        if application.product_line_code in [ProductLineCodes.MTL1, ProductLineCodes.STL1]:
            return False

        app_iti_low = application.applicationhistory_set.filter(
            change_reason=ITI_LOW_THRESHOLD)
        if app_iti_low:
            return False

        if application.product_line_code in [ProductLineCodes.MTL2, ProductLineCodes.STL2]:
            skip_validation = services.check_good_customer_or_not(customer)
            if skip_validation:
                good_customer = True
            if application.status == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                skip_validation = False

        status = application.applicationhistory_set.filter(
            status_old=ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            status_new=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )

        # checked status change from 120 to 141
        high_bypass = application.applicationhistory_set.filter(
            status_old=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            status_new=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )
        if high_bypass and application.product_line_code in [ProductLineCodes.MTL1, ProductLineCodes.STL1]:
            status = True
        if status and not skip_validation:
            return
        experiment = Experiment.objects.filter(code=ACBYPASS_141).last()

        if not experiment.is_active:
            return

        if (good_customer) or (application.product_line_code in [
            ProductLineCodes.MTL1, ProductLineCodes.STL1]):
            experiment_service = get_bypass_iti_experiment_service()
            if self.application.status == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER or \
                self.application.status == ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING:
                experiment_service.ac_bypass_141_to_150(self.application)
            else:
                if not self.application.is_julo_one():
                    experiment_service.sms_loan_approved(self.application)

    def eligibe_check_tokopedia_october_campaign(self):
        services.eligibe_check_tokopedia_october_campaign(self.application)

    def check_tokopedia_eligibe_january_campaign(self):
        services.check_tokopedia_eligibe_january_campaign(self.application)

    def check_customer_promo(self):
        services.check_customer_promo(self.application)

    def assign_to_legal_expired(self):
        process_after_digisign_failed.apply_async((self.application.id,),
            eta=timezone.localtime(timezone.now()) + timedelta(days=3))

    def assign_lender_in_loan(self):
        services.assign_lender_in_loan(self.application)

    def process_verify_ktp(self):
        processverifyktp = ProcessVerifyKTP(self.application)
        processverifyktp.process_verify_ktp()

    def send_application_event_by_certain_pgood(self, status_code):
        send_event_by_pgood_from_app_flow_services(
            self.application, status_code, ApplicationStatusEventType.APPSFLYER_AND_GA
        )

    def send_application_event_base_on_mycroft(self, status_code):
        send_event_by_mycroft_from_app_flow_services(
            self.application, status_code, ApplicationStatusEventType.APPSFLYER_AND_GA
        )

    def send_application_event_for_x105_bank_name_info(self):
        send_event_by_x105_from_app_flow_services(
            self.application,
            ApplicationStatusEventType.APPSFLYER_AND_GA,
        )

    def send_event_to_ga(self, event):
        app_instance_id = self.application.customer.app_instance_id
        if app_instance_id:
            if event == GAEvent.X190:
                send_event_to_ga_task_async.apply_async(
                    kwargs={'customer_id': self.application.customer.id, 'event': event}
                )
            elif event == GAEvent.REFERRAL_CODE_USED:
                if not self.application.referral_code:
                    return
                customer_referred = Customer.objects.get_or_none(
                    self_referral_code=self.application.referral_code.upper())
                referral_system = ReferralSystem.objects.filter(
                    name='PromoReferral', is_active=True
                ).first()
                if not referral_system or not customer_referred:
                    return
                account = customer_referred.account
                if account.status_id != AccountConstant.STATUS_CODE.active:
                    return
                send_event_to_ga_task_async.apply_async(
                    kwargs={'customer_id': self.application.customer.id, 'event': event}
                )

    def check_face_similarity(self):
        checkfacesimilarity = CheckFaceSimilarity(self.application)
        checkfacesimilarity.check_face_similarity()

    def face_matching_task(self):
        face_matching_task.delay(self.application.id)

    def underperforming_referral_deny_application(self):
        if self.application.status != ApplicationStatusCodes.FORM_PARTIAL:
            logger.warning(
                {
                    "message": f"Block attempt from application status {self.application.status}",
                    "action": "underperforming_referral_deny_application",
                    "application_id": self.application.id,
                }
            )
            return
        services.process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason="under performing partner",
        )

    def check_fraud_bank_account_number(self):
        # checks bank account prefix
        # returns True if moved to 133, else returns False
        account_number = self.application.bank_account_number
        application_bank_name = self.application.bank_name
        if not account_number or not application_bank_name:
            logger.warning(
                {
                    'message': 'Account number or bank name not exist',
                    'action': 'check_fraud_bank_account_number',
                    'application_id': self.application.id,
                    'bank_name': application_bank_name,
                    'account_number': account_number,
                }
            )
            raise JuloException("Account number or bank name not exist")

        bank_entry = BankManager.get_by_name_or_none(application_bank_name)
        if not bank_entry:
            logger.warning(
                {
                    'message': 'Bank not found',
                    'action': 'check_fraud_bank_account_number',
                    'application_id': self.application.id,
                    'bank_name': application_bank_name,
                }
            )
            raise JuloException("Bank not found")

        for prefix, bank_code in FraudBankAccountConst.REJECTED_BANK_ACCOUNT_NAMES.items():
            if str(account_number).startswith(str(prefix)) and bank_entry.bank_code == bank_code:
                change_reason = FraudBankAccountConst.REJECTED_BANK_ACCOUNT_MESSAGE[prefix]
                services.process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    change_reason,
                )

                logger.info(
                    {
                        'message': 'Fraud Bank Account Number Blocked',
                        'action': 'check_fraud_bank_account_number',
                        'application_id': self.application.id,
                        'bank_name': bank_entry.bank_code,
                        'prefix': prefix,
                        'reason': change_reason,
                    }
                )
                return True
        return False

    def is_terms_agreed(self):
        return self.application.is_term_accepted and self.application.is_verification_agreed

    def partnership_check_liveness_result(self):
        from juloserver.partnership.constants import PartnershipPreCheckFlag
        from juloserver.partnership.models import PartnershipApplicationFlag
        """
        for now we skip check liveness for webview leadgen.
        webview leadgen will have a liveness on the future
        """
        if (
            self.application.partner_name in PartnerNameConstant.list_partnership_web_view()
            or self.application.partner_name == PartnerNameConstant.QOALASPF
        ):
            logger.info({
                'action': 'skip_process_get_liveness_detection_result',
                'message': 'skip check liveness for webview leadgen',
                'application_id': self.application.id
            })
            return
        """
            Check if application is agent-assisted flow
        """
        partnership_application_id = self.application.id
        check_application_flag_name = (
            PartnershipApplicationFlag.objects.filter(application_id=partnership_application_id)
            .values_list('name', flat=True)
            .last()
        )

        if check_application_flag_name and check_application_flag_name in (
            PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK
        ):
            logger.info({
                'action': 'skip_process_get_liveness_detection_result',
                'message': 'skip check liveness for agent-assisted flow',
                'application_id': self.application.id
            })
            return

        # to check liveness already manual checking from ops or not
        if check_liveness_detour_workflow_status_path(
            self.application,
            ApplicationStatusCodes.FORM_PARTIAL,
            status_old=self.old_status_code,
            change_reason=self.change_reason,
        ):
            logger.info({
                'action': 'skip_process_get_liveness_detection_result',
                'message': 'manual check liveness from ops',
                'application_id': self.application.id
            })
            return

        is_feature_active = get_smile_liveness_config('web')
        liveness_info = get_liveness_info(self.application.customer)
        active_liveness = liveness_info.get('active_liveness_detection')
        passive_liveness = liveness_info.get('passive_liveness_detection')

        is_active_liveness_passed = (
            active_liveness and not active_liveness.get('status') == LivenessCheckStatus.PASSED
        )
        is_passive_liveness_passed = (
            passive_liveness and not passive_liveness.get('status') == LivenessCheckStatus.PASSED
        )

        """
        this condition to handle if feature is off and result smile liveness is fail/no record
        """
        if not is_feature_active and not is_active_liveness_passed and not is_passive_liveness_passed:
            logger.info({
                'action': 'skip_process_get_liveness_detection_result',
                'message': 'feature is off and no record liveness/fail',
                'application_id': self.application.id
            })
            return
        
        """
        this condition to handle if feature is active and result smile liveness is fail/no record
        """
        if is_feature_active and not is_active_liveness_passed and not is_passive_liveness_passed:
            logger.info({
                'action': 'skip_process_get_liveness_detection_result',
                'message': 'feature is active and no record liveness/fail',
                'application_id': self.application.id
            })
            return

        if not get_liveness_detection_result(self.application):
            services.process_application_status_change(
                self.application.id,
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                "Manual image verification from ops")

    def remove_application_from_fraud_application_bucket(self):
        if self.old_status_code != ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS:
            return

        from juloserver.fraud_security.tasks import remove_application_from_fraud_application_bucket

        logger.info(
            {
                'action': 'remove_application_from_fraud_application_bucket',
                'application_id': self.application.id,
            }
        )
        execute_after_transaction_safely(
            lambda: remove_application_from_fraud_application_bucket.delay(self.application.id),
        )

################################################################################

payment_path_origin_mapping = (

    {
        # 310
        'origin_status': PaymentStatusCodes.PAYMENT_NOT_DUE,  # 310
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_ON_TIME,  # 330
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,  # 311
                'action': []
            },
        )
    },
    {
        # 311
        'origin_status': PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,  # 311
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_ON_TIME,  # 330
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_DUE_TODAY,  # 312
                'action': []
            },
        )
    },
    {
        # 312
        'origin_status': PaymentStatusCodes.PAYMENT_DUE_TODAY,  # 312
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_ON_TIME,  # 330
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_1DPD,  # 320
                'action': []
            },
        )
    },
    {
        # 320
        'origin_status': PaymentStatusCodes.PAYMENT_1DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,  # 331
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_5DPD,  # 321
                'action': []
            },
        )
    },
    {
        # 321
        'origin_status': PaymentStatusCodes.PAYMENT_5DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_LATE,  # 332
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_30DPD,  # 322
                'action': []
            },
        )
    },
    {
        # 322
        'origin_status': PaymentStatusCodes.PAYMENT_30DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_LATE,  # 332
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_60DPD,  # 323
                'action': []
            },
        )
    },
    {
        # 323
        'origin_status': PaymentStatusCodes.PAYMENT_60DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_LATE,  # 332
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_90DPD,  # 324
                'action': []
            },
        )
    },
    {
        # 324
        'origin_status': PaymentStatusCodes.PAYMENT_90DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_LATE,  # 332
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_120DPD,  # 325
                'action': []
            },
        )
    },
    {
        # 325
        'origin_status': PaymentStatusCodes.PAYMENT_120DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_LATE,  # 332
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_150DPD,  # 326
                'action': []
            },
        )
    },
    {
        # 326
        'origin_status': PaymentStatusCodes.PAYMENT_150DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_LATE,  # 332
                'action': []
            },
            {
                'end_status': PaymentStatusCodes.PAYMENT_180DPD,  # 327
                'action': []
            },
        )
    },
    {
        # 327
        'origin_status': PaymentStatusCodes.PAYMENT_180DPD,
        'allowed_paths': (
            {
                'end_status': PaymentStatusCodes.PAID_LATE,  # 332
                'action': []
            },
        )
    },
)

loan_path_origin_mapping = (
    {
        # 213
        'origin_status': LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        'allowed_paths': (
            {
                'end_status': LoanStatusCodes.CURRENT,  # 220
                'action': []
            },
            {
                'end_status': LoanStatusCodes.CANCELLED_BY_CUSTOMER,  # 216
                'action': []
            },
        )
    },
)
