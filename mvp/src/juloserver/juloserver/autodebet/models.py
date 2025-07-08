from builtins import object
from django.db import models
from model_utils import FieldTracker

from juloserver.julo.models import GetInstanceMixin, TimeStampedModel, JuloModelManager
from juloserver.autodebet.constants import BRITransactionStatus
from django.conf import settings
from django.db.models import Q
from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager
from juloserver.dana_linking.models import DanaWalletAccount


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class AutodebetModelManager(GetInstanceMixin, JuloModelManager):
    pass


class AutodebetModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = AutodebetModelManager()


class AutodebetManager(AutodebetModelManager):
    def is_account_autodebet(self, account_id):
        return self.filter(account_id=account_id).filter(
            Q(is_use_autodebet=True) & Q(is_deleted_autodebet=False)
        ).exists()


class AutodebetAPILog(AutodebetModel):
    id = models.AutoField(db_column='autodebet_api_log_id', primary_key=True)
    application_id = models.BigIntegerField(db_column='application_id', null=True, blank=True)
    account_id = models.BigIntegerField(db_column='account_id', null=True, blank=True)
    account_payment_id = models.BigIntegerField(
        db_column='account_payment_id', null=True, blank=True
    )
    account_transaction_id = models.BigIntegerField(
        db_column='account_transaction_id', null=True, blank=True
    )
    request_type = models.TextField()
    http_status_code = models.IntegerField()
    request = models.TextField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    vendor = models.TextField(null=True, blank=True)
    deduction_source = models.TextField(null=True)

    class Meta(object):
        db_table = 'autodebet_api_log'
        managed = False


class AutodebetAccountManager(GetInstanceMixin, PIIVaultModelManager):
    def is_account_autodebet(self, account_id):
        return (
            self.filter(account_id=account_id)
            .filter(Q(is_use_autodebet=True) & Q(is_deleted_autodebet=False))
            .exists()
        )


class AutodebetAccount(PIIVaultModel):
    PII_FIELDS = ['linked_name', 'linked_mobile_phone', 'linked_email']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = models.AutoField(db_column='autodebet_account_id', primary_key=True)
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id')
    vendor = models.TextField(null=True, blank=True)
    is_use_autodebet = models.BooleanField(default=False)
    registration_ts = models.DateTimeField(null=True, blank=True)
    activation_ts = models.DateTimeField(null=True, blank=True)
    failed_ts = models.DateTimeField(null=True, blank=True)
    failed_reason = models.TextField(null=True, blank=True)

    is_deleted_autodebet = models.BooleanField(default=False)
    deleted_request_ts = models.DateTimeField(null=True, blank=True)
    deleted_success_ts = models.DateTimeField(null=True, blank=True)
    deleted_failed_ts = models.DateTimeField(null=True, blank=True)
    deleted_failed_reason = models.TextField(null=True, blank=True)
    request_id = models.TextField(null=True, blank=True)
    verification = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)

    bri_customer_id = models.TextField(null=True, blank=True)
    payment_method_id = models.TextField(null=True, blank=True)
    linked_account_id = models.TextField(null=True, blank=True)
    linked_mobile_phone = models.TextField(null=True, blank=True)
    linked_name = models.TextField(null=True, blank=True)
    linked_email = models.TextField(null=True, blank=True)
    card_expiry = models.TextField(null=True, blank=True)

    db_account_no = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(null=True, blank=True, default=0)
    is_manual_activation = models.BooleanField(default=False)
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.DO_NOTHING,
        db_column='auth_user_id', null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    deduction_cycle_day = models.IntegerField(null=True)
    deduction_source = models.TextField(null=True)
    is_payday_changed = models.BooleanField(default=False)
    is_experiment_complaint = models.BooleanField(default=False)
    is_suspended = models.BooleanField(default=False)
    is_force_unbind = models.BooleanField(default=False)

    tracker = FieldTracker(fields=['status'])

    linked_name_tokenized = models.TextField(null=True, blank=True)
    linked_mobile_phone_tokenized = models.TextField(null=True, blank=True)
    linked_email_tokenized = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'autodebet_account'

    objects = AutodebetAccountManager()


class AutodebetBenefit(AutodebetModel):
    id = models.AutoField(db_column='autodebet_benefit_id', primary_key=True)
    account_id = models.BigIntegerField(db_column='account_id', null=True, blank=True)
    benefit_type = models.TextField(null=True, blank=True)
    benefit_value = models.TextField(null=True, blank=True)
    is_benefit_used = models.NullBooleanField(default=False, null=True, blank=True)
    pre_assigned_benefit = models.TextField(null=True, blank=True)
    vendor = models.TextField(null=True, blank=True)
    phase = models.CharField(null=True, blank=True, max_length=10)

    class Meta(object):
        db_table = 'autodebet_benefit'
        managed = False


class AutodebetBenefitDetail(AutodebetModel):
    id = models.AutoField(db_column='autodebet_benefit_detail_id', primary_key=True)
    autodebet_benefit = models.ForeignKey(
        AutodebetBenefit, models.DO_NOTHING, db_column='autodebet_benefit_id'
    )
    account_payment_id = models.BigIntegerField(
        db_column='account_payment_id', null=True, blank=True
    )
    payment = models.BigIntegerField(blank=True, db_index=True, null=True)
    benefit_value = models.TextField(null=True, blank=True)
    phase = models.CharField(null=True, blank=True, max_length=10)

    class Meta(object):
        db_table = 'autodebet_benefit_detail'
        managed = False


class AutodebetBenefitCounter(AutodebetModel):
    id = models.AutoField(db_column='autodebet_benefit_counter_id', primary_key=True)
    name = models.TextField()
    counter = models.IntegerField(default=0)
    rounded_count = models.IntegerField(default=0, null=True, blank=True)

    class Meta(object):
        db_table = 'autodebet_benefit_counter'


class AutodebetBRITransaction(AutodebetModel):
    id = models.AutoField(db_column='autodebet_bri_transaction_id', primary_key=True)
    bri_transaction_id = models.TextField(null=True, blank=True)
    transaction_id = models.TextField(null=True, blank=True)
    autodebet_account = models.ForeignKey(
        AutodebetAccount, models.DO_NOTHING, db_column='autodebet_account_id'
    )
    account_payment = models.ForeignKey(
        "account_payment.AccountPayment", models.DO_NOTHING,
        db_column='account_payment_id'
    )
    amount = models.BigIntegerField(blank=True, null=True)
    status = models.TextField(null=True, blank=True, default=BRITransactionStatus.INITIAL)
    created_ts = models.DateTimeField(null=True, blank=True)
    updated_ts = models.DateTimeField(null=True, blank=True)
    otp_mobile_number = models.TextField(null=True, blank=True)
    otp_expiration_timestamp = models.DateTimeField(null=True, blank=True)
    failure_code = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    required_action = models.TextField(null=True, blank=True)
    tracker = FieldTracker(fields=['status'])

    class Meta(object):
        db_table = 'autodebet_bri_transaction'

    @property
    def is_success(self):
        return self.status == BRITransactionStatus.SUCCESS

    @property
    def is_pending(self):
        return self.status == BRITransactionStatus.OTP_PENDING


class AutodebetBRITransactionHistory(AutodebetModel):
    autodebet_bri_transaction = models.ForeignKey(
        AutodebetBRITransaction, models.DO_NOTHING, db_column='autodebet_bri_transaction_id'
    )
    old_status = models.TextField(null=True, blank=True)
    new_status = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'autodebet_bri_transaction_history'


class AutodebetSuspendLog(AutodebetModel):
    id = models.AutoField(db_column='autodebet_suspend_log_id', primary_key=True)
    reason = models.TextField(null=True, blank=True)
    autodebet_account = models.ForeignKey(
        AutodebetAccount, models.DO_NOTHING, db_column='autodebet_account_id'
    )
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )

    class Meta(object):
        db_table = 'autodebet_suspend_log'


class AutodebetMandiriAccount(AutodebetModel):
    id = models.AutoField(db_column='autodebet_mandiri_account_id', primary_key=True)
    autodebet_account = models.ForeignKey(
        AutodebetAccount, models.DO_NOTHING, db_column='autodebet_account_id'
    )
    charge_token = models.TextField(null=True, blank=True)
    bank_card_token = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=30, null=True, blank=True)
    journey_id = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'autodebet_mandiri_account'


class AutodebetMandiriTransaction(AutodebetModel):
    id = models.AutoField(db_column='autodebet_mandiri_transaction_id', primary_key=True)
    autodebet_mandiri_account = models.ForeignKey(
        AutodebetMandiriAccount, models.DO_NOTHING, db_column='autodebet_mandiri_account_id'
    )
    amount = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=30, null=True, blank=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment', models.DO_NOTHING,
        db_column='account_payment_id', blank=True, null=True)
    original_reference_no = models.TextField(null=True, blank=True, db_index=True)
    original_partner_reference_no = models.TextField(null=True, blank=True, db_index=True)

    class Meta(object):
        db_table = 'autodebet_mandiri_transaction'


class AutodebetBniAccount(AutodebetModel):
    id = models.AutoField(db_column='autodebet_bni_account_id', primary_key=True)
    auth_code = models.CharField(max_length=32, null=True, blank=True)
    state_code = models.CharField(max_length=32, null=True, blank=True)
    public_user_id = models.CharField(max_length=16, null=True, blank=True)
    account_token = models.CharField(max_length=32, null=True, blank=True)
    status = models.CharField(max_length=10, null=True, blank=True)
    autodebet_account = models.ForeignKey(
        AutodebetAccount, models.DO_NOTHING, db_column='autodebet_account_id'
    )
    x_external_id = models.CharField(max_length=32, null=True, blank=True)

    class Meta(object):
        db_table = 'autodebet_bni_account'


class AutodebetBniTransaction(AutodebetModel):
    id = models.AutoField(db_column='autodebet_bni_transaction_id', primary_key=True)
    autodebet_bni_account = models.ForeignKey(
        AutodebetBniAccount, models.DO_NOTHING, db_column='autodebet_bni_account'
    )
    x_external_id = models.CharField(max_length=32, null=True, blank=True)
    amount = models.BigIntegerField(null=True, blank=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )
    status = models.CharField(max_length=30, null=True, blank=True)
    status_desc = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'autodebet_bni_transaction'


class AutodebetBniUnbindingOtp(AutodebetModel):
    id = models.AutoField(db_column='autodebet_bni_unbinding_otp_id', primary_key=True)
    otp_token = models.CharField(max_length=32, null=True, blank=True)
    partner_reference_no = models.CharField(max_length=32, null=True, blank=True)
    reference_no = models.CharField(max_length=32, null=True, blank=True)
    autodebet_bni_account = models.ForeignKey(
        AutodebetBniAccount, models.DO_NOTHING, db_column='autodebet_bni_account'
    )
    status = models.CharField(max_length=10, null=True, blank=True)
    x_external_id = models.CharField(max_length=32, null=True, blank=True)

    class Meta(object):
        db_table = 'autodebet_bni_unbinding_otp'


class AutodebetIdfyVideoCall(AutodebetModel):
    id = models.AutoField(primary_key=True, db_column='autodebet_idfy_video_call_id')
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id')
    reference_id = models.CharField(db_column="reference_id", max_length=50, blank=True, null=True)
    profile_id = models.CharField(db_column="profile_id", max_length=100, blank=True, null=True)
    performed_video_call_by = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    status_tasks = models.CharField(max_length=50, blank=True, null=True)
    reviewer_action = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    profile_url = models.CharField(max_length=150, blank=True, null=True)
    reject_reason = models.CharField(max_length=150, blank=True, null=True)

    class Meta(object):
        db_table = 'autodebet_idfy_video_call'


class AutodebetDanaTransaction(AutodebetModel):
    id = models.AutoField(db_column='autodebet_dana_transaction_id', primary_key=True)
    dana_wallet_account = models.ForeignKey(
        DanaWalletAccount, models.DO_NOTHING, db_column='dana_wallet_account_id'
    )
    original_reference_no = models.TextField(null=True, blank=True, db_index=True)
    original_partner_reference_no = models.TextField(null=True, blank=True, db_index=True)
    amount = models.BigIntegerField(null=True, blank=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )
    status = models.CharField(max_length=30, null=True, blank=True)
    status_desc = models.TextField(blank=True, null=True)
    paid_amount = models.BigIntegerField(blank=True, null=True)
    is_partial = models.BooleanField(default=False)
    is_eligible_benefit = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'autodebet_dana_transaction'


class AutodebetOvoTransaction(AutodebetModel):
    id = BigAutoField(db_column='autodebet_ovo_transaction_id', primary_key=True)
    ovo_wallet_account = models.ForeignKey(
        'ovo.OvoWalletAccount', models.DO_NOTHING, db_column='ovo_wallet_account_id'
    )
    original_reference_no = models.TextField(null=True, blank=True, db_index=True)
    original_partner_reference_no = models.TextField(null=True, blank=True, db_index=True)
    amount = models.BigIntegerField(null=True, blank=True)
    account_payment_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=30, null=True, blank=True)
    status_desc = models.TextField(blank=True, null=True)
    paid_amount = models.BigIntegerField(blank=True, null=True)
    is_partial = models.BooleanField(default=False)
    is_eligible_benefit = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'autodebet_ovo_transaction'
        managed = False


class AutodebetDeactivationSurveyQuestion(AutodebetModel):
    id = models.AutoField(primary_key=True, db_column="autodebet_deactivation_survey_question_id")
    question = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'autodebet_deactivation_survey_question'
        managed = False

    def __str__(self):
        return self.question


class AutodebetDeactivationSurveyAnswer(AutodebetModel):
    id = models.AutoField(primary_key=True, db_column="autodebet_deactivation_survey_answer_id")
    question = models.ForeignKey(
        AutodebetDeactivationSurveyQuestion,
        models.DO_NOTHING,
        db_column='autodebet_deactivation_survey_question_id',
        related_name="answers",
    )
    answer = models.TextField(blank=True, null=True)
    order = models.SmallIntegerField(default=0)

    class Meta:
        db_table = 'autodebet_deactivation_survey_answer'
        managed = False

    def __str__(self):
        return self.answer


class AutodebetDeactivationSurveyUserAnswer(AutodebetModel):
    id = models.AutoField(
        primary_key=True, db_column="autodebet_deactivation_survey_user_answer_id"
    )
    account_id = models.BigIntegerField()
    autodebet_account_id = models.BigIntegerField()
    question = models.TextField(null=True, blank=True)
    answer = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'autodebet_deactivation_survey_user_answer'
        managed = False


class AutodebetPaymentOffer(AutodebetModel):
    """
    This class is used to store how many
    payment offer autodebet should show in mobile site
    """

    id = BigAutoField(primary_key=True, db_column="autodebet_payment_offer_id")
    account_id = models.BigIntegerField(null=True, blank=True)
    counter = models.IntegerField()
    is_should_show = models.BooleanField(default=False)

    class Meta:
        db_table = 'autodebet_payment_offer'
        managed = False


class GopayAutodebetSubscriptionRetry(AutodebetModel):
    id = BigAutoField(db_column='gopay_autodebet_subscription_retry_id', primary_key=True)
    account_payment_id = models.BigIntegerField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    is_retried = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'gopay_autodebet_subscription_retry'
        managed = False
