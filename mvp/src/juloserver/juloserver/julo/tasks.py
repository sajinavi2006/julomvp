from __future__ import absolute_import, division

import csv
import importlib
import io
import json
import logging
import math
import os
import random
from builtins import next, range, setattr, str
from collections import namedtuple
from datetime import date, datetime, timedelta
from datetime import time as datetime_time_alias
from functools import reduce
from itertools import chain, islice
from operator import or_
from django.db.models import Q

import dateutil.parser
import requests
import unicodecsv
from babel.dates import format_date
from babel.numbers import format_number
from bulk_update.helper import bulk_update
from celery import task
from croniter import croniter
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, transaction
from django.db.models import Count, F, Max, Q
from django.db.utils import IntegrityError
from django.template.loader import render_to_string
from django.utils import timezone
from past.utils import old_div

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.account.services.account_related import process_change_account_status
from juloserver.account.tasks.scheduled_tasks import (
    update_account_transaction_for_late_fee_event,
)
from juloserver.account_payment.models import AccountPayment, OldestUnpaidAccountPayment
from juloserver.account_payment.services.pause_reminder import (
    check_account_payment_is_blocked_comms,
)
from juloserver.ana_api.models import FDCInquiryPrioritizationReason2, CustomerHighLimitUtilization
from juloserver.api_token.authentication import generate_new_token
from juloserver.api_token.models import ExpiryToken
from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagStatus,
)
from juloserver.application_flow.services import (
    is_experiment_application,
    check_has_path_tag,
)
from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    is_experiment_group_autodebet,
)
from juloserver.autodebet.tasks import store_autodebet_streamline_experiment
from juloserver.cashback.models import CashbackEarned
from juloserver.cashback.services import get_pending_overpaid_apps
from juloserver.collectionbucket.models import CollectionRiskVerificationCallList
from juloserver.customer_module.constants import (
    ADJUST_AUTO_APPROVE_DATE_RELEASE,
    DELETION_REQUEST_AUTO_APPROVE_DAY_LIMIT,
    AccountDeletionRequestStatuses,
)
from juloserver.customer_module.models import AccountDeletionRequest
from juloserver.customer_module.services.crm_v1 import (
    in_app_deletion_customer_requests,
)
from juloserver.customer_module.services.customer_related import (
    update_cashback_balance_status,
)
from juloserver.customer_module.services.device_related import get_device_repository
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_original_value,
    is_application_status_deleteable,
)
from juloserver.dana.constants import DanaFDCResultStatus
from juloserver.dana.models import DanaCustomerData, DanaFDCResult
from juloserver.fdc.constants import FDCFailureReason
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.fdc.services import (
    get_and_save_fdc_data,
    get_fdc_inquiry_queue_size,
    get_fdc_inquiry_from_ana_filtered_by_date,
    check_if_fdc_inquiry_exist_filtered_by_date,
)
from juloserver.followthemoney.models import LenderBucket, LenderCurrent
from juloserver.grab.tasks import send_grab_failed_deduction_slack
from juloserver.julo.constants import (
    APP_STATUS_GRAB_SKIP_PRIORITY,
    APP_STATUS_GRAB_WITH_PRIORITY,
    APP_STATUS_J1_SKIP_PRIORITY,
    APP_STATUS_J1_WITH_PRIORITY,
    APP_STATUS_PARTNERSHIP_AGENT_ASSISTED,
    APP_STATUS_J1_AGENT_ASSISTED,
    APP_STATUS_SKIP_PRIORITY,
    APP_STATUS_SKIP_PRIORITY_NO_J1_NO_GRAB,
    APP_STATUS_WITH_PRIORITY,
    APP_STATUS_WITH_PRIORITY_NO_J1_NO_GRAB,
    APPLICATION_STATUS_EXPIRE_PATH,
    JULO_ANALYTICS_DB,
    LOAN_STATUS,
    LOAN_STATUS_J1,
    RETRY_EMAIL_MINUTE,
    RETRY_PN_MINUTE,
    TARGET_CUSTOMER,
    TARGET_PARTNER,
    AgentAssignmentTypeConst,
    AutoDebetComms,
    BNIVAConst,
    CashbackTransferConst,
    EmailDeliveryAddress,
    ExperimentConst,
    ExperimentDate,
    FeatureNameConst,
    LocalTimeType,
    NexmoRobocallConst,
    ReminderTypeConst,
    VendorConst,
    WaiveCampaignConst,
    OnboardingIdConst,
)
from juloserver.julo.decorators import delay_voice_call
from juloserver.julo.exceptions import (
    JuloException,
    SmsNotSent,
)
from juloserver.julo.management.commands.send_permata_prefix_notification import (
    Command as NotificationCommand,
)
from juloserver.julo.models import (
    PTP,
    AccountingCutOffDate,
    Agent,
    Application,
    ApplicationFieldChange,
    ApplicationHistory,
    ApplicationInstallHistory,
    ApplicationNote,
    AuthUserFieldChange,
    Autodialer122Queue,
    AutoDialerRecord,
    BniVirtualAccountSuffix,
    CashbackTransferTransaction,
    CreditScore,
    CrmNavlog,
    Customer,
    CustomerFieldChange,
    CustomerRemoval,
    CustomerWalletHistory,
    DashboardBuckets,
    Device,
    DeviceIpHistory,
    Disbursement,
    Document,
    DokuTransaction,
    EmailHistory,
    Experiment,
    ExperimentSetting,
    FaceRecognition,
    FDCInquiry,
    FDCInquiryRun,
    FDCRiskyHistory,
    FeatureSetting,
    Image,
    KycRequest,
    Loan,
    MandiriVirtualAccountSuffix,
    MassMoveApplicationsHistory,
    NotificationTemplate,
    Offer,
    OnboardingEligibilityChecking,
    OtpRequest,
    PartnerReportEmail,
    Payment,
    PaymentEvent,
    PaymentMethod,
    PaymentMethodLookup,
    PredictiveMissedCall,
    Skiptrace,
    SkiptraceHistory,
    SmsHistory,
    Sum,
    VendorDataHistory,
    VirtualAccountSuffix,
    VoiceRecord,
    WarningLetterHistory,
    WarningUrl,
    WlLevelConfig,
    Workflow,
    XidLookup,
    CommsRetryFlag,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.services2 import (
    encrypt,
    get_customer_service,
    get_redis_client,
)
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.workflows2.tasks import update_status_apps_flyer_task
from juloserver.julocore.constants import RedisWhiteList
from juloserver.julocore.python2.utils import py2round
from juloserver.julocore.utils import (
    capture_exception,
    get_minimum_model_id,
)
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.loan.services.views_related import process_image_upload_julo_one
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.services.loan_related import (
    get_payments_refinancing_pending_by_dpd,
)
from juloserver.minisquad.constants import (
    ExperimentConst as MinisquadExperimentConstants,
)
from juloserver.minisquad.tasks2.notifications import write_data_to_experiment_group
from juloserver.minisquad.utils import (
    batch_pk_query_with_cursor_with_custom_db,
    batch_pk_query_with_cursor,
)
from juloserver.moengage.constants import (
    INHOUSE,
    UNSENT_MOENGAGE,
    UNSENT_MOENGAGE_EXPERIMENT,
)
from juloserver.moengage.services.data_constructors import (
    construct_user_attributes_for_realtime_basis,
)
from juloserver.moengage.services.use_cases import (
    update_moengage_for_wl_url_data,
)
from juloserver.monitors.notifications import (
    get_slack_bot_client,
    notify_application_status_info,
    notify_application_status_info_to_reporter,
    notify_cashback_abnormal,
    notify_count_cashback_delayed,
    notify_failure,
    notify_sepulsa_balance_low,
    send_slack_bot_message,
)
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.partnership.models import (
    PartnershipApplicationFlag,
    PartnershipCustomerData,
)
from juloserver.pn_delivery.models import PNDelivery
from juloserver.portal.object.app_status.utils import courtesy_call_range
from juloserver.promo.models import PromoCode, WaivePromo
from juloserver.sdk.constants import (
    LIST_PARTNER,
    LIST_PARTNER_EXCLUDE_PEDE,
    PARTNER_PEDE,
)
from juloserver.minisquad.constants import SkiptraceContactSource
from juloserver.streamlined_communication.constant import (
    CardProperty,
    ImageType,
    RedisKey,
    autodebet_pn_dpds,
    autodebet_sms_dpds,
    CeleryTaskLocker,
)
from juloserver.streamlined_communication.constant import (
    ExperimentConst as StreamlinedExperimentConst,
)
from juloserver.application_flow.constants import AnaServerFormAPI

# dont 'delete this julocenterixclient because it is used to trigger the task

from juloserver.streamlined_communication.services import (
    is_holiday,
    determine_julo_gold_for_streamlined_communication,
)
from juloserver.urlshortener.models import ShortenedUrl
from juloserver.utilities.models import SlackEWABucket
from juloserver.utilities.services import get_bucket_emotion, get_bucket_slack_user
from juloserver.warning_letter.services import create_mtl_url

from ..apiv2.models import AutoDataCheck
from ..application_flow.constants import JuloOneChangeReason
from ..minisquad.services import get_caller_experiment_setting
from ..minisquad.services2.growthbook import (
    get_experiment_setting_data_on_growthbook,
)
from ..streamlined_communication.constant import (
    CommunicationPlatform,
    Product,
    TemplateCode,
)
from ..streamlined_communication.models import StreamlinedCommunication
from ..streamlined_communication.services import (
    filter_streamlined_based_on_partner_selection,
    get_list_dpd_experiment,
    get_pn_action_buttons,
    is_ptp_payment_already_paid,
    process_sms_message_j1,
    process_streamlined_comm_context_base_on_model_and_parameter,
    process_streamlined_comm_context_for_ptp,
    process_streamlined_comm_email_subject,
    process_streamlined_comm_without_filter,
    take_out_account_payment_for_experiment_dpd_minus_7,
)
from .clients import (
    get_julo_autodialer_client,
    get_julo_email_client,
    get_julo_pn_client,
    get_julo_sentry_client,
    get_julo_sms_client,
    get_julo_whatsapp_client,
    get_voice_client,
    get_julo_whatsapp_client_go,
)
from .constants import (
    VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT,
    XID_LOOKUP_UNUSED_MIN_COUNT,
    WorkflowConst,
    RETRY_SMS_J1_MINUTE,
    CommsRetryFlagStatus,
    XID_MAX_COUNT,
)
from .formulas import (
    compute_xid,
    filter_due_dates_by_pub_holiday,
    filter_due_dates_by_weekend,
)
from .payment_methods import PaymentMethodCodes
from .product_lines import ProductLineCodes
from .services import (
    check_good_customer_or_not,
    check_payment_is_blocked_comms,
    check_risky_customer,
    check_unprocessed_doku_payments,
    choose_number_to_robocall,
    create_application_checklist,
    get_expiry_date,
    get_extra_context,
    get_lebaran_2020_users,
    get_oldest_payment_due,
    get_payment_due_date_by_delta,
    get_payment_ids_for_wa_experiment_october,
    get_warning_letter_google_calendar_attachment,
    process_image_upload,
    process_thumbnail_upload,
    ptp_update,
    send_data_to_collateral_partner,
    send_lebaran_2020_email_subtask,
    send_lebaran_2020_pn_subtask,
    send_lebaran_2020_sms_subtask,
    update_flag_is_broken_ptp_plus_1,
    update_late_fee_amount,
    update_loan_and_payments,
)
from .services2 import get_agent_service, get_payment_event_service
from .services2.agent import convert_featurename_to_agentassignment_type
from .services2.experiment import (
    get_experiment_setting_by_code,
    payment_experiment_daily,
)
from .services2.payment_event import waiver_campaign_promo
from .services2.voice import (
    mark_voice_account_payment_reminder,
    mark_voice_account_payment_reminder_grab,
    mark_voice_payment_reminder,
)
from .services2.xendit import XenditConst
from .statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.credgenics.services.utils import (
    is_comms_block_active,
    get_credgenics_account_payment_ids,
    is_application_owned_by_credgenics_customer,
    is_account_payment_owned_by_credgenics_customer,
)
from juloserver.credgenics.constants.feature_setting import (
    CommsType,
)
from .utils import (
    chunk_array,
    display_rupiah,
    execute_after_transaction_safely,
    format_e164_indo_phone_number,
    have_pn_device,
    post_anaserver,
    upload_file_to_oss,
)
from juloserver.api_token.models import ExpiryToken
from juloserver.api_token.authentication import generate_new_token

from juloserver.streamlined_communication.constant import ImageType

# dont 'delete this julocenterixclient because it is used to trigger the task
from juloserver.streamlined_communication.services import is_holiday
from juloserver.streamlined_communication.constant import (
    ExperimentConst as StreamlinedExperimentConst,
    CommunicationTypeConst,
)
from juloserver.minisquad.tasks2.notifications import write_data_to_experiment_group
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from juloserver.account.services.account_related import process_change_account_status
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_email_from_applications,
    get_phone_from_applications,
    get_nik_from_applications,
    get_original_value,
    check_if_customer_is_elgible_to_delete,
    is_application_status_deleteable,
)
from bulk_update.helper import bulk_update
from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    loan_status_not_allowed,
    forbidden_account_status,
    forbidden_application_status_account_deletion,
)
from juloserver.customer_module.models import AccountDeletionRequest

from juloserver.customer_module.services.crm_v1 import (
    in_app_deletion_customer_requests,
)
from juloserver.routing.decorators import use_db_replica
from juloserver.julolog.julolog import JuloLog
from juloserver.otp.constants import SessionTokenAction
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.omnichannel.services.utils import (
    get_omnichannel_comms_block_active,
    get_exclusion_omnichannel_account_ids,
    is_application_owned_by_omnichannel_customer,
    is_account_payment_owned_by_omnichannel_customer,
)
from juloserver.omnichannel.services.settings import OmnichannelIntegrationSetting
from juloserver.pii_vault.constants import PiiSource
from juloserver.monitors.notifications import send_message_normal_format
from juloserver.streamlined_communication.models import Holiday
from juloserver.application_form.constants import ExpireDayForm

logger = logging.getLogger(__name__)
juloLog = JuloLog(__name__)
MTL = (ProductLineCodes.MTL1, ProductLineCodes.MTL2)
STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)
PEDE = (
    ProductLineCodes.PEDEMTL1,
    ProductLineCodes.PEDEMTL2,
    ProductLineCodes.PEDESTL1,
    ProductLineCodes.PEDESTL2,
)

DPD1_DPD29 = AgentAssignmentTypeConst.DPD1_DPD29
DPD30_DPD59 = AgentAssignmentTypeConst.DPD30_DPD59
DPD60_DPD89 = AgentAssignmentTypeConst.DPD60_DPD89
DPD90PLUS = AgentAssignmentTypeConst.DPD90PLUS
AGENT_ASSIGNMENT_DPD1_DPD29 = FeatureNameConst.AGENT_ASSIGNMENT_DPD1_DPD29
AGENT_ASSIGNMENT_DPD30_DPD59 = FeatureNameConst.AGENT_ASSIGNMENT_DPD30_DPD59
AGENT_ASSIGNMENT_DPD60_DPD89 = FeatureNameConst.AGENT_ASSIGNMENT_DPD60_DPD89
AGENT_ASSIGNMENT_DPD90PLUS = FeatureNameConst.AGENT_ASSIGNMENT_DPD90PLUS
AGENT_ASSIGNMENT_DPD1_DPD15 = FeatureNameConst.AGENT_ASSIGNMENT_DPD1_DPD15
AGENT_ASSIGNMENT_DPD16_DPD29 = FeatureNameConst.AGENT_ASSIGNMENT_DPD16_DPD29
AGENT_ASSIGNMENT_DPD30_DPD44 = FeatureNameConst.AGENT_ASSIGNMENT_DPD30_DPD44
AGENT_ASSIGNMENT_DPD45_DPD59 = FeatureNameConst.AGENT_ASSIGNMENT_DPD45_DPD59
ACBYPASS_141 = ExperimentConst.ACBYPASS141
TEMPLATES = {
    "1": {
        "email": "email.html",
        "sms": "sms_agreement.txt",
        'url': settings.AGREEMENT_WEBSITE,
        "subject": "Surat Peringatan Pertama",
    },
    "2": {
        "email": "email_warning_2.html",
        "sms": "sms_agreement_2.txt",
        "url": settings.AGREEMENT_WEBSITE_2,
        "subject": "Surat Peringatan Kedua",
    },
    "3": {
        "email": "email_warning_3.html",
        "sms": "sms_agreement_3.txt",
        "url": settings.AGREEMENT_WEBSITE_3,
        "subject": "Surat Peringatan Ketiga",
    },
}
WARNING_TYPE = "1"


@task(name='update_payment_status_subtask')
def update_payment_status_subtask(payment_id):
    """sub task to execute 1payment/1worker"""
    # double check to prevent race condition
    from juloserver.account_payment.tasks.scheduled_tasks import (
        update_account_payment_status_subtask,
    )

    with transaction.atomic():
        unpaid_payment = Payment.objects.select_related('loan__account__account_lookup').get(
            pk=payment_id
        )
        if unpaid_payment.status in PaymentStatusCodes.paid_status_codes():
            return

        payment_history = {}

        if unpaid_payment.loan.status >= LoanStatusCodes.CURRENT:
            payment_history['payment_old_status_code'] = unpaid_payment.status

        updated = unpaid_payment.update_status_based_on_due_date()
        if not updated:
            logger.debug({"payment": unpaid_payment.id, "updated": updated})
            return

        if unpaid_payment.due_late_days >= 5:
            update_cashback_balance_status(unpaid_payment.loan.customer)

        unpaid_payment.save(update_fields=['payment_status', 'udate'])
        if (
            unpaid_payment.loan
            and unpaid_payment.loan.account
            and unpaid_payment.loan.account.account_lookup.workflow.name == WorkflowConst.GRAB
        ):
            execute_after_transaction_safely(
                lambda: update_account_payment_status_subtask.delay(
                    unpaid_payment.account_payment_id
                )
            )

        loan = Loan.objects.select_for_update().get(id=unpaid_payment.loan_id)

        if loan.status >= LoanStatusCodes.CURRENT:
            payment_history['loan_old_status_code'] = loan.status

        updated = loan.update_status()
        if not updated:
            logger.debug({"loan": loan.id, "updated": updated})
        else:
            loan.save()
            if loan.status >= LoanStatusCodes.CURRENT:
                unpaid_payment.create_payment_history(payment_history)

    logger.info(
        {
            "payment": unpaid_payment,
            "payment_status": unpaid_payment.status,
            "loan": loan,
            "loan_status": loan.status,
            "updated": updated,
        }
    )


@task(name='update_payment_status')
def update_payment_status():
    """
    Goes through every unpaid payment for loan active and by comparing its due date and
    today's date, update its status (along with its loan status)
    """

    unpaid_payments = (
        Payment.objects.status_tobe_update()
        .exclude(
            loan__loan_status__in=(
                LoanStatusCodes.SELL_OFF,
                LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                LoanStatusCodes.HALT,
            ),
        )
        .exclude(
            loan__account__account_lookup__workflow__name__in={
                WorkflowConst.GRAB,
                WorkflowConst.JULO_ONE,
                WorkflowConst.JULO_STARTER,
                WorkflowConst.JULOVER,
            }
        )
    )

    for unpaid_payment_id in unpaid_payments.values_list("id", flat=True):
        logger.debug({"payment": unpaid_payment_id, "action": "updating_status"})
        update_payment_status_subtask.delay(unpaid_payment_id)


@task(queue='collection_normal')
def update_late_fee_amount_task(unpaid_payment_id):
    """
    Process of update late fee to make sure 1 task per 1 payment
    """
    with transaction.atomic():
        update_late_fee_amount(unpaid_payment_id)
        update_account_transaction_for_late_fee_event(unpaid_payment_id)


@task(queue='collection_high')
def update_payment_amount():
    """
    Goes through every unpaid payment for loan active and by comparing its due date and
    today's date, apply late fee as the rule. now is use just by axiata product lines,
    the rest move to juloserver.account_payment.tasks.scheduled_tasks.update_account_payment_status
    """
    unpaid_payments = (
        Payment.objects.not_paid_active_overdue()
        .filter(loan__application__product_line_id__in=ProductLineCodes.axiata())
        .values_list("id", flat=True)
    )

    for unpaid_payment_id in unpaid_payments:
        update_late_fee_amount_task.delay(unpaid_payment_id)


@task(name="update_loans_on_141")
def update_loans_on_141():
    """
    Goes through applications on 141 offer accepted by customer (verificationcalls pending)
    and updates loan and first payment amount
    """
    query = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
    )
    for application in query:
        try:
            update_loan_and_payments(application.loan)
        except ObjectDoesNotExist:
            logger.warning(
                {
                    "application": application.id,
                    "warning": "Tried to update loan and payments that DoesNotExist",
                }
            )


@task(queue="application_normal")
def mark_offer_expired():
    """
    Goes through every application in which offers have been made. If
    any of the offers has expired, update the application status.
    """
    offer_made_applications = list(Application.objects.offer_made())
    for application in offer_made_applications:

        offers_expired = False

        offers_made = list(Offer.objects.shown_for_application(application))

        offers_accepted = [offer for offer in offers_made if offer.is_accepted]
        if len(offers_accepted) > 0:
            logger.debug(
                {
                    "application": application,
                    "status": "offer_already_accepted",
                    "action": "skip",
                }
            )
            continue

        for offer in offers_made:
            if offer.expired:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.OFFER_EXPIRED,
                    change_reason="system_triggered",
                )
                logger.info(
                    {
                        "application": application,
                        "offer": offer,
                        "status": "offers_expired",
                    }
                )
                offers_expired = True
                break

        if not offers_expired:
            logger.debug({"application": application, "status": "offers_still_valid"})


@task(queue='application_low')
def mark_sphp_expired_subtask(application_id, sphp_exp_date):
    """sub task to run 1app/1worker"""
    application = Application(pk=application_id, sphp_exp_date=sphp_exp_date)

    if application.sphp_expired:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
            change_reason="system_triggered",
        )
        logger.info({"application": application.id, "status": "sphp_expired"})
    else:
        logger.debug({"application": application.id, "status": "sphp_not_yet_expired"})


@task(queue='loan_normal')
def mark_sphp_expired_julo_one_subtask(loan_id):
    """sub task to run 1app/1worker"""

    loan = Loan.objects.filter(pk=loan_id, loan_status__in=LoanStatusCodes.inactive_status()).last()
    if not loan:
        logger.info(
            {
                "action": "mark_sphp_expired_julo_one_subtask",
                "loan_id": loan_id,
                "reason": "The loan status is not inactive",
            }
        )
        return

    if loan.sphp_expired:
        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.SPHP_EXPIRED,
            change_reason="Legal agreement expired",
        )
        logger.info({"loan": loan.id, "status": "sphp_expired"})
    else:
        logger.debug({"loan": loan.id, "status": "sphp_not_yet_expired"})


@task(queue="application_normal")
def mark_sphp_expired():
    """
    Goes through every application in which offers have been made. If
    any of the offers has expired, update the application status.
    """
    applications = (
        Application.objects.activation_call_successful()
        .filter(sphp_exp_date__isnull=False)
        .values_list("id", "sphp_exp_date")
    )

    for application_id, sphp_exp_date in applications:
        mark_sphp_expired_subtask.delay(application_id, sphp_exp_date)


@task(name="mark_sphp_expired_julo_one", queue='loan_normal')
def mark_sphp_expired_julo_one():
    """
    Goes through every application in which offers have been made. If
    any of the offers has expired, update the application status.
    """
    loan_ids = (
        Loan.objects.filter(
            loan_status__in=LoanStatusCodes.inactive_status(), sphp_exp_date__isnull=False
        )
        .exclude(
            Q(product__product_line_id__in=ProductLineCodes.grab())
            | Q(
                transaction_method_id=TransactionMethodCode.JFINANCING.code,
                j_financing_verification__validation_status=JFinancingStatus.ON_REVIEW,
            )
        )
        .values_list('id', flat=True)
    )

    for loan_id in loan_ids:
        mark_sphp_expired_julo_one_subtask.delay(loan_id)


@task(queue="application_low")
def mark_form_partial_expired_subtask(
    application_id, update_date, application_status_id, workflow_name=None
):
    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.partnership.tasks import (
        send_email_106_for_agent_assisted_application,
    )
    from juloserver.application_form.services.application_service import get_julo_core_expiry_marks

    feature_setting = get_julo_core_expiry_marks()
    if not feature_setting:
        return

    juloLog.info(
        {
            'message': 'Start execute function mark_form_partial_expired_subtask',
            'application_id': application_id,
        }
    )

    score_obj = CreditScore.objects.get_or_none(application_id=application_id)
    score = None
    if score_obj:
        score = score_obj.score
    good_score = ExpireDayForm.LIST_GOOD_SCORE

    is_j1 = False
    if workflow_name in (WorkflowConst.JULO_ONE, WorkflowConst.JULO_ONE_IOS):
        is_j1 = True

    expire_105_106 = feature_setting.parameters[ExpireDayForm.KEY_105_TO_106]
    expire_120_106 = feature_setting.parameters[ExpireDayForm.KEY_120_TO_106]
    expire_127_106 = feature_setting.parameters[ExpireDayForm.KEY_127_TO_106]
    expire_155_106 = feature_setting.parameters[ExpireDayForm.KEY_155_TO_106]

    # target expired application to 90 days only for J1
    target_expired = timezone.now() - relativedelta(days=ExpireDayForm.DEFAULT_EXPIRE_DAY)
    if application_status_id == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        # check is_hsfbp True, exclude from expiration
        is_hsfbp = check_has_path_tag(application_id, 'is_hsfbp')
        if is_hsfbp:
            return

        target_expired = timezone.now() - relativedelta(days=expire_120_106)
    elif application_status_id == ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
        target_expired = timezone.now() - relativedelta(days=expire_127_106)
    elif application_status_id == ApplicationStatusCodes.WAITING_LIST:
        target_expired = timezone.now() - relativedelta(days=expire_155_106)
    elif application_status_id == ApplicationStatusCodes.FORM_PARTIAL and score in good_score:
        if not is_j1:
            # to keep existing flow (expired days value)
            target_expired = timezone.now() - relativedelta(
                days=ExpireDayForm.EXPIRE_DAY_105_GOOD_SCORE_NON_J1
            )
    else:
        if not is_j1:
            target_expired = timezone.now() - relativedelta(
                days=ExpireDayForm.EXPIRE_DAY_105_NON_J1
            )
        if is_j1 and score in ['C']:
            target_expired = timezone.now() - relativedelta(days=expire_105_106)

    app_history = ApplicationHistory.objects.filter(
        application_id=application_id,
        status_new=application_status_id,
    ).last()

    if app_history:
        update_date = app_history.cdate

    if update_date < target_expired:  # use udate of application if cdate is not found in history

        is_change_status = process_application_status_change(
            application_id, ApplicationStatusCodes.FORM_PARTIAL_EXPIRED, "system_triggered"
        )
        logger.info(
            {
                'message': '[mark_form_partial_expired_subtask] Trigger to move application to x106',
                'application_id': application_id,
                'application_status_id': application_status_id,
                'is_change_status': is_change_status,
            }
        )

        # Send email soft rejection for partnership if application agent assisted
        send_email_106_for_agent_assisted_application.delay(application_id=application_id)

    else:  # stuck 105
        if (
            application_status_id == ApplicationStatusCodes.FORM_PARTIAL
            and score in good_score
            and is_j1
        ):
            import traceback

            application_tag_tracking_task.delay(
                application_id, None, None, None, 'is_mandatory_docs', 1, traceback.format_stack()
            )

    juloLog.info(
        {
            'message': 'Finish execute function mark_form_partial_expired_subtask',
            'application_id': application_id,
        }
    )


@task(queue="application_low")
def mark_120_expired_in_1_days_subtask(
    application_id, update_date, application_status_id, workflow_name=None
):
    is_j1 = False
    if workflow_name == WorkflowConst.JULO_ONE:
        is_j1 = True

    if not is_j1:
        logger.info(
            {
                "msg": "Function mark_120_expired_in_1_days_subtask",
                "application_id": application_id,
                "status": "this is not j1",
            }
        )
        return

    # check is_hsfbp True, exclude from expiration
    is_hsfbp = check_has_path_tag(application_id, 'is_hsfbp')
    if is_hsfbp:
        logger.info({"msg" : "Function mark_120_expired_in_1_days_subtask", "application_id" : application_id, "status" : "this is hsfbp application"})
        return

    # target expired application to 1 days only for J1
    target_expired = timezone.now() - relativedelta(days=1)
    app_history = ApplicationHistory.objects.filter(
        application_id=application_id,
        status_new=application_status_id,
    ).last()
    if app_history:
        update_date = app_history.cdate
    if update_date < target_expired:  # use udate of application if cdate is not found in history
        process_application_status_change(
            application_id, ApplicationStatusCodes.FORM_PARTIAL_EXPIRED, "system_triggered"
        )
        logger.info(
            {
                "msg": "Function mark_120_expired_in_1_days_subtask",
                "application_id": application_id,
                "status": "success",
            }
        )
        return
    logger.info(
        {
            "msg": "Function mark_120_expired_in_1_days_subtask",
            "application_id": application_id,
            "status": "not eligible for move to x106",
        }
    )
    return


@task(queue="application_normal")
def mark_form_partial_expired():
    from juloserver.application_form.services.application_service import get_max_date_range_expiry

    juloLog.info({'message': 'Start execute function mark_form_partial_expired'})

    date_range = get_max_date_range_expiry(is_selected_status=False)
    workflows = [WorkflowConst.JULO_ONE, WorkflowConst.JULO_ONE_IOS]

    application_ids = (
        Application.objects.filter(
            Q(application_status_id__lte=ApplicationStatusCodes.FORM_PARTIAL)
            | Q(application_status_id=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED),
            workflow__name__in=workflows,
            cdate__date__lte=date_range,
        )
        .values_list('id', 'udate', 'application_status_id', 'workflow__name')
        .order_by('cdate')
    )

    juloLog.info(
        {
            'message': 'Running process partial expired (<=105 & 131)',
            'total_applications': len(application_ids),
        }
    )

    for application_id, update_date, application_status_id, workflow_name in application_ids:
        mark_form_partial_expired_subtask.delay(
            application_id,
            update_date,
            application_status_id,
            workflow_name,
        )

    date_range = get_max_date_range_expiry(is_selected_status=True)
    # handle for application in x120, x131
    applications_ids_experiment = (
        Application.objects.filter(
            application_status_id__in=(
                ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
                ApplicationStatusCodes.WAITING_LIST,
            ),
            cdate__date__lte=date_range,
            workflow__name=WorkflowConst.JULO_ONE,
        )
        .values_list('id', 'udate', 'application_status_id', 'workflow__name')
        .order_by('cdate')
    )

    juloLog.info(
        {
            'message': 'Running process partial expired (>105)',
            'total_applications': len(applications_ids_experiment),
        }
    )

    for (
        application_id,
        update_date,
        application_status_id,
        workflow_name,
    ) in applications_ids_experiment:
        if is_experiment_application(application_id, 'ExperimentUwOverhaul'):
            mark_form_partial_expired_subtask.delay(
                application_id,
                update_date,
                application_status_id,
                workflow_name,
            )


@task(queue="application_normal")
def mark_120_expired_in_1_days():
    # be aware with this function
    # this function only for temporary

    logger.info(
        {
            "msg": "Function mark_120_expired_in_1_days called",
        }
    )

    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MARK_120_EXPIRED_IN_1_DAYS
    ).last()
    if fs is None:
        logger.info(
            {
                "msg": "Function mark_120_expired_in_1_days",
                "status": "feature setting MARK_120_EXPIRED_IN_1_DAYS not found",
            }
        )
        return

    if fs.is_active is False:
        logger.info(
            {
                "msg": "Function mark_120_expired_in_1_days",
                "status": "feature setting MARK_120_EXPIRED_IN_1_DAYS is false",
            }
        )
        return

    applications_ids_experiment = (
        Application.objects.filter(
            application_status_id__in=(ApplicationStatusCodes.DOCUMENTS_SUBMITTED,)
        )
        .exclude(workflow__name__in=(WorkflowConst.GRAB, WorkflowConst.JULO_STARTER))
        .values_list('id', 'udate', 'application_status_id', 'workflow__name')
    )

    for (
        application_id,
        update_date,
        application_status_id,
        workflow_name,
    ) in applications_ids_experiment:
        # start move to 106
        logger.info(
            {
                "msg": "Function mark_120_expired_in_1_days",
                "status": "start move to 106",
                "application_id": application_id,
            }
        )

        try:
            if is_experiment_application(application_id, 'ExperimentUwOverhaul'):
                mark_120_expired_in_1_days_subtask.delay(
                    application_id,
                    update_date,
                    application_status_id,
                    workflow_name,
                )
        except Exception as e:
            logger.info(
                {
                    "msg": "Function mark_120_expired_in_1_days",
                    "status": "there is exception when run mark_120_expired_in_1_days_subtask()",
                    "error": str(e),
                    "application_id": application_id,
                }
            )

    logger.info(
        {
            "msg": "Function mark_120_expired_in_1_days ended",
        }
    )


@task(name="capture_device_ip")
def capture_device_ip(user, device_ip, path):
    """
    Save Device IP to device_ip_history table
    """
    if hasattr(user, "customer"):
        customer = user.customer
    else:
        logger.warn({"path": path, "status": "customer_does_not_exist", "user_id": user.id})
        return

    try:
        device = Device.objects.filter(customer=customer).latest("cdate")
        logger.info({"path": path, "action": "getting_device_id", "device_id": device.id})

    except Device.DoesNotExist:
        logger.warn(
            {
                "path": path,
                "status": "customer_device_does_not_exist",
                "customer_id": customer.id,
            }
        )
        return

    DeviceIpHistory.objects.create(
        customer=customer, device=device, ip_address=device_ip, path=path, count=1
    )

    logger.info(
        {
            "action": "saving_ip_address_to_device_ip_history",
            "ip_address": device_ip,
            "device_id": device.id,
            "customer_id": customer.id,
        }
    )


@task(queue='application_low')
def send_submit_document_reminder_am_subtask(application_id):
    """sub task to perform 1pn/1worker"""
    application = Application.objects.get(pk=application_id)
    device = application.device

    if have_pn_device(device):
        logger.info(
            {
                "action": "send_pn_reminder_upload_document_every_morning",
                "application_id": application_id,
                "device_id": device.id,
                "gcm_reg_id": device.gcm_reg_id,
            }
        )

        julo_pn_client = get_julo_pn_client()
        julo_pn_client.reminder_upload_document(device.gcm_reg_id, application_id)


@task(queue="application_low")
def send_submit_document_reminder_am():
    """
    send reminder for application status 110 every 9:00 AM
    """
    today = timezone.localtime(timezone.now())
    one_day_ago = today - relativedelta(days=1)
    seven_days_ago = today - relativedelta(days=7)
    not_allowed_score = ["C", "--"]
    # get all application in status 105

    application_ids = (
        ApplicationHistory.objects.filter(
            application__application_status=ApplicationStatusCodes.FORM_PARTIAL,
            application__creditscore__isnull=False,
            status_new=ApplicationStatusCodes.FORM_PARTIAL,
            cdate__range=[seven_days_ago, one_day_ago],
        )
        .exclude(application__creditscore__score__in=not_allowed_score)
        .exclude(application__product_line_id=ProductLineCodes.J1)
        .select_related('application__creditscore')
        .values_list("application_id", flat=True)
    )

    for application_id in application_ids:
        send_submit_document_reminder_am_subtask.delay(application_id)


@task(queue="application_low")
def send_submit_document_reminder_pm():
    """
    send reminder for application status 110 every 9:00 PM
    """
    not_allowed_score = ["C", "--"]
    # get all application in status 110
    applications = (
        Application.objects.filter(
            application_status__in=(
                ApplicationStatusCodes.FORM_SUBMITTED,
                ApplicationStatusCodes.FORM_PARTIAL,
            ),
            creditscore__isnull=False,
        )
        .exclude(creditscore__score__in=not_allowed_score)
        .exclude(product_line_id=ProductLineCodes.J1)
    )

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new__in=(
                ApplicationStatusCodes.FORM_SUBMITTED,
                ApplicationStatusCodes.FORM_PARTIAL,
            ),
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 8 <= pass_days <= 14:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_reminder_upload_document_every_night",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.reminder_upload_document(device.gcm_reg_id, application_id)


@task(name="send_resubmission_request_reminder_am")
def send_resubmission_request_reminder_am():
    """
    send reminder pn for satus 131 every 9:00 AM
    """
    # get all application in status 131
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
    ).exclude(product_line_id=ProductLineCodes.J1)

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 1 <= pass_days <= 7:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_reminder_docs_resubmission_every_morning",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.reminder_docs_resubmission(device.gcm_reg_id, application_id)


@task(name="send_resubmission_request_reminder_pm")
def send_resubmission_request_reminder_pm():
    """
    send reminder pn for satus 131 every 9:00 PM
    """
    # get all application in status 131
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
    ).exclude(product_line_id=ProductLineCodes.J1)

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 8 <= pass_days <= 14:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_reminder_docs_resubmission_every_night",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.reminder_docs_resubmission(device.gcm_reg_id, application_id)


@task(queue='application_high')
def send_phone_verification_reminder_am_subtask(application_id, device_id, gcm_reg_id):
    """sub task"""
    today = timezone.now()
    # get application_history
    app_histories = ApplicationHistory.objects.filter(
        status_new=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
        application_id=application_id,
    )

    for app_history in app_histories:
        # indication trigered pn is from application_history cdate
        delta = today - app_history.cdate
        pass_days = delta.days

        if 1 <= pass_days <= 7:
            if device_id and gcm_reg_id:
                logger.info(
                    {
                        "action": "send_pn_reminder_verification_call_ongoing_every_morning",
                        "application_id": application_id,
                        "device_id": device_id,
                        "gcm_reg_id": gcm_reg_id,
                    }
                )

                julo_pn_client = get_julo_pn_client()
                julo_pn_client.reminder_verification_call_ongoing(gcm_reg_id, application_id)


@task(queue="application_low")
def send_phone_verification_reminder_am():
    """
    Send reminder for status 138 every 9:00 AM
    """
    # get all application in status 138
    applications = (
        Application.objects.filter(
            application_status=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING
        )
        .exclude(product_line_id=ProductLineCodes.J1)
        .values_list('id', 'device_id', 'device__gcm_reg_id')
    )

    for application_id, device_id, gcm_reg_id in applications:
        # get application_history
        send_phone_verification_reminder_am_subtask.delay(application_id, device_id, gcm_reg_id)


@task(queue="application_low")
def send_phone_verification_reminder_pm():
    """
    Send reminder for status 138 every 9:00 PM
    """
    # get all application in status 138
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING
    ).exclude(product_line_id=ProductLineCodes.J1)

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 8 <= pass_days <= 14:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_reminder_verification_call_ongoing_every_night",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.reminder_verification_call_ongoing(
                        device.gcm_reg_id, application_id
                    )


@task(queue="application_low")
def send_accept_offer_reminder_am():
    """
    Send reminder for status 140 every 9:00 AM
    """
    # get all application in status 140
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
    ).exclude(product_line_id=ProductLineCodes.J1)

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 1 <= pass_days <= 7:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_inform_offers_made_every_morning",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.inform_offers_made(
                        app_history.application.fullname,
                        device.gcm_reg_id,
                        application_id,
                    )


@task(queue="application_low")
def send_accept_offer_reminder_pm():
    """
    Send reminder for status 140 every 9:00 PM
    """
    # get all application in status 140
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
    ).exclude(product_line_id=ProductLineCodes.J1)

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 8 <= pass_days <= 14:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_inform_offers_made_every_night",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.inform_offers_made(
                        app_history.application.fullname,
                        device.gcm_reg_id,
                        application_id,
                    )


@task(queue="application_low")
def send_sign_sphp_reminder_am():
    """
    Send reminder for status 160 every 9:00 AM
    """
    # get all application instatus 160
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
    ).exclude(product_line_id=ProductLineCodes.J1)

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 1 <= pass_days <= 7:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_inform_legal_document_every_morning",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.inform_legal_document(
                        app_history.application.fullname,
                        device.gcm_reg_id,
                        application_id,
                    )


@task(queue='application_low')
def send_sign_sphp_reminder_pm():
    """
    Send reminder for status 160 every 9:00 PM
    """
    # get all application instatus 160
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
    ).exclude(product_line_id=ProductLineCodes.J1)

    today = timezone.now()

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            if 8 <= pass_days <= 14:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_inform_legal_document_every_night",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.inform_legal_document(
                        app_history.application.fullname,
                        device.gcm_reg_id,
                        application_id,
                    )


@task(queue='application_high')
def upload_image(image_id, thumbnail=True, deleted_if_last_image=False):
    image = Image.objects.get_or_none(pk=image_id)
    if not image:
        logger.error({"image": image_id, "status": "not_found"})
    process_image_upload(image, thumbnail, deleted_if_last_image)


@task(queue='application_high')
def upload_image_julo_one(image_id, thumbnail=True, source_image_id=None):
    image = Image.objects.get_or_none(pk=image_id)
    if not image:
        logger.error({"image": image_id, "status": "not_found"})
    process_image_upload_julo_one(image, thumbnail, source_image_id)


@task(queue="loan_high")
def upload_voice_record(voice_record_id):
    voice_record = VoiceRecord.objects.get(id=voice_record_id)
    cust_id = voice_record.application.customer_id
    app_id = voice_record.application_id
    time_stamp = timezone.now().strftime("%Y-%m-%d_%H:%M:%S")
    _, extension = os.path.splitext(voice_record.tmp_path.path)
    extension = extension.replace(".", "")
    dest_name = "cust_{}/application_{}/sphp_{}.{}".format(cust_id, app_id, time_stamp, extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, voice_record.tmp_path.path, dest_name)
    voice_record.url = dest_name
    voice_record.tmp_path.delete()
    other_records = voice_record.application.voicerecord_set.all()
    other_records = other_records.exclude(id=voice_record.id)
    other_records = other_records.exclude(status=VoiceRecord.DELETED)
    for record in other_records:
        record.status = VoiceRecord.DELETED
        record.save()


@task(queue="loan_high")
def upload_voice_record_julo_one(voice_record_id):
    voice_record = VoiceRecord.objects.get(id=voice_record_id)
    cust_id = voice_record.loan.customer_id
    loan_id = voice_record.loan_id
    time_stamp = timezone.now().strftime("%Y-%m-%d_%H:%M:%S")
    _, extension = os.path.splitext(voice_record.tmp_path.path)
    extension = extension.replace(".", "")
    dest_name = "cust_{}/loan_{}/sphp_{}.{}".format(cust_id, loan_id, time_stamp, extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, voice_record.tmp_path.path, dest_name)
    voice_record.url = dest_name
    voice_record.tmp_path.delete()
    other_records = voice_record.loan.voicerecord_set.all()
    other_records = other_records.exclude(id=voice_record.id)
    other_records = other_records.exclude(status=VoiceRecord.DELETED)
    for record in other_records:
        record.status = VoiceRecord.DELETED
        record.save()


@task(queue="application_normal")
def upload_document(
    document_id,
    local_path,
    is_lender=False,
    is_bucket=False,
    is_loan=False,
    is_switching=False,
    is_write_off=False,
    is_qris=False,
    is_channeling=False,
    is_daily_disbursement_limit_whitelist=False,
):
    document = Document.objects.get_or_none(pk=document_id)
    if not document:
        logger.error({"document": document_id, "status": "not_found"})
        return None

    if is_lender:
        lender = LenderCurrent.objects.get_or_none(pk=document.document_source)
        if not lender:
            raise JuloException("Lender id {} not found".format(document.document_source))

        document_remote_filepath = "lender_{}/{}".format(
            document.document_source, document.filename
        )
    elif is_bucket:
        lenderbucket = LenderBucket.objects.get_or_none(pk=document.document_source)
        if not lenderbucket:
            raise JuloException("LenderBucket id {} not found".format(document.document_source))

        document_remote_filepath = "lenderbucket_{}/{}".format(
            document.document_source, document.filename
        )
    elif is_loan:
        loan = Loan.objects.get_or_none(pk=document.document_source)
        if not loan:
            raise JuloException("Loan id {} not found".format(document.document_source))
        cust_id = loan.customer.id
        document_remote_filepath = "cust_{}/loan_{}/{}".format(
            cust_id, document.document_source, document.filename
        )
    elif is_switching:
        document_remote_filepath = "AR_Switching/user_{}/{}".format(
            document.document_source, document.filename
        )
    elif is_write_off:
        document_remote_filepath = "Loan_Write_Off/user_{}/{}".format(
            document.document_source, document.filename
        )
    elif is_qris:
        document_remote_filepath = "qris_user_state_{}/{}".format(
            document.document_source, document.filename
        )
    elif is_channeling:
        document_remote_filepath = "channeling_loan/user_{}/{}".format(
            document.document_source, document.filename
        )
    elif is_daily_disbursement_limit_whitelist:
        document_remote_filepath = "daily_disbursement_limit_whitelist/user_{}/{}".format(
            document.document_source, document.filename
        )
    else:
        application = Application.objects.get_or_none(pk=document.document_source)
        if not application:
            raise JuloException("Application id {} not found".format(document.document_source))

        cust_id = application.customer.id
        document_remote_filepath = "cust_{}/application_{}/{}".format(
            cust_id, document.document_source, document.filename
        )

    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_path, document_remote_filepath)
    document.url = document_remote_filepath
    document.save()

    logger.info(
        {
            "status": "successfull upload document",
            "document_remote_filepath": document_remote_filepath,
            "document_source": document.document_source,
            "document_type": document.document_type,
        }
    )

    # Delete local document
    if os.path.isfile(local_path):
        logger.info(
            {
                "action": "deleting_local_document",
                "document_path": local_path,
                "document_source": document.document_source,
            }
        )
        os.remove(local_path)


@task(name="create_thumbnail_and_upload")
def create_thumbnail_and_upload(image):
    process_thumbnail_upload(image)


@task(queue='application_low')
def expire_application_status(application_id, application_status, status):
    """Task to auto expire applications stuck in certain statuses"""
    application_history = (
        ApplicationHistory.objects.filter(
            application_id=application_id, status_new=application_status
        )
        .order_by("cdate")
        .last()
    )
    if application_history is None:
        return

    exp_date = None
    if status.get('target') == TARGET_PARTNER:
        if status['status_to'] == ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED:
            exp_date = application_history.application.sphp_exp_date + timedelta(days=1)
        else:
            exp_date = get_expiry_date(application_history.cdate.date(), status['days'])
    else:
        exp_date = application_history.cdate.date() + relativedelta(days=status['days'])

    today = timezone.localtime(timezone.now()).date()
    if exp_date <= today:
        logger.info(
            {
                "action": "expire_application_status",
                "exp_date": exp_date,
                "status_old": status['status_old'],
                "application_id": application_id,
            }
        )
        reason = "status_expired"
        notes = (
            "change_status_from : " + str(status['status_old']) + "to :" + str(status['status_to'])
        )
        with transaction.atomic():
            try:
                process_application_status_change(
                    application_id, int(status['status_to']), reason, note=notes
                )
            except Exception as exc:
                logger.exception(exc)


@task(queue="application_normal")
def trigger_application_status_expiration():
    """Define stuck application status need expiration action"""
    stuck_statuses = APPLICATION_STATUS_EXPIRE_PATH

    for status in stuck_statuses:
        status_old = status['status_old']
        status_to = status['status_to']
        days = status['days']
        target = status.get('target', None)
        logger.info({'status_old': status_old, 'status_new': status_to, 'valid_duration': days})
        applications = Application.objects.filter(application_status=status_old)
        if target == TARGET_PARTNER:
            applications = applications.exclude(partner_id__isnull=True)
        elif target == TARGET_CUSTOMER:
            applications = applications.filter(partner_id__isnull=True)

        for application_id, application_status in applications.values_list(
            "id", "application_status"
        ):
            expire_application_status.delay(application_id, application_status, status)


@task(queue="application_low")
def trigger_send_email_follow_up_daily():
    """
    trigger celery task to send follow up email
    """
    follow_up_statuses = [
        {"status": ApplicationStatusCodes.FORM_SUBMITTED, "schedule": [3, 10]},
        # {
        #     'status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        #     'schedule': [3, 5]
        # },
        {"status": ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING, "schedule": [1]},
    ]

    for follow_up_status in follow_up_statuses:
        applications = Application.objects.filter(
            application_status=follow_up_status["status"]
        ).exclude(product_line_id=ProductLineCodes.J1)
        if applications:
            for application in applications:
                application_history = ApplicationHistory.objects.filter(
                    status_new=application.status, application=application
                ).last()
                if application_history:
                    cdate = application_history.cdate

                    for schedule in follow_up_status["schedule"]:
                        exp_day = cdate + relativedelta(days=schedule)
                        if exp_day.strftime("%Y-%m-%d") == timezone.now().strftime("%Y-%m-%d"):
                            send_email_follow_up.delay(application.id)
        else:
            logger.info(
                {
                    "status": follow_up_status["status"],
                    "messages": "no application in this status",
                }
            )


@task(queue='application_low')
def send_email_follow_up(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    application_history = ApplicationHistory.objects.filter(
        application=application, status_new=application.status
    ).last()
    if not application_history:
        return

    change_reason = application_history.change_reason

    email_method_name = "email_notification_" + str(application.application_status.status_code)
    email_client = get_julo_email_client()
    email_client_method = getattr(email_client, email_method_name)
    status, headers, subject, msg = email_client_method(application, change_reason)

    customer = application.customer
    message_id = headers["X-Message-Id"]

    if application.status == ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING:
        template_code = "email_" + change_reason
    else:
        template_code = "email_notif_" + str(application.status)
    if status == 202:
        EmailHistory.objects.create(
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=application.email,
            subject=subject,
            message_content=msg,
            template_code=template_code,
        )

        logger.info(
            {
                "action": "send_email_follow_up",
                "application_id": application.id,
                "status": application.status,
            }
        )


@task(queue="application_low")
def trigger_send_follow_up_email_100_daily():
    yesterday = timezone.now().date() - relativedelta(days=1)
    result_tuple_list = (
        Customer.objects.filter(
            cdate__date=yesterday, application__application_status__lte=100, email__isnull=False
        )
        .exclude(application__product_line_id=ProductLineCodes.J1)
        .distinct('id')
        .values_list('id', flat=True)
    )

    if not result_tuple_list:
        return

    for customer_id in result_tuple_list:
        suffix = "100v"
        send_email_follow_up_100.delay(customer_id, suffix)
        logger.info(
            {
                'action': 'trigger_send_follow_up_email_' + suffix,
                'customer_id': customer_id,
            }
        )


@task(queue="application_low")
def send_email_follow_up_100(customer_id, status_code):
    customer = Customer.objects.get(pk=customer_id)
    email_method = "email_notification_" + status_code
    email_cls = get_julo_email_client()
    email_client = getattr(email_cls, email_method)
    status, headers, subject, msg = email_client(customer)

    logger.info({"action": "send_follow_up_email_100", "customer_id": customer.id})

    template_code = "email_notif_" + str(status_code)
    message_id = headers["X-Message-Id"]
    if status == 202:
        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=message_id,
            to_email=customer.email,
            subject=subject,
            message_content=msg,
            template_code=template_code,
        )


@task(name="checking_doku_payments_peridically")
def checking_doku_payments_peridically():
    doku_transaction = DokuTransaction.objects.all().order_by("transaction_date").last()
    start_date_str = None
    if doku_transaction:
        start_date_str = str(doku_transaction.transaction_date).replace("-", "")
        start_date_str = start_date_str.replace(":", "")
        start_date_str = start_date_str.replace(" ", "")

        logger.info(
            {
                "start_date": str(timezone.localtime(doku_transaction.transaction_date)),
                "start_date_str": start_date_str,
                "now": timezone.localtime(timezone.now()),
            }
        )

    check_unprocessed_doku_payments(start_date_str)


@task(queue="application_normal")
def create_application_checklist_async(application_id):
    application = Application.objects.get(pk=application_id)

    logger.info(
        {
            "action": "create_application_checklist",
            "application_id": application_id,
            "date": timezone.now(),
        }
    )
    create_application_checklist(application)


@task(queue="application_normal")
def checking_application_checklist():
    now = timezone.localtime(timezone.now())
    ten_minutes_before = now - relativedelta(minutes=10)
    ten_days_before = now - relativedelta(days=10)
    application_ids = (
        Application.objects.using('replica')
        .filter(
            application_status_id__in=[
                ApplicationStatusCodes.FORM_PARTIAL,
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ],
            udate__lte=ten_minutes_before,
            udate__gte=ten_days_before,
            applicationchecklist__isnull=True,
            applicationchecklist__cdate__gte=ten_days_before,
        )
        .values_list("id", flat=True)
    )

    for application_id in application_ids:
        create_application_checklist_async.delay(application_id)


@task(name="trigger_robocall")
def trigger_robocall():
    sentry_client = get_julo_sentry_client()
    autodialer_client = get_julo_autodialer_client()
    mtl_days_from_now = [3, 5]
    all_robocall_active = Payment.objects.normal().filter(is_robocall_active=True)
    MTL_robocall_active = all_robocall_active.filter(
        loan__application__product_line__product_line_code__in=ProductLineCodes.mtl()
    )
    for day_from_now in mtl_days_from_now:
        selected_due_date = date.today() + relativedelta(days=day_from_now)
        for payment in MTL_robocall_active.filter(due_date=selected_due_date):
            if payment.payment_status.status_code < PaymentStatusCodes.PAYMENT_DUE_TODAY:
                try:
                    number_to_call, skiptrace_id = choose_number_to_robocall(
                        payment.loan.application
                    )
                    autodialer_client.robodial(
                        number_to_call,
                        skiptrace_id,
                        str(payment.payment_number),
                        str(payment.due_amount),
                        str(payment.due_date),
                        1,
                    )
                    skiptrace = Skiptrace.objects.filter(id=skiptrace_id).first()
                    AutoDialerRecord.objects.create(payment=payment, skiptrace=skiptrace)
                except Exception as e:
                    sentry_client.captureException()


@task(name="ontwo330_robocall_scheduler")
def mark_is_robocall_active():
    """
    For first two payments in loan that is paid on time, function sets all future payments
    to be robocall active
    DEPRECATED: logic has been moved to services.py, marked after each status update
    """
    all_loans = Loan.objects.exclude(loan_status_id=LoanStatusCodes.PAID_OFF).exclude(
        loan_status_id__in=LoanStatusCodes.inactive_status()
    )
    for loan in all_loans:

        payments = loan.payment_set.all()
        paid_on_time_payments = []
        for payment in payments:
            if payment.payment_status.status_code == PaymentStatusCodes.PAID_ON_TIME:
                paid_on_time_payments.append(payment)

        paid_on_time_payments = [p for p in paid_on_time_payments if p.payment_number in [1, 2]]

        if len(paid_on_time_payments) >= 2:
            remaining_payments = [p for p in payments if p.payment_number > 2]

            for payment in remaining_payments:
                if payment.is_robocall_active is None:
                    payment.is_robocall_active = True
                    payment.save(update_fields=["is_robocall_active", "udate"])


@task(name="send_data_to_collateral_partner_async")
def send_data_to_collateral_partner_async(application_id):
    application = Application.objects.get(pk=application_id)

    logger.info(
        {
            "action": "send_data_to_collateral_partner",
            "application_id": application_id,
            "date": timezone.now(),
        }
    )
    send_data_to_collateral_partner(application)


@task(queue='application_high')
def send_sms_otp_token(
    phone_number, text, customer_id, otp_id, change_sms_provide=False, template_code=None
):
    otp = OtpRequest.objects.get(pk=otp_id)
    customer = Customer.objects.filter(pk=customer_id).last() if customer_id else None
    mobile_number = format_e164_indo_phone_number(phone_number)
    get_julo_sms = get_julo_sms_client()
    txt_msg, response = get_julo_sms.premium_otp(mobile_number, text, change_sms_provide)

    if 'julo_sms_vendor' in response and response['julo_sms_vendor'] == VendorConst.INFOBIP:
        sms_sent = response['status'] == "1"
    else:
        sms_sent = response['status'] == "0"

    if not sms_sent:
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "message_id": response.get("message-id"),
                "sms_client_method_name": "sms_custom_payment_reminder",
                "error_text": response.get("error-text"),
            }
        )

    sms = create_sms_history(
        response=response,
        customer=customer,
        message_content=txt_msg,
        to_mobile_phone=format_e164_indo_phone_number(response["to"]),
        phone_number_type="mobile_phone_1",
        template_code=template_code,
    )

    # Save sms history to otp request
    otp.update_safely(sms_history=sms)

    logger.info(
        {
            "status": "sms_created",
            "sms_history_id": sms.id,
            "message_id": sms.message_id,
        }
    )


@task(queue='application_high')
def send_whatsapp_otp_token(phone_number, text, customer_id, otp_id, template_code=None):
    otp = OtpRequest.objects.get(pk=otp_id)
    customer = Customer.objects.filter(pk=customer_id).last() if customer_id else None
    mobile_number = format_e164_indo_phone_number(phone_number)
    msg_id = send_whatsapp_otp_go(mobile_number, otp.otp_token, 'JULO Platform', 'mvp')
    response = {
        'status': '1',
        'to': mobile_number,
        'message-id': msg_id,
        'julo_sms_vendor': 'whatsapp_service',
        'is_otp': True,
    }

    if (
        'julo_sms_vendor' in response
        and response['julo_sms_vendor'] == VendorConst.WHATSAPP_SERVICE
    ):
        sms_sent = response['status'] == "1"
    else:
        sms_sent = response['status'] == "0"

    if not sms_sent:
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "message_id": response.get("message-id"),
                "sms_client_method_name": "sms_custom_payment_reminder",
                "error_text": response.get("error-text"),
            }
        )

    sms = create_sms_history(
        response=response,
        customer=customer,
        message_content=text,
        to_mobile_phone=format_e164_indo_phone_number(response["to"]),
        phone_number_type="mobile_phone_1",
        template_code=template_code,
    )
    # Save whatsapp history to otp request
    otp.update_safely(sms_history=sms, whatsapp_xid=msg_id)

    logger.info(
        {
            "status": "whatsapp_created",
            "sms_history_id": sms.id,
            "message_id": sms.message_id,
        }
    )


@task(queue="application_high")
def send_pn_etl_done(application_id, success, credit_score=None):
    not_allowed_score = ["C", "--"]
    if credit_score in not_allowed_score:
        return

    application = Application.objects.get(id=application_id)
    julo_pn_client = get_julo_pn_client()
    if have_pn_device(application.device):
        is_spesial_check = False
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SPECIAL_EVENT_BINARY, is_active=True
        )
        if feature_setting and credit_score == 'C':
            data_check = AutoDataCheck.objects.filter(
                application_id=application.id, data_to_check='special_event', is_okay=False
            ).last()
            if data_check:
                is_spesial_check = True
        julo_pn_client.inform_etl_finished(application, success, is_spesial_check)


@task(queue="collection_low")
def send_sms_update_ptp(payment_id):
    payment = Payment.objects.select_related('loan__application').get(id=payment_id)
    # block sms to ICare client
    if not payment.loan.application.customer.can_notify:
        logger.info(
            {
                'status': 'sms_failed',
                'payment_id': payment.id,
                'error_text': 'can not sms to this customer',
            }
        )
        return

    julo_sms_client = get_julo_sms_client()
    txt_msg, response, template = julo_sms_client.sms_payment_ptp_update(payment)

    if response["status"] != "0":
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "payment_id": payment.id,
                "message_id": response.get("message-id"),
                "sms_client_method_name": "sms_payment_ptp_update",
                "error_text": response.get("error-text"),
            }
        )

    application = payment.loan.application
    customer = application.customer

    sms = create_sms_history(
        response=response,
        customer=customer,
        application=application,
        payment=payment,
        template_code=template,
        message_content=txt_msg,
        to_mobile_phone=format_e164_indo_phone_number(response["to"]),
        phone_number_type="mobile_phone_1",
    )

    logger.info(
        {
            "status": "sms_created",
            "payment_id": payment.id,
            "sms_history_id": sms.id,
            "message_id": sms.message_id,
        }
    )


@task(queue="application_normal")
def reminder_activation_code():
    kyc_request_list = KycRequest.objects.filter(is_processed=False)
    for kyc in kyc_request_list:
        start_date = timezone.localtime(timezone.now())
        end_date = timezone.localtime(kyc.expiry_time)
        range_time = start_date - end_date
        range_day = range_time.days
        if range_day == 1:
            message = "2 Hari Lagi"
            logger.info({"action": "reminder_activation_code", "message": message})
        elif range_day == 2:
            message = "1 Hari Lagi"
            logger.info({"action": "reminder_activation_code", "message": message})
        elif range_day == 3:
            message = "Hari ini E-code Form akan kadarluasa pada jam {} : {} ".format(
                kyc.expiry_time.hour, kyc.expiry_time.minute
            )
            logger.info({"action": "reminder_activation_code", "message": message})


@task(queue='application_low')
def send_resubmission_request_reminder_pn():
    """
    send reminder pn for satus 131 six hour before expired
    """
    # get all application in status 131
    today = timezone.localtime(timezone.now())

    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
    ).exclude(product_line_id=ProductLineCodes.J1)

    for application in applications:
        # get application_history
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = relativedelta(today, timezone.localtime(app_history.cdate))
            if (delta.days * 24 + delta.hours) in [24, 30]:
                device = app_history.application.device
                if have_pn_device(device):
                    application_id = app_history.application.id

                    logger.info(
                        {
                            "action": "send_pn_resubmission_request_24_and_30_hour_after_131",
                            "application_id": application_id,
                            "device_id": device.id,
                            "gcm_reg_id": device.gcm_reg_id,
                        }
                    )

                    julo_pn_client = get_julo_pn_client()

                    julo_pn_client.reminder_docs_resubmission(device.gcm_reg_id, application_id)


@task(queue="application_normal")
def expire_application_status_131():
    """Task to auto expire applications stuck in 131 status"""
    today = timezone.localtime(timezone.now()).date()

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS, is_active=True
    ).last()
    if not feature_setting:
        raise JuloException("JULO_CORE_EXPIRY_MARKS not active/missing")

    expire_131_136 = feature_setting.parameters['x131_to_x136']

    status_old = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
    status_to = ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED
    applications = Application.objects.filter(application_status=status_old)
    for application in applications:
        if (
            application.is_mf_web_app_flow()
            or application.is_axiata_flow()
            or application.is_merchant_flow()
            or application.is_dana_flow()
        ):
            continue

        application_history = (
            ApplicationHistory.objects.filter(
                application=application, status_new=application.status
            )
            .order_by("cdate")
            .last()
        )
        if application_history is None:
            continue

        delta = today - timezone.localtime(application_history.cdate).date()
        range_days = 90
        if application.is_julo_one_product():
            range_days = expire_131_136
        elif application.is_grab():
            range_days = 3

        if delta.days >= range_days:
            logger.info(
                {
                    "action": "expire_application_status_131",
                    "exp_date": today,
                    "status_old": status_old,
                    "application_id": application.id,
                    "range_days": range_days,
                }
            )
            reason = "status_expired"
            notes = "change_status_from : " + str(status_old) + "to :" + str(status_to)
            with transaction.atomic():
                process_application_status_change(
                    application.id, int(status_to), reason, note=notes
                )


@task(queue="application_normal")
def expire_application_status_175():
    today = timezone.localtime(timezone.now()).date()
    try:
        filter_due_dates_by_weekend((today,))
        filter_due_dates_by_pub_holiday((today,))
    except JuloException:
        logger.info(
            {
                "action": "expire_application_status_175",
                "warning": "in public holiday or weekend",
            }
        )
        return False

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS, is_active=True
    ).last()
    if not feature_setting:
        raise JuloException("JULO_CORE_EXPIRY_MARKS not active/missing")

    expire_175_135 = feature_setting.parameters['x175_to_x135']

    status_old = ApplicationStatusCodes.NAME_VALIDATE_FAILED
    status_to = ApplicationStatusCodes.APPLICATION_DENIED
    julo_one_workflow = Workflow.objects.filter(name=WorkflowConst.JULO_ONE).last()
    applications = Application.objects.filter(
        application_status=status_old, workflow=julo_one_workflow
    )
    for application in applications:
        application_history = (
            ApplicationHistory.objects.filter(
                application=application, status_new=application.status
            )
            .order_by("cdate")
            .last()
        )
        if application_history is None:
            continue

        delta = today - timezone.localtime(application_history.cdate).date()
        range_days = expire_175_135

        if delta.days >= range_days:
            logger.info(
                {
                    "action": "expire_application_status_175",
                    "exp_date": today,
                    "status_old": status_old,
                    "application_id": application.id,
                    "range_days": range_days,
                }
            )
            reason = "Expired Bank Verification"
            notes = "change_status_from : " + str(status_old) + "to :" + str(status_to)
            with transaction.atomic():
                process_application_status_change(
                    application.id, int(status_to), reason, note=notes
                )
                customer = application.customer
                customer.can_reapply = True
                customer.save()


@task(queue='application_low')
def reminder_email_application_status_105_subtask(application_id):
    """sub task to help send email 1 worker 1 email"""
    today = timezone.localtime(timezone.now()).date()
    application = Application.objects.select_related("customer").get(pk=application_id)
    credit_score_list = ["B-", "B+", "A-", "A"]

    application_history = (
        ApplicationHistory.objects.filter(application=application, status_new=application.status)
        .order_by("cdate")
        .last()
    )
    if application_history is None:
        return
    credit_score = CreditScore.objects.get_or_none(application_id=application_id)

    if not credit_score or credit_score.score.upper() not in credit_score_list:
        return

    delta = today - timezone.localtime(application_history.cdate).date()
    if delta.days >= 1:
        logger.info(
            {
                "action": "reminder_email_application_status_105",
                "application_id": application.id,
            }
        )
        customer = application.customer
        if customer.email:
            email_method = "email_reminder_105"
            email_cls = get_julo_email_client()
            email_client = getattr(email_cls, email_method)
            status, headers, subject, msg = email_client(application)

            template_code = "email_reminder_105"
            message_id = headers["X-Message-Id"]
            if status == 202:
                EmailHistory.objects.create(
                    customer=customer,
                    sg_message_id=message_id,
                    to_email=customer.email,
                    subject=subject,
                    message_content=msg,
                    template_code=template_code,
                )
        else:
            logger.error(
                {
                    "action": "reminder_email_application_status_105",
                    "application_id": application.id,
                    "error": "email field is null",
                }
            )


@task(queue='application_low')
def reminder_email_application_status_105():
    """Task to send email reminder for 105"""

    status = ApplicationStatusCodes.FORM_PARTIAL
    applications = (
        Application.objects.filter(application_status=status)
        .exclude(product_line_id=ProductLineCodes.J1)
        .values_list("id", flat=True)
    )
    for application_id in applications:
        reminder_email_application_status_105_subtask.delay(application_id)


@task(queue='application_low')
def pn_app_105_subtask(application_id, device_id, gcm_reg_id):
    """sub task to perform 1pn/1worker"""
    credit_score_list = ["B-", "B+", "A-", "A"]

    credit_score = CreditScore.objects.get_or_none(application_id=application_id)
    if not credit_score:
        return

    user_credit_score = credit_score.score.upper()
    if user_credit_score not in credit_score_list:
        return

    device = Device(id=device_id, gcm_reg_id=gcm_reg_id)
    if not have_pn_device(device):
        return

    logger.info(
        {
            "action": "send_reminder_push_notif_application_status_105",
            "application_id": application_id,
            "device_id": device.id,
            "gcm_reg_id": device.gcm_reg_id,
        }
    )
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.reminder_app_status_105(device.gcm_reg_id, application_id, user_credit_score)


@task(queue="application_low")
def scheduled_reminder_push_notif_application_status_105():
    """
    send reminder pn
    """
    today = timezone.now()
    yesterday = today - relativedelta(days=1)
    applications = (
        Application.objects.filter(
            application_status=ApplicationStatusCodes.FORM_PARTIAL, udate__gte=yesterday
        )
        .exclude(product_line_id=ProductLineCodes.J1)
        .values_list("pk", "device__pk", "device__gcm_reg_id")
    )

    for application_id, device_id, gcm_reg_id in applications:
        pn_app_105_subtask.delay(application_id, device_id, gcm_reg_id)


@task(queue="application_normal")
def scheduled_application_status_info():
    """
    send total of application from defined statuses
    """
    # send total of application from defined statuses

    bucket_status_obj = SlackEWABucket.objects.filter(disable=False)
    slack_ewa_items = SlackEWABucket.objects.all()
    attachment = ""
    text = (
        "<!here>\n"
        + "=== *Application Statuses Info* ===\n"
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    user_attachment = {}

    for bucket_status in bucket_status_obj:
        status = bucket_status.status_code.status_code
        status_name = (
            bucket_status.display_text if bucket_status.display_text else "x{}".format(status)
        )
        fattachment = ""

        count = Application.objects.filter(application_status__status_code=status).count()
        bucket = SlackEWABucket.objects.get_or_none(status_code=int(status))
        emoticon = get_bucket_emotion(bucket, count, slack_ewa_items)
        slack_users = get_bucket_slack_user(bucket, count, slack_ewa_items)

        if emoticon:
            fattachment = "{} -> {} {}\n".format(status_name, count, emoticon)
        else:
            fattachment = "{} -> {}   \n".format(status_name, count)
        attachment += fattachment

        for user in slack_users:
            user = str(user)
            if user not in user_attachment:
                user_attachment[user] = []
            user_attachment[user].append(fattachment)
    for user_id, message_array in list(user_attachment.items()):
        notify_application_status_info_to_reporter(user_id, "".join(message_array), text)

    notify_application_status_info(attachment, text)


def status_codes_counter(buckets, counter, statuses, prefix, types='app'):
    code_counter = {}

    status_type = 'application_status_id'

    if types == 'loan':
        status_type = 'loan_status__status_code'

    for count in counter:
        if status_type not in code_counter:
            code_counter[count[status_type]] = {'status_code': count[status_type], 'count': 0}
        code_counter[count[status_type]]['count'] += int(count['status_count'])

    for status in statuses:
        count = 0
        _status = status

        if status in code_counter:
            count = code_counter[status]['count']
            _status = code_counter[status]['status_code']

        setattr(buckets, prefix.format(_status), count)


@task(queue="application_normal")
def counter_0_turbo_bucket():
    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets()

    # BUCKET 0 TURBO - HAS NO APPLICATION
    from django.db import connection

    raw_0_turbo = """
        SELECT DISTINCT ON (oe.customer_id)
            oe.onboarding_eligibility_checking_id
        FROM
            onboarding_eligibility_checking AS oe
        ORDER BY
            customer_id, udate DESC
    """
    with connection.cursor() as cursor:
        cursor.execute(raw_0_turbo)
        result_0_turbo = cursor.fetchall()

    latest_0_turbo_ids = []
    for result in result_0_turbo:
        latest_0_turbo_ids.append(result[0])

    count_0_turbo = (
        OnboardingEligibilityChecking.objects.filter(Q(bpjs_check=2) | Q(fdc_check=2))
        .filter(id__in=latest_0_turbo_ids, dukcapil_check=None, application=None)
        .filter(id__in=latest_0_turbo_ids)
        .count()
    )

    setattr(buckets, "app_0_turbo", count_0_turbo)
    buckets.save()


@task(queue="application_normal")
def refresh_crm_dashboard():
    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets()

    app_statuses_skip_priority = APP_STATUS_SKIP_PRIORITY

    app_statuses_with_priority = APP_STATUS_WITH_PRIORITY

    app_statuses_skip_priority_no_julo1_no_grab = APP_STATUS_SKIP_PRIORITY_NO_J1_NO_GRAB

    app_statuses_with_priority_no_julo1_no_grab = APP_STATUS_WITH_PRIORITY_NO_J1_NO_GRAB

    app_statuses_julo_one_with_priority = APP_STATUS_J1_WITH_PRIORITY

    app_statuses_julo_one_skip_priority = APP_STATUS_J1_SKIP_PRIORITY

    app_statuses_grab_with_priority = APP_STATUS_GRAB_WITH_PRIORITY

    app_statuses_grab_skip_priority = APP_STATUS_GRAB_SKIP_PRIORITY

    partner_list = LIST_PARTNER

    app_status_partnership_agent_assisted = APP_STATUS_PARTNERSHIP_AGENT_ASSISTED

    app_status_j1_agent_assisted = APP_STATUS_J1_AGENT_ASSISTED

    count_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(application_status_id__in=app_statuses_with_priority_no_julo1_no_grab)
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_prio,
        statuses=app_statuses_with_priority_no_julo1_no_grab,
        prefix="app_{}",
    )

    is_revive_mtl_tag = ApplicationPathTagStatus.objects.get(
        application_tag='is_revive_mtl', status=1
    )
    application_ids = ApplicationPathTag.objects.filter(
        application_path_tag_status=is_revive_mtl_tag
    ).values_list('application_id', flat=True)
    count_175_mtl = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(
            application_status_id=ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            workflow__name=WorkflowConst.JULO_ONE,
            id__in=list(application_ids),
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_175_mtl,
        statuses=[ApplicationStatusCodes.NAME_VALIDATE_FAILED],
        prefix="app_{}_mtl",
    )

    count_j1_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(
            application_status_id__in=app_statuses_julo_one_with_priority,
            workflow__name=WorkflowConst.JULO_ONE,
        )
        .exclude(id__in=list(application_ids))
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_j1_prio,
        statuses=app_statuses_julo_one_with_priority,
        prefix="app_{}_j1",
    )

    count_exclude_j1_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(application_status_id__in=app_statuses_julo_one_with_priority)
        .exclude(workflow__name=WorkflowConst.JULO_ONE)
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_exclude_j1_prio,
        statuses=app_statuses_julo_one_with_priority,
        prefix="app_{}",
    )

    count_grab_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(
            application_status_id__in=app_statuses_grab_with_priority,
            product_line__product_line_code__in=ProductLineCodes.grab(),
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_grab_prio,
        statuses=app_statuses_grab_with_priority,
        prefix="app_{}_grab",
    )

    count_exclude_grab_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(application_status_id__in=app_statuses_grab_with_priority)
        .exclude(product_line__product_line_code__in=ProductLineCodes.grab())
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_exclude_grab_prio,
        statuses=app_statuses_grab_with_priority,
        prefix="app_{}",
    )

    prio_count = (
        Application.objects.filter(
            application_status_id__in=app_statuses_with_priority, partner__name__in=partner_list
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=prio_count,
        statuses=app_statuses_with_priority,
        prefix="app_priority_{}",
    )

    partner_list = LIST_PARTNER_EXCLUDE_PEDE

    count_exclude_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(application_status_id__in=app_statuses_skip_priority_no_julo1_no_grab)
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_exclude_prio,
        statuses=app_statuses_skip_priority_no_julo1_no_grab,
        prefix="app_{}",
    )

    count_j1_exclude_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(
            application_status_id__in=app_statuses_julo_one_skip_priority,
            workflow__name=WorkflowConst.JULO_ONE,
        )
        .exclude(id__in=list(application_ids))
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_j1_exclude_prio,
        statuses=app_statuses_julo_one_skip_priority,
        prefix="app_{}_j1",
    )

    count_exclude_j1_exclude_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(application_status_id__in=app_statuses_julo_one_skip_priority)
        .exclude(workflow__name=WorkflowConst.JULO_ONE)
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_exclude_j1_exclude_prio,
        statuses=app_statuses_julo_one_skip_priority,
        prefix="app_{}",
    )

    count_grab_exclude_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(
            application_status_id__in=app_statuses_grab_skip_priority,
            product_line__product_line_code__in=ProductLineCodes.grab(),
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_grab_exclude_prio,
        statuses=app_statuses_grab_skip_priority,
        prefix="app_{}_grab",
    )

    count_exclude_grab_exclude_prio = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(application_status_id__in=app_statuses_grab_skip_priority)
        .exclude(product_line__product_line_code__in=ProductLineCodes.grab())
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_exclude_grab_exclude_prio,
        statuses=app_statuses_grab_skip_priority,
        prefix="app_{}",
    )

    # Partnership Agent Assisted Ledgen
    partnership_application_flag_ids = list(
        PartnershipApplicationFlag.objects.filter(
            name=PartnershipPreCheckFlag.APPROVED
        ).values_list('application_id', flat=True)
    )

    count_partnership_agent_assisted_ledgen = (
        Application.objects.filter(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
            pk__in=partnership_application_flag_ids,
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_partnership_agent_assisted_ledgen,
        statuses=app_status_partnership_agent_assisted,
        prefix="app_partnership_agent_assisted_{}",
    )

    # Julo starter
    count_jstarter = (
        Application.objects.filter(
            application_status_id__in=[121, ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE],
            partner=None,
            workflow__name=WorkflowConst.JULO_STARTER,
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )
    status_codes_counter(
        buckets=buckets,
        counter=count_jstarter,
        statuses=[121, ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE],
        prefix="app_{}_jstarter",
    )

    exclude_prio_count = (
        Application.objects.filter(
            application_status_id__in=app_statuses_skip_priority, partner__name__in=partner_list
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=exclude_prio_count,
        statuses=app_statuses_skip_priority,
        prefix="app_priority_{}",
    )

    # separate 124 j1 sonic and hsfbp and regular base on this card
    # https://juloprojects.atlassian.net/browse/ENH-1123
    partner_list_for_124 = LIST_PARTNER_EXCLUDE_PEDE
    application_124_ids = (
        Application.objects.exclude(partner__name__in=partner_list_for_124)
        .filter(
            application_status_id=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            workflow__name=WorkflowConst.JULO_ONE,
        )
        .values_list('id', flat=True)
    )
    application_ids_124_sonic_and_hsfb = ApplicationHistory.objects.filter(
        application_id__in=application_124_ids,
        status_new=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        change_reason__in=JuloOneChangeReason.NOT_REGULAR_VERIFICATION_CALLS_SUCCESSFUL_REASON,
    ).values_list('application_id', flat=True)
    grab_application_count = Application.objects.filter(
        workflow__name=WorkflowConst.GRAB,
        application_status_id=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
    ).count()
    count_124_sonic_and_hsfb = application_ids_124_sonic_and_hsfb.count()
    count_124_regular = application_124_ids.exclude(
        id__in=application_ids_124_sonic_and_hsfb
    ).count()
    setattr(buckets, "app_124_j1", count_124_regular)
    setattr(buckets, "app_124", int(count_124_sonic_and_hsfb) + int(grab_application_count))

    application_153_ids = (
        Application.objects.exclude(partner__name__in=partner_list)
        .filter(
            application_status_id=ApplicationStatusCodes.ACTIVATION_AUTODEBET,
            workflow__name=WorkflowConst.JULO_ONE,
        )
        .values_list('id', flat=True)
    )
    count_153 = application_153_ids.count()
    setattr(buckets, "app_153", count_153)

    start, end = courtesy_call_range()
    today = timezone.now().date()
    dpd_min_5 = today + relativedelta(days=5)
    courtesy_count = (
        Application.objects.select_related("loan__offer", "loan__loan_status")
        .filter(
            application_status__status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            loan__loan_status__status_code__range=(
                LoanStatusCodes.CURRENT,
                LoanStatusCodes.RENEGOTIATED,
            ),
            loan__fund_transfer_ts__range=[start, end],
            is_courtesy_call=False,
            loan__offer__first_payment_date__gt=dpd_min_5,
        )
        .count()
    )
    buckets.app_courtesy_call = courtesy_count

    # bucket cashback_request
    cashback_request_count = (
        CashbackTransferTransaction.objects.filter(transfer_status=XenditConst.STATUS_REQUESTED)
        .values("application")
        .annotate(Count("application"))
        .count()
    )
    buckets.app_cashback_request = cashback_request_count

    # bucket pending cashback
    cashback_pending_count = (
        CashbackTransferTransaction.objects.filter(
            transfer_status=CashbackTransferConst.STATUS_PENDING
        )
        .values("application")
        .annotate(Count("application"))
        .count()
    )
    buckets.app_cashback_pending = cashback_pending_count

    # bucket failed cashback
    cashback_failed_count = (
        CashbackTransferTransaction.objects.filter(
            transfer_status=CashbackTransferConst.STATUS_FAILED
        )
        .values("application")
        .annotate(Count("application"))
        .count()
    )
    buckets.app_cashback_failed = cashback_failed_count

    # bucket overpaid verification
    overpaid_verification_app_count = get_pending_overpaid_apps(return_count=True)
    buckets.app_overpaid_verification = overpaid_verification_app_count

    loan_statuses = LOAN_STATUS

    loan_statuses_julo_one = LOAN_STATUS_J1

    count_exclude_j1 = (
        Loan.objects.filter(loan_status__status_code__in=loan_statuses)
        .exclude(product__product_line__product_line_code=ProductLineCodes.J1)
        .values('loan_status__status_code')
        .annotate(status_count=Count('loan_status__status_code'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_exclude_j1,
        statuses=loan_statuses,
        prefix="loan_{}",
        types="loan",
    )

    count = (
        Loan.objects.filter(
            loan_status__status_code__in=loan_statuses_julo_one,
            product__product_line__product_line_code=ProductLineCodes.J1,
        )
        .values('loan_status__status_code')
        .annotate(status_count=Count('loan_status__status_code'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count,
        statuses=loan_statuses_julo_one,
        prefix="loan_{}_j1",
        types="loan",
    )

    buckets.loan_cycle_day_requested = Loan.objects.filter(cycle_day_requested__gte=1).count()

    customer_on_deletion_count = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.CUSTOMER_ON_DELETION,
    ).count()
    setattr(buckets, "app_185", customer_on_deletion_count)

    deleted_customer_count = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.CUSTOMER_DELETED,
    ).count()
    setattr(buckets, "app_186", deleted_customer_count)

    application_ids_j1_phone = Application.objects.filter(
        mobile_phone_1__isnull=False,
        ktp__isnull=False,
        email__isnull=False,
        application_status_id=ApplicationStatusCodes.FORM_CREATED,
        workflow__name=WorkflowConst.JULO_ONE,
        onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID,
    )

    customer_ids_otp_verified = (
        OtpRequest.objects.filter(
            is_used=True,
            customer_id__in=list(application_ids_j1_phone.values_list('customer_id', flat=True)),
            action_type__in=(
                SessionTokenAction.VERIFY_PHONE_NUMBER,
                SessionTokenAction.PHONE_REGISTER,
            ),
        )
        .distinct('customer_id')
        .values_list('customer_id', flat=True)
    )

    application_ids_j1_phone = application_ids_j1_phone.filter(
        customer_id__in=list(customer_ids_otp_verified),
    ).values_list('id', flat=True)

    # image ktp self
    app_ids_has_image_ktp = (
        Image.objects.filter(
            image_source__in=list(application_ids_j1_phone),
            image_type='ktp_self',
            image_status=Image.CURRENT,
        )
        .distinct('image_source')
        .values_list('image_source', flat=True)
    )

    # Image Selfie
    app_ids_has_image = (
        Image.objects.filter(
            image_source__in=list(app_ids_has_image_ktp),
            image_type='selfie',
            image_status=Image.CURRENT,
        )
        .distinct('image_source')
        .values_list('image_source', flat=True)
    )

    count_j1_agent_assisted = (
        Application.objects.filter(
            pk__in=list(app_ids_has_image),
        )
        .values('application_status_id')
        .annotate(status_count=Count('application_status_id'))
    )

    status_codes_counter(
        buckets=buckets,
        counter=count_j1_agent_assisted,
        statuses=app_status_j1_agent_assisted,
        prefix="app_agent_assisted_{}",
    )

    buckets.save()


@task(queue="partnership_global")
def partner_daily_report_mailer():
    partner_reports = PartnerReportEmail.objects.filter(is_active=True)
    for partner_report in partner_reports:
        today = timezone.localtime(timezone.now()).strftime("%d-%m-%Y")
        sql_query = partner_report.sql_query
        subject = partner_report.email_subject.replace("{date}", today)
        content = partner_report.email_content.replace("{date}", today)
        recipients = partner_report.email_recipients.strip().replace(" ", "").replace("\n", "")
        filename = partner_report.partner.name + "_disbursement_report_" + today + ".csv"

        email_cls = get_julo_email_client()
        status, headers = email_cls.email_partner_daily_report(
            filename, sql_query, subject, content, recipients
        )

        if status == 202:
            logger.info(
                {
                    "action": "send_email_partner_daily_report",
                    "partner": partner_report.partner.name,
                }
            )

            message_id = headers["X-Message-Id"]

            EmailHistory.objects.create(
                partner=partner_report.partner,
                sg_message_id=message_id,
                to_email=recipients,
                subject=subject,
                message_content=content,
                template_code="send_email_partner_daily_report",
            )


@task(queue="application_normal")
def scheduling_can_apply():
    today = timezone.localtime(timezone.now())
    customers = Customer.objects.filter(can_reapply_date__lte=today)
    for customer in customers:
        execute_can_reapply.delay(customer.id)


@task(queue="application_normal")
def execute_can_reapply(customer_id):
    customer = Customer.objects.get_or_none(id=customer_id)
    if not customer:
        return

    customer.can_reapply = True
    customer.disabled_reapply_date = None
    customer.can_reapply_date = None
    customer.save()

    last_application = customer.application_set.regular_not_deletes().last()
    if last_application:
        from juloserver.moengage.services.use_cases import (
            update_moengage_for_application_status_change_event,
        )

        if last_application.status == ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED:
            update_moengage_for_application_status_change_event.apply_async(
                (ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED, None, last_application.id),
                countdown=settings.DELAY_FOR_REALTIME_EVENTS,
            )
        elif last_application.status == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
            update_moengage_for_application_status_change_event.apply_async(
                (ApplicationStatusCodes.FORM_PARTIAL_EXPIRED, None, last_application.id),
                countdown=settings.DELAY_FOR_REALTIME_EVENTS,
            )
        allow_send_sms = last_application.partner_name not in LIST_PARTNER
        change_reason = last_application.applicationhistory_set.last().change_reason
        if allow_send_sms:
            if 'application_date_of_birth' in change_reason or 'age not met' in change_reason:
                send_sms_135_21year.delay(last_application.id)


@task(queue='application_low')
def trigger_send_follow_up_100_on_6_hours_subtask(application):
    subject = "Kredit Pinjaman Tanpa Agunan, Cair Cepat, Bisa dicicil!"
    template = "email_notif_100_on_6_hours.html"
    msg = render_to_string(template)

    julo_email_client = get_julo_email_client()
    app_id, email = application
    status, body, headers = julo_email_client.send_email(subject, msg, email, "cs@julofinance.com")
    logger.info(
        {
            "action": "email_notif_100_on_6_hours",
            "email": email,
        }
    )
    # record email history
    message_id = headers["X-Message-Id"]
    if status == 202:
        EmailHistory.objects.create(
            application_id=app_id,
            sg_message_id=message_id,
            to_email=email,
            subject=subject,
            message_content=msg,
            template_code="email_notif_100_on_6_hours",
        )


@task(queue="application_low")
def trigger_send_follow_up_100_on_6_hours():
    time_ago = timezone.now() - timedelta(hours=6)
    applications = (
        Application.objects.exclude(emailhistory__template_code="email_notif_100_on_6_hours")
        .filter(
            application_status__status_code=ApplicationStatusCodes.FORM_CREATED,
            email__isnull=False,
            cdate__lte=time_ago,
        )
        .exclude(product_line_id=ProductLineCodes.J1)
        .values_list('pk', 'email')
    )

    for app_details in applications:
        trigger_send_follow_up_100_on_6_hours_subtask.delay(app_details)


@task(name="tasks_assign_collection_agent")
def tasks_assign_collection_agent():
    agent_service = get_agent_service()
    type = None
    features = FeatureSetting.objects.filter(
        feature_name__in=[
            AGENT_ASSIGNMENT_DPD1_DPD29,
            AGENT_ASSIGNMENT_DPD30_DPD59,
            AGENT_ASSIGNMENT_DPD60_DPD89,
            AGENT_ASSIGNMENT_DPD90PLUS,
            AGENT_ASSIGNMENT_DPD1_DPD15,
            AGENT_ASSIGNMENT_DPD16_DPD29,
            AGENT_ASSIGNMENT_DPD30_DPD44,
            AGENT_ASSIGNMENT_DPD45_DPD59,
        ],
        category='agent',
        is_active=True,
    ).order_by('feature_name')
    for feature in features:
        type = convert_featurename_to_agentassignment_type(feature.feature_name)
        if type:
            payments, agents, last_agent = agent_service.get_data_assign_agent(type)
        if payments and agents and type:
            agent_service.process_assign_loan_agent(payments, agents, last_agent, type)
            payments, agents, last_agent, type = None, None, None, None


@task(queue="application_low")
def send_sms_reminder_138_subtask(application_id):
    application = Application.objects.get(pk=application_id)
    get_julo_sms = get_julo_sms_client()
    message, response, template = get_julo_sms.sms_reminder_138(application.mobile_phone_1)

    if response['status'] != '0':
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "application_id": application.id,
                "message": message,
            }
        )

    sms = create_sms_history(
        response=response,
        application=application,
        to_mobile_phone=format_e164_indo_phone_number(response["to"]),
        template_code=template,
        phone_number_type="mobile_phone_1",
        customer=application.customer,
        message_content=message,
    )

    logger.info(
        {
            "status": "sms_created",
            "sms_history_id": sms.id,
            "message_id": sms.message_id,
        }
    )


@task(queue="application_low")
def send_sms_reminder_138():
    now = timezone.localtime(timezone.now())
    one_day_ago = now - relativedelta(days=1)
    application_138 = (
        Application.objects.filter(
            application_status_id=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            applicationhistory__status_new=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            applicationhistory__cdate__lte=one_day_ago.date(),
            mobile_phone_1__isnull=False,
        )
        .exclude(product_line_id=ProductLineCodes.J1)
        .values_list("id", flat=True)
        .distinct()
        .order_by()
    )

    for application in application_138:
        send_sms_reminder_138_subtask.delay(application)


@task(queue="application_low")
def send_sms_reminder_175_daily_8am():
    reminder_days = 2
    date_now = timezone.now().date()
    sms_client = get_julo_sms_client()
    application_list = (
        Application.objects.filter(
            application_status__status_code=ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        )
        .exclude(product_line_id=ProductLineCodes.J1)
        .values_list('id', flat=True)
    )
    application_notes = ApplicationNote.objects.filter(
        application_id__in=list(application_list), note_text__icontains="follow up next day"
    ).values_list('application_id', flat=True)
    applications = Application.objects.filter(pk__in=list(application_notes))

    for application in applications:
        # Prevent race condition with agent check
        application.refresh_from_db()
        if application.status != ApplicationStatusCodes.NAME_VALIDATE_FAILED:
            continue

        diff_days = (date_now - application.udate.date()).days
        if reminder_days == diff_days:
            try:
                message, response, template = sms_client.sms_reminder_175(
                    application.mobile_phone_1
                )
                sms = create_sms_history(
                    response=response,
                    application=application,
                    customer_id=application.customer.id,
                    template_code=template,
                    to_mobile_phone=format_e164_indo_phone_number(response["to"]),
                    phone_number_type="mobile_phone_1",
                )

                logger.info(
                    {
                        "status": "sms_created",
                        "sms_history_id": sms.id,
                        "message_id": sms.message_id,
                    }
                )
            except:
                raise SmsNotSent(
                    {
                        "send_status": response["status"],
                        "application_id": application.id,
                        "message": message,
                    }
                )


# send sms when applican age has 21 year for 135 'age not met' application
@task(queue="application_low")
def send_sms_135_21year(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if application:
        get_julo_sms = get_julo_sms_client()
        message, response = get_julo_sms.sms_reminder_135_21year(application)

        if response["status"] != "0":
            raise SmsNotSent(
                {
                    "send_status": response["status"],
                    "application_id": application.id,
                    "message": message,
                }
            )
        else:
            sms = create_sms_history(
                response=response,
                customer=application.customer,
                application=application,
                to_mobile_phone=format_e164_indo_phone_number(response["to"]),
                phone_number_type="mobile_phone_1",
            )

            logger.info(
                {
                    "status": "sms_created",
                    "sms_history_id": sms.id,
                    "message_id": sms.message_id,
                }
            )


@task(name="trigger_automated_grab_status_change")
def trigger_automated_grab_status_change():
    grab_apps = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        product_line_id__in=ProductLineCodes.grab(),
        creditscore__isnull=False,
        customer__partnerreferral__product_id=32,
    )
    for app in grab_apps:
        try:
            if str(app.id)[-1] in ["1", "2", "3", "4", "5"]:
                process_application_status_change(
                    app.id,
                    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    "system_triggered",
                    "Acvt Call Experiment",
                )
            else:
                process_application_status_change(
                    app.id,
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
                    "system_triggered",
                )
        except:
            logger.warning(
                {
                    "status": "status_change_failed",
                    "application_id": app.id,
                    "customer_id": app.customer.id,
                }
            )


@task(queue="loan_low")
def email_fraud_alert_blast():
    # can_notify=True
    # block notify to ICare client
    loans = (
        Loan.objects.get_queryset()
        .for_fraud_alert_mail()
        .filter(application__customer__can_notify=True)
    )
    for loan in loans:
        julo_email_client = get_julo_email_client()
        status, headers, subject, msg = julo_email_client.email_fraud_alert(loan)

        # record email history
        if status == 202:
            message_id = headers["X-Message-Id"]
            EmailHistory.objects.create(
                application=loan.application,
                sg_message_id=message_id,
                to_email=loan.application.email,
                subject=subject,
                message_content=msg,
                template_code="email_fraud_alert",
            )


@task(name="checking_disbursement_failed")
def checking_disbursement_failed():
    now = timezone.localtime(timezone.now())
    disbursements_failed = Disbursement.objects.filter(
        disburse_status="FAILED",
        loan__application__application_status_id=ApplicationStatusCodes.NAME_VALIDATE_FAILED,
    )
    for disbursement in disbursements_failed:
        last_updated_disbursement = disbursement.udate + timedelta(hours=2)
        if last_updated_disbursement < now:
            application = disbursement.loan.application
            disbursement.retry_times += 1
            disbursement.save()
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                "Legal Agreement Signed",
                "Retry disburse {} times by system".format(disbursement.retry_times),
            )


@task(name='trigger_automated_status_165_to_170_subtask')
def trigger_automated_status_165_to_170_subtask(application_id):
    """sub task"""
    history = ApplicationHistory.objects.filter(
        application_id=application_id,
        status_new=ApplicationStatusCodes.LENDER_APPROVAL,
        cdate__lte=timezone.now() - timedelta(minutes=15),
    ).exists()
    if not history:
        return
    with transaction.atomic():
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
            "Legal agreement signed",
        )


@task(name="trigger_automated_status_165_to_170")
def trigger_automated_status_165_to_170():
    # the function is not used anymore
    # based on jira link: https://juloprojects.atlassian.net/browse/ON-603
    is_active_ftm_configuration = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FTM_CONFIGURATION, category="followthemoney", is_active=True
    ).exists()

    # if not is_active_ftm_configuration:
    if False:
        applications_165 = Application.objects.filter(
            application_status__status_code=ApplicationStatusCodes.LENDER_APPROVAL
        ).values_list("id", flat=True)
        for application_id in applications_165:
            trigger_automated_status_165_to_170_subtask.delay(application_id)


def is_app_to_be_called(app_id):
    auto_122_queue = Autodialer122Queue.objects.get_or_none(
        application_id=app_id, is_agent_called=False
    )
    if not auto_122_queue:
        return True
    if (
        auto_122_queue.auto_call_result_status not in ("busy", "answered")
        and auto_122_queue.attempt < 3
    ):
        return True
    return False


@task(queue="application_high")
@delay_voice_call
def ping_auto_call_122_subtask(application_id, company_phone_number):
    """ping auto call in independent worker"""

    time_limit = datetime.strptime("16:00:00", "%H:%M:%S").time()
    if datetime.now().time() > time_limit:
        logger.warn(
            {
                "action": "ping_auto_call_122",
                "status": "timeout",
            }
        )
        return

    if is_app_to_be_called(application_id):
        voice_client = get_voice_client()
        voice_client.ping_auto_call(company_phone_number, application_id)


@task(queue="application_high")
def filter_122_with_nexmo_auto_call():
    today = timezone.localtime(timezone.now()).date()
    try:
        filter_due_dates_by_weekend((today,))
        filter_due_dates_by_pub_holiday((today,))
    except JuloException:
        logger.info(
            {
                "action": "filter_122_with_nexmo_auto_call",
                "warning": "skip execute In public holiday or weekend",
            }
        )
        return

    feature = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.AUTO_CALL_PING_122)
    if feature and feature.is_active:
        apps = Application.objects.filter(application_status=122).values_list(
            "id", "company_phone_number"
        )
        for application_id, company_phone_number in apps:
            ping_auto_call_122_subtask.delay(application_id, company_phone_number)


@task(queue="application_high")
@delay_voice_call
def ping_auto_call_138_subtask(application_id, company_phone_number):
    """ping auto call in independent worker"""

    voice_client = get_voice_client()
    voice_client.ping_auto_call_138(company_phone_number, application_id)


@task(queue="application_high")
def filter_138_with_nexmo_auto_call():
    current_ts = timezone.localtime(timezone.now())
    today = current_ts.date()
    try:
        filter_due_dates_by_weekend((today,))
        filter_due_dates_by_pub_holiday((today,))
    except JuloException:
        logger.info(
            {
                "action": "filter_138_with_nexmo_auto_call",
                "warning": "skip execute In public holiday or weekend",
            }
        )
        return
    feature = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.AUTO_CALL_PING_138)
    if feature and feature.is_active:
        two_day_ago = current_ts - timedelta(days=2)
        app_histories = ApplicationHistory.objects.filter(
            status_new=138, application__application_status=138, cdate__lt=two_day_ago
        ).values_list("application_id", "application__company_phone_number")
        if not app_histories:
            return

        for application_id, company_phone_number in app_histories:
            ping_auto_call_138_subtask.delay(application_id, company_phone_number)


@task(name="prefix_notification_due_in_3_0_days")
def prefix_notification_due_in_3_0_days():
    command = NotificationCommand()
    command.send_notification_task([3, 0])


@task(name="prefix_notification_due_in_1_days")
def prefix_notification_due_in_1_days():
    command = NotificationCommand()
    command.send_notification_task([1])


@task(name="process_applications_mass_move")
def process_applications_mass_move(rows, filename):
    mass_move_task = MassMoveApplicationsHistory.objects.get_or_none(filename=filename)
    if mass_move_task:
        mass_move_task.status = "in progress"
        mass_move_task.save()
        logger.info({"task": "mass move applications", "filename": filename})
        processed_count = 0
        skip_count = 0
        bad_app_ids_count = 0
        bad_app_ids = []

        for row in rows:
            app_id = row["application_id"].strip()
            curr_status = int(row["current_status"].strip())
            new_status = int(row["new_status"].strip())
            note = row["notes"].strip()
            app = Application.objects.get_or_none(pk=app_id)
            if app:
                if app.status != curr_status:
                    logger.warning(
                        {
                            "task": "mass move applications",
                            "filename": filename,
                            "app_id": app.id,
                            "current_status": app.status,
                            "message": "status has been changed before",
                        }
                    )
                    bad_app_ids.append(app_id)
                    bad_app_ids_count += 1
                    continue
            else:
                logger.warning(
                    {
                        "task": "mass move applications",
                        "filename": filename,
                        "message": "application with id %s not found" % app_id,
                    }
                )
                bad_app_ids.append(app_id)
                bad_app_ids_count += 1
                continue

            result = process_application_status_change(
                app_id, new_status, change_reason="system_triggered", note=note
            )

            if result:
                processed_count += 1
            else:
                logger.error(
                    {
                        "task": "mass move applications",
                        "filename": filename,
                        "app_id": app.id,
                        "current_status": app.status,
                        "message": "change status failed",
                    }
                )
                continue
        mass_move_task.result = json.dumps(
            {
                "apps moved": processed_count,
                "apps skiped": skip_count,
                "apps has been moved before": bad_app_ids_count,
                "apps has been moved before ids": bad_app_ids,
            },
            indent=4,
        )
        mass_move_task.status = "finished"
        mass_move_task.save()
    else:
        logger.info(
            {
                "task": "mass move applications",
                "filename": filename,
                "message": "mass_move_history_not_found",
            }
        )


def is_app_to_be_missed_called(app_id):
    in_queue = PredictiveMissedCall.objects.filter(
        application_id=app_id, is_agent_called=False
    ).last()
    if not in_queue:
        return True
    if in_queue.auto_call_result_status not in ("busy", "answered") and in_queue.attempt < 2:
        return True
    return False


@task(queue="application_high")
@delay_voice_call
def predictive_missed_called_subtask(application_id, phone_number):
    """ping auto call in independent worker"""

    time_limit = datetime.strptime("19:00:00", "%H:%M:%S").time()
    if datetime.now().time() > time_limit:
        logger.warn(
            {
                "action": "predictive_missed_called",
                "status": "timeout",
            }
        )
        return

    if is_app_to_be_missed_called(application_id):
        voice_client = get_voice_client()
        voice_client.predictive_missed_called(phone_number, application_id)


@task(queue="application_high")
def filter_application_by_predictive_missed_call():
    today = timezone.localtime(timezone.now()).date()
    try:
        filter_due_dates_by_weekend((today,))
        filter_due_dates_by_pub_holiday((today,))
    except JuloException:
        logger.info(
            {
                "action": "filter_by_predictive_missed_call",
                "warning": "skip execute In public holiday or weekend",
            }
        )
        return

    feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PREDICTIVE_MISSED_CALL
    )
    if feature and feature.is_active:
        statuses = PredictiveMissedCall().moved_statuses + PredictiveMissedCall().unmoved_statuses
        apps = (
            Application.objects.filter(application_status__in=statuses)
            .exclude(partner__name__in=LIST_PARTNER)
            .values_list("id", "mobile_phone_1")
        )
        for application_id, mobile_number in apps:
            predictive_missed_called_subtask.delay(application_id, mobile_number)


@task(queue="application_normal")
def reset_stuck_predictive_missed_call_state():
    names = (FeatureNameConst.PREDICTIVE_MISSED_CALL, FeatureNameConst.AUTO_CALL_PING_122)

    features = FeatureSetting.objects.filter(
        feature_name__in=names, is_active=True, parameters__is_running=True
    )

    for feature in features:
        feature.parameters = {"is_running": False}
        feature.save()


@task(queue="application_normal")
def application_auto_expiration():
    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.APPLICATION_AUTO_EXPIRATION, is_active=True
    ).first()
    if feature and isinstance(feature.parameters, list):
        workflows = feature.parameters
        for workflow in workflows:
            paths = workflow['paths']
            for path in paths:
                expiration = timezone.now() - timedelta(days=path["expiration_days"])
                application_auto_expiration_subtask.delay(
                    path["origins"], path["destination"], expiration, workflow['name']
                )


@task(queue="application_normal")
def application_auto_expiration_subtask(origin, destination, expiration, workflow_name):
    workflow = Workflow.objects.filter(name=workflow_name).first()

    apps = Application.objects.filter(
        workflow=workflow, application_status__in=origin, udate__lte=expiration
    )

    is_hsfbp_path_tag = ApplicationPathTagStatus.objects.get(application_tag='is_hsfbp', status=1)

    list_of_app_id = [app.id for app in apps]
    high_score_app_ids = (
        ApplicationPathTag.objects.filter(
            application_id__in=list(list_of_app_id),
            application_path_tag_status_id=is_hsfbp_path_tag.id,
        )
        .values_list('application_id', flat=True)
        .distinct()
    )

    expired_apps = apps.exclude(pk__in=list(high_score_app_ids))

    for app in expired_apps:
        app.refresh_from_db()  # prevent race condition

        if app.application_status_id in origin:  # prevent race condition
            try:
                process_application_status_change(
                    app.id, destination, "system_triggered", "auto expiration"
                )
            except Exception as e:
                logger.warn(
                    {
                        'action': "change_status_error_from_{}_to_{}".format(
                            app.application_status_id, destination
                        ),
                        'application_id': app.id,
                        'error': e,
                    }
                )


@task(name="run_payment_experiment_at_9am")
def run_payment_experiment_daily_9am():
    today = timezone.now()
    experiments = ExperimentSetting.objects.filter(
        is_active=True,
        type="payment",
        schedule="09:00",
        start_date__lte=today,
        end_date__gte=today,
    )
    payment_experiment_daily(experiments)


@task(queue="application_high")
def complete_form_reminder_pn():
    apps = (
        Application.objects.filter(
            application_status=ApplicationStatusCodes.FORM_CREATED, customer__device__isnull=False
        )
        .exclude(product_line_id=ProductLineCodes.J1)
        .distinct()
    )

    for app in apps:
        customer = app.customer
        julo_pn_client = get_julo_pn_client()
        response = julo_pn_client.complete_form_notification(customer)
        logger.info(
            {
                "action": "complete_form_reminder_pn",
                "application_id": app.id,
                "response": response,
            }
        )


@task(queue='loan_low')
def loan_paid_off_PN(customer_id):
    customer = Customer.objects.get(pk=customer_id)
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.loan_paid_off_rating(customer)


@task(queue='application_normal')
def delete_empty_folder_image_upload():
    # delete empty folder image has moved to SSO
    os.system("find /webapps/juloserverve/media/image_upload/ -type d -empty -delete")


########## COLLECTION TASKS ##############


@task(queue='collection_normal')
def clear_overdue_promise_to_pay():
    today = timezone.localtime(timezone.now()).date()
    one_days_ago = today - timedelta(days=1)

    for payment in Payment.objects.filter(ptp_date__lte=one_days_ago):
        logger.info(
            {
                'action': 'setting ptp_date to None',
                'payment_id': payment.id,
                'ptp_date': payment.ptp_date,
            }
        )
        payment.update_safely(ptp_date=None)


@task(name='send_pn_payment_subtask')
def send_pn_payment_subtask(payment_id, pn_type):
    julo_pn_client = get_julo_pn_client()
    pn_service = getattr(julo_pn_client, pn_type)
    payment = Payment.objects.get(pk=payment_id)
    device = payment.loan.application.device
    if not pn_service and not have_pn_device(device):
        return

    try:
        pn_service(payment)
    except Exception as e:
        logger.warn(
            {
                'action': "send_pn_payment_error_{}".format(pn_type),
                'payment_id': payment.id,
                'error': e.message,
            }
        )


@task(name='send_all_pn_payment_reminders')
def send_all_pn_payment_reminders():
    today = timezone.localtime(timezone.now()).date()
    date_before_due = today + relativedelta(days=3)
    one_day_before_due = today + relativedelta(days=1)
    dates_after_due = []
    dates_after_due.append(today - relativedelta(days=1))
    dates_after_due.append(today - relativedelta(days=5))
    # The list comprehension matches dates 30, 60 ... 180 days due
    dates_after_due.extend([today - relativedelta(days=i * 30) for i in range(1, 7)])

    product_line_mtl_stl = ProductLineCodes.mtl() + ProductLineCodes.stl()
    query = (
        Payment.objects.select_related('loan')
        .normal()
        .not_paid_active()
        .exclude(loan__application__product_line__product_line_code__in=product_line_mtl_stl)
    )
    regular_payments = query.filter(ptp_date__isnull=True)
    ptp_payments = query.filter(ptp_date__isnull=False)

    three_days_ago_iter = chain(
        regular_payments.filter(due_date=date_before_due).values_list('id', flat=True),
        ptp_payments.filter(ptp_date=date_before_due).values_list('id', flat=True),
    )
    for payment_id in three_days_ago_iter:
        send_pn_payment_subtask.delay(payment_id, 'inform_payment_due_soon')

    one_day_ago_iter = chain(
        regular_payments.filter(
            loan__application__product_line__product_line_code__in=ProductLineCodes.grabfood(),
            due_date=one_day_before_due,
        ).values_list('id', flat=True),
        ptp_payments.filter(
            loan__application__product_line__product_line_code__in=ProductLineCodes.grabfood(),
            ptp_date=one_day_before_due,
        ).values_list('id', flat=True),
    )
    for payment_id in one_day_ago_iter:
        send_pn_payment_subtask.delay(payment_id, 'inform_payment_due_soon')

    today_iter = chain(
        regular_payments.filter(due_date=today).values_list('id', flat=True),
        ptp_payments.filter(ptp_date=today).values_list('id', flat=True),
    )
    for payment_id in today_iter:
        send_pn_payment_subtask.delay(payment_id, 'inform_payment_due_today')

    late_iter = chain(
        regular_payments.filter(due_date__in=dates_after_due)
        .exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.grabfood())
        .values_list('id', flat=True),
        ptp_payments.filter(ptp_date__in=dates_after_due)
        .exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.grabfood())
        .values_list('id', flat=True),
    )
    for payment_id in late_iter:
        send_pn_payment_subtask.delay(payment_id, 'inform_payment_late')


@task(name='send_all_pn_payment_mtl_stl_reminders')
def send_all_pn_payment_mtl_stl_reminders():
    julo_pn_client = get_julo_pn_client()
    today = timezone.localtime(timezone.now()).date()
    # except payment with can_notify = False
    payments = Payment.objects.not_paid_active().filter(
        ptp_date__isnull=True, loan__application__customer__can_notify=True
    )
    late_date_range = [1, 2, 3, 4, 5, 30, 60, 90, 120, 150, 180]

    # PN T-5 > T-0
    for i in range(6):
        range_days = today + relativedelta(days=i)
        mtl_payment = payments.filter(
            loan__application__product_line__product_line_code__in=ProductLineCodes.mtl(),
            due_date=range_days,
        )
        stl_payment = payments.filter(
            loan__application__product_line__product_line_code__in=ProductLineCodes.stl(),
            due_date=range_days,
        )
        for payment in mtl_payment:
            device = payment.loan.application.device
            if have_pn_device(device):
                julo_pn_client.inform_mtl_payment(payment)  # PN t-5 MTL
        for payment in stl_payment:
            device = payment.loan.application.device
            if have_pn_device(device):
                julo_pn_client.inform_stl_payment(payment)  # PN t-5 > t-0 STL

    # PN T+1, T+5, T+29, T+60 ...
    for i in late_date_range:
        range_days = today - relativedelta(days=i)
        mtl_payment = payments.filter(
            loan__application__product_line__product_line_code__in=ProductLineCodes.mtl(),
            due_date=range_days,
        )
        stl_payment = payments.filter(
            loan__application__product_line__product_line_code__in=ProductLineCodes.stl(),
            due_date=range_days,
        )
        for payment in mtl_payment:
            device = payment.loan.application.device
            if have_pn_device(device):
                julo_pn_client.inform_mtl_payment(payment)  # PN t+1 > t+4 MTL
        for payment in stl_payment:
            device = payment.loan.application.device
            if have_pn_device(device):
                julo_pn_client.inform_stl_payment(payment)  # PN t+1 > t+4 STL


@task(queue='collection_low')
def send_sms_payment_reminder(payment_id, sms_client_method_name):
    """
    Depracated task function since migrate to send_automated_comms tasks
    """
    payment = Payment.objects.select_related('loan__application__product_line').get(id=payment_id)
    skip_task = False
    product_line_code = payment.loan.application.product_line.product_line_code
    if sms_client_method_name == 'sms_payment_dpd_10' and product_line_code in MTL:
        skip_task = True
    if sms_client_method_name == 'sms_payment_dpd_21' and product_line_code in STL:
        skip_task = True
    if not skip_task:
        julo_sms_client = get_julo_sms_client()
        # Experiment sms
        start_date_experiment = date(2018, 10, 27)
        end_date_experiment = date(2018, 11, 12)
        criteria = ['1', '2', '3', '4', '5']
        is_success = False
        if (
            start_date_experiment <= payment.due_date <= end_date_experiment
            and str(payment.loan_id)[-1] in criteria
            and product_line_code in (MTL + STL)
        ):
            sms_client_method = getattr(julo_sms_client, 'sms_experiment')
            try:
                txt_msg, response, template = sms_client_method(payment, sms_client_method_name)
                is_success = True
            except Exception as e:
                is_success = False
                logger.error(
                    {
                        'reason': 'SMS not sent',
                        'payment_id': payment_id,
                        'Due date': payment.due_date,
                        'product_line_code': product_line_code,
                    }
                )
                pass
        else:
            sms_client_method = getattr(julo_sms_client, sms_client_method_name)
            try:
                txt_msg, response, template = sms_client_method(payment)
                is_success = True
            except Exception as e:
                is_success = False
                logger.error(
                    {
                        'reason': 'SMS not sent',
                        'payment_id': payment_id,
                        'Due date': payment.due_date,
                        'product_line_code': product_line_code,
                    }
                )
                pass
        if is_success == True:
            if response['status'] != '0':
                raise SmsNotSent(
                    {
                        'send_status': response['status'],
                        'payment_id': payment.id,
                        'message_id': response.get('message-id'),
                        'sms_client_method_name': sms_client_method_name,
                        'error_text': response.get('error-text'),
                    }
                )

            application = payment.loan.application
            customer = application.customer
            sms = create_sms_history(
                response=response,
                customer=customer,
                application=application,
                payment=payment,
                template_code=template,
                message_content=txt_msg,
                to_mobile_phone=format_e164_indo_phone_number(response['to']),
                phone_number_type='mobile_phone_1',
            )

            logger.info(
                {
                    'status': 'sms_created',
                    'payment_id': payment.id,
                    'sms_history_id': sms.id,
                    'message_id': sms.message_id,
                }
            )


@task(queue='collection_low')
def send_all_email_payment_reminders_subtask(payment_id, date_key):
    """sub task to send email 1 mail/1 worker"""
    payment = Payment.objects.select_related("loan__application").get(pk=payment_id)
    application = payment.loan.application
    if application.partner:
        if application.partner.is_grab:
            return

    julo_email_client = get_julo_email_client()
    status, headers, subject, content = julo_email_client.email_payment_reminder(payment, date_key)

    if status == 202:
        customer_id = application.customer_id
        to_email = application.email
        message_id = headers['X-Message-Id']
        template_code = 'email_reminder_dpd_-' + str(date_key)
        if application.product_line.product_line_code in STL:
            template_code = 'stl_email_reminder_dpd_-' + str(date_key)
        if date_key == '+4':
            template_code = template_code.replace("-", "")

        EmailHistory.objects.create(
            payment=payment,
            application=application,
            customer_id=customer_id,
            sg_message_id=message_id,
            to_email=to_email,
            subject=subject,
            message_content=content,
            template_code=template_code,
        )

        logger.info(
            {
                'status': status,
                'payment_id': payment.id,
                'message_id': message_id,
                'to_email': to_email,
            }
        )

    else:
        logger.warn(
            {
                'status': status,
                'payment_id': payment.id,
            }
        )


@task(name='send_all_email_payment_reminders')
def send_all_email_payment_reminders():
    """
    scheduled to send email to all payment which in T-5, T-3, T-1, T+4
    """
    today = timezone.localtime(timezone.now()).date()
    # except payment with can_notify = False
    today_minus_4 = today - relativedelta(days=4)
    dpd_exclude = [
        today_minus_4,
    ]
    payments_id_exclude_pending_refinancing = get_payments_refinancing_pending_by_dpd(dpd_exclude)

    query = (
        Payment.objects.not_paid_active()
        .filter(loan__application__customer__can_notify=True)
        .exclude(id__in=payments_id_exclude_pending_refinancing)
    )
    regular_payments = query.filter(ptp_date__isnull=True)
    ptp_payments = query.filter(ptp_date__isnull=False)

    # Reminders 2 and 4 days before due_date (or ptp_date)
    for i in [2, 4]:
        iter_chain = list(
            regular_payments.filter(due_date=today + relativedelta(days=i)).values_list(
                "id", flat=True
            )
        ) + list(
            ptp_payments.filter(ptp_date=today + relativedelta(days=i)).values_list("id", flat=True)
        )
        for payment_id in iter_chain:
            send_all_email_payment_reminders_subtask.delay(payment_id, i)

    # Reminders plus 4
    iter_chain = list(
        regular_payments.filter(due_date=today - relativedelta(days=4)).values_list("id", flat=True)
    )
    for payment_id in iter_chain:
        send_all_email_payment_reminders_subtask.delay(payment_id, "+4")


@task(name='send_whatsapp_payment_reminder')
def send_whatsapp_payment_reminder(payment_id):
    """
    Deprecated Since we move to Golang Whatsapp Service
    send_whatsapp_otp_go()
    """
    payment = Payment.objects.select_related('loan__application__customer').get(pk=payment_id)
    wa_client = get_julo_whatsapp_client()
    wa_client.send_wa_payment_reminder(payment)
    payment.is_whatsapp_blasted = True
    payment.save(update_fields=['is_whatsapp_blasted'])


@task(name='send_all_whatsapp_payment_reminders')
def send_all_whatsapp_payment_reminders():
    """
    Depracated task function since migrate to send_automated_comms tasks
    """
    failed_robo_payments = Payment.objects.failed_robocall_payments(STL + MTL)
    t_min_5_payment_ids = failed_robo_payments.dpd(-5).values_list('id', flat=True)
    t_min_3_payment_ids = failed_robo_payments.dpd(-3).values_list('id', flat=True)
    # today = timezone.localtime(timezone.now()).date()
    # t_min_3_payment_ids_test = []
    # if  date(2019, 5, 24) <= today <= date(2019, 7, 5):
    #     t_min_3_test = failed_robo_payments.dpd(-3).values('id', 'loan__id')
    #     t_min_3_payment_ids_test = [p['id'] for p in t_min_3_test
    #                                 if (p['loan__id'] % 10 in (4, 5, 6))]  # tail test group number 4,5,6
    remind_payment_ids = list(t_min_5_payment_ids) + list(t_min_3_payment_ids)
    Payment.objects.filter(id__in=remind_payment_ids).update(
        is_whatsapp=False
    )  # move out of (manual) WA bucket

    for payment_id in remind_payment_ids:
        # send_whatsapp_payment_reminder.delay(payment_id)
        send_sms_payment_reminder.delay(payment_id, 'sms_payment_reminder_replaced_wa')


@task(name='send_whatsapp_on_wa_bucket')
def send_whatsapp_on_wa_bucket(payment_id):
    """
    Deprecated Since we move to Golang Whatsapp Service
    send_whatsapp_otp_go()
    """
    payment = Payment.objects.get(pk=payment_id)
    wa_client = get_julo_whatsapp_client()
    wa_client.send_wa_payment_reminder(payment)
    payment.update_safely(is_whatsapp=False, is_whatsapp_blasted=True)


@task(name='send_all_whatsapp_on_wa_bucket')
def send_all_whatsapp_on_wa_bucket():
    """
    To send whatsapp reminder for payments that are on wa bucket.
    The schedules are set at 17:00 PM and 20:00 PM everyday.
    """
    payments_on_wa_bucket = Payment.objects.get_payments_on_wa_bucket()

    for payment in payments_on_wa_bucket:
        send_whatsapp_on_wa_bucket.delay(payment.id)


@task(queue="collection_low")
def fill_uncalled_today_bucket():
    payment_active = Payment.objects.normal()
    uncalled_payments = payment_active.uncalled_group(from_task=True)
    for payment in uncalled_payments:
        if not payment.is_collection_called:
            today = timezone.localtime(timezone.now()).date()
            payment.uncalled_date = today
            payment.save(update_fields=['uncalled_date', 'udate'])


@task(queue='collection_normal')
def reset_collection_called_status_for_unpaid_payment():
    payment_active = Payment.objects.normal()
    to_be_reset_payments = payment_active.not_paid_active().filter(is_collection_called=True)
    for payment in to_be_reset_payments:
        payment.update_safely(
            is_collection_called=False, is_whatsapp=False, is_whatsapp_blasted=False
        )


@task(name='activate_lebaran_promo')
def activate_lebaran_promo():
    mindate = date(2018, 6, 8)
    maxdate = date(2018, 7, 7)
    today = timezone.localtime(timezone.now()).date()
    if today <= mindate:
        loans = Loan.objects.filter(payment__paymentevent__event_type='lebaran_promo')
        temp_loans = []
        for loan in loans:
            temp_loans.append(loan)
        disbursed_status = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        payments = (
            Payment.objects.normal()
            .filter(
                due_date__range=[mindate, maxdate],
                loan__application__customer__can_notify=True,
                loan__application__application_status_id=disbursed_status,
            )
            .exclude(loan__application__product_line_id__in=[40, 41, 50, 51])
            .exclude(payment_status_id__gte=PaymentStatusCodes.PAID_ON_TIME)
            .exclude(paymentevent__event_type='lebaran_promo')
            .order_by('id')
        )
        for payment in payments:
            if payment.loan not in temp_loans:
                if payment.due_amount <= 700000:
                    disc = 50000
                else:
                    disc = 100000
                with transaction.atomic():
                    event_date = today
                    PaymentEvent.objects.create(
                        payment=payment,
                        event_payment=disc,
                        event_due_amount=payment.due_amount,
                        event_date=event_date,
                        event_type='lebaran_promo',
                    )
                    payment.due_amount = payment.due_amount - disc
                    payment.paid_amount = payment.paid_amount + disc
                    payment.save(update_fields=['due_amount', 'paid_amount', 'udate'])
                    ApplicationNote.objects.create(
                        note_text='Promo Lebaran Disc', application_id=payment.loan.application.id
                    )
                temp_loans.append(payment.loan)


@task(name='send_email_lebaran_promo')
def send_email_lebaran_promo():
    payment_events = PaymentEvent.objects.filter(event_type='lebaran_promo').exclude(
        payment__payment_status_id__gte=330
    )
    julo_email_client = get_julo_email_client()
    for payment_event in payment_events:
        payment = payment_event.payment
        application = payment.loan.application
        status, headers, subject, msg = julo_email_client.email_lebaran_promo(application.email)

        # record email history
        if status == 202:
            message_id = headers['X-Message-Id']
            EmailHistory.objects.create(
                application=application,
                sg_message_id=message_id,
                to_email=application.email,
                subject=subject,
                message_content=msg,
                template_code='email_lebaran_promo',
            )


@task(name='send_sms_lebaran_promo')
def send_sms_lebaran_promo():
    payment_events = PaymentEvent.objects.filter(event_type='lebaran_promo').exclude(
        payment__payment_status_id__gte=330
    )
    get_julo_sms = get_julo_sms_client()
    for payment_event in payment_events:
        payment = payment_event.payment
        application = payment.loan.application
        if application.mobile_phone_1:
            try:
                message, response = get_julo_sms.sms_lebaran_promo(application, payment_event)

                if response['status'] != '0':
                    logger.warn(
                        {
                            'send_status': response['status'],
                            'application_id': application.id,
                            'message': message,
                        }
                    )
                else:
                    sms = create_sms_history(
                        response=response,
                        customer=application.customer,
                        application=application,
                        to_mobile_phone=format_e164_indo_phone_number(response['to']),
                        phone_number_type='mobile_phone_1',
                    )
                    logger.info(
                        {
                            'status': 'sms_created',
                            'sms_history_id': sms.id,
                            'message_id': sms.message_id,
                        }
                    )
            except:
                logger.warn(
                    {
                        'status': 'send_sms_lebaran_failed',
                        'application_id': application.id,
                    }
                )


@task(name='send_pn_lebaran_promo')
def send_pn_lebaran_promo():
    payment_events = PaymentEvent.objects.filter(event_type='lebaran_promo').exclude(
        payment__payment_status_id__gte=330
    )
    julo_pn_client = get_julo_pn_client()
    for payment_event in payment_events:
        payment = payment_event.payment
        application = payment.loan.application
        if have_pn_device(application.device):
            logger.info(
                {
                    'action': 'send_pn_lebaran_promo',
                    'application_id': application.id,
                }
            )
            julo_pn_client.notify_lebaran_promo(application)


@task(queue='loan_high')
def checking_cashback_delayed():
    wallets = CustomerWalletHistory.objects.filter(change_reason='payment_on_time_delayed')
    list_wallet_delays = []
    for wallet in wallets:
        list_wallet_delays.append(wallet.id)
    if list_wallet_delays:
        notify_count_cashback_delayed(list_wallet_delays)


@task(name='send_asian_games_campaign')
def send_asian_games_campaign():
    sms_dates = [date(2018, 8, x) for x in [11, 16, 23, 27, 31]] + [
        date(2018, 9, x) for x in [1, 2]
    ]
    pn_dates = [date(2018, 8, x) for x in [13, 17, 24, 28, 29, 30, 31]] + [
        date(2018, 9, x) for x in [1, 2]
    ]
    email_dates = [date(2018, 8, x) for x in [15, 22, 29, 30]] + [date(2018, 9, x) for x in [2]]

    today = timezone.localtime(timezone.now()).date()
    payments = (
        Payment.objects.normal()
        .filter(due_date__range=['2018-08-18', '2018-09-04'])
        .by_product_line_codes(ProductLineCodes.mtl())
        .not_overdue()
        .not_paid_active()
    )
    if today in sms_dates:
        get_julo_sms = get_julo_sms_client()
        for payment in payments:
            application = payment.loan.application
            message = (
                'Hi %s lunasi angsuran ke-%s Anda 2 hari sblm jth tempo & '
                'dapatkan cashback sebesar Rp 20.000! Berlaku s/d 2 sept 18. '
                'S&K: [bit.ly/promojulo]'
            ) % (application.fullname, payment.payment_number)
            if application.mobile_phone_1:
                try:
                    no_hp1 = format_e164_indo_phone_number(application.mobile_phone_1)
                    get_julo_sms.send_sms(no_hp1, message)
                except Exception as e:
                    logger.warn(
                        {'action': 'send_sms_asian_games_campaign', 'status': 'failed', 'error': e}
                    )

    if today in pn_dates:
        get_julo_pn = get_julo_pn_client()
        for payment in payments:
            customer = payment.loan.customer
            try:
                get_julo_pn.inform_asian_games_campaign(customer)
            except Exception as e:
                logger.warn(
                    {'action': 'send_pn_asian_games_campaign', 'status': 'failed', 'error': e}
                )

    if today in email_dates:
        get_julo_email = get_julo_email_client()
        for payment in payments:
            application = payment.loan.application
            email = application.email

            try:
                get_julo_email.email_promo_asian_games_blast(email)
            except Exception as e:
                logger.warn(
                    {
                        'action': 'send_email_asian_games_campaign',
                        'application': application.id,
                        'status': 'failed',
                        'error': e,
                    }
                )


@task(queue='loan_high')
def checking_cashback_abnormal():
    wallets = CustomerWalletHistory.objects.values(
        'customer_id', 'id', 'loan_id', 'payment_id'
    ).filter(
        wallet_balance_accruing__lt=F('wallet_balance_available'),
        wallet_balance_available__gt=0,
        latest_flag=True,
    )
    if wallets:
        notify_cashback_abnormal(list(wallets))


@task(queue='collection_high')
def reverse_waive_late_fee_daily():
    payment_event_service = get_payment_event_service()
    today = timezone.localtime(timezone.now()).date()
    note = 'reverse waive late fee daily by system.'
    payment_events = PaymentEvent.objects.select_related('payment__due_amount').filter(
        event_type='waive_late_fee', event_date=today, can_reverse=True
    )
    for payment_event in payment_events:
        if payment_event.payment.due_amount > 0:
            payment_event_service.process_reversal_event_type_waive_late_fee(payment_event, note)


@task(name='run_payment_experiment_at_9am')
def run_payment_experiment_daily_9am():
    today = timezone.now()
    experiments = ExperimentSetting.objects.filter(
        is_active=True, type="payment", schedule='09:00', start_date__lte=today, end_date__gte=today
    )
    payment_experiment_daily(experiments)


def log_url(customer, url, url_type):
    return WarningUrl.objects.create(
        customer=customer, url=url, is_enabled=True, url_type=url_type, warning_method=WARNING_TYPE
    )


def send_email_warning_letter(customer, loan, customer_email, url, last_date):
    url = url + "#email"
    template = TEMPLATES[WARNING_TYPE]
    application = loan.application
    payment_method = PaymentMethod.objects.filter(loan=loan, payment_method_code=319322).first()
    due_payment = (
        Payment.objects.normal()
        .filter(payment_status__lte=327, loan=loan, payment_status__gte=320)
        .order_by('due_date')
    )

    bank_code = PaymentMethodLookup.objects.filter(name=loan.julo_bank_name).first().code

    if due_payment:
        not_payed_start = due_payment.first().due_date
        not_payed_end = due_payment.last().due_date
        principal_sum = due_payment.aggregate(Sum('installment_principal'))[
            'installment_principal__sum'
        ]
        late_fee_applied_sum = due_payment.aggregate(Sum('late_fee_amount'))['late_fee_amount__sum']
        installment_interest = due_payment.aggregate(Sum('installment_interest'))[
            'installment_interest__sum'
        ]
        paid_sum = due_payment.aggregate(Sum('paid_amount'))['paid_amount__sum']
        change_due_date_interest = due_payment.aggregate(Sum('change_due_date_interest'))[
            'change_due_date_interest__sum'
        ]
        # due_sum = principal_sum + late_fee_applied_sum + installment_interest
        while paid_sum > 0:
            if principal_sum > 0:
                if paid_sum > principal_sum:
                    paid_sum -= principal_sum
                    principal_sum = 0
                else:
                    principal_sum -= paid_sum
                    paid_sum = 0
            elif installment_interest > 0:
                if paid_sum > installment_interest:
                    paid_sum -= installment_interest
                    installment_interest = 0
                else:
                    installment_interest -= paid_sum
                    paid_sum = 0
            elif late_fee_applied_sum > 0:
                if paid_sum > late_fee_applied_sum:
                    paid_sum -= late_fee_applied_sum
                    late_fee_applied_sum = 0
                else:
                    late_fee_applied_sum -= paid_sum
                    paid_sum = 0
            elif change_due_date_interest > 0:
                if paid_sum > change_due_date_interest:
                    paid_sum -= change_due_date_interest
                    change_due_date_interest = 0
                else:
                    change_due_date_interest -= paid_sum
                    paid_sum = 0
        total_sum = (
            principal_sum + late_fee_applied_sum + installment_interest + change_due_date_interest
        )
    else:
        not_payed_start = ""
        not_payed_end = ""
        principal_sum = ""
        late_fee_applied_sum = ""
        installment_interest = ""
        total_sum = 0

    context = {
        "url": url,
        "name": application.fullname_with_title,
        "loan_amount": loan.loan_amount,
        "loan_duration": loan.loan_duration,
        "application_xid": application.application_xid,
        "late_fee_amount": loan.late_fee_amount,
        "accepted_date": loan.sphp_accepted_ts.date(),
        "fullname": application.fullname_with_title,
        "name_only": application.fullname,
        "phone": customer.phone,
        "now": timezone.now().date(),
        "sphp_accepted_ts": loan.sphp_accepted_ts.date(),
        "not_payed_start": not_payed_start,
        "not_payed_end": not_payed_end,
        "due_amount_sum": principal_sum,
        "installment_interest": installment_interest,
        "late_fee_applied_sum": late_fee_applied_sum,
        "total_sum": format_number(total_sum, locale='id_ID'),
        "julo_bank_account_number": loan.julo_bank_account_number,
        "julo_bank_name": loan.julo_bank_name,
        "header_image": settings.EMAIL_STATIC_FILE_PATH + "header.png",
        "footer_image": settings.EMAIL_STATIC_FILE_PATH + "footer.png",
        "sign_image": settings.EMAIL_STATIC_FILE_PATH + "sign.png",
        'last_date': last_date,
        'bank_code': bank_code,
    }

    if payment_method:
        context['payment_method_name'] = payment_method.payment_method_name
        context['virtual_account'] = payment_method.virtual_account
    else:
        context['payment_method_name'] = ""
        context['virtual_account'] = ""
    text_message = render_to_string(template['email'], context=context)
    subject = template['subject'] + " - " + customer.email
    email = get_julo_email_client()
    status, headers, subject, msg = email.agreement_email(customer_email, text_message, subject)
    if status == 202:
        message_id = headers['X-Message-Id']
        EmailHistory.objects.create(
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=customer_email,
            subject=subject,
            message_content=msg,
            template_code='warningletterone',
        )

    else:
        logger.warning({'status': status, 'message_id': headers['X-Message-Id']})


def send_agreement(application_id, customer_email):
    application = Application.objects.get_or_none(pk=application_id)
    customer_id = application.customer_id
    loan_status = application.loan.loan_status
    customer = Customer.objects.get_or_none(pk=customer_id)
    last_date = ""
    url = WarningUrl.objects.filter(
        url_type="email", customer=customer, warning_method=WARNING_TYPE
    ).first()
    template = TEMPLATES[WARNING_TYPE]

    if customer:

        loan = (
            Loan.objects.filter(customer=customer, loan_status_id=loan_status).order_by('id').last()
        )
    else:
        logger.error("Customer not Found" + application_id)
        return

    if url:
        shorten_url_string = url.url
    else:
        encrypttext = encrypt()
        encoded_customer_id = encrypttext.encode_string(str(customer_id))
        url = template['url'].format(customer_id=encoded_customer_id)
        url = (
            url
            + "?date="
            + str(timezone.now().date())
            + "&ldate="
            + last_date
            + "&type="
            + WARNING_TYPE
        )
        shorten_url_string = url
        log_url(customer, url, "email")
    send_email_warning_letter(customer, loan, customer_email, shorten_url_string, last_date)


@task(name='run_payday_experiment')
def run_payday_experiment():
    if settings.ENVIRONMENT == "prod":
        """
        scheduled to send warningletter to all from excelsheet
        """
        csv_file_name = '../../email_blast/190212 WL1 Payday Experiment.csv'
        try:
            customer_csv = open(csv_file_name, 'rb')
        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
        application_index = None
        customer_email = None
        day = None
        csv_reader = csv.reader(customer_csv, delimiter=';', quotechar='"')

        for row in csv_reader:
            if application_index == None:
                application_index = row.index('application_id')
                customer_email = row.index('email')
                day = row.index('date')
            else:

                if int(row[day]) == timezone.localtime(timezone.now()).day:
                    send_agreement(row[application_index], row[customer_email])


@task(name='run_agent_active_flag_update')
def run_agent_active_flag_update():
    """
    scheduled to update active field of agent table to inactive based on expiry date
    """
    today = date.today()
    agents = Agent.objects.filter(inactive_date__lt=today, inactive_date__isnull=False)
    for agent in agents:
        User.objects.filter(username=agent.user.username).update(is_active=False)


#########################
# MARCH 2019 EXPERIMENT #
#########################


@task(name='send_sms_march_lottery')
def send_sms_march_lottery(population):
    def parsedate(string):
        date_obj = datetime.strptime(string, '%d/%m/%y').date()
        return datetime.strftime(date_obj, '%d/%m')

    sms_client = get_julo_sms_client()
    for person in population:
        application = Application.objects.get(pk=person['application_id'])
        template_name = '201903_exp/20190320_March SMS Promo T-5 Cash'
        context = {
            'first_name': application.first_name_with_title,
            'deadline': parsedate(person['deadline']),
        }
        message = render_to_string(template_name + '.txt', context)
        phone_number = format_e164_indo_phone_number(application.mobile_phone_1)

        try:
            text_message, response = sms_client.send_sms(phone_number, message)
            response = response['messages'][0]
            if response['status'] == '0':
                sms = create_sms_history(
                    response=response,
                    customer=application.customer,
                    application=application,
                    template_code=template_name,
                    message_content=text_message,
                    to_mobile_phone=format_e164_indo_phone_number(response['to']),
                    phone_number_type='mobile_phone_1',
                )
        except Exception as e:
            pass


@task(name='send_email_march_lottery')
def send_email_march_lottery(population):
    def parsedate(string):
        date_obj = datetime.strptime(string, '%d/%m/%y').date()
        return datetime.strftime(date_obj, '%d-%m-%Y')

    email_client = get_julo_email_client()
    for person in population:
        application = Application.objects.get(pk=person['application_id'])
        template_name = '201903_exp/20190320_March Email Promo T-5 Cash'
        deadline = parsedate(person['deadline'])
        context = {
            'fullname': application.fullname,
            'deadline': parsedate(person['deadline']),
        }
        message = render_to_string(template_name + '.html', context)
        try:
            subject = 'Bayar Cicilan Sebelum {}, Menangkan Uang Tunai 2 Juta!'.format(deadline)
            status, body, headers = email_client.send_email(
                subject=subject, content=message, email_to=application.email
            )
            email = EmailHistory.objects.create(
                application=application,
                customer=application.customer,
                sg_message_id=message_id,
                to_email=application.email,
                subject=subject,
                message_content=message,
                template_code=template_name,
            )
        except Exception as e:
            pass


@task(name='run_march_lottery_experiment')
def run_march_lottery_experiment():
    def parsedate(string):
        return datetime.strptime(string, '%d/%m/%y').date()

    today = timezone.localtime(timezone.now()).date()

    if today <= date(2019, 4, 1):
        Row = namedtuple('Row', ('application_id', 'loan_id', 'due_date', 'deadline', 'blast_date'))
        with open('../../email_blast/190321 T-5 March Promo Email.csv', 'r') as f:
            data = csv.reader(f, delimiter=';')
            next(data)  # Skip header
            email_population_data = [Row(*row) for row in data]
            email_population_data = [
                row for row in email_population_data if (parsedate(row.blast_date) == today)
            ]
            email_population = []
            for person in email_population_data:
                email_population.append(
                    {"application_id": person.application_id, "deadline": person.deadline}
                )

        with open('../../email_blast/190321 T-5 March Promo SMS.csv', 'r') as f:
            data = csv.reader(f, delimiter=';')
            next(data)  # Skip header
            sms_population_data = [Row(*row) for row in data]
            sms_population_data = [
                row for row in sms_population_data if (parsedate(row.blast_date) == today)
            ]
            sms_population = []
            for person in sms_population_data:
                sms_population.append(
                    {"application_id": person.application_id, "deadline": person.deadline}
                )

        send_sms_march_lottery.delay(email_population)
        send_email_march_lottery.delay(sms_population)


@task(name='send_rnf_t2_sms')
def send_rnf_t2_sms(persona, loan_ids):
    today = timezone.localtime(timezone.now()).date()
    query = Payment.objects.not_paid_active()
    payments = (
        query.filter(loan_id__in=loan_ids).distinct('loan_id').order_by('loan_id', 'due_date')
    )
    for payment in payments:
        if payment.due_date <= today + timedelta(days=2):
            plc = payment.loan.application.product_line.product_line_code
            if plc in ProductLineCodes.stl():
                template_name = '201903_exp/' + persona + '_t2_stl'
                context = {
                    'name': payment.loan.application.first_name_with_title,
                    'due_amount': display_rupiah(payment.due_amount),
                    'due_date': datetime.strftime(payment.due_date, '%d/%m'),
                    'url': 'https://bit.ly/julocarabayar',
                }
                message = render_to_string(template_name + '.txt', context)
            else:
                template_name = '201903_exp/' + persona + '_t2_mtl'
                cashback_amount = 0.01 * (
                    old_div(payment.loan.loan_amount, payment.loan.loan_duration)
                )
                context = {
                    'name': payment.loan.application.first_name_with_title,
                    'cashback_multiplier': payment.cashback_multiplier,
                    'payment_cashback_amount': display_rupiah(int(cashback_amount)),
                    'due_date_minus_2': datetime.strftime(
                        payment.due_date - timedelta(days=2), '%d/%m'
                    ),
                    'payment_number': payment.payment_number,
                    'due_amount': display_rupiah(payment.due_amount),
                    'due_date': datetime.strftime(payment.due_date, '%d/%m'),
                    'url': 'https://bit.ly/julocarabayar',
                }
                message = render_to_string(template_name + '.txt', context)

            client = get_julo_sms_client()
            phone_number = format_e164_indo_phone_number(payment.loan.application.mobile_phone_1)

            try:
                text_message, response = client.send_sms(phone_number, message)
                response = response['messages'][0]
                if response['status'] == '0':
                    sms = create_sms_history(
                        response=response,
                        customer=payment.loan.application.customer,
                        application=payment.loan.application,
                        payment=payment,
                        template_code=template_name,
                        message_content=text_message,
                        to_mobile_phone=format_e164_indo_phone_number(response['to']),
                        phone_number_type='mobile_phone_1',
                    )
            except Exception as e:
                pass


@task(name='send_rnf_t0_sms')
def send_rnf_t0_sms(persona, loan_ids):
    today = timezone.localtime(timezone.now()).date()
    query = Payment.objects.not_paid_active()
    payments = (
        query.filter(loan_id__in=loan_ids).distinct('loan_id').order_by('loan_id', 'due_date')
    )
    for payment in payments:
        if payment.due_date <= today + timedelta(days=2):
            plc = payment.loan.application.product_line.product_line_code
            if plc in ProductLineCodes.stl():
                template_name = '201903_exp/' + persona + '_t0_stl'
                context = context = {
                    'name': payment.loan.application.first_name_with_title,
                    'due_amount': display_rupiah(payment.due_amount),
                    'url': 'https://bit.ly/julocarabayar',
                }
                message = render_to_string(template_name + '.txt', context)
            else:
                template_name = '201903_exp/' + persona + '_t0_mtl'
                cashback_amount = 0.01 * (
                    old_div(payment.loan.loan_amount, payment.loan.loan_duration)
                )
                context = {
                    'name': payment.loan.application.first_name_with_title,
                    'payment_number': payment.payment_number,
                    'due_amount': display_rupiah(payment.due_amount),
                    'payment_cashback_amount': display_rupiah(int(cashback_amount)),
                    'url': 'https://bit.ly/julocarabayar',
                }
                message = render_to_string(template_name + '.txt', context)

            client = get_julo_sms_client()
            phone_number = format_e164_indo_phone_number(payment.loan.application.mobile_phone_1)

            try:
                text_message, response = client.send_sms(phone_number, message)
                response = response['messages'][0]
                if response['status'] == '0':
                    sms = create_sms_history(
                        response=response,
                        customer=payment.loan.application.customer,
                        application=payment.loan.application,
                        payment=payment,
                        template_code=template_name,
                        message_content=text_message,
                        to_mobile_phone=format_e164_indo_phone_number(response['to']),
                        phone_number_type='mobile_phone_1',
                    )
            except Exception as e:
                pass


@task(name='run_rudolf_friska_experiment')
def run_rudolf_friska_experiment():
    today = timezone.localtime(timezone.now()).date()

    if today <= date(2019, 4, 10):
        Row = namedtuple('Row', ('application_id', 'loan_id', 'due_date', 'blast_date'))

        def parsedate(string):
            return datetime.strptime(string, '%Y-%m-%d').date()

        with open('../../email_blast/190319 Friska Population.csv', 'r') as f:
            data = csv.reader(f, delimiter=';')
            next(data)  # Skip header
            friska_population = [Row(*row) for row in data]
            friska_t2_loan_ids = [
                int(row.loan_id)
                for row in friska_population
                if (parsedate(row.blast_date) == today)
            ]
            friska_t0_loan_ids = [
                int(row.loan_id) for row in friska_population if (parsedate(row.due_date) == today)
            ]
            send_rnf_t2_sms.delay('friska', friska_t2_loan_ids)
            send_rnf_t0_sms.delay('friska', friska_t0_loan_ids)

        with open('../../email_blast/190319 Rudolf Population.csv', 'r') as f:
            data = csv.reader(f, delimiter=';')
            next(data)  # Skip header
            rudolf_population = [Row(*row) for row in data]
            rudolf_t2_loan_ids = [
                int(row.loan_id)
                for row in rudolf_population
                if (parsedate(row.blast_date) == today)
            ]
            rudolf_t0_loan_ids = [
                int(row.loan_id) for row in rudolf_population if (parsedate(row.due_date) == today)
            ]
            send_rnf_t2_sms.delay('rudolf', rudolf_t2_loan_ids)
            send_rnf_t0_sms.delay('rudolf', rudolf_t0_loan_ids)


@task(name='run_cashback_reminder_experiment')
def run_cashback_reminder_experiment():
    start_date = date(2019, 3, 20)
    end_date = date(2019, 4, 3)
    today = timezone.localtime(timezone.now()).date()
    is_executed = start_date <= today <= end_date
    if not is_executed:
        return

    with open('../../email_blast/190319_cashback_reminder_test_group.csv', 'r') as testf:
        test_rows = csv.DictReader(testf, delimiter=';')
        rows = [r for r in test_rows]

    sms_client = get_julo_sms_client()
    for row in rows:
        blast_date = parse(row['blast_date']).date()
        # skip if blast_date not today
        if blast_date != today:
            continue
        loan = Loan.objects.get(pk=row['loan_id'])
        due_date = parse(row['due_date']).date()
        oldest_unpaid_payment = loan.payment_set.not_paid_active().filter(due_date=due_date).first()
        # skip is there's no payment mathc
        if not oldest_unpaid_payment:
            continue

        application = loan.application
        phone_number = application.mobile_phone_1
        cashback_due_date = oldest_unpaid_payment.due_date - relativedelta(days=4)
        cashback_amount = 0.03 * (old_div(loan.loan_amount, loan.loan_duration))
        template = "exp_sms_cashback_reminder"
        context = {
            "name": application.first_name_with_title,
            "cashback_due_date": cashback_due_date.strftime('%d/%m'),
            "cashback_amount": display_rupiah(cashback_amount),
            "url": "https://bit.ly/julocarabayar",
        }
        try:
            message, response = sms_client.blast_custom(phone_number, template, context)
            if response['status'] == '0':
                sms = create_sms_history(
                    response=response,
                    customer=loan.application.customer,
                    application=application,
                    payment=oldest_unpaid_payment,
                    template_code=template,
                    message_content=message,
                    to_mobile_phone=format_e164_indo_phone_number(response['to']),
                    phone_number_type='mobile_phone_1',
                )
            else:
                logger.warning(
                    {
                        'action': 'send sms cashback reminder',
                        'status': response['status'],
                        'payment_id': oldest_unpaid_payment.id,
                    }
                )

        except Exception as e:
            logger.warning(
                {
                    'status': 'failed send sms cashback reminder',
                    'payment_id': oldest_unpaid_payment.id,
                    'error': e.__str__(),
                }
            )


################################
# END OF MARCH 2019 EXPERIMENT #
################################


@task(queue='collection_normal')
def run_ptp_update():
    """
    scheduled to update ptp table for not paid status in reference to Payments table
    also used to update flag is_broken_ptp_plus_1
    """
    yesterday = timezone.localtime(timezone.now()).date() - timedelta(days=1)
    payments = Payment.objects.filter(ptp_date=yesterday, paid_amount=0)
    for payment in payments:
        ptp_update(payment.id, payment.ptp_date)
        # flag is_broken_ptp_plus_1
        update_flag_is_broken_ptp_plus_1(
            payment, is_account_payment=False, turn_off_broken_ptp_plus_1=False
        )


@task(name='send_email_april_lottery')
def send_email_april_lottery(population):
    email_client = get_julo_email_client()
    for person in population:
        application = Application.objects.get(pk=person['application_id'])
        template_name = '201904_exp/20190417_April Email Promo T-7-10 Gold'
        deadline = person['deadline'] - timedelta(days=5)
        context = {
            'fullname': application.fullname,
            'deadline': date.strftime(deadline, '%d %B %Y'),
        }
        message = render_to_string(template_name + '.html', context)
        try:
            subject = 'Mau Logam Mulia 5gr Gratis? Bayar Cicilan Anda Sekarang'
            status, body, headers = email_client.send_email(
                subject=subject, content=message, email_to=application.email
            )
            message_id = headers['X-Message-Id']
            email = EmailHistory.objects.create(
                application=application,
                customer=application.customer,
                sg_message_id=message_id,
                to_email=application.email,
                subject=subject,
                message_content=message,
                template_code=template_name,
            )
        except Exception as e:
            pass


@task(name='run_april_lottery_experiment')
def run_april_lottery_experiment():
    today = timezone.localtime(timezone.now()).date()

    if today <= date(2019, 5, 1):
        today_plus7 = today + relativedelta(days=7)
        today_plus10 = today + relativedelta(days=10)
        payment_test = (
            Payment.objects.select_related('loan')
            .filter(loan__loan_status_id=LoanStatusCodes.CURRENT)
            .filter(Q(due_date=today_plus10))
            .filter(Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME))
            .extra(
                where=[
                    "right(payment.loan_id::text, 2) in "
                    "('54','64','74','84','94','55','65','75','85','95',"
                    "'56','66','76','86','96','57','67','77','87','97','58',"
                    "'68','78','88','98','59','69','79','89','99')"
                ]
            )
            .order_by('loan')
        )
        payment_control = (
            Payment.objects.select_related('loan')
            .filter(loan__loan_status_id=LoanStatusCodes.CURRENT)
            .filter(Q(due_date=today_plus7))
            .filter(Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME))
            .extra(
                where=[
                    "right(payment.loan_id::text, 2) in "
                    "('00','10','20','30','40','50','60','70','80','90',"
                    "'01','11','21','31','41','51','61','71','81','91',"
                    "'02','12','22','32','42','52','62','72','82','92',"
                    "'03','13','23','33','43','53','63','73','83','93',"
                    "'04','14','24','34','44',"
                    "'05','15','25','35','45',"
                    "'06','16','26','36','46',"
                    "'07','17','27','37','47',"
                    "'08','18','28','38','48',"
                    "'09','19','29','39','49')"
                ]
            )
            .order_by('loan')
        )
        email_population_test = []
        email_population_control = []
        for payments in payment_test:
            email_population_test.append(
                {"application_id": payments.loan.application_id, "deadline": payments.due_date}
            )
        for payments in payment_control:
            email_population_control.append(
                {"application_id": payments.loan.application_id, "deadline": payments.due_date}
            )
        send_email_april_lottery.delay(email_population_test)
        send_email_april_lottery.delay(email_population_control)


@task(name='send_rudolf_firska_sms')
def send_rudolf_firska_sms(payments, group):
    today = timezone.localtime(timezone.now()).date()
    for payment in payments:
        if payment.loan.application.gender == 'Pria':
            persona = 'friska'
        else:
            persona = 'rudolf'
        if payment.due_date <= today:
            plc = payment.loan.application.product_line.product_line_code
            if plc in ProductLineCodes.stl():
                template_name = '201904_exp/' + persona + '_' + group + '_t0_stl'
                context = {
                    'name': payment.loan.application.first_name_with_title,
                    'due_amount': display_rupiah(payment.due_amount),
                    'url': 'https://bit.ly/julocarabayar ',
                }
                message = render_to_string(template_name + '.txt', context)
            else:
                template_name = '201904_exp/' + persona + '_' + group + '_t0_mtl'
                cashback_amount = 0.01 * (
                    old_div(payment.loan.loan_amount, payment.loan.loan_duration)
                )
                context = {
                    'name': payment.loan.application.first_name_with_title,
                    'payment_number': payment.payment_number,
                    'due_amount': display_rupiah(payment.due_amount),
                    'payment_cashback_amount': display_rupiah(int(cashback_amount)),
                    'url': 'https://bit.ly/julocarabayar ',
                }
                message = render_to_string(template_name + '.txt', context)
        else:
            plc = payment.loan.application.product_line.product_line_code
            if plc in ProductLineCodes.stl():
                template_name = '201904_exp/' + persona + '_' + group + '_t2_stl'
                context = {
                    'name': payment.loan.application.first_name_with_title,
                    'due_amount': display_rupiah(payment.due_amount),
                    'due_date': datetime.strftime(payment.due_date, '%d/%m'),
                    'url': 'https://bit.ly/julocarabayar ',
                }
                message = render_to_string(template_name + '.txt', context)
            else:
                template_name = '201904_exp/' + persona + '_' + group + '_t2_mtl'
                cashback_amount = 0.01 * (
                    old_div(payment.loan.loan_amount, payment.loan.loan_duration)
                )
                context = {
                    'name': payment.loan.application.first_name_with_title,
                    'cashback_multiplier': payment.cashback_multiplier,
                    'payment_cashback_amount': display_rupiah(int(cashback_amount)),
                    'bank_name': payment.loan.julo_bank_name,
                    'virtual_account_number': payment.loan.julo_bank_account_number,
                    'due_amount': display_rupiah(payment.due_amount),
                    'payment_number': payment.payment_number,
                    'due_date': datetime.strftime(payment.due_date, '%d/%m'),
                    'due_date_minus_2': datetime.strftime(
                        payment.due_date - timedelta(days=2), '%d/%m'
                    ),
                    'url': 'https://bit.ly/julocarabayar ',
                }
                message = render_to_string(template_name + '.txt', context)
        client = get_julo_sms_client()
        phone_number = format_e164_indo_phone_number(payment.loan.application.mobile_phone_1)
        try:
            text_message, response = client.send_sms(phone_number, message)
            response = response['messages'][0]
            if response['status'] == '0':
                sms = create_sms_history(
                    response=response,
                    customer=payment.loan.application.customer,
                    application=payment.loan.application,
                    payment=payment,
                    template_code=template_name,
                    message_content=text_message,
                    to_mobile_phone=format_e164_indo_phone_number(response['to']),
                    phone_number_type='mobile_phone_1',
                )
        except Exception as e:
            pass


@task(name='run_april_rudolf_friska_experiment')
def run_april_rudolf_friska_experiment():
    today = timezone.localtime(timezone.now()).date()
    if today <= date(2019, 5, 8):
        today_plus2 = today + relativedelta(days=2)
        payment_friska_test = (
            Payment.objects.select_related('loan')
            .not_paid_active()
            .filter(loan__loan_status_id=LoanStatusCodes.CURRENT)
            .filter(Q(due_date=today_plus2) | Q(due_date=today))
            .filter(Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME))
            .extra(
                where=[
                    "right(payment.loan_id::text, 2) in "
                    "('04','05','06','07','08','09',"
                    "'14','15','16','17','18','19',"
                    "'24','25','26','27','28','29',"
                    "'34','35','36','37','38','39',"
                    "'44','45','46','47','48','49')"
                ]
            )
            .distinct('loan')
            .order_by('loan', 'due_date')
        )
        send_rudolf_firska_sms.delay(payment_friska_test, 'test')
        payment_friska_control = (
            Payment.objects.select_related('loan')
            .not_paid_active()
            .filter(loan__loan_status_id=LoanStatusCodes.CURRENT)
            .filter(Q(due_date=today_plus2) | Q(due_date=today))
            .filter(Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME))
            .extra(
                where=[
                    "right(payment.loan_id::text, 2) in "
                    "('00','10','20','30','40','50','60','70','80','90',"
                    "'01','11','21','31','41','51','61','71','81','91',"
                    "'02','12','22','32','42','52','62','72','82','92',"
                    "'03','13','23','33','43','53','63','73','83','93',"
                    "'54','64','74','84','94','55','65','75','85','95',"
                    "'56','66','76','86','96','57','67','77','87','97','58',"
                    "'68','78','88','98','59','69','79','89','99')"
                ]
            )
            .distinct('loan')
            .order_by('loan', 'due_date')
        )
        send_rudolf_firska_sms.delay(payment_friska_control, 'control')


def email_warning_letter(payment, url, last_date, template, warning_type):
    customer = payment.loan.customer
    loan = payment.loan
    url = url + "#email"
    application = loan.application
    payment_method = PaymentMethod.objects.filter(loan=loan, payment_method_code=319322).first()
    due_payment = (
        Payment.objects.by_loan(loan)
        .filter(payment_status__lte=327, payment_status__gte=320, due_amount__gte=1)
        .order_by('due_date')
    )
    bank_code = PaymentMethodLookup.objects.filter(name=loan.julo_bank_name).first().code
    warning_letter_history = {}

    if due_payment:
        not_payed_start = due_payment.first().due_date
        not_payed_end = due_payment.last().due_date
        principal_sum = due_payment.aggregate(Sum('installment_principal'))[
            'installment_principal__sum'
        ]
        late_fee_applied_sum = due_payment.aggregate(Sum('late_fee_amount'))['late_fee_amount__sum']
        installment_interest = due_payment.aggregate(Sum('installment_interest'))[
            'installment_interest__sum'
        ]
        paid_sum = due_payment.aggregate(Sum('paid_amount'))['paid_amount__sum']
        change_due_date_interest = due_payment.aggregate(Sum('change_due_date_interest'))[
            'change_due_date_interest__sum'
        ]
        # due_sum = principal_sum + late_fee_applied_sum + installment_interest
        while paid_sum > 0:
            if principal_sum > 0:
                if paid_sum > principal_sum:
                    paid_sum -= principal_sum
                    principal_sum = 0
                else:
                    principal_sum -= paid_sum
                    paid_sum = 0
            elif installment_interest > 0:
                if paid_sum > installment_interest:
                    paid_sum -= installment_interest
                    installment_interest = 0
                else:
                    installment_interest -= paid_sum
                    paid_sum = 0
            elif late_fee_applied_sum > 0:
                if paid_sum > late_fee_applied_sum:
                    paid_sum -= late_fee_applied_sum
                    late_fee_applied_sum = 0
                else:
                    late_fee_applied_sum -= paid_sum
                    paid_sum = 0
            elif change_due_date_interest > 0:
                if paid_sum > change_due_date_interest:
                    paid_sum -= change_due_date_interest
                    change_due_date_interest = 0
                else:
                    change_due_date_interest -= paid_sum
                    paid_sum = 0
        total_sum = (
            principal_sum + late_fee_applied_sum + installment_interest + change_due_date_interest
        )
    else:
        not_payed_start = ""
        not_payed_end = ""
        principal_sum = ""
        late_fee_applied_sum = ""
        installment_interest = ""
        total_sum = ""
    if last_date:
        last_date = date.strftime(last_date, '%d %B %Y')
    sph_date = loan.sphp_accepted_ts
    if sph_date is None:
        sph_date = ""
    else:
        sph_date = loan.sphp_accepted_ts.date()
    context = {
        "url": url,
        "name": application.fullname_with_title,
        "loan_amount": loan.loan_amount,
        "loan_duration": loan.loan_duration,
        "application_xid": application.application_xid,
        "late_fee_amount": loan.late_fee_amount,
        "accepted_date": sph_date,
        "fullname": application.fullname_with_title,
        "name_only": application.fullname,
        "phone": customer.phone,
        "now": timezone.now().date(),
        "sphp_accepted_ts": sph_date,
        "not_payed_start": date.strftime(not_payed_start, '%d %B %Y'),
        "not_payed_end": date.strftime(not_payed_end, '%d %B %Y'),
        "due_amount_sum": principal_sum,
        "installment_interest": installment_interest,
        "late_fee_applied_sum": late_fee_applied_sum,
        "total_sum": format_number(total_sum, locale='id_ID'),
        "julo_bank_account_number": loan.julo_bank_account_number,
        "julo_bank_name": loan.julo_bank_name,
        "header_image": settings.EMAIL_STATIC_FILE_PATH + "header.png",
        "footer_image": settings.EMAIL_STATIC_FILE_PATH + "footer.png",
        "sign_image": settings.EMAIL_STATIC_FILE_PATH + "sign.png",
        'last_date': last_date,
        'last_date_plus_7': last_date,
        'bank_code': bank_code,
    }
    if payment_method:
        context['payment_method_name'] = payment_method.payment_method_name
        context['virtual_account'] = payment_method.virtual_account
    else:
        context['payment_method_name'] = ""
        context['virtual_account'] = ""
    warning_letter_history['warning_number'] = warning_type
    payment.create_warning_letter_history(warning_letter_history)
    text_message = render_to_string(template['email'], context=context)
    subject = template['subject'] + " - " + customer.email
    email_client = get_julo_email_client()
    email_from = "legal.dept@julo.co.id"
    name_from = "JULO"
    reply_to = "legal.dept@julo.co.id"
    status, body, headers = email_client.send_email(
        subject=subject,
        content=text_message,
        email_to=customer.email,
        email_from=email_from,
        email_cc=None,
        name_from=name_from,
        reply_to=reply_to,
    )
    email = EmailHistory.objects.create(
        application=application,
        customer=application.customer,
        sg_message_id=headers['X-Message-Id'],
        to_email=customer.email,
        subject=subject,
        message_content=text_message,
        template_code=template['email'],
        payment=payment,
    )


@task(name='run_send_warning_letter1')
def run_send_warning_letter1():
    today = timezone.localtime(timezone.now()).date()
    today_minus15 = today - relativedelta(days=15)
    payments = (
        Payment.objects.select_related('loan')
        .not_paid_active()
        .filter(loan__loan_status_id__lte=237, loan__loan_status_id__gte=230)
        .filter(Q(paid_amount=0))
        .filter(Q(due_date=today_minus15))
        .filter(Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME))
        .distinct('loan')
        .order_by('loan', 'due_date')
    )
    for payment in payments:
        if payment.loan.customer is None:
            logger.error("Customer not Found " + payment.loan.application_id)
            continue
        else:
            customer_id = payment.loan.customer.id
            WARNING_TYPE = "1"
            last_date = ""
            template = TEMPLATES[WARNING_TYPE]
            url = WarningUrl.objects.filter(
                url_type="email", customer=payment.loan.customer, warning_method=WARNING_TYPE
            ).first()
            encrypttext = encrypt()
            encoded_customer_id = encrypttext.encode_string(str(customer_id))
            url_string = template['url'].format(customer_id=encoded_customer_id)
            log_url(payment.loan.customer, url_string, "email")
            url_string = (
                url_string
                + "?date="
                + str(timezone.now().date())
                + "&ldate="
                + str(last_date)
                + "&type="
                + WARNING_TYPE
            )
            shorten_url_string = url_string
            customer = payment.loan.customer
            try:
                email_warning_letter(payment, shorten_url_string, last_date, template, 1)
            except Exception as e:
                logger.error(
                    {
                        'action': 'run_send_warning_letter1',
                        'loan id': payment.loan.id,
                        'errors': 'failed send email to {} - {}'.format(customer, e),
                    }
                )
                continue


@task(name='run_send_warning_letter2')
def run_send_warning_letter2():
    today = timezone.localtime(timezone.now()).date()
    today_minus15 = today - relativedelta(days=15)
    today_minus30 = today - relativedelta(days=30)
    payments = (
        Payment.objects.select_related('loan')
        .not_paid_active()
        .filter(loan__loan_status_id__lte=237, loan__loan_status_id__gte=230)
        .filter(Q(paid_amount=0))
        .filter(Q(due_date=today_minus30))
        .filter(Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME))
        .distinct('loan')
        .order_by('loan', 'due_date')
    )
    for payment in payments:
        if payment.loan.customer is None:
            logger.error("Customer not Found " + payment.loan.application_id)
            continue
        else:
            customer_id = payment.loan.customer.id
            WARNING_TYPE = "2"
            template = TEMPLATES[WARNING_TYPE]
            template_wl1 = TEMPLATES['1']
            email_history = (
                EmailHistory.objects.filter(application=payment.loan.application_id)
                .filter(customer=payment.loan.customer.id)
                .filter(payment=payment.id)
                .filter(template_code=template_wl1['email'])
                .last()
            )
            if email_history is None:
                continue
            else:
                last_date = today_minus15
                url = WarningUrl.objects.filter(
                    url_type="email", customer=payment.loan.customer, warning_method=WARNING_TYPE
                ).first()

                encrypttext = encrypt()
                encoded_customer_id = encrypttext.encode_string(str(customer_id))
                url_string = template['url'].format(customer_id=encoded_customer_id)
                log_url(payment.loan.customer, url_string, "email")
                url_string = (
                    url_string
                    + "?date="
                    + str(timezone.now().date())
                    + "&ldate="
                    + str(last_date)
                    + "&type="
                    + WARNING_TYPE
                )
                shorten_url_string = url_string
                customer = payment.loan.customer
                try:
                    email_warning_letter(payment, shorten_url_string, last_date, template, 2)
                except Exception as e:
                    logger.error(
                        {
                            'action': 'run_send_warning_letter2',
                            'loan id': payment.loan.id,
                            'errors': 'failed send email to {} - {}'.format(customer, e),
                        }
                    )
                    continue


@task(name='run_send_warning_letter3')
def run_send_warning_letter3():
    today = timezone.localtime(timezone.now()).date()
    today_minus30 = today - relativedelta(days=30)
    today_minus45 = today - relativedelta(days=45)
    payments = (
        Payment.objects.select_related('loan')
        .not_paid_active()
        .filter(loan__loan_status_id__lte=237, loan__loan_status_id__gte=230)
        .filter(Q(paid_amount=0))
        .filter(Q(due_date=today_minus45))
        .filter(Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME))
        .distinct('loan')
        .order_by('loan', 'due_date')
    )
    for payment in payments:
        if payment.loan.customer is None:
            logger.error("Customer not Found " + payment.loan.application_id)
            continue
        else:
            customer_id = payment.loan.customer.id
            WARNING_TYPE = "3"
            template = TEMPLATES[WARNING_TYPE]
            template_wl2 = TEMPLATES['2']
            email_history = (
                EmailHistory.objects.filter(application=payment.loan.application_id)
                .filter(payment=payment.id)
                .filter(customer=payment.loan.customer.id)
                .filter(template_code=template_wl2['email'])
                .last()
            )
            if email_history is None:
                continue
            else:
                last_date = today_minus30
                url = WarningUrl.objects.filter(
                    url_type="email", customer=payment.loan.customer, warning_method=WARNING_TYPE
                ).first()

                encrypttext = encrypt()
                encoded_customer_id = encrypttext.encode_string(str(customer_id))
                url_string = template['url'].format(customer_id=encoded_customer_id)
                log_url(payment.loan.customer, url_string, "email")
                url_string = (
                    url_string
                    + "?date="
                    + str(timezone.now().date())
                    + "&ldate="
                    + str(last_date)
                    + "&type="
                    + WARNING_TYPE
                )
                shorten_url_string = url_string
                customer = payment.loan.customer
                try:
                    email_warning_letter(payment, shorten_url_string, last_date, template, 3)
                except Exception as e:
                    logger.error(
                        {
                            'action': 'run_send_warning_letter3',
                            'loan id': payment.loan.id,
                            'errors': 'failed send email to {} - {}'.format(customer, e),
                        }
                    )
                    continue


def email_warning_letters(loan, due_payment, warning_type):
    loan = loan.loan
    payment_method = PaymentMethod.objects.filter(
        loan_id=loan.id, payment_method_code=PaymentMethodCodes.INDOMARET
    )
    due_payment_last = due_payment.last()
    if payment_method:
        virtual_account = payment_method.first().virtual_account
    else:
        virtual_account = None
    application = loan.application
    customer = loan.customer
    late_fee_total = due_payment.aggregate(Sum('late_fee_amount'))['late_fee_amount__sum']
    due_amount_total = due_payment.aggregate(Sum('due_amount'))['due_amount__sum']
    net_amount_to_pay = late_fee_total + due_amount_total
    sph_date = loan.sphp_accepted_ts
    if sph_date is None:
        sph_date = ""
    else:
        sph_date = loan.sphp_accepted_ts.date()
        sph_date = format_date(sph_date, 'dd MMMM yyyy', locale='id_ID')
    if due_payment:
        not_payed_start = format_date(due_payment.first().due_date, 'dd MMMM yyyy', locale='id_ID')
        not_payed_end = format_date(due_payment_last.due_date, 'dd MMMM yyyy', locale='id_ID')
    else:
        not_payed_start = ""
        not_payed_end = ""

    customer_id = customer.id
    encrypttext = encrypt()
    last_date = ''
    encoded_customer_id = encrypttext.encode_string(str(customer_id))
    sign_image = 'sign.png'
    if warning_type == 1:
        subject = 'Surat Peringatan Pertama'
        url_string = settings.AGREEMENT_WEBSITE.format(customer_id=encoded_customer_id)
    elif warning_type == 2:
        subject = 'Surat Peringatan Kedua'
        url_string = settings.AGREEMENT_WEBSITE_2.format(customer_id=encoded_customer_id)
    elif warning_type == 3:
        subject = 'Surat Peringatan Ketiga'
        url_string = settings.AGREEMENT_WEBSITE_3.format(customer_id=encoded_customer_id)
    else:
        subject = 'Surat Peringatan Ketiga'
        url_string = settings.AGREEMENT_WEBSITE_3.format(customer_id=encoded_customer_id)
        sign_image = 'sign_jtp.png'

    url = (
        url_string
        + "?date="
        + str(timezone.now().date())
        + "&ldate="
        + str(last_date)
        + "&type="
        + str(warning_type)
        + "#email"
    )
    date_today = format_date(timezone.now().date(), 'dd MMMM yyyy', locale='id_ID')
    email_client = get_julo_email_client()
    attachment_dict = None
    content_type = None
    link_url = None
    name = application.fullname_with_title
    capitalized_each_name = name.title()
    fullname = application.fullname_with_title
    capitalized_each_fullname = fullname.title()
    name_only = application.fullname
    capitalized_each_name_only = name_only.title()
    today = timezone.localtime(timezone.now()).date()
    if loan.application.product_line.product_line_code in ProductLineCodes.mtl():
        next_not_due_payment = Payment.objects.filter(
            loan_id=loan.id,
            due_date__gt=today,
            payment_status_id=PaymentStatusCodes.PAYMENT_NOT_DUE,
        ).order_by('payment_number')
        try:
            if next_not_due_payment:
                (
                    link_url,
                    attachment_dict,
                    content_type,
                ) = get_warning_letter_google_calendar_attachment(next_not_due_payment, application)
        except Exception as e:
            pass
    context = {
        "name": capitalized_each_name,
        "loan_amount": loan.loan_amount,
        "loan_duration": loan.loan_duration,
        "application_xid": application.application_xid,
        "late_fee_total": late_fee_total,
        "due_amount_total": due_amount_total,
        "net_amount_to_pay": net_amount_to_pay,
        "accepted_date": sph_date,
        "fullname": capitalized_each_fullname,
        "name_only": capitalized_each_name_only,
        "now": date_today,
        "sphp_accepted_ts": sph_date,
        "julo_bank_account_number": loan.julo_bank_account_number,
        "julo_bank_name": loan.julo_bank_name,
        "header_image": settings.EMAIL_STATIC_FILE_PATH + "wl_header.png",
        "footer_image": settings.EMAIL_STATIC_FILE_PATH + "footer.png",
        "sign_image": settings.EMAIL_STATIC_FILE_PATH + sign_image,
        "wa_image": settings.EMAIL_STATIC_FILE_PATH + "wl_whatsapp.png",
        "email_image": settings.EMAIL_STATIC_FILE_PATH + "wl_email.png",
        "lihat_image": settings.EMAIL_STATIC_FILE_PATH + "wl_lihat.png",
        'due_payment': due_payment,
        "not_payed_start": not_payed_start,
        "not_payed_end": not_payed_end,
        "virtual_account": virtual_account,
        "url": url,
        "phone_image": settings.EMAIL_STATIC_FILE_PATH + "wl_phone.png",
        "link_url": link_url,
        "play_store": settings.EMAIL_STATIC_FILE_PATH + "google-play-badge.png",
    }

    url_web_page = create_mtl_url(application, context, warning_type)
    update_moengage_for_wl_url_data.delay(customer, url_web_page, True)
    warning_letter_contacts_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WARNING_LETTER_CONTACTS, is_active=True
    ).last()
    if warning_letter_contacts_feature:
        parameter = warning_letter_contacts_feature.parameters
        context["collection_wa_number"] = parameter['collection_wa_number']
        context["collection_email_address"] = parameter['collection_email_address']
        context["collection_phone_number_1"] = parameter['collection_phone_number_1']
        context["collection_phone_number_2"] = parameter['collection_phone_number_2']

    if warning_type != 4:
        template_name = 'warning_letter' + str(warning_type) + '.html'
        text_message = render_to_string(template_name, context=context)
        subject = subject + " - " + customer.email
        email_from = EmailDeliveryAddress.LEGAL_JTF
        name_from = "JULO"
        reply_to = EmailDeliveryAddress.LEGAL_JTF
        email_cc = None
    else:
        template_name = 'warning_letter3_b5.html'
        text_message = render_to_string(template_name, context=context)
        subject = subject + " - " + customer.email
        email_from = EmailDeliveryAddress.LEGAL_JTF
        name_from = "JULO"
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        email_cc = EmailDeliveryAddress.LEGAL_JTF

    status, body, headers = email_client.send_email(
        subject=subject,
        content=text_message,
        email_to=customer.email,
        email_from=email_from,
        email_cc=email_cc,
        name_from=name_from,
        reply_to=reply_to,
        attachment_dict=attachment_dict,
        content_type=content_type,
    )
    email = EmailHistory.objects.create(
        application=application,
        customer=application.customer,
        sg_message_id=headers['X-Message-Id'],
        to_email=customer.email,
        subject=subject,
        cc_email=email_cc,
        message_content=text_message,
        template_code=template_name,
        payment=due_payment_last,
    )
    warning_letter_history = WarningLetterHistory.objects.create(
        warning_number=warning_type,
        customer=customer,
        loan=due_payment_last.loan,
        due_date=due_payment_last.due_date,
        payment=due_payment_last,
        loan_status_code=due_payment_last.loan.status,
        payment_status_code=due_payment_last.status,
        total_due_amount=due_amount_total,
        event_type='WL' + str(warning_type),
    )
    vendor_data_history = VendorDataHistory.objects.create(
        customer=customer,
        loan=due_payment_last.loan,
        payment=due_payment_last,
        loan_status_code=due_payment_last.loan.status,
        payment_status_code=due_payment_last.status,
        vendor=VendorConst.SENDGRID,
        template_code=template_name,
        reminder_type=ReminderTypeConst.EMAIL_TYPE_REMINDER,
    )


@task(queue='collection_low')
def run_send_warning_letters():
    today = timezone.localtime(timezone.now()).date()
    today_minus11 = today - relativedelta(days=11)
    today_minus25 = today - relativedelta(days=25)
    today_minus32 = today - relativedelta(days=32)
    today_minus35 = today - relativedelta(days=35)
    today_minus55 = today - relativedelta(days=55)
    today_minus62 = today - relativedelta(days=62)
    today_minus65 = today - relativedelta(days=65)
    today_minus92 = today - relativedelta(days=92)
    today_minus85 = today - relativedelta(days=85)
    today_minus115 = today - relativedelta(days=115)
    today_minus145 = today - relativedelta(days=145)
    today_minus175 = today - relativedelta(days=175)
    payments_to_exclude = (
        ProductLineCodes.PEDEMTL1,
        ProductLineCodes.PEDEMTL2,
        ProductLineCodes.PEDESTL1,
        ProductLineCodes.PEDESTL2,
        ProductLineCodes.LAKU1,
        ProductLineCodes.LAKU2,
        ProductLineCodes.ICARE1,
        ProductLineCodes.ICARE2,
        ProductLineCodes.AXIATA1,
        ProductLineCodes.AXIATA2,
        ProductLineCodes.J1,
    )
    query_set = (
        Payment.objects.select_related('loan')
        .exclude(loan__application__product_line__product_line_code__in=payments_to_exclude)
        .filter(
            loan__loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
            loan__loan_status_id__gte=LoanStatusCodes.LOAN_1DPD,
        )
        .filter(
            payment_status_id__lte=PaymentStatusCodes.PAYMENT_180DPD,
            payment_status_id__gte=PaymentStatusCodes.PAYMENT_1DPD,
            is_restructured=False,
        )
        .distinct('loan')
        .order_by('loan', 'due_date')
    )
    excluded_loan_id_from_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan_id__in=query_set.values_list('loan_id', flat=True),
        status=CovidRefinancingConst.STATUSES.approved,
        product_type__in=CovidRefinancingConst.reactive_products(),
    ).values_list('loan_id', flat=True)

    dpdlevel_payments = list(
        query_set.exclude(loan_id__in=excluded_loan_id_from_refinancing_request).values_list(
            'id', 'payment_number', 'loan_id'
        )
    )
    for dpdlevel_payment in dpdlevel_payments:
        payments = (
            Payment.objects.select_related('loan')
            .exclude(loan__application__product_line__product_line_code__in=payments_to_exclude)
            .filter(
                loan__loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
                loan__loan_status_id__gte=LoanStatusCodes.LOAN_1DPD,
            )
            .filter(
                Q(due_date=today_minus25)
                | Q(due_date=today_minus35)
                | Q(due_date=today_minus11)
                | Q(due_date=today_minus55)
                | Q(due_date=today_minus65)
                | Q(due_date=today_minus32)
                | Q(due_date=today_minus85)
                | Q(due_date=today_minus115)
                | Q(due_date=today_minus62)
                | Q(due_date=today_minus145)
                | Q(due_date=today_minus175)
                | Q(due_date=today_minus92)
            )
            .filter(payment_number=dpdlevel_payment[1])
            .filter(loan__id=dpdlevel_payment[2])
            .filter(id=dpdlevel_payment[0])
            .filter(account_payment__id__isnull=True)
        )
        wl_config = WlLevelConfig.objects.all()
        configMap = {}
        index = 1
        for wl_configs in wl_config:
            configMap[index] = wl_configs.wl_level
            index = index + 1
        due_date_list = {}
        due_date_list[today_minus11] = 11
        due_date_list[today_minus32] = 32
        due_date_list[today_minus55] = 55
        due_date_list[today_minus62] = 62
        due_date_list[today_minus92] = 92
        for payment in payments:
            loan_id = payment.loan.id
            due_date = payment.due_date
            if payment.loan.customer is None:
                logger.error("Customer not Found " + payment.loan.application_id)
                continue
            customer = payment.loan.customer
            due_payments = (
                Payment.objects.filter(
                    payment_status_id__lte=PaymentStatusCodes.PAYMENT_180DPD,
                    payment_status_id__gte=PaymentStatusCodes.PAYMENT_1DPD,
                    is_restructured=False,
                )
                .filter(Q(ptp_date=None) | Q(ptp_date__lt=today))
                .filter(loan_id=loan_id)
                .order_by('payment_number')
            )
            late_payment_count = len(due_payments)

            if late_payment_count > 0:
                application = payment.loan.application
                product_line_code = application.product_line_id if application else None
                if due_date in due_date_list and product_line_code in ProductLineCodes.stl():
                    dpd = due_date_list[due_date]
                    if dpd == 11:
                        wl_level = 1
                    elif dpd == 32:
                        wl_level = 2
                    else:
                        wl_level = 3
                elif due_date in due_date_list and due_date_list[due_date] != 55:
                    continue
                else:
                    wl_level = configMap.get(late_payment_count)
                if wl_level == 3 and payment.due_late_days >= 91:
                    wl_level = 4
                try:
                    email_warning_letters(payment, due_payments, wl_level)
                except Exception as e:
                    logger.error({
                        'action': 'run_send_warning_letters',
                        'loan id': loan_id,
                        'errors': 'failed send email to {} - {}'.format(customer, e)
                    })
                    continue

    retry_loan_refinancing_expired = LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.STATUSES.expired,
        product_type__in=CovidRefinancingConst.reactive_products(),
        account_id__isnull=True
    ).extra(
        where=[
            "(loan_refinancing_request.cdate::date + expire_in_days+1 * interval '1' day)::date"
            " = %s"
        ],
        params=[today]
    ).distinct('loan').order_by('loan', '-id')
    dpd_to_send = list(range(40, 51)) + list(range(70, 81)) + list(range(90, 111)) + list(range(120, 141)) + list(range(150, 171))
    for expired_loan_refinancing_request in retry_loan_refinancing_expired:
        loan = expired_loan_refinancing_request.loan
        # check last loan refinancing request
        existing_last_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            loan=loan
        ).last()
        if expired_loan_refinancing_request.id != existing_last_loan_refinancing_request.id:
            continue

        payment = get_oldest_payment_due(loan)
        if payment.due_late_days not in dpd_to_send:
            continue

        wl_config = WlLevelConfig.objects.all()
        configMap = {}
        index = 1
        for wl_configs in wl_config:
            configMap[index] = wl_configs.wl_level
            index = index + 1

        customer = payment.loan.customer
        due_payments = Payment.objects.filter(
            payment_status_id__lte=PaymentStatusCodes.PAYMENT_180DPD,
            payment_status_id__gte=PaymentStatusCodes.PAYMENT_1DPD,
            is_restructured=False
        ).filter(Q(ptp_date=None) | Q(ptp_date__lt=today))\
            .filter(loan_id=loan) \
            .order_by('payment_number')
        expired_late_payment_count = len(due_payments)
        if expired_late_payment_count > 0:
            product_line_code = payment.loan.application.product_line.product_line_code
            if product_line_code in ProductLineCodes.stl():
                wl_level = 3
            else:
                wl_level = configMap[expired_late_payment_count]
            try:
                email_warning_letters(payment, due_payments, wl_level)
            except Exception as e:
                logger.error({
                    'action': 'run_retry_send_warning_letters',
                    'loan id': loan.id,
                    'errors': 'failed send email to {} - {}'.format(customer, e)
                })
                continue


########## END OF COLLECTION TASKS ########
@task(queue='loan_high')
def send_pn_loan_approved():
    skip_validation = False
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        product_line__in = [ProductLineCodes.MTL1, ProductLineCodes.STL1, \
            ProductLineCodes.MTL2, ProductLineCodes.STL2]
            )
    experiment = Experiment.objects.filter(code=ACBYPASS_141).last()

    if not experiment.is_active:
        return

    for application in applications:
        customer = application.customer
        if application.product_line_code in [ProductLineCodes.MTL2, ProductLineCodes.STL2]:
            skip_validation = check_good_customer_or_not(customer)

        status = application.applicationhistory_set.filter(
            status_old=ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            status_new=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )

        # checked status change from 120 to 141
        high_bypass = application.applicationhistory_set.filter(
            status_old=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            status_new=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )
        if high_bypass:
            status = True

        product_code = application.product_line.product_line_code
        if ((skip_validation) or (not status and \
                product_code in [ProductLineCodes.MTL1, ProductLineCodes.STL1]))and \
                (application.device is not None):
            julo_pn_client = get_julo_pn_client()
            fullname = application.fullname
            gcm_reg_id = application.device.gcm_reg_id
            application_id = application.id
            julo_pn_client.inform_submission_approved(fullname, gcm_reg_id, application_id)


@task(queue='application_low')
def send_pn_180_playstore_rating(*postalcode):

    today = timezone.localtime(timezone.now())
    days_list = [2, 4, 6, 8, 10, 12, 14]

    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        customer__is_review_submitted__isnull=True,
        loan__loan_status_id=LoanStatusCodes.CURRENT,
        address_kodepos__in=postalcode
    )

    julo_pn_client = get_julo_pn_client()

    notif = NotificationTemplate.objects.get(notification_code='rating_app')
    current_image = Image.objects.get(image_source=notif.id, image_type='notification_image_ops')
    image_url = current_image.notification_image_url
    message = notif.body
    title = notif.title

    for application in applications:
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            application_id=application.id
        )
        for app_history in app_histories:
            delta = today - app_history.cdate
            pass_days = delta.days

            if pass_days in days_list and application.device is not None:
                gcm_reg_id = application.device.gcm_reg_id
                application_id = application.id
                fullname = application.fullname
                julo_pn_client.send_pn_playstore_rating(fullname, gcm_reg_id, application_id, message, image_url, title)


@task(name='auto_pn_remainder_playstore_rating')
def auto_pn_remainder_playstore_rating():
    '''
    push notification sent to customer at 180 for play store rating
    '''
    today = timezone.now()
    prior_date_str = '2019-09-04'
    release_date = datetime.strptime(prior_date_str, "%Y-%m-%d").date()

    starting_date = '2019-08-21'
    start_date = datetime.strptime(starting_date, "%Y-%m-%d").date()

    julo_pn_client = get_julo_pn_client()

    days_list = [1,10,15,21]

    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        customer__is_review_submitted__isnull=True,
        applicationhistory__status_new=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        applicationhistory__cdate__date__gte=start_date)

    for application in applications:
        app_histories = ApplicationHistory.objects.filter(
            status_new=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            application_id=application.id,
        )

        for app_history in app_histories:
            # indication trigered pn is from application_history cdate
            delta = today - app_history.cdate
            pass_days = delta.days

            fullname = application.fullname
            if application.device is not None:
                gcm_reg_id = application.device.gcm_reg_id
                application_id = application.id

                if (app_history.cdate.date() < release_date and release_date+timedelta(days=1) == today.date()) or \
                    (pass_days in days_list):
                    julo_pn_client.remainder_for_playstore_rating(fullname, gcm_reg_id, application_id)

                if pass_days == days_list[-1]:
                    customer = application.customer
                    customer.is_review_submitted = False
                    customer.save()

@task(name="waive_pede_campaign")
def waive_pede_campaign(loan_id, campaign_start_date):
    event_type = 'waiver_for_late_fee_and_interest'
    waiver_campaign_promo(loan_id, event_type, campaign_start_date)

@task(name="run_waive_pede_campaign")
def run_waive_pede_campaign():
    today = timezone.localtime(timezone.now()).date()
    campaign_start_date = date(2019, 10, 17)
    campaign_last_date = date(2019, 11, 5)

    if today < campaign_start_date or today > campaign_last_date:
        return

    # pede_partner_obj = Partner.objects.get(name='pede')
    eligible_loans_ids = WaivePromo.objects.get_queryset()\
        .eligible_loans('pede_oct').values_list('loan', flat=True)

    if len(eligible_loans_ids) == 0:
        return None

    for loan_id in eligible_loans_ids:
        waive_pede_campaign.delay(loan_id, campaign_start_date)


@task(name="send_email_pede_campaign")
def send_email_pede_campaign(loan_id):
    campaign_start_date = date(2019, 10, 17)
    promo_payments = WaivePromo.objects.filter(loan_id=loan_id)
    total_principal_amount = promo_payments.aggregate(
        total_principal_amount=Sum('remaining_installment_principal'))\
                                           .get('total_principal_amount')

    total_late_fee_amount = promo_payments.aggregate(
        total_remaining_late_fee=Sum('remaining_late_fee'))\
                                           .get('total_remaining_late_fee')

    total_interest_amount = promo_payments.aggregate(
        total_remaining_installment_interest=Sum('remaining_installment_interest'))\
                                           .get('total_remaining_installment_interest')

    promo_payment_ids = promo_payments.values_list('payment', flat=True)
    total_paid_amount = PaymentEvent.objects.filter(payment__in=promo_payment_ids,
                                                    event_type='payment',
                                                    cdate__gte=campaign_start_date)\
                                            .aggregate(total_paid_amount=Sum('event_payment'))\
                                            .get('total_paid_amount')

    if not total_paid_amount:
        total_paid_amount = 0

    total_remaining_principal_amount = total_principal_amount - total_paid_amount
    total_due_amount = total_remaining_principal_amount + total_late_fee_amount + \
        total_interest_amount

    loan = Loan.objects.get(pk=loan_id)
    customer = loan.customer
    julo_email_client = get_julo_email_client()
    status, headers, subject, msg = julo_email_client.email_waive_pede_campaign(loan,
                                                                           total_remaining_principal_amount,
                                                                           total_late_fee_amount,
                                                                           total_interest_amount,
                                                                           total_due_amount)

    template_code = "email_pede_oct"

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=customer.email,
        subject=subject,
        message_content=msg,
        template_code=template_code,
    )

    logger.info({
        "action": "email_pede_oct",
        "customer_id": customer.id,
        "promo_type": template_code
    })

@task(name="run_send_email_pede_campaign")
def run_send_email_pede_campaign():
    eligible_loans_ids = WaivePromo.objects.get_queryset()\
        .eligible_loans('pede_oct').values_list('loan', flat=True)

    if len(eligible_loans_ids) == 0:
        return False

    for loan_id in eligible_loans_ids:
        send_email_pede_campaign.delay(loan_id)

########## BEGIN OF SELL OFF OCTOBER CAMPAIGN ########

@task(name="run_waive_sell_off_oct_campaign")
def run_waive_sell_off_oct_campaign():
    today = timezone.localtime(timezone.now()).date()

    campaign_start_date = date(2019, 10, 26)
    campaign_last_date = date(2019, 11, 11)

    if today < campaign_start_date or today > campaign_last_date:
        logger.info({
            "action": "run_waive_sell_off_oct_campaign",
            "status": "outside schedule"
        })
        return

    eligible_loans_ids = WaivePromo.objects.get_queryset()\
        .eligible_loans('sell_off_oct').values_list('loan', flat=True)

    if len(eligible_loans_ids) == 0:
        return None

    for loan_id in eligible_loans_ids:
        waive_sell_off_oct_campaign.delay(loan_id)

@task(name="waive_sell_off_oct_campaign")
def waive_sell_off_oct_campaign(loan_id, override_date=None):
    # for QA test purpose
    if override_date:
        campaign_start_date = datetime.strptime(override_date, "%Y-%m-%d").date() - timedelta(days=1)
    else:
        campaign_start_date = date(2019, 10, 25)
    event_type = 'waiver for late fee, interest and 20% principal'
    waiver_campaign_promo(loan_id, event_type, campaign_start_date, principal_percentage=80)

@task(name="run_send_email_sell_off_oct_campaign")
def run_send_email_sell_off_oct_campaign():
    eligible_loans_ids = WaivePromo.objects.get_queryset() \
        .eligible_loans(WaiveCampaignConst.SELL_OFF_OCT).values_list('loan', flat=True)

    if len(eligible_loans_ids) == 0:
        logger.info({
            "action": "run_send_email_sell_off_oct_campaign",
            "status": "no eligible_loans need to processed"
        })
        return False

    for loan_id in eligible_loans_ids:
        send_email_sell_off_oct_campaign.delay(loan_id)

@task(name="send_email_sell_off_oct_campaign")
def send_email_sell_off_oct_campaign(loan_id, override_date=None):
    promo_payments = WaivePromo.objects.filter(loan_id=loan_id)
    total_principal_amount = promo_payments.aggregate(
        total_principal_amount=Sum('remaining_installment_principal')) \
        .get('total_principal_amount')

    campaign_start_date = date(2019, 10, 25)
    promo_payment_ids = promo_payments.values_list('payment', flat=True)
    total_paid_amount = PaymentEvent.objects.filter(
        payment__in=promo_payment_ids,
        event_type='payment',
        cdate__gte=campaign_start_date
    ).aggregate(total_paid_amount=Sum('event_payment')).get('total_paid_amount')

    if not total_paid_amount:
        total_paid_amount = 0

    eighty_percent_principal = old_div(total_principal_amount * 80,100)
    remaining_principal_to_paid = eighty_percent_principal - total_paid_amount

    total_late_fee_amount = promo_payments.aggregate(
        total_remaining_late_fee=Sum('remaining_late_fee')) \
        .get('total_remaining_late_fee')

    total_interest_amount = promo_payments.aggregate(
        total_remaining_installment_interest=Sum('remaining_installment_interest')) \
        .get('total_remaining_installment_interest')

    total_due_amount = (total_principal_amount - total_paid_amount) + \
                       total_late_fee_amount + total_interest_amount

    loan = Loan.objects.get(pk=loan_id)
    customer = loan.customer
    julo_email_client = get_julo_email_client()

    emoji = {'party_popper':   u'\U0001F389',
             'star_struck':    u'\U0001F929',
             'person_running': u'\U0001F3C3',
             'collision':      u'\U0001F4A5',
             'timer_clock':    u'\U000023F2'
             }

    subjects = {'2019-10-25': ('Tidak pernah sebelumnya, dan tidak ditawarkan 2 kali memperingan Beban Anda!'
                              + emoji['party_popper']),
               '2019-10-29': ('Penawaran terbaik yang pernah Ada dari pinjaman Anda'
                              + emoji['star_struck']),
               '2019-11-02': ('Kesempatan tidak akan berulang, jangan lewatkan kesempatan langka..'
                              + emoji['person_running']),
               '2019-11-06': (emoji['collision'] +
                              'Detik-detik terakhir untuk dapat diskon besar-besaran dari pinajaman Anda'),
               '2019-11-09': (emoji['timer_clock'] +
                              'Kesempatan terakhir untuk memanfaatkan penawaran luar biasa ini,'
                              ' jangan sampai menyesal jika terlewat')
               }
    #to make easier to test by QA
    today = timezone.localtime(timezone.now()).date()
    today_str = override_date if override_date else str(today)
    subject = subjects.get(today_str)

    if not subject:
        logger.info({
            "action": "email_sell_off_campaign",
            "status": "executed outside schedule"
        })
        return

    status, headers, msg = julo_email_client.email_waive_sell_off_campaign(
        loan,
        format_number(total_principal_amount, locale="id_ID"),
        format_number(total_late_fee_amount, locale="id_ID"),
        format_number(total_interest_amount, locale="id_ID"),
        format_number(total_due_amount, locale="id_ID"),
        format_number(remaining_principal_to_paid, locale="id_ID"),
        subject)

    template_code = "email_sell_off_campaign"

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=customer.email,
        subject=subject,
        message_content=msg,
        template_code=template_code,
    )

    logger.info({
        "action": "email_sell_off_campaign",
        "customer_id": customer.id,
        "promo_type": template_code
    })

@task(name="load_sell_off_oct_campaign_data")
def load_sell_off_oct_campaign_data():
    from ..promo.management.commands import load_sell_off_oct_campaign_data
    if str(date.today().year) != '2019': # run only once
        return
    load_sell_off_oct_campaign_data.Command().handle()
    logger.info({
        "action": "load_sell_off_oct_campaign_data",
    })

########## END OF SELL OFF OCTOBER CAMPAIGN ########

@task(name="run_wa_experiment")
def run_wa_experiment():
    now = timezone.localtime(timezone.now())
    date = now.date()
    experiment_start_date = (datetime.strptime(ExperimentDate.WA_EXPERIMENT_START_DATE, '%Y-%m-%d')).date()
    experiment_end_date = (datetime.strptime(ExperimentDate.WA_EXPERIMENT_END_DATE, '%Y-%m-%d')).date()

    if date < experiment_start_date or date > experiment_end_date:
        return None

    hour = now.hour
    minute = now.minute
    payment_ids = []

    # Experiment group 1, 4, 5
    if hour in [12, 13, 14, 17, 18, 19, 20, 21] and minute == 0:
        # Group 1
        if hour == 12:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIT, (0, 1))
        elif hour == 13:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WITA, (0, 1))
        elif hour == 14:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIB, (0, 1))
        # Group 4 and group 5
        elif hour == 17:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIT, (6, 7))
        elif hour == 18:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WITA, (6, 7))
        elif hour == 19:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIB, (6, 7))
            payment_ids.extend(get_payment_ids_for_wa_experiment_october(LocalTimeType.WIT, (8, 9)))
        elif hour == 20:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WITA, (8, 9))
        elif hour == 21:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIB, (8, 9))
    # Experiment group 2
    elif hour in [10, 11, 12] and minute == 5:
        loan_tails = (2, 3)
        if hour == 10:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIT, loan_tails)
        elif hour == 11:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WITA, loan_tails)
        elif hour == 12:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIB, loan_tails)
    # Experiment group 3
    elif hour in [14, 15, 16] and minute == 30:
        loan_tails = (4, 5)
        if hour == 14:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIT, loan_tails)
        elif hour == 15:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WITA, loan_tails)
        elif hour == 16:
            payment_ids = get_payment_ids_for_wa_experiment_october(LocalTimeType.WIB, loan_tails)

    Payment.objects.filter(id__in=payment_ids).update(is_whatsapp=False)
    for payment_id in payment_ids:
        send_whatsapp_payment_reminder.delay(payment_id)

@task(name="call_pede_api_with_payment_greater_5DPD")
def call_pede_api_with_payment_greater_5DPD():
    url = "/api/v1/loan-pinter/loan/installment"
    applications = Application.objects.filter(
        partner__name=PARTNER_PEDE,
        loan__payment__payment_status_id__in=PaymentStatusCodes.greater_5DPD_status_code()
        ).order_by('id').distinct('id')
    data=[]
    for application in applications:
        payment = Payment.objects.filter(
            loan__application=application,
            payment_status_id__in=PaymentStatusCodes.greater_5DPD_status_code()
            ).order_by('id').values(
                'loan__application__application_xid',
                'loan__application__mobile_phone_1',
                'loan__application__email',
                'due_date', 'installment_interest',
                'installment_principal','late_fee_amount',
                'due_amount'
            ).first()
        payment_dict = {}
        payment_dict['ApplicationXid'] = payment.get('loan__application__application_xid')
        payment_dict['PhoneNo'] = payment.get('loan__application__mobile_phone_1')
        payment_dict['Email'] = payment.get('loan__application__email')
        payment_dict['DueDate'] = payment.get('due_date').strftime("%Y-%m-%d")
        payment_dict['DaysAfterDueDate'] = (date.today() - payment.get('due_date')).days
        payment_dict['InstallmentAmount'] = payment.get('installment_interest') + \
            payment.get('installment_principal')
        payment_dict['LateFee'] = payment.get('late_fee_amount')
        payment_dict['TotalAmount'] = payment.get('due_amount')
        data.append(payment_dict)
    result = json.dumps({"data":data})
    response = requests.post(settings.PEDE_BASE_URL+ url, data=result)
    logger.info({
        'action':'call_pede_api_with_payment_greater_5DPD',
        'response_code':response.status_code,
        'message':response.text
    })
    if response.status_code != 200:
        raise JuloException(
        "Failed to call the pede api with payment greater 5DPD"
        "error : %s " % (response.text)
        )


@task(queue='collection_low')
def send_pn_to_customer_notify_backup_va(gcm_reg_id, first_name, va_method, va_number):
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_backup_va(
        gcm_reg_id,
        first_name,
        va_method,
        va_number
    )

@task(queue='collection_low')
def send_all_notification_to_customer_notify_backup_va(loan_ids):
    payment_methods = PaymentMethod.objects.values(
        'loan__application__device__gcm_reg_id',
        'bank_code',
        'virtual_account',
        'loan__application__fullname',
        'loan__application__mobile_phone_1',
        'payment_method_name',
        'loan__customer',
        'loan_id'
        ).filter(
            loan__in=loan_ids,
            is_primary=True)

    for payment_method in payment_methods:
        split_payment_method_name = payment_method['payment_method_name'].split()
        va_method = split_payment_method_name[-1] \
            if split_payment_method_name[0].lower() == 'bank' \
            else split_payment_method_name[0]
        first_name = payment_method['loan__application__fullname'].split()[0]
        send_email_notify_backup_va.delay(
            payment_method['loan_id'],
            first_name,
            payment_method['bank_code'],
            va_method,
            payment_method['virtual_account']
        )

        send_sms_to_customer_notify_backup_va.delay(
            first_name,
            va_method,
            payment_method['virtual_account'],
            payment_method['loan__application__mobile_phone_1'],
        )

        send_pn_to_customer_notify_backup_va.delay(
            payment_method['loan__application__device__gcm_reg_id'],
            first_name,
            va_method,
            payment_method['virtual_account']
        )

@task(queue='collection_low')
def send_sms_to_customer_notify_backup_va(first_name, va_method, va_number, phone_number):
    template_name = 'sms_notify_backup_va'
    context = {
        'first_name': first_name,
        'va_number': va_number,
        'va_method': va_method
    }

    client = get_julo_sms_client()
    message = render_to_string(template_name + '.txt', context)
    phone_number = format_e164_indo_phone_number(phone_number)
    text_message, response = client.send_sms(phone_number, message)

@task(queue='collection_low')
def send_email_notify_backup_va(loan_id, first_name, bank_code, va_method, va_number):
    loan = Loan.objects.get_or_none(id=loan_id)

    if loan is None:
        return

    customer = loan.customer

    if customer is None:
        return

    julo_email_client = get_julo_email_client()

    try:
        status, headers, subject, msg = julo_email_client.email_notify_backup_va(
            customer,
            first_name,
            bank_code,
            va_method,
            va_number
        )

        template_code = "email_notify_backup_va"

        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=customer.email,
            subject=subject,
            message_content=msg,
            template_code=template_code,
        )

        logger.info({
            "action": "email_notify_backup_va",
            "customer_id": customer.id,
            "template": template_code
        })
    except Exception as e:
        pass

@task(name='revert_primary_va_to_normal')
def revert_primary_va_to_normal():
    """this task is to revert back all va that has its is_primary changed
    """
    today = timezone.localtime(timezone.now())
    three_days_ago = today.date() - timedelta(days=3)
    with transaction.atomic():
        PaymentMethod.objects.filter(
            udate__date=three_days_ago,
            is_primary=True,
            is_affected=True
        ).update(
            is_primary=False,
            udate=today,
            is_affected=False
        )

        # this query is to take the first primary va that is changed to false of a loan
        primary_payment_methods = PaymentMethod.objects.filter(
            udate__date=three_days_ago,
            is_primary=False,
            is_affected=True
        ).distinct('loan').order_by('loan', 'udate').values_list('id', flat=True)

        PaymentMethod.objects.filter(id__in=primary_payment_methods)\
            .update(
                is_primary=True,
                udate=today,
                is_affected=False
            )

        # this query is to make sure that if more than one type are choose to be affected,
        # it will make sure that the affected column are revert back to false
        PaymentMethod.objects.filter(
            udate__date=three_days_ago,
            is_affected=True,
            is_primary=False
        ).update(
            is_affected=False,
            udate=today
        )


@task(queue='application_high')
def run_fdc_request(fdc_inquiry_data, reason, retry_count=0, retry=False, source=None):
    from juloserver.dana.tasks import process_dana_fdc_result
    from juloserver.fdc.tasks import j1_record_fdc_risky_history
    from juloserver.application_flow.constants import AnaServerFormAPI

    call_web_model_directly = False

    try:
        try:
            logger.info({
                "function" : "run_fdc_request",
                "action" : "call get_and_save_fdc_data",
                "fdc_inquiry_data" : fdc_inquiry_data,
                "reason" : reason,
                "retry_count" : retry_count,
                "retry" : retry,
                "source": source
            })
            get_and_save_fdc_data(fdc_inquiry_data, reason, retry)
        except ObjectDoesNotExist as err:
            log_message = {
                "function": "run_fdc_request",
                "action" : "call get_and_save_fdc_data",
                "source": source,
                "reason": str(err),
                "fdc_inquiry_id": fdc_inquiry_data.get("id"),
                "nik": fdc_inquiry_data.get("nik"),
                "application_status": None
            }
            nik = log_message.get("nik")
            if nik:
                application = Application.objects.filter(ktp=nik).last()
                if application:
                    log_message["application_status"] = application.application_status.status_code

            logger.error(log_message)
            return

        fdc_inquiry = FDCInquiry.objects.get(id=fdc_inquiry_data['id'])
        if not fdc_inquiry:
            return
        web_model_fdc_retry_setting = FeatureSetting.objects.filter(
            is_active=True,
            feature_name=FeatureNameConst.WEB_MODEL_FDC_RETRY_SETTING).last()
        if web_model_fdc_retry_setting:
            hours_threshold = web_model_fdc_retry_setting.parameters['threshold_in_hours']
            current_time = timezone.localtime(timezone.now())
            if current_time > timezone.localtime(fdc_inquiry.cdate) +\
                    timedelta(hours=hours_threshold):
                call_web_model_directly = True

        application_id = fdc_inquiry.application_id
        application = Application.objects.get_or_none(id=application_id)
        app_status = application.application_status.status_code

        # add logic to send fdc result to dana
        if application.is_dana_flow():
            dana_fdc_result = DanaFDCResult.objects.filter(
                application_id=application.id
            ).last()
            if dana_fdc_result and dana_fdc_result.fdc_status == DanaFDCResultStatus.INIT:
                process_dana_fdc_result.delay(application.id)

        # webapp run credit model if application has no credit score yet
        if (app_status == ApplicationStatusCodes.FORM_PARTIAL and \
                (application.is_web_app() or application.is_partnership_app()) and \
                not hasattr(application, 'creditscore')) and \
                (fdc_inquiry.inquiry_status in ('success', 'not_found') or call_web_model_directly):
            post_anaserver('/api/amp/v1/web-form/',
                           json={'application_id': application.id})

        # make sure scoring after fdc inquiry
        if app_status == ApplicationStatusCodes.FORM_PARTIAL \
                and application.is_regular_julo_one() \
                and not hasattr(application, 'creditscore'):

            post_anaserver(AnaServerFormAPI.COMBINED_FORM, json={'application_id': application.id})

        if (
            app_status == ApplicationStatusCodes.FORM_PARTIAL
            and application.is_julo_one_ios()
            and not hasattr(application, 'creditscore')
        ):
            post_anaserver(AnaServerFormAPI.IOS_FORM, json={'application_id': application.id})

        if app_status != ApplicationStatusCodes.LOC_APPROVED or reason != 2:
            return

        if not application.is_julo_one():
            return

        is_risky = get_customer_service().j1_check_risky_customer(application.id)
        j1_record_fdc_risky_history.delay(application.id, is_risky)

        # application.update_safely(is_fdc_risky=is_risky)
        # update_is_fdc_risky_early_payback_offer.delay(application.id)
        # application_original = application.applicationoriginal_set.first()
        # if not application_original:
        #     return
        #
        # application_original.update_safely(is_fdc_risky=is_risky)

    except FDCServerUnavailableException:
        logger.error({
                "action": "run_fdc_request",
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data
        })

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        logger.info(
            {
                "data": fdc_inquiry_data,
                "action": "run_fdc_request",
                "error": "got exception on run_fdc_request",
                "message": str(e),
            }
        )
    else:
        return

    # variable reason equal to 1 is for FDCx100
    # if reason != 1:
    #     return

    fdc_retry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_FDC_INQUIRY,
        category="fdc",
        is_active=True).first()

    if not fdc_retry_feature:
        logger.info({
            "action": "run_fdc_request",
            "error": "fdc_retry_feature is not active"
        })
        return

    params = fdc_retry_feature.parameters
    retry_interval_minutes = params['retry_interval_minutes']
    max_retries = params['max_retries']

    if retry_interval_minutes == 0:
        raise JuloException("Parameter retry_interval_minutes: %(retry_interval_minutes)s can not be zero value" % {'retry_interval_minutes': retry_interval_minutes})
    if not isinstance(retry_interval_minutes, int):
        raise JuloException("Parameter retry_interval_minutes should integer")

    if not isinstance(max_retries, int):
        raise JuloException("Parameter max_retries should integer")
    if max_retries <= 0:
        raise JuloException("Parameter max_retries should greater than zero")

    countdown_seconds = retry_interval_minutes * 60

    if retry_count > max_retries:
        logger.info(
            {
                "action": "run_fdc_request",
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
                "data": fdc_inquiry_data,
            }
        )

        return

    retry_count += 1

    logger.info(
        {
            'action': 'run_fdc_for_failure_status',
            'retry_count': retry_count,
            'count_down': countdown_seconds,
            "data": fdc_inquiry_data,
        }
    )

    run_fdc_request.apply_async((fdc_inquiry_data, reason, retry_count, retry,
                                 "triggered from run_fdc_request"),
                                countdown=countdown_seconds)


@task(queue='fdc_inquiry', bind=True, max_retries=3)
def run_fdc_api(self):
    logger.info({
        "task": "juloserver.julo.tasks.run_fdc_api",
        "message": "run_fdc_api task is running"
    })

    fdc_feature = FeatureSetting.objects.filter(feature_name="fdc_configuration",
                                                is_active=True).last()
    if not fdc_feature or (fdc_feature and not fdc_feature.parameters.get('outstanding_loan')):
        return

    today = timezone.localtime(timezone.now()).date()

    try:
        logger.info({
            "function" : "check_if_fdc_inquiry_exist_filtered_by_date",
            "action" : "call check_if_fdc_inquiry_exist_filtered_by_date",
            "date_input": today,
        })
        check_if_fdc_inquiry_exist_filtered_by_date(today)
    except JuloException as err:
        error_msg = {
            "task": "juloserver.julo.tasks.run_fdc_api",
            "message": "error on check_if_fdc_inquiry_exist_filtered_by_date",
            "attempt counts": self.request.retries,
            "timestamp": timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*"),
            "error": str(err),
        }

        # send error log if error
        logger.warning(error_msg)

        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

        if self.request.retries >= self.max_retries:
            # send to notification to slack if already failed the 3rd attempts

            slack_channel = "#fdc_alerts"
            mentions = "<@U03EPM28X88> <@U02GAP310VC>\n"
            title = ":alert: ===FDC Inquiry Failed to Run=== :alert: \n"
            timestamp = error_msg.get('timestamp') + "\n"
            content = "```" + str(err) +"```"
            text = mentions + title + timestamp + content
            if settings.ENVIRONMENT != 'prod':
                text = "*[" + settings.ENVIRONMENT + " notification]*\n" + text
                slack_channel = "#fdc_alerts_sandbox"

            send_slack_bot_message(slack_channel, text)
            raise err

        raise self.retry(exc=err, countdown=600)

    customer_id_list = FDCInquiryPrioritizationReason2.objects \
                        .filter(serving_date=today) \
                        .order_by('priority_rank') \
                        .values_list('customer_id', flat=True)
    fdc_inquiry_run = FDCInquiryRun.objects.create()
    for batch_customer_ids in batch_pk_query_with_cursor_with_custom_db(customer_id_list, batch_size=1000, database=JULO_ANALYTICS_DB):
        fdc_inquiry_list = []
        for customer_id in batch_customer_ids:
            try:
                value = Account.objects.filter(customer_id=customer_id).values('application__id', 'application__ktp', 'application__application_status_id', \
                        'customer_id', 'application__product_line_id')[0]
                nik = value['application__ktp']

                # dana are using fake nik on application table
                if value['application__product_line_id'] == ProductLineCodes.DANA:
                    dana_cust_data = DanaCustomerData.objects.filter(
                        application_id=value['application__id']).values('nik').last()
                    if dana_cust_data:
                        nik = dana_cust_data['nik']

                elif value['application__product_line_id'] == ProductLineCodes.AXIATA_WEB:
                    axiata_cust_nik = PartnershipCustomerData.objects.filter(
                        application_id=value['application__id']
                    ).values_list('nik', flat=True).last()

                    if axiata_cust_nik:
                        nik = axiata_cust_nik

                elif (
                    value['application__product_line_id']
                    == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
                ):
                    mf_cust_nik = (
                        PartnershipCustomerData.objects.filter(
                            application_id=value['application__id']
                        )
                        .values_list('nik', flat=True)
                        .last()
                    )

                    if mf_cust_nik:
                        nik = mf_cust_nik

                fdc_inquiry = FDCInquiry(
                    application_id=value['application__id'],
                    customer_id=value['customer_id'],
                    nik=nik,
                    fdc_inquiry_run=fdc_inquiry_run,
                    application_status_code=value['application__application_status_id'])

                fdc_inquiry_list.append(fdc_inquiry)
            except Exception as e:
                logger.error({'action': 'run_fdc_api', 'state': 'payload generation', 'error': str(e)})
                continue

        # create FDCInquiry for each batch
        if fdc_inquiry_list:
            FDCInquiry.objects.bulk_create(fdc_inquiry_list)
            fdc_inquiry_list = []
            logger.info({'action': 'run_fdc_api', 'state': 'payload generation', 'message': 'FDCInquiry created successfully'})
        else:
            logger.error({'action': 'run_fdc_api', 'state': 'payload generation', 'error': 'no FDCInquiry created'})


@task(queue='fdc_inquiry')
def run_fdc_api_resume():
    logger.info({
        "task": "juloserver.julo.tasks.run_fdc_api_resume",
        "message": "run_fdc_api_resume task is running"
    })

    # check if the previous task is already flushed out
    current_queue = get_fdc_inquiry_queue_size()

    if current_queue is None or current_queue == '':
        logger.error({
            "task": "juloserver.julo.tasks.run_fdc_api_resume",
            "message": "Can't get queue size from rabbitmq, please check",
            "queue_size": current_queue
        })
        msg = "Can't get Queue size from Rabbitmq, Task is not running Please Check"
        notify_failure(msg, channel='#fdc', label_env=True)
        return

    if current_queue > 1:
        logger.warning({
            "task": "juloserver.julo.tasks.run_fdc_api_resume",
            "message": "task is skipped because the previous task is not finish",
            "queue_size": current_queue
        })
        return

    fdc_feature = FeatureSetting.objects.filter(feature_name="fdc_configuration",
                                                is_active=True).last()
    if not fdc_feature:
        return

    # we set the RPS to lowest (3 RPS)
    rps_throttling = fdc_feature.parameters.get('rps_throttling', 3)
    # we set the batch size to 120000
    batch_size = fdc_feature.parameters.get('batch_size', 120000)
    delay = math.ceil(1000 / rps_throttling)

    today = timezone.localtime(timezone.now())

    fdc_inquiry_data_list = FDCInquiry.objects.filter(
        inquiry_status='pending', # status from julo
        fdc_inquiry_run=FDCInquiryRun.objects.latest('id'),
        status__isnull=True, # status from fdc
        cdate__gte=today.date()
        ).order_by('id').values('id', 'nik')[:batch_size]
    eta_time = timezone.localtime(timezone.now())
    for fdc_inquiry_data in fdc_inquiry_data_list:
        eta_time += timedelta(milliseconds=delay)
        run_fdc_request.apply_async(
            (fdc_inquiry_data, 2, 0, True, "triggered from run_fdc_api_resume"),
            queue='fdc_inquiry',
            routing_key='fdc_inquiry',
            eta=eta_time
        )


@task(queue='application_normal')
def trigger_fdc_inquiry(fdc_inquiry_id, application_ktp, application_status):
    fdc_inquiry_data = {'id': fdc_inquiry_id, 'nik': application_ktp}
    run_fdc_request.apply_async((fdc_inquiry_data, 1, 0, False,
                                 "triggered from trigger_fdc_inquiry"))


@task(queue='application_normal')
def run_fdc_for_failure_status():
    fdc_retry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SCHEDULED_RETRY_FDC_INQUIRY,
        category="fdc",
        is_active=True).first()

    if not fdc_retry_feature:
        logger.warning({
            "task": "run_fdc_for_failure_status",
            "message": "task skipped due to fdc_retry_feature is not active"
        })
        return

    params = fdc_retry_feature.parameters
    inquiry_reasons = params.get('filter_inquiry_reasons', None)
    delay_interval = params.get('delay_interval_milliseconds', 1000)
    limit = params.get('limit_per_cycle', 1000)
    fdc_inquiry_data_list = FDCInquiry.objects.filter(
        inquiry_status__in=['error', 'inquiry_disabled'])
    if inquiry_reasons:
        fdc_inquiry_data_list = fdc_inquiry_data_list.filter(inquiry_reason__in=inquiry_reasons)
    fdc_inquiry_data_list = fdc_inquiry_data_list.values(
        'id', 'nik', 'application_status_code', 'inquiry_reason')[:limit]
    eta_time = timezone.localtime(timezone.now())

    for fdc_inquiry_data in fdc_inquiry_data_list:
        eta_time += timedelta(milliseconds=delay_interval)
        inquiry_reason = (fdc_inquiry_data['inquiry_reason'][:1]) if fdc_inquiry_data['inquiry_reason'] \
            else '1'
        if fdc_inquiry_data['inquiry_reason'] == FDCFailureReason.REASON_FILTER[1]:
            run_fdc_request.apply_async(
                (fdc_inquiry_data, int(inquiry_reason), 0, True,
                 "triggered from run_fdc_for_failure_status"),
                eta=eta_time
            )
        else:
            run_fdc_request.apply_async(
                (fdc_inquiry_data, int(inquiry_reason), 0, True,
                 "triggered from run_fdc_for_failure_status"),
                eta=eta_time
            )
########## END OF COLLECTION TASKS ########

@task(queue='application_low')
def send_alert_notification_face_recog_through_slack():
    # send notification through slack to (Benjamin Uhlig, Martijn Wieriks, Ahmad Kasyfi, Yogi Suryadinata, Hafiz)
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SLACK_NOTIFICATION_FACE_RECOGNITION,
        is_active=True).first()
    if feature_setting:
        message = ('AWS Face Recognition feature has been turn off automatically due to server issue. '
                   'Please Check AWS Rekognition Server and turn on the feature manually in Django Admin page')
        for slack_id in feature_setting.parameters:
            get_slack_bot_client().api_call("chat.postMessage",
                                            channel=slack_id,
                                            text=message)

@task(queue='application_normal')
def set_off_face_recognition():
    face_recognition = FaceRecognition.objects.get_or_none(
        feature_name=FeatureNameConst.FACE_RECOGNITION,
        is_active=True
    )
    if face_recognition:
        face_recognition.is_active = False
        face_recognition.save()

@task(queue='application_normal')
def expired_application_147_for_digisign():
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.EXPIRED_147_FACE_RECOGNITION,
        is_active=True
    )
    if feature_setting:
        expired_time = timezone.localtime(timezone.now()) - timedelta(**feature_setting.parameters)
        applications = Application.objects.filter(application_status=ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
                                                  applicationhistory__status_new=ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
                                                  applicationhistory__cdate__lte=expired_time)

        for application in applications:
            process_application_status_change(application.id,ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                                              change_reason='Resubmission request abandoned')


@task(name='populate_xid_lookup', queue='loan_normal')
def populate_xid_lookup():
    unused_xid_lookup_count = XidLookup.objects.filter(is_used_application=False).count()
    params = get_xid_fs_parameters()
    xid_lookup_unused_min_count = params.get('xid_lookup_min_count', XID_LOOKUP_UNUSED_MIN_COUNT)
    send_slack_alerts = params.get('send_slack_alerts', False)

    # generate xid if unused count is less
    if unused_xid_lookup_count <= xid_lookup_unused_min_count:
        success_insert = 0
        start_range = 1000000000
        end_range = 9999999999
        max_count = params.get('max_count', XID_MAX_COUNT)
        batch_size = 1000

        randomize_xids = list(set([compute_xid(rand_number)
                                   for rand_number in random.sample(range(start_range, end_range), max_count)]))
        exist_xids = XidLookup.objects.filter(xid__in=randomize_xids).values_list("xid", flat=True)
        filtered_xids = [XidLookup(xid=xid, is_used_application=False)
                         for xid in randomize_xids if xid not in exist_xids]

        if len(filtered_xids) == 0:
            sentry_client = get_julo_sentry_client()
            sentry_client.capture_message("xid generation run out of random number")
            return

        for xids in chunk_array(filtered_xids, batch_size):
            XidLookup.objects.bulk_create(xids)

        # Update used xid
        populate_xid_lookup_subtask.delay(randomize_xids)

    # send slack alert for the number of remaining xids
    if send_slack_alerts:
        send_slack_alert_remaining_xids(unused_xid_lookup_count)


def get_xid_fs_parameters():
    parameters = {}
    feature_settings = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GENERATE_XID_MAX_COUNT, is_active=True
    ).last()
    if feature_settings:
        parameters = feature_settings.parameters
    return parameters


def send_slack_alert_remaining_xids(unused_xid_lookup_count):
    header = "<!here> :fire:\n"
    personal_header = ":fire:\n"
    message = "unused_xid_lookup_count : {} \n".format(unused_xid_lookup_count)
    if settings.ENVIRONMENT != 'prod':
        header += "Testing Purpose from {}".format(settings.ENVIRONMENT)
        personal_header += "Testing Purpose from {}".format(settings.ENVIRONMENT)
    formated_message_for_channel = "{} ```{}```".format(header, message)
    send_message_normal_format(formated_message_for_channel, channel='#alert-xid')


@task(name='populate_xid_lookup_subtask')
def populate_xid_lookup_subtask(randomize_xids):
    # update used application_xid in xid_lookup between the newly generated xids
    with transaction.atomic():
        limit = 100

        for xids in chunk_array(randomize_xids, limit):
            application_xid_list = Application.objects.filter(application_xid__in=xids, application_xid__isnull=False)\
                .values_list("application_xid", flat=True)\
                .order_by('application_xid')

            if not application_xid_list:
                continue
            xid_exists = XidLookup.objects.filter(xid__in=application_xid_list)
            if xid_exists:
                xid_exists.update(is_used_application=True)


#task to evaluate each row of uninstall/install data
@task(name='installation_data_row_subtask')
def installation_data_row_subtask(row):

    #get latest customer by appsflyer_id
    search_customer = Customer.objects.filter(appsflyer_device_id=row['AppsFlyer ID']).values('id').last()

    #set each column of the table
    data = ApplicationInstallHistory(
        customer_id=search_customer['id'] if search_customer else None,
        appsflyer=row['AppsFlyer ID'],
        event_name=row['Event Name'],
        event_time=row['Event Time'],
        partner=row['Partner'],
        media_source=row['Media Source'],
        campaign=row['Campaign'],
    )

    try:
        ApplicationInstallHistory.save(data)
    except IntegrityError as e:
        logger.info({
            "method": "installation_data_row_subtask",
            "error": str(e)
        })


#task to set range of time for uninstallation/installation data
@task(name='update_uninstallation_data')
def update_uninstallation_data():
    track_uninstallation_data_subtask.delay()


#updates uninstallation data
@task(name='track_uninstallation_data_subtask')
def track_uninstallation_data_subtask(timeDiff = 1):

    today = date.today() - timedelta(days = timeDiff)

    token = str(settings.APPS_FLYER_API_TOKEN)
    base_url = settings.APPS_FLYER_UNINSTALL_BASE_URL + token + settings.APPS_FLYER_UNINSTALL_LOCATION_QUERY + "&from=%s&to=%s" % (today, today)

    #try to make the API call
    try:
        response = requests.get(base_url)

        if not response.ok:

            #if its not ok, send an error message and log it
            error = {
                "method": "track_uninstallation_data_subtask",
                "status_code": response.status_code,
                "response": response.text
            }

            logger.info(error)
            raise Exception(response.text)

    except Exception as e:
        raise e

    #else, if it succeeds, parse the csv file and update the table
    reader_list = unicodecsv.DictReader(io.BytesIO(response.text.encode()))

    for row in reader_list:

        #for each row, call the row parser subtask
        installation_data_row_subtask.delay(row)


#task to set range of time for uninstallation/installation data
@task(queue='application_normal')
def update_installation_data():
    track_installation_data_subtask.delay()


#task to update installation data daily
@task(queue='application_normal')
def track_installation_data_subtask(timeDiff = 1):

    today = date.today() - timedelta(days = timeDiff)

    token = str(settings.APPS_FLYER_API_TOKEN)
    base_url = settings.APPS_FLYER_INSTALL_BASE_URL + token + settings.APPS_FLYER_UNINSTALL_LOCATION_QUERY + "&from=%s&to=%s" % (today, today)

    #try to make the API call
    try:
        response = requests.get(base_url)

        if not response.ok:

            #if its not ok, send an error message and log it
            error = {
                "method": "track_installation_data_subtask",
                "status_code": response.status_code,
                "response": response.text
            }

            logger.info(error)
            raise Exception(response.text)

    except Exception as e:
        raise e

    #else, if it succeeds, parse the csv file and update the table
    reader_list = unicodecsv.DictReader(io.BytesIO(response.text.encode()))

    for row in reader_list:

        #for each row, call the row parser subtask
        installation_data_row_subtask.delay(row)


#retroload 90 days of uninstall/install data in uat
@task(name='migrate_appsflyer_installation_data')
def migrate_appsflyer_installation_data():

    # Please call the function for the following ranges
    # Day 1:
    # range(89, 80, -1)
    # range(79, 70, -1)
    # Day 2:
    # range(70, 61, -1)
    # range(60, 51, -1)
    # Day 3:
    # range(51, 41, -1)
    # range(40, 31, -1)
    # Day 4:
    # range(31, 21, -1)
    # range(20, 11, -1)
    # Day 5:
    # range(11, 5, -1)

    for day in range(89, 80, -1):
        track_installation_data_subtask.delay(day)
        track_uninstallation_data_subtask.delay(day)


@task(queue='application_normal')
def recreate_skiptrace():
    # check for empty ST apps
    st_applications = Application.objects.\
        filter(application_status_id__in=(
            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED)).\
        filter(Q(partner_id__isnull=True) | Q(partner_id=5)).annotate(st_count=Count('customer__skiptrace')).\
        filter(st_count=0)

    for app in st_applications:
        ana_data = {'application_id': app.id}

        url = AnaServerFormAPI.COMBINED_FORM
        if app.is_julo_one_ios():
            url = AnaServerFormAPI.IOS_FORM

        post_anaserver(url, json=ana_data)


@task(name='call_ana_server', queue='application_high')
def call_ana_server(url, data):
    post_anaserver(url, json=data)


@task(name='populate_virtual_account_suffix')
def populate_virtual_account_suffix():
    from juloserver.integapiv1.services import get_last_va_suffix

    count_va_suffix_unused = VirtualAccountSuffix.objects.filter(
        loan=None, line_of_credit=None, account=None).count()
    # generate virtual_account_suffix if unused count is less
    if count_va_suffix_unused <= VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT:
        batch_size = 1000
        last_virtual_account_suffix = get_last_va_suffix(
            VirtualAccountSuffix,
            'virtual_account_suffix',
            PiiSource.VIRTUAL_ACCOUNT_SUFFIX,
        )

        start_range = int(last_virtual_account_suffix) + 1
        max_count = VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT
        end_range = start_range + max_count + 1

        va_suffix_obj = (
            VirtualAccountSuffix(
                virtual_account_suffix=str(va_suffix_val)
            ) for va_suffix_val in range(start_range, end_range)
        )
        while True:
            batch = list(islice(va_suffix_obj, batch_size))
            if not batch:
                break
            VirtualAccountSuffix.objects.bulk_create(batch, batch_size)

@task(queue='application_normal')
def rerun_update_status_apps_flyer_task():
    time_now = timezone.localtime(timezone.now())
    applications = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        partner_id__isnull=True,
        udate__lte=time_now - timedelta(minutes=30)
    ).values_list("id", flat=True).order_by('id')

    for app_id in applications:
        update_status_apps_flyer_task.delay(app_id, True)


@task(queue='collection_high')
def send_automated_robocall():
    """
    Process payment reminder for streamlined robocall
    """
    streamlined_communication_robocall = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.ROBOCALL,
        is_automated=True,
        call_hours__isnull=False
    )

    grab_robocall_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
        is_active=True
    )
    if not grab_robocall_feature_setting:
        streamlined_communication_robocall = streamlined_communication_robocall.exclude(product='nexmo_grab')
        logger.info({
            "action": "send_automated_robocall",
            "message": "grab robocall feature setting doesn't exist or inactive"
        })
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Robocall] Grab robocall feature setting not found / inactive !",
            msg_type=3
        )
    else:
        mark_schedule = grab_robocall_feature_setting.parameters.get("mark_schedule")
        # default to now
        next_mark_schedule = timezone.localtime(timezone.now())
        if mark_schedule:
            midnight_today = timezone.localtime(datetime.combine(timezone.localtime(
                timezone.now()).date(), datetime_time_alias()))
            mark_schedule_time = datetime.strptime(mark_schedule, '%H:%M').time()
            mark_schedule_cron_time = f'{mark_schedule_time.minute} {mark_schedule_time.hour} * * *'
            mark_croniter_data = croniter(mark_schedule_cron_time, midnight_today)
            next_mark_schedule = mark_croniter_data.get_next(datetime)

        dpd_list = streamlined_communication_robocall.filter(
            product='nexmo_grab').values_list('dpd', flat=True).filter(dpd__isnull=False).distinct()

        mark_voice_account_payment_reminder_grab.apply_async((dpd_list,), eta=next_mark_schedule)

    # mark the customer that can be called by robocall once
    mark_voice_payment_reminder.delay(
        streamlined_communication_robocall.exclude(
            product__in=NexmoRobocallConst.ALL_PRODUCTS
        ).values_list('dpd', flat=True).filter(dpd__isnull=False).distinct())

    mark_voice_account_payment_reminder.delay(
        streamlined_communication_robocall.filter(
            product__in=NexmoRobocallConst.WITHOUT_GRAB_PRODUCTS
        ).values_list('dpd', flat=True).filter(dpd__isnull=False).distinct())

    for streamlined_comm in streamlined_communication_robocall:
        call_hours = streamlined_comm.call_hours
        called_function = streamlined_comm.function_name
        product_line_name = streamlined_comm.product.split('_')[1]
        product_lines = getattr(ProductLineCodes, product_line_name)()
        for index, call_time in enumerate(call_hours):
            now = timezone.localtime(timezone.now())
            time_sent = call_time.split(':')
            function_name = called_function[index]
            hours = int(time_sent[0])
            minute = int(time_sent[1])
            for attempt in range(3):
                if attempt == 0:
                    prev_hour = hours - 2
                elif attempt == 1:
                    prev_hour = hours - 1
                else:
                    prev_hour = hours
                if prev_hour <= 0:
                    prev_hour = 0
                later = timezone.localtime(timezone.now()).replace(
                    hour=prev_hour, minute=minute, second=5)
                countdown = int(py2round((later - now).total_seconds()))
                if countdown >= 0:
                    try:
                        schema_module = importlib.import_module('juloserver.julo.services2.voice')
                        func = getattr(schema_module, function_name)
                        func.apply_async(
                            (attempt, prev_hour, product_lines, streamlined_comm.id,),
                            countdown=countdown)
                        logger.info({
                            'action': 'send_automated_robocall',
                            'function_name': function_name,
                            'attempt': attempt,
                            'prev_hour': prev_hour,
                            'product_lines': product_lines,
                            'streamlined_comm_id': streamlined_comm.id,
                            'message': 'success_run'
                        })
                    except Exception as e:
                        logger.exception({
                            'action': 'send_automated_robocall',
                            'function_name': function_name,
                            'message': str(e)
                        })
                else:
                    logger.info({
                        'action': 'send_automated_robocall',
                        'call_hours': time_sent,
                        'later': later,
                        'streamlined_comm': streamlined_comm.template_code,
                        'message': 'run failed because time had passed'
                    })


@task(queue='collection_high')
def send_automated_comms():
    """Handles scheduling of daily automated comms. This task is scheduled in Celery beat."""
    from juloserver.email_delivery.tasks import (
        trigger_all_email_payment_reminders,
        trigger_all_ptp_email_payment_reminders_j1,
    )

    # SMS Payment Reminder
    schedule_send_automated_comm_sms_non_account_based.delay()
    schedule_send_automated_comm_sms_account_based.delay()
    send_automated_comms_ptp_sms.delay()

    # Robocall Payment Reminder
    is_today_holiday = is_holiday()
    if not is_today_holiday:
        send_automated_robocall.delay()
    else:
        logger.info({
            'action': 'streamlined_comms (robocall)',
            'is_holiday': is_today_holiday,
            'message': 'Skip sending robocall due to holiday.'
        })

    # handle PN
    streamlined_communication_pn = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.PN,
        time_sent__isnull=False,
        is_automated=True
    ).exclude(Q(ptp='real-time') | Q(extra_conditions=UNSENT_MOENGAGE))
    for streamlined_pn in streamlined_communication_pn:
        now = timezone.localtime(timezone.now())
        time_sent = streamlined_pn.time_sent.split(':')
        hours = int(time_sent[0])
        minute = int(time_sent[1])
        later = timezone.localtime(timezone.now()).replace(hour=hours, minute=minute, second=5, microsecond=0)
        countdown = int(py2round((later - now).total_seconds()))
        # send base on schedule on streamlined
        if countdown >= 0:
            if streamlined_pn.template_code in TemplateCode.all_cashback_expired():
                # deprecated;
                continue
            elif streamlined_pn.product == "j1":
                if streamlined_pn.ptp is not None:
                    send_automated_comm_pn_ptp_j1.apply_async((streamlined_pn,), countdown=countdown)
            else:
                send_automated_comm_pn.apply_async((streamlined_pn.id,), countdown=countdown)
            logger.info({
                'action': 'send_automated_pn',
                'streamlined_comm': streamlined_pn.template_code,
                'message': 'success run'
            })
        else:
            logger.info({
                'action': 'send_automated_pn',
                'streamlined_comm': streamlined_pn.template_code,
                'message': 'run failed because time had passed'
            })

    # handle email
    streamlined_communication_email = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.EMAIL,
        is_automated=True, time_sent__isnull=False,
        extra_conditions__isnull=True
    ).exclude(ptp='real-time')
    for streamlined_email in streamlined_communication_email:
        now = timezone.localtime(timezone.now())
        time_sent = streamlined_email.time_sent.split(':')
        hours = int(time_sent[0])
        minute = int(time_sent[1])
        later = timezone.localtime(timezone.now()).replace(hour=hours, minute=minute, second=5, microsecond=0)
        countdown = int(py2round((later - now).total_seconds()))
        # send base on schedule on streamlined
        if countdown >= 0:
            if streamlined_email.product in ("j1", "jturbo"):
                if streamlined_email.ptp is not None:
                    trigger_all_ptp_email_payment_reminders_j1.apply_async((streamlined_email, ), countdown=countdown)
            else:
                trigger_all_email_payment_reminders.apply_async((streamlined_email.id,), countdown=countdown)
            logger.info({
                'action': 'send_automated_email',
                'streamlined_comm': streamlined_email.template_code,
                'message': 'success run'
            })
        else:
            logger.info({
                'action': 'send_automated_email',
                'streamlined_comm': streamlined_email.template_code,
                'message': 'run failed because time had passed'
            })


@task(queue='collection_high')
def schedule_send_automated_comm_sms_non_account_based():
    """
    Schedule the SMS payment reminder for non-account/old product
    For example STL/MTL/PEDE
    """
    streamlined_comm_sms_non_accounts = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.SMS,
        time_sent__isnull=False,
        is_automated=True,
        extra_conditions__isnull=True,
        dpd__isnull=False,
        ptp__isnull=True,
        product__in=Product.sms_non_account_products(),
    )
    for streamlined_comm in streamlined_comm_sms_non_accounts:
        now = timezone.localtime(timezone.now())
        time_sent = streamlined_comm.time_sent.split(':')
        hours = int(time_sent[0])
        minute = int(time_sent[1])
        later = timezone.localtime(timezone.now()).replace(
            hour=hours, minute=minute, second=0, microsecond=0
            )
        countdown = int(py2round((later - now).total_seconds()))
        # send base on schedule on streamlined
        if countdown >= 0:
            send_automated_comm_sms.apply_async((streamlined_comm.id,), countdown=countdown)
            logger.info(
                {
                    'action': 'schedule_send_automated_comm_sms_non_account_based',
                    'streamlined_comm': streamlined_comm.template_code,
                    'countdown': countdown,
                    'message': 'success run'
                }
            )
        else:
            logger.info(
                {
                    'action': 'schedule_send_automated_comm_sms_non_account_based',
                    'streamlined_comm': streamlined_comm.template_code,
                    'countdown': countdown,
                    'message': 'run failed because time had passed'
                }
            )


@task(queue='collection_high')
def schedule_send_automated_comm_sms_account_based():
    """
    Schedule the SMS payment reminder non-account based product
    For example J1, JTurbo
    """
    streamlined_comm_sms_accounts = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.SMS,
        time_sent__isnull=False,
        is_automated=True,
        ptp__isnull=True
    ).exclude(
        product__in=Product.sms_non_account_products()
    )
    for streamlined_comm in streamlined_comm_sms_accounts:
        time_sent = streamlined_comm.time_sent.split(':')
        time_sent = timezone.localtime(
            timezone.now()).replace(hour=int(time_sent[0]), minute=int(time_sent[1]))

        # Minute increment > time required to process email.
        minute_increment = RETRY_SMS_J1_MINUTE

        expected_sent_time = timezone.localtime(
            timezone.now()).replace(hour=time_sent.hour, minute=time_sent.minute)
        # Attempt sending sms j1 every 2 hours {minute_increment} minutes until 19:59
        while expected_sent_time.hour < 20:
            countdown = calculate_countdown(
                hour=expected_sent_time.hour, minute=expected_sent_time.minute)

            if countdown >= 0:
                task_obj = send_automated_comm_sms_j1.apply_async(
                    (streamlined_comm.id,), countdown=countdown
                    )
                logger.info(
                    {
                        'action': 'schedule_send_automated_comm_sms_account_based',
                        'streamlined_comm': streamlined_comm.template_code,
                        'countdown': countdown,
                        'message': 'success run',
                        'task_id': task_obj.id,
                    }
                )
            else:
                logger.info(
                    {
                        'action': 'schedule_send_automated_comm_sms_account_based',
                        'streamlined_comm': streamlined_comm.template_code,
                        'countdown': countdown,
                        'message': 'run failed because time had passed'
                    }
                )
            expected_sent_time += timezone.timedelta(minutes=minute_increment)


@task(queue='collection_high')
def send_automated_comm_sms(streamlined_comm_id):
    """
    Process SMS payment reminder for non-account-based product (STL,MTL,Axiata,etc)
    This function handling for the PTP case also.

    Args:
        streamlined_comm_id (int): StreamlinedCommunication model id

    Returns:
        None
    """
    today = timezone.localtime(timezone.now()).date()
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    if not streamlined:
        return

    if not streamlined.is_automated:
        logger.info({
            'status': 'dismiss',
            'action': 'send_automated_comm_sms',
            'streamlined_comm_id': streamlined_comm_id
        })
        return

    # get product list from class ProductLineCodes
    product_lines = getattr(ProductLineCodes, streamlined.product)()
    payments = []

    today_minus_21 = today - relativedelta(days=21)
    today_minus_7 = today - relativedelta(days=7)
    today_minus_5 = today - relativedelta(days=5)
    today_minus_1 = today - relativedelta(days=1)
    today_minus_2 = today - relativedelta(days=2)
    dpd_exclude = [
        today_minus_1,
        today_minus_5,
        today_minus_7,
        today_minus_21
    ]

    payments_exclude_pending_refinancing = \
        get_payments_refinancing_pending_by_dpd(dpd_exclude)

    query = Payment.objects.not_paid_active().filter(
        loan__application__customer__can_notify=True,
        loan__application__product_line__product_line_code__in=product_lines
    ).exclude(id__in=payments_exclude_pending_refinancing)

    if streamlined.dpd is not None:
        due_date = get_payment_due_date_by_delta(streamlined.dpd)
        payments = query.filter(ptp_date__isnull=True,
                                due_date=due_date)
    ptp_date = None
    if streamlined.ptp is not None:
        ptp_date = get_payment_due_date_by_delta(int(streamlined.ptp))
        payments = query.filter(ptp_date__isnull=False,
                                ptp_date=ptp_date)

    for payment in payments:
        if check_payment_is_blocked_comms(payment, 'sms'):
            continue
        product_line_code = payment.loan.application.product_line.product_line_code

        # only send sms reminder for oldest payment due, skip for the rest ones
        oldest_payment_due = get_oldest_payment_due(payment.loan)

        if oldest_payment_due and oldest_payment_due.id != payment.id:
            logger.warn({
                "action": "send_automated_comm_sms",
                "message": "skip sms for not oldest payment due",
                "data": {"payment_id": payment.id},
            })
            continue

        if ptp_date is not None:
            is_ptp_paid = is_ptp_payment_already_paid(payment.id, ptp_date)
            if is_ptp_paid:
                logger.info({
                    'action': 'send_automated_comm_sms',
                    'payment_id': payment.id,
                    'message': "ptp already paid",
                    'ptp_date': ptp_date
                })
                continue

        if product_line_code not in ProductLineCodes.grabfood():
            if streamlined.ptp is None:
                payment_number = payment.payment_number
                due_amount = payment.due_amount
                bank_name = payment.loan.julo_bank_name
                account_number = payment.loan.julo_bank_account_number
                first_name = payment.loan.application.first_name_only
                fullname = payment.loan.application.full_name_only
                bpk_ibu = payment.loan.application.bpk_ibu
                first_name_with_title_sms = payment.loan.application.first_name_with_title_short
                due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')
                available_context = {
                    'payment_number': payment_number,
                    'due_amount': display_rupiah(due_amount),
                    'due_date': due_date,
                    'bank_name': bank_name,
                    'account_number': account_number,
                    'firstname': first_name,
                    'fullname': fullname,
                    'bpk_ibu': bpk_ibu,
                    'first_name_with_title_sms': first_name_with_title_sms
                }

                available_context = get_extra_context(available_context, streamlined.message.parameter, payment)
            else:
                available_context = process_streamlined_comm_context_for_ptp(payment,
                                                 streamlined,
                                                 is_account_payment=False)

            message = process_streamlined_comm_without_filter(streamlined, available_context)
            send_automated_comm_sms_subtask.delay(payment.id, message, streamlined.template_code)

    slack_message = "*Template: {}* - send_automated_comm_sms (streamlined_id - {})".format(
        str(streamlined.template_code), str(streamlined_comm_id))
    send_slack_bot_message('alerts-comms-prod-sms', slack_message)


@task(queue='collection_high')
def send_automated_comm_sms_j1(streamlined_comm_id: int) -> None:
    """
    Processes account_payment expected to send as
    account-based product (J1, JTurbo) payment reminder

    Args:
        streamlined_comm_id (int): StreamlinedCommunication model id

    Returns:
        None
    """
    streamlined = StreamlinedCommunication.objects.get(pk=streamlined_comm_id)
    product = streamlined.product

    logger.info({
        'action': 'send_automated_comm_sms_j1',
        'streamlined_comm': streamlined,
        'template_code': streamlined.template_code,
        'message': 'Executing send_automated_comm_sms_j1',
    })

    today = timezone.localtime(timezone.now())
    # Retry mechanism logic
    flag_key = 'send_automated_comm_sms_j1:{}'.format(streamlined_comm_id)

    retry_flag_obj = CommsRetryFlag.objects.filter(flag_key=flag_key).first()
    # If the flag exists and is non-expired, exclude retry and return
    if retry_flag_obj and not retry_flag_obj.is_flag_expired:
        # alert if the current flag is Starting.
        if retry_flag_obj.flag_status == CommsRetryFlagStatus.START:
            slack_message = (
                "<!here> *Template: {}* - send_automated_comm_sms_j1 (streamlined_id - {}) "
                "- *START... [flag={}]*").format(
                str(streamlined.template_code), str(streamlined_comm_id), retry_flag_obj.flag_status
            )
            send_slack_bot_message('alerts-comms-prod-sms', slack_message)
        return
    if not retry_flag_obj:
        retry_flag_obj = CommsRetryFlag.objects.create(
            flag_key=flag_key,
            flag_status=CommsRetryFlagStatus.START,
            expires_at=today.replace(hour=20, minute=0, second=0, microsecond=0)
        )
        logger.info(
            {
                'action': 'send_automated_comm_sms_j1',
                'streamlined_comm': streamlined.template_code,
                'status': retry_flag_obj.flag_status,
                'message': 'RetryFlag obj created',
                'retry_flag': retry_flag_obj.id
            }
        )

    # If the flag has expired or is in START/ITERATION status, send a Slack message
    if retry_flag_obj.is_flag_expired and retry_flag_obj.is_valid_for_alert:
        slack_message = ("<!here> *Template: {}* - send_automated_comm_sms_j1 (streamlined_id - {}) "
                         "- *RETRYING... [flag={}]*").format(
            str(streamlined.template_code), str(streamlined_comm_id), retry_flag_obj.flag_status
        )
        send_slack_bot_message('alerts-comms-prod-sms', slack_message)

        logger.info(
            {
                'action': 'send_automated_comm_sms_j1',
                'streamlined_comm': streamlined.template_code,
                'status': retry_flag_obj.flag_status,
                'message': 'flag expired , attempting retry',
                'retry_flag': retry_flag_obj.id
            }
        )

    if 'autodebet' in streamlined.template_code:
        retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
        retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
        retry_flag_obj.save()
        logger.info({
            'streamlined_comm': streamlined,
            'template_code': streamlined.template_code,
            'message': 'Rejected streamlined communication contains autodebet template code.',
            'retry_flag': retry_flag_obj.id,
            'flag_status': retry_flag_obj.flag_status,
        })
        return

    date_of_day = today.date()
    # Get the start of the day (midnight)
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    # Get the end of the day (just before midnight)
    end_of_day = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    is_application = False
    if (streamlined.status_code and streamlined.status_code_id >=
        ApplicationStatusCodes.LOC_APPROVED) or \
            streamlined.dpd or streamlined.dpd_lower or streamlined.dpd_upper or \
            streamlined.dpd == 0:

        logger.info({
            'action': 'send_automated_comm_sms_j1',
            'streamlined_comm': streamlined,
            'template_code': streamlined.template_code,
            'message': 'Checking oldest_account_payment_ids is empty',
        })

        product_lines = getattr(ProductLineCodes, streamlined.product.lower())()
        account_payment_query_filter = {
            'account__customer__can_notify': True,
            'account__application__product_line__product_line_code__in': product_lines,
        }

        # Filter the account status lookup based on the product.
        # This logic is needed for J1 and JTurbo because a single account might have
        # JTurbo and J1 product line code.
        if streamlined.product.lower() == Product.SMS.JTURBO:
            account_payment_query_filter.update(
                account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER,
            )
        elif streamlined.product.lower() == Product.SMS.J1:
            account_payment_query_filter.update(
                account__account_lookup__workflow__name=WorkflowConst.JULO_ONE,
            )

        if streamlined.dpd is not None:
            due_date = get_payment_due_date_by_delta(streamlined.dpd)
            account_payment_query_filter.update(due_date=due_date)
        if streamlined.dpd_lower is not None:
            dpd_lower_date = get_payment_due_date_by_delta(streamlined.dpd_lower)
            account_payment_query_filter.update(due_date__lte=dpd_lower_date)
        if streamlined.dpd_upper is not None:
            dpd_upper_date = get_payment_due_date_by_delta(streamlined.dpd_upper)
            account_payment_query_filter.update(due_date__gte=dpd_upper_date)
        if streamlined.status_code:
            status_code_identifier = str(streamlined.status_code_id)[:1]
            if status_code_identifier == '1':
                # application code status
                account_ids = Application.objects.filter(
                    application_status=streamlined.status_code.status_code
                ).distinct('account_id').values_list('account_id', flat=True)
                account_payment_query_filter.update(account_id__in=account_ids)
            elif status_code_identifier == '2':
                # loan status code
                loan_account_ids = Loan.objects.filter(
                    account__application__product_line__product_line_code__in=product_lines,
                    loan_status_id=streamlined.status_code_id
                ).distinct('account_id').values_list('account_id', flat=True)
                account_payment_query_filter.update(account_id__in=list(loan_account_ids))
            elif status_code_identifier == '3':
                # payment status code
                account_payment_query_filter.update(status=streamlined.status_code_id)

        minimum_oldest_unpaid_account_payment_id = get_minimum_model_id(
            OldestUnpaidAccountPayment, date_of_day, 500000
        )

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM, is_active=True
        ).last()

        exclude_partner_end = dict()
        if feature_setting:
            partner_blacklist_config = feature_setting.parameters
            partner_config_end = []
            for partner_id in list(partner_blacklist_config.keys()):
                if partner_blacklist_config[partner_id] != 'end':
                    continue
                partner_config_end.append(partner_id)
                partner_blacklist_config.pop(partner_id)
            if partner_config_end:
                exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)

        query = (
            AccountPayment.objects.not_paid_active()
            .filter(**account_payment_query_filter)
            .extra(
                where=[
                    """EXISTS ( SELECT 1 FROM "oldest_unpaid_account_payment" U0
                    WHERE U0."oldest_unpaid_account_payment_id" >= %s
                    AND (U0."cdate" BETWEEN %s AND %s)
                    AND U0."dpd" = %s
                    AND U0."account_payment_id" = "account_payment"."account_payment_id")"""
                ],
                params=[
                    minimum_oldest_unpaid_account_payment_id,
                    start_of_day,
                    end_of_day,
                    streamlined.dpd,
                ],
            )
            .extra(
                where=[
                    """NOT ( "account"."status_code" IN %s
                    OR EXISTS ( SELECT 1 FROM "ptp" U0
                    WHERE U0."ptp_date" >= %s
                    AND U0."account_payment_id" = "account_payment"."account_payment_id"))"""
                ],
                params=[AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS, date_of_day],
            )
            .exclude(**exclude_partner_end)
        )

        # START experiment condition

        # LATE FEE EXPERIMENT
        query, _ = check_experiment_condition(
            MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            RedisKey.STREAMLINE_LATE_FEE_EXPERIMENT,
            streamlined,
            query,
            CardProperty.LATE_FEE_EARLIER_EXPERIMENT
        )

        if query is None:
            retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
            retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
            retry_flag_obj.save()
            return

        # SMS AFTER ROBOCALL EXPERIMENT
        query, _ = check_experiment_condition(
            MinisquadExperimentConstants.SMS_AFTER_ROBOCALL,
            RedisKey.STREAMLINE_SMS_AFTER_ROBOCALL_EXPERIMENT,
            streamlined,
            query,
            CardProperty.SMS_AFTER_ROBOCALL_EXPERIMENT,
            experiment_identifier='experiment_group_2'
        )

        if query is None:
            return
        # END experiment condition

    else:
        is_application = True
        product_lines = getattr(ProductLineCodes, streamlined.product.lower())()
        query = Application.objects.filter(
            product_line__product_line_code__in=product_lines,
        )
        if not streamlined.status_code:
            logger.error({
                'action': 'send_automated_comm_sms_subtask',
                'reason': 'cannot send to all application without status code',
                'streamlined_code': streamlined_comm_id
            })
            retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
            retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
            retry_flag_obj.save()
            return

        status_code_identifier = str(streamlined.status_code_id)[:1]
        if status_code_identifier == '1':
            # application code status
            query = query.filter(
                application_status_id=streamlined.status_code_id
            )
        elif status_code_identifier == '2':
            # TODO: Potentially redundant as status code >190 cannot reach here
            # loan status code
            application_ids = Loan.objects.filter(
                loan_status_id=streamlined.status_code_id,
                application__product_line__product_line_code__in=product_lines
            ).values_list('application_id', flat=True)
            query = query.filter(
                id__in=list(application_ids)
            )
        elif status_code_identifier == '3':
            # TODO: Potentially redundant as status code >190 cannot reach here
            # payment status code
            loan_ids = Payment.objects.filter(
                account_payment__isnull=False,
                payment_status_id=streamlined.status_code_id
            ).distinct('loan').values_list('loan_id', flat=True)
            application_ids = Loan.objects.filter(
                id__in=list(loan_ids)).values_list('application_id', flat=True)
            query = query.filter(id__in=list(application_ids))

    # Autodebet Streamline
    autodebet_streamlined = None
    account_use_autodebet = False
    if not is_application and streamlined.dpd and streamlined.dpd in autodebet_sms_dpds:
        autodebet_streamlined = StreamlinedCommunication.objects.filter(
            template_code='{}_sms_autodebet_dpd_{}'.format(product, streamlined.dpd),
            communication_platform=CommunicationPlatform.SMS,
            is_automated=True,
            dpd__isnull=False
        ).last()

    query = filter_streamlined_based_on_partner_selection(streamlined, query)
    # take out dpd -7 for experiment
    if streamlined.template_code == '{}_sms_dpd_-7'.format(product):
        experiment_setting_take_out_dpd_minus_7 = get_caller_experiment_setting(
            StreamlinedExperimentConst.SMS_MINUS_7_TAKE_OUT_EXPERIMENT)
        if experiment_setting_take_out_dpd_minus_7:
            query, experiment_account_payment_ids = \
                take_out_account_payment_for_experiment_dpd_minus_7(
                    query, experiment_setting_take_out_dpd_minus_7)
            write_data_to_experiment_group.delay(
                experiment_setting_take_out_dpd_minus_7.id,
                list(query.values_list('id', flat=True)), experiment_account_payment_ids)

    logger.info({
        'action': 'send_automated_comm_sms_j1',
        'streamlined_comm': streamlined,
        'template_code': streamlined.template_code,
        'message': 'Starting to iterate',
    })

    account_payment_processed = 0
    autodebet_account_ids = []

    # julo gold
    query = determine_julo_gold_for_streamlined_communication(streamlined.julo_gold_status, query)
    for application_or_account_payment in query.iterator():
        retry_flag_obj.flag_status = CommsRetryFlagStatus.ITERATION
        retry_flag_obj.expires_at = retry_flag_obj.calculate_expires_at(1)
        retry_flag_obj.save()

        logger_data = {
            'action': 'send_automated_comm_sms_j1',
            'application_or_account_payment': application_or_account_payment.pk,
            'is_application': is_application,
            'retry_flag': retry_flag_obj.id,
            'flag_status': retry_flag_obj.flag_status,
            'message': 'Query in loop iteration'
        }

        if not is_application:
            # validation comms block
            if check_account_payment_is_blocked_comms(application_or_account_payment, 'sms'):
                logger.info({
                    **logger_data,
                    'message': 'customer got comms block for sms'
                })
                continue

            sent_sms = SmsHistory.objects.filter(
                cdate__date=date_of_day,
                template_code__in=[
                    streamlined.template_code,
                    '{}_sms_autodebet_dpd_{}'.format(product, streamlined.dpd)
                ],
                account_payment=application_or_account_payment,
            ).last()

            if sent_sms:
                logger.info({
                    **logger_data,
                    'last_sent_sms': sent_sms.id,
                    'message': 'Ignore sending due to existing sms history.'
                })
                continue

        logger.info({
            **logger_data,
            'message': 'Processing data for SMS sending.'
        })

        current_streamlined = streamlined
        if autodebet_streamlined:
            autodebet_account = get_existing_autodebet_account(
                application_or_account_payment.account)
            if autodebet_account and autodebet_account.is_use_autodebet:
                account_use_autodebet = True
                current_streamlined = autodebet_streamlined

                autodebet_account_ids.append(application_or_account_payment.account.id)
                if is_experiment_group_autodebet(application_or_account_payment.account):
                    logger.info(
                        {**logger_data, 'message': 'Autodebet SMS excluded for experiment.'}
                    )
                    continue

        processed_message = process_sms_message_j1(
            current_streamlined.message.message_content, application_or_account_payment,
            is_have_account_payment=not is_application
        )

        logger.info({
            **logger_data,
            'account_use_autodebet': account_use_autodebet,
            'streamlined_comm': current_streamlined,
            'template_code': current_streamlined.template_code,
            'message': 'Processed SMS message.'
        })

        send_automated_comm_sms_j1_subtask.delay(
            application_or_account_payment.id, processed_message, current_streamlined.template_code,
            current_streamlined.type, is_application=is_application
        )
        account_payment_processed += 1

    # Experiment Autodebet Data Storing
    store_autodebet_streamline_experiment.delay(autodebet_account_ids)

    retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
    retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
    retry_flag_obj.save()
    logger.info({
        'action': 'send_automated_comm_sms_j1',
        'streamlined_comm': streamlined,
        'template_code': streamlined.template_code,
        'message': 'Iteration complete. Processed {} account payment'.format(
            account_payment_processed),
        'retry_flag': retry_flag_obj.id,
        'flag_status': retry_flag_obj.flag_status,
    })

    slack_message = "*Template: {}* - send_automated_comm_sms_j1 (streamlined_id - {})".format(
        str(streamlined.template_code), str(streamlined_comm_id))
    send_slack_bot_message('alerts-comms-prod-sms', slack_message)


@task(queue='collection_high')
def send_automated_comm_sms_subtask(payment_id, message, template_code):
    """
    Trigger the send SMS for non-account-based product (STL,MTL,Axiata,etc)
    For PTP case, please see: send_automated_comm_sms_ptp_j1()

    Args:
        payment_id (int): The Payment primary key.
        message (str): The SMS text content.
        template_code (str): The template code text.

    Returns:
        None
    """
    julo_sms_client = get_julo_sms_client()
    payment = Payment.objects.get_or_none(pk=payment_id)
    category = ""
    try:
        txt_msg, response, template = julo_sms_client.sms_automated_comm(payment, message, template_code)
        is_success = True
    except Exception as e:
        is_success = False
        logger.error({'reason': 'SMS not sent',
                      'action': 'send_automated_comm_sms_subtask',
                      'payment_id': payment_id,
                      'Due date': payment.due_date,
                      'product_line_code': payment.loan.application.product_line.product_line_code})
    if is_success:
        if response['status'] != '0':
            raise SmsNotSent({
                'send_status': response['status'],
                'payment_id': payment.id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': 'sms_automated_comm',
                'error_text': response.get('error-text'),
            })
        application = payment.loan.application
        customer = application.customer
        if "ptp" in template_code:
            category = "PTP"
        sms = create_sms_history(response=response,
                                 customer=customer,
                                 application=application,
                                 payment=payment,
                                 template_code=template,
                                 message_content=txt_msg,
                                 to_mobile_phone=format_e164_indo_phone_number(response['to']),
                                 phone_number_type='mobile_phone_1',
                                 category=category
                                 )

        logger.info({
            'message': 'SMS history created.',
            'payment_id': payment.id,
            'sms_history_id': sms.id,
            'message_id': sms.message_id
        })


@task(queue='collection_high')
def send_automated_comm_sms_j1_subtask(
        application_or_account_payment_id, processed_message, template_code, sms_type,
        is_application=False
):
    """
    Trigger the send SMS for account-based product (J1/JTurbo)
    For PTP case, please see: send_automated_comm_sms_ptp_j1_subtask()

    Args:
        application_or_account_payment_id (int): Either application id or account_payment id.
        processed_message (str): the sms text content.
        template_code (str): the template code text
        sms_type (str): the sms type, usually depends on the streamlined_communiation.type.
        is_application (bool):
            Flag to know if application_or_account_payment_id arg is an application

    Returns:
        None
    """
    julo_sms_client = get_julo_sms_client()
    omnichannel_exclusion_request = get_omnichannel_comms_block_active(
        OmnichannelIntegrationSetting.CommsType.SMS
    )
    if not is_application:
        application_or_account_payment = AccountPayment.objects.get(
            pk=application_or_account_payment_id
        )

        # omnichannel customer exclusion
        if (
            omnichannel_exclusion_request.is_excluded
            and is_account_payment_owned_by_omnichannel_customer(
                exclusion_req=omnichannel_exclusion_request,
                account_payment=application_or_account_payment,
            )
        ):
            return
    else:
        application_or_account_payment = Application.objects.get(
            pk=application_or_account_payment_id
        )

        # omnichannel customer exclusion
        if (
            is_application
            and omnichannel_exclusion_request.is_excluded
            and is_application_owned_by_omnichannel_customer(
                application=application_or_account_payment,
                exclusion_req=omnichannel_exclusion_request,
            )
        ):
            return
    try:
        txt_msg, response, template = julo_sms_client.sms_automated_comm_j1(
            application_or_account_payment,
            processed_message, template_code, sms_type, is_application=is_application
        )
        is_success = True
    except Exception as e:
        is_success = False
        logger.exception({
            'reason': 'SMS not sent',
            'action': 'send_automated_comm_sms_j1_subtask',
            'application_or_account_payment': application_or_account_payment_id
        })
        capture_exception()

    if is_success:
        if response['status'] != '0' and response['julo_sms_vendor'] != 'infobip':
            raise SmsNotSent({
                'send_status': response['status'],
                'application_or_account_payment_id': application_or_account_payment_id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': 'sms_automated_comm_j1',
                'error_text': response.get('error-text'),
            })
        if not is_application:
            account = application_or_account_payment.account
            application = account.application_set.filter(
                workflow_id=account.account_lookup.workflow_id,
            ).last()
        else:
            application = application_or_account_payment
        customer = application.customer
        sms_history_params = dict(
            response=response,
            customer=customer,
            application=application,
            template_code=template,
            message_content=txt_msg,
            to_mobile_phone=format_e164_indo_phone_number(response['to']),
            phone_number_type='mobile_phone_1',
        )
        if not is_application:
            sms_history_params.update(account_payment=application_or_account_payment)

        sms = create_sms_history(**sms_history_params)

        logger.info({
            'message': 'SMS history created.',
            'application_or_account_payment_id': application_or_account_payment_id,
            'is_application': is_application,
            'sms_history_id': sms.id,
            'message_id': sms.message_id
        })


@task(name='send_email_osp_recovery')
def send_email_osp_recovery():
    today = timezone.localtime(timezone.now()).date()
    if today > (datetime.strptime('2020-04-14', '%Y-%m-%d')).date():
        return None
    change_banner_date = (datetime.strptime('2020-04-10', '%Y-%m-%d')).date()
    banner = 'banner_osp_recovery_1.png'
    if today >= change_banner_date:
        banner = 'banner_osp_recovery_2.png'
    data_osp_recovery_campaign = WaivePromo.objects.get_queryset() \
        .eligible_loans('OSP_RECOVERY_APR_2020').values_list('loan', flat=True)
    for loan_id in data_osp_recovery_campaign:
        send_email_osp_recovery_subtask.delay(loan_id, banner)


@task(name='send_email_osp_recovery_subtask')
def send_email_osp_recovery_subtask(loan_id, banner):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None

    application = loan.application
    customer = application.customer
    payments = loan.payment_set.all().order_by('payment_number')
    payment_sum = loan.payment_set.aggregate(
        total_current_late_fee=Sum('late_fee_amount'),
        total_interest=Sum('installment_interest'),
        total_installment_principal=Sum('installment_principal'),
        total_due_amount=Sum('due_amount'),
        remaining_interest=Sum('installment_interest') - Sum('paid_interest'),
    )
    total_current_late_fee = payment_sum['total_current_late_fee']
    total_interest = payment_sum['total_interest']
    total_installment_amount = payment_sum['total_installment_principal'] + total_interest
    total_due_amount = payment_sum['total_due_amount']
    total_due_amount_without_late_fee = total_due_amount - total_current_late_fee
    list_table = []
    banner_image_path = settings.EMAIL_STATIC_FILE_PATH + banner
    for payment_table in payments:
        dpd = str(payment_table.due_late_days)
        if payment_table.payment_status_id in PaymentStatusCodes.paid_status_codes():
            is_paid = 'Ya'
            dpd = '-'
        else:
            is_paid = 'Tidak'
        if payment_table.due_late_days <= 0 and is_paid != 'Ya':
            dpd = 'NA'
            is_paid = 'Not Due'


        list_table.append(
            dict(
                payment_number=payment_table.payment_number,
                installment_principal=display_rupiah(payment_table.original_due_amount),
                due_date=format_date(payment_table.due_date, 'dd-MMMM-YYYY', locale='id_ID'),
                dpd=dpd,
                is_paid=is_paid,
                late_fee_amount=display_rupiah(payment_table.late_fee_amount),
                paid_amount=display_rupiah(payment_table.paid_amount),
                due_amount=display_rupiah(payment_table.due_amount)
            )
        )

    context = dict(
        cashback_40_percent=display_rupiah((0.4 * payment_sum['remaining_interest'])),
        fullname_with_title=loan.application.fullname_with_title,
        total_installment_amount=display_rupiah(total_installment_amount),
        total_current_late_fee=display_rupiah(total_current_late_fee),
        total_due_amount=display_rupiah(total_due_amount),
        total_due_amount_without_late_fee=display_rupiah(total_due_amount_without_late_fee),
        table_list=list_table,
        base_url=settings.BASE_URL,
        banner_image=banner_image_path
    )
    julo_email_client = get_julo_email_client()
    try:
        status, headers, subject, msg = julo_email_client.email_osp_recovery(
            context, email_to=customer.email)
        template_code = "email_OSP_Recovery_Apr2020"

        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=customer.email,
            subject=subject,
            application=application,
            message_content=msg,
            template_code=template_code,
            status=status
        )

        logger.info({
            "action": "email_OSP_Recovery_Apr2020",
            "customer_id": customer.id,
            "promo_type": template_code
        })
    except Exception as e:
        logger.error({
            "action": "email_OSP_Recovery_Apr2020",
            "message": str(e)
        })

@task(name='send_sms_osp_recovery')
def send_sms_osp_recovery():
    today = timezone.localtime(timezone.now()).date()
    if today.year > 2020:
        return None

    data_osp_recovery_campaign = WaivePromo.objects.get_queryset() \
        .eligible_loans('OSP_RECOVERY_APR_2020').values_list('loan', flat=True)
    for loan_id in data_osp_recovery_campaign:
        send_sms_osp_recovery_sub_task.delay(loan_id)

@task(name="send_sms_osp_recovery_sub_task")
def send_sms_osp_recovery_sub_task(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None
    application = loan.application
    today = timezone.localtime(timezone.now()).date()
    is_change_template = today == (datetime.strptime('2020-04-11', '%Y-%m-%d')).date()
    get_julo_sms = get_julo_sms_client()
    message, response = get_julo_sms.sms_osp_recovery_promo(application.mobile_phone_1,
                                                            is_change_template=is_change_template)

    if response['status'] != '0':
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "application_id": application.id,
                "message": message,
            }
        )

    sms = create_sms_history(response=response,
                             application=application,
                             to_mobile_phone=format_e164_indo_phone_number(response["to"]),
                             phone_number_type="mobile_phone_1",
                             customer=application.customer,
                             template_code='mtl_sms_OSP_Recovery_Apr2020',
                             message_content=message
                             )
    logger.info(
        {
            "status": "sms_created",
            "sms_history_id": sms.id,
            "message_id": sms.message_id,
        }
    )

@task(name='send_sms_repayment_awareness_campaign')
def send_sms_repayment_awareness_campaign():
    today = timezone.localtime(timezone.now()).date()
    if today > (datetime.strptime('2020-05-08', '%Y-%m-%d')).date():
        return None

    logger.info(
        {
            "action": "send_sms_repayment_awareness_campaign",
            "date": today,
        }
    )
    # dpd 1 - 40
    dpd_list = list(range(1, 41))
    due_date_list = []
    for dpd in dpd_list:
        due_date_list.append(today - relativedelta(days=dpd))

    selected_product_line = ProductLineCodes.mtl() + ProductLineCodes.stl()
    data_repayment_awareness_campaign = Payment.objects.not_paid_active().filter(
        loan__application__customer__can_notify=True, ptp_date__isnull=True,
        due_date__in=due_date_list,
        loan__application__product_line__product_line_code__in=selected_product_line
    )
    for payment in data_repayment_awareness_campaign:
        send_sms_repayment_awareness_campaign_sub_task.delay(payment.id, today.day)

@task(name="send_sms_repayment_awareness_campaign_sub_task")
def send_sms_repayment_awareness_campaign_sub_task(payment_id, day):
    payment = Payment.objects.get_or_none(pk=payment_id)
    if not payment:
        return None
    application = payment.loan.application
    get_julo_sms = get_julo_sms_client()
    message, response = get_julo_sms.sms_repayment_awareness_campaign(
        firstname_with_short_title=application.first_name_with_title_short,
        day=day,
        mobile_phone=application.mobile_phone_1,
    )
    if response['status'] != '0':
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "application_id": application.id,
                "message": message,
            }
        )

    sms = create_sms_history(response=response,
                             application=application,
                             payment_id=payment_id,
                             to_mobile_phone=format_e164_indo_phone_number(response["to"]),
                             phone_number_type="mobile_phone_1",
                             customer=application.customer,
                             template_code='mtlstl_sms_cara_membayar_2020',
                             message_content=message
                             )
    logger.info(
        {
            "status": "sms_created",
            "sms_history_id": sms.id,
            "message_id": sms.message_id,
        }
    )


@task(name='get_lebaran_2020_loan_execute')
def get_lebaran_2020_loan_execute(loan_id, date, tnc_url="default",
                                  is_partner=False, is_sms=False,
                                  is_email=False, is_pn=False):
    loan = Loan.objects.select_related('application').get(id=loan_id)
    payments = loan.payment_set.filter(payment_status__gte=PaymentStatusCodes.PAYMENT_NOT_DUE,
                                       payment_status__lte=PaymentStatusCodes.PAID_LATE,
                                       paid_date__range=["2020-04-24", "2020-05-10"]).count()
    if payments < 2:
        payment = loan.payment_set.last()
        application = loan.application
        if application.product_line_id in ProductLineCodes.mtl():
            if not check_risky_customer(application.id):
                if is_email:
                    send_lebaran_2020_email_subtask(application=application,
                                                    payment=payment, tnc_url=tnc_url,
                                                    date=date, is_partner=is_partner)
                if is_pn:
                    send_lebaran_2020_pn_subtask(application=application,
                                                 payment=payment, date=date,
                                                 is_partner=is_partner)
                if is_sms:
                    send_lebaran_2020_sms_subtask(application=application,
                                                  payment=payment, date=date,
                                                  is_partner=is_partner)
        else:
            if is_email:
                send_lebaran_2020_email_subtask(application=application,
                                                payment=payment, tnc_url=tnc_url,
                                                date=date, is_partner=is_partner)
            if is_pn:
                send_lebaran_2020_pn_subtask(application=application,
                                             payment=payment, date=date,
                                             is_partner=is_partner)
            if is_sms:
                send_lebaran_2020_sms_subtask(application=application,
                                              payment=payment, date=date,
                                              is_partner=is_partner)


@task(name='send_lebaran_campaign_2020_email')
def send_lebaran_campaign_2020_email():
    date = timezone.localtime(timezone.now()).date()
    if date.year != 2020:
        return

    lebaran_2020_url = "https://julo.co.id/promo-lebaran-2020-terms-and-conditions.html"
    lebaran_2020_short_url, _ = ShortenedUrl.objects.get_or_create(short_url='GebyarLebaran20',
                                                                   full_url=lebaran_2020_url)
    if lebaran_2020_short_url is None:
        return
    lebaran20_shortened_url = settings.URL_SHORTENER_BASE + lebaran_2020_short_url.short_url

    mtl_loan_ids = get_lebaran_2020_users(is_partner=False, is_sms=False)
    for mtl_loan_id in mtl_loan_ids:
        loan_id = mtl_loan_id['id']
        get_lebaran_2020_loan_execute.delay(loan_id, date=date,
                                            tnc_url=lebaran20_shortened_url,
                                            is_partner=False,
                                            is_email=True)

    partner_loan_ids = get_lebaran_2020_users(is_partner=True, is_sms=False)
    for partner_loan_id in partner_loan_ids:
        loan_id = partner_loan_id['id']
        # since bitly has rate limiting of 5 concurrent calls the task for partner loans
        # is sent to the lower queue running fewer workers
        get_lebaran_2020_loan_execute.apply_async(
            args=(loan_id, date),
            kwargs=dict(tnc_url=lebaran20_shortened_url, is_partner=True, is_email=True),
            queue='lower')


@task(name='send_lebaran_campaign_2020_pn')
def send_lebaran_campaign_2020_pn():
    date = timezone.localtime(timezone.now()).date()
    if date.year != 2020:
        return
    mtl_loan_ids = get_lebaran_2020_users(is_partner=False, is_sms=False)
    for mtl_loan_id in mtl_loan_ids:
        loan_id = mtl_loan_id['id']
        get_lebaran_2020_loan_execute.delay(loan_id, date=date, is_partner=False, is_pn=True)


@task(name='send_lebaran_campaign_2020_sms')
def send_lebaran_campaign_2020_sms():
    date = timezone.localtime(timezone.now()).date()
    if date.year != 2020:
        return

    mtl_loan_ids = get_lebaran_2020_users(is_partner=False, is_sms=True)
    for mtl_loan_id in mtl_loan_ids:
        loan_id = mtl_loan_id['id']
        get_lebaran_2020_loan_execute.delay(loan_id, date=date,
                                            is_partner=False, is_sms=True)

    partner_loan_ids = get_lebaran_2020_users(is_partner=True, is_sms=True)
    for partner_loan_id in partner_loan_ids:
        loan_id = partner_loan_id['id']
        # since bitly has rate limiting of 5 concurrent calls the task for partner loans
        # is sent to the lower queue running fewer workers
        get_lebaran_2020_loan_execute.apply_async(
            args=(loan_id, date),
            kwargs=dict(is_partner=True, is_sms=True),
            queue='lower')


@task(queue='collection_high')
def send_automated_comm_pn(streamlined_comm_id):
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    if not streamlined:
        return

    if not streamlined.is_automated:
        logger.info({
            'status': 'dismiss',
            'action': 'send_automated_comm_pn',
            'streamlined_comm_id': streamlined_comm_id
        })
        return

    product_lines = getattr(ProductLineCodes, streamlined.product)()
    query = Payment.objects.not_paid_active().filter(
        loan__application__customer__can_notify=True,
        loan__application__product_line__product_line_code__in=product_lines
    ).exclude(account_payment__account__status_id=AccountConstant.STATUS_CODE.sold_off)
    payments = []
    if streamlined.dpd is not None:
        due_date = get_payment_due_date_by_delta(streamlined.dpd)
        payments = query.filter(ptp_date__isnull=True,
                                due_date=due_date)
    ptp_date = None
    if streamlined.ptp is not None:
        # handle for prevent send double PN if have PTP and DPD
        ptp_date = get_payment_due_date_by_delta(int(streamlined.ptp))
        payments = query.filter(ptp_date__isnull=False,
                                ptp_date=ptp_date)
    buttons = get_pn_action_buttons(streamlined.id)
    for payment in payments:
        if check_payment_is_blocked_comms(payment, 'pn'):
            continue
        # handle payment base on loan level
        oldest_payment_due = get_oldest_payment_due(payment.loan)
        if oldest_payment_due.id != payment.id:
            logger.warn(
                {
                    "action": "send_automated_comm_PN",
                    "message": "skip PN for not oldest payment due",
                    "data": {"payment_id": payment.id},
                }
            )
            continue
        device = payment.loan.application.device
        # credgenics comss block here
        if is_comms_block_active(CommsType.PN) and is_account_payment_owned_by_credgenics_customer(
            account_payment_id=payment.account_payment_id
        ):
            continue
        if have_pn_device(device):
            if ptp_date is not None:
                is_ptp_paid = is_ptp_payment_already_paid(payment.id, ptp_date)
                if is_ptp_paid:
                    logger.info(
                        {
                            'status': 'send_automated_comm_sms',
                            'payment_id': payment.id,
                            'message': "ptp already paid",
                            'ptp_date': ptp_date,
                        }
                    )
                    continue
                available_context = process_streamlined_comm_context_for_ptp(payment,
                                                                             streamlined,
                                                                             is_account_payment=False)
                message = process_streamlined_comm_without_filter(streamlined, available_context)
                heading_title = process_streamlined_comm_email_subject(streamlined.heading_title,
                                                                       available_context)
            else:
                message, heading_title = process_streamlined_comm_context_base_on_model_and_parameter(
                    streamlined, payment, is_with_header=True
                )
            image = Image.objects.get_or_none(
                image_source=streamlined.id, image_type=ImageType.STREAMLINED_PN, image_status=Image.CURRENT
            )

            send_automated_comm_pn_subtask.delay(
                payment.id, message, heading_title, streamlined.template_code, buttons, image
            )
        else:
            logger.warn({
                "action": "send_automated_comm_PN",
                "message": "skip PN have_pn_device False",
                "data": {"payment_id": payment.id},
            })
            continue
    slack_message = "*Template: {}* - send_automated_comm_pn (streamlined_id - {})".format(
        str(streamlined.template_code), str(streamlined_comm_id))
    send_slack_bot_message('alerts-comms-prod-pn', slack_message)

@task(queue='collection_high')
def send_automated_comm_pn_subtask(payment_id, message, heading_title, template_code, buttons, image=None):
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment:
        julo_pn_client = get_julo_pn_client()
        julo_pn_client.automated_payment_reminder(
            payment, message, heading_title, template_code, buttons, image)
    else:
        logger.warn({
            "action": "send_automated_comm_PN",
            "message": "skip PN because payment is None",
            "data": {"payment_id": payment_id},
        })


@task(name='record_fdc_risky_history')
def record_fdc_risky_history(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        return
    loan = application.loan
    if not loan.is_active:
        return
    unpaid_payments = loan.payment_set.by_loan(loan).not_paid().order_by('payment_number')
    FDCRiskyHistory.objects.create(
        application_id=application.id,
        loan_id=loan.id,
        dpd=unpaid_payments[0].due_late_days if unpaid_payments else None,
        is_fdc_risky=application.is_fdc_risky,
    )


@task(name='create_accounting_cut_off_date_monthly_entry')
def create_accounting_cut_off_date_monthly_entry():
    today = timezone.localtime(timezone.now())
    accounting_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.ACCOUNTING_CUT_OFF_DATE, is_active=True)
    if not accounting_feature:
        return
    accounting_period = (today - timedelta(days=1)).replace(day=1).date()
    cut_off_date = today.replace(day=int(
        accounting_feature.parameters['cut_off_date'])).date()
    AccountingCutOffDate.objects.create(
        accounting_period=accounting_period,
        cut_off_date=cut_off_date,
        cut_off_date_last_change_ts=accounting_feature.udate
    )


@task(queue='collection_normal')
def reset_collection_called_status_for_unpaid_account_payment():
    account_payment_active = AccountPayment.objects.normal()
    to_be_reset_account_payments = account_payment_active.not_paid_active().filter(is_collection_called=True)
    for account_payment in to_be_reset_account_payments:
        account_payment.update_safely(is_collection_called=False)


@task(queue='moengage_high')
def send_automated_comm_sms_for_unsent_moengage(streamlined_comm_id):
    today = timezone.localtime(timezone.now())
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    if 'autodebet' in streamlined.template_code:
        return

    due_date = get_payment_due_date_by_delta(streamlined.dpd)
    template_codes = [streamlined.template_code]
    # These template codes are streamlined comms only
    if streamlined.dpd in autodebet_sms_dpds:
        template_codes.append('j1_sms_autodebet_dpd_{}'.format(streamlined.dpd))

    # TODO: need to update the query if apply send sms reminder via moengage
    sent_account_payments_ids = SmsHistory.objects.filter(
        cdate__gte=start_of_day, cdate__lt=end_of_day).filter(
            reduce(or_, [Q(template_code__contains=template_code) for template_code in template_codes])
    ).values_list('account_payment_id', flat=True)

    unsent_account_payments_ids = OldestUnpaidAccountPayment.objects.filter(
        cdate__gte=start_of_day, cdate__lt=end_of_day,
        dpd=streamlined.dpd).exclude(account_payment_id__in=sent_account_payments_ids)\
            .values_list('account_payment_id', flat=True)

    if not unsent_account_payments_ids:
        logger.info(
            {
                'action': 'send_automated_comm_sms_for_unsent_moengage',
                'message': 'all data is sent successfully',
                'template_code': template_codes,
                'date': str(today.date()),
            }
        )

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM, is_active=True
    ).last()

    exclude_partner_end = dict()
    if feature_setting:
        partner_blacklist_config = feature_setting.parameters
        partner_config_end = []
        for partner_id in list(partner_blacklist_config.keys()):
            if partner_blacklist_config[partner_id] != 'end':
                continue
            partner_config_end.append(partner_id)
            partner_blacklist_config.pop(partner_id)
        if partner_config_end:
            exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)

    account_payments = (
        AccountPayment.objects.filter(id__in=unsent_account_payments_ids)
        .filter(account__account_lookup__workflow__name=WorkflowConst.JULO_ONE)
        .exclude(
            status__in=(
                PaymentStatusCodes.PAID_ON_TIME,
                PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                PaymentStatusCodes.PAID_LATE,
            )
        )
        .exclude(**exclude_partner_end)
    )

    # SMS AFTER ROBOCALL EXPERIMENT
    account_payments, _ = check_experiment_condition(
        MinisquadExperimentConstants.SMS_AFTER_ROBOCALL,
        RedisKey.STREAMLINE_SMS_AFTER_ROBOCALL_EXPERIMENT,
        streamlined,
        account_payments,
        CardProperty.SMS_AFTER_ROBOCALL_EXPERIMENT,
        experiment_identifier='experiment_group_2')

    autodebet_account_ids = []
    for account_payment in account_payments:
        if check_account_payment_is_blocked_comms(account_payment, 'sms'):
            continue

        customer = account_payment.account.customer
        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        available_context = user_attributes['attributes']
        current_streamlined_comm = streamlined

        # handle for autodebet customer
        if streamlined.dpd < 0:
            autodebet_account = get_existing_autodebet_account(account_payment.account)
            if autodebet_account and autodebet_account.is_use_autodebet:
                if streamlined.dpd not in AutoDebetComms.SMS_DPDS:
                    continue
                autodebet_streamlined = StreamlinedCommunication.objects.filter(
                    template_code='j1_sms_autodebet_dpd_{}'.format(streamlined.dpd),
                    communication_platform=CommunicationPlatform.SMS,
                    time_sent__isnull=False,
                    is_automated=True,
                    extra_conditions=UNSENT_MOENGAGE,
                    dpd__isnull=False
                ).last()
                if not autodebet_streamlined:
                    logger.warning('autodebet streamlined communication is not found, '
                                   'dpd={}'.format(streamlined.dpd))
                    continue
                autodebet_account_ids.append(account_payment.account.id)
                if is_experiment_group_autodebet(account_payment.account):
                    continue
                current_streamlined_comm = autodebet_streamlined

        message = process_streamlined_comm_without_filter(
            current_streamlined_comm, available_context)
        send_automated_comm_sms_subtask_for_unsent_moengage.delay(
            account_payment.id, message, current_streamlined_comm.template_code
        )

    # Experiment Autodebet Data Storing
    store_autodebet_streamline_experiment.delay(autodebet_account_ids)

    slack_message = (
        "*Template: {}* - send_automated_comm_sms_for_unsent_moengage (streamlined_id - {})".format(
            str(streamlined.template_code), str(streamlined_comm_id)
        )
    )
    send_slack_bot_message('alerts-comms-prod-sms', slack_message)


@task(queue='moengage_high')
def send_automated_comm_sms_subtask_for_unsent_moengage(account_payment_id, message, template_code):
    julo_sms_client = get_julo_sms_client()
    account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
    try:
        txt_msg, response, template = julo_sms_client.sms_automated_comm_unsent_moengage(
            account_payment, message, template_code)
        is_success = True
    except Exception as e:
        is_success = False
        logger.error({'reason': 'SMS not sent',
                      'action': 'send_automated_comm_sms_subtask_for_unsent_moengage',
                      'account_payment_id': account_payment_id})
    if is_success:
        if response['status'] != '0':
            raise SmsNotSent({
                'send_status': response['status'],
                'account_payment_id': account_payment_id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': 'sms_automated_comm',
                'error_text': response.get('error-text'),
            })

        account = account_payment.account
        application = account.application_set.last()
        customer = account.customer
        sms = create_sms_history(
            response=response,
            customer=customer,
            application=application,
            account_payment=account_payment,
            template_code=template,
            message_content=txt_msg,
            to_mobile_phone=format_e164_indo_phone_number(response['to']),
            phone_number_type='mobile_phone_1',
            source=INHOUSE
        )

        logger.info({
            'status': 'sms_created',
            'account_payment_id': account_payment.id,
            'sms_history_id': sms.id,
            'message_id': sms.message_id
        })


@task(queue='collection_high')
def send_automated_comm_email_for_unsent_moengage(streamlined_comm_id):
    from juloserver.email_delivery.tasks import (
        send_email_payment_reminder_for_unsent_moengage,
    )

    logger_data = {
        'action': 'send_automated_comm_email_for_unsent_moengage',
    }

    process_name = RedisKey.EMAIL_UNSENT_MOENGAGE.format(streamlined_comm_id)
    redis_client = get_redis_client()
    cache_process = redis_client.get(process_name)
    if not cache_process:
        redis_client.set(process_name, CeleryTaskLocker.STATUS['START'], CeleryTaskLocker.TIMEOUT)
    else:
        if cache_process != CeleryTaskLocker.STATUS['DONE']:
            logger.info(
                {
                    'message': 'Task process return early due to similar task still running.',
                    **logger_data,
                }
            )
            return
        else:
            redis_client.set(
                process_name, CeleryTaskLocker.STATUS['START'], CeleryTaskLocker.TIMEOUT
            )

    today = timezone.localtime(timezone.now())
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    if 'autodebet' in streamlined.template_code:
        return

    filter_template_codes = (streamlined.template_code, streamlined.moengage_template_code,
                             '{0}_email_autodebet_dpd_{1}'.format(streamlined.product, streamlined.dpd))

    sent_customer_ids = EmailHistory.objects.filter(
        cdate__gte=start_of_day, cdate__lt=end_of_day).filter(
            reduce(or_, [Q(template_code__contains=q) for q in filter_template_codes])
    ).values_list('customer_id', flat=True)

    unsent_account_payments_ids = OldestUnpaidAccountPayment.objects.filter(
        cdate__gte=start_of_day, cdate__lt=end_of_day,
        dpd=streamlined.dpd
    ).exclude(
        account_payment__account__customer_id__in=sent_customer_ids
    ).values_list('account_payment_id', flat=True)

    if not unsent_account_payments_ids:
        logger.info(
            {
                'message': 'all data is sent successfully',
                'template_code': filter_template_codes,
                'date': str(today.date()),
                **logger_data,
            }
        )
        return

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM, is_active=True
    ).last()

    exclude_partner_end = dict()
    if feature_setting:
        partner_blacklist_config = feature_setting.parameters
        partner_config_end = []
        for partner_id in list(partner_blacklist_config.keys()):
            if partner_blacklist_config[partner_id] != 'end':
                continue
            partner_config_end.append(partner_id)
            partner_blacklist_config.pop(partner_id)
        if partner_config_end:
            exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)

    account_payments = (
        AccountPayment.objects.filter(id__in=unsent_account_payments_ids)
        .exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
        .exclude(
            status__in=(
                PaymentStatusCodes.PAID_ON_TIME,
                PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                PaymentStatusCodes.PAID_LATE,
            )
        )
        .exclude(**exclude_partner_end)
    )

    if streamlined.product.lower() == Product.EMAIL.JTURBO:
        account_payments = account_payments.filter(
            account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
            )
    elif streamlined.product.lower() == Product.EMAIL.J1:
        account_payments = account_payments.filter(
            account__account_lookup__workflow__name=WorkflowConst.JULO_ONE
            )
    else:
        raise Exception('The streamlined product {} do not match with email product J1 and Jturbo'.
                        format(streamlined.product))

    # START experiment condition

    # LATE FEE EXPERIMENT
    query, condition = check_experiment_condition(
        MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
        RedisKey.STREAMLINE_LATE_FEE_EXPERIMENT,
        streamlined,
        account_payments,
        UNSENT_MOENGAGE_EXPERIMENT
    )

    if query is None:
        if 'reminder_in' in streamlined.moengage_template_code:
            return
    else:
        if condition == 'exists' and 'reminder_in' in streamlined.moengage_template_code:
            account_payments = query
        elif condition == 'not exists':
            account_payments = query

    # END experiment condition

    logger.info(
        {
            'streamlined_comm': streamlined.template_code,
            'unsent_account_payments': unsent_account_payments_ids,
            **logger_data,
        }
    )
    redis_client.set(process_name, CeleryTaskLocker.STATUS['IN_PROGRESS'], CeleryTaskLocker.TIMEOUT)
    account_payments = determine_julo_gold_for_streamlined_communication(
        streamlined.julo_gold_status, account_payments
    )
    for account_payment in account_payments:
        if check_account_payment_is_blocked_comms(account_payment, 'email'):
            logger.info(
                {
                    'streamlined_comm': streamlined.template_code,
                    'account_payment_id': account_payment.id,
                    'message': 'account_payment_is_blocked_comms true',
                    **logger_data,
                }
            )
            continue
        # ignore send payment reminder email for Bukuwarung customer if dpd is not valid
        if streamlined.dpd in (-4, -2):
            product_line_code = account_payment.account.application_set.last().product_line_code
            if product_line_code == ProductLineCodes.BUKUWARUNG:
                continue

        current_streamlined_comm_id = streamlined_comm_id
        if streamlined.dpd < 0:
            autodebet_account = get_existing_autodebet_account(account_payment.account)
            if autodebet_account and autodebet_account.is_use_autodebet:
                if streamlined.dpd not in AutoDebetComms.EMAIL_DPDS:
                    continue
                autodebet_streamlined = StreamlinedCommunication.objects.filter(
                    template_code='{}_email_autodebet_dpd_{}'.format(streamlined.product, streamlined.dpd),
                    communication_platform=CommunicationPlatform.EMAIL,
                    time_sent__isnull=False,
                    is_automated=True,
                    extra_conditions=UNSENT_MOENGAGE,
                    dpd__isnull=False
                ).last()
                if not autodebet_streamlined:
                    logger.warning(
                        {
                            'message': 'streamlined communication is not found, '
                            'dpd={}, account_payment_id={}'.format(
                                streamlined.dpd, account_payment.id
                            ),
                            **logger_data,
                        }
                    )
                    continue
                current_streamlined_comm_id = autodebet_streamlined.id

        send_email_payment_reminder_for_unsent_moengage.delay(
            account_payment.id,
            current_streamlined_comm_id,
            'send_automated_comm_email_for_unsent_moengage'
        )
        logger.info(
            {
                'streamlined_comm': current_streamlined_comm_id,
                'account_payment_id': account_payment.id,
                'message': 'triggered send_email_payment_reminder_for_unsent_moengage',
                **logger_data,
            }
        )
    redis_client.set(process_name, CeleryTaskLocker.STATUS['DONE'], CeleryTaskLocker.TIMEOUT)
    slack_message = "*Template: {}* - send_automated_comm_email_for_unsent_moengage (streamlined_id - {})".format(
        str(streamlined.template_code), str(streamlined_comm_id))
    send_slack_bot_message('alerts-comms-prod-email', slack_message)

@task(queue='collection_high')
def send_email_sms_for_unsent_moengage():
    send_sms_for_unsent_moengage()
    send_email_for_unsent_moengage()


def send_email_for_unsent_moengage():
    streamlined_communication_emails = StreamlinedCommunication.objects.filter(
            communication_platform=CommunicationPlatform.EMAIL,
            time_sent__isnull=False,
            is_automated=True,
            extra_conditions__in=(UNSENT_MOENGAGE, UNSENT_MOENGAGE_EXPERIMENT),
            dpd__isnull=False)

    for streamlined_email in streamlined_communication_emails:
        time_sent = streamlined_email.time_sent.split(':')
        time_sent = timezone.localtime(
                timezone.now()).replace(hour=int(time_sent[0]), minute=int(time_sent[1]))

        # Minute increment > time required to process email. Please check email_history.
        minute_increment = RETRY_EMAIL_MINUTE
        expected_sent_time = timezone.localtime(
                timezone.now()).replace(hour=time_sent.hour, minute=time_sent.minute)
        # Attempt sending email every {minute_increment} minutes
        # Comm rules. Cannot send above 19:59
        while expected_sent_time.hour < 20:
            countdown = calculate_countdown(
                    hour=expected_sent_time.hour, minute=expected_sent_time.minute)

            if countdown >= 0:
                send_automated_comm_email_for_unsent_moengage.apply_async(
                        (streamlined_email.id,), countdown=countdown)
                logger.info({
                    'action': 'send_email_sms_for_unsent_moengage',
                    'streamlined_comm': streamlined_email.template_code,
                    'message': 'success run send_automated_comm_email_for_unsent_moengage'
                })
            else:
                logger.info({
                    'action': 'send_email_sms_for_unsent_moengage',
                    'streamlined_comm': streamlined_email.template_code,
                    'message': 'run failed because time had passed send_automated_comm_email_for_unsent_moengage'
                })

            expected_sent_time += timezone.timedelta(minutes=minute_increment)


def send_sms_for_unsent_moengage():
    streamlined_communication_sms = StreamlinedCommunication.objects.filter(
            communication_platform=CommunicationPlatform.SMS,
            time_sent__isnull=False,
            is_automated=True,
            extra_conditions=UNSENT_MOENGAGE,
            dpd__isnull=False)

    for streamlined_comm in streamlined_communication_sms:
        time_sent = streamlined_comm.time_sent.split(':')
        hours = int(time_sent[0])
        minute = int(time_sent[1])
        countdown = calculate_countdown(hour=hours, minute=minute)

        if countdown >= 0:
            send_automated_comm_sms_for_unsent_moengage.apply_async(
                    (streamlined_comm.id,),
                    countdown=countdown)
            logger.info({
                'action': 'send_sms_for_unsent_moengage',
                'streamlined_comm': streamlined_comm.template_code,
                'message': 'success run'
            })
        else:
            logger.info({
                'action': 'send_sms_for_unsent_moengage',
                'streamlined_comm': streamlined_comm.template_code,
                'message': 'run failed because time had passed'
            })


def calculate_countdown(hour, minute, second=0, now=None):
    if not now:
        now = timezone.localtime(timezone.now())
    later = timezone.localtime(timezone.now()).replace(
            hour=hour, minute=minute, second=second)
    countdown = int(py2round((later - now).total_seconds()))

    return countdown


@task(queue='collection_high')
def send_manual_pn_for_unsent_moengage_sub_task(streamlined_pn_id: int) -> None:
    """
    Processes account payment for delivering PN that was unsent in MoEngage.

    Args:
        streamlined_pn_id (int): StreamlinedCOmmunication object ID.
    """
    today = timezone.localtime(timezone.now())
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    is_religious_holiday = Holiday.check_is_religious_holiday()
    streamlined_pn = StreamlinedCommunication.objects.get(id=streamlined_pn_id)
    if is_religious_holiday:
        logger.info(
            {
                "action": "send_manual_pn_for_unsent_moengage_sub_task",
                "message": "Payment reminder is skipped due to Religious Holiday",
                "template_code": streamlined_pn.template_code,
            }
        )

    if 'autodebet' in streamlined_pn.template_code:
        return

    product = streamlined_pn.product
    if product == 'j1':
        workflow = WorkflowConst.JULO_ONE
    elif product == 'jturbo':
        workflow = WorkflowConst.JULO_STARTER
    else:
        return

    # Get template codes for filtering if PN already sent by MoEngage
    filter_template_codes = (streamlined_pn.template_code, streamlined_pn.moengage_template_code)
    if streamlined_pn.dpd in autodebet_pn_dpds:
        if streamlined_pn.dpd == 0 and product == 'j1':
            # Special condition for DPD 0 with product J1 due to legacy template codes did not
            # conform with standard naming and is still used.
            filter_template_codes += ('j1_pn_autodebet_fail_T0_first_try_backup',
                                      'j1_pn_autodebet_fail_T0_first_try',)
        else:
            filter_template_codes += ('{}_pn_autodebet_T{}'.format(product, streamlined_pn.dpd),
                                      '{}_pn_autodebet_T{}_backup'.format(
                                          product, streamlined_pn.dpd),)

    sent_account_payments_ids = (
        PNDelivery.objects.filter(
            created_on__gte=start_of_day,
            created_on__lt=end_of_day,
            pntracks__account_payment_id__isnull=False,
        )
        .filter(
            reduce(
                or_,
                [
                    Q(pn_blast__name__contains=template_code)
                    for template_code in filter_template_codes
                ],
            )
        )
        .values_list('pntracks__account_payment_id', flat=True)
    )

    unsent_account_payments_ids = (
        OldestUnpaidAccountPayment.objects.filter(
            cdate__gte=start_of_day, cdate__lt=end_of_day, dpd=streamlined_pn.dpd
        )
        .exclude(account_payment_id__in=sent_account_payments_ids)
        .values_list('account_payment_id', flat=True)
    )

    account_payments = (
        AccountPayment.objects.filter(id__in=unsent_account_payments_ids)
        .filter(account__account_lookup__workflow__name=workflow)
        .exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
        .exclude(
            status=PaymentStatusCodes.PAID_ON_TIME,
        )
    )

    # credgenics customer block
    if is_comms_block_active(CommsType.PN):
        credgenics_account_payment_ids = get_credgenics_account_payment_ids()
        account_payments = account_payments.exclude(id__in=credgenics_account_payment_ids)

    omnichannel_comms_blocked = get_omnichannel_comms_block_active(
        OmnichannelIntegrationSetting.CommsType.PN,
    )

    if omnichannel_comms_blocked.is_excluded:
        omnichannel_account_ids = get_exclusion_omnichannel_account_ids(omnichannel_comms_blocked)
        account_payments = account_payments.exclude(account_id__in=omnichannel_account_ids)

    # START experiment condition

    # LATE FEE EXPERIMENT
    query, condition = check_experiment_condition(
        MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
        RedisKey.STREAMLINE_LATE_FEE_EXPERIMENT,
        streamlined_pn,
        account_payments,
        UNSENT_MOENGAGE_EXPERIMENT
    )

    if query is None:
        if 'pn_T' in streamlined_pn.moengage_template_code:
            return
    else:
        if condition == 'exists' and 'pn_T' in streamlined_pn.moengage_template_code:
            account_payments = query
        elif condition == 'not exists':
            account_payments = query

    # END experiment condition

    if not account_payments:
        logger.info({
            'action': 'send_manual_pn_for_unsent_moengage_sub_task',
            'template_code': filter_template_codes,
            'message': 'no unsent data'
        })
        return

    account_payments = account_payments
    device_repository = get_device_repository()
    for account_payment in account_payments.iterator():
        current_streamlined = streamlined_pn
        try:
            logger_data = {
                "module": 'juloserver.julo.tasks',
                "action": "send_manual_pn_for_unsent_moengage_sub_task",
                "template_code": filter_template_codes,
                "account_payment_id": account_payment.id,
                "dpd": current_streamlined.dpd,
            }

            # validation comms block
            if check_account_payment_is_blocked_comms(account_payment, 'pn'):
                logger.info({
                    **logger_data,
                    'message': 'customer got comms block for pn'
                })
                continue

            gcm_reg_id = device_repository.get_active_fcm_id(account_payment.account.customer_id)

            if not gcm_reg_id:
                logger.info({
                    **logger_data,
                    'message': 'customer did not have device'
                })
                continue

            # check for autodebet customer
            # TODO: Remove dependency between normal and autodebet comms
            autodebet_account = get_existing_autodebet_account(account_payment.account)
            is_autodebet = False
            if (current_streamlined.dpd in autodebet_pn_dpds and autodebet_account and
                autodebet_account.is_use_autodebet):
                is_autodebet = True

                if current_streamlined.dpd == 0 and product == 'j1':
                    # Special condition for DPD 0 with product J1 due to legacy template codes did
                    # not conform with standard naming and is still used.
                    template_code = 'j1_pn_autodebet_fail_T0_first_try_backup'
                    moengage_template_code = 'j1_pn_autodebet_fail_T0_first_try'
                else:
                    template_code = '{}_pn_autodebet_T{}_backup'.format(
                        product, current_streamlined.dpd)
                    moengage_template_code = '{}_pn_autodebet_T{}'.format(
                        product, current_streamlined.dpd)

                current_streamlined = StreamlinedCommunication.objects.filter(
                    communication_platform=CommunicationPlatform.PN,
                    time_sent__isnull=False,
                    is_automated=True,
                    dpd__isnull=False,
                    template_code=template_code,
                    moengage_template_code=moengage_template_code,
                    extra_conditions=UNSENT_MOENGAGE
                ).last()

            # Skip sending if it's a religious holiday and NOT autodebet
            if is_religious_holiday and not is_autodebet:
                logger.info(
                    {
                        "module": 'juloserver.julo.tasks',
                        "action": "skip send_manual_pn",
                        "account_payment_id": account_payment.id,
                        "message": "Skipping PN due to religious holiday)",
                    }
                )
                continue

            logger_data['is_autodebet'] = is_autodebet

            if not current_streamlined:
                logger.info({
                    **logger_data,
                    'message': 'Fail sending manual_blast_pn due to missing '
                               'stream_lined_communication '
                })
                continue

            julo_pn_client = get_julo_pn_client()

            logger.info({
                **logger_data,
                'template_code': current_streamlined.template_code,
                'message': 'Sending manual_blast_pn'
            })

            render_data = {
                'due_amount': account_payment.due_amount,
                'due_date': account_payment.due_date,
                'pn_cashback_counter': account_payment.account.cashback_counter_for_customer,
                'pn_month_due_date' : format_date(account_payment.due_date, 'MMMM', locale='id_ID')
            }

            julo_pn_client.manual_blast_pn(
                    account_payment,
                    gcm_reg_id,
                    current_streamlined,
                    render_data)
        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception(str(e))
    slack_message = "*Template: {}* - send_manual_pn_for_unsent_moengage_sub_task (streamlined_id - {})".format(
        str(streamlined_pn.template_code), str(streamlined_pn_id))
    send_slack_bot_message('alerts-comms-prod-pn', slack_message)


@task(queue='collection_high')
def send_manual_pn_for_unsent_moengage():
    """
    PN payment reminder daily scheduler for unsent to customer in MoEngage.
    Task execution time: juloserver/settings/collection_celery
    """
    streamlined_pns = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.PN,
        time_sent__isnull=False,
        is_automated=True,
        extra_conditions__in=(UNSENT_MOENGAGE, UNSENT_MOENGAGE_EXPERIMENT),
        template_code__isnull=False,
        moengage_template_code__isnull=False,
        product__in=['j1', 'jturbo']
    )

    for streamlined_pn in streamlined_pns:
        time_sent = streamlined_pn.time_sent.split(':')
        time_sent = timezone.localtime(
            timezone.now()).replace(hour=int(time_sent[0]), minute=int(time_sent[1]))

        # Minute increment > time required to process email. Please check email_history.
        minute_increment = RETRY_PN_MINUTE
        expected_sent_time = timezone.localtime(
            timezone.now()).replace(hour=time_sent.hour, minute=time_sent.minute)
        # Attempt sending email every {minute_increment} minutes
        # Comm rules. Cannot send above 19:59
        expected_time_limit = (timezone.localtime(timezone.now()).replace(hour=20, minute=0) -
                               timezone.timedelta(minutes=minute_increment))
        while expected_sent_time < expected_time_limit:
            countdown = calculate_countdown(
                hour=expected_sent_time.hour, minute=expected_sent_time.minute)

            if countdown >= 0:
                send_manual_pn_for_unsent_moengage_sub_task.apply_async(
                    (streamlined_pn.id,), countdown=countdown)
                logger.info({
                    'action': 'send_manual_pn_for_unsent_moengage',
                    'streamlined_comm': streamlined_pn.template_code,
                    'message': 'success run'
                })
            else:
                logger.warning({
                    "action": "send_manual_pn_for_unsent_moengage",
                    "message": "Ignore queuing backup PN due to send time exceeded",
                    "data": {"template_code": streamlined_pn.template_code, "countdown": countdown},
                })
            expected_sent_time += timezone.timedelta(minutes=minute_increment)

@task(queue='collection_high')
def send_automated_comm_pn_ptp_j1(streamlined):
    # this will now only handle ptp notifications
    streamlined.refresh_from_db()
    if not streamlined:
        return

    if not streamlined.is_automated:
        logger.info({
            'message': 'Dismissed for streamline not is_automated',
            'action': 'send_automated_comm_pn_ptp_j1',
            'streamlined_comm_id': streamlined.id
        })
        return

    if streamlined.ptp is None:
        return
    account_payments = []
    # get product list from class ProductLineCodes
    product_lines = getattr(ProductLineCodes, streamlined.product)()
    query = AccountPayment.objects.not_paid_active()\
        .filter(account__application__product_line__product_line_code__in=product_lines)

    ptp_date = get_payment_due_date_by_delta(int(streamlined.ptp))
    account_payments = query.filter(ptp_date__isnull=False,
                                        ptp_date=ptp_date)

    buttons = get_pn_action_buttons(streamlined.id)
    for account_payment in account_payments:
        if ptp_date is not None:
            is_ptp_paid = is_ptp_payment_already_paid(account_payment.id, ptp_date, is_account_payment=True)
            if is_ptp_paid:
                logger.info({
                    'status': 'send_automated_comm_pn_ptp_j1',
                    'account_payment_id': account_payment.id,
                    'message': "ptp already paid",
                    'ptp_date': ptp_date
                })
                continue
        send_automated_comm_pn_ptp_j1_subtask.delay(
            account_payment, streamlined, buttons
        )
    slack_message = "*Template: {}* - send_automated_comm_pn_ptp_j1 (streamlined_id - {})".format(
        str(streamlined.template_code), str(streamlined.id))
    send_slack_bot_message('alerts-comms-prod-pn', slack_message)

@task(queue='collection_high')
def send_automated_comm_pn_ptp_j1_subtask(account_payment, streamlined, buttons):
    application = account_payment.account.application_set.last()
    device = application.device
    if have_pn_device(device):
        available_context = process_streamlined_comm_context_for_ptp(account_payment,
                                                 streamlined,
                                                 is_account_payment=True)
        message = process_streamlined_comm_without_filter(streamlined, available_context)
        heading_title = process_streamlined_comm_email_subject(streamlined.heading_title,
                                                               available_context)
        template_code = streamlined.template_code
        image = Image.objects.get_or_none(
            image_source=streamlined.id, image_type=ImageType.STREAMLINED_PN, image_status=Image.CURRENT
        )
    else:
        logger.warn({
            "action": "send_automated_comm_PN_j1",
            "message": "skip PN have_pn_device False",
            "data": {"payment_id": account_payment.id},
        })
        return
    if account_payment:
        julo_pn_client = get_julo_pn_client()
        julo_pn_client.automated_payment_reminder_j1(
            account_payment, message, heading_title, template_code, buttons, image
        )
    else:
        logger.warn({
            "action": "send_automated_comm_PN j1",
            "message": "skip PN because payment is None",
            "data": {"account_payment_id": account_payment.id},
        })


@task(queue='collection_high')
def send_automated_comm_sms_ptp_j1(streamlined_comm_id: int) -> None:
    """
    Processes account_payment expected to send as
    account-based product (J1, JTurbo) payment reminder for PTP Case

    Args:
        streamlined_comm_id (int): StreamlinedCommunication model id

    Return:
        None
    """
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    if not streamlined:
        return

    logger_data = {
        'action': 'send_automated_comm_sms_ptp_j1',
        'streamlined_comm': streamlined,
        'template_code': streamlined.template_code
    }

    if streamlined.ptp is None:
        logger.info({
            **logger_data,
            'message': 'Dismissed for missing ptp',
        })
        return

    if not streamlined.is_automated:
        logger.info({
            **logger_data,
            'is_automated': streamlined.is_automated,
            'message': 'Dismissed for streamline not is_automated'
        })
        return

    product_lines = getattr(ProductLineCodes, streamlined.product)()
    ptp_date = get_payment_due_date_by_delta(int(streamlined.ptp))
    logger_data.update(ptp_date=ptp_date)
    account_payment_ids = PTP.objects.filter(
        cdate__lte=ptp_date,
        ptp_date=ptp_date
    ).values_list('account_payment_id', flat=True)
    account_payments = AccountPayment.objects.not_paid_active().filter(
        account__application__product_line__product_line_code__in=product_lines,
        id__in=account_payment_ids
    )

    # Filter the account status lookup based on the product.
    # This logic is needed for J1 and JTurbo because a single account might have
    # JTurbo and J1 product line code.
    if streamlined.product.lower() == Product.SMS.JTURBO:
        account_payments = account_payments.filter(
            account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER,
        )
    elif streamlined.product.lower() == Product.SMS.J1:
        account_payments = account_payments.filter(
            account__account_lookup__workflow__name=WorkflowConst.JULO_ONE,
        )

    # exclude omnichannel customer population
    omnichannel_exclusion_request = get_omnichannel_comms_block_active(
        OmnichannelIntegrationSetting.CommsType.SMS
    )

    if omnichannel_exclusion_request.is_excluded:
        omnichannel_account_ids = get_exclusion_omnichannel_account_ids(
            omnichannel_exclusion_request
        )
        account_payments = account_payments.exclude(account_id__in=omnichannel_account_ids)

    for account_payment in account_payments.distinct().iterator():
        if ptp_date is not None:
            is_ptp_paid = is_ptp_payment_already_paid(account_payment.id, ptp_date, is_account_payment=True)
            if is_ptp_paid:
                logger.info({
                    'action': 'send_automated_comm_sms_ptp_j1',
                    'account_payment_id': account_payment.id,
                    'message': "ptp already paid",
                    'ptp_date': ptp_date
                })
                continue

        logger.info({
            **logger_data,
            'is_ptp_paid': None if ptp_date is None else is_ptp_paid,
            'account_payment': account_payment.id,
            'message': 'Execute send_automated_comm_sms_ptp_j1_subtask'
        })

        send_automated_comm_sms_ptp_j1_subtask.delay(account_payment, streamlined)
    slack_message = "*Template: {}* - send_automated_comm_sms_ptp_j1 (streamlined_id - {})".format(
        str(streamlined.template_code), str(streamlined_comm_id))
    send_slack_bot_message('alerts-comms-prod-sms', slack_message)


@task(queue='collection_high')
def send_automated_comm_sms_ptp_j1_subtask(account_payment, streamlined):
    """
    Trigger send sms for account-based product (J1, JTurbo) payment reminder for PTP Case

    Args:
        account_payment (AccountPayment): AccountPayment object
        streamlined (StreamlinedCommunication): StreamlinedCommunication object

    Returns:
        None
    """
    logger.info({
        'action': 'send_automated_comm_sms_ptp_j1_subtask',
        'account_payment_id': account_payment.id,
        'streamlined_comm': streamlined,
        'template_code': streamlined.template_code,
        'message': "Starting action process."
    })

    julo_sms_client = get_julo_sms_client()
    account_payment_id = account_payment.id
    application = account_payment.account.application_set.filter(
        workflow_id=account_payment.account.account_lookup.workflow_id,
    ).last()
    template_code = streamlined.template_code
    available_context = process_streamlined_comm_context_for_ptp(account_payment,
                                                                     streamlined,
                                                                     is_account_payment=True)

    message = process_streamlined_comm_without_filter(streamlined, available_context)

    category = ""
    try:
        txt_msg, response, template = julo_sms_client.sms_automated_comm_j1(account_payment, message, template_code)
        is_success = True
    except Exception as e:
        is_success = False
        logger.error({'reason': 'SMS not sent',
                      'action': 'send_automated_comm_sms_ptp_j1_subtask',
                      'account_payment_id': account_payment_id,
                      'due_date': account_payment.due_date})
        capture_exception()

    if is_success:
        if response['status'] != '0':
            raise SmsNotSent({
                'send_status': response['status'],
                'account_payment_id': account_payment_id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': 'sms_automated_comm_j1',
                'error_text': response.get('error-text'),
            })

        customer = application.customer
        if streamlined.ptp is not None:
            category = "PTP"
        sms = create_sms_history(response=response,
                                 customer=customer,
                                 application=application,
                                 account_payment=account_payment,
                                 template_code=template,
                                 message_content=txt_msg,
                                 to_mobile_phone=format_e164_indo_phone_number(response['to']),
                                 phone_number_type='mobile_phone_1',
                                 category=category
                                 )

        logger.info({
            'message': 'SMS history created.',
            'account_payment_id': account_payment_id,
            'sms_history_id': sms.id,
            'message_id': sms.message_id
        })


@task(queue='collection_high')
def send_realtime_ptp_notification(ptp_id):
    from juloserver.email_delivery.tasks import (
        send_email_payment_reminder,
        send_email_ptp_payment_reminder_j1,
    )

    ptp = PTP.objects.get(pk=ptp_id)
    ptp_status = ['Paid after ptp date', 'Paid', 'Partial', 'Not Paid']
    eligible_to_send = True

    if ptp.ptp_status in ptp_status:
        eligible_to_send = False

    if ptp is not None:
        streamline_comm_function_list = {
            "j1": {CommunicationPlatform.SMS: send_automated_comm_sms_ptp_j1_subtask,
                   CommunicationPlatform.PN: send_automated_comm_pn_ptp_j1_subtask,
                   CommunicationPlatform.EMAIL: send_email_ptp_payment_reminder_j1
                   }
        }

        streamlined_communications = StreamlinedCommunication.objects \
            .filter(communication_platform__in=[CommunicationPlatform.SMS,
                                                CommunicationPlatform.EMAIL,
                                                CommunicationPlatform.PN],
                    is_automated=True,
                    ptp='real-time')

        is_account_payment = True if ptp.account_payment is not None else False
        if is_account_payment:
            payment_id = ptp.account_payment_id
            payment_or_account_payment = AccountPayment.objects.get_or_none(id=payment_id)
            application = payment_or_account_payment.account.application_set.last()
            streamlined_communications = streamlined_communications.filter(product__in=["j1","jturbo"])
        else:
            payment_id = ptp.payment_id
            payment_or_account_payment = Payment.objects.get_or_none(id=payment_id)
            application = payment_or_account_payment.loan.application
            streamlined_communications = streamlined_communications.exclude(product__in=["j1","jturbo"])

        if streamlined_communications is not None:
            for streamlined_comm in streamlined_communications:
                platform = streamlined_comm.communication_platform
                if streamlined_comm.product != 'internal_product':
                    product_lines = getattr(ProductLineCodes, streamlined_comm.product)()
                else:
                    product_lines = ProductLineCodes.mtl() + ProductLineCodes.stl()

                if application.product_line.product_line_code not in product_lines:
                    continue

                if platform == CommunicationPlatform.PN:
                    buttons = get_pn_action_buttons(streamlined_comm.id)

                if is_account_payment:
                    if platform == CommunicationPlatform.PN:
                        streamline_comm_function_list['j1'][platform].delay(payment_or_account_payment, streamlined_comm, buttons)
                    elif platform == CommunicationPlatform.EMAIL:
                        if eligible_to_send:
                            send_email_ptp_payment_reminder_j1.delay(payment_or_account_payment, streamlined_comm)
                    else:
                        streamline_comm_function_list['j1'][platform].delay(payment_or_account_payment, streamlined_comm)
                else:
                    available_context = process_streamlined_comm_context_for_ptp(payment_or_account_payment,
                                                                                 streamlined_comm,
                                                                                 is_account_payment=False)
                    message = process_streamlined_comm_without_filter(streamlined_comm, available_context)

                    if platform == CommunicationPlatform.PN:
                        heading_title = process_streamlined_comm_email_subject(streamlined_comm.heading_title,
                                                                               available_context)
                        send_automated_comm_pn_subtask.delay(payment_id, message, heading_title, streamlined_comm.template_code, buttons)
                    elif platform == CommunicationPlatform.EMAIL:
                        if eligible_to_send:
                            send_email_payment_reminder.delay(payment_id, streamlined_comm.id)
                    elif platform == CommunicationPlatform.SMS:
                        send_automated_comm_sms_subtask.delay(payment_id, message, streamlined_comm.template_code)

        logger.info({
            'status': 'send_realtime_ptp_notification',
            'account_payment_or_payment': payment_id,
            'ptp_id': ptp_id,
            'eligible_to_send': eligible_to_send
        })


@task(queue='collection_high')
def send_automated_comms_ptp_sms():
    """
    Schedule SMS payment reminder for PTP (Promise To Pay) case
    This is for non-account and account based product

    Returns:
        None
    """
    streamlined_communication_sms_ptp = StreamlinedCommunication.objects \
        .filter(communication_platform=CommunicationPlatform.SMS,
                time_sent__isnull=False,
                is_automated=True,
                extra_conditions__isnull=True,
                dpd__isnull=True,
                ptp__isnull=False)\
        .exclude(ptp='real-time')

    # handle sms for dpd
    for streamlined_comm in streamlined_communication_sms_ptp:
        now = timezone.localtime(timezone.now())
        time_sent = streamlined_comm.time_sent.split(':')
        hours = int(time_sent[0])
        minute = int(time_sent[1])
        later = timezone.localtime(timezone.now()).replace(hour=hours, minute=minute, second=0, microsecond=0)
        countdown = int(py2round((later - now).total_seconds()))

        logger_data = {
            'streamlined_id': streamlined_comm.id,
            'streamlined_comm': streamlined_comm.template_code,
            'countdown': countdown
        }

        # send base on schedule on streamlined
        if countdown >= 0:
            if streamlined_comm.product in Product.sms_non_account_products():
                send_automated_comm_sms.apply_async((streamlined_comm.id,), countdown=countdown)
                logger.info({
                    'action': 'send_automated_comms_ptp_sms non-account product',
                    'message': 'success run',
                    **logger_data
                })
                continue

            send_automated_comm_sms_ptp_j1.apply_async((streamlined_comm.id,), countdown=countdown)
            logger.info({
                'action': 'send_automated_comms_ptp_sms account-based product',
                'message': 'success run',
                **logger_data
            })
        else:
            logger.info({
                'action': 'send_automated_comms_ptp_sms',
                'message': 'run failed because time had passed',
                **logger_data
            })


@task(queue='collection_high')
def send_cashback_expired_pn(streamlined_comm_id):
    # deprecated since CLS3-440;
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    today = timezone.localtime(timezone.now()).date()
    expire_date = today + timedelta(days=streamlined.dpd)

    cashback_earned_list = CashbackEarned.objects.filter(
        current_balance__gt=0,
        expired_on_date=expire_date
    )
    for cashback_earned in cashback_earned_list.iterator():
        customer = cashback_earned.customerwallethistory.customer
        device = customer.application_set.last().device
        if have_pn_device(device):
            message = process_streamlined_comm_context_base_on_model_and_parameter(
                streamlined, cashback_earned, is_with_header=False
            )
            send_cashback_expired_pn_subtask.delay(
                customer.id, message, streamlined.template_code
            )
        else:
            logger.warning({
                "action": "send_cashback_expired_pn",
                "message": "skip PN have_pn_device False",
                "data": {"cashback_earned_id": cashback_earned.id,
                         "customer_id": customer.id},
            })
            continue


@task(queue='collection_high')
def send_cashback_expired_pn_subtask(customer_id, message, template_code):
    # deprecated;
    customer = Customer.objects.get_or_none(pk=customer_id)
    if customer:
        julo_pn_client = get_julo_pn_client()
        julo_pn_client.cashback_expire_reminder(customer, message, template_code)
    else:
        logger.warning({
            "action": "send_cashback_expired_pn_subtask",
            "message": "skip PN because customer is None",
            "data": {"customer_id": customer_id},
        })


@task(name='run_broken_ptp_flag_update')
def run_broken_ptp_flag_update():
    """
    scheduled to turn off flag is_broken_ptp_plus_1
    """
    range_2days_ago = timezone.localtime(timezone.now()).date() - timedelta(days=2)
    payments = Payment.objects.filter(ptp_date__lte=range_2days_ago,
                                      loan__is_broken_ptp_plus_1=True)
    for payment in payments:
        # turn off  is_broken_ptp_plus_1 on ptp+2
        update_flag_is_broken_ptp_plus_1(payment, is_account_payment=False, turn_off_broken_ptp_plus_1=True)


@task(queue='partnership_global')
def send_sms_otp_partnership(
        phone_number, text, partnership_customer_data_id,
        otp_id, change_sms_provide=False, template_code=None):
    otp = OtpRequest.objects.get(pk=otp_id)
    partnership_customer_data = PartnershipCustomerData.objects.get_or_none(
        pk=partnership_customer_data_id)
    if not partnership_customer_data:
        raise JuloException("Partnership customer data is Null")
    mobile_number = format_e164_indo_phone_number(phone_number)
    get_julo_sms = get_julo_sms_client()

    txt_msg, response = get_julo_sms.premium_otp(mobile_number, text, change_sms_provide)

    if response["status"] != "0":
        raise SmsNotSent(
            {
                "send_status": response["status"],
                "message_id": response.get("message-id"),
                "sms_client_method_name": "sms_custom_payment_reminder",
                "error_text": response.get("error-text"),
            }
        )

    sms = create_sms_history(response=response,
                             partnership_customer_data=partnership_customer_data,
                             message_content=txt_msg,
                             to_mobile_phone=format_e164_indo_phone_number(response["to"]),
                             phone_number_type="mobile_phone_1",
                             template_code=template_code
                             )

    # Save sms history to otp request
    otp.sms_history = sms
    otp.save()

    logger.info(
        {
            "status": "sms_created",
            "sms_history_id": sms.id,
            "message_id": sms.message_id,
        }
    )


@task(queue='application_xid')
def store_new_xid_task(application_id):
    application = Application.objects.get(id=application_id)
    application_xid = XidLookup.get_new_xid()
    application.update_safely(application_xid=application_xid)
    logger.info(
        {
            "msg": "get_new_xid success by async task",
            "application_id": application_id,
        }
    )

@task
def async_store_crm_navlog(navlog_obj: dict):
    try:
        with transaction.atomic():
            for row in navlog_obj:
                if row['event'] == 'pageviews':
                    json_timestamp = row['extra']['globalTimestamp']
                    element = ""
                    path = ""
                else:
                    json_timestamp = row['timestamp']
                    element_dict = {
                        k: v for k, v in list(row['element'].items()) if k not in ['path']
                    }
                    element = json.dumps(element_dict)
                    path = row['element']['path']
                parsed_timestamp = dateutil.parser.parse(json_timestamp)
                try:
                    CrmNavlog.objects.create(
                        page_url=row['page_url'],
                        referrer_url=row['referrer_url'],
                        user=row['extra']['user'],
                        timestamp=parsed_timestamp,
                        element=element,
                        path=path,
                        event=row['event'],
                    )
                except KeyError:
                    pass
    except DatabaseError as e:
        logger.info({'message': 'Fail to save CRM log record.', 'error': e})


@task(queue='repayment_high')
def populate_mandiri_virtual_account_suffix():
    from juloserver.integapiv1.services import get_last_va_suffix

    count_mandiri_va_suffix_unused = MandiriVirtualAccountSuffix.objects.filter(
        account=None).count()
    # generate mandiri_virtual_account_suffix if unused count is less
    if count_mandiri_va_suffix_unused <= VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT:
        batch_size = 1000
        last_mandiri_virtual_account_suffix = get_last_va_suffix(
            MandiriVirtualAccountSuffix,
            'mandiri_virtual_account_suffix',
            PiiSource.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX,
        )

        start_range = int(last_mandiri_virtual_account_suffix) + 1
        max_count = VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT
        end_range = start_range + max_count + 1

        va_suffix_objs = (
            MandiriVirtualAccountSuffix(
                mandiri_virtual_account_suffix=str(va_suffix_val).zfill(8)
            ) for va_suffix_val in range(start_range, end_range)
        )

        MandiriVirtualAccountSuffix.objects.bulk_create(va_suffix_objs, batch_size)


@task(queue='low')
def patch_delete_account():
    customers = Customer.objects.filter(
        can_reapply=False,
        is_active=True, user__is_active=False)

    application_field_changes = []
    customer_field_changes = []
    auth_user_field_changes = []
    customer_removals = []
    try:
        with transaction.atomic():
            for customer in customers.iterator():
                applications = customer.application_set.all()
                application = applications.last()
                unpaid_loan = Loan.objects.filter(
                    customer=customer, loan_status_id__gte=220, loan_status_id__lt=250
                    )
                if not unpaid_loan:
                    customer_field_changes.append(CustomerFieldChange(
                        customer=customer,
                        application=application,
                        field_name='can_reapply',
                        old_value=customer.can_reapply,
                        new_value=False,
                    ))

                    customer_field_changes.append(CustomerFieldChange(
                        customer=customer,
                        application=application,
                        field_name='is_active',
                        old_value=customer.is_active,
                        new_value=False,
                    ))
                    auth_user_field_changes.append(
                        AuthUserFieldChange(
                            user=customer.user,
                            customer=customer,
                            field_name='is_active',
                            old_value=customer.user.is_active,
                            new_value=False,
                    ))
                    customer_exists_in_customer_removal = CustomerRemoval.objects.filter(customer=customer)
                    if not customer_exists_in_customer_removal.exists():
                        customer_removals.append(CustomerRemoval(
                            customer=customer,
                            application=application,
                            user=customer.user,
                            reason="Patched using Retroload",
                        ))
                    customer.update_safely(can_reapply=False, is_active=False)

                    for application in applications:
                        application_field_changes.append(ApplicationFieldChange(
                            application=application,
                            field_name='is_deleted',
                            old_value=application.is_deleted,
                            new_value=True,
                        ))
                        application.update_safely(is_deleted=True)

                    expiry_token = ExpiryToken.objects.get(user=customer.user)
                    generate_new_token(customer.user,)
                    expiry_token.update_safely(is_active=False)
                    customer.user.is_active = False
                    customer.user.save()
                else:
                    continue

        ApplicationFieldChange.objects.bulk_create(application_field_changes)
        CustomerFieldChange.objects.bulk_create(customer_field_changes)
        AuthUserFieldChange.objects.bulk_create(auth_user_field_changes)
        CustomerRemoval.objects.bulk_create(customer_removals)
    except Exception as e:
        logger.exception({
            'task': 'patch_delete_account',
            'message': 'to patch all customers deleted by the PRE manually',
            'errors': str(e)

        })


@task(queue='repayment_high')
def populate_bni_virtual_account_suffix(validate_limit=True):
    from juloserver.integapiv1.services import get_last_va_suffix
    logger.info(
        {
            'action': 'populate_bni_virtual_account_suffix',
            'message': 'Intialzing the suffix population for bni virtual account',
        }
    )
    count_bni_va_suffix_unused = BniVirtualAccountSuffix.objects.filter(account_id=None).count()
    # generate bni_virtual_account_suffix if unused count is less
    if validate_limit and not count_bni_va_suffix_unused <= VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT:
        logger.info({
            'action': 'populate_bni_virtual_account_suffix',
            'bni_va_suffix_unused_count': count_bni_va_suffix_unused,
            'message': 'skip populating bni virtual account suffix because unused count is large'
        })
        return

    batch_size = 1000
    last_bni_virtual_account_suffix = get_last_va_suffix(
        BniVirtualAccountSuffix,
        'bni_virtual_account_suffix',
        PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX,
    )

    start_range = int(last_bni_virtual_account_suffix) + 1
    max_count = VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT
    end_range = start_range + max_count + 1

    bni_va_suffix_objs = []
    for va_suffix_val in range(start_range, end_range):
        # millions are not valid since digit already out of the prefix quota.
        if va_suffix_val % 1000000 == 0:
            continue

        bni_va_suffix_objs.append(
            BniVirtualAccountSuffix(bni_virtual_account_suffix=str(va_suffix_val).zfill(6))
        )

    BniVirtualAccountSuffix.objects.bulk_create(bni_va_suffix_objs, batch_size)

    # SEND WARNING EMAIL
    prefix = PaymentMethodCodes.BNI
    if end_range > 1000000:
        prefix = PaymentMethodCodes.BNI_V2

    remaining_count = 1000000 - (end_range % 1000000)
    if remaining_count < 200.000:
        send_email_bni_va_suffix_limit_task.delay(prefix, remaining_count)

    logger.info(
        {
            'action': 'populate_bni_virtual_account_suffix',
            'message': 'successfully populated the bni virtual account suffix',
        }
    )


@task(queue='repayment_normal')
def send_email_bni_va_generation_limit_alert(bni_va_count):

    # trigger email to notify the bni va generation limit

    if bni_va_count == BNIVAConst.MAX_LIMIT:
        subject = 'BNI VA generation reached maximum limit'
    else:
        subject = 'BNI VA generation almost reached maximum limit'
    email_to = settings.BNI_VA_EMAIL_TO
    email_cc = settings.BNI_VA_EMAIL_CC

    email_client = get_julo_email_client()
    status, headers, message = email_client.email_bni_va_generation_limit_alert(
        bni_va_count, subject, email_to, email_cc)

    if status == 202:
        logger.info({
            'action': 'send_email_bni_va_generation_limit_alert',
            'email_to': email_to,
            'email_cc': email_cc,
            'status': str(status)
        })

        message_id = headers["X-Message-Id"]

        EmailHistory.objects.create(
            sg_message_id=message_id,
            to_email=email_to,
            cc_email=email_cc,
            subject=subject,
            message_content=message,
            template_code="email_bni_va_generation_limit_alert",
        )


@task(name='warn_sepulsa_balance_low_once_daily_async')
def warn_sepulsa_balance_low_once_daily_async(balance):
    startdate = datetime.today()
    startdate = startdate.replace(hour=0, minute=0, second=0)
    enddate = startdate + timedelta(days=1)
    subject = 'Warning - Sepulsa Balance Low'
    last_email = EmailHistory.objects.filter(cdate__range=[startdate, enddate], subject=subject).last()
    if last_email:
        return
    if settings.ENVIRONMENT != 'prod':
        return
    # notify email
    julo_email_client = get_julo_email_client()
    status, subject, msg = julo_email_client.email_notif_balance_sepulsa_low(balance, subject)
    if status == requests.codes.accepted:
        EmailHistory.objects.create(
            subject=subject,
            message_content=msg,
            template_code='email_notif_balance_sepulsa_low'
        )
    # notify slack chanel
    text_data = {
        'message': 'Warning - Sepulsa Balance Low',
        'balance': display_rupiah(balance)
    }
    notify_sepulsa_balance_low(text_data)


@task(queue='normal')
def send_pn_invalidate_caching_loans_android(customer_id, loan_xid, loan_amount):
    pn = get_julo_pn_client()
    device = Device.objects.filter(customer_id=customer_id).last()
    if not device or not device.gcm_reg_id:
        return

    pn.pn_loan_success_x220(device.gcm_reg_id, loan_xid, loan_amount)


@task(queue='loan_normal')
def send_pn_invalidate_caching_downgrade_alert(customer_id):
    pn = get_julo_pn_client()
    device = Device.objects.filter(customer_id=customer_id).last()
    if not device or not device.gcm_reg_id:
        return

    pn.pn_downgrade_alert(device.gcm_reg_id, customer_id)


@task(queue='collection_normal')
def update_skiptrace_number(application_id, contact_source, new_number, fullname=None):
    logger.info({
        'action': 'update_skiptrace_number',
        'message': 'Update skiptrace history with application',
        'application_id' : application_id,
        'contact_source' : contact_source,
        'new_number' : new_number,
    })
    with transaction.atomic():
        application = Application.objects.get(id=application_id)
        if not fullname:
            fullname = application.fullname
        if new_number:
            # Get or create a Skiptrace object for the given application, contact source, and new number
            skiptrace, created = Skiptrace.objects.get_or_create(
                customer=application.customer,
                phone_number=format_e164_indo_phone_number(new_number),
                defaults={
                    'contact_source': contact_source,
                    'contact_name': fullname,
                    'application':application,
                }
            )
            if not created:
                if (
                    contact_source == SkiptraceContactSource.FC_CUSTOMER_MOBILE_PHONE
                    and skiptrace.contact_source in SkiptraceContactSource.APPLICATION_SOURCES
                ):
                    raise JuloException(
                        "Nomor yang Anda masukkan sudah terdaftar. Silakan masukkan nomor lain."
                    )
                # Update contact source on skiptrace if we found same number on skiptrace,
                # skip case when current skiptrace number is 'mobile_phone_1' because 1 customer
                # can have same phone number on different sources.
                if (
                    skiptrace.contact_source != contact_source
                    and skiptrace.contact_source != SkiptraceContactSource.MOBILE_PHONE_1
                ):
                    skiptrace.update_safely(contact_source=contact_source)

            # Find old Skiptrace objects for the same customer and contact source, excluding the newly created one
            old_skiptraces = Skiptrace.objects.filter(
                customer=application.customer,
                contact_source=contact_source,
            ).exclude(id=skiptrace.id)
        else:
            # Delete phonenumber case or phone number is None
            # Find old Skiptrace objects for the same customer and contact source
            old_skiptraces = Skiptrace.objects.filter(
                customer=application.customer,
                contact_source=contact_source,
            )

        # Update the old Skiptrace objects by appending 'old' to their contact source
        for old_skiptrace in old_skiptraces:
            old_skiptrace.update_safely(contact_source='old_' + contact_source)

        return


@task(queue='low')
def update_account_status_of_deleted_customers():

    accounts = [ customer_removal.customer.account for customer_removal in
                CustomerRemoval.objects.filter(customer__account__status=AccountConstant.STATUS_CODE.active)]
    try:
        for account in accounts:
            logger.info({
                'action': 'update_account_status_of_deleted_customers',
                'account': account.id,
                'account_status': account.status_id,
            })
            applications = account.application_set
            application = applications.last()
            if application:
                if not is_application_status_deleteable(application.status):
                    return None
                process_change_account_status(
                                account=account,
                                new_status_code=AccountConstant.STATUS_CODE.deactivated,
                                change_reason="patched account status using retroload",
                            )
    except Exception as e:
        logger.exception({
            'action': 'update_account_status_of_deleted_customers',
            'messaage': 'exception rasises while updating the deleteted account',
            'error': str(e),
        })



@task(queue='low')
def update_credentials_of_deleted_customers():
    customer_removals = CustomerRemoval.objects.filter(nik=None, email=None, phone=None)
    updated_from_customer_or_application = []
    try:
        for customer_removal in customer_removals:
            logger.info({
                'action': 'update_credentials_of_deleted_customers',
                'account': customer_removal.id,
                'customer': customer_removal.customer_id,
            })
            customer = customer_removal.customer
            applications = customer.application_set.all()
            edited_nik = customer.get_nik
            edited_phone = customer.get_phone
            edited_email = customer.get_email

            nik = get_original_value(customer.id, applications, edited_nik)
            email =  get_original_value(customer.id, applications, edited_email)
            phone =  get_original_value(customer.id, applications, edited_phone)
            cred_updated_from_customer_application = {}

            if nik:
                nik = nik.get('old_value')
            else:
                nik = edited_nik
                cred_updated_from_customer_application.update({'nik': nik})

            if email:
                email = email.get('old_value')
            else:
                email = edited_email
                cred_updated_from_customer_application.update({'email': email})

            if phone:
                phone = phone.get('old_value')
            else:
                phone = edited_phone
                cred_updated_from_customer_application.update({'phone': phone})

            customer_removal.email=email
            customer_removal.nik=nik
            customer_removal.phone=phone

            if cred_updated_from_customer_application:
                cred_updated_from_customer_application.update({'customer_id': customer.id})
                updated_from_customer_or_application.append(cred_updated_from_customer_application)
        logger.info({
            'action': 'update_credentials_of_deleted_customers',
            'messaage': 'credentials were updated from customer or application table',
            'data': updated_from_customer_or_application
        })
        bulk_update(customer_removals, update_fields=['email', 'nik', 'phone' ], batch_size=1000)
        return updated_from_customer_or_application

    except Exception as e:
        logger.exception({
            'action': 'update_credentials_of_deleted_customers',
            'messaage': 'exception rasised while updating the deleteted account',
            'error': str(e),
        })

        raise Exception(e)


@task(queue='application_high')
def inapp_account_deletion_deactivate_account_pending_status():
    import datetime

    today = datetime.date.today()
    pending_request_date_30_days = today - datetime.timedelta(days=30)
    pending_request_date_20_days = today - datetime.timedelta(days=20)

    account_deletion_requests = AccountDeletionRequest.objects.filter(
        Q(
            cdate__date__gte=ADJUST_AUTO_APPROVE_DATE_RELEASE,
            cdate__date=pending_request_date_20_days,
        ) |
        Q(
            cdate__date__lt=ADJUST_AUTO_APPROVE_DATE_RELEASE,
            cdate__date=pending_request_date_30_days,
        ),
        request_status=AccountDeletionRequestStatuses.PENDING,
    )
    in_app_deletion_customer_requests(account_deletion_requests)


@task(queue='application_high')
def inapp_account_deletion_deactivate_account_approved_status():
    today = timezone.localtime(timezone.now())
    start_date = today - timedelta(days=30)
    end_date = today - timedelta(days=10)

    account_deletion_requests = AccountDeletionRequest.objects.filter(
        request_status=AccountDeletionRequestStatuses.APPROVED,
        cdate__date__range=(start_date, end_date),
    )
    in_app_deletion_customer_requests(account_deletion_requests)


def check_experiment_condition(
        experiment_code: str, redis_key: str, streamlined: StreamlinedCommunication, query,
        extra_conditions: str = None, experiment_identifier: str ='experiment'):
    # Case for cashback new scheme
    condition = ""
    experiment_setting = get_experiment_setting_by_code(experiment_code)
    experiment_setting_id = experiment_setting.id if experiment_setting else None

    if not extra_conditions:
        extra_conditions = experiment_code

    if streamlined.extra_conditions == extra_conditions and not experiment_setting_id:
        return None, condition

    if experiment_setting_id:
        experiment_dpd_list = get_list_dpd_experiment(extra_conditions, streamlined.communication_platform, redis_key)

        experiment_group_condition = """EXISTS ( SELECT "experiment_group"."experiment_group_id"
                                FROM "experiment_group"
                                WHERE "experiment_group"."account_id" = "account"."account_id"
                                AND "experiment_group"."experiment_setting_id" = %s AND "experiment_group"."group" = %s)"""

        if streamlined.extra_conditions == extra_conditions:
            query = query.extra(
                where=[experiment_group_condition], params=[
                    experiment_setting_id, experiment_identifier])
            condition = "exists"
        elif streamlined.dpd in experiment_dpd_list:
            query = query.extra(
                where=[f'NOT {experiment_group_condition}'], params=[
                    experiment_setting_id, experiment_identifier])
            condition = "not exists"

    return query, condition

@task(queue='application_high')
def send_whatsapp_otp_go(phone_number, whatsapp_content, purpose, hostname):
    """
        This task is to initiate the otp send process trough julo-internal whatsapp service.
        The required parameteres are
            phone_number,
            whatsapp_content,
            purpose,
            hostname,
        Currently the value for "purpose" and "hostname" is fixed, but for further improvement, I put it as a configurable parameters.
    """
    wa_client = get_julo_whatsapp_client_go()
    response = (wa_client.send_whatsapp(phone_number, whatsapp_content, purpose, hostname)).json()
    if not response:
        raise SmsNotSent(
            {
                "send_status": response["success"],
                "message_id": response["data"]["xid"],
                "sms_client_method_name": "whatsapp_service_go",
                "error_text": response["error"],
            }
        )
    msg_id = response["data"]["xid"]
    return msg_id

@task(queue='application_high')
def send_otpless_sms_request(phone_number, verification_link):
    """
    This task is temporary solution while waiting for OTPLess team
    to whitelist their sms header.

    We expose our sms client to be able to be used temporarily
    """
    julo_sms_client = get_julo_sms_client()
    msg = (
        'Klik link {} untuk melakukan verifikasi kamu di JULO.\n'
        'Pesan ini akan kedaluwarsa dalam 60 detik.'
    ).format(verification_link)
    phone_number = format_e164_indo_phone_number(phone_number)
    message, response = julo_sms_client.send_sms(phone_number, msg)
    response = response['messages'][0]

    return response

@task(queue='collection_high')
def populate_collection_risk_bucket_list():
    logger.info({
        'action': 'populate_collection_risk_bucket_list',
        'message': 'Intialzing the suffix population for collection rist bucket list'
    })
    sentry_client = get_julo_sentry_client()
    today = timezone.localtime(timezone.now())
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    # skip customer_id if already exists
    existing_customer_collection_risk = list(
        CollectionRiskVerificationCallList.objects.values_list('customer_id', flat=True)
    )

    customer_id_list_high = (
        CustomerHighLimitUtilization.objects.filter(
            cdate__gte=start_of_day, cdate__lt=end_of_day, is_high=True
        )
        .exclude(customer_id__in=existing_customer_collection_risk)
        .values_list('customer_id', flat=True)
    )

    for batch_customer_ids in batch_pk_query_with_cursor_with_custom_db(
        customer_id_list_high, batch_size=10000, database=JULO_ANALYTICS_DB
    ):
        collection_risk_verification_list = []
        for customer_id in batch_customer_ids:
            try:
                account = Account.objects.filter(customer_id=customer_id).last()
                if not account:
                    logger.error({'action': 'populate_collection_risk_bucket_list',
                                  'state': 'payload generation',
                                  'error': 'account for customer not found',
                                  'customer_id': customer_id})
                    continue
                oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
                application = account.get_active_application() or account.last_application()
                # set to False for now because require a lot of query
                is_connected = False
                is_verified = False
                is_paid_first_installment = account.accountpayment_set.filter(paid_date__isnull=False).exists()
                collection_risk_verification = CollectionRiskVerificationCallList(
                    application=application,
                    customer_id=customer_id,
                    account=account,
                    account_payment=oldest_unpaid_account_payment,
                    is_verified=is_verified,
                    is_connected=is_connected,
                    is_passed_minus_11=oldest_unpaid_account_payment.dpd > -11
                    if oldest_unpaid_account_payment
                    else False,
                    is_paid_first_installment=is_paid_first_installment,
                )
                collection_risk_verification_list.append(collection_risk_verification)
            except Exception as e:
                sentry_client.captureException()
                logger.error({'action': 'populate_collection_risk_bucket_list', 'state': 'payload generation', 'error': str(e)})
                continue

        # create CollectionRiskVerificationCallList for each batch
        if collection_risk_verification_list:
            CollectionRiskVerificationCallList.objects.bulk_create(
                collection_risk_verification_list
            )
            collection_risk_verification_list = []
            logger.info(
                {
                    'action': 'populate_collection_risk_bucket_list',
                    'state': 'payload generation',
                    'message': 'populate_collection_risk_bucket_list created successfully',
                }
            )
        else:
            logger.error(
                {
                    'action': 'populate_collection_risk_bucket_list',
                    'state': 'payload generation',
                    'error': 'no populate_collection_risk_bucket_list created',
                }
            )
    return

@task(queue='collection_high')
def update_collection_risk_bucket_list_passed_minus_11():
    logger.info({
        'action': 'update_collection_risk_bucket_list_passed_minus_11',
        'message': 'Intialzing the suffix population for collection rist bucket list'
    })
    sentry_client = get_julo_sentry_client()
    collection_risk_list_to_update=CollectionRiskVerificationCallList.objects.filter(
        is_passed_minus_11=False,
        ).values_list('id', flat=True)

    for collection_risk_batch in batch_pk_query_with_cursor(collection_risk_list_to_update, 10000):
        ids_to_bulk_update=[]
        for collection_risk_id in collection_risk_batch:
            try:
                collection_risk = CollectionRiskVerificationCallList.objects.filter(
                    id=collection_risk_id
                ).last()
                if collection_risk.account.dpd > -11:
                    ids_to_bulk_update.append(collection_risk.id)

            except Exception as err:
                sentry_client.captureException()
                logger.error(
                    {
                        'action': 'update_collection_risk_bucket_list_passed_minus_11',
                        'state': 'payload generation',
                        'error': str(err),
                    }
                )
                continue

        CollectionRiskVerificationCallList.objects.filter(id__in=ids_to_bulk_update).update(is_passed_minus_11=True)


def send_automated_comm_sms_j1_autodebet_only(streamlined_comm_id: int) -> None:
    """
    Processes account_payment expected to send as
    account-based product (J1, JTurbo) payment reminder

    Args:
        streamlined_comm_id (int): StreamlinedCommunication model id

    Returns:
        None
    """
    streamlined = StreamlinedCommunication.objects.get(pk=streamlined_comm_id)
    product = streamlined.product

    logger.info(
        {
            'action': 'send_automated_comm_sms_j1_autodebet_only',
            'streamlined_comm': streamlined,
            'template_code': streamlined.template_code,
            'message': 'Executing send_automated_comm_sms_j1',
        }
    )

    today = timezone.localtime(timezone.now())
    # Retry mechanism logic
    flag_key = 'send_automated_comm_sms_j1:{}'.format(streamlined_comm_id)

    retry_flag_obj = CommsRetryFlag.objects.filter(flag_key=flag_key).first()
    # If the flag exists and is non-expired, exclude retry and return
    if retry_flag_obj and not retry_flag_obj.is_flag_expired:
        # alert if the current flag is Starting.
        if retry_flag_obj.flag_status == CommsRetryFlagStatus.START:
            slack_message = (
                "<!here> *Template: {}* - send_automated_comm_sms_j1 (streamlined_id - {}) "
                "- *START... [flag={}]*"
            ).format(
                str(streamlined.template_code), str(streamlined_comm_id), retry_flag_obj.flag_status
            )
            send_slack_bot_message('alerts-comms-prod-sms', slack_message)
        return
    if not retry_flag_obj:
        retry_flag_obj = CommsRetryFlag.objects.create(
            flag_key=flag_key,
            flag_status=CommsRetryFlagStatus.START,
            expires_at=today.replace(hour=20, minute=0, second=0, microsecond=0),
        )
        logger.info(
            {
                'action': 'send_automated_comm_sms_j1_autodebet_only',
                'streamlined_comm': streamlined.template_code,
                'status': retry_flag_obj.flag_status,
                'message': 'RetryFlag obj created',
                'retry_flag': retry_flag_obj.id,
            }
        )

    # If the flag has expired or is in START/ITERATION status, send a Slack message
    if retry_flag_obj.is_flag_expired and retry_flag_obj.is_valid_for_alert:
        slack_message = (
            "<!here> *Template: {}* - send_automated_comm_sms_j1_autodebet_only (streamlined_id - {}) "
            "- *RETRYING... [flag={}]*"
        ).format(
            str(streamlined.template_code), str(streamlined_comm_id), retry_flag_obj.flag_status
        )
        send_slack_bot_message('alerts-comms-prod-sms', slack_message)

        logger.info(
            {
                'action': 'send_automated_comm_sms_j1_autodebet_only',
                'streamlined_comm': streamlined.template_code,
                'status': retry_flag_obj.flag_status,
                'message': 'flag expired , attempting retry',
                'retry_flag': retry_flag_obj.id,
            }
        )

    if 'autodebet' in streamlined.template_code:
        retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
        retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
        retry_flag_obj.save()
        logger.info(
            {
                'streamlined_comm': streamlined,
                'template_code': streamlined.template_code,
                'message': 'Rejected streamlined communication contains autodebet template code.',
                'retry_flag': retry_flag_obj.id,
                'flag_status': retry_flag_obj.flag_status,
            }
        )
        return

    date_of_day = today.date()
    # Get the start of the day (midnight)
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    # Get the end of the day (just before midnight)
    end_of_day = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    is_application = False
    if (
        (
            streamlined.status_code
            and streamlined.status_code_id >= ApplicationStatusCodes.LOC_APPROVED
        )
        or streamlined.dpd
        or streamlined.dpd_lower
        or streamlined.dpd_upper
        or streamlined.dpd == 0
    ):

        logger.info(
            {
                'action': 'send_automated_comm_sms_j1_autodebet_only',
                'streamlined_comm': streamlined,
                'template_code': streamlined.template_code,
                'message': 'Checking oldest_account_payment_ids is empty',
            }
        )

        product_lines = getattr(ProductLineCodes, streamlined.product.lower())()
        account_payment_query_filter = {
            'account__customer__can_notify': True,
            'account__application__product_line__product_line_code__in': product_lines,
        }

        # Filter the account status lookup based on the product.
        # This logic is needed for J1 and JTurbo because a single account might have
        # JTurbo and J1 product line code.
        if streamlined.product.lower() == Product.SMS.JTURBO:
            account_payment_query_filter.update(
                account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER,
            )
        elif streamlined.product.lower() == Product.SMS.J1:
            account_payment_query_filter.update(
                account__account_lookup__workflow__name=WorkflowConst.JULO_ONE,
            )

        if streamlined.dpd is not None:
            due_date = get_payment_due_date_by_delta(streamlined.dpd)
            account_payment_query_filter.update(due_date=due_date)
        if streamlined.dpd_lower is not None:
            dpd_lower_date = get_payment_due_date_by_delta(streamlined.dpd_lower)
            account_payment_query_filter.update(due_date__lte=dpd_lower_date)
        if streamlined.dpd_upper is not None:
            dpd_upper_date = get_payment_due_date_by_delta(streamlined.dpd_upper)
            account_payment_query_filter.update(due_date__gte=dpd_upper_date)
        if streamlined.status_code:
            status_code_identifier = str(streamlined.status_code_id)[:1]
            if status_code_identifier == '1':
                # application code status
                account_ids = (
                    Application.objects.filter(
                        application_status=streamlined.status_code.status_code
                    )
                    .distinct('account_id')
                    .values_list('account_id', flat=True)
                )
                account_payment_query_filter.update(account_id__in=account_ids)
            elif status_code_identifier == '2':
                # loan status code
                loan_account_ids = (
                    Loan.objects.filter(
                        account__application__product_line__product_line_code__in=product_lines,
                        loan_status_id=streamlined.status_code_id,
                    )
                    .distinct('account_id')
                    .values_list('account_id', flat=True)
                )
                account_payment_query_filter.update(account_id__in=list(loan_account_ids))
            elif status_code_identifier == '3':
                # payment status code
                account_payment_query_filter.update(status=streamlined.status_code_id)

        minimum_oldest_unpaid_account_payment_id = get_minimum_model_id(
            OldestUnpaidAccountPayment, date_of_day, 500000
        )

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM, is_active=True
        ).last()

        exclude_partner_end = dict()
        if feature_setting:
            partner_blacklist_config = feature_setting.parameters
            partner_config_end = []
            for partner_id in list(partner_blacklist_config.keys()):
                if partner_blacklist_config[partner_id] != 'end':
                    continue
                partner_config_end.append(partner_id)
                partner_blacklist_config.pop(partner_id)
            if partner_config_end:
                exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)

        query = (
            AccountPayment.objects.not_paid_active()
            .filter(**account_payment_query_filter)
            .extra(
                where=[
                    """EXISTS ( SELECT 1 FROM "oldest_unpaid_account_payment" U0
                    WHERE U0."oldest_unpaid_account_payment_id" >= %s
                    AND (U0."cdate" BETWEEN %s AND %s)
                    AND U0."dpd" = %s
                    AND U0."account_payment_id" = "account_payment"."account_payment_id")"""
                ],
                params=[
                    minimum_oldest_unpaid_account_payment_id,
                    start_of_day,
                    end_of_day,
                    streamlined.dpd,
                ],
            )
            .extra(
                where=[
                    """NOT ( "account"."status_code" IN %s
                    OR EXISTS ( SELECT 1 FROM "ptp" U0
                    WHERE U0."ptp_date" >= %s
                    AND U0."account_payment_id" = "account_payment"."account_payment_id"))"""
                ],
                params=[AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS, date_of_day],
            )
            .exclude(**exclude_partner_end)
        )

        # START experiment condition

        # LATE FEE EXPERIMENT
        query, _ = check_experiment_condition(
            MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            RedisKey.STREAMLINE_LATE_FEE_EXPERIMENT,
            streamlined,
            query,
            CardProperty.LATE_FEE_EARLIER_EXPERIMENT,
        )

        if query is None:
            retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
            retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
            retry_flag_obj.save()
            return

        # SMS AFTER ROBOCALL EXPERIMENT
        query, _ = check_experiment_condition(
            MinisquadExperimentConstants.SMS_AFTER_ROBOCALL,
            RedisKey.STREAMLINE_SMS_AFTER_ROBOCALL_EXPERIMENT,
            streamlined,
            query,
            CardProperty.SMS_AFTER_ROBOCALL_EXPERIMENT,
            experiment_identifier='experiment_group_2',
        )

        if query is None:
            return
        # END experiment condition

    else:
        is_application = True
        product_lines = getattr(ProductLineCodes, streamlined.product.lower())()
        query = Application.objects.filter(
            product_line__product_line_code__in=product_lines,
        )
        if not streamlined.status_code:
            logger.error(
                {
                    'action': 'send_automated_comm_sms_j1_autodebet_only',
                    'reason': 'cannot send to all application without status code',
                    'streamlined_code': streamlined_comm_id,
                }
            )
            retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
            retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
            retry_flag_obj.save()
            return

        status_code_identifier = str(streamlined.status_code_id)[:1]
        if status_code_identifier == '1':
            # application code status
            query = query.filter(application_status_id=streamlined.status_code_id)
        elif status_code_identifier == '2':
            # TODO: Potentially redundant as status code >190 cannot reach here
            # loan status code
            application_ids = Loan.objects.filter(
                loan_status_id=streamlined.status_code_id,
                application__product_line__product_line_code__in=product_lines,
            ).values_list('application_id', flat=True)
            query = query.filter(id__in=list(application_ids))
        elif status_code_identifier == '3':
            # TODO: Potentially redundant as status code >190 cannot reach here
            # payment status code
            loan_ids = (
                Payment.objects.filter(
                    account_payment__isnull=False, payment_status_id=streamlined.status_code_id
                )
                .distinct('loan')
                .values_list('loan_id', flat=True)
            )
            application_ids = Loan.objects.filter(id__in=list(loan_ids)).values_list(
                'application_id', flat=True
            )
            query = query.filter(id__in=list(application_ids))

    # Autodebet Streamline
    autodebet_streamlined = None
    account_use_autodebet = False
    if not is_application and streamlined.dpd and streamlined.dpd in autodebet_sms_dpds:
        autodebet_streamlined = StreamlinedCommunication.objects.filter(
            template_code='{}_sms_autodebet_dpd_{}'.format(product, streamlined.dpd),
            communication_platform=CommunicationPlatform.SMS,
            is_automated=True,
            dpd__isnull=False,
        ).last()

    if not autodebet_streamlined:
        return "Autodebet Streamlined Communication not found"

    query = filter_streamlined_based_on_partner_selection(streamlined, query)
    # take out dpd -7 for experiment
    if streamlined.template_code == '{}_sms_dpd_-7'.format(product):
        experiment_setting_take_out_dpd_minus_7 = get_caller_experiment_setting(
            StreamlinedExperimentConst.SMS_MINUS_7_TAKE_OUT_EXPERIMENT
        )
        if experiment_setting_take_out_dpd_minus_7:
            (
                query,
                experiment_account_payment_ids,
            ) = take_out_account_payment_for_experiment_dpd_minus_7(
                query, experiment_setting_take_out_dpd_minus_7
            )
            write_data_to_experiment_group.delay(
                experiment_setting_take_out_dpd_minus_7.id,
                list(query.values_list('id', flat=True)),
                experiment_account_payment_ids,
            )

    logger.info(
        {
            'action': 'send_automated_comm_sms_j1_autodebet_only',
            'streamlined_comm': streamlined,
            'template_code': streamlined.template_code,
            'message': 'Starting to iterate',
        }
    )

    account_payment_processed = 0
    autodebet_account_ids = []
    total_customer = 0
    total_non_autodebet = 0
    # julo gold
    query = determine_julo_gold_for_streamlined_communication(streamlined.julo_gold_status, query)
    for application_or_account_payment in query.iterator():
        retry_flag_obj.flag_status = CommsRetryFlagStatus.ITERATION
        retry_flag_obj.expires_at = retry_flag_obj.calculate_expires_at(1)
        retry_flag_obj.save()

        logger_data = {
            'action': 'send_automated_comm_sms_j1_autodebet_only',
            'application_or_account_payment': application_or_account_payment.pk,
            'is_application': is_application,
            'retry_flag': retry_flag_obj.id,
            'flag_status': retry_flag_obj.flag_status,
            'message': 'Query in loop iteration',
        }

        if not is_application:
            # validation comms block
            if check_account_payment_is_blocked_comms(application_or_account_payment, 'sms'):
                logger.info({**logger_data, 'message': 'customer got comms block for sms'})
                continue

            sent_sms = SmsHistory.objects.filter(
                cdate__date=date_of_day,
                template_code__in=[
                    streamlined.template_code,
                    '{}_sms_autodebet_dpd_{}'.format(product, streamlined.dpd),
                ],
                account_payment=application_or_account_payment,
            ).last()

            if sent_sms:
                logger.info(
                    {
                        **logger_data,
                        'last_sent_sms': sent_sms.id,
                        'message': 'Ignore sending due to existing sms history.',
                    }
                )
                continue

        logger.info({**logger_data, 'message': 'Processing data for SMS sending.'})

        total_customer += 1
        current_streamlined = streamlined
        if autodebet_streamlined:
            autodebet_account = get_existing_autodebet_account(
                application_or_account_payment.account
            )
            if not autodebet_account or not autodebet_account.is_use_autodebet:
                total_non_autodebet += 1
                logger.info({**logger_data, 'message': 'Account is not using autodebet.'})
                continue

            if autodebet_account and autodebet_account.is_use_autodebet:
                account_use_autodebet = True
                current_streamlined = autodebet_streamlined

                autodebet_account_ids.append(application_or_account_payment.account.id)
                if is_experiment_group_autodebet(application_or_account_payment.account):
                    logger.info(
                        {**logger_data, 'message': 'Autodebet SMS excluded for experiment.'}
                    )
                    continue

        processed_message = process_sms_message_j1(
            current_streamlined.message.message_content,
            application_or_account_payment,
            is_have_account_payment=not is_application,
        )

        logger.info(
            {
                **logger_data,
                'account_use_autodebet': account_use_autodebet,
                'streamlined_comm': current_streamlined,
                'template_code': current_streamlined.template_code,
                'message': 'Processed SMS message.',
            }
        )

        send_automated_comm_sms_j1_subtask.delay(
            application_or_account_payment.id,
            processed_message,
            current_streamlined.template_code,
            current_streamlined.type,
            is_application=is_application,
        )
        account_payment_processed += 1

    # Experiment Autodebet Data Storing
    store_autodebet_streamline_experiment.delay(autodebet_account_ids)

    retry_flag_obj.flag_status = CommsRetryFlagStatus.FINISH
    retry_flag_obj.expires_at = today.replace(hour=20, minute=0, second=0, microsecond=0)
    retry_flag_obj.save()
    logger.info(
        {
            'action': 'send_automated_comm_sms_j1_autodebet_only',
            'streamlined_comm': streamlined,
            'template_code': streamlined.template_code,
            'message': 'Iteration complete. Processed {} account payment'.format(
                account_payment_processed
            ),
            'retry_flag': retry_flag_obj.id,
            'flag_status': retry_flag_obj.flag_status,
        }
    )

    slack_message = (
        "*Template: {}* - send_automated_comm_sms_j1_autodebet_only (streamlined_id - {})".format(
            str(streamlined.template_code), str(streamlined_comm_id)
        )
    )
    send_slack_bot_message('alerts-comms-prod-sms', slack_message)
    return {
        'template_code': str(autodebet_streamlined.template_code),
        'total_sent': account_payment_processed,
        'total_customer': total_customer,
        'total_non_autodebet': total_non_autodebet,
        'total_experiment': len(autodebet_account_ids),
    }


@task(queue='loan_normal')
def send_pn_invalidate_caching_point_change(customer_id):
    pn = get_julo_pn_client()
    device = Device.objects.filter(customer_id=customer_id).last()
    if not device or not device.gcm_reg_id:
        return

    pn.pn_point_change(device.gcm_reg_id, customer_id)


@task(queue='repayment_normal')
def send_email_bni_va_suffix_limit_task(prefix_group, remaining_count):
    message = (
        'Dear Team of Repayments,\n'
        'This is a message from Julo Repayment MVP to alert on our BNI Virtual Account Suffix quota '
        'for prefix {} is near the limit.\n'
        'Currently there are only {} suffix remaining.\n'
        'Please check whether we still have prefix quota left, otherwise please '
        'add more BNI Virtual Account Suffix immediately!'
    ).format(prefix_group, remaining_count)
    julo_email_client = get_julo_email_client()
    julo_email_client.email_bni_va_limit(message)

    logger.info(
        {
            "action": "send_email_bni_va_suffix_limit_task",
            "prefix_group": prefix_group,
            "remaining_count": remaining_count,
        }
    )
