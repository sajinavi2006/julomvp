import uuid

from cuser.fields import CurrentUserField
from django.core.validators import RegexValidator
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

from juloserver.account.models import Account
from juloserver.dana.constants import (
    RepaymentReferenceStatus,
    PaymentReferenceStatus,
    DanaReferenceStatus,
    DanaFDCResultStatus,
    DanaFDCStatusSentRequest,
    DanaAccountInfoStatus,
    DanaProductType,
)
from juloserver.julo.models import (
    Application,
    Customer,
    Loan,
    Payment,
    ascii_validator,
    UploadAsyncState,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigOneToOneField,
    BigForeignKey,
    BigAutoField,
)
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.pii_vault.models import PIIVaultModelManager, PIIVaultModel


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class DanaCustomerDataManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaCustomerDataPIIVaultManager(PIIVaultModelManager, DanaCustomerDataManager):
    pass


class DanaCustomerData(PIIVaultModel):
    """
    This model represents a customer Dana
    This model will stored all of information user when Dana send a payload contains user data
    Also mapping all information to Julo Customer and Application Data
    Created When:
    - /v1.0/registration-account-creation called on serializer.save()

    Update When:
    - generate_dana_credit_limit() when application status change from 105 to 130
    """

    PII_FIELDS = ['mobile_number', 'nik', 'full_name']
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = BigAutoField(db_column='dana_customer_id', primary_key=True)
    dana_customer_identifier = models.TextField(
        help_text="This customerId payload from Dana",
    )
    partner = BigForeignKey(
        'julo.Partner',
        models.DO_NOTHING,
        db_column='partner_id',
        related_name='dana_customers_data',
    )
    customer = BigOneToOneField(
        'julo.Customer',
        models.DO_NOTHING,
        db_column='customer_id',
        related_name='dana_customer_data',
        blank=True,
        null=True,
    )
    application = BigOneToOneField(
        Application,
        models.DO_NOTHING,
        related_name='dana_customer_data',
        db_column='application_id',
        blank=True,
        null=True,
    )
    account = BigOneToOneField(
        Account,
        models.DO_NOTHING,
        related_name='dana_customer_data',
        db_column='account_id',
        blank=True,
        null=True,
    )
    mobile_number = models.CharField(max_length=16)
    nik = models.CharField(
        max_length=16,
        help_text="This cardId payload from Dana",
        validators=[
            ascii_validator,
            RegexValidator(regex='^[0-9]{16}$', message='KTP has to be 16 numeric digits'),
        ],
    )
    full_name = models.CharField(max_length=255, help_text="This cardName payload from Dana")
    dob = models.DateField(default="1990-01-01")
    address = models.TextField(default="")
    proposed_credit_limit = models.FloatField()
    registration_time = models.DateTimeField()
    selfie_image_url = models.TextField()
    ktp_image_url = models.TextField()
    credit_score = models.IntegerField(blank=True, null=True)
    lender_product_id = models.CharField(max_length=255, blank=True, null=True)
    app_id = models.CharField(max_length=255, blank=True, null=True)
    income = models.CharField(max_length=255, blank=True, null=True)
    pob = models.CharField(max_length=64, blank=True, null=True)
    gender = models.CharField(max_length=64, blank=True, null=True)
    city_home_address = models.CharField(max_length=64, blank=True, null=True)
    province_home_address = models.CharField(max_length=64, blank=True, null=True)
    postal_code_home_address = models.CharField(max_length=64, blank=True, null=True)
    occupation = models.CharField(max_length=64, blank=True, null=True)
    source_of_income = models.CharField(max_length=64, blank=True, null=True)
    domicile_address = models.TextField(blank=True, null=True)
    marriage_status = models.CharField(max_length=16, blank=True, null=True)
    house_ownership = models.CharField(max_length=64, blank=True, null=True)
    educational_level = models.CharField(max_length=64, blank=True, null=True)
    full_name_tokenized = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    mobile_number_tokenized = models.TextField(blank=True, null=True)
    dialer_vendor = models.CharField(max_length=75, blank=True, null=True)
    first_date_91_plus_assignment = models.DateTimeField(blank=True, null=True)

    objects = DanaCustomerDataPIIVaultManager()

    class Meta(object):
        db_table = 'dana_customer_data'
        unique_together = ('dana_customer_identifier', 'lender_product_id')

    def __str__(self) -> str:
        return self.full_name

    @property
    def is_cash_loan(self):
        return self.lender_product_id == DanaProductType.CASH_LOAN

    @property
    def is_cicil(self):
        return self.lender_product_id == DanaProductType.CICIL


class DanaApplicationReferenceManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaApplicationReference(TimeStampedModel):
    """
    This Model represents indentifier for mapping all created data,
    from application to customer dana Identifer
    This table will create if request to create user is success
    The idenifier is:
    - partner_reference_no = Identifier user from Dana
    - reference_no = Identifier user from JULO

    Created When:
    - /v1.0/registration-account-creation called on function create_dana_user()
    """

    id = BigAutoField(db_column='dana_application_reference_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True, unique=True)
    partner_reference_no = models.TextField(
        unique=True, help_text="This partnerReferenceNo from Dana", db_index=True
    )
    reference_no = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    creditor_check_status = models.CharField(max_length=255, blank=True, null=True)

    objects = DanaApplicationReferenceManager()

    class Meta(object):
        db_table = 'dana_application_reference'
        managed = False

    def __str__(self) -> str:
        return self.partner_reference_no


class DanaLoanReference(TimeStampedModel):
    id = BigAutoField(db_column='dana_loan_reference_id', primary_key=True)
    loan = BigOneToOneField(
        Loan,
        models.DO_NOTHING,
        db_column='loan_id',
        blank=True,
        null=True,
    )
    partner_reference_no = models.TextField(
        unique=True, help_text="This partnerReferenceNo from Dana", db_index=True
    )
    reference_no = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    original_order_amount = models.BigIntegerField(default=None, null=True)
    trans_time = models.DateTimeField(blank=True, null=True)
    customer_id = models.CharField(max_length=255, blank=True, null=True)
    order_info = models.TextField(blank=True, null=True)
    lender_product_id = models.CharField(max_length=255, blank=True, null=True)
    merchant_id = models.CharField(max_length=255, blank=True, null=True)
    credit_usage_mutation = models.BigIntegerField(blank=True, null=True)
    amount = models.BigIntegerField(blank=True, null=True)
    partner_email = models.CharField(max_length=255, blank=True, null=True)
    partner_tnc = models.CharField(max_length=255, blank=True, null=True)
    partner_privacy_rule = models.CharField(max_length=255, blank=True, null=True)
    provision_fee_amount = models.BigIntegerField(blank=True, null=True)
    late_fee_rate = models.FloatField(blank=True, null=True)
    max_late_fee_days = models.IntegerField(blank=True, null=True)
    bill_detail = JSONField(blank=True, null=True)
    repayment_plan_list = JSONField(blank=True, null=True)
    application_id = models.BigIntegerField(null=True, blank=True)
    loan_amount = models.BigIntegerField(blank=True, null=True)
    loan_duration = models.IntegerField(blank=True, null=True)
    installment_amount = models.BigIntegerField(blank=True, null=True)
    is_whitelisted = models.NullBooleanField(blank=True)
    # We add bill_detail_self to save our own calculation on Payment Consult
    bill_detail_self = JSONField(blank=True, null=True, help_text="backup bill_detail")
    interest_rate = models.FloatField(blank=True, null=True)
    payment_id = models.CharField(
        max_length=255, null=True, blank=True, help_text="additional payment identifier"
    )
    disbursement_method = models.CharField(max_length=255, blank=True, null=True)
    beneficiary_account_number = models.CharField(
        max_length=100,
        validators=[
            RegexValidator(regex='^[0-9]+$', message='Virtual account has to be numeric digits')
        ],
        blank=True,
        null=True,
    )
    beneficiary_account_name = models.CharField(max_length=255, blank=True, null=True)
    beneficiary_bank_code = models.CharField(max_length=255, blank=True, null=True)
    beneficiary_bank_name = models.CharField(max_length=255, blank=True, null=True)
    installment_config = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'dana_loan_reference'

    def __str__(self) -> str:
        return "loan_{}".format(self.partner_reference_no)


class DanaPaymentBill(TimeStampedModel):
    id = BigAutoField(db_column='dana_payment_bill_id', primary_key=True)
    bill_id = models.CharField(max_length=64, unique=True, db_index=True)
    principal_amount = models.BigIntegerField()
    interest_fee_amount = models.BigIntegerField()
    late_fee_amount = models.BigIntegerField(default=0)
    total_amount = models.BigIntegerField()
    due_date = models.DateField()
    payment_id = models.BigIntegerField()
    deposit_deducted = models.NullBooleanField(blank=True)
    deducted_date = models.DateField(null=True, blank=True)
    waived_principal_amount = models.BigIntegerField(blank=True, null=True)
    waived_interest_fee_amount = models.BigIntegerField(blank=True, null=True)
    waived_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    total_waived_amount = models.BigIntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'dana_payment_bill'
        managed = False

    def __str__(self) -> str:
        return "{}_{}".format(self.bill_id, self.payment_id)


# collection section
class DanaDialerTemporaryDataModelManager(GetInstanceMixin, JuloModelManager):
    def get_daily_temp_data_per_bucket(self, bucket_name):
        return self.get_queryset().filter(
            team=bucket_name, cdate__date=timezone.localtime(timezone.now()).date()
        )


class DanaDialerTemporaryDataPIIVaultManager(
    PIIVaultModelManager, DanaDialerTemporaryDataModelManager
):
    pass


class DanaDialerTemporaryData(PIIVaultModel):
    PII_FIELDS = ['nama_customer', 'mobile_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    # this model will always flush every day at 8PM and generate it every day at 1AM
    id = models.AutoField(db_column='dana_dialer_temporary_id', primary_key=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )
    customer_id = models.TextField(db_column='customer_id')
    application_id = models.TextField(db_column='application_id')
    sort_order = models.IntegerField(blank=True, null=True)
    dpd = models.IntegerField(blank=True, null=True)
    team = models.TextField(blank=True, null=True)
    nama_customer = models.TextField(blank=True, null=True)
    tanggal_jatuh_tempo = models.TextField(blank=True, null=True)
    mobile_number = models.CharField(max_length=16)
    total_jumlah_pinjaman = models.IntegerField(blank=True, null=True)
    total_denda = models.BigIntegerField(blank=True, null=True)
    total_due_amount = models.BigIntegerField(blank=True, null=True)
    total_outstanding = models.BigIntegerField(blank=True, null=True)
    total_angsuran_per_bulan = models.BigIntegerField(blank=True, null=True)
    metadata = JSONField(blank=True, null=True)
    is_active = models.NullBooleanField()
    nama_customer_tokenized = models.TextField(blank=True, null=True)
    mobile_number_tokenized = models.TextField(blank=True, null=True)
    objects = DanaDialerTemporaryDataPIIVaultManager()

    class Meta(object):
        db_table = 'dana_dialer_temporary_data'


class DanaSkiptraceHistory(TimeStampedModel):
    id = BigAutoField(db_column='dana_skiptrace_history_id', primary_key=True)
    skiptrace = models.ForeignKey('julo.Skiptrace', models.DO_NOTHING, db_column='skiptrace_id')
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField(blank=True, null=True)
    agent = CurrentUserField(related_name="dana_skiptrace_call_history")
    agent_name = models.TextField(null=True, blank=True)
    spoke_with = models.TextField(null=True, blank=True)
    call_result = models.ForeignKey(
        'julo.SkiptraceResultChoice', db_column='skiptrace_result_choice_id'
    )
    application = BigForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', null=True, blank=True
    )
    payment_status = models.IntegerField(blank=True, null=True)
    notes = models.TextField(null=True, blank=True)
    callback_time = models.CharField(max_length=12, blank=True, null=True)
    excluded_from_bucket = models.NullBooleanField()
    non_payment_reason = models.TextField(null=True, blank=True)
    status_group = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    account_payment_status = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, null=True, blank=True
    )
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )
    caller_id = models.TextField(null=True, blank=True)
    dialer_task = models.ForeignKey(
        'minisquad.DialerTask', models.DO_NOTHING, db_column='dialer_task_id', null=True, blank=True
    )
    source = models.TextField(null=True, blank=True)
    unique_call_id = models.TextField(null=True, blank=True)
    is_fraud_colls = models.BooleanField(default=False)
    external_unique_identifier = models.TextField(null=True, blank=True, unique=True, db_index=True)

    class Meta(object):
        db_table = 'dana_skiptrace_history'


class DanaHangupReasonPDS(TimeStampedModel):
    id = models.AutoField(db_column='dana_hangup_reason_pds_id', primary_key=True)
    dana_skiptrace_history_id = models.BigIntegerField()
    hangup_reason = models.IntegerField(db_column='hangup_reason_id')
    reason = models.TextField()

    class Meta(object):
        db_table = 'dana_hangup_reason_pds'
        managed = False


class DanaCallLogPocAiRudderPdsPIIVaultManager(PIIVaultModelManager):
    pass


class DanaCallLogPocAiRudderPds(PIIVaultModel):
    PII_FIELDS = ['phone_number', 'contact_name', 'main_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='dana_call_log_poc_airudder_pds_id', primary_key=True)

    dana_skiptrace_history = BigForeignKey(
        DanaSkiptraceHistory,
        models.DO_NOTHING,
        db_column='dana_skiptrace_history_id',
    )

    call_log_type = models.TextField(blank=True, null=True)
    task_id = models.TextField(blank=True, null=True)
    task_name = models.TextField(blank=True, null=True)
    group_name = models.TextField(blank=True, null=True)
    state = models.TextField(blank=True, null=True)
    phone_number = models.TextField(blank=True, null=True)
    call_id = models.TextField(blank=True, null=True, db_index=True)
    contact_name = models.TextField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    info_1 = models.TextField(blank=True, null=True)
    info_2 = models.TextField(blank=True, null=True)
    info_3 = models.TextField(blank=True, null=True)
    remark = models.TextField(blank=True, null=True)
    main_number = models.TextField(blank=True, null=True)
    phone_tag = models.TextField(blank=True, null=True)
    private_data = models.TextField(blank=True, null=True)
    hangup_reason = models.IntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(blank=True, null=True)
    recording_link = models.TextField(blank=True, null=True)
    nth_call = models.IntegerField(blank=True, null=True)
    talk_remarks = models.TextField(blank=True, null=True)

    phone_number_tokenized = models.TextField(blank=True, null=True)
    contact_name_tokenized = models.TextField(blank=True, null=True)
    main_number_tokenized = models.TextField(blank=True, null=True)

    objects = DanaCallLogPocAiRudderPdsPIIVaultManager()

    class Meta(object):
        db_table = 'dana_call_log_poc_airudder_pds'


# end of collection section


class DanaRepaymentReference(TimeStampedModel):
    id = BigAutoField(db_column='dana_repayment_reference_id', primary_key=True)
    payment = BigForeignKey(
        Payment,
        models.DO_NOTHING,
        db_column='payment_id',
        blank=True,
        null=True,
    )
    partner_reference_no = models.TextField(
        help_text="This partnerReferenceNo from Dana", db_index=True
    )
    reference_no = models.UUIDField(default=uuid.uuid4, editable=False)
    bill_id = models.CharField(max_length=64, blank=True, null=True)
    customer_id = models.CharField(max_length=64, blank=True, null=True)
    bill_status = models.CharField(max_length=64, blank=True, null=True)
    principal_amount = models.BigIntegerField(default=0)
    interest_fee_amount = models.BigIntegerField(default=0)
    late_fee_amount = models.BigIntegerField(default=0)
    total_repayment_amount = models.BigIntegerField(default=0)
    repaid_time = models.DateTimeField(blank=True, null=True)
    credit_usage_mutation = models.BigIntegerField(blank=True, null=True)
    repayment_id = models.TextField(blank=True, null=True)
    lender_product_id = models.CharField(max_length=64, blank=True, null=True)
    waived_principal_amount = models.BigIntegerField(blank=True, null=True)
    waived_interest_fee_amount = models.BigIntegerField(blank=True, null=True)
    waived_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    total_waived_amount = models.BigIntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'dana_repayment_reference'

    def __str__(self) -> str:
        return "repayment_{}".format(self.partner_reference_no)


class DanaRepaymentReferenceHistory(TimeStampedModel):
    id = BigAutoField(db_column='dana_repayment_reference_history_id', primary_key=True)
    repayment_reference = BigForeignKey(
        DanaRepaymentReference,
        models.DO_NOTHING,
        db_column='dana_repayment_reference_id',
        related_name='dana_repayment_reference_history',
    )
    upload_async_state = BigForeignKey(
        UploadAsyncState,
        models.DO_NOTHING,
        db_column='upload_async_state_id',
        blank=True,
        null=True,
    )
    repaid_time = models.DateTimeField(blank=True, null=True)
    bill_id = models.CharField(max_length=64, blank=True, null=True)
    customer_id = models.CharField(max_length=64, blank=True, null=True)
    bill_status = models.CharField(max_length=64, blank=True, null=True)
    principal_amount = models.BigIntegerField(default=0)
    interest_fee_amount = models.BigIntegerField(default=0)
    late_fee_amount = models.BigIntegerField(default=0)
    total_repayment_amount = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'dana_repayment_reference_history'

    def __str__(self) -> str:
        return "repayment_reference_{}".format(self.repayment_reference.partner_reference_no)


class DanaRepaymentReferenceStatusManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaRepaymentReferenceStatus(TimeStampedModel):
    id = BigAutoField(db_column='dana_repayment_status_id', primary_key=True)
    dana_repayment_reference_id = models.BigIntegerField()
    REPAYMENT_STATUS = (
        (RepaymentReferenceStatus.SUCCESS, 'Success'),
        (RepaymentReferenceStatus.PENDING, 'Pending'),
        (RepaymentReferenceStatus.CANCELLED, 'Cancelled'),
        (RepaymentReferenceStatus.FAILED, 'Failed'),
    )
    status = models.CharField(
        choices=REPAYMENT_STATUS,
        max_length=50,
        default=RepaymentReferenceStatus.SUCCESS,
    )

    objects = DanaRepaymentReferenceStatusManager()

    class Meta(object):
        db_table = 'dana_repayment_reference_status'
        managed = False

    def __str__(self) -> str:
        return "repayment_reference_{}".format(
            DanaRepaymentReference.objects.filter(pk=self.dana_repayment_reference_id)
            .first()
            .partner_reference_no
        )


class DanaLoanReferenceStatusManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaLoanReferenceStatus(TimeStampedModel):
    id = BigAutoField(db_column='dana_loan_status_id', primary_key=True)
    dana_loan_reference = BigOneToOneField(
        DanaLoanReference,
        models.DO_NOTHING,
        db_column='dana_loan_reference_id',
        related_name='dana_loan_status',
    )
    PAYMENT_STATUS = (
        (PaymentReferenceStatus.SUCCESS, 'Success'),
        (PaymentReferenceStatus.PENDING, 'Pending'),
        (PaymentReferenceStatus.CANCELLED, 'Cancelled'),
        (PaymentReferenceStatus.FAILED, 'Failed'),
    )
    status = models.CharField(
        choices=PAYMENT_STATUS,
        max_length=50,
        default=PaymentReferenceStatus.SUCCESS,
    )

    objects = DanaLoanReferenceStatusManager()

    class Meta(object):
        db_table = 'dana_loan_reference_status'

    def __str__(self) -> str:
        return "loan_reference_{}".format(self.dana_loan_reference.partner_reference_no)


class DanaLoanReferenceInsufficientHistory(TimeStampedModel):
    # Change the primary key column name and field type
    id = BigAutoField(db_column='dana_loan_reference_insufficient_history_id', primary_key=True)
    dana_loan_reference = BigOneToOneField(
        DanaLoanReference,
        models.DO_NOTHING,
        db_column='dana_loan_reference_id',
    )
    current_limit = models.FloatField()
    is_recalculated = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'dana_loan_reference_insufficient_history'


class DanaRefundReferenceManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaRefundReference(TimeStampedModel):
    id = BigAutoField(db_column='dana_refund_reference_id', primary_key=True)
    partner_refund_no = models.TextField(
        unique=True, help_text="This refund reference no from dana", db_index=True
    )
    refund_no = models.UUIDField(default=uuid.uuid4, editable=False)
    original_partner_reference_no = models.TextField(
        help_text="This loan partner_reference_no", db_index=True
    )
    original_reference_no = models.TextField(help_text="This loan reference_no")
    original_external_id = models.TextField(blank=True, null=True)
    refund_amount = models.BigIntegerField()
    reason = models.TextField(blank=True, null=True)
    customer_id = models.CharField(max_length=255, blank=True, null=True)
    refund_time = models.DateTimeField(blank=True, null=True)
    lender_product_id = models.CharField(max_length=255, blank=True, null=True)
    credit_usage_mutation = models.BigIntegerField(blank=True, null=True)
    disburse_back_amount = models.BigIntegerField(blank=True, null=True)
    REFUND_STATUS = (
        (DanaReferenceStatus.SUCCESS, 'Success'),
        (DanaReferenceStatus.PENDING, 'Pending'),
        (DanaReferenceStatus.CANCELLED, 'Cancelled'),
        (DanaReferenceStatus.FAILED, 'Failed'),
    )
    status = models.CharField(
        choices=REFUND_STATUS,
        max_length=50,
        default=DanaReferenceStatus.SUCCESS,
    )

    objects = DanaRefundReferenceManager()

    class Meta(object):
        db_table = 'dana_refund_reference'

    def __str__(self) -> str:
        return "refund_{}".format(self.partner_refund_no)


class DanaRefundTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaRefundTransaction(TimeStampedModel):
    id = BigAutoField(db_column='dana_refund_transaction_id', primary_key=True)
    dana_refund_reference = BigForeignKey(
        DanaRefundReference,
        models.DO_NOTHING,
        db_column='dana_refund_reference_id',
        related_name='dana_refund_transactions',
    )
    dana_loan_reference = BigOneToOneField(
        DanaLoanReference,
        models.DO_NOTHING,
        db_column='dana_loan_reference_id',
        related_name='dana_refund_transaction',
    )

    objects = DanaRefundTransactionManager()

    class Meta(object):
        db_table = 'dana_refund_transaction'

    def __str__(self) -> str:
        return "loan_reference_{}".format(self.dana_loan_reference.partner_reference_no)


class DanaRefundedBillTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaRefundedBill(TimeStampedModel):
    """
    This model represents as all Bill ID need to refund ignore if one of the
    bill is already refunded or not, and cummulated_due_date_id is
    represented as new_transaction if we suppport for partial refund
    Currently we only support full refund
    """

    id = BigAutoField(db_column='dana_refunded_bill_id', primary_key=True)
    dana_refund_transaction = BigForeignKey(
        DanaRefundTransaction,
        models.DO_NOTHING,
        db_column='dana_refund_transaction_id',
        related_name='dana_refunded_bills',
    )
    bill_id = models.CharField(max_length=64, db_index=True)
    due_date = models.DateField()
    cumulate_due_date_id = models.CharField(max_length=64, blank=True, null=True)
    period_no = models.CharField(max_length=64, blank=True, null=True)
    principal_amount = models.BigIntegerField(default=0)
    interest_fee_amount = models.BigIntegerField(default=0)
    late_fee_Amount = models.BigIntegerField(default=0)
    paid_principal_amount = models.BigIntegerField(default=0)
    paid_interest_fee_amount = models.BigIntegerField(default=0)
    paid_late_fee_amount = models.BigIntegerField(default=0)
    total_amount = models.BigIntegerField(default=0)
    total_paid_amount = models.BigIntegerField(default=0)
    waived_principal_amount = models.BigIntegerField(blank=True, null=True)
    waived_interest_fee_amount = models.BigIntegerField(blank=True, null=True)
    waived_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    total_waived_amount = models.BigIntegerField(blank=True, null=True)

    objects = DanaRefundedBillTransactionManager()

    class Meta(object):
        db_table = 'dana_refunded_bill'

    def __str__(self) -> str:
        return "payment_bill_{}".format(self.bill_id)


class DanaRefundedRepaymentManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaRefundedRepayment(TimeStampedModel):
    """
    This model purposes is stored repayment need to refund for example:
    1. User Request A loan
    2. User Repayment Bill id 99999
    3. User Do Refund
    4. Dana send the repayment from step 2 in payload and stored in this table
    It's mean if user did a repayment before
    and then do refund dana will send the repayment need to refund in here
    """

    id = BigAutoField(db_column='dana_refunded_repayment_id', primary_key=True)
    bill_id = models.CharField(max_length=64, db_index=True)
    dana_refund_transaction = BigForeignKey(
        DanaRefundTransaction,
        models.DO_NOTHING,
        db_column='dana_refund_transaction_id',
        related_name='dana_refunded_repayments',
    )
    repayment_partner_reference_no = models.TextField(
        help_text="This reference from table dana_repayment_reference.partner_reference_no",
        db_index=True,
    )
    principal_amount = models.BigIntegerField(default=0)
    interest_fee_amount = models.BigIntegerField(default=0)
    late_fee_amount = models.BigIntegerField(default=0)
    total_amount = models.BigIntegerField(default=0)
    waived_principal_amount = models.BigIntegerField(blank=True, null=True)
    waived_interest_fee_amount = models.BigIntegerField(blank=True, null=True)
    waived_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    total_waived_amount = models.BigIntegerField(blank=True, null=True)

    objects = DanaRefundedRepaymentManager()

    class Meta(object):
        db_table = 'dana_refunded_repayment'

    def __str__(self) -> str:
        return "repayment_reference_no{}".format(self.repayment_partner_reference_no)


class DanaFDCResult(TimeStampedModel):
    id = BigAutoField(db_column='dana_fdc_result_id', primary_key=True)
    fdc_status = models.CharField(
        max_length=30,
        default=DanaFDCResultStatus.INIT,
        choices=DanaFDCResultStatus.FDC_STATUS_CHOICES,
        help_text="This to set result fdc status",
    )
    status = models.CharField(
        max_length=30,
        default=DanaFDCStatusSentRequest.SUCCESS,
        choices=DanaFDCStatusSentRequest.CHOICES,
        help_text="To check status data, is already sent or not to dana",
    )
    dana_customer_identifier = models.TextField(db_index=True)
    application_id = models.BigIntegerField(db_index=True)
    lender_product_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta(object):
        db_table = 'dana_fdc_result'
        managed = False


class DanaAccountInfo(TimeStampedModel):
    id = BigAutoField(db_column='dana_account_info_id', primary_key=True)
    dana_customer_identifier = models.TextField(db_index=True)
    dana_fdc_result_id = models.BigIntegerField(db_index=True)
    lender_product_id = models.CharField(max_length=255, blank=True, null=True)
    update_info_list = JSONField(blank=True, null=True)
    additional_info = JSONField(blank=True, null=True)
    status = models.CharField(
        max_length=30,
        default=DanaAccountInfoStatus.SUCCESS,
        choices=DanaAccountInfoStatus.CHOICES,
        help_text="To check status data, is already update or not to dana",
    )

    class Meta(object):
        managed = False
        db_table = 'dana_account_info'


class DanaAIRudderPayloadTemp(TimeStampedModel):
    id = models.AutoField(db_column='dana_ai_rudder_payload_temp_id', primary_key=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True
    )
    phonenumber = models.TextField(db_index=True)
    nama_customer = models.TextField(blank=True, null=True, default='')
    nama_perusahaan = models.TextField(blank=True, null=True, default='')
    posisi_karyawan = models.TextField(blank=True, null=True, default='')
    dpd = models.IntegerField(blank=True, null=True)
    total_denda = models.BigIntegerField(blank=True, null=True)
    total_due_amount = models.BigIntegerField(blank=True, null=True)
    total_outstanding = models.BigIntegerField(blank=True, null=True)
    angsuran_ke = models.IntegerField(blank=True, null=True)
    tanggal_jatuh_tempo = models.TextField(blank=True, null=True, default='')
    nama_pasangan = models.TextField(blank=True, null=True, default='')
    nama_kerabat = models.TextField(blank=True, null=True, default='')
    hubungan_kerabat = models.TextField(blank=True, null=True, default='')
    alamat = models.TextField(blank=True, null=True, default='')
    kota = models.TextField(blank=True, null=True, default='')
    jenis_kelamin = models.TextField(blank=True, null=True, default='')
    tgl_lahir = models.TextField(blank=True, null=True, default='')
    tgl_gajian = models.TextField(blank=True, null=True, default='')
    tujuan_pinjaman = models.TextField(blank=True, null=True, default='')
    jumlah_pinjaman = models.BigIntegerField(blank=True, null=True)
    tgl_upload = models.TextField(blank=True, null=True, default='')
    va_bca = models.TextField(blank=True, null=True, default='')
    va_permata = models.TextField(blank=True, null=True, default='')
    va_maybank = models.TextField(blank=True, null=True, default='')
    va_alfamart = models.TextField(blank=True, null=True, default='')
    va_indomaret = models.TextField(blank=True, null=True, default='')
    va_mandiri = models.TextField(blank=True, null=True, default='')
    tipe_produk = models.TextField(blank=True, null=True, default='')
    last_pay_date = models.TextField(blank=True, null=True, default='')
    last_pay_amount = models.BigIntegerField(blank=True, null=True)
    partner_name = models.TextField(blank=True, null=True, default='')
    last_agent = models.TextField(blank=True, null=True, default='')
    last_call_status = models.TextField(blank=True, null=True, default='')
    refinancing_status = models.TextField(blank=True, null=True, default='')
    activation_amount = models.BigIntegerField(blank=True, null=True)
    program_expiry_date = models.TextField(blank=True, null=True, default='')
    customer_bucket_type = models.TextField(blank=True, null=True, default='')
    promo_untuk_customer = models.TextField(blank=True, null=True, default='')
    zip_code = models.TextField(blank=True, null=True, default='')
    mobile_phone_2 = models.TextField(blank=True, null=True, default='')
    telp_perusahaan = models.TextField(blank=True, null=True, default='')
    mobile_phone_1_2 = models.TextField(blank=True, null=True, default='')
    mobile_phone_2_2 = models.TextField(blank=True, null=True, default='')
    no_telp_pasangan = models.TextField(blank=True, null=True, default='')
    mobile_phone_1_3 = models.TextField(blank=True, null=True, default='')
    mobile_phone_2_3 = models.TextField(blank=True, null=True, default='')
    no_telp_kerabat = models.TextField(blank=True, null=True, default='')
    mobile_phone_1_4 = models.TextField(blank=True, null=True, default='')
    mobile_phone_2_4 = models.TextField(blank=True, null=True, default='')
    bucket_name = models.TextField(db_index=True, default='')
    sort_order = models.IntegerField(blank=True, null=True)
    angsuran_per_bulan = models.BigIntegerField(blank=True, null=True)
    uninstall_indicator = models.TextField(blank=True, null=True, default='')
    fdc_risky = models.TextField(blank=True, null=True, default='')
    potensi_cashback = models.BigIntegerField(blank=True, null=True)
    total_seluruh_perolehan_cashback = models.BigIntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'dana_ai_rudder_payload_temp'
