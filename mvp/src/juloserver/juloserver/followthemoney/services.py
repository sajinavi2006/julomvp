from builtins import str
from decimal import ROUND_HALF_UP, Decimal
import logging
import re
import io
import pandas as pd
import numpy as np
from typing import List, Union
from django.db.models import F, Sum, Q, QuerySet, ExpressionWrapper, fields

from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.db import transaction
from babel.dates import format_date
from bulk_update.helper import bulk_update
from datetime import date, timedelta, datetime
from juloserver.julo.utils import display_rupiah
from juloserver.julo.services2 import get_redis_client

from juloserver.julo.models import (
    Application,
    FeatureSetting,
    Payment,
    RepaymentTransaction,
    StatusLookup,
    Loan,
    PaymentEvent,
    ApplicationHistory,
    FeatureSetting,
    Bank,
    Partner,
    Document,
    ProductLookup,
    PaybackTransaction,
)

from juloserver.followthemoney.models import (
    ApplicationLenderHistory,
    LenderCurrent,
    LenderBalanceCurrent,
    LenderSignature,
    LenderTransactionMapping,
    LenderTransactionType,
    LenderTransaction,
    LoanAgreementTemplate,
    LenderBankAccount,
    LoanWriteOff,
    LenderRepaymentTransaction,
    LenderDisbursementMethod,
    LenderApproval,
    LenderReversalTransaction,
    LenderReversalTransactionHistory,
    LenderManualRepaymentTracking,
    LoanLenderHistory,
    LenderBucket,
    SbDailyOspProductLender,
    LenderRepaymentDetail,
)
from juloserver.followthemoney.constants import (
    LenderName,
    LenderTransactionTypeConst,
    SnapshotType,
    BankAccountType,
    LoanWriteOffPeriodConst,
    LenderRepaymentTransactionStatus,
    LoanAgreementType,
    LateFeeDefault,
    LenderRepaymentTransferType,
    LenderReversalTransactionConst,
    ReassignLenderProductLine,
    LenderNameByPartner,
    LenderInterestTax,
    RedisLockWithExTimeType,
    LOCK_ON_REDIS_WITH_EX_TIME,
    REDIS_LOCK_IN_TIME,
)

from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    PaymentStatusCodes,
    LoanStatusCodes
)
from juloserver.julo.constants import (
    FeatureNameConst,
    ApplicationStatusCodes,
    ExperimentConst,
    FalseRejectMiniConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.exceptions import JuloException, DuplicateProcessing, RedisNameNotExists
from juloserver.disbursement.constants import DisbursementVendors
from django.conf import settings
from django.template import Context
from django.template import Template
from juloserver.followthemoney.utils import masked_transfer_amount
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.services2 import get_redis_client
from juloserver.julocore.python2.utils import py2round
from juloserver.disbursement.services.xfers import (
    JTPXfersService,
    JTFXfersService,
)
from juloserver.customer_module.services.digital_signature import (
    Signature,
    DigitalSignature,
    CertificateAuthority
)
from juloserver.dana.constants import DANA_SERVICE_FEE_RATE_P3
from juloserver.minisquad.services2.google_drive import get_finance_google_drive_api_client
from juloserver.account.models import AccountTransaction


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class PusdafilLenderException(Exception):
    def __init__(self, msg):
        self.msg = msg


class LoanAgreementBorrowerSignature(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk meminjam"

    @property
    def box(self) -> tuple:
        v_start = 20
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 9


class LoanAgreementBorrowerSignatureAxiataWeb(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk meminjam"

    @property
    def box(self) -> tuple:
        v_start = 20
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 6


class LoanAgreementBorrowerSignatureBSS(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk meminjam"

    @property
    def box(self) -> tuple:
        v_start = 20
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 9


class LoanAgreementBorrowerSignatureGosel(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk meminjam"

    @property
    def box(self) -> tuple:
        v_start = 20
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 6


class LoanAgreementLenderSignature(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk memberi pinjaman"

    @property
    def box(self) -> tuple:
        v_start = 410
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 9


class LoanAgreementLenderSignatureAxiataWeb(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk memberi pinjaman"

    @property
    def box(self) -> tuple:
        v_start = 410
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 6


class LoanAgreementLenderSignatureBSS(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk memberi pinjaman"

    @property
    def box(self) -> tuple:
        v_start = 380
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 9


class LoanAgreementLenderSignatureGosel(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk memberi pinjaman"

    @property
    def box(self) -> tuple:
        v_start = 410
        h_start = 590
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 6


class GrabLoanAgreementBorrowerSignature(LoanAgreementBorrowerSignature):
    @property
    def box(self) -> tuple:
        v_start = 50
        h_start = 340
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 12


class LenderAgreementLenderSignature(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk memberi pinjaman"

    @property
    def box(self) -> tuple:
        v_start = 50
        h_start = 360
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 7


class GrabLenderAgreementLenderSignature(LenderAgreementLenderSignature):
    @property
    def box(self) -> tuple:
        v_start = 400
        h_start = 340
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 12


class LenderAgreementProviderSignature(Signature):
    @property
    def reason(self) -> str:
        return "Setuju untuk menjadi fasilitator"

    @property
    def box(self) -> tuple:
        v_start = 280
        h_start = 360
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 7


class JuloverLoanAgreementBorrowerSignature(LoanAgreementBorrowerSignature):
    @property
    def box(self) -> tuple:
        v_start = 20
        h_start = 600
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 2


class JuloverLoanAgreementLenderSignature(LoanAgreementLenderSignature):
    @property
    def box(self) -> tuple:
        v_start = 410
        h_start = 600
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 2


class RedisCacheLoanBucketXidPast:
    PREFIX_KEY = 'loan_bucket_xid'

    @property
    def cache(self):
        return get_redis_client()

    def get(self, loan_id):
        key = self._cache_key(loan_id)
        return self.cache.get(key)

    def set(self, loan_id, data, timeout=timedelta(days=3)):
        key = self._cache_key(loan_id)
        return self.cache.set(key, data, timeout)

    def _cache_key(self, key):
        return '{}::{}'.format(RedisCacheLoanBucketXidPast.PREFIX_KEY, key)

    def set_keys(self, loan_ids, lender_bucket_xid):
        for loan_id in loan_ids:
            self.set(loan_id, lender_bucket_xid)

    def get_by_loan_ids(self, loan_ids):
        return {loan_id: self.get(loan_id) for loan_id in loan_ids if self.get(loan_id)}


def reassign_lender(application_id):
    from juloserver.julo.services import assign_lender_to_disburse, process_application_status_change
    from juloserver.followthemoney.tasks import auto_expired_application_tasks

    try:
        application = Application.objects.get_or_none(pk=application_id)
        get_application_count = ApplicationLenderHistory.objects.filter(
            application=application).count()

        ftm_configuration = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.FTM_CONFIGURATION,
            category="followthemoney",is_active=True)

        if get_application_count < ftm_configuration.parameters['reassign_count']:
            loan = application.loan
            lender = assign_lender_to_disburse(application, loan.lender.id)
            # this only for handle FTM
            partner = lender.user.partner
            loan.partner = partner
            loan.lender = lender
            loan.save()

            ApplicationLenderHistory.objects.create(
                lender=lender, application=application)

            lender_approval = LenderApproval.objects.get_or_none(partner=partner)

            if not lender_approval:
                logger.info({'task': 'reassign_lender',
                            'application_id': application.id,
                            'status': 'lender_approval not found'})
                return

            gaps = timedelta(hours=lender_approval.expired_in.hour,
                minutes=lender_approval.expired_in.minute,
                seconds=lender_approval.expired_in.second)

            auto_expired_application_tasks.apply_async((application.id, lender.id,),
                eta=timezone.localtime(timezone.now()) + gaps)

        else:
            process_application_status_change(application.id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                "trigger_by_folllowthemoney", "followthemoney")

    except Exception as e:
        sentry_client.captureException()
        logger.error({
            'action_view': 'FollowTheMoney - ReAssignLender',
            'data': application_id,
            'errors': str(e)
        })

def get_aggregate(qs, field):
    subtotal = qs.aggregate(
        Sum( '%s' % (field) ))
    if not subtotal['%s__sum' % (field)]:
        return 0

    return subtotal['%s__sum' % (field)]

def get_summary_value(loan_id, field):
    qs = Payment.objects.filter(loan=loan_id)
    return get_aggregate(qs, field)

def get_repayment(loan_id):
    qs = RepaymentTransaction.objects.filter(loan=loan_id)
    return get_aggregate(qs, 'lender_received')

def calculate_net_profit(loan_status, principal, interest, fee):
    if loan_status == StatusLookup.PAID_OFF_CODE:
        return principal + interest - fee

    return 0


def get_outstanding_loans_by_lender(lender_id=None, last_fund_transfer_ts=None, limit=None,
                                    include_paid_off=False,
                                    today=timezone.localtime(timezone.now()).date()):
    write_off_90_loans = LoanWriteOff.objects.filter(wo_period=LoanWriteOffPeriodConst.WO_90)\
                                             .values('loan_id',
                                                     'paid_interest',
                                                     'paid_principal',
                                                     'total_paid',
                                                     'due_amount',
                                                     'loan_amount',
                                                     'paid_latefee')

    write_off_90_dict = {}

    for write_off in write_off_90_loans:
        write_off_90_dict[write_off['loan_id']] = {
            'paid_interest': write_off['paid_interest'],
            'paid_principal': write_off['paid_principal'],
            'total_paid': write_off['total_paid'],
            'due_amount': write_off['paid_latefee'],
            'loan_amount': write_off['loan_amount'],
            'paid_latefee': write_off['paid_latefee'],
        }

    loans = Loan.objects.select_related('application')

    if lender_id:
        lenderCount = LenderCurrent.objects.filter(pk=lender_id).count()
        if lenderCount == 0:
            return None

        loans = loans.filter(lender_id=lender_id)

    if include_paid_off:
        loans = loans.filter(Q(loan_status_id__gte=LoanStatusCodes.CURRENT,
                             loan_status_id__lte=LoanStatusCodes.LOAN_180DPD) |
                             Q(loan_status_id=LoanStatusCodes.PAID_OFF))
    else:
        loans = loans.filter(loan_status_id__gte=LoanStatusCodes.CURRENT,
                             loan_status_id__lte=LoanStatusCodes.LOAN_180DPD)

    if not lender_id:
        loans = loans.filter(lender_id__isnull=False)

    if limit:
        max_data = limit if limit else 25
        filter_ = {}

        order_by = '-fund_transfer_ts'

        if last_fund_transfer_ts:
            filter_['fund_transfer_ts__lt'] = last_fund_transfer_ts

        loans = loans.filter(**filter_).order_by(order_by)[:max_data]

    loans = loans.values('id', 'lender_id', 'fund_transfer_ts',
                         'loan_status_id',
                         'loan_duration', 'application__application_xid',
                         'loan_amount', 'application__loan_purpose')

    loan_dict = {}

    for loan in loans:
        loan_dict[loan['id']] = {
            'lender_id': loan['lender_id'],
            'fund_transfer_ts': loan['fund_transfer_ts'],
            'loan_amount': loan['loan_amount'],
            'loan_status_code': loan['loan_status_id'],
            'lla_xid': loan['application__application_xid'],
            'loan_duration': loan['loan_duration'],
            'loan_purpose': loan['application__loan_purpose'],
            'paid_principal': 0,
            'paid_interest': 0,
            'paid_latefee': 0,
            'total_paid': 0,
            'due_amount': 0,
            'outstanding_principal_amount': 0,
            'outstanding_interest_amount': 0,
            'wo_date_90': None,
            'wo_date_180': None
        }

    payments = Payment.objects.filter(payment_status_id__gte=PaymentStatusCodes.PAYMENT_NOT_DUE,
                                      payment_status_id__lte=PaymentStatusCodes.PAID_LATE,
                                      loan_id__in=list(loan_dict.keys()))\
                                      .order_by('id').values('paid_principal', 'due_date',
                                                             'loan_id', 'paid_date',
                                                             'paid_interest', 'installment_principal',
                                                             'paid_amount', 'due_amount',
                                                             'paid_late_fee',
                                                             'installment_interest')

    ninety_day_delta = timedelta(days=91)
    one_eighty_day_delta = timedelta(days=181)

    for payment in payments:
        loan_id = payment['loan_id']
        loan = loan_dict[loan_id]

        due_date = payment['due_date']
        paid_date = payment['paid_date']
        paid_principal = payment['paid_principal']
        paid_interest = payment['paid_interest']
        installment_principal = payment['installment_principal']
        due_amount = payment['due_amount']
        paid_amount = payment['paid_amount']
        paid_late_fee = payment['paid_late_fee']

        dpd90 = due_date + ninety_day_delta
        dpd180 = due_date + one_eighty_day_delta

        is_write_off_90 = False

        if today >= due_date:
            if 'paid_yield_amount' not in loan_dict[loan_id]:
                loan_dict[loan_id]['paid_yield_amount'] = 0
                loan_dict[loan_id]['loan_principal_amount'] = 0
                loan_dict[loan_id]['running_terms_date'] = None

            running_terms_date = loan_dict[loan_id]['running_terms_date']
            paid_terms_to_today = None

            if loan_id in write_off_90_dict:
                is_write_off_90 = True

            if is_write_off_90:
                loan['paid_yield_amount'] += \
                    write_off_90_dict[loan_id]['paid_interest'] + write_off_90_dict[loan_id]['paid_principal']
                loan['loan_principal_amount'] += \
                    write_off_90_dict[loan_id]['loan_amount']

            due_terms_to_today = (today - due_date).days

            if paid_date is not None:
                paid_terms_to_today = (today - paid_date).days

            if running_terms_date is None:
                if paid_terms_to_today is not None and paid_terms_to_today < due_terms_to_today:
                    running_terms_date = paid_date
                else:
                    running_terms_date = due_date

                loan['running_terms_date'] = running_terms_date
            else:
                if paid_terms_to_today is not None and paid_terms_to_today < due_terms_to_today \
                        and (today - running_terms_date).days > paid_terms_to_today:
                    running_terms_date = paid_date
                elif paid_terms_to_today is not None and paid_terms_to_today > due_terms_to_today \
                        and (today - running_terms_date).days > due_terms_to_today:
                    running_terms_date = due_date
                elif due_terms_to_today < (today - running_terms_date).days:
                    running_terms_date = due_date

                loan['running_terms_date'] = running_terms_date

            loan['paid_yield_amount'] += \
                payment['paid_principal'] + payment['paid_interest']

            loan['loan_principal_amount'] += installment_principal

        if today == dpd180 and is_write_off_90:
            loan['wo_date_180'] = today

        if is_write_off_90:
            paid_principal = write_off_90_dict[loan_id]['paid_principal']
            paid_interest = write_off_90_dict[loan_id]['paid_interest']
            total_paid = write_off_90_dict[loan_id]['total_paid']
            total_due_amount = write_off_90_dict[loan_id]['due_amount']
            total_late_fee = write_off_90_dict[loan_id]['paid_latefee']
        else:
            paid_principal = payment['paid_principal']
            paid_interest = payment['paid_interest']

        if (today == dpd90 and due_amount > 0) or \
                loan['wo_date_90'] is not None:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['wo_date_90'] = today
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee
        elif today == dpd90 and is_write_off_90:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['paid_principal'] = paid_principal
            loan['paid_interest'] = paid_interest
            loan['total_paid'] = total_paid
            loan['due_amount'] = total_due_amount
            loan['paid_latefee'] = total_late_fee
        elif today == dpd180 and loan['wo_date_180'] is not None:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['wo_date_180'] = today
            paid_principal = payment['paid_principal']
            paid_interest = payment['paid_interest']
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee
        else:
            loan['outstanding_principal_amount'] += installment_principal - \
                paid_principal
            loan['outstanding_interest_amount'] += payment['installment_interest'] - \
                paid_interest
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee

    return loan_dict


def get_loan_details(lender_id=None, last_loan_id=None, limit=25, today=timezone.localtime(timezone.now()).date()):
    write_off_90_loans = LoanWriteOff.objects.filter(wo_period=LoanWriteOffPeriodConst.WO_90)\
                                             .values('loan_id',
                                                     'paid_interest',
                                                     'paid_principal',
                                                     'total_paid',
                                                     'due_amount',
                                                     'loan_amount',
                                                     'paid_latefee')

    write_off_90_dict = {}

    for write_off in write_off_90_loans:
        write_off_90_dict[write_off['loan_id']] = {
            'paid_interest': write_off['paid_interest'],
            'paid_principal': write_off['paid_principal'],
            'total_paid': write_off['total_paid'],
            'due_amount': write_off['paid_latefee'],
            'loan_amount': write_off['loan_amount'],
            'paid_latefee': write_off['paid_latefee'],
        }

    loans = Loan.objects.select_related('application')

    if lender_id:
        lenderCount = LenderCurrent.objects.filter(pk=lender_id).count()
        if lenderCount == 0:
            return None

        loans = loans.filter(lender_id=lender_id)

    loans = loans.filter(Q(loan_status_id__gte=LoanStatusCodes.CURRENT,
                           loan_status_id__lte=LoanStatusCodes.LOAN_180DPD) |
                         Q(loan_status_id=LoanStatusCodes.PAID_OFF))

    if not lender_id:
        loans = loans.filter(lender_id__isnull=False)

    max_data = limit if limit else 25

    filter_ = {}

    if last_loan_id:
        last_loan = Loan.objects.get(pk=last_loan_id)
        last_fund_transfer_ts = last_loan.fund_transfer_ts
        filter_['fund_transfer_ts__lte'] = last_fund_transfer_ts
        loans = loans.filter(**filter_).exclude(fund_transfer_ts=None).exclude(id=last_loan_id).order_by('-fund_transfer_ts')[:max_data]
    else:
        loans = loans.exclude(fund_transfer_ts=None).order_by('-fund_transfer_ts')[:max_data]

    loans = loans.values('id', 'lender_id', 'fund_transfer_ts',
                         'loan_status_id', 'loan_xid', 'product__product_profile__code',
                         'loan_duration', 'account__application__application_xid',
                         'loan_amount', 'account__application__loan_purpose')

    loan_dict = {}

    for loan in loans:
        lla_xid = loan['account__application__application_xid']
        if int(
                loan['product__product_profile__code']
        ) in ProductLineCodes.julo_one() + ProductLineCodes.grab():
            lla_xid = loan['loan_xid']

        loan_dict[loan['id']] = {
            'lender_id': loan['lender_id'],
            'fund_transfer_ts': loan['fund_transfer_ts'],
            'loan_amount': loan['loan_amount'],
            'loan_status_code': loan['loan_status_id'],
            'lla_xid': lla_xid,
            'loan_duration': loan['loan_duration'],
            'loan_purpose': loan['account__application__loan_purpose'],
            'paid_principal': 0,
            'paid_interest': 0,
            'paid_latefee': 0,
            'total_paid': 0,
            'due_amount': 0,
            'outstanding_principal_amount': 0,
            'outstanding_interest_amount': 0,
            'wo_date_90': None,
            'wo_date_180': None
        }

    payments = Payment.objects.filter(payment_status_id__gte=PaymentStatusCodes.PAYMENT_NOT_DUE,
                                      payment_status_id__lte=PaymentStatusCodes.PAID_LATE,
                                      loan_id__in=list(loan_dict.keys()))\
                                      .order_by('id').values('paid_principal', 'due_date',
                                                             'loan_id', 'paid_date',
                                                             'paid_interest', 'installment_principal',
                                                             'paid_amount', 'due_amount',
                                                             'paid_late_fee',
                                                             'installment_interest')

    ninety_day_delta = timedelta(days=91)
    one_eighty_day_delta = timedelta(days=181)

    for payment in payments:
        loan_id = payment['loan_id']
        loan = loan_dict[loan_id]

        due_date = payment['due_date']
        paid_date = payment['paid_date']
        paid_principal = payment['paid_principal']
        paid_interest = payment['paid_interest']
        installment_principal = payment['installment_principal']
        due_amount = payment['due_amount']
        paid_amount = payment['paid_amount']
        paid_late_fee = payment['paid_late_fee']

        dpd90 = due_date + ninety_day_delta
        dpd180 = due_date + one_eighty_day_delta

        is_write_off_90 = False

        if today >= due_date:
            if 'paid_yield_amount' not in loan_dict[loan_id]:
                loan_dict[loan_id]['paid_yield_amount'] = 0
                loan_dict[loan_id]['loan_principal_amount'] = 0
                loan_dict[loan_id]['running_terms_date'] = None

            running_terms_date = loan_dict[loan_id]['running_terms_date']
            paid_terms_to_today = None

            if loan_id in write_off_90_dict:
                is_write_off_90 = True

            if is_write_off_90:
                loan['paid_yield_amount'] += \
                    write_off_90_dict[loan_id]['paid_interest'] + write_off_90_dict[loan_id]['paid_principal']
                loan['loan_principal_amount'] += \
                    write_off_90_dict[loan_id]['loan_amount']

            due_terms_to_today = (today - due_date).days

            if paid_date is not None:
                paid_terms_to_today = (today - paid_date).days

            if running_terms_date is None:
                if paid_terms_to_today is not None and paid_terms_to_today < due_terms_to_today:
                    running_terms_date = paid_date
                else:
                    running_terms_date = due_date

                loan['running_terms_date'] = running_terms_date
            else:
                if paid_terms_to_today is not None and paid_terms_to_today < due_terms_to_today \
                        and (today - running_terms_date).days > paid_terms_to_today:
                    running_terms_date = paid_date
                elif paid_terms_to_today is not None and paid_terms_to_today > due_terms_to_today \
                        and (today - running_terms_date).days > due_terms_to_today:
                    running_terms_date = due_date
                elif due_terms_to_today < (today - running_terms_date).days:
                    running_terms_date = due_date

                loan['running_terms_date'] = running_terms_date

            loan['paid_yield_amount'] += \
                payment['paid_principal'] + payment['paid_interest']

            loan['loan_principal_amount'] += installment_principal

        if today == dpd180 and is_write_off_90:
            loan['wo_date_180'] = today

        if is_write_off_90:
            paid_principal = write_off_90_dict[loan_id]['paid_principal']
            paid_interest = write_off_90_dict[loan_id]['paid_interest']
            total_paid = write_off_90_dict[loan_id]['total_paid']
            total_due_amount = write_off_90_dict[loan_id]['due_amount']
            total_late_fee = write_off_90_dict[loan_id]['paid_latefee']
        else:
            paid_principal = payment['paid_principal']
            paid_interest = payment['paid_interest']

        if (today == dpd90 and due_amount > 0) or \
                loan['wo_date_90'] is not None:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['wo_date_90'] = today
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee
        elif today == dpd90 and is_write_off_90:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['paid_principal'] = paid_principal
            loan['paid_interest'] = paid_interest
            loan['total_paid'] = total_paid
            loan['due_amount'] = total_due_amount
            loan['paid_latefee'] = total_late_fee
        elif today == dpd180 and loan['wo_date_180'] is not None:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['wo_date_180'] = today
            paid_principal = payment['paid_principal']
            paid_interest = payment['paid_interest']
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee
        else:
            loan['outstanding_principal_amount'] += installment_principal - \
                paid_principal
            loan['outstanding_interest_amount'] += payment['installment_interest'] - \
                paid_interest
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee

    return loan_dict


def get_loan_level_details(
        lender_id=None, last_loan_id=None, limit=25, loan_xid=None, product_line_code=None,
        today=timezone.localtime(timezone.now()).date(), partner_id=None
):
    # This function access loan level data
    write_off_90_loans = LoanWriteOff.objects.filter(wo_period=LoanWriteOffPeriodConst.WO_90)\
                                             .values('loan_id',
                                                     'paid_interest',
                                                     'paid_principal',
                                                     'total_paid',
                                                     'due_amount',
                                                     'loan_amount',
                                                     'paid_latefee')

    write_off_90_dict = {}

    for write_off in write_off_90_loans:
        write_off_90_dict[write_off['loan_id']] = {
            'paid_interest': write_off['paid_interest'],
            'paid_principal': write_off['paid_principal'],
            'total_paid': write_off['total_paid'],
            'due_amount': write_off['paid_latefee'],
            'loan_amount': write_off['loan_amount'],
            'paid_latefee': write_off['paid_latefee'],
        }

    loans = Loan.objects.filter(
        Q(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
        )
        | Q(loan_status_id=LoanStatusCodes.PAID_OFF)
    ).annotate(lender_bucket_xid=F('lendersignature__lender_bucket_xid'))

    if loan_xid:
        loans = loans.filter(loan_xid=loan_xid)

    if product_line_code:
        loans = loans.filter(product__product_line=product_line_code)

    if partner_id:
        loans = loans.filter(partnerloanrequest__partner_id=partner_id)

    lender_name = ""
    if lender_id:
        lender_queryset = LenderCurrent.objects.filter(pk=lender_id)
        lenderCount = lender_queryset.count()
        if lenderCount == 0:
            return None

        loans = loans.filter(lender_id=lender_id)
        lender_name = lender_queryset.last().lender_name

    if not lender_id:
        loans = loans.filter(lender_id__isnull=False)

    hidden_product_line_codes = get_list_product_line_code_need_to_hide()
    if hidden_product_line_codes:
        loans = loans.exclude(product__product_line__in=hidden_product_line_codes)

    max_data = limit if limit else 25

    filter_ = {}

    if last_loan_id:
        last_loan = Loan.objects.get(pk=last_loan_id)
        last_fund_transfer_ts = last_loan.fund_transfer_ts
        filter_['fund_transfer_ts__lte'] = last_fund_transfer_ts
        loans = loans.filter(**filter_).exclude(fund_transfer_ts=None).exclude(id=last_loan_id).order_by('-fund_transfer_ts')[:max_data]
    else:
        loans = loans.exclude(fund_transfer_ts=None).order_by('-fund_transfer_ts')[:max_data]

    loans = loans.values(
        'id',
        'lender_id',
        'fund_transfer_ts',
        'loan_status_id',
        'loan_duration',
        'loan_xid',
        'loan_amount',
        'loan_purpose',
        'lender_bucket_xid',
    )

    loan_dict = {}

    for loan in loans:
        loan_purpose = loan['loan_purpose']

        if lender_name and lender_name in LenderNameByPartner.GRAB:
            loan_obj = Loan.objects.get_or_none(id=loan['id'])
            if loan_obj.account and loan_obj.get_application:
                loan_purpose = loan_obj.get_application.loan_purpose

        loan_dict[loan['id']] = {
            'lender_id': loan['lender_id'],
            'lender_bucket_xid': loan['lender_bucket_xid'],
            'fund_transfer_ts': loan['fund_transfer_ts'],
            'loan_amount': loan['loan_amount'],
            'loan_status_code': loan['loan_status_id'],
            'lla_xid': loan['loan_xid'],
            'loan_duration': loan['loan_duration'],
            'loan_purpose': loan_purpose,
            'paid_principal': 0,
            'paid_interest': 0,
            'paid_latefee': 0,
            'total_paid': 0,
            'due_amount': 0,
            'outstanding_principal_amount': 0,
            'outstanding_interest_amount': 0,
            'wo_date_90': None,
            'wo_date_180': None
        }

    payments = Payment.objects.filter(payment_status_id__gte=PaymentStatusCodes.PAYMENT_NOT_DUE,
                                      payment_status_id__lte=PaymentStatusCodes.PAID_LATE,
                                      loan_id__in=list(loan_dict.keys()))\
                                      .order_by('id').values('paid_principal', 'due_date',
                                                             'loan_id', 'paid_date',
                                                             'paid_interest', 'installment_principal',
                                                             'paid_amount', 'due_amount',
                                                             'paid_late_fee',
                                                             'installment_interest')

    ninety_day_delta = timedelta(days=91)
    one_eighty_day_delta = timedelta(days=181)

    for payment in payments:
        loan_id = payment['loan_id']
        loan = loan_dict[loan_id]

        due_date = payment['due_date']
        paid_date = payment['paid_date']
        paid_principal = payment['paid_principal']
        paid_interest = payment['paid_interest']
        installment_principal = payment['installment_principal']
        due_amount = payment['due_amount']
        paid_amount = payment['paid_amount']
        paid_late_fee = payment['paid_late_fee']

        dpd90 = due_date + ninety_day_delta
        dpd180 = due_date + one_eighty_day_delta

        is_write_off_90 = False

        if today >= due_date:
            if 'paid_yield_amount' not in loan_dict[loan_id]:
                loan_dict[loan_id]['paid_yield_amount'] = 0
                loan_dict[loan_id]['loan_principal_amount'] = 0
                loan_dict[loan_id]['running_terms_date'] = None

            running_terms_date = loan_dict[loan_id]['running_terms_date']
            paid_terms_to_today = None

            if loan_id in write_off_90_dict:
                is_write_off_90 = True

            if is_write_off_90:
                loan['paid_yield_amount'] += \
                    write_off_90_dict[loan_id]['paid_interest'] + write_off_90_dict[loan_id]['paid_principal']
                loan['loan_principal_amount'] += \
                    write_off_90_dict[loan_id]['loan_amount']

            due_terms_to_today = (today - due_date).days

            if paid_date is not None:
                paid_terms_to_today = (today - paid_date).days

            if running_terms_date is None:
                if paid_terms_to_today is not None and paid_terms_to_today < due_terms_to_today:
                    running_terms_date = paid_date
                else:
                    running_terms_date = due_date

                loan['running_terms_date'] = running_terms_date
            else:
                if paid_terms_to_today is not None and paid_terms_to_today < due_terms_to_today \
                        and (today - running_terms_date).days > paid_terms_to_today:
                    running_terms_date = paid_date
                elif paid_terms_to_today is not None and paid_terms_to_today > due_terms_to_today \
                        and (today - running_terms_date).days > due_terms_to_today:
                    running_terms_date = due_date
                elif due_terms_to_today < (today - running_terms_date).days:
                    running_terms_date = due_date

                loan['running_terms_date'] = running_terms_date

            loan['paid_yield_amount'] += \
                payment['paid_principal'] + payment['paid_interest']

            loan['loan_principal_amount'] += installment_principal

        if today == dpd180 and is_write_off_90:
            loan['wo_date_180'] = today

        if is_write_off_90:
            paid_principal = write_off_90_dict[loan_id]['paid_principal']
            paid_interest = write_off_90_dict[loan_id]['paid_interest']
            total_paid = write_off_90_dict[loan_id]['total_paid']
            total_due_amount = write_off_90_dict[loan_id]['due_amount']
            total_late_fee = write_off_90_dict[loan_id]['paid_latefee']
        else:
            paid_principal = payment['paid_principal']
            paid_interest = payment['paid_interest']

        if (today == dpd90 and due_amount > 0) or \
                loan['wo_date_90'] is not None:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['wo_date_90'] = today
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee
        elif today == dpd90 and is_write_off_90:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['paid_principal'] = paid_principal
            loan['paid_interest'] = paid_interest
            loan['total_paid'] = total_paid
            loan['due_amount'] = total_due_amount
            loan['paid_latefee'] = total_late_fee
        elif today == dpd180 and loan['wo_date_180'] is not None:
            loan['outstanding_principal_amount'] = 0
            loan['outstanding_interest_amount'] = 0
            loan['wo_date_180'] = today
            paid_principal = payment['paid_principal']
            paid_interest = payment['paid_interest']
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee
        else:
            loan['outstanding_principal_amount'] += installment_principal - \
                paid_principal
            loan['outstanding_interest_amount'] += payment['installment_interest'] - \
                paid_interest
            loan['paid_principal'] += paid_principal
            loan['paid_interest'] += paid_interest
            loan['total_paid'] += paid_amount
            loan['due_amount'] += due_amount
            loan['paid_latefee'] += paid_late_fee

    return loan_dict


def get_available_balance(lender_id):
    from juloserver.disbursement.services.xfers import JTPXfersService
    service = JTPXfersService(lender_id)
    mock_balance = FeatureSetting.objects.get_or_none(feature_name='mock_available_balance',
                                                      is_active=True)

    current_balance = 0
    lender = LenderCurrent.objects.get(pk=lender_id)
    if lender.lender_name in LenderCurrent.manual_lender_list():
        current_balance = lender.lenderbalancecurrent.available_balance
    else:
        if mock_balance:
            current_balance = mock_balance.parameters['available_balance']
        else:
            current_balance = service.get_balance()

        if lender.lender_name == LenderCurrent.master_lender:
            lender_balance = LenderBalanceCurrent.objects.filter(
                lender__lender_name__in=LenderCurrent.bss_lender_list(),
                lender__lender_status="active",
            ).aggregate(Sum('available_balance'))['available_balance__sum'] or 0
            current_balance = float(current_balance) - float(lender_balance)

        if not current_balance:
            raise JuloException("Failed get current balance")

    # Calculate available balance
    available_balance = float(current_balance)

    return available_balance


def update_committed_amount_for_lender_balance(disbursement, loan_id):
    from juloserver.followthemoney.tasks import calculate_available_balance
    loan = Loan.objects.get_or_none(pk=loan_id)

    if loan is None:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to get loan with disbursement {}'.format(disbursement.id)
        })

        raise JuloException('Loan is not found')
    lender = loan.lender
    loan_amount = loan.loan_amount

    current_lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                            .filter(lender=lender).last()

    if not current_lender_balance:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to update commmited current balance',
            'error': 'loan have invalid lender id: {}'.format(lender.id)
        })
        raise JuloException('Loan does not have lender id')

    current_lender_committed_amount = current_lender_balance.committed_amount
    updated_committed_amount = current_lender_committed_amount + loan_amount
    updated_dict = {
        'loan_amount': loan_amount,
        'committed_amount': updated_committed_amount
    }

    calculate_available_balance.delay(
        current_lender_balance.id,
        SnapshotType.TRANSACTION,
        **updated_dict
    )

    ltm = LenderTransactionMapping.objects.filter(disbursement=disbursement)
    if not ltm:
        LenderTransactionMapping.objects.create(disbursement=disbursement)

    logger.info({
        'method': 'updated_committed_amount_for_lender_balance',
        'msg': 'success to update lender balance current',
        'disbursement_id': disbursement.id,
        'loan_id': loan_id
    })


def update_lender_balance_current_for_disbursement(loan_id, disbursement_summary=None,
                                                   lender_transaction_id=None):
    from juloserver.followthemoney.tasks import (
        update_lender_balance_current_for_disbursement_async_task)
    update_lender_balance_current_for_disbursement_async_task.delay(
        loan_id, disbursement_summary, lender_transaction_id)


def get_ltm_order(list_payment_event_ids):
    if list_payment_event_ids is None:
        list_payment_event_ids = []

    reversal_transactions = []

    # to exclude reversal transactions
    over_paid_payment_event = PaymentEvent.objects.filter(
        id__in=list_payment_event_ids,
        event_type='payment_void',
        event_payment__lt=0
    ).values('payment_id', 'payment_receipt')

    for payment_event in over_paid_payment_event:
        payment_event_object = PaymentEvent.objects.filter(
            event_type='payment',
            payment_receipt=payment_event['payment_receipt'],
            payment_id=payment_event['payment_id'],
        ).last()
        if payment_event_object:
            reversal_transactions.append(payment_event_object.id)

    wrong_paid_payment_event = PaymentEvent.objects.filter(
        id__in=list_payment_event_ids,
        reversal__isnull=False
    )

    for payment_event in wrong_paid_payment_event:
        reversal_transactions.append(payment_event.id)

    filter_ = {
        'payment_event__isnull': False,
        'payment_event__event_type': 'payment',
        'payment_event__payment__loan__lender__id__isnull': False,
        'lender_transaction__isnull': True,
        'payment_event__id__in': list_payment_event_ids
    }

    list_ltm = LenderTransactionMapping.objects.filter(
        **filter_).values(
            'payment_event__payment__loan__lender__id',
            'payment_event__payment__installment_principal',
            'payment_event__payment__installment_interest',
            'payment_event__payment__late_fee_amount',
            'payment_event__event_payment',
            'payment_event__payment__id',
            'payment_event__event_due_amount',
            'id').exclude(payment_event__id__in=reversal_transactions)
    return list_ltm


def get_transfer_order(redis_key):
    ltm_dict = {}

    redis_client = get_redis_client()
    cached_va = redis_client.get(redis_key)
    if cached_va is None:
        return None

    va_dict = eval(cached_va)
    for repayment_type, data in list(va_dict.items()):
        list_ltm = get_ltm_order(data)
        for ltm in list_ltm:
            lender_id = ltm['payment_event__payment__loan__lender__id']
            payment_id = ltm['payment_event__payment__id']

            if not ltm_dict.get(ltm['payment_event__payment__loan__lender__id']):
                ltm_dict[lender_id] = {}
            if repayment_type not in ltm_dict[lender_id]:
                ltm_dict[lender_id][repayment_type] = {}
                repayment_data = ltm_dict[lender_id][repayment_type]
                repayment_data['transaction_mapping_ids'] = []
                repayment_data['payment_ids'] = set()
                repayment_data['paid_principal'] = 0
                repayment_data['paid_interest'] = 0

            repayment_data = ltm_dict[lender_id][repayment_type]

            installment_principal = ltm['payment_event__payment__installment_principal']
            installment_interest = ltm['payment_event__payment__installment_interest']
            late_fee = ltm['payment_event__payment__late_fee_amount']
            paid_amount = ltm['payment_event__event_payment']
            due_amount = ltm['payment_event__event_due_amount']

            total_amount = installment_principal + installment_interest + late_fee
            paid_amount_previous = total_amount - due_amount
            remaining_interest = installment_interest
            remaining_principal = installment_principal

            # calc remaining installment base on paid_amount_previous
            remaining_principal -= paid_amount_previous
            if remaining_principal < 0:
                paid_amount_previous = remaining_principal * -1
                remaining_principal = 0

                remaining_interest -= paid_amount_previous
                if remaining_interest < 0:
                    paid_amount_previous = remaining_interest * -1
                    remaining_interest = 0

            paid_principal = 0
            paid_interest = 0

            if paid_amount < remaining_principal:
                paid_principal = paid_amount
            else:
                paid_principal = remaining_principal
                remaining_paid_amount = paid_amount - remaining_principal
                if remaining_paid_amount < paid_interest:
                    paid_interest = remaining_paid_amount
                else:
                    paid_interest = remaining_interest

            repayment_data['paid_principal'] += paid_principal
            repayment_data['paid_interest'] += paid_interest

            if payment_id not in repayment_data['payment_ids']:
                repayment_data['payment_ids'].add(payment_id)

            repayment_data['transaction_mapping_ids'].append(ltm['id'])

    lenders = LenderCurrent.objects.all()\
                                   .values('id', 'lender_display_name',
                                           'service_fee')

    lender_dict = {}
    for lender in lenders:
        lender_id = lender['id']
        lender_bank_account = LenderBankAccount.objects.get_or_none(
            lender_id=lender_id,
            bank_account_type=BankAccountType.REPAYMENT_VA
        )
        transaction_detail, can_manually = get_transaction_detail(lender_id)

        if not transaction_detail:
            transaction_detail = get_last_transaction(lender_id)

        if lender_bank_account is None:
            continue

        lender_dict[lender_id] = {}
        lender_data = lender_dict[lender_id]

        lender_data['bank_name'] = lender_bank_account.bank_name
        lender_data['account_name'] = \
            lender_bank_account.account_name
        lender_data['account_number'] = \
            lender_bank_account.account_number
        lender_data['lender_name'] = lender['lender_display_name']
        lender_data['service_fee'] = lender['service_fee']
        lender_data['status'] = \
            LenderRepaymentTransactionStatus.UNPROCESSED
        lender_data['displayed_amount'] = 0
        lender_data['can_manually'] = can_manually
        lender_data['transaction_detail'] = transaction_detail
        lender_data['repayment_detail'] = {}

    for lender, payment_dict in list(ltm_dict.items()):
        for key, values in list(payment_dict.items()):
            lender_id = lender
            repayment_type = key
            paid_principal = values['paid_principal']
            paid_interest = values['paid_interest']

            total_paid_amount = paid_principal + paid_interest

            if repayment_type not in lender_dict[lender_id]['repayment_detail']:
                lender_dict[lender_id]['repayment_detail'][repayment_type] = {}
            repayment_detail = lender_dict[lender_id]['repayment_detail'][repayment_type]

            service_fee = lender_dict[lender_id]['service_fee']
            repayment_detail['paid_principal'] = paid_principal
            repayment_detail['paid_interest'] = paid_interest
            repayment_detail['total_service_fee'] = int(
                service_fee * total_paid_amount)

            repayment_detail['transfer_amount'] = total_paid_amount - \
                repayment_detail['total_service_fee']
            repayment_detail['original_amount'] = total_paid_amount
            repayment_detail['transaction_mapping_ids'] = \
                values['transaction_mapping_ids']

            lender_dict[lender_id]['displayed_amount'] += (
                repayment_detail['transfer_amount']
            )
        lender_dict[lender_id]['displayed_amount'] = masked_transfer_amount(
            lender_dict[lender_id]['displayed_amount'])

    return lender_dict


def get_loan_agreement_template(application, lender):
    template = LoanAgreementTemplate.objects.get_or_none(
        lender=lender, is_active=True, agreement_type=LoanAgreementType.GENERAL)
    if not template:
        return None
    loan = application.loan
    first_payment = loan.payment_set.all().order_by('id').first()
    julo_logo = settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png'
    if 'localhost' in julo_logo:
        julo_logo = "#"

    app_history_170 = ApplicationHistory.objects.filter(
        status_new=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED).last()

    context = {'addendum_number': lender.addendum_number,
             'lender_name': lender.lender_name,
             'lender_display_name': lender.lender_display_name,
             'pks_number': lender.pks_number,
             'date_today': format_date(app_history_170.cdate, 'd MMMM yyyy', locale='id_ID'),
             'lender_address': lender.lender_address,
             'poc_name': lender.poc_name,
             'poc_position': lender.poc_position,
             'service_fee': lender.service_fee * 100,
             'application_xid': application.application_xid,
             'loan_amount': display_rupiah(loan.loan_amount),
             'provision_fee_amount': display_rupiah(loan.provision_fee()),
             'interest_rate': '{}%'.format(loan.interest_percent_monthly()),
             'installment_amount': display_rupiah(loan.installment_amount),
             'late_fee_amount': display_rupiah(loan.late_fee_amount),
             'cycle_day': loan.cycle_day,
             'duration_month': loan.loan_duration,
             'due_date_1': format_date(first_payment.due_date, 'd MMMM yyyy', locale='id_ID'),
             'julo_logo': julo_logo,
             'company_logo': lender.logo}

    template = Template(template.body)
    return template.render(Context(context))


def get_default_latefee(application):
    late_fee = LateFeeDefault.MTL_LATEFEE

    if application.product_line_code in ProductLineCodes.stl():
        late_fee = LateFeeDefault.STL_LATEFEE

    return late_fee


def get_loan_detail(app_values, is_loan=False):
    app_id = app_values.first()['id']
    if is_loan:
        loan = Loan.objects.get_or_none(id=app_id)
    else:
        loan = Loan.objects.get_or_none(application_id=app_id)

    if loan:
        for data in app_values:
            application = loan.application
            if not application:
                application = loan.get_application
            default_latefee = get_default_latefee(application)
            latefee_amount = loan.installment_amount * loan.product.late_fee_pct

            if is_loan:
                data['fullname'] = application.fullname
                data['loan_purpose'] = application.loan_purpose
                try:
                    credit_score = application.creditscore.score
                except Exception as e:
                    credit_score = 'b'
                data['creditscore__score'] = credit_score
                data['application_xid'] = loan.loan_xid

            data['fund_transfer_ts'] = loan.fund_transfer_ts
            data['interest_rate'] = '{}%'.format(loan.interest_percent_monthly())
            data['loan_amount'] = display_rupiah(loan.loan_amount)
            data['installment_amount'] = display_rupiah(loan.installment_amount)
            data['loan_duration'] = loan.loan_duration
            data['insurance_policy_number'] = loan.insurance_policy_number if loan.insurance_policy_number else "-"
            data['late_fee_amount'] = display_rupiah(default_latefee if latefee_amount < default_latefee else latefee_amount)

    return app_values


def get_lender_and_director_julo(lender_name):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LIST_LENDER_INFO, is_active=True).first()
    if feature_setting:
        parameters = feature_setting.parameters
        lender_info = parameters.get('lenders').get(lender_name.lower())
        director_info = parameters.get('director')
        return lender_info, director_info
    return {}, {}

def get_detail_loans(approved):
    # separating from get_list_loan to check on ORM level for the DANA logic
    detail_loans = Loan.objects.annotate(
        total_installment_interest=Sum('payment__installment_interest'),
        provision_fee_1=ExpressionWrapper(
            F('product__origination_fee_pct') * F('loan_amount'),
            output_field=fields.FloatField()),
        provision_fee_2=ExpressionWrapper(
            F('loanadjustedrate__adjusted_provision_rate') * F('loan_amount'),
            output_field=fields.FloatField()),
    ).prefetch_related('payment_set').filter(Q(application_id__in=approved) | Q(pk__in=approved))

    return detail_loans


def get_list_loans(detail_loans):
    loans = []
    for loan in detail_loans:
        loan.provision_fee = int(py2round(loan.provision_fee_1))
        if loan.provision_fee_2:
            loan.provision_fee = int(py2round(loan.provision_fee_2))

        last_payment = loan.payment_set.order_by('-late_fee_amount').first()
        loan.payment_late_fee = last_payment.late_fee_amount if last_payment else 0

        loans.append(loan)
    return loans


def check_loans_is_dana_flow(loans):
    is_dana_loan = False
    # check product_line_code 700
    dana_loans = loans.filter(product__product_line__product_line_code=ProductLineCodes.DANA).exists()
    if dana_loans:
        is_dana_loan = True

    return is_dana_loan


def check_loans_is_dana_cash_loan(loans):
    is_dana_loan = False
    dana_loans = loans.filter(product__product_line__product_line_code=ProductLineCodes.DANA_CASH_LOAN).exists()
    if dana_loans:
        is_dana_loan = True

    return is_dana_loan


def check_loans_is_axiata_flow(loans):
    is_axiata_loan = False
    axiata_loans = loans.filter(
        product__product_line__product_line_code=ProductLineCodes.AXIATA_WEB
    ).exists()
    if axiata_loans:
        is_axiata_loan = True

    return is_axiata_loan


def get_summary_loan_agreement_template(
    lender_bucket,
    lender,
    use_fund_transfer=False,
    loan_ids=None,
):
    template = LoanAgreementTemplate.objects.get_or_none(
        lender=lender, is_active=True, agreement_type=LoanAgreementType.SUMMARY
    )

    lender_info, director_info = get_lender_and_director_julo(lender.lender_name)
    if not template or not director_info:
        return None

    today = timezone.localtime(timezone.now())
    lender_bucket_xid = None

    if lender_bucket:
        lender_bucket_xid = lender_bucket.lender_bucket_xid
        if use_fund_transfer:
            today = timezone.localtime(lender_bucket.action_time)
        if lender_bucket.application_ids and lender_bucket.application_ids['approved']:
            approved = lender_bucket.application_ids['approved']
        else:
            approved = lender_bucket.loan_ids['approved']
    else:
        """
        Flow before lender bucket created.
        Since lender haven't approved, the lender sign are removed.
        """
        approved = loan_ids

    detail_loans = get_detail_loans(approved)
    is_dana_flow = check_loans_is_dana_flow(detail_loans)
    loans = get_list_loans(detail_loans)
    if is_dana_flow:
        """
            For Dana cases, p3 template is using different template
            DANA lender are JTP, but since JTP already have p3 template,
            therefore LoanAgreementType 'SUMMARY_DANA' was used for this.
            If there was 1 loan that was not belong to DANA flow (not product_code 700)
            will use normal p3 template instead of DANA template
        """
        template = LoanAgreementTemplate.objects.get_or_none(
            lender=lender, is_active=True, agreement_type=LoanAgreementType.SUMMARY_DANA
        )

    is_dana_cash_loan = check_loans_is_dana_cash_loan(detail_loans)
    if is_dana_cash_loan:
        template = LoanAgreementTemplate.objects.get_or_none(
            lender=lender, is_active=True, agreement_type=LoanAgreementType.SUMMARY_DANA_CASH_LOAN
        )
    dana_cl_product_lookup = (
        ProductLookup.objects.filter(product_line=ProductLineCodes.DANA_CASH_LOAN).last()
    )
    dana_cl_feature_setting = FeatureSetting.objects.get_or_none(
        is_active=True, feature_name=FeatureNameConst.DANA_CASH_LOAN
    )
    dana_cl_service_fee_rate = dana_cl_feature_setting.parameters.get('service_fee_rate')
    dana_cl_interest_rate = dana_cl_product_lookup.interest_rate / 12
    dana_cl_late_fee_rate = dana_cl_product_lookup.late_fee_pct / 30

    is_axiata_flow = check_loans_is_axiata_flow(detail_loans)
    if is_axiata_flow and lender.lender_name != LenderName.JTP:
        template = LoanAgreementTemplate.objects.get_or_none(
            lender=lender, is_active=True, agreement_type=LoanAgreementType.SUMMARY_AXIATA
        )

    for loan in loans:
        loan.total_interest = "-"
        daily_interest = loan.interest_rate_monthly / 30
        if lender and lender in LenderNameByPartner.GRAB:
            # grab save loan in monthly, so calling interest_rate_monthly will produce wrong result
            daily_interest = loan.product.interest_rate / 30

        payments = Payment.objects.filter(loan_id=loan.id).order_by('due_date')
        payment = payments.last()
        if not payment:
            continue

        due_date = payment.due_date
        accepted_date = loan.sphp_accepted_ts.date()
        loan_duration = (due_date - accepted_date).days
        loan.total_interest = py2round(loan_duration * daily_interest * 100, 2)

        loan.dana_late_fee = 0
        loan.platform_fees = []
        loan.platform_tax_fees = []
        loan.interest_tax_fees = []
        if is_dana_cash_loan:
            if hasattr(loan, 'danaloanreference') and loan.danaloanreference.loan_duration:
                loan_duration = loan.danaloanreference.loan_duration
                
            total_interest = dana_cl_interest_rate * loan_duration * loan.loan_amount
            late_fee_amount_per_day = dana_cl_late_fee_rate * (payment.installment_principal + payment.installment_interest)
            service_fee_amount = dana_cl_service_fee_rate * total_interest
            service_fee_tax_amount = service_fee_amount * (11 / 12 * 0.12)

            service_fee_amount = int(Decimal(service_fee_amount).to_integral_value(rounding=ROUND_HALF_UP))
            service_fee_tax_amount = int(Decimal(service_fee_tax_amount).to_integral_value(rounding=ROUND_HALF_UP))

            
            loan.total_interest = int(Decimal(total_interest).to_integral_value(rounding=ROUND_HALF_UP))
            loan.late_fees = int(Decimal(late_fee_amount_per_day).to_integral_value(rounding=ROUND_HALF_UP))
            loan.platform_fees.append('Rp.{}'. format(str(service_fee_amount)))
            loan.platform_tax_fees.append('Rp.{}'. format(str(service_fee_tax_amount)))
            loan.interest_tax_fees.append('15% dari total bunga yang dibayarkan pada pendana (jika berlaku)')

        else:
            # for DANA cases, total interest calculation must be 8%

            # DANA duration always 60 days
            loan_duration = 60

            if hasattr(loan, 'danaloanreference') and loan.danaloanreference.interest_rate:
                loan.total_interest = (
                    loan.danaloanreference.credit_usage_mutation - loan.danaloanreference.amount
                )

            for index, payment in enumerate(payments):
                if index > 3 :
                    # Only 4 payment for DANA case, if more than that may break the p3 Lampiran
                    logger.info({
                        'method': 'get_summary_loan_agreement_template',
                        'msg': 'error loan for DANA have more than 4 payments {}'.format(loan.id)
                    })
                    break

                loan.late_fees = int(
                    py2round(
                        0.7 / 100 * (payment.installment_principal + payment.installment_interest)
                    )
                )
                platform_fee = payment.installment_interest * DANA_SERVICE_FEE_RATE_P3[index] / 100
                platform_fee = int(Decimal(platform_fee).to_integral_value(rounding=ROUND_HALF_UP))
                platform_tax_fee = platform_fee * (11 / 12 * 0.12)
                platform_tax_fee = int(
                    Decimal(platform_tax_fee).to_integral_value(rounding=ROUND_HALF_UP)
                )
                interest_tax_fee = int(payment.installment_interest * 0.15)

                loan.platform_fees.append('Cicilan {}: Rp.{}'. format(str(index+1), str(platform_fee)))
                loan.platform_tax_fees.append('Cicilan {}: Rp.{}'. format(str(index+1), str(platform_tax_fee)))
                loan.interest_tax_fees.append('Cicilan {}: Rp.{}'. format(str(index+1), str(interest_tax_fee)))

    interest_tax = ""
    if lender.lender_name in LenderInterestTax.TAX_LIST:
        interest_tax = str(LenderInterestTax.TAX_LIST[lender.lender_name]) + LenderInterestTax.MESSAGE

    context = {
        'lender': lender,
        'today_date': today.strftime("%d-%m-%Y"),
        'today_datetime': today.strftime("%d-%m-%Y %H:%M:%S"),
        'lender_poc_name': lender.poc_name,
        'no_SKP3': lender_bucket_xid,
        'lender_poc_position': lender.poc_position,
        'loans': loans,
        'director_poc_name': director_info.get('poc_name'),
        'director_poc_position': director_info.get('poc_position'),
        'director_signature': director_info.get('signature','#'),
        'full_lender_company_name': 'full_lender_company_name',
        'lender_license_no': lender.license_number,
        'lender_address': lender.lender_address,
        'lender_company_name': lender.company_name,
        'interest_tax': interest_tax,
    }

    template = Template(template.body)
    return template.render(Context(context))


def count_reconcile_transaction(lender_id, since=None):
    filter_ = {}
    filter_['lender_id'] = lender_id

    if since:
        filter_['cdate__gt'] = since

    disbursement_transaction_type = LenderTransactionType.objects.get(
        transaction_type=LenderTransactionTypeConst.DISBURSEMENT
    )

    #exclude old money flow that happens on 2019-11-5
    today = date(2019, 11, 5)
    excluded_old_money_flow_transactions = LenderTransactionMapping.objects.filter(
        cdate__date=today,
        lender_transaction__isnull=False,
        disbursement__disbursement_type='loan',
        disbursement__method=DisbursementVendors.XFERS,
        disbursement__step__isnull=True
    ).values_list('lender_transaction', flat=True)

    reconcile_amount = LenderTransaction.objects.filter(**filter_)\
                                                .exclude(
                                                    transaction_type=disbursement_transaction_type,
                                                    transaction_description='bca')\
                                                .exclude(
                                                    pk__in=excluded_old_money_flow_transactions)\
                                                .aggregate(total=Sum('transaction_amount'))\
                                                .get('total')

    if not reconcile_amount:
        reconcile_amount = 0

    return reconcile_amount

@transaction.atomic
def update_successful_repayment(group_id, lender_transaction_mapping_ids,
                                lender_id, paid_principal, paid_interest,
                                total_service_fee, original_amount):
    from juloserver.followthemoney.tasks import calculate_available_balance
    lender_balance_current = LenderBalanceCurrent.objects.select_for_update()\
                                                 .filter(lender_id=lender_id)\
                                                 .last()

    if lender_balance_current is None:
        raise JuloException('Lender tidak ditemukan')

    repayment_transaction_type = LenderTransactionType.objects\
                                            .get_or_none(
                                                transaction_type=LenderTransactionTypeConst.REPAYMENT)

    platform_fee_transaction_type = LenderTransactionType.objects\
                                            .get_or_none(
                                                transaction_type=LenderTransactionTypeConst.PLATFORM_FEE)
    transaction_description = 'ref: {}'.format(group_id)

    #create transaction for repayment
    repayment_lender_transaction = LenderTransaction.objects.create(
        lender_id=lender_id,
        lender_balance_current=lender_balance_current,
        transaction_type=repayment_transaction_type,
        transaction_amount=original_amount,
        transaction_description=transaction_description
    )

    LenderTransactionMapping.objects.filter(
        id__in=lender_transaction_mapping_ids
    ).update(
        lender_transaction=repayment_lender_transaction
    )

    service_fee_description = 'ref: {}'.format(
        repayment_lender_transaction.id
    )

    #create transaction for service fee
    LenderTransaction.objects.create(
        lender_id=lender_id,
        lender_balance_current=lender_balance_current,
        transaction_type=platform_fee_transaction_type,
        transaction_amount=total_service_fee * -1,
        transaction_description=service_fee_description
    )

    updated_outstanding_principal = lender_balance_current.outstanding_principal - \
        paid_principal

    updated_outstanding_interest = lender_balance_current.outstanding_interest - \
        paid_interest

    updated_paid_principal = lender_balance_current.paid_principal + \
        paid_principal

    updated_paid_interest = lender_balance_current.paid_interest + \
        paid_interest

    updated_data_dict = {
        'repayment_amount': original_amount,
        'outstanding_principal': updated_outstanding_principal,
        'outstanding_interest': updated_outstanding_interest,
        'paid_principal': updated_paid_principal,
        'paid_interest': updated_paid_interest
    }

    calculate_available_balance.delay(
        lender_balance_current.id, SnapshotType.TRANSACTION, **updated_data_dict)

    return repayment_lender_transaction.id


def new_repayment_transaction(repayment_data, lender=None):
    transaction_record = LenderRepaymentTransaction.objects.create(
        lender=lender,
        **repayment_data
    )
    return transaction_record


def retry_repayment_transaction(lender_id):
    failed_group = LenderRepaymentTransaction.objects.filter(
        lender_id=lender_id,
        status=LenderRepaymentTransactionStatus.FAILED,
    )

    for transaction in failed_group:
        transaction.status = LenderRepaymentTransactionStatus.PENDING
        transaction.transfer_type = LenderRepaymentTransferType.MANUAL
        transaction.reference_id = None
        transaction.save()
    return True


def create_repayment_data(amount, cust_account_number, bank_name,
                          cust_name_in_bank, additional_info,
                          transfer_type, group_id, repayment_type):
    transaction_date = datetime.now().strftime('%Y-%m-%d')
    reference_id = transaction_date + '/BCA'
    currency_code = 'IDR'
    cust_bank_code = Bank.objects.get(bank_name=bank_name).swift_bank_code
    description = 'repayment daily transfer'

    transaction_data = dict(
        transaction_date=transaction_date,
        currency_code=currency_code,
        amount=amount,
        beneficiary_account_number=cust_account_number,
        beneficiary_bank_code=cust_bank_code,
        beneficiary_name=cust_name_in_bank,
        remark=description,
        group_id=group_id,
        transfer_type=transfer_type,
        additional_info=additional_info,
        repayment_type=repayment_type
    )
    if transfer_type == LenderRepaymentTransferType.AUTO:
        transaction_data['reference_id'] = reference_id
    return transaction_data


def get_repayment_transaction_data(lender_target, filtering=False, redis_key=None):
    lender_dict = get_transfer_order(redis_key)

    if filtering:
        lender_dict = filter_by_repayment_transaction(lender_dict)

    jtp_data = lender_dict.get(lender_target.id)

    if not jtp_data:
        return

    data = {}
    data['repayment_detail'] = {}
    data['cust_account_number'] = jtp_data['account_number']
    data['bank_name'] = jtp_data['bank_name']
    data['cust_name_in_bank'] = jtp_data['account_name']

    repayment_detail = jtp_data.get('repayment_detail')
    for repayment_type, values in list(repayment_detail.items()):
        transfer_amount = values['transfer_amount']
        paid_principal = values['paid_principal']
        paid_interest = values['paid_interest']
        original_amount = values['original_amount']
        transaction_mapping_ids = values['transaction_mapping_ids']
        total_service_fee = values['total_service_fee']

        data['repayment_detail'][repayment_type] = {}
        data['repayment_detail'][repayment_type]['amount'] = transfer_amount
        data['repayment_detail'][repayment_type]['additional_info'] = {
            'paid_principal': paid_principal,
            'paid_interest': paid_interest,
            'original_amount': original_amount,
            'transaction_mapping_ids': transaction_mapping_ids,
            'service_fee': jtp_data['service_fee'],
            'total_service_fee': total_service_fee,
        }

    return data


def filter_by_repayment_transaction(lender_dict):
    removed_lenders = []
    for lender_id in lender_dict:
        amount = lender_dict[lender_id]['displayed_amount'] or 0
        if not amount or int(amount) <= 0:
            removed_lenders.append(lender_id)

    for removed_lender in removed_lenders:
        lender_dict.pop(removed_lender, None)
    return lender_dict


def get_transaction_detail(lender_id):
    res = {}
    can_manual_transfer = True
    unsuccessful_trans_group = LenderRepaymentTransaction.objects.filter(
        lender_id=lender_id,
        status__in=[LenderRepaymentTransactionStatus.FAILED,
                    LenderRepaymentTransactionStatus.PENDING]
    ).values_list('group_id', flat=True).distinct()
    if not unsuccessful_trans_group:
        return res, can_manual_transfer

    for group_id in unsuccessful_trans_group:
        dict_data = LenderRepaymentTransaction.objects.filter(
            group_id=group_id,
            lender_id=lender_id
        ).values('id', 'amount', 'transfer_type', 'status', 'reference_id', 'repayment_type', 'cdate')
        res[str(group_id)] = dict_data
        for trans in dict_data:
            if trans['status'] == LenderRepaymentTransactionStatus.PENDING:
                can_manual_transfer = False
                break

    return res, can_manual_transfer


def get_last_transaction(lender_id):
    res = {}
    max_group_id = get_current_group_id(lender_id)
    if not max_group_id:
        return res
    dict_data = LenderRepaymentTransaction.objects.filter(
        lender_id=lender_id,
        group_id=max_group_id
    ).values('id', 'amount', 'transfer_type', 'status', 'reference_id', 'repayment_type', 'cdate')

    res[str(max_group_id)] = dict_data
    return res


def generate_group_id(lender_id):
    group_id = get_current_group_id(lender_id) + 1
    return group_id


def get_current_group_id(lender_id):
    max_group = LenderRepaymentTransaction.objects.filter(lender_id=lender_id).extra(
        select={'group_id_int': 'MAX(group_id::INTEGER)'}
    ).values_list('group_id_int', flat=True)

    if max_group:
        return int(max_group[0] or 0)
    return 0

def get_next_status_by_disbursement_method(application_id, partner_id):
    status = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
    application = Application.objects.get_or_none(pk=application_id)

    if application.status > ApplicationStatusCodes.LENDER_APPROVAL:
        return None

    partner = Partner.objects.get_or_none(pk=partner_id)
    if not partner:
        return status

    if not application:
        return status

    lender_disbursement_methods = LenderDisbursementMethod.objects.filter(
        partner=partner)

    for lender_disbursement_method in lender_disbursement_methods:
        # ProductLineCodes.bri(), ProductLineCodes.loc()
        # ProductLineCodes.grab(), ProductLineCodes.grabfood()
        # ProductLineCodes.laku6(), ProductLineCodes.icare(), ProductLineCodes.axiata()
        # ProductLineCodes.pedemtl(), ProductLineCodes.pedestl()
        # ProductLineCodes.ctl()
        product_lines = eval('ProductLineCodes.{}()'.format(lender_disbursement_method.product_lines))
        if application.product_line_id in product_lines and lender_disbursement_method.is_bulk:
            status = ApplicationStatusCodes.BULK_DISBURSAL_ONGOING
            break

    return status


def get_reversal_trx_data(count=None):
    filter_ = {
        'payment_event__isnull': False,
        'payment_event__event_type': 'payment_void',
        'payment_event__payment__loan__lender__id__isnull': False,
        'payment_event__lenderreversaltransaction__isnull': False
    }
    result = LenderTransactionMapping.objects.filter(**filter_)
    if count:
        return result.count() or 0

    list_reversal_trx = result.annotate(
        destination_lender=F('payment_event__lenderreversaltransaction__destination_lender__lender_name'),
        source_lender=F('payment_event__lenderreversaltransaction__source_lender__lender_name'),
        reversal_amount=F('payment_event__lenderreversaltransaction__amount'),
        destination_bank_name=F('payment_event__lenderreversaltransaction__bank_name'),
        destination_va =F('payment_event__lenderreversaltransaction__va_number'),
        status=F('payment_event__lenderreversaltransaction__status'),
        loan_desc=F('payment_event__lenderreversaltransaction__loan_description'),
        lender_reversal_trx_id=F('payment_event__lenderreversaltransaction__id')

    ).values(
        'id',
        'payment_event__cdate',
        'destination_lender',
        'source_lender',
        'reversal_amount',
        'destination_bank_name',
        'destination_va',
        'payment_event__payment__id',
        'loan_desc',
        'status',
        'lender_reversal_trx_id'
    ).order_by('-payment_event__cdate')
    return list_reversal_trx


def create_lender_reversal_trx_history(data):
    LenderReversalTransactionHistory.objects.create(
        lender_reversal_transaction_id=data['id'],
        amount=data['amount'],
        method=data['method'],
        order_id=data.get('order_id'),
        idempotency_id=data.get('idempotency_id'),
        status=data['status'],
        reason=data['reason'],
        reference_id=data.get('reference_id'),
        step=data['step']
    )


def deduct_lender_reversal_transaction(data):
    from juloserver.followthemoney.tasks import create_lender_transaction_for_reversal_payment
    lender_reversal_trx = LenderReversalTransaction.objects.get_or_none(pk=data['id'])
    if not lender_reversal_trx:
        return False, 'lender reversal transaction not found'

    xfers_service = JTPXfersService(lender_reversal_trx.source_lender.id)
    if check_lender_reversal_step_needed(lender_reversal_trx):
        lender_balance = get_available_balance(lender_reversal_trx.source_lender.id)
        insufficient_balance = lender_reversal_trx.amount > lender_balance
        history_data = xfers_service.charge_reversal_from_lender(lender_reversal_trx, insufficient_balance)
        create_lender_reversal_trx_history(history_data)
    else:
        # deduct
        create_lender_transaction_for_reversal_payment.delay(
            lender_reversal_trx.source_lender.id,
            lender_reversal_trx.amount * -1,
            lender_reversal_trx.voided_payment_event.payment.id,
            lender_reversal_trx.voided_payment_event
        )
        # then create addition
        create_lender_transaction_for_reversal_payment.delay(
            lender_reversal_trx.destination_lender.id,
            lender_reversal_trx.amount,
            lender_reversal_trx.voided_payment_event.payment.id,
            lender_reversal_trx.voided_payment_event.correct_payment_event
        )
        lender_reversal_trx.update_safely(status=LenderReversalTransactionConst.COMPLETED)
    return True, ''


def check_lender_reversal_step_needed(lender_reversal_trx):
    if lender_reversal_trx.source_lender == lender_reversal_trx.destination_lender:
        return LenderReversalTransactionConst.SAME_LENDER_TRX_STEP
    else:
        if lender_reversal_trx.destination_lender:
            return LenderReversalTransactionConst.INTER_LENDER_TRX_STEP
        else:
            return LenderReversalTransactionConst.LENDER_TO_JTF_STEP


def withdraw_to_lender_for_reversal_transaction(lender_reversal_trx):
    xfers_service = JTFXfersService()
    history_data = xfers_service.withdraw_to_lender(lender_reversal_trx)
    create_lender_reversal_trx_history(history_data)


def update_committed_amount_for_lender_balance_payment_point(sepulsa_transaction):
    from juloserver.followthemoney.tasks import calculate_available_balance
    loan = Loan.objects.get_or_none(pk=sepulsa_transaction.loan.id)

    if loan is None:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to get loan with sepulsa_transaction {}'.format(sepulsa_transaction.id)
        })

        raise JuloException('Loan is not found')
    lender = loan.lender
    loan_amount = loan.loan_amount

    current_lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                            .filter(lender=lender).last()

    if not current_lender_balance:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to update commmited current balance',
            'error': 'loan have invalid lender id: {}'.format(lender.id)
        })
        raise JuloException('Loan does not have lender id')

    current_lender_committed_amount = current_lender_balance.committed_amount
    updated_committed_amount = current_lender_committed_amount + loan_amount
    updated_dict = {
        'loan_amount': loan_amount,
        'committed_amount': updated_committed_amount
    }

    calculate_available_balance.delay(
        current_lender_balance.id,
        SnapshotType.TRANSACTION,
        **updated_dict
    )

    ltm = LenderTransactionMapping.objects.filter(sepulsa_transaction=sepulsa_transaction)
    if not ltm:
        LenderTransactionMapping.objects.create(sepulsa_transaction=sepulsa_transaction)

    logger.info({
        'method': 'updated_committed_amount_for_lender_balance',
        'msg': 'success to update lender balance current',
        'sepulsa_transaction_id': sepulsa_transaction.id,
        'loan_id': loan.id
    })


def deposit_internal_lender_balance(lender, amount, transaction_type):
    from juloserver.followthemoney.tasks import calculate_available_balance
    from juloserver.followthemoney.tasks import send_warning_message_low_balance_amount
    if lender.lender_name not in LenderCurrent.manual_lender_list():
        return

    lender_balance = lender.lenderbalancecurrent
    lender_transaction_type = LenderTransactionType.objects.get_or_none(
        transaction_type=transaction_type)

    lender_transaction = LenderTransaction.objects.create(
        lender=lender,
        lender_balance_current=lender_balance,
        transaction_type=lender_transaction_type,
        transaction_amount=amount
    )

    ltm, _ = LenderTransactionMapping.objects.get_or_create(lender_transaction=lender_transaction)
    logger.info({
        'method': 'juloserver.followthemoney.services.deposit_internal_lender_balance',
        'message': 'start deposit lender balance for {}'.format(lender.lender_name),
    })
    if lender.lender_name in LenderCurrent.manual_lender_list():
        calculate_available_balance(
            lender_balance.id, SnapshotType.TRANSACTION,
            repayment_amount=amount,
            is_delay=False
        )
    else:
        calculate_available_balance.delay(
            lender_balance.id, SnapshotType.TRANSACTION,
            repayment_amount=amount,
        )

    if transaction_type == LenderTransactionTypeConst.REPAYMENT:
        LenderManualRepaymentTracking.objects.create(
            lender_transaction_mapping=ltm,
            principal=0,
            interest=0,
            late_fee=0,
            amount=-amount,
            lender=lender,
            transaction_type="settlement",
        )

    if lender.lender_name not in LenderCurrent.escrow_lender_list():
        jtp = LenderCurrent.objects.filter(lender_name="jtp", lender_status="active").last()
        if jtp and jtp.lenderbalancecurrent:
            calculate_available_balance.delay(
                jtp.lenderbalancecurrent.id, SnapshotType.TRANSACTION)

    send_warning_message_low_balance_amount.delay(lender.lender_name)


def create_manual_transaction_mapping(loan, payment_event, principal, interest, late_fee):
    if not loan.lender:
        return

    if loan.lender.lender_name not in LenderCurrent.manual_lender_list():
        return

    ltm = LenderTransactionMapping.objects.get_or_none(payment_event=payment_event)
    if not ltm:
        return

    amount = principal + interest
    if loan.account and loan.account.is_grab_account():
        amount += late_fee

    if payment_event.event_type == "payment_void":
        amount = -amount

    LenderManualRepaymentTracking.objects.create(
        lender_transaction_mapping=ltm,
        principal=principal,
        interest=interest,
        late_fee=late_fee,
        amount=amount,
        lender=loan.lender,
        transaction_type=payment_event.event_type,
    )


def update_committed_amount_for_lender_balance_qris(qris_transaction):
    from juloserver.followthemoney.tasks import calculate_available_balance
    loan = qris_transaction.loan
    if loan is None:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to get loan with qris_transaction {}'.format(qris_transaction.id)
        })

        raise JuloException('Loan is not found')
    lender = loan.lender
    loan_amount = loan.loan_amount

    current_lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                         .filter(lender=lender).last()

    if not current_lender_balance:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to update commmited current balance',
            'error': 'loan have invalid lender id: {}'.format(lender.id)
        })
        raise JuloException('Loan does not have lender id')

    current_lender_committed_amount = current_lender_balance.committed_amount
    updated_committed_amount = current_lender_committed_amount + loan_amount
    updated_dict = {
        'loan_amount': loan_amount,
        'committed_amount': updated_committed_amount
    }

    calculate_available_balance.delay(
        current_lender_balance.id,
        SnapshotType.TRANSACTION,
        **updated_dict
    )

    ltm = LenderTransactionMapping.objects.filter(qris_transaction=qris_transaction)
    if not ltm:
        LenderTransactionMapping.objects.create(qris_transaction=qris_transaction)

    logger.info({
        'method': 'updated_committed_amount_for_lender_balance',
        'msg': 'success to update lender balance current',
        'sepulsa_transaction_id': qris_transaction.id,
        'loan_id': loan.id
    })


def get_bypass_lender_matchmaking(loan, application=None):
    """
    Can only used if the application has an account.
    """
    if not application:
        application = loan.get_application

    # Bypass using application id
    bypass_lender_matchmaking_process = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS,
        category="followthemoney",
        is_active=True
    ).first()
    if (
        bypass_lender_matchmaking_process
        and application.id in bypass_lender_matchmaking_process.parameters['application_ids']
    ):
        lender_name = bypass_lender_matchmaking_process.parameters['lender_name']
        return LenderCurrent.objects.get_or_none(lender_name=lender_name), True

    # Bypass using application product line
    bypass_by_product_line = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE,
        category="followthemoney",
        is_active=True
    ).first()
    if bypass_by_product_line:
        lender_mapping = bypass_by_product_line.parameters
        lender_id = lender_mapping.get(str(application.product_line_id))
        if lender_id:
            return LenderCurrent.objects.get_or_none(id=lender_id), True

    return None, False


def reassign_lender_julo_one(loan_id):
    from juloserver.followthemoney.tasks import auto_expired_loan_tasks
    from juloserver.loan.services.lender_related import (
        julo_one_lender_auto_matchmaking,
        is_application_whitelist_manual_approval_feature,
    )
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history

    try:
        loan = Loan.objects.get_or_none(pk=loan_id)
        if (
            loan.product.product_line.product_line_code
            not in ReassignLenderProductLine.PRODUCT_LINE_CODE_INCLUDE
        ):
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.LENDER_REJECT,
                change_reason="Lender Reject",
            )
            return

        get_loan_lender_history = LoanLenderHistory.objects.filter(loan=loan)

        loan_lender_map = {int(loan.lender.id): True}
        for loan_lender in get_loan_lender_history:
            loan_lender_map[loan_lender.lender_id] = True

        ftm_configuration = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.FTM_CONFIGURATION,
            category="followthemoney", is_active=True)

        if len(get_loan_lender_history) < ftm_configuration.parameters['reassign_count']:
            lender = julo_one_lender_auto_matchmaking(loan, list(loan_lender_map.keys()))
            if not lender:
                # all lender already reject
                update_loan_status_and_loan_history(
                    loan.id,
                    new_status_code=LoanStatusCodes.LENDER_REJECT,
                    change_reason="No Lender found",
                )
                return

            if lender.id in loan_lender_map and not loan.account.is_grab_account():
                # loan already assigned to previous lender, so rejected
                update_loan_status_and_loan_history(
                    loan.id,
                    new_status_code=LoanStatusCodes.LENDER_REJECT,
                    change_reason="Lender Reject",
                )
                return

            LoanLenderHistory.objects.create(lender=loan.lender, loan=loan)
            # this only for handle FTM
            partner = lender.user.partner
            loan.partner = partner
            loan.lender = lender
            loan.save()

            lender_approval = LenderApproval.objects.get_or_none(partner=partner)

            if not lender_approval:
                logger.info({
                    'task': 'reassign_lender_julo_one',
                    'loan_id': loan.id,
                    'status': 'lender_approval not found',
                })
                return

        else:
            # Loan declined more than reassign_count setting, change status to 219
            if not loan.account.is_grab_account():
                update_loan_status_and_loan_history(
                    loan.id,
                    new_status_code=LoanStatusCodes.LENDER_REJECT,
                    change_reason="Lender Reject",
                )

    except Exception as e:
        sentry_client.captureException()
        logger.error({
            'action_view': 'FollowTheMoney - ReAssignLenderJuloOne',
            'data': loan_id,
            'errors': str(e)
        })


def get_list_product_line_code_need_to_hide():
    hide_partner_loan_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.HIDE_PARTNER_LOAN,
        category='followthemoney',
        is_active=True
    )
    if hide_partner_loan_fs:
        return hide_partner_loan_fs.parameters['hidden_product_line_codes']
    return []


def get_skrtp_or_sphp_pdf(loan, application=None):
    # get SPHP / SKRTP pdf, if not exist create and upload to oss
    from juloserver.followthemoney.tasks import generate_julo_one_loan_agreement

    if application:
        filter_document = dict(
            document_source=application.id,
            document_type__in=("skrtp_julo", "sphp_julo", "sphp_digisign", "sphp_privy"),
        )
    else:
        application = loan.get_application
        filter_document = dict(
            loan_xid=loan.loan_xid,
            document_source=loan.id,
            document_type__in=(
                'sphp_privy', 'sphp_julo', 'sphp_grab', 'dana_loan_agreement', 'skrtp_julo',
            ),
        )

    document = Document.objects.filter(**filter_document).last()
    if not document:
        generate_julo_one_loan_agreement(loan.id)
        document = Document.objects.filter(**filter_document).last()
        if not document:
            raise Exception("loan agreement not found")

    return document


def get_signature_key_config():
    default_key = '1'
    feature_setting = FeatureSetting.objects.filter(
        is_active=True,
        feature_name=FeatureNameConst.SIGNATURE_KEY_CONFIGURATION,
    ).last()
    if not feature_setting:
        return [], default_key

    parameters = feature_setting.parameters
    if not parameters:
        return [], default_key

    return parameters.get('users', []), parameters.get('default', default_key)


def generate_lender_signature(lender, signature_key=None):
    if not lender:
        return False

    lender.refresh_from_db()
    user = lender.user
    if not user:
        return False

    if not signature_key:
        user_keys, default_key = get_signature_key_config()
        lender_user_id = str(lender.user_id)
        signature_key = user_keys[lender_user_id] if lender_user_id in user_keys else default_key

    signer = DigitalSignature.Signer(
        user=user,
        key_name="key-{}-{}".format(user.id, signature_key),
        for_organization=True,
        organization=lender.company_name,
        full_name=lender.poc_name,
        email=lender.poc_email,
        province=lender.lender_address_province,
        city=lender.lender_address_city,
        address=lender.lender_address,
    )
    if not signer.key_exists():
        signer.generate_key_pairs()

    if signer.signer.has_certificate():
        return False

    signer.signer.generate_csr()
    CertificateAuthority(
        private_key=settings.JULO_CERTIFICATE_AUTHORITY["PRIVATE_KEY"],
        passphrase=settings.JULO_CERTIFICATE_AUTHORITY["PASSPHRASE"],
        certificate=settings.JULO_CERTIFICATE_AUTHORITY["CERTIFICATE"],
    ).make_certificate(signer.signer)

    return True


def update_loan_agreement_template(template_dir, lender=None):
    with open(settings.BASE_DIR + template_dir, "r") as file:
        html = file.read()

    agreement_filter = {'agreement_type': LoanAgreementType.SKRTP}
    if lender:
        agreement_filter['lender'] = lender
    loan_agreement_templates = LoanAgreementTemplate.objects.filter(**agreement_filter)
    if loan_agreement_templates:
        loan_agreement_templates.update(body=html)

    return loan_agreement_templates


def get_total_outstanding_for_lender(
    lender_name: str, day_filter: date = None, is_get_from_previous_day: bool = False
):
    if not day_filter:
        day_filter = timezone.localtime(timezone.now()).date() - timedelta(days=1)
    day_filter_as_string = day_filter.strftime("%Y-%m-%d")

    # return data from cache if exist
    redis_client = get_redis_client()
    cache_key = 'total_outstanding:{}:{}'.format(lender_name, day_filter_as_string)
    total_outstanding = redis_client.get(cache_key)

    if total_outstanding:
        return float(total_outstanding)

    # return query data from database and cache it for later use
    # because DS update sb.daily_osp_product_lender table every day, so we can cache it for 1 day
    total_outstanding = SbDailyOspProductLender.objects.filter(
        lender=lender_name,
        day=day_filter_as_string
    ).annotate(
        row_sum=(
            F('current') + F('dpd1') + F('dpd30') + F('dpd60') + F('dpd90')
            + F('dpd120') + F('dpd150')
        )
    ).aggregate(
        total_outstanding=Sum('row_sum')
    )['total_outstanding'] or 0.0

    # only cache when table contains new data (DS team only update data once per day)
    if SbDailyOspProductLender.objects.filter(day=day_filter_as_string).exists():
        redis_client.set(key=cache_key, value=total_outstanding, expire_time=timedelta(days=1))

    # if data not exist for today, try to get data from previous day to avoid total_outstanding = 0
    # but only get data from previous day once to avoid infinite recursion
    if not total_outstanding and not is_get_from_previous_day:
        total_outstanding = get_total_outstanding_for_lender(
            lender_name=lender_name,
            day_filter=day_filter - timedelta(days=1),  # yesterday
            is_get_from_previous_day=True,
        )

    return total_outstanding


def assign_lenderbucket_xid_to_lendersignature_service(
    loans: Union[QuerySet, List[Loan]],
    lender_bucket_xid: int,
) -> None:
    lender_signature_dict = {}
    lender_signature_created_list = []
    lender_signature_updated_list = []

    lender_signatures = (
        LenderSignature.objects.filter(loan__in=loans)
        .select_related('loan')
        .only("id", "lender_bucket_xid", "loan__id")
    )
    for lender_signature in lender_signatures:
        lender_signature_dict[lender_signature.loan.id] = lender_signature

    for loan in loans:
        lender_signature = lender_signature_dict.get(loan.id)
        if not lender_signature:
            lender_signature = LenderSignature(loan=loan, lender_bucket_xid=lender_bucket_xid)
            lender_signature_created_list.append(lender_signature)
        else:
            lender_signature.lender_bucket_xid = lender_bucket_xid
            lender_signature_updated_list.append(lender_signature)

    LenderSignature.objects.bulk_create(lender_signature_created_list)
    bulk_update(lender_signature_updated_list, update_fields=['lender_bucket_xid'])


def get_application_credit_score(application):
    if not hasattr(application, "creditscore"):
        return None

    loan_experiment = application.applicationexperiment_set.filter(
        experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION
    )
    if loan_experiment:
        return FalseRejectMiniConst.SCORE

    return application.creditscore.score.upper()

def get_lender_bucket_xids_by_loans(loans) -> dict:
    combined_query = Q()
    loan_ids = [loan.pk for loan in loans]

    redis_cache = RedisCacheLoanBucketXidPast()
    loan_lender_bucket_xids = redis_cache.get_by_loan_ids(loan_ids)
    non_cache_loan_ids = list(set(loan_ids) - set(loan_lender_bucket_xids.keys()))

    if non_cache_loan_ids:
        for loan_id in non_cache_loan_ids:
            combined_query |= Q(loan_ids__approved__contains=[loan_id])
        lender_buckets = list(
            LenderBucket.objects.filter(combined_query)
            .values('loan_ids', 'lender_bucket_xid')[:len(non_cache_loan_ids)]
        )

        for loan_id in non_cache_loan_ids:
            for lender_bucket in lender_buckets:
                if loan_id in lender_bucket['loan_ids']['approved']:
                    loan_lender_bucket_xids[loan_id] = lender_bucket['lender_bucket_xid']
                    redis_cache.set(loan_id, lender_bucket['lender_bucket_xid'])
                    break

    return loan_lender_bucket_xids


def get_max_limit(limit: Union[str, int], max_limit=25) -> int:
    """
    limit is positive and less than max lvalue,
    if error return max
    """
    try:
        if not limit:
            raise ValueError
        limit = int(limit)
        # negative
        if limit < 1 or limit > max_limit:
            raise ValueError

    except ValueError:
        return max_limit

    return limit


# pusdafil services


def get_pusdafil_dataframe_from_gdrive(pusdafil_folder_id, date_year, date_month, date_day):
    gdrive_client = get_finance_google_drive_api_client()

    # get today pusdafil csv data
    folder_hierarchy = [date_year, date_month, date_day]
    current_folder_id = pusdafil_folder_id

    for folder_name in folder_hierarchy:
        current_folder_id = gdrive_client.find_file_or_folder_by_name(
            folder_name, current_folder_id, True
        )
        if not current_folder_id:
            return None, None, False

    data_id = gdrive_client.find_file_or_folder_by_name("data.xlsx", current_folder_id, False)
    if not data_id:
        return None, None, False

    data = gdrive_client.get_data_by_file_id(data_id)
    dataframe = pd.read_excel(io.BytesIO(data))

    return dataframe, current_folder_id, True


def process_lender_repayment_dataframe(df):

    if 'payment_date' not in df or 'payment_receipt' not in df:
        raise PusdafilLenderException(
            "Please use 'payment_date' and 'payment_receipt' for column name"
        )

    error_rows = []
    batch_size = 500
    for i in range(0, len(df), batch_size):
        bulk_lender = []
        df_batch = df[i : i + batch_size]
        for _, data in df_batch.iterrows():
            try:
                error = None
                payment_date = datetime.strptime(data["payment_date"], "%d-%m-%Y %H:%M:%S")
                pusdafil_lender = LenderRepaymentDetail.objects.filter(
                    payment_receipt_id=data["payment_receipt"],
                )
                if pusdafil_lender.exists():
                    raise PusdafilLenderException("Duplicate payment_receipt found")
                else:

                    # find payment event and other data
                    payback_transaction = PaybackTransaction.objects.filter(
                        transaction_id=data["payment_receipt"],
                    ).last()

                    if not payback_transaction:
                        raise PusdafilLenderException("Payment receipt not found")

                    account_transaction = AccountTransaction.objects.filter(
                        payback_transaction=payback_transaction,
                    ).last()

                    if not account_transaction:
                        raise PusdafilLenderException("Payment receipt not found")

                    # create
                    bulk_lender.append(
                        LenderRepaymentDetail(
                            upload_date=timezone.localtime(timezone.now()),
                            payment_receipt_id=data["payment_receipt"],
                            payment_date=payment_date,
                            account_transaction_id=account_transaction.id,
                        )
                    )
            except ValueError as err:
                error = "Please use the right payment_date format dd-mm-yyyy hh:mm:ss"
            except Exception as err:
                error = str(err)
            finally:
                if error:
                    error_rows.append(
                        [
                            data["payment_receipt"],
                            data["payment_date"],
                            error,
                        ]
                    )

        # bulk create
        LenderRepaymentDetail.objects.bulk_create(bulk_lender)

    return error_rows


def upload_pusdafil_error_to_gdrive(error_str, date_folder_id):
    error_df = pd.DataFrame(
        [[error_str]],
        columns=['error'],
    )

    return upload_dataframe_to_gdrive(error_df, date_folder_id, 'error.xlsx')


def upload_pusdafil_partial_error_to_gdrive(error_row, date_folder_id):
    error_df = pd.DataFrame(
        error_row,
        columns=['payment_receipt', 'payment_date', 'error'],
    )

    return upload_dataframe_to_gdrive(error_df, date_folder_id, 'error.xlsx')


def upload_dataframe_to_gdrive(df, folder_id, file_name):
    df_byte = io.BytesIO()
    df.to_excel(df_byte)

    gdrive_client = get_finance_google_drive_api_client()
    gdrive_client.upload_to_folder_id(
        df_byte,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        folder_id,
        file_name,
    )

    return


def delete_data_from_gdrive(file_name, folder_id=None, is_folder=False):
    gdrive_client = get_finance_google_drive_api_client()
    file_id = gdrive_client.find_file_or_folder_by_name(file_name, folder_id, is_folder)

    if not file_id:
        return

    gdrive_client.delete_file_by_file_id(file_id)
    return


def lock_on_redis_with_ex_time(key_name, unique_value, ex=REDIS_LOCK_IN_TIME):
    """
    Acquires a Redis lock to handle concurrent requests in a period of time
        params:: key_name must define in RedisLockWithExTimeType and unique for specific feature
        params:: unique_value is a unique value for specific customers, accounts.
        params:: ex is expiry time in seconds
    """
    # LOCK_ON_REDIS + key_name + unique_value
    if not RedisLockWithExTimeType.key_name_exists(key_name):
        raise RedisNameNotExists("key_name doesn't exists")

    key_name = ':'.join([LOCK_ON_REDIS_WITH_EX_TIME, key_name, str(unique_value)])
    redis_client = get_redis_client()
    if redis_client.set(key_name, unique_value, ex=ex, nx=True):
        return

    raise DuplicateProcessing


def exclude_processed_loans(loan_ids: list):
    new_loan_ids = []
    for loan_id in loan_ids:
        try:
            lock_on_redis_with_ex_time(
                key_name=RedisLockWithExTimeType.APPROVED_LOAN_ON_LENDER_DASHBOARD,
                unique_value=loan_id,
            )
            new_loan_ids.append(loan_id)
        except DuplicateProcessing:
            continue

    logger.info(
        {
            'acction': 'followthemoney.services.exclude_processed_loans',
            'old_loan_ids': loan_ids,
            'new_loan_ids': new_loan_ids,
        }
    )
    return new_loan_ids
