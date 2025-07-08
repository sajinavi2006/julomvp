from builtins import str
from builtins import object
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from cuser.fields import CurrentUserField
from django.contrib.postgres.fields import JSONField, ArrayField

from juloserver.julocore.data.models import GetInstanceMixin, JuloModelManager, TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julo.models import (
    Application, Loan, Customer, Payment, ascii_validator, PIIType
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey, BigOneToOneField
from juloserver.julo.models import SkiptraceHistoryManager
from juloserver.grab.constants import (
    AccountHaltStatus, GrabFeatureNameConst, PromoCodeStatus,
    ApplicationStatus
)
from juloserver.disbursement.models import Disbursement
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager

class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class GrabCustomerDataManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabCustomerDataPIIVaultManager(PIIVaultModelManager, GrabCustomerDataManager):
    pass


class GrabCustomerData(PIIVaultModel):
    class Meta(object):
        db_table = 'grab_customer_data'

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"

    OTP_STATUS = [
        (UNVERIFIED, "Unverified Phone Number"),
        (VERIFIED, "Verified Phone Number")
    ]
    PII_FIELDS = ['phone_number']

    id = models.AutoField(db_column='grab_customer_data_id', primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id',
                                 blank=True,
                                 null=True)
    phone_number = models.CharField(max_length=16)
    grab_validation_status = models.BooleanField(default=False)
    otp_status = models.CharField(max_length=15, choices=OTP_STATUS, default=UNVERIFIED)
    token = models.TextField(blank=True, null=True, db_index=True)
    otp_last_failure_time = models.DateTimeField(null=True, blank=True, default=None)
    otp_latest_failure_count = models.IntegerField(default=0)
    device = models.CharField(max_length=125, blank=True, null=True)
    web_browser = models.CharField(max_length=125, blank=True, null=True)
    hashed_phone_number = models.TextField(blank=True, null=True, db_index=True)
    is_customer_blocked_for_loan_creation = models.NullBooleanField()
    phone_number_tokenized = models.TextField(blank=True, null=True)

    objects = GrabCustomerDataPIIVaultManager()

    def __str__(self):
        return str(self.id)

    def is_authenticated(self):
        return True


class GrabLoanInquiryManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabLoanInquiry(TimeStampedModel):
    class Meta(object):
        db_table = 'grab_loan_inquiry'

    id = models.AutoField(db_column='grab_loan_inquiry_id', primary_key=True)
    grab_customer_data = models.ForeignKey(GrabCustomerData, models.DO_NOTHING,
                                           db_column='grab_customer_data_id',
                                           blank=True,
                                           null=True)

    # loan offer data
    program_id = models.CharField(max_length=125)
    max_loan_amount = models.FloatField(blank=True, null=True)
    min_loan_amount = models.FloatField(blank=True, null=True)
    instalment_amount = models.FloatField(blank=True, null=True)
    loan_duration = models.IntegerField(blank=True, null=True)
    frequency_type = models.CharField(max_length=15)
    fee_value = models.FloatField(blank=True, null=True)
    loan_disbursement_amount = models.FloatField(blank=True, null=True)
    interest_type = models.CharField(max_length=30)
    interest_value = models.FloatField(blank=True, null=True)
    penalty_type = models.CharField(max_length=30)
    penalty_value = models.FloatField(blank=True, null=True)

    # repayment data
    amount_plan = models.FloatField(blank=True, null=True)
    tenure_plan = models.IntegerField(blank=True, null=True)
    interest_type_plan = models.CharField(max_length=30)
    interest_value_plan = models.FloatField(blank=True, null=True)
    instalment_amount_plan = models.FloatField(blank=True, null=True)
    fee_type_plan = models.CharField(max_length=30)
    fee_value_plan = models.FloatField(blank=True, null=True)
    total_repayment_amount_plan = models.FloatField(blank=True, null=True)
    weekly_instalment_amount = models.FloatField(blank=True, null=True)

    objects = GrabLoanInquiryManager()

    def __str__(self):
        return str(self.id)


class GrabLoanDataManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabLoanData(TimeStampedModel):
    class Meta(object):
        db_table = 'grab_loan_data'

    id = models.AutoField(db_column='grab_loan_data_id', primary_key=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING,
                             db_column='loan_id',
                             blank=True,
                             null=True)
    grab_loan_inquiry = models.ForeignKey(GrabLoanInquiry, models.DO_NOTHING,
                                          db_column='grab_loan_inquiry_id',
                                          blank=True,
                                          null=True)
    program_id = models.CharField(max_length=125)
    selected_amount = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(20000000)])
    selected_tenure = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(180)])
    selected_fee = models.FloatField(blank=True, null=True)
    selected_interest = models.FloatField(blank=True, null=True)
    selected_instalment_amount = models.FloatField(blank=True, null=True)
    auth_transaction_id = models.TextField(blank=True, null=True)
    auth_called = models.NullBooleanField(blank=True)
    capture_called = models.NullBooleanField(blank=True)
    cancel_called = models.NullBooleanField(blank=True)

    loan_halt_date = models.DateField(blank=True, null=True)
    loan_resume_date = models.DateField(blank=True, null=True)
    is_repayment_capped = models.NullBooleanField()
    is_early_write_off = models.NullBooleanField()
    restructured_date = models.DateTimeField(null=True, blank=True)
    early_write_off_date = models.DateTimeField(null=True, blank=True)
    account_halt_info = JSONField(null=True, blank=True)  # JSON field,
    account_halt_status = models.CharField(
        max_length=50, choices=AccountHaltStatus.CHOICES,
        null=True, blank=True)

    objects = GrabLoanDataManager()

    def __str__(self):
        return str(self.id)


class GrabAPILogManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabAPILog(TimeStampedModel):
    class Meta(object):
        db_table = 'grab_api_log'

    GRAB_API = [
        ("api.grab_account_link", 'Grab Account Link API'),
        ("api.loan_offer", 'Loan Offer API'),
        ("api.repayment_plans", 'Repayment Plan API'),
        ("api.application_creation", 'Application Creation API'),
        ("api.loan_creation", 'Loan Creation API'),
        ("api.pre_disbursal_check", 'Pre Disbursal Check API'),
        ("api.disbursal_creation", 'Disbursal Creation API'),
    ]

    id = models.AutoField(db_column='grab_api_log_id', primary_key=True)
    application_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    loan_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    customer_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    api_type = models.CharField(max_length=50, choices=GRAB_API)
    http_status_code = models.IntegerField(
        validators=[MinValueValidator(100), MaxValueValidator(525)])
    query_params = models.CharField(max_length=255)
    request = models.TextField(null=True, blank=True)
    response = models.TextField()
    error_message = models.CharField(max_length=255)
    grab_customer_data_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    external_error_code = models.CharField(max_length=255, blank=True, null=True)

    objects = GrabAPILogManager()

    def __str__(self):
        return str(self.id)


class GrabPaymentTransaction(TimeStampedModel):
    transaction_id = models.TextField(db_index=True)
    payment = BigForeignKey(
        Payment, models.DO_NOTHING,
        db_column='payment_id',
        blank=True,
        null=True)
    loan = BigForeignKey(
        Loan, models.DO_NOTHING,
        db_column='loan_id',
        blank=True,
        null=True
    )
    payment_amount = models.FloatField()

    class Meta(object):
        db_table = 'grab_payment_transaction'

    def __str__(self):
        return "Grab Transaction id - {}".format(self.pk)


class GrabPaymentDataManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabPaymentData(TimeStampedModel):
    HALT = 'halt'
    RESUME = 'resume'
    description_choices = [
        ('halt', 'loan is halted'),
        ('resume', 'loan is resumed')
    ]

    id = models.AutoField(db_column='grab_payment_data_id', primary_key=True)
    payment_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    loan_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    payment_status_code = models.BigIntegerField(blank=True, null=True, db_index=True)
    payment_number = models.IntegerField()
    due_date = models.DateField(null=True)
    ptp_date = models.DateField(blank=True, null=True)
    ptp_robocall_template_id = models.BigIntegerField(blank=True, null=True, db_index=True,
                                                      db_column='robocall_template_id')
    is_ptp_robocall_active = models.NullBooleanField()
    due_amount = models.BigIntegerField()
    installment_principal = models.BigIntegerField(default=0)
    installment_interest = models.BigIntegerField(default=0)

    paid_date = models.DateField(blank=True, null=True)
    paid_amount = models.BigIntegerField(blank=True, default=0)
    redeemed_cashback = models.BigIntegerField(default=0)
    cashback_earned = models.BigIntegerField(blank=True, default=0)

    late_fee_amount = models.BigIntegerField(blank=True, default=0)
    late_fee_applied = models.IntegerField(blank=True, default=0)
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
    account_payment_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    description = models.CharField(max_length=200, choices=description_choices)

    objects = GrabPaymentDataManager()

    class Meta:
        db_table = 'grab_payment_data'
        managed = False


class GrabPaybackTransaction(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='grab_payback_transaction_id')
    payback_transaction = models.OneToOneField('julo.PaybackTransaction')
    grab_txn_id = models.TextField(blank=True, null=True, db_index=True)
    loan = BigForeignKey(
        'julo.Loan', models.DO_NOTHING, db_column='loan_id')

    class Meta(object):
        db_table = 'grab_payback_transaction'


class GrabTransactions(TimeStampedModel):
    # This Field ie the grab_transaction_id will be the uuid which will be
    # the unique identifier.
    INITITATED = 'initiated'
    IN_PROGRESS = 'in_progress'
    SUCCESS = 'success'
    FAILED = 'failed'
    EXPIRED = 'expired'
    id = models.TextField(primary_key=True, db_column='grab_transaction_id')
    grab_api_log_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    status = models.TextField()
    batch = models.TextField()
    loan_id = models.BigIntegerField(blank=True, null=True, db_index=True)

    class Meta(object):
        db_table = 'grab_transactions'


class GrabProgramFeatureSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabProgramFeatureSetting(TimeStampedModel):
    id = models.AutoField(db_column='grab_program_feature_setting_id', primary_key=True)
    feature_setting = models.ForeignKey(
        'julo.FeatureSetting', models.CASCADE, db_column='feature_setting_id',
        related_name='program_feature_settings')
    program_id = models.ForeignKey(
        'grab.GrabProgramInterest', models.CASCADE, db_column='program_id',
        related_name='program_interests')
    is_active = models.BooleanField(default=True)

    objects = GrabProgramFeatureSettingManager()

    class Meta(object):
        db_table = 'grab_program_feature_setting'


class GrabProgramInterestManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabProgramInterest(TimeStampedModel):
    id = BigAutoField(db_column='grab_program_interest_id', primary_key=True)
    program_id = models.TextField()
    interest = models.FloatField(default=0)

    objects = GrabProgramInterestManager()

    class Meta(object):
        db_table = 'grab_program_interest'
        unique_together = (("program_id", "interest"),)

    def __str__(self):
        """Visual identification"""
        return "{}:{} - {}".format(self.id, self.program_id, self.interest)


class GrabExcludedOldRepaymentLoan(TimeStampedModel):
    """
    Temporary Model to Store the loan_ids which follow the new repayment flow
    Only to be used during rollout
    """
    loan = BigOneToOneField(
        Loan, models.DO_NOTHING, db_column='loan_id', db_index=True, primary_key=True)

    class Meta(object):
        db_table = 'grab_excluded_old_repayment_loan'


class GrabCollectionDialerTemporaryData(TimeStampedModel):

    id = models.AutoField(
        db_column='grab_collection_dialer_temporary_id', primary_key=True)
    customer_id = models.BigIntegerField(blank=True, null=True)
    application_id = models.BigIntegerField(blank=True, null=True)
    nama_customer = models.TextField(blank=True, null=True)
    nama_perusahaan = models.TextField(blank=True, null=True)
    posisi_karyawan = models.TextField(blank=True, null=True)
    nama_pasangan = models.TextField(blank=True, null=True)
    nama_kerabat = models.TextField(blank=True, null=True)
    hubungan_kerabat = models.TextField(blank=True, null=True)
    jenis_kelamin = models.TextField(blank=True, null=True)
    tgl_lahir = models.TextField(blank=True, null=True)
    tgl_gajian = models.TextField(blank=True, null=True)
    tujuan_pinjaman = models.TextField(blank=True, null=True)
    tanggal_jatuh_tempo = models.TextField(blank=True, null=True)
    alamat = models.TextField(blank=True, null=True)
    kota = models.TextField(blank=True, null=True)
    tipe_produk = models.TextField(blank=True, null=True)
    partner_name = models.TextField(blank=True, null=True)
    account_payment_id = models.BigIntegerField(blank=True, null=True)
    sort_order = models.IntegerField(blank=True, null=True)
    dpd = models.IntegerField(blank=True, null=True)
    team = models.TextField(blank=True, null=True)
    payment_id = models.BigIntegerField(blank=True, null=True)
    loan_id = models.BigIntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'grab_collection_dialer_temporary_data'
        managed = False


class GrabSkiptraceHistoryPIIVaultManager(PIIVaultModelManager):
    pass


class GrabSkiptraceHistory(PIIVaultModel):
    PII_FIELDS = [
        'agent_name',
        'spoke_with'
    ]
    PII_TYPE = PIIType.KV
    id = models.AutoField(db_column='grab_skiptrace_history_id', primary_key=True)

    skiptrace = models.ForeignKey('julo.Skiptrace', models.DO_NOTHING,
                                  db_column='skiptrace_id')
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField(blank=True, null=True)
    agent = CurrentUserField(related_name="grab_skiptrace_call_history")
    agent_name = models.TextField(null=True, blank=True)
    spoke_with = models.TextField(null=True, blank=True)
    call_result = models.ForeignKey('julo.SkiptraceResultChoice',
                                    db_column='skiptrace_result_choice_id')
    application = models.ForeignKey('julo.Application', models.DO_NOTHING,
                                    db_column='application_id', null=True, blank=True)
    application_status = models.IntegerField(null=True, blank=True)
    old_application_status = models.IntegerField(null=True, blank=True)
    loan = models.ForeignKey('julo.Loan', models.DO_NOTHING,
                             db_column='loan_id', null=True, blank=True)
    loan_status = models.IntegerField(null=True, blank=True)
    payment = models.ForeignKey('julo.Payment', models.DO_NOTHING,
                                db_column='payment_id', null=True, blank=True)
    payment_status = models.IntegerField(blank=True, null=True)

    objects = SkiptraceHistoryManager()
    notes = models.TextField(null=True, blank=True)
    callback_time = models.CharField(max_length=12, blank=True, null=True)
    excluded_from_bucket = models.NullBooleanField()
    non_payment_reason = models.TextField(null=True, blank=True)
    status_group = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    account_payment_status = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, null=True, blank=True)
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    caller_id = models.TextField(null=True, blank=True)
    dialer_task = models.ForeignKey('minisquad.DialerTask', models.DO_NOTHING,
                                    db_column='dialer_task_id', null=True, blank=True)
    source = models.TextField(null=True, blank=True)
    unique_call_id = models.TextField(null=True, blank=True)
    is_fraud_colls = models.BooleanField(default=False)
    external_unique_identifier = models.CharField(max_length=200, blank=True, null=True, unique=True, db_index=True)
    external_task_identifier = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    agent_name_tokenized = models.TextField(null=True, blank=True)
    spoke_with_tokenized = models.TextField(null=True, blank=True)

    objects = GrabSkiptraceHistoryPIIVaultManager()

    class Meta(object):
        db_table = 'grab_skiptrace_history'


class GrabReferralWhitelistProgram(TimeStampedModel):
    id = models.AutoField(db_column='grab_referral_whitelist_program_id', primary_key=True)
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'grab_referral_whitelist_program'

    def save(self, *args, **kwargs):
        if self.is_active:
            qs = type(self).objects.filter(is_active=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            qs.update(is_active=False)
        super(GrabReferralWhitelistProgram, self).save(*args, **kwargs)


class GrabCustomerReferralWhitelistHistory(TimeStampedModel):
    id = models.AutoField(db_column='grab_customer_referral_whitelist_history_id', primary_key=True)
    grab_referral_whitelist_program = models.ForeignKey(
        'grab.GrabReferralWhitelistProgram', models.DO_NOTHING,
        db_column='grab_referral_whitelist_program_id', null=True, blank=True
    )
    customer = models.ForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id')

    class Meta(object):
        db_table = 'grab_customer_referral_whitelist_history'


class GrabConstructedCollectionDialerTemporaryData(TimeStampedModel):
    id = models.AutoField(db_column='grab_construct_collection_id', primary_key=True)
    application_id = models.BigIntegerField(blank=True, null=True)
    customer_id = models.BigIntegerField(blank=True, null=True)
    nama_customer = models.TextField(blank=True, null=True)
    nama_perusahaan = models.TextField(blank=True, null=True)
    posisi_karyawan = models.TextField(blank=True, null=True)
    nama_pasangan = models.TextField(blank=True, null=True)
    nama_kerabat = models.TextField(blank=True, null=True)
    hubungan_kerabat = models.TextField(blank=True, null=True)
    jenis_kelamin = models.TextField(blank=True, null=True)
    tgl_lahir = models.TextField(blank=True, null=True)
    tgl_gajian = models.TextField(blank=True, null=True)
    tujuan_pinjaman = models.TextField(blank=True, null=True)
    tanggal_jatuh_tempo = models.TextField(blank=True, null=True)
    alamat = models.TextField(blank=True, null=True)
    kota = models.TextField(blank=True, null=True)
    tipe_produk = models.TextField(blank=True, null=True)
    partner_name = models.TextField(blank=True, null=True)
    account_payment_id = models.BigIntegerField(blank=True, null=True)
    sort_order = models.IntegerField(blank=True, null=True)
    dpd = models.IntegerField(blank=True, null=True)
    team = models.TextField(blank=True, null=True)
    payment_id = models.BigIntegerField(blank=True, null=True)
    loan_id = models.BigIntegerField(blank=True, null=True)
    mobile_phone_1 = models.TextField(blank=True, null=True)
    mobile_phone_2 = models.TextField(blank=True, null=True)
    telp_perusahaan = models.TextField(blank=True, null=True)
    angsuran = models.IntegerField(blank=True, null=True)
    denda = models.IntegerField(blank=True, null=True)
    outstanding = models.BigIntegerField(blank=True, null=True)
    angsuran_ke = models.TextField(blank=True, null=True)
    no_telp_pasangan = models.TextField(blank=True, null=True)
    no_telp_kerabat = models.TextField(blank=True, null=True)
    tgl_upload = models.TextField(blank=True, null=True)
    va_bca = models.TextField(blank=True, null=True)
    va_permata = models.TextField(blank=True, null=True)
    va_maybank = models.TextField(blank=True, null=True)
    va_alfamart = models.TextField(blank=True, null=True)
    va_indomaret = models.TextField(blank=True, null=True)
    campaign = models.TextField(blank=True, null=True)
    jumlah_pinjaman = models.BigIntegerField(blank=True, null=True)
    tenor = models.TextField(blank=True, null=True)
    last_agent = models.TextField(blank=True, null=True)
    last_call_status = models.TextField(blank=True, null=True)
    customer_bucket_type = models.TextField(blank=True, null=True)
    zip_code = models.TextField(blank=True, null=True)
    disbursement_period = models.TextField(blank=True, null=True)
    repeat_or_first_time = models.TextField(blank=True, null=True)
    account_id = models.BigIntegerField(blank=True, null=True)
    is_j1 = models.NullBooleanField()
    Autodebit = models.TextField(blank=True, null=True)
    refinancing_status = models.TextField(blank=True, null=True)
    activation_amount = models.TextField(blank=True, null=True)
    program_expiry_date = models.TextField(blank=True, null=True)
    promo_untuk_customer = models.TextField(blank=True, null=True)
    last_pay_date = models.TextField(blank=True, null=True)
    last_pay_amount = models.BigIntegerField(blank=True, null=True)
    status_tagihan = JSONField(null=True, blank=True)  # JSON field,

    class Meta(object):
        db_table = 'grab_constructed_collection_dialer'
        managed = False


class GrabTask(TimeStampedModel):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    IN_PROGRESS = "IN_PROGRESS"

    TASK_STATUS = [
        (SUCCESS, "Success"),
        (FAILED, "Failed"),
        (IN_PROGRESS, "In Progress")
    ]
    id = models.AutoField(db_column='grab_task_status_id', primary_key=True)
    task_id = models.TextField(blank=True, null=True)
    task_type = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=15, choices=TASK_STATUS, default=IN_PROGRESS)
    return_value = models.TextField(blank=True, null=True)
    params = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'grab_task_status'


class ReferralCodeUpperCaseField(models.TextField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        if value:
            return str(value).upper()
        return value


class GrabReferralCode(TimeStampedModel):
    id = models.AutoField(db_column='grab_referral_code_id', primary_key=True)
    application = BigOneToOneField(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    referral_code = ReferralCodeUpperCaseField(db_index=True)
    referred_customer = BigForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='referred_customer_id')

    class Meta(object):
        db_table = 'grab_referral_code'


class GrabIntelixCScore(TimeStampedModel):
    id = models.AutoField(db_column='grab_intelix_c_score_id', primary_key=True)
    loan_xid = models.BigIntegerField(blank=True, null=True)
    grab_user_id = models.TextField(blank=True, null=True)
    vehicle_type = models.TextField(blank=True, null=True)
    cscore = models.IntegerField()
    prediction_date = models.DateField(null=True, blank=True)
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id',
                                 null=True, blank=True)
    dpd = models.IntegerField(null=True, blank=True)
    outstanding_amount = models.FloatField(null=True, blank=True)
    oldest_unpaid_payment_id = models.BigIntegerField(null=True, blank=True)
    class Meta(object):
        db_table = 'grab_intelix_c_score'


class GrabAsyncAuditCron(TimeStampedModel):
    INITIATED = 'initiated'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    LOANS = 'loans'
    DAILY_TRANSACTIONS = 'daily_transactions'

    CRON_STATUS = [
        (INITIATED, 'INITIATED'),
        (IN_PROGRESS, 'IN_PROGRESS'),
        (COMPLETED, 'COMPLETED'),
        (FAILED, 'FAILED')
    ]

    FILE_TYPE = [
        (LOANS, 'loans'),
        (DAILY_TRANSACTIONS, 'daily_transactions'),
    ]
    id = models.AutoField(primary_key=True, db_column='grab_async_audit_cron_id')
    event_date = models.DateField()
    cron_file_type = models.CharField(max_length=20, choices=FILE_TYPE, default=LOANS)
    cron_file_name = models.TextField()
    cron_status = models.CharField(max_length=15, choices=CRON_STATUS)
    file_uploaded_to_oss = models.BooleanField(default=False)
    oss_remote_path = models.TextField(null=True, blank=True)
    cron_start_time = models.DateTimeField(null=True, blank=True)
    cron_end_time = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = 'grab_async_audit_cron'

    def __str__(self):
        return "Grab Audit Cron task - {}, Remote Path - {}".format(
            self.cron_file_name,
            self.oss_remote_path
        )


class PaymentGatewayVendorManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayVendor(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='payment_gateway_vendor_id')
    name = models.CharField(max_length=150, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    objects = PaymentGatewayVendorManager()

    class Meta(object):
        db_table = 'payment_gateway_vendor'


class PaymentGatewayCustomerDataManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayCustomerData(PIIVaultModel):
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    id = BigAutoField(primary_key=True, db_column='payment_gateway_customer_data_id')
    customer_id = models.BigIntegerField()
    phone_number = models.CharField(max_length=25, null=True, blank=True)
    payment_gateway_vendor = models.ForeignKey(
        PaymentGatewayVendor,
        models.DO_NOTHING,
        db_column='payment_gateway_vendor_id'
    )
    beneficiary_id = models.TextField(null=True, blank=True)
    account_number = models.CharField(max_length=50, null=True, blank=True)
    bank_code = models.CharField(max_length=50, null=True, blank=True)
    account_type = models.CharField(max_length=50, null=True, blank=True)
    status = models.IntegerField(null=True, blank=True)
    external_customer_id = models.CharField(max_length=50, null=True, blank=True)
    phone_number_tokenized = models.CharField(max_length=225, null=True, blank=True)
    beneficiary_request_retry_limit = models.IntegerField(null=True, blank=True)
    
    objects = PaymentGatewayCustomerDataManager()

    class Meta(object):
        db_table = 'payment_gateway_customer_data'


class PaymentGatewayCustomerDataHistoryManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayCustomerDataHistory(PIIVaultModel):
    PII_FIELDS = [
        'old_phone_number',
        'new_phone_number'
    ]
    PII_TYPE = PIIType.KV
    id = BigAutoField(primary_key=True, db_column='payment_gateway_customer_data_history_id')
    payment_gateway_customer_data = models.ForeignKey(
        PaymentGatewayCustomerData,
        models.DO_NOTHING,
        db_column='payment_gateway_customer_data_id'
    )
    old_beneficiary_id = models.CharField(max_length=50, null=True, blank=True)
    new_beneficiary_id = models.CharField(max_length=50, null=True, blank=True)
    old_account_number = models.CharField(max_length=50, null=True, blank=True)
    new_account_number = models.CharField(max_length=50, null=True, blank=True)
    old_bank_code = models.CharField(max_length=50, blank=True, null=True)
    new_bank_code = models.CharField(max_length=50, blank=True, null=True)
    old_status = models.IntegerField(null=True, blank=True)
    new_status = models.IntegerField(null=True, blank=True)
    old_phone_number = models.CharField(max_length=25, null=True, blank=True)
    new_phone_number = models.CharField(max_length=25, null=True, blank=True)
    old_external_customer_id = models.CharField(max_length=50, null=True, blank=True)
    new_external_customer_id = models.CharField(max_length=50, null=True, blank=True)
    new_phone_number_tokenized = models.CharField(max_length=225, null=True, blank=True)
    old_phone_number_tokenized = models.CharField(max_length=225, null=True, blank=True)
    objects = PaymentGatewayCustomerDataHistoryManager()

    class Meta(object):
        db_table = 'payment_gateway_customer_data_history'
        managed = False


class PaymentGatewayApiLogManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayApiLog(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='payment_gateway_api_log_id')
    customer_id = models.BigIntegerField()
    application_id = models.BigIntegerField()
    beneficiary_id = models.TextField(null=True, blank=True)
    request_data = models.TextField(null=True, blank=True)
    response = JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=25, null=True, blank=True)
    http_status_code = models.CharField(max_length=25, null=True, blank=True)

    api_url = models.CharField(max_length=100, null=True, blank=True)
    correlation_id = models.CharField(max_length=50, blank=True, null=True)
    transaction_id = models.CharField(max_length=50, blank=True, null=True)
    payment_gateway_vendor = models.ForeignKey(
        PaymentGatewayVendor,
        models.DO_NOTHING,
        db_column='payment_gateway_vendor_id',
        blank=True,
        null=True
    )
    objects = PaymentGatewayApiLogManager()

    class Meta(object):
        db_table = 'payment_gateway_api_log'


class PaymentGatewayBankManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayBankCode(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='payment_gateway_bank_code_id')
    payment_gateway_vendor = models.ForeignKey(
        PaymentGatewayVendor,
        models.DO_NOTHING,
        db_column='payment_gateway_vendor_id'
    )
    bank_id = models.BigIntegerField()
    swift_bank_code = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    objects = PaymentGatewayBankManager()

    class Meta(object):
        db_table = 'payment_gateway_bank_code'


class PaymentGatewayLogIdentifierManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayLogIdentifier(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='payment_gateway_identifier_id')
    payment_gateway_api_log = models.OneToOneField(
        PaymentGatewayApiLog, models.DO_NOTHING, db_column='payment_gateway_api_log_id'
    )
    identifier = models.CharField(max_length=200)
    query_param = models.TextField()
    is_active = models.BooleanField(default=True)
    objects = PaymentGatewayLogIdentifierManager()

    class Meta(object):
        db_table = 'payment_gateway_log_identifier'


class PaymentGatewayApiLogArchivalManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayApiLogArchival(models.Model):
    id = BigAutoField(primary_key=True, db_column='payment_gateway_api_log_archival_id')
    customer_id = models.BigIntegerField()
    application_id = models.BigIntegerField()
    beneficiary_id = models.TextField(null=True, blank=True)
    request_data = models.TextField(null=True, blank=True)
    response = JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=25, null=True, blank=True)
    http_status_code = models.CharField(max_length=25, null=True, blank=True)

    api_url = models.CharField(max_length=100, null=True, blank=True)
    correlation_id = models.CharField(max_length=50, blank=True, null=True)
    transaction_id = models.CharField(max_length=50, blank=True, null=True)
    payment_gateway_vendor = models.ForeignKey(
        PaymentGatewayVendor,
        models.DO_NOTHING,
        db_column='payment_gateway_vendor_id',
        blank=True,
        null=True
    )
    objects = PaymentGatewayApiLogArchivalManager()
    cdate = models.DateTimeField()
    udate = models.DateTimeField()

    class Meta(object):
        db_table = 'payment_gateway_api_log_archival'


class GrabLoanOffer(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='grab_loan_offer_id')
    grab_customer_data = models.ForeignKey(GrabCustomerData, models.DO_NOTHING,
                                        db_column='grab_customer_data_id',
                                        blank=True,
                                        null=True)
    program_id = models.CharField(max_length=125, db_index=True)
    max_loan_amount = models.FloatField(blank=True, null=True)
    min_loan_amount = models.FloatField(blank=True, null=True)
    weekly_installment_amount = models.FloatField(blank=True, null=True)
    tenure = models.IntegerField(blank=True, null=True)
    min_tenure = models.IntegerField(blank=True, null=True)
    tenure_interval = models.IntegerField(blank=True, null=True)
    fee_type = models.CharField(max_length=30)
    fee_value = models.FloatField(blank=True, null=True)
    interest_type = models.CharField(max_length=30)
    interest_value = models.FloatField(blank=True, null=True)
    penalty_type = models.CharField(max_length=30)
    penalty_value = models.FloatField(blank=True, null=True)
    frequency_type = models.CharField(max_length=15)

    class Meta(object):
        db_table = 'grab_loan_offer'
        unique_together = ('grab_customer_data', "program_id", )
        managed = False


class GrabLoanOfferArchival(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='grab_loan_offer_id')
    grab_customer_data = models.ForeignKey(GrabCustomerData, models.DO_NOTHING,
                                        db_column='grab_customer_data_id',
                                        blank=True,
                                        null=True)
    program_id = models.CharField(max_length=125, db_index=True)
    max_loan_amount = models.FloatField(blank=True, null=True)
    min_loan_amount = models.FloatField(blank=True, null=True)
    weekly_installment_amount = models.FloatField(blank=True, null=True)
    tenure = models.IntegerField(blank=True, null=True)
    min_tenure = models.IntegerField(blank=True, null=True)
    tenure_interval = models.IntegerField(blank=True, null=True)
    fee_type = models.CharField(max_length=30)
    fee_value = models.FloatField(blank=True, null=True)
    interest_type = models.CharField(max_length=30)
    interest_value = models.FloatField(blank=True, null=True)
    penalty_type = models.CharField(max_length=30)
    penalty_value = models.FloatField(blank=True, null=True)
    frequency_type = models.CharField(max_length=15)

    class Meta(object):
        db_table = 'grab_loan_offer_archival'
        managed = False


class GrabExperimentManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabExperiment(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='grab_experiment_id')
    experiment_name = models.TextField(blank=True, null=True)
    grab_customer_data = models.ForeignKey(GrabCustomerData, models.DO_NOTHING,
                                           db_column='grab_customer_data_id', blank=True, null=True)
    grab_loan_data = models.ForeignKey(GrabLoanData, models.DO_NOTHING,
                                       db_column='grab_loan_data_id', blank=True, null=True)
    parameters = JSONField(default={})
    is_active = models.BooleanField(default=True)
    objects = GrabExperimentManager()

    class Meta(object):
        db_table = 'grab_experiment'


class GrabCallLogPocAiRudderPdsPIIVaultManager(PIIVaultModelManager):
    pass


class GrabCallLogPocAiRudderPds(PIIVaultModel):
    PII_FIELDS = [
        'phone_number',
        'contact_name',
        'main_number'
    ]
    PII_TYPE = PIIType.KV
    id = BigAutoField(db_column='grab_call_log_poc_airudder_pds_id', primary_key=True)

    grab_skiptrace_history_id = models.BigIntegerField(blank=True, null=True, db_index=True)

    call_log_type = models.CharField(max_length=100, blank=True, null=True)
    task_id = models.CharField(max_length=200, blank=True, null=True)
    task_name = models.CharField(max_length=200, blank=True, null=True)
    group_name = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    phone_number = models.CharField(max_length=30, blank=True, null=True)
    call_id = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    contact_name = models.CharField(max_length=200, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    info_1 = models.TextField(blank=True, null=True)
    info_2 = models.TextField(blank=True, null=True)
    info_3 = models.TextField(blank=True, null=True)
    remark = models.TextField(blank=True, null=True)
    main_number = models.CharField(max_length=30, blank=True, null=True)
    phone_tag = models.CharField(max_length=100, blank=True, null=True)
    private_data = models.CharField(max_length=200, blank=True, null=True)
    hangup_reason = models.IntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(blank=True, null=True)
    recording_link = models.TextField(blank=True, null=True)
    nth_call = models.IntegerField(blank=True, null=True)
    talk_remarks = models.TextField(blank=True, null=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)
    main_number_tokenized = models.TextField(null=True, blank=True)
    contact_name_tokenized = models.TextField(null=True, blank=True)

    objects = GrabCallLogPocAiRudderPdsPIIVaultManager()

    class Meta(object):
        db_table = 'grab_call_log_poc_airudder_pds'
        managed = False


class GrabHangupReasonPDS(TimeStampedModel):
    id = BigAutoField(
        db_column='grab_hangup_reason_pds_id', primary_key=True)
    grab_skiptrace_history = models.ForeignKey(
        'grab.GrabSkiptraceHistory',
        models.DO_NOTHING,
        db_column='grab_skiptrace_history_id',
        blank=True,
        null=True
    )
    hangup_reason = models.IntegerField(db_column='hangup_reason_id')
    reason = models.TextField()

    class Meta(object):
        db_table = 'grab_hangup_reason_pds'


class PaymentGatewayTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentGatewayTransaction(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='payment_gateway_transaction_id')
    disbursement_id = models.BigIntegerField()
    correlation_id = models.CharField(max_length=50, blank=True, null=True)
    transaction_id = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=25, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    payment_gateway_vendor = models.ForeignKey(
        PaymentGatewayVendor,
        models.DO_NOTHING,
        db_column='payment_gateway_vendor_id',
        blank=True,
        null=True
    )
    objects = PaymentGatewayTransactionManager()

    class Meta(object):
        db_table = 'payment_gateway_transaction'


class GrabTempAccountDataManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabTempAccountData(TimeStampedModel):
    class Meta(object):
        db_table = 'grab_temp_account_data'

    id = models.AutoField(db_column='grab_temp_account_data_id', primary_key=True)
    account_id = models.BigIntegerField(blank=False, null=False)
    objects = GrabTempAccountDataManager()

    class Meta(object):
        db_table = 'grab_temp_account_data'
        index_together = [('account_id', 'cdate')]

    def __str__(self):
        return str(self.id)


class GrabMisCallOTPTracker(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='grab_miscall_otp_tracker_id')
    miscall_otp = BigForeignKey('otp.MisCallOTP', models.DO_NOTHING, db_column='miscall_otp_id')
    otp_request = BigForeignKey('julo.OtpRequest', models.DO_NOTHING, db_column='otp_request_id')

    class Meta(object):
        db_table = 'grab_miscall_otp_tracker'


class GrabPromoCodeManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabPromoCode(TimeStampedModel):
    NEW_USER = 1
    EXISTING_USER_WITH_OUTSTANDING = 2
    EXISTING_USER_WITHOUT_OUTSTANDING = 3

    USER_RULE_CHOICES = [
        (NEW_USER, 'New User'),
        (EXISTING_USER_WITH_OUTSTANDING, 'Existing User With Outstanding'),
        (EXISTING_USER_WITHOUT_OUTSTANDING, 'Existing User Without Outstanding'),
    ]

    promo_code = models.CharField(max_length=50, db_index=True, primary_key=True)
    title = models.CharField(null=True, blank=True, max_length=75)
    description = models.TextField(null=True, blank=True)
    active_date = models.DateField()
    expire_date = models.DateField()
    image_url = models.TextField(null=True, blank=True)
    rule = ArrayField(
        models.IntegerField(choices=USER_RULE_CHOICES),
        null=True,
        blank=True
    )
    blog_url = models.TextField(null=True, blank=True)
    objects = GrabPromoCodeManager()

    class Meta(object):
        db_table = 'grab_promo_code'

    def __str__(self):
        return str(self.promo_code)


class GrabLoanPromoCodeManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabLoanPromoCode(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='grab_loan_promo_code_id')
    promo_code = models.ForeignKey(GrabPromoCode, models.DO_NOTHING,
                                   db_column='promo_code',
                                   db_index=True)
    loan_id = models.CharField(max_length=20, null=True, blank=True)
    grab_loan_data_id = models.CharField(max_length=25, null=True, blank=True)
    status = models.CharField(max_length=25, choices=PromoCodeStatus.CHOICES,
                              default=PromoCodeStatus.INITIATED)
    objects = GrabLoanPromoCodeManager()

    class Meta(object):
        db_table = 'grab_loan_promo_code'


class GrabExperimentGroupModelManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabExperimentGroup(TimeStampedModel):
    id = BigAutoField(db_column='grab_experiment_group_id', primary_key=True)
    experiment_setting_id = models.BigIntegerField()
    grab_customer_data_id = models.BigIntegerField()
    application_id = models.BigIntegerField(blank=True, null=True)
    group = models.TextField(blank=True, null=True)
    segment = models.TextField(blank=True, null=True)
    payment_id = models.BigIntegerField(blank=True, null=True)
    is_failsafe = models.NullBooleanField(null=True, default=None)
    source = models.TextField(null=True, blank=True, default=None)

    objects = GrabExperimentGroupModelManager()

    class Meta(object):
        db_table = 'grab_experiment_group'


class GrabPaymentPlansManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabPaymentPlans(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='grab_payment_plans_id')
    grab_customer_data_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    program_id = models.CharField(max_length=125)
    payment_plans = models.TextField(blank=True, null=True)
    objects = GrabPaymentPlansManager()

    class Meta(object):
        index_together = [('grab_customer_data_id', 'program_id')]
        db_table = 'grab_payment_plans'


class GrabTempLoanNoCscore(TimeStampedModel):
    id = BigAutoField(db_column='grab_temp_loan_no_cscore_id', primary_key=True)
    loan_id = models.BigIntegerField(blank=True, null=True, unique=True)
    loan_xid = models.BigIntegerField(blank=True, null=True)
    grab_user_id = models.TextField(blank=True, null=True)
    customer_id = models.BigIntegerField(blank=True, null=True)
    dpd = models.IntegerField(null=True, blank=True)
    outstanding_amount = models.FloatField(null=True, blank=True)
    oldest_unpaid_payment_id = models.BigIntegerField(null=True, blank=True)
    class Meta(object):
        db_table = 'grab_temp_loan_no_cscore'
        managed = False


class EmergencyContactApprovalLinkManager(GetInstanceMixin, JuloModelManager):
    pass


class EmergencyContactApprovalLink(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='emergency_contact_approval_link_id')
    application_id = models.BigIntegerField(blank=True, null=True, default=None)
    unique_link = models.CharField(max_length=128, unique=True, db_index=True)
    expiration_date = models.DateTimeField(blank=True, null=True)
    is_used = models.NullBooleanField()

    objects = EmergencyContactApprovalLinkManager()

    class Meta(object):
        db_table = 'emergency_contact_approval_link'


class GrabFeatureSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class GrabFeatureSetting(TimeStampedModel):
    id = BigAutoField(db_column='grab_feature_setting_id', primary_key=True)
    feature_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)
    parameters = JSONField(blank=True, null=True)
    category = models.CharField(max_length=100)
    description = models.CharField(max_length=200)

    objects = GrabFeatureSettingManager()

    class Meta(object):
        db_table = 'grab_feature_setting'

    @classmethod
    def fetch_feature_state(cls, feature_name: str):
        return cls.objects.get(feature_name=feature_name).is_active

    def __str__(self):
        return self.feature_name


class GrabMasterLock(TimeStampedModel):
    id = BigAutoField(db_column='grab_master_lock_id', primary_key=True)
    customer_id = models.BigIntegerField(blank=True, null=True)
    application_id = models.BigIntegerField(blank=True, null=True)
    expire_ts = models.DateTimeField()
    lock_reason = models.TextField(blank=True, null=True)
    last_updated = models.DateTimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'grab_master_lock'
        managed = False


class GrabRestructreHistoryLog(TimeStampedModel):
    id = BigAutoField(db_column='grab_restructure_history_log_id', primary_key=True)
    loan_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    is_restructured = models.NullBooleanField()
    restructure_date = models.DateTimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'grab_restructure_history_log'
        managed = False


class FDCCheckManualApproval(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='fdc_check_manual_approval_id')
    application_id = models.BigIntegerField(blank=True, null=True)
    status = models.CharField(max_length=25, choices=ApplicationStatus.CHOICES)

    class Meta:
        db_table = 'fdc_check_manual_approval'
        managed = False
