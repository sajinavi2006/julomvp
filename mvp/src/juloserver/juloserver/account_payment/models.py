from __future__ import unicode_literals
import logging
import collections

from datetime import timedelta

from babel.dates import format_date
from dateutil.relativedelta import relativedelta

from builtins import object
from ckeditor.fields import RichTextField

from cuser.fields import CurrentUserField
from django.db import models
from django.db.models import Q
from django.utils import timezone
from datetime import date, datetime
from django.db.models import Sum
from django.contrib.postgres.fields import JSONField, ArrayField

from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import (
    GetInstanceMixin, JuloModelManager, TimeStampedModel, CustomQuerySet
)
from juloserver.julo.models import (
    StatusLookup,
    XidLookup,
    GlobalPaymentMethod,
)
from juloserver.account.constants import AccountConstant
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes
from juloserver.julo.constants import BucketConst, WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.account_payment.constants import (
    CheckoutRequestCons,
    AccountPaymentDueStatus,
)
from juloserver.grab.utils import get_grab_dpd
import ast

from juloserver.pii_vault.collection.services import mask_phone_number_sync

logger = logging.getLogger(__name__)


class AccountPaymentModelManager(GetInstanceMixin, JuloModelManager):
    pass


class AccountPaymentModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = AccountPaymentModelManager()


class AccountPaymentQuerySet(CustomQuerySet):
    def normal(self):
        return self.exclude(is_restructured=True)

    def overdue(self):
        today = timezone.localtime(timezone.now()).date()
        return self.not_paid_active().filter(due_date__lt=today)

    def not_paid_active(self):
        return self.normal().filter(status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def bucket_1_t0(self, account_ids):
        today = timezone.localtime(timezone.now())
        return self.filter(
            status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            due_date=today).exclude(
            account_id__in=account_ids).exclude(id__in=list(
                self.eligible_for_b5_gte(only_account_payment_ids=True)))

    def bucket_1_minus(self, days, account_ids):
        today = timezone.localtime(timezone.now())
        days_later = today + timedelta(days=days)
        return self.filter(
            status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            due_date=days_later).exclude(
            account_id__in=account_ids).exclude(id__in=list(
                self.eligible_for_b5_gte(only_account_payment_ids=True)))

    def bucket_1_t_minus_1(self, account_ids):
        return self.bucket_1_minus(1, account_ids)

    def bucket_1_plus(self, range1, range2, account_ids):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)

        return self.filter(
            status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            due_date__range=[range2_ago, range1_ago]
        ).exclude(
            account_id__in=account_ids).exclude(id__in=list(
                self.eligible_for_b5_gte(only_account_payment_ids=True)))

    def bucket_1_t1_t4(self, account_ids):
        return self.bucket_1_plus(1, 4, account_ids)

    def bucket_1_t5_t10(self, account_ids):
        return self.bucket_1_plus(5, 10, account_ids)

    def bucket_1_t1_t10(self, account_ids):
        return self.bucket_1_plus(
            BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to'], account_ids
        )

    def dpd_to_be_called(self):
        return self.not_paid_active().filter(is_collection_called=False)

    def get_bucket_1(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['to'])

        return self.filter(due_date__range=[range2_ago, range1_ago])\
            .exclude(id__in=self.eligible_for_b5_gte(only_account_payment_ids=True))

    def get_bucket_2(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_2_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_2_DPD['to'])

        return self.filter(due_date__range=[range2_ago, range1_ago])\
            .exclude(id__in=self.eligible_for_b5_gte(only_account_payment_ids=True))

    def get_bucket_3(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_3_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_3_DPD['to'])

        return self.filter(due_date__range=[range2_ago, range1_ago])\
            .exclude(id__in=self.eligible_for_b5_gte(only_account_payment_ids=True))

    def get_bucket_4(self):
        today = timezone.localtime(timezone.now()).date()
        range1_ago = today - timedelta(days=BucketConst.BUCKET_4_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_4_DPD['to'])
        release_date = datetime.strptime(BucketConst.EXCLUDE_RELEASE_DATE, '%Y-%m-%d')
        range1_ago_release_date = release_date - timedelta(days=91)
        range2_ago_release_date = release_date - timedelta(days=100)

        return self.filter(Q(due_date__range=[range2_ago, range1_ago]) |
                           Q(due_date__range=[range2_ago_release_date, range1_ago_release_date])
                           ).exclude(id__in=self.eligible_for_b5_gte(only_account_payment_ids=True))

    def eligible_for_b5_gte(self, only_account_payment_ids=False):
        from juloserver.julo.models import Payment
        eligible_account_payment_ids = Payment.objects.filter(
            account_payment__isnull=False,
            loan__ever_entered_B5=True).exclude(
            loan__loan_status_id=LoanStatusCodes.PAID_OFF
        ).distinct('account_payment_id').\
            values_list('account_payment_id', flat=True)
        if only_account_payment_ids:
            return eligible_account_payment_ids

        return self.filter(id__in=eligible_account_payment_ids)

    def eligible_for_b5_gte_improved(self, only_account_payment_ids=False):
        from juloserver.julo.models import Payment
        from juloserver.julo.services2 import get_redis_client
        redisClient = get_redis_client()
        cached_eligible_for_b5_account_payment_ids = redisClient.get_list(
            'ELIGIBLE_FOR_B5_ACCOUNT_PAYMENT_IDS')
        if not cached_eligible_for_b5_account_payment_ids:
            eligible_account_payment_ids = Payment.objects.filter(
                account_payment__isnull=False,
                loan__ever_entered_B5=True).exclude(
                loan__loan_status_id=LoanStatusCodes.PAID_OFF
            ).distinct('account_payment_id'). \
                values_list('account_payment_id', flat=True)
            if eligible_account_payment_ids:
                redisClient.set_list(
                    'ELIGIBLE_FOR_B5_ACCOUNT_PAYMENT_IDS', eligible_account_payment_ids,
                    timedelta(hours=6))
        else:
            eligible_account_payment_ids = list(
                map(int, cached_eligible_for_b5_account_payment_ids))

        if only_account_payment_ids:
            return eligible_account_payment_ids
        return self.filter(id__in=eligible_account_payment_ids)

    def get_all_bucket_5(self, end_dpd):
        today = timezone.localtime(timezone.now()).date()
        end_range = today - timedelta(days=end_dpd)
        return self.eligible_for_b5_gte().filter(
            due_date__gte=end_range)

    def get_bucket_5_by_range(self, start_dpd, end_dpd=None):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=start_dpd)
        if not end_dpd:
            return self.eligible_for_b5_gte().filter(
                due_date__gte=range1_ago, account__ever_entered_B5=True)

        range2_ago = today - timedelta(days=end_dpd)
        return self.eligible_for_b5_gte().filter(
            due_date__range=[range2_ago, range1_ago])

    def get_bucket_6_by_range(self, start_dpd, end_dpd=None):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=start_dpd)
        if not end_dpd:
            return self.eligible_for_b5_gte().filter(
                due_date=range1_ago)

        range2_ago = today - timedelta(days=end_dpd)

        return self.eligible_for_b5_gte().filter(
            due_date__range=[range2_ago, range1_ago]
        )

    def determine_bucket_by_range(self, ranges):
        today = timezone.localtime(timezone.now())
        if collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to']]):
            return self.get_bucket_1()
        elif collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']]):
            return self.get_bucket_2()
        elif collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']]):
            return self.get_bucket_3()
        elif collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']]):
            return self.get_bucket_4()
        else:
            range1_ago = today - timedelta(days=ranges[0])
            range2_ago = today - timedelta(days=ranges[1])
            return self.filter(due_date__range=[range2_ago, range1_ago])

    def list_bucket_group_with_range(self, range1, range2):
        today = timezone.localtime(timezone.now())
        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)
        else:
            return self.dpd_to_be_called().determine_bucket_by_range([range1, range2])

    def bucket_list_t11_to_t40(self):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']
        ).exclude(account__ever_entered_B5=True)

    def bucket_list_t41_to_t70(self):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
        ).exclude(account__ever_entered_B5=True)

    def bucket_list_t71_to_t90(self):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_4_DPD['to'], BucketConst.BUCKET_4_DPD['from']
        ).exclude(id__in=self.eligible_for_b5_gte(only_account_payment_ids=True))

    def get_all_bucket_by_range(self, start_dpd, end_dpd=None):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=start_dpd)
        if not end_dpd:
            return self.filter(
                due_date__lte=range1_ago)

        range2_ago = today - timedelta(days=end_dpd)
        return self.filter(
            due_date__range=[range2_ago, range1_ago])

    def paid_or_partially_paid(self):
        return self.filter(paid_amount__gt=0)

    def by_product_line_codes(self, codes):
        return self.filter(
            account__application__product_line__product_line_code__in=codes)

    def exclude_product_codes(self, ids):
        return self.exclude(
            account__application__product_line_id__in=ids)

    def not_overdue(self):
        return self.filter(status__lt=PaymentStatusCodes.PAYMENT_DUE_TODAY)

    def get_grab_payments(self):
        return self.not_paid_active().filter(
            account__account_lookup__workflow__name=WorkflowConst.GRAB,
        )

    def get_julo_one_payments(self):
        return self.filter(
            account__account_lookup__workflow__name__in=[
                WorkflowConst.JULO_ONE,
                WorkflowConst.JULO_ONE_IOS,
            ]
        )

    def get_julo_turbo_payments(self):
        return self.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER)

    def due_soon(self, due_in_days=3):
        today = date.today()
        day_delta = timedelta(days=due_in_days)
        days_from_now = today + day_delta
        return self.not_paid_active().filter(due_date=days_from_now)

    def paid(self):
        # query the active loan
        return self.filter(status__gte=PaymentStatusCodes.PAID_ON_TIME,
                           status__lte=PaymentStatusCodes.PAID_LATE)\
            .exclude(status=PaymentStatusCodes.SELL_OFF)

    def exclude_recovery_bucket(self, recovery_bucket_list):
        return self.exclude(account__accountbuckethistory__bucket_name__in=recovery_bucket_list)


class AccountPaymentManager(AccountPaymentModelManager):
    # we define this for future if we have something that need to be exclude (like loan refinancing)
    def get_queryset(self):
        return AccountPaymentQuerySet(self.model)

    def normal(self):
        return self.get_queryset().exclude(is_restructured=True)

    def not_paid_active(self):
        return self.normal().not_paid_active()

    def status_overdue(self):
        return self.not_paid_active().exclude(status__lt=PaymentStatusCodes.PAYMENT_DUE_TODAY)

    def oldest_account_payment(self):
        return self.not_paid_active()\
            .order_by('account', 'due_date')\
            .distinct('account')

    def paid_or_partially_paid(self):
        return self.normal().paid_or_partially_paid()

    def paid(self):
        return self.normal().paid()

    def status_tobe_update(self, is_partner=False):
        today = timezone.localtime(timezone.now()).date()
        dpd_1 = today - timedelta(days=1)
        dpd_4 = today - timedelta(days=4)
        dpd_5 = today - timedelta(days=5)
        dpd_8 = today - timedelta(days=8)
        dpd_30 = today - timedelta(days=30)
        dpd_60 = today - timedelta(days=60)
        dpd_90 = today - timedelta(days=90)
        dpd_120 = today - timedelta(days=120)
        dpd_150 = today - timedelta(days=150)
        dpd_180 = today - timedelta(days=180)
        qs = self.normal().not_paid_active().filter(
            (
                Q(due_date=today) &
                Q(status_id__lt=PaymentStatusCodes.PAYMENT_DUE_TODAY)
            ) |
            (
                Q(due_date__lte=dpd_1) &
                Q(status_id__lt=PaymentStatusCodes.PAYMENT_1DPD)
            ) |
            (
                Q(account__application__product_line_id=ProductLineCodes.DAGANGAN) &
                Q(due_date=dpd_4) & Q(status_id__lt=PaymentStatusCodes.PAYMENT_4DPD)
            ) |
            (
                Q(due_date__lte=dpd_5) &
                Q(status_id__in={
                    PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                    PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_4DPD
                })
            ) |
            (
                Q(account__application__product_line_id__in=[
                    ProductLineCodes.KOPERASI_TUNAS, ProductLineCodes.KOPERASI_TUNAS_45
                ]) &
                Q(due_date=dpd_8) & Q(status_id__lt=PaymentStatusCodes.PAYMENT_8DPD)
            ) |
            (
                Q(due_date__lte=dpd_30) &
                Q(status_id__in={
                    PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                    PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_4DPD,
                    PaymentStatusCodes.PAYMENT_5DPD, PaymentStatusCodes.PAYMENT_8DPD
                })
            ) |
            (
                Q(due_date__lte=dpd_60) &
                Q(status_id__in={
                    PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                    PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_4DPD,
                    PaymentStatusCodes.PAYMENT_5DPD, PaymentStatusCodes.PAYMENT_8DPD,
                    PaymentStatusCodes.PAYMENT_30DPD
                })
            ) |
            (
                Q(due_date__lte=dpd_90) &
                Q(status_id__in={
                    PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                    PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_4DPD,
                    PaymentStatusCodes.PAYMENT_5DPD, PaymentStatusCodes.PAYMENT_8DPD,
                    PaymentStatusCodes.PAYMENT_30DPD, PaymentStatusCodes.PAYMENT_60DPD
                })
            ) |
            (
                Q(due_date__lte=dpd_120) &
                Q(status_id__in={
                    PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                    PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_4DPD,
                    PaymentStatusCodes.PAYMENT_5DPD, PaymentStatusCodes.PAYMENT_8DPD,
                    PaymentStatusCodes.PAYMENT_30DPD, PaymentStatusCodes.PAYMENT_60DPD,
                    PaymentStatusCodes.PAYMENT_90DPD
                })
            ) |
            (
                Q(due_date__lte=dpd_150) &
                Q(status_id__in={
                    PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                    PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_4DPD,
                    PaymentStatusCodes.PAYMENT_5DPD, PaymentStatusCodes.PAYMENT_8DPD,
                    PaymentStatusCodes.PAYMENT_30DPD, PaymentStatusCodes.PAYMENT_60DPD,
                    PaymentStatusCodes.PAYMENT_90DPD, PaymentStatusCodes.PAYMENT_120DPD
                })
            ) |
            (
                Q(due_date__lte=dpd_180) &
                Q(status_id__in={
                    PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                    PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_4DPD,
                    PaymentStatusCodes.PAYMENT_5DPD, PaymentStatusCodes.PAYMENT_8DPD,
                    PaymentStatusCodes.PAYMENT_30DPD, PaymentStatusCodes.PAYMENT_60DPD,
                    PaymentStatusCodes.PAYMENT_90DPD, PaymentStatusCodes.PAYMENT_120DPD,
                    PaymentStatusCodes.PAYMENT_150DPD
                })
            )
        ).exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
        if not is_partner:
            qs = qs.exclude(account__account_lookup__workflow__name__in=WorkflowConst.
                            specific_partner_for_account_reactivation())
        else:
            qs = qs.filter(account__account_lookup__workflow__name__in=WorkflowConst.
                           specific_partner_for_account_reactivation())

        return qs

    def failed_automated_robocall_account_payments(self, product_codes, dpd):
        today = timezone.localtime(timezone.now()).date()
        filter_day = None
        if dpd > 0:
            filter_day = today - relativedelta(days=abs(dpd))
        else:
            filter_day = today + relativedelta(days=abs(dpd))

        qs = self.normal()\
                 .by_product_line_codes(product_codes)\
                 .not_paid_active()

        return qs.filter(due_date=filter_day).exclude(
            Q(is_success_robocall=True) | Q(is_collection_called=True))

    def tobe_robocall_account_payments(self, product_codes, dpd_list):
        today = timezone.localtime(timezone.now()).date()
        list_due_date = []
        for dpd in dpd_list:
            if dpd > 0:
                date = today - relativedelta(days=abs(dpd))
            else:
                date = today + relativedelta(days=abs(dpd))
            list_due_date.append(date)

        qs = self.normal()\
                 .by_product_line_codes(product_codes)\
                 .not_paid_active()
        return qs.filter(due_date__in=list_due_date)

    def due_soon(self, due_in_days):
        return self.normal().due_soon(due_in_days=due_in_days)

    def get_oldest_unpaid_by_account(self, account_ids):
        """
        Similar logic with Account::get_oldest_unpaid_account_payment()
        """
        qs = self.not_paid_active().filter(account_id__in=account_ids)
        return list(qs.distinct('account_id').order_by('account_id', 'due_date'))

    def get_last_paid_by_account(self, account_ids):
        qs = self.get_queryset().paid().filter(account_id__in=account_ids)
        return list(qs.distinct('account_id').order_by('account_id', '-due_date'))


class AccountPayment(AccountPaymentModel):
    id = models.AutoField(db_column='account_payment_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id')
    due_date = models.DateField()
    due_amount = models.BigIntegerField(default=0)
    principal_amount = models.BigIntegerField(default=0)
    interest_amount = models.BigIntegerField(default=0)
    late_fee_amount = models.BigIntegerField(default=0)
    paid_date = models.DateField(null=True, blank=True)
    paid_amount = models.BigIntegerField(default=0)
    paid_principal = models.BigIntegerField(default=0)
    paid_interest = models.BigIntegerField(default=0)
    paid_late_fee = models.BigIntegerField(default=0)
    status = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, db_column='status_code')
    late_fee_applied = models.IntegerField(blank=True, null=True)
    locked_by = CurrentUserField()
    is_locked = models.BooleanField(default=False)

    is_collection_called = models.BooleanField(default=False)
    is_ptp_robocall_active = models.NullBooleanField()
    is_reminder_called = models.BooleanField(default=False)
    is_robocall_active = models.NullBooleanField()
    is_success_robocall = models.NullBooleanField()
    ptp_amount = models.BigIntegerField(blank=True, default=0)
    ptp_date = models.DateField(blank=True, null=True)
    is_restructured = models.BooleanField(default=False)
    account_payment_xid = models.BigIntegerField(
        blank=True, null=True, db_index=True, unique=True)
    paid_during_refinancing = models.NullBooleanField(blank=True, null=True, default=None)
    is_paid_within_dpd_1to10 = models.NullBooleanField(blank=True, null=True, default=None)
    autodebet_retry_count = models.IntegerField(default=0)

    class Meta(object):
        db_table = 'account_payment'

    objects = AccountPaymentManager()

    DUE_SOON_DAYS = 3

    @property
    def dpd(self):
        """
        Negative value means it's not due yet. 0 means due today. Positive
        value means due is late.
        """
        if self.account.account_lookup.workflow.name == WorkflowConst.GRAB:
            return get_grab_dpd(self.id)
        else:
            if not self.due_date or self.is_paid:
                days = 0
            else:
                time_delta = date.today() - self.due_date
                days = time_delta.days
            logger.debug({'due_date': self.due_date, 'dpd': days})
            return days

    @property
    def is_paid(self):
        return self.status_id >= PaymentStatusCodes.PAID_ON_TIME

    @property
    def cashback_multiplier(self):
        due_date = self.due_date
        today = timezone.localtime(timezone.now()).date()
        if due_date - timedelta(days=3) <= today <= due_date - timedelta(days=2):
            return 2
        elif due_date - timedelta(days=3) > today:
            return 3
        else:
            return 1

    def get_status_based_on_due_date(self):
        if self.account.account_lookup.workflow.name == WorkflowConst.GRAB:
            payments = self.payment_set.not_paid_active()
            highest_payment_status_code = None
            for payment in payments:
                grab_payment_status_code = payment.payment_status_id
                if not highest_payment_status_code:
                    highest_payment_status_code = grab_payment_status_code
                if highest_payment_status_code < grab_payment_status_code:
                    highest_payment_status_code = grab_payment_status_code
            if highest_payment_status_code:
                return highest_payment_status_code
        if self.dpd < -self.DUE_SOON_DAYS:
            return PaymentStatusCodes.PAYMENT_NOT_DUE
        elif self.dpd < -1:
            return PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS
        elif self.dpd < 0:
            return PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS
        elif self.dpd == 0:
            return PaymentStatusCodes.PAYMENT_DUE_TODAY
        elif self.account.last_application.product_line_id == ProductLineCodes.DAGANGAN and\
                self.dpd == 4:
            return PaymentStatusCodes.PAYMENT_4DPD
        elif self.dpd < 5:
            return PaymentStatusCodes.PAYMENT_1DPD
        elif self.dpd < 30:
            if self.account.last_application.product_line_id in {
                ProductLineCodes.KOPERASI_TUNAS,
                ProductLineCodes.KOPERASI_TUNAS_45,
            }:
                if self.dpd < 8:
                    return PaymentStatusCodes.PAYMENT_1DPD
                else:
                    return PaymentStatusCodes.PAYMENT_8DPD
            elif self.account.last_application.product_line_id == ProductLineCodes.DAGANGAN:
                return PaymentStatusCodes.PAYMENT_4DPD
            else:
                return PaymentStatusCodes.PAYMENT_5DPD
        elif self.dpd < 60:
            return PaymentStatusCodes.PAYMENT_30DPD
        elif self.dpd < 90:
            return PaymentStatusCodes.PAYMENT_60DPD
        elif self.dpd < 120:
            return PaymentStatusCodes.PAYMENT_90DPD
        elif self.dpd < 150:
            return PaymentStatusCodes.PAYMENT_120DPD
        elif self.dpd < 180:
            return PaymentStatusCodes.PAYMENT_150DPD
        elif self.dpd >= 180:
            return PaymentStatusCodes.PAYMENT_180DPD

    def change_status(self, status_code):
        new_status = StatusLookup.objects.get(status_code=status_code)
        self.status = new_status

    def create_account_payment_status_history(self, data):
        data['account_payment'] = self
        data['status_new'] = self.status
        payment_history = AccountPaymentStatusHistory(**data)
        payment_history.save()

    @property
    def payment_number(self):
        return 1

    @property
    def due_late_days(self):
        today = timezone.localtime(timezone.now()).date()

        due_late_days = today - self.due_date
        days = due_late_days.days

        return days

    def due_status(self, account_info=True):
        dpd = self.due_late_days
        due_status = 'TERLAMBAT'
        if dpd < 0:
            due_status = 'Lancar' if account_info else 'Belum jatuh tempo'
        elif dpd == 0:
            due_status = 'Jatuh Tempo' if account_info else 'Jatuh tempo hari ini'

        if self.is_paid:
            due_status = "Terbayar tepat waktu"
            if PaymentStatusCodes.PAID_ON_TIME < self.status.status_code \
                    <= PaymentStatusCodes.PAID_LATE:
                due_status = "Terbayar terlambat"

        return due_status

    def due_statusv2(self):
        dpd = self.due_late_days
        due_status = AccountPaymentDueStatus.LATE
        if dpd < 0:
            due_status = AccountPaymentDueStatus.NOT_DUE
        elif dpd == 0:
            due_status = AccountPaymentDueStatus.DUE

        if self.is_paid:
            due_status = AccountPaymentDueStatus.PAID_ON_TIME
            if (
                PaymentStatusCodes.PAID_ON_TIME
                < self.status.status_code
                <= PaymentStatusCodes.PAID_LATE
            ):
                due_status = AccountPaymentDueStatus.PAID_LATE

        return due_status

    @property
    def remaining_late_fee(self):
        return self.late_fee_amount - self.paid_late_fee

    @property
    def remaining_interest(self):
        return self.interest_amount - self.paid_interest

    @property
    def remaining_principal(self):
        return self.principal_amount - self.paid_principal

    @property
    def paid_status_str(self):
        if self.is_paid:
            return 'Paid'
        elif self.paid_amount != 0:
            return 'Partially Paid'

        return 'Not Paid'

    @property
    def due_status_str(self):
        if self.dpd < 0:
            return 'N'

        return 'Y'

    @property
    def paid_off_status_str(self):
        if self.due_amount > 0:
            return 'N'

        return 'Y'

    @property
    def bucket_number(self):
        if self.dpd < 1:
            return 0

        if self.dpd <= 10:
            return 1

        if self.dpd <= 40:
            return 2

        if self.dpd <= 70:
            return 3

        if self.dpd <= 90:
            return 4

        return 5

    def update_status_based_on_payment(self):
        worst_status = max(list(
            self.payment_set.exclude(
                payment_status_id__in=PaymentStatusCodes.paid_status_codes()
            ).values_list('payment_status_id', flat=True)
        ))
        self.change_status(worst_status)

    def update_paid_date_based_on_payment(self):
        paid_date = None
        paid_date_list = list(
            self.payment_set.all().values_list('paid_date', flat=True)
        )
        paid_date_list = [x for x in paid_date_list if x is not None]
        if paid_date_list:
            paid_date = max(paid_date_list)

        self.paid_date = paid_date

    @property
    def paid_late_days(self):
        if self.due_date is None or self.paid_date is None:
            days = 0
        else:
            time_delta = self.paid_date - self.due_date
            days = time_delta.days
        logger.debug({'paid_late_days': days})
        return days

    def update_late_fee_amount(self, late_fee):
        self.late_fee_amount += abs(late_fee)
        self.due_amount += abs(late_fee)
        if self.late_fee_applied:
            self.late_fee_applied += 1
        else:
            self.late_fee_applied = 1
        self.save(update_fields=['late_fee_applied', 'late_fee_amount', 'due_amount'])

    def total_cashback_earned(self):
        return self.payment_set.all().aggregate(Sum('cashback_earned'))['cashback_earned__sum']

    def total_redeemed_cashback(self):
        return self.payment_set.all().aggregate(Sum('redeemed_cashback'))['redeemed_cashback__sum']

    def max_cashback_earned(self):
        amount = 0
        for payment in self.payment_set.select_related('loan').all():
            amount += payment.loan.cashback_monthly
        return amount

    def get_previous_account_payment(self):
        query = self.account.accountpayment_set.filter(
            due_date__lt=self.due_date)
        return query.last()

    def get_next_unpaid_payment(self):
        query = self.account.accountpayment_set.filter(
            due_date__gt=self.due_date,
            status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
        if query:
            return query.order_by("due_date").first()
        else:
            return None

    @property
    def bucket_number_special_case(self):
        if self.account.ever_entered_B5:
            return 5

        if self.dpd < 1:
            return 0

        if self.dpd <= 10:
            return 1

        if self.dpd <= 40:
            return 2

        if self.dpd <= 70:
            return 3

        if self.dpd <= 90:
            return 4

        return 0

    @property
    def notification_due_date(self):
        if self.ptp_date:
            return self.ptp_date
        else:
            return self.due_date

    @property
    def bucket_number_when_paid(self):
        if not self.is_paid:
            return 0

        if self.account.ever_entered_B5:
            return 5

        time_delta = self.paid_date - self.due_date
        dpd = time_delta.days
        if dpd < 1:
            return 0

        if dpd <= 10:
            return 1

        if dpd <= 40:
            return 2

        if dpd <= 70:
            return 3

        if dpd <= 90:
            return 4

        return 5

    @property
    def due_date_indonesian_format(self):
        if not self.due_date:
            return ''
        return format_date(
            self.due_date, 'dd MMMM yyyy', locale='id_ID')

    def generate_xid(self):
        if self.id is None or self.account_payment_xid is not None:
            return
        self.account_payment_xid = XidLookup.get_new_xid()

    def remaining_installment_amount(self):
        remaining_amount = (self.principal_amount + self.interest_amount) - \
            (self.paid_principal + self.paid_interest)
        return remaining_amount

    def sum_total_installment_amount(self):
        return self.principal_amount + self.interest_amount

    @property
    def get_all_loan_purpose_for_crm(self):
        all_loan_purposes = self.payment_set.exclude(
            loan__loan_status_id__in=LoanStatusCodes.loan_status_not_active()).values_list(
            'loan__loan_purpose', flat=True).order_by('-loan__loan_amount')[:2]
        return '-' if not all_loan_purposes else '/'.join(all_loan_purposes)

    @property
    def risk_score(self):
        from juloserver.apiv2.models import PdCollectionModelResult

        collection_model_result = PdCollectionModelResult.objects.filter(
            account_payment_id=self.id
        ).last()
        return collection_model_result.segment_name if collection_model_result else None


class AccountPaymentStatusHistory(AccountPaymentModel):
    id = models.AutoField(db_column='account_payment_status_history_id', primary_key=True)
    account_payment = models.ForeignKey(
        'AccountPayment', models.DO_NOTHING, db_column='account_payment_id')
    status_old = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='status_old',
        null=True, blank=True,
        related_name='account_payment_status_history_old'
    )
    status_new = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='status_new',
        related_name='account_payment_status_history_new'
    )
    changed_by = CurrentUserField()
    change_reason = models.TextField(null=True, blank=True,)

    class Meta(object):
        db_table = 'account_payment_status_history'


class AccountPaymentNote(AccountPaymentModel):
    id = models.AutoField(db_column='account_payment_note_id', primary_key=True)
    account_payment_status_history = models.ForeignKey(
        'AccountPaymentStatusHistory',
        models.DO_NOTHING,
        db_column='account_payment_status_history_id',
        null=True, blank=True)
    account_payment = models.ForeignKey(
        'AccountPayment', models.DO_NOTHING, db_column='account_payment_id',
        null=True, blank=True)
    note_text = models.TextField()
    added_by = CurrentUserField()
    extra_data = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'account_payment_note'

    def __init__(self, *args, **kwargs):
        super(AccountPaymentNote, self).__init__(*args, **kwargs)
        if self.note_text:
            self.note_text = mask_phone_number_sync(self.note_text)
        if self.extra_data:
            value = ast.literal_eval(mask_phone_number_sync(self.extra_data, True))
            self.extra_data = value


class AccountPaymentLockHistory(AccountPaymentModel):
    id = models.AutoField(db_column='account_payment_lock_history_id', primary_key=True)
    account_payment = models.ForeignKey(
        'AccountPayment', models.DO_NOTHING, db_column='account_payment_id')
    user_id = CurrentUserField()
    is_locked = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'account_payment_lock_history'


class AccountPaymentPreRefinancing(AccountPaymentModel):
    id = models.AutoField(db_column='account_payment_pre_refinancing_id', primary_key=True)

    due_date = models.DateField(null=True)
    ptp_date = models.DateField(blank=True, null=True)

    is_ptp_robocall_active = models.NullBooleanField()
    due_amount = models.BigIntegerField()
    principal_amount = models.BigIntegerField(default=0)
    interest_amount = models.BigIntegerField(default=0)

    paid_date = models.DateField(blank=True, null=True)
    paid_amount = models.BigIntegerField(blank=True, default=0)

    late_fee_amount = models.BigIntegerField(blank=True, default=0)
    late_fee_applied = models.IntegerField(blank=True, default=0, null=True)
    discretionary_adjustment = models.BigIntegerField(blank=True, default=0)

    is_robocall_active = models.NullBooleanField()
    is_success_robocall = models.NullBooleanField()
    is_collection_called = models.BooleanField(default=False)
    uncalled_date = models.DateField(null=True)
    reminder_call_date = models.DateTimeField(blank=True, null=True)
    is_reminder_called = models.BooleanField(default=False)
    is_whatsapp = models.BooleanField(default=False)
    is_whatsapp_blasted = models.NullBooleanField(default=False)

    paid_interest = models.BigIntegerField(blank=True, default=0)
    paid_principal = models.BigIntegerField(blank=True, default=0)
    paid_late_fee = models.BigIntegerField(blank=True, default=0)
    ptp_amount = models.BigIntegerField(blank=True, default=0)

    change_due_date_interest = models.BigIntegerField(blank=True, default=0)
    is_restructured = models.BooleanField(default=False)

    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id')
    account_payment = models.ForeignKey(
        'AccountPayment', models.DO_NOTHING, db_column='account_payment_id')
    status_code = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, db_column='status_code')
    loan_refinancing_request = models.ForeignKey(
        'loan_refinancing.LoanRefinancingRequest', models.DO_NOTHING,
        db_column='loan_refinancing_request_id')

    class Meta(object):
        db_table = 'account_payment_pre_financing'


class OldestUnpaidAccountPayment(TimeStampedModel):
    """
    this table for storing a snapshot of all oldest
    unpaid account payments for collection reminder comms.
    """

    id = models.AutoField(db_column='oldest_unpaid_account_payment_id', primary_key=True)
    account_payment = models.ForeignKey(
        'AccountPayment', models.DO_NOTHING, db_column='account_payment_id')
    dpd = models.IntegerField(blank=True, null=True)
    due_amount = models.BigIntegerField(default=0)
    snapshot_ts = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    class Meta(object):
        db_table = 'oldest_unpaid_account_payment'


class CheckoutRequestQuerySet(CustomQuerySet):
    def status_tobe_update_expired(self):
        now = timezone.localtime(timezone.now())
        return self.filter(
            status=CheckoutRequestCons.ACTIVE,
            expired_date__lte=now
        )


class CheckoutRequestManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return CheckoutRequestQuerySet(self.model)

    def status_tobe_update_expired(self):
        return self.get_queryset().status_tobe_update_expired()


class CheckoutRequest(TimeStampedModel):
    """
    this table for storing a checkout request
    """

    CHECKOUT_STATUS_CHOICES = (
        ('active', 'active'),
        ('expired', 'expired'),
        ('canceled', 'canceled'),
        ('redeemed', 'redeemed'),
        ('finished', 'finished'))
    id = models.AutoField(db_column='checkout_request_id', primary_key=True)
    account_id = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id'
    )
    checkout_request_xid = models.CharField(max_length=100, unique=True)
    status = models.CharField(choices=CHECKOUT_STATUS_CHOICES,
                              max_length=50, blank=True, null=True, default='active')
    total_payments = models.BigIntegerField(blank=True, default=0)
    payment_event_ids = ArrayField(models.CharField(max_length=100),
                                   null=True, default=None, blank=True)
    account_payment_ids = ArrayField(models.CharField(max_length=100),
                                     null=True, default=None, blank=True)
    cashback_used = models.BigIntegerField(blank=True, default=0)
    checkout_payment_method_id = models.ForeignKey(
        'julo.PaymentMethod', models.DO_NOTHING, db_column='checkout_payment_method_id',
        blank=True, null=True, default=None
    )
    receipt_ids = ArrayField(models.CharField(max_length=100),
                             null=True, default=None, blank=True)
    expired_date = models.DateTimeField(blank=True, null=True)
    checkout_amount = models.BigIntegerField(blank=True, default=0)
    session_id = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=15, null=True, blank=True)
    loan_refinancing_request = models.ForeignKey(
        'loan_refinancing.LoanRefinancingRequest',
        models.DO_NOTHING,
        db_column='loan_refinancing_request_id',
        null=True,
        blank=True,
    )
    total_late_fee_discount = models.BigIntegerField(blank=True, null=True)

    objects = CheckoutRequestManager()

    class Meta(object):
        db_table = 'checkout_request'


class PaymentMethodInstruction(TimeStampedModel):
    id = models.AutoField(db_column='payment_method_instruction_id', primary_key=True)
    global_payment_method = models.ForeignKey(
        GlobalPaymentMethod, models.DO_NOTHING, db_column='global_payment_method_id'
    )
    title = models.TextField()
    content = RichTextField(config_name='payment_method_instruction')
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'payment_method_instruction'


class PaymentDetailPageAccessHistory(TimeStampedModel):
    id = models.AutoField(db_column='payment_detail_page_access_history_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id'
    )
    url = models.URLField(max_length=1000)
    access_count = models.IntegerField()

    class Meta(object):
        db_table = 'payment_detail_page_access_history'


class RepaymentRecallLog(TimeStampedModel):
    id = models.AutoField(db_column='repayment_recall_log_id', primary_key=True)
    payback_transaction_id = models.BigIntegerField(
        blank=True,
        null=True,
    )
    customer_id = models.BigIntegerField()

    class Meta(object):
        db_table = 'repayment_recall_log'
        managed = False


class RepaymentApiLog(TimeStampedModel):
    id = models.AutoField(db_column='repayment_api_log_id', primary_key=True)
    application_id = models.BigIntegerField(blank=True, null=True)
    account_id = models.BigIntegerField(blank=True, null=True)
    account_payment_id = models.BigIntegerField(blank=True, null=True)
    request_type = models.TextField()
    http_status_code = models.IntegerField()
    request = models.TextField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    vendor = models.TextField()

    class Meta(object):
        db_table = 'repayment_api_log'
        managed = False


class CRMCustomerDetail(TimeStampedModel):
    id = models.AutoField(db_column='crm_customer_detail_id', primary_key=True)
    section = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    attribute_name = models.TextField(blank=True, null=True)
    sort_order = models.IntegerField()
    parameter_model_value = JSONField(default=None, blank=True, null=True)

    class Meta(object):
        db_table = 'crm_customer_detail'


class LateFeeRule(TimeStampedModel):
    id = models.AutoField(db_column='late_fee_rule_id', primary_key=True)
    dpd = models.IntegerField()
    product_lookup = models.ForeignKey(
        'julo.ProductLookup', models.DO_NOTHING, db_column='product_code'
    )
    late_fee_pct = models.FloatField()

    class Meta(object):
        db_table = 'late_fee_rule'


class LateFeeBlock(TimeStampedModel):
    id = models.AutoField(db_column='late_fee_block_id', primary_key=True)
    payment = BigForeignKey(
        'julo.Payment', models.DO_NOTHING, db_column='payment_id', blank=True, null=True
    )
    dpd = models.IntegerField()
    block_reason = models.TextField(blank=True, null=True)
    valid_until = models.DateField(blank=True, null=True)
    ptp = BigForeignKey('julo.PTP', models.DO_NOTHING, db_column='ptp_id', blank=True, null=True)

    class Meta(object):
        db_table = 'late_fee_block'


class CashbackClaim(TimeStampedModel):
    id = models.AutoField(db_column='cashback_claim_id', primary_key=True)
    status = models.TextField(blank=True, null=True)
    account_id = models.BigIntegerField(db_index=True, blank=False, null=False)
    account_transaction_id = models.BigIntegerField(db_index=True, blank=True, null=True)
    total_cashback_amount = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'cashback_claim'
        managed = False


class CashbackClaimPayment(TimeStampedModel):
    id = models.AutoField(db_column='cashback_claim_payment_id', primary_key=True)
    cashback_claim = models.ForeignKey(
        CashbackClaim,
        models.DO_NOTHING,
        db_column='cashback_claim_id',
        blank=True,
        null=True,
    )
    status = models.TextField(blank=True, null=True)
    payment_id = models.BigIntegerField(db_index=True, blank=False, null=False)
    max_claim_date = models.DateField(blank=True, null=True)
    cashback_amount = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'cashback_claim_payment'
        managed = False
