import os

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.postgres.fields.array import ArrayField
from django.contrib.postgres.fields.jsonb import JSONField

from juloserver.account.models import Account
from juloserver.julo.fields import EmailLowerCaseField
from juloserver.julo.services2 import get_redis_client
from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin
from juloserver.julo.models import (
    XidLookup,
    ascii_validator,
    Application,
    Loan,
    Partner,
    S3ObjectModel
)
from juloserver.partnership.constants import (
    LoanDurationType,
    PartnershipLogStatus,
    PaylaterTransactionStatuses,
    APISourceFrom,
    PartnershipImageStatus,
    PartnershipImageService,
    PartnershipImageType,
    PartnershipImageProductType,
    PaylaterUserAction,
    PartnershipTokenType,
)
from juloserver.pii_vault.models import PIIVaultModelManager, PIIVaultModel
from juloserver.pin.models import CustomerPin
from juloserver.julocore.customized_psycopg2.models import (
    BigForeignKey,
    BigOneToOneField,
    BigAutoField
)
from django.core.validators import RegexValidator, MaxLengthValidator
from juloserver.julo.utils import (
    get_oss_presigned_url,
    get_oss_public_url,
    get_oss_presigned_url_external,
)
from juloserver.julo.clients import get_s3_url
from juloserver.julocore.python2.utils import py2round
from past.utils import old_div

from typing import Any

from juloserver.partnership.liveness_partnership.constants import (
    LivenessImageService,
    LivenessImageStatus,
    LivenessResultMappingStatus,
)


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class MerchantDistributorCategory(TimeStampedModel):
    id = models.AutoField(db_column='merchant_distributor_category_id', primary_key=True)
    category_name = models.TextField()

    class Meta(object):
        db_table = 'merchant_distributor_category'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.category_name)


class PartnershipTypeManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipType(TimeStampedModel):
    id = models.AutoField(db_column='partnership_type_id', primary_key=True)
    partner_type_name = models.TextField()

    objects = PartnershipTypeManager()

    class Meta(object):
        db_table = 'partnership_type'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.partner_type_name)


class DistributorManager(GetInstanceMixin, JuloModelManager):

    def create(self, *args, **kwargs):
        distributor = super(DistributorManager, self).create(*args, **kwargs)
        distributor.generate_xid()
        distributor.save(update_fields=["distributor_xid"])
        return distributor


class DistributorPIIVaultManager(PIIVaultModelManager, DistributorManager):
    pass


class Distributor(PIIVaultModel):
    PII_FIELDS = ['email', 'phone_number', 'npwp', 'bank_account_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='distributor_id', primary_key=True)
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING, db_column='partner_id')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='auth_user_id')
    distributor_category = models.ForeignKey(
        'MerchantDistributorCategory', models.DO_NOTHING, db_column='distributor_category_id')
    name = models.TextField()
    address = models.TextField()
    email = models.EmailField()
    phone_number = models.TextField()
    type_of_business = models.TextField()
    npwp = models.TextField()
    nib = models.TextField()
    bank_account_name = models.TextField()
    bank_account_number = models.TextField()
    # this field will be filled after save / update from django admin
    name_bank_validation = models.ForeignKey(
        'disbursement.NameBankValidation', models.DO_NOTHING,
        db_column='name_bank_validation_id', blank=True, null=True)
    bank_name = models.TextField()
    external_distributor_id = models.TextField(blank=True, null=True)
    distributor_xid = models.BigIntegerField(blank=True, null=True, db_index=True)

    email_tokenized = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)
    npwp_tokenized = models.TextField(null=True, blank=True)
    bank_account_number_tokenized = models.TextField(null=True, blank=True)

    objects = DistributorPIIVaultManager()

    def generate_xid(self):
        if self.id is None or self.distributor_xid is not None:
            return
        self.distributor_xid = XidLookup.get_new_xid()

    class Meta(object):
        db_table = 'distributor'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.name)


class PartnershipApiLog(TimeStampedModel):
    id = models.AutoField(db_column='partnership_api_log_id', primary_key=True)
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING, db_column='partner_id')
    customer = models.ForeignKey('julo.Customer',
                                 models.DO_NOTHING, db_column='customer_id',
                                 blank=True, null=True)
    application = models.ForeignKey('julo.Application',
                                    models.DO_NOTHING, db_column='application_id',
                                    blank=True, null=True)
    distributor = models.ForeignKey('Distributor',
                                    models.DO_NOTHING, db_column='distributor_id',
                                    blank=True, null=True)
    api_type = models.TextField()
    query_params = models.TextField(blank=True, null=True)
    api_url = models.TextField(blank=True, null=True)

    # Will remove immediatly after migration to new field success
    request_body = models.TextField(blank=True, null=True)
    response = models.TextField(blank=True, null=True)

    # New field to store log in json format
    request_body_json = JSONField(blank=True, null=True)
    response_json = JSONField(blank=True, null=True)
    http_status_code = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    FROM = (
        (APISourceFrom.INTERNAL, 'Internal'),
        (APISourceFrom.EXTERNAL, 'External'),
    )
    api_from = models.CharField(choices=FROM, blank=True, null=True,
                                max_length=20)

    class Meta(object):
        db_table = 'partnership_api_log'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.api_type)


class MerchantHistoricalTransaction(TimeStampedModel):

    VERIFIED = "verified"
    UNVERIFIED = "unverified"

    PAYMENT_METHOD_CHOICES = (
        (VERIFIED, VERIFIED),
        (UNVERIFIED, UNVERIFIED),
    )

    CREDIT = "credit"
    DEBIT = "debit"

    TRANSACTION_TYPE_CHOICES = (
        (CREDIT, CREDIT),
        (DEBIT, DEBIT),
    )

    id = models.AutoField(db_column='merchant_historical_transaction_id', primary_key=True)
    merchant = models.ForeignKey('merchant_financing.Merchant',
                                 models.DO_NOTHING, db_column='merchant_id')
    type = models.TextField(choices=TRANSACTION_TYPE_CHOICES)
    transaction_date = models.DateField()
    booking_date = models.DateField()
    payment_method = models.TextField(choices=PAYMENT_METHOD_CHOICES)
    amount = models.BigIntegerField(default=0)
    term_of_payment = models.BigIntegerField()
    is_using_lending_facilities = models.BooleanField(default=False)
    # when Partner reupload merchant historical transaction,
    # the previous merchant historical transaction will be set to True
    is_deleted = models.BooleanField(default=False, db_index=True)
    # application ID will be use as an identifier for soft delete the previous
    # merchant historical transaction
    application = BigForeignKey('julo.Application',
                                models.DO_NOTHING, db_column='application_id', blank=True,
                                null=True)
    merchant_historical_transaction_task = models.ForeignKey(
        'merchant_financing.MerchantHistoricalTransactionTask', models.DO_NOTHING,
        db_column='merchant_historical_transaction_task_id', blank=True, null=True
    )
    reference_id = models.CharField(max_length=50)

    class Meta(object):
        db_table = 'merchant_historical_transaction'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.type)


class PartnershipConfigManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipConfig(TimeStampedModel):
    id = models.AutoField(db_column='partnership_config_id', primary_key=True)
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING, db_column='partner_id')
    partnership_type = models.ForeignKey(
        'PartnershipType', models.DO_NOTHING,
        db_column='partnership_type_id', blank=True, null=True)
    callback_url = models.URLField(null=True, blank=True, max_length=200)
    callback_token = models.TextField(null=True, blank=True)
    is_transaction_use_pin = models.BooleanField(default=True)
    is_use_signature = models.BooleanField(default=True)
    loan_duration = ArrayField(models.IntegerField(validators=[MinValueValidator(1)]),
                               blank=True, null=True)
    redirect_url = models.URLField(null=True, blank=True)
    access_token = models.TextField(null=True, blank=True)
    refresh_token = models.TextField(null=True, blank=True)
    loan_cancel_duration = models.IntegerField(default=0)
    is_validation_otp_checking = models.BooleanField(default=False)
    is_show_loan_simulations = models.BooleanField(
        default=False,
        help_text="This only used for partnership type paylater")
    is_show_interest_in_loan_simulations = models.BooleanField(
        default=False,
        help_text="This only used for partnership type paylater")
    julo_partner_webview_url = models.URLField(null=True, blank=True)

    help_text_adding_mdr_ppn = 'If this field is active, ' \
        'product_lookup.origination_fee_pct should be increase ' \
        'using this calculation (origination_fee_pct + mdr(0.1) + mdr_ppn(0.11). ' \
        'currently running only for merchant financing'
    is_loan_amount_adding_mdr_ppn = models.BooleanField(default=False,
                                                        help_text=help_text_adding_mdr_ppn)
    historical_transaction_date_count = models.IntegerField(
        default=30,
        help_text='This field is use to check if there are historical transaction is found '
                  'on the range of the current_date - {value} of this field. \n'
                  'Example: 30 Aug and the value for this field is 30. So we will check if there '
                  'are historical transaction from 1 Aug - 30 Aug'
    )
    historical_transaction_month_duration = models.IntegerField(
        default=6,
        help_text='This field is use to get the start date for the merchant historical transaction '
                  'from the founded the end_date. \n'
                  'Example: the latest transaction date found is 1 August and '
                  'historical_transaction_month_duration = 6. Then we set the start date '
                  'from 1 August to 6 months before that'
    )
    is_active = models.BooleanField(default=False,
                                    help_text="This should be using only for partnership paylater")
    order_validation = models.BooleanField(
        default=False,
        help_text="This only used for holding partner loan status to 211"
    )

    objects = PartnershipConfigManager()

    class Meta(object):
        db_table = 'partnership_config'

    def __str__(self):
        """Visual identification"""
        partner_name = self.partner.name if self.partner else '-'
        return "%s id='%s' type'=%s'" % (partner_name, self.id, self.partnership_type)


class CustomerPinVerifyManager(GetInstanceMixin, JuloModelManager):
    pass


class CustomerPinVerify(TimeStampedModel):
    id = models.AutoField(db_column='customer_pin_verify_id', primary_key=True)
    customer = models.ForeignKey('julo.Customer',
                                 models.DO_NOTHING, db_column='customer_id')
    customer_pin = models.ForeignKey(CustomerPin,
                                     models.DO_NOTHING,
                                     db_column='customer_pin_id')

    is_pin_used = models.BooleanField(default=False)
    expiry_time = models.DateTimeField(blank=True, null=True)

    objects = CustomerPinVerifyManager()

    class Meta(object):
        db_table = 'customer_pin_verify'

    def __str__(self):
        """Visual identification"""
        return str(self.id)


class CustomerPinVerifyHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class CustomerPinVerifyHistory(TimeStampedModel):
    id = models.AutoField(db_column='customer_pin_verify_history_id', primary_key=True)
    customer_pin_verify = models.ForeignKey(CustomerPinVerify,
                                            models.DO_NOTHING,
                                            db_column='customer_pin_verify_id')

    is_pin_used = models.BooleanField(default=False)
    expiry_time = models.DateTimeField(blank=True, null=True)

    objects = CustomerPinVerifyHistoryManager()

    class Meta(object):
        db_table = 'customer_pin_verify_history'

    def __str__(self):
        """Visual identification"""
        return str(self.id)


class MasterPartnerConfigProductLookup(TimeStampedModel):
    id = models.AutoField(db_column='master_partner_config_product_lookup_id', primary_key=True)
    product_lookup = models.ForeignKey(
        'julo.ProductLookup', models.DO_NOTHING, db_column='product_code'
    )
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING, db_column='partner_id')
    minimum_score = models.FloatField(validators=[MinValueValidator(0.01), MaxValueValidator(1)],
                                      help_text="This value must be lower than maximum score")
    maximum_score = models.FloatField(validators=[MinValueValidator(0.01), MaxValueValidator(1)],
                                      help_text="Maximal value is 1")

    class Meta(object):
        db_table = 'master_partner_config_product_lookup'
        unique_together = ('partner', 'maximum_score', 'minimum_score', 'product_lookup')

    def __str__(self):
        return "{}".format(self.id)


class HistoricalPartnerConfigProductLookup(TimeStampedModel):
    id = models.AutoField(
        db_column='historical_partner_config_product_lookup_id', primary_key=True
    )
    product_lookup = models.ForeignKey(
        'julo.ProductLookup', models.DO_NOTHING, db_column='product_code'
    )
    master_partner_config_product_lookup = models.ForeignKey(
        'MasterPartnerConfigProductLookup', models.DO_NOTHING,
        db_column='master_partner_config_product_lookup_id'
    )
    minimum_score = models.FloatField(validators=[MinValueValidator(0.1), MaxValueValidator(1)])
    maximum_score = models.FloatField(validators=[MinValueValidator(0.1), MaxValueValidator(1)])

    class Meta(object):
        db_table = 'historical_partner_config_product_lookup'

    def __str__(self):
        return "{}".format(self.id)


class PartnerLoanRequest(TimeStampedModel):
    LOAN_DURATION_TYPE = (
        (LoanDurationType.DAYS, LoanDurationType.DAYS),
        (LoanDurationType.WEEKLY, LoanDurationType.WEEKLY),
        (LoanDurationType.BIWEEKLY, LoanDurationType.BIWEEKLY),
        (LoanDurationType.MONTH, LoanDurationType.MONTH),
    )
    """
    This table is use to identify the loan is created from/for which Partner
    """
    id = models.AutoField(
        db_column='partner_loan_request_id', primary_key=True
    )
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING, db_column='partner_id')
    distributor = models.ForeignKey(
        'partnership.Distributor', models.DO_NOTHING,
        db_column='distributor_id', blank=True, null=True)
    loan_amount = models.FloatField()
    loan_disbursement_amount = models.FloatField()
    loan_original_amount_help_text = "This field original amount based on user request"
    loan_original_amount = models.FloatField(default=0,
                                             help_text=loan_original_amount_help_text)
    partner_origin_name = models.TextField(blank=True, null=True)
    receipt_number = models.TextField(blank=True, null=True)
    loan_duration_type = models.CharField(
        choices=LOAN_DURATION_TYPE,
        max_length=10,
        null=True,
        blank=True,
    )
    # For New Axiata (Merchant Financing) Loan
    funder = models.CharField(max_length=6, blank=True, null=True)
    loan_type = models.CharField(max_length=4, blank=True, null=True)
    loan_request_date = models.DateField(blank=True, null=True)
    interest_rate = models.FloatField(null=True, blank=True)
    provision_rate = models.FloatField(null=True, blank=True)
    financing_amount = models.FloatField(null=True, blank=True)
    financing_tenure = models.IntegerField(null=True, blank=True)
    installment_number = models.IntegerField(null=True, blank=True)
    partnership_distributor = models.ForeignKey(
        'partnership.PartnershipDistributor',
        models.DO_NOTHING,
        db_column='partnership_distributor_id',
        blank=True,
        null=True,
    )
    invoice_number = models.CharField(max_length=100, blank=True, null=True)
    buyer_name = models.CharField(max_length=100, blank=True, null=True)
    buying_amount = models.IntegerField(null=True, blank=True)
    partnership_product = models.ForeignKey(
        "partnership.PartnershipProduct",
        models.DO_NOTHING,
        db_column="partnership_product_id",
        blank=True,
        null=True,
    )
    skrtp_link = models.TextField(blank=True, null=True)
    max_platform_check = models.NullBooleanField()
    provision_amount = models.FloatField(null=True, blank=True)
    is_manual_skrtp = models.NullBooleanField(blank=True)
    partnership_product_lookup = models.BigIntegerField(
        db_column='partnership_product_lookup_id', blank=True, null=True
    )
    paid_provision_amount = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = 'partner_loan_request'

    def __str__(self):
        return "ID{} - Partner({}) - Loan({})".format(self.id, self.partner.name, self.loan.id)


class PartnershipCustomerDataManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipCustomerDataPIIVaultManager(PIIVaultModelManager, PartnershipCustomerDataManager):
    pass


class PartnershipApplicationDataManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipApplicationDataPIIVaultManager(
    PIIVaultModelManager, PartnershipApplicationDataManager
):
    pass


class PartnershipCustomerData(PIIVaultModel):

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"

    OTP_STATUS = [
        (UNVERIFIED, "Unverified Phone Number"),
        (VERIFIED, "Verified Phone Number")
    ]

    EMAIL_OTP_STATUS = [
        (UNVERIFIED, "Unverified Email"),
        (VERIFIED, "Verified Email")
    ]
    PII_FIELDS = ['email', 'nik', 'phone_number']
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(
        db_column='partnership_customer_data_id', primary_key=True
    )
    customer = BigForeignKey('julo.Customer', models.DO_NOTHING,
                             db_column='customer_id',
                             blank=True,
                             null=True)
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING,
                                db_column='partner_id')
    phone_number = models.CharField(max_length=16, blank=True, null=True)
    email = EmailLowerCaseField(null=True, blank=True, db_index=True)
    otp_status = models.CharField(
        max_length=15,
        choices=OTP_STATUS,
        default=UNVERIFIED,
        help_text='this field using for LinkAja',
        null=True,
        blank=True,
    )
    email_otp_status = models.CharField(
        max_length=15,
        choices=EMAIL_OTP_STATUS,
        default=UNVERIFIED,
        help_text='this field using for LinkAja',
        null=True,
        blank=True,
    )
    token = models.TextField(
        db_index=True,
        help_text='this field using for LinkAja',
        null=True,
        blank=True,
    )
    nik = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(regex='^[0-9]{16}$', message='KTP has to be 16 numeric digits'),
        ],
        blank=True,
        null=True,
    )
    last_j1_application_status = models.CharField(
        max_length=50, blank=True, null=True, help_text='this field using for LinkAja'
    )
    application = BigOneToOneField(
        Application,
        models.DO_NOTHING,
        related_name='partnership_customer_data',
        db_column='application_id',
        blank=True,
        null=True,
    )
    account = BigOneToOneField(
        Account,
        models.DO_NOTHING,
        related_name='partnership_customer_data',
        db_column='account_id',
        blank=True,
        null=True,
    )
    phone_number_tokenized = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    npwp = models.TextField(blank=True, null=True)
    user_type = models.CharField(max_length=50, blank=True, null=True)
    certificate_number = models.CharField("Nomor akta", max_length=100, blank=True, null=True)
    certificate_date = models.DateField("Tanggal akta", blank=True, null=True)
    customer_id_old = models.BigIntegerField(blank=True, null=True)

    objects = PartnershipCustomerDataPIIVaultManager()

    class Meta(object):
        db_table = 'partnership_customer_data'
        unique_together = ('phone_number', 'partner', 'nik', )

    def __str__(self):
        return str(self.id) + " - " + str(self.nik)


class PartnershipApplicationData(PIIVaultModel):
    PII_FIELDS = [
        'email',
        'mobile_phone_1',
        'fullname',
        'spouse_name',
        'spouse_mobile_phone',
        'close_kin_name',
        'close_kin_mobile_phone',
        'kin_name',
        'kin_mobile_phone',
    ]
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(
        db_column='partnership_application_data_id', primary_key=True
    )
    application = BigForeignKey('julo.Application', on_delete=models.DO_NOTHING,
                                db_column='application_id', blank=True, null=True)
    partnership_customer_data = models.ForeignKey(
        PartnershipCustomerData, on_delete=models.DO_NOTHING,
        db_column='partnership_customer_data_id')
    email = models.EmailField()
    is_used_for_registration = models.BooleanField(default=False)
    is_submitted = models.BooleanField(default=False)
    encoded_pin = models.TextField(blank=True, null=True)
    fullname = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True)
    birth_place = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    gender = models.CharField("Jenis kelamin",
                              choices=Application.GENDER_CHOICES,
                              max_length=10,
                              validators=[ascii_validator],
                              blank=True, null=True)
    mother_maiden_name = models.CharField(max_length=100, blank=True, null=True)
    address_street_num = models.CharField(max_length=100, validators=[ascii_validator],
                                          blank=True, null=True)
    address_provinsi = models.CharField(max_length=100, validators=[ascii_validator],
                                        blank=True, null=True)
    address_kabupaten = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kecamatan = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kelurahan = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kodepos = models.CharField(max_length=5, blank=True, null=True,
                                       validators=[
                                           ascii_validator,
                                           RegexValidator(
                                               regex='^[0-9]{5}$',
                                               message='Kode pos has to be 5 numeric digits')
                                       ])
    home_status = models.CharField("Status domisili",
                                   choices=Application.HOME_STATUS_CHOICES,
                                   max_length=50,
                                   validators=[ascii_validator],
                                   blank=True, null=True)
    marital_status = models.CharField("Status sipil",
                                      choices=Application.MARITAL_STATUS_CHOICES,
                                      max_length=50,
                                      validators=[ascii_validator],
                                      blank=True, null=True)
    dependent = models.IntegerField(
        "Jumlah tanggungan",
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        blank=True, null=True)
    mobile_phone_1 = models.CharField(
        max_length=50, blank=True, null=True,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^\+?\d{10,15}$',
                message='mobile phone has to be 10 to 15 numeric digits')
        ])
    mobile_phone_2 = models.CharField(
        max_length=50, blank=True, null=True,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^\+?\d{10,15}$',
                message='mobile phone has to be 10 to 15 numeric digits')
        ])
    occupied_since = models.DateField(blank=True, null=True)
    spouse_name = models.CharField(max_length=100, blank=True, null=True,
                                   validators=[ascii_validator])
    spouse_mobile_phone = models.CharField(
        max_length=50, blank=True, null=True,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^\+?\d{10,15}$',
                message='mobile phone has to be 10 to 15 numeric digits')
        ])
    close_kin_name = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True)
    close_kin_mobile_phone = models.CharField(
        max_length=50, blank=True, null=True,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^\+?\d{10,15}$',
                message='mobile phone has to be 10 to 15 numeric digits')
        ])
    kin_relationship = models.CharField("Hubungan kerabat",
                                        choices=Application.KIN_RELATIONSHIP_CHOICES,
                                        max_length=50,
                                        validators=[ascii_validator],
                                        blank=True, null=True)
    kin_mobile_phone = models.CharField(max_length=50,
                                        validators=[ascii_validator],
                                        blank=True, null=True)
    kin_name = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True)
    job_type = models.CharField("Tipe pekerjaan",
                                choices=Application.JOB_TYPE_CHOICES,
                                max_length=50,
                                validators=[ascii_validator],
                                blank=True, null=True)
    job_industry = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    job_description = models.CharField(max_length=100, blank=True, null=True,
                                       validators=[ascii_validator])
    company_name = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    company_phone_number = models.CharField(
        max_length=50, blank=True, null=True,
        validators=[
            ascii_validator, RegexValidator(
                regex='^\+?\d{6,15}$',
                message='phone has to be 6 to 15 numeric digits')
        ])
    job_start = models.DateField(blank=True, null=True)
    payday = models.IntegerField(
        blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(28)])
    last_education = models.CharField("Pendidikan terakhir",
                                      choices=Application.LAST_EDUCATION_CHOICES,
                                      max_length=50,
                                      validators=[ascii_validator],
                                      blank=True, null=True)
    monthly_income = models.BigIntegerField(blank=True, null=True)
    monthly_expenses = models.BigIntegerField(blank=True, null=True)
    monthly_housing_cost = models.BigIntegerField(blank=True, null=True)
    total_current_debt = models.BigIntegerField(blank=True, null=True)
    bank_name = models.CharField(max_length=250, validators=[ascii_validator],
                                 blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, validators=[ascii_validator],
                                           blank=True, null=True)
    loan_purpose = models.CharField("Tujuan pinjaman", max_length=100, blank=True, null=True)
    loan_purpose_description_expanded = models.TextField(blank=True, null=True,
                                                         validators=[MaxLengthValidator(500)])
    loan_purpose_desc = models.TextField(
        blank=True, null=True,
        validators=[
            RegexValidator(
                regex='^[ -~]+$',
                message='characters not allowed')
        ]
    )
    is_term_accepted = models.BooleanField(default=False)
    is_verification_agreed = models.BooleanField(default=False)
    address_same_as_ktp = models.NullBooleanField()
    web_version = models.CharField(blank=True, null=True, max_length=50)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    business_duration = models.IntegerField(blank=True, null=True)
    nib = models.CharField(max_length=25, blank=True, null=True)
    proposed_limit = models.FloatField(blank=True, null=True)
    product_line = models.CharField(max_length=100, blank=True, null=True)
    business_category = models.CharField(max_length=100, blank=True, null=True)
    is_sended_to_email = models.NullBooleanField(null=True)
    reject_reason = JSONField(null=True, blank=True)
    total_revenue_per_year = models.BigIntegerField(blank=True, null=True)
    fullname_tokenized = models.TextField(blank=True, null=True)
    mobile_phone_1_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    close_kin_name_tokenized = models.TextField(blank=True, null=True)
    close_kin_mobile_phone_tokenized = models.TextField(blank=True, null=True)
    kin_name_tokenized = models.TextField(blank=True, null=True)
    kin_mobile_phone_tokenized = models.TextField(blank=True, null=True)
    spouse_name_tokenized = models.TextField(blank=True, null=True)
    spouse_mobile_phone_tokenized = models.TextField(blank=True, null=True)
    business_type = models.CharField(max_length=100, blank=True, null=True)
    risk_assessment_check = models.NullBooleanField(null=True)
    business_entity = models.CharField(max_length=100, blank=True, null=True)

    objects = PartnershipApplicationDataPIIVaultManager()

    class Meta(object):
        db_table = 'partnership_application_data'

    def __str__(self):
        return str(self.id) + " - " + str(self.email)


class PartnershipCustomerDataOTPManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipCustomerDataOTP(TimeStampedModel):
    EMAIL = 'email'
    PHONE = 'phone'

    OTP_TYPE = (
        (EMAIL, EMAIL),
        (PHONE, PHONE)
    )

    id = models.AutoField(
        db_column='partnership_customer_data_otp_id', primary_key=True
    )
    # the relation for "partnership_customer_data" before is one to one,
    # but we need to change into foreign key because
    # we need to have 2 types of OTP.
    # So 1 partnership_customer_data can have partnership_customer_data_otp for email and phone
    partnership_customer_data = models.ForeignKey(
        PartnershipCustomerData, on_delete=models.DO_NOTHING,
        db_column='partnership_customer_data_id', related_name='partnership_customer_data_otps')
    otp_last_failure_time = models.DateTimeField(null=True, blank=True, default=None)
    otp_failure_count = models.IntegerField(default=0)
    otp_latest_failure_count = models.IntegerField(default=0)
    otp_type = models.CharField(choices=OTP_TYPE, max_length=5, default=PHONE)
    objects = PartnershipCustomerDataOTPManager()

    class Meta(object):
        db_table = 'partnership_customer_data_otp'


class PartnershipSessionInformationPIIVaultManager(PIIVaultModelManager):
    pass


class PartnershipSessionInformation(PIIVaultModel):
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(
        db_column='partnership_session_information', primary_key=True
    )
    phone_number = models.CharField(max_length=16)
    partner_id = models.BigIntegerField(db_index=True)
    session_id = models.CharField(max_length=255)
    time_session_verified = models.DateTimeField(null=True, blank=True, default=None)
    customer_token = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)

    objects = PartnershipSessionInformationPIIVaultManager()

    class Meta(object):
        db_table = 'partnership_session_information'
        managed = False


class PartnershipTransaction(TimeStampedModel):
    id = models.AutoField(
        db_column='partnership_transaction_id', primary_key=True
    )
    transaction_id = models.CharField(max_length=255)
    partner_transaction_id = models.CharField(max_length=255)
    is_done_inquiry = models.BooleanField(default=False)
    is_done_confirmation = models.BooleanField(default=False)
    customer = BigForeignKey('julo.Customer', models.DO_NOTHING,
                             db_column='customer_id')
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING,
                                db_column='partner_id')
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING,
                         db_column='loan_id', null=True, blank=True)
    reference_num = models.CharField(
        db_column='reference_num', max_length=255, null=True, blank=True
    )

    def save(self, *args, **kwargs):
        super(PartnershipTransaction, self).save(*args, **kwargs)
        if not self.transaction_id:
            transaction_id = '%s%04d' % (self.customer.id, self.id)
            self.update_safely(transaction_id=transaction_id)

    class Meta(object):
        db_table = 'partnership_transaction'


class PartnershipLoanExpectationManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipLoanExpectation(TimeStampedModel):
    id = models.AutoField(
        db_column='partnership_loan_expectation_id', primary_key=True
    )
    partnership_customer_data_id = models.BigIntegerField()
    loan_amount_request = models.IntegerField(
        validators=[MinValueValidator(1000000), MaxValueValidator(20000000)],
        help_text="This value must be  between 1000000 and 20000000"
    )
    loan_duration_request = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="This value must be  between 1 and 12"
    )

    objects = PartnershipLoanExpectationManager()

    class Meta(object):
        db_table = 'partnership_loan_expectation'
        managed = False


class PartnershipLogRetryCheckTransactionStatus(TimeStampedModel):
    id = models.AutoField(
        db_column='partnership_log_retry_transaction_id', primary_key=True
    )
    loan = BigForeignKey(
        'julo.Loan', models.DO_NOTHING,
        db_column='loan_id', null=True, blank=True
    )
    STATUS = (
        (PartnershipLogStatus.IN_PROGRESS, 'In Progress'),
        (PartnershipLogStatus.SUCCESS, 'Success'),
        (PartnershipLogStatus.FAILED, 'Failed'),
    )
    status = models.CharField(
        choices=STATUS, default=PartnershipLogStatus.IN_PROGRESS, max_length=20
    )
    partnership_api_log = models.ForeignKey(
        PartnershipApiLog,
        on_delete=models.DO_NOTHING,
        db_column='partnership_api_log_id',
        blank=True, null=True
    )
    notes = models.CharField(max_length=255, blank=True, null=True)

    class Meta(object):
        db_table = 'partner_log_retry_check_transaction_status'

    def update_status(self, status: str) -> None:
        self.status = status
        self.save(update_fields=['status'])


class PartnershipCustomerCallbackToken(TimeStampedModel):
    id = models.AutoField(
        db_column='partnership_customer_callback_token_id', primary_key=True
    )
    callback_token = models.CharField(max_length=255, default=None, blank=True, null=True)
    callback_url = models.TextField(default=None, blank=True, null=True)
    customer = BigForeignKey('julo.Customer',
                             models.DO_NOTHING, db_column='customer_id')
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING, db_column='partner_id')

    class Meta(object):
        db_table = 'partnership_customer_callback_token'


class PartnershipUserOTPAction(TimeStampedModel):
    id = models.AutoField(db_column='partnership_user_otp_action_id', primary_key=True)
    otp_request = models.BigIntegerField(db_column="partner_otp_action_id", unique=True)
    request_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    otp_service_type = models.CharField(max_length=50, blank=True, null=True)
    action_type = models.CharField(max_length=100, blank=True, null=True)
    is_used = models.BooleanField(default=False)
    action_logs = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'partnership_user_otp_action'

    def __str__(self) -> str:
        return self.request_id if self.request_id else '-'


class PartnershipRepaymentUpload(TimeStampedModel):
    id = models.AutoField(db_column='partnership_repayment_upload_id', primary_key=True)
    application_xid = models.BigIntegerField(default=0)
    payment_amount = models.BigIntegerField(default=0)
    due_date = models.DateField(blank=True, null=True)
    payment_date = models.DateField(blank=True, null=True)
    messages = models.TextField(blank=True, null=True)
    account_payment_id = models.ForeignKey(
        'account_payment.AccountPayment', models.DO_NOTHING,
        db_column='account_payment_id', null=True
    )

    class Meta(object):
        db_table = 'partnership_repayment_upload'


class PartnerLoanSimulations(TimeStampedModel):
    id = models.AutoField(db_column='partner_loan_simulation_id', primary_key=True)
    partnership_config = models.ForeignKey(PartnershipConfig, models.DO_NOTHING,
                                           related_name="loan_simulations",
                                           db_column='partnership_config_id',
                                           blank=True, null=True)
    interest_rate = models.FloatField(help_text="In percentage, if 2% should be 0.02")
    tenure = models.IntegerField(help_text="In months")
    is_active = models.BooleanField(default=True)
    origination_rate = models.FloatField(help_text="In percentage, if 2% should be 0.02")

    class Meta(object):
        db_table = 'partner_loan_simulations'
        verbose_name = 'Partner Loan Simulation'

    def __str__(self) -> str:
        return str(self.partnership_config.id) if self.partnership_config else '-'

    def save(self, *args: Any, **kwargs: Any) -> None:
        partner_co_id_before_updated = self.partnership_config.id
        super().save(*args, **kwargs)
        self.refresh_from_db()
        update_partner_config_id = self.partnership_config.id
        redis_client = get_redis_client()
        if partner_co_id_before_updated == update_partner_config_id:
            partner_key = '%s_%s' % ("partner_simulation_key:", update_partner_config_id)
            redis_client.delete_key(partner_key)
        else:
            updated_partner_key = '%s_%s' % ("partner_simulation_key:", update_partner_config_id)
            redis_client.delete_key(updated_partner_key)
            partner_key = '%s_%s' % ("partner_simulation_key:", partner_co_id_before_updated)
            redis_client.delete_key(partner_key)


class PaylaterTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class PaylaterTransaction(TimeStampedModel):
    id = models.AutoField(
        db_column='paylater_transaction_id', primary_key=True
    )
    partner_reference_id = models.TextField()
    transaction_amount = models.FloatField()
    cart_amount = models.FloatField(default=0,
                                    help_text='This field should be filled based on '
                                              'TransactionDetails price * qty')
    kodepos = models.TextField(blank=True, null=True)
    kabupaten = models.TextField(blank=True, null=True)
    provinsi = models.TextField(blank=True, null=True)
    paylater_transaction_xid = models.BigIntegerField(db_index=True, unique=True)
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING,
                                db_column='partner_id')
    objects = PaylaterTransactionManager()

    class Meta(object):
        db_table = 'paylater_transaction'

    def update_transaction_status(self, status: str) -> None:
        if not hasattr(self, 'paylater_transaction_status'):
            raise ValueError('Paylater Transaction dont have paylater status object')

        self.paylater_transaction_status.transaction_status = status
        self.paylater_transaction_status.save(update_fields=['transaction_status'])


class PaylaterTransactionDetailsManager(GetInstanceMixin, JuloModelManager):
    pass


class PaylaterTransactionDetails(TimeStampedModel):
    id = models.AutoField(
        db_column='paylater_transaction_details_id', primary_key=True
    )
    merchant_name = models.CharField(max_length=255)
    product_name = models.TextField(blank=True, null=True)
    product_qty = models.IntegerField(default=0)
    product_price = models.FloatField()
    paylater_transaction = models.ForeignKey(PaylaterTransaction,
                                             models.DO_NOTHING,
                                             related_name="paylater_transaction_details",
                                             db_column='paylater_transaction_id')
    objects = PaylaterTransactionDetailsManager()

    class Meta(object):
        db_table = 'paylater_transaction_details'


class PaylaterTransactionStatusManager(GetInstanceMixin, JuloModelManager):
    pass


class PaylaterTransactionStatus(TimeStampedModel):
    """
        initiate =  when hit /v1/transaction-details API
        in_progress =  pin or linking success
        success =  loan creation done
        cancel = cancel within 7 or 9 days etc.
    """
    STATUS = (
        (PaylaterTransactionStatuses.INITIATE, 'Initiated'),
        (PaylaterTransactionStatuses.IN_PROGRESS, 'In Progress'),
        (PaylaterTransactionStatuses.SUCCESS, 'Success'),
        (PaylaterTransactionStatuses.CANCEL, 'Cancelled'),
    )
    id = models.AutoField(
        db_column='paylater_transaction_status_id', primary_key=True
    )
    transaction_status = models.CharField(
        choices=STATUS, default=PaylaterTransactionStatuses.INITIATE, max_length=50
    )
    paylater_transaction = models.OneToOneField(PaylaterTransaction,
                                                models.DO_NOTHING,
                                                related_name="paylater_transaction_status",
                                                db_column='paylater_transaction_id')
    objects = PaylaterTransactionStatusManager()

    class Meta(object):
        db_table = 'paylater_transaction_status'


class PreLoginCheckPaylaterManager(GetInstanceMixin, JuloModelManager):
    pass


class PreLoginCheckPaylaterPIIVaultManager(PIIVaultModelManager, PreLoginCheckPaylaterManager):
    pass


class PreLoginCheckPaylater(PIIVaultModel):
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='pre_login_check_paylater_id', primary_key=True)
    phone_number = models.TextField(db_index=True)
    paylater_transaction = models.ForeignKey(PaylaterTransaction,
                                             models.DO_NOTHING,
                                             db_column='paylater_transaction_id',
                                             related_name="pre_login_check_paylaters")
    phone_number_tokenized = models.TextField(null=True, blank=True)

    objects = PreLoginCheckPaylaterPIIVaultManager()

    class Meta(object):
        db_table = 'pre_login_check_paylater'

    def __str__(self):
        """Visual identification"""
        return str(self.id)


class PreLoginCheckPaylaterAttemptManager(GetInstanceMixin, JuloModelManager):
    pass


class PreLoginCheckPaylaterAttempt(TimeStampedModel):
    id = models.AutoField(db_column='pre_login_check_paylater_attempt_id', primary_key=True)
    attempt = models.IntegerField()
    blocked_until = models.DateTimeField(blank=True, null=True)
    pre_login_check_paylater = models.OneToOneField(PreLoginCheckPaylater,
                                                    models.DO_NOTHING,
                                                    db_column='pre_login_check_paylater_id',
                                                    related_name="pre_login_check_paylater_attempt")

    objects = PreLoginCheckPaylaterAttemptManager()

    class Meta(object):
        db_table = 'pre_login_check_paylater_attempt'

    def __str__(self):
        """Visual identification"""
        return str(self.id)


class PaylaterTransactionLoan(TimeStampedModel):
    id = models.AutoField(db_column='paylater_transaction_loan_id', primary_key=True)
    loan = BigOneToOneField(Loan, on_delete=models.DO_NOTHING, db_column='loan_id',
                            related_name='paylater_transaction_loan', blank=True, null=True,)
    paylater_transaction = models.OneToOneField(PaylaterTransaction, on_delete=models.DO_NOTHING,
                                                db_column="paylater_transaction_id",
                                                related_name='transaction_loan')

    class Meta(object):
        db_table = 'paylater_transaction_loan'

    def __str__(self) -> str:
        return str(self.paylater_transaction.id) if self.paylater_transaction else '-'


def upload_to(instance: Any, filename: str) -> str:
    return "image_upload/{0}/{1}".format(instance.pk, filename)


class PartnershipImageManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipImage(S3ObjectModel):
    IMAGE_TYPE_CHOICES = (
        (PartnershipImageType.KTP_SELF, "KTP"),
        (PartnershipImageType.SELFIE, "Selfie"),
        (PartnershipImageType.CROP_SELFIE, "Crop Selfie"),
        (PartnershipImageType.BANK_STATEMENT, "Bank Statement"),
    )
    SERVICE_CHOICES = (
        (PartnershipImageService.S3, "s3"),
        (PartnershipImageService.OSS, "oss"),
    )
    IMAGE_STATUS_CHOICES = (
        (PartnershipImageStatus.INACTIVE, "Inactive"),
        (PartnershipImageStatus.ACTIVE, "Active"),
        (PartnershipImageStatus.RESUBMISSION_REQ, "Resubmission Required"),
    )
    PRODUCT_TYPE_CHOICES = (
        (PartnershipImageProductType.PARTNERSHIP_DEFAULT, "Partnership"),
        (PartnershipImageProductType.EMPLOYEE_FINANCING, "Employee Financing"),
        (PartnershipImageProductType.MF_CSV_UPLOAD, "Merchant Financing CSV Upload"),
        (PartnershipImageProductType.PAYLATER, "Paylater"),
        (PartnershipImageProductType.LEADGEN, "Leadgen"),
        (PartnershipImageProductType.MF_API, "Merchant Financing API"),
        (PartnershipImageProductType.GRAB, "Grab"),
        (PartnershipImageProductType.DANA, "Dana")
    )

    id = models.AutoField(db_column="partnership_image_id", primary_key=True)
    ef_image_source = models.BigIntegerField(
        db_column="ef_image_source", null=True, blank=True
    )
    image_type = models.CharField(
        max_length=50, choices=IMAGE_TYPE_CHOICES, default=PartnershipImageType.KTP_SELF
    )
    url = models.CharField(max_length=200)
    thumbnail_url = models.CharField(max_length=200)
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES, default="oss")
    image_status = models.IntegerField(
        choices=IMAGE_STATUS_CHOICES, default=PartnershipImageStatus.ACTIVE
    )
    image = models.ImageField(
        db_column="internal_path", blank=True, null=True, upload_to=upload_to
    )
    product_type = models.CharField(
        max_length=100,
        choices=PRODUCT_TYPE_CHOICES,
        default=PartnershipImageProductType.PARTNERSHIP_DEFAULT,
    )
    application_image_source = models.BigIntegerField(
        db_column="application_image_source", null=True, blank=True, db_index=True
    )
    loan_image_source = models.BigIntegerField(db_column="loan_image_source", null=True, blank=True)
    user_id = models.BigIntegerField(db_column="user_id", null=True, blank=True)

    class Meta(object):
        db_table = "partnership_image"
        managed = False

    def __str__(self) -> str:
        return "{}_{}".format(self.product_type, str(self.application_image_source))

    objects = PartnershipImageManager()

    @staticmethod
    def full_image_name(image_name: str) -> str:
        path_and_name, extension = os.path.splitext(image_name)
        if not extension:
            extension = ".jpg"
        return path_and_name + extension

    @property
    def image_url(self) -> str:
        if self.service == "oss":
            if self.url == "" or self.url is None:
                return None
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url)
        elif self.service == "s3":
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
            if url == "":
                return None
            return url

    @property
    def public_image_url(self) -> str:
        if self.url == "" or self.url is None:
            return None
        return get_oss_public_url(settings.OSS_PUBLIC_ASSETS_BUCKET, self.url)

    @property
    def image_url_external(self) -> str:
        if self.url == "" or self.url is None:
            return None
        return get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, self.url)


class PaylaterOriginManager(GetInstanceMixin, JuloModelManager):
    pass


class PaylaterOriginPIIVaultManager(PIIVaultModelManager, PaylaterOriginManager):
    pass


class PartnerOrigin(PIIVaultModel):
    PII_FIELDS = ['email', 'phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='paylater_origin_id', primary_key=True)
    partnership_api_log = BigOneToOneField(
        PartnershipApiLog, models.DO_NOTHING, db_column='partnership_api_log_id',
        related_name="partner_origin"
    )
    partner = models.ForeignKey(
        Partner, models.DO_NOTHING, db_column='partner_id',
        related_name="partner_origin_logs"
    )
    partner_origin_name = models.TextField(blank=True, null=True)
    phone_number = models.TextField(blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    application_xid = models.BigIntegerField(db_index=True, blank=True, null=True)
    is_linked = models.NullBooleanField(blank=True, null=True)
    email_tokenized = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)

    objects = PaylaterOriginPIIVaultManager()

    class Meta(object):
        db_table = 'partner_origin'

    def __str__(self) -> str:
        return str(self.id)


class UserActionManager(GetInstanceMixin, JuloModelManager):
    pass


class UserAction(TimeStampedModel):
    STATUS = (
        (PaylaterUserAction.CHECKOUT_INITIATED, 'checkout initiated'),
        (PaylaterUserAction.CREATING_PIN, 'creating pin'),
        (PaylaterUserAction.LONG_FORM_APPLICATION, 'long form application'),
        (PaylaterUserAction.APPLICATION_SUBMISSION, 'application submission'),
        (PaylaterUserAction.ONLY_EMAIL_AND_PHONE_MATCH, 'only email/phone number match'),
        (PaylaterUserAction.TOGGLE_SWITCHED_ON, 'toggle switched on'),
        (PaylaterUserAction.TOGGLE_SWITCHED_OFF, 'toggle switched off'),
        (PaylaterUserAction.LOGIN_SCREEN, 'login screen'),
        (PaylaterUserAction.VERIFY_OTP, 'verify otp'),
        (PaylaterUserAction.LINKING_COMPLETED, 'linking completed'),
        (PaylaterUserAction.INSUFFICIENT_BALANCE, 'insufficient balance'),
        (PaylaterUserAction.SELECT_DURATION, 'select duration'),
        (PaylaterUserAction.TRANSACTION_SUMMARY, 'transaction summary'),
        (PaylaterUserAction.SUCCESSFUL_TRANSACTION, 'successful transaction'),
        (PaylaterUserAction.CANCELLED_TRANSACTION, 'cancelled transaction'),
    )
    id = models.AutoField(
        db_column='session_id', primary_key=True
    )
    application_xid = models.TextField(blank=True, null=True)
    paylater_transaction_xid = models.TextField(blank=True, null=True)
    status = models.CharField(
        choices=STATUS, blank=True, null=True, max_length=100
    )
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING,
                                db_column='partner_id')
    partner_reference_id = models.TextField()
    objects = UserActionManager()

    class Meta(object):
        db_table = 'user_action'


class UserActionHistoryDetailsManager(GetInstanceMixin, JuloModelManager):
    pass


class UserActionHistoryDetails(TimeStampedModel):
    STATUS = (
        (PaylaterUserAction.CHECKOUT_INITIATED, 'checkout initiated'),
        (PaylaterUserAction.CREATING_PIN, 'creating pin'),
        (PaylaterUserAction.LONG_FORM_APPLICATION, 'long form application'),
        (PaylaterUserAction.APPLICATION_SUBMISSION, 'application submission'),
        (PaylaterUserAction.ONLY_EMAIL_AND_PHONE_MATCH, 'only email/phone number match'),
        (PaylaterUserAction.TOGGLE_SWITCHED_ON, 'toggle switched on'),
        (PaylaterUserAction.TOGGLE_SWITCHED_OFF, 'toggle switched off'),
        (PaylaterUserAction.LOGIN_SCREEN, 'login screen'),
        (PaylaterUserAction.VERIFY_OTP, 'verify otp'),
        (PaylaterUserAction.LINKING_COMPLETED, 'linking completed'),
        (PaylaterUserAction.INSUFFICIENT_BALANCE, 'insufficient balance'),
        (PaylaterUserAction.SELECT_DURATION, 'select duration'),
        (PaylaterUserAction.TRANSACTION_SUMMARY, 'transaction summary'),
        (PaylaterUserAction.SUCCESSFUL_TRANSACTION, 'successful transaction'),
        (PaylaterUserAction.CANCELLED_TRANSACTION, 'cancelled transaction'),
    )
    id = models.AutoField(
        db_column='partner_session_history_id', primary_key=True
    )
    session = models.ForeignKey(UserAction,
                                models.DO_NOTHING,
                                related_name="user_action_history_details",
                                db_column='session_id')
    status_old = models.CharField(
        choices=STATUS, blank=True, null=True, max_length=100
    )
    status_new = models.CharField(
        choices=STATUS, blank=True, null=True, max_length=100
    )
    objects = UserActionHistoryDetailsManager()

    class Meta(object):
        db_table = 'user_action_history_details'


class PartnershipUserSessionManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipUserSession(TimeStampedModel):
    STATUS = (
        (PaylaterUserAction.CHECKOUT_INITIATED, 'checkout initiated'),
        (PaylaterUserAction.CREATING_PIN, 'creating pin'),
        (PaylaterUserAction.LONG_FORM_APPLICATION, 'long form application'),
        (PaylaterUserAction.APPLICATION_SUBMISSION, 'application submission'),
        (PaylaterUserAction.ONLY_EMAIL_AND_PHONE_MATCH, 'only email/phone number match'),
        (PaylaterUserAction.TOGGLE_SWITCHED_ON, 'toggle switched on'),
        (PaylaterUserAction.TOGGLE_SWITCHED_OFF, 'toggle switched off'),
        (PaylaterUserAction.LOGIN_SCREEN, 'login screen'),
        (PaylaterUserAction.VERIFY_OTP, 'verify otp'),
        (PaylaterUserAction.LINKING_COMPLETED, 'linking completed'),
        (PaylaterUserAction.INSUFFICIENT_BALANCE, 'insufficient balance'),
        (PaylaterUserAction.SELECT_DURATION, 'select duration'),
        (PaylaterUserAction.TRANSACTION_SUMMARY, 'transaction summary'),
        (PaylaterUserAction.SUCCESSFUL_TRANSACTION, 'successful transaction'),
        (PaylaterUserAction.CANCELLED_TRANSACTION, 'cancelled transaction'),
    )
    id = models.AutoField(
        db_column='session_id', primary_key=True
    )
    application_xid = models.TextField(blank=True, null=True)
    paylater_transaction_xid = models.TextField(blank=True, null=True)
    status = models.CharField(
        choices=STATUS, blank=True, null=True, max_length=100
    )
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING,
                                db_column='partner_id')
    partner_reference_id = models.TextField()
    objects = PartnershipUserSessionManager()

    class Meta(object):
        db_table = 'partnership_user_session'


class PartnershipUserSessionHistoryDetailsManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipUserSessionHistoryDetails(TimeStampedModel):
    STATUS = (
        (PaylaterUserAction.CHECKOUT_INITIATED, 'checkout initiated'),
        (PaylaterUserAction.CREATING_PIN, 'creating pin'),
        (PaylaterUserAction.LONG_FORM_APPLICATION, 'long form application'),
        (PaylaterUserAction.APPLICATION_SUBMISSION, 'application submission'),
        (PaylaterUserAction.ONLY_EMAIL_AND_PHONE_MATCH, 'only email/phone number match'),
        (PaylaterUserAction.TOGGLE_SWITCHED_ON, 'toggle switched on'),
        (PaylaterUserAction.TOGGLE_SWITCHED_OFF, 'toggle switched off'),
        (PaylaterUserAction.LOGIN_SCREEN, 'login screen'),
        (PaylaterUserAction.VERIFY_OTP, 'verify otp'),
        (PaylaterUserAction.LINKING_COMPLETED, 'linking completed'),
        (PaylaterUserAction.INSUFFICIENT_BALANCE, 'insufficient balance'),
        (PaylaterUserAction.SELECT_DURATION, 'select duration'),
        (PaylaterUserAction.TRANSACTION_SUMMARY, 'transaction summary'),
        (PaylaterUserAction.SUCCESSFUL_TRANSACTION, 'successful transaction'),
        (PaylaterUserAction.CANCELLED_TRANSACTION, 'cancelled transaction'),
    )
    id = models.AutoField(
        db_column='partner_session_history_id', primary_key=True
    )
    session = models.ForeignKey(PartnershipUserSession,
                                models.DO_NOTHING,
                                related_name="partnership_user_session_history_details",
                                db_column='session_id')
    status_old = models.CharField(
        choices=STATUS, blank=True, null=True, max_length=100
    )
    status_new = models.CharField(
        choices=STATUS, blank=True, null=True, max_length=100
    )
    objects = PartnershipUserSessionHistoryDetailsManager()

    class Meta(object):
        db_table = 'partnership_user_session_history_details'


class PartnershipJSONWebToken(TimeStampedModel):
    id = BigAutoField(db_column='partnership_json_web_token_id', primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='user_id')
    JWT_TOKEN_TYPE = (
        (PartnershipTokenType.ACCESS_TOKEN, 'access_token'),
        (PartnershipTokenType.REFRESH_TOKEN, 'refresh_token'),
    )
    name = models.CharField(max_length=100, blank=True, null=True)
    partner_name = models.CharField(max_length=100, blank=True, null=True)
    token = models.TextField()
    token_type = models.CharField(choices=JWT_TOKEN_TYPE, max_length=50)
    expired_at = models.DateTimeField(null=True, blank=True)
    is_active = models.NullBooleanField(blank=True, null=True)

    class Meta(object):
        db_table = 'partnership_json_web_token'

    def __str__(self) -> str:
        return self.name


class PartnershipUserManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipUser(TimeStampedModel):
    id = models.AutoField(db_column='partnership_user_id', primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='user_id')
    partner = models.ForeignKey(
        'julo.Partner', models.DO_NOTHING, db_column='partner_id', null=True, blank=True
    )
    role = models.CharField(max_length=50, blank=True, null=True)

    objects = PartnershipUserManager()

    class Meta(object):
        db_table = 'partnership_user'


class PartnershipDistributorManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipDistributorPIIVaultManager(PIIVaultModelManager, PartnershipDistributorManager):
    pass


class PartnershipDistributor(PIIVaultModel):
    PII_FIELDS = ['distributor_bank_account_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='partnership_distributor_id', primary_key=True)
    distributor_id = models.BigIntegerField(db_index=True)
    distributor_name = models.TextField(null=True, blank=True)
    distributor_bank_account_number = models.TextField(null=True, blank=True, db_index=True)
    distributor_bank_account_name = models.TextField(null=True, blank=True)
    bank_code = models.TextField(null=True, blank=True)
    bank_name = models.TextField(null=True, blank=True)
    partner = models.ForeignKey(
        'julo.Partner', models.DO_NOTHING, db_column='partner_id', null=True, blank=True
    )
    is_deleted = models.NullBooleanField()
    bank_account_destination_id = models.BigIntegerField(db_index=True, blank=True, null=True)
    created_by_user_id = models.BigIntegerField(db_index=True, null=True, blank=True)
    distributor_bank_account_number_tokenized = models.TextField(null=True, blank=True)

    objects = PartnershipDistributorPIIVaultManager()

    class Meta(object):
        db_table = 'partnership_distributor'


class PartnershipApplicationFlagManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipApplicationFlag(TimeStampedModel):
    id = BigAutoField(db_column='partnership_application_flag_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    name = models.CharField(max_length=100, db_index=True)

    objects = PartnershipApplicationFlagManager()

    class Meta(object):
        db_table = 'partnership_application_flag'
        managed = False

    def __str__(self) -> str:
        return "application_id_{}".format(self.application_id)


class PartnershipFlowFlagManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipFlowFlag(TimeStampedModel):
    id = BigAutoField(db_column='partnership_flow_flag_id', primary_key=True)
    partner = models.ForeignKey(
        'julo.Partner',
        models.DO_NOTHING,
        related_name='partnership_flow_flags',
        db_column='partner_id'
    )
    name = models.CharField(max_length=100)
    configs = JSONField(blank=True, null=True)

    objects = PartnershipFlowFlagManager()

    class Meta(object):
        db_table = 'partnership_flow_flag'

    def __str__(self) -> str:
        return "partner_id_{}".format(self.partner.id)


class PartnershipProductManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipProduct(TimeStampedModel):
    id = models.AutoField(db_column='partnership_product_id', primary_key=True)
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING, db_column='partner_id')
    product_line = models.ForeignKey(
        'julo.ProductLine', models.DO_NOTHING, db_column='product_line_code'
    )
    product_name = models.CharField(max_length=255)
    product_price = models.BigIntegerField()

    objects = PartnershipProductManager()

    class Meta(object):
        db_table = 'partnership_product'


class PartnershipFeatureSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipFeatureSetting(TimeStampedModel):
    id = models.AutoField(db_column='partnership_feature_setting_id', primary_key=True)

    feature_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)
    parameters = JSONField(blank=True, null=True)
    category = models.CharField(max_length=100)
    description = models.CharField(max_length=200)

    objects = PartnershipFeatureSettingManager()

    class Meta(object):
        db_table = 'partnership_feature_setting'
        managed = False


class PartnershipProductLookupManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipProductLookup(TimeStampedModel):
    id = models.AutoField(db_column='partnership_product_lookup_id', primary_key=True)
    product_name = models.CharField(max_length=100)
    interest_rate = models.FloatField()
    origination_fee_pct = models.FloatField()
    late_fee_pct = models.FloatField()
    cashback_initial_pct = models.FloatField()
    cashback_payment_pct = models.FloatField()
    product_line_id = models.IntegerField(db_index=True)
    product_profile_id = models.IntegerField(db_index=True)
    partner_id = models.IntegerField(db_index=True)
    eligible_amount = models.BigIntegerField(blank=True, null=True)
    eligible_duration = models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    admin_fee = models.IntegerField(blank=True, null=True)

    objects = PartnershipProductLookupManager()

    class Meta(object):
        db_table = 'partnership_product_lookup'
        managed = False

    def __str__(self):
        return self.product_name

    @property
    def monthly_interest_rate(self):
        """interest_rate stored in DB is yearly interest rate"""
        return py2round(old_div(self.interest_rate, 12), 3)

    @property
    def has_cashback(self):
        """have cashback"""
        if self.cashback_initial_pct > 0 or self.cashback_payment_pct > 0:
            return True
        else:
            return False

    @property
    def has_cashback_pmt(self):
        """have payment cashback"""
        if self.cashback_payment_pct > 0:
            return True
        else:
            return False

    @property
    def has_cashback_loan_init(self):
        """have loan init cashback"""
        if self.cashback_initial_pct > 0:
            return True
        else:
            return False

    @property
    def daily_interest_rate(self):
        """interest_rate stored in DB is yearly interest rate"""
        return py2round(self.monthly_interest_rate / 30, 3)


class PartnershipDocumentManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipDocument(S3ObjectModel):
    SERVICE_CHOICES = (('s3', 's3'), ('oss', 'oss'))
    DELETED = -1
    CURRENT = 0
    RESUBMISSION_REQ = 1
    IMAGE_STATUS_CHOICES = (
        (DELETED, 'Deleted'),
        (CURRENT, 'Current'),
        (RESUBMISSION_REQ, 'Resubmission Required'),
    )

    id = models.AutoField(db_column='partnership_document_id', primary_key=True)
    document_source = models.BigIntegerField(db_column='document_source_id', db_index=True)
    url = models.CharField(max_length=200, help_text='url path to the file S3/OSS')
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES, default='oss')
    document_type = models.CharField(max_length=50)
    filename = models.CharField(max_length=200, blank=True, null=True)
    file = models.FileField(
        db_column='internal_path',
        blank=True,
        null=True,
        upload_to=upload_to,
        help_text="path to the file before uploaded to S3/OSS",
    )
    document_status = models.IntegerField(
        blank=True, null=True, choices=IMAGE_STATUS_CHOICES, default=CURRENT
    )
    user_id = models.BigIntegerField(db_column="user_id", null=True, blank=True)

    class Meta(object):
        db_table = 'partnership_document'
        managed = False

    objects = PartnershipDocumentManager()

    @property
    def document_url_api(self):
        if self.service == 'oss':
            if self.url == '' or self.url is None:
                return None
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url)
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
            if url == '':
                return None
            return url

    @property
    def document_url_external(self) -> str:
        if self.url == "" or self.url is None:
            return None
        return get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, self.url)

    @staticmethod
    def full_document_name(document_name):
        path_and_name, extension = os.path.splitext(document_name)
        if not extension:
            extension = '.jpg'
        return path_and_name + extension

    @property
    def image_ext(self):
        name, extension = os.path.splitext(self.url)
        return extension.lower()


class LivenessConfigurationManager(GetInstanceMixin, JuloModelManager):
    pass


class LivenessConfiguration(TimeStampedModel):
    id = BigAutoField(db_column='liveness_configuration_id', primary_key=True)
    partner_id = models.BigIntegerField(db_index=True)
    client_id = models.UUIDField(editable=False, unique=True, db_index=True)
    api_key = models.TextField(blank=True, null=True)
    detection_types = JSONField(blank=True, null=True)
    whitelisted_domain = JSONField(blank=True, null=True)
    provider = models.CharField(max_length=100, blank=True, null=True)
    platform = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='This is used to explain the platform used as web/ios/android',
    )
    is_active = models.BooleanField(default=False)

    objects = LivenessConfigurationManager()

    class Meta(object):
        db_table = 'liveness_configuration'
        managed = False


class LivenessResult(TimeStampedModel):
    id = BigAutoField(db_column='liveness_result_id', primary_key=True)
    liveness_configuration_id = models.BigIntegerField(db_index=True)
    client_id = models.UUIDField(db_index=True)
    image_ids = JSONField(blank=True, null=True)
    platform = models.CharField(
        max_length=100,
        help_text='This is used to explain the platform used as web/ios/android',
    )
    detection_types = models.CharField(
        max_length=100,
        help_text='detection types passive or smile',
    )
    score = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=100, blank=True, null=True)
    reference_id = models.UUIDField(editable=False, unique=True)

    class Meta(object):
        db_table = 'liveness_result'
        managed = False


class LivenessResultMetadata(TimeStampedModel):
    id = BigAutoField(db_column='liveness_result_metadata_id', primary_key=True)
    liveness_result_id = models.BigIntegerField(db_index=True)
    config_applied = JSONField(blank=True, null=True)
    response_data = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'liveness_result_metadata'
        managed = False


class LivenessImageManager(GetInstanceMixin, JuloModelManager):
    pass


class LivenessImage(S3ObjectModel):
    SERVICE_CHOICES = (
        (LivenessImageService.S3, "s3"),
        (LivenessImageService.OSS, "oss"),
    )
    IMAGE_STATUS_CHOICES = (
        (LivenessImageStatus.INACTIVE, "Inactive"),
        (LivenessImageStatus.ACTIVE, "Active"),
        (LivenessImageStatus.RESUBMISSION_REQ, "Resubmission Required"),
    )

    id = models.AutoField(db_column="liveness_image_id", primary_key=True)
    image = models.ImageField(db_column="internal_path", blank=True, null=True, upload_to=upload_to)
    image_type = models.CharField(max_length=50, blank=True, null=True)
    image_status = models.IntegerField(
        choices=IMAGE_STATUS_CHOICES, default=LivenessImageStatus.ACTIVE
    )
    url = models.CharField(max_length=200)
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES, default="oss")
    image_source = models.BigIntegerField(
        db_column="image_source",
        db_index=True,
        help_text='This field is used to establish a relationship with the liveness_result table',
    )

    class Meta(object):
        db_table = "liveness_image"
        managed = False

    objects = LivenessImageManager()

    @staticmethod
    def full_image_name(image_name: str) -> str:
        path_and_name, extension = os.path.splitext(image_name)
        if not extension:
            extension = ".jpg"
        return path_and_name + extension

    @property
    def image_url(self) -> str:
        if self.service == "oss":
            if self.url == "" or self.url is None:
                return None
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url)
        elif self.service == "s3":
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
            if url == "":
                return None
            return url

    @property
    def public_image_url(self) -> str:
        if self.url == "" or self.url is None:
            return None
        return get_oss_public_url(settings.OSS_PUBLIC_ASSETS_BUCKET, self.url)


class PartnershipApplicationFlagHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipApplicationFlagHistory(TimeStampedModel):
    id = BigAutoField(db_column='partnership_application_flag_history_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    old_application_id = models.BigIntegerField(db_index=True)
    status_old = models.CharField(max_length=100, blank=True, null=True)
    status_new = models.CharField(max_length=100, blank=True, null=True)

    objects = PartnershipApplicationFlagHistoryManager()

    class Meta(object):
        db_table = 'partnership_application_flag_history'
        managed = False


class PartnershipClikModelResultManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipClikModelResult(TimeStampedModel):
    id = BigAutoField(db_column='partnership_clik_model_result_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    pgood = models.FloatField()
    status = models.CharField(max_length=100)
    notes = models.TextField(blank=True, null=True)
    metadata = JSONField(blank=True, null=True)

    objects = PartnershipClikModelResultManager()

    class Meta(object):
        db_table = 'partnership_clik_model_result'
        managed = False


class AnaPartnershipNullPartner(TimeStampedModel):
    """
    This table is for retroloading partner maintained by data team
    Data Source from Prisqia Hanifa
    tablle created by Charles Zonaphan, Richard Dharmawan
    <<< PARTNER-4329 6 January 2025 >>>
    covered partner (nex, ayokenalin, cermati)

    this will cover application with partner referral code or partner onelink
    """

    id = models.AutoField(db_column='partnership_null_partner_id', primary_key=True)
    application_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    supposed_partner_id = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = '"ana"."partnership_null_partner"'
        managed = False


class LivenessResultsMapping(TimeStampedModel):
    id = BigAutoField(db_column='liveness_results_mapping_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    liveness_reference_id = models.UUIDField(db_index=True)
    STATUS = (
        (LivenessResultMappingStatus.ACTIVE, 'active'),
        (LivenessResultMappingStatus.INACTIVE, 'inactive'),
    )
    status = models.CharField(
        choices=STATUS, default=LivenessResultMappingStatus.INACTIVE, max_length=20
    )
    detection_type = models.CharField(
        max_length=100,
        help_text='detection types passive or smile',
        blank=True,
        null=True,
    )

    class Meta(object):
        db_table = 'liveness_results_mapping'
        managed = False


class PartnershipLoanAdditionalFeeManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnershipLoanAdditionalFee(TimeStampedModel):
    BORROWER = 'borrower'
    LENDER = 'lender'
    PARTNER = 'partner'
    CHARGED_TO_CHOICES = ((BORROWER, 'Borrower'), (LENDER, 'Lender'), (PARTNER, 'Partner'))

    id = models.AutoField(db_column='partnership_loan_additional_fee_id', primary_key=True)
    loan_id = models.BigIntegerField(db_index=True)
    fee_type = models.CharField(max_length=30)
    fee_amount = models.BigIntegerField()
    charged_to = models.CharField(choices=CHARGED_TO_CHOICES, blank=True, null=True, max_length=20)

    objects = PartnershipLoanAdditionalFeeManager()

    class Meta(object):
        db_table = 'partnership_loan_additional_fee'
        managed = False


class DanaLenderSettlementFileManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaLenderSettlementFile(TimeStampedModel):
    id = BigAutoField(db_column='dana_lender_settlement_file_id', primary_key=True)
    customer_id = models.CharField(max_length=255, blank=True, null=True)
    partner_id = models.CharField(max_length=255, blank=True, null=True)
    lender_product_id = models.CharField(max_length=255, blank=True, null=True)
    partner_reference_no = models.TextField(
        help_text="This partnerReferenceNo from Dana", db_index=True, blank=True, null=True
    )
    txn_type = models.CharField(max_length=255, blank=True, null=True)
    amount = models.BigIntegerField(blank=True, null=True)
    status = models.CharField(max_length=255, blank=True, null=True)
    bill_id = models.CharField(max_length=64, blank=True, null=True)
    due_date = models.DateTimeField(blank=True, null=True)
    period_no = models.CharField(max_length=64, blank=True, null=True)
    credit_usage_mutation = models.BigIntegerField(blank=True, null=True)
    principal_amount = models.BigIntegerField(blank=True, null=True)
    interest_fee_amount = models.BigIntegerField(blank=True, null=True)
    late_fee_amount = models.BigIntegerField(blank=True, null=True)
    total_amount = models.BigIntegerField(blank=True, null=True)
    paid_principal_amount = models.BigIntegerField(blank=True, null=True)
    paid_interest_fee_amount = models.BigIntegerField(blank=True, null=True)
    paid_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    total_paid_amount = models.BigIntegerField(blank=True, null=True)
    trans_time = models.DateTimeField(blank=True, null=True)
    is_partial_refund = models.BooleanField()
    fail_code = models.CharField(max_length=255, blank=True, null=True)
    original_order_amount = models.BigIntegerField(blank=True, null=True)
    original_partner_reference_no = models.TextField(
        help_text="This originalPartnerReferenceNo from Dana", blank=True, null=True
    )
    txn_id = models.TextField(blank=True, null=True)
    waived_principal_amount = models.BigIntegerField(blank=True, null=True)
    waived_interest_fee_amount = models.BigIntegerField(blank=True, null=True)
    waived_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    total_waived_amount = models.BigIntegerField(blank=True, null=True)

    objects = DanaLenderSettlementFileManager()

    class Meta(object):
        db_table = 'dana_lender_settlement_file'
        managed = False
