from __future__ import unicode_literals

from builtins import object, str
from juloserver.julo.mixin import GetActiveApplicationMixin

import semver
from cuser.fields import CurrentUserField
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from model_utils import FieldTracker

from juloserver.account.constants import AccountConstant, AccountLookupNameConst
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from juloserver.julo.constants import NewCashbackConst
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.payback.constants import WaiverConst
from juloserver.payment_point.models import SpendTransaction
from juloserver.dana.constants import DANA_ACCOUNT_LOOKUP_NAME
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from django.contrib.postgres.fields import JSONField
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetBenefit,
)

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class AccountModelManager(GetInstanceMixin, JuloModelManager):
    pass


class AccountModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = AccountModelManager()


class AccountLookup(AccountModel):
    id = models.AutoField(db_column='account_lookup_id', primary_key=True)
    partner = models.ForeignKey(
        'julo.Partner', models.DO_NOTHING, db_column='partner_id', null=True
    )
    workflow = models.ForeignKey('julo.Workflow', models.DO_NOTHING, db_column='workflow_id')
    name = models.TextField()
    payment_frequency = models.TextField()
    moengage_mapping_number = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'account_lookup'


class Account(AccountModel, GetActiveApplicationMixin):
    id = models.AutoField(db_column='account_id', primary_key=True)
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    status = models.ForeignKey('julo.StatusLookup', models.DO_NOTHING, db_column='status_code')
    account_lookup = models.ForeignKey(
        'AccountLookup', models.DO_NOTHING, db_column='account_lookup_id'
    )
    cycle_day = models.IntegerField()
    ever_entered_B5 = models.BooleanField(default=False)
    app_version = models.TextField(blank=True, null=True)
    ever_entered_B5_timestamp = models.DateTimeField(null=True, blank=True)
    is_settled_1 = models.NullBooleanField(null=True)
    is_settled_2 = models.NullBooleanField(null=True)
    is_warehouse_1 = models.NullBooleanField(null=True)
    is_warehouse_2 = models.NullBooleanField(null=True)
    is_restructured = models.BooleanField(default=False)
    is_5_days_unreachable = models.BooleanField(default=False)
    is_broken_ptp_plus_1 = models.BooleanField(default=False)
    linked_account_id = models.TextField(null=True, blank=True)
    credit_card_status = models.TextField(blank=True, null=True)
    is_ldde = models.BooleanField(default=False)
    is_payday_changed = models.BooleanField(default=False)
    cashback_counter = models.IntegerField(default=0)
    user_timezone = models.TextField(db_index=True, null=True, blank=True)

    class Meta(object):
        db_table = 'account'

    def __str__(self):
        """Visual identification"""
        return "{} - {}".format(self.id, self.customer.fullname)

    def get_unpaid_account_payment_ids(self):
        return (
            self.accountpayment_set.not_paid_active()
            .order_by('due_date')
            .values_list('id', flat=True)
        )

    def get_paid_account_payment_ids_sorted_by_latest_udate(self):
        return (
            self.accountpayment_set.paid_or_partially_paid()
            .order_by('udate')
            .values_list('id', flat=True)
        )

    def get_outstanding_principal(self):
        total_principal = self.accountpayment_set.aggregate(Sum('principal_amount'))[
            'principal_amount__sum'
        ]
        paid_principal = self.accountpayment_set.paid_or_partially_paid().aggregate(
            Sum('paid_principal')
        )['paid_principal__sum']
        return total_principal - paid_principal

    def get_outstanding_interest(self):
        total_interest = self.accountpayment_set.not_paid_active().aggregate(
            Sum('interest_amount')
        )['interest_amount__sum']
        paid_interest = self.accountpayment_set.paid_or_partially_paid().aggregate(
            Sum('paid_interest')
        )['paid_interest__sum']
        return total_interest - paid_interest

    def get_outstanding_late_fee(self):
        total_late_fee = (
            self.accountpayment_set.not_paid_active().aggregate(Sum('late_fee_amount'))[
                'late_fee_amount__sum'
            ]
            or 0
        )
        paid_late_fee = (
            self.accountpayment_set.not_paid_active().aggregate(Sum('paid_late_fee'))[
                'paid_late_fee__sum'
            ]
            or 0
        )
        return total_late_fee - paid_late_fee

    def get_total_outstanding_due_amount(self):
        today = timezone.localtime(timezone.now()).date()
        due_amount_outstanding = (
            self.accountpayment_set.not_paid_active()
            .filter(due_date__lte=today)
            .aggregate(Sum('due_amount'))['due_amount__sum']
        )
        return due_amount_outstanding if due_amount_outstanding else 0

    def get_total_outstanding_amount(self):
        return self.accountpayment_set.not_paid_active().aggregate(Sum('due_amount'))[
            'due_amount__sum'
        ]

    def get_total_overdue_amount(self):
        return self.accountpayment_set.status_overdue().aggregate(Sum('due_amount'))[
            'due_amount__sum'
        ]

    @property
    def get_account_limit(self):
        return self.accountlimit_set.last()

    def get_oldest_unpaid_account_payment(self):
        """
        Similar logic with: AccountPayment.objects.get_oldest_unpaid_by_account(self.id)
        """
        return self.accountpayment_set.not_paid_active().order_by('due_date').first()

    def sum_of_all_active_loan_amount(self):
        return self.loan_set.filter(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
        ).aggregate(Sum('loan_amount'))['loan_amount__sum']

    def sum_of_all_active_installment_amount(self):
        return (
            self.loan_set.filter(
                loan_status_id__gte=LoanStatusCodes.CURRENT,
                loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
            ).aggregate(Sum('installment_amount'))['installment_amount__sum']
            or 0
        )

    def sum_of_all_account_payment_paid_amount(self):
        return self.accountpayment_set.all().aggregate(Sum('paid_amount'))['paid_amount__sum']

    @property
    def last_application(self):
        return self.application_set.last()

    @property
    def bucket_number(self):
        last_account_payment = self.get_oldest_unpaid_account_payment()
        if not last_account_payment:
            return 0

        return last_account_payment.bucket_number

    @property
    def bucket_name(self):
        if self.bucket_number == 0:
            return 'Current'

        return str(self.bucket_number)

    @property
    def dpd(self):
        last_account_payment = self.get_oldest_unpaid_account_payment()
        if not last_account_payment:
            return 0

        return last_account_payment.dpd

    def get_all_active_loan(self):
        return self.loan_set.filter(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
        )

    def sum_of_all_active_loan_duration(self):
        return self.get_all_active_loan().aggregate(Sum('loan_duration'))['loan_duration__sum'] or 0

    def sum_of_all_active_loan_cashback_earned_total(self):
        return (
            self.get_all_active_loan().aggregate(Sum('cashback_earned_total'))[
                'cashback_earned_total__sum'
            ]
            or 0
        )

    def sum_of_all_active_loan_disbursement_amount(self):
        return (
            self.get_all_active_loan().aggregate(Sum('loan_disbursement_amount'))[
                'loan_disbursement_amount__sum'
            ]
            or 0
        )

    def is_grab_account(self):
        return self.account_lookup.name == GRAB_ACCOUNT_LOOKUP_NAME

    def get_last_unpaid_account_payment(self):
        return self.accountpayment_set.not_paid_active().order_by('due_date').first()

    def get_last_account_payment(self):
        return self.accountpayment_set.order_by('due_date').last()

    def count_account_payment(self):
        return len(self.accountpayment_set.all())

    def get_last_payment_event_date_and_amount(self):
        from juloserver.julo.models import PaymentEvent

        paid_account_payment = (
            self.accountpayment_set.paid_or_partially_paid().order_by('paid_date').last()
        )
        if not paid_account_payment:
            return None, 0

        last_payment_event = PaymentEvent.objects.filter(
            event_type='payment',
            payment_id__in=paid_account_payment.payment_set.all().values_list('id', flat=True),
        ).last()
        if not last_payment_event:
            return None, 0

        return last_payment_event.event_date, last_payment_event.event_payment

    def is_account_ever_suspeneded(self):
        return self.accountstatushistory_set.filter(
            status_new=AccountConstant.STATUS_CODE.suspended
        ).exists()

    def waiver_is_active(self):
        return self.waivertemp_set.filter(
            status__in=[WaiverConst.ACTIVE_STATUS, WaiverConst.IMPLEMENTED_STATUS]
        ).exists()

    def is_account_eligible_to_hit_channeling_api(self):
        is_autodebet_active = self.autodebetaccount_set.filter(is_use_autodebet=True).exists()
        is_benefit_type_waive_interest = AutodebetBenefit.objects.filter(
            account_id=self.id, benefit_type='waive_interest', is_benefit_used=False
        ).exists()

        if is_autodebet_active and is_benefit_type_waive_interest:
            return False
        return True

    def get_all_paid_off_loan(self):
        return self.loan_set.filter(loan_status_id=LoanStatusCodes.PAID_OFF)

    def is_app_version_outdated(self, minimum_version: str) -> bool:
        """
        Check if the current app version is older than the given minimum version.
        """
        current_ver = self.app_version

        # if there is no app version, considered outdated
        if not current_ver:
            return True

        return semver.match(current_ver, "<%s" % minimum_version)

    @property
    def is_dana(self) -> bool:
        return self.account_lookup.name == DANA_ACCOUNT_LOOKUP_NAME

    def latest_limit_values_graduation(self):
        from juloserver.graduation.models import GraduationCustomerHistory2
        latest_graduation_history = GraduationCustomerHistory2.objects.filter(
            account_id=self.id, latest_flag=True
        ).last()
        if not latest_graduation_history:
            return {'value_old': None, 'value_new': None}

        set_limit = AccountLimitHistory.objects.get(
            id=latest_graduation_history.set_limit_history_id
        )
        return {'value_old': set_limit.value_old, 'value_new': set_limit.value_new}

    @property
    def is_selloff(self):
        return self.status_id == AccountConstant.STATUS_CODE.sold_off

    def is_julo_one_account(self):
        return self.account_lookup.name == AccountLookupNameConst.JULO1

    @property
    def cashback_counter_for_customer(self):
        if self.cashback_counter < NewCashbackConst.MAX_CASHBACK_COUNTER:
            return (self.cashback_counter or 0) + 1

        return NewCashbackConst.MAX_CASHBACK_COUNTER

    def get_total_not_due_outstanding_amount(self):
        return (
            self.accountpayment_set.not_paid_active()
            .not_due_yet()
            .aggregate(Sum('due_amount'))['due_amount__sum']
            or 0
        )

    @property
    def get_last_used_payment_method_name(self):
        last_paid_account_payment = (
            self.accountpayment_set.filter(paid_date__isnull=False).order_by('paid_date').last()
        )
        if not last_paid_account_payment:
            return '-'

        last_payment = (
            last_paid_account_payment.payment_set.filter(paid_date__isnull=False)
            .order_by('paid_date')
            .last()
        )
        if not last_payment:
            return '-'

        last_payment_event = (
            last_payment.paymentevent_set.filter(event_type='payment', payment_method__isnull=False)
            .order_by('event_date')
            .last()
        )
        if not last_payment_event:
            return '-'

        return (
            '-'
            if not last_payment_event.payment_method
            else last_payment_event.payment_method.payment_method_name
        )

    @property
    def get_first_loan_fund_transfer_ts_for_crm(self):
        from babel.dates import format_date

        first_loan = (
            self.loan_set.filter(fund_transfer_ts__isnull=False)
            .order_by('fund_transfer_ts')
            .first()
        )
        if not first_loan:
            return '-'

        return (
            '-'
            if not first_loan.fund_transfer_ts
            else format_date(first_loan.fund_transfer_ts, 'dd MMMM yyyy', locale='id_ID')
        )

    @property
    def is_eligible_for_cashback_new_scheme(self) -> bool:
        if AutodebetAccount.objects.is_account_autodebet(self.id):
            return False
        application = self.last_application
        if not application:
            return False

        return application.is_eligible_for_new_cashback()

    @property
    def is_account_active_refinancing(self) -> bool:
        if (
            self.status_id == AccountConstant.STATUS_CODE.suspended
            or self.get_all_active_loan().filter(is_restructured=True).exists()
        ):
            return True
        return False

    @property
    def is_cashback_new_scheme(self) -> bool:
        """
        this function will call by UI purpose
        """
        return self.is_eligible_for_cashback_new_scheme and not self.is_account_active_refinancing

    @property
    def julo_one_starter_have_unpaid_loan(self):
        if not self.last_application.is_julo_one_or_starter():
            return False

        for loan in self.get_all_active_loan():
            if loan.get_oldest_unpaid_payment():
                return True
        return False

    @property
    def cashback_incoming_level(self):
        from juloserver.julo.models import CashbackCounterHistory

        """
        expected return of this function
        current -> incoming -> return
        0 -> 1 -> 1
        1 -> 2 -> 2
        2 -> 3 -> 3
        3 -> 4 -> 4
        4 -> 5 -> 5
        5 -> 5 -> 6
        6 -> 5 -> 7
        """
        current_level = self.cashback_counter
        incoming_level = self.cashback_counter_for_customer
        if incoming_level == 5 and current_level == 4:
            return incoming_level
        if incoming_level == 5 and current_level == 5:
            incoming_level += 1
            last_cashback_history = (
                CashbackCounterHistory.objects.filter(account_payment__account__id=self.id)
                .only('counter')
                .order_by('-cdate')[:2]
            )
            if len(last_cashback_history) == 2:
                incoming_level = (
                    incoming_level + 1 if last_cashback_history[1].counter == 5 else incoming_level
                )
        return incoming_level


class AccountStatusHistory(AccountModel):
    id = models.AutoField(db_column='account_status_history_id', primary_key=True)
    account = models.ForeignKey('Account', models.DO_NOTHING, db_column='account_id')
    status_old = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='status_old',
        null=True,
        blank=True,
        related_name='account_status_history_old',
    )
    status_new = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='status_new',
        related_name='account_status_history_new',
    )
    changed_by = CurrentUserField()
    change_reason = models.TextField()
    is_reactivable = models.NullBooleanField()

    class Meta(object):
        db_table = 'account_status_history'


class AccountLimit(AccountModel):
    id = models.AutoField(db_column='account_limit_id', primary_key=True)
    account = models.ForeignKey('Account', models.DO_NOTHING, db_column='account_id')
    max_limit = models.BigIntegerField(default=0)
    set_limit = models.BigIntegerField(default=0)
    available_limit = models.BigIntegerField(default=0)
    used_limit = models.BigIntegerField(default=0)
    latest_affordability_history = models.ForeignKey(
        'julo.AffordabilityHistory',
        models.DO_NOTHING,
        db_column='latest_affordability_history_id',
        null=True,
        blank=True,
    )
    latest_credit_score = models.ForeignKey(
        'julo.CreditScore',
        models.DO_NOTHING,
        db_column='latest_credit_score_id',
        null=True,
        blank=True,
    )

    # please add new field to FieldTracker when create new field
    # for ForeignKey field, add '_id' to suffix of field
    tracker = FieldTracker(
        [
            'account_id',
            'max_limit',
            'set_limit',
            'available_limit',
            'used_limit',
            'latest_affordability_history_id',
            'latest_credit_score_id',
        ]
    )

    class Meta(object):
        db_table = 'account_limit'


class AccountLimitHistory(AccountModel):
    id = models.AutoField(db_column='account_limit_history_id', primary_key=True)
    account_limit = models.ForeignKey(
        'AccountLimit', models.DO_NOTHING, db_column='account_limit_id'
    )
    field_name = models.TextField()
    value_old = models.TextField(null=True, blank=True)
    value_new = models.TextField()

    affordability_history = models.ForeignKey(
        'julo.AffordabilityHistory',
        models.DO_NOTHING,
        db_column='affordability_history_id',
        blank=True,
        null=True,
    )
    credit_score = models.ForeignKey(
        'julo.CreditScore', models.DO_NOTHING, db_column='credit_score_id', blank=True, null=True
    )

    class Meta(object):
        db_table = 'account_limit_history'


class AccountTransaction(AccountModel):
    id = models.AutoField(db_column='account_transaction_id', primary_key=True)
    account = models.ForeignKey('Account', models.DO_NOTHING, db_column='account_id')
    payback_transaction = models.OneToOneField(
        'julo.PaybackTransaction',
        models.DO_NOTHING,
        db_column='payback_transaction_id',
        null=True,
        blank=True,
    )
    disbursement = models.ForeignKey(
        'disbursement.Disbursement',
        models.DO_NOTHING,
        db_column='disbursement_id',
        null=True,
        blank=True,
    )
    transaction_date = models.DateTimeField()
    accounting_date = models.DateTimeField()
    transaction_amount = models.BigIntegerField()
    transaction_type = models.TextField()
    towards_principal = models.BigIntegerField(default=0)
    towards_interest = models.BigIntegerField(default=0)
    towards_latefee = models.BigIntegerField(default=0)
    can_reverse = models.BooleanField(default=True)
    reversed_transaction_origin = models.OneToOneField(
        "self",
        models.DO_NOTHING,
        db_column='reversed_transaction_origin_id',
        blank=True,
        null=True,
        related_name="transaction_destination",
    )
    reversal_transaction = models.OneToOneField(
        "self",
        models.DO_NOTHING,
        db_column='reversal_transaction_id',
        blank=True,
        null=True,
        related_name="original_transaction",
    )
    spend_transaction = models.ForeignKey(
        SpendTransaction, models.DO_NOTHING, db_column='spend_transaction_id', null=True, blank=True
    )
    device = models.ForeignKey(
        'julo.Device', models.DO_NOTHING, db_column='device_id', null=True, blank=True
    )
    account_transaction_note = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'account_transaction'

    def save(self, *args, **kwargs):
        # Forbidding accounting date from being updated
        if "update_fields" in kwargs:
            update_fields = kwargs["update_fields"]
            if "accounting_date" in update_fields:
                update_fields.remove("accounting_date")

        super(AccountTransaction, self).save(*args, **kwargs)


class CreditLimitGeneration(TimeStampedModel):
    id = models.AutoField(db_column='credit_limit_generation_id', primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id', blank=True, null=True
    )
    account = models.ForeignKey(
        'Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    affordability_history = models.ForeignKey(
        'julo.AffordabilityHistory', models.DO_NOTHING, db_column='affordability_history_id'
    )
    credit_matrix = models.ForeignKey(
        'julo.CreditMatrix', models.DO_NOTHING, db_column='credit_matrix_id', null=True
    )
    max_limit = models.BigIntegerField()
    set_limit = models.BigIntegerField()
    log = models.TextField()
    reason = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'credit_limit_generation'


class AccountProperty(AccountModel):
    id = models.AutoField(db_column='account_property_id', primary_key=True)
    account = models.ForeignKey('Account', models.DO_NOTHING, db_column='account_id')

    pgood = models.FloatField()
    p0 = models.FloatField()
    proven_threshold = models.BigIntegerField()
    is_proven = models.BooleanField(default=False)
    is_premium_area = models.BooleanField(default=True)
    is_salaried = models.BooleanField(default=True)
    voice_recording = models.BooleanField(default=True)
    concurrency = models.BooleanField(default=False)
    ever_refinanced = models.BooleanField(default=False)
    refinancing_ongoing = models.BooleanField(default=False)
    is_entry_level = models.BooleanField(default=False)
    last_graduation_date = models.DateField(null=True, blank=True)

    class Meta(object):
        db_table = 'account_property'


class AccountPropertyHistory(AccountModel):
    id = models.AutoField(db_column='account_property_history_id', primary_key=True)
    account_property = models.ForeignKey(
        'AccountProperty', models.DO_NOTHING, db_column='account_property_id', blank=True, null=True
    )
    field_name = models.TextField()
    value_old = models.TextField(null=True, blank=True)
    value_new = models.TextField()

    class Meta(object):
        db_table = 'account_property_history'


class CurrentCreditMatrix(TimeStampedModel):
    id = models.AutoField(db_column='current_credit_matrix_id', primary_key=True)
    credit_matrix = models.ForeignKey(
        'julo.CreditMatrix', models.DO_NOTHING, db_column='credit_matrix_id'
    )
    transaction_type = models.TextField()

    class Meta(object):
        db_table = 'current_credit_matrix'


class AdditionalCustomerInfo(TimeStampedModel):
    HOME_STATUS_CHOICES = (
        ('Kos', 'Kos'),
        ('Milik keluarga', 'Milik keluarga'),
        ('Milik sendiri, lunas', 'Milik sendiri, lunas'),
        ('Milik sendiri, mencicil', 'Milik sendiri, mencicil'),
        ('Kontrak', 'Kontrak'),
    )

    id = models.AutoField(db_column='additional_customer_info_id', primary_key=True)
    additional_customer_info_type = models.TextField()
    customer = models.ForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id', blank=True, null=True
    )
    additional_address_number = models.IntegerField(blank=True, null=True)
    street_number = models.TextField()
    provinsi = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    kabupaten = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True
    )
    kecamatan = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True
    )
    kelurahan = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True
    )
    kode_pos = models.CharField(
        max_length=5,
        validators=[
            ascii_validator,
            RegexValidator(regex='^[0-9]{5}$', message='Kode pos has to be 5 numeric digits'),
        ],
        blank=True,
        null=True,
    )
    home_status = models.CharField(
        "Status domisili",
        choices=HOME_STATUS_CHOICES,
        max_length=50,
        validators=[ascii_validator],
        blank=True,
        null=True,
    )
    occupied_since = models.DateField(blank=True, null=True)
    latest_updated_by = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='latest_updated_by_id',
    )
    latest_action = models.TextField()

    class Meta(object):
        db_table = 'additional_customer_info'


class AccountFavorites(TimeStampedModel):
    id = models.AutoField(db_column='account_favorites_id', primary_key=True)
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod', models.DO_NOTHING, db_column='transaction_method_id'
    )
    ranking = models.IntegerField()
    account = models.ForeignKey(Account, models.DO_NOTHING, db_column='account_id')

    class Meta(object):
        db_table = 'account_favorites'


class Address(TimeStampedModel):
    id = models.AutoField(db_column='address_id', primary_key=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    provinsi = models.TextField()
    kabupaten = models.TextField()
    kecamatan = models.TextField()
    kelurahan = models.TextField()
    kodepos = models.CharField(
        max_length=5,
        blank=True,
        null=True,
        validators=[
            ascii_validator,
            RegexValidator(regex='^[0-9]{5}$', message='Kodepos harus 5 digit angka'),
        ],
    )
    detail = models.TextField()

    class Meta(object):
        db_table = 'address'

    def __str__(self):
        return self.id

    @property
    def full_address(self):
        full_address = ", ".join(
            [
                _f
                for _f in [
                    self.detail,
                    self.kelurahan,
                    self.kecamatan,
                    self.kabupaten,
                    self.provinsi,
                    self.kodepos,
                ]
                if _f
            ]
        )
        return full_address


class ExperimentGroupModelManager(GetInstanceMixin, JuloModelManager):
    pass


class ExperimentGroup(TimeStampedModel):
    id = models.AutoField(db_column='experiment_group_id', primary_key=True)
    experiment_setting = models.ForeignKey(
        'julo.ExperimentSetting', models.DO_NOTHING, db_column='experiment_setting_id'
    )
    account = models.ForeignKey(
        Account, models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id', blank=True, null=True
    )
    group = models.TextField(blank=True, null=True)
    segment = models.TextField(blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )

    # Customer ID for record ExperimentJuloStarter
    customer = BigForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id', blank=True, null=True
    )
    is_failsafe = models.NullBooleanField(null=True, default=None)
    source = models.TextField(null=True, blank=True, default=None)

    objects = ExperimentGroupModelManager()

    class Meta(object):
        db_table = 'experiment_group'


class AccountNote(TimeStampedModel):
    id = models.AutoField(db_column='account_note_id', primary_key=True)
    added_by = CurrentUserField(related_name="account_notes")
    account = models.ForeignKey(Account, models.DO_NOTHING, db_column='account_id')
    note_text = models.TextField()

    class Meta(object):
        db_table = 'account_note'


class AccountCycleDayHistory(TimeStampedModel):
    id = models.AutoField(db_column='account_cycle_day_history_id', primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    account = models.ForeignKey(Account, models.DO_NOTHING, db_column='account_id')
    latest_flag = models.BooleanField(default=True)
    old_cycle_day = models.IntegerField()
    new_cycle_day = models.IntegerField()
    reason = models.CharField(max_length=50, blank=True, null=True)
    parameters = JSONField(default=dict)
    end_date = models.DateField(blank=True, null=True)
    auto_adjust_changes = JSONField(default=dict)

    class Meta(object):
        db_table = 'account_cycle_day_history'

    objects = ExperimentGroupModelManager()


class AccountGTL(AccountModel):
    id = models.AutoField(db_column='account_gtl_id', primary_key=True)
    account = models.OneToOneField(Account, models.DO_NOTHING, db_column='account_id')
    is_gtl_inside = models.BooleanField(default=False)
    is_maybe_gtl_inside = models.BooleanField(default=False)
    is_gtl_outside = models.BooleanField(default=False)
    is_gtl_outside_bypass = models.BooleanField(default=False)
    last_gtl_outside_blocked = models.DateTimeField(
        null=True, help_text='last expiry time for GTL outside blocking',
    )

    class Meta(object):
        db_table = 'account_gtl'


class AccountGTLHistory(AccountModel):
    id = models.AutoField(db_column='account_gtl_history_id', primary_key=True)
    account_gtl = models.ForeignKey(AccountGTL, models.DO_NOTHING, db_column='account_gtl_id')
    field_name = models.TextField()
    value_old = models.TextField(null=True, blank=True)
    value_new = models.TextField()
    change_reason = models.CharField(max_length=100, null=True, blank=True)

    class Meta(object):
        db_table = 'account_gtl_history'


class EverDPD90Whitelist(TimeStampedModel):
    id = models.AutoField(db_column='everdpd90_whitelist_id', primary_key=True)
    account_id = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."everdpd90_whitelist"'
        managed = False


class PaymentMethodMapping(TimeStampedModel):
    id = models.AutoField(db_column='payment_method_mapping_id', primary_key=True)
    payment_method_name = models.CharField(max_length=150, blank=False, null=False)
    visible_payment_method_name = models.CharField(max_length=150, blank=False, null=False)

    class Meta(object):
        db_table = 'payment_method_mapping'
