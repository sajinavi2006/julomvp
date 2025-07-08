from __future__ import division
from builtins import map
from builtins import str
from builtins import range

from babel.dates import format_datetime
from past.utils import old_div
import logging
import redis
import ast

from itertools import chain
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta, time
from datetime import date

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction, IntegrityError
from django.db.models import Count, When, Case, IntegerField, F, ExpressionWrapper, Q, Prefetch
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.auth.models import User

from juloserver.julo.models import (
    Payment,
    Partner,
    Loan,
    Agent,
    SkiptraceResultChoice,
    SkiptraceHistory,
    PaymentMethod,
    SkiptraceHistoryCentereix,
    CustomerCampaignParameter,
    CampaignSetting,
    ExperimentSetting,
    PaymentNote,
    PTP,
    Skiptrace,
    FeatureSetting,
    CommsBlocked,
    Application,
    FDCInquiryLoan
)
from juloserver.julo.constants import (
    WaiveCampaignConst,
    ExperimentConst,
    WorkflowConst,
    FeatureNameConst,
    PTPStatus,
    InAppPTPDPD,
)
from juloserver.julo.constants import BucketConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.partners import PartnerConstant
from .models import (
    CollectionHistory,
    CollectionSquad,
    CommissionLookup,
    CollectionSquadAssignment,
    SentToCenterixLog,
    VendorQualityExperiment,
    SentToDialer,
    NotSentToDialer,
    intelixBlacklist,
    CallbackPromiseApp,
    CollectionBucketInhouseVendor,
    AccountDueAmountAbove2Mio,
    VendorRecordingDetail,
)
from .constants import (
    Threshold,
    SquadNames,
    RedisKey,
    CenterixCallResult,
    CollectedBy,
    DialerVendor,
    IntelixIcareIncludedCompanies,
    IntelixTeam,
    ReasonNotSentToDialer,
    IntelixResultChoiceMapping,
    DialerSystemConst,
    DEFAULT_DB,
    AiRudder,
)
from juloserver.minisquad.constants import FeatureNameConst as MinisquadFeatureSettings
from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_julo_centerix_client,
    get_julo_email_client,
)
from .models import (
    CollectionHistory,
    CollectionSquad,
    CommissionLookup,
    CollectionSquadAssignment,
    SentToCenterixLog,
    VendorQualityExperiment,
    SentToDialer,
    NotSentToDialer,
    intelixBlacklist,
    CallbackPromiseApp,
    CollectionBucketInhouseVendor,
)
from .constants import (
    Threshold,
    SquadNames,
    RedisKey,
    CenterixCallResult,
    CollectedBy,
    DialerVendor,
    IntelixIcareIncludedCompanies,
    IntelixTeam,
    ReasonNotSentToDialer,
    IntelixResultChoiceMapping,
    DEFAULT_DB,
    AiRudder,
)
from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_julo_centerix_client,
    get_julo_email_client,
)
from juloserver.minisquad.clients import get_julo_field_collection_client
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes, JuloOneCodes
from juloserver.collectionbucket.models import CollectionAgentTask, CollectionRiskVerificationCallList
from juloserver.julo.services2 import get_redis_client
from .utils import parse_string_to_dict
from ..account.constants import AccountConstant
from juloserver.apiv2.models import (
    PdCollectionModelResult,
    PdBTTCModelResult,
)
from juloserver.monitors.notifications import (
    get_slack_bot_client,
    notify_fail_exclude_account_ids_collection_field_ai_rudder,
)
from juloserver.julo.services2 import get_customer_service
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest, LoanRefinancingRequestCampaign)
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from ..collection_vendor.models import SubBucket, CollectionVendorAssignment
from juloserver.account_payment.models import (
    AccountPayment
)
from juloserver.account.models import (Account, AccountLookup, ExperimentGroup)
from juloserver.grab.constants import GRAB_INTELIX_CALL_DELAY_DAYS
from juloserver.collection_vendor.services import (
    get_assigned_b4_account_payment_ids_to_vendors, b3_vendor_distribution)
from juloserver.autodebet.models import AutodebetAccount
from juloserver.grab.models import GrabSkiptraceHistory
from typing import List
from juloserver.ana_api.models import B2ExcludeFieldCollection, B3ExcludeFieldCollection
from django.db import connections
from juloserver.pii_vault.constants import PiiSource
from juloserver.minisquad.utils import collection_detokenize_sync_kv_in_bulk

logger = logging.getLogger(__name__)


def get_payment_details_for_calling(payment_bucket, experiment_setting=None):
    from juloserver.julo.services2.experiment import check_cootek_experiment

    today = timezone.localtime(timezone.now()).date()
    today_minus_4 = today - relativedelta(days=4)
    loans_pending_refinancing = LoanRefinancingRequest.objects.values_list('loan', flat=True).filter(
        status=CovidRefinancingConst.STATUSES.approved,
        udate__date__gte=today_minus_4,
        udate__date__lt=today,
    )

    bucket_1_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_1_DPD['to'] - 3)
    bucket_1_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_1_DPD['to'])
    bucket_2_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_2_DPD['to'] - 3)
    bucket_2_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_2_DPD['to'])
    bucket_3_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_3_DPD['to'] - 3)
    bucket_3_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_3_DPD['to'])
    bucket_4_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_4_DPD['to'] - 3)
    bucket_4_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_4_DPD['to'])
    payments_refinancing = Payment.objects.values_list('id', flat=True).filter(
        loan_id__in=loans_pending_refinancing).filter(
        ~Q(due_date__range=[bucket_1_dpd_date_from, bucket_1_dpd_date_to]) &
        ~Q(due_date__range=[bucket_2_dpd_date_from, bucket_2_dpd_date_to]) &
        ~Q(due_date__range=[bucket_3_dpd_date_from, bucket_3_dpd_date_to]) &
        ~Q(due_date__range=[bucket_4_dpd_date_from, bucket_4_dpd_date_to])
    )

    payments = []
    qs = Payment.objects.not_paid_active().filter(
        account_payment_id__isnull=True,
        loan__account_id__isnull=True).exclude(id__in=payments_refinancing)
    not_sent_to_dialer_payment = []
    qs_payments_excluded_because_partner = None
    qs_payments_excluded_because_partner_icare = None
    if payment_bucket == IntelixTeam.JULO_T0 or payment_bucket == IntelixTeam.JULO_T_1:
        exclude_partner_ids = Partner.objects.filter(
            name__in=PartnerConstant.form_partner()) \
            .values_list('id', flat=True)
        payments_excluded_because_partner = qs.filter(
            loan__application__partner__id__in=exclude_partner_ids).extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PARTNER_ACCOUNT']}).values("id", "reason")
        not_sent_to_dialer_payment += list(payments_excluded_because_partner)
        qs = qs.exclude(loan__application__partner__id__in=exclude_partner_ids)
    else:
        exclude_partner_ids = Partner.objects.filter(
            name__in=PartnerConstant.excluded_partner_intelix())\
            .values_list('id', flat=True)
        qs_payments_excluded_because_partner = qs.filter(
            loan__application__partner__id__in=exclude_partner_ids)
        qs = qs.exclude(loan__application__partner__id__in=exclude_partner_ids)
        icare_partner_id = Partner.objects.filter(name=PartnerConstant.ICARE_PARTNER) \
            .values_list('id', flat=True)
        qs_payments_excluded_because_partner_icare = qs.filter(
            Q(loan__application__partner__id__in=icare_partner_id,
              loan__application__product_line__product_line_code__in=ProductLineCodes.icare()),
            ~Q(loan__application__company_name__in=IntelixIcareIncludedCompanies.ICARE_COMPANIES))
        qs = qs.exclude(Q(loan__application__partner__id__in=icare_partner_id,
                          loan__application__product_line__product_line_code__in=ProductLineCodes.
                          icare()),
                        ~Q(loan__application__company_name__in=IntelixIcareIncludedCompanies.
                           ICARE_COMPANIES))

    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
    cached_excluded_payment_bucket_level_ids = redisClient.get_list(
        RedisKey.EXCLUDED_BUCKET_LEVEL_PAYMENT_IDS
    )

    assigned_loan_ids = []

    if not cached_oldest_payment_ids:
        if payment_bucket == IntelixTeam.JULO_T0 or payment_bucket == IntelixTeam.JULO_T_1:
            oldest_payment_ids = get_oldest_payment_ids_loans()
        else:
            oldest_payment_ids = get_oldest_payment_ids_loans(is_intelix=True)

        if oldest_payment_ids:
            redisClient.set_list(RedisKey.OLDEST_PAYMENT_IDS, oldest_payment_ids, timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    if not cached_excluded_payment_bucket_level_ids:
        excluded_bucket_level_loan_ids = SkiptraceHistory.objects.filter(
            excluded_from_bucket=True,
            loan_id__isnull=False
        ).order_by('loan', '-cdate').distinct('loan').values_list('loan', flat=True)

        if excluded_bucket_level_loan_ids:
            redisClient.set_list(
                RedisKey.EXCLUDED_BUCKET_LEVEL_PAYMENT_IDS,
                excluded_bucket_level_loan_ids, timedelta(hours=4))
    else:
        excluded_bucket_level_loan_ids = list(map(
            int,
            cached_excluded_payment_bucket_level_ids))
    excluded_ptp_loan_ids = exclude_ptp_payment_loan_ids()
    # For daily data
    qs_excluded_payment_by_loan_status = Payment.objects.filter(
        loan__loan_status_id__in=(
            LoanStatusCodes.INACTIVE, LoanStatusCodes.PAID_OFF,
            LoanStatusCodes.SELL_OFF, LoanStatusCodes.DRAFT),
        payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
        is_restructured=False
    )
    qs_payments_excluded_by_pending_refinancing = Payment.objects.not_paid_active().filter(
        id__in=payments_refinancing)
    excluded_payment_by_loan_status = None
    excluded_payments_by_pending_refinancing = None
    excluded_payments_because_partner = None
    excluded_payments_because_partner_icare = None
    # Bucket 1 data
    if payment_bucket == 'JULO_T0':
        excluded_loan_ids = list(chain(assigned_loan_ids, excluded_ptp_loan_ids))
        payments = qs.bucket_1_t0(excluded_loan_ids)
        payments = payments.filter(id__in=oldest_payment_ids)
        payments = check_cootek_experiment(payments, 0)
    elif payment_bucket == 'JULO_T-1':
        excluded_loan_ids = list(chain(assigned_loan_ids, excluded_ptp_loan_ids))
        payments = qs.bucket_1_t_minus_1(excluded_loan_ids)
        payments = payments.filter(id__in=oldest_payment_ids)
        payments = check_cootek_experiment(payments, -1)
    elif payment_bucket == 'JULO_T1-T4':
        excluded_loan_ids = list(chain(assigned_loan_ids, excluded_ptp_loan_ids))
        payments = qs.bucket_1_t1_t4(excluded_loan_ids)
        payments = payments.filter(id__in=oldest_payment_ids)
    elif payment_bucket == 'JULO_T5-T10':
        excluded_loan_ids = list(chain(assigned_loan_ids, excluded_ptp_loan_ids))
        payments = qs.bucket_1_t5_t10(excluded_loan_ids)
        payments = payments.filter(id__in=oldest_payment_ids)
    elif payment_bucket == 'JULO_B1':
        excluded_loan_ids = list(chain(
            assigned_loan_ids,
            excluded_bucket_level_loan_ids,
            excluded_ptp_loan_ids))
        payments = qs.bucket_1_t1_t10(excluded_loan_ids)
        payments = payments.filter(id__in=oldest_payment_ids)
        not_sent_payments = qs.bucket_1_t1_t10(None, only_base_query=True).filter(
            id__in=oldest_payment_ids
        )
        if excluded_bucket_level_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(loan_id__in=excluded_bucket_level_loan_ids))
            not_sent_payments = not_sent_payments.exclude(
                loan_id__in=excluded_bucket_level_loan_ids)
        if excluded_ptp_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(loan_id__in=excluded_ptp_loan_ids))
            not_sent_payments = not_sent_payments.exclude(
                loan_id__in=excluded_ptp_loan_ids)

        not_sent_filter_criteria = dict(
            is_collection_called=True,
            loan__is_ignore_calls=True, is_whatsapp=True,
        )
        not_sent_reasons = [
            ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED_AND_WHATSAPP'],
            ReasonNotSentToDialer.UNSENT_REASON['IGNORE_CALLS'],
        ]

        not_sent_to_dialer_payment += format_not_sent_payment(
            not_sent_payments, not_sent_reasons, not_sent_filter_criteria,
            extra_field="case when loan.loan_status_code in (210, 250, 260) "
                        "then concat(', Loan Status is ', loan.loan_status_code) else '' end ")
        excluded_payment_by_loan_status = qs_excluded_payment_by_loan_status.bucket_1_t1_t10(
            None, only_base_query=True)
        excluded_payments_by_pending_refinancing = qs_payments_excluded_by_pending_refinancing.\
            bucket_1_t1_t10(None, only_base_query=True)
        excluded_payments_because_partner = qs_payments_excluded_because_partner.\
            bucket_1_t1_t10(None, only_base_query=True).exclude(loan_id__in=excluded_loan_ids)
        excluded_payments_because_partner_icare = qs_payments_excluded_because_partner_icare.\
            bucket_1_t1_t10(None, only_base_query=True).exclude(loan_id__in=excluded_loan_ids)
    # Bucket 2 data
    elif payment_bucket == 'JULO_B2':
        excluded_loan_ids = list(chain(
            assigned_loan_ids,
            excluded_bucket_level_loan_ids,
            excluded_ptp_loan_ids))
        payment_t11_to_t40 = qs.bucket_list_t11_to_t40(is_intelix=True).\
            exclude(loan_id__in=excluded_loan_ids)
        payments = payment_t11_to_t40.filter(id__in=oldest_payment_ids)
        not_sent_payment_t11_to_t40 = qs.bucket_list_t11_to_t40(
            is_intelix=True, only_base_query=True).filter(id__in=oldest_payment_ids)
        if excluded_bucket_level_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payment_t11_to_t40, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(loan_id__in=excluded_bucket_level_loan_ids))
            not_sent_payment_t11_to_t40 = not_sent_payment_t11_to_t40.exclude(
                loan_id__in=excluded_bucket_level_loan_ids)
        if excluded_ptp_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payment_t11_to_t40, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(loan_id__in=excluded_ptp_loan_ids))
            not_sent_payment_t11_to_t40 = not_sent_payment_t11_to_t40.exclude(
                loan_id__in=excluded_ptp_loan_ids)

        not_sent_filter_criteria = dict(
            is_collection_called=True,
            loan__is_ignore_calls=True, is_whatsapp=True,
        )
        not_sent_reasons = [
            ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED_AND_WHATSAPP'],
            ReasonNotSentToDialer.UNSENT_REASON['IGNORE_CALLS'],
        ]
        not_sent_to_dialer_payment += format_not_sent_payment(
            not_sent_payment_t11_to_t40, not_sent_reasons, not_sent_filter_criteria)
        excluded_payment_by_loan_status = qs_excluded_payment_by_loan_status.determine_bucket_by_range(
            [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']])
        excluded_payments_by_pending_refinancing = qs_payments_excluded_by_pending_refinancing\
            .bucket_list_t11_to_t40(is_intelix=True, only_base_query=True)
        excluded_payments_because_partner = qs_payments_excluded_because_partner\
            .bucket_list_t11_to_t40(is_intelix=True, only_base_query=True).\
            exclude(loan_id__in=excluded_loan_ids)
        excluded_payments_because_partner_icare = qs_payments_excluded_because_partner_icare\
            .bucket_list_t11_to_t40(is_intelix=True, only_base_query=True).\
            exclude(loan_id__in=excluded_loan_ids)

    elif payment_bucket == 'JULO_B2.S1':
        squad = CollectionSquad.objects.get_or_none(squad_name=SquadNames.COLLECTION_BUCKET_2_SQUAD_1)
        if squad is None:
            return payments

        payments = CollectionHistory.objects.get_bucket_t11_to_t40(squad.id)
    elif payment_bucket == 'JULO_B2.S2':
        squad = CollectionSquad.objects.get_or_none(squad_name=SquadNames.COLLECTION_BUCKET_2_SQUAD_2)
        if squad is None:
            return payments

        payments = CollectionHistory.objects.get_bucket_t11_to_t40(squad.id)
    # Bucket 3 data
    elif payment_bucket == 'JULO_B3':
        excluded_loan_ids = list(chain(
            assigned_loan_ids,
            excluded_bucket_level_loan_ids,
            excluded_ptp_loan_ids))
        payment_t41_to_t70 = qs.bucket_list_t41_to_t70(is_intelix=True). \
            exclude(loan_id__in=excluded_loan_ids)
        payments = payment_t41_to_t70.filter(id__in=oldest_payment_ids)
        not_sent_payment_t41_to_t70 = qs.bucket_list_t41_to_t70(
            is_intelix=True, only_base_query=True).filter(id__in=oldest_payment_ids)
        if excluded_bucket_level_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payment_t41_to_t70, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(loan_id__in=excluded_bucket_level_loan_ids))
            not_sent_payment_t41_to_t70 = not_sent_payment_t41_to_t70.exclude(
                loan_id__in=excluded_bucket_level_loan_ids)

        if excluded_ptp_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payment_t41_to_t70, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(loan_id__in=excluded_ptp_loan_ids))
            not_sent_payment_t41_to_t70 = not_sent_payment_t41_to_t70.exclude(
                loan_id__in=excluded_ptp_loan_ids)

        not_sent_filter_criteria = dict(
            is_collection_called=True,
            loan__is_ignore_calls=True, is_whatsapp=True,
        )
        not_sent_reasons = [
            ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED_AND_WHATSAPP'],
            ReasonNotSentToDialer.UNSENT_REASON['IGNORE_CALLS'],
        ]
        not_sent_to_dialer_payment += format_not_sent_payment(
            not_sent_payment_t41_to_t70, not_sent_reasons, not_sent_filter_criteria)
        excluded_payment_by_loan_status = qs_excluded_payment_by_loan_status.determine_bucket_by_range(
            [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']])
        excluded_payments_by_pending_refinancing = qs_payments_excluded_by_pending_refinancing.\
            bucket_list_t41_to_t70(is_intelix=True, only_base_query=True)
        excluded_payments_because_partner = qs_payments_excluded_because_partner.\
            bucket_list_t41_to_t70(is_intelix=True, only_base_query=True).\
            exclude(loan_id__in=excluded_loan_ids)
        excluded_payments_because_partner_icare = qs_payments_excluded_because_partner_icare.\
            bucket_list_t41_to_t70(is_intelix=True, only_base_query=True).\
            exclude(loan_id__in=excluded_loan_ids)

    elif payment_bucket == 'JULO_B3.S1':
        squad = CollectionSquad.objects.get_or_none(squad_name=SquadNames.COLLECTION_BUCKET_3_SQUAD_1)
        if squad is None:
            return payments

        payments = CollectionHistory.objects.get_bucket_t41_to_t70(squad.id)
    elif payment_bucket == 'JULO_B3.S2':
        squad = CollectionSquad.objects.get_or_none(squad_name=SquadNames.COLLECTION_BUCKET_3_SQUAD_2)
        if squad is None:
            return payments

        payments = CollectionHistory.objects.get_bucket_t41_to_t70(squad.id)
    elif payment_bucket == 'JULO_B3.S3':
        squad = CollectionSquad.objects.get_or_none(squad_name=SquadNames.COLLECTION_BUCKET_3_SQUAD_3)
        if squad is None:
            return payments

        payments = CollectionHistory.objects.get_bucket_t41_to_t70(squad.id)
    # Bucket 4 data
    elif payment_bucket == 'JULO_B4':
        excluded_loan_ids = list(chain(
            assigned_loan_ids,
            excluded_bucket_level_loan_ids,
            excluded_ptp_loan_ids))

        payment_t71_to_t100 = qs.bucket_list_t71_to_t90(is_intelix=True).\
            exclude(loan_id__in=excluded_loan_ids)
        payments = payment_t71_to_t100.filter(id__in=oldest_payment_ids)
        not_sent_payment_t71_to_t100 = qs.bucket_list_t71_to_t90(
            is_intelix=True, only_base_query=True).filter(id__in=oldest_payment_ids)
        if excluded_bucket_level_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payment_t71_to_t100, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(loan_id__in=excluded_bucket_level_loan_ids))
            not_sent_payment_t71_to_t100 = not_sent_payment_t71_to_t100.exclude(
                loan_id__in=excluded_bucket_level_loan_ids)
        if excluded_ptp_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payment_t71_to_t100, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(loan_id__in=excluded_ptp_loan_ids))
            not_sent_payment_t71_to_t100 = not_sent_payment_t71_to_t100.exclude(
                loan_id__in=excluded_ptp_loan_ids)

        not_sent_filter_criteria = dict(
            is_collection_called=True,
            loan__is_ignore_calls=True, is_whatsapp=True,
        )
        not_sent_reasons = [
            ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED_AND_WHATSAPP'],
            ReasonNotSentToDialer.UNSENT_REASON['IGNORE_CALLS'],
        ]

        not_sent_to_dialer_payment += format_not_sent_payment(
            not_sent_payment_t71_to_t100, not_sent_reasons, not_sent_filter_criteria)
        excluded_payment_by_loan_status = qs_excluded_payment_by_loan_status.determine_bucket_by_range(
            [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']])
        excluded_payments_by_pending_refinancing = qs_payments_excluded_by_pending_refinancing.\
            bucket_list_t71_to_t90(is_intelix=True, only_base_query=True)
        excluded_payments_because_partner = qs_payments_excluded_because_partner.\
            bucket_list_t71_to_t90(is_intelix=True, only_base_query=True).\
            exclude(loan_id__in=excluded_loan_ids)
        excluded_payments_because_partner_icare = qs_payments_excluded_because_partner_icare.\
            bucket_list_t71_to_t90(is_intelix=True, only_base_query=True).\
            exclude(loan_id__in=excluded_loan_ids)

    elif payment_bucket == 'JULO_B4.S1':
        squad = CollectionSquad.objects.get_or_none(squad_name=SquadNames.COLLECTION_BUCKET_4_SQUAD_1)
        if squad is None:
            return payments
        payments = CollectionHistory.objects.get_bucket_t71_to_t90(squad.id)
    elif payment_bucket == 'JULO_B5':
        sub_bucket = SubBucket.sub_bucket_five(1)
        assigned_to_vendor = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True,
            payment__isnull=False
        ).distinct('payment__loan_id').values_list("payment__loan_id", flat=True)
        payments = qs.get_sub_bucket_5_1_special_case(
            sub_bucket.end_dpd).filter(id__in=oldest_payment_ids).exclude(
            loan_id__in=assigned_to_vendor
        )
        unsent_payments = qs.get_sub_bucket_5_1_special_case(
            sub_bucket.end_dpd).filter(id__in=oldest_payment_ids)
        not_sent_filter_criteria = dict(
            loan_id__in=assigned_to_vendor
        )
        not_sent_to_dialer_payment += format_not_sent_payment(
            unsent_payments, ReasonNotSentToDialer.UNSENT_REASON['LOAN_TO_THIRD_PARTY'], not_sent_filter_criteria)
        excluded_payment_by_loan_status = qs_excluded_payment_by_loan_status.\
            get_sub_bucket_5_1_special_case(sub_bucket.end_dpd)
        excluded_payments_by_pending_refinancing = qs_payments_excluded_by_pending_refinancing.\
            get_sub_bucket_5_1_special_case(sub_bucket.end_dpd)
        excluded_payments_because_partner = qs_payments_excluded_because_partner.\
            get_sub_bucket_5_1_special_case(sub_bucket.end_dpd)
        excluded_payments_because_partner_icare = qs_payments_excluded_because_partner_icare.\
            get_sub_bucket_5_1_special_case(sub_bucket.end_dpd)

    elif payment_bucket in ('JULO_B6_1', 'JULO_B6_2'):
        sub_bucket = SubBucket.sub_bucket_six(int(payment_bucket[-1]))
        assigned_to_vendor = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True,
            payment__isnull=False
        ).distinct('payment__loan_id').values_list("payment__loan_id", flat=True)
        payments = qs.get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd).filter(
            id__in=oldest_payment_ids).exclude(loan_id__in=assigned_to_vendor)
        unsent_payments = qs.get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd).filter(
            id__in=oldest_payment_ids)
        not_sent_filter_criteria = dict(
            loan_id__in=assigned_to_vendor
        )
        not_sent_to_dialer_payment += format_not_sent_payment(
            unsent_payments, ReasonNotSentToDialer.UNSENT_REASON['LOAN_TO_THIRD_PARTY'], not_sent_filter_criteria)
        excluded_payment_by_loan_status = qs_excluded_payment_by_loan_status.get_sub_bucket_5_by_range(
            sub_bucket.start_dpd, sub_bucket.end_dpd)
        excluded_payments_by_pending_refinancing = qs_payments_excluded_by_pending_refinancing.\
            get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)
        excluded_payments_because_partner = qs_payments_excluded_because_partner.\
            get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)
        excluded_payments_because_partner_icare = qs_payments_excluded_because_partner_icare.\
            get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)

    elif payment_bucket == 'PTP':
        payments = CollectionHistory.objects.get_bucket_ptp_data_all_agent()

    elif payment_bucket == 'JULO_B1_NON_CONTACTED':
        non_contact_bucket_payments = qs.bucket_1_t1_t10(excluded_ptp_loan_ids).filter(
            loan_id__in=excluded_bucket_level_loan_ids
        )
        non_contact_bucket_payments = non_contact_bucket_payments.filter(
            id__in=oldest_payment_ids)

        # record not sent to intelix
        not_sent_payments = qs.bucket_1_t1_t10(None, only_base_query=True).filter(
            id__in=oldest_payment_ids
        )
        not_sent_to_dialer_payment = []
        if excluded_ptp_loan_ids:
            not_sent_to_dialer_payment += format_not_sent_payment(
                not_sent_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(loan_id__in=excluded_ptp_loan_ids))
            not_sent_payments = not_sent_payments.exclude(
                loan_id__in=excluded_ptp_loan_ids)

        return non_contact_bucket_payments, not_sent_to_dialer_payment

    elif payment_bucket == 'JULO_B2_NON_CONTACTED':
        squad_ids = CollectionSquad.objects\
            .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_2)\
            .values_list('id', flat=True)
        non_contact_squad_payments = CollectionHistory.objects\
            .get_bucket_non_contact_squads(squad_ids)

        non_contact_bucket_payments = qs.bucket_list_t11_to_t40(is_intelix=True).\
            exclude(loan_id__in=excluded_ptp_loan_ids).filter(
                loan_id__in=excluded_bucket_level_loan_ids
                )
        non_contact_bucket_payments = non_contact_bucket_payments.filter(id__in=oldest_payment_ids)

        unsent_non_contact_bucket_payments = SkiptraceHistory.objects.\
            get_non_contact_bucket2().filter(
                loan__id__in=excluded_ptp_loan_ids
        ).extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW']})\
            .values("payment_id", "reason")
        not_sent_to_dialer_payment += list(unsent_non_contact_bucket_payments)

        return non_contact_squad_payments, non_contact_bucket_payments, not_sent_to_dialer_payment

    elif payment_bucket == 'JULO_B3_NON_CONTACTED':
        squad_ids = CollectionSquad.objects\
            .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_3)\
            .values_list('id', flat=True)
        non_contact_squad_payments = CollectionHistory.objects\
            .get_bucket_non_contact_squads(squad_ids)

        non_contact_bucket_payments = qs.bucket_list_t41_to_t70(is_intelix=True). \
            exclude(loan_id__in=excluded_ptp_loan_ids).filter(
                loan_id__in=excluded_bucket_level_loan_ids)
        non_contact_bucket_payments = non_contact_bucket_payments.filter(id__in=oldest_payment_ids)

        unsent_non_contact_bucket_payments = SkiptraceHistory.objects.get_non_contact_bucket3().filter(
            loan__id__in=excluded_ptp_loan_ids
        ).extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW']}) \
            .values("payment_id", "reason")
        not_sent_to_dialer_payment += list(unsent_non_contact_bucket_payments)
        return non_contact_squad_payments, non_contact_bucket_payments, not_sent_to_dialer_payment

    elif payment_bucket == 'JULO_B4_NON_CONTACTED':
        squad_ids = CollectionSquad.objects\
            .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_4)\
            .values_list('id', flat=True)
        non_contact_squad_payments = CollectionHistory.objects\
            .get_bucket_non_contact_squads(squad_ids)

        non_contact_bucket_payments = qs.bucket_list_t71_to_t90(is_intelix=True).\
            exclude(loan_id__in=excluded_ptp_loan_ids).filter(
                loan_id__in=excluded_bucket_level_loan_ids
            )

        non_contact_bucket_payments = non_contact_bucket_payments.filter(id__in=oldest_payment_ids)

        unsent_non_contact_bucket_payments = SkiptraceHistory.objects.get_non_contact_bucket4().filter(
            loan__id__in=excluded_ptp_loan_ids
        ).extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW']}) \
            .values("payment_id", "reason")
        not_sent_to_dialer_payment += list(unsent_non_contact_bucket_payments)
        return non_contact_squad_payments, non_contact_bucket_payments, not_sent_to_dialer_payment

    elif payment_bucket == 'BUCKET_PTP':
        excluded_ptp_payments = PTP.objects.filter(
            payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            ptp_status__isnull=True,
            cdate__date__lt=date(2020, 5, 27)
        ).order_by('payment', '-cdate').distinct('payment')
        payments = qs.filter(
            id__in=oldest_payment_ids,
            ptp_date__isnull=False).exclude(id__in=excluded_ptp_payments.values_list(
                'payment', flat=True))
        centerix_ptp_payments, intelix_ptp_payments = filter_loan_id_based_on_experiment_settings(
            experiment_setting, payments
        )
    elif payment_bucket == 'GRAB':
        excluded_loan_halt_ids = Loan.objects.filter(
            loan_status=LoanStatusCodes.HALT).values_list('id', flat=True)
        today = timezone.localtime(timezone.now())
        excluded_loan_ids = list(chain(
            assigned_loan_ids,
            excluded_bucket_level_loan_ids,
            excluded_ptp_loan_ids,
            excluded_loan_halt_ids
        ))
        payments = Payment.objects.annotate(
            dpd=ExpressionWrapper(
                today.date() - F('due_date'),
                output_field=IntegerField())).exclude(
            loan__loan_status=LoanStatusCodes.INACTIVE).filter(
            loan__account__account_lookup__workflow__name=WorkflowConst.GRAB,
            dpd__gte = GRAB_INTELIX_CALL_DELAY_DAYS
        ).exclude(loan_id__in=excluded_loan_ids)
        payments = payments.filter(id__in=oldest_payment_ids)
        return payments

    if excluded_payment_by_loan_status:
        not_sent_to_dialer_payment += format_not_sent_payment(
            excluded_payment_by_loan_status, [''],
            dict(loan_id__isnull=False), extra_field="concat('Loan Status is ', loan.loan_status_code)")
    if excluded_payments_by_pending_refinancing:
        excluded_payments_by_pending_refinancing = excluded_payments_by_pending_refinancing.extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PENDING_REFINANCING']})\
            .values("id", "reason")
        not_sent_to_dialer_payment += list(excluded_payments_by_pending_refinancing)
    if excluded_payments_because_partner:
        excluded_payments_because_partner = excluded_payments_because_partner.extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PARTNER_ACCOUNT']})\
            .values("id", "reason")
        not_sent_to_dialer_payment += list(excluded_payments_because_partner)
    if excluded_payments_because_partner_icare:
        excluded_payments_because_partner_icare = excluded_payments_because_partner_icare.extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PARTNER_ACCOUNT']})\
            .values("id", "reason")
        not_sent_to_dialer_payment += list(excluded_payments_because_partner_icare)

    return payments, not_sent_to_dialer_payment


def check_if_payment_is_oldest_payment_and_not_j1(
        payments, is_julo_one=False, return_with_exclude_payment_ids=False):
    if payments is None:
        return

    exclude_pmts = []
    exclude_pmts_because_not_oldest = []

    if not is_julo_one:
        for item in payments:
            payment = item.payment
            loan = payment.loan
            oldest_payment = loan.get_oldest_unpaid_payment()
            if payment and oldest_payment:
                if payment.id != oldest_payment.id or payment.account_payment:
                    exclude_pmts.append(payment.id)
                if payment.id != oldest_payment.id and not payment.account_payment:
                    exclude_pmts_because_not_oldest.append(payment.id)

        if return_with_exclude_payment_ids:
            return payments.exclude(payment_id__in=exclude_pmts), exclude_pmts_because_not_oldest

        return payments.exclude(payment_id__in=exclude_pmts)

    else:
        for item in payments:
            account_payment = item.account_payment
            account = account_payment.account
            oldest_account_payment = account.get_oldest_unpaid_account_payment()

            if account_payment and oldest_account_payment:
                if account_payment.id != oldest_account_payment.id:
                    exclude_pmts.append(account_payment.id)
        if return_with_exclude_payment_ids:
            return payments.exclude(account_payment_id__in=exclude_pmts), exclude_pmts

        return payments.exclude(account_payment_id__in=exclude_pmts)


def exclude_payment_from_daily_upload(latest_history, is_julo_one=False):
    """exclude payment if it is non contacted according to failed call threshold
        consecutively if there is rpc before for bucket and squad level
    Arguments:
        latest_history {object}
    """

    if not latest_history:
        return

    first_called_date = timezone.localtime(
        latest_history.cdate - relativedelta(days=Threshold.FAILED_CALLED - 1)
    ).date()
    last_called_date = timezone.localtime(latest_history.cdate).date()
    call_result_names = CenterixCallResult.RPC + CenterixCallResult.WPC

    payment_bucket_1 = None
    account_payment_bucket_1 = None
    if latest_history.__class__ is SkiptraceHistory:
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['to'])

        if not is_julo_one:
            is_excluded = SkiptraceHistory.objects.filter(loan_id=latest_history.loan_id,
                                                          excluded_from_bucket=True)
            payment_bucket_1 = Payment.objects.filter(
                pk=latest_history.payment_id,
                due_date__range=[range2_ago, range1_ago]
            ).last()

        else:
            is_excluded = SkiptraceHistory.objects.filter(account_id=latest_history.account_id,
                                                          excluded_from_bucket=True)
            account_payment_bucket_1 = AccountPayment.objects.filter(
                pk=latest_history.account_payment_id,
                due_date__range=[range2_ago, range1_ago]
            ).last()

        if is_excluded:
            latest_history.update_safely(excluded_from_bucket=True)
            return Threshold.FAILED_CALLED

        select_dict = {
            'date': "(skiptrace_history.cdate AT TIME ZONE 'Asia/Jakarta')::date"
        }

    else:
        if not is_julo_one:
            is_excluded = CollectionHistory.objects.filter(loan_id=latest_history.loan_id,
                                                           excluded_from_bucket=True)
        else:
            is_excluded = CollectionHistory.objects.filter(
                account_id=latest_history.account_id,
                excluded_from_bucket=True)

        if is_excluded:
            latest_history.update_safely(excluded_from_bucket=True)
            return Threshold.FAILED_CALLED

        select_dict = {
            'date': "(collection_history.cdate AT TIME ZONE 'Asia/Jakarta')::date"
        }

    if not is_julo_one:
        filter_ = dict(payment=latest_history.payment)

    else:
        filter_ = dict(account_payment=latest_history.account_payment)

    call_histories = latest_history.__class__.objects.extra(
        select=select_dict).values('date')\
        .filter(**filter_).filter(cdate__date__range=(first_called_date, last_called_date))\
        .annotate(rpc_calls=Count(Case(
            When(call_result__name__in=call_result_names, then=1), output_field=IntegerField())))

    threshold_count = 0

    for call_history in call_histories:
        if call_history['rpc_calls'] == 0:
            threshold_count += 1

    excluded_from_bucket = False

    if payment_bucket_1:
        if threshold_count >= Threshold.B1_NC_FAILED_CALLED:
            excluded_from_bucket = True
    elif account_payment_bucket_1:
        if threshold_count >= Threshold.B1_NC_FAILED_CALLED:
            excluded_from_bucket = True
    else:
        if threshold_count >= Threshold.FAILED_CALLED:
            excluded_from_bucket = True

    if excluded_from_bucket:
        latest_history.update_safely(excluded_from_bucket=True)

    return threshold_count


def get_upload_centerix_data_params(payment):
    # Get application data
    application =  payment.loan.application
    loan = payment.loan
    address = '{} {} {} {} {} {}'.format(
        application.address_street_num,
        application.address_provinsi,
        application.address_kabupaten,
        application.address_kecamatan,
        application.address_kelurahan,
        application.address_kodepos)

    # Get payment data
    date = timezone.localtime(timezone.now()).date()
    today = datetime.strftime(date, "%Y-%m-%d")
    if payment.payment_status in PaymentStatusCodes.paid_status_codes():
        is_paid = 1
    else:
        is_paid = 0

    outstanding_amount = payment.due_amount
    other_payments =  Payment.objects.filter(loan=loan).order_by('payment_number')
    if other_payments:
        others = {}
        last_pay_amount = other_payments.last().paid_amount
        last_pay_dates = other_payments.last().paid_date
        last_pay_date = '' if last_pay_dates is None else last_pay_dates

        last_pay_details = {'LAST_PAY_DATE': str(last_pay_date), 'LAST_PAY_AMOUNT' : last_pay_amount}
        for other_payment in other_payments:
            others.update({'STATUS_ANG_'+str(other_payment.payment_number):
                               str(other_payment.payment_status.status_code) + "; " + str(other_payment.due_amount)})
            status_code = other_payment.payment_status.status_code
            if PaymentStatusCodes.PAYMENT_1DPD <= status_code <= PaymentStatusCodes.PAYMENT_180DPD \
                     and other_payment.id != payment.id:
                outstanding_amount += other_payment.due_amount
    else:
        last_pay_details = {'LAST_PAY_DATE': '', 'LAST_PAY_AMOUNT': ''}
        others = {'STATUS_ANG_1': '', 'STATUS_ANG_2': '', 'STATUS_ANG_3': '', 'STATUS_ANG_4': '', 'STATUS_ANG_5': '', 'STATUS_ANG_6': ''}

    payment_methods = PaymentMethod.objects.filter(loan=loan, is_shown=True)
    va_indomaret = ''
    va_alfamart = ''
    va_maybank = ''
    va_permata = ''
    va_bca = ''
    if payment_methods:
        for payment_method in payment_methods:
            if payment_method.payment_method_name == 'INDOMARET':
                va_indomaret = payment_method.virtual_account
            if payment_method.payment_method_name == 'ALFAMART':
                va_alfamart = payment_method.virtual_account
            if payment_method.payment_method_name == 'Bank MAYBANK':
                va_maybank = payment_method.virtual_account
            if payment_method.payment_method_name == 'PERMATA Bank':
                va_permata = payment_method.virtual_account
            if payment_method.payment_method_name == 'Bank BCA':
                va_bca = payment_method.virtual_account

    is_risky = 'No'
    refinancing_status = ''
    loan_refinancing = LoanRefinancingRequest.objects.filter(loan=loan).last()
    if loan_refinancing:
        proactive_stasuses = list(CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values())
        if loan_refinancing.status == CovidRefinancingConst.STATUSES.approved:
            refinancing_status = 'Pending {}'.format(loan_refinancing.product_type)
        elif loan_refinancing.status == CovidRefinancingConst.STATUSES.activated:
            refinancing_status = 'Refinanced {}'.format(loan_refinancing.product_type)
        elif loan_refinancing.status == CovidRefinancingConst.STATUSES.proposed:
            refinancing_status = 'Proposed {}'.format(loan_refinancing.product_type)
        elif loan_refinancing.status == CovidRefinancingConst.STATUSES.inactive:
            refinancing_status = 'Inactivated {}'.format(loan_refinancing.product_type)
        elif loan_refinancing.status in proactive_stasuses:
            refinancing_status = '{} {}'.format(loan_refinancing.channel, loan_refinancing.status)

    if application.product_line.product_line_code in ProductLineCodes.mtl() and \
            loan.status != LoanStatusCodes.SELL_OFF:
        today_plus10 = date + relativedelta(days=10)
        today_minus10 = date + relativedelta(days=-10)
        today_minus25 = date + relativedelta(days=-25)
        today_minus55 = date + relativedelta(days=-55)
        check_risky_on_dpd = [today_plus10, today_minus10, today_minus25, today_minus55]
        campaign_setting = CampaignSetting.objects.filter(campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF,
                                                          is_active=True).last()
        customer_campaign_params = CustomerCampaignParameter.objects.filter(
            customer=application.customer,
            campaign_setting=campaign_setting,
        ).last()
        if customer_campaign_params and \
                date <= customer_campaign_params.effective_date + relativedelta(days=10):
            is_risky = 'Yes'
        elif payment.due_date in check_risky_on_dpd:
            customer_service = get_customer_service()
            is_risky = 'Yes' if customer_service.check_risky_customer(application.id) else is_risky

    params = {
        'CUSTOMER_ID':  application.customer.id,
        'APPLICATION_ID': application.id,
        'NAMA_CUSTOMER': str(application.fullname),
        'MOBILE_PHONE_1': str(application.mobile_phone_1),
        'MOBILE_PHONE_2': str(application.mobile_phone_2),
        'NAMA_PERUSAHAAN': str(application.company_name),
        'POSISI_KARYAWAN': str(application.position_employees),
        'TELP_PERUSAHAAN': str(application.company_phone_number),
        'DPD': payment.due_late_days,
        'ANGSURAN': loan.installment_amount,
        'DENDA': payment.late_fee_amount,
        'OUTSTANDING': outstanding_amount,
        'ANGSURAN_KE': payment.payment_number,
        'DUEDATE': str(payment.due_date),
        'NAMA_SPOUSE': str(application.spouse_name),
        'SPOUSE_PHONE': str(application.spouse_mobile_phone),
        'NAMA_KIN':  str(application.kin_name),
        'KIN_PHONE': str(application.kin_mobile_phone),
        'HUBUNGAN_KIN': str(application.kin_relationship),
        'ALAMAT': address,
        'KOTA': str(application.address_kabupaten),
        'GENDER': str(application.gender),
        'TGL_LAHIR': str(application.dob),
        'TGL_GAJIAN': str(application.payday),
        'TUJUAN_PINJAMAN': str(application.loan_purpose),
        'TGL_UPLOAD': today,
        'EXP_DATE': str(application.sphp_exp_date),
        'VA_BCA': va_bca,
        'VA_PERMATA': va_permata,
        'VA_MAYBANK': va_maybank,
        'VA_ALFAMART': va_alfamart,
        'VA_INDOMARET': va_indomaret,
        'CAMPAIGN': 'JULO',
        'PRODUCT_TYPE': application.product_line.product_line_type,
        'LOAN_AMOUNT': loan.loan_amount,
        'TENOR': loan.loan_duration,
        'UPLOAD_KE': '1',
        'ISPAID': is_paid,
        'PAYMENT_ID':payment.id,
        'ZIPCODE': application.address_kodepos,
        'IS_FDC_RISKY': str(is_risky),
        'CUSTOMER_BUCKET_TYPE': check_customer_bucket_type(payment),
        'REFINANCING_STATUS': str(refinancing_status),
    }
    params.update(others)
    params.update(last_pay_details)

    return params


def upload_payment_details(data, campaign):
    # need_get_payment_relation = (PdCollectionModelResult, CollectionHistory, SkiptraceHistory)
    # if data:
    #     params_list = []
    #     for item in data:
    #         # for is_for_collection_model = True item is payment_collection object
    #         # so it's need get payment from it relation
    #         if type(item) in need_get_payment_relation:
    #             try:
    #                 payment = item.payment
    #             except Payment.DoesNotExist as error:
    #                 logger.error({
    #                     "action": "upload_payment_details",
    #                     "error": "Payment not found",
    #                     "data": {"payment_id": item.payment_id}
    #                 })
    #                 continue
    #
    #         else:
    #             # for is_for_collection_model = False (previous version) item is payment object
    #             payment = item
    #
    #         params = get_upload_centerix_data_params(payment)
    #         params_list.append(params)
    #
    #     centerix_client = get_julo_centerix_client()
    #     response = centerix_client.upload_centerix_data(campaign, params_list)
    #     return response
    # else:
    return 'No data to upload to centerix'


def upload_ptp_agent_level_data(payment_groups, experiment_dict={}):
    return True
    # centerix_client = get_julo_centerix_client()
    #
    # for key in payment_groups:
    #     payment_params = []
    #     campaign_code = 'JULO_' + key
    #
    #     for data in payment_groups[key]:
    #         params = get_upload_centerix_data_params(data.payment)
    #         agent_data = {
    #             'AgentData': {
    #                 'PTPDATE': str(data.payment.ptp_date),
    #                 'PTP': data.payment.ptp_amount,
    #                 'AgentCode': data.agent.username
    #             }
    #         }
    #         params.update(agent_data)
    #         payment_params.append(params)
    #
    #     response_message = centerix_client.upload_centerix_data(campaign_code , payment_params)
    #     logger.info({
    #         'action': 'upload_ptp_agent_level_data',
    #         'response_message': response_message
    #     })
    #
    #     if experiment_dict:
    #         experiment_dict.update({
    #             'bucket_type': campaign_code
    #         })
    #
    #     record_centerix_log(payment_groups[key], campaign_code, experiment_dict)


def get_oldest_payment_ids_loans(is_intelix=False):
    exclude_partner_ids = Partner.objects.filter(
        name__in=PartnerConstant.excluded_for_crm_intelix()
        if is_intelix else PartnerConstant.excluded_for_crm()) \
        .values_list('id', flat=True)

    loans = Loan.objects\
        .filter(loan_status_id__gte=LoanStatusCodes.CURRENT,
                loan_status_id__lt=LoanStatusCodes.RENEGOTIATED)\
        .exclude(application__partner__id__in=exclude_partner_ids)\
        .values_list('id', flat=True)

    payments = Payment.objects.filter(
        loan_id__in=loans,
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        account_payment_id__isnull=True
    ).exclude(is_restructured=True)\
     .order_by('loan', 'id').distinct('loan').values_list('id', flat=True)

    return payments


def calculate_commission_amount(paid_amount, diff_days=None, squad_id=None,
                                agent=None, total_agent=None):
    credited_amount = 0

    if (diff_days or 0) > 3:
        today = timezone.localtime(timezone.now()).date()
        agents = CollectionSquadAssignment\
            .objects.distinct('agent')\
        .order_by('agent', '-id').values_list('id', flat=True)

        active_agents_in_squad = CollectionSquadAssignment\
            .objects.filter(
                pk__in=agents,
                squad_id=squad_id,
                cdate__date__lt=today,
                agent__is_active=True).count()

        credited_amount = float(old_div(paid_amount, active_agents_in_squad))

        return credited_amount

    if agent is not None:
        return paid_amount

    if total_agent is not None:
        credited_amount = float(old_div(paid_amount, total_agent))

    return credited_amount


def get_last_rpc_agent(payment, last_rpc_date, is_julo_one=False):
    """get last rpc agent by comparing if the payment exist
       on collection history. Then, proceed to get the agent id
       from skiptrace history centerix table

    Arguments:
        payment {obj}
        last_rpc_date {datetime}
    """
    local_cdate = timezone.localtime(last_rpc_date).date()
    if not is_julo_one:
        last_rpc_st = SkiptraceHistory.objects\
            .filter(payment=payment,
                    cdate__date=local_cdate)\
            .last()

    else:
        last_rpc_st = SkiptraceHistory.objects\
            .filter(account_payment=payment,
                    cdate__date=local_cdate)\
            .last()

    if last_rpc_st is None:
        return None

    rpc_user = User.objects.filter(username=last_rpc_st.agent_name).last()

    if rpc_user is None:
        return None
    else:
        return rpc_user


def insert_data_into_commission_table(payment, actual_agent, paid_amount):
    """insert data to commission table on payment made

    Arguments:
        payment {[object]}
        actual_agent {[object]}
        paid_amount {[int]}
    """

    collection_history = CollectionHistory.objects.filter(payment=payment,
                                                          last_current_status=True)\
                                                  .last()

    # this block to get the agent / squad in case of multiple payments
    squad_id = None

    if collection_history is None:
        today = timezone.localtime(timezone.now()).date()

        previous_commission = CommissionLookup.objects.filter(
            loan=payment.loan,
            cdate__date=today
        ).last()

        if previous_commission is not None:
            actual_agent = previous_commission.agent if \
                previous_commission.agent else None
            squad_id = previous_commission.squad_id if \
                previous_commission.squad_id else None

    if collection_history is None and actual_agent is None \
            and squad_id is None:
        logger.info({
            'method': 'insert_data_into_commission_table',
            'message': 'payment does not have collection history and collected_by',
            'payment': payment.id
        })

        return

    # this block to get agent beside bucket 2 since we don't store
    # the agent information on collection agent task
    if collection_history is not None and actual_agent is None \
            and collection_history.is_ptp is False:
        rpc_call_ids = SkiptraceResultChoice.objects.filter(
            name__in=CenterixCallResult.RPC
        ).values_list('id', flat=True)

        rpc_history = CollectionHistory.objects.filter(
            call_result_id__in=rpc_call_ids,
            payment=payment
        ).last()

        if rpc_history is None:
            return

        actual_agent = get_last_rpc_agent(payment, rpc_history.cdate)

        if actual_agent is None:
            logger.info({
                'method': 'insert_data_into_commission_table',
                'message': 'cannot get rpc agent from skiptrace history',
                'payment': payment.id
            })

            return

        agent = Agent.objects.get_or_none(user=actual_agent)

        if agent is None:
            logger.info({
                'method': 'insert_data_into_commission_table',
                'error': 'failed to insert into commission table',
                'message': 'cannot get rpc agent from table agent',
                'payment': payment.id
            })

            return

        if agent.squad_id != collection_history.squad_id:
            logger.info({
                'method': 'insert_data_into_commission_table',
                'error': 'failed to insert into commission table',
                'message': 'last rpc agent squad_id and current agent squad_id is different',
                'last_rpc_agent': agent.squad_id,
                'collection_history_agent': collection_history.squad_id,
                'payment': payment.id
            })

            return

    if collection_history is None and (actual_agent is not None or
                                       squad_id is not None):
        # this condition is to check whether the user paid multiple payments in one go.
        # if that's the case, the credit will go to the agent / squad

        if actual_agent is None:
            credited_amount = calculate_commission_amount(
                paid_amount,
                squad_id=squad_id,
                diff_days=4)

            CommissionLookup.objects.create(
                payment=payment,
                payment_amount=paid_amount,
                credited_amount=credited_amount,
                squad_id=squad_id,
                collected_by=CollectedBy.SQUAD,
                loan=payment.loan
            )

            return

        agent = Agent.objects.get_or_none(user=actual_agent)

        if agent is None:
            return

        if agent.squad_id is None:
            # this block is to make sure that payment goes to minisquad agent only
            return

        credited_amount = calculate_commission_amount(
            paid_amount,
            agent=actual_agent)

        CommissionLookup.objects.create(
            payment=payment,
            payment_amount=paid_amount,
            credited_amount=credited_amount,
            squad_id=agent.squad_id,
            agent=actual_agent,
            collected_by=CollectedBy.AGENT,
            loan=payment.loan
        )

    return

    # PTP commission calculation, just need the agent that create the PTP call
    # to get the commission
    if collection_history.is_ptp is True and \
            payment.paid_date <= payment.ptp_date:
        ptp_history = CollectionHistory.objects.filter(
            call_result__name='RPC - PTP',
            payment=payment
        ).last()

        if ptp_history is None:
            return

        ptp_agent = Agent.objects.get_or_none(user=ptp_history.agent)

        if ptp_agent is None:
            logger.info({
                'method': 'insert_data_into_commission_table',
                'error': 'failed to insert into commission table',
                'message': 'agent not found',
                'payment': payment.id
            })

            return

        if ptp_agent.squad_id != collection_history.squad_id:
            logger.info({
                'method': 'insert_data_into_commission_table',
                'error': 'failed to insert into commission table',
                'message': 'agent has different squad with the data',
                'payment': payment.id
            })

            return

        credited_amount = calculate_commission_amount(
            paid_amount,
            agent=ptp_agent)

        CommissionLookup.objects.create(
            payment=payment,
            payment_amount=paid_amount,
            credited_amount=credited_amount,
            squad_id=ptp_agent.squad_id,
            agent_id=ptp_agent.user_id,
            collected_by=CollectedBy.AGENT,
            loan=payment.loan
        )

        return

    # RPC call calculation
    last_rpc_date = timezone.localtime(collection_history.cdate).date()
    today = timezone.localtime(timezone.now()).date()
    diff_in_days = (today - last_rpc_date).days

    # to know which payment goes to which agent during RPC since we don't
    # store information about the agent during RPC call, so we use actual agent
    # from collection agent task or skiptrace history centerix agent name
    credited_amount = calculate_commission_amount(paid_amount, diff_days=diff_in_days,
                                                  squad_id=collection_history.squad_id,
                                                  agent=actual_agent)

    if diff_in_days > 3:
        extra_field = {
            'collected_by': CollectedBy.SQUAD
        }
    else:
        extra_field = {
            'agent': actual_agent,
            'collected_by': CollectedBy.AGENT
        }

    CommissionLookup.objects.create(
        payment=payment,
        payment_amount=paid_amount,
        credited_amount=credited_amount,
        squad_id=collection_history.squad_id,
        loan=payment.loan,
        **extra_field
    )


def update_bucket_level_payment(payment_dpd, today):
    """this method to return the excluded payment to bucket level when bucket changes

    Arguments:
        payment_dpd {[type]} -- [description]
        today {[type]} -- [description]
    """
    skiptraces_ids = SkiptraceHistory.objects.filter(
        excluded_from_bucket=True
    ).annotate(
        dpd=ExpressionWrapper(
            today - F('payment__due_date'),
            output_field=IntegerField())).filter(dpd=payment_dpd)\
     .values_list('pk', flat=True)


def unassign_bucket1_payment(dpd=11,
                             today=timezone.localtime(timezone.now()).date()):
    update_bucket_level_payment(dpd, today)


def unassign_bucket2_payment(dpd=41,
                             today=timezone.localtime(timezone.now()).date()):
    today = timezone.localtime(timezone.now()).date()
    update_bucket_level_payment(dpd, today)


def unassign_bucket3_payment(dpd=71,
                             today=timezone.localtime(timezone.now()).date()):
    today = timezone.localtime(timezone.now()).date()
    update_bucket_level_payment(dpd, today)


def unassign_bucket4_payment(dpd=101,
                             today=timezone.localtime(timezone.now()).date()):
    today = timezone.localtime(timezone.now()).date()
    update_bucket_level_payment(dpd, today)


def send_slack_message_centrix_failure(message):
    get_slack_client = get_slack_bot_client()
    get_slack_client.api_call(
        "chat.postMessage", channel='urgent', text=message
    )


def record_centerix_log(payments, bucket, experiment_dict={}):
    if not payments:
        return
    need_get_payment_relation = (PdCollectionModelResult, CollectionHistory, SkiptraceHistory)
    all_centerix_data = []
    all_caller_experiment_data = []

    for payment in payments:
        # since we combined 2 sorted and not sorted then this way is for getting is_sorted
        is_sorted_by_collection_model = True if type(payment) == PdCollectionModelResult else False
        if type(payment) in need_get_payment_relation:
            try:
                payment = payment.payment
            except Payment.DoesNotExist as error:
                logger.error({
                    "action": "upload_payment_details",
                    "error": "Payment not found",
                    "data": {"payment_id": payment.payment_id}
                })
                continue
        centerix_data = dict(
            application=payment.loan.application,
            payment=payment,
            bucket=bucket,
            sorted_by_collection_model=is_sorted_by_collection_model
        )

        if experiment_dict:
            experiment_data = dict(
                loan=payment.loan,
                payment=payment,
                bucket=experiment_dict['bucket_type'],
                experiment_group=experiment_dict['experiment_group'],
                experiment_setting=experiment_dict['experiment_setting']
            )

            all_caller_experiment_data.append(VendorQualityExperiment(**experiment_data))

        all_centerix_data.append(SentToCenterixLog(**centerix_data))

    SentToCenterixLog.objects.bulk_create(all_centerix_data)
    VendorQualityExperiment.objects.bulk_create(all_caller_experiment_data)


def record_vendor_experiment_data(
        payments, experiment_dict, is_ptp=False, vendor_name=DialerVendor.INTELIX):
    all_caller_experiment_data = []

    for payment in payments:
        payment_obj = payment if payment.__class__ is Payment else payment.payment

        if is_ptp:
            bucket_name = get_bucket_type_based_on_dpd(payment_obj)

            if not bucket_name:
                continue
        else:
            bucket_name = experiment_dict['bucket_type']

        experiment_data = dict(
            loan=payment_obj.loan,
            payment=payment_obj,
            bucket=bucket_name,
            experiment_group=vendor_name,
            experiment_setting=experiment_dict['experiment_setting']
        )

        all_caller_experiment_data.append(VendorQualityExperiment(**experiment_data))

    VendorQualityExperiment.objects.bulk_create(all_caller_experiment_data)


def get_bucket_type_based_on_dpd(payment):
    due_date = payment.due_date
    today = timezone.localtime(timezone.now()).date()
    dpd = (today - due_date).days

    if 1 <= dpd <= 10:
        return 'B1_PTP'
    elif 11 <= dpd <= 40:
        return 'B2_PTP'
    elif 41 <= dpd <= 70:
        return 'B3_PTP'
    elif 71 <= dpd <= 100:
        return 'B4_PTP'
    else:
        return ''


def check_customer_bucket_type(payment):
    if payment.__class__ is Payment:
        dpd = payment.due_late_days
        loan = payment.loan
        previous_payments_on_bucket = loan.payment_set.filter(
            payment_number__lt=payment.payment_number,
            payment_status_id__gt=PaymentStatusCodes.PAID_ON_TIME,
            paid_date__isnull=False
        )
        status = payment.payment_status_id
    elif payment.__class__ is AccountPayment:
        dpd = payment.dpd
        account = payment.account
        previous_payments_on_bucket = account.accountpayment_set.filter(
            id__lt=payment.id,
            status_id__gt=PaymentStatusCodes.PAID_ON_TIME,
            paid_date__isnull=False
        )
        status = payment.status_id
    if payment.is_paid and status == PaymentStatusCodes.PAID_ON_TIME:
        return 'NA'
    if dpd <= 0 and not payment.is_paid:
        return 'NA'
    current_payment_bucket = get_bucket_status(dpd)
    biggest_entered_bucket = 0
    for previous_payment in previous_payments_on_bucket:
        calculate_pay_on_dpd = previous_payment.paid_date - previous_payment.due_date
        dpd_when_paid = calculate_pay_on_dpd.days
        previous_bucket = get_bucket_status(dpd_when_paid)
        if previous_bucket > biggest_entered_bucket:
            biggest_entered_bucket = previous_bucket

    if current_payment_bucket <= biggest_entered_bucket:
        return 'Stabilized'

    return 'Fresh'


def check_customer_bucket_type_account_payment(account_payment):
    dpd = account_payment.dpd
    if account_payment.is_paid and account_payment.status_id == PaymentStatusCodes.PAID_ON_TIME:
        return 'NA'
    if dpd <= 0 and not account_payment.is_paid:
        return 'NA'
    account = account_payment.account
    previous_payments_on_bucket = account.accountpayment_set.filter(
        id__lt=account_payment.id,
        status_id=PaymentStatusCodes.PAID_ON_TIME,
        paid_date__isnull=False
    )
    current_payment_bucket = get_bucket_status(dpd)
    biggest_entered_bucket = 0
    for previous_payment in previous_payments_on_bucket:
        calculate_pay_on_dpd = previous_payment.paid_date - previous_payment.due_date
        dpd_when_paid = calculate_pay_on_dpd.days
        previous_bucket = get_bucket_status(dpd_when_paid)
        if previous_bucket > biggest_entered_bucket:
            biggest_entered_bucket = previous_bucket

    if current_payment_bucket <= biggest_entered_bucket:
        return 'Stabilized'

    return 'Fresh'


def check_customer_bucket_type_account_payment(account_payment):
    dpd = account_payment.dpd
    if account_payment.is_paid and account_payment.status_id == PaymentStatusCodes.PAID_ON_TIME:
        return 'NA'
    if dpd <= 0 and not account_payment.is_paid:
        return 'NA'
    account = account_payment.account
    previous_payments_on_bucket = account.accountpayment_set.filter(
        id__lt = account_payment.id,
        status_id = PaymentStatusCodes.PAID_ON_TIME,
        paid_date__isnull=False
    )
    current_payment_bucket = get_bucket_status(dpd)
    biggest_entered_bucket = 0
    for previous_payment in previous_payments_on_bucket:
        calculate_pay_on_dpd = previous_payment.paid_date - previous_payment.due_date
        dpd_when_paid = calculate_pay_on_dpd.days
        previous_bucket = get_bucket_status(dpd_when_paid)
        if previous_bucket > biggest_entered_bucket:
            biggest_entered_bucket = previous_bucket

    if current_payment_bucket <= biggest_entered_bucket:
        return 'Stabilized'

    return 'Fresh'

def get_bucket_status(dpd):
    bucket_1 = list(range(1, 11))# 1 - 10
    bucket_2 = list(range(11, 41))# 11 - 40
    bucket_3 = list(range(41, 71))# 41 - 70
    bucket_4 = list(range(71, 91))# 71 - 90
    bucket_5 = 91
    if dpd in bucket_1:
        return 1
    if dpd in bucket_2:
        return 2
    if dpd in bucket_3:
        return 3
    if dpd in bucket_4:
        return 4
    if dpd >= bucket_5:
        return 5
    return 0


def filter_loan_id_based_on_experiment_settings(experiment_setting, payments):
    if not experiment_setting:
        return payments

    centerix_experiment_criteria = experiment_setting.criteria[DialerVendor.CENTERIX]
    intelix_experiment_criteria = experiment_setting.criteria[DialerVendor.INTELIX]

    return payments.annotate(last_two_digit_loan_id=F('loan_id') % 100).filter(
        last_two_digit_loan_id__range=centerix_experiment_criteria
    ), payments.annotate(last_two_digit_loan_id=F('loan_id') % 100).filter(
        last_two_digit_loan_id__range=intelix_experiment_criteria
    )


def get_caller_experiment_setting(experiment_name, db_name=DEFAULT_DB):
    today = timezone.localtime(timezone.now()).date()
    dialer_experiment = ExperimentSetting.objects.using(db_name).filter(
        code=experiment_name,
        is_active=True
    ).filter(
        (Q(start_date__date__lte=today) & Q(end_date__date__gte=today)) | Q(is_permanent=True)
    ).last()

    return dialer_experiment


def exclude_ptp_payment_loan_ids():
    today = timezone.localtime(timezone.now()).date()
    excluded_ptp_loan_id = (
        PTP.objects.filter(ptp_date__gte=today, account_id__isnull=True)
        .distinct('loan')
        .values_list('loan_id', flat=True)
    )

    return excluded_ptp_loan_id


def exclude_active_ptp_account_payment_ids():
    today = timezone.localtime(timezone.now()).date()
    return (
        PTP.objects.filter(ptp_date__gte=today, account_payment_id__isnull=False)
        .distinct('account')
        .values_list('account_id', flat=True)
    )


def exclude_pending_refinancing():
    today = timezone.localtime(timezone.now()).date()
    today_minus_4 = today - relativedelta(days=4)

    bucket_1_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_1_DPD['to'] - 3)
    bucket_1_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_1_DPD['to'])
    bucket_2_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_2_DPD['to'] - 3)
    bucket_2_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_2_DPD['to'])
    bucket_3_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_3_DPD['to'] - 3)
    bucket_3_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_3_DPD['to'])
    bucket_4_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_4_DPD['to'] - 3)
    bucket_4_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_4_DPD['to'])

    loans_pending_refinancing = LoanRefinancingRequest.objects.values_list(
        'loan', flat=True).filter(
        status=CovidRefinancingConst.STATUSES.approved,
        udate__date__gte=today_minus_4,
        udate__date__lt=today,
    )

    account_payment_refinancing = AccountPayment.objects.filter(
        payment__loan_id__in=loans_pending_refinancing).filter(
            ~Q(due_date__range=[bucket_1_dpd_date_from, bucket_1_dpd_date_to]) &
            ~Q(due_date__range=[bucket_2_dpd_date_from, bucket_2_dpd_date_to]) &
            ~Q(due_date__range=[bucket_3_dpd_date_from, bucket_3_dpd_date_to]) &
            ~Q(due_date__range=[bucket_4_dpd_date_from, bucket_4_dpd_date_to])
        )

    return account_payment_refinancing


# def exclude_assigned_account_ids():

#     return CollectionAgentTask.objects.filter(
#         unassign_time__isnull=True,
#         assign_to_vendor=True).distinct(
#             'account').values_list(
#                 'account_id', flat=True)


def get_oldest_unpaid_account_payment_ids(
    specific_account_status_ids=None, db_name=DEFAULT_DB, is_only_return_pk=True
):
    account_statuses = AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
    if specific_account_status_ids:
        account_statuses = specific_account_status_ids

    account_payments = (
        AccountPayment.objects.using(db_name)
        .filter(status_id__in=PaymentStatusCodes.not_paid_status_codes(), is_restructured=False)
        .exclude(account__status_id__in=account_statuses)
        .order_by('account', 'due_date')
        .distinct('account')
    )
    if not is_only_return_pk:
        return account_payments

    return account_payments.using(db_name).values_list('id', flat=True)


def get_excluded_bucket_account_level_ids():
    return SkiptraceHistory.objects.filter(
        excluded_from_bucket=True,
        account_payment_id__isnull=False).order_by(
            'account', '-cdate').distinct('account').values_list(
                'account', flat=True)


def get_account_payment_details_for_calling(bucket_name, experiment_setting=None):
    from juloserver.minisquad.services2.dialer_related import get_eligible_account_payment_for_dialer_and_vendor_qs

    account_payment_refinancing = exclude_pending_refinancing()
    exclude_account_status_list = [
        JuloOneCodes.FRAUD_REPORTED,
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
        JuloOneCodes.SCAM_VICTIM
    ]
    account_payments = []
    not_sent_to_dialer_account_payments = []
    qs = get_eligible_account_payment_for_dialer_and_vendor_qs().exclude(
        id__in=account_payment_refinancing).exclude(
        account__status_id__in=exclude_account_status_list)
    # oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
    not_sent_oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids(
        specific_account_status_ids=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
    )
    excluded_bucket_level_account_ids = get_excluded_bucket_account_level_ids()

    # assigned_account_ids = exclude_assigned_account_ids()
    assigned_account_ids = []
    excluded_ptp_account_ids = exclude_active_ptp_account_payment_ids()
    qs_account_payments_excluded_by_pending_refinancing = AccountPayment.objects.not_paid_active().filter(
        id__in=account_payment_refinancing)
    excluded_account_payments_by_pending_refinancing = None
    excluded_account_payments_by_intelix_blacklist = None
    excluded_account_ids_by_intelix_blacklist = get_exclude_account_ids_by_intelix_blacklist()
    qs_account_payments_excluded_by_intelix_blacklist = \
        AccountPayment.objects.not_paid_active().filter(
            account_id__in=excluded_account_ids_by_intelix_blacklist
        )
    excluded_account_payments_by_turned_on_autodebet = \
        get_turned_on_autodebet_customer_exclude_for_dpd_plus()
    if bucket_name == 'JULO_B1':
        excluded_account_ids = list(chain(
            assigned_account_ids,
            excluded_bucket_level_account_ids,
            excluded_ptp_account_ids,
            excluded_account_ids_by_intelix_blacklist,
            excluded_account_payments_by_turned_on_autodebet))
        account_payments = qs.bucket_1_t1_t10(excluded_account_ids)
        # not sent to dialer
        not_sent_account_payments = qs.bucket_1_t1_t10([])
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        if excluded_bucket_level_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(account_id__in=excluded_bucket_level_account_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_bucket_level_account_ids)
        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))

        not_sent_account_payments = qs.bucket_1_t1_t10([]).filter(
            id__in=not_sent_oldest_account_payment_ids).exclude(
            account_id__in=excluded_account_ids
        )
        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )

        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")

        excluded_account_payments_by_pending_refinancing = qs_account_payments_excluded_by_pending_refinancing.\
            bucket_1_t1_t10([])

        excluded_account_payments_by_intelix_blacklist = \
            qs_account_payments_excluded_by_intelix_blacklist.bucket_1_t1_t10([])

    elif bucket_name == 'JULO_B2':
        excluded_account_ids = list(chain(
            assigned_account_ids,
            excluded_bucket_level_account_ids,
            excluded_ptp_account_ids,
            excluded_account_ids_by_intelix_blacklist,
            excluded_account_payments_by_turned_on_autodebet))
        account_payment_t11_to_t40 = qs.bucket_list_t11_to_t40().\
            exclude(account_id__in=excluded_account_ids)

        account_payments = account_payment_t11_to_t40
        # not sent to dialer
        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']])
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        if excluded_bucket_level_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(account_id__in=excluded_bucket_level_account_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_bucket_level_account_ids)
        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))

        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED'],
            dict(is_collection_called=True))

        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']]).filter(
            id__in=not_sent_oldest_account_payment_ids).exclude(
            account_id__in=excluded_account_ids
        )
        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")
        excluded_account_payments_by_pending_refinancing = qs_account_payments_excluded_by_pending_refinancing. \
            determine_bucket_by_range([BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']])

        excluded_account_payments_by_intelix_blacklist = \
            qs_account_payments_excluded_by_intelix_blacklist.determine_bucket_by_range(
                [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']]
            )

    elif bucket_name == 'JULO_B3':
        block_traffic_intelix_on = FeatureSetting.objects.get_or_none(
            feature_name='block_traffic_intelix', is_active=True)
        # exclude account payment from send to dialer, with cdate today and bucket name b3 nc
        excluded_account_payment_ids = []
        if block_traffic_intelix_on:
            excluded_bucket_level_account_ids = []
            excluded_nc_account_payment_ids = SentToDialer.objects.filter(
                cdate__date=timezone.now().date(),
                bucket='JULO_B3_NON_CONTACTED',
                account_payment_id__isnull=False
            ).values_list('account_payment', flat=True)
            excluded_sent_to_vendor_nc_b3_account_payment_ids = NotSentToDialer.objects.filter(
                cdate__date=timezone.now().date(),
                bucket='JULO_B3_NON_CONTACTED',
                account_payment_id__isnull=False,
                unsent_reason='sending b3 to vendor'
            ).values_list('account_payment', flat=True)
            excluded_account_payment_ids = list(excluded_nc_account_payment_ids) + list(
                excluded_sent_to_vendor_nc_b3_account_payment_ids)

        excluded_account_ids = list(chain(
            assigned_account_ids,
            excluded_bucket_level_account_ids,
            excluded_ptp_account_ids,
            excluded_account_ids_by_intelix_blacklist,
            excluded_account_payments_by_turned_on_autodebet))
        account_payment_t41_to_t70 = qs.bucket_list_t41_to_t70(). \
            exclude(account_id__in=excluded_account_ids)
        # include the exclude filter from
        account_payments = account_payment_t41_to_t70.exclude(
            id__in=excluded_account_payment_ids)
        # not sent to dialer
        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']])
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        if excluded_bucket_level_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(account_id__in=excluded_bucket_level_account_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_bucket_level_account_ids)
        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_ptp_account_ids)

        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED'],
            dict(is_collection_called=True))

        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']]).filter(
            id__in=not_sent_oldest_account_payment_ids).exclude(
            account_id__in=excluded_account_ids
        )
        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")

        # block traffic to intelix by mark as sending b3 to vender
        if block_traffic_intelix_on:
            block_intelix_params = block_traffic_intelix_on.parameters
            sending_b3_to_vendor = b3_vendor_distribution(
                account_payments, block_intelix_params, IntelixTeam.JULO_B3)
            if sending_b3_to_vendor:
                not_sent_to_dialer_account_payments += format_not_sent_payment(
                    account_payments,
                    ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR'],
                    dict(pk__in=sending_b3_to_vendor))
                account_payments = account_payments.exclude(pk__in=sending_b3_to_vendor)

        excluded_account_payments_by_pending_refinancing = qs_account_payments_excluded_by_pending_refinancing. \
            determine_bucket_by_range([BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']])

        excluded_account_payments_by_intelix_blacklist = \
            qs_account_payments_excluded_by_intelix_blacklist.determine_bucket_by_range(
                [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']]
            )

    elif bucket_name == 'JULO_B4':
        logger.info({
            "action": "get_account_payment_details_for_calling",
            "bucket": bucket_name,
            "info": "get account payment detail for B4 begin"
        })
        assigned_to_vendor_account_payment_ids = get_assigned_b4_account_payment_ids_to_vendors()
        excluded_account_ids = list(chain(
            assigned_account_ids,
            excluded_bucket_level_account_ids,
            excluded_ptp_account_ids,
            excluded_account_ids_by_intelix_blacklist,
            excluded_account_payments_by_turned_on_autodebet
        ))
        account_payment_t71_to_t100 = qs.bucket_list_t71_to_t90().\
            exclude(account_id__in=excluded_account_ids).exclude(id__in=assigned_to_vendor_account_payment_ids)
        account_payments = account_payment_t71_to_t100
        # not sent to dialer
        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']])
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        if excluded_bucket_level_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
                dict(account_id__in=excluded_bucket_level_account_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_bucket_level_account_ids)
        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_ptp_account_ids)
        if assigned_to_vendor_account_payment_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_TO_THIRD_PARTY'],
                dict(id__in=assigned_to_vendor_account_payment_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(id__in=assigned_to_vendor_account_payment_ids)

        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED'],
            dict(is_collection_called=True))

        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']]).filter(
            id__in=not_sent_oldest_account_payment_ids).exclude(
            account_id__in=excluded_account_ids
        )
        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")

        excluded_account_payments_by_intelix_blacklist = \
            qs_account_payments_excluded_by_intelix_blacklist.determine_bucket_by_range(
                [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']]
            )

        logger.info({
            "action": "get_account_payment_details_for_calling",
            "bucket": bucket_name,
            "account_payment_ids": list(account_payments.values_list('id', flat=True))
        })

    elif bucket_name == 'JULO_B5':
        sub_bucket = SubBucket.sub_bucket_five(1)
        assigned_to_vendor = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True, account_payment__isnull=False
        ).distinct("account_payment__account_id").values_list("account_payment__account_id", flat=True)
        excluded_account_ids = list(chain(assigned_to_vendor,
                                          excluded_account_ids_by_intelix_blacklist,
                                          excluded_account_payments_by_turned_on_autodebet))
        account_payments = qs.get_all_bucket_5(sub_bucket.end_dpd).exclude(
            account_id__in=excluded_account_ids
        )
        # not sent to intelix
        unsent_payments = qs.get_all_bucket_5(sub_bucket.end_dpd)
        not_sent_filter_criteria = dict(
            account_id__in=assigned_to_vendor
        )
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                unsent_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            unsent_payments = unsent_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            unsent_payments, ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_TO_THIRD_PARTY'],
            not_sent_filter_criteria)

        not_sent_account_payments = qs.get_all_bucket_5(sub_bucket.end_dpd)\
            .filter(id__in=not_sent_oldest_account_payment_ids)

        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")
        excluded_account_payments_by_pending_refinancing = qs_account_payments_excluded_by_pending_refinancing. \
            get_all_bucket_5(sub_bucket.end_dpd)

        excluded_account_payments_by_intelix_blacklist = \
            qs_account_payments_excluded_by_intelix_blacklist.get_all_bucket_5(sub_bucket.end_dpd)

    elif bucket_name in ('JULO_B6_1', 'JULO_B6_2'):
        sub_bucket = SubBucket.sub_bucket_six(int(bucket_name[-1]))
        assigned_to_vendor = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True, account_payment__isnull=False
        ).distinct("account_payment__account_id").values_list("account_payment__account_id", flat=True)
        excluded_account_ids = list(chain(assigned_to_vendor,
                                          excluded_account_ids_by_intelix_blacklist,
                                          excluded_account_payments_by_turned_on_autodebet))
        account_payments = qs.get_bucket_6_by_range(
            sub_bucket.start_dpd, sub_bucket.end_dpd
        ).exclude(account_id__in=excluded_account_ids)
        # not sent to intelix
        unsent_payments = qs.get_bucket_6_by_range(
            sub_bucket.start_dpd, sub_bucket.end_dpd
        )
        not_sent_filter_criteria = dict(
            account_id__in=assigned_to_vendor
        )
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                unsent_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            unsent_payments = unsent_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            unsent_payments, ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_TO_THIRD_PARTY'],
            not_sent_filter_criteria)

        not_sent_account_payments = qs.get_bucket_6_by_range(
            sub_bucket.start_dpd, sub_bucket.end_dpd
        ).filter(id__in=not_sent_oldest_account_payment_ids)

        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")
        excluded_account_payments_by_pending_refinancing = qs_account_payments_excluded_by_pending_refinancing. \
            get_bucket_6_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)

        excluded_account_payments_by_intelix_blacklist = \
            qs_account_payments_excluded_by_intelix_blacklist.get_bucket_6_by_range(
                sub_bucket.start_dpd, sub_bucket.end_dpd
            )

    elif bucket_name == 'JULO_B1_NON_CONTACTED':
        excluded_account_ids = list(chain(excluded_ptp_account_ids,
                                          excluded_account_ids_by_intelix_blacklist,
                                          excluded_account_payments_by_turned_on_autodebet))
        non_contact_bucket_account_payments = qs.bucket_1_t1_t10([]).filter(
            account_id__in=excluded_bucket_level_account_ids).exclude(
                account_id__in=excluded_account_ids
            )
        non_contact_bucket_account_payments = non_contact_bucket_account_payments

        # not sent to intelix
        not_sent_account_payments = qs.bucket_1_t1_t10([])
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))

        not_sent_account_payments = qs.bucket_1_t1_t10([]).filter(
            id__in=not_sent_oldest_account_payment_ids).exclude(
            account_id__in=excluded_account_ids
        )

        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )

        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")

        if excluded_account_ids_by_intelix_blacklist:
            excluded_account_payments_by_intelix_blacklist = \
                qs_account_payments_excluded_by_intelix_blacklist.bucket_1_t1_t10([])
            excluded_account_payments_by_intelix_blacklist = \
                excluded_account_payments_by_intelix_blacklist.extra(
                    select={
                        'reason': ReasonNotSentToDialer.UNSENT_REASON[
                            'USER_REQUESTED_INTELIX_REMOVAL']
                    }
                ).values("id", "reason")
            not_sent_to_dialer_account_payments += list(
                excluded_account_payments_by_intelix_blacklist
            )

        return non_contact_bucket_account_payments, not_sent_to_dialer_account_payments

    elif bucket_name == 'JULO_B2_NON_CONTACTED':
        squad_ids = CollectionSquad.objects\
            .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_2)\
            .values_list('id', flat=True)
        non_contact_squad_account_payments = CollectionHistory.objects\
            .get_bucket_non_contact_squads(squad_ids)

        excluded_account_ids = list(chain(excluded_ptp_account_ids,
                                          excluded_account_ids_by_intelix_blacklist,
                                          excluded_account_payments_by_turned_on_autodebet))
        non_contact_bucket_account_payments = qs.bucket_list_t11_to_t40().\
            exclude(account_id__in=excluded_account_ids).filter(
                account_id__in=excluded_bucket_level_account_ids)

        non_contact_bucket_account_payments = non_contact_bucket_account_payments

        # record not sent account payment
        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']])
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)

        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))

        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']]).filter(
            id__in=not_sent_oldest_account_payment_ids).exclude(
            account_id__in=excluded_account_ids
        )

        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")

        if excluded_account_ids_by_intelix_blacklist:
            excluded_account_payments_by_intelix_blacklist = \
                qs_account_payments_excluded_by_intelix_blacklist.bucket_list_t11_to_t40()
            excluded_account_payments_by_intelix_blacklist = \
                excluded_account_payments_by_intelix_blacklist.extra(
                    select={
                        'reason': ReasonNotSentToDialer.UNSENT_REASON[
                            'USER_REQUESTED_INTELIX_REMOVAL']
                    }
                ).values("id", "reason")
            not_sent_to_dialer_account_payments += list(
                excluded_account_payments_by_intelix_blacklist
            )

        return non_contact_squad_account_payments, non_contact_bucket_account_payments, \
               not_sent_to_dialer_account_payments

    elif bucket_name == 'JULO_B3_NON_CONTACTED':
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        non_contact_bucket_account_payments = []
        squad_ids = CollectionSquad.objects \
            .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_3) \
            .values_list('id', flat=True)
        non_contact_squad_account_payments = CollectionHistory.objects \
            .get_bucket_non_contact_squads(squad_ids)

        excluded_account_ids = list(chain(excluded_ptp_account_ids,
                                          excluded_account_ids_by_intelix_blacklist,
                                          excluded_account_payments_by_turned_on_autodebet))
        non_contact_bucket_account_payments = qs.bucket_list_t41_to_t70(). \
            exclude(account_id__in=excluded_account_ids).filter(
            account_id__in=excluded_bucket_level_account_ids).filter(
            id__in=oldest_account_payment_ids)
        sending_b3_to_vendor = []
        if experiment_setting and experiment_setting['toggle'] == 'Exp1':
            today = timezone.localtime(timezone.now()).date()
            not_nc = CenterixCallResult.RPC + CenterixCallResult.WPC
            start_checking_date = today - timedelta(days=5)
            non_contact_bucket_account_payment_ids = SentToDialer.objects.filter(
                cdate__date__gte=start_checking_date,
                bucket='JULO_B3',
                account_payment_id__in=oldest_account_payment_ids,
                account_payment__skiptracehistory__call_result__name__in=CenterixCallResult.NC,
                account_payment__skiptracehistory__cdate__date__gte=start_checking_date). \
                exclude(account_payment__skiptracehistory__call_result__name__in=not_nc).\
                distinct('account_payment_id').values_list('account_payment_id',
                                                           flat=True)
            non_contact_bucket_account_payments = non_contact_bucket_account_payments.filter(
                id__in=non_contact_bucket_account_payment_ids)
            sending_b3_to_vendor = b3_vendor_distribution(
                non_contact_bucket_account_payments, experiment_setting, IntelixTeam.JULO_B3_NC)

        # record not sent account payment
        not_sent_account_payments_qs = qs.bucket_list_t41_to_t70().filter(
            account_id__in=excluded_bucket_level_account_ids).filter(
            id__in=oldest_account_payment_ids).exclude(pk__in=sending_b3_to_vendor)
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments_qs, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments_qs = not_sent_account_payments_qs.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)
        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments_qs, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))
            not_sent_account_payments_qs = not_sent_account_payments_qs.exclude(
                account_id__in=excluded_ptp_account_ids)

        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments_qs, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")

        if excluded_account_ids_by_intelix_blacklist:
            excluded_account_payments_by_intelix_blacklist = \
                qs_account_payments_excluded_by_intelix_blacklist.bucket_list_t41_to_t70()
            excluded_account_payments_by_intelix_blacklist = \
                excluded_account_payments_by_intelix_blacklist.extra(
                    select={
                        'reason': ReasonNotSentToDialer.UNSENT_REASON[
                            'USER_REQUESTED_INTELIX_REMOVAL']
                    }
                ).values("id", "reason")
            not_sent_to_dialer_account_payments += list(
                excluded_account_payments_by_intelix_blacklist
            )
        if sending_b3_to_vendor:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                non_contact_bucket_account_payments,
                ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR'],
                dict(pk__in=sending_b3_to_vendor))
            non_contact_bucket_account_payments = non_contact_bucket_account_payments.exclude(
                pk__in=sending_b3_to_vendor)

        return non_contact_squad_account_payments, non_contact_bucket_account_payments, \
               not_sent_to_dialer_account_payments

    elif bucket_name == 'JULO_B4_NON_CONTACTED':
        logger.info({
            "action": "get_account_payment_details_for_calling",
            "bucket": bucket_name,
            "info": "get account payment detail for B4 NC begin"
        })
        squad_ids = CollectionSquad.objects\
            .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_4)\
            .values_list('id', flat=True)
        non_contact_squad_account_payments = CollectionHistory.objects\
            .get_bucket_non_contact_squads(squad_ids)
        assigned_to_vendor_account_payment_ids = get_assigned_b4_account_payment_ids_to_vendors()
        excluded_account_ids = list(chain(excluded_ptp_account_ids,
                                          excluded_account_ids_by_intelix_blacklist,
                                          excluded_account_payments_by_turned_on_autodebet))
        non_contact_bucket_account_payments = qs.bucket_list_t71_to_t90().\
            exclude(account_id__in=excluded_account_ids).filter(account_id__in=excluded_bucket_level_account_ids).\
            exclude(id__in=assigned_to_vendor_account_payment_ids)
        non_contact_bucket_account_payments = non_contact_bucket_account_payments

        # record not sent account payment
        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']])
        # exclude for turned on autodebet
        if excluded_account_payments_by_turned_on_autodebet:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
                dict(account_id__in=excluded_account_payments_by_turned_on_autodebet))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_account_payments_by_turned_on_autodebet)

        if assigned_to_vendor_account_payment_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_TO_THIRD_PARTY'],
                dict(id__in=assigned_to_vendor_account_payment_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(id__in=assigned_to_vendor_account_payment_ids)

        if excluded_ptp_account_ids:
            not_sent_to_dialer_account_payments += format_not_sent_payment(
                not_sent_account_payments, ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
                dict(account_id__in=excluded_ptp_account_ids))
            not_sent_account_payments = not_sent_account_payments.exclude(
                account_id__in=excluded_ptp_account_ids)

        not_sent_account_payments = qs.determine_bucket_by_range(
            [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']]).filter(
            id__in=not_sent_oldest_account_payment_ids).exclude(
            account_id__in=excluded_account_ids
        )
        not_sent_filter_criteria = dict(
            account__status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS
        )
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            not_sent_account_payments, [''], not_sent_filter_criteria,
            extra_field="concat('Account Status is ', account.status_code)")

        if excluded_account_ids_by_intelix_blacklist:
            excluded_account_payments_by_intelix_blacklist = \
                qs_account_payments_excluded_by_intelix_blacklist.bucket_list_t71_to_t90()
            excluded_account_payments_by_intelix_blacklist = \
                excluded_account_payments_by_intelix_blacklist.extra(
                    select={
                        'reason': ReasonNotSentToDialer.UNSENT_REASON[
                            'USER_REQUESTED_INTELIX_REMOVAL']
                    }
                ).values("id", "reason")
            not_sent_to_dialer_account_payments += list(
                excluded_account_payments_by_intelix_blacklist
            )

        logger.info({
            "action": "get_account_payment_details_for_calling",
            "bucket": bucket_name,
            "account_payment_ids": list(non_contact_bucket_account_payments.values_list('id', flat=True))
        })

        return non_contact_squad_account_payments, non_contact_bucket_account_payments, \
               not_sent_to_dialer_account_payments

    elif bucket_name == 'GRAB':
        halt_account_ids = list(set(Loan.objects.filter(
            loan_status=LoanStatusCodes.HALT).values_list('account_id', flat=True)))
        halted_account_payment_ids = Payment.objects.filter(
            loan__loan_status=LoanStatusCodes.HALT).values_list('account_payment_id', flat=True)
        exclude_halt_account_ids = []
        for halt_account in halt_account_ids:
            loan_flag = Loan.objects.filter(account_id=halt_account).exclude(
                loan_status=LoanStatusCodes.HALT).exists()
            if not loan_flag:
                exclude_halt_account_ids.append(halt_account)
            else:
                not_halted_loans = Loan.objects.filter(account_id=halt_account).exclude(
                    loan_status=LoanStatusCodes.HALT).values_list('id', flat=True)
                active_account_payments = Payment.objects.filter(
                    loan__id__in=not_halted_loans).values_list('account_payment_id', flat=True)
                halted_account_payment_ids = list(set(halted_account_payment_ids) - set(active_account_payments))
        today = timezone.localtime(timezone.now()).date()
        excluded_account_ids = list(chain(
            assigned_account_ids,
            excluded_ptp_account_ids,
            exclude_halt_account_ids
        ))
        account_payment_grab = AccountPayment.objects.\
            annotate(
                    acc_pmt_dpd=ExpressionWrapper(
                        today - F('due_date'),
                        output_field=IntegerField()))\
            .filter(due_date__lt=today)\
            .get_grab_payments()\
            .exclude(id__in=account_payment_refinancing)\
            .exclude(account_id__in=excluded_account_ids)\
            .exclude(id__in=halted_account_payment_ids).\
            filter(acc_pmt_dpd__gte=GRAB_INTELIX_CALL_DELAY_DAYS)
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        account_payments = account_payment_grab.filter(id__in=oldest_account_payment_ids)
        return account_payments

    if excluded_account_payments_by_pending_refinancing:
        excluded_account_payments_by_pending_refinancing = excluded_account_payments_by_pending_refinancing\
            .extra(select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PENDING_REFINANCING']})\
            .values("id", "reason")
        not_sent_to_dialer_account_payments += list(excluded_account_payments_by_pending_refinancing)

    if excluded_account_payments_by_intelix_blacklist:
        excluded_account_payments_by_intelix_blacklist = \
            excluded_account_payments_by_intelix_blacklist.extra(
                select={
                    'reason': ReasonNotSentToDialer.UNSENT_REASON['USER_REQUESTED_INTELIX_REMOVAL']
                }
            ).values("id", "reason")
        not_sent_to_dialer_account_payments += list(
            excluded_account_payments_by_intelix_blacklist)

    

    return account_payments, not_sent_to_dialer_account_payments


def exclude_pending_refinancing_per_bucket(bucket_name, grouped_account_payments_by_bucket):
    today = timezone.localtime(timezone.now()).date()
    # to exclude cohort campaign R4 from pending refinancing
    active_loan_refinancing_campaign = LoanRefinancingRequestCampaign.objects.filter(
        expired_at__gte=today,
        offer='R4',
        status='Success'
    ).values_list('account_id', flat=True)
    today_minus_4 = today - relativedelta(days=4)
    account_id_pending_refinancing = LoanRefinancingRequest.objects.select_related(
        'account').filter(
        status=CovidRefinancingConst.STATUSES.approved,
        udate__date__gte=today_minus_4,
        udate__date__lt=today,
        account_id__isnull=False,
        account_id__in=grouped_account_payments_by_bucket.values_list('account_id', flat=True)
    ).values_list('account_id', flat=True)
    if bucket_name in {IntelixTeam.JULO_B1, IntelixTeam.JULO_B1_NC,
                       IntelixTeam.JTURBO_B1, IntelixTeam.JTURBO_B1_NC}:
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_1_DPD['to'] - 3)
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_1_DPD['to'])
    elif bucket_name in {IntelixTeam.JULO_B2, IntelixTeam.JULO_B2_NC,
                         IntelixTeam.JTURBO_B2, IntelixTeam.JTURBO_B2_NC}:
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_2_DPD['to'] - 3)
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_2_DPD['to'])
    elif bucket_name in {IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC,
                         IntelixTeam.JTURBO_B3, IntelixTeam.JTURBO_B3_NC}:
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_3_DPD['to'] - 3)
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_3_DPD['to'])
    elif bucket_name in {IntelixTeam.JULO_B4, IntelixTeam.JULO_B4_NC,
                         IntelixTeam.JTURBO_B4, IntelixTeam.JTURBO_B4_NC}:
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_4_DPD['to'] - 3)
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_4_DPD['to'])
    else:
        return AccountPayment.objects.none()

    account_payment_refinancing = grouped_account_payments_by_bucket.filter(
        account_id__in=account_id_pending_refinancing).exclude(
        due_date__range=[bucket_dpd_date_from, bucket_dpd_date_to]).exclude(
        account_id__in=active_loan_refinancing_campaign
    )

    return account_payment_refinancing


def get_pending_refinancing_by_account_ids(account_ids, duration=None):
    today = timezone.localtime(timezone.now()).date()
    loan_refinancing_requests = LoanRefinancingRequest.objects.select_related('account').filter(
        status=CovidRefinancingConst.STATUSES.approved,
        account_id__in=account_ids,
        account_id__isnull=False,
        loanrefinancingrequestcampaign__isnull=True,
    )
    if duration:
        duration_date = today - relativedelta(days=duration)
        loan_refinancing_requests.filter(
            udate__date__gte=duration_date,
        )

    return loan_refinancing_requests


def get_excluded_bucket_account_level_ids_improved(
        bucket_name, list_grouped_by_bucket_account_payment_ids):
    if len(list_grouped_by_bucket_account_payment_ids) == 0:
        return AccountPayment.objects.none()

    today = timezone.localtime(timezone.now()).date()
    bucket_dpd_date_from = None
    bucket_dpd_date_to = None
    skiptrace_history_filter = dict(
        excluded_from_bucket=True,
        account_payment_id__isnull=False,
        account_payment_id__in=list_grouped_by_bucket_account_payment_ids)
    if bucket_name in (IntelixTeam.JULO_B1, IntelixTeam.JULO_B1_NC,
                       IntelixTeam.JTURBO_B1, IntelixTeam.JTURBO_B1_NC):
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_1_DPD['to'])
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_1_DPD['from'])
    elif bucket_name in (IntelixTeam.JULO_B2, IntelixTeam.JULO_B2_NC,
                         IntelixTeam.JTURBO_B2, IntelixTeam.JTURBO_B2_NC):
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_2_DPD['to'])
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_2_DPD['from'])
    elif bucket_name in (IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC,
                         IntelixTeam.JTURBO_B3, IntelixTeam.JTURBO_B3_NC):
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_3_DPD['to'])
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_3_DPD['from'])
    elif bucket_name in (IntelixTeam.JULO_B4, IntelixTeam.JULO_B4_NC,
                         IntelixTeam.JTURBO_B4, IntelixTeam.JTURBO_B4_NC):
        bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_4_DPD['to'])
        bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_4_DPD['from'])
    if  bucket_dpd_date_from and bucket_dpd_date_to:
        skiptrace_history_filter.update(dict(cdate__date__gte=bucket_dpd_date_from))

    return SkiptraceHistory.objects.select_related('account_payment').filter(
        **skiptrace_history_filter).only('account').order_by(
            'account', '-cdate').distinct('account').values_list('account', flat=True)


def exclude_active_ptp_account_payment_ids_improved(list_grouped_by_bucket_account_payment_ids):
    if len(list_grouped_by_bucket_account_payment_ids) == 0:
        return AccountPayment.objects.none()

    today = timezone.localtime(timezone.now()).date()
    return (
        PTP.objects.select_related('account_payment')
        .filter(
            ptp_date__gte=today,
            account_payment_id__isnull=False,
            account_payment_id__in=list_grouped_by_bucket_account_payment_ids,
        )
        .distinct('account')
        .values_list('account_id', flat=True)
    )


def get_active_ptp_by_account_ids(account_ids):
    if len(account_ids) == 0:
        return PTP.objects.none()

    today = timezone.localtime(timezone.now()).date()
    return PTP.objects.filter(
        ptp_date__gte=today,
        account_payment_id__isnull=False,
        account_id__in=account_ids,
    )


def get_exclude_account_ids_by_intelix_blacklist_improved(list_grouped_by_bucket_account_ids):
    if len(list_grouped_by_bucket_account_ids) == 0:
        return AccountPayment.objects.none()

    today = timezone.localtime(timezone.now()).date()
    exclude_ids = intelixBlacklist.objects.select_related('account').exclude(
        skiptrace__isnull=False).filter(
        Q(expire_date__gt=today) | Q(expire_date__isnull=True),
        account_id__in=list_grouped_by_bucket_account_ids,
    ).only('account_id').values_list('account_id', flat=True)

    return exclude_ids


def get_turned_on_autodebet_customer_exclude_for_dpd_plus_improved(
        list_grouped_by_bucket_account_ids, for_dpd='dpd_plus'):
    # 'for_dpd' parameter use as key dict
    # for now we have 3 key ["dpd_plus", "dpd_zero", "dpd_minus"]
    if len(list_grouped_by_bucket_account_ids) == 0:
        return AccountPayment.objects.none()

    autodebet_customer_turned_on = AccountPayment.objects.none()
    autodebet_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
        is_active=True
    )
    if autodebet_feature_setting:
        # validation for check parameter dpd plus is active
        if autodebet_feature_setting.parameters.get(for_dpd):
            autodebet_customer_turned_on = AutodebetAccount.objects.select_related(
                'account').filter(Q(is_use_autodebet=True) & Q(is_deleted_autodebet=False),
                account_id__in=list_grouped_by_bucket_account_ids
            ).distinct('account').values_list('account_id', flat=True)

    return autodebet_customer_turned_on


def get_exclude_account_ids_by_ana_above_2_mio(account_ids, bucket_name=DialerSystemConst.DIALER_BUCKET_1):
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=MinisquadFeatureSettings.DA2M_ACCOUNTS_EXPERIMENT,
        is_active=True
    )
    if feature_setting:
        if bucket_name in feature_setting.parameters.get('buckets',[]):
            today = timezone.localtime(timezone.now())
            cdate_range = [
                today.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1),
                today.replace(hour=2, minute=0, second=0, microsecond=0)
            ]
            return AccountDueAmountAbove2Mio.objects.filter(
                account_id__in=account_ids,
                cdate__range=cdate_range,
            ).values_list('account_id',flat=True)

    return AccountDueAmountAbove2Mio.objects.none()


def get_account_payment_details_for_calling_improved(bucket_name, experiment_setting=None):
    from juloserver.minisquad.services2.dialer_related import \
        get_eligible_account_payment_for_dialer_and_vendor_qs
    redis_client = get_redis_client()
    redis_excluded_account_keys = [
        'excluded_by_account_status_{}'.format(bucket_name)
    ]
    exclude_account_status_list = [
        JuloOneCodes.FRAUD_REPORTED,
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
        JuloOneCodes.SCAM_VICTIM
    ]
    grouped_account_payments_by_bucket = AccountPayment.objects.none()
    excluded_from_bucket_var = [
        'excluded_account_ids_by_dialer_service_blacklist',
        'excluded_account_ids_by_turned_on_autodebet']
    eligible_account_payment_ids = list(
        get_eligible_account_payment_for_dialer_and_vendor_qs().values_list('id', flat=True))
    qs = AccountPayment.objects.filter(id__in=eligible_account_payment_ids).exclude(
        account__status_id__in=exclude_account_status_list)
    if bucket_name == IntelixTeam.JULO_B1:
        grouped_account_payments_by_bucket = qs.bucket_1_t1_t10([])
        # determine which criteria for doing exclude from bucket
        excluded_from_bucket_var.extend(
            ['excluded_bucket_level_account_ids', 'excluded_ptp_account_ids'])
    elif bucket_name == IntelixTeam.JULO_B2:
        grouped_account_payments_by_bucket = qs.bucket_list_t11_to_t40()
        # determine which criteria for doing exclude from bucket
        excluded_from_bucket_var.extend(
            ['excluded_bucket_level_account_ids', 'excluded_ptp_account_ids'])
    elif bucket_name == IntelixTeam.JULO_B3:
        grouped_account_payments_by_bucket = qs.bucket_list_t41_to_t70()
        # determine which criteria for doing exclude from bucket
        excluded_from_bucket_var.extend(
            ['excluded_bucket_level_account_ids', 'excluded_ptp_account_ids'])
    elif bucket_name == IntelixTeam.JULO_B5:
        sub_bucket = SubBucket.sub_bucket_five(1)
        assigned_to_vendor_account_payment_ids = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True, account_payment__isnull=False
        ).distinct("account_payment__account_id").values_list(
            "account_payment__account_id", flat=True)
        if assigned_to_vendor_account_payment_ids:
            redis_key_name = 'b5_rule_assigned_to_vendor_account_payment_ids_{}'.format(
                bucket_name)
            redis_excluded_account_keys.append(redis_key_name)
            redis_client.set_list(redis_key_name, assigned_to_vendor_account_payment_ids)
        grouped_account_payments_by_bucket = qs.get_all_bucket_5(sub_bucket.end_dpd).exclude(
            account_id__in=assigned_to_vendor_account_payment_ids
        )
    elif bucket_name in (IntelixTeam.JULO_B6_1, IntelixTeam.JULO_B6_2):
        sub_bucket = SubBucket.sub_bucket_six(int(bucket_name[-1]))
        assigned_to_vendor_account_payment_ids = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True, account_payment__isnull=False
        ).distinct("account_payment__account_id").values_list(
            "account_payment__account_id", flat=True)
        if assigned_to_vendor_account_payment_ids:
            redis_key_name = 'b5_rule_assigned_to_vendor_account_payment_ids_{}'.format(
                bucket_name)
            redis_excluded_account_keys.append(redis_key_name)
            redis_client.set_list(redis_key_name, assigned_to_vendor_account_payment_ids)

        grouped_account_payments_by_bucket = qs.get_bucket_6_by_range(
            sub_bucket.start_dpd, sub_bucket.end_dpd
        ).exclude(account_id__in=assigned_to_vendor_account_payment_ids)
    elif bucket_name in IntelixTeam.NON_CONTACTED_BUCKET:
        if bucket_name == IntelixTeam.JULO_B1_NC:
            grouped_account_payments_by_bucket = qs.bucket_1_t1_t10([])
        elif bucket_name == IntelixTeam.JULO_B2_NC:
            grouped_account_payments_by_bucket = qs.bucket_list_t11_to_t40()
        elif bucket_name == IntelixTeam.JULO_B3_NC:
            grouped_account_payments_by_bucket = qs.bucket_list_t41_to_t70()
        excluded_bucket_level_account_ids = get_excluded_bucket_account_level_ids()
        grouped_account_payments_by_bucket = grouped_account_payments_by_bucket.filter(
            account_id__in=excluded_bucket_level_account_ids)
        # for prevent long query for non contacted will stored on redis and can use again
        # for write the not sent
        if grouped_account_payments_by_bucket.exists():
            redis_client.delete_key(
                RedisKey.CACHED_NON_CONTACTED_ACCOUNT_PAYMENT_IDS.format(bucket_name))
            redis_client.set_list(
                RedisKey.CACHED_NON_CONTACTED_ACCOUNT_PAYMENT_IDS.format(bucket_name),
                list(grouped_account_payments_by_bucket.values_list('id', flat=True)))

        excluded_from_bucket_var.extend(['excluded_ptp_account_ids'])

    if not grouped_account_payments_by_bucket.exists():
        return AccountPayment.objects.none()
    # exclude pending refinancing
    account_payment_refinancing = exclude_pending_refinancing()
    # create redis key for store exclude pending refinancing for processed on
    # process_not_sent_to_dialer_per_bucket this function
    if account_payment_refinancing.exists():
        redis_key_name = 'exclude_payment_refinancing_{}'.format(bucket_name)
        redis_excluded_account_keys.append(redis_key_name)
        redis_client.delete_key(redis_key_name)
        account_payment_refinancing_ids = list(
            account_payment_refinancing.values_list('id', flat=True))
        redis_client.set_list(redis_key_name, account_payment_refinancing_ids)
        grouped_account_payments_by_bucket = grouped_account_payments_by_bucket.exclude(
            id__in=account_payment_refinancing_ids)
    # general excluded
    excluded_account_ids = []
    grouped_account_and_account_payment_list = \
        list(grouped_account_payments_by_bucket.values('id', 'account_id'))
    for exclude_key in excluded_from_bucket_var:
        criteria_excluded_account_ids = []
        if exclude_key == 'excluded_bucket_level_account_ids':
            criteria_excluded_account_ids = get_excluded_bucket_account_level_ids()
        elif exclude_key == 'excluded_ptp_account_ids':
            criteria_excluded_account_ids = exclude_active_ptp_account_payment_ids()
        elif exclude_key == 'excluded_account_ids_by_dialer_service_blacklist':
            criteria_excluded_account_ids = get_exclude_account_ids_by_intelix_blacklist()
        elif exclude_key == 'excluded_account_ids_by_turned_on_autodebet':
            criteria_excluded_account_ids = \
                get_turned_on_autodebet_customer_exclude_for_dpd_plus()
        if len(criteria_excluded_account_ids) > 0:
            # store excluded account ids by criteria
            # will used on juloserver.minisquad.
            # tasks2.intelix_task2.process_not_sent_to_dialer_per_bucket
            converted_criteria = list(criteria_excluded_account_ids)
            redis_key_name = '{}_{}'.format(exclude_key, bucket_name)
            redis_excluded_account_keys.append(redis_key_name)
            redis_client.delete_key(redis_key_name)
            redis_client.set_list(redis_key_name, converted_criteria)
            excluded_account_ids.extend(converted_criteria)
    grouped_account_payments_by_bucket = grouped_account_payments_by_bucket.exclude(
        account_id__in=excluded_account_ids
    )
    # exclude special case
    if bucket_name == IntelixTeam.JULO_B3:
        block_traffic_intelix_on = FeatureSetting.objects.get_or_none(
            feature_name='block_traffic_intelix', is_active=True)
        if block_traffic_intelix_on:
            excluded_nc_account_payment_ids = SentToDialer.objects.filter(
                cdate__date=timezone.now().date(),
                bucket='JULO_B3_NON_CONTACTED',
                account_payment_id__isnull=False,
            ).values_list('account_payment', flat=True)
            excluded_sent_to_vendor_nc_b3_account_payment_ids = NotSentToDialer.objects.filter(
                cdate__date=timezone.now().date(),
                bucket='JULO_B3_NON_CONTACTED',
                account_payment_id__isnull=False,
                unsent_reason='sending b3 to vendor',
            ).values_list('account_payment', flat=True)
            excluded_account_payment_ids = list(excluded_nc_account_payment_ids) + list(
                excluded_sent_to_vendor_nc_b3_account_payment_ids)
            grouped_account_payments_by_bucket = grouped_account_payments_by_bucket.exclude(
                id__in=excluded_account_payment_ids)
            if len(excluded_account_payment_ids) > 0:
                redis_key_name = 'excluded_account_payment_ids_block_traffic_dialer_service_{}'.format(
                    bucket_name)
                redis_excluded_account_keys.append(redis_key_name)
                redis_client.set_list(redis_key_name, excluded_account_payment_ids)

            block_intelix_params = block_traffic_intelix_on.parameters
            account_payment_ids_sent_to_b3_vendor = b3_vendor_distribution(
                grouped_account_payments_by_bucket, block_intelix_params, IntelixTeam.JULO_B3)
            if len(account_payment_ids_sent_to_b3_vendor) > 0:
                redis_key_name = 'account_payment_ids_sent_to_b3_vendor_{}'.format(bucket_name)
                redis_excluded_account_keys.append(redis_key_name)
                redis_client.set_list(redis_key_name, account_payment_ids_sent_to_b3_vendor)
                grouped_account_payments_by_bucket = grouped_account_payments_by_bucket.exclude(
                    pk__in=account_payment_ids_sent_to_b3_vendor)
    elif bucket_name == IntelixTeam.JULO_B3_NC and experiment_setting and \
            experiment_setting['toggle'] == 'Exp1':
        today = timezone.localtime(timezone.now()).date()
        not_nc = CenterixCallResult.RPC + CenterixCallResult.WPC
        start_checking_date = today - timedelta(days=5)
        non_contact_bucket_account_payment_ids = SentToDialer.objects.select_related(
            'account_payment').filter(
            cdate__date__gte=start_checking_date,
            bucket='JULO_B3',
            account_payment__skiptracehistory__call_result__name__in=CenterixCallResult.NC,
            account_payment__skiptracehistory__cdate__date__gte=start_checking_date). \
            exclude(account_payment__skiptracehistory__call_result__name__in=not_nc). \
            distinct('account_payment_id').values_list('account_payment_id',
                                                       flat=True)
        grouped_account_payments_by_bucket = grouped_account_payments_by_bucket.filter(
            id__in=non_contact_bucket_account_payment_ids)
        account_payment_ids_sent_to_b3_nc_vendor = b3_vendor_distribution(
            grouped_account_payments_by_bucket, experiment_setting, IntelixTeam.JULO_B3_NC)
        if len(account_payment_ids_sent_to_b3_nc_vendor) > 0:
            redis_key_name = 'account_payment_ids_sent_to_b3_vendor_{}'.format(bucket_name)
            redis_excluded_account_keys.append(redis_key_name)
            # delete if exist so the data will always new
            redis_client.delete_key(redis_key_name)
            redis_client.set_list(redis_key_name, account_payment_ids_sent_to_b3_nc_vendor)
            grouped_account_payments_by_bucket = grouped_account_payments_by_bucket.exclude(
                pk__in=account_payment_ids_sent_to_b3_nc_vendor)
    # will used on juloserver.minisquad.
    # tasks2.intelix_task2.process_not_sent_to_dialer_per_bucket
    # for record not sent to dialer
    if redis_excluded_account_keys:
        redis_client.set_list(
            RedisKey.EXCLUDED_KEY_LIST_OF_ACCOUNT_IDS_PER_BUCKET.format(bucket_name),
            redis_excluded_account_keys
        )
    return grouped_account_payments_by_bucket



def get_transaction_amount(payment_events):
    transaction_amount = 0
    for payment_event in payment_events:
        if payment_event.event_type == 'payment':
            transaction_amount += payment_event.event_payment

    return transaction_amount


def insert_data_into_commission_table_for_j1(payment_events):
    """insert data to commission table on payment event made"""
    if not payment_events:
        logger.info({
            'method': 'insert_data_into_commission_table',
            'message': 'payment_events not found',
            'payment_events': payment_events,
        })
        return

    paid_amount = get_transaction_amount(payment_events)
    payment_event = payment_events[0]
    account_payment = payment_event.payment.account_payment

    paid_date = account_payment.paid_date
    ptp = PTP.objects.filter(
        account_payment=account_payment
    ).last()

    if not ptp:
        logger.info({
            'method': 'insert_data_into_commission_table',
            'message': 'this account payment does not have ptp',
            'account_payment': account_payment.id
        })
        return

    if ptp and paid_date < ptp.cdate.date():
        logger.info({
            'method': 'insert_data_into_commission_table',
            'message': 'this ptp already expired',
            'account_payment': account_payment.id
        })

        return

    if ptp and paid_date > ptp.ptp_date:
        logger.info({
            'method': 'insert_data_into_commission_table',
            'message': 'paid after ptp_date',
            'account_payment': account_payment.id
        })
        return

    actual_agent = None
    today = timezone.localtime(timezone.now()).date()
    previous_commission = CommissionLookup.objects.filter(
        account=account_payment.account,
        cdate__date=today
    ).last()

    if previous_commission is not None:
        actual_agent = previous_commission.agent if \
            previous_commission.agent else None

    ptp_agent_assigned = ptp.agent_assigned
    if ptp_agent_assigned:
        actual_agent = Agent.objects.get_or_none(user=ptp_agent_assigned)
    if actual_agent is None:
        logger.info({
            'method': 'insert_data_into_commission_table_for_j1',
            'error': 'failed to insert into commission table',
            'message': 'agent not found',
            'account_payment': account_payment.id
        })

        return

    CommissionLookup.objects.create(
        account_payment=account_payment,
        payment_amount=paid_amount,
        credited_amount=paid_amount,
        agent_id=actual_agent.user_id,
        collected_by=CollectedBy.AGENT,
        account=account_payment.account
    )

    return


def format_not_sent_payment(base_qs, reasons, filter_criteria, extra_field=None, field_id_name="id"):
    all_reasons = reasons
    if type(reasons) == list:
        all_reasons = "''"
        if len(reasons) > 0:
            formated_reasons = []
            for reason in reasons:
                formated_reasons.append(reason.replace("'", ""))
            formated_reasons = ", ".join(formated_reasons)
            if extra_field:
                all_reasons = "concat('{}', {})".format(
                    formated_reasons, extra_field)
            else:
                all_reasons = "'{}'".format(formated_reasons)

    payment_or_account_payments = base_qs.filter(**filter_criteria).extra(
        select={'reason': all_reasons}).values(field_id_name, "reason")
    return list(payment_or_account_payments)


def record_not_sent_to_intelix(
        payments_or_account_payments, dialer_task, bucket_name, is_julo_one=False):
    not_sent_data = []
    if not is_julo_one:
        for item in payments_or_account_payments:
            payment_id = item.get('id')
            if not payment_id:
                payment_id = item.get('payment_id')

            payment = Payment.objects.get(pk=payment_id)
            loan = payment.loan
            excluded_bucket_level_loan = SkiptraceHistory.objects.filter(
                excluded_from_bucket=True,
                loan=loan
            )
            is_paid_off = PaymentStatusCodes.PAID_ON_TIME <= payment.payment_status_id <= \
                          PaymentStatusCodes.PAID_LATE
            paid_off_timestamp = None
            if is_paid_off:
                payment_history = payment.paymenthistory_set.filter(
                    payment_new_status_code__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
                )
                if payment_history:
                    paid_off_timestamp = payment_history.last().cdate

            not_sent_data.append(NotSentToDialer(
                loan=loan,
                payment=payment,
                bucket=bucket_name,
                dpd=payment.due_late_days,
                is_excluded_from_bucket=True if excluded_bucket_level_loan else False,
                is_paid_off=is_paid_off,
                paid_off_timestamp=paid_off_timestamp,
                unsent_reason=item.get('reason'),
                dialer_task=dialer_task
            ))
    else:
        for item in payments_or_account_payments:
            account_payment_id = item.get('id')
            if not account_payment_id:
                account_payment_id = item.get('account_payment_id')

            account_payment = AccountPayment.objects.get(pk=account_payment_id)
            account = account_payment.account
            excluded_bucket_level_account = SkiptraceHistory.objects.filter(
                excluded_from_bucket=True,
                account=account
            )
            is_paid_off = PaymentStatusCodes.PAID_ON_TIME <= account_payment.status_id <=\
                          PaymentStatusCodes.PAID_LATE
            paid_off_timestamp = None
            if is_paid_off:
                account_payment_history = account_payment.accountpaymentstatushistory_set.filter(
                    status_new__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
                )
                paid_off_timestamp = account_payment_history.last().cdate

            not_sent_data.append(NotSentToDialer(
                account_payment=account_payment,
                account=account,
                bucket=bucket_name,
                dpd=account_payment.dpd,
                is_excluded_from_bucket=True if excluded_bucket_level_account else False,
                is_paid_off=is_paid_off,
                paid_off_timestamp=paid_off_timestamp,
                unsent_reason=item.get('reason'),
                is_j1=True,
                dialer_task=dialer_task
            ))
    NotSentToDialer.objects.bulk_create(not_sent_data)


def get_not_sent_to_intelix_account_payments_dpd_minus(
        dpd, collection_model_account_payments, oldest_account_payment_ids
):
    account_payment_id_sent_to_intelix_j1 = collection_model_account_payments.values_list(
        'account_payment_id', flat=True)
    not_sent_non_risky_j1_customer = AccountPayment.objects.due_soon(abs(dpd)).filter(
        id__in=oldest_account_payment_ids).exclude(
        id__in=list(account_payment_id_sent_to_intelix_j1)
    ).extra(
        select={'reason': ReasonNotSentToDialer.UNSENT_REASON['NON_RISKY_CUSTOMERS']}
    ).values("id", "reason")

    return list(not_sent_non_risky_j1_customer)


def insert_col_history_data_based_on_call_result(
    payment, user, call_result, is_julo_one=False, is_grab=False, is_dana=False):
    """Insert data to collection history table based on call result
        as historical data
    Arguments:
        payment {[obj]}
        user {[obj]}
        call_result {[obj]}
        is_grab -- boolean (used to indicate if grab account)
    """
    sentry_client = get_julo_sentry_client()

    if not user:
        return

    if user.is_anonymous():
        return

    try:
        agent = Agent.objects.get(user=user)
    except ObjectDoesNotExist:
        sentry_client.captureException()
        logger.info({
            'error': 'failed to insert data to collection history',
            'message': 'agent does not exist',
            'agent': user,
            'payment': payment.id,
            'is_julo_one': is_julo_one
        })

        return

    if not is_julo_one and not is_grab:
        latest_collection_history_list = CollectionHistory.objects.filter(
            payment=payment, last_current_status=True)
    else:
        latest_collection_history_list = CollectionHistory.objects.filter(
            account_payment=payment, last_current_status=True)

    latest_collection_history = latest_collection_history_list.last()

    # we only insert wpc/nc into squad when there is rpc before
    if call_result.name not in CenterixCallResult.RPC and \
            latest_collection_history is None:
        logger.info({
            'info': 'failed to insert data to collection history',
            'message': 'call result is wpc/nc',
            'agent': user.id,
            'payment': payment.id
        })
        if not is_julo_one and not is_grab and not is_dana:
            skiptrace_history = SkiptraceHistory.objects.filter(
                payment=payment).last()
            exclude_payment_from_daily_upload(skiptrace_history)
        elif is_grab:
            skiptrace_history = GrabSkiptraceHistory.objects.filter(
                account_payment=payment).last()

            exclude_payment_from_daily_upload(skiptrace_history, True)
        elif is_dana:
            return
        else:
            skiptrace_history = SkiptraceHistory.objects.filter(
                account_payment=payment).last()

            exclude_payment_from_daily_upload(skiptrace_history, True)
        return
    # since dana doesnt have noncontacted we can ealry return here
    if is_dana:
        return

    last_ptp_status = False
    squad_id = None

    if latest_collection_history is not None:
        last_ptp_status = latest_collection_history.is_ptp

    is_ptp = call_result.name == 'RPC - PTP' or last_ptp_status is True
    ptp_or_b4_agent = agent.user

    # J1 will not check squad
    if not is_julo_one and not is_grab:
        if not agent.squad:
            logger.info({
                'error': 'failed to insert data to collection history',
                'message': 'agent does not have squad id',
                'agent': user.id,
                'payment': payment.id,
                'is_julo_one': is_julo_one
            })

            return

        today = timezone.localtime(timezone.now()).date()
        group_name = agent.squad.group.name

        dpd_dict = {
            JuloUserRoles.COLLECTION_BUCKET_1: (5, BucketConst.BUCKET_1_DPD['to']),
            JuloUserRoles.COLLECTION_BUCKET_2: (
                BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']
            ),
            JuloUserRoles.COLLECTION_BUCKET_3: (
                BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
            ),
            JuloUserRoles.COLLECTION_BUCKET_4: (
                BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']
            ),
            JuloUserRoles.COLLECTION_BUCKET_5: (BucketConst.BUCKET_5_DPD, 9999)
        }

        dpd1, dpd2 = dpd_dict[group_name]
        payment_dpd = (today - payment.due_date).days

        # to make sure that no agent can call cross bucket
        if payment_dpd < dpd1 or payment_dpd > dpd2:
            logger.info({
                'error': 'failed to insert data to collection history',
                'message': 'agent is not belong to the correct bucket',
                'agent': user.id,
                'payment': payment.id,
                'squad': agent.squad_id,
                'is_julo_one': is_julo_one
            })

            return

        squad_id = agent.squad_id

        bucket = agent.squad.group.name
        # the second OR condition is to determine whether the last active
        # status is ptp or not. If it's ptp and rpc , we will put the agent id for commission
        ptp_or_b4_agent = agent.user if call_result.name == 'RPC - PTP' or \
            last_ptp_status is True or bucket == JuloUserRoles.COLLECTION_BUCKET_4 else None

    loan_id = None
    payment_id = None
    account_id = None
    customer_id = None
    account_payment_id = None

    if not is_julo_one and not is_grab:
        loan = Loan.objects.get(payment=payment)
        loan_id = loan.id
        payment_id = payment.id
        application = loan.application
        customer_id = loan.customer.id
    else:
        account_id = payment.account.id
        account = payment.account
        application = account.customer.application_set.last()
        customer_id = application.customer.id
        account_payment_id = payment.id

    # we only need to check this in between bucket 2 until 4
    # bucket 2 start from dpd 11 and bucket 4 ended at dpd 100
    current_time = timezone.localtime(timezone.now())
    range1_ago = current_time - timedelta(days=11)
    range2_ago = current_time - timedelta(days=100)

    is_non_contacted = SkiptraceHistory.objects.not_paid_active(
        is_julo_one).filter(account_payment__due_date__range=[range2_ago, range1_ago],
                            excluded_from_bucket=True).filter(application=application).exists()

    # this handle if the payment is excluded from bucket level,
    # somehow agent got rpc from wa/manual call, it won't be excluded from bucket anymore

    try:
        with transaction.atomic():
            if latest_collection_history is not None:
                latest_collection_history.update_safely(last_current_status=False)

            if not is_non_contacted:
                collection_history = CollectionHistory.objects.create(
                    payment_id=payment_id,
                    agent=ptp_or_b4_agent,
                    squad_id=squad_id,
                    loan_id=loan_id,
                    customer_id=customer_id,
                    call_result=call_result,
                    is_ptp=is_ptp,
                    account_id=account_id,
                    account_payment_id=account_payment_id)

                if not is_julo_one and not is_grab:
                    exclude_payment_from_daily_upload(collection_history)
                elif is_grab:
                    pass
                else:
                    exclude_payment_from_daily_upload(collection_history, True)

            if not is_julo_one and not is_grab:
                CollectionAgentTask.objects.filter(
                    payment=payment,
                    unassign_time__isnull=True
                ).update(
                    actual_agent=ptp_or_b4_agent
                )

        logger.info({
            'message': 'success insert data to collection history table',
            'payment_id': payment.id,
            'squad': squad_id,
            'agent': user.id,
            'is_julo_one': is_julo_one
        })

    except IntegrityError:
        sentry_client.captureException()
        logger.info({
            'error': 'failed to insert data to collection history',
            'message': 'database error',
            'agent': user.id,
            'payment': payment.id,
            'is_julo_one': is_julo_one
        })


def get_exclude_account_ids_by_intelix_blacklist():
    today = timezone.localtime(timezone.now()).date()
    exclude_ids = intelixBlacklist.objects.exclude(skiptrace__isnull=False).filter(
        Q(expire_date__gt=today) | Q(expire_date__isnull=True)
    ).values_list('account_id', flat=True)

    return exclude_ids

def is_eligible_for_in_app_ptp(account):
    today = timezone.localtime(timezone.now()).date()
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IN_APP_PTP_SETTING,
        is_active=True).last()
    if not feature_setting:
        return False, None, None, None

    in_app_ptp_order = feature_setting.parameters.get('order_config')
    account_payment = account.get_last_unpaid_account_payment()
    if not account_payment:
        return False, None, None, None

    ptp = PTP.objects.filter(
        ptp_date__isnull=False,
        ptp_date__gte=today,
        account=account,
    )

    ongoing_ptp = ptp.filter(
        Q(ptp_status__isnull=True) | Q(ptp_status=PTPStatus.PARTIAL)
    ).last()

    if ongoing_ptp:
        return False, None, None, None

    dpd = account.dpd
    dpd_start_appear = feature_setting.parameters.get('dpd_start_appear') or InAppPTPDPD.DPD_START_APPEAR
    dpd_stop_appear = feature_setting.parameters.get('dpd_stop_appear') or InAppPTPDPD.DPD_STOP_APPEAR

    if dpd != None:
        if not dpd_start_appear <= dpd <= dpd_stop_appear:
            return False, None, None, None

    if account_payment.status_id in PaymentStatusCodes.paid_status_codes():
        ptp_date = None
        ptp = ptp.filter(account_payment=account_payment).last()
        if ptp:
            ptp_date = ptp.ptp_date

        return True, True, ptp_date, in_app_ptp_order

    return True, False, None, in_app_ptp_order

def block_intelix_comms_ptp(account, account_payment, ptp_date, comms_block_days):
    comms_block_data = dict(
        is_email_blocked=True,
        is_sms_blocked=True,
        is_robocall_blocked=True,
        is_cootek_blocked=True,
        is_pn_blocked=True,
        block_until=comms_block_days,
        account=account,
        impacted_payments=[account_payment.id]
    )
    CommsBlocked.objects.create(**comms_block_data)

def account_bucket_name_definition(last_unpaid_account_payment):
    is_nc = SkiptraceHistory.objects.filter(
        excluded_from_bucket=True,
        account_payment_id__isnull=False,
        account=last_unpaid_account_payment.account
    ).order_by('account', '-cdate').distinct('account').exists()
    bucket_number = last_unpaid_account_payment.bucket_number_special_case
    if bucket_number == 5:
        dpd = last_unpaid_account_payment.dpd
        if dpd < BucketConst.BUCKET_5_END_DPD:
            return IntelixTeam.JULO_B5
        if dpd in list(range(
                BucketConst.BUCKET_6_1_DPD['from'],
                BucketConst.BUCKET_6_1_DPD['to'] + 1)):
            return IntelixTeam.JULO_B6_1
        elif dpd in list(
                range(BucketConst.BUCKET_6_2_DPD['from'],
                      BucketConst.BUCKET_6_2_DPD['to'] + 1)):
            return IntelixTeam.JULO_B6_2
        elif dpd in list(
                range(BucketConst.BUCKET_6_3_DPD['from'],
                      BucketConst.BUCKET_6_3_DPD['to'] + 1)):
            return IntelixTeam.JULO_B6_3

        return IntelixTeam.JULO_B6_4

    bucket_name = f'JULO_B{bucket_number}'
    if is_nc:
        bucket_name += '_NON_CONTACTED'
    return bucket_name


def is_eligible_for_in_app_callback(account):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IN_APP_CALLBACK_SETTING,
        is_active=True).last()
    if not feature_setting:
        return False, None

    parameter = feature_setting.parameters
    last_unpaid_account_payment = account.get_last_unpaid_account_payment()
    if not last_unpaid_account_payment:
        return False, None

    bucket_name = account_bucket_name_definition(last_unpaid_account_payment)
    if bucket_name not in parameter['eligible_buckets']:
        return False, None

    today = timezone.localtime(timezone.now()).date()
    yesterday = today - relativedelta(days=1)
    check_connected_call = SkiptraceHistory.objects.filter(
        cdate__date__in=[yesterday, today],
        account_payment=last_unpaid_account_payment,
        call_result__name__in=IntelixResultChoiceMapping.CONNECTED_STATUS
    )
    if check_connected_call:
        return False, None

    callback_promise_data = CallbackPromiseApp.objects.filter(
        account_payment=last_unpaid_account_payment,
        bucket=bucket_name,
        selected_time_slot_start__isnull=False,
        selected_time_slot_end__isnull=False,
    )
    latest_callback_promise = callback_promise_data.last()
    if not latest_callback_promise:
        return True, False

    last_cdate_promise_callback = latest_callback_promise.cdate.date()
    next_call_cdate_schedule = last_cdate_promise_callback + relativedelta(days=1)
    end_schedule = latest_callback_promise.selected_time_slot_end.split(':')
    end_schedule_hour = int(end_schedule[0])
    end_schedule_minute = int(end_schedule[1])
    end_time = int(end_schedule_hour) * 60 + int(end_schedule_minute)
    current_time = timezone.localtime(timezone.now())
    current_time_comparison = current_time.hour * 60 + current_time.minute
    is_time_passed = current_time_comparison >= end_time
    is_miss_call_threshold = callback_promise_data.count() == int(
        parameter['miss_days_threshold'])

    if today > next_call_cdate_schedule and is_miss_call_threshold:
        # broken promise
        return False, None
    elif today == next_call_cdate_schedule:
        if is_miss_call_threshold and is_time_passed:
            return False, False

        if is_time_passed:
            # means broke promise but still can access UI
            return True, False
        elif not is_time_passed:
            # means eligible for in app, and already fill schedule
            return True, latest_callback_promise.selected_time_slot_start
    elif today < next_call_cdate_schedule:
        return True, latest_callback_promise.selected_time_slot_start
    # means eligible for in app, but not fill the schedule yet
    return True, False


def filter_account_id_based_on_experiment_settings(
        experiment_setting, account_payments):
    if not experiment_setting:
        return account_payments

    genesys_experiment_criteria = experiment_setting.criteria[DialerVendor.GENESYS]
    genesys_account_payments = account_payments.annotate(
        last_digit_account_id=F('account_id') % 10).filter(
        last_digit_account_id__in=genesys_experiment_criteria,
        account__application__partner_id__isnull=True,
        account__application__product_line_id__in=ProductLineCodes.j1(),
    )
    intelix_account_payments = account_payments.exclude(
        id__in=list(genesys_account_payments.values_list('id', flat=True))
    )
    return intelix_account_payments, genesys_account_payments


def j1_record_vendor_experiment_data(
        account_payments, experiment_dict, vendor_name=DialerVendor.INTELIX
):
    all_caller_experiment_data = []
    for account_payment in account_payments:
        account_payment_obj = account_payment if account_payment.__class__ is AccountPayment \
            else account_payment.account_payment
        experiment_data = dict(
            account_id=account_payment_obj.account.id,
            account_payment=account_payment_obj,
            bucket=experiment_dict['bucket_type'],
            experiment_group=vendor_name,
            experiment_setting=experiment_dict['experiment_setting']
        )

        all_caller_experiment_data.append(VendorQualityExperiment(**experiment_data))
    VendorQualityExperiment.objects.bulk_create(all_caller_experiment_data)


def exclude_cohort_campaign_from_normal_bucket(account_payments_queryset, is_jturbo=False, db_name=DEFAULT_DB):
    if not account_payments_queryset:
        return account_payments_queryset, []

    workflow_name = WorkflowConst.JULO_ONE
    if is_jturbo:
        workflow_name = WorkflowConst.JULO_STARTER
    current_date = timezone.localtime(timezone.now()).date()
    list_account_ids = list(account_payments_queryset.values_list('account_id', flat=True))
    cohort_account_ids = LoanRefinancingRequestCampaign.objects.using(db_name).filter(
        account_id__in=list_account_ids,
        status='Success',
        account__account_lookup__workflow__name=workflow_name,
        loan_refinancing_request__isnull=False,
        expired_at__gte=current_date
    ).exclude(
        loan_refinancing_request__status__in=CovidRefinancingConst.GRAVEYARD_STATUS
    ).values_list('account_id', flat=True)
    cohort_account_payment_ids = list(account_payments_queryset.filter(
        account_id__in=list(cohort_account_ids)
    ).values_list('id', flat=True))

    normal_bucket_account_payments = account_payments_queryset.exclude(
        id__in=cohort_account_payment_ids
    )
    return normal_bucket_account_payments, cohort_account_payment_ids


def bttc_filter_account_payments(experiment_setting, account_payments_queryset, dpd_list, db_name=DEFAULT_DB):
    if not experiment_setting:
        return [], account_payments_queryset

    j1_account_lookup = AccountLookup.objects.using(db_name).filter(name='JULO1').last()
    current_date = timezone.localtime(timezone.now()).date()
    bttc_account_payment_qs = account_payments_queryset.filter(
        account__account_lookup_id=j1_account_lookup.id
    )
    bttc_qs = PdBTTCModelResult.objects.using(db_name).filter(
        account_payment_id__in=list(bttc_account_payment_qs.values_list(
            'id', flat=True)),
        cdate__date=current_date,
        range_from_due_date__in=dpd_list,
        is_active=True
    )
    account_payments_queryset = account_payments_queryset.exclude(
        id__in=list(bttc_qs.values_list('account_payment_id', flat=True))
    )
    return account_payments_queryset, bttc_qs.values_list('id', flat=True)


def exclude_j1_partner_from_dialer_call():
    redisClient = get_redis_client()
    cached_excluded_partner_account_ids = redisClient.get_list(RedisKey.EXCLUDED_PARTNER_FROM_DIALER)
    if not cached_excluded_partner_account_ids:
        account_ids = Application.objects.filter(
            product_line__in=ProductLineCodes.j1_excluded_partner_from_dialer(),
            account__isnull=False
        ).values_list('account_id', flat=True)
        if account_ids:
            redisClient.set_list(
                RedisKey.EXCLUDED_PARTNER_FROM_DIALER, account_ids, timedelta(hours=4))
    else:
        cached_excluded_partner_account_ids = list(map(int, cached_excluded_partner_account_ids))

    return list(cached_excluded_partner_account_ids)


def separate_special_cohort_data_from_normal_bucket(
        data_qs, qs_type='AccountPayment'):
    if qs_type not in ('AccountPayment', 'Payment'):
        return data_qs, []
    special_cohort_feature_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.SPECIAL_COHORT_SPECIFIC_LOAN_DISBURSED_DATE
    ).last()
    if not special_cohort_feature_setting or not data_qs:
        return data_qs, []
    is_mtl = False if qs_type == 'AccountPayment' else True
    selected_field = 'account_id' if not is_mtl else 'loan_id'
    eligible_loan_or_account_ids = list(data_qs.values_list(
        selected_field, flat=True)
    )
    param = special_cohort_feature_setting.parameters
    start_month = param['start_month']
    end_month = param['end_month']
    year = param['year']
    if not start_month or not end_month or not year:
        return data_qs, []

    extra_where = "EXTRACT('month' FROM loan.fund_transfer_ts AT TIME ZONE 'Asia/Jakarta') >= {} AND" \
                  " EXTRACT('month' FROM loan.fund_transfer_ts AT TIME ZONE 'Asia/Jakarta') <= {} AND" \
                  " EXTRACT('year' FROM loan.fund_transfer_ts AT TIME ZONE 'Asia/Jakarta') = {}".\
        format(start_month, end_month, year)
    base_filter = {'account_id__in': eligible_loan_or_account_ids} if not is_mtl else \
        {'id__in': eligible_loan_or_account_ids}
    selected_field = 'account_id' if not is_mtl else 'id'
    special_cohort_loan_or_account_ids = list(Loan.objects.filter(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lte=LoanStatusCodes.LOAN_180DPD
    ).filter(**base_filter).extra(where=[extra_where]).values_list(selected_field, flat=True))
    special_cohort_filter = {'account_id__in': special_cohort_loan_or_account_ids} \
        if not is_mtl else {'id__in': special_cohort_loan_or_account_ids}
    eligible_payment_or_account_payment_qs = data_qs.filter(
        **special_cohort_filter)
    if not eligible_payment_or_account_payment_qs:
        return data_qs, []
    normal_bucket_payment_or_account_payment_qs = data_qs.exclude(
        id__in=list(eligible_payment_or_account_payment_qs.values_list('id', flat=True))
    )
    return normal_bucket_payment_or_account_payment_qs, eligible_payment_or_account_payment_qs


def serialize_data_for_sent_to_vendor(data, is_mtl=False):
    not_allow_duplicate_ids = []
    serialized_data = []
    for item in data:
        field_id = item['account_payment_id'] if not is_mtl else item['payment_id']
        # skip account id that already on new list of dictionaries
        if field_id in not_allow_duplicate_ids:
            continue
        not_allow_duplicate_ids.append(field_id)
        serialized_data.append(item)
    return serialized_data


def finalcall_v7_filter_account_payments(account_payments_queryset, dpd_list, db_name=DEFAULT_DB):
    j1_account_lookup = AccountLookup.objects.filter(name='JULO1').last()
    today_date = timezone.localtime(timezone.now()).date()
    finalcall_account_payment_qs = account_payments_queryset.filter(
        account__account_lookup_id=j1_account_lookup.id
    )
    finalcall_v7_qs = PdCollectionModelResult.objects.filter(
        account_payment_id__in=list(finalcall_account_payment_qs.values_list(
            'id', flat=True)),
        prediction_date=today_date,
        range_from_due_date__in=dpd_list,
        model_version='FinalCall B1 v7.0.0'
    )
    account_payments_v7_excluded = account_payments_queryset.exclude(
        id__in=list(finalcall_v7_qs.values_list('account_payment_id', flat=True))
    )
    finalcall_v7_account_payments = account_payments_queryset.filter(
        id__in=list(finalcall_v7_qs.values_list('account_payment_id', flat=True))
    )
    return account_payments_v7_excluded, finalcall_v7_account_payments.values_list('id', flat=True)


def get_turned_on_autodebet_customer_exclude_for_dpd_plus():
    autodebet_customer_turned_on = []
    autodebet_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
        is_active=True
    )
    if autodebet_feature_setting:
        # validation for check parameter dpd plus is active
        if autodebet_feature_setting.parameters.get('dpd_plus'):
            autodebet_customer_turned_on = AutodebetAccount.objects.filter(
                Q(is_use_autodebet=True) &
                Q(is_deleted_autodebet=False)
            ).distinct('account').values_list('account_id', flat=True)

    return autodebet_customer_turned_on


def get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet(
        dpd, oldest_account_payment_ids, collection_model_account_payments
):
    not_sent_turned_autodebet_j1_customer = []
    exclude_autodebet_turned_on = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
        is_active=True
    )
    if exclude_autodebet_turned_on:
        # validation for check parameter dpd minus is active
        if exclude_autodebet_turned_on.parameters.get('dpd_minus'):
            account_payment_id_sent_to_intelix_j1 = collection_model_account_payments.values_list(
                'account_payment_id', flat=True)
            all_account_payment_ids = list(oldest_account_payment_ids) + list(account_payment_id_sent_to_intelix_j1)
            not_sent_turned_autodebet_j1_customer = AccountPayment.objects.due_soon(abs(dpd)).filter(
                id__in=all_account_payment_ids
            ).filter(
                Q(account__autodebetaccount__is_use_autodebet=True) &
                Q(account__autodebetaccount__is_deleted_autodebet=False)
            )
            if not not_sent_turned_autodebet_j1_customer:
                return not_sent_turned_autodebet_j1_customer, oldest_account_payment_ids, \
                    collection_model_account_payments
            # exclude autodebet customer
            oldest_account_payment_ids = AccountPayment.objects.filter(
                pk__in=oldest_account_payment_ids
            ).exclude(
                pk__in=not_sent_turned_autodebet_j1_customer
            ).order_by('account', 'due_date').distinct('account').values_list('id', flat=True)
            collection_model_account_payments = collection_model_account_payments.exclude(
                account_payment_id__in=not_sent_turned_autodebet_j1_customer
            )
            not_sent_turned_autodebet_j1_customer = not_sent_turned_autodebet_j1_customer.extra(
                select={'reason': ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET']}
            ).values("id", "reason")

    return list(not_sent_turned_autodebet_j1_customer), oldest_account_payment_ids, \
        collection_model_account_payments


def get_b3_distribution_experiment(db_name=DEFAULT_DB):
    today_date = timezone.localtime(timezone.now()).date()
    b3_experiment = ExperimentSetting.objects.using(db_name).filter(
        is_active=True, code=ExperimentConst.B3_DISTRIBUTION_EXPERIMENT
    ).filter(
        (Q(start_date__date__lte=today_date) & Q(end_date__date__gte=today_date))
        | Q(is_permanent=True)
    ).last()

    return b3_experiment


@transaction.atomic()
def record_b3_distribution_data_to_experiment_group(
        account_payment_list, is_vendor=False):
    b3_experiment = get_b3_distribution_experiment()
    account_payment_ids = AccountPayment.objects.filter(
        pk__in=account_payment_list
    ).values_list('id', flat=True)
    if not b3_experiment or not account_payment_ids:
        return

    group = "b3 inhouse group"
    if is_vendor:
        group = "b3 vendor group"
    experiment_data = []
    for account_payment in account_payment_ids.iterator():
        experiment_data.append(
            ExperimentGroup(
                experiment_setting=b3_experiment,
                group=group,
                account_payment_id=account_payment
            )
        )

    return ExperimentGroup.objects.bulk_create(experiment_data)


def filter_intelix_blacklist_for_t0(account_payments, not_sent_account_payments):
    if not account_payments:
        return account_payments, not_sent_account_payments

    account_payment_ids = [account_payment.id for account_payment in account_payments]
    account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids)
    account_ids = list(account_payments.distinct(
        'account_id').values_list('account_id', flat=True))
    excluded_account_ids = \
        get_exclude_account_ids_by_intelix_blacklist_improved(account_ids)

    if not excluded_account_ids:
        return list(account_payments), not_sent_account_payments

    not_sent_account_payments += list(account_payments.filter(
        account_id__in=excluded_account_ids).extra(
        select={'reason': ReasonNotSentToDialer.UNSENT_REASON['USER_REQUESTED_INTELIX_REMOVAL']}
    ).values("id", "reason"))
    account_payments = list(account_payments.exclude(account_id__in=excluded_account_ids))

    return account_payments, not_sent_account_payments


def record_not_sent_to_dialer_service(
    payments_or_account_payments, 
    dialer_task, 
    bucket_name, 
    is_julo_one=False,
):
    not_sent_data = []
    if not is_julo_one:
        for item in payments_or_account_payments:
            payment_id = item.get('id')
            if not payment_id:
                payment_id = item.get('payment_id')

            payment = Payment.objects.get(pk=payment_id)
            loan = payment.loan
            excluded_bucket_level_loan = SkiptraceHistory.objects.filter(
                excluded_from_bucket=True,
                loan=loan
            )
            is_paid_off = PaymentStatusCodes.PAID_ON_TIME <= payment.payment_status_id <= \
                          PaymentStatusCodes.PAID_LATE
            paid_off_timestamp = None
            if is_paid_off:
                payment_history = payment.paymenthistory_set.filter(
                    payment_new_status_code__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
                )
                if payment_history:
                    paid_off_timestamp = payment_history.last().cdate

            not_sent_data.append(NotSentToDialer(
                loan=loan,
                payment=payment,
                bucket=bucket_name,
                dpd=payment.due_late_days,
                is_excluded_from_bucket=True if excluded_bucket_level_loan else False,
                is_paid_off=is_paid_off,
                paid_off_timestamp=paid_off_timestamp,
                unsent_reason=item.get('reason'),
                dialer_task=dialer_task
            ))
    else:
        for item in payments_or_account_payments:
            account_payment_id = item.get('id')
            if not account_payment_id:
                account_payment_id = item.get('account_payment_id')

            account_payment = AccountPayment.objects.get(pk=account_payment_id)
            account = account_payment.account
            excluded_bucket_level_account = SkiptraceHistory.objects.filter(
                excluded_from_bucket=True,
                account=account
            )
            is_paid_off = PaymentStatusCodes.PAID_ON_TIME <= account_payment.status_id <=\
                          PaymentStatusCodes.PAID_LATE
            paid_off_timestamp = None
            if is_paid_off:
                account_payment_history = account_payment.accountpaymentstatushistory_set.filter(
                    status_new__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
                )
                paid_off_timestamp = account_payment_history.last().cdate

            not_sent_data.append(NotSentToDialer(
                account_payment=account_payment,
                account=account,
                bucket=bucket_name,
                dpd=account_payment.dpd,
                is_excluded_from_bucket=True if excluded_bucket_level_account else False,
                is_paid_off=is_paid_off,
                paid_off_timestamp=paid_off_timestamp,
                unsent_reason=item.get('reason'),
                is_j1=True,
                dialer_task=dialer_task
            ))
    NotSentToDialer.objects.bulk_create(not_sent_data)


def update_collection_risk_verification_call_list(coll_risk_skiptrace_history):
    coll_risk_skiptrace_history_status = coll_risk_skiptrace_history.status
    coll_risk_skiptrace_history_agent = coll_risk_skiptrace_history.agent
    account = coll_risk_skiptrace_history.account
    collection_risk_list = CollectionRiskVerificationCallList.objects.filter(
        Q(is_verified=False) | Q(is_connected=False),
        account=account,
    )
    if not collection_risk_list:
        return

    collection_risk = collection_risk_list.last()
    updates = dict()
    connected_exclude_keys = ['AnsweringMachine', 'BusyTone', 'DeadCall']
    connected_filtered_values = [
        value
        for key, value in AiRudder.SKIPTRACE_RESULT_CHOICE_MAP.items()
        if key not in connected_exclude_keys
    ]

    if (
        not collection_risk.is_verified
        and coll_risk_skiptrace_history_status
        == AiRudder.SKIPTRACE_RESULT_CHOICE_MAP.get('RPC-Regular')
    ):
        updates['is_verified'] = True
    if (
        not collection_risk.is_connected
        and coll_risk_skiptrace_history_agent
        and coll_risk_skiptrace_history_status
        and not (coll_risk_skiptrace_history_status not in connected_filtered_values)
    ):
        updates['is_connected'] = True
    if updates:
        collection_risk.update_safely(**updates)


def get_exclude_account_ids_collection_field(
    account_ids: List = None, bucket_name: str = ''
) -> List:
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=MinisquadFeatureSettings.BUCKET_FIELD_COLLECTION_EXCLUDED, is_active=True
    )

    excluded_account_ids = []
    if feature_setting:
        logger.info(
            {
                'function': 'get_exclude_account_ids_collection_field',
                'message': 'starting get account ids for excluded',
                'bucket': bucket_name,
            }
        )
        buckets = feature_setting.parameters.get('buckets', [])
        if bucket_name in buckets:
            excluded_account_ids = get_exclude_account_ids_from_fc_service(account_ids, bucket_name)

        logger.info(
            {
                'function': 'get_exclude_account_ids_collection_field',
                'message': 'Successfully get account ids for excluded',
                'bucket': bucket_name,
                'excluded_account_ids': excluded_account_ids,
            }
        )
    return excluded_account_ids


def get_exclude_account_ids_from_fc_service(
    account_ids: List = None, bucket_name: str = ''
) -> List:
    from juloserver.minisquad.tasks import sent_webhook_to_field_collection_service_by_category

    fn = 'get_exclude_account_ids_from_fc_service'
    bucket_mapping = {
        DialerSystemConst.DIALER_BUCKET_1: 'B1',
        DialerSystemConst.DIALER_JTURBO_B1: 'B1',
        DialerSystemConst.DIALER_BUCKET_2: 'B2',
        DialerSystemConst.DIALER_JTURBO_B2: 'B2',
        DialerSystemConst.DIALER_BUCKET_3: 'B3',
        DialerSystemConst.DIALER_JTURBO_B3: 'B3',
        DialerSystemConst.DIALER_BUCKET_4: 'B4',
        DialerSystemConst.DIALER_JTURBO_B4: 'B4',
        DialerSystemConst.DIALER_BUCKET_5: 'B5',
    }
    bucket_name = bucket_mapping.get(bucket_name, '')
    if not bucket_name:
        return []

    fc_exclude_pds_per_page = 1000
    fc_exclude_pds_page = 1
    fc_exclude_pds_error_count = 0
    excluded_account_ids = []
    while True:
        try:
            response = sent_webhook_to_field_collection_service_by_category(
                category='exclude-pds',
                external_account_ids=account_ids,
                bucket=bucket_name,
                per_page=fc_exclude_pds_per_page,
                page=fc_exclude_pds_page,
            )
        except Exception as e:
            msg = 'Exception {} occurred: {}'.format(bucket_name, str(e))
            logger.error(
                {
                    'function': fn,
                    'error': msg,
                    'bucket': bucket_name,
                }
            )
            fc_exclude_pds_error_count += 1
            if fc_exclude_pds_error_count > 3:
                logger.error(
                    {
                        'function': fn,
                        'error': 'Failed after 3 retries due to exceptions',
                        'bucket': bucket_name,
                    }
                )
                notify_fail_exclude_account_ids_collection_field_ai_rudder(msg)
                return []
            continue

        if response is None:
            msg = '{} Response is None'.format(bucket_name)
            logger.error(
                {
                    'function': fn,
                    'error': msg,
                    'bucket': bucket_name,
                }
            )
            fc_exclude_pds_error_count += 1
            if fc_exclude_pds_error_count > 3:
                notify_fail_exclude_account_ids_collection_field_ai_rudder(msg)
                return []
            continue

        if response.status_code == 404:
            logger.info(
                {
                    'function': fn,
                    'message': 'No accounts to exclude',
                    'bucket': bucket_name,
                }
            )
            break
        elif response.status_code != 200:
            msg = '{} Received status code {}'.format(bucket_name, response.status_code)
            logger.warning(
                {
                    'function': fn,
                    'error': msg,
                    'bucket': bucket_name,
                }
            )
            fc_exclude_pds_error_count += 1
            if fc_exclude_pds_error_count > 3:
                logger.error(
                    {
                        'function': fn,
                        'error': 'Failed after 3 retries due to non-200 status codes',
                        'bucket': bucket_name,
                    }
                )
                notify_fail_exclude_account_ids_collection_field_ai_rudder(msg)
                return []
            continue
        else:
            try:
                data = response.json().get('data', [])
                excluded_account_ids += [item['external_account_id'] for item in data]
                if len(data) < fc_exclude_pds_per_page:
                    break
                fc_exclude_pds_page += 1
                fc_exclude_pds_error_count = 0  # Reset error count
            except Exception as e:
                msg = '{} Failed to parse response data: {}'.format(bucket_name, str(e))
                logger.error(
                    {
                        'function': fn,
                        'error': msg,
                        'bucket': bucket_name,
                    }
                )
                fc_exclude_pds_error_count += 1
                if fc_exclude_pds_error_count > 3:
                    notify_fail_exclude_account_ids_collection_field_ai_rudder(msg)
                    return []
                continue

    return excluded_account_ids


def get_exclude_account_ids_collection_field_by_account_ids(
    account_ids: List = None, bucket_name: str = ''
) -> List:
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=MinisquadFeatureSettings.BUCKET_FIELD_COLLECTION_EXCLUDED, is_active=True
    )

    excluded_account_ids = []
    if feature_setting:
        buckets = feature_setting.parameters.get('buckets', [])
        if bucket_name in buckets:
            if bucket_name == DialerSystemConst.DIALER_BUCKET_2:
                excluded_account_ids = list(
                    B2ExcludeFieldCollection.objects.filter(account_id__in=account_ids).values_list(
                        'account_id', flat=True
                    )
                )
            elif bucket_name == DialerSystemConst.DIALER_BUCKET_3:
                excluded_account_ids = list(
                    B3ExcludeFieldCollection.objects.filter(account_id__in=account_ids).values_list(
                        'account_id', flat=True
                    )
                )

    return excluded_account_ids


def get_bucket_number_base_on_dpd(dpd):
    bucket_1 = list(range(BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to'] + 1))
    bucket_2 = list(range(BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to'] + 1))
    bucket_3 = list(range(BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to'] + 1))
    bucket_4 = list(range(BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to'] + 1))
    bucket_5 = list(range(BucketConst.BUCKET_5_DPD, BucketConst.BUCKET_5_END_DPD + 1))
    bucket_6_1 = list(
        range(BucketConst.BUCKET_6_1_DPD['from'], BucketConst.BUCKET_6_1_DPD['to'] + 1)
    )
    bucket_6_2 = list(
        range(BucketConst.BUCKET_6_2_DPD['from'], BucketConst.BUCKET_6_2_DPD['to'] + 1)
    )
    if dpd in bucket_1:
        return "1"
    if dpd in bucket_2:
        return "2"
    if dpd in bucket_3:
        return "3"
    if dpd in bucket_4:
        return "4"
    if dpd in bucket_5:
        return "5"
    if dpd in bucket_6_1:
        return "6.1"
    if dpd in bucket_6_2:
        return "6.2"
    return 0


def get_call_summary_mjolnir_data(application, last_skiptrace_history_id=None, sort_order='desc'):
    account = application.account
    using = DEFAULT_DB
    last_id_condition = '<'
    if sort_order == 'asc':
        last_id_condition = '>'
    # Define the SQL query for skiptrace_history and related tables
    skiptrace_query = """
            SELECT
                sh.skiptrace_history_id, sh.cdate, sh.skiptrace_result_choice_id, sh.non_payment_reason,
                s.skiptrace_id, s.contact_source, sh.spoke_with,
                sh.external_unique_identifier, ap.due_date, v.unique_call_id, rr.recording_report_id
            FROM
                skiptrace_history sh
            INNER JOIN
                skiptrace s ON s.skiptrace_id = sh.skiptrace_id
            INNER JOIN
                account_payment ap ON ap.account_payment_id = sh.account_payment_id
            INNER JOIN
                vendor_recording_detail v ON v.unique_call_id = sh.external_unique_identifier
            INNER JOIN
                airudder_recording_upload as aru on aru.vendor_recording_detail_id = v.vendor_recording_detail_id
            INNER JOIN
                recording_report as rr on rr.airruder_recording_upload_id = aru.airruder_recording_upload_id
            WHERE
                sh.account_id = %s AND sh.external_unique_identifier IS NOT NULL 
                AND rr.recording_report_id is not null
            {}
            ORDER BY
                sh.skiptrace_history_id {}
            LIMIT 10
    """.format(
        'AND sh.skiptrace_history_id {} %s'.format(last_id_condition)
        if last_skiptrace_history_id and last_skiptrace_history_id != "null"
        else '',
        'ASC' if sort_order == 'asc' else 'DESC',
    )

    # Execute the query on the default database
    with connections[using].cursor() as cursor:
        cursor.execute(
            skiptrace_query,
            [account.id, last_skiptrace_history_id] if last_skiptrace_history_id else [account.id],
        )
        skiptrace_history_batch = cursor.fetchall()

    # Extract external IDs for the secondary query
    external_ids = [row[10] for row in skiptrace_history_batch]
    skiptraces = Skiptrace.objects.filter(pk__in=[row[4] for row in skiptrace_history_batch])
    skiptraces_dict = {skiptrace.id: skiptrace for skiptrace in skiptraces.iterator()}
    detokenized_skiptraces = collection_detokenize_sync_kv_in_bulk(
        PiiSource.SKIPTRACE,
        skiptraces,
        ['phone_number'],
    )
    # Define the SQL query for MLMjolnirResult in the secondary database
    secondary_db = 'julo_analytics_db'  # Update with your actual secondary DB alias
    ml_query = """
        SELECT
            ml.recording_report_id,
            ml.call_summary_personal,
            ml.call_summary_company,
            ml.call_summary_kin
        FROM
            ana.ml_mjolnir_result ml
        WHERE
            ml.recording_report_id IN %s
    """

    # Execute the query on the secondary database
    with connections[secondary_db].cursor() as cursor:
        cursor.execute(ml_query, [tuple(external_ids) if tuple(external_ids) else (0,)])
        ml_results = cursor.fetchall()

    # Combine results in Python
    ml_result_dict = {
        row[0]: {
            'call_summary_personal': row[1],
            'call_summary_company': row[2],
            'call_summary_kin': row[3],
        }
        for row in ml_results
    }

    data = []
    for row in skiptrace_history_batch:
        skiptrace = skiptraces_dict.get(row[4])
        phone_number = str(
            detokenized_skiptraces.get(row[4]).phone_number
            if detokenized_skiptraces.get(row[4])
            else skiptrace.phone_number
        )
        cdate_obj = row[1]
        item = {
            "skiptrace_history_id": row[0],
            "cdate": format_datetime(cdate_obj, "dd MMM yyyy", locale='id_ID') if cdate_obj else "",
            "phone_number": phone_number,
            "contact_source": row[5],
            "spoke_with": row[6],
            "skiptrace_history_non_payment_reason": row[3],
            "call_summary": {},
        }

        contact_source = row[5]
        if contact_source not in AiRudder.MJOLNIR_CONTACT_SOURCE:
            data.append(item)
            continue

        # Get MLMjolnirResult data
        ml_result = ml_result_dict.get(row[10])
        if ml_result:
            mjolnir_call_summary = ""
            if contact_source in AiRudder.PERSONAL_CONTACT_SOURCE:
                mjolnir_call_summary = ml_result['call_summary_personal']
            elif contact_source in AiRudder.COMPANY_CONTACT_SOURCE:
                mjolnir_call_summary = ml_result['call_summary_company']
            elif contact_source in AiRudder.KIN_CONTACT_SOURCE:
                mjolnir_call_summary = ml_result['call_summary_kin']

            mjolnir_call_data = parse_string_to_dict(mjolnir_call_summary)
            dpd = int((row[1].date() - row[8]).days)
            mjolnir_call_data["bucket"] = get_bucket_number_base_on_dpd(dpd)
            item["call_summary"] = mjolnir_call_data

        data.append(item)

    new_last_id = skiptrace_history_batch[-1][0] if skiptrace_history_batch else None

    return data, new_last_id


def get_other_numbers_to_pds(
    account: Account, phone_numbers: List, limit_other_numbers: int, ineffective_phone_numbers: List
):
    other_numbers = []
    today = timezone.localtime(timezone.now())
    today_minus_30 = today - relativedelta(days=30)
    today_minus_30_min = datetime.combine(today_minus_30, time.min)
    skiptrace_ids_without_kin = list(
        Skiptrace.objects.filter(customer_id=account.customer_id)
        .exclude(phone_number__in=phone_numbers)
        .exclude(contact_source__regex=r'(?i)(^|[^a-zA-Z0-9])kin([^a-zA-Z0-9]|$)')
        .exclude(contact_source__regex=r'(?i)(^|[^a-zA-Z0-9])ckin([^a-zA-Z0-9]|$)')
        .values_list('pk', flat=True)
    )
    if not skiptrace_ids_without_kin:
        return other_numbers

    skiptrace_ids_30_days = list(
        SkiptraceHistory.objects.filter(
            cdate__range=(today_minus_30_min, today),
            call_result__name__in=AiRudder.EVER_RPC_STATUSES,
            skiptrace_id__in=skiptrace_ids_without_kin,
        )
        .values_list('skiptrace_id', flat=True)
    )
    if not skiptrace_ids_30_days:
        return other_numbers

    skiptrace_ids_30_days = list(set(skiptrace_ids_30_days))
    skiptraces = Skiptrace.objects.filter(pk__in=skiptrace_ids_30_days[:limit_other_numbers])
    skiptrace_list_detokenize = collection_detokenize_sync_kv_in_bulk(
        PiiSource.SKIPTRACE,
        skiptraces,
        ['phone_number'],
    )
    for skiptrace in skiptraces:
        detokenized_skiptrace = skiptrace_list_detokenize.get(skiptrace.id)
        phone_number = getattr(detokenized_skiptrace, 'phone_number', skiptrace.phone_number)
        str_phone_number = str(phone_number)
        if str_phone_number not in ineffective_phone_numbers:
            other_numbers.append(str(phone_number))

    return other_numbers

def get_fdc_details_for_customer(customer, last_fdc_id):
    fdc_details = []
    from juloserver.fdc.constants import FDCLoanStatus
    base_filter = {'fdc_inquiry__customer_id': customer.id}
    if last_fdc_id:
        base_filter.update({'id__lt': last_fdc_id})
    fdc_inquiry_loan_list = (FDCInquiryLoan.objects.select_related('fdc_inquiry').
                             filter(**base_filter)).exclude(
        status_pinjaman=FDCLoanStatus.FULLY_PAID).order_by('-id')[:10]
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FDC_LENDER_MAP, is_active=True)
    parameters = {}
    penyelenggara = None
    if feature_setting:
        parameters = feature_setting.parameters

    for fdc_inquiry_loan in fdc_inquiry_loan_list:
        if parameters:
            penyelenggara = parameters[fdc_inquiry_loan.id_penyelenggara] \
                if fdc_inquiry_loan.id_penyelenggara in parameters \
                else '-'
        fdc_details.append({
            'id_penyelenggara': fdc_inquiry_loan.id_penyelenggara
            if fdc_inquiry_loan.id_penyelenggara !='' else '-',
            'sisa_pinjaman_berjalan': fdc_inquiry_loan.sisa_pinjaman_berjalan,
            'tgl_jatuh_tempo_pinjaman': format_datetime(fdc_inquiry_loan.tgl_jatuh_tempo_pinjaman,
                                                        "MMM dd, yyyy", locale='en')
            if fdc_inquiry_loan.tgl_jatuh_tempo_pinjaman else '-',
            'cdate': format_datetime(fdc_inquiry_loan.cdate, "MMM dd, yyyy, hh:mm a", locale='en'),
            'penyelenggara': penyelenggara if penyelenggara else "-",
            'id':fdc_inquiry_loan.id
        })
    length = len(fdc_inquiry_loan_list)
    new_last_fdc_id = fdc_inquiry_loan_list[length - 1].id if length > 0  else None

    return fdc_details, new_last_fdc_id


def get_similar_field_collection_agents(fullname):
    field_collection_client = get_julo_field_collection_client()
    data = field_collection_client.get_similar_active_agents(fullname)

    return data.get('agents', [])
