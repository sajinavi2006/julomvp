from __future__ import absolute_import, division, print_function
from typing import (
    Tuple,
    Union,
)

import base64
import json
import logging
import math
import os
import re
import shutil
import tempfile
from builtins import map, object, range, str, zip
from calendar import monthrange
from datetime import date, datetime, timedelta, time
from math import ceil

import pdfkit
import phonenumbers
import requests
import semver
import vobject
from babel.dates import format_date
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.conf import settings

# from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, F, Q, Sum, Max
from django.db.utils import IntegrityError
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone
from geographiclib.geodesic import Geodesic
from geopy.exc import GeopyError
from past.utils import old_div
from PIL import Image as Imagealias
from PIL import ImageFile

import juloserver.loan_refinancing.services.notification_related as loan_refinancing_service
from juloserver.account.constants import AccountConstant, LDDEReasonConst
from juloserver.account.models import AccountLimit, AccountTransaction
from juloserver.account_payment.models import AccountPayment
from juloserver.apiv2.constants import CreditMatrixType
from juloserver.apiv2.services import (
    false_reject_min_exp,
    is_customer_paid_on_time,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.services import is_experiment_application
from juloserver.application_flow.models import HsfbpIncomeVerification
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.collection_vendor.task import process_unassignment_when_paid
from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.collectionbucket.services import get_agent_service_for_bucket
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import NameBankValidation
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.followthemoney.models import LenderBalanceCurrent, LenderCurrent
from juloserver.grab.exceptions import GrabLogicException
from juloserver.grab.models import GrabCustomerData
from juloserver.grab.tasks import (
    trigger_application_updation_grab_api,
    trigger_push_notification_grab,
)
from juloserver.grab.utils import GrabUtils
from juloserver.julo.clients import get_url_shorten_service
from juloserver.julo.constants import (
    AXIATA_LENDER_NAME,
    URL_CARA_BAYAR,
    BucketConst,
    FraudModelExperimentConst,
    ScoreTag,
    WorkflowConst,
    ApplicationStatusChange,
    OnboardingIdConst,
)
from juloserver.julo.exceptions import (
    ApplicationEmergencyLocked,
    InvalidPhoneNumberError,
    JuloException,
    JuloInvalidStatusChange,
    SmsNotSent,
)
from juloserver.julo.models import (
    DeviceGeolocation,
    EmailSetting,
    PTPLoan,
    Document,
    AuthUser as User,
)
from juloserver.julo.services2 import encrypt
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.utils import (
    eval_or_none,
    execute_after_transaction_safely,
    format_nexmo_voice_phone_number,
    format_valid_e164_indo_phone_number,
    generate_ics_link,
    get_float_or_none,
)

from juloserver.warning_letter.tasks2 import upload_warning_letter
from juloserver.julo.workflows2.schemas.cash_loan import CashLoanSchema
from juloserver.julo.workflows2.schemas.grab_food import GrabFoodSchema
from juloserver.julo.workflows2.schemas.partner_workflow import PartnerWorkflowSchema
from juloserver.loan.constants import DisbursementAutoRetryConstant
from juloserver.loan_refinancing.constants import (
    CovidRefinancingConst,
    LoanRefinancingStatus,
)
from juloserver.loan_refinancing.models import LoanRefinancingRequest, WaiverRequest
from juloserver.loan_refinancing.services.loan_related import (
    get_loan_refinancing_request_info,
)
from juloserver.loan_refinancing.services.refinancing_product_related import (
    check_eligibility_of_covid_loan_refinancing,
    get_activated_covid_loan_refinancing_request,
    process_partial_paid_loan_refinancing,
)
from juloserver.minisquad.constants import CenterixCallResult, DEFAULT_DB
from juloserver.minisquad.services import (
    get_bucket_status,
    insert_data_into_commission_table,
    upload_payment_details,
)
from juloserver.nexmo.models import RobocallCallingNumberChanger
from juloserver.partnership.constants import (
    ErrorMessageConst,
    PartnershipPreCheckFlag,
    PartnershipFeatureNameConst,
)
from juloserver.partnership.models import (
    PartnershipApplicationData,
    PartnershipApplicationFlag,
    PartnershipCustomerData,
    PartnershipFeatureSetting,
)
from juloserver.payback.models import WaiverConst, WaiverPaymentTemp, WaiverTemp
from juloserver.payback.services.payback import create_pbt_status_history
from juloserver.payback.services.waiver import (
    automate_late_fee_waiver,
    process_waiver_before_payment,
)
from juloserver.paylater.models import Statement
from juloserver.promo.models import PromoCode, PromoHistory, WaivePromo
from juloserver.sdk.services import get_laku6_sphp, get_partner_product_sphp
from juloserver.urlshortener.services import shorten_url
from juloserver.pii_vault.services import detokenize_for_model_object

from ..account.models import AccountPropertyHistory
from ..apiv2.credit_matrix2 import get_score_product
from ..apiv2.models import (
    PdCollectionModelResult,
    PdExpensePredictModelResult,
    PdIncomePredictModelResult,
    PdIncomeTrustModelResult,
    PdThinFileModelResult,
)
from ..apiv2.services import check_fraud_model_exp, get_credit_score3
from ..disbursement.utils import bank_name_similarity_check
from ..integapiv1.tasks import send_push_notif_async
from ..line_of_credit.constants import LocTransConst
from ..monitors.notifications import (
    notify_partner_account_attribution,
    notify_payment_over_paid,
)
from juloserver.partnership.utils import partnership_detokenize_sync_object_model
from ..sdk.constants import ProductMatrixPartner
from ..sdk.models import AxiataCustomerData
from . import workflows
from .application_checklist import application_checklist, application_checklist_update
from .banks import BankCodes, BankManager
from .checkers import (
    check_age_requirements,
    check_applicant_not_blacklist,
    check_company_not_blacklist,
    check_dob_match_fb_form,
    check_email_match_fb_form,
    check_fb_friends_gt_50,
    check_gender_match_fb_form,
    check_home_address_vs_gps,
    check_is_owned_phone,
    check_job_not_blacklist,
    check_jobterm_requirements,
    check_kin_not_declined,
    check_ktp_vs_area,
    check_ktp_vs_dob,
    check_salary_requirements,
    check_spouse_not_declined,
)
from .clients import (
    get_julo_bri_client,
    get_julo_email_client,
    get_julo_perdana_sms_client,
    get_julo_pn_client,
    get_julo_sentry_client,
    get_julo_sms_client,
    get_julo_tokopedia_client,
)
from .constants import (
    APPLICATION_STATUS_EXPIRE_PATH,
    DATA_CHECK_AGE_SEQ,
    DATA_CHECK_APPL_BL_SEQ,
    DATA_CHECK_COMPANT_BL_SEQ,
    DATA_CHECK_DOB_MATCH_FB_FORM,
    DATA_CHECK_EMAIL_MATCH_FB_FORM,
    DATA_CHECK_FB_FRIENDS_GT_50,
    DATA_CHECK_GENDER_MATCH_FB_FORM,
    DATA_CHECK_HOME_ADDRESS_VS_GPS,
    DATA_CHECK_JOB_NOT_BLACKLIST,
    DATA_CHECK_JOB_TERM_SEQ,
    DATA_CHECK_KIN_NOT_DECLINED_SEQ,
    DATA_CHECK_KTP_AREA_SEQ,
    DATA_CHECK_KTP_DOB_SEQ,
    DATA_CHECK_OWN_PHONE_SEQ,
    DATA_CHECK_SALARY_SEQ,
    DATA_CHECK_SPOUSE_NOT_DECLINED_SEQ,
    TARGET_PARTNER,
    CommsConst,
    CreditExperiments,
    EmailTemplateConst,
    ExperimentConst,
    FeatureNameConst,
    LoanGenerationChunkingConstant,
    LocalTimeType,
    ReferralConstant,
)
from .formulas import (
    compute_adjusted_payment_installment,
    compute_laku6_adjusted_payment_installment,
    compute_laku6_payment_installment,
    compute_payment_installment,
    compute_skiptrace_effectiveness,
    determine_first_due_dates_by_payday,
    get_available_due_dates_weekday_daily,
    get_new_due_dates_by_cycle_day,
    get_start_date_in_business_day,
    round_rupiah,
)
from .formulas.offers import get_offer_options
from .formulas.underwriting import compute_affordable_payment
from .models import (
    PTP,
    AdditionalExpense,
    AdditionalExpenseHistory,
    Application,
    ApplicationCheckList,
    ApplicationCheckListComment,
    ApplicationCheckListHistory,
    ApplicationExperiment,
    ApplicationFieldChange,
    ApplicationHistory,
    ApplicationNote,
    CommsBlocked,
    CootekRobocall,
    Customer,
    CustomerFieldChange,
    DataCheck,
    DisbursementTransaction,
    DokuTransaction,
    EmailHistory,
    Experiment,
    ExperimentAction,
    ExperimentSetting,
    FDCDeliveryTemp,
    FDCInquiryLoan,
    FeatureSetting,
    FraudHotspot,
    Image,
    InAppPTPHistory,
    LenderBalance,
    LenderBalanceEvent,
    LenderDisburseCounter,
    LenderProductCriteria,
    LenderServiceRate,
    Loan,
    LoanStatusChange,
    NotificationTemplate,
    Offer,
    OriginalPassword,
    Partner,
    PartnerAccountAttribution,
    PartnerAccountAttributionSetting,
    PartnerLoan,
    PartnerOriginationData,
    PartnerReferral,
    PaybackTransaction,
    Payment,
    PaymentEvent,
    PaymentMethod,
    PaymentNote,
    PaymentStatusChange,
    ProductLine,
    ProductLookup,
    ReferralCampaign,
    RepaymentTransaction,
    Skiptrace,
    SkiptraceHistory,
    SkiptraceResultChoice,
    SphpTemplate,
    StatusLookup,
    VirtualAccountSuffix,
    Workflow,
    WorkflowStatusPath,
    CashbackCounterHistory,
    CollectionPrimaryPTP,
)
from .partners import PartnerConstant, get_bfi_client, get_doku_client
from .payment_methods import PaymentMethodCodes, PaymentMethodManager
from .product_lines import ProductLineCodes, ProductLineManager
from .services2 import get_appsflyer_service
from .services2.payment_method import get_payment_methods
from .services2.primo import MAPPING_CALL_RESULT
from .statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
    StatusManager,
)
from .utils import (
    clean_special_character,
    construct_remote_filepath,
    construct_remote_filepath_base,
    display_rupiah,
    format_e164_indo_phone_number,
    get_geolocator,
    have_pn_device,
    remove_current_user,
    upload_file_to_oss,
    upload_file_as_bytes_to_oss,
    add_plus_62_mobile_phone,
)
from .workflows2.handlers import execute_action
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from juloserver.customer_module.services.customer_related import check_if_phone_exists
from juloserver.pii_vault.services import (
    tokenize_pii_data,
    prepare_pii_event,
)
from juloserver.pii_vault.constants import PiiSource

from juloserver.customer_module.tasks.notification import (
    send_customer_data_change_by_agent_notification_task,
)
from juloserver.customer_module.constants import (
    AgentDataChange,
)
from juloserver.integapiv1.constants import (
    FaspaySnapInquiryResponseCodeAndMessage,
)
from juloserver.line_of_credit.models import LineOfCredit
from juloserver.julo.services2.payment_method import get_application_primary_phone
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from django.core.files import File
from io import BytesIO
from PyPDF2 import PdfFileReader


logger = logging.getLogger(__name__)
ImageFile.LOAD_TRUNCATED_IMAGES = True

STL_CODES = (ProductLineCodes.STL1, ProductLineCodes.STL2)
stl_min_payment = 1000000
mtl_min_payment = 413000

sentry_client = get_julo_sentry_client()


def mark_is_robocall_active_or_inactive(payment):
    """
    sets all future payments to robocall active when
    there is a paid on time payment, and otherwise for
    paid late, grace period payments, and dpd
    """
    if payment.status not in [
        PaymentStatusCodes.PAYMENT_NOT_DUE,
        PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
        PaymentStatusCodes.PAYMENT_DUE_TODAY,
        PaymentStatusCodes.DOWN_PAYMENT_DUE,
        PaymentStatusCodes.DOWN_PAYMENT_RECEIVED,
        PaymentStatusCodes.DOWN_PAYMENT_ABANDONED,
    ]:
        if (
            payment.status == PaymentStatusCodes.PAID_ON_TIME
            and payment.loan.application.product_line_code in ProductLineCodes.mtl()
        ):
            if (
                payment.payment_number == 1
                or payment.loan.payment_set.filter(
                    payment_number__in=[payment.payment_number, (payment.payment_number - 1)],
                    payment_status=PaymentStatusCodes.PAID_ON_TIME,
                ).count()
                == 2
            ):
                payment_set = payment.loan.payment_set.filter(
                    payment_number__gt=payment.payment_number
                )
                for payments in payment_set:
                    payments.is_robocall_active = True
                    payments.save()
        else:  # for paid late and grace period, and any dpd status code
            payment_set = payment.loan.payment_set.all()
            for payments in payment_set:
                payments.is_robocall_active = False
                payments.save()


def ptp_create(
    payment_or_account_payment,
    ptp_date,
    ptp_amount,
    agent_obj,
    is_julo_one=False,
    is_grab=False,
    in_app_ptp_history_id=None,
):
    from juloserver.minisquad.tasks2.google_calendar_task import (
        set_google_calendar_payment_reminder_by_account_payment_id,
    )
    from juloserver.minisquad.tasks2.dialer_system_task import (
        delete_paid_payment_from_dialer,
        handle_manual_agent_assignment_ptp,
    )

    """
    create new ptp data
    Dana also using julo one flow for ptp process
    """

    new_ptp_dict = dict()
    account_payment_id = None
    ptp_object_for_relation = None

    if payment_or_account_payment:
        if not is_julo_one and not is_grab:
            payment = payment_or_account_payment
            ptp_object = PTP.objects.filter(payment=payment, ptp_status__isnull=True)
        else:
            account_payment = payment_or_account_payment
            ptp_object = PTP.objects.filter(
                account_payment=account_payment, ptp_status__isnull=True
            )

        if ptp_date is not None and agent_obj is not None:
            ptp_insert = False

            if ptp_object:
                # Get ptp entry with same ptp_date
                current_ptp_date_obj = ptp_object.filter(
                    ptp_date=ptp_date,
                    agent_assigned=agent_obj).last()

                if current_ptp_date_obj is None:
                    ptp_insert = True
                else:
                    ptp_object = ptp_object.exclude(id=current_ptp_date_obj.id)

                ptp_object.update(ptp_status='Not Paid')
            else:
                ptp_insert = True

            if ptp_insert is True:
                if not is_julo_one and not is_grab:
                    PTP.objects.create(
                        payment=payment,
                        loan=payment.loan,
                        agent_assigned=agent_obj,
                        ptp_date=ptp_date,
                        ptp_amount=ptp_amount,
                        in_app_ptp_history_id=in_app_ptp_history_id,
                    )
                else:
                    new_ptp_dict = dict(
                        account_payment=account_payment,
                        account=account_payment.account,
                        agent_assigned=agent_obj,
                        ptp_date=ptp_date,
                        ptp_amount=ptp_amount,
                        in_app_ptp_history_id=in_app_ptp_history_id,
                    )
                    ptp_object_for_relation = PTP.objects.create(**new_ptp_dict)

                    account_payment_id = account_payment.id
            else:
                ptp_change_field={
                    'ptp_amount': ptp_amount,
                }
                if in_app_ptp_history_id:
                    ptp_change_field['in_app_ptp_history_id']=in_app_ptp_history_id
                current_ptp_date_obj.update_safely(**ptp_change_field)

            if is_julo_one:
                current_primary_ptp_date_obj = (
                    CollectionPrimaryPTP.objects.filter(
                        ptp_date=ptp_date,
                        agent_assigned=agent_obj,
                        account_payment=account_payment,
                    )
                    .exclude(ptp_status='Paid')
                    .last()
                )

                if not current_primary_ptp_date_obj:
                    new_ptp_dict.update(ptp=ptp_object_for_relation)
                    CollectionPrimaryPTP.objects.create(**new_ptp_dict)
                else:
                    ptp_change_field = dict(
                        ptp_amount=ptp_amount,
                        in_app_ptp_history_id=in_app_ptp_history_id,
                    )
                    current_primary_ptp_date_obj.update_safely(**ptp_change_field)

        if is_julo_one:
            # for 5 minutes delay
            set_google_calendar_payment_reminder_by_account_payment_id.apply_async(
                kwargs={'account_payment_id': account_payment_id},
                countdown=5 * 60)
            delete_paid_payment_from_dialer.delay(account_payment.id)
            if ptp_insert and ptp_object_for_relation:
                execute_after_transaction_safely(
                    lambda: handle_manual_agent_assignment_ptp.delay(ptp_object_for_relation.id)
                )


def get_loans_from_payment_table(payment_or_account_payment, is_payment):
    if is_payment:
        loan = payment_or_account_payment.loan
        if loan is None:
            return []
        else:
            return [loan]

    payments = Payment.objects.filter(
        account_payment_id=payment_or_account_payment.id,
        payment_status__status_code__in=PaymentStatusCodes.not_paid_status_codes(),
    )
    if payments is None:
        return []

    loans = []
    loan_id_set = set()
    for payment in payments:
        if payment.loan and payment.loan.id not in loan_id_set:
            curr_loan = payment.loan
            loans.append(curr_loan)
            loan_id_set.add(curr_loan.id)

    return loans

def get_loans_from_ptp_loan_table(ptp_id):
    ptp_loans = PTPLoan.objects.filter(ptp_id=ptp_id)
    if ptp_loans is None:
        return []

    return [ptp_loan for ptp_loan in ptp_loans]

# NOTE: This function is use by Dana Collection Also
def ptp_create_v2(
    payment_or_account_payment,
    ptp_date,
    ptp_amount,
    agent_obj,
    is_julo_one=False,
    is_grab=False,
    in_app_ptp_history_id = None
):
    ptp_create(payment_or_account_payment, ptp_date, ptp_amount, agent_obj, is_julo_one, is_grab, in_app_ptp_history_id)

    is_payment = not is_julo_one and not is_grab
    if is_payment:
        ptp = PTP.objects.filter(payment=payment_or_account_payment).last()
    else:
        ptp = PTP.objects.filter(account_payment=payment_or_account_payment).last()

    loans = get_loans_from_payment_table(payment_or_account_payment, is_payment)

    ptp_loans = get_loans_from_ptp_loan_table(ptp.id)
    ptp_loans_id = [ptp_loan.id for ptp_loan in ptp_loans]

    not_intersect_loans = [e for e in loans if e.id not in ptp_loans_id]

    bulk_create_data = []
    for loan in not_intersect_loans:
        bulk_create_data.append(PTPLoan(ptp=ptp, loan=loan))

    PTPLoan.objects.bulk_create(bulk_create_data)

def ptp_update(payment_id, ptp_date):
    """
    update ptp table in reference to Payments table
    """
    if ptp_date is not None:
        paid_status_codes = [PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD, PaymentStatusCodes.PAID_LATE,
                             PaymentStatusCodes.PAID_ON_TIME]
        payment = Payment.objects.get(pk=payment_id)

        ptp_status = None
        agent_assigned = CollectionAgentTask.objects.filter(
            payment_id=payment.id,
            unassign_time__isnull=True).order_by('id').last()
        agent = None
        if agent_assigned is not None:
            agent = agent_assigned.actual_agent

        if payment.paid_date is not None and payment.paid_amount != 0:
            if payment.payment_status_id in paid_status_codes:
                if payment.paid_date > ptp_date:
                    ptp_status = "Paid after ptp date"
                elif payment.paid_date <= ptp_date and payment.due_amount != 0:
                    ptp_status = "Partial"
                else:
                    ptp_status = "Paid"
            elif payment.due_amount != 0:
                ptp_status = "Partial"
        else:
            ptp_status = "Not Paid"

        if ptp_status is not None:
            ptp_object = PTP.objects.filter(payment=payment, ptp_date=ptp_date, ptp_status__isnull=True).last()
            if not ptp_object:
                if agent is None:
                    ptp_object = PTP.objects.\
                        filter(payment=payment, ptp_date=ptp_date, agent_assigned_id__isnull=False).last()
                    if ptp_object:
                        agent = ptp_object.agent_assigned
                ptp_parent = PTP.objects.filter(
                    payment=payment,
                    ptp_date=ptp_date,
                    ptp_amount=payment.ptp_amount).first()
                PTP.objects.create(
                    payment=payment,
                    loan=payment.loan,
                    agent_assigned=agent,
                    ptp_date=ptp_date,
                    ptp_status=ptp_status,
                    ptp_amount=payment.ptp_amount,
                    ptp_parent=ptp_parent
                )
            else:
                if agent is None:
                    agent = ptp_object.agent_assigned
                ptp_object.update_safely(
                    agent_assigned=agent,
                    ptp_status=ptp_status,
                    ptp_amount=payment.ptp_amount
                )


def create_promo_history_and_payment_event(payment):
    # create promo history and payment event to the application who has the used promo

    if not payment.payment_number == 1:
        return

    loan = payment.loan
    application = loan.application
    if not application:
        return

    today = timezone.localtime(timezone.now())

    waive_promo = WaivePromo.objects.filter(loan=loan, payment=payment)

    if waive_promo:
        first_waive_promo = waive_promo.order_by('id').first()
        promo_event_type = first_waive_promo.promo_event_type
        PromoHistory.objects.create(
            customer=application.customer, loan=loan, promo_type=promo_event_type,
            payment=payment
        )

        if first_waive_promo.remaining_installment_interest:
            waive_promo_5dpd = WaivePromo.objects.filter(
                loan=loan, payment=payment,
                promo_event_type=promo_event_type + '_321')

            event_type = 'waive_interest'
            if waive_promo_5dpd:
                event_type = 'waive_late_fee'

            PaymentEvent.objects.create(
                payment=payment,
                event_payment=payment.installment_interest,
                event_due_amount=payment.installment_principal + payment.installment_interest,
                event_date=timezone.localtime(timezone.now()).date(),
                event_type=event_type)


def create_tokopedia_jan_promo_entry(payment):
    loan = payment.loan
    application = loan.application
    if not application:
        return

    partner = application.partner
    if not partner or not partner.name == PartnerConstant.TOKOPEDIA_PARTNER or \
         not payment.payment_number == 1:
            return

    today = timezone.localtime(timezone.now())

    waive_promo = WaivePromo.objects.filter(loan=loan,payment=payment)

    if waive_promo:
        PromoHistory.objects.create(
            customer=application.customer,loan=loan,promo_type="promo-tokopedia-jan-zero-interest",
            payment=payment
        )

        waive_promo_5dpd = WaivePromo.objects.filter(
            loan=loan,payment=payment,
            promo_event_type='jan_promo_tokopedia_321')

        event_type = 'waive_interest'
        if waive_promo_5dpd:
            event_type = 'waive_late_fee'

        PaymentEvent.objects.create(
            payment=payment,
            event_payment=payment.installment_interest,
            event_due_amount=payment.installment_principal + payment.installment_interest,
            event_date=timezone.localtime(timezone.now()).date(),
            event_type=event_type)


def should_refinance_cashback_be_removed(loan, payment):
    last_covid_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan=loan).last()

    if not last_covid_loan_refinancing_request:
        return False

    if last_covid_loan_refinancing_request.status == \
            CovidRefinancingConst.STATUSES.activated:
        return True
    if last_covid_loan_refinancing_request.status in \
            [CovidRefinancingConst.STATUSES.offer_selected,
             CovidRefinancingConst.STATUSES.approved]:
        eligible_refinancing = check_eligibility_of_covid_loan_refinancing(
            last_covid_loan_refinancing_request, payment.paid_date)
        if eligible_refinancing:
            last_covid_loan_refinancing_request.update_safely(
                status=CovidRefinancingConst.STATUSES.activated,
                offer_activated_ts=timezone.localtime(timezone.now()))
            return True

    waiver_temp = WaiverTemp.objects.filter(status=WaiverConst.IMPLEMENTED_STATUS).last()
    loan_ref_req = LoanRefinancingRequest.objects.filter(
        loan=loan, status=CovidRefinancingConst.STATUSES.activated).last()
    if not waiver_temp or not loan_ref_req:
        return False
    waiver_payment_temp = WaiverPaymentTemp.objects.filter(waiver_temp=waiver_temp).first()
    waiver_request = WaiverRequest.objects.filter(
        loan=loan, program_name=loan_ref_req.product_type).last()
    if not waiver_request or not waiver_payment_temp:
        return False

    start_payment_number = waiver_payment_temp.payment.payment_number
    last_payment_number = waiver_request.last_payment_number

    if start_payment_number <= payment.payment_number <= last_payment_number:
        return True

    return False


def process_received_payment(payment):
    processed = False
    if payment.due_date is None or payment.paid_date is None:
        logger.warn({
            'due_date': payment.due_date,
            'paid_date': payment.paid_date,
            'payment': payment,
            'processed': processed
        })
        return processed
    payment.refresh_from_db()
    loan = payment.loan
    paid_late_days = payment.paid_late_days
    ptp_date = payment.ptp_date
    loan_refinancing_request = get_loan_refinancing_request_info(loan)

    is_cashback_earned = False
    is_ptp_update = False
    payment_history = {}
    payment_update_fields = ['ptp_date', 'payment_status', 'udate']

    with transaction.atomic():
        if loan_refinancing_request:
            change_status = StatusLookup.PAID_ON_TIME_CODE
            loan_refinancing_request.change_status(LoanRefinancingStatus.ACTIVE)
            loan_refinancing_request.save()
        else:
            if paid_late_days <= 0:
                # When payment was paid on time
                # add if statement for no cashback for stl loan here
                change_status = StatusLookup.PAID_ON_TIME_CODE
                is_ptp_update = True
                if loan.product.has_cashback_pmt:
                    is_cashback_earned = True

            elif paid_late_days < get_grace_period_days(payment):
                # When payment was paid within grace period
                change_status = StatusLookup.PAID_WITHIN_GRACE_PERIOD_CODE
                is_ptp_update = True

            else:
                # When payment was paid late
                change_status = StatusLookup.PAID_LATE_CODE
                is_ptp_update = True

            if should_refinance_cashback_be_removed(loan, payment):
                is_cashback_earned = False

        if is_cashback_earned:
            payment.update_cashback_earned()
            loan.update_cashback_earned_total(payment.cashback_earned)
            payment_update_fields.append('cashback_earned')

        payment_history['payment_old_status_code'] = payment.status
        payment.change_status(change_status)
        payment.ptp_date = None
        payment.save(update_fields=payment_update_fields)
        if is_ptp_update:
            ptp_update(payment.id, ptp_date)
            loan.refresh_from_db()
        payment_history['loan_old_status_code'] = loan.status
        loan.update_status()
        loan.save()


    #adding payment history data when payment is succesfully received
    payment.create_payment_history(payment_history)

    if payment.loan.application and payment.loan.application.device:
        if payment.loan.application.device.gcm_reg_id:
            send_push_notif_async.delay(
                'inform_payment_received',
                [payment.loan.application.device.gcm_reg_id,
                 payment.payment_number, payment.loan.application.id,
                 payment.loan.application.product_line.product_line_code,
                 payment.payment_status_id])

    # if product_line_code in ProductLineCodes.grab():
    #     if payment.payment_status.status_code == PaymentStatusCodes.PAID_ON_TIME:
    #         send_email_reminder_grab_by_status(payment)
    #     if loan.loan_status.status_code == LoanStatusCodes.PAID_OFF:
    #         send_email_paid_off_grab()

    logger.info({
        'days_paid_late': paid_late_days,
        'cashback_earned': payment.cashback_earned,
        'payment': payment,
        'processed': processed,
        'status': 'received_payment_processed'
    })

    create_tokopedia_jan_promo_entry(payment)
    create_promo_history_and_payment_event(payment)

    processed = True
    if loan.application and not loan.application.partner:
        appsflyer_service = get_appsflyer_service()
        appsflyer_service.info_loan_status(loan.id)
    return processed


def change_cycle_day(loan):
    if loan.cycle_day_requested is None:
        logger.warn({
            'loan': loan,
            'cycle_day_requested': loan.cycle_day_requested,
            'status': 'cycle_day_not_changed'
        })
        raise JuloException("The requested cycle day must not be blank")

    affected_payments = list(
        Payment.objects
            .by_loan(loan)
            .not_paid()
            .not_overdue()
            .order_by('payment_number')
    )
    affected_payment_count = len(affected_payments)
    if affected_payment_count == 0:
        logger.warn({
            'loan': loan,
            'unpaid_payment_count': affected_payment_count,
            'status': 'no_more_due_payments'
        })
        raise JuloException("The loan has no more payments due")

    with transaction.atomic():

        loan.update_cycle_day()
        loan.save()

        remaining_due_dates = [
            payment.due_date for payment in affected_payments
            ]
        new_due_dates = get_new_due_dates_by_cycle_day(
            loan.cycle_day, remaining_due_dates)

        for payment, new_due_date in zip(affected_payments, new_due_dates):
            payment.due_date = new_due_date
            updated = payment.update_status_based_on_due_date()
            if not updated:
                logger.info({
                    'status': 'payment_status_not_updated',
                    'loan': loan,
                    'payment_number': payment.payment_number,
                })
            payment.save(update_fields=['due_date',
                                        'udate'])
            logger.info({
                'loan': loan,
                'payment_number': payment.payment_number,
                'new_due_date': new_due_date
            })

    logger.info({
        'loan': loan,
        'affected_payment_count': affected_payment_count,
        'new_cycle_day': loan.cycle_day,
        'status': 'cycle_day_changed'
    })


def change_due_dates(loan, new_next_due_date, partner=None):
    """Adjusting due dates before loan starts"""
    payments = list(
        Payment.objects.by_loan(loan).not_paid().order_by('payment_number')
    )

    new_cycle_day = new_next_due_date.day
    if new_cycle_day > loan.MAX_CYCLE_DAY and partner != PartnerConstant.AXIATA_PARTNER:
        raise JuloException({
            'loan': loan.id,
            'new_next_due_date': new_next_due_date,
            'error': 'invalid_cycle_day'
        })

    with transaction.atomic():

        new_due_date = new_next_due_date
        for payment in payments:
            logger.info({
                'action': 'changing_due_date',
                'loan': loan.id,
                'payment': payment.id,
                'payment_number': payment.payment_number,
                'old_due_date': payment.due_date,
                'new_due_date': new_due_date
            })
            payment.due_date = new_due_date
            payment.save(update_fields=['due_date',
                                        'udate'])
            new_due_date = new_due_date + relativedelta(months=1)

        logger.info({
            'status': 'due_dates_changed',
            'action': 'updating_cycle_day',
            'new_cycle_day': new_cycle_day,
            'loan': loan.id,
        })
        loan.cycle_day = new_cycle_day
        loan.save()


def create_loan_and_payments(offer):
    """
    Internal function to create loan and payments. Should not be called
    as an action
    """

    with transaction.atomic():

        productline_code = offer.application.product_line.product_line_code
        today_date = timezone.localtime(timezone.now()).date()
        first_payment_date = offer.first_payment_date
        if productline_code in ProductLineCodes.grab():
            start_date = get_start_date_in_business_day(today_date, 3)
            range_due_date = get_available_due_dates_weekday_daily(
                start_date, offer.loan_duration_offer)
            today_date = range_due_date[0]
            first_payment_date = range_due_date[-1]

        principal_first, interest_first, installment_first = compute_adjusted_payment_installment(
            offer.loan_amount_offer, offer.loan_duration_offer,
            offer.interest_rate_monthly, today_date, first_payment_date)

        installment_first = check_eligible_for_campaign_referral(
                    productline_code, principal_first, installment_first, offer.loan_amount_offer, offer.application)

        if productline_code in ProductLineCodes.stl() + ProductLineCodes.pedestl():
            principal_rest, interest_rest = principal_first, interest_first
            installment_rest = installment_first
        if productline_code in ProductLineCodes.mtl() + ProductLineCodes.pedemtl():
            principal_rest, interest_rest, installment_rest = compute_payment_installment(
                offer.loan_amount_offer, offer.loan_duration_offer, offer.interest_rate_monthly)
        if productline_code in ProductLineCodes.bri():
            principal_rest, interest_rest, installment_rest = compute_payment_installment(
                offer.loan_amount_offer, offer.loan_duration_offer, offer.interest_rate_monthly)
        if productline_code in ProductLineCodes.grab():
            principal_rest, interest_rest = principal_first, interest_first
            installment_rest = installment_first
        if productline_code in ProductLineCodes.icare():
            principal_rest, interest_rest, installment_rest = compute_payment_installment(
                offer.loan_amount_offer, offer.loan_duration_offer, offer.interest_rate_monthly)
            principal_first, interest_first, installment_first = principal_rest, interest_rest, installment_rest
        if productline_code in ProductLineCodes.axiata():
            principal_rest, interest_rest = principal_first, interest_first
            installment_rest = installment_first

        loan = Loan.objects.create(
            customer=offer.application.customer,
            application=offer.application,
            offer=offer,
            loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
            product=offer.product,
            loan_amount=offer.loan_amount_offer,
            loan_duration=offer.loan_duration_offer,
            first_installment_amount=installment_first,
            installment_amount=installment_rest)

        axiata_customer_data = AxiataCustomerData.objects.get_or_none(application=offer.application)
        if axiata_customer_data:
            partner = PartnerOriginationData.objects.get_or_none(pk=int(axiata_customer_data.distributor))
            if not partner:
                partner = PartnerOriginationData.objects.get_or_none(pk=-1)
            timedelta_days = relativedelta(
                axiata_customer_data.first_payment_date, axiata_customer_data.acceptance_date.date()).days
            origination_fee = partner.origination_fee
            if timedelta_days > 7:
                origination_fee = float(origination_fee * 2)

            original_fee = float(origination_fee * loan.loan_amount)
            loan.loan_disbursement_amount = loan.loan_amount - original_fee
            try:
                lender_axiata = LenderCurrent.objects.get(lender_name=AXIATA_LENDER_NAME)
                loan.lender_id = lender_axiata.id
            except Exception as e:
                sentry_client.captureException()
                logger.error({
                    'action': 'get_axiata_lender_id',
                    'data': loan.id,
                    'errors': str(e)
                })

        loan.cycle_day = offer.first_payment_date.day
        loan.set_disbursement_amount()
        loan.save()
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for payment_number in range(loan.loan_duration):
            if payment_number == 0:
                if offer.special_first_payment_date:
                    first_payment_date = offer.special_first_payment_date
                else:
                    first_payment_date = offer.first_payment_date
                principal, interest, installment = principal_first, interest_first, installment_first
                due_date = first_payment_date
            else:
                principal, interest, installment = principal_rest, interest_rest, installment_rest
                if productline_code in ProductLineCodes.grab():
                    due_date = range_due_date[payment_number]
                else:
                    due_date = offer.first_payment_date + relativedelta(months=payment_number)

            if payment_number == (loan.loan_duration - 1) and productline_code not in ProductLineCodes.icare():
                total_installment_principal = principal * loan.loan_duration
                if total_installment_principal < loan.loan_amount:
                    less_amount = loan.loan_amount - total_installment_principal
                    principal += less_amount
                    interest -= less_amount

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

    return True


def update_loan_and_payments(loan):
    first_payment = loan.payment_set.get(payment_number=1)
    today_date = timezone.localtime(timezone.now()).date()
    principal_first, interest_first, installment_first = compute_adjusted_payment_installment(
        loan.loan_amount, loan.loan_duration, loan.interest_rate_monthly,
        today_date, first_payment.due_date)

    productline_code = loan.application.product_line.product_line_code

    installment_first = check_eligible_for_campaign_referral(
                    productline_code, principal_first, installment_first,loan.offer.loan_amount_offer,loan.application)

    first_payment.installment_principal = principal_first
    first_payment.installment_interest = interest_first
    first_payment.due_amount = installment_first
    first_payment.save(update_fields=['due_amount',
                                      'installment_principal',
                                      'installment_interest',
                                      'udate'])

    if productline_code in ProductLineCodes.stl() + ProductLineCodes.pedestl():
        loan.first_installment_amount = installment_first
        loan.installment_amount = loan.first_installment_amount
    if productline_code in ProductLineCodes.mtl() + ProductLineCodes.pedemtl():
        loan.first_installment_amount = installment_first
        _, _, installment_rest = compute_payment_installment(
            loan.loan_amount, loan.loan_duration, loan.interest_rate_monthly)
        loan.installment_amount = installment_rest
    loan.save()


def simulate_adjusted_payment_installment(loan, new_due_date):
    paid_instalments = loan.payment_set.all().paid()
    if paid_instalments:
        latest_paid = paid_instalments.order_by('-due_date').first()
        payment_start = latest_paid.due_date
    else:
        offer_accepted_date = timezone.localtime(loan.offer.offer_accepted_ts).date()
        if offer_accepted_date:
            payment_start = offer_accepted_date
        else:
            payment_start = date.today()

    _, _, new_installment = compute_adjusted_payment_installment(
        loan.loan_amount, loan.loan_duration,
        loan.interest_rate_monthly, payment_start, new_due_date)

    logger.info({
        'status': 'simulate_first_payment_installment',
        'new_installment_amount': new_installment,
        'loan': loan.id
    })
    return new_installment


def update_payment_installment(loan, new_due_date, simulate=False):
    paid_installments = loan.payment_set.all().paid()
    if paid_installments:
        latest_paid = paid_installments.order_by('-due_date').first()
        payment_start = latest_paid.due_date
    elif loan.sphp_sent_ts:
        payment_start = loan.sphp_sent_ts.date()
    else:
        payment_start = timezone.localtime(timezone.now()).date()

    first_payment = (
        Payment.objects.by_loan(loan).not_paid().order_by('payment_number').first()
    )
    if first_payment is None:
        raise JuloException({
            'status': 'no_payment_found',
            'loan': loan.id
        })

    new_principal, new_interest, new_installment = compute_adjusted_payment_installment(
        loan.loan_amount, loan.loan_duration,
        loan.interest_rate_monthly, payment_start, new_due_date)
    new_due_amount = (
        new_installment - first_payment.paid_amount + first_payment.late_fee_amount
    )

    if simulate:
        return new_due_amount

    with transaction.atomic():
        orig_due_amount = first_payment.due_amount

        first_payment.due_amount = new_due_amount
        first_payment.installment_principal = new_principal
        first_payment.installment_interest = new_interest
        first_payment.save(update_fields=['due_amount',
                                    'installment_principal',
                                    'installment_interest',
                                    'udate'])

        if paid_installments:
            pass
        elif loan.application.product_line.product_line_code in ProductLineCodes.stl():
            loan.installment_amount = new_due_amount
            loan.first_installment_amount = new_due_amount
            loan.save()
        elif loan.application.product_line.product_line_code in ProductLineCodes.mtl():
            loan.first_installment_amount = new_due_amount
            loan.save()

        change_amount = orig_due_amount - first_payment.due_amount

        PaymentEvent.objects.create(
            payment=first_payment,
            event_payment=change_amount,
            event_due_amount=orig_due_amount,
            event_date=timezone.localtime(timezone.now()).date(),
            event_type='due_date_adjustment')

    logger.info({
        'status': 'update_payment_installment',
        'new_principal': new_principal,
        'new_interest': new_interest,
        'new_due_amount': new_due_amount,
        'loan': loan.id,
        'payment_number': first_payment.payment_number,
        'payment': first_payment.id
    })
    return new_due_amount


def run_auto_data_checks(application):
    check_age_requirements(application, DATA_CHECK_AGE_SEQ)
    check_is_owned_phone(application, DATA_CHECK_OWN_PHONE_SEQ)
    check_salary_requirements(application, DATA_CHECK_SALARY_SEQ)
    check_jobterm_requirements(application, DATA_CHECK_JOB_TERM_SEQ)
    check_ktp_vs_area(application, DATA_CHECK_KTP_AREA_SEQ)
    check_ktp_vs_dob(application, DATA_CHECK_KTP_DOB_SEQ)
    check_company_not_blacklist(application, DATA_CHECK_COMPANT_BL_SEQ)
    check_applicant_not_blacklist(application, DATA_CHECK_APPL_BL_SEQ)
    check_spouse_not_declined(application, DATA_CHECK_SPOUSE_NOT_DECLINED_SEQ)
    check_kin_not_declined(application, DATA_CHECK_KIN_NOT_DECLINED_SEQ)
    check_job_not_blacklist(application, DATA_CHECK_JOB_NOT_BLACKLIST)


def run_auto_data_checks_facebook(application):
    check_fb_friends_gt_50(application, DATA_CHECK_FB_FRIENDS_GT_50)
    check_dob_match_fb_form(application, DATA_CHECK_DOB_MATCH_FB_FORM)
    check_gender_match_fb_form(application, DATA_CHECK_GENDER_MATCH_FB_FORM)
    check_email_match_fb_form(application, DATA_CHECK_EMAIL_MATCH_FB_FORM)


def run_auto_data_checks_gps(application):
    check_home_address_vs_gps(application, DATA_CHECK_HOME_ADDRESS_VS_GPS)


def create_data_checks(application):
    data_checks_args = [
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'DOCUMENT - Verified',
        },
        {
            'responsibility': (
                ' / '.join([DataCheck.DATA_VERIFIER, DataCheck.FINANCE])
            ),
            'data_to_check': 'BANK_ACCOUNT - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'FACEBOOK_DATA - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'ADDRESS_GEOLOCATION - Verified',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KTP_SELF - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KTP_SELF - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KTP_SELF_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KTP_SELF_dob',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KTP_SELF_address',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KTP_SELF_ktp_num',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KK - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KK - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KK_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KK_dob',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'KK_spouse',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'ELECTRIC_BILL - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'ELECTRIC_BILL - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'ELECTRIC_BILL_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'ELECTRIC_BILL_address',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'RENTAL_DOCUMENT - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'RENTAL_DOCUMENT - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'RENTAL_DOCUMENT_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'RENTAL_DOCUMENT_address',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'GOVERNMENT_DOCUMENT - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'GOVERNMENT_DOCUMENT - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'GOVERNMENT_DOCUMENT_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'GOVERNMENT_DOCUMENT_address',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'TAX_DOCUMENT - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'TAX_DOCUMENT - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'TAX_DOCUMENT_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'TAX_DOCUMENT_address',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'PAY_STUB - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'PAY_STUB - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'PAY_STUB_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'PAY_STUB_income',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BUSINESS_INCOME_STATEMENT - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BUSINESS_INCOME_STATEMENT - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BUSINESS_INCOME_STATEMENT_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BUSINESS_INCOME_STATEMENT_income',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BANK_STATEMENT - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BANK_STATEMENT - Verified',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BANK_STATEMENT_name',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'BANK_STATEMENT_income',
        },
        #######################################################################
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'SELFIE - Readable',
        },
        {
            'responsibility': DataCheck.DATA_VERIFIER,
            'data_to_check': 'SELFIE - Verified',
        },
        #######################################################################
        {
            'responsibility': DataCheck.OUTBOUND_CALLER,
            'data_to_check': 'SPOUSE - Verified',
        },
        {
            'responsibility': DataCheck.OUTBOUND_CALLER,
            'data_to_check': 'KIN - Verified',
        },
        {
            'responsibility': DataCheck.OUTBOUND_CALLER,
            'data_to_check': 'COMPANY - Verified',
        },
        {
            'responsibility': DataCheck.OUTBOUND_CALLER,
            'data_to_check': 'LANDLORD - Verified',
        },
        {
            'responsibility': DataCheck.OUTBOUND_CALLER,
            'data_to_check': 'FINAL_CALL - Successful',
        },
        #######################################################################
        {
            'responsibility': DataCheck.FINANCE,
            'data_to_check': 'SPHP_SIGNATURE - Verified',
        }
    ]

    with transaction.atomic():
        for data_checks_arg in data_checks_args:
            data_checks_arg['application'] = application
            logger.debug(data_checks_arg)

            data_check = DataCheck.objects.create(**data_checks_arg)
            logger.info({
                'data_check': data_check.data_to_check,
                'application': application,
                'status': 'created'
            })


def get_application_allowed_path(status_code, application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if application:
        workflow = application.workflow
        if not workflow:
            workflow = Workflow.objects.get(name='LegacyWorkflow')  # use the default one

        allowed_statuses = workflow.workflowstatuspath_set.filter(status_previous=int(status_code), is_active=True)
        allowed_status_list = list([x.status_next for x in allowed_statuses])
        if allowed_statuses:
            logger.info({
                'status': 'path_found',
                'path_statuses': allowed_status_list
            })
            return allowed_status_list
        else:
            logger.warn({
                'status': 'path_not_found',
                'status_code': status_code
            })
            return None
    else:
        logger.warn({
            'status': 'application_not_found',
            'status_code': status_code
        })
        return None


def get_allowed_application_statuses_for_ops(status_code, application):
    list_result = []

    if not isinstance(application, Application):
        application = Application.objects.get_or_none(pk=application)

    if application:
        workflow = application.workflow
        if not workflow:
            workflow = Workflow.objects.get(name='LegacyWorkflow')  # use the default one
        allowed_statuses = workflow.workflowstatuspath_set.filter(status_previous=int(status_code),
                                                                  agent_accessible=True, is_active=True)
        if allowed_statuses:

            if is_experiment_application(application.id, 'ExperimentUwOverhaul'):
                status = ApplicationStatusCodes.DOCUMENTS_VERIFIED
                target_status = WorkflowStatusPath.objects.get_or_none(status_previous=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                                                       status_next=status, workflow=workflow)
                if target_status in allowed_statuses:
                    allowed_statuses = list(allowed_statuses)
                    allowed_statuses.pop(allowed_statuses.index(target_status))

            for status in allowed_statuses:
                logger.info({
                    'status': 'path_found',
                    'path_status': status
                })
                next_status = StatusManager.get_or_none(status.status_next)
                if next_status:
                    list_result.append(next_status)
        else:
            logger.warn({
                'status': 'path_not_found',
                'status_code': status_code
            })
    else:
        logger.warn({
            'status': 'application_not_found',
        })

    return list_result


def get_payment_path_origin(status_code):
    for path_origin in workflows.payment_path_origin_mapping:
        if path_origin['origin_status'] == status_code:
            logger.info({
                'func': 'get_payment_path_origin',
                'status': 'path_origin_found',
                'path_origin_status': path_origin['origin_status']
            })
            return path_origin

    logger.warn({
        'func': 'get_payment_path_origin',
        'status': 'path_origin_not_found',
        'status_code': status_code
    })
    return None


def get_loan_path_origin(status_code):
    for path_origin in workflows.loan_path_origin_mapping:
        if path_origin['origin_status'] == status_code:
            logger.info({
                'func': 'get_payment_path_origin',
                'status': 'path_origin_found',
                'path_origin_status': path_origin['origin_status']
            })
            return path_origin

    logger.warn({
        'func': 'get_payment_path_origin',
        'status': 'path_origin_not_found',
        'status_code': status_code
    })
    return None


def get_allowed_payment_statuses(status_code):
    allowed_statuses = []

    path_origin = get_payment_path_origin(status_code)

    if path_origin is None:
        return allowed_statuses

    for path in path_origin['allowed_paths']:
        allowed_status_code = path['end_status']
        allowed_statuses.append(StatusManager.get_or_none(allowed_status_code))
        logger.info({
            'status': 'allowed_path_found',
            'allowed_path': path
        })

    return allowed_statuses


def is_in_latest_application(application, customer=None):
    """
    Check  if the application is the latest application.
    """

    cust = application.customer if customer is None else customer
    max_created_date = Application.objects.filter(customer=cust).aggregate(Max('cdate'))
    return application.cdate == max_created_date['cdate__max']


def is_in_latest_jstarter_application(application, customer=None):
    """
    Check if the application is the latest Julo Starter application.
    """
    workflow = Workflow.objects.get_or_none(name=WorkflowConst.JULO_STARTER)
    cust = application.customer if customer is None else customer
    max_created_date = Application.objects.filter(customer=cust, workflow=workflow).aggregate(Max('cdate'))
    return application.cdate == max_created_date['cdate__max']


def is_allow_to_change_status(application, customer=None, new_status_code=None):
    """
    Check is application allow changing status from the total application
    """
    # allow all case to be status changed for x185 and x186
    if new_status_code in [ApplicationStatusCodes.CUSTOMER_ON_DELETION, ApplicationStatusCodes.CUSTOMER_DELETED]:
        return True

    # allow all case to be status changed for x183 and x184
    if new_status_code in [
        ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL,
        ApplicationStatusCodes.CUSTOMER_CONSENT_WITHDRAWED,
    ]:
        return True

    # check is allow to change status for julo starter
    allow_change_for_julo_starter_upgrade = all((
        application.is_julo_starter(),
        application.application_status_id == ApplicationStatusCodes.LOC_APPROVED,
        new_status_code == ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
    ))

    cust = application.customer if customer is None else customer
    total_application = Application.objects.filter(customer=cust).count()
    if total_application == 1 or (
        total_application > 1 and
        (is_in_latest_application(application, customer) or
         is_in_latest_jstarter_application(application, customer))
    ) or allow_change_for_julo_starter_upgrade or application.is_axiata_flow():
        return True

    if total_application >= 2 and application.status == ApplicationStatusCodes.FORM_CREATED\
            and (application.is_julo_starter() or application.is_julo_one()):
        return True

    return False


def correct_application_new_status_code(
        application: Application, old_status_code: int, new_status_code: int, change_reason: str
):
    """
    Change the new_status_code to the correct one if the current application matches with condition.
    The condition can be anything depending on the use case
    """
    # check the julo one application is missing emergency contact
    if application.is_julo_one_product() and new_status_code == ApplicationStatusCodes.LOC_APPROVED:
        from juloserver.application_form.services.application_service import (
            check_is_emergency_contact_filled
        )
        from juloserver.application_form.constants import EMERGENCY_CONTACT_APPLICATION_STATUSES

        if (
            application.onboarding_id == OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
            and old_status_code in EMERGENCY_CONTACT_APPLICATION_STATUSES
            and not check_is_emergency_contact_filled(application)
        ):
            new_status_code = ApplicationStatusCodes.MISSING_EMERGENCY_CONTACT
            change_reason = "missing emergency contact"

        return new_status_code, change_reason

    return new_status_code, change_reason


def process_application_status_change(application_id: Union[int, Application], new_status_code, change_reason, note=None):
    """The best way to change application status"""
    _application_id = application_id
    if not isinstance(application_id, Application):
        application = Application.objects.get_or_none(id=application_id)
    else:
        application = application_id

    if application is None:
        logger.warn({
            'status': 'application_not_found',
            'application': _application_id
        })
        return False


    if not is_allow_to_change_status(application, application.customer, new_status_code):
        return False

    if application.status_path_locked:
        if new_status_code != application.status_path_locked:
            raise ApplicationEmergencyLocked("Aplikasi terkunci sementara karena alasan tertentu."
                                             "silahkan hubungi Administrator")

    old_status_code = application.status
    new_status_code, change_reason = correct_application_new_status_code(
        application, old_status_code, new_status_code, change_reason
    )

    experiment = experimentation(application, new_status_code)
    if experiment['is_experiment']:
        ApplicationExperiment.objects.create(
            application=application, experiment_id=experiment['experiment_id'])

    status_changed = normal_application_status_change(
        application, new_status_code, change_reason, experiment['is_experiment'], note)
    if experiment['is_experiment'] and status_changed:
        experiment_application_status_change(application, experiment, old_status_code)

    if application.is_grab():
        trigger_application_updation_grab_api.delay(application.id)
        trigger_push_notification_grab.apply_async(
            kwargs={'application_id': application.id})

    if application.is_julo_one() and new_status_code == ApplicationStatusCodes.FORM_CREATED:
        from juloserver.moengage.services.use_cases import (
            send_user_attributes_to_moengage_for_customer_reminder_vkyc,
        )
        # for 5 minutes delay
        send_user_attributes_to_moengage_for_customer_reminder_vkyc.apply_async(
            (application.id,), countdown=5 * 60
        )
        # for 10 minutes delay
        send_user_attributes_to_moengage_for_customer_reminder_vkyc.apply_async(
            (application.id,), countdown=10 * 60
        )

    return True


def experiment_application_status_change(application, experiment, old_status_code=None):
    from juloserver.moengage.services.data_constructors import (
        APPLICATION_EVENT_STATUS_CONSTRUCTORS,
    )
    from juloserver.moengage.services.use_cases import (
        send_user_attributes_to_moengage_for_realtime_basis,
        update_moengage_for_application_status_change_event,
    )

    if not old_status_code:
        raise JuloInvalidStatusChange('old_status_code must not be None')

    new_status_code = int(experiment['change_status'])
    note = None
    change_reason = experiment['code']

    if change_reason == ExperimentConst.BYPASS_CA_CALCULATION:
        app_iti_low = application.applicationhistory_set.filter(
            change_reason=ExperimentConst.ITI_LOW_THRESHOLD)
        if app_iti_low:
            return False

        generate_offer = experimentation_automate_offer(application)
        if not generate_offer:
            new_status_code = ApplicationStatusCodes.APPLICATION_DENIED
    # don't record agent_id on bypass
    remove_current_user()
    with ApplicationHistoryUpdated(application, change_reason=experiment['code']) as updated:

        workflow = application.workflow
        if not workflow:
            workflow = Workflow.objects.get(name='LegacyWorkflow')  # use the default one

        status_path = WorkflowStatusPath.objects.get_or_none(
            workflow=workflow, status_previous=application.status, status_next=new_status_code, is_active=True)

        if not status_path:
            logger.error({'reason': 'Workflow not specified for status change',
                          'application_id': application.id,
                          'old_status_code': old_status_code,
                          'new_status_code': new_status_code})
            raise JuloInvalidStatusChange(
                "No path from status {} to {}".format(old_status_code, new_status_code))

        processed = execute_action(application, old_status_code, new_status_code, change_reason, note, workflow, 'pre')
        if not processed:
            logger.warn({
                'status': 'workflow_action_ran',
                'workflow_action': 'pre actions',
                'new_status_code': new_status_code,
                'path_end': new_status_code
            })
            return False
        application.change_status(new_status_code)
        application.save(update_fields=['application_status'])

    execute_action(application, old_status_code, new_status_code, change_reason, note, workflow, 'post')
    execute_action(application, old_status_code, new_status_code, change_reason, note, workflow, 'async_task')
    status_change = updated.status_change

    trigger_info_application_partner(status_change)

    if experiment['notes']:
        for note in experiment['notes']:
            application_note = ApplicationNote.objects.create(
                note_text=note,
                application_id=application.id,
                application_history_id=status_change.id,
            )
            logger.info(
                {
                    'status': 'status_change_noted',
                    'application_note': application_note,
                    'status_change': status_change,
                }
            )
    if old_status_code != new_status_code:
        if (
            not application.is_julo_one()
            and not application.is_grab()
            and not application.is_julo_starter()
        ):
            send_user_attributes_to_moengage_for_realtime_basis.apply_async(
                (application.customer.id,),
                countdown=settings.DELAY_FOR_REALTIME_EVENTS)
        else:
            app_status_changes = list(APPLICATION_EVENT_STATUS_CONSTRUCTORS.keys())
            if new_status_code in app_status_changes:
                update_moengage_for_application_status_change_event.apply_async((
                    new_status_code,
                    None,
                    application.id), countdown=settings.DELAY_FOR_REALTIME_EVENTS)
            send_user_attributes_to_moengage_for_realtime_basis.apply_async(
                (application.customer.id,),
                countdown=settings.DELAY_FOR_REALTIME_EVENTS)

    return True


def normal_application_status_change(application, new_status_code,
                                     change_reason, is_experiment, note=None):
    old_status_code = application.status
    from juloserver.moengage.services.data_constructors import (
        APPLICATION_EVENT_STATUS_CONSTRUCTORS,
    )
    from juloserver.moengage.services.use_cases import (
        send_user_attributes_to_moengage_for_realtime_basis,
        update_moengage_for_application_status_change_event,
    )
    from juloserver.partnership.tasks import (
        send_email_notification_to_user_check_submission_status_task,
        trigger_partnership_callback,
        process_checking_mandatory_document_at_120,
    )

    from juloserver.application_flow.services import process_antifraud_status_decision_x120

    if (
        application.is_regular_julo_one()
        and application.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        and new_status_code == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        and process_antifraud_status_decision_x120(application)
    ):
        return False

    is_salesops_submission = (
        application.is_agent_assisted_submission()
        and new_status_code == ApplicationStatusCodes.FORM_PARTIAL
    )

    if new_status_code == old_status_code and not is_salesops_submission:
        logger.warning({
            'reason': 'Status change to itself!',
            'application_id': application.id,
            'old_status_code': old_status_code,
            'new_status_code': new_status_code
        })
        return False

    with ApplicationHistoryUpdated(application, change_reason=change_reason, is_experiment=is_experiment) as updated:

        workflow = application.workflow
        if not workflow:
            workflow = Workflow.objects.get(name='LegacyWorkflow')  # use the default one
        status_path = WorkflowStatusPath.objects.get_or_none(
            workflow=workflow, status_previous=application.status, status_next=new_status_code, is_active=True)
        if not status_path:
            logger.error({'reason': 'Workflow not specified for status change',
                          'application_id': application.id,
                          'old_status_code': old_status_code,
                          'new_status_code': new_status_code})
            raise JuloInvalidStatusChange(
                "No path from status {} to {}".format(old_status_code, new_status_code))

            # Triggering workflow action defined in workflows submodule
        # if is_experiment:
        #     application.change_status(new_status_code)
        #     application.save()
        # else:
        # TODO : need to add new feature to skip action
        processed = execute_action(application, old_status_code, new_status_code, change_reason, note, workflow,
                                   'pre')
        if not processed:
            logger.warn({
                'status': 'workflow_action_ran',
                'workflow_action': 'pre actions',
                'new_status_code': new_status_code,
                'path_end': new_status_code
            })
            return False
        application.change_status(new_status_code)
        application.save(update_fields=['application_status'])
        logger.info({
            'current_status': application.status,
            'action': 'application status already changed by change_status() function',
            'application_id': application.id
        })

    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.entry_limit.tasks import entry_level_limit_force_status

    logger.info({
        'current_status': application.status,
        'action': 'application status already changed with history',
        'application_id': application.id
    })

    application_tag_tracking_task(
        application.id,
        old_status_code,
        new_status_code,
        change_reason
    )

    logger.info({
        'current_status': application.status,
        'action': 'application tag tracking task already triggered after status changes',
        'application_id': application.id
    })

    is_force = entry_level_limit_force_status(application.id, new_status_code)

    logger.info({
        'current_status': application.status,
        'action': 'force change status EL already triggered',
        'application_id': application.id,
        'is_force': is_force,
    })

    if not is_force:
        execute_action(application, old_status_code, new_status_code,
                       change_reason, note, workflow, 'post')
        execute_action(application, old_status_code, new_status_code,
                       change_reason, note, workflow, 'async_task')
        execute_action(application, old_status_code, new_status_code,
                       change_reason, note, workflow, 'after')
    status_change = updated.status_change

    logger.info({
        'current_status': application.status,
        'action': 'workflow action already executed',
        'application_id': application.id,
        'updated.status_change' : updated.status_change
    })

    if application.is_partnership_app() or application.is_partnership_webapp():
        # partnership agent assisted flow
        partnership_application_id = application.id
        agent_assisted_app_flag_name = PartnershipApplicationFlag.objects.filter(
            application_id=partnership_application_id,
            name=PartnershipPreCheckFlag.APPROVED,
        ).exists()
        if (
            agent_assisted_app_flag_name
            and application.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        ):
            logger.info(
                {
                    'action': 'agent_assisted_process_checking_mandatory_document',
                    'message': 'start check mandatory documents',
                    'status_code': str(application.status),
                    'application': application.id,
                }
            )
            process_checking_mandatory_document_at_120.apply_async(
                args=[application.id], countdown=5
            )

        if new_status_code != ApplicationStatusCodes.FORM_PARTIAL:
            trigger_partnership_callback.delay(application.id, new_status_code)

    if not is_experiment:
        trigger_info_application_partner(status_change)

    partner = application.partner
    is_form_created = ApplicationStatusCodes.FORM_CREATED
    is_form_partial = ApplicationStatusCodes.FORM_PARTIAL
    if partner and (old_status_code == is_form_created and new_status_code == is_form_partial):
        # Send notification if user need to check submission to upload more document
        # Only Leadgen partner
        countdown_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PARTNERSHIP_COUNTDOWN_NOTIFY_105_APPLICATION
        ).last()
        # This feature setting will save the countdown to run the task
        # the default should be 1 minute
        if countdown_feature_setting and countdown_feature_setting.parameters.get("countdown"):
            countdown = countdown_feature_setting.parameters.get("countdown")
        else:
            countdown = 60

        # Handle dana not send email notification, since the flow itself different
        # And dana user don't have an email, email in application is masking form JULO side
        if not application.is_dana_flow():
            send_email_notification_to_user_check_submission_status_task.apply_async(
                args=[application.id], countdown=countdown
            )

    if note:
        application_note = ApplicationNote.objects.create(
            note_text=note, application_id=application.id, application_history_id=status_change.id
        )
        logger.info(
            {
                'status': 'status_change_noted',
                'application_note': application_note,
                'status_change': status_change,
            }
        )

    logger.info({
        'current_status': application.status,
        'action': 'start send to moengage on status changes',
        'application_id': application.id,
        'old_status_code' : old_status_code,
        'new_status_code' : new_status_code,
    })

    if old_status_code != new_status_code:
        if (
            not application.is_julo_one()
            and not application.is_grab()
            and not application.is_julo_starter()
            and not application.is_julo_one_ios()
        ):
            send_user_attributes_to_moengage_for_realtime_basis.apply_async(
                (application.customer.id,),
                countdown=settings.DELAY_FOR_REALTIME_EVENTS)
        else:
            app_status_changes = list(APPLICATION_EVENT_STATUS_CONSTRUCTORS.keys())
            if new_status_code in app_status_changes:
                update_moengage_for_application_status_change_event.apply_async((
                    new_status_code,
                    None,
                    application.id), countdown=settings.DELAY_FOR_REALTIME_EVENTS)
            send_user_attributes_to_moengage_for_realtime_basis.apply_async(
                (application.customer.id,),
                countdown=settings.DELAY_FOR_REALTIME_EVENTS)

    logger.info({
        'current_status': application.status,
        'action': 'normal application status change is finish',
        'application_id': application.id,
    })
    return True


def process_payment_status_change(
        payment_id, new_status_code, change_reason, note=None):
    payment = Payment.objects.get_or_none(id=payment_id)
    if payment is None:
        logger.warn({
            'status': 'payment_not_found',
            'payment': payment_id
        })
        return False

    current_status_code = payment.status

    path_origin = get_payment_path_origin(current_status_code)
    for path in path_origin['allowed_paths']:
        if path['end_status'] == new_status_code:
            path_end = path
            logger.info({
                'status': 'path_end_found',
                'new_status_code': new_status_code,
                'path_end': path_end
            })

    old_status_code = payment.status

    # No specific function has been defined yet for this change path.
    # Simply changing the status code.
    payment.change_status(new_status_code)
    payment.save(update_fields=['payment_status',
                                'udate'])

    new_status_code = payment.status
    status_change = PaymentStatusChange.objects.create(
        payment=payment,
        status_old=old_status_code,
        status_new=new_status_code,
        change_reason=change_reason)
    if note:
        payment_note = PaymentNote.objects.create(
            note_text=note,
            payment=payment,
            status_change=status_change)
        logger.info({
            'status': 'status_change_noted',
            'payment_note': payment_note,
            'status_change': status_change
        })
    # block notify to partner
    if payment.loan.application.customer.can_notify:
        event_end_year(payment, new_status_code, old_status_code)

    create_tokopedia_jan_promo_entry(payment)
    create_promo_history_and_payment_event(payment)

    return True


def is_loan_processing_eligible_at_216(loan):
    application = loan.get_application
    eligibles = [
        application.is_julo_one,
        application.is_grab,
        application.is_merchant_flow,
        application.is_julover,
    ]
    return any(x() for x in eligibles)


def process_loan_status_change(loan_id, new_status_code, change_reason, user=None):
    from juloserver.loan.services.lender_related import (
        julo_one_loan_disbursement_success,
    )
    from juloserver.loan.services.loan_related import (
        update_loan_status_and_loan_history,
    )

    loan = Loan.objects.get_or_none(id=loan_id)
    if loan is None:
        logger.warn({
            'status': 'application_not_found',
            'application': loan_id
        })
        return False
    current_status_code = loan.status
    path_origin = get_loan_path_origin(current_status_code)
    for path in path_origin['allowed_paths']:
        if path['end_status'] == new_status_code:
            path_end = path
            logger.info({
                'status': 'path_end_found',
                'new_status_code': new_status_code,
                'path_end': path_end
            })

    old_status_code = loan.status

    #For manual CRM Loan Disbursement.
    if new_status_code == LoanStatusCodes.CURRENT:
        julo_one_loan_disbursement_success(loan)
        loan.refresh_from_db()
    elif (new_status_code == LoanStatusCodes.CANCELLED_BY_CUSTOMER and
            is_loan_processing_eligible_at_216(loan)):
        if not user:
            raise JuloException("User Not Found")
        user_groups = user.groups.values_list('name', flat=True)
        if 'bo_data_verifier' not in user_groups:
            raise JuloException("User doesn't have access to change loan status")
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=new_status_code,
            change_by_id=user.id,
            change_reason=change_reason
        )
    else:
        loan.change_status(new_status_code)
        loan.save(update_fields=['loan_status',
                                    'udate'])

    status_change = LoanStatusChange.objects.create(
        loan=loan,
        status_old=old_status_code,
        status_new=new_status_code,
        change_reason=change_reason)
    return True


def get_paid_amount_and_wallet_amount(
        payment, customer, paid_amount, use_wallet, account_payment=None,
        change_reason=None):
    def _get_wallet_balance_available():
        if use_wallet:
            if change_reason == CashbackChangeReason.SYSTEM_USED_ON_PAYMENT_EXPIRY_DATE:
                expiry_date = get_expire_cashback_date_setting()
                return customer.wallet_history.get_queryset().\
                    total_cashback_earned_available_to_date(expiry_date)

            return customer.wallet_balance_available

    remaining_paid_amount = 0
    remaining_wallet_amount = 0
    wallet_amount = 0
    if account_payment:
        due_amount = account_payment.due_amount
    else:
        due_amount = payment.due_amount
    if paid_amount > due_amount:
        remaining_paid_amount = paid_amount - due_amount
        paid_amount -= remaining_paid_amount
        if use_wallet:
            remaining_wallet_amount = _get_wallet_balance_available()
        return remaining_paid_amount, paid_amount, remaining_wallet_amount, wallet_amount
    if use_wallet:
        wallet_amount = _get_wallet_balance_available()
    else:
        paid_amount = paid_amount
        return remaining_paid_amount, paid_amount, remaining_wallet_amount, wallet_amount
    paid_amount_with_wallet = paid_amount + wallet_amount
    if due_amount >= paid_amount_with_wallet:
        return remaining_paid_amount, paid_amount, remaining_wallet_amount, wallet_amount
    wallet_used = due_amount - paid_amount
    remaining_wallet_amount = wallet_amount - wallet_used
    wallet_amount = wallet_used
    return remaining_paid_amount, paid_amount, remaining_wallet_amount, wallet_amount


def process_partial_payment(
        payment, paid_amount, note,
        paid_date_str=None, paid_date=None, use_wallet=False,
        payment_receipt=None, payment_method=None, collected_by=None, reversal_payment_event_id=None,
        payment_order=0, change_reason=None):

    from juloserver.cootek.tasks import cancel_phone_call_for_payment_paid_off
    from juloserver.customer_module.services.customer_related import (
        update_cashback_balance_status,
    )
    from juloserver.moengage.tasks import (
        async_update_moengage_for_payment_due_amount_change,
    )

    from ..minisquad.tasks2 import delete_paid_payment_from_intelix_if_exists_async

    payment.refresh_from_db()
    # Convert paid date from string into datetime.date type
    if paid_date_str:
        paid_datetime = datetime.strptime(paid_date_str, "%d-%m-%Y")
        paid_date = paid_datetime.date()
    if not paid_date and not paid_date_str:
        paid_date = timezone.now().date()

    # delete late fee
    customer = payment.loan.customer
    if payment.late_fee_amount:
        if paid_date < (payment.due_date + relativedelta(
                days=get_grace_period_days(payment))):
            payment = process_delete_late_fee(payment, customer, paid_amount, paid_date, use_wallet)

    # Get Customer paid and use wallet
    remaining_paid_amount, paid_amount, remaining_wallet_amount, wallet_amount = \
        get_paid_amount_and_wallet_amount(
            payment, customer, paid_amount, use_wallet, change_reason=change_reason
        )
    total_paid_amount = paid_amount + wallet_amount
    total_remaining_amount = remaining_paid_amount + remaining_wallet_amount

    # Update due amount
    old_due_amount = payment.due_amount
    new_due_amount = old_due_amount - total_paid_amount

    logger.info({
        'paid_amount': paid_amount,
        'remaining_paid_amount': remaining_paid_amount,
        'wallet_amount': wallet_amount,
        'remaining_wallet_amount': remaining_wallet_amount,
        'total_paid_amount': total_paid_amount,
        'old_due_amount': old_due_amount,
        'new_due_amount': new_due_amount,
        'payment': payment.id,
        'paid_date': paid_date,
        'action': 'process_partial_payment'
    })

    payment_method_id = None

    with transaction.atomic():
        payment.paid_amount += total_paid_amount
        payment.due_amount = new_due_amount
        payment.paid_date = paid_date
        payment.redeemed_cashback += wallet_amount
        payment.save(update_fields=['paid_amount',
                                    'due_amount',
                                    'paid_date',
                                    'redeemed_cashback',
                                    'udate'])

        if payment_method is not None:
            payment_method_id = payment_method.id

        # initiate agent service instance
        agent_service = get_agent_service_for_bucket()

        if use_wallet and wallet_amount > 0:
            customer.change_wallet_balance(change_accruing=-wallet_amount,
                                           change_available=-wallet_amount,
                                           reason=change_reason,
                                           payment=payment)
            payment_event = PaymentEvent.objects.create(
                # added_by=user,
                payment=payment,
                event_payment=wallet_amount,
                event_due_amount=old_due_amount,
                event_date=paid_date,
                event_type='customer_wallet')

            record_payment_transaction(
                payment, wallet_amount, old_due_amount, paid_date, 'borrower_wallet')

            old_due_amount -= wallet_amount

        # check payment for cootek if already paid off
        if payment.due_amount == 0:
            process_unassignment_when_paid.delay(payment.id)
            payment_form_cootek = CootekRobocall.objects.filter(
                payment=payment).last()

            if payment_form_cootek:
                cancel_phone_call_for_payment_paid_off.delay(payment_form_cootek.id)

        if paid_amount > 0:
            # only get agent collect if no agent passed and late payment (dpd1++)
            assignment = None
            if collected_by is None and paid_date > payment.due_date:
                assignment = agent_service.get_current_payment_assignment(payment)

                if assignment and assignment.actual_agent:
                    collected_by = assignment.actual_agent

                logger.info({
                    'set_agent_collected': collected_by,
                    'payment_id': payment.id
                })

            if (assignment is not None and assignment.assign_to_vendor
                    is False) or assignment is None:
                insert_data_into_commission_table(
                    payment,
                    collected_by,
                    total_paid_amount)

            payment_event = PaymentEvent.objects.create(
                # added_by=user,
                payment=payment,
                event_payment=paid_amount,
                event_due_amount=old_due_amount,
                event_date=paid_date,
                event_type='payment',
                payment_receipt=payment_receipt,
                payment_method=payment_method,
                collected_by=collected_by,
                reversal_id=reversal_payment_event_id
            )

            record_payment_transaction(
                payment, paid_amount, old_due_amount, paid_date,
                'borrower_bank', payment_receipt, payment_method)


        if note:
            payment_note = PaymentNote.objects.create(
                note_text=note,
                payment=payment)
            logger.info({
                'payment_note_create': payment_note,
                'payment_event_create': payment,
            })

        if new_due_amount == 0:
            logger.info({
                'status': 'payment_paid_off',
                'action': 'updating_loan_payments',
                'payment': payment.id
            })
            processed = process_received_payment(payment)
            update_cashback_balance_status(customer)

            # unassign paid payment
            agent_service.unassign_payment(payment)

            if not processed:
                return False
            process_promo_asian_games(payment, customer)
            delete_paid_payment_from_intelix_if_exists_async.delay(payment.id)

    # upload_data_to_centerix_async.apply_async((payment.id, payment_method_id), countdown=30)

    # Recursive call if payment went over
    if total_remaining_amount > 0:

        next_payment = payment.get_next_unpaid_payment()
        # payment acrossing loan
        if not next_payment:
            next_loan = get_next_unpaid_loan(customer)
            if next_loan:
                next_payment = get_oldest_payment_due(next_loan)

        account = payment.loan.account
        if account:
            application = account.last_application
        else:
            customer = payment.loan.customer
            application = customer.application_set.last()

        if next_payment:
            payment_order += 1
            if not 'AXIATA' in application.product_line.product_line_type:
                process_partial_payment(next_payment, remaining_paid_amount, note,
                                        None, paid_date, use_wallet,
                                        payment_receipt, payment_method, collected_by,
                                        payment_order=payment_order, change_reason=change_reason)
        if not next_payment or ('AXIATA' in application.product_line.product_line_type):
            if remaining_paid_amount > 0:
                notify_payment_over_paid(payment, remaining_paid_amount)
                customer.change_wallet_balance(change_accruing=remaining_paid_amount,
                                               change_available=remaining_paid_amount,
                                               reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                                               payment=payment,
                                               payment_event=payment_event)
    return True


def update_customer_data(application, customer=None, only_update_provided_fields=False):
    # get object customer by application_id
    if not customer:
        customer = application.customer
        customer.refresh_from_db()
    data = {} if only_update_provided_fields else dict(can_reapply=False)
    if application.fullname and customer.fullname != application.fullname:
        data['fullname'] = application.fullname
    if application.mobile_phone_1 and customer.phone != application.mobile_phone_1:
        data['phone'] = application.mobile_phone_1
    if application.email and customer.email != application.email:
        data['email'] = application.email
    customer.update_safely(**data)

    logger.info({
        'application': application.id,
        'customer_id': application.customer_id,
        'customer_name': application.fullname,
        'customer_phone': application.mobile_phone_1,
        'action': 'updating_customer',
    })
    return customer


def send_custom_sms_payment_reminder(payment, phone_number, phone_type, category, text,
                                     template_code):
    mobile_number = format_e164_indo_phone_number(phone_number)
    # call sms client
    is_bucket_5, _template = loan_refinancing_service.check_template_bucket_5(
        payment, template_code, 'crm_sending')
    if is_bucket_5:
        get_julo_sms = get_julo_perdana_sms_client()
    else:
        get_julo_sms = get_julo_sms_client()

    message_content, api_response = get_julo_sms.sms_custom_payment_reminder(
        mobile_number, text)

    if api_response['status'] != '0':
        raise SmsNotSent({
            'send_status': api_response['status'],
            'payment_id': payment.id,
        })

    application = payment.loan.application
    customer = payment.loan.application.customer
    sms = create_sms_history(response=api_response,
                             customer=customer,
                             application=application,
                             payment=payment,
                             status='sent',
                             message_content=message_content,
                             phone_number_type=phone_type,
                             template_code=template_code,
                             category=category,
                             to_mobile_phone=format_e164_indo_phone_number(mobile_number))


def send_custom_sms_account_payment_reminder(account_payment, phone_number, phone_type, category,
                                             text, template_code):
    mobile_number = format_e164_indo_phone_number(phone_number)
    # call sms client
    get_julo_sms = get_julo_sms_client()
    message_content, api_response = get_julo_sms.sms_custom_payment_reminder(
        mobile_number, text)
    if api_response['status'] != '0':
        raise SmsNotSent({
            'send_status': api_response['status'],
            'account_payment_id': account_payment.id,
        })
    application = account_payment.account.last_application
    customer = account_payment.account.customer
    sms = create_sms_history(response=api_response,
                             customer=customer,
                             application=application,
                             payment=None,
                             account_payment=account_payment,
                             status='sent',
                             message_content=message_content,
                             phone_number_type=phone_type,
                             template_code=template_code,
                             category=category,
                             to_mobile_phone=format_e164_indo_phone_number(mobile_number))


def check_partner_account_id_by_application(application):
    partner_account_id_used = False
    applications = Application.objects.filter(
        customer=application.customer,
        partner__isnull=False,
        partner=application.partner)
    already_partner_account_id = applications.exclude(id=application.id)
    if already_partner_account_id:
        partner_account_id_used = True
    return partner_account_id_used


def get_partner_account_id_by_partner_refferal(application, rules_setting):
    partner_account_id = None
    partner_referral = None
    partner_referrals = PartnerReferral.objects.filter(
        partner=application.partner,
        cust_email__iexact=application.email,
        cust_nik=application.ktp,
        partner_account_id__isnull=rules_setting.is_blank,
        pre_exist=True
    ).order_by('id').last()
    if partner_referrals:
        partner_account_id = partner_referrals.partner_account_id
        partner_referral = partner_referrals
    return partner_account_id, partner_referral


def create_partner_account_attribution(application, partner_referral):
    # check setting partner account attritbution settings
    rules_setting = PartnerAccountAttributionSetting.objects.filter(partner=partner_referral.partner).last()
    if not rules_setting:
        return
    partner_account_id = partner_referral.partner_account_id
    # implementation rules partner attritbution settings
    if rules_setting.is_uniqe:
        # check if partner_account_id has already been used
        if check_partner_account_id_by_application(application):
            partner_account_id, partner_referral = get_partner_account_id_by_partner_refferal(application, rules_setting)
    logger.info({
        'action': 'create_partner_account_attribution',
        'application': application,
        'partner_referral': partner_referral,
        'partner_account_id': partner_account_id
    })
    if not partner_account_id:
        partner_referral = None
    partner_account_attribution = PartnerAccountAttribution.objects.filter(application=application).last()

    if partner_account_attribution:
        partner_account_attribution.partner_referral = partner_referral
        partner_account_attribution.partner_account_id = partner_account_id
        partner_account_attribution.save()
    else:
        PartnerAccountAttribution.objects.create(
            customer=application.customer,
            partner=application.partner,
            partner_referral=partner_referral,
            application=application,
            partner_account_id=partner_account_id
        )


def link_to_partner_if_exists(application):
    # change query base on cust_email and
    partner_referral = None
    customer = application.customer
    detokenize_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenize_customers[0]
    if application.customer.email:
        partner_referral = PartnerReferral.objects.filter(cust_email=customer.email).last()

    if not partner_referral:
        partner_referral = PartnerReferral.objects.filter(cust_nik=customer.nik).last()

    if not partner_referral and application.customer.phone:
        # We use e164 format because PartnerReferral mobile_phone is save in e164 format
        try:
            parse_phone_number = phonenumbers.parse(number=customer.phone, region='ID')
        except phonenumbers.NumberParseException:
            customer_phone = customer.phone.replace('+', '')
            parse_phone_number = phonenumbers.parse(
                number=customer_phone, region='ID'
            )
        phone_number_e164 = phonenumbers.format_number(
            parse_phone_number, phonenumbers.PhoneNumberFormat.E164
        )
        partner_referral = PartnerReferral.objects.filter(
            mobile_phone__in=[phone_number_e164, application.customer.phone]
        ).last()

        """
            Edge case sometimes field mobile_phone field fill in "+NoneNone"
            the queryset from PhoneNumberField will be return this data
            eg: PartnerReferral.objects.filter(mobile_phone='082212345678')
            ^ this will be return the data from row contains mobile_phone
            filled by +NoneNone mobile_phone = '+NoneNone (Should be bug from PhoneNumberField)
        """
        if partner_referral and 'None' in partner_referral.mobile_phone.raw_input:
            partner_referral = None

    if not partner_referral:
        logger.info({
            'status': 'application_has_no_partner',
            'application': application,
        })
        return None

    if not partner_referral.customer:
        partner_referral.customer = application.customer
        logger.info({
            'action': 'create_link_partner_referral_to_customer',
            'customer_id': application.customer.id,
            'partner_referral_id': partner_referral.id,
            'email': application.customer.email
        })
        partner_referral.save()

    # if partner id are not partner referral skip all process
    if partner_referral.partner.name not in PartnerConstant.referral_partner():
        return partner_referral

    diff_date = application.cdate - partner_referral.cdate
    if diff_date.days > 30:
        logger.info({
            'status': 'application_has_no_partner',
            'application': application,
        })
        application.partner = None
        application.save()
        PartnerAccountAttribution.objects.filter(application=application).delete()
        return partner_referral

    application.partner = partner_referral.partner
    logger.info({
        'status': 'application_link_to_partner',
        'application': application,
        'partner': partner_referral.partner.name
    })
    application.save()
    create_partner_account_attribution(application, partner_referral)
    return partner_referral


def link_to_partner_by_product_line(application):
    application.refresh_from_db()
    partner = None
    if application.product_line.product_line_code in ProductLineCodes.bri():
        partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
    if application.product_line.product_line_code in ProductLineCodes.ctl():
        partner = Partner.objects.get(name=PartnerConstant.BFI_PARTNER)
    if application.product_line.product_line_code in ProductLineCodes.loc():
        partner = None
        application.partner = partner
        application.save()
    if partner:
        application.partner = partner
        logger.info({
            'status': 'application_link_to_partner_by_product_line',
            'application': application,
            'partner': partner.name
        })
        application.save()


def send_data_to_collateral_partner(application):
    partner_loan = PartnerLoan.objects.filter(application=application).first()

    try:
        get_bfi_client().send_data_application(application)
        partner_loan.approval_status = 'sent'
        partner_loan.save()
    except Exception:
        partner_loan.approval_status = 'not_sent'
        partner_loan.save()


def send_custom_email_payment_reminder(payment, email, subject, content, category, pre_header,
                                       template_code):

    is_bucket_5, _template = loan_refinancing_service.check_template_bucket_5(
        payment, template_code, 'crm_sending')
    email_client = get_julo_email_client()
    status, _, headers = email_client.email_custom_payment_reminder(
        email, subject, content, pre_header, is_bucket_5)

    if status == 202:
        message_id = headers['X-Message-Id']
        payment = payment
        application = payment.loan.application
        customer = application.customer

        EmailHistory.objects.create(
            payment=payment,
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=email,
            subject=subject,
            message_content=content,
            template_code=template_code,
            pre_header=pre_header,
            category=category
        )

        logger.info({
            'status': status,
            'message_id': message_id
        })

        return True

    else:
        logger.warn({
            'status': status,
            'message_id': headers['X-Message-Id']
        })


def send_custom_email_account_payment_reminder(account_payment, email, subject, content,
                                               category, pre_header, template_code):

    email_client = get_julo_email_client()
    status, _, headers = email_client.email_custom_payment_reminder(
        email, subject, content, pre_header)

    if status == 202:
        message_id = headers['X-Message-Id']
        customer = account_payment.account.customer

        EmailHistory.objects.create(
            account_payment=account_payment,
            customer=customer,
            sg_message_id=message_id,
            to_email=email,
            subject=subject,
            message_content=content,
            template_code=template_code,
            pre_header=pre_header,
            category=category
        )

        logger.info({
            'status': status,
            'message_id': message_id
        })

        return True

    else:
        logger.warn({
            'status': status,
            'message_id': headers['X-Message-Id']
        })


def send_email_application(application, email_sender, email_receiver, subject, content, email_cc=None, template_code='custom'):
    client = get_julo_email_client()
    status, _, headers = client.send_email(
        subject=subject, content=content, email_to=email_receiver, email_from=email_sender,
        pre_header=None, email_cc=email_cc
    )
    if status == 202:
        message_id = headers['X-Message-Id']
        application = application
        customer = application.customer

        EmailHistory.objects.create(
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=email_receiver,
            cc_email=email_cc,
            subject=subject,
            message_content=content,
            template_code=template_code
        )

        logger.info({
            'status': status,
            'message_id': message_id,
            'application_id': application.id
        })

        return True

    else:
        logger.warn({
            'status': status,
            'message_id': headers['X-Message-Id']
        })


def send_email_courtesy(application):
    client = get_julo_email_client()
    status, headers, msg, subject = client.email_courtesy(application)
    if status == 202:
        message_id = headers['X-Message-Id']
        application = application
        customer = application.customer

        EmailHistory.objects.create(
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=application.email,
            subject=subject,
            message_content=msg,
            template_code='custom'
        )

        logger.info({
            'status': status,
            'message_id': message_id,
            'application_id': application.id
        })

        return True

    else:
        logger.warn({
            'status': status,
            'message_id': headers['X-Message-Id']
        })


def update_late_fee_amount(payment_id):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.loan.product.latefeerule_set.exists():
            logger.warning(
                {
                    "action": "juloserver.julo.services.update_late_fee_amount",
                    "message": "new late fee implementation",
                    "payment_id": payment_id,
                }
            )
            return
        if payment.status in PaymentStatusCodes.paid_status_codes():
            logger.warning(
                {
                    "action": "juloserver.julo.services.update_late_fee_amount",
                    "message": "payment in paid status",
                    "payment_id": payment_id,
                }
            )
            return
        loan = payment.loan
        #freeze late fee for sold off loan
        if loan.status == LoanStatusCodes.SELL_OFF:
            logger.warning(
                {
                    "action": "juloserver.julo.services.update_late_fee_amount",
                    "message": "loan is sell off status",
                    "payment_id": payment_id,
                }
            )
            return
        product_line_id = payment.loan.product.product_line_id

        pl_manual_process_and_rabando = ProductLineCodes.manual_process() + [ProductLineCodes.RABANDO]
        if payment.is_julo_one_payment or \
                (product_line_id in ProductLineCodes.axiata() and payment.account_payment) or \
                product_line_id in pl_manual_process_and_rabando or \
                payment.is_julo_starter_payment:
            product_line_code = payment.account_payment.account.last_application.product_line.product_line_code
        elif product_line_id in ProductLineCodes.grab() and payment.account_payment:
            logger.warning(
                {
                    "action": "juloserver.julo.services.update_late_fee_amount",
                    "message": "grab payment",
                    "payment_id": payment_id,
                }
            )
            return
        elif product_line_id == ProductLineCodes.RENTEE:
            product_line_code = product_line_id
        elif loan.application:
            product_line_code = payment.loan.application.product_line.product_line_code
        else:
            logger.warning(
                {
                    "action": "juloserver.julo.services.update_late_fee_amount",
                    "message": "product line is not eligible",
                    "payment_id": payment_id,
                }
            )
            return

        product_line = ProductLineManager.get_or_none(product_line_code)

        if payment.late_fee_applied >= len(product_line.late_dates):
            logger.warning({
                'warning': 'late fee applied maximum times',
                'late_fee_applied': payment.late_fee_applied,
                'payment_id': payment.id,
            })
            return

        late_date_rule = product_line.late_dates[payment.late_fee_applied]
        # late fee earlier
        late_date_rule = pull_late_fee_earlier(payment, late_date_rule)
        today = date.today()
        due_late_days = relativedelta(date.today(), payment.due_date)
        old_late_fee_amount = payment.late_fee_amount

        if payment.due_date + late_date_rule[0] <= today:
            if product_line_id in pl_manual_process_and_rabando:
                late_fee = payment.calculate_late_fee_productive_loan(product_line_id)
            else:
                late_fee = payment.calculate_late_fee()
            if late_fee > 0:
                due_amount_before = payment.due_amount
                # decrease late fee STL
                if product_line.product_line_code in ProductLineCodes.stl() and payment.late_fee_applied < 2:
                    late_fee = late_fee - (old_div(late_fee * 50, 100))
                # set max late_fee
                late_fee, status_max_late_fee = loan.get_status_max_late_fee(late_fee)
                if status_max_late_fee:
                    logger.warning(
                        {
                            "action": "juloserver.julo.services.update_late_fee_amount",
                            "message": "payment in status max late fee",
                            "payment_id": payment_id,
                        }
                    )
                    return
                payment.apply_late_fee(late_fee)
                payment.refresh_from_db()
                PaymentEvent.objects.create(payment=payment,
                                            event_payment=-late_fee,
                                            event_due_amount=due_amount_before,
                                            event_date=today,
                                            event_type='late_fee')
                logger.info({
                    'action': 'update_late_fee_amount',
                    'payment_id': payment.id,
                    'due_late_days': due_late_days,
                    'old_late_fee': old_late_fee_amount,
                    'late_fee_amount_added': late_fee,
                })
                if payment.late_fee_applied > 2:
                    customer = loan.customer
                    customer.can_reapply = False
                    customer.save(update_fields=['can_reapply'])

                if not payment.account_payment:
                    automate_late_fee_waiver(payment, late_fee, today)

            return
        logger.debug({'payment': payment.id,
                      'updated': False})

def file_to_bytes(file_obj: File) -> bytes:
    file_obj.seek(0)  # Ensure you're at the beginning of the file
    return file_obj.read()


def create_imagealias_from_file(file_obj: File) -> Imagealias:
    image_stream = BytesIO(file_to_bytes(file_obj))
    image = Imagealias.open(image_stream)
    return image


def convert_imagealias_to_bytes(image: Imagealias, filename: str, ext: str = None) -> bytes:
    # Determine format based on filename extension
    if not ext:
        _, ext = os.path.splitext(filename)
    ext = ext.lower().strip('.')

    ext_to_format = {
        'jpg': 'JPEG',
        'jpeg': 'JPEG',
        'png': 'PNG',
        'webp': 'WEBP',
        'gif': 'GIF',
        'bmp': 'BMP',
        'tiff': 'TIFF',
    }

    format = ext_to_format.get(ext)
    if not format:
        raise ValueError(f"Unsupported file extension: {ext}")

    image_io = BytesIO()
    image.save(image_io, format=format)
    return image_io.getvalue()


def process_image_upload_direct(
    image, file, thumbnail=True, delete_if_last_image=False, suffix=None, image_file_name=None
):
    """
    Upload an image file directly to OSS (bypassing NFS) and handle optional thumbnail creation,
    image versioning, and cleanup of old images. This function duplicated from process_image_upload()

    Args:
        image (Image): Django Image model instance containing metadata (e.g., image_source, image_type).
        file (File): Django `File` object or file-like object to be uploaded.
        thumbnail (bool, optional): Whether to generate and upload a thumbnail version. Defaults to True.
        delete_if_last_image (bool, optional): If True, old images will be marked deleted only if this is the last image. Defaults to False.
        suffix (str, optional): Optional suffix to append to the filename.
        file_extension (str, optional): File extension to use for saved files. Defaults to "png".

    Raises:
        JuloException: If the image source (Application, Loan, or Customer) is not found or invalid.

    Returns:
        None
    """
    if 2000000000 < int(image.image_source) < 2999999999:
        application = Application.objects.get_or_none(pk=image.image_source)
        if not application:
            raise JuloException("Application id=%s not found" % image.image_source)
        cust_id = application.customer_id
    elif 3000000000 < int(image.image_source) < 3999999999:
        loan = Loan.objects.get_or_none(pk=image.image_source)
        if not loan:
            raise JuloException("Loan id=%s not found" % image.image_source)
        cust_id = loan.customer_id
    elif 1000000000 < int(image.image_source) < 1999999999:
        is_customer_exists = Customer.objects.filter(pk=image.image_source).exists()
        if not is_customer_exists:
            raise JuloException("Customer id=%s not found" % image.image_source)
        cust_id = int(image.image_source)
    else:
        raise JuloException('Unrecognized image_source=%s' % image.image_source)

    image_remote_filepath = construct_remote_filepath_base(
        cust_id, image, suffix, image_file_name=image_file_name
    )
    file_bytes = file_to_bytes(file)
    upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, file_bytes, image_remote_filepath)
    image.update_safely(url=image_remote_filepath)

    logger.info(
        {
            'status': 'successfull upload image to s3',
            'image_remote_filepath': image_remote_filepath,
            'application_id': image.image_source,
            'image_type': image.image_type,
        }
    )

    # mark all other images with same type as 'deleted'
    image_query = (
        Image.objects.exclude(id=image.id)
        .exclude(image_status=Image.DELETED)
        .filter(image_source=image.image_source, image_type=image.image_type)
    )

    # handle race condition if image type is ktp_self
    if image.image_type == 'ktp_self':

        # getting application data
        application = Application.objects.filter(pk=image.image_source).last()
        if application and application.is_julo_one_or_starter():

            # get other images to delete with id <= current_image.id
            image_query = image_query.filter(id__lte=image.id)
            logger.info(
                {
                    'status': 'delete selected image',
                    'image_remote_filepath': image_remote_filepath,
                    'application_id': image.image_source,
                    'image_id': image.id,
                    'image_list': list(image_query),
                }
            )

    images = list(image_query)
    mark_delete_images = True
    if delete_if_last_image:
        last_image = Image.objects.filter(
            image_source=image.image_source, image_type=image.image_type
        ).last()
        mark_delete_images = True if last_image.id == image.id else False

    if mark_delete_images:
        for img in images:
            logger.info({'action': 'marking_deleted', 'image': img.id})
            img.update_safely(image_status=Image.DELETED)

    if image.image_ext != '.pdf' and thumbnail:

        # create thumbnail
        im = create_imagealias_from_file(file)
        im = im.convert('RGB')
        size = (150, 150)
        im.thumbnail(size, Imagealias.ANTIALIAS)
        _, file_extension = os.path.splitext(image_file_name)
        thumbnail_bytes = convert_imagealias_to_bytes(im, filename=None, ext=file_extension)

        # upload thumbnail to s3
        thumbnail_dest_name = construct_remote_filepath_base(
            cust_id, image, suffix='thumbnail', image_file_name=image_file_name
        )
        upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, thumbnail_bytes, thumbnail_dest_name)

        image.update_safely(thumbnail_url=thumbnail_dest_name)

        logger.info(
            {
                'status': 'successfull upload thumbnail to s3',
                'thumbnail_dest_name': thumbnail_dest_name,
                'application_id': image.image_source,
                'image_type': image.image_type,
            }
        )


def process_image_upload(image, thumbnail=True, delete_if_last_image=False, suffix=None):
    """
    Upload an image file and handle optional thumbnail creation,
    image versioning, and cleanup of old images. This function duplicated by process_image_upload_direct()

    Args:
        image (Image): Django Image model instance containing metadata (e.g., image_source, image_type).
        file (File): Django `File` object or file-like object to be uploaded.
        thumbnail (bool, optional): Whether to generate and upload a thumbnail version. Defaults to True.
        delete_if_last_image (bool, optional): If True, old images will be marked deleted only if this is the last image. Defaults to False.
        suffix (str, optional): Optional suffix to append to the filename.

    Raises:
        JuloException: If the image source (Application, Loan, or Customer) is not found or invalid.

    Returns:
        None
    """
    if 2000000000 < int(image.image_source) < 2999999999:
        application = Application.objects.get_or_none(pk=image.image_source)
        cust_id = application.customer_id
        if not application:
            raise JuloException("Application id=%s not found" % image.image_source)
    elif 3000000000 < int(image.image_source) < 3999999999:
        loan = Loan.objects.get_or_none(pk=image.image_source)
        cust_id = loan.customer_id
        if not loan:
            raise JuloException("Loan id=%s not found" % image.image_source)
    elif 1000000000 < int(image.image_source) < 1999999999:
        is_customer_exists = Customer.objects.filter(pk=image.image_source).exists()
        cust_id = int(image.image_source)
        if not is_customer_exists:
            raise JuloException("Customer id=%s not found" % image.image_source)
    else:
        raise JuloException('Unrecognized image_source=%s' % image.image_source)

    # upload image to s3 and save s3url to field
    image_path = image.image.path

    image_remote_filepath = construct_remote_filepath(cust_id, image, suffix)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, image.image.path, image_remote_filepath)
    image.update_safely(url=image_remote_filepath)

    logger.info({
        'status': 'successfull upload image to s3',
        'image_remote_filepath': image_remote_filepath,
        'application_id': image.image_source,
        'image_type': image.image_type
    })

    # mark all other images with same type as 'deleted'
    image_query = (
        Image.objects.exclude(id=image.id)
        .exclude(image_status=Image.DELETED)
        .filter(image_source=image.image_source, image_type=image.image_type)
    )

    # handle race condition if image type is ktp_self
    if image.image_type == 'ktp_self':

        # getting application data
        application = Application.objects.filter(pk=image.image_source).last()
        if application and application.is_julo_one_or_starter():

            # get other images to delete with id <= current_image.id
            image_query = image_query.filter(id__lte=image.id)
            logger.info(
                {
                    'status': 'delete selected image',
                    'image_remote_filepath': image_remote_filepath,
                    'application_id': image.image_source,
                    'image_id': image.id,
                    'image_list': list(image_query),
                }
            )

    images = list(image_query)
    mark_delete_images = True
    if delete_if_last_image:
        last_image = Image.objects.filter(
            image_source=image.image_source, image_type=image.image_type
        ).last()
        mark_delete_images = True if last_image.id == image.id else False

    if mark_delete_images:
        for img in images:
            logger.info({
                'action': 'marking_deleted',
                'image': img.id
            })
            img.update_safely(image_status=Image.DELETED)

    if image.image_ext != '.pdf' and thumbnail:

        # create thumbnail
        im = Imagealias.open(image.image.path)
        im = im.convert('RGB')
        size = (150, 150)
        im.thumbnail(size, Imagealias.ANTIALIAS)
        image_thumbnail_path = image.thumbnail_path
        im.save(image_thumbnail_path)

        # upload thumbnail to s3
        thumbnail_dest_name = construct_remote_filepath(cust_id, image, suffix='thumbnail')
        upload_file_to_oss(
            settings.OSS_MEDIA_BUCKET, image_thumbnail_path, thumbnail_dest_name)
        image.update_safely(thumbnail_url=thumbnail_dest_name)

        logger.info({
            'status': 'successfull upload thumbnail to s3',
            'thumbnail_dest_name': thumbnail_dest_name,
            'application_id': image.image_source,
            'image_type': image.image_type
        })

        # delete thumbnail from local disk
        if os.path.isfile(image_thumbnail_path):
            logger.info({
                'action': 'deleting_thumbnail_local_file',
                'image_thumbnail_path': image_thumbnail_path,
                'application_id': image.image_source,
                'image_type': image.image_type
            })
            os.remove(image_thumbnail_path)

    # delete image
    if os.path.isfile(image_path):
        logger.info(
            {
                'action': 'deleting_local_file',
                'image_id': image.id,
                'image_path': image_path,
                'application_id': image.image_source,
                'image_type': image.image_type,
            }
        )
        image.image.delete()

    # check make sure it's already deleted
    if os.path.isfile(image_path):
        logger.info(
            {
                'info': 'ANOMALY DETECTED, delete is not working !',
                'image_id': image.id,
                'image_path': image_path,
                'application_id': image.image_source,
                'image_type': image.image_type,
            }
        )
    else:
        logger.info(
            {
                'info': 'delete is success !',
                'image_id': image.id,
                'image_path': image_path,
                'application_id': image.image_source,
                'image_type': image.image_type,
            }
        )


def process_thumbnail_upload(image):
    if 2000000000 < int(image.image_source) < 2999999999:
        application = Application.objects.get_or_none(pk=image.image_source)
        if not application:
            raise JuloException("Application id=%s not found" % image.image_source)
    elif 3000000000 < int(image.image_source) < 3999999999:
        loan = Loan.objects.get_or_none(pk=image.image_source)
        if not loan:
            raise JuloException("Loan id=%s not found" % image.image_source)
    else:
        raise JuloException('Unrecognized image_source=%' % image.image_source)
    cust_id = application.customer.id

    # check is directory exist, if not create dir
    temp_dir = tempfile.mkdtemp()
    image_dir = os.path.join(temp_dir, 'media', 'image_upload', str(image.id))
    if not os.path.isdir(image_dir):
        os.makedirs(image_dir)

    _, extension = os.path.splitext(image.url)

    # download image from cloud storage and write to image file
    response = requests.get(image.image_url, stream=True)
    image_name = os.path.join(image_dir, image.image_type + extension)
    with open(image_name, 'wb') as out_file:
        shutil.copyfileobj(response.raw, out_file)
    logger.info({
        'image_path': image_name,
        'status': 'downloaded'
    })
    # create thumbnail from image
    size = (150, 150)
    suffix = '_thumbnail'
    image_thumbnail = os.path.join(image_dir, image.image_type + suffix + extension)
    im = Imagealias.open(image_name)
    im = im.convert('RGB')
    im.thumbnail(size, Imagealias.ANTIALIAS)
    im.save(image_thumbnail)
    logger.info({
        'image_path': image_name,
        'thumbnail_path': image_thumbnail,
        'status': 'thumbnail_created'
    })

    # construct thumbnail remote path and upload to cloud storage
    thumb_dest_name = construct_remote_filepath(cust_id, image, suffix) + extension
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, image_thumbnail, thumb_dest_name)
    image.thumbnail_url = thumb_dest_name
    image.save()

    # delete thumbnail and original file after upload to s3
    if os.path.isdir(temp_dir):
        logger.info({
            'action': 'deleting_local_file',
            'image_thumbnail': image_thumbnail,
            'application_id': image.image_source,
            'image_type': image.image_type
        })
        shutil.rmtree(temp_dir)


def update_skiptrace_score(skiptrace, start_ts):
    skiptrace.effectiveness = compute_skiptrace_effectiveness(skiptrace)
    skiptrace.recency = start_ts
    if skiptrace.frequency is None:
        skiptrace.frequency = 1
    else:
        skiptrace.frequency += 1
    skiptrace.save()
    logger.info({
        'status': 'skiptrace_score_updated',
        'skiptrace_id': skiptrace.id,
        'effectiveness': skiptrace.effectiveness,
        'recency': skiptrace.recency,
        'frequency': skiptrace.frequency,
    })
    return skiptrace


def primo_update_skiptrace(primo_record, user_obj, call_result):
    skiptrace = primo_record.skiptrace
    application = primo_record.application
    skiptrace_choice_id = 1
    if call_result in list(MAPPING_CALL_RESULT.keys()):
        skiptrace_choice_id = MAPPING_CALL_RESULT[call_result]
    skiptrace_choice = SkiptraceResultChoice.objects.get(pk=skiptrace_choice_id)
    now = timezone.localtime(timezone.now())
    skiptrace_history = SkiptraceHistory.objects.create(
        skiptrace=skiptrace,
        start_ts=primo_record.udate,
        end_ts=now,
        agent=user_obj,
        agent_name=user_obj.username,
        application=application,
        call_result=skiptrace_choice,
        application_status=application.status
    )
    update_skiptrace_score(skiptrace, now)


def choose_number_to_robocall(application):
    skiptrace = Skiptrace.objects.filter(
        customer__id=application.customer_id).filter(
        contact_source__in=['mobile_phone_number_1',
                            'mobile_phone',
                            'mobile_phone_1',
                            'mobile_phone_2',
                            'mobile_phone_3',
                            'mobile phone',
                            'mobile phone 1',
                            'mobile phone 2',
                            'mobile_phone_lain',
                            'mobile_phone1',
                            'mobile_phone2',
                            'mobile',
                            'mobile 1',
                            'mobile 2',
                            'mobile2',
                            'mobile 3',
                            'mobile aktif',
                            'App mobile phone',
                            'App_mobile_phone']).order_by('-effectiveness').first()
    if skiptrace is None:
        raise Exception('Skiptrace for robocall event not found!')

    return str(skiptrace.phone_number), str(skiptrace.id)


def check_unprocessed_doku_payments(start_date):
    response = get_doku_client().check_activities(start_date=start_date)
    new_doku_transactions = []
    for data in reversed(response['mutasi']):
        data_to_save = {}
        if data['type'] == 'C' and 'DOKUID' in data['title']['en']:

            str_doku_id = re.findall(r"DOKUID "'\d+', data['title']['en'])
            doku_id = re.findall(r'\b\d+\b', str_doku_id[0])[0]
            data_to_save['account_id'] = doku_id

            transaction_date = datetime.strptime(data['date'], '%Y-%m-%d %H:%M:%S')
            data_to_save['transaction_date'] = transaction_date

            data_to_save['reference_id'] = data['refId']
            data_to_save['transaction_id'] = data['transactionId']
            data_to_save['amount'] = data['amount']
            data_to_save['transaction_type'] = data['type']

            try:
                doku_transaction = DokuTransaction(**data_to_save)
                doku_transaction.save()
                new_doku_transactions.append(doku_transaction)
            except IntegrityError:
                logger.info({
                    'status': 'already_exists_in_db',
                    'transaction_id': data['transactionId']
                })

    old_unprocessed_transactions = list(DokuTransaction.objects.exclude(is_processed=True))
    unprocessed_transactions = old_unprocessed_transactions + new_doku_transactions

    for doku_transaction in unprocessed_transactions:
        payment_event = PaymentEvent.objects.get_or_none(
            payment_receipt=doku_transaction.transaction_id)
        if payment_event:
            logger.info({
                'status': 'marking_autodebit_transaction_processed',
                'transaction_id': doku_transaction.transaction_id,
                'payment_event': payment_event.id
            })
            doku_transaction.is_processed = True
        else:
            is_processed = process_doku_payment(doku_transaction)
            doku_transaction.is_processed = is_processed
        doku_transaction.save()


def process_doku_payment(doku_transaction):
    account_id = doku_transaction.account_id
    partner_referral = PartnerReferral.objects.filter(
        partner_account_id=account_id).exclude(customer=None).first()

    if not partner_referral:
        logger.warning({
            'status': 'unknown_doku_account_id',
            'account_id': account_id,
            'doku_transaction_id': doku_transaction.transaction_id
        })
        return False

    customer = partner_referral.customer
    active_loan = customer.loan_set.filter(
        loan_status__gte=LoanStatusCodes.CURRENT).exclude(
        loan_status=LoanStatusCodes.PAID_OFF).first()
    if not active_loan:
        logger.warning({
            'status': 'no_active_loan',
            'customer': customer.id,
            'doku_account_id': partner_referral.partner_account_id
        })
        return False

    payment = active_loan.payment_set.not_paid().first()
    if not payment:
        logger.warning({
            'status': 'no_unpaid_payment',
            'loan': active_loan.id,
            'doku_account_id': partner_referral.partner_account_id
        })
        return False

    notes = "doku automation checking payment transaction_id: %s, amount: %s \
            from application %s for payment %s" % (
        doku_transaction.transaction_id, doku_transaction.amount,
        active_loan.application.id, payment.id
    )

    payment_method = get_payment_methods(payment.loan).filter(
        payment_method_code=PaymentMethodCodes.DOKU).first()


    process_partial_payment(
        payment, int(doku_transaction.amount), notes,
        payment_receipt=doku_transaction.transaction_id,
        payment_method=payment_method)

    return True


def create_application_checklist(application):
    # create application checklist data for the first time at 110
    application.refresh_from_db()
    if application.applicationchecklist_set.all().exists():
        return True
    for field in application_checklist:
        data_to_create = {
            'application': application,
            'field_name': field
        }
        application_checklist_obj = ApplicationCheckList(**data_to_create)
        application_checklist_obj.save()


def get_application_comment_list(comments, field_name, group):
    application_cheklist_comments = []
    for comment in comments:
        if comment["group"] == group and comment["field_name"] == field_name:
            agent_name = comment["agent__username"] if comment["agent_id"] else None
            data = {
                'id': comment["id"],
                'comment': comment["comment"],
                'cdate': str(timezone.localtime(comment["cdate"])),
                'agent': agent_name
            }
            application_cheklist_comments.append(data)

    logger.info({
        'action': 'get_application_comment_list',
        'application_checklist_comments': application_cheklist_comments
    })

    return application_cheklist_comments


def get_undisclosed_expense_detail(application_id, field_name):
    additional_expense = AdditionalExpense.objects.select_related('agent').values(
        'id', 'description', 'amount', 'agent__username', 'udate').filter(
            application=application_id,
            field_name=field_name,
            is_deleted=False).order_by('id')
    additional_expense_collection = []
    for expense in additional_expense:
        agent_name = expense["agent__username"] if expense["agent__username"] else None
        data = {
            'id': expense["id"],
            'description': clean_special_character(expense["description"]),
            'amount': expense["amount"],
            'agent': agent_name,
            'udate': expense["udate"],
        }
        additional_expense_collection.append(data)
    return additional_expense_collection


def get_data_application_checklist_collection(application, for_app_only=False):
    data_application_checklist = ApplicationCheckList.objects.values(
        'field_name', 'sd', 'pv', 'dv', 'ca', 'fin', 'coll').filter(
            application_id=int(application.id))
    comments = ApplicationCheckListComment.objects.select_related('agent').values(
        'id', 'agent_id', 'agent__username',
        'cdate', 'comment', 'group', 'field_name').filter(
            application_id=int(application.id)).order_by('-cdate')
    data_collection = {}
    app_checklist = application_checklist_update if for_app_only else application_checklist

    for field in data_application_checklist:
        statuses = []
        if app_checklist[field["field_name"]]["sd"]:
            statuses.append("sd")
        if app_checklist[field["field_name"]]["pv"]:
            statuses.append("pv")
        if app_checklist[field["field_name"]]["dv"]:
            statuses.append("dv")
        if app_checklist[field["field_name"]]["ca"]:
            statuses.append("ca")
        if app_checklist[field["field_name"]]["fin"]:
            statuses.append("fin")
        if application_checklist[field["field_name"]]["coll"]:
            statuses.append("coll")

        extra_field = (
            "bank_scrape", "fraud_report", "karakter",
            "selfie", "signature", "voice_recording",
            "hrd_name", "company_address",
            "bidang_usaha", "number_of_employees", "position_employees",
            "employment_status", "billing_office", "mutation",
            "area_in_nik", "dob_in_nik"
        )
        data_collection[field["field_name"]] = {}
        if field["field_name"] == 'total_current_debt':
            undisclosed_expense_detail = get_undisclosed_expense_detail(
                application.id, 'total_current_debt')
            data_collection['total_current_debt']['undisclosed_expenses'] = undisclosed_expense_detail
        elif field["field_name"] in extra_field:
            data_collection[field["field_name"]]['value'] = ''
        else:
            data_collection[field["field_name"]]['value'] = str(eval('application.%s' % field["field_name"]))

        data_collection[field["field_name"]]['statuses'] = statuses
        data_collection[field["field_name"]]['groups'] = []
        for status in statuses:
            data_each_status = {
                "group_name": status,
                "checklist_status": True,
                "checklist_value": field.get(status, None),
                "comments": get_application_comment_list(comments, field["field_name"], status)
            }
            data_collection[field["field_name"]]['groups'].append(data_each_status)

        logger.info({
            'action': 'get_data_application_checklist_collection_each_field',
            'application_id': application.id,
            'field': field["field_name"],
            'statuses': statuses,
        })

    return data_collection


def update_application_checklist_data(application, data):
    application_checklist_obj = ApplicationCheckList.objects.filter(
        field_name=data['field_name'], application=application).first()
    if not application_checklist_obj:
        raise JuloException('application %s has no checklist' % application.id)

    old_checklist = getattr(application_checklist_obj, data['group'])
    new_checklist = data['value']

    if old_checklist != new_checklist:
        setattr(application_checklist_obj, data['group'], new_checklist)
        application_checklist_obj.save()
        ApplicationCheckListHistory.objects.create(
            application=application,
            field_name=data['field_name'],
            changed_to=new_checklist,
            changed_from=old_checklist,
            group=data['group'],
        )
        logger.info({
            'status': 'application_checklist_data updated',
            'application_checklist_id': application_checklist_obj.id
        })


def update_application_field(application, data):
    # Importing here due to import error
    from juloserver.payback.services.gopay import GopayServices
    from juloserver.account.services.account_related import create_account_cycle_day_history

    if 'value' not in data:
        return True

    if data['field_name'] == 'verified_income':
        hsfbp = HsfbpIncomeVerification.objects.filter(application_id=application.id).last()
        old_value = None
        type_date = None
        if hsfbp:
            old_value = application.hsfbp_verified_income()
            type_date = hsfbp._meta.get_field(data['field_name']).get_internal_type()
    else:
        old_value = getattr(application, data['field_name'])
        type_date = application._meta.get_field(data['field_name']).get_internal_type()
    new_value = data['value'] if 'value' in data else None

    if new_value == old_value or type_date is None:
        return
    if type_date in ['BigIntegerField', 'IntegerField']:
        new_value = int(new_value)
    if type_date == 'DateField':
        new_value = parse(new_value, dayfirst=True)
    if isinstance(old_value, ProductLine):
        new_value = ProductLine.objects.get(pk=int(new_value))

    if data['field_name'] == 'ktp':
        update_ktp_relations(application, new_value)
        customer = application.customer
        CustomerFieldChange.objects.create(
            customer=customer,
            application=application,
            field_name=data['field_name'],
            old_value=old_value,
            new_value=new_value
        )

    if data['field_name'] == 'mobile_phone_1' and application.is_grab():
        update_grab_phone(application, new_value)
        application.refresh_from_db()
        logger.info({
            'status': 'update_application_field',
            'application_id': application.id
        })

        if application.account:
            GopayServices().unbind_gopay_account_linking(application.account)

        return True

    if data['field_name'] == 'mobile_phone_1':
        if check_if_phone_exists(new_value, application.customer):
            raise JuloException(ApplicationStatusChange.DUPLICATE_PHONE)

    setattr(application, data['field_name'], new_value)
    application.save()

    if data['field_name'] == 'mobile_phone_1' and application.account:
        GopayServices().unbind_gopay_account_linking(application.account)

    if data['field_name'] in ['gender', 'fullname']:
        customer = application.customer
        to_update = {
            data['field_name'] : new_value
        }
        customer.update_safely(**to_update)
        CustomerFieldChange.objects.create(
            customer=customer,
            application=application,
            field_name=data['field_name'],
            old_value=old_value,
            new_value=new_value
        )

    if data['field_name'] == 'dob':
        new_value = new_value.date()
        customer = application.customer
        to_update = {
            data['field_name']: new_value
        }
        customer.update_safely(**to_update)
        CustomerFieldChange.objects.create(
            customer=customer,
            application=application,
            field_name=data['field_name'],
            old_value=old_value,
            new_value=new_value
        )

    if data['field_name'] == 'payday':
        account = application.account
        if account:
            old_cycle_day = account.cycle_day
            account.update_safely(
                cycle_day=1 if new_value == 31 else new_value + 1,
                is_payday_changed=True
            )
            create_account_cycle_day_history(
                {}, account, LDDEReasonConst.Manual,
                old_cycle_day, application.pk
            )

    if data['field_name'] == 'verified_income':
        if hsfbp:
            hsfbp.update_safely(verified_income=new_value)

    logger.info({
        'status': 'update_application_field',
        'application_id': application.id
    })

    ApplicationFieldChange.objects.create(
        application=application,
        field_name=data['field_name'],
        old_value=old_value,
        new_value=new_value,
    )

    return True


def update_ktp_relations(application, new_ktp):
    customer = application.customer
    customer.update_safely(nik=new_ktp)
    # update ktp of all application for customer
    customer.application_set.update(ktp=new_ktp)

    user_obj = customer.user
    if user_obj and user_obj.username.isnumeric():
        user_obj.username = new_ktp
        user_obj.save()


def update_undisclosed_expense(application, data):
    old_expenses = AdditionalExpense.objects.filter(
        application=application,
        field_name=data['field_name'],
        is_deleted=False)
    new_ids = [int(new_id['id']) for new_id in data['undisclosed_expense'] if 'id' in new_id]
    for old_expense in old_expenses:
        # old_data
        old_description = old_expense.description
        old_amount = old_expense.amount
        for new_expense in data['undisclosed_expense']:
            # new data
            new_description = new_expense['desc']
            new_amount = int(new_expense['amount'])

            if 'id' in new_expense:
                same_id = int(new_expense['id']) == old_expense.id
                same_description = old_description == new_description
                same_amount = old_amount == new_amount
                if same_id and same_description and same_amount:
                    logger.info({
                        'action': 'update_undisclosed_expense',
                        'status': 'no updated additional expense',
                        'additional_expense_id': old_expense.id
                    })
                if same_id and (not same_description or not same_amount):
                    # update additional expense
                    old_expense.description = new_description
                    old_expense.amount = new_amount
                    old_expense.group = data['group']
                    old_expense.save()

                    logger.info({
                        'action': 'update_undisclosed_expense',
                        'status': 'updated',
                        'additional_expense_id': old_expense.id,
                    })

                    # create history
                    AdditionalExpenseHistory.objects.create(
                        application=application,
                        additional_expense=old_expense,
                        field_name=data['field_name'],
                        old_description=old_description,
                        old_amount=old_amount,
                        new_description=new_description,
                        new_amount=new_amount,
                        group=data['group'],
                    )

        if old_expense.id not in new_ids:
            deleted_id = old_expense.id
            old_expense.is_deleted = True
            old_expense.save()

            # create_delete_history
            AdditionalExpenseHistory.objects.create(
                application=application,
                additional_expense=old_expense,
                field_name=data['field_name'],
                old_description=old_description,
                old_amount=old_amount,
                new_description='deleted',
                new_amount=0,
                group=data['group'],
            )

            logger.info({
                'action': 'mark is_deleted undisclosed expense',
                'additional_expense_id': deleted_id,
            })

    # adding new row
    new_expenses = [new_row for new_row in data['undisclosed_expense'] if 'id' not in new_row]
    for new_data in new_expenses:
        add_expense = AdditionalExpense.objects.create(
            application=application,
            field_name=data['field_name'],
            description=new_data['desc'],
            amount=int(new_data['amount']),
            group=data['group'],
        )

        # create add history
        AdditionalExpenseHistory.objects.create(
            application=application,
            additional_expense=add_expense,
            field_name=data['field_name'],
            old_description='',
            old_amount=0,
            new_description=new_data['desc'],
            new_amount=int(new_data['amount']),
            group=data['group'],
        )

        logger.info({
            'action': 'add undisclosed expense',
            'additional_expense_id': add_expense.id,
        })

    return True


def update_application_checklist_collection(application, new_data):
    with transaction.atomic():
        for data in new_data:
            if data['type'] == 'checklist':
                update_application_checklist_data(application, data)

            # save comment
            if data['type'] == 'comment':
                ApplicationCheckListComment.objects.create(
                    field_name=data['field_name'], application=application,
                    comment=data['value'], group=data['group'],
                )

            if data['type'] == 'field':
                if data['field_name'] == 'verified_income':
                    previous_value = application.hsfbp_verified_income()
                else:
                    previous_value = getattr(application, data['field_name'])
                new_value = data['value']
                update_application_field(application, data)
                
                if previous_value != new_value:
                    send_customer_data_change_by_agent_notification_task.delay(
                        customer_id=application.customer_id,
                        field_changed=AgentDataChange.map_ajax_field_change(data['field_name']),
                        previous_value=previous_value,
                        new_value=new_value,
                        timestamp=application.udate,
                    )

            if data['type'] == 'undisclosed_expense':
                update_undisclosed_expense(application, data)

        # sync data from last application to customer table
        last_application = Application.objects.filter(customer_id=application.customer_id).last()
        if last_application.id == application.id:
            exclude_workflows = (
                    GrabFoodSchema.NAME, PartnerWorkflowSchema.NAME, WorkflowConst.GRAB,
                    WorkflowConst.MERCHANT_FINANCING_WORKFLOW, WorkflowConst.DANA)
            if not application.workflow or application.workflow.name not in exclude_workflows:
                from juloserver.customer_module.services.customer_related import (
                    update_customer_data_by_application,
                )
                customer = last_application.customer
                data = {}
                if application.fullname and customer.fullname != application.fullname:
                    data['fullname'] = application.fullname
                if application.mobile_phone_1 and customer.phone != application.mobile_phone_1:
                    data['phone'] = application.mobile_phone_1
                if application.email and customer.email != application.email:
                    data['email'] = application.email
                customer = update_customer_data_by_application(customer, last_application, data)

                return customer

    return True


def get_offer_recommendations(
        product_line_code, loan_amount_requested, loan_duration_requested, affordable_payment,
        payday, application_nik, application_id, partner=None):
    output = {
        'product_rate':{},
        'offers': [],
        'requested_offer': {}
    }
    today = timezone.localtime(timezone.now()).date()

    application = Application.objects.get(pk=application_id)
    product_line = ProductLine.objects.get(pk=product_line_code)

    # replace attr base on credit matrix
    credit_score = get_credit_score3(application)
    if not credit_score:
        logger.error({
            'action':'get_offer_recommendations',
            'status': 'can not find credit score',
            'data': 'application_id: %s' % application_id
            })
        raise JuloException('CreditCore is not found')

    customer = application.customer
    credit_matrix_type = CreditMatrixType.WEBAPP if application.is_web_app() else (
        CreditMatrixType.JULO if not customer.is_repeated else CreditMatrixType.JULO_REPEAT)
    score_product = get_score_product(credit_score, credit_matrix_type,
                                      product_line_code, application.job_type)
    if not score_product:
        logger.warn({
            'action':'get_offer_recommendations',
            'status': 'can not find score_product from credit score',
            'data': 'application_id: %s' % application_id
            })
        return output

    product_line.min_amount = score_product.min_loan_amount
    product_line.max_amount = score_product.max_loan_amount
    product_line.min_duration = score_product.min_duration
    product_line.max_duration = score_product.max_duration
    product_line.min_interest_rate = score_product.interest
    product_line.max_interest_rate = score_product.interest

    # update the minimum loan amount and duration for false reject experiment
    if check_fraud_model_exp(application.id) and product_line_code in ProductLineCodes.mtl():
        product_line.min_amount = FraudModelExperimentConst.MIN_AMOUNT
        product_line.max_amount = FraudModelExperimentConst.MAX_AMOUNT
        product_line.min_duration = FraudModelExperimentConst.MIN_DURATION
        product_line.max_duration = FraudModelExperimentConst.MAX_DURATION
        product_line.max_interest_rate = FraudModelExperimentConst.INTEREST_RATE_MONTHLY
        product_line.min_interest_rate = FraudModelExperimentConst.INTEREST_RATE_MONTHLY

    # Determine product lookup
    if product_line_code in ProductLineCodes.grab():
        try:
            partner_referral = PartnerReferral.objects.get(cust_nik=application_nik)
            product_lookup = partner_referral.product
        except Exception:
            raise JuloException('could not get recomendations due partner refferal not exist')
    elif product_line_code in ProductLineCodes.loc():
        product_lookup = ProductLookup.objects.filter(
            product_line_id=product_line_code).first()
    else:
        # try to use product_lookup field on credit_matrix
        product_lookup = score_product.get_product_lookup(product_line.max_interest_rate)

    # Calculate installment and payment date
    first_payment_date_requested = determine_first_due_dates_by_payday(
        payday, today, product_line_code, loan_duration_requested)

    if product_line_code in ProductLineCodes.grab():
        start_date = today + relativedelta(days=3)
        range_due_date = get_available_due_dates_weekday_daily(
            start_date, loan_duration_requested)
        today = range_due_date[0]
        first_payment_date_requested = range_due_date[-1]

    _, _, first_installment_requested = compute_adjusted_payment_installment(
        loan_amount_requested, loan_duration_requested, product_lookup.monthly_interest_rate,
        today, first_payment_date_requested)

    if product_line_code in ProductLineCodes.stl() + ProductLineCodes.grab():
        installment_requested = first_installment_requested
    else:
        _, _, installment_requested = compute_payment_installment(
            loan_amount_requested, loan_duration_requested, product_lookup.monthly_interest_rate)

    can_afford = installment_requested <= affordable_payment
    output['requested_offer'] = {
        'product': product_lookup.product_code,
        'loan_amount_offer': loan_amount_requested,
        'loan_duration_offer': loan_duration_requested,
        'installment_amount_offer': installment_requested,
        'first_installment_amount': first_installment_requested,
        'first_payment_date': first_payment_date_requested,
        'can_afford': can_afford
    }

    # Return also product rate

    output['product_rate'] = {
        'annual_interest_rate': product_lookup.interest_rate,
        'late_fee_rate': product_lookup.late_fee_pct,
        'origination_fee_rate': product_lookup.origination_fee_pct,
        'cashback_initial_rate': product_lookup.cashback_initial_pct,
        'cashback_payment_rate': product_lookup.cashback_payment_pct,
        'monthly_interest_rate': product_lookup.monthly_interest_rate,
    }

    # Give offer recommendations

    logger.info({
        'product_line_code': product_line_code,
        'loan_amount_requested': loan_amount_requested,
        'loan_duration_requested': loan_duration_requested,
        'affordable_payment': affordable_payment,
        'payday': payday,
        'can_afford': can_afford
    })
    last_application_xid = None
    date_now = timezone.now()
    setting = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.LOAN_GENERATION_CHUNKING_BY_100K,
        is_active=True, start_date__lte=date_now, end_date__gte=date_now
    )

    if setting:
        application_xid_str = str(application.application_xid)
        last_application_xid = int(application_xid_str[-1])

    if product_line_code in ProductLineCodes.stl():

        if setting and last_application_xid in setting.criteria['test_group_app_xid']:
            if not can_afford:
                product_line.amount_increment = LoanGenerationChunkingConstant.AMOUNT_INCREMENT

        offer_options = get_offer_options(
            product_line,
            loan_amount_requested,
            loan_duration_requested,
            product_lookup.monthly_interest_rate,
            affordable_payment)
        if offer_options:
            offer_option = offer_options[0]

            first_payment_date = determine_first_due_dates_by_payday(
                payday, today, product_line_code)

            _, _, first_installment = compute_adjusted_payment_installment(
                offer_option.loan_amount, offer_option.loan_duration,
                product_lookup.monthly_interest_rate,
                today, first_payment_date)

            output['offers'].append(
                {
                    'product': product_lookup.product_code,
                    'offer_number': 1,
                    'loan_amount_offer': offer_option.loan_amount,
                    'loan_duration_offer': offer_option.loan_duration,
                    'installment_amount_offer': first_installment,
                    'first_installment_amount': first_installment,
                    'first_payment_date': first_payment_date,
                    'is_accepted': False
                }
            )

        return output

    if product_line_code in ProductLineCodes.grab():

        offer_options = get_offer_options(
            product_line,
            loan_amount_requested,
            loan_duration_requested,
            product_lookup.monthly_interest_rate,
            affordable_payment)
        if offer_options:
            offer_option = offer_options[0]
            first_payment_date = range_due_date[0]
            last_payment_date = range_due_date[-1]

            _, _, first_installment = compute_adjusted_payment_installment(
                offer_option.loan_amount, offer_option.loan_duration,
                product_lookup.monthly_interest_rate,
                first_payment_date, last_payment_date)

            output['offers'].append(
                {
                    'product': product_lookup.product_code,
                    'offer_number': 1,
                    'loan_amount_offer': offer_option.loan_amount,
                    'loan_duration_offer': offer_option.loan_duration,
                    'installment_amount_offer': first_installment,
                    'first_installment_amount': first_installment,
                    'first_payment_date': first_payment_date,
                    'is_accepted': False
                }
            )

        return output

    if product_line_code in ProductLineCodes.mtl() + ProductLineCodes.bri():
        if setting and last_application_xid in setting.criteria['test_group_app_xid']:
            if not can_afford:
                product_line.amount_increment = LoanGenerationChunkingConstant.AMOUNT_INCREMENT

        offer_options = get_offer_options(
            product_line,
            loan_amount_requested,
            loan_duration_requested,
            product_lookup.monthly_interest_rate,
            affordable_payment)

        for offer_option in offer_options:
            first_payment_date = determine_first_due_dates_by_payday(
                payday, today, product_line_code, offer_option.loan_duration)
            principal_first, _, first_installment = compute_adjusted_payment_installment(
                offer_option.loan_amount, offer_option.loan_duration,
                product_lookup.monthly_interest_rate,
                today, first_payment_date)

            first_installment = check_eligible_for_campaign_referral(
                product_line_code, principal_first, first_installment,
                offer_option.loan_amount, application)

            output['offers'].append(
                {
                    'product': product_lookup.product_code,
                    'loan_amount_offer': offer_option.loan_amount,
                    'loan_duration_offer': offer_option.loan_duration,
                    'installment_amount_offer': offer_option.installment,
                    'first_installment_amount': first_installment,
                    'first_payment_date': first_payment_date,
                    'is_accepted': False
                }
            )

        for i, offer in enumerate(output['offers']):
            offer['offer_number'] = i + 1

        # only return the best offer options
        options_limit = 1
        if len(output['offers']) > options_limit:
            output['offers'] = output['offers'][:options_limit]

        return output


def update_offer(application, offers):
    if application.application_status.status_code >= ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        raise JuloException('could not update_offer')

    offers = json.loads(offers)
    for offer in offers:
        if 'id' in offer:
            offer_obj = Offer.objects.get(pk=offer['id'])
            product = ProductLookup.objects.get(pk=offer['product'])
            application_product_line = application.product_line
            first_payment_date = parse(offer['first_payment_date'], yearfirst=True) if offer[
                'first_payment_date'] else None
            with transaction.atomic():
                offer_obj.loan_amount_offer = int(offer['loan_amount_offer'].replace('.', ''))
                offer_obj.loan_duration_offer = offer['loan_duration_offer']
                offer_obj.installment_amount_offer = int(offer['installment_amount_offer'].replace('.', ''))
                offer_obj.product = product
                offer_obj.is_approved = True
                if offer['only_first_payment']:
                    offer_obj.special_first_payment_date = first_payment_date
                else:
                    offer_obj.first_payment_date = first_payment_date

                offer_obj.first_installment_amount = int(offer['first_installment_amount'].replace('.', ''))
                offer_obj.save()

                if application_product_line != product.product_line:
                    application.product_line = product.product_line
                    application.save()

            logger.info({
                'action': 'update_offer',
                'application_id': offer_obj.application.id,
                'offer_id': offer_obj.id
            })

        else:
            product = ProductLookup.objects.get(pk=offer['product'])
            application_product_line = application.product_line
            first_payment_date = parse(offer['first_payment_date'], yearfirst=True) if offer[
                'first_payment_date'] else None
            special_first_payment_date = None
            if offer['only_first_payment']:
                special_first_payment_date = first_payment_date
                first_payment_date = parse(
                    offer['init_first_payment_date'],
                    yearfirst=True) if offer['init_first_payment_date'] else None

            with transaction.atomic():
                offer_obj = Offer.objects.create(
                    application=application,
                    loan_amount_offer=int(offer['loan_amount_offer'].replace('.', '')),
                    loan_duration_offer=offer['loan_duration_offer'],
                    installment_amount_offer=int(offer['installment_amount_offer'].replace('.', '')),
                    offer_number=int(offer['offer_number']),
                    product=product,
                    is_accepted=False,
                    is_approved=True,
                    first_payment_date=first_payment_date,
                    special_first_payment_date=special_first_payment_date,
                    first_installment_amount=int(offer['first_installment_amount'].replace('.', ''))
                )

                if application_product_line != product.product_line:
                    application.product_line = product.product_line
                    application.save()

            logger.info({
                'action': 'create_offer',
                'application_id': application.id,
                'offer_id': offer_obj.id
            })

    logger.info({
        'status': 'success_save_offer',
        'application': application.id
    })

    return True


def disable_original_password(customer, temporary_password):
    original_password = OriginalPassword.objects.filter(user=customer.user).first()

    with transaction.atomic():
        if original_password is None:
            OriginalPassword.objects.create(
                original_password=customer.user.password,
                temporary_password=temporary_password,
                user_id=customer.user.id)
        else:
            original_password.temporary_password = temporary_password
            original_password.save()

        u = User.objects.get(id=customer.user.id)
        u.set_password(temporary_password)
        u.save()


def enable_original_password(customer):
    original_password = OriginalPassword.objects.filter(user=customer.user).first()
    if original_password is None:
        return
    with transaction.atomic():
        u = User.objects.get(id=customer.user.id)
        u.password = original_password.original_password
        u.save()
        original_password.delete()


class ApplicationHistoryUpdated(object):
    """
    Controlled execution that can be called using with statement
    to make sure application status change is captured
    """

    def __init__(self, application, change_reason='system_triggered', is_experiment=False):
        self.application = application
        self.change_reason = change_reason
        self.old_status_code = None
        self.status_change = None
        self.is_skip_workflow_action = is_experiment

    def __enter__(self):
        old_status_code = self.application.application_status.status_code
        logger.debug({
            'old_status_code': old_status_code
        })
        self.old_status_code = old_status_code
        return self

    def __exit__(self, exc_type, exc_value, traceback):

        if exc_value:
            logger.error({
                'application': self.application.pk,
                'old_status_code': self.old_status_code,
                'current_status' : self.application.status,
                'exc_type' : str(exc_type),
                'exc_value' : str(exc_value),
                'change_reason' : self.change_reason,
                'action' : 'exit from ApplicationHistoryUpdated'
            })
            return

        self.application = (
            Application.objects
            .select_related('account')
            .select_related('application_status')
            .select_related('customer')
            .select_related('customer__user')
            .select_related('name_bank_validation')
            .select_related('partner')
            .select_related('loan')
            .select_related('workflow')
            .select_related('product_line')
            .prefetch_related('account__accountlimit_set')
            .prefetch_related('account__accountproperty_set')
            .prefetch_related('devicescrapeddata_set')
            .prefetch_related('offer_set')
            .get(pk=self.application.id)
        )

        old_status_code = self.old_status_code
        new_status_code = self.application.application_status.status_code

        # We want to be able to reject application multiple times
        # To keep a log for different reasons of rejection
        reject_status_codes = [ApplicationStatusCodes.PRE_REJECTION,
                               ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                               ApplicationStatusCodes.APPLICATION_DENIED]
        if old_status_code == new_status_code and new_status_code not in reject_status_codes:
            # This block is to capture the first time application is created
            if not self.application.is_agent_assisted_submission():
                if old_status_code not in (
                    ApplicationStatusCodes.FORM_PARTIAL,
                    ApplicationStatusCodes.FORM_SUBMITTED,
                ):
                    logger.warn(
                        {
                            'status': 'application_status_not_changed',
                            'action': 'nothing',
                            'application': self.application.pk,
                            'old_status_code': old_status_code,
                            'new_status_code': new_status_code,
                        }
                    )
                    return
                old_status_code = ApplicationStatusCodes.NOT_YET_CREATED

        logger.info({
            'status': 'application_status_changed',
            'application': self.application.pk,
            'old_status_code': old_status_code,
            'new_status_code': new_status_code,
            'change_reason' : self.change_reason
        })
        status_change = ApplicationHistory.objects.create(
            application=self.application,
            status_old=old_status_code,
            status_new=new_status_code,
            change_reason=self.change_reason,
            is_skip_workflow_action=self.is_skip_workflow_action)
        self.status_change = status_change


def trigger_info_application_tokopedia(status_change):
    # init variable
    application = status_change.application
    partner_account_attribution = PartnerAccountAttribution.objects.filter(application=application).last()
    partner_referral = application.customer.partnerreferral_set.filter(pre_exist=False).order_by('id').last()
    # logger
    logger.info({
        'action': 'trigger_info_application_tokopedia',
        'application': application,
        'partner_account_attribution': partner_account_attribution,
        'partner_referral': partner_referral
    })
    # if application not have partner account attritbution
    julo_tokopedia_client = get_julo_tokopedia_client()
    if not partner_account_attribution:
        # run if status tokopedia approve
        if status_change.status_new not in julo_tokopedia_client.list_status_new_approved:
            return
        # skip and notif if application have partner but not have partner refferal
        if not partner_referral:
            notify_partner_account_attribution(application, partner_referral, 'TOKOPEDIA_partner_referral_not_found')
            return
        PartnerAccountAttribution.objects.create(
            customer=application.customer,
            partner=application.partner,
            partner_referral=None,
            application=application,
            partner_account_id=None
        )
        return
        # update application tokopedia status
    if partner_account_attribution.get_rules_is_blank() and not partner_account_attribution.partner_account_id:
        notify_partner_account_attribution(application, partner_account_attribution.partner_referral, 'partner_account_id_blank')
        return
    julo_tokopedia_client.update_application_status(status_change)


def trigger_info_application_partner(status_change):
    if not status_change or not status_change.application:
        return
    if not status_change.application.product_line_id:
        return
    if status_change.application.product_line_id in ProductLineCodes.bri():
        julo_bri_client = get_julo_bri_client()
        julo_bri_client.update_info_application(status_change)
    if status_change.application.partner_id:
        if status_change.application.partner.name == 'tokopedia':
            julo_tokopedia_client = get_julo_tokopedia_client()
            if status_change.status_new in julo_tokopedia_client.list_status_new:
                trigger_info_application_tokopedia(status_change)


def event_end_year(payment, new_status_code, old_status_code):
    allow_status_code = [310, 311]
    if old_status_code in allow_status_code and new_status_code == 330:
        start_date = date(2017, 12, 26)
        date_list = [start_date + timedelta(days=x) for x in range(0, 10)]
        if payment.due_date in date_list:
            rule_date = payment.due_date - timedelta(2)
            if payment.paid_date <= rule_date:
                get_julo_sms = get_julo_sms_client()
                application = payment.loan.application
                logger.info({
                    'action': 'sms_event_end_year',
                    'phone 1': application.mobile_phone_1,
                    'phone 2': application.mobile_phone_2
                })
                if application.mobile_phone_1:
                    _, api_response1 = get_julo_sms.sms_event_end_year(
                        application.mobile_phone_1)
                    if api_response1['status'] != '0':
                        raise SmsNotSent({
                            'send_status': api_response1['status'],
                            'payment_id': payment.id,
                        })
                if application.mobile_phone_2:
                    _, api_response2 = get_julo_sms.sms_event_end_year(
                        application.mobile_phone_2)
                    if api_response2['status'] != '0':
                        raise SmsNotSent({
                            'send_status': api_response2['status'],
                            'payment_id': payment.id,
                        })


def process_lender_deposit(partner, amount):
    if partner.type not in 'lender':
        raise JuloException({
            'action': 'lender_deposit',
            'partner': partner,
            'error': 'Partner not lender'
        })

    with transaction.atomic():
        lender_balance = LenderBalance.objects.select_for_update().filter(partner=partner).first()
        LenderBalanceEvent.objects.create(
            lender_balance=lender_balance,
            amount=amount,
            before_amount=lender_balance.available_balance,
            after_amount=lender_balance.available_balance + amount,
            type='deposit')

        lender_balance.total_deposit += amount
        lender_balance.available_balance += amount
        lender_balance.save()


def process_lender_withdraw(partner, amount):
    if partner.type not in 'lender':
        raise JuloException({
            'action': 'lender_deposit',
            'partner': partner,
            'error': 'Partner not lender'
        })
    with transaction.atomic():
        lender_balance = LenderBalance.objects.select_for_update().filter(partner=partner).first()
        if amount > lender_balance.available_balance:
            raise JuloException({
                'action': 'process_lender_withdraw',
                'available_balance': lender_balance.available_balance,
                'amount_withdraw': amount,
                'error': 'Balance insufficient'
            })
        LenderBalanceEvent.objects.create(
            lender_balance=lender_balance,
            amount=amount,
            before_amount=lender_balance.available_balance,
            after_amount=lender_balance.available_balance - amount,
            type='withdraw')

        lender_balance.total_withdrawal += amount
        lender_balance.available_balance -= amount
        lender_balance.save()


def record_bulk_disbursement_transaction(disbursement_summary):
    applications = Application.objects.filter(pk__in=disbursement_summary.transaction_ids)

    for application in applications:
        record_disbursement_transaction(application.loan)


def record_disbursement_transaction(loan):
    already_disbursement_trans = DisbursementTransaction.objects.filter(loan=loan).last()
    if already_disbursement_trans:
        return

    if not loan.application:
        return

    with transaction.atomic():
        lender_balance = LenderBalance.objects.select_for_update().filter(partner=loan.partner).first()
        if not lender_balance:
            raise JuloException({
                'action': 'record_loan_transaction',
                'partner_id': loan.partner_id,
                'error': 'Lender balance not found'
            })
        lender_disbursed = loan.loan_amount
        if lender_disbursed > lender_balance.available_balance:
            raise JuloException({
                'action': 'record_loan_transaction',
                'available_balance': lender_balance.available_balance,
                'amount_disburse': lender_disbursed,
                'error': 'Balance insufficient'
            })
        lender_service_rate = LenderServiceRate.objects.get_or_none(partner=loan.partner)
        if not lender_service_rate:
            raise JuloException({
                'action': 'record_loan_transaction',
                'partner_id': loan.partner_id,
                'error': 'Lender service rate not found'
            })
        lender_balance_after = lender_balance.available_balance - lender_disbursed
        total_provision_received = int(math.floor(lender_disbursed * loan.product.origination_fee_pct))
        borrower_received = lender_disbursed - total_provision_received
        lender_provision_received = int(math.floor(total_provision_received * lender_service_rate.provision_rate))
        julo_provision_received = total_provision_received - lender_provision_received
        DisbursementTransaction.objects.create(
            lender_disbursed=lender_disbursed,
            borrower_received=borrower_received,
            total_provision_received=total_provision_received,
            julo_provision_received=julo_provision_received,
            lender_provision_received=lender_provision_received,
            lender_balance_before=lender_balance.available_balance,
            lender_balance_after=lender_balance_after,
            partner=loan.partner,
            customer=loan.customer,
            loan=loan)
        lender_balance.available_balance = lender_balance_after
        lender_balance.total_disbursed_principal += lender_disbursed
        lender_balance.outstanding_principal += lender_disbursed
        lender_balance.save()


def record_payment_transaction(payment, borrower_paid_amount, due_amount_before, event_date,
                               repayment_source, payment_receipt=None, payment_method=None):
    ptp_update(payment.id, payment.ptp_date)
    # get calculation payment objects
    objects = payment.process_transaction(borrower_paid_amount)
    payment.save(update_fields=['paid_principal',
                                'paid_interest',
                                'paid_late_fee',
                                'udate'])

    loan = payment.loan
    disbursement_transaction = DisbursementTransaction.objects.filter(loan=loan).last()
    if not disbursement_transaction or not loan.partner:
        return
    with transaction.atomic():
        # set value
        lender_balance = LenderBalance.objects.select_for_update().filter(partner=loan.partner).first()
        if not lender_balance:
            raise JuloException({
                'action': 'record_payment_transaction',
                'partner_id': loan.partner_id,
                'error': 'Lender balance not found'
            })
        lender_service_rate = LenderServiceRate.objects.get_or_none(partner=loan.partner)
        if not lender_service_rate:
            raise JuloException({
                'action': 'record_payment_transaction',
                'partner_id': loan.partner_id,
                'error': 'Lender service rate not found'
            })
        borrower_repaid_principal = objects['principal']
        borrower_repaid_interest = objects['interest']
        borrower_repaid_late_fee = objects['late_fee']
        due_amount_after = due_amount_before - borrower_paid_amount
        lender_received_principal = int(math.floor(borrower_repaid_principal * lender_service_rate.principal_rate))
        julo_fee_received_principal = borrower_repaid_principal - lender_received_principal
        lender_received_interest = int(math.floor(borrower_repaid_interest * lender_service_rate.interest_rate))
        julo_fee_received_interest = borrower_repaid_interest - lender_received_interest
        lender_received_late_fee = int(math.floor(borrower_repaid_late_fee * lender_service_rate.late_fee_rate))
        julo_fee_received_late_fee = borrower_repaid_late_fee - lender_received_late_fee
        lender_received = lender_received_principal + lender_received_interest + lender_received_late_fee
        julo_fee_received = julo_fee_received_principal + julo_fee_received_interest + julo_fee_received_late_fee
        lender_balance_after = lender_balance.available_balance + lender_received
        RepaymentTransaction.objects.create(
            partner=loan.partner,
            customer=loan.application.customer,
            loan=loan,
            payment=payment,
            event_date=event_date,
            repayment_source=repayment_source,
            borrower_repaid=borrower_paid_amount,
            borrower_repaid_principal=borrower_repaid_principal,
            borrower_repaid_interest=borrower_repaid_interest,
            borrower_repaid_late_fee=borrower_repaid_late_fee,
            julo_fee_received=julo_fee_received,
            lender_received=lender_received,
            lender_received_principal=lender_received_principal,
            lender_received_interest=lender_received_interest,
            lender_received_late_fee=lender_received_late_fee,
            julo_fee_received_principal=julo_fee_received_principal,
            julo_fee_received_interest=julo_fee_received_interest,
            julo_fee_received_late_fee=julo_fee_received_late_fee,
            due_amount_before=due_amount_before,
            due_amount_after=due_amount_after,
            lender_balance_before=lender_balance.available_balance,
            lender_balance_after=lender_balance_after,
            payment_receipt=payment_receipt,
            payment_method=payment_method,
        )
        lender_balance.available_balance = lender_balance_after
        lender_balance.total_received += lender_received
        lender_balance.total_paidout += julo_fee_received
        lender_balance.total_received_principal += lender_received_principal
        lender_balance.total_paidout_principal += julo_fee_received_principal
        lender_balance.total_received_interest += lender_received_interest
        lender_balance.total_paidout_interest += julo_fee_received_interest
        lender_balance.total_received_late_fee += lender_received_late_fee
        lender_balance.total_paidout_late_fee += julo_fee_received_late_fee
        lender_balance.outstanding_principal -= borrower_repaid_principal
        lender_balance.save()


def experimentation(application, new_status_code):
    application_id = application.id
    old_status_code = application.status
    experiment_qs = Experiment.objects.get_queryset()
    experiments = (
        experiment_qs.active()
        .filter(status_old=old_status_code, status_new=new_status_code)
        .order_by('id')
        .cache()
    )
    experiment_applied = None
    returned_result = {'change_status': None, 'notes': [], 'is_experiment': False,
                       'experiment_id': None, 'code': None}
    for experiment in experiments:
        criteria = experiment.experimenttestgroup_set.all()
        for criterion in criteria:
            result = eval("experimentation_check_" + criterion.type.lower() + "_criteria")(criterion, application)
            if not result:
                break
        if result:
            experiment_applied = experiment
            break
    if experiment_applied:
        action_status = experiment_applied.experimentaction_set.filter(
            type=ExperimentAction.TYPELIST['CHANGE_STATUS']).first()
        action_notes = experiment_applied.experimentaction_set.filter(
            type=ExperimentAction.TYPELIST['ADD_NOTE'])

        allowed_path_statuses = get_application_allowed_path(old_status_code, application_id)
        if action_status and int(action_status.value) in allowed_path_statuses:
            returned_result['change_status'] = action_status.value
            returned_result['is_experiment'] = True
            returned_result['experiment_id'] = experiment_applied.id
            returned_result['code'] = experiment_applied.code
            if action_notes:
                notes = list([x.value for x in action_notes])
                returned_result['notes'] = notes

    logger.info({
        'is_experiment': returned_result['is_experiment'],
        'change_status': returned_result['change_status'],
        'experiment_id': returned_result['experiment_id'],
        'code': returned_result['code'],
        'notes': returned_result['notes']
    })

    return returned_result


def is_credit_experiment(application, probability_fpd):
    date_now = timezone.localtime(timezone.now()).date()
    experiment = Experiment.objects.filter(
        is_active=True, code=CreditExperiments.RABMINUS165,
        date_start__lte=date_now, date_end__gte=date_now
    ).first()
    result = False
    if experiment:
        # is application re apply
        previous_app_good_pay = False
        previous_app_status_check = True
        application_number = application.application_number
        application_number = application_number if application_number else 1
        if application_number >= 2:
            previous_success_app = application.customer.application_set.filter(
                application_status_id=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL).last()
            if previous_success_app:
                previous_app_good_pay = is_customer_paid_on_time(
                    application.customer, application_id=previous_success_app.id)
                # To check  prev application codes
                application_number_prev_success = previous_success_app.application_number
                application_number_prev = application_number - 1
                if application_number_prev_success != application_number_prev:
                    previous_apps = application.customer.application_set.filter(
                        application_number__gt=application_number_prev_success,
                        application_number__lte=application_number_prev)
                    for previous_app in previous_apps:
                        if previous_app.application_status_id in [ApplicationStatusCodes.APPLICATION_DENIED,
                                                           ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD]:
                            previous_app_status_check = False
                            break

        if previous_app_good_pay and previous_app_status_check:
            criteria = experiment.experimenttestgroup_set.all()
            for cri in criteria:
                result = experimentation_check_probability_fpd_met_criteria(cri, probability_fpd)
                if not result:
                    break
    return {
        "experiment": experiment if result else None,
        "is_experiment": result
    }


def experimentation_check_application_id_criteria(criterion, application):
    group_test = criterion.value.split(":")
    result = False
    if group_test[0] == "#nth":
        digit_index = int(group_test[1])
        digit_criteria = group_test[2].split(",")
        digit = str(application.id)[digit_index] if digit_index < 0 else str(application.id)[digit_index - 1]
        if digit in digit_criteria:
            result = True
    return result


def experimentation_check_application_xid_criteria(criterion, application):
    group_test = criterion.value.split(":")
    result = False
    if group_test[0] == "#nth":
        digit_index = int(group_test[1])
        digit_criteria = group_test[2].split(",")
        digit = str(application.application_xid)[digit_index] if digit_index < 0 else str(application.application_xid)[digit_index - 1]
        if digit in digit_criteria:
            result = True
    return result


def experimentation_check_product_criteria(criterion, application):
    product_line_criteria = criterion.value.lower().split(",")
    result = False
    if application.product_line:
        if application.product_line.product_line_type.lower() in product_line_criteria:
            result = True
    return result


def experimentation_check_credit_score_criteria(criterion, application):
    credit_score_criteria = criterion.value.upper().split(",")
    result = False
    credit_score = get_credit_score3(application)
    if credit_score.score.upper() in credit_score_criteria:
        result = True
    return result


def experimentation_check_reason_last_change_status_criteria(criterion, application):
    change_status_criteria = criterion.value.lower().split(",")
    change_status_criteria = [x.strip() for x in change_status_criteria]
    result = False
    if application.applicationhistory_set.last().change_reason.lower() in change_status_criteria:
        result = True
    return result


def experimentation_check_income_prediction_criteria(criterion, application):
    score_criteria = criterion.value.split("~")
    result = False
    income_prediction = PdIncomePredictModelResult.objects.filter(application_id=application.id).last()
    if income_prediction:
        if float(score_criteria[0]) <= income_prediction.value <= float(score_criteria[1]):
            result = True
    return result


def experimentation_check_income_trust_index_criteria(criterion, application):
    """
    The ITI score has no upper limit so the upper limit is ignored here
    """
    lower_limit_inclusive, _ = criterion.value.split("~")
    income_trust = PdIncomeTrustModelResult.objects.filter(
        application_id=application.id).last()
    if not income_trust:
        return False
    return income_trust.value >= float(lower_limit_inclusive)


def experimentation_check_expense_prediction_criteria(criterion, application):
    score_criteria = criterion.value.split("~")
    result = False
    expense_prediction = PdExpensePredictModelResult.objects.filter(application_id=application.id).last()
    if expense_prediction:
        if float(score_criteria[0]) <= expense_prediction.value <= float(score_criteria[1]):
            result = True
    return result


def experimentation_check_thin_file_criteria(criterion, application):
    score_criteria = criterion.value.split("~")
    result = False
    thin_file_score = PdThinFileModelResult.objects.filter(application_id=application.id).last()
    if thin_file_score:
        if float(score_criteria[0]) <= thin_file_score.probability_fpd <= float(score_criteria[1]):
            result = True
    return result


def experimentation_check_loan_count_criteria(criterion, application):
    customer = application.customer
    result = False
    group_test = criterion.value.split(":")
    if group_test[0] == "#eq":
        if (customer.loan_set.count() == int(group_test[1])):
            result = True
    elif group_test[0] == "#lte":
        if (customer.loan_set.count() <= int(group_test[1])):
            result = True
    elif group_test[0] == "#gte":
        if (customer.loan_set.count() >= int(group_test[1])):
            result = True
    elif group_test[0] == "#lt":
        if (customer.loan_set.count() < int(group_test[1])):
            result = True
    elif group_test[0] == "#gt":
        if (customer.loan_set.count() > int(group_test[1])):
            result = True
    return result


def experimentation_check_probability_fpd_met_criteria(criterion, probability_fpd):
    result = False
    group_test = criterion.value.split(":")
    if len(group_test) in [2]:
        if group_test[0] == "#rng":
            range_val = group_test[1].split(",")
            from_val = get_float_or_none(range_val[0])
            to_val = get_float_or_none(range_val[1])
            condition = "%s <= %s <= %s" % (from_val, probability_fpd, to_val)
            eval_res = eval_or_none(condition)
            if eval_res:
                result = True
    return result


def get_monthly_income_by_experiment_group(application, monthly_income=None):
    application_experiment = application.applicationexperiment_set.filter(
        experiment__code__in=ExperimentConst.ITI_FIRST_TIME_CUSTOMER).last()
    if application_experiment:
        pd_income = PdIncomePredictModelResult.objects.filter(application_id=application.id).last()
        if pd_income:
            return pd_income.value
    elif monthly_income:
        return monthly_income

    return application.monthly_income


def experimentation_automate_offer(application):
    app_data = get_data_application_checklist_collection(application)
    sum_undisclosed_expense = 0
    if 'total_current_debt' in app_data:
        for expense in app_data['total_current_debt']['undisclosed_expenses']:
            sum_undisclosed_expense += expense['amount']
    monthly_income = get_monthly_income_by_experiment_group(application)
    input_params = {
        'product_line_code': application.product_line.product_line_code,
        'job_start_date': application.job_start,
        'job_end_date': timezone.localtime(application.cdate).date(),
        'job_type': application.job_type,
        'monthly_income': monthly_income,
        'monthly_expense': application.monthly_expenses,
        'dependent_count': application.dependent,
        'undisclosed_expense': sum_undisclosed_expense,
        'monthly_housing_cost': application.monthly_housing_cost,
        'application_id': application.id,
        'application_xid': application.application_xid,
    }
    calculation_results = compute_affordable_payment(**input_params)

    recomendation_offers = get_offer_recommendations(
        application.product_line.product_line_code,
        application.loan_amount_request,
        application.loan_duration_request,
        calculation_results['affordable_payment'],
        application.payday,
        application.ktp,
        application.id,
        application.partner
    )

    if len(recomendation_offers['offers']) > 0:
        if application.offer_set.count() > 0:
            offer = application.offer_set.filter(offer_number=1).last()
        else:
            if len(recomendation_offers['offers']) > 0:
                offer_data = recomendation_offers['offers'][0]
                product = ProductLookup.objects.get(pk=offer_data['product'])
                offer_data['product'] = product
                offer_data['application'] = application
                offer_data['is_approved'] = True
                offer = Offer(**offer_data)
                offer.save()
        return True
    return False


def process_delete_late_fee(payment, customer, paid_amount, paid_date, use_wallet):
    if not payment.late_fee_applied > 0:
        return payment
    product_line_code = payment.loan.application.product_line_code
    product_line = ProductLineManager.get_or_none(product_line_code)
    if not product_line or not product_line.late_dates[0][0]:
        return payment

    # check late fee void
    late_fee_void_amount = 0
    late_fee_void_applied_index = []
    due_date = payment.due_date
    for index in range(payment.late_fee_applied):
        if product_line_code in ProductLineCodes.manual_process() + [ProductLineCodes.RABANDO]:
            late_fee_amount = payment.calculate_late_fee_productive_loan(product_line.product_line_code)
        else:
            late_fee_amount = payment.calculate_late_fee()
        days_late = product_line.late_dates[index][0]
        late_date = due_date + days_late
        if paid_date < late_date:
            if product_line_code in ProductLineCodes.stl() and index < 2:
                late_fee_amount = late_fee_amount - (old_div(late_fee_amount * 50, 100))
            late_fee_void_amount += late_fee_amount
            late_fee_void_applied_index.append(index)

    # implementation late_fee_void
    late_fee_void_amount = 0
    due_amount = payment.due_amount
    late_fee_void_applied_index.sort(reverse=True)
    for applied_index in late_fee_void_applied_index:
        if product_line_code in ProductLineCodes.manual_process() + [ProductLineCodes.RABANDO]:
            late_fee_amount = payment.calculate_late_fee_productive_loan(product_line.product_line_code)
        else:
            late_fee_amount = payment.calculate_late_fee()
        if product_line_code in ProductLineCodes.stl() and applied_index < 2:
            late_fee_amount = (late_fee_amount - (old_div(late_fee_amount * 50, 100)))

        due_amount -= late_fee_amount
        days_late = product_line.late_dates[applied_index][0]
        late_date = due_date + days_late
        exist_late_fee_event = PaymentEvent.objects.filter(
            event_type='late_fee',
            event_due_amount=due_amount,
            event_date__lte=late_date,
            can_reverse=True).order_by('event_date').last()
        if not exist_late_fee_event:
            return payment
        exist_late_fee_event.can_reverse = False
        exist_late_fee_event.save()
        PaymentEvent.objects.create(
            payment=payment,
            event_payment=late_fee_amount,
            event_due_amount=due_amount,
            event_date=late_date,
            event_type='late_fee_void',
            can_reverse=False)
    payment.due_amount = due_amount
    payment.late_fee_amount -= late_fee_void_amount
    payment.late_fee_applied -= len(late_fee_void_applied_index)
    payment.update_status_based_on_late_fee_applied()
    return payment


def process_change_due_date(payment, new_date_str, note, new_change_due_date_interest):
    with transaction.atomic():
        change_due_date_interest = new_change_due_date_interest
        payment_number = payment.payment_number
        status_not_due = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        today = date.today()
        payments = payment.loan.payment_set.filter(
            payment_number__gte=payment_number).order_by('payment_number')
        new_date = datetime.strptime(new_date_str, "%d-%m-%Y")
        loan = payment.loan
        new_due_amount = payment.due_amount + change_due_date_interest
        current_payment_id = payment.id
        for payment in payments:
            notes = ('[Change Due Date]\n' +
                     'Original due amount : %s, \n' +
                     'New due amount : %s, \n' +
                     'Original due date : %s, \n' +
                     'New due date : %s, \n' +
                     'Reason : %s') % (display_rupiah(payment.due_amount),
                                       display_rupiah(new_due_amount),
                                       payment.due_date.strftime("%d-%m-%Y"),
                                       new_date.strftime("%d-%m-%Y"),
                                       note)

            payment.due_amount += change_due_date_interest
            payment.change_due_date_interest = change_due_date_interest
            payment.due_date = new_date
            payment.late_fee_amount = 0
            payment.late_fee_applied = 0
            payment.payment_status = status_not_due
            payment.save(update_fields=['due_amount',
                                        'change_due_date_interest',
                                        'due_date',
                                        'late_fee_amount',
                                        'late_fee_applied',
                                        'payment_status',
                                        'udate'])
            PaymentEvent.objects.create(payment=payment,
                                        event_payment=-payment.change_due_date_interest,
                                        event_due_amount=payment.due_amount,
                                        event_date=today,
                                        event_type='due_date_adjustment')
            PaymentNote.objects.create(note_text=notes, payment=payment)
            new_date += relativedelta(months=1)

        loan.update_status()
        loan.save()
        app_note = ('[Change Due Date]\n' +
                    'Installment Delay to %s\n' +
                    'Delay fee %s\n' +
                    'Reason %s') % (new_date.strftime("%d-%m-%Y"),
                                    str(display_rupiah(change_due_date_interest)),
                                    note)
        ApplicationNote.objects.create(
            note_text=app_note, application_id=loan.application.id, application_history_id=None
        )


def upload_payment_details_to_centerix(current_payment_id):
    payment_query = Payment.objects.select_related(
        'loan', 'loan__application', 'loan__application__partner'
    ).exclude(
        loan__application__partner__name__in=PartnerConstant.form_partner()
    ).normal().filter(id=current_payment_id)
    date = timezone.localtime(timezone.now()).date()
    for payment in payment_query:
        diff = payment.due_date - date
        diff_day = diff.days
        if diff_day in  [0, 1]:
            if diff_day == 0:
                day = 'T0'
            elif diff_day == 1:
                day = 'T-'+str(diff_day)
            response = upload_payment_details(payment_query, 'JULO_'+str(day))
            print(response)


def reset_lender_disburse_counter():
    lender_disburse_counter_list = LenderDisburseCounter.objects.filter(
        rounded_count__gt=1)

    if not lender_disburse_counter_list:
        return True

    try:
        with transaction.atomic():
            for lender_disburse_counter in lender_disburse_counter_list:
                lender_disburse_counter.rounded_count = 1
                lender_disburse_counter.save()
            return True

    except Exception as e:
        raise Exception(e)


def get_adress_from_geolocation(application):
    if application.addressgeolocation:
        latitude = application.addressgeolocation.latitude
        longitude = application.addressgeolocation.longitude
        try:
            location = get_geolocator().reverse('%s, %s' % (latitude, longitude))
        except GeopyError as gu:
            logger.error({
                'status': str(gu),
                'service': 'google_maps',
                'error_type': str(type(gu))
            })
            return None

        address = location.address.lower().split(',')
        cleaned_address = [address_item.strip(' ') for address_item in address]

        return cleaned_address

    cleaned_address = [application.address_street_num.lower(),
                       application.address_kelurahan.lower(),
                       application.address_kecamatan.lower(),
                       application.address_kabupaten.lower(),
                       application.address_provinsi.lower(),
                       application.address_kodepos.lower()]

    return cleaned_address


def assign_lender_to_disburse(application, lender_id=None):
    today_date = date.today()
    customer = application.customer
    customer_age = 0
    if customer.dob:
        customer_age = today_date.year - customer.dob.year
        if today_date.month == customer.dob.month:
            if today_date.day < customer.dob.day:
                customer_age -= 1
        elif today_date.month < customer.dob.month:
            customer_age -= 1

    lender_exclusive_by_product = PartnerConstant.lender_exclusive_by_product()
    loan = application.loan
    loan_amount = loan.loan_amount
    loan_duration = loan.loan_duration
    monthly_income = application.monthly_income

    try:
        credit_score = [application.creditscore.score]
    except ObjectDoesNotExist:
        credit_score = []

    loan_purpose = [application.loan_purpose]
    company_name = application.company_name
    job_type = [application.job_type]
    job_industry = [application.job_industry]
    job_description = [application.job_description]
    product_profile = application.product_line.product_profile
    offer = application.offer_set.filter(is_accepted=True).first()
    product = offer.product

    lender_balance_list = LenderBalanceCurrent.objects.filter(
        lender__lender_status='active').exclude(
        lender__lender_name__in=lender_exclusive_by_product).exclude(
        lender__id=lender_id)

    if not lender_balance_list:
        raise JuloException({
            'action': 'assigned_lender to disburse',
            'message': 'no lender has enough available balance for this loan!!',
            'loan_id': loan.id
        })

    lender_balance_filter = LenderProductCriteria.objects.filter(
        lender_id__in=[lender_balance.lender.id for lender_balance in lender_balance_list])

    lender_product_list = lender_balance_filter.filter(
        # lender product criteria filter
        Q(product_profile_list__contains=[product_profile.id]) & \
        # lender customer filter
        (Q(lender__lendercustomercriteria__credit_score__isnull=True) | \
            Q(lender__lendercustomercriteria__credit_score=[]) | \
            Q(lender__lendercustomercriteria__credit_score__contains=credit_score)) &\
        (Q(lender__lendercustomercriteria__company_name__isnull=True) | \
            Q(lender__lendercustomercriteria__company_name=[]) | \
            Q(lender__lendercustomercriteria__company_name__icontains=company_name)) &\
        (Q(lender__lendercustomercriteria__loan_purpose__isnull=True) | \
            Q(lender__lendercustomercriteria__loan_purpose=[]) | \
            Q(lender__lendercustomercriteria__loan_purpose__contains=loan_purpose)) &\
        (Q(lender__lendercustomercriteria__min_age__isnull=True) | \
            Q(lender__lendercustomercriteria__min_age__lte=customer_age)) &\
        (Q(lender__lendercustomercriteria__max_age__isnull=True) | \
            Q(lender__lendercustomercriteria__max_age__gte=customer_age)) &\
        (Q(lender__lendercustomercriteria__job_type__isnull=True) | \
            Q(lender__lendercustomercriteria__job_type=[]) | \
            Q(lender__lendercustomercriteria__job_type__contains=job_type)) &\
        (Q(lender__lendercustomercriteria__job_industry__isnull=True) | \
            Q(lender__lendercustomercriteria__job_industry=[]) | \
            Q(lender__lendercustomercriteria__job_industry__contains=job_industry))
    )

    matched_lender_product = lender_product_list.order_by(
        'lender__lenderdisbursecounter__rounded_count',
        'lender__lenderdisbursecounter__cdate').first()

    if not matched_lender_product:
        default_lender_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
            category="followthemoney",
            is_active=True).first()

        if default_lender_setting and default_lender_setting.parameters['lender_name']:
            lender_name = default_lender_setting.parameters['lender_name']
            assigned_lender = LenderCurrent.objects.get_or_none(lender_name=lender_name)

    else:
        assigned_lender = matched_lender_product.lender

    if assigned_lender:
        update_lender_disbursement_counter(assigned_lender)

    return assigned_lender


def update_lender_disbursement_counter(lender, is_increment=True):
    lender_disburse_counter = LenderDisburseCounter.objects.filter(lender=lender).first()
    if is_increment:
        lender_disburse_counter.actual_count += 1
        lender_disburse_counter.rounded_count += 1
    else:
        lender_disburse_counter.actual_count -= 1
        lender_disburse_counter.rounded_count -= 1
    lender_disburse_counter.save()


def process_sepulsa_reduction_wallet_customer(customer, product, sepulsa_transaction):
    customer.change_wallet_balance(
        change_accruing=-product.customer_price,
        change_available=-product.customer_price,
        reason='sepulsa_purchase',
        sepulsa_transaction=sepulsa_transaction)


def process_sepulsa_addition_wallet_customer(customer, product, sepulsa_transaction):
    customer.change_wallet_balance(
        change_accruing=product.customer_price,
        change_available=product.customer_price,
        reason='sepulsa_refund',
        sepulsa_transaction=sepulsa_transaction)


def action_cashback_sepulsa_transaction(transaction_type, sepulsa_transaction):
    from juloserver.loan.services.lender_related import (
        julo_one_loan_disbursement_failed,
        julo_one_loan_disbursement_success,
    )

    loan = sepulsa_transaction.loan
    if transaction_type == 'create_transaction':
        if sepulsa_transaction.transaction_status != 'failed':
            process_sepulsa_reduction_wallet_customer(
                sepulsa_transaction.customer,
                sepulsa_transaction.product,
                sepulsa_transaction)
    elif transaction_type in ['update_transaction_via_callback', 'update_transaction_via_task']:
        if sepulsa_transaction.transaction_status != 'success':
            if loan:
                force_failed = sepulsa_transaction.retry_times >= \
                    DisbursementAutoRetryConstant.PPOB_MAX_RETRIES
                julo_one_loan_disbursement_failed(loan, force_failed=force_failed)
            else:
                process_sepulsa_addition_wallet_customer(
                    sepulsa_transaction.customer,
                    sepulsa_transaction.product,
                    sepulsa_transaction)
        elif sepulsa_transaction.transaction_status == 'success' and loan:
            julo_one_loan_disbursement_success(loan)
    is_cashback = False if loan else True
    if sepulsa_transaction.transaction_status == 'failed' \
            and loan and loan.loan_status_id == LoanStatusCodes.FUND_DISBURSAL_FAILED:
        return
    if sepulsa_transaction.transaction_status != 'pending':
        pn_client = get_julo_pn_client()
        pn_client.infrom_cashback_sepulsa_transaction(
            sepulsa_transaction.customer,
            sepulsa_transaction.transaction_status,
            is_cashback)


def process_sepulsa_transaction_failed(sepulsa_transaction):
    sepulsa_transaction.transaction_status = 'failed'
    sepulsa_transaction.is_order_created = True
    sepulsa_transaction.save()


def create_payment_method_loc(loc):
    """
         payment method for LOC
    """
    payment_methods = PaymentMethodManager.get_faspay_bank_list('bank')
    alfamart = PaymentMethodManager.get_or_none(PaymentMethodCodes.ALFAMART)
    payment_methods.append(alfamart)
    va_suffix = VirtualAccountSuffix.objects.filter(
        loan=None, line_of_credit=None).first()

    if va_suffix is None:
        logger.error({
            'customer': loc.customer.id,
            'line_of_credit': loc.id,
            'status': 'no_more_va_suffix'
        })
        raise JuloException('Ran out of VA suffix for faspay')

    for payment_method in payment_methods:
        is_shown = False

        if payment_method.code in [BankCodes.MAYBANK, PaymentMethodCodes.ALFAMART]:
            is_shown = True

        virtual_account = "".join([
            payment_method.faspay_payment_code,
            va_suffix.virtual_account_suffix
        ])
        logger.info({
            'action': 'assigning_new_va',
            'bank_code': payment_method.code,
            'va': virtual_account,
            'line_of_credit': loc.id,
            'type': payment_method.type
        })
        bank_code = ''
        if payment_method.type == 'bank':
            bank_code = payment_method.code

        PaymentMethod.objects.create(
            payment_method_code=payment_method.faspay_payment_code,
            payment_method_name=payment_method.name,
            bank_code=bank_code,
            line_of_credit=loc,
            virtual_account=virtual_account,
            is_shown=is_shown
        )

    va_suffix.line_of_credit = loc
    va_suffix.save()


def faspay_payment_inquiry_loan(loan, payment_method):
    """
    """
    payment = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    ).exclude(is_restructured=True).order_by('payment_number').first()
    if payment is None:
        data = {
            'response': 'Payment Notification',
            'response_code': '01',
            'response_desc': 'Payment not found'
        }
        return data

    due_amount = payment.due_amount
    virtual_account = int(payment_method.virtual_account)
    customer_name = loan.application.fullname
    data = {
        'response': 'VA Static Response',
        'va_number': virtual_account,
        'amount': due_amount,
        'cust_name': customer_name,
        'response_code': '00'
    }
    return data


def faspay_snap_payment_inquiry_loan(
    loan: Loan, 
    payment_method: PaymentMethod,
    faspay_bill: dict
) -> Tuple[dict, int]:
    """
    Get inquiry faspay snap loan
    """
    payment = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    ).exclude(is_restructured=True).order_by('payment_number').first()
    if payment is None:
        faspay_bill['responseCode'] = FaspaySnapInquiryResponseCodeAndMessage.\
                    TRANSACTION_NOT_FOUND.code
        faspay_bill['responseMessage'] = FaspaySnapInquiryResponseCodeAndMessage. \
            TRANSACTION_NOT_FOUND.message
        return faspay_bill, 0
    
    due_amount = payment.due_amount
    application = (
        loan.application
        if loan.application
        else Application.objects.get_or_none(pk=loan.application_id2)
    )
    if not application:
        faspay_bill[
            'responseCode'
        ] = FaspaySnapInquiryResponseCodeAndMessage.BILL_OR_VA_OR_CUSTOMER_INVALID.code
        faspay_bill[
            'responseMessage'
        ] = FaspaySnapInquiryResponseCodeAndMessage.BILL_OR_VA_OR_CUSTOMER_INVALID.message
        return faspay_bill, 0

    phone_number = get_application_primary_phone(application)

    faspay_bill['virtualAccountData']['virtualAccountName'] = application.fullname
    faspay_bill['virtualAccountData']['virtualAccountEmail'] = application.email
    faspay_bill['virtualAccountData']['virtualAccountPhone'] = add_plus_62_mobile_phone(
        phone_number
    )
    faspay_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(due_amount, '00')
    return faspay_bill, due_amount


def faspay_payment_inquiry_loc(loc, payment_method):
    from juloserver.line_of_credit.services import LineOfCreditStatementService

    last_statement = LineOfCreditStatementService().get_last_statement(loc.id)
    customer_name = loc.customer.fullname
    virtual_account = int(payment_method.virtual_account)
    amount = 0

    if last_statement:
        amount = last_statement.minimum_payment

    data = {
        'response': 'VA Static Response',
        'va_number': virtual_account,
        'amount': amount,
        'cust_name': customer_name,
        'response_code': '00'
    }

    return data


def faspay_snap_payment_inquiry_loc(
    loc: LineOfCredit, 
    payment_method: PaymentMethod,
    faspay_bill: dict,
) -> Tuple[dict, int]:
    from ..line_of_credit.services import LineOfCreditStatementService

    last_statement = LineOfCreditStatementService().get_last_statement(loc.id)
    customer = loc.customer
    amount = 0

    if last_statement:
        amount = last_statement.minimum_payment

    faspay_bill['virtualAccountData']['virtualAccountName'] = customer.fullname
    faspay_bill['virtualAccountData']['virtualAccountEmail'] = customer.email
    faspay_bill['virtualAccountData']['virtualAccountPhone'] = add_plus_62_mobile_phone(
        customer.phone
    )
    faspay_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(amount, '00')

    return faspay_bill, amount


def get_oldest_payment_due(loan):
    payment = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    ).exclude(is_restructured=True).order_by('payment_number').first()
    if payment is None:
        return None

    return payment


def get_next_unpaid_loan(customer):
    loan = customer.loan_set.filter(
        loan_status_id__gte=LoanStatusCodes.CURRENT,
        loan_status_id__lte=LoanStatusCodes.RENEGOTIATED
    ).first()

    return loan


def get_last_statement(loc):
    from ..line_of_credit.services import LineOfCreditStatementService
    last_statement = LineOfCreditStatementService().get_last_statement(loc.id)
    amount = 0
    if last_statement:
        amount = last_statement.minimum_payment

    data = {
        'amount': amount,
        'last_statement': last_statement
    }
    return data


def faspay_payment_process_loan(loan, payment_method, faspay, data, note):
    from juloserver.julo.services2.payment_event import (
        check_eligibility_of_waiver_early_payoff_campaign_promo,
    )
    from juloserver.paylater.services import process_payment_for_bl_statement

    payment_date = datetime.strptime(data['payment_date'], '%Y-%m-%d %H:%M:%S')
    old_status = faspay.status_code
    payment_transaction = None
    # Since we need to accomodate Paylater, a change is needed to identify is it loan or statement

    covid_loan_refinancing_request = None
    if loan.__class__ is Loan:
        payment_transaction = loan.payment_set.filter(
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)\
            .exclude(is_restructured=True)\
            .order_by('payment_number')\
            .first()
        if not payment_transaction:
            return False
        payment_transaction.refresh_from_db()
        # update payment in payback_transaction
        faspay.payment = payment_transaction
        covid_loan_refinancing_request = get_activated_covid_loan_refinancing_request(loan)
    elif loan.__class__ is Statement:
        payment_transaction = loan

    paid_amount = faspay.amount
    if covid_loan_refinancing_request and \
            check_eligibility_of_covid_loan_refinancing(covid_loan_refinancing_request, payment_date.date(),
                                                        paid_amount):

        paid_amount = process_partial_paid_loan_refinancing(
            covid_loan_refinancing_request,
            payment_transaction,
            paid_amount
        )

    with transaction.atomic():
        process_payment = None
        faspay = PaybackTransaction.objects.select_for_update().get(pk=faspay.id)
        if faspay.is_processed:
            return False
        if payment_transaction.__class__ is Payment:
            process_payment_func = process_partial_payment
        elif payment_transaction.__class__ is Statement:
            process_payment_func = process_payment_for_bl_statement

        # waive process if exist
        if payment_transaction.__class__ is Payment:
            process_waiver_before_payment(payment_transaction, faspay.amount, payment_date.date())

        process_payment = process_payment_func(
                payment_transaction, paid_amount, note, paid_date=payment_date.date(),
                payment_receipt=data['trx_id'],
                payment_method=payment_method)
        faspay.status_code = data['payment_status_code']
        faspay.status_desc = data['payment_status_desc']
        faspay.transaction_date = data['payment_date']
        faspay.is_processed = True
        faspay.save()
        create_pbt_status_history(faspay, old_status, faspay.status_code)

        if payment_transaction.__class__ is Payment:
            check_eligibility_of_waiver_early_payoff_campaign_promo(payment_transaction.loan.id)
    if not process_payment:
        return False

    return True


def faspay_payment_process_loc(loc, faspay, data, note):
    from ..line_of_credit.services import LineOfCreditTransactionService

    amount = faspay.amount
    transaction_date = datetime.strptime(data['payment_date'], '%Y-%m-%d %H:%M:%S')

    with transaction.atomic():
        process_payment = LineOfCreditTransactionService().add_payment(
            loc.id,
            amount,
            LocTransConst.CHANNEL_FASPAY,
            transaction_date,
            note)
        faspay.status_code = data['payment_status_code']
        faspay.status_desc = data['payment_status_desc']
        faspay.transaction_date = data['payment_date']
        faspay.is_processed = True
        faspay.save()

    if not process_payment:
        return False

    return True


def send_email_payment_reminder_grab(payment):
    payment_reminder_status = [PaymentStatusCodes.PAID_ON_TIME,
                               PaymentStatusCodes.PAYMENT_DUE_TODAY,
                               PaymentStatusCodes.PAYMENT_1DPD,
                               PaymentStatusCodes.PAYMENT_5DPD,
                               PaymentStatusCodes.PAYMENT_30DPD,
                               PaymentStatusCodes.PAYMENT_60DPD,
                               PaymentStatusCodes.PAYMENT_90DPD,
                               PaymentStatusCodes.PAYMENT_120DPD,
                               PaymentStatusCodes.PAYMENT_150DPD,
                               PaymentStatusCodes.PAYMENT_180DPD]
    payment_status = payment.payment_status.status_code
    if payment_status not in payment_reminder_status:
        return

    template = EmailTemplateConst.REMINDER_DPD_GRAB
    if payment_status == PaymentStatusCodes.PAYMENT_DUE_TODAY:
        template = EmailTemplateConst.REMINDER_GRAB_DUE_TODAY
    if payment_status == PaymentStatusCodes.PAID_ON_TIME:
        template = EmailTemplateConst.NOTIF_GRAB_330

    email_client = get_julo_email_client()
    status, headers, subject, content = email_client.email_reminder_grab(payment,
                                                                         template)
    if status == 202:
        application = payment.loan.application
        customer = application.customer
        to_email = application.email
        message_id = headers['X-Message-Id']

        EmailHistory.objects.create(
            payment=payment,
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=to_email,
            subject=subject,
            message_content=content,
            template_code=template
        )
        logger.info({
            'action': 'send_email_payment_reminder_grab',
            'status': status,
            'payment_id': payment.id,
            'message_id': message_id,
            'to_email': to_email
        })

    else:
        logger.warn({
            'action': 'send_email_payment_reminder_grab',
            'status': status,
            'payment_id': payment.id,
        })


def send_email_paid_off_grab(loan):
    if loan.loan_status.status_code != LoanStatusCodes.PAID_OFF:
        return

    application = loan.application
    to_email = application.email
    template = EmailTemplateConst.NOTIF_GRAB_250
    email_client = get_julo_email_client()
    status, headers, subject, content = email_client.email_paid_off_grab(to_email,
                                                                         template)
    if status == 202:
        customer = application.customer
        message_id = headers['X-Message-Id']

        EmailHistory.objects.create(
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=to_email,
            subject=subject,
            message_content=content,
            template_code=template
        )
        logger.info({
            'action': 'send_email_paid_off_grab',
            'status': status,
            'loan_id': loan.id,
            'message_id': message_id,
            'to_email': to_email
        })

    else:
        logger.warn({
            'action': 'send_email_paid_off_grab',
            'status': status,
            'loan_id': loan.id,
        })


def reverse_repayment_transaction(repayment, repayment_source):
    with transaction.atomic():
        lender_balance = LenderBalance.objects.select_for_update().filter(partner=repayment.partner).first()
        payment_transaction = RepaymentTransaction.objects.create(
            partner=repayment.partner,
            customer=repayment.customer,
            loan=repayment.loan,
            payment=repayment.payment,
            event_date=date.today(),
            repayment_source=repayment_source,
            borrower_repaid=repayment.borrower_repaid * -1,
            borrower_repaid_principal=repayment.borrower_repaid_principal * -1,
            borrower_repaid_interest=repayment.borrower_repaid_interest * -1,
            borrower_repaid_late_fee=repayment.borrower_repaid_late_fee * -1,
            julo_fee_received=repayment.julo_fee_received * -1,
            lender_received=repayment.lender_received * -1,
            lender_received_principal=repayment.lender_received_principal * -1,
            lender_received_interest=repayment.lender_received_interest * -1,
            lender_received_late_fee=repayment.lender_received_late_fee * -1,
            julo_fee_received_principal=repayment.julo_fee_received_principal * -1,
            julo_fee_received_interest=repayment.julo_fee_received_interest * -1,
            julo_fee_received_late_fee=repayment.julo_fee_received_late_fee * -1,
            due_amount_before=repayment.due_amount_before * -1,
            due_amount_after=repayment.due_amount_after * -1,
            lender_balance_before=lender_balance.available_balance,
            lender_balance_after=lender_balance.available_balance - repayment.lender_received,
            payment_receipt=repayment.payment_receipt,
            payment_method=repayment.payment_method)
        lender_balance.available_balance -= repayment.lender_received
        lender_balance.total_received -= repayment.lender_received
        lender_balance.total_paidout -= repayment.julo_fee_received
        lender_balance.total_received_principal -= repayment.lender_received_principal
        lender_balance.total_paidout_principal -= repayment.julo_fee_received_principal
        lender_balance.total_received_interest -= repayment.lender_received_interest
        lender_balance.total_paidout_interest -= repayment.julo_fee_received_interest
        lender_balance.total_received_late_fee -= repayment.lender_received_late_fee
        lender_balance.total_paidout_late_fee -= repayment.julo_fee_received_late_fee
        lender_balance.outstanding_principal += repayment.borrower_repaid_principal
        lender_balance.save()


def process_promo_asian_games(payment, customer):
    # check product
    application = payment.loan.application
    if application and not application.product_line.product_line_code in ProductLineCodes.mtl():
        return
    # check rule pay 2 days early
    rule_date = payment.due_date - timedelta(days=2)
    if payment.paid_date > rule_date:
        return
    # check rule paid on promo duration
    start_date_promo = date(2018, 8, 16)
    end_date_promo = date(2018, 9, 2)
    if payment.paid_date < start_date_promo or payment.paid_date > end_date_promo:
        return
    if payment.due_date < (start_date_promo + timedelta(days=2)) or\
       payment.due_date > (end_date_promo + timedelta(days=2)):
        return
    # create cashback
    promo_amount = 20000
    customer.change_wallet_balance(change_accruing=promo_amount,
                                   change_available=promo_amount,
                                   reason='promo_asian_games',
                                   payment=payment)
    # notifications get cashback
    pn_client = get_julo_pn_client()
    pn_client.inform_get_cashback_promo_asian_games(customer)


def autodialer_next_turn(application_status):
    # delay in hour
    delay = {
        '122': 3,
        '124': 2,
        '138': 3,
        '140': 1,
        '141': 2,
        '160': 1,
        '180': None,
        'fu': 12,
        'colT0': 5,
        '172': 1
    }
    feature_autodialer_delay = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODIALER_SESSION_DELAY,
        category='autodialer',
        is_active=True).values('parameters').last()
    if feature_autodialer_delay:
        delay = feature_autodialer_delay['parameters']
    today = timezone.localtime(timezone.now())
    next_turn = None
    if delay.get(str(application_status)):
        total_hours = delay[str(application_status)]
        total_minutes = 0
        total_days = 0
        next_turn = today + timedelta(
            days=total_days,
            hours=total_hours,
            minutes=total_minutes
        )
    return next_turn


def get_sphp_template(application_id, use_default_template=True):
    application = Application.objects.get_or_none(pk=application_id)
    template_obj = None
    template = ''

    if not application:
        return None

    if not use_default_template:
        template_obj = SphpTemplate.objects.filter(
            product_name=application.product_line.product_line_type).get()
        template_obj = Template(template_obj.sphp_template)

    loan = application.loan
    lender = loan.lender
    pks_number = '1.JTF.201707'
    if lender and lender.pks_number:
        pks_number = lender.pks_number
    sphp_date = timezone.now().date()
    context = {
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'agreement_letter_number': pks_number
    }

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(virtual_account=loan.julo_bank_account_number).first()
        if payment_method:
            context['julo_bank_code'] = payment_method.bank_code

    if application.product_line.product_line_code in ProductLineCodes.stl():
        first_payment = loan.payment_set.all().order_by('id').first()
        context['installment_amount'] = display_rupiah(loan.installment_amount)
        context['min_due_date'] = format_date(first_payment.due_date, 'd MMMM yyyy', locale='id_ID')
        context['first_late_fee_amount'] = display_rupiah(50000)
        if use_default_template:
            template = render_to_string('stl_sphp_document.html', context=context)
        else:
            context_obj = Context(context)
            template = template_obj.render(context_obj)
    elif application.product_line.product_line_code in ProductLineCodes.mtl():
        payments = loan.payment_set.all().order_by('id')
        for payment in payments:
            payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
            payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
        context['payments'] = payments
        context['max_total_late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
        context['provision_fee_amount'] = display_rupiah(loan.provision_fee())
        context['interest_rate'] = '{}%'.format(loan.interest_percent_monthly())
        if use_default_template:
            template = render_to_string('mtl_sphp_document.html', context=context)
        else:
            context_obj = Context(context)
            template = template_obj.render(context_obj)

    return template


def get_lender_sphp(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    template_obj = None
    template = ''

    if not application:
        return None

    loan = application.loan
    sphp_date = timezone.now().date()
    first_payment = loan.payment_set.all().order_by('id').first()

    lender = loan.lender
    lender_name = ""
    company_name = ""
    lender_address = ""
    agreement_letter_number = ""

    if lender:
        lender_name = lender.lender_name
        company_name = lender.lender_name
        lender_address = lender.lender_address
        agreement_letter_number = lender.pks_number

    context = {
        'lender_name': lender_name,
        'company_name': company_name,
        'lender_address': lender_address,
        'agreement_letter_number': agreement_letter_number,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'application_xid': application.application_xid,
        'loan_amount': display_rupiah(loan.loan_amount),
        'provision_fee_amount': display_rupiah(loan.provision_fee()),
        'interest_rate': '{}%'.format(loan.interest_percent_monthly()),
        'installment_amount': display_rupiah(loan.installment_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'cycle_day': loan.cycle_day,
        'duration_month': loan.loan_duration,
        'due_date_1': format_date(first_payment.due_date, 'd MMMM yyyy', locale='id_ID'),
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
    }

    template = render_to_string('lender_sphp.html', context=context)
    return template


def create_loan_and_payments_laku6(offer):
    """
    Internal function to create loan and payments. Should not be called
    as an action
    """

    with transaction.atomic():
        application = offer.application
        # productline_code = offer.application.product_line.product_line_code
        today_date = timezone.localtime(timezone.now()).date()
        first_payment_date = offer.first_payment_date

        principal_first, interest_first, installment_first = compute_laku6_adjusted_payment_installment(
            application.loan_amount_request, offer.loan_amount_offer, offer.loan_duration_offer,
            offer.interest_rate_monthly, today_date, first_payment_date)

        principal_rest, interest_rest, installment_rest = compute_laku6_payment_installment(
            application.loan_amount_request, offer.loan_amount_offer, offer.loan_duration_offer,
            offer.interest_rate_monthly)

        loan = Loan.objects.create(
            customer=offer.application.customer,
            application=offer.application,
            offer=offer,
            loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
            product=offer.product,
            loan_amount=offer.loan_amount_offer,
            loan_duration=offer.loan_duration_offer,
            first_installment_amount=installment_first,
            installment_amount=installment_rest)

        loan.cycle_day = offer.first_payment_date.day

        # erase erafone_fee and insurance for disbursement amount
        disburse_amount = loan.loan_amount - ProductMatrixPartner.ERAFONE_FEE - ProductMatrixPartner.insurance(
            application.loan_amount_request)
        loan.loan_disbursement_amount = disburse_amount
        loan.save()
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for payment_number in range(loan.loan_duration):
            if payment_number == 0:
                principal, interest, installment = principal_first, interest_first, installment_first
                due_date = offer.first_payment_date
            else:
                principal, interest, installment = principal_rest, interest_rest, installment_rest
                due_date = offer.first_payment_date + relativedelta(months=payment_number)

            if payment_number == (loan.loan_duration - 1):
                total_installment_principal = principal * loan.loan_duration
                if total_installment_principal < loan.loan_amount:
                    less_amount = loan.loan_amount - total_installment_principal
                    principal += less_amount
                    interest -= less_amount
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

        if offer.last_installment_amount:
            due_date = offer.first_payment_date + relativedelta(months=loan.loan_duration)

            payment = Payment.objects.create(
                loan=loan,
                payment_status=payment_status,
                payment_number=loan.loan_duration + 1,
                due_date=due_date,
                due_amount=offer.last_installment_amount,
                installment_principal=offer.last_installment_amount,
                installment_interest=0)

            logger.info({
                'loan': loan,
                'payment_number': loan.loan_duration + 1,
                'payment_amount': payment.due_amount,
                'due_date': due_date,
                'payment_status': payment.payment_status.status,
                'status': 'payment_created'
            })

    return True


def get_and_upload_pdf_content_from_html(
    html_content,
    filename,
    application,
    document_type,
    account_payment_id=None,
    is_phycical_wl: bool = False,
):
    temp_dir = '/media'
    options = {
        'page-size': 'A4',
        'margin-top': '0in',
        'margin-right': '0in',
        'margin-bottom': '0in',
        'margin-left': '0in',
        'encoding': "UTF-8",
        'no-outline': None,
    }
    file_path = os.path.join(temp_dir, filename)
    if is_phycical_wl:
        options['margin-bottom'] = '0.2in'
        pdfkit.from_string(html_content, file_path, options=options)
        pdf_bytes_io = BytesIO()
        with open(file_path, 'rb') as pdf_file:
            pdf_bytes_io.write(pdf_file.read())

        # get page number of pdf file
        pdf_reader = PdfFileReader(pdf_bytes_io)
        num_pages = pdf_reader.getNumPages()

        # delete pdf file from local
        os.remove(file_path)
        return pdf_bytes_io, num_pages
    else:
        pdfkit.from_string(html_content, file_path, options=options)
        with open(file_path, 'rb') as f:
            data = f.read()
            f.close()
        document = Document.objects.create(
            document_source=application.id,
            document_type=document_type,
            filename=filename,
            application_xid=application.application_xid,
            account_payment_id=account_payment_id,
        )
        upload_warning_letter.delay(document.id, file_path)
        encoded = base64.b64encode(data).decode()
        return encoded if isinstance(encoded, str) else encoded.decode()


def get_pdf_content_from_html(html_content, filename, options=None):
    temp_dir = tempfile.mkdtemp()
    if not options:
        options = {
            'page-size': 'A4',
            'margin-top': '0in',
            'margin-right': '0in',
            'margin-bottom': '0in',
            'margin-left': '0in',
            'encoding': "UTF-8",
            'no-outline': None,
        }
    file_path = os.path.join(temp_dir, filename)
    pdfkit.from_string(html_content, file_path, options=options)
    with open(file_path, 'rb') as f:
        data = f.read()
        f.close()
    encoded = base64.b64encode(data)
    if os.path.exists(file_path):
        os.remove(file_path)
    return encoded if isinstance(encoded, str) else encoded.decode()


def get_expiry_date(expiry_date, count):
    '''
    Function to get the next expire date based on working days
    '''
    dates =[]
    current_date = expiry_date
    while (count > len(dates)):
        weekday = current_date.weekday()
        current_date += timedelta(days=1)
        if weekday >= 5:
            continue
        else:
            dates.append(current_date)
    return current_date


def get_partner_application_status_exp_date(application):
    exp_date = None
    exp_rule = [x for x in APPLICATION_STATUS_EXPIRE_PATH if x['status_old'] == application.status]
    if exp_rule:
        application_history = ApplicationHistory.objects.filter(
            application=application, status_new=application.status).order_by('cdate').last()
        if application_history is None:
            return exp_date
        final_rule = [x for x in exp_rule if x.get('target') == TARGET_PARTNER]
        if final_rule:
            if final_rule[0]['status_to'] == ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED:
                exp_date = application_history.application.sphp_exp_date
            else:
                exp_date = get_expiry_date(application_history.cdate.date(), final_rule[0]['days'])
        else:
            exp_date = application_history.cdate.date() + relativedelta(days=exp_rule[0]['days'])
    return exp_date


def get_highest_reapply_reason(failed_checks):
    three_months_reason = Customer.REAPPLY_THREE_MONTHS_REASON
    one_year_reason = Customer.REAPPLY_ONE_YEAR_REASON
    reapply_not_allowed = Customer.REAPPLY_NOT_ALLOWED_REASON
    failed_check_reason = None
    level = 0
    for check in failed_checks:
        if level == 0 and check in three_months_reason:
            failed_check_reason = check
            level = 1
        if level in [0, 1] and check in one_year_reason:
            failed_check_reason = check
            level = 2
        if level in [0, 1, 2] and check in reapply_not_allowed:
            failed_check_reason = check
            level = 3
    return failed_check_reason


def get_application_sphp(application):
    """
    This function provides sphp for jtp, axiata, icare, laku6 for now
    """

    if application.partner_name == PartnerConstant.JTP_PARTNER:
        return get_sphp_template(application.id, use_default_template=False)
    elif application.partner_name == PartnerConstant.LAKU6_PARTNER:
        return get_laku6_sphp(application.id, application.customer)
    elif application.partner_name == PartnerConstant.PEDE_PARTNER:
        return get_partner_product_sphp(application.id, application.customer)


def get_email_setting_options(application):
    email_setting = EmailSetting.objects.get_or_none(
            status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            enabled=True)
    partner_setting = None
    julo_customer_setting = None

    if email_setting:
        partner_setting = email_setting.partneremailsetting_set.get_or_none(
            partner=application.partner,enabled=True)
        julo_customer_setting = email_setting.julocustomeremailsetting if (
            email_setting.julocustomeremailsetting and email_setting.julocustomeremailsetting.enabled ) else None

    email_setting_config = {
        'send_to_julo_customer': False,
        'attach_sphp_julo_customer': False,
        'send_to_partner': False,
        'attach_sphp_partner': False,
        'send_to_partner_customer': False,
        'attach_sphp_partner_customer': False,
        'email_setting': email_setting,
        'partner_setting': partner_setting,
        'julo_customer_setting': julo_customer_setting
    }

    if email_setting:
        if partner_setting:
            if partner_setting.send_to_partner:
                #send to partner
                email_setting_config['send_to_partner'] = True
            if partner_setting.attach_sphp_partner:
                email_setting_config['attach_sphp_partner'] = True
            if application.partner and partner_setting.send_to_partner_customer:
                # send to partner customer
                email_setting_config['send_to_partner_customer'] = True
                if partner_setting.attach_sphp_partner_customer:
                    email_setting_config['attach_sphp_partner_customer'] = True
        if julo_customer_setting and julo_customer_setting.send_email:
            # send to julo customera
            email_setting_config['send_to_julo_customer'] = True
            if julo_customer_setting.attach_sphp:
                email_setting_config['attach_sphp_julo_customer'] = True
        return email_setting_config
    else:
        return None


def check_eligible_for_campaign_referral(productline_code, principal, installment_first, loan_amount_offer, application):

    installment_first = installment_first

    ref_code, start_date, end_date = '', None, None

    referral_campaign = ReferralCampaign.objects.filter(
        referral_code=ReferralConstant.CAMPAIGN_CODE).first()

    if referral_campaign:
        ref_code = referral_campaign.referral_code
        start_date = referral_campaign.start_date
        end_date = referral_campaign.end_date

    today_date = datetime.now().date()

    if ref_code:
        ref_code = ref_code.lower()

    referral_code = application.referral_code if application else None

    if referral_code:
        referral_code = referral_code.lower()

    if productline_code in  ProductLineCodes.mtl()\
        and loan_amount_offer > ReferralConstant.MIN_AMOUNT and \
            referral_code == ref_code and \
                today_date >= start_date and \
                    today_date <= end_date:
        installment_first = round_rupiah(principal)
    return installment_first

def process_bank_account_validation(application):
    loan = application.loan
    # prepare data to validate
    data_to_validate = {'name_bank_validation_id': loan.name_bank_validation_id,
                        'bank_name': application.bank_name,
                        'account_number': application.bank_account_number,
                        'name_in_bank': application.name_in_bank,
                        'mobile_phone': application.mobile_phone_1,
                        'application': application
                        }
    name_bank_validation = NameBankValidation.objects.get_or_none(pk=loan.name_bank_validation_id)
    attempt = 0 if name_bank_validation is None else name_bank_validation.attempt
    attempt += 1
    is_name_similar = bank_name_similarity_check(application.fullname, application.name_in_bank.lower())
    is_bank_account_va = suspect_account_number_is_va(application.bank_account_number,
                                                               application.bank_name)
    is_success = False
    # for saving the changes account_number and name_in_bank from customer
    validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
    # do validation when fullname similar with bank_name and bank account not VA
    if is_name_similar and not is_bank_account_va:
        validation.validate()
        is_success = validation.is_success()
    name_bank_validation.attempt = attempt
    name_bank_validation.save(update_fields=["attempt"])
    if not is_success:
        if name_bank_validation.attempt == 3:
            new_status_code = ApplicationStatusCodes.NAME_VALIDATE_FAILED
            change_reason = 'Bank Name validation failed 3 times'
            note = 'Bank Name in Bank Validation Failed triggered by customer'
            process_application_status_change(application.id,
                                              new_status_code,
                                              change_reason,
                                              note)
            raise JuloException("Bank validation failed 3 times")
        name_bank_validation = NameBankValidation.objects.get_or_none(pk=loan.name_bank_validation_id)
        raise JuloException(name_bank_validation.reason)
    else:
        change_reason = 'Success Bank Account validation'
        note = 'Name in Bank Validation success triggered by customer'
        process_application_status_change(application.id,
                                          ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                                          change_reason,
                                          note)

def is_bank_name_validated(application):
    if not application.workflow:
        return True
    if application.workflow.name != CashLoanSchema.NAME:
        return True
    if application.app_version:
        is_old_version = semver.match(application.app_version,
                                      NameBankValidationStatus.OLD_VERSION_APPS)
        if is_old_version:
            return True

    if application.status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING:
        loan = application.loan
        name_bank_validation = NameBankValidation.objects.get_or_none(pk=loan.name_bank_validation_id)
        if name_bank_validation:
            if name_bank_validation.validation_status != NameBankValidationStatus.SUCCESS:
                return False
    return True

def get_google_calendar_attachment(application, is_generate_link=False):
    calendar = vobject.iCalendar()
    description_template = None
    summary_template = None
    get_template = False

    loan = application.loan
    loan_amount = loan.loan_amount
    loan_bank_name = loan.julo_bank_name
    loan_duration = loan.loan_duration
    loan_virtual_account_number = loan.julo_bank_account_number
    phone_number = application.mobile_phone_1

    if loan_bank_name == "Bank BCA":
        if application.product_line.product_line_code in ProductLineCodes.stl():
            description_template = 'description_google_calendar_bca_stl'
            summary_template = "Saatnya bayar tagihan JULO Anda! Abaikan jika sudah bayar."
            get_template = True
        elif application.product_line.product_line_code in ProductLineCodes.mtl():
            description_template = 'description_google_calendar_bca_mtl'
            summary_template = "Saatnya bayar cicilan JULO Anda! Abaikan jika sudah bayar."
            get_template = True
    else:
        if application.product_line.product_line_code in ProductLineCodes.stl():
            description_template = 'description_google_calendar_other_banks_stl'
            summary_template = "Saatnya bayar tagihan JULO Anda! Abaikan jika sudah bayar."
            get_template = True
        elif application.product_line.product_line_code in ProductLineCodes.mtl():
            description_template = 'description_google_calendar_other_banks_mtl'
            summary_template = "Saatnya bayar cicilan JULO Anda! Abaikan jika sudah bayar."
            get_template = True

    context_description = {
        'loan_amount': display_rupiah(loan_amount),
        'phone_number': phone_number,
        'va_number': loan_virtual_account_number,
        'prefix_va_bca': settings.PREFIX_BCA,
        'prefix_va_alfamart': settings.FASPAY_PREFIX_ALFAMART,
        'prefix_va_indomaret': settings.FASPAY_PREFIX_INDOMARET,
        'prefix_va_permata': settings.FASPAY_PREFIX_PERMATA,
    }

    if not get_template:
        return None, None

    description = render_to_string(description_template + '.html', context_description)
    payments = application.loan.payment_set.all()
    payment_number_first_day = application.loan.payment_set.order_by('payment_number').first().due_date.day

    for payment in payments:
        due_date = payment.due_date
        if payment_number_first_day in [28, 29, 30] and due_date.month != 2:
            due_date = due_date.replace(day=payment_number_first_day)

        due_date_min_1 = due_date - timedelta(days=1)
        due_date_min_1 = datetime(
            year=due_date_min_1.year,
            month=due_date_min_1.month,
            day=due_date_min_1.day
        )

        due_date_min_1 = due_date_min_1.replace(hour=9)
        event_attachment = calendar.add('vevent')
        event_attachment.add('summary').value = summary_template
        event_attachment.add('description').value = description
        event_attachment.add('rrule').value = "FREQ=MONTHLY;COUNT=%d" % loan_duration
        attendee = vobject.base.ContentLine('ATTENDEE', [], [application.email])
        event_attachment.attendee_list = [attendee]
        event_attachment.add('dtstart').value = due_date_min_1
        event_attachment.add('dtend').value = due_date_min_1

    icalstream = calendar.serialize()
    attachment_dict = {
        "content": base64.b64encode(icalstream.encode()).decode(),
        "filename": 'Repayment.ics',
        "type": "text/calendar"
    }
    if is_generate_link:
        description = calendar.contents['vevent'][0].contents['description'][0].value
        summary = calendar.contents['vevent'][0].contents['summary'][0].value
        start_date = str(calendar.contents['vevent'][0].contents['dtstart'][0].value - timedelta(hours=7))\
                         .replace("-","").replace(":", "").replace(" ", "T") + "Z"
        end_date = str(calendar.contents['vevent'][0].contents['dtend'][0].value - timedelta(hours=7)) \
                       .replace("-","").replace(":", "").replace(" ", "T") + "Z"
        date_formated = start_date + "%2f" + end_date
        link_url = "http://www.google.com/calendar/event?action=TEMPLATE&recur=RRULE:FREQ=MONTHLY;COUNT={}&" \
                   "dates={}&text={}&location=&details={}".format(loan_duration, date_formated, summary, description)
        return attachment_dict, "text/html", link_url
    else:
        return attachment_dict, "text/html"


def eligibe_check_tokopedia_october_campaign(application):

    loan = application.loan
    offer = loan.offer
    today_date = timezone.localtime(timezone.now()).date()

    if (application.cdate.month == 10) and (application.cdate.year == 2019):
        first_payment = loan.payment_set.order_by('payment_number').first()
        orig_due_amount = first_payment.due_amount
        principal_first, interest_first, installment_first = compute_adjusted_payment_installment(
            offer.loan_amount_offer, offer.loan_duration_offer,
            offer.interest_rate_monthly,
            today_date, offer.first_payment_date)

        first_payment.due_amount = principal_first
        first_payment.paid_amount = orig_due_amount - principal_first
        first_payment.paid_date = today_date
        first_payment.save()

        PaymentEvent.objects.create(
            payment=first_payment,
            event_payment=orig_due_amount - principal_first,
            event_due_amount=orig_due_amount,
            event_date=timezone.localtime(timezone.now()).date(),
            event_type='tokopedia_oct2019_promo')


def sort_payments_by_collection_model(payments, dpd, is_object_payment=True):
    if not payments:
        return []
    today = timezone.localtime(timezone.now()).date()
    filter_ = dict(
        cdate__date=today,
    )
    if isinstance(dpd, list):
        dpd = list(map(str, dpd))
    else:
        dpd = str(dpd)
        dpd = list(dpd)

    if is_object_payment:
        filter_['payment__id__in'] = tuple(payments.values_list('id', flat=True))
    else:
        filter_['payment__id__in'] = tuple(payments.values_list('payment_id', flat=True))

    if isinstance(dpd, list):
        filter_['range_from_due_date__in'] = dpd
    else:
        filter_['range_from_due_date'] = dpd

    ordered_results = PdCollectionModelResult.objects.filter(**filter_).order_by('sort_rank')
    exclude_filter_ = dict()
    if is_object_payment:
        exclude_filter_['id__in'] = tuple(ordered_results.values_list('payment_id', flat=True))
    else:
        exclude_filter_['payment__id__in'] = tuple(ordered_results.values_list('payment_id', flat=True))
    not_ordered_rank = payments.exclude(**exclude_filter_)
    # payments that not on pd_collection_model_results will put on bottom of list
    results = list(ordered_results) + list(not_ordered_rank)

    return results


def sort_payment_and_account_payment_by_collection_model(payments, account_payments, dpd, db_name=DEFAULT_DB):
    if not account_payments and not payments:
        return []

    today = timezone.localtime(timezone.now()).date()
    filter_ = dict(
        cdate__date=today,
    )
    if isinstance(dpd, list):
        dpd = list(map(str, dpd))
    else:
        dpd = str(dpd)
        dpd = list(dpd)

    if isinstance(dpd, list):
        filter_['range_from_due_date__in'] = dpd
    else:
        filter_['range_from_due_date'] = dpd

    account_payment_ids = tuple(account_payments.values_list('id', flat=True))
    payment_ids = tuple(payments.values_list('id', flat=True))
    ordered_results = PdCollectionModelResult.objects.filter(
        Q(payment_id__in=payment_ids) | Q(account_payment_id__in=account_payment_ids),
    ).filter(**filter_).order_by('sort_rank')
    not_ordered_rank_payments = payments.exclude(
        id__in=ordered_results.filter(
            payment_id__isnull=False).values_list('payment_id', flat=True)
    )
    not_ordered_rank_account_payments = account_payments.exclude(
        id__in=ordered_results.filter(
            account_payment_id__isnull=False).values_list('account_payment_id', flat=True)
    )
    not_ordered_rank = list(not_ordered_rank_payments) + list(not_ordered_rank_account_payments)
    results = list(ordered_results) + list(not_ordered_rank)
    return results


def sort_payments_for_grab_customer(payments):
    payments = payments.values_list('id', flat=True)
    skip_trace_histories = SkiptraceHistory.objects.filter(payment__id__in=payments)
    new_payments = set(payments) ^ set(skip_trace_histories.values_list(
        'payment', flat=True))
    new_payments = Payment.objects.filter(id__in=new_payments).order_by(
        'cdate').values_list('id', flat=True)
    non_contacted_skiptrace_payments_ids = skip_trace_histories.order_by(
        'payment', '-udate').distinct(
        'payment').exclude(
        status__in=CenterixCallResult.RPC + CenterixCallResult.WPC).values_list(
        'payment', flat=True)
    ordered_payments = list(new_payments) + list(
        non_contacted_skiptrace_payments_ids) + list(
        set(payments) - set(new_payments) - set(
            non_contacted_skiptrace_payments_ids))
    objects = Payment.objects.filter(id__in=ordered_payments)
    objects = dict([(obj.id, obj) for obj in objects])
    sorted_objects = [objects[id] for id in ordered_payments]
    return sorted_objects


def sort_account_payments_for_grab_customer(account_payments):
    account_payments = account_payments.values_list('id', flat=True)
    skip_trace_histories = SkiptraceHistory.objects.filter(account_payment__id__in=account_payments)
    new_account_payments = set(account_payments) ^ set(skip_trace_histories.values_list(
        'account_payment', flat=True))
    new_account_payments = AccountPayment.objects.filter(id__in=new_account_payments).order_by(
        'cdate').values_list('id', flat=True)
    non_contacted_skiptrace_account_payments_ids = skip_trace_histories.order_by(
        'account_payment', '-udate').distinct(
        'account_payment').exclude(
        status__in=CenterixCallResult.RPC + CenterixCallResult.WPC).values_list(
        'account_payment', flat=True)
    ordered_account_payments = list(new_account_payments) + list(
        non_contacted_skiptrace_account_payments_ids) + list(
        set(account_payments) - set(new_account_payments) - set(
            non_contacted_skiptrace_account_payments_ids))
    objects = AccountPayment.objects.filter(id__in=ordered_account_payments)
    objects = dict([(obj.id, obj) for obj in objects])
    sorted_objects = [objects[id] for id in ordered_account_payments]
    return sorted_objects


def get_failed_robocall_payments(localtime_type, product_line_codes, due_start_date, due_end_date):
    if localtime_type == LocalTimeType.WIB:
        failed_robocall_payments = Payment.objects\
            .failed_robocall_payments_with_date_and_wib_localtime(
                product_line_codes, due_start_date, due_end_date)
    elif localtime_type == LocalTimeType.WITA:
        failed_robocall_payments = Payment.objects\
            .failed_robocall_payments_with_date_and_wita_localtime(
                product_line_codes, due_start_date, due_end_date)
    elif localtime_type == LocalTimeType.WIT:
        failed_robocall_payments = Payment.objects\
            .failed_robocall_payments_with_date_and_wit_localtime(
                product_line_codes, due_start_date, due_end_date)

    return failed_robocall_payments

def get_payment_ids_for_wa_experiment_october(localtime_type, loan_tails):
    product_line_codes = ProductLineCodes.mtl()
    due_start_date = date(2019, 10, 27)
    due_end_date = date(2019, 11, 7)

    payments = get_failed_robocall_payments(localtime_type, product_line_codes, due_start_date, due_end_date)\
        .values('id', 'loan__id')

    payment_ids = []
    for payment in payments:
        loan_id = old_div(payment['loan__id'], 10)
        if loan_id % 10 in loan_tails:
            payment_ids.append(payment['id'])

    return payment_ids


def assign_lender_in_loan(application):
    product_code = []
    try:
        loan = application.loan
    except Exception as e:
        loan = None

    if application.product_line:
        product_code = application.product_line.product_line_code

    bri_partner = LenderCurrent.objects.get(lender_name=PartnerConstant.BRI_PARTNER)
    grab_partner = LenderCurrent.objects.get(lender_name=PartnerConstant.GRAB_PARTNER)
    jtp_partner = LenderCurrent.objects.get(lender_name=PartnerConstant.JTP_PARTNER)

    if loan:
        if product_code in  ProductLineCodes.grab() + ProductLineCodes.lended_by_grabfood():
            lender = grab_partner
        elif product_code in  ProductLineCodes.bri():
            lender = bri_partner
        elif product_code in ProductLineCodes.pede() + [ProductLineCodes.PEDE1, ProductLineCodes.PEDE2]:
            lender = jtp_partner
        else:
            lender = assign_lender_to_disburse(application)
        # this only for handle FTM
        # prevent race condition
        loan.update_safely(lender=lender, partner=lender.user.partner)


def experimentation_false_reject_min_exp(application):
    # false_reject_minimization_experiment

    date_now = timezone.localtime(timezone.now()).date()
    experiment = Experiment.objects.filter(
        is_active=True, code=ExperimentConst.FALSE_REJECT_MINIMIZATION,
        date_start__lte=date_now, date_end__gte=date_now
        ).first()

    customer = application.customer

    last_two_digits = []
    if experiment:
        experiment_settings = experiment.experimenttestgroup_set.filter(
            value__isnull=False).first()
        if experiment_settings:
            last_two_digits = experiment_settings.value.split(':')[2].split(',')

    job_type = ['Pegawai negeri', 'Pegawai swasta', 'Pekerja rumah tangga', 'Staf rumah tangga']

    application_count_experiment = 1700

    application_count = ApplicationExperiment.objects.filter(
        application__application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        experiment=experiment).count()

    if experiment and str(application.application_xid)[:2] in last_two_digits and \
        application.job_type in job_type and \
            application_count < application_count_experiment and \
                application.creditscore.score_tag == ScoreTag.C_LOW_CREDIT_SCORE and \
                    not application.customer.is_repeated and not application.partner:

        application_experiment = ApplicationExperiment.objects.filter(
            application=application, experiment=experiment
            )

        if not application_experiment:
            ApplicationExperiment.objects.create(
                application=application, experiment=experiment
                )

def count_payment_dashboard_buckets():
    """
    count some values of payment
    """

    payment_query = Payment.objects.exclude(
        loan__application__partner__name__in=PartnerConstant.form_partner()
    ).normal()

    buckets_dict = {}
    buckets_dict['TnotCalled'] = payment_query.uncalled_group().count()
    buckets_dict['PTP'] = payment_query.bucket_ptp().count()
    buckets_dict['grab'] = payment_query.grab_0plus().count()
    buckets_dict['whatsapp'] = payment_query.bucket_whatsapp().count()
    buckets_dict['whatsapp_blasted'] = payment_query.bucket_whatsapp_blasted().count()
    buckets_dict['Tminus5Robo'] = payment_query.bucket_list_t_minus_5_robo().count()
    buckets_dict['Tminus3Robo'] = payment_query.bucket_list_t_minus_3_robo().count()

    # Status 330, 331, 332
    for status in PaymentStatusCodes.paid_status_codes():
        count = payment_query.filter(payment_status__status_code=status).count()
        buckets_dict[str(status)] = count

    return buckets_dict


def check_customer_promo(application):
    # check customer used any active promotion to reduce the first month interest to 0 %
    today = timezone.now().date()
    promo_active = PromoCode.objects.filter(
        promo_code__iexact=application.referral_code, is_active=True,
        start_date__lte=today, end_date__gte=today
        ).first()
    if promo_active and promo_active.promo_benefit != 'cashback':
        validation = True

        if not promo_active.partner and not promo_active.product_line and \
            not promo_active.credit_score:
            return

        if promo_active.partner:
            if not (application.partner_name in promo_active.partner):
                validation = False
            if 'All' in promo_active.partner:
                validation = True

        if validation and promo_active.product_line and application.product_line_code:
            if not (str(int(application.product_line_code)) in promo_active.product_line):
                validation = False
            if 'All' in promo_active.product_line:
                validation = True

        if validation and promo_active.credit_score:
            if not (application.creditscore.score in promo_active.credit_score):
                validation = False
            if 'All' in promo_active.credit_score:
                validation = True

        if validation:
            remaining_installment_interest = 0
            loan = application.loan
            payment = loan.payment_set.order_by('payment_number').first()
            if promo_active.promo_benefit:
                payment.due_amount = payment.installment_principal
                payment.paid_amount = payment.installment_interest
                payment.paid_date = today
                payment.save()
                remaining_installment_interest = payment.installment_interest

            promo_name = 'promo_{}'.format(promo_active.promo_name)

            waive_promo = WaivePromo.objects.filter(
                loan=loan, payment=payment, promo_event_type=promo_name
            )

            if not waive_promo:
                WaivePromo.objects.create(
                    loan=loan, payment=payment,
                    remaining_installment_principal=payment.installment_principal,
                    remaining_installment_interest=remaining_installment_interest,
                    remaining_late_fee=0, promo_event_type=promo_name
                )
    elif promo_active and promo_active.promo_benefit == 'cashback':
        application.customer.change_wallet_balance(
            change_accruing=0,
            change_available=promo_active.cashback_amount,
            reason='cashback_promo'
        )
        loan = application.loan
        payment = loan.payment_set.last()
        PromoHistory.objects.create(
            loan= loan,
            customer=application.customer,
            payment=payment,
            promo_type=promo_active.promo_name,
        )


def check_tokopedia_eligibe_january_campaign(application):
    loan = application.loan
    payment = loan.payment_set.order_by('payment_number').first()

    start_date = datetime(2020, 1, 1)
    end_date = datetime(2020, 2, 29)

    today = timezone.localtime(timezone.now())

    if application.cdate.date() >= start_date.date() \
        and application.cdate.date() <= end_date.date() and \
            start_date.date() <= today.date() and end_date.date() >= today.date():

        payment.due_amount = payment.installment_principal
        payment.paid_amount = payment.installment_interest
        payment.paid_date = today.date()
        payment.save()

        waive_promo = WaivePromo.objects.filter(
            loan=loan, payment=payment,promo_event_type='jan_promo_tokopedia_interest'
        )

        if not waive_promo:
            WaivePromo.objects.create(
                loan=loan, payment=payment,
                remaining_installment_principal=payment.installment_principal,
                remaining_installment_interest=payment.installment_interest,
                remaining_late_fee=0,promo_event_type='jan_promo_tokopedia_interest'
            )


def check_good_customer_or_not(customer):
    good_customer = False
    application = customer.application_set.filter(
        loan__loan_status=LoanStatusCodes.PAID_OFF
    ).order_by('id').last()
    if application:
        today = timezone.localtime(timezone.now()).date()
        payments = application.loan.payment_set.order_by('id')
        last_payment = payments.last()
        days = (today - last_payment.paid_date).days
        count = payments.filter(payment_status=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD).count()
        if days <= 90 and count <= 1:
            all_statuses = list([x.status for x in payments])
            good_customer = not any(status == PaymentStatusCodes.PAID_LATE for status in all_statuses)
    return good_customer


def send_pn_playstore_rating(application):
    customer = application.customer
    if application.device is not None and not customer.is_review_submitted:
        notif = NotificationTemplate.objects.get(notification_code='rating_app_180')
        current_image = Image.objects.get(
            image_source=notif.id, image_type='notification_image_ops'
            )
        image_url = current_image.notification_image_url
        gcm_reg_id = application.device.gcm_reg_id
        application_id = application.id
        julo_pn_client = get_julo_pn_client()
        fullname = application.fullname
        message = notif.body
        title = notif.title
        julo_pn_client.send_pn_playstore_rating(fullname, gcm_reg_id, application_id, message, image_url, title)


def cem_b2_3_4_experiment(payments, status_dpd, is_object_payment=True):
    active_experiment = ExperimentSetting.objects.filter(
        Q(code=ExperimentConst.CEM_B2_B3_B4_EXPERIMENT, is_active=True) &
        Q(is_permanent=True)
    ).last()
    if not active_experiment:
        return payments
    test_group_last_loan_ids = active_experiment.criteria['test_group_last_loan_id']
    # comment out control_group_last_loan_id (https://juloprojects.atlassian.net/browse/ENH-233)
    # control_group_last_loan_id = active_experiment.criteria['control_group_last_loan_id']
    dpd = None
    # bucket 2
    if 'JULO_B2' in status_dpd:
        dpd = list(range(11, 41))
    # bucket 3
    elif 'JULO_B3' in status_dpd:
        dpd = list(range(41, 71))
    # bucket 4
    elif 'JULO_B4' in status_dpd:
        dpd = list(range(71, 101))
    if not dpd:
        return payments
    payments = payments.annotate(last_digit_loan_id=F('loan_id') % 10)
    test_group_payments = sort_payments_by_collection_model(
        payments.filter(last_digit_loan_id__in=test_group_last_loan_ids),
        dpd=dpd,
        is_object_payment=is_object_payment
    )
    if not test_group_payments:
        logger.info({
            "action": "send data CeM experiment",
            "conclution": "Send data without ratio because "
                          "test group not in pd_collection_model_result"
        })
        return payments
    # comment out control_group_last_loan_id (https://juloprojects.atlassian.net/browse/ENH-233)
    # control_group_payments = payments.filter(last_digit_loan_id__in=control_group_last_loan_id)
    # combined_payments = combine_array_with_ratio(control_group_payments, test_group_payments,
    #                                              ratio_1=2, ratio_2=3)
    return test_group_payments


def faspay_snap_payment_inquiry_statement(
    statement: Statement, 
    payment_method: PaymentMethod,
    faspay_bill: dict
) -> Tuple[dict, int]:
    due_amount = statement.statement_total_due_amount
    customer = statement.customer_credit_limit.customer

    faspay_bill['virtualAccountData']['virtualAccountNo'] = payment_method.virtual_account
    faspay_bill['virtualAccountData']['virtualAccountName'] = customer.fullname
    faspay_bill['virtualAccountData']['virtualAccountEmail'] = customer.email
    faspay_bill['virtualAccountData']['virtualAccountPhone'] = add_plus_62_mobile_phone(
        customer.phone
    )
    faspay_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(due_amount, '00')

    return faspay_bill, due_amount


def faspay_payment_inquiry_statement(statement, payment_method):
    due_amount = statement.statement_total_due_amount
    virtual_account = int(payment_method.virtual_account)
    customer_name = statement.customer_credit_limit.customer.fullname

    data = {
        'response': 'VA Static Response',
        'va_number': virtual_account,
        'amount': due_amount,
        'cust_name': customer_name,
        'response_code': '00'
    }

    return data


def suspect_account_number_is_va(bank_account_number, bank_name):
    if bank_account_number:
        len_account_number = len(bank_account_number)
        bank_entry = BankManager.get_by_name_or_none(bank_name)
        if bank_entry:
            if len_account_number < NameBankValidationStatus.SUSPECT_VA_LENGTH:
                return False
            if len_account_number == NameBankValidationStatus.SUSPECT_VA_LENGTH and \
                    bank_entry.bank_code in NameBankValidationStatus.EXCEPTIONAL_BANK_CODE:
                return False
        return True
    else:
        return False

def get_warning_letter_google_calendar_attachment(next_not_due_payment, application):
    calendar = vobject.iCalendar()
    if application.is_julo_one():
        account = application.account
        loan = Loan.objects.filter(account=account).last()
    else:
        loan = application.loan
    loan_bank_name = loan.julo_bank_name
    phone_number = application.mobile_phone_1
    permata_virtual_account = PaymentMethodCodes.PERMATA + " " + phone_number
    alfamaret_virtual_account = PaymentMethodCodes.ALFAMART + " " + phone_number
    indomaret_virtual_account = PaymentMethodCodes.INDOMARET + " " + phone_number
    bca_virtual_account = PaymentMethodCodes.BCA + " " + phone_number
    summary_template = "Saatnya melakukan pembayaran tagihan JULO Anda!"
    if loan_bank_name == "Bank BCA":
        description_template = 'wl_description_google_calendar_bca_mtl'
    else:
        description_template = 'wl_description_google_calendar_other_banks_mtl'

    payment_number_first_day = next_not_due_payment.first().due_date.day
    payment_methods = PaymentMethod.objects.filter(loan_id=loan.id,
                                                  payment_method_code__in=[PaymentMethodCodes.PERMATA,
                                                                          PaymentMethodCodes.ALFAMART,
                                                                          PaymentMethodCodes.INDOMARET,
                                                                          PaymentMethodCodes.BCA])
    for payment_method in payment_methods:
        virtual_account = payment_method.virtual_account.replace(payment_method.payment_method_code,
                                                                             payment_method.payment_method_code + " ")
        if payment_method.payment_method_code == PaymentMethodCodes.PERMATA:
            permata_virtual_account = virtual_account

        if payment_method.payment_method_code == PaymentMethodCodes.ALFAMART:
            alfamaret_virtual_account = virtual_account

        if payment_method.payment_method_code == PaymentMethodCodes.INDOMARET:
            indomaret_virtual_account = virtual_account

        if payment_method.payment_method_code == PaymentMethodCodes.BCA:
            bca_virtual_account = virtual_account

    for payment in next_not_due_payment:
        date = datetime.strftime(payment.due_date, "%d-%m-%Y")
        context_description = {
            'due_amount': display_rupiah(payment.due_amount),
            'permata_virtual_account': permata_virtual_account,
            'indomaret_virtual_account': indomaret_virtual_account,
            'alfamaret_virtual_account': alfamaret_virtual_account,
            'bca_virtual_account': bca_virtual_account,
            'due_date': date
        }

        description = render_to_string(description_template + '.html', context_description)
        due_date = payment.due_date
        num_days = monthrange(due_date.year, due_date.month)[1]
        if payment_number_first_day == 31:
            due_date = due_date.replace(day=num_days)
        if payment_number_first_day in [29, 30]:
            if due_date.month == 2:
                due_date = due_date.replace(day=num_days)
            else:
                due_date = due_date.replace(day=payment_number_first_day)
        due_date = datetime(
            year=due_date.year,
            month=due_date.month,
            day=due_date.day
        )

        due_date = due_date.replace(hour=12).replace(minute=15)
        event_attachment = calendar.add('vevent')
        event_attachment.add('summary').value = summary_template
        event_attachment.add('description').value = description
        event_attachment.add('rrule').value = "FREQ=MONTHLY;COUNT=%d" % len(next_not_due_payment)
        attendee = vobject.base.ContentLine('ATTENDEE', [], [loan.customer.email])
        event_attachment.attendee_list = [attendee]
        event_attachment.add('dtstart').value = due_date
        event_attachment.add('dtend').value = due_date

    icalstream = calendar.serialize()
    link_url = generate_ics_link(calendar)
    attachment_dict = {
        "content": base64.b64encode(icalstream).decode(),
        "filename": 'Repayment.ics',
        "type": "text/calendar"
    }

    return link_url, attachment_dict, "text/html"


def get_google_calendar_data_non_j1(application, is_dpd_plus):
    description_template = None
    loan = application.loan
    loan_amount = loan.loan_amount
    loan_bank_name = loan.julo_bank_name
    loan_virtual_account_number = loan.julo_bank_account_number
    phone_number = application.mobile_phone_1
    payments = application.loan.payment_set.all().not_overdue().order_by('payment_number')
    if not payments:
        return None, None

    loan_duration_remaining = len(payments)
    if is_dpd_plus:
        summary_template = "Saatnya bayar cicilan JULO Anda!"
        description_template = 'description_google_calendar_dpd+4'
    else:
        summary_template = "Saatnya bayar tagihan JULO Anda! Abaikan jika sudah bayar."
        if loan_bank_name == "Bank BCA":
            if application.product_line.product_line_code in ProductLineCodes.stl():
                description_template = 'description_google_calendar_bca_stl'
            elif application.product_line.product_line_code in ProductLineCodes.mtl():
                description_template = 'description_google_calendar_bca_mtl'
        else:
            if application.product_line.product_line_code in ProductLineCodes.stl():
                description_template = 'description_google_calendar_other_banks_stl'
            elif application.product_line.product_line_code in ProductLineCodes.mtl():
                description_template = 'description_google_calendar_other_banks_mtl'

    context_description = {
        'loan_amount': display_rupiah(loan_amount),
        'phone_number': phone_number,
        'va_number': loan_virtual_account_number,
        'prefix_va_bca': settings.PREFIX_BCA,
        'prefix_va_alfamart': settings.FASPAY_PREFIX_ALFAMART,
        'prefix_va_indomaret': settings.FASPAY_PREFIX_INDOMARET,
        'prefix_va_permata': settings.FASPAY_PREFIX_PERMATA,
    }

    description = render_to_string(description_template + '.html', context_description)
    payment_number_first_day = application.loan.payment_set.order_by('payment_number').first().due_date.day
    calendar_data = []
    for payment in payments:
        due_date = payment.notification_due_date
        if not payment.ptp_date:
            if payment_number_first_day in [28, 29, 30] and due_date.month != 2:
                due_date = due_date.replace(day=payment_number_first_day)

        due_date = datetime(
            year=due_date.year,
            month=due_date.month,
            day=due_date.day,
            hour=9
        )
        calendar_data.append(
            dict(
                summary=summary_template, description=description,
                due_date=due_date
            )
        )

    return calendar_data, loan_duration_remaining


def get_google_calendar_data_j1(application):
    summary_template = "Saatnya bayar tagihan JULO Anda! Abaikan jika sudah bayar."
    description_template = 'description_google_calendar_for_j1'
    primary_payment_method = PaymentMethod.objects.filter(
        customer=application.customer,
        is_primary=True
    ).last()
    alfamart_payment_method = PaymentMethod.objects.filter(
        customer=application.customer,
        payment_method_name="ALFAMART"
    ).last()
    indomaret_payment_method = PaymentMethod.objects.filter(
        customer=application.customer,
        payment_method_name="INDOMARET"
    ).last()
    alfamart_va_number = '-' if not alfamart_payment_method \
        else alfamart_payment_method.virtual_account
    indomaret_va_number = '-' if not indomaret_payment_method \
        else indomaret_payment_method.virtual_account

    context_description = {
        'first_name': application.first_name_only,
        'due_amount_for_that_periode_tagihan': 'Rp. ',
        'primary_payment_method_name': primary_payment_method.payment_method_name,
        'primary_virtual_account_number': primary_payment_method.virtual_account,
        'alfamart_va_number': alfamart_va_number,
        'indomaret_va_number': indomaret_va_number,
    }
    account = application.account
    account_payments = account.accountpayment_set.all().not_overdue() \
        .order_by('due_date')
    if not account_payments:
        return None, None

    loan_duration_remaining = account_payments.count()
    calendar_data = []
    for account_payment in account_payments:
        context_description['due_amount_for_that_periode_tagihan'] = \
            display_rupiah(account_payment.due_amount)
        description = render_to_string(description_template + '.html', context_description)
        due_date = account_payment.notification_due_date
        due_date = datetime(
            year=due_date.year,
            month=due_date.month,
            day=due_date.day,
            hour=9
        )
        calendar_data.append(
            dict(
                summary=summary_template, description=description,
                due_date=due_date
            )
        )

    return calendar_data, loan_duration_remaining


def get_google_calendar_for_email_reminder(
        application, is_dpd_plus=False, is_for_j1=False, is_ptp=False):
    calendar = vobject.iCalendar()
    if not is_for_j1:
        calendar_data, loan_duration_remaining = get_google_calendar_data_non_j1(
            application, is_dpd_plus)
    else:
        calendar_data, loan_duration_remaining = get_google_calendar_data_j1(application)

    if not calendar_data:
        return None, None, None

    for item in calendar_data:
        event_attachment = calendar.add('vevent')
        event_attachment.add('summary').value = item['summary']
        if is_ptp:
            item['description'] = ""
        event_attachment.add('description').value = item['description']
        event_attachment.add('rrule').value = "FREQ=MONTHLY;COUNT=%d" % loan_duration_remaining
        attendee = vobject.base.ContentLine('ATTENDEE', [], [application.email])
        event_attachment.attendee_list = [attendee]
        event_attachment.add('dtstart').value = item['due_date']
        event_attachment.add('dtend').value = item['due_date']

    icalstream = calendar.serialize()
    attachment_dict = {
        "content": base64.b64encode(icalstream.encode()).decode(),
        "filename": 'Repayment.ics',
        "type": "text/calendar"
    }
    description = calendar.contents['vevent'][0].contents['description'][0].value
    summary = calendar.contents['vevent'][0].contents['summary'][0].value
    start_date = str(calendar.contents['vevent'][0].contents['dtstart'][0].value - timedelta(hours=7))\
                     .replace("-","").replace(":", "").replace(" ", "T") + "Z"
    end_date = str(calendar.contents['vevent'][0].contents['dtend'][0].value - timedelta(hours=7)) \
                   .replace("-","").replace(":", "").replace(" ", "T") + "Z"
    date_formated = start_date + "%2f" + end_date
    link_url = "http://www.google.com/calendar/event?action=TEMPLATE&recur=RRULE:FREQ=MONTHLY;COUNT={}&" \
               "dates={}&text={}&location=&details={}".format(loan_duration_remaining, date_formated, summary, description)
    return attachment_dict, "text/html", link_url


def store_to_temporary_table(data):
    """temporary store fdc data for matching purpose"""
    fdc_temporary_data = []
    for item in data:
        temp_record = FDCDeliveryTemp(
            dpd_max=item['status_pinjaman_max_dpd'],
            dpd_terakhir=item['status_pinjaman_dpd'],
            id_penyelenggara=item['id_penyelenggara'],
            jenis_pengguna=item['jenis_pengguna'],
            kualitas_pinjaman=item['id_kualitas_pinjaman'],
            nama_borrower=item['nama_borrower'],
            nilai_pendanaan=item['nilai_pendanaan'],
            no_identitas=item['no_identitas'],
            no_npwp=item['no_npwp'],
            sisa_pinjaman_berjalan=item['sisa_pinjaman_berjalan'],
            status_pinjaman=item['status_pinjaman'],
            tgl_jatuh_tempo_pinjaman=item['tgl_jatuh_tempo_pinjaman'],
            tgl_pelaporan_data=item['tgl_pelaporan_data'],
            tgl_penyaluran_dana=item['tgl_penyaluran_dana'],
            tgl_perjanjian_borrower=item['tgl_perjanjian_borrower']
        )
        fdc_temporary_data.append(temp_record)

    FDCDeliveryTemp.objects.bulk_create(fdc_temporary_data)
    logger.info({
        "action": "store to temporary table",
        "status": "Done"
    })


def get_nexmo_from_phone_number() -> Tuple[str, str]:
    """
    Returns a single number from RobocallCallingNumberChange

    Returns:
        phone_number (str): The phone number that Nexmo client will use to call.
        test_number (str): The test number used for test call in Django Admin.

    TODO:
        This function is deprecated with implementation of PLAT-785.
    Note:
        This function is changed from its original implementation as of PLAT-785. Please check prior
        commit to see original code.
    """
    now = datetime.now()
    robocall_calling_number_changer = RobocallCallingNumberChanger.objects.filter(
        start_date__lte=now, end_date__gte=now,
    ).last()
    if not robocall_calling_number_changer:
        robocall_calling_number_changer = RobocallCallingNumberChanger.objects.first()
        if not robocall_calling_number_changer:
            phone_number = ''
            test_number = ''
        else:
            # phone_number = robocall_calling_number_changer.default_number
            phone_number = robocall_calling_number_changer.new_calling_number
            test_number = robocall_calling_number_changer.test_to_call_number
    else:
        phone_number = robocall_calling_number_changer.new_calling_number
        test_number = robocall_calling_number_changer.test_to_call_number

    return phone_number, test_number


def get_payment_url_from_payment(payment, is_partner=False):
    if is_partner:
        encrypttext = encrypt()
        encoded_payment_id = encrypttext.encode_string(str(payment.id))
        url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
        shorten = get_url_shorten_service()
        shorten_url = shorten.short(url)
        return shorten_url['url']
    else:
        return "go.onelink.me/zOQD/howtopay"

def check_risky_customer(application_id):
    try:
        application = Application.objects.get_or_none(pk=application_id)
        if application is None:
            return True
        customer = application.customer
        app_history_100 = ApplicationHistory.objects.filter(application=application,
                                                            status_new=ApplicationStatusCodes.FORM_CREATED).last()
        is_risky = False

        app_history_180 = ApplicationHistory.objects.filter(
            application=application,
            status_new=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        ).last()

        fdc_ongoing_loan_after_180 = FDCInquiryLoan.objects.filter(
            no_identitas=customer.nik,
            status_pinjaman='Outstanding', cdate__gte=app_history_180.cdate
        ).exclude(is_julo_loan=True).count()

        fdc_ongoing_loan_after_100 = FDCInquiryLoan.objects.filter(
            no_identitas=customer.nik,
            status_pinjaman='Outstanding', cdate__gte=app_history_100.cdate, cdate__lt=app_history_180.cdate
        ).exclude(is_julo_loan=True).count()

        delinquent = FDCInquiryLoan.objects.filter(
            dpd_terakhir__gte=5, cdate__gte=app_history_180.cdate
        ).exclude(is_julo_loan=True).last()

        if fdc_ongoing_loan_after_180 > fdc_ongoing_loan_after_100 or delinquent:
            is_risky = True

        return is_risky

    except AttributeError:
        is_risky = True

        return is_risky

def get_lebaran_2020_users(is_partner=False, is_sms=False):
    """
        To get All the MLT/partner Users who payed within range 24-04-2020 to 10-05-2020
        key - email/sms
    """
    if is_partner:
        if is_sms:
            product_line = ProductLineCodes.icare() + ProductLineCodes.pede() + ProductLineCodes.laku6()
        else:
            product_line = ProductLineCodes.pede() + ProductLineCodes.laku6()
        loan_ids = Loan.objects.filter(loan_status__gte=LoanStatusCodes.CURRENT,
                                       loan_status__lt=LoanStatusCodes.PAID_OFF,
                                       application__product_line_id__in=product_line).values('id')
    else:
        loan_ids = Loan.objects.get_queryset().all_active_mtl().values('id')
    return loan_ids

def send_lebaran_2020_email_subtask(application, payment, tnc_url, date, is_partner=False):
    julo_email_client = get_julo_email_client()
    if is_partner:
        payment_url = get_payment_url_from_payment(payment, is_partner=True)
        status, headers, subject, msg, template_code = julo_email_client.email_lebaran_campaign_2020(
            application=application,
            date=date,
            is_partner=True,
            tnc_url=tnc_url,
            payment_url=payment_url)
    else:
        payment_url = get_payment_url_from_payment(payment)
        status, headers, subject, msg, template_code = julo_email_client.email_lebaran_campaign_2020(
            application=application,
            date=date,
            tnc_url=tnc_url,
            payment_url=payment_url)
    if status == 202:
        message_id = headers['X-Message-Id']
        EmailHistory.objects.create(
            application=application,
            sg_message_id=message_id,
            to_email=application.email,
            subject=subject,
            message_content=msg,
            template_code=template_code
        )

def send_lebaran_2020_sms_subtask(application, payment, date, is_partner=False):
    if not application.mobile_phone_1:
        return
    julo_sms_client = get_julo_sms_client()
    if is_partner:
        payment_url = get_payment_url_from_payment(payment, is_partner=True)
        message, response, template, msg = julo_sms_client.sms_lebaran_campaign_2020(
            application=application,
            date=date,
            is_partner=True,
            payment_url=payment_url)
    else:
        payment_url = get_payment_url_from_payment(payment)
        message, response, template, msg = julo_sms_client.sms_lebaran_campaign_2020(
            application=application,
            date=date,
            payment_url=payment_url)
    if response['status'] != '0':
        logger.warn({
            'send_status': response['status'],
            'application_id': application.id,
            'message': message,
        })
    else:
        sms = create_sms_history(response=response,
                                 customer=application.customer,
                                 application=application,
                                 to_mobile_phone=format_e164_indo_phone_number(response['to']),
                                 phone_number_type='mobile_phone_1',
                                 template_code=template,
                                 message_content=msg
                                 )
        logger.info({
            'status': 'sms_created',
            'sms_history_id': sms.id,
            'message_id': sms.message_id
        })


def send_lebaran_2020_pn_subtask(application, payment, date, is_partner=False):
    if not have_pn_device(application.device):
        return
    julo_pn_client = get_julo_pn_client()
    logger.info({
        'action': 'send_pn_lebaran_campaign_reminder',
        'application_id': application.id,
    })
    julo_pn_client.notify_lebaran_campaign_2020_mtl(application, date)


def is_last_payment_status_notpaid(payment):
    loan = payment.loan
    last_payment = loan.payment_set.exclude(id__gte=payment.id).order_by('id').last()
    if not last_payment:
        return False
    return last_payment.status not in PaymentStatusCodes.paid_status_codes()


def get_payment_due_date_by_delta(dpd):
    today = timezone.localtime(timezone.now()).date()
    if dpd > 0:
        return today - relativedelta(days=abs(dpd))
    else:
        return today + relativedelta(days=abs(dpd))


def get_extra_context(available_context, extra_context, payment):

    if 'cashback_multiplier' in extra_context:
        available_context.update({'cashback_multiplier': payment.cashback_multiplier})

    if 'payment_cashback_amount' in extra_context:
        cashback_percent = 0.01
        if 'due_date_minus_2' in extra_context:
            cashback_percent = 0.02
            available_context.update({'due_date_minus_2':
                                     format_date(payment.due_date - timedelta(days=2), 'dd-MMM', locale='id_ID')})

        if 'due_date_minus_4' in extra_context:
            cashback_percent = 0.03
            available_context.update({'due_date_minus_4':
                                     format_date(payment.due_date - timedelta(days=4), 'dd-MMM', locale='id_ID')})

        available_context.update({'payment_cashback_amount': display_rupiah(int(
            (old_div(cashback_percent, payment.loan.loan_duration)) * payment.loan.loan_amount))})

    if 'payment_details_url' in extra_context:
        encrypttext = encrypt()
        encoded_payment_id = encrypttext.encode_string(str(payment.id))
        url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
        shortened_url = shorten_url(url)
        available_context.update({'payment_details_url': shortened_url})

    if 'how_pay_url' in extra_context:
        available_context.update({'how_pay_url': URL_CARA_BAYAR})

    return available_context


def update_payment_fields(loan, axiata_customer_data, additional_loan_data):
    payments = list(
        Payment.objects.by_loan(loan).not_paid().order_by('payment_number')
    )
    interest_rate = axiata_customer_data.interest_rate
    is_interest_less_than_equal_0 = False
    if additional_loan_data['is_exceed']:
        interest_rate = additional_loan_data['new_interest_rate']
        if additional_loan_data['new_interest_rate'] <= 0:
            is_interest_less_than_equal_0 = True

    for payment in payments:
        logger.info({
            'action': 'changing_payment_fields',
            'loan': loan.id,
            'payment': payment.id,
            'payment_number': payment.payment_number,
        })
        installment_principal = axiata_customer_data.loan_amount
        installment_amount = 0
        if not is_interest_less_than_equal_0 and additional_loan_data['is_exceed']:
            installment_amount = ceil(interest_rate * axiata_customer_data.loan_amount)
        elif not is_interest_less_than_equal_0 and not additional_loan_data['is_exceed']:
            installment_amount = ceil(
                (old_div(interest_rate, 100)) * axiata_customer_data.loan_amount)

        due_amount = installment_principal + installment_amount
        payment.update_safely(installment_interest=installment_amount,
                              due_amount=due_amount,
                              installment_principal=installment_principal)


def update_is_proven_julo_one(loan):
    from juloserver.account.services.credit_limit import store_account_property_history

    if loan.status != LoanStatusCodes.PAID_OFF:
        return

    account = loan.account
    account_property = account.accountproperty_set.last()
    if not account_property:
        return
    # check is update is_proven is first time
    is_account_ever_delinquent = AccountPropertyHistory.objects.filter(
        account_property=account_property,
        field_name='is_proven', value_old=True, value_new=False).exists()

    if is_account_ever_delinquent:
        return

    total_paid_amount = Loan.objects.filter(
        account=account, loan_status_id=LoanStatusCodes.PAID_OFF
    ).aggregate(Sum('loan_amount'))['loan_amount__sum']

    if not total_paid_amount:
        return

    if total_paid_amount > account_property.proven_threshold:
        current_account_property = list(account.accountproperty_set.values())[-1]
        input_params = dict(concurrency=True, is_proven=True, voice_recording=False)
        account_property.update_safely(**input_params)
        # create history
        store_account_property_history(
            input_params, account_property, current_account_property)


def get_julo_one_is_proven(account):

    from juloserver.account.services.account_related import (
        get_account_property_by_account,
    )

    if not account:
        return False

    account_property = get_account_property_by_account(account)

    if not account_property:
        return False
    return account_property.is_proven


def get_grace_period_days(payment, is_j1=False):
    grace_period_days = Payment.GRACE_PERIOD_DAYS
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LATE_FEE_GRACE_PERIOD,
        is_active=True,
    )

    product_line_code = None

    if isinstance(payment, Payment):
        product_line_code = payment.loan.product.product_line.product_line_code
    elif isinstance(payment, AccountPayment):
        product_line_code = payment.account.last_application.product_line_id

    if product_line_code in {ProductLineCodes.KOPERASI_TUNAS, ProductLineCodes.KOPERASI_TUNAS_45}:
        grace_period_days = 8
    elif product_line_code in {ProductLineCodes.J1, ProductLineCodes.JTURBO} and feature_setting:
        if feature_setting:
            grace_period_days = feature_setting.parameters.get('grade_period', grace_period_days)

    if is_j1:
        return grace_period_days
    application = payment.loan.application
    if not application:
        return grace_period_days
    # check app is axiata?
    axiata_customer_data = AxiataCustomerData.objects.filter(application=application).last()
    if not axiata_customer_data:
        return grace_period_days
    partner = PartnerOriginationData.objects.get_or_none(
        pk=int(axiata_customer_data.distributor))
    if not partner:
        logger.warning('axiata partner not found, customer=%s' % axiata_customer_data.id)
        return grace_period_days

    axiata_grace_period_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AXIATA_DISTRIBUTOR_GRACE_PERIOD,
        is_active=True).last()
    if not axiata_grace_period_setting:
        return grace_period_days
    if axiata_grace_period_setting.parameters:
        distributor_grace_period_setting = axiata_grace_period_setting.parameters.get(
            str(partner.id))
        if distributor_grace_period_setting and distributor_grace_period_setting['is_active']:
            grace_period_days = distributor_grace_period_setting['grace_period_days']

    return grace_period_days


def check_payment_is_blocked_comms(payment, comm_type):
    comms_block = CommsBlocked.objects.filter(loan=payment.loan).last()
    if not comms_block:
        return False
    impacted_account_payments = comms_block.impacted_payments
    payment_blocked_dpd_condition = -7 <= payment.get_dpd <= -0 and \
        payment.get_dpd <= comms_block.block_until
    product_line_code = payment.loan.application.product_line.product_line_code
    delinquent_condition = True
    for payment_id in comms_block.impacted_payments:
        _payment = Payment.objects.get(id=payment_id)
        if _payment.get_dpd > 0:
            delinquent_condition = False
    if comms_block and impacted_account_payments and check_comm_type(comm_type, comms_block) \
            and payment.id in impacted_account_payments and payment_blocked_dpd_condition \
            and product_line_code in ProductLineCodes.mtl() + ProductLineCodes.julo_one() \
            + ProductLineCodes.jturbo() and delinquent_condition:
        logger.info('payment_id %s comms is blocked by comms_block_id %s' % (
            payment.id, comms_block.id))
        return True

    return False


def check_comm_type(comm_type, comms_block):
    comm_type_mapping = {
        CommsConst.PN: comms_block.is_pn_blocked,
        CommsConst.EMAIL: comms_block.is_email_blocked,
        CommsConst.SMS: comms_block.is_sms_blocked,
        CommsConst.COOTEK: comms_block.is_cootek_blocked,
        CommsConst.ROBOCALL: comms_block.is_robocall_blocked
    }
    return comm_type_mapping[comm_type]


def update_is_proven_account_payment_level(account):
    from juloserver.account.services.credit_limit import store_account_property_history

    account_property = account.accountproperty_set.last()
    # check is account ever have Paid off loan
    is_account_ever_proven = AccountPropertyHistory.objects.filter(
        account_property=account_property,
        field_name='is_proven', value_old=False, value_new=True).exists()
    if not is_account_ever_proven:
        return

    if account_property.is_proven:
        return

    total_paid_amount = None
    account_property_history = AccountPropertyHistory.objects.filter(
        account_property=account_property,
        field_name='is_proven', value_old=True, value_new=False).last()
    if account_property_history:
        total_paid_amount = AccountTransaction.objects.filter(
            account=account,
            cdate__gte=account_property_history.cdate,
            transaction_type='payment'
        ).aggregate(total=Sum(F('towards_principal') + F('towards_interest')))['total']

    if not total_paid_amount:
        return

    if total_paid_amount > account_property.proven_threshold:
        current_account_property = list(account.accountproperty_set.values())[-1]
        input_params = dict(is_proven=True)
        account_property.update_safely(**input_params)
        # create history
        store_account_property_history(
            input_params, account_property, current_account_property)


def update_is_proven_bad_customers(account):
    from juloserver.account.services.credit_limit import store_account_property_history

    account_property = account.accountproperty_set.last()
    if not account_property or not account_property.is_proven:
        return

    current_account_property = list(account.accountproperty_set.values())[-1]
    input_params = dict(is_proven=False)
    account_property.update_safely(**input_params)
    # create history
    store_account_property_history(
        input_params, account_property, current_account_property)


def capture_device_geolocation(device, lat, lon, reason):
    device_geo, created = DeviceGeolocation.objects.get_or_create(
        device=device,
        latitude=lat,
        longitude=lon,
        reason=reason
    )

    return device_geo


def check_fraud_hotspot_gps(lat: float, lon: float) -> bool:
    is_active = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUD_HOTSPOT,
        is_active=True
    ).exists()
    if not is_active:
        return False

    fraud_hotspots = FraudHotspot.objects.all()
    if not fraud_hotspots:
        return False

    try:
        if not isinstance(lat, float):
            lat = float(lat)
        if not isinstance(lon, float):
            lon = float(lon)
    except ValueError as e:
        sentry_client.captureException()
        raise JuloException('convert lat lon error')

    for hotspot in fraud_hotspots:
        try:
            if calculate_distance(lat, lon, hotspot.latitude, hotspot.longitude) < hotspot.radius:
                return True
        except Exception:
            sentry_client.captureException()

    return False


def calculate_distance(lat1, lon1, lat2, lon2):
    geod = Geodesic.WGS84
    g = geod.Inverse(lat1, lon1, lat2, lon2)
    return g['s12'] / 1000  # the result format in kilometer


def process_status_change_on_failed_call(autodialer_session):
    autodialer_attempts_for_status_change = {
        ApplicationStatusCodes.DOCUMENTS_VERIFIED: 3,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL: 3,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER: 3
    }

    autodialer_status_change = {
        ApplicationStatusCodes.DOCUMENTS_VERIFIED: 138,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL: 139,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER: 139
    }

    application = autodialer_session.application
    if not application:
        return
    if application.application_status_id not in list(autodialer_attempts_for_status_change.keys()):
        return
    attempts_limit = autodialer_attempts_for_status_change[application.application_status_id]
    if autodialer_session.failed_count >= attempts_limit:
        next_status_code = autodialer_status_change[application.application_status_id]
        process_application_status_change(
            application.id, next_status_code,
            'Autodialer Limit Reached'
        )


def prevent_web_login_cases_check(user, partner_name=None):
    customer = user.customer
    application_set = customer.application_set.all()
    is_multiple_application = (application_set.count() > 1 or customer.can_reapply)
    if is_multiple_application and partner_name not in {
        PartnerConstant.RENTEE, PartnerNameConstant.LINKAJA
    }:
        return False, ErrorMessageConst.APPLIED_APPLICATION

    if partner_name == PartnerConstant.RENTEE:
        application = application_set.select_related('partner', 'workflow').filter(
            workflow__name=WorkflowConst.JULO_ONE,
        ).last()
        if application.workflow.name != WorkflowConst.JULO_ONE:
            return False, ErrorMessageConst.NOT_FOUND
        if not application.partner and application.status != ApplicationStatusCodes.LOC_APPROVED:
            return False, ErrorMessageConst.CANT_ACCESS_RENTEE
        if application.partner:
            if is_multiple_application and \
                    application.partner.name == PartnerConstant.RENTEE:
                return False, ErrorMessageConst.APPLIED_APPLICATION
            if application.partner.name != PartnerConstant.RENTEE and \
                    application.status != ApplicationStatusCodes.LOC_APPROVED:
                return False, ErrorMessageConst.CANT_ACCESS_RENTEE
            if application.partner.name != PartnerConstant.RENTEE and \
                    application.status == ApplicationStatusCodes.LOC_APPROVED:
                feature_partner_eligible_use_rentee = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.PARTNER_ELIGIBLE_USE_RENTEE
                ).last()
                if feature_partner_eligible_use_rentee and \
                        feature_partner_eligible_use_rentee.is_active:
                    if application.partner.id not in feature_partner_eligible_use_rentee.parameters[
                        'partner_ids'
                    ]:
                        return False, ErrorMessageConst.CANT_ACCESS_RENTEE
                else:
                    return False, ErrorMessageConst.CANT_ACCESS_RENTEE
    return True, None


def get_oldest_unpaid_account_payment_ids_within_dpd(due_date_start, due_date_end):
    account_payment_ids = AccountPayment.objects.filter(
        status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        due_date__range=[due_date_end, due_date_start]
    ).order_by('account', 'due_date').distinct('account').values_list('id', flat=True)

    return account_payment_ids


def get_oldest_unpaid_payment_within_dpd(due_date_range1, due_date_range2):
    selected_product_line = ProductLineCodes.mtl() + ProductLineCodes.stl()
    payment_ids = Payment.objects.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        loan__application__customer__can_notify=True,
        due_date__range=[due_date_range2, due_date_range1],
        loan__application__product_line__product_line_code__in=selected_product_line
    ).order_by('loan', 'id').distinct('loan').values_list('id', flat=True)

    return payment_ids


def update_flag_is_5_days_unreachable_and_sendemail(payment_id, is_account_payment=False, is_real_time=False):
    from juloserver.email_delivery.tasks import send_email_is_5_days_unreachable

    today = timezone.localtime(timezone.now()).date()
    no_contact_skip_callresult = [
        'Rejected/Busy',
        'No Answer',
        'Ringing no pick up / Busy',
        'Busy Tone',
        'Answering Machine',
        'Busy Tone',
        'Ringing',
        'Dead Call',
        'Busy',
        'Tidak Diangkat',
        'Answering Machine - System',
        'Abandoned by Customer',
        'Call Failed',
        'Not Active',
        'Unreachable'
    ]
    contact_source = ['mobile phone 1', 'mobile_phone1', 'mobile_phone 1', 'mobile_phone_1',
                      'Mobile phone 1', 'Mobile_phone_1', 'Mobile_Phone_1', 'mobile_phone1_1']
    if is_account_payment:
        payment_or_account_payment = AccountPayment.objects.\
            filter(id=payment_id, status_id__lt=PaymentStatusCodes.PAID_ON_TIME).last()
        skip_trace_histories = SkiptraceHistory.objects.\
            filter(account_payment=payment_or_account_payment, skiptrace__contact_source__in=contact_source).\
            order_by('id')
    else:
        payment_or_account_payment = Payment.objects.\
            filter(id=payment_id, payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME).last()
        skip_trace_histories = SkiptraceHistory.objects.\
            filter(payment=payment_or_account_payment, skiptrace__contact_source__in=contact_source).\
            order_by('id')

    if (payment_or_account_payment is None) or (skip_trace_histories is None):
        logger.warn({
            'action': 'is_5_days_unreachable',
            'is_account_payment': is_account_payment,
            'payment': payment_id,
            'message': "payment or skiptrace history empty",
            'is_real_time': is_real_time
        })
        return


    dpd = payment_or_account_payment.dpd if is_account_payment else payment_or_account_payment.get_dpd
    current_bucket = get_bucket_status(dpd)
    if current_bucket not in range(1,5):
        return

    range1_ago = today - timedelta(days=5)
    range2_ago = today

    skip_trace_histories_5days = skip_trace_histories.filter(cdate__date__range=[range1_ago, range2_ago])
    skip_trace_histories_5days_contacted = skip_trace_histories_5days.exclude(
        call_result__name__in=no_contact_skip_callresult)
    skip_trace_histories_5days_nocontact = skip_trace_histories_5days.filter(
        call_result__name__in=no_contact_skip_callresult)

    # flag is_5_days_unreachable
    update_flag = None

    if skip_trace_histories_5days_nocontact:
        if skip_trace_histories_5days_nocontact.count() >= 5:
            skiptrace_5days_in_a_row = skip_trace_histories_5days_nocontact.\
                extra(select={'cdate_day': "EXTRACT(day FROM skiptrace_history.cdate)"}).\
                values('cdate_day').annotate(count_items=Count('cdate'))
            if skiptrace_5days_in_a_row.count() >= 5:
                is_5_days_unreachable = True
                update_flag = True

    if skip_trace_histories_5days_contacted:
        is_5_days_unreachable = False
        update_flag = True

    if update_flag is None:
        logger.info({
            'action': 'is_5_days_unreachable',
            'is_account_payment': is_account_payment,
            'payment': payment_or_account_payment.id,
            'update_flag': update_flag,
            'is_real_time': is_real_time
        })
        return

    if is_account_payment:
        payment_or_account_payment.account.update_safely(is_5_days_unreachable=is_5_days_unreachable)
    else:
        payment_or_account_payment.loan.update_safely(is_5_days_unreachable=is_5_days_unreachable)

    if (not is_real_time) and (is_5_days_unreachable is True):
        is_email_sent_in_same_bucket = check_no_contact_email_already_sent_in_same_bucket(payment_or_account_payment, is_account_payment, current_bucket)
        if not is_email_sent_in_same_bucket:
            send_email_is_5_days_unreachable.apply_async((payment_or_account_payment.id, is_account_payment),
                                                             countdown=settings.DELAY_FOR_REALTIME_EVENTS)

        logger.info({
            'action': 'is_5_days_unreachable',
            'is_account_payment': is_account_payment,
            'payment': payment_or_account_payment.id,
            'is_email_sent_in_same_bucket': is_email_sent_in_same_bucket,
            'is_real_time': is_real_time,
            'range1_ago': range1_ago,
            'range2_ago': range2_ago
        })
        return payment_or_account_payment

    logger.warn({
        'action': 'is_5_days_unreachable',
        'is_account_payment': is_account_payment,
        'payment': payment_or_account_payment.id,
        'is_5_days_unreachable': "Not satisfied",
        'is_real_time': is_real_time,
        'range1_ago': range1_ago,
        'range2_ago': range2_ago
    })
    return payment_or_account_payment


def check_no_contact_email_already_sent_in_same_bucket(payment_or_account_payment, is_account_payment, current_bucket):
    due_date = payment_or_account_payment.due_date
    bucket_range = {
                1: [BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to']],
                2: [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']],
                3: [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']],
                4: [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']]
             }

    template_code = "call_not_answered_email"
    range2_ago = due_date + timedelta(days=bucket_range[current_bucket][0])
    range1_ago = due_date + timedelta(days=bucket_range[current_bucket][1] + 1)

    range2_datetime = datetime.combine(range2_ago, time(0, 0, 0))
    range1_datetime = datetime.combine(range1_ago, time(0, 0, 0))

    filter_ = dict(
        template_code=template_code,
        cdate__gte=range2_datetime,
        cdate__lt=range1_datetime,
    )
    if is_account_payment:
        filter_['account_payment'] = payment_or_account_payment
    else:
        filter_['payment'] = payment_or_account_payment

    email_history = EmailHistory.objects.\
        filter(**filter_).order_by('cdate')

    logger.info({
        'action': 'is_5_days_unreachable',
        'is_account_payment': is_account_payment,
        'payment': payment_or_account_payment.id,
        'email_check': 'check_no_contact_email_already_sent_in_same_bucket',
        'email_history': email_history,
        'date_from': range2_ago,
        'date_to': range1_ago
    })

    if email_history:
        return True
    return False


def get_wa_message_is_5_days_unreachable(application):
    fullname = application.full_name_only
    title = application.gender_title
    context = {
        'fullname': fullname,
        'title': title
    }
    template_code = 'wa_call_not_answered'

    message = render_to_string(template_code + '.txt', context=context)
    return message


def update_flag_is_broken_ptp_plus_1(payment_or_account_payment,
                                     is_account_payment=False,
                                     turn_off_broken_ptp_plus_1=False):
    if payment_or_account_payment:
        if turn_off_broken_ptp_plus_1:
            is_broken_ptp_plus_1 = False
        else:
            yesterday = timezone.localtime(timezone.now()).date() - timedelta(days=1)
            if payment_or_account_payment.ptp_date == yesterday:
                filter_ = dict(
                    ptp_date=payment_or_account_payment.ptp_date
                )
                if is_account_payment:
                    filter_['account_payment'] = payment_or_account_payment
                else:
                    filter_['payment'] = payment_or_account_payment

                ptp_object = PTP.objects.filter(**filter_).\
                    filter(Q(ptp_status__isnull=True) | Q(ptp_status='Not Paid'))
                if ptp_object:
                    is_broken_ptp_plus_1 = True
                else:
                    logger.info(
                        {
                            'action': 'is_broken_ptp_plus_1',
                            'turn_off_broken_ptp_plus_1': turn_off_broken_ptp_plus_1,
                            'is_account_payment': is_account_payment,
                            'payment': payment_or_account_payment.id,
                            'flag': "error: ptp filter empty",
                            'ptp_date': yesterday,
                        }
                    )
                    return
            else:
                logger.info(
                    {
                        'action': 'is_broken_ptp_plus_1',
                        'turn_off_broken_ptp_plus_1': turn_off_broken_ptp_plus_1,
                        'is_account_payment': is_account_payment,
                        'payment': payment_or_account_payment.id,
                        'flag': "error:date check failed",
                        'ptp_date': payment_or_account_payment.ptp_date,
                        'date_check': yesterday,
                    }
                )
                return

        if is_account_payment:
            account = payment_or_account_payment.account
            existing_is_broken_ptp_plus_1 = account.is_broken_ptp_plus_1
            if existing_is_broken_ptp_plus_1 is not is_broken_ptp_plus_1:
                account.update_safely(is_broken_ptp_plus_1=is_broken_ptp_plus_1)
        else:
            loan = payment_or_account_payment.loan
            existing_is_broken_ptp_plus_1 = loan.is_broken_ptp_plus_1
            if existing_is_broken_ptp_plus_1 is not is_broken_ptp_plus_1:
                loan.update_safely(is_broken_ptp_plus_1=is_broken_ptp_plus_1)

        logger.info(
            {
                'action': 'is_broken_ptp_plus_1',
                'turn_off_broken_ptp_plus_1': turn_off_broken_ptp_plus_1,
                'is_account_payment': is_account_payment,
                'payment': payment_or_account_payment.id,
                'flag': is_broken_ptp_plus_1,
            }
        )


def get_wa_message_is_broken_ptp_plus_1(payment_or_account_payment, application):
    fullname = application.full_name_only
    title = application.gender_title

    ptp_amount = payment_or_account_payment.ptp_amount
    ptp_date = format_date(payment_or_account_payment.ptp_date, 'd-MMM-yyyy', locale='id_ID')

    context = {
        'fullname': fullname,
        'title': title,
        'ptp_amount': display_rupiah(ptp_amount),
        'ptp_date': ptp_date,
    }
    template_code = 'wa_is_broken_ptp_plus1'

    message = render_to_string(template_code + '.txt', context=context)
    return message


def send_email_fraud_mitigation(
    application, email_content, template_code, email_subject="", email_to=""
):
    if not email_content:
        return

    client = get_julo_email_client()
    email_subject= email_subject if email_subject else "Pemberitahuan Atas Akun JULO Anda"
    email_to = email_to if email_to else application.email
    email_from = "collections@julo.co.id"

    status, _, headers = client.send_email(email_subject, email_content, email_to, email_from)

    if status == 202:
        message_id = headers['X-Message-Id']
        application = application
        customer = application.customer

        email_history = EmailHistory.objects.create(
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=email_to,
            subject=email_subject,
            message_content=email_content,
            template_code=template_code,
        )

        logger.info(
            {
                'action': "send_email_fraud_mitigation",
                'status': status,
                'message_id': message_id,
                'application_id': application.id,
            }
        )

        return email_history

    else:
        logger.warn({'status': status, 'message_id': headers['X-Message-Id']})

    return False


def send_magic_link_sms(application, phone_number, generated_magic_link):
    mobile_number = format_e164_indo_phone_number(phone_number)
    get_julo_sms = get_julo_sms_client()
    template_code = "cs_change_number_verification"
    message_content, api_response = get_julo_sms.sms_magic_link(
        mobile_number, generated_magic_link, template_code
    )

    if api_response['status'] != '0':
        return

    customer = application.customer
    sms_history = create_sms_history(
        response=api_response,
        customer=customer,
        application=application,
        status='sent',
        message_content=message_content,
        phone_number_type="mobile_phone_1",
        template_code=template_code,
        category="magic link sms",
        to_mobile_phone=phone_number,
    )

    return sms_history


# bttc = Best time to call model, FC = final call models
def sort_bttc_by_fc(bttc_grouped_data_qs, dpd):
    if not bttc_grouped_data_qs:
        return []

    current_date = timezone.localtime(timezone.now()).date()
    account_payment_ids = list(bttc_grouped_data_qs.values_list('account_payment', flat=True))
    ordered_results = PdCollectionModelResult.objects.filter(
        range_from_due_date__in=dpd,
        account_payment_id__in=account_payment_ids,
        cdate__date=current_date,
    ).order_by('sort_rank')
    not_ordered_rank_account_payments = bttc_grouped_data_qs.exclude(
        account_payment_id__in=list(ordered_results.values_list('account_payment_id', flat=True))
    )
    results = list(ordered_results) + list(not_ordered_rank_account_payments)
    return results


def update_grab_phone(application, phone_number):
    from juloserver.loan.services.loan_related import (
        update_loan_status_and_loan_history,
    )
    from juloserver.grab.segmented_tasks.disbursement_tasks import (
        trigger_create_or_update_ayoconnect_beneficiary,
    )

    customer = application.customer
    formatted_phone_number = format_nexmo_voice_phone_number(phone_number)
    with transaction.atomic():
        existing_grab_customer = GrabCustomerData.objects.filter(
            grab_validation_status=True, phone_number=formatted_phone_number
        )
        if existing_grab_customer.filter(customer__isnull=False).exists():
            raise GrabLogicException("Customer Already registered " "with new_phone_number")
        else:
            existing_grab_customer.update(
                grab_validation_status=False, otp_status=GrabCustomerData.UNVERIFIED
            )

        grab_customer_data = GrabCustomerData.objects.filter(customer=customer).last()
        application = customer.application_set.filter(workflow__name=WorkflowConst.GRAB).last()
        if not application:
            application = customer.application_set.last()
        ApplicationFieldChange.objects.create(
            application=application,
            field_name='mobile_phone_1',
            old_value=application.mobile_phone_1,
            new_value=formatted_phone_number,
            agent=None,
        )
        application.update_safely(mobile_phone_1=formatted_phone_number)

        CustomerFieldChange.objects.create(
            customer=customer,
            field_name='phone',
            old_value=customer.phone,
            new_value=formatted_phone_number,
            application_id=application.id,
            changed_by=None,
        )
        customer.phone = formatted_phone_number
        customer.save(update_fields=['phone'])

        loans = Loan.objects.filter(
            customer=customer,
            account__account_lookup__workflow__name=WorkflowConst.GRAB,
            loan_status_id=LoanStatusCodes.INACTIVE,
        )
        for loan in loans:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                change_by_id=customer.user.id,
                change_reason="Customer phone number changed",
            )
        new_hashed_phone = GrabUtils.create_user_token(formatted_phone_number)
        grab_customer_data.phone_number = formatted_phone_number
        grab_customer_data.hashed_phone_number = new_hashed_phone
        grab_customer_data.save(update_fields=['phone_number', 'hashed_phone_number'])
        trigger_create_or_update_ayoconnect_beneficiary.delay(customer.id, update_phone=True)


def remove_character_by_regex(string, regex):
    new_string = re.sub(regex, '', string)
    return new_string


def send_custom_sms_account(account, phone_number, phone_type, category,
                                             text, template_code):
    mobile_number = format_e164_indo_phone_number(phone_number)
    # call sms client
    get_julo_sms = get_julo_sms_client()
    message_content, api_response = get_julo_sms.send_sms(mobile_number, text)
    api_response = api_response['messages'][0]
    if api_response['status'] != '0':
        raise SmsNotSent(
            {
                'send_status': api_response['status'],
                'account_payment_id': account.id,
            }
        )
    application = account.last_application
    customer = account.customer
    sms = create_sms_history(
        response=api_response,
        customer=customer,
        application=application,
        payment=None,
        account=account,
        status='sent',
        message_content=message_content,
        phone_number_type=phone_type,
        template_code=template_code,
        category=category,
        to_mobile_phone=format_e164_indo_phone_number(mobile_number),
    )


def get_application_phone_number(application):
    """
    Get a valid phone number for an application.

    :param application: Application objects
    :return: string, A valid E164 Phone number, ex: +628123456789
    :raises: InvalidPhoneNumberError, if the phone number is not valid or not found.
    """
    logger_data = {
        "action": "get_application_phone_number",
        "application_id": application.id,
    }
    if application.product_line_code == ProductLineCodes.DANA:
        if application.account and application.account.dana_customer_data:
            mobile_number = detokenize_partnership_phone_number(
                application.account.dana_customer_data,
                application.account.dana_customer_data.customer.customer_xid,
            )
            return format_valid_e164_indo_phone_number(mobile_number)
        elif application.customer and application.customer.dana_customer_data:
            mobile_number = detokenize_partnership_phone_number(
                application.customer.dana_customer_data, application.customer.customer_xid
            )
            return format_valid_e164_indo_phone_number(mobile_number)
        else:
            mobile_number = detokenize_partnership_phone_number(
                application.dana_customer_data, application.dana_customer_data.customer.customer_xid
            )
            return format_valid_e164_indo_phone_number(mobile_number)
    try:
        application_detokenized = collection_detokenize_sync_object_model(
            PiiSource.APPLICATION,
            application,
            application.customer.customer_xid,
            ['mobile_phone_1'],
        )
        return format_valid_e164_indo_phone_number(application_detokenized.mobile_phone_1)
    except InvalidPhoneNumberError:
        logger.warning(
            {
                "message": "Invalid application phone number.",
                **logger_data,
            }
        )

    customer = application.customer
    try:
        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['phone'],
        )
        logger_data.update(customer_id=customer.id)
        return format_valid_e164_indo_phone_number(customer_detokenized.phone)
    except InvalidPhoneNumberError:
        logger.warning(
            {
                "message": "Invalid customer phone number.",
                **logger_data,
            }
        )

    skiptrace = Skiptrace.objects.filter(
        customer_id=application.customer_id,
        contact_source='mobile_phone_1',
    ).last()
    skiptrace_detokenized = collection_detokenize_sync_object_model(
        PiiSource.SKIPTRACE,
        skiptrace,
        None,
        ['phone_number'],
        PiiVaultDataType.KEY_VALUE,
    )
    if not skiptrace:
        raise InvalidPhoneNumberError('Customer does not have mobile_phone_1 skiptrace')

    return format_valid_e164_indo_phone_number(skiptrace_detokenized.phone_number)


def detokenize_partnership_phone_number(dana_customer_data, customer_xid):
    detokenize_phone_number = partnership_detokenize_sync_object_model(
        PiiSource.DANA_CUSTOMER_DATA,
        dana_customer_data,
        customer_xid,
        ['mobile_number'],
    )

    return detokenize_phone_number.mobile_number


def get_used_wallet_customer_for_paid_checkout_experience(customer, account_payments):
    due_amount = 0
    for account_payment in account_payments:
        due_amount += account_payment.due_amount

    used_wallet_amount = customer.wallet_balance_available
    if due_amount >= used_wallet_amount:
        return used_wallet_amount

    return due_amount


def get_expire_cashback_date_setting():
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EXPIRE_CASHBACK_DATE_SETTING, is_active=True
    ).last()
    if fs:
        month = fs.parameters.get('month') or 12
        day = fs.parameters.get('day') or 31
        return timezone.localtime(datetime(year=datetime.now().year, month=month, day=day)).date()

    return None


def log_cashback_task_dpd(event, customer_id, dict_abnormal):
    if dict_abnormal:
        sentry_client.captureMessage(
            {
                'error': 'abnormal case cashback account payment',
                'task': 'system_used_on_payment_dpd',
                'event': event,
                'customer_id': customer_id,
                **dict_abnormal,
            }
        )
    else:
        logger.info(
            {
                'action': 'use_cashback_pay_account_payment_dpd_by_batch_' + event,
                'customer': customer_id,
            }
        )


def handle_notify_moengage_after_payment_method_change(payment_method):
    from juloserver.moengage.services.use_cases import (
        send_user_attributes_to_moengage_for_va_change,
    )

    customer_id = payment_method.customer_id
    execute_after_transaction_safely(
        lambda: send_user_attributes_to_moengage_for_va_change.delay(customer_id)
    )

    logger.info(
        {
            'action': 'finish run notify_moengage_after_payment_method_change',
            'customer_id': customer_id,
        }
    )


def create_julo_application(
    customer,
    nik=None,
    app_version=None,
    web_version=None,
    email=None,
    partner=None,
    phone=None,
    onboarding_id=None,
    workflow=None,
    product_line=None,
):
    return Application.objects.create(
        customer=customer,
        ktp=nik,
        app_version=app_version,
        web_version=web_version,
        email=email,
        partner=partner,
        workflow=workflow,
        product_line=product_line,
        mobile_phone_1=phone,
        onboarding_id=onboarding_id,
    )


def pull_late_fee_earlier(payment, late_date_rule):
    from juloserver.account.services.account_related import get_experiment_group_data

    # for now late fee earlier eligible for J1 and JTurbo only
    # this function will implement late fee to dpd 1 instead of dpd 5
    # only implemented when late fee applied still 0
    if (
        payment.is_julo_one_payment or payment.is_julo_starter_payment
    ) and payment.late_fee_applied == 0:
        # account and account_payment should exist,
        # since on begin function have validation for j1 and jturbo
        account_id = payment.account_payment.account_id
        _, experiment_data = get_experiment_group_data(
            MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT, account_id
        )
        if experiment_data and experiment_data.group == 'experiment':
            return (relativedelta(days=1), 1)

    return late_date_rule


def record_data_for_cashback_new_scheme(
    payment, new_wallet_history, counter, reason, new_cashback_percentage=0
):
    account_payment = payment.account_payment
    loan = payment.loan
    cashback_pct = loan.product.cashback_payment_pct if loan.product else 0.0
    CashbackCounterHistory.objects.create(
        payment=payment,
        account_payment=account_payment,
        cashback_percentage=(cashback_pct * new_cashback_percentage),
        customer_wallet_history=new_wallet_history,
        consecutive_payment_number=payment.payment_number,
        counter=counter,
        reason=reason,
    )


def create_mf_axiata_skrtp(loan, application):
    from juloserver.portal.object.bulk_upload.services import create_mf_sphp

    create_mf_sphp(application, loan)
