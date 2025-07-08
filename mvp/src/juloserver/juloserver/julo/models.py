from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import datetime as datetime_module
import json
import logging
import math
import os
import random
import re
import string
import urllib.error
import urllib.parse
import urllib.request
import uuid
from builtins import object, range, str
from collections import Iterable
from datetime import date, datetime, time, timedelta
from enum import Enum
from random import SystemRandom
from juloserver.julo.mixin import GetActiveApplicationMixin

import semver
from ckeditor.fields import RichTextField
from cuser.fields import CurrentUserField
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core import exceptions
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import DatabaseError, models, transaction, connection
from django.db.models import (
    Case,
    CharField,
    Count,
    F,
    IntegerField,
    Max,
    Q,
    Sum,
    Value,
    When,
    ExpressionWrapper,
    DateTimeField,
)
from django.db.models.functions import Coalesce
from django.db.utils import IntegrityError, OperationalError
from django.template.defaultfilters import truncatechars
from django.utils import timezone
from future import standard_library
from model_utils import FieldTracker
from past.builtins import basestring
from past.utils import old_div
from phonenumber_field.modelfields import PhoneNumberField
from rest_framework.serializers import ValidationError
from tinymce.models import HTMLField
from django.contrib.auth.models import User, AbstractUser, UserManager

from juloserver.account.constants import AccountConstant
from juloserver.apiv2.constants import CreditMatrixType
from juloserver.apiv2.models import PdFraudDetection, PdIncomeVerification
from juloserver.application_flow.constants import (
    ApplicationRiskyDecisions,
)
from juloserver.application_flow.models import ApplicationRiskyCheck, MycroftThreshold
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.followthemoney.constants import DocumentType
from juloserver.grab.constants import AccountHaltStatus, grab_rejection_mapping_statuses
from juloserver.julo.constants import (
    MAX_LATE_FEE_RATE,
    AddressPostalCodeConst,
    BucketConst,
    CommsRetryFlagStatus,
    EmailReminderModuleType,
    EmailReminderType,
    FeatureNameConst,
    NewCashbackReason,
    OnboardingIdConst,
    UploadAsyncStateStatus,
    WorkflowConst,
    ApplicationStatusCodes,
    CloudStorage,
)
from juloserver.julo.fields import EmailLowerCaseField
from juloserver.julo.utils import (
    execute_after_transaction_safely,
    get_age_from_timestamp,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
    BigOneToOneField,
)
from juloserver.julocore.data.models import (
    CustomQuerySet,
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.julocore.constants import RedisWhiteList
from juloserver.julocore.python2.utils import py2round
from juloserver.julocore.utils import generate_unique_identifier
from juloserver.moengage.constants import UpdateFields
from juloserver.otp.constants import SessionTokenAction
from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
    TransactionMethodCode,
)
from juloserver.sdk.constants import LIST_PARTNER, PARTNER_PEDE
from juloserver.pii_vault.models import (
    PIIVaultModel,
    PIIVaultPrimeModel,
    PIIVaultModelManager,
    PIIVaultQueryset,
)

from ..application_flow.constants import JuloOne135Related
from .clients import get_julo_pn_client, get_julo_sentry_client, get_s3_url
from .exceptions import JuloException, MaxRetriesExceeded
from .formulas import (
    compute_cashback_monthly,
    compute_cashback_total,
    compute_new_cashback_monthly,
    compute_payment_installment,
)
from .lookups import telco_operator_codes
from .product_lines import ProductLineCodes
from .services2 import get_cashback_service
from .statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from .utils import get_delayed_rejection_time, get_oss_presigned_url, get_oss_public_url
from juloserver.minisquad.constants import CollectionQueue
from juloserver.apiv3.constants import BankNameWithLogo

standard_library.install_aliases()


standard_library.install_aliases()
logger = logging.getLogger(__name__)


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


sentry_client = get_julo_sentry_client()

"""
NOTE:
* We're not using django table naming convention of prefixing the name with the
  the app name. Hence, the override in the model.
* For ProductLookup and StatusLookup, the primary key is overwritten with
  product_code and status_code respectively.
* By convention the name of the variable that represents a foreign key ignores
  the suffix (e.g product for product_code)
"""
ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class NoValidatePhoneNumberField(PhoneNumberField):
    default_validators = []


class StatusChangeModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    status_old = models.IntegerField()
    status_new = models.IntegerField()
    change_reason = models.CharField(default="system_triggered", max_length=100)


class S3ObjectModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    def __str__(self):
        return self.url

    @property
    def s3_bucket(self):
        # The s3 bucket is the first part before the first slash
        bucket = self.url.split('/')[0] if self.url else ''
        logger.debug({
            'url': self.url,
            'bucket': bucket
        })
        return bucket

    def s3_object_path(self, s3_url):
        # The s3 object path is everything after the first slash
        maxsplit = 1
        url_parts = s3_url.split('/', maxsplit) if s3_url else ''

        if len(url_parts) < 2:
            logger.warn({
                'url': s3_url,
                'status': 'object_path_missing'
            })
            return ''

        object_path = url_parts[1]
        logger.debug({
            'url': s3_url,
            'object_path': object_path
        })
        return object_path


class ModelExtensionManager(GetInstanceMixin, JuloModelManager):
    pass


class DeviceManager(GetInstanceMixin, JuloModelManager):
    pass


class Device(TimeStampedModel):
    id = models.AutoField(db_column='device_id', primary_key=True)

    customer = models.ForeignKey(
        'Customer', models.DO_NOTHING, db_column='customer_id')

    gcm_reg_id = models.TextField()
    android_id = models.TextField(blank=True, null=True, db_index=True)
    imei = models.TextField(blank=True)
    device_model_name = models.TextField(blank=True, null=True)
    julo_device_id = models.TextField(blank=True, null=True)
    ios_id = models.TextField(null=True, blank=True)

    objects = DeviceManager()

    class Meta(object):
        db_table = 'device'

    def __str__(self):
        """Visual identification"""
        return self.imei if self.imei is not None else str(self.id)

    @property
    def is_new_customer_device(self):
        device_count = Device.objects.filter(
            customer=self.customer, android_id=self.android_id).count()
        time_limit = timezone.localtime(timezone.now()) - relativedelta(days=1)
        if timezone.localtime(self.cdate) > time_limit and device_count <= 1:
            return True
        return False


class AgentManager(GetInstanceMixin, JuloModelManager):
    pass


class Agent(TimeStampedModel):
    class Meta(object):
        db_table = 'agent'

    def __str__(self):
        """Visual identification"""
        return str(self.user_extension)

    user_extension = models.CharField(max_length=50, blank=True, null=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='auth_user_id')
    is_autodialer_online = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, related_name='%(class)s_created_by')
    inactive_date = models.DateField(null=True, blank=True)
    squad = models.ForeignKey('minisquad.CollectionSquad',
                              on_delete=models.CASCADE,
                              db_column='squad_id',
                              blank=True,
                              null=True)

    objects = AgentManager()

    def get_agent_promo_code(self):
        from juloserver.promo.models import PromoCodeAgentMapping
        agent_promo_mapping = PromoCodeAgentMapping.objects.filter(agent_id=self.id).last()
        return None if not agent_promo_mapping else agent_promo_mapping.promo_code


class QuirosProfileManager(GetInstanceMixin, JuloModelManager):
    pass


class QuirosProfile(TimeStampedModel):
    """To store valid credentials for calling Quiros API"""

    id = models.AutoField(db_column='quiros_profile_id', primary_key=True)
    agent = models.OneToOneField(
        Agent, on_delete=models.DO_NOTHING, db_column='agent_id')

    username = models.CharField(max_length=100)
    password = models.CharField(max_length=100)  # TODO: need to be encrypted
    current_token = models.TextField(blank=True, null=True)
    last_login_time = models.DateTimeField(blank=True, null=True)

    objects = QuirosProfileManager()

    MAX_LAST_LOGIN_HOURS = 24

    class Meta(object):
        db_table = 'quiros_profile'

    @property
    def does_token_need_renewal(self):
        if self.last_login_time is None:
            return True
        time_now = timezone.now()
        since_last_login = relativedelta(time_now, self.last_login_time)
        return since_last_login.hours > QuirosProfile.MAX_LAST_LOGIN_HOURS

    def update_token(self, token, time_now=None):
        self.current_token = token
        if time_now is None:
            time_now = timezone.now()
        self.last_login_time = time_now


class QuirosCallRecord(TimeStampedModel):
    """To store outcome of outbound calls by agents through Quiros"""

    id = models.AutoField(db_column='quiros_call_record_id', primary_key=True)
    agent = models.ForeignKey(
        Agent, on_delete=models.DO_NOTHING, db_column='agent_id')
    skiptrace = models.ForeignKey(
        'Skiptrace', on_delete=models.DO_NOTHING, db_column='skiptrace_id')

    call_id = models.CharField(max_length=100, db_index=True)
    phone_number = NoValidatePhoneNumberField()
    status = models.CharField(max_length=50, blank=True, null=True)
    duration = models.PositiveIntegerField(blank=True, null=True)
    extension = models.CharField(max_length=10, blank=True, null=True)
    created_time = models.DateTimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'quiros_call_record'


class ApplicationQuerySet(PIIVaultQueryset):

    def submitted(self):
        s = StatusLookup.objects.get(status=StatusLookup.FORM_SUBMITTED)
        return self.filter(application_status=s)

    def documents_submitted(self):
        s = StatusLookup.objects.get(status=StatusLookup.DOCUMENTS_SUBMITTED)
        return self.filter(application_status=s)

    def verification_calls_successful(self):
        s = StatusLookup.objects.get(
            status=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL)
        return self.filter(application_status=s)

    def offer_accepted(self):
        s = StatusLookup.objects.get(status=StatusLookup.OFFER_ACCEPTED)
        return self.filter(application_status=s)

    def verification_call_successful(self):
        s = StatusLookup.objects.get(
            status=StatusLookup.VERIFICATION_CALL_SUCCESSFUL)
        return self.filter(application_status=s)

    def activation_call_successful(self):
        status = StatusLookup.objects.get(
            status_code=StatusLookup.ACTIVATION_CALL_SUCCESSFUL_CODE)
        return self.filter(application_status=status)

    def offer_made(self):
        status = StatusLookup.objects.get(
            status_code=StatusLookup.OFFER_MADE_TO_CUSTOMER_CODE)
        return self.filter(application_status=status)

    def with_sphp_info(self):
        status = StatusLookup.VERIFICATION_CALLS_SUCCESSFUL_CODE
        return self.filter(application_status__status_code__gte=status)

    def resubmission_requested(self):
        status = StatusLookup.objects.get(
            status_code=StatusLookup.APPLICATION_RESUBMISSION_REQUESTED_CODE)
        return self.filter(application_status=status)

    def autodialer_predictive_missed_called(self, status_code, order_args=[]):
        if status_code == 122:
            qs = self.annotate(
                is_priority=Max(
                    Case(
                        When(
                            autodialer122queue__auto_call_result_status__in=['answered', 'busy'],
                            autodialer122queue__is_agent_called=False,
                            then=1
                        ),
                        default=0,
                        output_field=CharField()
                    )
                )

            )
        else:
            qs = self.annotate(
                is_priority=Max(
                    Case(
                        When(
                            predictivemissedcall__auto_call_result_status__in=['answered', 'busy'],
                            predictivemissedcall__application_status=status_code,
                            predictivemissedcall__is_agent_called=False,
                            then=1
                        ),
                        default=0,
                        output_field=CharField()
                    )
                )
            )

        return qs.order_by('-is_priority', *order_args)

    def active_account(self):
        return self.filter(application_status_id__in=ApplicationStatusCodes.active_account())


class ApplicationManager(GetInstanceMixin, PIIVaultModelManager):

    def get_queryset(self):
        return ApplicationQuerySet(self.model)

    def offer_made(self):
        return self.get_queryset().offer_made()

    def activation_call_successful(self):
        return self.get_queryset().activation_call_successful()

    def create(self, *args, **kwargs):
        application = super(ApplicationManager, self).create(*args, **kwargs)
        application.generate_xid()
        application.save(update_fields=["application_xid"])
        return application

    def autodialer_uncalled_app(
        self, status_code, locked_list, is_julo_one=None, is_pmc=False
    ):
        qs = self.get_queryset()\
            .exclude(id__in=locked_list)\
            .exclude(partner__name__in=LIST_PARTNER)\
            .filter(application_status_id=status_code)

        if is_julo_one is not None:
            if is_julo_one:
                qs = qs.filter(workflow__name=WorkflowConst.JULO_ONE)
            else:
                qs = qs.exclude(workflow__name=WorkflowConst.JULO_ONE)

        # get latest change status history to status code to get the oldest app in bucket
        # get application that doesn't has autodialer session in status_code
        qs = qs.annotate(
            latest_change_status=Max('applicationhistory__cdate'),
            session_count=Count(
                Case(
                    When(autodialersession__status=status_code,
                         autodialersession__next_session_ts__isnull=False,
                         then=1),
                    output_field=CharField()
                )
            ),
        ).filter(
            Q(session_count=0)
            | Q(autodialersession__isnull=True)
        )

        # Old application status, MTL, STL product
        if status_code == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            today = timezone.now()
            today_minus_14 = today - timedelta(days=14)
            today_minus_28 = today - timedelta(days=28)
            start_date = datetime.combine(today_minus_28, time.min)
            end_date = datetime.combine(today_minus_14, time.max)
            dpd_min_5 = today.date() + timedelta(days=5)
            qs = qs.select_related('loan__offer', 'loan__loan_status').filter(
                is_courtesy_call=False,
                loan__loan_status__status_code__range=(
                    LoanStatusCodes.CURRENT, LoanStatusCodes.RENEGOTIATED),
                loan__fund_transfer_ts__range=[start_date, end_date],
                loan__offer__first_payment_date__gt=dpd_min_5)

        order_args = ['latest_change_status']
        if status_code == ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING:
            if qs:
                application_note = (
                    ApplicationNote.objects.values('application_id')
                    .annotate(Max('udate'))
                    .filter(
                        application_id=qs.first().id,
                    )
                    .last()
                )
                if application_note:
                    qs = (
                        qs.annotate(
                            max_udate_application_note=ExpressionWrapper(
                                Coalesce(application_note['udate__max'], None),
                                output_field=DateTimeField(),
                            )
                        )
                        .order_by('-max_udate_application_note')
                    )

                    order_args = ['max_udate_application_note']

        if is_pmc:
            return qs.autodialer_predictive_missed_called(status_code, order_args).first()

        return qs.order_by(*order_args).first()

    def autodialer_recalled(
        self, status_code, locked_list, is_julo_one=None, is_pmc=False, is_fast_forward=False
    ):
        qs = self.get_queryset()\
            .exclude(id__in=locked_list)\
            .filter(application_status_id=status_code)

        if is_julo_one is not None:
            if is_julo_one:
                qs = qs.filter(workflow__name=WorkflowConst.JULO_ONE)
            else:
                qs = qs.exclude(workflow__name=WorkflowConst.JULO_ONE)

        current_time = timezone.localtime(timezone.now())

        session_next_session_q = Q(autodialersession__next_session_ts__lte=current_time)
        if is_fast_forward:
            session_next_session_q = Q(autodialersession__next_session_ts__gt=current_time)

        qs = qs.filter(
            Q(autodialersession__status=status_code)
            & Q(autodialersession__failed_count__gte=0)
            & Q(autodialersession__next_session_ts__isnull=False)
            & session_next_session_q
        )

        order_args = ['autodialersession__next_session_ts']
        if is_pmc:
            return qs.autodialer_predictive_missed_called(status_code, order_args).first()

        return qs.order_by(*order_args).first()

    def regular_not_deletes(self):
        return self.get_queryset().filter(
            customer_credit_limit__isnull=True).exclude(is_deleted=True)

    def get_active_julo_product_applications(self):
        return (
            self.get_queryset()
            .filter(
                application_status_id__gte=ApplicationStatusCodes.LOC_APPROVED,
                product_line__product_line_code__in=ProductLineCodes.julo_product(),
            )
            .exclude(is_deleted=True)
        )


class ApplicationTemplate(TimeStampedModel):
    GENDER_CHOICES = (
        ('Pria', 'Pria'),
        ('Wanita', 'Wanita'))
    HOME_STATUS_CHOICES = (
        ('Mess karyawan', 'Mess karyawan'),
        ('Kontrak', 'Kontrak'),
        ('Kos', 'Kos'),
        ('Milik orang tua', 'Milik orang tua'),
        ('Milik keluarga', 'Milik keluarga'),
        ('Milik sendiri, lunas', 'Milik sendiri, lunas'),
        ('Milik sendiri, mencicil', 'Milik sendiri, mencicil'),
        ('Lainnya', 'Lainnya'))
    MARITAL_STATUS_CHOICES = (
        ('Lajang', 'Lajang'),
        ('Menikah', 'Menikah'),
        ('Cerai', 'Cerai'),
        ('Janda / duda', 'Janda / duda'))
    KIN_GENDER_CHOICES = (
        ('Pria', 'Pria'),
        ('Wanita', 'Wanita'))
    KIN_RELATIONSHIP_CHOICES = (
        ('Orang tua', 'Orang tua'),
        ('Saudara kandung', 'Saudara kandung'),
        ('Famili lainnya', 'Famili lainnya'))
    JOB_TYPE_CHOICES = (
        ('Pegawai swasta', 'Pegawai swasta'),
        ('Pegawai negeri', 'Pegawai negeri'),
        ('Pengusaha', 'Pengusaha'),
        ('Freelance', 'Freelance'),
        ('Pekerja rumah tangga', 'Pekerja rumah tangga'),
        ('Lainnya', 'Lainnya'),
        ('Staf rumah tangga', 'Staf rumah tangga'),
        ('Ibu rumah tangga', 'Ibu rumah tangga'),
        ('Mahasiswa', 'Mahasiswa'),
        ('Tidak bekerja', 'Tidak bekerja'))
    LAST_EDUCATION_CHOICES = (
        ('SD', 'SD'),
        ('SLTP', 'SLTP'),
        ('SLTA', 'SLTA'),
        ('Diploma', 'Diploma'),
        ('S1', 'S1'),
        ('S2', 'S2'),
        ('S3', 'S3'))
    VEHICLE_TYPE_CHOICES = (
        ('Sepeda motor', 'Sepeda motor'),
        ('Mobil', 'Mobil'),
        ('Lainnya', 'Lainnya'),
        ('Tidak punya', 'Tidak punya'))
    VEHICLE_OWNERSHIP_CHOICES = (
        ('Lunas', 'Lunas'),
        ('Mencicil', 'Mencicil'),
        ('Diagunkan', 'Diagunkan'),
        ('Lainnya', 'Lainnya'),
        ('Tidak punya', 'Tidak punya'))
    GMAIL_SCRAPED_CHOICES = (('Not scraped', 'Not scraped'),
                             ('Working', 'Working'),
                             ('Done', 'Done'))

    DIALECT_CHOICES = (
        ('Bahasa Jawa', 'Bahasa Jawa'),
        ('Bahasa Melayu', 'Bahasa Melayu'),
        ('Bahasa Sunda', 'Bahasa Sunda'),
        ('Bahasa Madura', 'Bahasa Madura'),
        ('Bahasa Batak', 'Bahasa Batak'),
        ('Bahasa Minangkabau', 'Bahasa Minangkabau'),
        ('Bahasa Bugis', 'Bahasa Bugis'),
        ('Bahasa Aceh', 'Bahasa Aceh'),
        ('Bahasa Bali', 'Bahasa Bali'),
        ('Bahasa Banjar', 'Bahasa Banjar'),
        ('Lainnya', 'Lainnya'),
        ('Tidak ada', 'Tidak ada')
    )
    PII_FIELDS = ['fullname', 'ktp', 'email', 'mobile_phone_1', 'name_in_bank']

    SPHP_EXPIRATION_DAYS = 3

    id = models.AutoField(db_column='application_id', primary_key=True)

    customer = models.ForeignKey(
        'Customer', models.DO_NOTHING, db_column='customer_id')
    device = models.ForeignKey(
        'Device', models.DO_NOTHING, db_column='device_id', blank=True, null=True)
    application_status = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='application_status_code',
        blank=True, null=True)
    product_line = models.ForeignKey(
        'ProductLine', models.DO_NOTHING, db_column='product_line_code', blank=True, null=True)
    partner = models.ForeignKey(
        'Partner', models.DO_NOTHING, db_column='partner_id',
        blank=True, null=True)
    mantri = models.ForeignKey(
        'Mantri', models.DO_NOTHING, db_column='mantri_id',
        blank=True, null=True)
    line_of_credit = models.ForeignKey(
        'line_of_credit.LineOfCredit', models.DO_NOTHING, db_column='line_of_credit_id',
        blank=True, null=True)

    loan_amount_request = models.BigIntegerField(blank=True, null=True)
    loan_duration_request = models.IntegerField(blank=True, null=True)
    validated_qr_code = models.BooleanField(default=False, blank=True)
    loan_duration_request = models.IntegerField(blank=True, null=True)
    loan_purpose = models.CharField("Tujuan pinjaman", max_length=100, blank=True, null=True)
    loan_purpose_desc = models.TextField(
        blank=True, null=True
    )
    marketing_source = models.CharField("Dari mana tahu",
                                        max_length=100,
                                        validators=[ascii_validator],
                                        blank=True, null=True)
    payday = models.IntegerField(
        blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(31)])
    referral_code = models.CharField(max_length=20, blank=True, null=True,
                                     validators=[ascii_validator])
    is_own_phone = models.NullBooleanField()

    fullname = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    birth_place = models.CharField(max_length=100, validators=[
                                   ascii_validator], blank=True, null=True)
    gender = models.CharField("Jenis kelamin",
                              choices=GENDER_CHOICES,
                              max_length=10,
                              validators=[ascii_validator],
                              blank=True, null=True)
    ktp = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ],
        blank=True, null=True,
        db_index=True
    )

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
    address_detail = models.CharField(null=True, blank=True, max_length=100,
                                      validators=[ascii_validator])

    occupied_since = models.DateField(blank=True, null=True)
    home_status = models.CharField("Status domisili",
                                   choices=HOME_STATUS_CHOICES,
                                   max_length=50,
                                   validators=[ascii_validator],
                                   blank=True, null=True)
    landlord_mobile_phone = models.CharField(max_length=50, blank=True, null=True,
                                             validators=[
                                                 ascii_validator,
                                                 RegexValidator(
                                                     regex='^\+?\d{10,15}$',
                                                     message='mobile phone has to be 10 to 15 numeric digits')
                                             ])
    mobile_phone_1 = models.CharField(max_length=50, blank=True, null=True,
                                      validators=[
                                          ascii_validator,
                                          RegexValidator(
                                              regex='^\+?\d{10,15}$',
                                              message='mobile phone has to be 10 to 15 numeric digits')
                                      ])
    new_mobile_phone = models.CharField(max_length=50, blank=True, null=True,
                                        validators=[
                                            ascii_validator,
                                            RegexValidator(
                                                regex='^\+?\d{10,15}$',
                                                message='mobile phone has to be 10 to 15 numeric digits')
                                        ])

    has_whatsapp_1 = models.NullBooleanField(blank=True, null=True)
    mobile_phone_2 = models.CharField(max_length=50, blank=True, null=True,
                                      validators=[
                                          ascii_validator,
                                          RegexValidator(
                                              regex='^\+?\d{10,15}$',
                                              message='mobile phone has to be 10 to 15 numeric digits')
                                      ])
    has_whatsapp_2 = models.NullBooleanField()
    email = models.EmailField(blank=True, null=True)
    bbm_pin = models.CharField(max_length=50, blank=True, null=True,
                               validators=[ascii_validator])
    twitter_username = models.CharField(max_length=50, blank=True, null=True,
                                        validators=[ascii_validator])
    instagram_username = models.CharField(max_length=50, blank=True, null=True,
                                          validators=[ascii_validator])
    marital_status = models.CharField("Status sipil",
                                      choices=MARITAL_STATUS_CHOICES,
                                      max_length=50,
                                      validators=[ascii_validator],
                                      blank=True, null=True)
    dependent = models.IntegerField(
        "Jumlah tanggungan",
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        blank=True, null=True)
    spouse_name = models.CharField(max_length=100, blank=True, null=True,
                                   validators=[ascii_validator])
    spouse_dob = models.DateField(blank=True, null=True)
    spouse_mobile_phone = models.CharField(max_length=50, blank=True, null=True,
                                           validators=[
                                               ascii_validator,
                                               RegexValidator(
                                                   regex='^\+?\d{10,15}$',
                                                   message='mobile phone has to be 10 to 15 numeric digits')
                                           ])
    spouse_has_whatsapp = models.NullBooleanField()
    kin_name = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    kin_dob = models.DateField(blank=True, null=True)

    kin_gender = models.CharField("Jenis kelamin kerabat",
                                  choices=KIN_GENDER_CHOICES,
                                  max_length=10,
                                  blank=True, null=True,
                                  validators=[ascii_validator])
    kin_mobile_phone = models.CharField(max_length=50, blank=True, null=True,
                                        validators=[
                                            ascii_validator,
                                            RegexValidator(
                                                regex='^\+?\d{10,15}$',
                                                message='mobile phone has to be 10 to 15 numeric digits')
                                        ])
    kin_relationship = models.CharField("Hubungan kerabat",
                                        choices=KIN_RELATIONSHIP_CHOICES,
                                        max_length=50,
                                        validators=[ascii_validator],
                                        blank=True, null=True)
    is_kin_approved = models.SmallIntegerField(blank=True, null=True)
    kin_consent_code = models.CharField(max_length=10, blank=True, null=True)
    close_kin_name = models.CharField(max_length=100, validators=[
                                      ascii_validator], blank=True, null=True)
    close_kin_mobile_phone = models.CharField(max_length=50, blank=True, null=True,
                                              validators=[
                                                  ascii_validator,
                                                  RegexValidator(
                                                      regex='^\+?\d{10,15}$',
                                                      message='mobile phone has to be 10 to 15 numeric digits')
                                              ])
    close_kin_relationship = models.CharField("Hubungan kerabat",
                                              choices=KIN_RELATIONSHIP_CHOICES,
                                              max_length=50,
                                              validators=[ascii_validator],
                                              blank=True, null=True)
    job_type = models.CharField("Tipe pekerjaan",
                                choices=JOB_TYPE_CHOICES,
                                max_length=50,
                                validators=[ascii_validator],
                                blank=True, null=True)
    job_industry = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    job_function = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    job_description = models.CharField(max_length=100, blank=True, null=True,
                                       validators=[ascii_validator])
    company_name = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    company_phone_number = models.CharField(max_length=50, blank=True, null=True,
                                            validators=[
                                                ascii_validator,
                                                RegexValidator(
                                                    regex='^\+?\d{6,15}$',
                                                    message='phone has to be 6 to 15 numeric digits')
                                            ])
    work_kodepos = models.CharField(max_length=5,
                                    blank=True,
                                    null=True,
                                    validators=[
                                        ascii_validator,
                                        RegexValidator(
                                            regex='^[0-9]{5}$',
                                            message='Kode pos has to be 5 numeric digits')
                                    ])
    job_start = models.DateField(blank=True, null=True)
    monthly_income = models.BigIntegerField(blank=True, null=True)
    income_1 = models.BigIntegerField(blank=True, null=True)
    income_2 = models.BigIntegerField(blank=True, null=True)
    income_3 = models.BigIntegerField(blank=True, null=True)

    last_education = models.CharField("Pendidikan terakhir",
                                      choices=LAST_EDUCATION_CHOICES,
                                      max_length=50,
                                      validators=[ascii_validator],
                                      blank=True, null=True)
    college = models.CharField(max_length=100, blank=True, null=True,
                               validators=[ascii_validator])
    major = models.CharField(max_length=100, blank=True, null=True,
                             validators=[ascii_validator])
    graduation_year = models.IntegerField(blank=True, null=True)
    gpa = models.FloatField(blank=True, null=True)

    has_other_income = models.BooleanField(default=False)
    other_income_amount = models.BigIntegerField(blank=True, null=True)
    other_income_source = models.CharField(max_length=250, blank=True, null=True,
                                           validators=[ascii_validator])
    monthly_housing_cost = models.BigIntegerField(blank=True, null=True)
    monthly_expenses = models.BigIntegerField(blank=True, null=True)
    total_current_debt = models.BigIntegerField(blank=True, null=True)

    vehicle_type_1 = models.CharField(
        "Kendaraan pribadi 1",
        choices=VEHICLE_TYPE_CHOICES,
        max_length=50,
        validators=[ascii_validator],
        blank=True, null=True)
    vehicle_ownership_1 = models.CharField("Kepemilikan 1",
                                           choices=VEHICLE_OWNERSHIP_CHOICES,
                                           max_length=50,
                                           blank=True, null=True,
                                           validators=[ascii_validator])

    bank_name = models.CharField(max_length=250, validators=[ascii_validator],
                                 blank=True, null=True)
    bank_branch = models.CharField(max_length=100, validators=[ascii_validator],
                                   blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, validators=[ascii_validator],
                                           blank=True, null=True)
    name_in_bank = models.CharField(max_length=100, validators=[ascii_validator],
                                    blank=True, null=True)

    is_term_accepted = models.BooleanField(default=False)
    is_verification_agreed = models.BooleanField(default=False)
    is_document_submitted = models.NullBooleanField()
    is_sphp_signed = models.NullBooleanField()
    sphp_exp_date = models.DateField(blank=True, null=True)
    application_xid = models.BigIntegerField(blank=True, null=True, db_index=True)
    app_version = models.CharField(
        max_length=10,
        blank=True, null=True,
        validators=[ascii_validator])
    web_version = models.CharField(
        max_length=10,
        blank=True, null=True,
        validators=[ascii_validator])
    application_number = models.IntegerField(blank=True, null=True)
    gmail_scraped_status = models.CharField(
        max_length=15,
        choices=GMAIL_SCRAPED_CHOICES,
        default='Not scraped',
        validators=[ascii_validator])
    is_courtesy_call = models.NullBooleanField(default=False)
    hrd_name = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    company_address = models.CharField(max_length=100, validators=[ascii_validator],
                                       blank=True, null=True)
    number_of_employees = models.IntegerField(blank=True, null=True)
    position_employees = models.CharField(max_length=100, validators=[ascii_validator],
                                          blank=True, null=True)
    employment_status = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    billing_office = models.CharField(max_length=100, validators=[ascii_validator],
                                      blank=True, null=True)
    mutation = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    workflow = models.ForeignKey(
        'Workflow', models.DO_NOTHING, db_column='workflow_id', null=True, blank=True)
    dialect = models.CharField("Bahasa sehari-hari",
                               choices=DIALECT_CHOICES,
                               max_length=50,
                               validators=[ascii_validator],
                               blank=True, null=True)
    teaser_loan_amount = models.BigIntegerField(blank=True, null=True)
    customer_credit_limit = models.ForeignKey(
        'paylater.CustomerCreditLimit', models.DO_NOTHING, db_column='customer_credit_limit_id', null=True, blank=True)
    is_deleted = models.NullBooleanField()
    status_path_locked = models.IntegerField(blank=True, null=True)
    additional_contact_1_name = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True)
    additional_contact_1_number = models.CharField(max_length=50, blank=True, null=True,
                                                   validators=[
                                                       ascii_validator,
                                                       RegexValidator(
                                                           regex='^\+?\d{10,15}$',
                                                           message='mobile phone has to be 10 to 15 numeric digits')
                                                   ])
    additional_contact_2_name = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True)
    additional_contact_2_number = models.CharField(max_length=50, blank=True, null=True,
                                                   validators=[
                                                       ascii_validator,
                                                       RegexValidator(
                                                           regex='^\+?\d{10,15}$',
                                                           message='mobile phone has to be 10 to 15 numeric digits')
                                                   ])
    loan_purpose_description_expanded = models.TextField(blank=True, null=True,
                                                         validators=[MaxLengthValidator(500)])
    is_fdc_risky = models.NullBooleanField()
    address_same_as_ktp = models.NullBooleanField()
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True)
    name_bank_validation = models.ForeignKey(
        'disbursement.NameBankValidation', models.DO_NOTHING, db_column='name_bank_validation_id',
        null=True)
    merchant = models.ForeignKey(
        'merchant_financing.Merchant', models.DO_NOTHING,
        db_column='merchant_id', null=True, blank=True)
    bss_eligible = models.NullBooleanField()
    sphp_general_ts = models.DateTimeField(null=True, blank=True)
    company = models.ForeignKey(
        'employee_financing.Company', models.DO_NOTHING, db_column='company_id',
        null=True, blank=True
    )
    onboarding = models.ForeignKey(
        'julo.Onboarding', models.DO_NOTHING, db_column='onboarding_id', null=True)
    is_assisted_selfie = models.NullBooleanField()
    email_tokenized = models.CharField(max_length=50, null=True, blank=True)
    fullname_tokenized = models.CharField(max_length=50, null=True, blank=True)
    ktp_tokenized = models.CharField(max_length=50, null=True, blank=True)
    mobile_phone_1_tokenized = models.CharField(max_length=50, null=True, blank=True)
    name_in_bank_tokenized = models.CharField(max_length=50, null=True, blank=True)

    class Meta(object):
        abstract = True

    @property
    def gender_mintos(self):
        if self.gender == 'Pria':
            return 'M'

        return 'F'

    @property
    def customer_mother_maiden_name(self):
        if self.customer and self.customer.mother_maiden_name:
            return self.customer.mother_maiden_name

        return None

    @property
    def yearly_income(self):
        return self.monthly_income * 12


class Application(PIIVaultPrimeModel, ApplicationTemplate):
    objects = ApplicationManager()
    tracker = FieldTracker(fields=['application_status_id', 'address_kodepos', 'account_id'])

    class Meta(object):
        db_table = 'application'

    def __init__(self, *args, **kwargs):
        super(Application, self).__init__(*args, **kwargs)

        # Store the last risky check query to class property, so make it available in instance call
        self._last_risky_check = None

        self._has_pass_hsfbp = None
        self._has_pass_sonic = None

    def __str__(self):
        """Visual identification"""
        if not self.customer.email:
            self.customer.email = ''

        return " - ".join([str(self.id), self.customer.email])

    @property
    def status(self):
        return self.application_status_id

    @property
    def product_line_code(self):
        return self.product_line_id

    @property
    def is_warning(self):
        query = PdFraudDetection.objects.filter(application_id=self.id)
        query = query.filter(self_field_name__in=['fullname+dob', 'geo location'])
        if query.exists():
            return True
        for income_ver in PdIncomeVerification.objects.filter(application_id=self.id):
            if income_ver.yes_no_income == 'unverified':
                return True
        return False

    @property
    def is_onboarding_form(self):
        if not self.app_version:
            return False
        return semver.match(self.app_version, '>=7.0.0')

    def change_status(self, status_code):
        previous_status = self.application_status
        new_status = StatusLookup.objects.get(status_code=status_code)
        logger.info({
            'previous_status': previous_status.status_code,
            'new_status': new_status.status_code,
            'action': 'changing_status',
            'application_id': self.id
        })
        self.application_status = new_status

    def change_status_old(self, status_name):
        """DEPRECATED: use change_status"""
        application_status = StatusLookup.objects.get(status=status_name)
        self.application_status = application_status
        self.save()
        logger.info("Application id=%s marked with status=%s" % (
            self.id, application_status.status))

    def mark_documents_submitted(self):
        """DEPRECATED"""
        self.change_status_old(StatusLookup.DOCUMENTS_SUBMITTED)

    def mark_offer_accepted(self):
        """DEPRECATED"""
        self.change_status_old(StatusLookup.OFFER_ACCEPTED)

    def mark_verification_call_successful(self):
        """DEPRECATED"""
        self.change_status_old(StatusLookup.VERIFICATION_CALL_SUCCESSFUL)

    def mark_activation_call_successful(self):
        """DEPRECATED"""
        self.change_status_old(StatusLookup.ACTIVATION_CALL_SUCCESSFUL)

    def mark_legal_agreement_signed(self):
        """DEPRECATED"""
        self.change_status_old(StatusLookup.LEGAL_AGREEMENT_SIGNED)

    def check_status(self, status_code):
        status_to_check = StatusLookup.objects.get(status_code=status_code)
        status_correct = True
        if self.application_status != status_to_check:
            logger.debug({
                'status_to_check': status_to_check,
                'application_status': self.application_status,
                'status': 'not_correct'
            })
            status_correct = False
        return status_correct

    def can_mark_document_submitted(self):
        can_mark = False

        if self.check_status(ApplicationStatusCodes.FORM_PARTIAL):
            can_mark = True
        if self.check_status(ApplicationStatusCodes.FORM_SUBMITTED):
            can_mark = True
        if self.check_status(ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED):
            can_mark = True
        return can_mark

    def can_mark_sphp_signed(self):
        can_mark = False
        if self.check_status(ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL):
            can_mark = True
        if self.check_status(ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED):
            can_mark = True
        # TODO: more checks can be done here
        return can_mark

    def generate_xid(self):
        if self.id is None or self.application_xid is not None:
            return
        if self.is_regular_julo_one():
            from juloserver.julo.tasks import store_new_xid_task
            execute_after_transaction_safely(
                lambda: store_new_xid_task.apply_async(
                    (self.id,), countdown=settings.DELAY_FOR_REALTIME_EVENTS)
            )
        elif self.is_dana_flow():
            # Handle for dana user, and put this to new elif
            # Because this we want to isolated different flow from dana and J1

            if not self.application_xid:
                from juloserver.julo.tasks import store_new_xid_task
                execute_after_transaction_safely(
                    lambda: store_new_xid_task.apply_async(
                        (self.id,), countdown=3)
                )
        else:
            self.application_xid = XidLookup.get_new_xid()

    @property
    def sphp_expired(self):
        expired = False
        today = date.today()
        expired_time_delta = today - self.sphp_exp_date
        expired_days = expired_time_delta.days
        if expired_days > 0:
            expired = True
        logger.debug({
            'today': today,
            'offer_expiration_date': self.sphp_exp_date,
            'days_before_expire': -expired_days,
            'expired': expired
        })
        return expired

    def set_sphp_expiration_date(self):
        today = date.today()
        expiration_time_delta = timedelta(days=self.SPHP_EXPIRATION_DAYS)
        sphp_expiration_date = today + expiration_time_delta
        self.sphp_exp_date = sphp_expiration_date
        logger.debug({
            'validity_days': expiration_time_delta.days,
            'sphp_expiration_date': sphp_expiration_date,
            'status': 'set'
        })

    @property
    def basic_financial(self):
        income = self.monthly_income if self.monthly_income else 0
        housing_cost = self.monthly_housing_cost if self.monthly_housing_cost else 0
        expenses = self.monthly_expenses if self.monthly_expenses else 0
        debt = self.total_current_debt if self.total_current_debt else 0

        savings_margin = income - housing_cost - expenses - debt
        logger.debug({
            'income': income,
            'housing_cost': housing_cost,
            'expenses': expenses,
            'debt': debt,
            'savings_margin': savings_margin
        })
        return savings_margin

    @property
    def basic_installment(self):
        _, _, monthly_installment = compute_payment_installment(
            self.loan_amount_request,
            self.loan_duration_request,
            self.default_interest_rate)

        return monthly_installment

    @property
    def basic_installment_discount(self):
        installment_discount = 0.20
        monthly_installment = self.basic_installment
        return monthly_installment * (1 - installment_discount)

    @property
    def dti_capacity(self):
        if self.monthly_income:
            return float(self.monthly_income * self.dti_multiplier)
        return None

    @property
    def default_interest_rate(self):
        if self.product_line_id in ProductLineCodes.mtl():
            return 0.03
        elif self.product_line_id in ProductLineCodes.stl():
            return 0.10
        elif self.product_line_id in ProductLineCodes.ctl():
            return None
        elif self.product_line_id in ProductLineCodes.bri():
            return 0.04
        elif self.product_line_id in ProductLineCodes.grab():
            return 0.00
        elif self.product_line_id in ProductLineCodes.loc():
            return 0.00
        elif self.product_line_id in ProductLineCodes.grabfood():
            return 0.00
        elif self.product_line_id in ProductLineCodes.laku6():
            return 0.04
        elif self.product_line_id in ProductLineCodes.icare():
            return 0.025
        if self.product_line_id in ProductLineCodes.pedemtl():
            return 0.03
        elif self.product_line_id in ProductLineCodes.pedestl():
            return 0.10
        elif self.product_line_id in ProductLineCodes.julo_one():
            return 0.00
        elif self.product_line_id in ProductLineCodes.merchant_financing():
            return 0.00
        elif self.product_line_id in ProductLineCodes.employee_financing():
            return 0.00
        elif self.product_line_id in ProductLineCodes.DANA:
            return 0.00
        else:
            raise JuloException("Expected product line MTL, STL, CTL, BRI, GRAB, MF or EF")

    @property
    def dti_multiplier(self):
        if self.product_line:
            return self.product_line.product_profile.debt_income_ratio

    @property
    def complete_addresses(self):
        if self.address_street_num and self.address_kodepos:
            addrs = "%s, %s, %s, %s, %s, %s" % (self.address_street_num,
                                                self.address_kelurahan,
                                                self.address_kecamatan,
                                                self.address_kabupaten,
                                                self.address_provinsi,
                                                self.address_kodepos)
            return addrs
        else:
            return None

    @property
    def full_address(self):
        addrs = ", ".join([_f for _f in [self.address_street_num,
                                         self.address_kelurahan,
                                         self.address_kecamatan,
                                         self.address_kabupaten,
                                         self.address_provinsi,
                                         self.address_kodepos] if _f])
        return addrs

    @property
    def gmap_url(self):
        urls = None
        if self.complete_addresses:
            complete_addresses = urllib.parse.quote_plus(
                str(self.complete_addresses).strip().replace(' ', '+'))
            maps_place = "https://www.google.com/maps/place/"
            urls = "%s%s " % (maps_place, complete_addresses)
        return urls

    @property
    def fullname_with_title(self):

        fullname = self.detokenize_fullname
        if not fullname:
            return ''

        if self.gender == 'Wanita':
            return 'Ibu ' + fullname.title()
        if self.gender == 'Pria':
            return 'Bapak ' + fullname.title()
        if not self.gender:
            return '' + fullname.title()

    @property
    def fullname_with_short_title(self):
        from juloserver.grab.utils import get_customer_name_with_title
        return get_customer_name_with_title(self.gender, self.fullname)

    @property
    def detokenize_fullname(self):
        from juloserver.minisquad.utils import collection_detokenize_sync_object_model

        return collection_detokenize_sync_object_model(
            'application', self, self.customer.customer_xid, ['fullname']
        ).fullname

    @property
    def first_name_with_title(self):
        firstname = self.detokenize_fullname.split()[0]
        if self.gender == 'Wanita':
            return 'Ibu ' + firstname.title()
        if self.gender == 'Pria':
            return 'Bapak ' + firstname.title()

    @property
    def first_name_with_title_short(self):
        firstname = self.fullname.split()[0].title()
        if self.gender == 'Wanita':
            return 'Ibu ' + firstname
        if self.gender == 'Pria':
            return 'Bpk ' + firstname

    @property
    def first_name_only(self):
        if self.detokenize_fullname:
            return self.detokenize_fullname.split()[0].title()

    @property
    def full_name_only(self):
        if self.fullname:
            return self.fullname.title()

    @property
    def bpk_ibu(self):
        if self.gender == 'Wanita':
            return 'Ibu '
        if self.gender == 'Pria':
            return 'Bpk '

    @property
    def gender_initial(self):
        if self.gender == 'Wanita':
            return 'P'
        if self.gender == 'Pria':
            return 'L'

    @property
    def partner_name(self):
        if self.partner is None:
            return None
        return self.partner.name

    @property
    def gender_title(self):
        if self.gender == 'Wanita':
            return 'Ibu'
        if self.gender == 'Pria':
            return 'Bapak'

    @property
    def split_name(self):
        word_count = len(self.fullname.split())
        if word_count > 1:
            firstname = self.fullname.rsplit(' ', 1)[0].title()
            lastname = self.fullname.split()[-1].title()
        else:
            firstname = self.fullname.title()
            lastname = ''
        return firstname, lastname

    @property
    def can_show_status(self):
        app_status = self.status
        if app_status != ApplicationStatusCodes.APPLICATION_DENIED:
            return True

        reject_history = self.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.APPLICATION_DENIED
        ).first()
        if not reject_history:
            return True
        rejection_time = reject_history.cdate
        delayed_rejection_time = get_delayed_rejection_time(rejection_time)

        now = timezone.localtime(timezone.now())
        can_show = now >= delayed_rejection_time

        logger.info({
            'app_status': app_status,
            'delayed_rejection_time': str(delayed_rejection_time),
            'rejection_time': str(rejection_time),
            'now': str(now)
        })
        return can_show

    @property
    def disbursement_date(self):
        try:
            loan = self.loan
            disbursement = Disbursement.objects.get_or_none(loan=loan)
            if disbursement:
                return disbursement.cdate
            else:
                return None
        except:
            return None

    @property
    def determine_kind_of_installment(self):
        if self.product_line:  # so it does not break 105 bucket
            if self.product_line.payment_frequency == 'Monthly':
                return 'bulan'
            elif self.product_line.payment_frequency == 'Weekly':
                return 'minggu'
            elif self.product_line.payment_frequency == 'Daily':
                return 'hari'
            else:
                raise JuloException("payment frequency not available")

    @property
    def loc_id(self):
        if self.line_of_credit:
            return self.line_of_credit.id
        return None

    def is_active(self):
        active = True
        workflow = self.workflow if self.workflow else Workflow.objects.get(
            name="LegacyWorkflow")
        graveyard_statuses = list(set(workflow.workflowstatuspath_set.filter(
            type="graveyard").values_list('status_next', flat=True)))
        if self.application_status.status_code in graveyard_statuses:
            active = False
        return active

    def is_new_version(self):
        is_new_app_version = True
        if self.app_version:  # handle the new web app which is has no app_version
            is_new_app_version = semver.match(self.app_version, ">=3.0.0")
        return is_new_app_version

    def is_digisign_version(self):
        is_digisign_version = True
        if self.app_version:  # handle the new web app which is has no app_version
            is_digisign_version = semver.match(self.app_version, ">3.11.0")
        return is_digisign_version

    def is_web_app(self):
        if not self.app_version and self.web_version:
            return True
        return False

    def is_partnership_app(self):
        if self.is_grab():
            return False

        if self.partner or (self.partner and self.partner.is_csv_upload_applicable):
            return True
        return False

    def is_partnership_webapp(self):
        if self.partner and self.web_version and not self.app_version:
            return True
        return False

    def is_force_filled_partner_app(self):
        """
        partner application is retroloaded from fill_partner_application()
        <<< PARTNER-4329 6 January 2025 >>>
        covered partner (nex, ayokenalin, cermati)
        """
        from juloserver.partnership.constants import PartnershipFlag
        from juloserver.partnership.models import PartnershipApplicationFlag

        if not self.is_julo_one_product() or not self.partner:
            return False

        return PartnershipApplicationFlag.objects.filter(
            application_id=self.id,
            name=PartnershipFlag.FORCE_FILLED_PARTNER_ID,
        ).exists()

    def is_regular_julo_one(self):
        return self.is_julo_one() and not self.is_web_app() and not self.is_partnership_app()

    @property
    def device_scraped_data(self):
        return self.devicescrapeddata_set.exclude(url=None).exclude(url='')

    def is_julo_one(self):
        """
        Deprecated. Should use is_julo_one_product() instead.
        """
        if not self.workflow:
            return False
        return self.workflow.name == WorkflowConst.JULO_ONE

    def is_julo_one_product(self):
        return self.product_line_code == ProductLineCodes.J1

    def is_julo_starter(self):
        if not self.workflow:
            return False
        return self.workflow.name == WorkflowConst.JULO_STARTER

    def is_julo_one_or_starter(self):
        return self.is_julo_one_product() or self.is_julo_starter()

    @property
    def julo_one_or_starter(self):
        return self.is_julo_one_or_starter()

    @property
    def is_jstarter(self):
        # Make alias as class property
        return self.is_julo_starter()

    def is_julo_starter_experiment(self):
        if not self.workflow or not self.onboarding or not self.product_line_code:
            return False
        return self.onboarding.id == OnboardingIdConst.JULO_STARTER_FORM_ID and \
            self.workflow.name == WorkflowConst.JULO_ONE and \
            self.product_line_code == ProductLineCodes.J1

    @property
    def is_jstarter_experiment(self):
        return self.is_julo_starter_experiment()

    def is_julo_360(self):
        # use onboarding_id instead of onboarding.id to avoid errors on older test code
        if not self.onboarding_id:
            return False
        return self.onboarding_id in [
            OnboardingIdConst.JULO_360_TURBO_ID,
            OnboardingIdConst.JULO_360_J1_ID,
        ]

    def is_agent_assisted_submission(self):
        from juloserver.application_flow.models import ApplicationPathTag

        return ApplicationPathTag.objects.filter(
            application_id=self.id,
            application_path_tag_status__application_tag='is_agent_assisted_submission',
            application_path_tag_status__status=1,
        ).exists()

    def is_clik_model(self):
        from juloserver.application_flow.models import ApplicationPathTag

        return ApplicationPathTag.objects.filter(
            application_id=self.id,
            application_path_tag_status__application_tag='is_clik_model',
            application_path_tag_status__status=1,
        ).exists()

    def is_julover(self):
        return self.product_line_code == ProductLineCodes.JULOVER

    def is_axiata_flow(self):
        if not self.workflow:
            return False
        return self.workflow.name in {WorkflowConst.MERCHANT_FINANCING_WORKFLOW, WorkflowConst.PARTNER} and \
            self.product_line_code in ProductLineCodes.axiata()

    def is_grab(self):
        if not self.workflow:
            return False
        return self.workflow.name == WorkflowConst.GRAB

    def is_qoala(self):
        from juloserver.application_flow.constants import PartnerNameConstant
        if not self.partner:
            return False
        return self.partner.name.lower() == PartnerNameConstant.QOALA

    def is_merchant_flow(self):
        if not self.workflow:
            return False
        return self.workflow.name == WorkflowConst.MERCHANT_FINANCING_WORKFLOW

    def is_dana_flow(self) -> bool:
        if not self.workflow:
            return False
        return self.workflow.name == WorkflowConst.DANA

    def can_access_julo_app(self):
        return self.is_julo_one() or self.is_julover() or self.is_julo_starter()

    def is_mf_web_app_flow(self) -> bool:
        if not self.workflow:
            return False
        return self.workflow.name == WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW

    @property
    def mobile_phone_prefix_62(self):
        if not self.mobile_phone_1:
            return None
        if self.mobile_phone_1.startswith("0"):
            return "62%s" % self.mobile_phone_1[1:]

        return self.mobile_phone_1

    def get_last_risky_check(self):
        from juloserver.application_flow.models import ApplicationRiskyCheck

        if self._last_risky_check is None:
            self._last_risky_check = ApplicationRiskyCheck.objects.filter(application=self).last()

        return self._last_risky_check

    def eligible_for_hsfbp(self, risky_checklist=None):
        risky_checklist = risky_checklist or self.get_last_risky_check()
        if risky_checklist and risky_checklist.decision:
            if risky_checklist.decision.decision_name in ApplicationRiskyDecisions.no_dv_bypass():
                return False
        return True

    def has_pass_hsfbp(self):
        from juloserver.application_flow.models import (
            ApplicationPathTag,
            ApplicationPathTagStatus,
        )

        if self._has_pass_hsfbp is None:
            application_tags = [
                'is_hsfbp',
                'is_hsfbp_decline_doc',
                'is_hsfbp_no_doc'
            ]

            hsfbp_path_tags = ApplicationPathTagStatus.objects.filter(
                application_tag__in=application_tags, status=1
            ).values_list('id', flat=True)
            application_path = ApplicationPathTag.objects.filter(
                application_id=self.id, application_path_tag_status_id__in=hsfbp_path_tags
            ).exists()

            self._has_pass_hsfbp = application_path

        return self._has_pass_hsfbp

    def hsfbp_verified_income(self):
        from juloserver.application_flow.models import HsfbpIncomeVerification
        hsfbp = HsfbpIncomeVerification.objects.filter(application_id=self.id).last()
        if not hsfbp:
            return None
        return hsfbp.verified_income

    def has_pass_sonic(self):
        from juloserver.application_flow.models import (
            ApplicationPathTag,
            ApplicationPathTagStatus,
        )

        if self._has_pass_sonic is None:
            sonic_path_tag = ApplicationPathTagStatus.objects.filter(
                application_tag='is_sonic', status=1
            ).last()
            application_path = ApplicationPathTag.objects.filter(
                application_id=self.id, application_path_tag_status=sonic_path_tag
            ).last()

            if application_path:
                self._has_pass_sonic = True
            else:
                self._has_pass_sonic = False

        return self._has_pass_sonic

    def eligible_for_sonic(self):
        risky_checklist = self.get_last_risky_check()
        decision = risky_checklist.decision if risky_checklist else None
        if decision and decision.decision_name in ApplicationRiskyDecisions.no_pve_bypass():
            return False
        return True

    def can_ignore_fraud(self):
        risky_checklist = self.get_last_risky_check()
        decision = risky_checklist.decision if risky_checklist else None
        if decision and decision.decision_name == ApplicationRiskyDecisions.NO_DV_BYPASS:
            return True
        return False

    def has_suspicious_application_in_device(self) -> bool:
        """
        Checks if the application has suspicious software in device.
        The development of this function assumes Suspicious Application Check is done.

        Returns:
            (bool): True if suspicious software is found in this application device.
                False if no suspicious software or ApplicationRiskyCheck not evaluated yet.
        """
        application_risky_check = ApplicationRiskyCheck.objects.filter(
            application=self.id
        ).first()

        if application_risky_check:
            return application_risky_check.is_sus_app_detected

        return False

    @property
    def partnership_status(self):
        from juloserver.partnership.constants import partnership_status_mapping_statuses
        partnership_status_code = 'UNKNOWN'
        for partnership_status in partnership_status_mapping_statuses:
            if self.application_status_id == partnership_status.list_code:
                partnership_status_code = partnership_status.mapping_status
        return partnership_status_code

    @property
    def code_status(self):
        try:
            id = self.application_status_id
            status_lookup = StatusLookup.objects.get_or_none(status_code=id)
            if status_lookup:
                return status_lookup.status
            else:
                return None
        except:
            return None

    @property
    def credit_score(self):
        try:
            credit_score = CreditScore.objects.get_or_none(application=self.id)
            if credit_score:
                return credit_score.score, credit_score.message
            else:
                return None, None
        except:
            return None, None

    def grab_rejection_reason(self, additional_reason=None):
        grab_rejection_reason = None
        for rejection_mapping in grab_rejection_mapping_statuses:
            if self.application_status_id == \
                rejection_mapping.application_loan_status and \
                    rejection_mapping.additional_check == additional_reason:
                grab_rejection_reason = rejection_mapping.mapping_status
        return grab_rejection_reason

    @property
    def eligible_for_cfs(self):
        if (
            self.status in ApplicationStatusCodes.active_account()
            and self.is_julo_one_or_starter()
        ):
            return True

        return False

    @property
    def eligible_for_promo_entry_page(self):
        if (
            self.status in ApplicationStatusCodes.active_account()
            and self.is_julo_one_or_starter()
        ):
            return True

        return False

    def is_reapply_app(self):
        return True if self.application_number and self.application_number > 1 else False

    def dukcapil_eligible(self):
        dukcapil_response = self.dukcapilresponse_set.last()
        if dukcapil_response:
            return dukcapil_response.is_eligible()
        else:
            return True

    def is_allow_for_j1_migration(self):
        return (
            not self.is_julo_one_product()
            and not self.is_julover()
            and not self.is_julo_starter()
        )

    def has_master_agreement(self):
        # handle non j1 application
        if (
            not self.is_julo_one_product()
            and not self.is_julo_starter()
        ):
            return True

        ma_template = MasterAgreementTemplate.objects \
            .filter(product_name='J1', is_active=True) \
            .last()
        # handle if no active template on django admin
        if not ma_template:
            return True

        ma = Document.objects.get_or_none(document_source=self.id,
                                          document_type='master_agreement')
        return True if ma else False

    def has_submit_extra_form(self):
        from juloserver.apiv2.models import EtlStatus
        etl_status = EtlStatus.objects.filter(application_id=self.id).last()
        if not etl_status:
            return False
        if 'julo_turbo_part2_start_tasks' not in etl_status.executed_tasks:
            return False
        return True

    def has_neo_banner(self, app_version=None, is_ios_device=False):
        from juloserver.streamlined_communication.models import NeoBannerCard
        from juloserver.streamlined_communication.services import get_neo_status

        neo_banner = False
        status = get_neo_status(self, app_version=app_version, is_ios_device=is_ios_device)
        if self.is_julo_one() or self.is_julo_one_ios():
            neo_banner = NeoBannerCard.objects.filter(
                is_active=True,
                statuses__contains=status,
                product="J1"
            ).last()

        return True if neo_banner else False

    @property
    def crm_revamp_url(self):
        crm_revamp_base_url = settings.CRM_REVAMP_BASE_URL
        if not crm_revamp_base_url:
            return None

        uri = '/app_status/change_status/{}/'.format(self.id)
        return urllib.parse.urljoin(crm_revamp_base_url, uri)

    @property
    def is_uw_overhaul(self):
        """ to check  application is underwriting or not."""
        from juloserver.application_flow.services import is_experiment_application
        is_application_experiment = is_experiment_application(self.id, 'ExperimentUwOverhaul')
        experiment_setting = ExperimentSetting.objects.get_or_none(code='ExperimentUwOverhaul')
        is_experiment_have_tag = experiment_setting.criteria['crm_tag'] if experiment_setting else False
        return is_application_experiment and experiment_setting and is_experiment_have_tag

    @property
    def last_month_salary(self):
        # use in bpjs direct
        prev_month = self.cdate.replace(day=1) - timedelta(days=1)
        return prev_month.strftime("%m/%Y")

    def is_idfy_approved(self):
        """
        Check if application J1 using IDFy and got approved
        """

        if self.is_julo_one():
            from juloserver.application_form.models import IdfyVideoCall

            is_idfy_user_approved = IdfyVideoCall.objects.filter(
                application_id=self.id,
                status='completed',
                reviewer_action='approved',
            ).exists()

            return is_idfy_user_approved

        return False

    @property
    def length_of_work_in_year(self):
        if not self.job_start:
            return 0
        return math.ceil(
            (timezone.localtime(timezone.now()).date() - self.job_start).days / 365
        )

    @property
    def workplace_phone_number(self):
        if not self.company_phone_number:
            return self.mobile_phone_1
        return self.company_phone_number

    @property
    def gender_salutation(self):
        if self.gender == 'Pria':
            return 'mr'

        return 'mrs'

    def is_eligible_for_collection(self):
        eligible_workflow = [WorkflowConst.JULO_ONE, WorkflowConst.JULO_STARTER]
        eligible_status_code = [
            ApplicationStatusCodes.LOC_APPROVED,
            ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
        ]
        return (
            not self.partner
            and self.workflow.name in eligible_workflow
            and self.status in eligible_status_code
        )

    def is_eligible_for_new_cashback(self):
        eligible_status_code = [
            ApplicationStatusCodes.LOC_APPROVED,
            ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
        ]
        return (
            (not self.partner or self.is_partnership_leadgen())
            and self.workflow.name == WorkflowConst.JULO_ONE
            and self.status in eligible_status_code
        )

    def first_name_only_by_str(self, fullname):
        if fullname:
            return fullname.split()[0].title()

    def first_name_with_title_by_str(self, fullname):
        firstname = fullname.split()[0]
        if self.gender == 'Wanita':
            return 'Ibu ' + firstname.title()
        if self.gender == 'Pria':
            return 'Bapak ' + firstname.title()

    def is_julo_one_ios(self):
        if not self.workflow:
            return False
        return self.workflow.name == WorkflowConst.JULO_ONE_IOS

    def is_partnership_leadgen(self):
        """
        To decide if partner name
        in feature settings 'partnership_leadgen_api_config.allowed_partner'
        If yes its a using standard leadgen partnership
        """
        from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting

        if self.partner:
            leadgen_partners = list()
            leadgen_config_params = (
                FeatureSetting.objects.filter(
                    feature_name=LeadgenFeatureSetting.API_CONFIG, is_active=True
                )
                .values_list('parameters', flat=True)
                .last()
            )

            if leadgen_config_params:
                leadgen_partners = (
                    leadgen_config_params.get('allowed_partner', [])
                    if leadgen_config_params
                    else []
                )

            if self.partner.name.lower() in leadgen_partners:
                return True

        return False


class ApplicationOriginalPIIVaultManager(PIIVaultModelManager):
    pass


class ApplicationOriginal(PIIVaultPrimeModel, ApplicationTemplate):
    current_application = models.ForeignKey(
        'Application', models.DO_NOTHING, db_column='current_application_id',
        null=True, blank=True)

    objects = ApplicationOriginalPIIVaultManager()

    class Meta(object):
        db_table = 'application_original'


class ApplicationHistoryQuerySet(CustomQuerySet):
    def called_app_ids(self, status_code):
        return self.filter(
            application__application_status_id=status_code,
            status_new=status_code,
            autodialersessionstatus__isnull=False
        ).values_list('application_id', flat=True)

    def autodialer_uncalled(self, status_code, locked_list, app122queue):
        qs = self.filter(status_new=status_code)
        called_app_ids = self.called_app_ids(status_code)
        exclude_application_list = locked_list + list(called_app_ids)
        if app122queue:
            qs = qs.filter(application__id__in=app122queue)

        qs = qs.filter(application__application_status__status_code=status_code,
                       autodialersessionstatus__isnull=True).exclude(
            application__id__in=exclude_application_list)
        return qs


class ApplicationHistoryManager(GetInstanceMixin, JuloModelManager):

    def get_queryset(self):
        return ApplicationHistoryQuerySet(self.model)

    def autodialer_uncalled_app(self, status_code, locked_list, app122queue=None):
        qs = self.get_queryset().autodialer_uncalled(status_code, locked_list, app122queue)
        if status_code == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            today = timezone.localtime(timezone.now())
            today_minus_14 = today - timedelta(days=14)
            today_minus_28 = today - timedelta(days=28)
            start_date = datetime.combine(today_minus_28, time.min)
            end_date = datetime.combine(today_minus_14, time.max)
            qs = qs.filter(application__is_courtesy_call=False, cdate__range=[start_date, end_date]).exclude(
                partner__name__in=LIST_PARTNER
            )
        if status_code == ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING:
            if qs:
                application_note = (
                    ApplicationNote.objects.values('application_id')
                    .annotate(Max('udate'))
                    .filter(
                        application_id=qs.order_by('udate').first().application_id,
                    )
                    .last()
                )
                if application_note:
                    qs = (
                        qs.annotate(
                            max_udate=ExpressionWrapper(
                                Coalesce(application_note['udate__max'], None),
                                output_field=DateTimeField(),
                            )
                        )
                        .order_by('-max_udate')
                        .last()
                    )
        else:
            qs = qs.order_by("udate").first()
        if qs:
            return qs.application
        else:
            return None

    def uncalled_app_list(self, status_code):
        qs = self.get_queryset().autodialer_uncalled(status_code, [], None)
        if status_code == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            today = timezone.localtime(timezone.now())
            today_minus_14 = today - timedelta(days=14)
            today_minus_28 = today - timedelta(days=28)
            start_date = datetime.combine(today_minus_28, time.min)
            end_date = datetime.combine(today_minus_14, time.max)
            qs = qs.filter(application__is_courtesy_call=False, cdate__range=[start_date, end_date])
        if status_code == ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING:
            if qs:
                application_note = (
                    ApplicationNote.objects.values('application_id')
                    .annotate(Max('udate'))
                    .filter(
                        application_id=qs.order_by('udate').first().application_id,
                    )
                    .last()
                )
                if application_note:
                    qs = (
                        qs.annotate(
                            max_udate=ExpressionWrapper(
                                Coalesce(application_note['udate__max'], None),
                                output_field=DateTimeField(),
                            )
                        )
                        .order_by('-max_udate')
                        .last()
                    )
        else:
            qs = qs.order_by("udate")

        return qs


class ApplicationHistory(TimeStampedModel):
    """
    TODO: rename this to ApplicationStatusChange
    """
    objects = ApplicationHistoryManager()
    id = models.AutoField(db_column='application_history_id', primary_key=True)

    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')

    status_old = models.IntegerField()
    status_new = models.IntegerField()
    # TODO: for some reason the api user is not being captured. Asking its
    # maintainer for help
    changed_by = CurrentUserField(
        related_name="application_status_changes")

    change_reason = models.TextField(
        default="system_triggered")

    is_skip_workflow_action = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'application_history'
        verbose_name_plural = "Application History"


class AddressGeolocationQuerySet(CustomQuerySet):

    def by_application(self, application):
        return self.filter(application=application)


class DeviceGeolocationQuerySet(CustomQuerySet):
    def by_device(self, device):
        return self.filter(device=device)


class AddressGeolocationManager(GetInstanceMixin, JuloModelManager):

    def get_queryset(self):
        return AddressGeolocationQuerySet(self.model)

    def by_application(self, application):
        return self.get_queryset().by_application(application)


class AddressGeolocation(TimeStampedModel):
    id = models.AutoField(db_column='address_geolocation_id', primary_key=True)

    application = models.OneToOneField(
        'Application', models.DO_NOTHING, db_column='application_id',
        null=True, blank=True)

    customer = models.OneToOneField(
        'Customer', models.DO_NOTHING, db_column='customer_id',
        null=True, blank=True)

    latitude = models.FloatField()
    longitude = models.FloatField()
    provinsi = models.CharField(null=True, blank=True, max_length=100)
    kabupaten = models.CharField(null=True, blank=True, max_length=100)
    kecamatan = models.CharField(null=True, blank=True, max_length=100)
    kelurahan = models.CharField(null=True, blank=True, max_length=100)
    kodepos = models.CharField(null=True, blank=True, max_length=5)

    # These fields latitude and longitude from map-picker when user pick point in x100 form.
    address_latitude = models.FloatField(null=True, blank=True)
    address_longitude = models.FloatField(null=True, blank=True)

    objects = AddressGeolocationManager()

    class Meta(object):
        db_table = 'address_geolocation'

    def __str__(self):
        google_maps_url = "https://maps.google.com/maps?/z=10&q="
        coordinate = str(self.latitude) + "+" + str(self.longitude)
        return google_maps_url + coordinate

    @property
    def gmap_address_and_latlon_url(self):
        maps_direction = "https://www.google.com/maps/dir/"
        urls = "%s%s,%s/%s/" % (maps_direction, str(self.latitude), str(self.longitude),
                                self.application.complete_addresses)
        return urls


class DeviceGeolocationManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return DeviceGeolocationQuerySet(self.model)

    def by_device(self, device):
        return self.get_queryset().by_device(device)


class DeviceGeolocation(TimeStampedModel):
    id = models.AutoField(db_column='device_geolocation_id', primary_key=True)

    device = models.ForeignKey(
        'Device', models.DO_NOTHING, db_column='device_id')

    latitude = models.FloatField()
    longitude = models.FloatField()
    timestamp = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(null=True, blank=True, max_length=100)
    fraud_hotspot = models.NullBooleanField()

    objects = DeviceGeolocationManager()

    class Meta(object):
        db_table = 'device_geolocation'


class DataCheck(TimeStampedModel):
    DATA_VERIFIER = 'Data Verifier'
    OUTBOUND_CALLER = 'Outbound Caller'
    FINANCE = 'Finance'

    id = models.AutoField(db_column='data_check_id', primary_key=True)

    application = models.ForeignKey(
        'Application', models.DO_NOTHING, db_column='application_id')

    responsibility = models.CharField(max_length=100)
    data_to_check = models.CharField(max_length=100)
    is_okay = models.NullBooleanField()

    class Meta(object):
        db_table = 'data_check'

    def __str__(self):
        """Visual identification"""
        return self.data_to_check


class DeviceScrapedDataQuerySet(CustomQuerySet):

    def by_application(self, application):
        return self.filter(application=application)


class DeviceScrapedDataManager(GetInstanceMixin, JuloModelManager):

    def get_queryset(self):
        return DeviceScrapedDataQuerySet(self.model)

    def by_application(self, application):
        return self.get_queryset().by_application(application)


def upload_to(instance, filename):
    return 'image_upload/{0}/{1}'.format(instance.pk, filename)


class DeviceScrapedData(S3ObjectModel):
    id = models.AutoField(db_column='device_scraped_data_id', primary_key=True)

    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    url = models.CharField(max_length=200, blank=True, null=True)

    # Path to the file before uploaded to S3
    file = models.FileField(
        db_column='internal_path', blank=True, null=True, upload_to=upload_to)
    reports_url = models.CharField(max_length=200, blank=True)

    file_type = models.CharField(max_length=50, blank=True, null=True)
    SERVICE_CHOICES = (
        ('s3', 's3'),
        ('oss', 'oss')
    )
    service = models.CharField(
        max_length=50, choices=SERVICE_CHOICES, default='s3')
    objects = DeviceScrapedDataManager()

    class Meta(object):
        db_table = 'device_scraped_data'

    @property
    def raw_s3_url(self):
        url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
        if url == '':
            return None
        return url

    @property
    def reports_ext(self):
        name, extension = os.path.splitext(self.file.name)
        return extension

    @property
    def reports_s3_bucket(self):
        # The s3 bucket is the first part before the first slash
        bucket = self.reports_url.split('/')[0]
        return bucket

    @property
    def reports_xls_s3_url(self):
        if self.service == 'oss':
            if self.url == '' or self.url is None:
                return None
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.s3_object_path(self.reports_url))
        elif self.service == 's3':
            url = get_s3_url(
                self.reports_s3_bucket, self.s3_object_path(self.reports_url))
            if url == '':
                return None
            return url

    def __str__(self):
        """Visual identification"""
        return str(self.id)


class FacebookData(TimeStampedModel):
    id = models.AutoField(db_column='facebook_data_id', primary_key=True)

    application = models.OneToOneField('Application',
                                       models.DO_NOTHING,
                                       db_column='application_id',
                                       related_name='facebook_data',
                                       blank=True, null=True)

    facebook_id = models.BigIntegerField()
    fullname = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=50, blank=True, null=True)
    friend_count = models.IntegerField(blank=True, null=True)
    open_date = models.DateField(blank=True, null=True)
    created_date = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_date = models.DateTimeField(auto_now=True, blank=True, null=True)

    class Meta(object):
        db_table = 'facebook_data'


class FacebookDataHistory(TimeStampedModel):
    application = models.ForeignKey('Application',
                                    models.DO_NOTHING,
                                    db_column='application_id',
                                    related_name='facebook_history_data',
                                    blank=True, null=True)

    facebook_id = models.BigIntegerField()
    fullname = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=50, blank=True, null=True)
    friend_count = models.IntegerField(blank=True, null=True)
    open_date = models.DateField(blank=True, null=True)
    created_date = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_date = models.DateTimeField(auto_now=True, blank=True, null=True)

    class Meta(object):
        db_table = 'detailed_fb_change'


class DecisionManager(GetInstanceMixin, JuloModelManager):
    pass


class Decision(TimeStampedModel):
    id = models.AutoField(db_column='decision_id', primary_key=True)

    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')

    is_non_fraud = models.NullBooleanField()
    is_able_to_pay = models.NullBooleanField()
    is_willing_to_pay = models.NullBooleanField()
    is_approved = models.NullBooleanField()

    interest_rate = models.FloatField(blank=True, null=True)
    origination_fee_pct = models.FloatField(blank=True, null=True)
    late_fee_pct = models.FloatField(blank=True, null=True)
    cashback_initial_pct = models.FloatField(blank=True, null=True)
    cashback_payment_pct = models.FloatField(blank=True, null=True)
    monthly_saving = models.BigIntegerField(blank=True, null=True)
    saving_confidence_pct = models.FloatField(blank=True, null=True)
    max_monthly_pmt = models.BigIntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'decision'

    objects = DecisionManager()

    def __str__(self):
        """Visual identification"""
        return str(self.application)


class VoiceRecordManager(GetInstanceMixin, JuloModelManager):
    pass


class VoiceRecord(S3ObjectModel):
    DELETED = -1
    CURRENT = 0
    RESUBMISSION_REQ = 1
    RECORD_STATUS_CHOICES = (
        (DELETED, 'Deleted'),
        (CURRENT, 'Current'),
        (RESUBMISSION_REQ, 'Resubmission Required'))

    id = models.AutoField(db_column='voice_record_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    status = models.IntegerField(
        blank=True, null=True, choices=RECORD_STATUS_CHOICES, default=CURRENT)
    SERVICE_CHOICES = (
        ('s3', 's3'),
        ('oss', 'oss')
    )
    service = models.CharField(
        max_length=50, choices=SERVICE_CHOICES, default='oss')
    url = models.TextField(blank=True, null=True)
    loan = models.ForeignKey('Loan', models.DO_NOTHING,
                             db_column='loan_id', blank=True, null=True)

    # Path to the image before uploaded to S3
    tmp_path = models.FileField(db_column='internal_path', blank=True, null=True)

    class Meta(object):
        db_table = 'voice_record'

    objects = VoiceRecordManager()

    @property
    def presigned_url(self):
        if self.service == 'oss':
            if self.url == '' or self.url is None:
                return None
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url)
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
            if url == '':
                return None
            return url


class ImageManager(GetInstanceMixin, JuloModelManager):
    pass


class Image(S3ObjectModel):
    id = models.AutoField(db_column='image_id', primary_key=True)

    # The ID of the table this image is associated with, depending which
    # table is associated.
    image_source = models.BigIntegerField(db_column='image_source_id')
    image_type = models.CharField(max_length=50)
    url = models.CharField(max_length=200)
    thumbnail_url = models.CharField(max_length=200)
    SERVICE_CHOICES = (
        ('s3', 's3'),
        ('oss', 'oss')
    )
    service = models.CharField(
        max_length=50, choices=SERVICE_CHOICES, default='oss')
    DELETED = -1
    CURRENT = 0
    RESUBMISSION_REQ = 1
    IMAGE_STATUS_CHOICES = (
        (DELETED, 'Deleted'),
        (CURRENT, 'Current'),
        (RESUBMISSION_REQ, 'Resubmission Required')
    )
    image_status = models.IntegerField(
        blank=True, null=True, choices=IMAGE_STATUS_CHOICES, default=CURRENT)

    # Path to the image before uploaded to S3
    image = models.ImageField(
        db_column='internal_path', blank=True, null=True, upload_to=upload_to)

    class Meta(object):
        db_table = 'image'

    objects = ImageManager()

    @staticmethod
    def full_image_name(image_name):
        path_and_name, extension = os.path.splitext(image_name)
        if not extension:
            extension = '.jpg'
        return path_and_name + extension

    @property
    def image_url(self):
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
    def notification_image_url(self):
        if self.service == 'oss':
            if self.url == '' or self.url is None:
                return None
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url, expires_in_seconds=(24 * 60 * 60))
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
            if url == '':
                return None
            return url

    @property
    def image_url_api(self):
        if self.service == 'oss':
            if self.url == '' or self.url is None:
                return None
            return get_oss_presigned_url(
                settings.OSS_MEDIA_BUCKET, self.url, expires_in_seconds=60)
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url), 60)
            if url == '':
                return None
            return url

    @property
    def thumbnail_url_api(self):
        if self.service == 'oss':
            if self.url == '' or self.url is None:
                return None
            return get_oss_presigned_url(
                settings.OSS_MEDIA_BUCKET, self.thumbnail_url, expires_in_seconds=3600
            )
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.thumbnail_url), 60)
            if url == '':
                return self.image_url_api
            return url

    @property
    def image_ext(self):
        name, extension = os.path.splitext(self.url)
        return extension.lower()

    @property
    def thumbnail_path(self):
        if self.image.name == '':
            return None
        path_and_name, extension = os.path.splitext(self.image.path)
        if not extension:
            extension = '.jpg'
        return path_and_name + '_thumbnail' + extension

    @property
    def application_id(self):
        if 2000000000 < int(self.image_source) < 2999999999:
            return self.image_source
        else:
            return None

    @property
    def public_image_url(self):
        if self.url == '' or self.url is None:
            return None
        return get_oss_public_url(settings.OSS_PUBLIC_ASSETS_BUCKET, self.url)

    def collection_image_url(self, expires_in_seconds=60):
        if not self.url:
            return None

        url = None
        if self.service == 'oss':
            url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url, expires_in_seconds)
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url), expires_in_seconds)

        return url

    def collection_thumbnail_url(self, expires_in_seconds=60):
        path = self.thumbnail_url if self.thumbnail_url else self.url
        if not path:
            return None

        url = None
        if self.service == 'oss':
            url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, path, expires_in_seconds)
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(path), expires_in_seconds)

        return url

    @property
    def static_image_url(self):
        if not self.url:
            return None

        return settings.JULOFILES_BUCKET_URL + self.url

    def channeling_related_url(self, expires_in_seconds=60):
        return self.collection_image_url(expires_in_seconds)


class ImageMetadata(TimeStampedModel):
    id = models.AutoField(db_column='image_metadata_id', primary_key=True)
    image = BigForeignKey(
        Image, models.DO_NOTHING, db_column='image_id'
    )
    application = BigForeignKey(
        Application, models.DO_NOTHING, db_column='application_id'
    )
    file_name = models.CharField(max_length=500)
    directory = models.CharField(max_length=500, null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    file_modification_time = models.DateTimeField(null=True, blank=True)
    file_access_time = models.DateTimeField(null=True, blank=True)
    file_creation_time = models.DateTimeField(null=True, blank=True)
    file_permission = models.CharField(max_length=50, null=True, blank=True)
    file_type = models.CharField(max_length=50, null=True, blank=True)
    file_type_extension = models.CharField(max_length=50, null=True, blank=True)
    file_mime = models.CharField(max_length=50, null=True, blank=True)
    exif_byte_order = models.CharField(max_length=255, null=True, blank=True)
    gps_lat_ref = models.CharField(max_length=50, null=True, blank=True)
    gps_date = models.CharField(max_length=255, null=True, blank=True)
    gps_timestamp = models.DateTimeField(null=True, blank=True)
    gps_altitude = models.SmallIntegerField(null=True, blank=True)
    gps_long_ref = models.CharField(max_length=50, null=True, blank=True)
    modify_date = models.DateTimeField(null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)
    camera_model_name = models.CharField(max_length=100, null=True, blank=True)
    orientation = models.CharField(max_length=50, null=True, blank=True)
    flash_status = models.IntegerField(null=True, blank=True)
    exif_version = models.CharField(max_length=50, null=True, blank=True)
    camera_focal_length = models.CharField(max_length=255, null=True, blank=True)
    white_balance = models.CharField(max_length=50, null=True, blank=True)
    exif_image_width = models.IntegerField(null=True, blank=True)
    exif_image_height = models.IntegerField(null=True, blank=True)
    sub_sec_time = models.IntegerField(null=True, blank=True)
    original_timestamp = models.DateTimeField(null=True, blank=True)
    sub_sec_time_original = models.IntegerField(null=True, blank=True)
    sub_sec_time_digitized = models.IntegerField(null=True, blank=True)
    make = models.CharField(max_length=255, null=True, blank=True)
    jfif_version = models.CharField(max_length=50, null=True, blank=True)
    resolution_unit = models.CharField(max_length=50, null=True, blank=True)
    x_res = models.CharField(max_length=255, null=True, blank=True)
    y_res = models.CharField(max_length=255, null=True, blank=True)
    image_width = models.IntegerField(null=True, blank=True)
    image_height = models.IntegerField(null=True, blank=True)
    encoding = models.CharField(max_length=255, null=True, blank=True)
    bits_per_sample = models.IntegerField(null=True, blank=True)
    color_components = models.IntegerField(null=True, blank=True)
    ycbcrsub_sampling = models.CharField(max_length=255, null=True, blank=True)
    image_size = models.CharField(max_length=255, null=True, blank=True)
    megapixels = models.FloatField(null=True, blank=True)
    create_date = models.DateTimeField(null=True, blank=True)
    datetime_original = models.DateTimeField(null=True, blank=True)
    gps_lat = models.CharField(max_length=100, null=True, blank=True)
    gps_long = models.CharField(max_length=100, null=True, blank=True)
    gps_position = models.CharField(max_length=255, null=True, blank=True)
    bit_depth = models.SmallIntegerField(null=True, blank=True)
    interlace = models.CharField(max_length=255, null=True, blank=True)
    color_type = models.CharField(max_length=255, null=True, blank=True)
    compression = models.CharField(max_length=100, null=True, blank=True)
    filter = models.CharField(max_length=255, null=True, blank=True)

    class Meta(object):
        db_table = 'image_metadata'


class DocumentManager(GetInstanceMixin, JuloModelManager):
    pass


class Document(S3ObjectModel):

    SERVICE_CHOICES = (
        ('s3', 's3'),
        ('oss', 'oss')
    )

    id = models.AutoField(db_column='document_id', primary_key=True)
    document_source = models.BigIntegerField(db_column='document_source_id', db_index=True)
    url = models.CharField(max_length=200)
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES, default='oss')
    document_type = models.CharField(max_length=50)
    filename = models.CharField(max_length=200, blank=True, null=True)
    application_xid = models.BigIntegerField(blank=True, null=True, db_index=True)
    loan_xid = models.BigIntegerField(blank=True, null=True, db_index=True)
    account_payment_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    hash_digi_sign = models.TextField(blank=True, null=True)
    accepted_ts = models.DateTimeField(blank=True, null=True)
    key_id = models.BigIntegerField(db_column='key_id', db_index=True, blank=True, null=True)
    signature_version = models.CharField(max_length=20, blank=True, null=True)

    class Meta(object):
        db_table = 'document'

    objects = DocumentManager()

    @property
    def document_url(self):
        if self.service == 'oss':
            if self.url == '' or self.url is None:
                return None
            expires_in_seconds = 120
            if self.document_type in DocumentType.LIST:
                expires_in_seconds = 7200
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url, expires_in_seconds)
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
            if url == '':
                return None
            return url

    @property
    def path(self):
        return self.url

    @property
    def signature(self):
        return self.hash_digi_sign

    def channeling_related_url(self, expires_in_seconds=60):
        if not self.url:
            return None

        url = None
        if self.service == 'oss':
            url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url, expires_in_seconds)
        elif self.service == 's3':
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url), expires_in_seconds)

        return url


class Note(TimeStampedModel):
    """
    DEPRECATED: see ApplicationNote
    """
    id = models.AutoField(db_column='note_id', primary_key=True)

    application = models.OneToOneField(
        Application, models.DO_NOTHING, db_column='application_id')

    note_text = models.TextField()

    class Meta(object):
        db_table = 'note'


class ApplicationNote(TimeStampedModel):
    id = models.AutoField(db_column='application_note_id', primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    application_history_id = models.BigIntegerField(
        db_column='application_history_id',
        blank=True,
        null=True
    )
    note_text = models.TextField()
    added_by_id = models.BigIntegerField(blank=True, null=True, db_column='added_by_id')

    @property
    def added_by(self):
        if self.added_by_id:
            user = User.objects.filter(id=self.added_by_id).last()
            if not user:
                return None

            return user.username
        return None

    class Meta(object):
        db_table = 'application_note'
        managed = False


class OfferQuerySet(CustomQuerySet):

    def accepted(self):
        return self.filter(is_accepted=True)

    def shown_for_application(self, application):
        if application.application_status.status != StatusLookup.OFFER_MADE:
            logger.debug(
                "Offer has not been made for application_id=%s" %
                application.id)
            return self.none()
        logger.info("Getting offers for application_id=%s" % application.id)
        return self.filter(application=application)


class OfferManager(GetInstanceMixin, JuloModelManager):

    def get_queryset(self):
        return OfferQuerySet(self.model)

    def shown_for_application(self, application):
        return self.get_queryset().shown_for_application(application)

    def accepted(self):
        return self.get_queryset().accepted()


class Offer(TimeStampedModel):
    EXPIRATION_DAYS = 3

    id = models.AutoField(db_column='offer_id', primary_key=True)

    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    product = models.ForeignKey(
        'ProductLookup', models.DO_NOTHING, db_column='product_code')

    offer_number = models.IntegerField()
    loan_amount_offer = models.BigIntegerField()
    loan_duration_offer = models.IntegerField()
    installment_amount_offer = models.BigIntegerField()
    is_accepted = models.NullBooleanField()
    offer_sent_ts = models.DateTimeField(blank=True, null=True)
    offer_accepted_ts = models.DateTimeField(blank=True, null=True)
    offer_exp_date = models.DateField(blank=True, null=True)
    first_payment_date = models.DateField()
    first_installment_amount = models.BigIntegerField()
    last_installment_amount = models.BigIntegerField(blank=True, null=True)
    is_approved = models.NullBooleanField()
    # for different first payment date for long holiday case such as lebaran holiday
    special_first_payment_date = models.DateField(blank=True, null=True)

    objects = OfferManager()

    class Meta(object):
        db_table = 'offer'

    def __str__(self):
        return "Offer for %s" % self.product.product_name

    @property
    def interest_rate_monthly(self):
        return py2round(self.product.monthly_interest_rate, 3)

    @property
    def loan_amount_received(self):
        return py2round(self.loan_amount_offer * (1 - self.product.origination_fee_pct), 0)

    @property
    def cashback_total_pct(self):
        # Note: might be cleaner as product field
        return self.product.cashback_initial_pct + self.product.cashback_payment_pct

    @property
    def cashback_potential(self):

        if self.loan_amount_offer <= 0:
            return 0

        if self.loan_duration_offer <= 0:
            return 0

        return compute_cashback_total(
            self.loan_amount_offer,
            self.product.cashback_initial_pct,
            self.product.cashback_payment_pct)

    @property
    def disbursement_amount(self):
        disbursement_amount = self.loan_amount_offer * (1 - self.product.origination_fee_pct)
        return disbursement_amount

    @property
    def just_accepted(self):
        offer_just_accepted = False
        if self.is_accepted:
            loan = Loan.objects.get_or_none(
                customer=self.application.customer, offer=self)
            if loan is None:
                logger.info({
                    'status': 'offer_already_has_loan',
                    'offer': self.id
                })
                offer_just_accepted = True
        return offer_just_accepted

    @property
    def expired(self):
        expired = False
        today = date.today()
        expired_time_delta = today - self.offer_exp_date
        expired_days = expired_time_delta.days
        if expired_days > 0:
            expired = True
        logger.debug({
            'today': today,
            'offer_expiration_date': self.offer_exp_date,
            'days_before_expire': -expired_days,
            'expired': expired
        })
        return expired

    @property
    def max_total_late_fee_amount(self):
        return self.loan_amount_offer * MAX_LATE_FEE_RATE

    @property
    def interest_percent_monthly(self):
        return (self.product.monthly_interest_rate * 100)

    @property
    def provision_fee(self):
        origination_fee = self.loan_amount_offer * self.product.origination_fee_pct
        return py2round(origination_fee)

    def set_expiration_date(self):
        today = date.today()
        expiration_time_delta = timedelta(days=self.EXPIRATION_DAYS)
        expiration_date = today + expiration_time_delta
        self.offer_sent_ts = timezone.localtime(timezone.now())
        self.offer_exp_date = expiration_date
        logger.debug({
            'expiration_days': expiration_time_delta.days,
            'expiration_date': expiration_date,
            'status': 'set'
        })

    def set_installment_amount_offer(self):
        previous_installment_amount = self.installment_amount_offer
        _, _, installment = compute_payment_installment(
            self.loan_amount_offer, self.loan_duration_offer,
            self.product.monthly_interest_rate)
        self.installment_amount_offer = installment
        logger.debug({
            'previous_installment_amount_offer': previous_installment_amount,
            'current_installment_amount_offer': self.installment_amount_offer,
            'status': 'set'
        })

    def mark_accepted(self):
        if self.is_accepted:
            return
        self.offer_accepted_ts = timezone.localtime(timezone.now())
        self.is_accepted = True
        logger.debug({
            'is_accepted': self.is_accepted,
            'status': 'changed'
        })


class LoanQuerySet(CustomQuerySet):

    def application_signed(self):
        status = StatusLookup.objects.get(
            status=StatusLookup.LEGAL_AGREEMENT_SIGNED)
        return self.filter(application__application_status=status)

    def inactive(self):
        return self.filter(
            loan_status=StatusLookup.objects.get(status=StatusLookup.INACTIVE))

    def not_inactive(self):
        return self.exclude(
            loan_status=StatusLookup.objects.get(status=StatusLookup.INACTIVE))

    def all_loan(self):
        return self.all()

    def paid_off(self):
        return self.filter(loan_status=LoanStatusCodes.PAID_OFF)

    def for_fraud_alert_mail(self):
        return self.filter(loan_status__gte=LoanStatusCodes.INACTIVE,
                           loan_status__lt=LoanStatusCodes.PAID_OFF)

    def not_paid_active(self):
        return self.filter(loan_status__status_code__range=(LoanStatusCodes.LOAN_1DPD,
                                                            LoanStatusCodes.LOAN_180DPD))

    def all_active_mtl(self):
        return self.filter(loan_status__gte=LoanStatusCodes.CURRENT,
                           loan_status__lt=LoanStatusCodes.PAID_OFF,
                           application__product_line__product_line_code__in=ProductLineCodes.mtl())

    def exclude_julo_one(self):
        return self.exclude(account__isnull=False)

    def all_active_julo_one(self):
        return self.filter(loan_status__gte=LoanStatusCodes.CURRENT,
                           loan_status__lt=LoanStatusCodes.PAID_OFF,
                           account__isnull=False)

    def disbursed(self):
        return self.filter(fund_transfer_ts__isnull=False).exclude(loan_disbursement_amount=0)


class LoanManager(GetInstanceMixin, JuloModelManager):

    def get_queryset(self):
        return LoanQuerySet(self.model)

    def create(self, *args, **kwargs):
        loan = super(LoanManager, self).create(*args, **kwargs)
        loan.generate_xid()
        loan.save(update_fields=["loan_xid"])
        return loan


class Loan(TimeStampedModel):
    id = models.AutoField(db_column='loan_id', primary_key=True)

    customer = models.ForeignKey('Customer',
                                 models.DO_NOTHING,
                                 db_column='customer_id')
    application = models.OneToOneField('Application',
                                       models.DO_NOTHING,
                                       db_column='application_id',
                                       blank=True,
                                       null=True)
    offer = models.ForeignKey('Offer',
                              models.DO_NOTHING,
                              db_column='offer_id',
                              blank=True,
                              null=True)
    loan_status = models.ForeignKey('StatusLookup',
                                    models.DO_NOTHING,
                                    db_column='loan_status_code')
    product = models.ForeignKey('ProductLookup',
                                models.DO_NOTHING,
                                db_column='product_code',
                                blank=True, null=True)

    application_xid = models.ForeignKey('Application',
                                        models.DO_NOTHING,
                                        db_column='application_xid',
                                        related_name='+',
                                        blank=True, null=True)
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='agent_id', blank=True, null=True)
    agent_2 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='agent_2', related_name='agent_2', blank=True, null=True)

    agent_3 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='agent_3', related_name='agent_3', blank=True, null=True)

    partner = models.ForeignKey('Partner',
                                models.DO_NOTHING,
                                db_column='partner',
                                blank=True, null=True)

    loan_amount = models.BigIntegerField()
    loan_duration = models.IntegerField()
    sphp_sent_ts = models.DateTimeField(blank=True, null=True)
    sphp_accepted_ts = models.DateTimeField(blank=True, null=True)
    first_installment_amount = models.BigIntegerField()
    installment_amount = models.BigIntegerField()
    cashback_earned_total = models.BigIntegerField(default=0)
    initial_cashback = models.BigIntegerField(default=0)
    loan_disbursement_amount = models.BigIntegerField(default=0)
    loan_disbursement_method = models.TextField(blank=True, null=True)
    fund_transfer_ts = models.DateTimeField(blank=True, null=True)
    julo_bank_name = models.CharField(max_length=250, blank=True)
    julo_bank_branch = models.CharField(max_length=100, blank=True)
    julo_bank_account_number = models.CharField(
        max_length=50,
        blank=True,
        validators=[RegexValidator(
            regex='^[0-9]+$', message='Bank account number has to be numeric digits')])
    cycle_day = models.IntegerField(blank=True, null=True,
                                    validators=[MinValueValidator(1),
                                                MaxValueValidator(28)])
    cycle_day_change_date = models.DateField(blank=True, null=True)
    cycle_day_requested = models.IntegerField(blank=True, null=True,
                                              validators=[MinValueValidator(1),
                                                          MaxValueValidator(28)])
    cycle_day_requested_date = models.DateField(blank=True, null=True)
    is_ignore_calls = models.BooleanField(default=False)
    name_bank_validation_id = models.BigIntegerField(null=True,
                                                     blank=True,
                                                     db_index=True)
    disbursement_id = models.BigIntegerField(null=True,
                                             blank=True,
                                             db_index=True)
    lender = models.ForeignKey('followthemoney.LenderCurrent',
                               models.DO_NOTHING,
                               db_column='lender_id',
                               null=True,
                               blank=True)
    credit_matrix = models.ForeignKey('julo.CreditMatrix',
                                      models.DO_NOTHING,
                                      db_column='credit_matrix_id',
                                      blank=True, null=True)
    insurance_policy_number = models.CharField(max_length=100, blank=True, null=True)
    is_restructured = models.BooleanField(default=False)
    ever_entered_B5 = models.BooleanField(default=False)
    is_settled_1 = models.NullBooleanField()
    is_settled_2 = models.NullBooleanField()
    is_warehouse_1 = models.NullBooleanField()
    is_warehouse_2 = models.NullBooleanField()
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True)
    loan_xid = models.BigIntegerField(blank=True, null=True, db_index=True)
    bank_account_destination = models.ForeignKey(
        'customer_module.BankAccountDestination',
        models.DO_NOTHING,
        db_column='bank_account_destination_id',
        blank=True,
        null=True
    )

    loan_purpose = models.TextField(blank=True, null=True)
    sphp_exp_date = models.DateField(blank=True, null=True)
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod',
        models.DO_NOTHING,
        db_column='transaction_method_id',
        blank=True,
        null=True
    )

    # this below field application_id2 need to filled only for analytic purposes
    # currently this field use for get which active application when this loan created
    # related to jTurbo
    application_id2 = models.BigIntegerField(null=True, blank=True, db_index=True)
    is_5_days_unreachable = models.BooleanField(default=False)
    is_broken_ptp_plus_1 = models.BooleanField(default=False)
    loan_duration_unit = models.ForeignKey(
        'LoanDurationUnit',
        models.DO_NOTHING,
        db_column='loan_duration_unit_id',
        db_constraint=False,
        null=True,
        blank=True,
    )

    objects = LoanManager()
    tracker = FieldTracker(fields=['loan_status_id'])

    MAX_CYCLE_DAY = 28
    SPHP_EXPIRATION_DAYS = 3

    class Meta(object):
        db_table = 'loan'

    def __str__(self):
        return str(self.id)

    def save(self, *args, **kwargs):
        # no need to worry about instance.save(update_fields=['udate'])
        # we handle that automatically
        if kwargs and kwargs.get('update_fields'):
            if 'udate' not in kwargs['update_fields']:
                kwargs['update_fields'].append("udate")
        if not self.application_id2:
            if self.account:
                application = self.account.get_active_application()
                if application:
                    self.application_id2 = application.id
            elif self.application_id:
                self.application_id2 = self.application_id
        super(TimeStampedModel, self).save(*args, **kwargs)

    @property
    def status(self):
        return self.loan_status_id

    @property
    def is_julo_one_loan(self):
        if self.account:
            return True
        return False

    def is_j1_or_jturbo_loan(self):
        return self.product.product_line_id in [ProductLineCodes.J1, ProductLineCodes.JTURBO]

    def is_julover_loan(self):
        return self.product.product_line_id == ProductLineCodes.JULOVER

    def is_grab_loan(self):
        return self.product.product_line_id == ProductLineCodes.GRAB

    @property
    def total_installment(self):
        return self.loan_duration * self.installment_amount

    def process_paid_off(self, record_history = True):
        from juloserver.apiv2.services import is_customer_paid_on_time
        from juloserver.julo.tasks import loan_paid_off_PN
        from juloserver.referral.services import generate_customer_level_referral_code
        old_status_code = self.loan_status
        self.change_status(StatusLookup.PAID_OFF_CODE)
        if record_history:
            self.record_history(old_status_code, "Process Paid Off")

        # Re-applying processing
        customer = self.customer
        can_reapply, potential_skip_pv_dv, reapply_date = customer.process_can_reapply(self)
        customer.can_reapply = can_reapply
        customer.potential_skip_pv_dv = potential_skip_pv_dv
        customer.can_reapply_date = reapply_date
        customer.save()
        # block notify to ICare client
        if customer.can_notify:
            if not self.application:
                self.application = Application.objects.get(id=self.application_id2)
            paid_on_time = is_customer_paid_on_time(customer, self.application.id)
            if paid_on_time:
                loan_paid_off_PN.delay(customer.id)
        # generate_referral_code
        generate_customer_level_referral_code(self.application)

    def update_status(self, record_history=True):
        from juloserver.loan_refinancing.constants import LoanRefinancingStatus
        from juloserver.loan_refinancing.services.loan_related import (
            get_loan_refinancing_active_obj,
        )

        # we prevent update only for halted grab loan
        if self.status in {LoanStatusCodes.HALT, LoanStatusCodes.LOAN_INVALIDATED}:
            return False

        # never update sold off loan
        if self.status == LoanStatusCodes.SELL_OFF:
            return True

        unpaid_payments = list(Payment.objects.by_loan(self).not_paid())
        loan_refinancing = get_loan_refinancing_active_obj(self)
        old_status_code = self.loan_status

        if len(unpaid_payments) == 0:
            if self.status == LoanStatusCodes.RENEGOTIATED:
                self.process_paid_off(record_history)
                return True

            else:
                # When all payments have been paid
                if self.product.has_cashback:
                    cashback_payments = self.payment_set.aggregate(
                        total=Sum('cashback_earned'))['total']
                    cashback_earned = cashback_payments + self.initial_cashback
                    customer = self.customer
                    customer.change_wallet_balance(change_accruing=0,
                                                   change_available=cashback_earned,
                                                   reason='loan_paid_off')
                self.process_paid_off(record_history)
                if loan_refinancing:
                    loan_refinancing.change_status(LoanRefinancingStatus.PAID_OFF)
                    loan_refinancing.save()

                return True

        elif self.status == LoanStatusCodes.RENEGOTIATED:
            return True

        overdue_payments = []
        for unpaid_payment in unpaid_payments:
            if unpaid_payment.is_overdue:
                overdue_payments.append(unpaid_payment)
        if len(overdue_payments) == 0:
            # When some payments are unpaid but none is overdue
            self.change_status(StatusLookup.CURRENT_CODE)
            if record_history:
                self.record_history(old_status_code, "Update Status Current")
            return True

        # When any of the unpaid payments is overdue
        most_overdue_payment = overdue_payments[0]
        for overdue_payment in overdue_payments:
            status_code = overdue_payment.payment_status.status_code
            if status_code > most_overdue_payment.payment_status.status_code:
                most_overdue_payment = overdue_payment
        # check if loan.status is active
        if self.status != StatusLookup.INACTIVE_CODE:
            status_code = most_overdue_payment.payment_status.status_code
            if status_code == StatusLookup.PAYMENT_1DPD_CODE:
                self.change_status(StatusLookup.LOAN_1DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_4DPD_CODE:
                self.change_status(StatusLookup.LOAN_4DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_5DPD_CODE:
                self.change_status(StatusLookup.LOAN_5DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_8DPD_CODE:
                self.change_status(StatusLookup.LOAN_8DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_30DPD_CODE:
                self.change_status(StatusLookup.LOAN_30DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_60DPD_CODE:
                self.change_status(StatusLookup.LOAN_60DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_90DPD_CODE:
                self.change_status(StatusLookup.LOAN_90DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_120DPD_CODE:
                self.change_status(StatusLookup.LOAN_120DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_150DPD_CODE:
                self.change_status(StatusLookup.LOAN_150DPD_CODE)
            elif status_code == StatusLookup.PAYMENT_180DPD_CODE:
                self.change_status(StatusLookup.LOAN_180DPD_CODE)
            else:
                logger.warn({
                    'payment': most_overdue_payment,
                    'payment_status': most_overdue_payment.payment_status,
                    'action': 'not_updating_status'
                })
                return False

            if record_history:
                self.record_history(old_status_code, "Update Status by DPD")

            return True
        else:
            logger.warn({
                'payment': most_overdue_payment,
                'payment_status': most_overdue_payment.payment_status,
                'loan_status': self.status,
                'action': 'not_updating_status'
            })
            return False

    def change_status(self, status_code):
        previous_status = self.loan_status

        # never update sold off loan
        if previous_status == LoanStatusCodes.SELL_OFF:
            new_status = previous_status
        else:
            new_status = StatusLookup.objects.get(status_code=status_code)
        self.loan_status = new_status
        logger.info({
            'previous_status': previous_status,
            'new_status': new_status,
            'action': 'changing_status'
        })

    def record_history(self, old_status_code, reason):
        new_status_code = self.loan_status
        if old_status_code != new_status_code:
            loan_history_data = {
                'loan': self,
                'status_old': old_status_code.status_code,
                'status_new': new_status_code.status_code,
                'change_reason': reason,
            }
            LoanHistory.objects.create(**loan_history_data)
        else:
            logger.info({
                'loan': self,
                'status_old': old_status_code.status_code,
                'status_new': new_status_code.status_code,
                'action': 'loan.record_history',
                'message': 'nothing is changed',
            })

    def set_fund_transfer_time(self):
        self.fund_transfer_ts = datetime.today()
        logger.info({
            'fund_transfer_ts': self.fund_transfer_ts,
            'action': 'timestamping_fund_transfer'
        })

    @property
    def cashback_monthly(self):

        if self.loan_amount <= 0:
            return 0

        if self.loan_duration <= 0:
            return 0

        return compute_cashback_monthly(
            self.loan_amount, self.product.cashback_payment_pct, self.loan_duration)

    def new_cashback_monthly(self, counter):
        if counter == 0:
            return 0

        if self.loan_amount <= 0:
            return 0

        if self.loan_duration <= 0:
            return 0

        return compute_new_cashback_monthly(
            self.loan_amount, self.product.cashback_payment_pct, self.loan_duration, counter)

    @property
    def late_fee_amount(self):
        application = self.application
        if not application:
            application = self.account.last_application

        if application.product_line.product_line_code in ProductLineCodes.stl():
            return 100000

        elif application.product_line.product_line_code in (
                ProductLineCodes.julo_one() + ProductLineCodes.manual_process()
        ):
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value, -2)

        elif application.product_line.product_line_code in ProductLineCodes.mtl():
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value if value > 55000 else 55000, -2)

        elif application.product_line.product_line_code in ProductLineCodes.bri():
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value if value > 55000 else 55000, -2)

        elif application.product_line.product_line_code in ProductLineCodes.grab():
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value, -2)

        elif application.product_line.product_line_code in ProductLineCodes.grabfood():
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value, -2)

        elif application.product_line.product_line_code in ProductLineCodes.laku6():
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value if value > 55000 else 55000, -2)

        elif application.product_line.product_line_code in ProductLineCodes.pedemtl():
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value if value > 55000 else 55000, -2)

        elif application.product_line.product_line_code in ProductLineCodes.pedestl():
            return 100000

        elif application.product_line.product_line_code in ProductLineCodes.axiata():
            value = self.product.late_fee_pct * self.installment_amount

            return py2round(value if value > 55000 else 55000, -2)
        elif application.product_line.product_line_code in ProductLineCodes.merchant_financing():
            value = self.product.late_fee_pct * self.loan_disbursement_amount
            return py2round(value, -2)
        elif application.product_line.product_line_code == ProductLineCodes.JULO_STARTER:
            value = self.product.late_fee_pct * self.installment_amount
            return py2round(value, -2)
        else:
            return 0

    @property
    def interest_rate_monthly(self):
        # Use credit_matrix_repeat instead of credit_matrix if exist
        credit_matrix_repeat_loan = CreditMatrixRepeatLoan.objects.filter(loan=self).first()
        tenor_based_pricing = self.tenorbasedpricing_set.first()
        if tenor_based_pricing and tenor_based_pricing.new_pricing:
            monthly_interest_rate = tenor_based_pricing.new_pricing

        elif credit_matrix_repeat_loan and credit_matrix_repeat_loan.credit_matrix_repeat:
            monthly_interest_rate = credit_matrix_repeat_loan.credit_matrix_repeat.interest

        else:
            monthly_interest_rate = self.product.monthly_interest_rate

        if hasattr(self, 'loanadjustedrate'):
            monthly_interest_rate = self.loanadjustedrate.adjusted_monthly_interest_rate
        if hasattr(self, 'loanzerointerest'):
            monthly_interest_rate = 0

        return py2round(monthly_interest_rate, 3)

    @property
    def loan_status_label(self):
        return StatusLookup.STATUS_LABEL_BAHASA.get(self.loan_status.status_code, '')

    @property
    def late_fee_rate_per_day(self):
        return py2round(self.product.late_fee_pct * 100, 3)

    @property
    def grab_loan_description(self):
        from juloserver.grab.constants import grab_status_description
        loan_status_code = self.loan_status.status_code
        grab_loan_description = None
        for grab_description in grab_status_description:
            if loan_status_code in grab_description.list_code:
                grab_loan_description = grab_description.mapping_status
        return grab_loan_description

    def update_cycle_day(self):
        old_cycle_day = self.cycle_day
        self.cycle_day = self.cycle_day_requested
        self.cycle_day_change_date = date.today()
        self.cycle_day_requested = None
        logger.info({
            'old_cycle_day': old_cycle_day,
            'new_cycle_day': self.cycle_day,
            'cycle_day_requested': self.cycle_day_requested,
            'cycle_day_change_date': self.cycle_day_change_date,
            'action': 'updating_cycle_day',
            'status': 'updated'
        })

    @property
    def is_active(self):
        code = self.loan_status.status_code
        return LoanStatusCodes.CURRENT <= code <= LoanStatusCodes.RENEGOTIATED

    def set_disbursement_amount(self, promo_code_data=None):
        tax_fee = self.get_loan_tax_fee()
        digisign_fee = self.get_loan_digisign_fee()
        registration_fee = self.get_loan_registration_fee()
        origination_fee = self.provision_fee(promo_code_data=promo_code_data)
        self.loan_disbursement_amount = int(
            py2round(
                self.loan_amount - origination_fee - tax_fee - digisign_fee - registration_fee
            )
        )
        logger.info(
            {
                'status': 'loan_disbursement_amount_set',
                'origination_fee': origination_fee,
                'tax_fee': tax_fee,
                'digisign_fee': digisign_fee,
                'registration_fee': registration_fee,
                'loan_disbursement_amount': self.loan_disbursement_amount,
                'loan_id': self.id,
            }
        )

    def provision_fee(self, promo_code_data=None):
        from juloserver.promo.constants import PromoCodeBenefitConst
        # Use credit_matrix_repeat instead of credit_matrix if exist
        credit_matrix_repeat_loan = CreditMatrixRepeatLoan.objects.filter(loan=self).first()
        if credit_matrix_repeat_loan and credit_matrix_repeat_loan.credit_matrix_repeat:
            origination_fee_pct = credit_matrix_repeat_loan.credit_matrix_repeat.provision
        else:
            origination_fee_pct = self.product.origination_fee_pct

        if hasattr(self, 'loanadjustedrate'):
            origination_fee_pct = self.loanadjustedrate.adjusted_provision_rate

        loan_amount = self.loan_amount
        if hasattr(self, 'loanzerointerest'):
            loan_amount = self.loanzerointerest.original_loan_amount

        # Tax, registration_fee and digisign_fee have to be calculated here
        #      or else will messed up disbursement amount
        # only for non tarik dana since its increases the loan_amount
        if self.transaction_method_id != TransactionMethodCode.SELF.code:
            tax_fee = self.get_loan_tax_fee()
            digisign_fee = self.get_loan_digisign_fee()
            registration_fee = self.get_loan_registration_fee()
            loan_amount -= (tax_fee + digisign_fee + registration_fee)
        
        # Apply provision discount for calculating disbursement amount
        if promo_code_data and\
            promo_code_data.get('type') in [PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
                                            PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT]:
            apply_benefit_service_handler = promo_code_data.get('handler')
            _, origination_fee = apply_benefit_service_handler(
                loan_amount=loan_amount,
                provision_rate=origination_fee_pct,
            )
        else:
            origination_fee = loan_amount * origination_fee_pct

        if hasattr(self, 'loanjulocare'):
            origination_fee += self.loanjulocare.insurance_premium

        if hasattr(self, 'loandelaydisbursementfee'):
            origination_fee += self.loandelaydisbursementfee.delay_disbursement_premium_fee

        return py2round(origination_fee)

    @property
    def provision_rate(self):
        # use for zero interest
        credit_matrix_repeat_loan = CreditMatrixRepeatLoan.objects.filter(loan=self).first()
        if credit_matrix_repeat_loan and credit_matrix_repeat_loan.credit_matrix_repeat:
            origination_fee_pct = credit_matrix_repeat_loan.credit_matrix_repeat.provision
        else:
            origination_fee_pct = self.product.origination_fee_pct

        if hasattr(self, 'loanadjustedrate'):
            origination_fee_pct = self.loanadjustedrate.adjusted_provision_rate

        return py2round(origination_fee_pct, 3)

    @property
    def disbursement_fee(self):
        if hasattr(self, 'loanzerointerest'):
            return self.loan_amount - (self.loan_disbursement_amount +  self.provision_fee())
        return 0

    @property
    def is_zero_interest(self):
        if hasattr(self, 'loanzerointerest'):
            return True
        return False

    @property
    def disbursement_rate(self):
        if hasattr(self, 'loanzerointerest'):
            return py2round(self.loanzerointerest.adjusted_provision_rate - self.provision_rate, 2)
        return 0

    def interest_percent_monthly(self):
        # Use credit_matrix_repeat instead of credit_matrix if exist
        credit_matrix_repeat_loan = CreditMatrixRepeatLoan.objects.filter(loan=self).first()
        if credit_matrix_repeat_loan and credit_matrix_repeat_loan.credit_matrix_repeat:
            monthly_interest_rate = credit_matrix_repeat_loan.credit_matrix_repeat.interest
        else:
            monthly_interest_rate = self.product.monthly_interest_rate

        if hasattr(self, 'loanzerointerest'):
            return 0

        if hasattr(self, 'loanadjustedrate'):
            monthly_interest_rate = self.loanadjustedrate.adjusted_monthly_interest_rate

        return round(monthly_interest_rate * 100, 2)

    def update_cashback_earned_total(self, cashback_earned):
        previous_total = self.cashback_earned_total
        new_total = self.cashback_earned_total + cashback_earned
        self.cashback_earned_total = new_total
        logger.info({
            'previous_cashback_earned_total': previous_total,
            'new_cashback_earned_total': new_total,
            'cashback_earned': cashback_earned
        })

    @property
    def payment_virtual_accounts(self):
        return list(BankVirtualAccount.objects.filter(loan=self).values())

    @property
    def max_total_late_fee_amount(self):
        return self.loan_amount * MAX_LATE_FEE_RATE

    def get_status_max_late_fee(self, late_fee_amount):
        payment_sum = self.payment_set.aggregate(
            total_current_late_fee=Sum('late_fee_amount'),
            total_interest=Sum('installment_interest'),
            total_change_due_date_interest=Sum('change_due_date_interest'))
        total_current_late_fee = payment_sum['total_current_late_fee']
        total_interest = payment_sum['total_interest']
        total_change_due_date_interest = payment_sum['total_change_due_date_interest']
        new_late_fee_amount = late_fee_amount + total_current_late_fee
        new_late_fee_interest = new_late_fee_amount + total_interest
        # total accumulate amount after apply new late_fee + interest
        new_late_fee_interest += total_change_due_date_interest
        total_current_late_fee_interest = total_current_late_fee + total_interest
        # total accumulate amount before apply new late fee
        total_current_late_fee_interest += total_change_due_date_interest
        if total_current_late_fee_interest >= self.loan_amount:
            return 0, True
        elif new_late_fee_interest <= self.loan_amount:
            return late_fee_amount, False
        else:
            return self.loan_amount - total_current_late_fee_interest, False

    def get_ontime_payment(self):
        ontime_payments = self.payment_set.filter(
            payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        ontime_payments_count = len(ontime_payments)
        for payment in ontime_payments:
            if payment.paymentevent_set.filter(event_type='due_date_adjustment'):
                ontime_payments_count -= 1
        return ontime_payments_count

    def get_oldest_unpaid_payment(self):
        exclude_statuses = (LoanStatusCodes.INACTIVE,
                            LoanStatusCodes.DRAFT,
                            LoanStatusCodes.PAID_OFF,
                            LoanStatusCodes.RENEGOTIATED)
        if self.status in exclude_statuses:
            return None
        oldest_unpaid = self.payment_set.not_paid_active()\
                                        .order_by('payment_number')\
                                        .first()
        return oldest_unpaid

    def get_last_unpaid_payment(self):
        return self.payment_set.not_paid_active().order_by(
            'due_date').first()

    def get_oldest_unpaid_payment_grab(self):
        oldest_unpaid = self.payment_set.not_paid_active()\
                                        .order_by('payment_number')\
                                        .first()
        return oldest_unpaid

    def generate_xid(self):
        if self.id is None or self.loan_xid is not None:
            return
        self.loan_xid = XidLookup.get_new_xid()

    def set_sphp_expiration_date(self):
        today = date.today()
        expiration_time_delta = timedelta(days=self.SPHP_EXPIRATION_DAYS)
        sphp_expiration_date = today + expiration_time_delta
        self.sphp_exp_date = sphp_expiration_date
        self.save()
        logger.debug({
            'validity_days': expiration_time_delta.days,
            'sphp_expiration_date': sphp_expiration_date,
            'status': 'set'
        })

    @property
    def sphp_expired(self):
        expired = False
        today = date.today()
        expired_time_delta = today - self.sphp_exp_date
        expired_days = expired_time_delta.days
        if expired_days > 0:
            expired = True
        logger.debug({
            'today': today,
            'offer_expiration_date': self.sphp_exp_date,
            'days_before_expire': -expired_days,
            'expired': expired
        })
        return expired

    @property
    def loan_status_label_julo_one(self):
        if self.status == LoanStatusCodes.CURRENT:
            status = 'Sedang berjalan'
        else:
            status = StatusLookup.STATUS_LABEL_BAHASA.get(self.loan_status_id, '')
        return status

    @property
    def get_application(self):
        # this function is for get application from application_id2 for J1
        if not self.account_id:
            return self.application
        elif self.account_id:
            application = Application.objects.get_or_none(pk=self.application_id2)
            if application:
                return application
            return self.account.get_active_application()

    @property
    def disbursement_date(self):
        from juloserver.disbursement.models import Disbursement as Disbursement2
        disbursement = Disbursement2.objects.get_or_none(id=self.disbursement_id)
        return disbursement.cdate if disbursement else self.fund_transfer_ts if self.fund_transfer_ts else None

    @property
    def dpd(self):
        payment = self.payment_set.normal().not_paid_active().order_by('payment_number').first()
        if not payment:
            return 0

        return payment.get_dpd

    def get_outstanding_principal(self):
        total_principal = self.payment_set.aggregate(
            Sum('installment_principal'))['installment_principal__sum']
        paid_principal = self.payment_set.aggregate(
            Sum('paid_principal'))['paid_principal__sum']
        return total_principal - paid_principal

    def get_outstanding_interest(self):
        total_interest = self.payment_set.aggregate(
            Sum('installment_interest'))['installment_interest__sum']
        paid_interest = self.payment_set.aggregate(
            Sum('paid_interest'))['paid_interest__sum']
        return total_interest - paid_interest

    def get_outstanding_late_fee(self):
        total_late_fee = self.payment_set.aggregate(
            Sum('late_fee_amount'))['late_fee_amount__sum']
        paid_late_fee = self.payment_set.aggregate(
            Sum('paid_late_fee'))['paid_late_fee__sum']
        return total_late_fee - paid_late_fee

    def get_total_outstanding_due_amount(self):
        today = timezone.localtime(timezone.now()).date()
        due_amount_outstanding = self.payment_set.not_paid_active().filter(
            due_date__lte=today).aggregate(Sum('due_amount'))['due_amount__sum']
        return due_amount_outstanding if due_amount_outstanding else 0

    def get_total_outstanding_amount(self):
        return self.payment_set.not_paid_active().aggregate(
            Sum('due_amount'))['due_amount__sum'] or 0

    def get_unpaid_payment_ids(self):
        return self.payment_set.not_paid_active().order_by(
            'due_date').values_list('id', flat=True)

    def get_loan_tax_fee(self):
        from juloserver.loan.constants import LoanTaxConst
        from juloserver.loan.models import LoanAdditionalFee

        loan_tax = LoanAdditionalFee.objects.filter(
            loan_id=self.id,
            fee_type__name=LoanTaxConst.ADDITIONAL_FEE_TYPE
        ).values_list('fee_amount', flat=True).last()
        return loan_tax if loan_tax else 0

    def get_loan_digisign_fee(self):
        from juloserver.loan.constants import LoanDigisignFeeConst
        from juloserver.loan.models import LoanAdditionalFee

        fee_amount = LoanAdditionalFee.objects.filter(
            loan_id=self.id,
            fee_type__name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE
        ).values_list('fee_amount', flat=True).last()
        return fee_amount if fee_amount else 0

    def get_loan_registration_fee(self):
        from juloserver.loan.constants import LoanDigisignFeeConst
        from juloserver.loan.models import LoanAdditionalFee

        fee_amounts = LoanAdditionalFee.objects.filter(
            loan_id=self.id,
            fee_type__name__in=[
                LoanDigisignFeeConst.REGISTRATION_DUKCAPIL_FEE_TYPE,
                LoanDigisignFeeConst.REGISTRATION_FR_FEE_TYPE,
                LoanDigisignFeeConst.REGISTRATION_LIVENESS_FEE_TYPE,
            ]
        ).values_list('fee_amount', flat=True)

        return sum(list(fee_amounts))

    def get_digisign_and_registration_fee(self):
        from juloserver.loan.constants import LoanDigisignFeeConst
        from juloserver.loan.models import LoanAdditionalFee

        fee_amounts = LoanAdditionalFee.objects.filter(
            loan_id=self.id,
            fee_type__name__in=LoanDigisignFeeConst.digisign_plus_register_types(),
        ).values_list('fee_amount', flat=True)

        return sum(list(fee_amounts))

    @property
    def calculated_total_paid_amount(self):
        return self.payment_set.all().aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0

    @property
    def calculated_overdue_unpaid_amount(self):
        return self.get_total_outstanding_due_amount()

    @property
    def calculated_total_due_amount(self):
        return self.get_total_outstanding_amount()

    @property
    def is_qris_product(self):
        return self.transaction_method_id == TransactionMethodCode.QRIS.code

    def is_payment_point_product(self):
        return self.transaction_method_id in TransactionMethodCode.payment_point()

    def is_rentee_loan(self):
        return self.product.product_line_id == ProductLineCodes.RENTEE

    def is_mf_loan(self):
        return self.product.product_line_id == ProductLineCodes.MF

    def is_mf_std_loan(self):
        return self.product.product_line_id == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT

    @property
    def is_credit_card_product(self):
        return self.transaction_method_id == TransactionMethodCode.CREDIT_CARD.code

    @property
    def is_ecommerce_product(self):
        return self.transaction_method_id == TransactionMethodCode.E_COMMERCE.code

    @property
    def is_education_product(self):
        return self.transaction_method_id == TransactionMethodCode.EDUCATION.code

    @property
    def is_healthcare_product(self):
        return self.transaction_method_id == TransactionMethodCode.HEALTHCARE.code

    @property
    def is_electricity_product(self):
        return self.transaction_method_id == TransactionMethodCode.LISTRIK_PLN.code

    @property
    def is_water_product(self):
        return self.transaction_method_id == TransactionMethodCode.PDAM.code

    @property
    def is_bpjs_product(self):
        return self.transaction_method_id == TransactionMethodCode.BPJS_KESEHATAN.code

    @property
    def is_train_ticket_product(self):
        return self.transaction_method_id == TransactionMethodCode.TRAIN_TICKET.code

    @property
    def is_ewallet_product(self):
        return self.transaction_method_id == TransactionMethodCode.DOMPET_DIGITAL.code

    @property
    def is_to_self(self):
        return self.transaction_method_id == TransactionMethodCode.SELF.code

    @property
    def is_to_other(self):
        return self.transaction_method_id == TransactionMethodCode.OTHER.code

    @property
    def is_mobile_product(self):
        return self.transaction_method_id == TransactionMethodCode.PULSA_N_PAKET_DATA.code

    @property
    def is_mobile_postpaid(self):
        return self.transaction_method_id == TransactionMethodCode.PASCA_BAYAR.code

    @property
    def is_jfinancing_product(self):
        return self.transaction_method_id == TransactionMethodCode.JFINANCING.code

    @property
    def is_qris_1_product(self):
        return self.transaction_method_id == TransactionMethodCode.QRIS_1.code

    @property
    def disbursement_status(self):
        from juloserver.disbursement.models import Disbursement as Disbursement2

        disbursement_status = ''
        if self.disbursement_id:
            disbursement = Disbursement2.objects.get_or_none(id=self.disbursement_id)
            disbursement_history = disbursement.disbursement2history_set.last()
            if disbursement_history:
                disbursement_status = 'Step {}'.format(disbursement_history.step)
        elif self.is_qris_product:
            disbursement_status = self.qris_transaction.transaction_status
        elif self.is_ppob_transaction:
            sepulsa_transaction = self.sepulsatransaction_set.last()
            disbursement_status = sepulsa_transaction.transaction_status

        return disbursement_status

    @property
    def is_cash_transaction(self):
        if self.transaction_method_id in TransactionMethodCode.cash():
            return True

        return False

    @property
    def juloshop_transaction(self):
        from juloserver.ecommerce.juloshop_service import (
            get_juloshop_transaction_by_loan,
        )

        if hasattr(self, '_juloshop_transaction'):
            return self._juloshop_transaction

        # set juloshop transaction
        juloshop_transaction = get_juloshop_transaction_by_loan(self)
        self._juloshop_transaction = juloshop_transaction

        return self._juloshop_transaction

    @property
    def is_xfers_ewallet_transaction(self):
        return hasattr(self, 'xfers_ewallet_transaction')

    @property
    def fund_id(self):
        from juloserver.ecommerce.juloshop_service import (
            get_juloshop_transaction_by_loan,
        )
        from juloserver.qris.models import DokuQrisTransactionPayment

        fund_id = None
        if self.disbursement_id:
            fund_id = self.disbursement_id
        elif self.is_ppob_transaction:
            sepulsa_transaction = self.sepulsatransaction_set.last()
            fund_id = sepulsa_transaction.id if sepulsa_transaction else None
        elif self.is_qris_product:
            qr_payment = DokuQrisTransactionPayment.objects.filter(loan=self).last()
            if qr_payment:
                fund_id = qr_payment.invoice
        elif self.is_ecommerce_product:
            juloshop_transaction = get_juloshop_transaction_by_loan(self)
            if juloshop_transaction:
                fund_id = juloshop_transaction.transaction_xid
        return fund_id

    @property
    def is_ppob_transaction(self):
        sepulsa_transaction = self.sepulsatransaction_set.last()
        if sepulsa_transaction:
            return True

        return False

    @property
    def ppob_number(self):
        sepulsa_transaction = self.sepulsatransaction_set.last()
        if not sepulsa_transaction:
            return None
        ppob_number = sepulsa_transaction.customer_number
        if not ppob_number:
            ppob_number = sepulsa_transaction.phone_number
        return ppob_number

    @property
    def transaction_detail(self):
        from juloserver.customer_module.services.bank_account_related import (
            is_ecommerce_bank_account,
        )
        from juloserver.ecommerce.juloshop_service import (
            get_juloshop_transaction_by_loan,
        )
        from juloserver.julo.partners import PartnerConstant
        from juloserver.julo.utils import display_rupiah
        from juloserver.qris.models import DokuQrisTransactionPayment
        from juloserver.payment_point.services.sepulsa import (
            get_payment_point_transaction_from_loan,
        )
        from juloserver.balance_consolidation.services import \
            get_transaction_detail_balance_consolidation

        transaction_detail = ''
        if self.is_cash_transaction:
            application = self.account.last_application
            if application.is_merchant_flow():
                bank_name = application.merchant.distributor.bank_name
                account_number = application.merchant.distributor.bank_account_number
            else:
                if not self.bank_account_destination:
                    bank_name = '-'
                    account_number = '-'
                else:
                    bank_name = self.bank_account_destination.get_bank_name
                    account_number = self.bank_account_destination.account_number
            transaction_detail = '{}, {}'.format(bank_name, account_number)
        elif is_ecommerce_bank_account(self.bank_account_destination):
            transaction_detail = '{}, {}, {}'.format(
                self.bank_account_destination.description,
                self.bank_account_destination.get_bank_name,
                self.bank_account_destination.account_number,
            )
        elif self.transaction_method_id in TransactionMethodCode.payment_point():
            payment_point_transaction = get_payment_point_transaction_from_loan(
                loan=self,
            )
            price = payment_point_transaction.customer_amount
            if not price:
                price = payment_point_transaction.product.customer_price_regular

            transaction_detail = '{}, {}, {}'.format(
                payment_point_transaction.product.product_name,
                payment_point_transaction.product.category,
                display_rupiah(price),
            )
        elif self.is_qris_product:
            qr_payment = DokuQrisTransactionPayment.objects.filter(loan=self).last()
            if qr_payment:
                qr_scan = qr_payment.doku_qris_transaction_scan
                transaction_detail = '{}, {}'.format(
                    qr_scan.merchant_name,
                    qr_scan.merchant_city
                )
        elif self.is_credit_card_transaction:
            transaction_detail = self.transaction_method.fe_display_name
        elif self.is_ecommerce_product:
            juloshop_transaction = get_juloshop_transaction_by_loan(self)
            if juloshop_transaction:
                transaction_detail = '{}, {}'.format(
                    PartnerConstant.JULOSHOP,
                    juloshop_transaction.seller_name,
                )
        elif self.is_balance_consolidation:
            transaction_detail = get_transaction_detail_balance_consolidation(
                self.balanceconsolidationverification.balance_consolidation,
                self.transaction_method,
            )

        return transaction_detail

    @property
    def get_promo_code_usage(self):
        from juloserver.promo.services import get_promo_code_usage_on_loan_details

        return get_promo_code_usage_on_loan_details(self)

    @property
    def get_disbursement_date(self):
        disbursement_date = self.fund_transfer_ts
        if self.is_ppob_transaction:
            sepulsa_transaction = self.sepulsatransaction_set.last()
            disbursement_date = sepulsa_transaction.transaction_success_date

        return disbursement_date

    @property
    def is_unexpected_path(self):
        unexpected_path = self.loanhistory_set.order_by('cdate').last()
        if unexpected_path.status_old == LoanStatusCodes.CURRENT \
                and unexpected_path.status_new == LoanStatusCodes.FUND_DISBURSAL_FAILED:
            return True

        return False

    @property
    def partnership_status(self):
        from juloserver.partnership.constants import partnership_status_mapping_statuses
        partnership_status_code = 'UNKNOWN'
        for partnership_status in partnership_status_mapping_statuses:
            if self.loan_status.status_code == partnership_status.list_code:
                partnership_status_code = partnership_status.mapping_status
        return partnership_status_code

    @property
    def is_credit_card_transaction(self):
        if self.transaction_method_id == TransactionMethodCode.CREDIT_CARD.code:
            return True

        return False

    @property
    def transaction_detail_for_paid_letter(self):
        from juloserver.julo.utils import display_rupiah
        from juloserver.payment_point.services.sepulsa import (
            get_payment_point_transaction_from_loan,
        )

        if self.is_cash_transaction:
            application = self.account.last_application
            if application.is_merchant_flow():
                bank_name = application.merchant.distributor.bank_name
            else:
                bank_name = self.bank_account_destination.get_bank_name
            return "Transaksi  pencairan  limit  ke  rekening {} sebesar {},-".format(
                bank_name, display_rupiah(self.loan_disbursement_amount))
        elif self.transaction_method_id in TransactionMethodCode.payment_point():
            payment_point_transaction = get_payment_point_transaction_from_loan(
                loan=self,
            )
            price = payment_point_transaction.customer_amount
            if not price:
                price = payment_point_transaction.product.customer_price_regular
            return "Transaksi pembelian {} {} sebesar {},-".format(
                payment_point_transaction.product.category,
                payment_point_transaction.product.product_name,
                display_rupiah(price)
            )
        return self.transaction_detail

    def is_axiata_loan(self):
        if self.application and self.application.product_line_code in ProductLineCodes.axiata():
            return True
        return False

    def is_axiata_web_loan(self):
        if not self.application:
            self.application = Application.objects.get(id=self.application_id2)

        if self.application and self.application.product_line_code == ProductLineCodes.AXIATA_WEB:
            return True
        return False

    @property
    def is_balance_consolidation(self):
        return hasattr(self, 'balanceconsolidationverification')

    @property
    def is_first_time_220(self):
        first_loan = Loan.objects.filter(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            customer_id=self.customer_id
        ).first()
        return first_loan.id == self.id

    @property
    def is_ongoing_grab_loan(self):
        if not self.loan_status.status_code == LoanStatusCodes.FUND_DISBURSAL_ONGOING:
            return False
        if not self.account.account_lookup.workflow.name == WorkflowConst.GRAB:
            return False
        return True

    @property
    def transaction_detail_for_j1_300(self):
        from juloserver.customer_module.services.bank_account_related import (
            is_ecommerce_bank_account,
        )
        from juloserver.ecommerce.juloshop_service import (
            get_juloshop_transaction_by_loan,
        )
        from juloserver.julo.partners import PartnerConstant
        from juloserver.julo.utils import display_rupiah
        from juloserver.qris.models import DokuQrisTransactionPayment
        from juloserver.payment_point.services.sepulsa import (
            get_payment_point_transaction_from_loan,
        )

        transaction_detail = ''
        if self.is_cash_transaction:
            application = self.account.last_application
            if application.is_merchant_flow():
                bank_name = application.merchant.distributor.bank_name
                account_number = application.merchant.distributor.bank_account_number
            else:
                if not self.bank_account_destination:
                    bank_name = '-'
                    account_number = '-'
                else:
                    bank_name = self.bank_account_destination.get_bank_name
                    account_number = self.bank_account_destination.account_number

            masked_account_number = '*' * (len(account_number) - 3) + account_number[-3:]
            transaction_detail = '{}, {}'.format(bank_name, masked_account_number)
        elif is_ecommerce_bank_account(self.bank_account_destination):
            masked_account_number = self.bank_account_destination.account_number
            if masked_account_number:
                masked_account_number = '*' * (len(masked_account_number) - 3) + masked_account_number[-3:]
            transaction_detail = '{}, {}, {}'.format(
                self.bank_account_destination.description,
                self.bank_account_destination.get_bank_name,
                masked_account_number,
            )
        elif self.transaction_method_id in TransactionMethodCode.payment_point():
            payment_point_transaction = get_payment_point_transaction_from_loan(
                loan=self,
            )
            price = payment_point_transaction.customer_amount
            if not price:
                price = payment_point_transaction.product.customer_price_regular
            transaction_detail = '{}, {}, {}'.format(
                payment_point_transaction.product.product_name,
                payment_point_transaction.product.category,
                display_rupiah(price),
            )
        elif self.is_qris_product:
            qr_payment = DokuQrisTransactionPayment.objects.filter(loan=self).last()
            if qr_payment:
                qr_scan = qr_payment.doku_qris_transaction_scan
                transaction_detail = '{}, {}'.format(
                    qr_scan.merchant_name,
                    qr_scan.merchant_city
                )
        elif self.is_credit_card_transaction:
            transaction_detail = self.transaction_method.fe_display_name
        elif self.is_ecommerce_product:
            juloshop_transaction = get_juloshop_transaction_by_loan(self)
            if juloshop_transaction:
                transaction_detail = '{}, {}'.format(
                    PartnerConstant.JULOSHOP,
                    juloshop_transaction.seller_name,
                )
        return transaction_detail

    @property
    def oldest_unpaid_payment(self):
        return self.get_oldest_unpaid_payment()

    @property
    def total_installment_count(self):
        # get the last payment_number
        return self.payment_set.aggregate(Max('payment_number'))['payment_number__max'] or None

    @property
    def fund_transfer_ts_or_cdate(self):
        return self.fund_transfer_ts if self.fund_transfer_ts else self.cdate

    @property
    def sphp_accepted_ts_or_cdate(self):
        return self.sphp_accepted_ts if self.sphp_accepted_ts else self.cdate

# Uncomment this after delete field julo_bank_account_number
    # @property
    # def julo_bank_account_number(self):
    #     bank_virtual_account = self.bankvirtualaccount_set.all().first()
    #     return bank_virtual_account.virtual_account_number


class LoanStatusChange(StatusChangeModel):
    id = models.AutoField(db_column='loan_status_change_id', primary_key=True)

    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    # TODO: for some reason the api user is not being captured. Asking its
    # maintainer for help
    changed_by = CurrentUserField(related_name="loan_status_changes")

    class Meta(object):
        db_table = 'loan_status_change'


class RobocallTemplateManager(GetInstanceMixin, JuloModelManager):
    pass


class RobocallTemplate(TimeStampedModel):
    PROMISE_TO_PAY = 'PTP'
    DEFAULT = 'DEFAULT'
    PROMOTIONAL_MESSAGES = 'PROMO'
    ANNOUNCEMENT = 'ANNOUCE'
    MISCELLANEOUS = 'MISC'
    EXPERIMENT = 'EXPERIMENT'

    TEMPLATE_CATEGORY_CHOICES = (
        (PROMISE_TO_PAY, 'PTP'),
        (DEFAULT, 'Default'),
        (PROMOTIONAL_MESSAGES, 'Promos'),
        (ANNOUNCEMENT, 'Announce'),
        (MISCELLANEOUS, 'Misc'),
        (EXPERIMENT, 'EXPERIMENT')
    )

    id = models.AutoField(db_column='robocall_template_id', primary_key=True)
    template_name = models.CharField(max_length=150, unique=True)
    text = models.TextField()
    is_active = models.BooleanField(default=True)
    added_by = CurrentUserField()
    template_category = models.CharField(
        choices=TEMPLATE_CATEGORY_CHOICES, default=DEFAULT, max_length=7)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)

    objects = RobocallTemplateManager()

    class Meta(object):
        db_table = 'robocall_template'


class PaymentQuerySet(CustomQuerySet):
    def normal(self):
        return self.exclude(
            loan__loan_status=LoanStatusCodes.RENEGOTIATED).exclude(is_restructured=True)

    def renegotiated(self):
        return self.filter(loan__loan_status=LoanStatusCodes.RENEGOTIATED)

    def by_loan(self, loan):
        logger.info("Getting payments for loan_id=%s" % loan.id)
        return self.filter(loan=loan).exclude(is_restructured=True)

    def by_product_line_codes(self, codes):
        return self.filter(
            loan__application__product_line__product_line_code__in=codes,
            is_restructured=False)

    # get all loan which are not_paid
    def not_paid(self):
        # TODO: more check can be done here
        # query the active loan
        return self.filter(payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)\
                   .exclude(is_restructured=True)

    def paid(self):
        # query the active loan
        return self.filter(payment_status__gte=PaymentStatusCodes.PAID_ON_TIME,
                           payment_status__lte=PaymentStatusCodes.PAID_LATE)\
            .exclude(payment_status=PaymentStatusCodes.SELL_OFF)

    # get all active loan which are not_paid
    def not_paid_active(self):
        # TODO: more check can be done here
        # query the active loan
        qs = self.filter(loan__loan_status__gte=LoanStatusCodes.CURRENT)\
                 .exclude(loan__loan_status__in=[LoanStatusCodes.INACTIVE, LoanStatusCodes.DRAFT])\
                 .exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.grab())
        return qs.filter(payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                         is_restructured=False)

    def not_paid_active_julo_one(self):
        qs = self.exclude(loan__loan_status__in=[LoanStatusCodes.INACTIVE, LoanStatusCodes.DRAFT])
        return qs.filter(payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                         is_restructured=False)

    def due_soon(self, due_in_days=3):
        # TODO: more logic can be added here
        today = date.today()
        day_delta = timedelta(days=due_in_days)
        days_from_now = today + day_delta
        return self.not_paid_active().filter(due_date=days_from_now)

    def not_overdue(self):
        return self.filter(payment_status__lt=PaymentStatusCodes.PAYMENT_DUE_TODAY)\
                   .exclude(is_restructured=True)

    def overdue(self):
        today = timezone.localtime(timezone.now()).date()
        return self.not_paid_active().filter(due_date__lt=today)

    def due_today(self):
        today = timezone.localtime(timezone.now()).date()
        return self.not_paid_active().filter(due_date__lte=today)

    def dpd(self, days_pass_due):
        today = date.today()
        day_delta = timedelta(days=days_pass_due)
        dpd_date = today - day_delta
        return self.not_paid_active().filter(due_date=dpd_date)

    def dpd_groups(self, pass_date=6):
        today = date.today()
        day_delta = timedelta(days=pass_date)
        six_days_from_now = today + day_delta
        return self.not_paid_active().filter(due_date__lt=six_days_from_now)

    def dpd_groups_1to5(self):
        today = date.today()
        day_delta_1 = timedelta(days=1)
        day_delta_5 = timedelta(days=5)
        five_days_from_now = today + day_delta_5
        one_days_from_now = today + day_delta_1
        return self.not_paid_active().filter(
            due_date__range=[one_days_from_now, five_days_from_now])

    def dpd_to_be_called(self, is_intelix=False, only_base_query=False):
        from juloserver.julo.partners import PartnerConstant
        if only_base_query:
            return self.not_paid_active()

        return self.not_paid_active().filter(is_collection_called=False,
                                             loan__is_ignore_calls=False,
                                             is_whatsapp=False)\
            .exclude(loan__application__partner__name__in=PartnerConstant.excluded_partner_intelix()
                     if is_intelix else PartnerConstant.form_partner())

    def dpd_uncalled(self):
        yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
        return self.not_paid_active().filter(is_collection_called=False,
                                             uncalled_date=yesterday, ptp_date__isnull=True)\
            .exclude(loan__application__product_line_id__in=ProductLineCodes.grab())

    def dpd_groups_minus5and3and1(self):
        today = timezone.localtime(timezone.now())
        one_days_later = today + timedelta(days=1)
        # five_days_later = today + timedelta(days=5)
        three_days_later = today + timedelta(days=3)
        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)
        else:

            return self.dpd_to_be_called() \
                .filter(due_date__in=[one_days_later, three_days_later]) \
                .exclude(Q(due_date=three_days_later) & ~
                         Q(loan__application__product_line_id__in=ProductLineCodes.stl()))

    def dpd_groups_before_due(self, days, exclude_stl=True):
        today = timezone.localtime(timezone.now())
        days_later = today + timedelta(days=days)
        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)

        dpd_groups = self.dpd_to_be_called() \
            .filter(due_date=days_later) \

        if exclude_stl:
            dpd_groups = dpd_groups.exclude(
                loan__application__product_line_id__in=ProductLineCodes.stl())

        return dpd_groups

    def overdue_group_plus_with_range(self, range1, range2):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)
        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)
        else:
            return self.dpd_to_be_called().filter(due_date__range=[range2_ago, range1_ago])

    def list_bucket_group_with_range(self, range1, range2, is_intelix=False, only_base_query=False):
        today = timezone.localtime(timezone.now())

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called(
                is_intelix, only_base_query=only_base_query).filter(cdate=None)
        else:
            return self.dpd_to_be_called(
                is_intelix, only_base_query=only_base_query).determine_bucket_by_range([range1, range2])

    def get_bucket_1(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['to'])

        return self.filter(due_date__range=[range2_ago, range1_ago])

    def get_bucket_2(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_2_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_2_DPD['to'])

        return self.filter(due_date__range=[range2_ago, range1_ago])

    def get_bucket_3(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_3_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_3_DPD['to'])

        return self.filter(due_date__range=[range2_ago, range1_ago])

    def get_bucket_4(self):
        today = timezone.localtime(timezone.now()).date()
        range1_ago = today - timedelta(days=BucketConst.BUCKET_4_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_4_DPD['to'])
        release_date = datetime.strptime(BucketConst.EXCLUDE_RELEASE_DATE, '%Y-%m-%d')
        range1_ago_release_date = release_date - timedelta(days=91)
        range2_ago_release_date = release_date - timedelta(days=100)

        return self.filter(Q(due_date__range=[range2_ago, range1_ago])
                           | Q(due_date__range=[range2_ago_release_date, range1_ago_release_date])
                           & Q(ptp_date__isnull=False)
                           & Q(ptp_date__gte=today))

    def get_bucket_5(self):
        today = timezone.localtime(timezone.now()).date()
        due_date = today - timedelta(days=BucketConst.BUCKET_5_DPD)
        release_date = datetime.strptime(BucketConst.EXCLUDE_RELEASE_DATE, '%Y-%m-%d')
        range1_ago_release_date = release_date - timedelta(days=91)
        range2_ago_release_date = release_date - timedelta(days=100)

        return self.filter(due_date__lte=due_date).exclude(
            Q(due_date__range=[range2_ago_release_date, range1_ago_release_date])
            & Q(ptp_date__isnull=False)
            & Q(ptp_date__gte=today)
        )

    def determine_bucket_by_range(self, ranges):
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
            today = timezone.localtime(timezone.now())
            range1_ago = today - timedelta(days=ranges[0])
            range2_ago = today - timedelta(days=ranges[1])
            return self.filter(due_date__range=[range2_ago, range1_ago])

    def list_bucket_group_with_date(self, date):
        today = timezone.localtime(timezone.now())
        due_date = today - timedelta(days=date)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)
        else:
            return self.dpd_to_be_called().filter(due_date__lt=due_date)

    def list_bucket_group_before_due(self, due_date):
        return self.dpd_to_be_called()\
            .due_soon(due_in_days=due_date)\
            .filter(loan__loan_status=LoanStatusCodes.CURRENT)\
            .exclude(is_robocall_active=True,
                     is_success_robocall=True,
                     is_whatsapp_blasted=True)

    def list_bucket_group_robocall_before_due(self, due_date):
        return self.dpd_to_be_called()\
            .due_soon(due_in_days=due_date)\
            .filter(is_robocall_active=True,
                    loan__loan_status=LoanStatusCodes.CURRENT)\
            .exclude(is_success_robocall=True)

    def list_bucket_group_ptp_only_with_range(self, range1, range2):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 ptp_date__isnull=False,
                                                 cdate=None)
        else:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 ptp_date__isnull=False,
                                                 due_date__range=[range2_ago, range1_ago])

    def list_bucket_group_ptp_only_with_date(self, date):
        today = timezone.localtime(timezone.now())
        due_date = today - timedelta(days=date)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 ptp_date__isnull=False,
                                                 cdate=None)
        else:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 ptp_date__isnull=False,
                                                 due_date__lt=due_date)

    def list_bucket_group_wa_only_with_range(self, range1, range2):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 is_whatsapp=True,
                                                 cdate=None)
        else:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 is_whatsapp=True,
                                                 due_date__range=[range2_ago, range1_ago])

    def list_bucket_group_wa_only_with_date(self, date):
        today = timezone.localtime(timezone.now())
        due_date = today - timedelta(days=date)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 is_whatsapp=True,
                                                 cdate=None)
        else:
            return self.not_paid_active().filter(loan__is_ignore_calls=False,
                                                 is_whatsapp=True,
                                                 due_date__lt=due_date)

    def list_bucket_group_ignore_called_only_with_range(self, range1, range2):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.not_paid_active().filter(loan__is_ignore_calls=True, cdate=None)

        return self.not_paid_active()\
                   .filter(loan__is_ignore_calls=True,
                           due_date__range=[range2_ago, range1_ago])

    def list_bucket_group_ignore_called_only_with_date(self, date):
        today = timezone.localtime(timezone.now())
        due_date = today - timedelta(days=date)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.not_paid_active().filter(loan__is_ignore_calls=True,
                                                 cdate=None)

        return self.not_paid_active().filter(loan__is_ignore_calls=True,
                                             due_date__lt=due_date)

    def dpd_groups_minus5(self):
        return self.dpd_groups_before_due(5)

    def dpd_groups_minus3(self):
        return self.dpd_groups_before_due(3)

    def dpd_groups_minus1(self, exclude_stl=True):
        return self.dpd_groups_before_due(1, exclude_stl=exclude_stl)

    def list_bucket_3_group_ignore_called_only(self):
        return self.list_bucket_group_ignore_called_only_with_range(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
        )

    def list_bucket_4_group_ignore_called_only(self):
        return self.list_bucket_group_ignore_called_only_with_range(
            BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']
        )

    def list_bucket_5_group_ignore_called_only(self):
        return self.list_bucket_group_ignore_called_only_with_date(BucketConst.BUCKET_5_DPD)

    def list_bucket_1_group_ptp_only(self):
        return self.list_bucket_group_ptp_only_with_range(
            BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to']
        )

    def list_bucket_2_group_ptp_only(self):
        return self.list_bucket_group_ptp_only_with_range(
            BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']
        )

    def list_bucket_3_group_ptp_only(self):
        return self.list_bucket_group_ptp_only_with_range(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
        )

    def list_bucket_4_group_ptp_only(self):
        return self.list_bucket_group_ptp_only_with_range(
            BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']
        )

    def list_bucket_5_group_ptp_only(self):
        return self.list_bucket_group_ptp_only_with_date(100)

    def list_bucket_1_group_wa_only(self):
        return self.list_bucket_group_wa_only_with_range(
            BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to']
        )

    def list_bucket_2_group_wa_only(self):
        return self.list_bucket_group_wa_only_with_range(
            BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']
        )

    def list_bucket_3_group_wa_only(self):
        return self.list_bucket_group_wa_only_with_range(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
        )

    def list_bucket_4_group_wa_only(self):
        return self.list_bucket_group_wa_only_with_range(
            BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']
        )

    def list_bucket_5_group_wa_only(self):
        return self.list_bucket_group_wa_only_with_date(BucketConst.BUCKET_5_DPD)

    def bucket_list_t_minus_5_robo(self):
        return self.list_bucket_group_robocall_before_due(5)

    def bucket_list_t_minus_3_robo(self):
        return self.list_bucket_group_robocall_before_due(3)

    def bucket_list_t_minus_1(self):
        return self.list_bucket_group_before_due(1)

    def bucket_list_t_minus_3(self):
        return self.list_bucket_group_before_due(3)

    def bucket_list_t_minus_5(self):
        return self.list_bucket_group_before_due(5)

    def bucket_list_t1_to_t4(self):
        return self.list_bucket_group_with_range(1, 4)

    def bucket_list_t5_to_t10(self):
        return self.list_bucket_group_with_range(5, 10)

    def bucket_list_t11_to_t25(self):
        return self.list_bucket_group_with_range(11, 25)

    def bucket_list_t26_to_t40(self):
        return self.list_bucket_group_with_range(26, 40)

    def bucket_list_t11_to_t40(self, is_intelix=False, only_base_query=False):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to'], is_intelix,
            only_base_query=only_base_query
        ).exclude(loan__ever_entered_B5=True)

    def bucket_list_t41_to_t55(self):
        return self.list_bucket_group_with_range(41, 55)

    def bucket_list_t56_to_t70(self):
        return self.list_bucket_group_with_range(56, 70)

    def bucket_list_t41_to_t70(self, is_intelix=False, only_base_query=False):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to'], is_intelix,
            only_base_query=only_base_query
        ).exclude(loan__ever_entered_B5=True)

    def bucket_list_t71_to_t85(self):
        return self.list_bucket_group_with_range(71, 85)

    def bucket_list_t86_to_t100(self):
        return self.list_bucket_group_with_range(86, 100)

    def bucket_list_t71_to_t90(self, is_intelix=False, only_base_query=False):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_4_DPD['to'], BucketConst.BUCKET_4_DPD['from'], is_intelix,
            only_base_query=only_base_query
        ).exclude(loan__ever_entered_B5=True)

    def bucket_list_t16_to_t29(self):
        return self.list_bucket_group_with_range(16, 29)

    def bucket_list_t30_to_t44(self):
        return self.list_bucket_group_with_range(30, 44)

    def bucket_list_t45_to_t59(self):
        return self.list_bucket_group_with_range(45, 59)

    def bucket_list_t60_to_t74(self):
        return self.list_bucket_group_with_range(60, 74)

    def bucket_list_t75_to_t89(self):
        return self.list_bucket_group_with_range(75, 89)

    def bucket_list_t90_to_t119(self):
        return self.list_bucket_group_with_range(90, 119)

    def bucket_list_t120_to_t179(self):
        return self.list_bucket_group_with_range(120, 179)

    def bucket_list_t5_to_t30(self):
        return self.list_bucket_group_with_range(5, 30)

    def bucket_1_plus(self, range1, range2, loan_ids, only_base_query=False):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)
        if only_base_query:
            return self.filter(
                loan__ever_entered_B5=False,
                payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                due_date__range=[range2_ago, range1_ago])

        return self.filter(is_collection_called=False,
                           loan__is_ignore_calls=False,
                           is_whatsapp=False,
                           loan__loan_status__gte=LoanStatusCodes.CURRENT,
                           loan__loan_status__lte=LoanStatusCodes.LOAN_30DPD,
                           loan__ever_entered_B5=False,
                           payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                           due_date__range=[range2_ago, range1_ago])\
            .exclude(loan_id__in=loan_ids)

    def bucket_1_t1_t4(self, loan_ids):
        return self.bucket_1_plus(1, 4, loan_ids)

    def bucket_1_t5_t10(self, loan_ids):
        return self.bucket_1_plus(5, 10, loan_ids)

    def bucket_1_t1_t10(self, loan_ids, only_base_query=False):
        return self.bucket_1_plus(
            BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to'], loan_ids,
            only_base_query=only_base_query
        )

    def bucket_1_minus(self, days, loan_ids, exclude_stl=True):
        today = timezone.localtime(timezone.now())
        days_later = today + timedelta(days=days)

        if exclude_stl:
            return self.filter(is_collection_called=False,
                               ptp_date__isnull=True,
                               loan__is_ignore_calls=False,
                               is_whatsapp=False,
                               loan__loan_status__gte=LoanStatusCodes.CURRENT,
                               loan__loan_status__lte=LoanStatusCodes.LOAN_30DPD,
                               payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                               due_date=days_later, loan__ever_entered_B5=False)\
                .exclude(loan__application__product_line_id__in=ProductLineCodes.stl())\
                .exclude(loan_id__in=loan_ids)
        else:
            return self.filter(is_collection_called=False,
                               ptp_date__isnull=True,
                               loan__is_ignore_calls=False,
                               is_whatsapp=False,
                               loan__loan_status__gte=LoanStatusCodes.CURRENT,
                               loan__loan_status__lte=LoanStatusCodes.LOAN_30DPD,
                               payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                               due_date=days_later, loan__ever_entered_B5=False)\
                .exclude(loan_id__in=loan_ids)

    def bucket_1_t_minus_5(self, loan_ids):
        return self.bucket_1_minus(5, loan_ids)

    def bucket_1_t_minus_3(self, loan_ids):
        return self.bucket_1_minus(3, loan_ids)

    def bucket_1_t_minus_1(self, loan_ids):
        return self.bucket_1_minus(1, loan_ids)

    def bucket_1_t_minus_2(self, loan_ids):
        return self.bucket_1_minus(2, loan_ids)

    def bucket_cootek(self, excluded_loan_ids, exclude_stl=False, dpd=None):
        today = timezone.localtime(timezone.now())

        qs = self.filter(is_collection_called=False,
                         ptp_date__isnull=True,
                         loan__is_ignore_calls=False,
                         is_whatsapp=False,
                         loan__loan_status__gte=LoanStatusCodes.CURRENT,
                         loan__loan_status__lte=LoanStatusCodes.LOAN_30DPD,
                         payment_status__lt=PaymentStatusCodes.PAID_ON_TIME) \
            .exclude(loan_id__in=excluded_loan_ids)

        if exclude_stl:
            qs = qs.exclude(loan__application__product_line_id__in=ProductLineCodes.stl())
        if dpd is not None:
            days_later = today + timedelta(days=-1 * dpd)
            qs = qs.filter(due_date=days_later)

        return qs

    def bucket_1_t0(self, loan_ids, exclude_stl=True):
        today = timezone.localtime(timezone.now())

        if exclude_stl:
            return self.filter(is_collection_called=False,
                               ptp_date__isnull=True,
                               loan__is_ignore_calls=False,
                               is_whatsapp=False,
                               loan__loan_status=LoanStatusCodes.CURRENT,
                               payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                               due_date=today, loan__ever_entered_B5=False) \
                .exclude(loan__application__product_line_id__in=ProductLineCodes.stl()) \
                .exclude(loan_id__in=loan_ids)
        else:
            return self.filter(is_collection_called=False,
                               ptp_date__isnull=True,
                               loan__is_ignore_calls=False,
                               is_whatsapp=False,
                               loan__loan_status=LoanStatusCodes.CURRENT,
                               payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                               due_date=today, loan__ever_entered_B5=False) \
                .exclude(loan_id__in=loan_ids)

    def bucket_1_wa(self, loan_ids):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=1)
        range2_ago = today - timedelta(days=10)

        return self.filter(loan__loan_status__gte=LoanStatusCodes.CURRENT,
                           loan__loan_status__lte=LoanStatusCodes.LOAN_30DPD,
                           payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                           loan__is_ignore_calls=False,
                           is_whatsapp=True,
                           due_date__range=[range2_ago, range1_ago])\
            .exclude(loan_id__in=loan_ids)

    def bucket_1_ptp(self, loan_ids):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=1)
        range2_ago = today - timedelta(days=10)

        return self.filter(loan__loan_status__gte=LoanStatusCodes.CURRENT,
                           loan__loan_status__lte=LoanStatusCodes.LOAN_30DPD,
                           payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                           loan__is_ignore_calls=False,
                           ptp_date__isnull=False,
                           due_date__range=[range2_ago, range1_ago])\
            .exclude(loan_id__in=loan_ids)

    def bucket_1_list(self):
        today = timezone.localtime(timezone.now())
        five_days_later = today + timedelta(days=5)
        three_days_later = today + timedelta(days=3)
        one_days_later = today + timedelta(days=1)
        bucket_t0_to_t10 = self.list_bucket_group_with_range(0, 10)

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            bucket_1_list_query = (self.dpd_to_be_called().filter(cdate=None) | bucket_t0_to_t10
                                   | self.list_bucket_1_group_ptp_only() | self.list_bucket_1_group_wa_only())

            return bucket_1_list_query

        dpd_minus5and3and1 = self.dpd_to_be_called() \
            .filter(due_date__in=[one_days_later, three_days_later, five_days_later]) \
            .exclude(loan__application__product_line_id__in=ProductLineCodes.stl())

        bucket_1_list_query = (dpd_minus5and3and1 | bucket_t0_to_t10
                               | self.list_bucket_1_group_ptp_only() | self.list_bucket_1_group_wa_only())

        return bucket_1_list_query.exclude(loan__ever_entered_B5=True)

    def bucket_2_list(self):
        bucket_2_list_query = (self.list_bucket_group_with_range(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
        ) | self.list_bucket_2_group_ptp_only() | self.list_bucket_2_group_wa_only())

        return bucket_2_list_query.exclude(loan__ever_entered_B5=True)

    def bucket_3_list(self):
        bucket_3_list_query = (self.list_bucket_group_with_range(BucketConst.BUCKET_3_DPD['from'],
                                                                 BucketConst.BUCKET_3_DPD['to']) |
                               self.list_bucket_3_group_ptp_only()
                               | self.list_bucket_3_group_ignore_called_only()
                               | self.list_bucket_3_group_wa_only())

        return bucket_3_list_query.exclude(loan__ever_entered_B5=True)

    def bucket_4_list(self):
        bucket_4_list_query = (self.list_bucket_group_with_range(BucketConst.BUCKET_4_DPD['from'],
                                                                 BucketConst.BUCKET_4_DPD['to']) |
                               self.list_bucket_4_group_ptp_only()
                               | self.list_bucket_4_group_ignore_called_only()
                               | self.list_bucket_4_group_wa_only())
        return bucket_4_list_query.exclude(loan__ever_entered_B5=True)

    def bucket_5_list(self):
        bucket_5_list_query = self.dpd_to_be_called().filter(loan__ever_entered_B5=True)
        return bucket_5_list_query

    def bucket_list_t0(self):
        return self.list_bucket_group_with_date(0)

    def bucket_list_t30plus(self):
        return self.list_bucket_group_with_date(30)

    def bucket_list_t180plus(self):
        return self.list_bucket_group_with_date(180)

    def bucket_whatsapp(self):
        return self.list_bucket_group_wa_only_with_range(1, 100)

    def bucket_whatsapp_blasted(self):
        return self.not_paid_active().filter(
            is_whatsapp_blasted=True,
            payment_status__lte=PaymentStatusCodes.PAYMENT_DUE_TODAY)

    def bucket_ptp(self):
        return self.list_bucket_group_ptp_only_with_range(1, 100)

    def bucket_ignore_called(self):
        return self.list_bucket_group_ignore_called_only_with_range(41, 100)

    def due_group0(self):
        today = timezone.localtime(timezone.now())
        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)
        else:
            return self.dpd_to_be_called().filter(due_date=today)

    def overdue_group_plus30(self):
        today = timezone.localtime(timezone.now())
        thirty_days_ago = today - timedelta(days=30)
        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)
        else:
            return self.dpd_to_be_called().filter(due_date__lt=thirty_days_ago)

    def overdue_group_plus180(self):
        today = timezone.localtime(timezone.now())
        one_hundred_eighty_one_days_ago = today - timedelta(days=181)
        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called().filter(cdate=None)
        else:
            return self.dpd_to_be_called().filter(due_date__lt=one_hundred_eighty_one_days_ago)

    def uncalled_group(self, from_task=False):
        today = timezone.localtime(timezone.now())
        one_days_later = today + timedelta(days=1)
        five_days_later = today + timedelta(days=5)
        three_days_later = today + timedelta(days=3)
        if from_task or today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.dpd_to_be_called()\
                .filter(Q(due_date__lte=today)
                        | Q(due_date__in=[one_days_later, three_days_later, five_days_later]))\
                .exclude(Q(due_date=three_days_later) & ~
                         Q(loan__application__product_line_id__in=ProductLineCodes.stl()))
        else:
            return self.dpd_uncalled()\
                .filter(Q(due_date__lte=today)
                        | Q(due_date__in=[one_days_later, three_days_later, five_days_later]))\
                .exclude(Q(due_date=three_days_later) & ~
                         Q(loan__application__product_line_id__in=ProductLineCodes.stl()))

    def grab_0plus(self):
        six_week_ago = date.today() - timedelta(weeks=6)
        fund_disbursal_successful = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        return self.not_paid_active()\
                   .filter(
            loan__application__product_line_id__in=ProductLineCodes.grab(),
            loan__application__applicationhistory__status_new=fund_disbursal_successful,
            loan__application__applicationhistory__cdate__lte=six_week_ago)

    def get_grab_payments(self):
        return self.not_paid().filter(
            loan__account__account_lookup__name=WorkflowConst.GRAB,
        )

    def mtl_product_payments(self):
        return self.filter(
            loan__application__product_line__product_line_code__in=ProductLineCodes.mtl()
        )

    def duration(self, number, op):
        if op == 'gt':
            return self.annotate(pmt_number=Case(
                When(loan__loan_duration__gte=5, then=Value(3)),
                When(loan__loan_duration__lte=4, then=Value(2)),
                output_field=IntegerField())
            ).filter(Q(payment_number__gt=F('loan__loan_duration') - F('pmt_number')))
        if op == 'lt':
            return self.filter(Q(payment_number__lt=F('loan__loan_duration') - number))
        if op == 'eq':
            return self.filter(Q(payment_number=F('loan__loan_duration') - number))

    def get_bucket_5(self):
        # todo add filtering
        today = timezone.localtime(timezone.now()).date()
        due_date = today - timedelta(days=91)
        release_date = datetime.strptime('2020-09-1', '%Y-%m-%d')
        range1_ago_release_date = release_date - timedelta(days=91)
        range2_ago_release_date = release_date - timedelta(days=100)

        return self.filter(due_date__lte=due_date).exclude(
            Q(due_date__range=[range2_ago_release_date, range1_ago_release_date])
            & Q(ptp_date__isnull=False)
            & Q(ptp_date__gte=today)
        )

    # only for dpd < 91
    def get_sub_bucket_5_1_special_case(self, dpd_end):
        today = timezone.localtime(timezone.now()).date()
        end_range = today - timedelta(days=dpd_end)
        return self.filter(due_date__gte=end_range, loan__ever_entered_B5=True)

    def get_sub_bucket_5_by_range(self, dpd_start=None, dpd_end=None):
        today = timezone.localtime(timezone.now()).date()
        filter_range_ = dict(loan__ever_entered_B5=True)
        range1_ago = today - timedelta(days=dpd_start)
        if dpd_start and dpd_end:
            range2_ago = today - timedelta(days=dpd_end)
            filter_range_['due_date__range'] = [range2_ago, range1_ago]

        if dpd_start and not dpd_end:
            filter_range_['due_date'] = range1_ago

        return self.get_bucket_5().filter(**filter_range_)


class PaymentManager(GetInstanceMixin, JuloModelManager):
    def normal(self):
        return self.get_queryset().exclude(
            loan__loan_status=LoanStatusCodes.RENEGOTIATED).exclude(is_restructured=True)

    def get_queryset(self):
        return PaymentQuerySet(self.model)

    def renegotiated(self):
        return self.get_queryset().filter(
            loan__loan_status=LoanStatusCodes.RENEGOTIATED)

    def by_loan(self, loan):
        return self.get_queryset().by_loan(loan)

    def paid(self):
        return self.normal().paid()

    def not_paid(self):
        return self.normal().not_paid()

    def not_paid_active(self):
        return self.normal().not_paid_active()

    def due_today(self):
        return self.normal().due_today()

    def not_paid_active_julo_one(self):
        return self.normal().not_paid_active_julo_one()

    def not_paid_active_overdue(self):
        return self.normal().overdue()\
            .exclude(loan__loan_status=LoanStatusCodes.SELL_OFF)

    def due_soon(self, due_in_days):
        return self.normal().due_soon(due_in_days=due_in_days)

    def dpd(self, days_pass_due):
        return self.normal().dpd(days_pass_due)

    def get_payments_on_wa_bucket(self):
        return self.filter(is_whatsapp=True)

    def autodialer_uncalled_payment(self, status, locked_list):
        today = timezone.localtime(timezone.now())
        if status == 531:
            row = None
            qs = self.normal().dpd_groups_minus5and3and1()
            qs1 = qs.exclude(id__in=locked_list).order_by("-due_date")
            if qs1:
                for payment_row in qs1:
                    autodial_session = payment_row.paymentautodialersession_set.last()
                    if autodial_session:
                        if autodial_session.dpd_code < 0 and \
                                autodial_session.dpd_code != (today.date() - payment_row.due_date).days:
                            row = payment_row
                    else:
                        row = payment_row
                    if row:
                        break

        elif status == 0:
            qs = self.normal().due_group0()
            qs1 = qs.filter(paymentautodialersession__isnull=True).exclude(
                id__in=locked_list).order_by("-due_date")
            row = qs1.first() if qs1 else None
            if not row:
                qs2 = qs.filter(paymentautodialersession__dpd_code__lte=0).exclude(id__in=locked_list).\
                    order_by("-due_date").distinct()
                for qrow in qs2:
                    if (len(qrow.paymentautodialersession_set.all()) < 4):
                        row = qrow
                        break
        return row

    def autodialer_recalled_payment(self, status, locked_list):
        qs = self.normal().due_group0()
        current_time = timezone.now()
        qs = qs.filter(Q(paymentautodialersession__dpd_code=status)
                       & (
            Q(paymentautodialersession__next_session_ts__lte=current_time)
            | Q(paymentautodialersession__next_session_ts__isnull=True)
        )).exclude(id__in=locked_list)
        qs = qs.order_by("-due_date")

        if qs:
            return qs.first()
        else:
            return None

    def failed_robocall_payments_with_date(self, product_codes, due_start_date, due_end_date):
        return self.normal()\
            .by_product_line_codes(product_codes)\
            .not_paid_active()\
            .filter(
            loan__loan_status=LoanStatusCodes.CURRENT,
            due_date__range=[due_start_date, due_end_date])\
            .exclude(Q(is_success_robocall=True) | Q(is_success_robocall__isnull=True)
                     | Q(is_collection_called=True))

    def failed_robocall_payments_with_date_and_wib_localtime(self, product_codes, due_start_date, due_end_date):
        return self.failed_robocall_payments_with_date(product_codes, due_start_date, due_end_date)\
            .filter(loan__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE)

    def failed_robocall_payments_with_date_and_wita_localtime(self, product_codes, due_start_date, due_end_date):
        return self.failed_robocall_payments_with_date(product_codes, due_start_date, due_end_date)\
            .filter(loan__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE)

    def failed_robocall_payments_with_date_and_wit_localtime(self, product_codes, due_start_date, due_end_date):
        return self.failed_robocall_payments_with_date(product_codes, due_start_date, due_end_date)\
            .filter(loan__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE)

    def failed_robocall_payments(self, product_codes):
        today = timezone.localtime(timezone.now()).date()
        dayplus3 = today + relativedelta(days=3)
        dayplus5 = today + relativedelta(days=5)
        qs = self.normal()\
                 .by_product_line_codes(product_codes)\
                 .not_paid_active()\
                 .filter(loan__loan_status=LoanStatusCodes.CURRENT)

        return qs.filter(Q(due_date=dayplus3)
                         | Q(due_date=dayplus5)
                         ).exclude(Q(is_success_robocall=True)
                                   | Q(is_collection_called=True))

    def failed_automated_robocall_payments(self, product_codes, dpd):
        today = timezone.localtime(timezone.now()).date()
        filter_day = None
        if dpd > 0:
            filter_day = today - relativedelta(days=abs(dpd))
        else:
            filter_day = today + relativedelta(days=abs(dpd))

        qs = self.normal()\
                 .by_product_line_codes(product_codes)\
                 .not_paid_active()

        return qs.filter(due_date=filter_day).exclude(Q(is_success_robocall=True)
                                                      | Q(is_collection_called=True))

    def tobe_robocall_payments(self, product_codes, dpd_list):
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

    def renegotiated_unpaid_active(self):
        return self.renegotiate().not_paid_active()

    def status_tobe_update(self):
        today = timezone.localtime(timezone.now()).date()
        dpd_1 = today - relativedelta(days=1)
        dpd_5 = today - relativedelta(days=5)
        dpd_30 = today - relativedelta(days=30)
        dpd_60 = today - relativedelta(days=60)
        dpd_90 = today - relativedelta(days=90)
        dpd_120 = today - relativedelta(days=120)
        dpd_150 = today - relativedelta(days=150)
        dpd_180 = today - relativedelta(days=180)
        qs = self.normal().not_paid_active().filter(
            (
                Q(due_date=today)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_DUE_TODAY)
            )
            | (
                Q(due_date__lte=dpd_1)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_1DPD)
            )
            | (
                Q(due_date__lte=dpd_5)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_5DPD)
            )
            | (
                Q(due_date__lte=dpd_30)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_30DPD)
            )
            | (
                Q(due_date__lte=dpd_60)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_60DPD)
            )
            | (
                Q(due_date__lte=dpd_90)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_90DPD)
            )
            | (
                Q(due_date__lte=dpd_120)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_120DPD)
            )
            | (
                Q(due_date__lte=dpd_150)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_150DPD)
            )
            | (
                Q(due_date__lte=dpd_180)
                & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_180DPD)
            )
        )
        return qs

    def status_tobe_update_grab(self, processed_day_gap_from_halt=None,
                                processing_resume_dates=None, is_q_query=False):
        """
            This is the function which is used to get the
            gap_in_days: this field is to make sure to select the appropriate payment
                         provided loan has been halted. Should always be positive value.
                         this will reduce from the original due_date

            eg: orginal_due_date = 5th Jan and gap_in_days = 4,
                new_due_date = 1st Jan

            NOTE:
                Please make sure to filter out the loan_id's outside this
                manager else will cause problems.

        """
        if processing_resume_dates is None:
            processing_resume_dates = []
        if processed_day_gap_from_halt is None:
            processed_day_gap_from_halt = []
        if not processing_resume_dates:
            today_date = timezone.localtime(timezone.now()).date()
            dpd_1 = today_date - relativedelta(days=1)
            dpd_5 = today_date - relativedelta(days=5)
            dpd_30 = today_date - relativedelta(days=30)
            dpd_60 = today_date - relativedelta(days=60)
            dpd_90 = today_date - relativedelta(days=90)
            dpd_120 = today_date - relativedelta(days=120)
            dpd_150 = today_date - relativedelta(days=150)
            dpd_180 = today_date - relativedelta(days=180)
            if not is_q_query:
                qs = self.normal().not_paid_active().filter(
                    (
                        Q(due_date=today_date)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_DUE_TODAY)
                    )
                    | (
                        Q(due_date__lte=dpd_1)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_1DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_5)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_5DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_30)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_30DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_60)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_60DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_90)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_90DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_120)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_120DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_150)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_150DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_180)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_180DPD)
                    )
                )
            else:
                qs = (
                    (
                        Q(due_date=today_date)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_DUE_TODAY)
                    )
                    | (
                        Q(due_date__lte=dpd_1)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_1DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_5)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_5DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_30)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_30DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_60)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_60DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_90)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_90DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_120)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_120DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_150)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_150DPD)
                    )
                    | (
                        Q(due_date__lte=dpd_180)
                        & Q(payment_status_id__lt=PaymentStatusCodes.PAYMENT_180DPD)
                    )
                )
        else:
            today_date = timezone.localtime(timezone.now()).date()
            dpd_1 = today_date - relativedelta(days=1)
            dpd_5 = today_date - relativedelta(days=5)
            dpd_30 = today_date - relativedelta(days=30)
            dpd_60 = today_date - relativedelta(days=60)
            dpd_90 = today_date - relativedelta(days=90)
            dpd_120 = today_date - relativedelta(days=120)
            dpd_150 = today_date - relativedelta(days=150)
            dpd_180 = today_date - relativedelta(days=180)
            dates = [today_date, dpd_1, dpd_5, dpd_30, dpd_60, dpd_90, dpd_120, dpd_150, dpd_180]
            for account_idx, account_resume_date in enumerate(processing_resume_dates):
                for idx, starting_date in enumerate(dates):
                    if starting_date < datetime.strptime(account_resume_date, '%Y-%m-%d').date():
                        starting_date = starting_date + timedelta(
                            days=processed_day_gap_from_halt[account_idx])
                        dates[idx] = starting_date

            qs = Q()
            for idx, date_check in enumerate(dates):
                if idx == 0:
                    payment_status_code = PaymentStatusCodes.PAYMENT_DUE_TODAY
                elif idx == 1:
                    payment_status_code = PaymentStatusCodes.PAYMENT_1DPD
                elif idx == 2:
                    payment_status_code = PaymentStatusCodes.PAYMENT_5DPD
                elif idx == 3:
                    payment_status_code = PaymentStatusCodes.PAYMENT_30DPD
                elif idx == 4:
                    payment_status_code = PaymentStatusCodes.PAYMENT_60DPD
                elif idx == 5:
                    payment_status_code = PaymentStatusCodes.PAYMENT_90DPD
                elif idx == 6:
                    payment_status_code = PaymentStatusCodes.PAYMENT_120DPD
                elif idx == 7:
                    payment_status_code = PaymentStatusCodes.PAYMENT_150DPD
                else:
                    payment_status_code = PaymentStatusCodes.PAYMENT_180DPD
                if idx != 0:
                    sub_query = (Q(due_date__lte=date_check) & Q(
                        payment_status_id__lt=payment_status_code))
                else:
                    sub_query = (Q(due_date=date_check) & Q(
                        payment_status_id__lt=payment_status_code))
                qs = qs | sub_query
            if not is_q_query:
                qs = self.normal().not_paid_active().filter(qs)
        return qs

    def is_not_paid_active_with_refinancing(self) -> bool:
        qs = (
            self.filter(loan__loan_status__gte=LoanStatusCodes.CURRENT)
            .exclude(loan__loan_status__in=[LoanStatusCodes.INACTIVE, LoanStatusCodes.DRAFT])
            .exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.grab())
        )
        return qs.filter(
            payment_status__lt=PaymentStatusCodes.PAID_ON_TIME, loan__is_restructured=True
        ).exists()


class Payment(TimeStampedModel):

    id = models.AutoField(db_column='payment_id', primary_key=True)

    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    payment_status = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='payment_status_code')

    payment_number = models.IntegerField()
    due_date = models.DateField(null=True, db_index=True)
    ptp_date = models.DateField(blank=True, null=True)
    ptp_robocall_template = models.ForeignKey('RobocallTemplate',
                                              models.DO_NOTHING,
                                              db_column='robocall_template_id',
                                              null=True,
                                              blank=True)
    ptp_robocall_phone_number = models.CharField(
        max_length=18, blank=True, null=True, validators=[ascii_validator])
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
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment', models.DO_NOTHING, db_column='account_payment_id',
        blank=True, null=True
    )

    tracker = FieldTracker(fields=['payment_status_id', 'paid_amount'])

    objects = PaymentManager()

    class Meta(object):
        db_table = 'payment'

    GRACE_PERIOD_DAYS = 5
    DUE_SOON_DAYS = 3

    # Temporary function display correct due amount on app
    # Should be only used on juloserver.apiv1.serializers.PaymentSerializer
    # DERPRECATED as soon as frontend start to use the original_due_amount property
    def convert_interest_to_round_sum(self):
        orig_due_unrounded = self.installment_principal + self.installment_interest
        return self.installment_interest - (orig_due_unrounded % 1000)

    @property
    def original_due_amount(self):
        return self.installment_principal + self.installment_interest

    @property
    def status(self):
        return self.payment_status_id

    @property
    def is_overdue(self):
        status_code = self.payment_status.status_code
        overdue = status_code > StatusLookup.PAYMENT_DUE_TODAY_CODE \
            and status_code < StatusLookup.PAID_ON_TIME_CODE
        logger.debug({'overdue': overdue, 'status': self.payment_status})
        return overdue

    @property
    def grace_date(self):
        grace_date = self.due_date + timedelta(days=4)
        return grace_date

    @property
    def paid_late_days(self):
        if self.due_date is None or self.paid_date is None:
            days = 0
        else:
            time_delta = self.paid_date - self.due_date
            days = time_delta.days
        logger.debug({'paid_late_days': days})
        return days

    @property
    def is_paid(self):
        return self.payment_status_id >= PaymentStatusCodes.PAID_ON_TIME

    @property
    def due_late_days(self):
        """
        Negative value means it's not due yet. 0 means due today. Positive
        value means due is late.
        """
        if not self.due_date or self.is_paid:
            days = 0
        else:
            time_delta = date.today() - self.due_date
            days = time_delta.days
        logger.debug({
            'due_date': self.due_date,
            'due_late_days': days
        })
        return days

    @property
    def due_late_days_formatted(self):
        from babel.dates import format_date
        date = format_date(self.due_date, 'dd MMMM yyyy', locale='id_ID')
        return date

    @property
    def payment_status_label(self):
        return StatusLookup.STATUS_LABEL_BAHASA.get(self.payment_status.status_code, '')

    @property
    def notification_due_date(self):
        if self.ptp_date:
            return self.ptp_date
        else:
            return self.due_date

    @property
    def remaining_principal(self):
        return self.installment_principal - self.paid_principal

    @property
    def remaining_interest(self):
        return self.installment_interest - self.paid_interest

    @property
    def remaining_late_fee(self):
        return self.late_fee_amount - self.paid_late_fee

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

    @property
    def not_paid_active_payment_number_list(self):
        return Payment.objects.by_loan(self.loan).not_paid_active().order_by(
            'payment_number').values_list('payment_number', flat=True)

    @property
    def ptp_late_days(self):
        """
        Negative value means it's not ptp due yet. 0 means ptp due today. Positive
        value means ptp due is late.
        """
        if not self.ptp_date or self.is_paid:
            return None

        time_delta = date.today() - self.ptp_date
        return time_delta.days

    @property
    def bucket_number(self):
        if self.due_late_days < 1:
            return 0

        if self.due_late_days <= 10:
            return 1

        if self.due_late_days <= 40:
            return 2

        if self.due_late_days <= 70:
            return 3

        if self.due_late_days <= 90:
            return 4

        return 5

    @property
    def bucket_number_special_case(self):
        if self.loan.ever_entered_B5:
            return 5

        if self.due_late_days < 1:
            return 0

        if self.due_late_days <= 10:
            return 1

        if self.due_late_days <= 40:
            return 2

        if self.due_late_days <= 70:
            return 3

        if self.due_late_days <= 90:
            return 4

        return 0

    @property
    def is_julo_one_payment(self):
        if self.loan.product.product_line.product_line_type == 'J1':
            if self.payment_status_id >= 320:
                if self.account_payment:
                    return True
                else:
                    return False
            return True
        return False

    @property
    def is_julo_starter_payment(self):
        if self.loan.product.product_line.product_line_type == 'J-STARTER':
            return True
        return False

    @property
    def get_dpd(self):
        """
        Negative value means it's not due yet. 0 means due today. Positive
        value means due is late.
        """
        if not self.due_date or self.is_paid:
            days = 0
        else:
            time_delta = date.today() - self.due_date
            days = time_delta.days
        logger.debug({
            'due_date': self.due_date,
            'dpd': days
        })
        return days

    @property
    def due_late_days_grab(self):
        """
        Negative value means it's not due yet. 0 means due today. Positive
        value means due is late.
        This function is to be used only by Grab.
        This property is different to get_grab_dpd due to the fact that the
        data is fetched from db rather than prefetched data. Since this is
        used in other areas.
        """
        days = 0
        if self.due_date or not self.is_paid:
            loan_account_halt_info = list()
            loan = self.loan
            grab_loan_data = loan.grabloandata_set.only(
                'pk', 'account_halt_info', 'account_halt_status'
            ).last()
            if not grab_loan_data:
                return
            account_halt_info = grab_loan_data.account_halt_info
            account_halt_status = grab_loan_data.account_halt_status
            base_date = date.today()
            time_delta = base_date - self.due_date
            if account_halt_info:
                if isinstance(account_halt_info, str):
                    loaded_account_halt_info = json.loads(account_halt_info)
                else:
                    loaded_account_halt_info = account_halt_info
                for account_halt_details in loaded_account_halt_info:
                    account_halt_date = datetime.strptime(
                        account_halt_details['account_halt_date'], '%Y-%m-%d').date()
                    account_resume_date = datetime.strptime(
                        account_halt_details['account_resume_date'], '%Y-%m-%d').date()
                    account_halt_dict = {
                        'account_halt_date': account_halt_date,
                        'account_resume_date': account_resume_date
                    }
                    loan_account_halt_info.append(account_halt_dict)

                if loan.loan_status_id == LoanStatusCodes.HALT and loan_account_halt_info:
                    last_loan_halted_detail = loan_account_halt_info[-1]
                    if account_halt_status == AccountHaltStatus.HALTED:
                        base_date = last_loan_halted_detail['account_halt_date']
                    elif account_halt_status == AccountHaltStatus.HALTED_UPDATED_RESUME_LOGIC:
                        if self.due_date < \
                                last_loan_halted_detail['account_resume_date']:
                            base_date = last_loan_halted_detail['account_halt_date']
                        else:
                            base_date = last_loan_halted_detail['account_resume_date']
                    if last_loan_halted_detail['account_halt_date'] <= self.due_date < \
                            last_loan_halted_detail['account_resume_date']:
                        oldest_payment = loan.grab_oldest_unpaid_payments[0]
                        if self == oldest_payment:
                            time_delta = base_date - self.due_date
                        else:
                            time_delta = timedelta(
                                days=loan.grab_oldest_unpaid_payments[0].get_grab_dpd)
                    elif self.due_date >= \
                            last_loan_halted_detail['account_resume_date']:
                        time_delta = base_date - self.due_date
                    else:
                        days_gap = 0
                        for account_halt_data in loan_account_halt_info[:-1]:
                            if self.due_date < account_halt_data['account_halt_date']:
                                days_gap += (account_halt_data['account_resume_date']
                                             - account_halt_data['account_halt_date']).days
                        time_delta = (base_date - self.due_date) - timedelta(days=days_gap)
                else:
                    days_gap = 0
                    for account_halt_data in loan_account_halt_info:
                        if self.due_date < account_halt_data['account_halt_date']:
                            days_gap += (account_halt_data['account_resume_date']
                                         - account_halt_data['account_halt_date']).days
                    time_delta = (base_date - self.due_date) - timedelta(days=days_gap)

            days = time_delta.days
        logger.debug({
            'due_date': self.due_date,
            'dpd': days
        })
        return days

    @property
    def get_grab_dpd(self):
        """
        Negative value means it's not due yet. 0 means due today. Positive
        value means due is late.
        """
        days = 0
        if self.due_date or not self.is_paid:
            loan_account_halt_info = list()
            loan = self.loan
            grab_loan_data = loan.grab_loan_data_set
            account_halt_info = None
            account_halt_status = None
            if grab_loan_data:
                first_grab_loan_data = grab_loan_data[0]
                account_halt_info = first_grab_loan_data.account_halt_info
                account_halt_status = first_grab_loan_data.account_halt_status
            base_date = date.today()
            time_delta = base_date - self.due_date
            if account_halt_info:
                if isinstance(account_halt_info, str):
                    loaded_account_halt_info = json.loads(account_halt_info)
                else:
                    loaded_account_halt_info = account_halt_info

                for account_halt_details in loaded_account_halt_info:
                    account_halt_date = datetime.strptime(
                        account_halt_details['account_halt_date'], '%Y-%m-%d').date()
                    account_resume_date = datetime.strptime(
                        account_halt_details['account_resume_date'], '%Y-%m-%d').date()
                    account_halt_dict = {
                        'account_halt_date': account_halt_date,
                        'account_resume_date': account_resume_date
                    }
                    loan_account_halt_info.append(account_halt_dict)

                if loan.loan_status_id == LoanStatusCodes.HALT and loan_account_halt_info:
                    last_loan_halted_detail = loan_account_halt_info[-1]
                    if account_halt_status == AccountHaltStatus.HALTED:
                        base_date = last_loan_halted_detail['account_halt_date']
                    elif account_halt_status == AccountHaltStatus.HALTED_UPDATED_RESUME_LOGIC:
                        if self.due_date < \
                                last_loan_halted_detail['account_resume_date']:
                            base_date = last_loan_halted_detail['account_halt_date']
                        else:
                            base_date = last_loan_halted_detail['account_resume_date']
                    if last_loan_halted_detail['account_halt_date'] <= self.due_date < \
                            last_loan_halted_detail['account_resume_date']:
                        oldest_payment = loan.grab_oldest_unpaid_payments[0]
                        if self == oldest_payment:
                            time_delta = base_date - self.due_date
                        else:
                            time_delta = timedelta(
                                days=loan.grab_oldest_unpaid_payments[0].get_grab_dpd)
                    elif self.due_date >= \
                            last_loan_halted_detail['account_resume_date']:
                        time_delta = base_date - self.due_date
                    else:
                        days_gap = 0
                        for account_halt_data in loan_account_halt_info[:-1]:
                            if self.due_date < account_halt_data['account_halt_date']:
                                days_gap += (account_halt_data['account_resume_date']
                                             - account_halt_data['account_halt_date']).days
                        time_delta = (base_date - self.due_date) - timedelta(days=days_gap)
                else:
                    days_gap = 0
                    for account_halt_data in loan_account_halt_info:
                        if self.due_date < account_halt_data['account_halt_date']:
                            days_gap += (account_halt_data['account_resume_date']
                                         - account_halt_data['account_halt_date']).days
                    time_delta = (base_date - self.due_date) - timedelta(days=days_gap)

            days = time_delta.days
        logger.debug({
            'due_date': self.due_date,
            'dpd': days
        })
        return days

    def total_principal_by_loan(self, exclude_paid_late=False, max_payment_number=0):
        excluded_status = PaymentStatusCodes.waiver_exclude_status_codes()
        payment_numbers = [self.payment_number]
        if exclude_paid_late:
            excluded_status.append(PaymentStatusCodes.PAID_LATE)
            payment_numbers = list(range(1, max_payment_number + 1))

        payments = self.loan.payment_set.exclude(
            payment_status__in=excluded_status
        ).filter(
            payment_number__in=payment_numbers
        )
        total_remaining_amount = 0
        for payment in payments:
            amount = payment.paid_amount - payment.installment_principal
            if amount <= 0:
                total_remaining_amount += abs(amount)
        return total_remaining_amount

    def total_interest_by_loan(self, exclude_paid_late=False, max_payment_number=0):
        excluded_status = PaymentStatusCodes.waiver_exclude_status_codes()
        payment_numbers = [self.payment_number]
        if exclude_paid_late:
            excluded_status.append(PaymentStatusCodes.PAID_LATE)
            payment_numbers = list(range(1, max_payment_number + 1))

        payments = self.loan.payment_set.exclude(
            payment_status__in=excluded_status
        ).filter(
            payment_number__in=payment_numbers
        )
        total_remaining_amount = 0
        for payment in payments:
            amount = payment.paid_amount - payment.installment_principal
            if amount >= 0:
                amount -= payment.installment_interest
                if amount <= 0:
                    total_remaining_amount += abs(amount)
            else:
                total_remaining_amount += payment.installment_interest
        return total_remaining_amount

    def total_late_fee_by_loan(self, exclude_paid_late=False, max_payment_number=0):
        excluded_status = PaymentStatusCodes.waiver_exclude_status_codes()
        payment_numbers = [self.payment_number]
        if exclude_paid_late:
            excluded_status.append(PaymentStatusCodes.PAID_LATE)
            payment_numbers = list(range(1, max_payment_number + 1))

        payments = self.loan.payment_set.exclude(
            payment_status__in=excluded_status
        ).filter(
            payment_number__in=payment_numbers
        )
        total_remaining_amount = 0
        for payment in payments:
            amount = payment.paid_amount - payment.installment_principal
            if amount >= 0:
                amount -= payment.installment_interest
                if amount >= 0:
                    amount -= payment.late_fee_amount
                    if amount <= 0:
                        total_remaining_amount += abs(amount)
                else:
                    total_remaining_amount += payment.late_fee_amount
            else:
                total_remaining_amount += payment.late_fee_amount
        return total_remaining_amount

    def get_next_payment(self):
        query = self.loan.payment_set.filter(due_date__gt=self.due_date)
        return query.order_by("due_date").first()

    def get_next_unpaid_payment(self):
        query = self.loan.payment_set.filter(due_date__gt=self.due_date,
                                             payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
        if query:
            return query.order_by("due_date").first()
        else:
            return None

    def get_previous_payment(self):
        previous_payment_number = self.payment_number - 1
        if previous_payment_number == 0:
            return False

        query = self.loan.payment_set.filter(payment_number=previous_payment_number)
        return query.first()

    def update_cashback_earned(self):
        if self.change_due_date_interest == 0:
            loan = self.loan
            productline_code = loan.application.product_line.product_line_code
            cashback_earned = loan.cashback_monthly
            logger.debug({'cashback_earned': cashback_earned})
            paid_date_3_days_earlier = self.due_date - timedelta(days=3)
            paid_date_2_days_earlier = self.due_date - timedelta(days=2)

            if productline_code in ProductLineCodes.mtl():
                if paid_date_3_days_earlier <= self.paid_date <= paid_date_2_days_earlier:
                    cashback_earned = cashback_earned * 2
                elif paid_date_3_days_earlier > self.paid_date:
                    cashback_earned = cashback_earned * 3

            if self.cashback_earned:
                self.cashback_earned += cashback_earned
            else:
                self.cashback_earned = cashback_earned

            customer = loan.customer
            customer.change_wallet_balance(change_accruing=cashback_earned,
                                           change_available=0,
                                           reason='payment_on_time',
                                           payment=self)

    def change_status(self, status_code):
        previous_status = self.payment_status
        new_status = StatusLookup.objects.get(status_code=status_code)
        logger.info({
            'previous_status': previous_status,
            'new_status': new_status,
            'action': 'changing_status',
            'payment_id': self.id
        })
        # never update sold off loan
        if self.status == PaymentStatusCodes.SELL_OFF:
            return True
        self.payment_status = new_status
        loan = self.loan
        partner = loan.application.partner if loan.application else loan.partner
        if previous_status.status_code in PaymentStatusCodes.greater_5DPD_status_code() and \
                partner and partner.name == PARTNER_PEDE:
            from juloserver.julo.tasks import call_pede_api_with_payment_greater_5DPD
            call_pede_api_with_payment_greater_5DPD.delay()

    def change_due_amount(self, status_code):
        if status_code == StatusLookup.PAYMENT_5DPD_CODE:
            late_fee = self.calculate_late_fee()
            due_amount = self.due_amount + late_fee

        elif status_code > StatusLookup.PAYMENT_5DPD_CODE \
                and status_code <= StatusLookup.PAYMENT_180DPD_CODE:
            late_fee = self.late_fee_amount + self.calculate_late_fee()
            due_amount = self.due_amount + late_fee

        logger.debug({
            'status': status_code,
            'prev_late_fee': self.late_fee_amount,
            'new_late_fee': late_fee,
            'prev_due_amount': self.due_amount,
            'new_due_amount': due_amount,
            'action': 'change_due_amount'
        })
        self.late_fee_amount = late_fee
        self.due_amount = due_amount

    def update_status_based_on_due_date(self):
        updated = False
        due_late_days = self.due_late_days
        if self.loan.account and self.loan.account.account_lookup.workflow.name \
                == WorkflowConst.GRAB:
            due_late_days = self.due_late_days_grab

        if due_late_days is None:
            return updated

        if due_late_days < -self.DUE_SOON_DAYS:
            if self.status != StatusLookup.PAYMENT_NOT_DUE_CODE:
                self.change_status(StatusLookup.PAYMENT_NOT_DUE_CODE)
                updated = True
        elif due_late_days < 0:
            if self.status != StatusLookup.PAYMENT_DUE_IN_3_DAYS_CODE:
                self.change_status(StatusLookup.PAYMENT_DUE_IN_3_DAYS_CODE)
                updated = True
        elif due_late_days == 0:
            if self.status != StatusLookup.PAYMENT_DUE_TODAY_CODE:
                self.change_status(StatusLookup.PAYMENT_DUE_TODAY_CODE)
                updated = True
        elif due_late_days < 5:
            if due_late_days == 4 and \
                    self.loan.product.product_line.product_line_code == ProductLineCodes.DAGANGAN:
                self.change_status(StatusLookup.PAYMENT_4DPD_CODE)
                updated = True
            elif self.status != StatusLookup.PAYMENT_1DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_1DPD_CODE)
                updated = True
        elif due_late_days < 30:
            if self.loan.product.product_line.product_line_code in {
                ProductLineCodes.KOPERASI_TUNAS,
                ProductLineCodes.KOPERASI_TUNAS_45,
            }:
                if due_late_days < 8 and self.status != StatusLookup.PAYMENT_1DPD_CODE:
                    self.change_status(StatusLookup.PAYMENT_1DPD_CODE)
                    updated = True
                elif due_late_days >= 8 and self.status != StatusLookup.PAYMENT_8DPD_CODE:
                    self.change_status(StatusLookup.PAYMENT_8DPD_CODE)
                    updated = True
            elif self.loan.product.product_line.product_line_code == ProductLineCodes.DAGANGAN:
                self.change_status(StatusLookup.PAYMENT_4DPD_CODE)
                updated = True
            elif self.status != StatusLookup.PAYMENT_5DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_5DPD_CODE)
                updated = True
        elif due_late_days < 60:
            if self.status != StatusLookup.PAYMENT_30DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_30DPD_CODE)
                updated = True
        elif due_late_days < 90:
            if self.status != StatusLookup.PAYMENT_60DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_60DPD_CODE)
                updated = True
        elif due_late_days < 120:
            if self.status != StatusLookup.PAYMENT_90DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_90DPD_CODE)
                updated = True
        elif due_late_days < 150:
            if self.status != StatusLookup.PAYMENT_120DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_120DPD_CODE)
                updated = True
        elif due_late_days < 180:
            if self.status != StatusLookup.PAYMENT_150DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_150DPD_CODE)
                updated = True
        else:
            if self.status != StatusLookup.PAYMENT_180DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_180DPD_CODE)
                updated = True

        return updated

    def update_status_based_on_late_fee_applied(self):
        if self.late_fee_applied == 0:
            self.change_status(StatusLookup.PAID_WITHIN_GRACE_PERIOD_CODE)
        if self.late_fee_applied == 1:
            self.change_status(StatusLookup.PAYMENT_5DPD_CODE)
        if self.late_fee_applied == 2:
            self.change_status(StatusLookup.PAYMENT_30DPD_CODE)
        if self.late_fee_applied == 3:
            self.change_status(StatusLookup.PAYMENT_60DPD_CODE)
        if self.late_fee_applied == 4:
            self.change_status(StatusLookup.PAYMENT_90DPD_CODE)
        if self.late_fee_applied == 5:
            self.change_status(StatusLookup.PAYMENT_120DPD_CODE)
        if self.late_fee_applied == 6:
            self.change_status(StatusLookup.PAYMENT_150DPD_CODE)
        else:
            self.change_status(StatusLookup.PAYMENT_180DPD_CODE)

    def apply_late_fee(self, late_fee):
        if self.late_fee_amount:
            self.late_fee_amount += late_fee
        else:
            self.late_fee_amount = late_fee
        self.due_amount += late_fee
        self.late_fee_applied += 1
        self.save()

        logger.info({
            'action': 'apply_late_fee',
            'late_fee_amount': self.late_fee_amount,
            'due_amount': self.due_amount
        })

    def create_payment_history(self, data):
        data['payment'] = self
        data['payment_new_status_code'] = self.status
        data['payment_number'] = self.payment_number
        data['paid_amount'] = self.paid_amount
        data['paid_date'] = self.paid_date
        data['due_date'] = self.due_date
        data['due_amount'] = self.due_amount
        data['application'] = self.loan.application
        data['loan'] = self.loan
        data['loan_new_status_code'] = self.loan.status
        payment_history = PaymentHistory(**data)

        payment_history.save()

    def create_warning_letter_history(self, data):
        data['payment'] = self
        data['payment_status_code'] = self.status
        data['due_date'] = self.due_date
        data['customer'] = self.loan.customer
        data['loan'] = self.loan
        data['loan_status_code'] = self.loan.status

        warning_letter_history = WarningLetterHistory(**data)
        warning_letter_history.save()

    def process_transaction(self, event_amount):
        objects = {}
        objects['principal'] = 0
        objects['interest'] = 0
        objects['late_fee'] = 0
        unaccounted_amount = event_amount
        # check principal
        if unaccounted_amount <= self.remaining_principal:
            self.paid_principal += unaccounted_amount
            objects['principal'] = unaccounted_amount
            return objects
        unaccounted_amount -= self.remaining_principal
        objects['principal'] = self.remaining_principal
        self.paid_principal += self.remaining_principal

        # check interest
        if unaccounted_amount <= self.remaining_interest:
            self.paid_interest += unaccounted_amount
            objects['interest'] = unaccounted_amount
            return objects
        unaccounted_amount -= self.remaining_interest
        objects['interest'] = self.remaining_interest
        self.paid_interest += self.remaining_interest

        # check late fee
        self.paid_late_fee += unaccounted_amount
        objects['late_fee'] = unaccounted_amount
        return objects

    @property
    def payment_status_label_julo_one(self):
        status = 'Belum jatuh tempo'

        if self.is_paid:
            status = 'Terbayar tepat waktu'
            if self.paid_late_days > 0:
                status = 'Terbayar terlambat'
        elif self.due_late_days == 0:
            status = 'Jatuh tempo hari ini'
        elif self.due_late_days > 0:
            status = 'Terlambat'

        return status

    @property
    def maximum_cashback(self):
        """
        Maximum cashback earned for payment.
        """
        total_fee = self.loan.loanadditionalfee_set.aggregate(total=Sum('fee_amount'))['total'] or 0
        return (
            math.ceil(
                (self.loan.loan_amount - self.loan.loan_disbursement_amount - total_fee)
                / self.loan.loan_duration
            )
            + self.installment_interest
        )

    def get_last_payment_event_date_and_amount(self):
        last_payment_event = self.paymentevent_set.filter(
            event_type='payment',
        ).last()
        if not last_payment_event:
            return None, 0
        return last_payment_event.event_date, last_payment_event.event_payment

    def calculate_late_fee_productive_loan(self, product_line_id):
        late_fee_percentage = self.loan.product.late_fee_pct
        if product_line_id == ProductLineCodes.DAGANGAN:
            if self.due_late_days == 4:
                late_fee_percentage = 0.004
            elif self.due_late_days == 30:
                late_fee_percentage = 0.026
        elif product_line_id in (ProductLineCodes.KOPERASI_TUNAS, ProductLineCodes.KOPERASI_TUNAS_45):
            if self.due_late_days == 8:
                late_fee_percentage = 0.008
            elif self.due_late_days == 30:
                late_fee_percentage = 0.022
        else:
            if self.due_late_days == 5:
                late_fee_percentage = 0.005
            elif self.due_late_days == 30:
                late_fee_percentage = 0.025
        late_fee = late_fee_percentage * self.remaining_principal
        return py2round(late_fee, -2)

    def calculate_late_fee(self):
        late_fee_percentage = self.loan.product.late_fee_pct
        if (not self.is_julo_one_payment and not self.is_julo_starter_payment) or \
                late_fee_percentage <= 0.05:
            return self.loan.late_fee_amount
        if self.due_late_days <= 29:
            late_fee_percentage = 0.015
        elif 30 <= self.due_late_days < 60:
            late_fee_percentage = 0.075
        late_fee = late_fee_percentage * self.remaining_principal
        return py2round(late_fee, -2)


class PaymentStatusChange(StatusChangeModel):

    id = models.AutoField(db_column='payment_status_change_id', primary_key=True)

    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id')
    # TODO: for some reason the api user is not being captured. Asking its
    # maintainer for help
    changed_by = CurrentUserField(related_name="payment_status_changes")

    class Meta(object):
        db_table = 'payment_status_change'


class PaymentNote(TimeStampedModel):

    id = models.AutoField(db_column='payment_note_id', primary_key=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING,
        db_column='payment_id',
        blank=True,
        null=True)
    status_change = models.OneToOneField(
        PaymentStatusChange, models.DO_NOTHING,
        db_column='payment_status_change_id',
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
    note_text = models.TextField()
    added_by = CurrentUserField(related_name="payment_notes")
    extra_data = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'payment_note'


class PaymentMethodLookup(TimeStampedModel):
    code = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=50)
    image_logo_url = models.CharField(max_length=500, blank=True, null=True)
    image_background_url = models.CharField(max_length=500, blank=True, null=True)
    bank_virtual_name = models.CharField(max_length=50, blank=True, null=True)
    is_shown_mf = models.BooleanField(default=False)
    image_logo_url_v2 = models.CharField(max_length=500, blank=True, null=True)

    class Meta(object):
        db_table = 'payment_method_lookup'

    def __str__(self):
        """Visual identification"""
        return "%s %s" % (self.code, self.name)


class PaymentMethodQuerySet(PIIVaultQueryset):
    def active_by_customer(self, customer):
        return self.filter(customer=customer, is_shown=True)

    def exclude_bank_name(self, loan):
        bank_name = re.sub("(?i)bank", "", loan.julo_bank_name)
        return self.filter(loan=loan, is_shown=True) \
            .exclude(payment_method_name__icontains=bank_name.strip())


class PaymentMethodManager(GetInstanceMixin, JuloModelManager, PIIVaultModelManager):

    def get_queryset(self):
        return PaymentMethodQuerySet(self.model)

    def displayed(self, loan):
        return self.get_queryset().exclude_bank_name(loan)

    def active_payment_method(self, customer):
        return self.get_queryset().active_by_customer(customer)


class PaymentMethod(PIIVaultModel):
    PII_FIELDS = ['virtual_account']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = models.AutoField(db_column='payment_method_id', primary_key=True)

    payment_method_code = models.CharField(max_length=10)
    payment_method_name = models.CharField(max_length=150)
    bank_code = models.CharField(max_length=4, null=True, blank=True)
    loan = models.ForeignKey(
        Loan, models.DO_NOTHING, db_column='loan_id', null=True, blank=True)
    line_of_credit = models.ForeignKey(
        'line_of_credit.LineOfCredit', models.DO_NOTHING, db_column='line_of_credit_id',
        null=True, blank=True)
    virtual_account = models.CharField(
        max_length=50,
        blank=True,
        validators=[RegexValidator(
            regex='^[0-9]+$', message='Virtual account has to be numeric digits')
        ],
        unique=False,
        db_index=True
    )
    customer = models.ForeignKey(
        'Customer', models.DO_NOTHING,
        db_column='customer_id', null=True, blank=True)
    is_primary = models.NullBooleanField()
    is_shown = models.NullBooleanField(default=True)
    is_preferred = models.NullBooleanField(default=False)
    sequence = models.IntegerField(null=True, blank=True)
    is_affected = models.NullBooleanField()
    customer_credit_limit = models.ForeignKey(
        'paylater.CustomerCreditLimit',
        models.DO_NOTHING,
        db_column='customer_credit_limit_id',
        null=True, blank=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='edited_by', null=True)
    is_latest_payment_method = models.NullBooleanField()
    virtual_account_tokenized = models.TextField(blank=True, null=True)
    vendor = models.CharField(max_length=50, blank=True, null=True)

    _payment_method_new_name = None

    objects = PaymentMethodManager()

    class Meta(object):
        db_table = 'payment_method'

    def save(self, *args, **kwargs):
        mobile_feature = MobileFeatureSetting.objects.filter(
            feature_name=self.payment_method_name).cache().first()
        if not self.pk and mobile_feature:
            # change is_shown only when the payment method is created
            # indicated by the pk being none
            self.is_shown = mobile_feature.is_active
        super(PaymentMethod, self).save(*args, **kwargs)

    @property
    def payment_method_new_name(self):
        if not self._payment_method_new_name:
            self._payment_method_new_name = self.payment_method_name
            if self.bank_code in ['014', '022']:
                check_existing = BankVirtualAccount.objects.filter(
                    bank_code=self.bank_code,
                    virtual_account_number=self.virtual_account
                ).exists()
                if check_existing:
                    self._payment_method_new_name = 'Bank CIMB Offline'
                    if self.bank_code == '014':
                        self._payment_method_new_name = 'Bank BCA Offline'

        return self._payment_method_new_name


class VirtualAccountSuffixManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class VirtualAccountSuffix(PIIVaultModel):
    PII_FIELDS = ['virtual_account_suffix']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = models.AutoField(db_column='virtual_account_suffix_id', primary_key=True)
    virtual_account_suffix = models.CharField(
        max_length=10,
        blank=True,
        validators=[RegexValidator(
            regex='^[0-9]+$', message='Virtual account suffix has to be numeric digits')
        ],
        unique=True
    )
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', null=True, blank=True)
    line_of_credit = models.ForeignKey(
        'line_of_credit.LineOfCredit', models.DO_NOTHING, db_column='line_of_credit_id',
        null=True, blank=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True)
    virtual_account_suffix_tokenized = models.TextField(null=True, blank=True)
    objects = VirtualAccountSuffixManager()

    class Meta(object):
        db_table = 'virtual_account_suffix'


class PaymentEventManager(GetInstanceMixin, JuloModelManager):
    def bulk_create(self, objs, **kwargs):
        from juloserver.julo.tasks2.channeling_related_tasks import (
            trigger_create_channeling_payment_event_bulk_create,
        )

        payment_ids = set()
        payment_event_manager = super(PaymentEventManager, self).bulk_create(objs, **kwargs)

        for i in objs:
            payment_ids.add(i.payment.id)

        execute_after_transaction_safely(
            lambda: trigger_create_channeling_payment_event_bulk_create.delay(
                payment_ids=payment_ids
            )
        )

        return payment_event_manager


class PaymentEvent(TimeStampedModel):
    id = models.AutoField(db_column='payment_event_id', primary_key=True)

    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id')
    event_payment = models.BigIntegerField()
    event_due_amount = models.BigIntegerField()
    event_date = models.DateField()
    event_type = models.CharField(max_length=50, default='payment')
    payment_receipt = models.TextField(null=True, blank=True)
    payment_method = models.ForeignKey(
        PaymentMethod, models.DO_NOTHING, db_column='payment_method_id',
        blank=True, null=True)

    added_by = CurrentUserField(related_name="payment_events")
    can_reverse = models.BooleanField(default=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='collected_by', blank=True, null=True)
    reversal = models.OneToOneField("self", models.DO_NOTHING, db_column='reversal',
                                    blank=True, null=True,
                                    related_name="correct_payment_event")
    accounting_date = models.DateField(blank=True, null=True)
    account_transaction = models.ForeignKey(
        'account.AccountTransaction',
        models.DO_NOTHING,
        db_column='account_transaction_id',
        blank=True, null=True)

    objects = PaymentEventManager()

    class Meta(object):
        db_table = 'payment_event'

    def save(self, *args, **kwargs):
        # Forbidding accounting date from being updated
        if "update_fields" in kwargs:
            update_fields = kwargs["update_fields"]
            if "accounting_date" in update_fields:
                update_fields.remove("accounting_date")

        super(PaymentEvent, self).save(*args, **kwargs)


class PartnerManager(GetInstanceMixin, JuloModelManager):
    MAX_GENERATE_XID_RETRY = 10

    def create(self, *args, **kwargs):
        obj = super(PartnerManager, self).create(*args, **kwargs)
        if kwargs.get('partner_xid'):
            return obj

        return self.generate_and_update_partner_xid(obj)

    def generate_and_update_partner_xid(self, partner):
        """
        Use this function to generate and update partner_xid for existing partner.
        """
        try:
            for i in range(0, self.MAX_GENERATE_XID_RETRY + 1):
                partner.generate_xid()
                if self.filter(partner_xid=partner.partner_xid).count() == 0:
                    partner.save(update_fields=['partner_xid'])
                    return partner

                partner.partner_xid = None
                if i == self.MAX_GENERATE_XID_RETRY:
                    raise MaxRetriesExceeded(
                        'Cannot generate unique partner_xid for partner {}'.format(partner.id)
                    )
        except MaxRetriesExceeded as ex:
            sentry_client = get_julo_sentry_client()
            logger.exception(
                {
                    "module": "julo",
                    "action": "PartnerManager.generate_and_update_partner_xid",
                    "message": str(ex),
                    "partner_id": partner.id,
                }
            )
            sentry_client.captureException()
        return partner


class PartnerPIIVaultManager(PIIVaultModelManager, PartnerManager):
    pass


class Partner(PIIVaultModel):
    PII_FIELDS = [
        'name',
        'email',
        'phone',
        'npwp',
        'poc_name',
        'poc_email',
        'poc_phone',
        'partner_bank_account_number',
        'recipients_email_address_for_bulk_disbursement',
        'recipients_email_address_for_190_application',
        'cc_email_address_for_bulk_disbursement',
        'cc_email_address_for_190_application',
        'sender_email_address_for_bulk_disbursement',
        'sender_email_address_for_190_application',
    ]
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    TYPE_CHOICES = (('referrer', 'referrer'),
                    ('receiver', 'receiver'),
                    ('lender', 'lender'))
    TYPE_DUE_DATE_CHOICES = (('monthly', 'monthly'),
                             ('end of tenor', 'end of tenor'))
    id = models.AutoField(db_column='partner_id', primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='auth_user_id', null=True, blank=True)

    name = models.CharField(max_length=100, db_index=True)
    email = models.EmailField(blank=True, null=True)
    phone = PhoneNumberField(null=True, blank=True)
    token = models.CharField(max_length=256, null=True, blank=True)
    systrace = models.CharField(max_length=256, null=True, blank=True)
    type = models.CharField(
        choices=TYPE_CHOICES, null=True, blank=True, max_length=50)
    is_active = models.BooleanField(default=False)

    npwp = models.CharField(max_length=20, null=True, blank=True)
    poc_name = models.CharField(max_length=100, null=True, blank=True)
    poc_email = models.CharField(max_length=100, null=True, blank=True)
    poc_phone = PhoneNumberField(null=True, blank=True)
    source_of_fund = models.CharField(max_length=256, null=True, blank=True)
    company_name = models.CharField(max_length=100, null=True, blank=True)
    company_address = models.CharField(max_length=512, null=True, blank=True)
    business_type = models.CharField(max_length=100, null=True, blank=True)
    agreement_letter_number = models.TextField(null=True, blank=True)
    is_csv_upload_applicable = models.BooleanField(default=False)
    is_disbursement_to_partner_bank_account = models.BooleanField(default=False)
    is_disbursement_to_distributor_bank_account = models.NullBooleanField(
        help_text="Currently only used in partnership merchant financing product"
    )
    partner_bank_account_number = models.CharField(max_length=50,
                                                   null=True,
                                                   blank=True,
                                                   help_text='Please add partner bank account number '
                                                             'if the disbursement needs to '
                                                             'done on partner bank account')
    partner_bank_account_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Please add partner bank account name '
                  'if the disbursement needs to '
                  'done on partner bank account'
    )
    partner_bank_name = models.CharField(max_length=255, null=True, blank=True)
    name_bank_validation = models.ForeignKey(
        'disbursement.NameBankValidation', models.DO_NOTHING,
        db_column='name_bank_validation_id', blank=True, null=True)
    recipients_email_address_for_bulk_disbursement = models. \
        TextField(blank=True, null=True,
                  help_text='Please add email address separated by comma')
    recipients_email_address_for_190_application = models. \
        TextField(blank=True, null=True,
                  help_text='Please add email address separated by comma')
    cc_email_address_for_bulk_disbursement = models. \
        TextField(blank=True, null=True,
                  help_text='Please add email address separated by comma')
    cc_email_address_for_190_application = models. \
        TextField(blank=True, null=True,
                  help_text='Please add email address separated by comma')
    sender_email_address_for_bulk_disbursement = models. \
        TextField(blank=True, null=True)
    sender_email_address_for_190_application = models. \
        TextField(blank=True, null=True)
    due_date_type = models.CharField(
        choices=TYPE_DUE_DATE_CHOICES, blank=True, null=True, max_length=50)
    is_email_send_to_customer = models.BooleanField(default=False,
                                                    help_text='Is 190 application email and '
                                                              'disbursement email send directly to customer')
    product_line = models.ForeignKey(
        'ProductLine', db_column='product_line_id', blank=True, null=True)

    name_tokenized = models.TextField(null=True, blank=True)
    email_tokenized = models.TextField(null=True, blank=True)
    phone_tokenized = models.TextField(null=True, blank=True)
    npwp_tokenized = models.TextField(null=True, blank=True)
    poc_name_tokenized = models.TextField(null=True, blank=True)
    poc_email_tokenized = models.TextField(null=True, blank=True)
    poc_phone_tokenized = models.TextField(null=True, blank=True)
    partner_bank_account_number_tokenized = models.TextField(null=True, blank=True)
    recipients_email_address_for_bulk_disbursement_tokenized = models.TextField(
        null=True, blank=True
    )
    recipients_email_address_for_190_application_tokenized = models.TextField(null=True, blank=True)
    cc_email_address_for_bulk_disbursement_tokenized = models.TextField(null=True, blank=True)
    cc_email_address_for_190_application_tokenized = models.TextField(null=True, blank=True)
    sender_email_address_for_bulk_disbursement_tokenized = models.TextField(null=True, blank=True)
    sender_email_address_for_190_application_tokenized = models.TextField(null=True, blank=True)

    partner_xid = models.CharField(max_length=20, null=True, blank=True, unique=True)

    objects = PartnerPIIVaultManager()

    class Meta(object):
        db_table = 'partner'

    def __str__(self):
        return self.name

    @property
    def is_grab(self):
        if self.name == "grab":
            return True
        else:
            return False

    @property
    def is_active_lender(self):
        if self.type == "lender" and self.is_active:
            return True
        else:
            return False

    @property
    def logo(self):
        image = Image.objects.filter(
            image_source=self.id, image_type="partner_logo"
        ).order_by('-id').last()
        if image:
            return image.image_url

        return None

    @property
    def partnership_config(self):
        partnership_config = self.partnershipconfig_set.last()
        return partnership_config

    def generate_xid(self):
        if self.id is None or self.partner_xid is not None:
            return

        # e.g. facebook => FACxAFD
        # e.g. vn => VNxSIYP
        prefix = self.name.strip().upper().replace(' ', '')[:3] + 'x'
        self.partner_xid = generate_unique_identifier(
            chars=string.ascii_uppercase,
            prefix=prefix,
            length=7,
        )

    @property
    def name_detokenized(self):
        from juloserver.pii_vault.constants import PiiSource
        from juloserver.partnership.utils import partnership_detokenize_sync_object_model

        detokenize_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            self,
            None,
            ['name'],
        )
        return detokenize_data.name


class PartnerProperty(TimeStampedModel):
    id = models.AutoField(db_column='partner_property_id', primary_key=True)
    account = models.ForeignKey('account.Account',
                                models.DO_NOTHING, db_column='account_id')
    partner = models.ForeignKey(Partner,
                                models.DO_NOTHING, db_column='partner_id')
    partner_reference_id = models.TextField(null=True, blank=True)
    partner_customer_id = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = 'partner_property'
        unique_together = ('partner', 'account')


class ProductProfileManager(GetInstanceMixin, JuloModelManager):
    pass


class ProductProfile(TimeStampedModel):
    PAYMENT_FREQ_CHOICES = (('Monthly', 'Monthly'),
                            ('Yearly', 'Yearly'),
                            ('Daily', 'Daily'),
                            ('Weekly', 'Weekly'))
    PRODUCT_TYPE_CHOICES = (('Initial', 'Initial'),
                            ('Forward', 'Forward'))

    id = models.AutoField(db_column='product_profile_id', primary_key=True)
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=250)
    min_amount = models.BigIntegerField(default=0)
    max_amount = models.BigIntegerField(default=0)
    min_duration = models.IntegerField(default=0)
    max_duration = models.IntegerField(default=0)
    min_interest_rate = models.FloatField()
    max_interest_rate = models.FloatField()
    interest_rate_increment = models.FloatField(default=0.0000)
    payment_frequency = models.CharField(choices=PAYMENT_FREQ_CHOICES,
                                         max_length=50)
    min_origination_fee = models.FloatField()
    max_origination_fee = models.FloatField()
    origination_fee_increment = models.FloatField(default=0.0000)
    late_fee = models.FloatField(default=0.0000)
    cashback_initial = models.FloatField(default=0.0000)
    cashback_payment = models.FloatField(default=0.0000)
    debt_income_ratio = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_product_exclusive = models.BooleanField(default=False)
    is_initial = models.BooleanField(default=False)

    objects = ProductProfileManager()

    class Meta(object):
        db_table = 'product_profile'

    def clean(self):
        # negative value validation
        if self.min_duration and self.min_duration < 0:
            raise Exception('min duration cannot be negative value')
        if self.max_duration and self.max_duration < 0:
            raise Exception('max duration cannot be negative value')
        if self.min_amount and self.min_amount < 0:
            raise Exception('min amount cannot be negative value')
        if self.max_amount and self.max_amount < 0:
            raise Exception('max amount cannot be negative value')
        if self.min_interest_rate and self.min_interest_rate < 0:
            raise Exception('min interest rate cannot be negative value')
        if self.max_interest_rate and self.max_interest_rate < 0:
            raise Exception('max interest rate cannot be negative value')
        if self.min_origination_fee and self.min_origination_fee < 0:
            raise Exception('min origination fee cannot be negative value')
        if self.max_origination_fee and self.max_origination_fee < 0:
            raise Exception('max origination fee cannot be negative value')
        if self.interest_rate_increment and self.interest_rate_increment < 0:
            raise Exception('interest rate increment cannot be negative value')
        if self.origination_fee_increment and self.origination_fee_increment < 0:
            raise Exception('origination fee increment cannot be negative value')
        if self.late_fee and self.late_fee < 0:
            raise Exception('late fee cannot be negative value')
        if self.cashback_initial and self.cashback_initial < 0:
            raise Exception('cashback initial cannot be negative value')
        if self.cashback_payment and self.cashback_payment < 0:
            raise Exception('cashback payment cannot be negative value')
        if self.debt_income_ratio and self.debt_income_ratio < 0:
            raise Exception('debt income ratio cannot be negative value')
        # greater than validation
        if self.min_amount > self.max_amount:
            raise Exception('min amount cannot greater than max amount')
        if self.min_duration > self.max_duration:
            raise Exception('min duration cannot greater than max duration')
        if self.min_interest_rate > self.max_interest_rate:
            raise Exception('min interest rate cannot greater than max interest rate')
        if self.min_origination_fee > self.max_origination_fee:
            raise Exception('min origination fee cannot greater \
                            than max origination fee')
        if self.interest_rate_increment > self.max_interest_rate:
            raise Exception('interest_rate_increment cannot greater \
                            than max interest rate')
        if self.origination_fee_increment > self.max_origination_fee:
            raise Exception('origination fee increment cannot greater \
                            than max origination fee')


class ProductCustomerCriteriaManager(GetInstanceMixin, JuloModelManager):
    pass


class ProductCustomerCriteria(TimeStampedModel):
    id = models.AutoField(db_column='product_customer_criteria_id', primary_key=True)
    product_profile = models.OneToOneField(ProductProfile,
                                           on_delete=models.CASCADE,
                                           db_column='product_profile_id')
    min_age = models.IntegerField(null=True, blank=True)
    max_age = models.IntegerField(null=True, blank=True)
    min_income = models.BigIntegerField(null=True, blank=True)
    max_income = models.BigIntegerField(null=True, blank=True)
    job_type = ArrayField(models.CharField(max_length=250), blank=True, null=True)
    job_industry = ArrayField(models.CharField(max_length=250), blank=True, null=True)
    job_description = ArrayField(models.CharField(max_length=250), blank=True, null=True)
    location = ArrayField(models.CharField(max_length=250), null=True, blank=True)
    credit_score = ArrayField(models.CharField(max_length=5), null=True, blank=True)

    objects = ProductCustomerCriteriaManager()

    class Meta(object):
        db_table = 'product_customer_criteria'

    def clean(self):
        # negative value validation
        if self.min_age and self.min_age < 0:
            raise Exception('min age cannot be negative value')
        if self.max_age and self.max_age < 0:
            raise Exception('max age cannot be negative value')
        if self.min_income and self.min_income < 0:
            raise Exception('min income cannot be negative value')
        if self.max_income and self.max_income < 0:
            raise Exception('max income cannot be negative value')
        # greater than validation
        if self.min_age and self.max_age:
            if self.min_age > self.max_age:
                raise Exception('min age cannot greater than max age')
        if self.min_income and self.max_income:
            if self.min_income > self.max_income:
                raise Exception('min income cannot greater than max inxome')


class LenderProductCriteriaManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderProductCriteria(TimeStampedModel):
    LENDER_PRODUCT_TYPE_CHOICES = (('Product Definition', 'Product Definition'),
                                   ('Product List', 'Product List'))

    id = models.AutoField(db_column='lender_product_criteria_id', primary_key=True)
    partner = models.OneToOneField(Partner,
                                   on_delete=models.CASCADE,
                                   db_column='partner_id',
                                   blank=True, null=True)
    lender = models.OneToOneField('followthemoney.LenderCurrent',
                                  on_delete=models.CASCADE,
                                  db_column='lender_id',
                                  blank=True, null=True)
    type = models.CharField(choices=LENDER_PRODUCT_TYPE_CHOICES, max_length=50)
    product_profile_list = ArrayField(models.IntegerField(), blank=True, null=True)
    min_amount = models.BigIntegerField(null=True, blank=True)
    max_amount = models.BigIntegerField(null=True, blank=True)
    min_duration = models.IntegerField(null=True, blank=True)
    max_duration = models.IntegerField(null=True, blank=True)
    min_interest_rate = models.FloatField(null=True, blank=True)
    max_interest_rate = models.FloatField(null=True, blank=True)
    min_origination_fee = models.FloatField(null=True, blank=True)
    max_origination_fee = models.FloatField(null=True, blank=True)
    min_late_fee = models.FloatField(null=True, blank=True)
    max_late_fee = models.FloatField(null=True, blank=True)
    min_cashback_initial = models.FloatField(null=True, blank=True)
    max_cashback_initial = models.FloatField(null=True, blank=True)
    min_cashback_payment = models.FloatField(null=True, blank=True)
    max_cashback_payment = models.FloatField(null=True, blank=True)

    objects = LenderProductCriteriaManager()

    class Meta(object):
        db_table = 'lender_product_criteria'

    def clean(self):
        # negative value validation
        if self.min_amount and self.min_amount < 0:
            raise Exception('min amount cannot be negative value')
        if self.max_amount and self.max_amount < 0:
            raise Exception('max amount cannot be negative value')
        if self.min_duration and self.min_duration < 0:
            raise Exception('min duration cannot be negative value')
        if self.max_duration and self.max_duration < 0:
            raise Exception('max duration cannot be negative value')
        if self.min_interest_rate and self.min_interest_rate < 0:
            raise Exception('min interest rate cannot be negative value')
        if self.max_interest_rate and self.max_interest_rate < 0:
            raise Exception('max interest rate cannot be negative value')
        if self.min_origination_fee and self.min_origination_fee < 0:
            raise Exception('min origination fee cannot be negative value')
        if self.max_origination_fee and self.max_origination_fee < 0:
            raise Exception('max origination fee cannot be negative value')
        if self.min_late_fee and self.min_late_fee < 0:
            raise Exception('min late fee cannot be negative value')
        if self.max_late_fee and self.max_late_fee < 0:
            raise Exception('max late fee cannot be negative value')
        if self.min_cashback_initial and self.min_cashback_initial < 0:
            raise Exception('min cashback initial cannot be negative value')
        if self.max_cashback_initial and self.max_cashback_initial < 0:
            raise Exception('max cashback initial cannot be negative value')
        if self.min_cashback_payment and self.min_cashback_payment < 0:
            raise Exception('min cashback payment cannot be negative value')
        if self.max_cashback_payment and self.max_cashback_payment < 0:
            raise Exception('max cashback payment cannot be negative value')
        # greater than validation
        if self.min_amount and self.max_amount:
            if self.min_amount > self.max_amount:
                raise Exception('min amount cannot greater than max amount')
        if self.min_duration and self.max_duration:
            if self.min_duration > self.max_duration:
                raise Exception('min duration cannot greater than max duration')
        if self.min_interest_rate and self.max_interest_rate:
            if self.min_interest_rate > self.max_interest_rate:
                raise Exception('min interest rate cannot greater than max interest rate')
        if self.min_origination_fee and self.max_origination_fee:
            if self.min_origination_fee > self.max_origination_fee:
                raise Exception('min origination fee cannot greater \
                                than max origination fee')
        if self.min_late_fee and self.max_late_fee:
            if self.min_late_fee > self.max_late_fee:
                raise Exception('min late fee cannot greater than max late fee')
        if self.min_cashback_initial and self.max_cashback_initial:
            if self.min_cashback_initial > self.max_cashback_initial:
                raise Exception('min cashback initial cannot greater \
                                than max cashback initial')
        if self.min_cashback_payment and self.max_cashback_payment:
            if self.min_cashback_payment > self.max_cashback_payment:
                raise Exception('min cashback payment cannot greater \
                                than max cashback payment')


class LenderCustomerCriteriaManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderCustomerCriteria(TimeStampedModel):
    id = models.AutoField(db_column='lender_customer_criteria_id', primary_key=True)
    lender = models.OneToOneField('followthemoney.LenderCurrent',
                                  on_delete=models.CASCADE,
                                  db_column='lender_id',
                                  blank=True, null=True)
    partner = models.OneToOneField(Partner,
                                   on_delete=models.CASCADE,
                                   db_column='partner_id',
                                   blank=True, null=True)
    min_age = models.IntegerField(null=True, blank=True)
    max_age = models.IntegerField(null=True, blank=True)
    min_income = models.BigIntegerField(null=True, blank=True)
    max_income = models.BigIntegerField(null=True, blank=True)
    job_type = ArrayField(models.CharField(max_length=250), blank=True, null=True)
    job_industry = ArrayField(models.CharField(max_length=250), blank=True, null=True)
    job_description = ArrayField(models.CharField(max_length=250), blank=True, null=True)
    location = ArrayField(models.CharField(max_length=250), null=True, blank=True)
    credit_score = ArrayField(models.CharField(max_length=5), null=True, blank=True)
    loan_purpose = ArrayField(models.CharField(max_length=250), null=True, blank=True)
    company_name = ArrayField(models.CharField(max_length=250), null=True, blank=True)

    objects = LenderCustomerCriteriaManager()

    class Meta(object):
        db_table = 'lender_customer_criteria'

    def clean(self):
        # negative value validation
        if self.min_age and self.min_age < 0:
            raise Exception('min age cannot be negative value')
        if self.max_age and self.max_age < 0:
            raise Exception('max age cannot be negative value')
        if self.min_income and self.min_income < 0:
            raise Exception('min income cannot be negative value')
        if self.max_income and self.max_income < 0:
            raise Exception('max income cannot be negative value')
        # greater than validation
        if self.min_age and self.max_age:
            if self.min_age > self.max_age:
                raise Exception('min age cannot greater than max age')
        if self.min_income and self.max_income:
            if self.min_income > self.max_income:
                raise Exception('min income cannot be greater than max income')


class ProductLineQuerySet(CustomQuerySet):

    def first_time_lines(self):
        return self.exclude(product_line_type__endswith='2')

    def repeat_lines(self):
        return self.exclude(product_line_type__endswith='1')


class ProductLineManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return ProductLineQuerySet(self.model)


class ProductLine(TimeStampedModel):
    product_line_code = models.BigIntegerField(primary_key=True)
    product_line_type = models.CharField(max_length=50)
    min_amount = models.BigIntegerField()
    max_amount = models.BigIntegerField()
    min_duration = models.IntegerField()
    max_duration = models.IntegerField()
    min_interest_rate = models.FloatField()
    max_interest_rate = models.FloatField()
    payment_frequency = models.CharField(max_length=50)
    product_profile = models.OneToOneField(ProductProfile,
                                           on_delete=models.CASCADE,
                                           db_column='product_profile_id',
                                           null=True, blank=True)
    default_workflow = models.ForeignKey(
        'Workflow', models.DO_NOTHING, db_column='workflow_id', null=True, blank=True)
    # Class of actions will be executed
    handler = models.CharField(max_length=100, null=True, blank=True)
    non_premium_area_min_amount = models.BigIntegerField(default=None, null=True, blank=True)
    non_premium_area_max_amount = models.BigIntegerField(default=None, null=True, blank=True)
    amount_increment = models.BigIntegerField(blank=True, null=True, default=None)

    objects = ProductLineManager()

    class Meta(object):
        db_table = 'product_line'

    def __str__(self):
        return '%s_%s' % (self.product_line_code, self.product_line_type)


class ProductLookupManager(GetInstanceMixin, JuloModelManager):
    pass


class ProductLookup(TimeStampedModel):
    product_code = models.AutoField(primary_key=True)
    product_name = models.CharField(max_length=100)
    interest_rate = models.FloatField()
    origination_fee_pct = models.FloatField()
    late_fee_pct = models.FloatField()
    cashback_initial_pct = models.FloatField()
    cashback_payment_pct = models.FloatField()
    product_line = models.ForeignKey(
        ProductLine, models.DO_NOTHING, db_column='product_line_code')
    product_profile = models.ForeignKey(ProductProfile,
                                        models.DO_NOTHING,
                                        db_column='product_profile_id',
                                        null=True, blank=True)
    eligible_amount = models.BigIntegerField(blank=True, null=True)
    eligible_duration = models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    admin_fee = models.IntegerField(blank=True, null=True)

    objects = ProductLookupManager()

    class Meta(object):
        db_table = 'product_lookup'

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


class StatusLookupManager(GetInstanceMixin, JuloModelManager):
    pass


class StatusLookup(TimeStampedModel):
    """Status lookup table to define statuses for applications, loans, and
    payments.

    DEPRECATED: See statuses.ApplicationStatusCodes, statuses.LoanStatusCodes,
    and statuses.PaymentStatusCodes

    """
    status_code = models.IntegerField(primary_key=True)

    # Application

    FORM_SUBMITTED = 'Form submitted'
    DOCUMENTS_SUBMITTED = 'Documents submitted'
    APPLICATION_VERIFIED = 'Application verified'
    OFFER_MADE = 'Offer made to customer'
    OFFER_ACCEPTED = 'Offer accepted by customer'
    VERIFICATION_CALL_SUCCESSFUL = 'Verification calls successful'
    ACTIVATION_CALL_SUCCESSFUL = 'Activation call successful'
    LEGAL_AGREEMENT_SIGNED = 'Legal agreement signed'
    FUND_DISBURSAL_SUCCESSFUL = 'Fund disbursal successful'

    FORM_SUBMITTED_CODE = 110
    DOCUMENTS_SUBMITTED_CODE = 120
    TYPO_CALLS_UNSUCCESSFUL = 127
    CUSTOMER_IGNORES_CALLS = 128
    PENDING_PARTNER_APPROVAL = 129
    APPLICATION_VERIFIED_CODE = 130
    APPLICATION_RESUBMISSION_REQUESTED_CODE = 131
    APPLICATION_RESUBMITTED_CODE = 132
    APPLICATION_FLAGGED_FOR_FRAUD_CODE = 133
    APPLICATION_FLAGGED_FOR_SUPERVISOR_CODE = 134
    APPLICATION_DENIED_CODE = 135
    OFFER_MADE_TO_CUSTOMER_CODE = 140
    OFFER_ACCEPTED_BY_CUSTOMER_CODE = 141
    OFFER_DECLINED_BY_CUSTOMER_CODE = 142
    OFFER_EXPIRED_CODE = 143
    NAME_BANK_VALIDATION_FAILED_CODE = 144
    VERIFICATION_CALLS_SUCCESSFUL_CODE = 150
    VERIFICATION_CALLS_ONGOING_CODE = 151
    VERIFICATION_CALLS_FAILED_CODE = 152
    ACTIVATION_CALL_SUCCESSFUL_CODE = 160
    ACTIVATION_CALL_FAILED_CODE = 161
    LEGAL_AGREEMENT_SIGNED_CODE = 170
    LEGAL_AGREEMENT_EXPIRED_CODE = 171
    FUND_DISBURSAL_SUCCESSFUL_CODE = 180
    FUND_DISBURSAL_FAILED_CODE = 181
    MISSING_EMERGENCY_CONTACT = 188
    JULO_STARTER_AFFORDABILITY_CHECK = 108
    JULO_STARTER_LIMIT_GENERATED = 109
    JULO_STARTER_TURBO_UPGRADE = 191
    JULO_STARTER_UPGRADE_ACCEPTED = 192
    # Loan

    INACTIVE = 'Inactive'
    CURRENT = 'Current'

    INACTIVE_CODE = 210
    LENDER_APPROVAL = 211
    FUND_DISBURSAL_ONGOING = 212
    MANUAL_FUND_DISBURSAL_ONGOING = 213
    GRAB_AUTH_FAILED = 214
    CANCELLED_BY_CUSTOMER = 216
    SPHP_EXPIRED = 217
    FUND_DISBURSAL_FAILED = 218
    LENDER_REJECT = 219
    CURRENT_CODE = 220
    LOAN_1DPD_CODE = 230
    LOAN_4DPD_CODE = 238
    LOAN_5DPD_CODE = 231
    LOAN_8DPD_CODE = 239
    LOAN_30DPD_CODE = 232
    LOAN_60DPD_CODE = 233
    LOAN_90DPD_CODE = 234
    LOAN_120DPD_CODE = 235
    LOAN_150DPD_CODE = 236
    LOAN_180DPD_CODE = 237
    RENEGOTIATED_CODE = 240
    PAID_OFF_CODE = 250
    SELL_OFF = 260

    # Payment

    PAYMENT_NOT_DUE = 'Payment not due'
    PAID_ON_TIME = 'Paid on time'

    PAYMENT_NOT_DUE_CODE = 310
    PAYMENT_DUE_IN_3_DAYS_CODE = 311
    PAYMENT_DUE_TODAY_CODE = 312
    PAYMENT_1DPD_CODE = 320
    PAYMENT_4DPD_CODE = 328
    PAYMENT_5DPD_CODE = 321
    PAYMENT_8DPD_CODE = 329
    PAYMENT_30DPD_CODE = 322
    PAYMENT_60DPD_CODE = 323
    PAYMENT_90DPD_CODE = 324
    PAYMENT_120DPD_CODE = 325
    PAYMENT_150DPD_CODE = 326
    PAYMENT_180DPD_CODE = 327
    PAID_ON_TIME_CODE = 330
    PAID_WITHIN_GRACE_PERIOD_CODE = 331
    PAID_LATE_CODE = 332
    PARTIAL_RESTRUCTURED = 334
    SELL_OFF = 360

    # Credit Card

    CARD_OUT_OF_STOCK = 505
    CARD_APPLICATION_SUBMITTED = 510
    CARD_VERIFICATION_SUCCESS = 520
    CARD_ON_SHIPPING = 530
    CARD_APPLICATION_REJECTED = 525
    RESUBMIT_SELFIE = 523
    CARD_RECEIVED_BY_USER = 540
    CARD_VALIDATED = 545
    CARD_ACTIVATED = 580
    CARD_BLOCKED = 581
    CARD_UNBLOCKED = 582
    CARD_CLOSED = 583

    STATUS_LABEL_BAHASA = {
        105: "Formulir dikirim",
        190: "Akun diaktifkan",
        210: "NON-AKTIF",
        211: "Sedang diproses",  # Lender approval
        212: "Sedang diproses",  # Fund disbursal ongoing
        213: "Sedang diproses",  # Manual fund disbursal ongoing
        214: "GRAB Gagal proses",  # GRAB auth failed
        216: "Pinjaman dibatalkan",  # Customer cancelled on SPHP
        217: "Pinjaman kedaluwarsa",  # SPHP Expired
        218: "Sedang diproses",  # Fund disbursal failed
        219: "Pinjaman dibatalkan",  # Loan rejected by lender
        220: "LANCAR",
        230: "TERLAMBAT",
        231: "TERLAMBAT",
        232: "TERLAMBAT",
        233: "TERLAMBAT",
        234: "TERLAMBAT",
        235: "TERLAMBAT",
        236: "TERLAMBAT",
        237: "TERLAMBAT",
        250: "LUNAS",
        260: "DIALIHKAN",
        310: "Belum jatuh tempo",
        311: "Jatuh tempo sebentar lagi",
        312: "Jatuh tempo hari ini",
        320: "TERLAMBAT",
        321: "TERLAMBAT 5hr+",
        322: "TERLAMBAT 30hr+",
        323: "TERLAMBAT 60hr+",
        324: "TERLAMBAT 90hr+",
        325: "TERLAMBAT 120hr+",
        326: "TERLAMBAT 150hr+",
        327: "TERLAMBAT 180hr+",
        330: "Dibayar lunas, tepat waktu",
        331: "Dibayar lunas, dalam waktu tenggang",
        332: "Dibayar lunas, terlambat",
        360: "DIALIHKAN",
        505: "Kartu habis",
        510: "Pengajuan Kartu Kredit dikirim",
        520: "Pengajuan Kartu Kredit terverifikasi",
        530: "Kartu Kredit dikirim",
        525: "Pengajuan Kartu Kredit ditolak",
        523: "Pengiriman ulang selfie",
        540: "Kartu Kredit diterima",
        545: "Kartu Kredit tervalidasi",
        580: "Kartu Kredit teraktivasi",
        581: "Kartu Kredit diblock",
        582: "Kartu Kredit dibuka",
        583: "Kartu Kredit ditutup"
    }

    status = models.CharField(max_length=50)
    # Class of actions will be executed
    handler = models.CharField(max_length=100, null=True, blank=True)

    objects = StatusLookupManager()

    class Meta(object):
        db_table = 'status_lookup'

    def __str__(self):
        """Visual identification"""
        return '%s - %s' % (self.status_code, self.status)

    @property
    def show_status(self):
        """Visual identification"""
        return self.status


class ThirdPartyData(TimeStampedModel):
    id = models.AutoField(db_column='third_party_data_id', primary_key=True)

    application = models.OneToOneField(
        Application, related_name="third_party_data")

    lenddo = models.CharField(max_length=50, blank=True, null=True)
    emailage = models.CharField(max_length=50, blank=True, null=True)
    trulioo = models.CharField(max_length=50, blank=True, null=True)
    trustev = models.CharField(max_length=50, blank=True, null=True)
    creditcheck = models.CharField(max_length=50, blank=True, null=True)
    efl = models.CharField(max_length=50, blank=True, null=True)

    class Meta(object):
        db_table = 'third_party_data'


class CustomerManager(GetInstanceMixin, PIIVaultModelManager):
    MAX_GENERATE_XID_RETRY = 2

    def create(self, *args, **kwargs):
        obj = super(CustomerManager, self).create(*args, **kwargs)
        if kwargs.get('customer_xid'):
            return obj

        return self.generate_and_update_customer_xid(obj)

    def generate_and_update_customer_xid(self, customer):
        """
        Use this function to generate and update customer_xid for existing customer.
        """
        try:
            for i in range(0, self.MAX_GENERATE_XID_RETRY + 1):
                customer.generate_xid()
                if self.filter(customer_xid=customer.customer_xid).count() == 0:
                    customer.save(update_fields=['customer_xid'])
                    return customer

                customer.customer_xid = None
                if i == self.MAX_GENERATE_XID_RETRY:
                    raise MaxRetriesExceeded(
                        'Cannot generate unique customer_xid. {}'.format(customer.id))
        except MaxRetriesExceeded as ex:
            sentry_client = get_julo_sentry_client()
            logger.exception({
                "module": "julo",
                "action": "CustomerManager.generate_and_update_customer_xid",
                "message": str(ex),
                "customer_id": customer.id
            })
            sentry_client.captureException()
        return customer


class CustomerAttributesMixin(models.Model):
    """
    Extra attributes for Customer model. These attributes are duplicated from application.
    """
    class Meta:
        abstract = True

    app_version = models.TextField(blank=True, null=True, default=None)
    web_version = models.TextField(blank=True, null=True, default=None)
    current_application_id = models.BigIntegerField(blank=True, null=True, default=None)
    current_application_xid = models.BigIntegerField(blank=True, null=True, default=None)
    application_number = models.IntegerField(blank=True, null=True, default=None)

    application_is_deleted = models.NullBooleanField()
    application_status = models.ForeignKey(
        'StatusLookup', db_column='application_status_code',
        blank=True, null=True, default=None,
        db_constraint=False, db_index=False,
    )
    onboarding = models.ForeignKey(
        'julo.Onboarding', db_column='onboarding_id',
        null=True, blank=True, default=None,
        db_constraint=False, db_index=False,
    )
    product_line = models.ForeignKey(
        'ProductLine', db_column='product_line_code',
        blank=True, null=True, default=None,
        db_constraint=False, db_index=False,
    )
    partner = models.ForeignKey(
        'Partner', db_column='partner_id',
        blank=True, null=True, default=None,
        db_constraint=False, db_index=False,
    )
    workflow = models.ForeignKey(
        'Workflow', db_column='workflow_id',
        null=True, blank=True, default=None,
        db_constraint=False, db_index=False,
    )

    loan_purpose = models.TextField(blank=True, null=True, default=None)
    marketing_source = models.TextField(blank=True, null=True, default=None)
    referral_code = models.TextField(blank=True, null=True, default=None)
    address_detail = models.TextField(blank=True, null=True, default=None)
    address_street_num = models.TextField(blank=True, null=True, default=None)
    address_provinsi = models.TextField(blank=True, null=True, default=None)
    address_kabupaten = models.TextField(blank=True, null=True, default=None)
    address_kecamatan = models.TextField(blank=True, null=True, default=None)
    address_kelurahan = models.TextField(blank=True, null=True, default=None)
    address_kodepos = models.TextField(blank=True, null=True, default=None)
    mobile_phone_2 = models.TextField(blank=True, null=True, default=None)
    marital_status = models.TextField(blank=True, null=True, default=None)
    spouse_name = models.TextField(blank=True, null=True, default=None)
    spouse_mobile_phone = models.TextField(blank=True, null=True, default=None)
    kin_name = models.TextField(blank=True, null=True, default=None)
    kin_mobile_phone = models.TextField(blank=True, null=True, default=None)
    kin_relationship = models.TextField(blank=True, null=True, default=None)
    close_kin_mobile_phone = models.TextField(blank=True, null=True, default=None)
    close_kin_name = models.TextField(blank=True, null=True, default=None)
    close_kin_relationship = models.TextField(blank=True, null=True, default=None)
    birth_place = models.TextField(blank=True, null=True, default=None)

    last_education = models.TextField(blank=True, null=True, default=None)
    job_type = models.TextField(blank=True, null=True, default=None)
    job_description = models.TextField(blank=True, null=True, default=None)
    job_industry = models.TextField(blank=True, null=True, default=None)
    job_start = models.DateField(blank=True, null=True, default=None)
    company_name = models.TextField(blank=True, null=True, default=None)
    company_phone_number = models.TextField(blank=True, null=True, default=None)
    payday = models.IntegerField(blank=True, null=True, default=None)
    monthly_income = models.BigIntegerField(blank=True, null=True, default=None)
    monthly_expenses = models.BigIntegerField(blank=True, null=True, default=None)
    total_current_debt = models.BigIntegerField(blank=True, null=True, default=None)
    teaser_loan_amount = models.BigIntegerField(blank=True, null=True, default=None)

    bank_name = models.TextField(blank=True, null=True, default=None)
    name_in_bank = models.TextField(blank=True, null=True, default=None)
    bank_account_number = models.TextField(blank=True, null=True, default=None)
    name_bank_validation = models.ForeignKey(
        'disbursement.NameBankValidation',
        db_column='name_bank_validation_id',
        blank=True, null=True, default=None,
        db_constraint=False, db_index=False,
    )

    is_term_accepted = models.NullBooleanField()
    is_verification_agreed = models.NullBooleanField()
    is_document_submitted = models.NullBooleanField()
    is_courtesy_call = models.NullBooleanField()
    is_assisted_selfie = models.NullBooleanField()
    is_fdc_risky = models.NullBooleanField()
    bss_eligible = models.NullBooleanField()
    current_device = models.ForeignKey(
        Device,
        db_column='device_id',
        blank=True, null=True, default=None,
        db_constraint=False, db_index=False,
        related_name='current_customer',
    )
    application_merchant = models.ForeignKey(
        'merchant_financing.Merchant',
        db_column='merchant_id',
        blank=True, null=True, default=None,
        db_constraint=False, db_index=False,
        related_name='current_customer',
    )
    application_company = models.ForeignKey(
        'employee_financing.Company',
        db_column='company_id',
        blank=True, null=True, default=None,
        db_constraint=False, db_index=False,
    )
    monthly_housing_cost = models.BigIntegerField(blank=True, null=True, default=None)
    loan_purpose_desc = models.TextField(blank=True, null=True, default=None)


class Customer(PIIVaultModel, CustomerAttributesMixin, GetActiveApplicationMixin):
    REAPPLY_THREE_MONTHS_REASON = [
        'monthly_income_gt_3_million',
        'monthly_income',
        'sms_grace_period_3_months',
        'sms_grace_period_24_months',
        'job type blacklisted',
        'basic_savings',
        'job_term_gt_3_month',
        'debt_to_income_40_percent',
        'grace period',
        'form_partial_income',
        'saving_margin',
        'long_form_binary_checks',
        'failed_in_credit_score',
        'failed_dv_identity',
    ]
    REAPPLY_HALF_A_YEAR_REASON = ['foto tidak senonoh']
    REAPPLY_ONE_YEAR_REASON = [
        'negative data in sd', 'sms_delinquency_24_months',
        'email_delinquency_24_months', 'negative payment history with julo']
    REAPPLY_NOT_ALLOWED_REASON = [
        'fraud_form_partial_device', 'fraud_device', 'fraud_form_partial_hp_own',
        'fraud_form_partial_hp_kin', 'fraud_hp_spouse', 'fraud_email']
    REAPPLY_CUSTOM = ['application_date_of_birth', 'age not met']
    GENDER_CHOICES = (
        ('Pria', 'Pria'),
        ('Wanita', 'Wanita'))

    # PII ATTRIBUTES
    PII_FIELDS = ['fullname', 'phone', 'email', 'nik']

    id = models.AutoField(db_column='customer_id', primary_key=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='auth_user_id')

    fullname = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    phone = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    country = models.CharField(max_length=50, blank=True, null=True)
    nik = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ], blank=True, null=True, unique=True)
    self_referral_code = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    email_verification_key = models.CharField(max_length=50, blank=True, null=True)
    email_key_exp_date = models.DateTimeField(blank=True, null=True)
    reset_password_key = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    reset_password_exp_date = models.DateTimeField(blank=True, null=True)
    can_reapply = models.BooleanField(default=False)
    is_review_submitted = models.NullBooleanField()
    is_phone_verified = models.NullBooleanField()
    is_email_verified = models.NullBooleanField()
    appsflyer_device_id = models.CharField(max_length=50, blank=True, null=True)
    appsflyer_customer_id = models.CharField(max_length=50, blank=True, null=True)
    advertising_id = models.CharField(max_length=50, blank=True, null=True)
    disabled_reapply_date = models.DateTimeField(blank=True, null=True)
    can_reapply_date = models.DateTimeField(blank=True, null=True)
    potential_skip_pv_dv = models.BooleanField(default=False)
    google_access_token = models.CharField(max_length=500, blank=True, null=True)
    google_refresh_token = models.CharField(max_length=500, blank=True, null=True)
    is_digisign_registered = models.NullBooleanField()
    is_digisign_activated = models.NullBooleanField()
    # needed by paylater
    customer_xid = models.BigIntegerField(blank=True, null=True)
    gender = models.CharField("Jenis kelamin",
                              choices=GENDER_CHOICES,
                              max_length=10,
                              validators=[ascii_validator],
                              blank=True, null=True)
    dob = models.DateField(blank=True, null=True)

    # block notify to ICare client
    can_notify = models.BooleanField(default=True)
    is_digisign_affected = models.BooleanField(default=False)
    is_new_va = models.BooleanField(default=False)
    mother_maiden_name = models.CharField(max_length=100, blank=True, null=True)
    ever_entered_250 = models.BooleanField(default=False)
    app_instance_id = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    fullname_tokenized = models.CharField(max_length=50, blank=True, null=True)
    email_tokenized = models.CharField(max_length=50, blank=True, null=True)
    nik_tokenized = models.CharField(max_length=50, blank=True, null=True)
    phone_tokenized = models.CharField(max_length=50, blank=True, null=True)
    customer_capped_limit = models.IntegerField(blank=True, null=True)
    is_use_whatsapp = models.NullBooleanField()
    is_use_telegram = models.NullBooleanField()

    objects = CustomerManager()

    class Meta(object):
        db_table = 'customer'

    def __str__(self):
        """Visual identification"""
        visual_id = self.email
        if self.fullname != '':
            visual_id = "%s (%s)" % (visual_id, self.fullname)
        return visual_id

    @property
    def wallet_balance_available(self):
        qs = self.wallet_history.get_queryset().cashback_earned_available().aggregate(
            Sum('cashback_earned__current_balance')
        )
        return qs['cashback_earned__current_balance__sum'] or 0

    @property
    def wallet_balance_accruing(self):
        wallet_history_last = self.wallet_history.order_by('cdate').last()
        if wallet_history_last:
            return wallet_history_last.wallet_balance_accruing
        else:
            return 0

    @property
    def is_loc_shown(self):
        app = self.application_set.filter(line_of_credit__isnull=False).last()
        if app:
            last_statement = app.line_of_credit.lineofcreditstatement_set.last()
            if last_statement.billing_amount > 0:
                return True
        return False

    @property
    def is_repeated(self):
        loan = Loan.objects.filter(customer=self.id).paid_off().first()
        return True if loan else False

    @property
    def split_name(self):
        word_count = len(self.fullname.split())
        if word_count > 1:
            firstname = self.fullname.rsplit(' ', 1)[0].title()
            lastname = self.fullname.split()[-1].title()
        else:
            firstname = self.fullname.title()
            lastname = ''
        return firstname, lastname

    @property
    def last_application(self):
        if hasattr(self, "prefetched_applications"):
            return self.prefetched_applications[0] if self.prefetched_applications else None
        return self.application_set.regular_not_deletes().last()

    @property
    def active_applications(self):
        if hasattr(self, "prefetched_active_applications"):
            return self.prefetched_active_applications[0] if self.prefetched_active_applications else None
        return self.application_set.filter(application_status=190).first()

    @property
    def get_active_or_last_application(self):
        from juloserver.customer_module.services.pii_vault import detokenize_sync_object_model
        from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

        active_application = self.active_applications
        if active_application:
            application = active_application

        else:
            application = self.last_application

        detokenized_cust = detokenize_sync_object_model(
            PiiSource.APPLICATION, PiiVaultDataType.PRIMARY, [application]
        )[0]

        return detokenized_cust

    @property
    def last_month_salary(self):
        # use in bpjs direct
        prev_month = self.cdate.replace(day=1) - timedelta(days=1)
        return prev_month.strftime("%m/%Y")

    def get_last_loan_active_mtl(self):
        return self.loan_set.filter(
            loan_status__gte=LoanStatusCodes.CURRENT,
            loan_status__lt=LoanStatusCodes.PAID_OFF,
            application__product_line__product_line_code__in=ProductLineCodes.mtl()
        ).last()

    def change_wallet_balance(
        self,
        change_accruing,
        change_available,
        reason,
        payment=None,
        sepulsa_transaction=None,
        event_date=None,
        cashback_transfer_transaction=None,
        account_payment=None,
        loan=None,
        payment_event=None,
        is_eligible_new_cashback=False,
        counter=0,
        new_cashback_percentage=0,
        reversal_counter=False,
    ):
        from juloserver.cashback.services import (
            update_customer_cashback_balance,
            update_wallet_earned,
        )
        from juloserver.customer_module.models import CashbackBalance
        from juloserver.julo.services import record_data_for_cashback_new_scheme
        from juloserver.julo_starter.services.services import (
            determine_application_for_credit_info,
        )
        from juloserver.moengage.services.use_cases import (
            send_user_attributes_to_moengage_for_realtime_basis,
        )

        logger.info({
            "action": "change_wallet_balance",
            "customer": self,
            "change_accruing": change_accruing,
            "change_available": change_available,
            "reason": reason,
            "sepulsa_transaction": sepulsa_transaction,
            "event_date": event_date,
            "cashback_transfer_transaction": cashback_transfer_transaction,
            "account_payment": account_payment,
            "loan": loan
        })

        # valid_reasons = [x[0] for x in CustomerWalletHistory.CREDIT_CHANGE_REASONS]
        # if reason not in valid_reasons:
        #     raise JuloException('Customer.change_wallet_balance: Invalid change reason')
        loan = loan if loan else self.loan_set.order_by('cdate').last()
        cashback_service = get_cashback_service()
        change_accruing, wallet_delayed_amount, reason = cashback_service.check_cashback_earned(
            loan, reason, change_accruing, payment)
        wallet_balance_accruing_old = 0
        wallet_balance_available_old = 0
        total_cashback_earned = self.wallet_balance_available
        with transaction.atomic():
            # order by cdate is temp solution for DB slow anomaly
            Customer.objects.select_for_update().get(id=self.id)
            last_wallet_history = CustomerWalletHistory.objects.select_for_update().filter(
                customer=self, latest_flag=True
            ).last()
            if last_wallet_history:
                wallet_balance_accruing_old = last_wallet_history.wallet_balance_accruing
                wallet_balance_available_old = last_wallet_history.wallet_balance_available
            wallet_balance_accruing = wallet_balance_accruing_old + change_accruing
            wallet_balance_available = wallet_balance_available_old + change_available

            if total_cashback_earned > wallet_balance_available_old:
                logger.info(
                    {
                        'action': 'change_wallet_balance_negative_cashback',
                        'customer': self,
                        'reason': reason,
                        'message': 'total_cashback_earned > wallet_balance_available_old',
                        'total_cashback_earned': total_cashback_earned,
                        'wallet_balance_available_old': wallet_balance_available_old,
                    }
                )
            if wallet_balance_available < 0:
                logger.info(
                    {
                        'action': 'change_wallet_balance_negative_cashback',
                        'customer': self,
                        'reason': reason,
                        'wallet_balance_available': wallet_balance_available,
                        'wallet_balance_accruing': wallet_balance_accruing,
                    }
                )
            CustomerWalletHistory.objects.filter(
                customer=self, latest_flag=True
            ).update(latest_flag=False)

            loan = payment.loan if payment else loan
            cashback_balance = CashbackBalance.objects.filter(
                customer=self
            ).last()
            new_wallet_history = CustomerWalletHistory.objects.create(
                customer=self,
                application=determine_application_for_credit_info(self),
                loan=loan,
                payment=payment,
                account_payment=account_payment,
                sepulsa_transaction=sepulsa_transaction,
                cashback_transfer_transaction=cashback_transfer_transaction,
                wallet_balance_accruing=wallet_balance_accruing,
                wallet_balance_available=wallet_balance_available,
                wallet_balance_accruing_old=wallet_balance_accruing_old,
                wallet_balance_available_old=wallet_balance_available_old,
                wallet_delayed_amount=wallet_delayed_amount,
                change_reason=reason,
                latest_flag=True,
                event_date=event_date,
                cashback_balance=cashback_balance,
                payment_event=payment_event
            )
            if is_eligible_new_cashback:
                reason = NewCashbackReason.PAID_AFTER_TERMS
                if counter > 0:
                    reason = NewCashbackReason.PAID_BEFORE_TERMS
                if reversal_counter:
                    reason = NewCashbackReason.PAYMENT_REVERSE
                record_data_for_cashback_new_scheme(
                    payment, new_wallet_history, counter, reason, new_cashback_percentage
                )
            update_wallet_earned(new_wallet_history, change_available)
            update_customer_cashback_balance(self)

        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_for_realtime_basis.delay(
                customer_id=self.id,
                update_field=UpdateFields.CASHBACK,
            )
        )
        logger.info({
            'info': "Changing wallet balance for customer {}".format(self.id),
            'wallet_accruing': self.wallet_balance_accruing,
            'wallet_available': self.wallet_balance_available,
            'change_accruing': change_accruing,
            'change_available': change_available,
            'reason': reason})
        return new_wallet_history

    def has_emailkey_expired(self):
        tz_info = self.email_key_exp_date.tzinfo
        return self.email_key_exp_date < datetime.now(tz_info)

    def has_resetkey_expired(self):
        tz_info = self.reset_password_exp_date.tzinfo
        return self.reset_password_exp_date < datetime.now(tz_info)

    def set_scheduling_reapply(self, application, reason):
        expired_date = None
        today = timezone.localtime(timezone.now())

        three_months_reason = self.REAPPLY_THREE_MONTHS_REASON
        half_a_year_reason = self.REAPPLY_HALF_A_YEAR_REASON
        one_year_reason = self.REAPPLY_ONE_YEAR_REASON
        reapply_not_allowed = self.REAPPLY_NOT_ALLOWED_REASON
        custom_reapply = self.REAPPLY_CUSTOM

        if application.is_julo_one or application.is_julo_one_ios():
            one_months_reason = JuloOne135Related.REAPPLY_AFTER_ONE_MONTHS_REASON_J1
            three_months_reason += JuloOne135Related.REAPPLY_AFTER_THREE_MONTHS_REASON_J1
            half_a_year_reason += JuloOne135Related.REAPPLY_AFTER_HALF_A_YEAR_REASON_J1
            one_year_reason += JuloOne135Related.REAPPLY_AFTER_ONE_YEAR_REASON_J1
            reapply_not_allowed += JuloOne135Related.REAPPLY_NOT_ALLOWED_REASON_J1

            if any(word in reason for word in one_months_reason):
                expired_date = today + relativedelta(months=1)

        if any(word in reason for word in three_months_reason):
            expired_date = today + relativedelta(months=+3)

        if any(word in reason for word in half_a_year_reason):
            expired_date = today + relativedelta(months=+6)

        if any(word in reason for word in one_year_reason):
            expired_date = today + relativedelta(years=+1)

        if any(word in reason for word in custom_reapply):
            born = application.dob
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            if age < 18:
                expired_date = datetime.combine(born + relativedelta(years=+18), datetime.min.time()).replace(
                    tzinfo=timezone.localtime(timezone.now()).tzinfo)

        if any(word in reason for word in reapply_not_allowed):
            self.disabled_reapply_date = today

        if expired_date:
            self.disabled_reapply_date = today
            self.can_reapply_date = expired_date

    def process_can_reapply(self, loan):
        can_reapply = False
        can_skip_pv_dv_process = False
        reapply_date = None

        if loan.loan_status.status_code != LoanStatusCodes.PAID_OFF:
            return can_reapply, can_skip_pv_dv_process, reapply_date

        application = loan.application
        payments = loan.payment_set.all().exclude(is_restructured=True).order_by('payment_number')
        count_payment = len(payments)
        count_payment_ontime = 0
        count_payment_grace = 0
        count_payment_late_lte_30days = 0
        count_payment_late_gt_30days = 0

        # grab partner stuff
        if application and application.partner is not None and application.partner.name in\
           ['grab', 'grabfood']:
            return can_reapply, can_skip_pv_dv_process, reapply_date

        # get count payment status
        for payment in payments:
            payment_stt_code = payment.payment_status_id
            if payment_stt_code == PaymentStatusCodes.PAID_LATE:
                range_day_paid = (payment.paid_date - payment.due_date).days
                if range_day_paid <= 30:
                    count_payment_late_lte_30days += 1
                else:
                    count_payment_late_gt_30days += 1
            elif payment_stt_code == PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD or \
                    payment_stt_code == PaymentStatusCodes.PARTIAL_RESTRUCTURED:
                count_payment_grace += 1
            elif payment_stt_code == PaymentStatusCodes.PAID_ON_TIME:
                count_payment_ontime += 1
            else:
                raise JuloException('Cant not update can_reapply field, '
                                    + 'all payments need to be paid off first')
        # use (a+b-1)/b to round up in python
        if count_payment_ontime + count_payment_grace >= old_div((count_payment + 1), 2) \
                and count_payment_late_gt_30days == 0:
            can_reapply = True

            # check skip pv and dv
            if count_payment_ontime == count_payment:
                can_skip_pv_dv_process = True
            elif count_payment_grace == 1 and count_payment_late_lte_30days == 0:
                can_skip_pv_dv_process = True
        else:
            today = timezone.localtime(timezone.now())
            reapply_date = today.replace(today.year + 1)  # block reapply for 1 year

        return can_reapply, can_skip_pv_dv_process, reapply_date

    @property
    def last_gcm_id(self):
        device_query = self.device_set.all()
        return device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()

    @property
    def account(self):
        return self.account_set.last()

    @property
    def remaining_reapply_date(self):
        if self.can_reapply_date:
            today = timezone.localtime(timezone.now())
            delta_time = self.can_reapply_date - today
            total_month = math.ceil(delta_time.days / 30.0)
            return int(total_month)
        return None

    @property
    def reapply_msg(self):
        if self.remaining_reapply_date:
            return 'Silahkan ajukan kembali setelah %s bulan.' % self.remaining_reapply_date

        return ''

    @property
    def is_cashback_freeze(self):
        account = self.account
        is_cashback_freeze = False
        if account:
            if account.status_id == AccountConstant.STATUS_CODE.suspended:
                is_cashback_freeze = True
        else:
            loan = self.loan_set.get_queryset().all_active_mtl().last()
            if loan:
                oldest_unpaid_payment = loan.get_oldest_unpaid_payment()
                if oldest_unpaid_payment and \
                        oldest_unpaid_payment.due_late_days >= 5:
                    is_cashback_freeze = True

        return is_cashback_freeze

    @property
    def primary_va_name(self):
        from juloserver.julo.services2.payment_method import (
            get_main_payment_method,
        )

        payment_method = get_main_payment_method(self)
        if payment_method:
            return payment_method.payment_method_name
        return '-'

    @property
    def primary_va_number(self):
        from juloserver.julo.services2.payment_method import (
            get_main_payment_method,
        )

        payment_method = get_main_payment_method(self)
        if payment_method:
            return payment_method.virtual_account
        return '-'

    @property
    def bpk_ibu(self):
        application = self.application_set.last()
        if application.gender == 'Wanita':
            return 'Ibu '
        if application.gender == 'Pria':
            return 'Bpk '

    @property
    def bapak_ibu(self):
        application = self.application_set.last()
        if application.gender == 'Wanita':
            return 'Ibu '
        if application.gender == 'Pria':
            return 'Bapak '

    @property
    def first_name_only(self):
        if self.fullname:
            return self.fullname.split()[0].title()

    @property
    def fullname_with_short_title(self):
        application = self.application_set.last()
        from juloserver.grab.utils import get_customer_name_with_title
        return get_customer_name_with_title(application.gender, self.fullname)

    @property
    def generated_customer_xid(self):
        if self.customer_xid:
            return self.customer_xid

        customer = Customer.objects.generate_and_update_customer_xid(self)
        return customer.customer_xid

    def generate_xid(self):
        if self.customer_xid is not None:
            return
        rand_sys = SystemRandom()
        self.customer_xid = rand_sys.randrange(10**13, 10**14 - 1)


    @property
    def last_application_id(self):
        return self.last_application.id if self.last_application else ""

    @property
    def get_nik(self):
        from juloserver.customer_module.services.pii_vault import detokenize_sync_object_model
        from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

        if self.nik:
            detokenized_cust = detokenize_sync_object_model(
                PiiSource.CUSTOMER, PiiVaultDataType.PRIMARY, [self]
            )[0]
            return detokenized_cust.nik

        applications = self.application_set.all()
        if not applications.exists():
            return None
        for application in applications:
            if application.ktp:
                detokenized_app = detokenize_sync_object_model(
                    PiiSource.APPLICATION, PiiVaultDataType.PRIMARY, [application]
                )[0]
                return detokenized_app.ktp

    @property
    def get_email(self):
        from juloserver.customer_module.services.pii_vault import detokenize_sync_object_model
        from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

        if self.email:
            detokenized_cust = detokenize_sync_object_model(
                PiiSource.CUSTOMER, PiiVaultDataType.PRIMARY, [self]
            )[0]
            return detokenized_cust.email

        applications = self.application_set.all()
        if not applications.exists():
            return None
        for application in applications:
            if application.email:
                detokenized_app = detokenize_sync_object_model(
                    PiiSource.APPLICATION, PiiVaultDataType.PRIMARY, [application]
                )[0]
                return detokenized_app.email

    @property
    def get_phone(self):
        from juloserver.customer_module.services.pii_vault import detokenize_sync_object_model
        from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

        if self.phone:
            detokenized_cust = detokenize_sync_object_model(
                PiiSource.CUSTOMER, PiiVaultDataType.PRIMARY, [self]
            )[0]
            return detokenized_cust.phone

        applications = self.application_set.all()
        if not applications.exists():
            return None
        for application in applications:
            if application.mobile_phone_1:
                detokenized_app = detokenize_sync_object_model(
                    PiiSource.APPLICATION, PiiVaultDataType.PRIMARY, [application]
                )[0]
                return detokenized_app.mobile_phone_1

    @property
    def get_fullname(self):
        from juloserver.customer_module.services.pii_vault import detokenize_sync_object_model
        from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

        if self.fullname:
            detokenized_cust = detokenize_sync_object_model(
                PiiSource.CUSTOMER, PiiVaultDataType.PRIMARY, [self]
            )[0]
            return detokenized_cust.fullname

    @property
    def is_julocare_eligible(self):
        app = self.account.get_active_application()
        return app.product_line_code in [ProductLineCodes.J1, ProductLineCodes.JULO_STARTER]

    @property
    def full_address(self):
        address = self.address_street_num
        if address:
            from juloserver.julo.utils import validation_of_roman_numerals
            address = validation_of_roman_numerals(address)
        addrs = ", ".join(
            [
                _f
                for _f in [
                    address,
                    self.address_kelurahan,
                    self.address_kecamatan,
                    self.address_kabupaten,
                    self.address_provinsi,
                    self.address_kodepos,
                ]
                if _f
            ]
        )
        return addrs

# @receiver(signals.pre_save, sender=Customer)
def send_gcm_after_email_verified(
        sender, instance=None, **kwargs):
    """
    send notification when user confirmed email address.
    """
    customer_to_save = instance  # the data to be saved in DB
    if customer_to_save.is_email_verified:
        # Get the data already saved in DB
        customer_saved = Customer.objects.get_or_none(id=customer_to_save.id)
        if not customer_saved.is_email_verified:
            # When is_email_verified is being set to true
            # Send notification
            device = (
                Device.objects
                      .filter(customer=customer_saved)
                      .order_by('-udate')
                      .first()
            )
            if device is not None:
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.inform_email_verified(device.gcm_reg_id)


class MobileOperatorManager(GetInstanceMixin, JuloModelManager):
    pass


class MobileOperator(TimeStampedModel):
    id = models.AutoField(db_column='mobile_operator_id', primary_key=True)
    name = models.CharField(max_length=100)
    initial_numbers = ArrayField(models.CharField(max_length=10), blank=True, null=True)
    is_active = models.BooleanField(default=False)

    objects = MobileOperatorManager()

    class Meta(object):
        db_table = 'mobile_operator'


class SepulsaProductManager(GetInstanceMixin, JuloModelManager):
    pass


class SepulsaProduct(TimeStampedModel):
    id = models.AutoField(db_column='sepulsa_product_id', primary_key=True)
    operator = models.ForeignKey(
        'MobileOperator', models.DO_NOTHING, db_column='mobile_operator_id', blank=True, null=True)
    product_id = models.CharField(max_length=100, blank=True, null=True)
    product_name = models.CharField(max_length=200, blank=True, null=True)
    product_nominal = models.BigIntegerField(blank=True, null=True)
    product_label = models.CharField(max_length=200, blank=True, null=True)
    product_desc = models.CharField(max_length=500, blank=True, null=True)
    type = models.CharField(max_length=50, blank=True, null=True)
    category = models.CharField(max_length=50, blank=True, null=True)
    partner_price = models.BigIntegerField(blank=True, null=True)
    customer_price = models.BigIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=False)
    customer_price_regular = models.BigIntegerField(null=True, blank=True)
    is_not_blocked = models.BooleanField(default=False)
    admin_fee = models.BigIntegerField(blank=True, null=True)
    service_fee = models.BigIntegerField(blank=True, null=True)
    collection_fee = models.BigIntegerField(blank=True, null=True)

    objects = SepulsaProductManager()

    class Meta(object):
        db_table = 'sepulsa_product'

    def title_product(self):
        if self.type == 'electricity' and self.category == 'prepaid':
            return 'PLN Prabayar'
        elif self.type == 'mobile' and self.category == 'pulsa':
            return 'Pulsa'
        elif self.type == 'mobile' and self.category == 'paket_data':
            return 'Paket Data'
        else:
            return ''

    @property
    def ewallet_logo(self):
        if self.type != SepulsaProductType.EWALLET and not self.category:
            return

        return settings.EWALLET_LOGO_STATIC_FILE_PATH + '{}.png'.format(self.category.lower())

    @property
    def sepulsa_id(self) -> int:
        return self.id


class SepulsaTransactionManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class SepulsaTransaction(PIIVaultModel):
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    TRANSACTION_STATUS_CHOICES = (
        ('success', 'Success'),
        ('pending', 'Pending'),
        ('failed', 'Failed'),
        ('initiate', 'Initiate'))
    id = models.AutoField(db_column='sepulsa_transaction_id', primary_key=True)
    product = models.ForeignKey(
        'SepulsaProduct', models.DO_NOTHING, db_column='sepulsa_product_id')
    customer = models.ForeignKey(
        'Customer', models.DO_NOTHING, db_column='customer_id')
    line_of_credit_transaction = models.ForeignKey(
        'line_of_credit.LineOfCreditTransaction',
        models.DO_NOTHING, db_column='line_of_credit_transaction_id', blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    transaction_code = models.CharField(max_length=100, blank=True, null=True)
    transaction_status = models.CharField(
        choices=TRANSACTION_STATUS_CHOICES, max_length=50, blank=True, null=True)
    is_order_created = models.NullBooleanField()
    transaction_success_date = models.DateTimeField(blank=True, null=True)
    serial_number = models.CharField(max_length=100, blank=True, null=True)
    response_code = models.CharField(max_length=50, blank=True, null=True)
    customer_number = models.CharField(max_length=100, blank=True, null=True)
    account_name = models.CharField(max_length=50, blank=True, null=True)
    transaction_token = models.CharField(max_length=50, blank=True, null=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', null=True, blank=True)
    partner_price = models.BigIntegerField(null=True, blank=True)
    customer_price = models.BigIntegerField(null=True, blank=True)
    customer_price_regular = models.BigIntegerField(null=True, blank=True)
    retry_times = models.IntegerField(null=True, blank=True)
    paid_period = models.IntegerField(blank=True, null=True)
    category = models.TextField(blank=True, null=True)
    customer_amount = models.BigIntegerField(blank=True, null=True)
    partner_amount = models.BigIntegerField(blank=True, null=True)
    admin_fee = models.BigIntegerField(blank=True, null=True)
    service_fee = models.BigIntegerField(blank=True, null=True)
    collection_fee = models.BigIntegerField(blank=True, null=True)
    order_id = models.TextField(blank=True, null=True)
    phone_number_tokenized = models.CharField(max_length=225, null=True, blank=True)

    objects = SepulsaTransactionManager()

    class Meta(object):
        db_table = 'sepulsa_transaction'

    @property
    def is_not_auto_retry_product(self):
        if self.category in SepulsaProductCategory.not_auto_retry_category():
            return True

        return False

    @property
    def is_instant_transfer_to_dana(self):
        product = self.product
        return (product and product.type == SepulsaProductType.E_WALLET_OPEN_PAYMENT and
                product.category == SepulsaProductCategory.DANA)


class SepulsaTransactionHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class SepulsaTransactionHistory(TimeStampedModel):
    id = models.AutoField(db_column='sepulsa_transaction_history_id', primary_key=True)
    sepulsa_transaction = models.ForeignKey(
        'SepulsaTransaction', models.DO_NOTHING, db_column='sepulsa_transaction_id')
    before_transaction_status = models.NullBooleanField()
    before_transaction_success_date = models.DateTimeField(blank=True, null=True)
    before_response_code = models.CharField(max_length=50, blank=True, null=True)
    after_transaction_status = models.NullBooleanField()
    after_transaction_success_date = models.DateTimeField(blank=True, null=True)
    after_response_code = models.CharField(max_length=50, blank=True, null=True)
    transaction_type = models.CharField(max_length=50, blank=True, null=True)
    request_payload = models.TextField(blank=True, null=True)
    objects = SepulsaTransactionHistoryManager()

    class Meta(object):
        db_table = 'sepulsa_transaction_history'


class CashbackXenditTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class CashbackXenditTransaction(TimeStampedModel):
    id = models.AutoField(db_column='cashback_xendit_transaction_id',
                          primary_key=True)
    customer = models.ForeignKey(Customer,
                                 models.DO_NOTHING,
                                 db_column='customer_id')
    application = models.ForeignKey(Application,
                                    models.DO_NOTHING,
                                    db_column='application_id')
    bank_name = models.CharField(max_length=100)
    bank_code = models.CharField(max_length=50, null=True)
    bank_number = models.CharField(max_length=50)
    name_in_bank = models.CharField(max_length=250)
    validation_status = models.CharField(max_length=50, null=True)
    validation_id = models.CharField(max_length=250, null=True)
    validated_name = models.CharField(max_length=250, null=True)
    transfer_status = models.CharField(max_length=50, null=True)
    transfer_id = models.CharField(max_length=250, null=True)
    failure_code = models.CharField(max_length=250, null=True)
    failure_message = models.TextField(null=True)
    transfer_amount = models.BigIntegerField()
    redeem_amount = models.BigIntegerField()
    external_id = models.CharField(max_length=250, blank=True, null=True)
    retry_times = models.IntegerField(default=0, blank=True, null=True)

    objects = CashbackXenditTransactionManager()

    class Meta(object):
        db_table = 'cashback_xendit_transaction'


class CashbackTransferTransactionManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class CashbackTransferTransaction(PIIVaultModel):
    PII_FIELDS = ['name_in_bank']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'utilization_pii_vault'

    id = models.AutoField(db_column='cashback_transfer_transaction_id',
                          primary_key=True)
    customer = models.ForeignKey(Customer,
                                 models.DO_NOTHING,
                                 db_column='customer_id')
    application = models.ForeignKey(Application,
                                    models.DO_NOTHING,
                                    db_column='application_id')
    bank_name = models.CharField(max_length=100)
    bank_code = models.CharField(max_length=50, null=True)
    bank_number = models.CharField(max_length=50)
    name_in_bank = models.CharField(max_length=250)
    validation_status = models.CharField(max_length=50, null=True)
    validation_id = models.CharField(max_length=250, null=True)
    validated_name = models.CharField(max_length=250, null=True)
    transfer_status = models.CharField(max_length=50, null=True)
    transfer_id = models.CharField(max_length=250, null=True)
    failure_code = models.CharField(max_length=250, null=True)
    failure_message = models.TextField(null=True)
    transfer_amount = models.BigIntegerField()
    redeem_amount = models.BigIntegerField()
    external_id = models.CharField(max_length=250, blank=True, null=True)
    retry_times = models.IntegerField(default=0, blank=True, null=True)
    partner_transfer = models.CharField(max_length=20, blank=True, null=True)
    # latest = models.BooleanField(default=False)
    fund_transfer_ts = models.DateTimeField(null=True)
    name_in_bank_tokenized = models.TextField(blank=True, null=True)

    objects = CashbackTransferTransactionManager()

    class Meta(object):
        db_table = 'cashback_transfer_transaction'


class CustomerWalletHistoryQuerySet(CustomQuerySet):

    def cashback_earned_available(self):
        return self.filter(
            cashback_earned__isnull=False,
            cashback_earned__verified=True,
            cashback_earned__current_balance__gt=0,
        )

    def total_cashback_earned_available(self):
        qs = self.cashback_earned_available().aggregate(
            Sum('cashback_earned__current_balance')
        )
        return qs['cashback_earned__current_balance__sum'] or 0

    def cashback_earned_available_to_date(self, to_date):
        return self.cashback_earned_available().filter(
            cashback_earned__expired_on_date__lte=to_date
        )

    def total_cashback_earned_available_to_date(self, to_date):
        qs = self.cashback_earned_available_to_date(to_date).aggregate(
            Sum('cashback_earned__current_balance')
        )
        return qs['cashback_earned__current_balance__sum'] or 0


class CustomerWalletHistoryManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return CustomerWalletHistoryQuerySet(self.model)


class CustomerWalletHistory(TimeStampedModel):
    CREDIT_CHANGE_REASONS = (('loan_initial', 'Earned on Loan Start'),
                             ('loan_paid_off', 'Earned from Loan'),
                             ('payment_on_time', 'Payment on Time'),
                             ('paid_back_to_customer', 'Paid back to Customer'),
                             (CashbackChangeReason.USED_ON_PAYMENT, 'Used on Payment'),
                             (CashbackChangeReason.CASHBACK_OVER_PAID, 'Cashback Over Paid'),
                             ('used_buy_pulsa', 'Used buy pulsa'),
                             ('refunded_buy_pulsa', 'Refunded buy pulsa'),
                             ('used_transfer', 'Used Transfer'),
                             ('refunded_transfer', 'Refunded Transfer'),
                             ('agent_finance_adjustment', 'Agent Finance Adjustment'),
                             ('gopay_transfer', 'Transfer GoPay'),
                             ('refunded_transfer_gopay', 'Refunded Transfer GoPay'),
                             )
    customer = models.ForeignKey('Customer',
                                 models.DO_NOTHING,
                                 db_column='customer_id',
                                 related_name='wallet_history')
    application = models.ForeignKey(Application, models.DO_NOTHING,
                                    db_column='application_id', null=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', null=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING,
                                db_column='payment_id', blank=True, null=True)
    sepulsa_transaction = models.ForeignKey(
        SepulsaTransaction, models.DO_NOTHING,
        db_column='sepulsa_transaction_id',
        blank=True, null=True)
    cashback_xendit_transaction = models.ForeignKey(
        CashbackXenditTransaction, models.DO_NOTHING,
        db_column='cashback_xendit_transaction_id',
        blank=True, null=True)
    cashback_transfer_transaction = models.ForeignKey(
        CashbackTransferTransaction, models.DO_NOTHING,
        db_column='cashback_transfer_transaction_id',
        blank=True, null=True)
    wallet_balance_accruing = models.BigIntegerField(default=0)
    wallet_balance_available = models.BigIntegerField(default=0)
    wallet_balance_accruing_old = models.BigIntegerField(default=0)
    wallet_balance_available_old = models.BigIntegerField(default=0)
    wallet_delayed_amount = models.BigIntegerField(default=0)
    change_reason = models.CharField(choices=CREDIT_CHANGE_REASONS, max_length=50)
    latest_flag = models.BooleanField(default=False)
    event_date = models.DateField(blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING, db_column='account_payment_id', blank=True, null=True)
    cashback_balance = models.ForeignKey(
        'customer_module.CashbackBalance', db_column='cashback_balance_id', blank=True, null=True
    )
    cashback_earned = models.OneToOneField('cashback.CashbackEarned',
                                           models.DO_NOTHING,
                                           db_column='cashback_earned_id',
                                           blank=True,
                                           null=True)
    payment_event = models.ForeignKey(PaymentEvent,
                                      models.DO_NOTHING, db_column='payment_event_id', blank=True, null=True)

    objects = CustomerWalletHistoryManager()

    class Meta(object):
        db_table = 'customer_wallet_history'


class Transaction(TimeStampedModel):
    id = models.AutoField(db_column='transaction_id', primary_key=True)

    julo_bank_name = models.CharField(max_length=250, blank=True)
    julo_bank_branch = models.CharField(max_length=100, blank=True)
    julo_bank_account_number = models.CharField(
        max_length=50, blank=True,
        validators=[
            RegexValidator(
                regex='^[0-9]+$',
                message='Bank account number has to be numeric digits')
        ]
    )
    transaction_ts = models.DateTimeField()
    transaction_type = models.CharField(max_length=50)
    transaction_amount = models.BigIntegerField()
    transaction_note = models.TextField(blank=True)

    class Meta(object):
        db_table = 'transaction'


class ApplicationFieldManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationField(TimeStampedModel):
    """
    """

    id = models.AutoField(db_column='application_field_id', primary_key=True)

    field_name = models.CharField(null=False, blank=False, max_length=50)
    edit_status = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    description = models.CharField(max_length=50, default="-inital data-")

    objects = ApplicationFieldManager()

    class Meta(object):
        db_table = 'application_field'

    def __str__(self):
        """Visual identification"""
        return "%s -> %s" % (self.id, self.field_name)


class ApplicationDataCheck(TimeStampedModel):
    """
    check_type :
    1 : means boolean, then check value is_okay
    2 : means text, then check text_value
    3 : means option value, then check number_value
    4 : means money value, then check number_value
    automation :
    0 : need to be automate
    1 : automation already take in place
    2 : manual checker
    """

    id = models.AutoField(db_column='data_check_id', primary_key=True)
    application_id = models.BigIntegerField(null=False, blank=False, db_column='application_id')
    application_field_id = models.BigIntegerField(
        null=True, blank=True, db_column='application_field_id'
    )
    automation = models.SmallIntegerField(null=True, blank=True)
    prioritize = models.SmallIntegerField(null=True, blank=True)
    sequence = models.SmallIntegerField(null=True, blank=True)
    data_to_check = models.CharField(null=False, blank=False, max_length=100)
    description = models.CharField(max_length=200)

    check_type = models.SmallIntegerField(null=True, blank=True)
    is_okay = models.NullBooleanField()
    text_value = models.CharField(null=True, blank=True,
                                  max_length=150)
    number_value = models.BigIntegerField(null=True, blank=True)

    changed_by = CurrentUserField(related_name="user_app_verification_check")

    class Meta(object):
        db_table = 'application_data_check'
        ordering = ['application_id', 'sequence']
        managed = False

    def __str__(self):
        """Visual identification"""
        return "%s -> %s" % (self.data_to_check, self.description)


class DeviceIpHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class DeviceIpHistory(TimeStampedModel):

    id = models.AutoField(db_column='device_ip_history_id', primary_key=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')
    device = models.ForeignKey(
        Device, models.DO_NOTHING, db_column='device_id', blank=True, null=True)

    ip_address = models.GenericIPAddressField()
    count = models.PositiveIntegerField()
    path = models.CharField(max_length=200, blank=True, null=True)
    objects = DeviceIpHistoryManager()

    class Meta(object):
        db_table = 'device_ip_history'
        verbose_name_plural = "Device IP History"


class PartnerCleanse(models.Model):
    """
    Abstract model class that will replace characters in char and text fields before save.
    \n = " "
    \r = ""
    <non ascii> = "?"
    """

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        for key, val in list(self.__dict__.items()):
            if isinstance(val, basestring):
                replaced_str = val.replace('\n', ' ').replace('\r', '')
                replaced_str = re.sub(r'[^\x20-\x7F]+', '?', replaced_str)
                setattr(self, key, replaced_str)

        return models.Model.save(
            self, force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields)

    class Meta(object):
        abstract = True


class PartnerReferral(TimeStampedModel, PartnerCleanse):
    GENDER_CHOICES = (
        ('Pria', 'Pria'),
        ('Wanita', 'Wanita'))
    HOME_STATUS_CHOICES = (
        ('Kontrak', 'Kontrak'),
        ('Kos', 'Kos'),
        ('Milik orang tua', 'Milik orang tua'),
        ('Milik keluarga', 'Milik keluarga'),
        ('Milik sendiri, lunas', 'Milik sendiri, lunas'),
        ('Milik sendiri, mencicil', 'Milik sendiri, mencicil'),
        ('Lainnya', 'Lainnya'))
    MARITAL_STATUS_CHOICES = (
        ('Lajang', 'Lajang'),
        ('Menikah', 'Menikah'),
        ('Cerai', 'Cerai'),
        ('Janda / duda', 'Janda / duda'))
    KIN_GENDER_CHOICES = (
        ('Pria', 'Pria'),
        ('Wanita', 'Wanita'))
    KIN_RELATIONSHIP_CHOICES = (
        ('Orang tua', 'Orang tua'),
        ('Saudara kandung', 'Saudara kandung'),
        ('Famili lainnya', 'Famili lainnya'))
    JOB_TYPE_CHOICES = (
        ('Pegawai swasta', 'Pegawai swasta'),
        ('Pegawai negeri', 'Pegawai negeri'),
        ('Pengusaha', 'Pengusaha'),
        ('Freelance', 'Freelance'),
        ('Pekerja rumah tangga', 'Pekerja rumah tangga'),
        ('Lainnya', 'Lainnya'),
        ('Staf rumah tangga', 'Staf rumah tangga'),
        ('Ibu rumah tangga', 'Ibu rumah tangga'),
        ('Mahasiswa', 'Mahasiswa'),
        ('Tidak bekerja', 'Tidak bekerja'))
    LAST_EDUCATION_CHOICES = (
        ('SD', 'SD'),
        ('SLTP', 'SLTP'),
        ('SLTA', 'SLTA'),
        ('Diploma', 'Diploma'),
        ('S1', 'S1'),
        ('S2', 'S2'),
        ('S3', 'S3'))
    VEHICLE_TYPE_CHOICES = (
        ('Sepeda motor', 'Sepeda motor'),
        ('Mobil', 'Mobil'),
        ('Lainnya', 'Lainnya'),
        ('Tidak punya', 'Tidak punya'))
    VEHICLE_OWNERSHIP_CHOICES = (
        ('Lunas', 'Lunas'),
        ('Mencicil', 'Mencicil'),
        ('Diagunkan', 'Diagunkan'),
        ('Lainnya', 'Lainnya'),
        ('Tidak punya', 'Tidak punya'))
    id = models.AutoField(db_column='partner_referral_id', primary_key=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING,
        db_column='customer_id', blank=True, null=True)

    partner = models.ForeignKey(
        'Partner', models.DO_NOTHING, db_column='partner_id',
        blank=True, null=True)

    product = models.ForeignKey(
        'ProductLookup', models.DO_NOTHING, db_column='product_code',
        blank=True, null=True)

    # Partner customer identity (to be populated to the application form)

    cust_fullname = models.CharField(null=True, blank=True, max_length=100)
    cust_dob = models.DateField(null=True, blank=True)
    cust_nik = models.CharField(
        null=True,
        blank=True,
        max_length=16,
        validators=[
            RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ],
        db_index=True
    )
    cust_npwp = models.CharField(
        null=True,
        blank=True,
        max_length=15,
        validators=[
            RegexValidator(
                regex='^[0-9]{15}$',
                message='NPWP has to be 15 numeric digits')
        ]
    )
    cust_email = EmailLowerCaseField(null=True, blank=True, db_index=True)

    mobile_phone = PhoneNumberField(null=True, blank=True, db_index=True)

    # Account details

    account_tenure_mth = models.PositiveIntegerField(null=True, blank=True)
    past_gmv = models.BigIntegerField(null=True, blank=True)
    past_purchase_count = models.PositiveIntegerField(null=True, blank=True)
    partner_account_id = models.CharField(null=True, blank=True, max_length=50)
    kyc_indicator = models.NullBooleanField()
    is_android_user = models.NullBooleanField()
    pre_exist = models.NullBooleanField()
    loan_amount_request = models.BigIntegerField(blank=True, null=True)
    loan_duration_request = models.IntegerField(blank=True, null=True)
    loan_purpose = models.CharField("Tujuan pinjaman", max_length=100, blank=True, null=True)
    loan_purpose_desc = models.TextField(
        blank=True, null=True,
        validators=[
            RegexValidator(
                regex='^[ -~]+$',
                message='characters not allowed')
        ]
    )
    marketing_source = models.CharField("Dari mana tahu",
                                        max_length=100,
                                        validators=[ascii_validator], blank=True, null=True)
    payday = models.IntegerField(
        blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(28)])
    referral_code = models.CharField(max_length=20, blank=True, null=True,
                                     validators=[ascii_validator])
    is_own_phone = models.NullBooleanField()
    gender = models.CharField("Jenis kelamin",
                              max_length=10,
                              choices=GENDER_CHOICES,
                              validators=[ascii_validator],
                              blank=True, null=True)
    occupied_since = models.DateField(blank=True, null=True)
    home_status = models.CharField("Status domisili",
                                   choices=HOME_STATUS_CHOICES,
                                   max_length=50,
                                   validators=[ascii_validator],
                                   blank=True, null=True)
    landlord_mobile_phone = models.CharField(max_length=50,
                                             blank=True,
                                             null=True,
                                             validators=[ascii_validator])
    mobile_phone_1 = models.CharField(max_length=50,
                                      validators=[ascii_validator],
                                      blank=True,
                                      null=True)
    has_whatsapp_1 = models.NullBooleanField()
    mobile_phone_2 = models.CharField(max_length=50, blank=True, null=True,
                                      validators=[ascii_validator])
    has_whatsapp_2 = models.NullBooleanField()
    bbm_pin = models.CharField(max_length=50, blank=True, null=True,
                               validators=[ascii_validator])
    twitter_username = models.CharField(max_length=50, blank=True, null=True,
                                        validators=[ascii_validator])
    instagram_username = models.CharField(max_length=50, blank=True, null=True,
                                          validators=[ascii_validator])
    marital_status = models.CharField("Status sipil",
                                      choices=MARITAL_STATUS_CHOICES,
                                      max_length=50,
                                      validators=[ascii_validator],
                                      blank=True, null=True)
    dependent = models.IntegerField("Jumlah tanggungan",
                                    validators=[MinValueValidator(0), MaxValueValidator(10)],
                                    blank=True, null=True)
    spouse_name = models.CharField(max_length=100, blank=True, null=True,
                                   validators=[ascii_validator])
    spouse_dob = models.DateField(blank=True, null=True)
    spouse_mobile_phone = models.CharField(max_length=50, blank=True, null=True,
                                           validators=[ascii_validator])
    spouse_has_whatsapp = models.NullBooleanField()
    kin_name = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    kin_dob = models.DateField(blank=True, null=True)
    kin_gender = models.CharField("Jenis kelamin kerabat",
                                  choices=KIN_GENDER_CHOICES,
                                  max_length=10,
                                  blank=True, null=True,
                                  validators=[ascii_validator])
    kin_mobile_phone = models.CharField(max_length=50,
                                        validators=[ascii_validator],
                                        blank=True, null=True)
    kin_relationship = models.CharField("Hubungan kerabat",
                                        choices=KIN_RELATIONSHIP_CHOICES,
                                        max_length=50,
                                        validators=[ascii_validator], blank=True, null=True)
    job_type = models.CharField("Tipe pekerjaan",
                                choices=JOB_TYPE_CHOICES,
                                max_length=50,
                                validators=[ascii_validator],
                                blank=True, null=True)
    job_industry = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    job_function = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    job_description = models.CharField(max_length=100, blank=True, null=True,
                                       validators=[ascii_validator])
    company_name = models.CharField(max_length=100, blank=True, null=True,
                                    validators=[ascii_validator])
    company_phone_number = models.CharField(max_length=50, blank=True, null=True,
                                            validators=[ascii_validator])
    work_kodepos = models.CharField(max_length=5,
                                    blank=True,
                                    null=True,
                                    validators=[ascii_validator])
    job_start = models.DateField(blank=True, null=True)
    monthly_income = models.BigIntegerField(blank=True, null=True)
    last_education = models.CharField("Pendidikan terakhir",
                                      choices=LAST_EDUCATION_CHOICES,
                                      max_length=50,
                                      validators=[ascii_validator],
                                      blank=True, null=True)
    college = models.CharField(max_length=100, blank=True, null=True,
                               validators=[ascii_validator])
    major = models.CharField(max_length=100, blank=True, null=True,
                             validators=[ascii_validator])
    graduation_year = models.IntegerField(blank=True, null=True)
    gpa = models.FloatField(blank=True, null=True)
    has_other_income = models.BooleanField(default=False)
    other_income_amount = models.BigIntegerField(blank=True, null=True)
    other_income_source = models.CharField(max_length=250, blank=True, null=True,
                                           validators=[ascii_validator])
    monthly_housing_cost = models.BigIntegerField(blank=True, null=True)
    monthly_expenses = models.BigIntegerField(blank=True, null=True)
    total_current_debt = models.BigIntegerField(blank=True, null=True)
    vehicle_type_1 = models.CharField("Kendaraan pribadi 1",
                                      choices=VEHICLE_TYPE_CHOICES,
                                      max_length=50,
                                      validators=[ascii_validator],
                                      blank=True, null=True)
    vehicle_ownership_1 = models.CharField("Kepemilikan 1",
                                           choices=VEHICLE_OWNERSHIP_CHOICES,
                                           max_length=50,
                                           blank=True, null=True,
                                           validators=[ascii_validator])
    bank_name = models.CharField(max_length=250,
                                 validators=[ascii_validator],
                                 blank=True, null=True)
    bank_branch = models.CharField(max_length=100,
                                   validators=[ascii_validator],
                                   blank=True, null=True)
    bank_account_number = models.CharField(max_length=50,
                                           validators=[ascii_validator],
                                           blank=True, null=True)
    name_in_bank = models.CharField(max_length=100,
                                    validators=[ascii_validator],
                                    blank=True, null=True)
    application_xid = models.BigIntegerField(blank=True, null=True)
    reminder_email_sent = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'partner_referral'


class PartnerTransaction(TimeStampedModel):
    id = models.AutoField(db_column='partner_transaction_id', primary_key=True)

    partner_referral = models.ForeignKey(
        PartnerReferral, models.DO_NOTHING,
        related_name='transactions',
        db_column='partner_referral_id')

    transaction_date = models.DateField(null=True, blank=True)
    transaction_amount = models.BigIntegerField(null=True, blank=True)
    transaction_type = models.CharField(null=True, blank=True, max_length=50)
    payment_method = models.CharField(null=True, blank=True, max_length=50)
    is_current = models.NullBooleanField()

    class Meta(object):
        db_table = 'partner_transaction'


class PartnerTransactionItem(TimeStampedModel):
    id = models.AutoField(
        db_column='partner_transaction_item_id', primary_key=True)

    partner_transaction = models.ForeignKey(
        PartnerTransaction, models.DO_NOTHING,
        related_name='transaction_items',
        db_column='partner_transaction_id')

    item_name = models.CharField(null=True, blank=True, max_length=250)
    item_price = models.BigIntegerField(null=True, blank=True)
    item_quantity = models.PositiveIntegerField(null=True, blank=True)
    product_category = models.CharField(null=True, blank=True, max_length=100)

    class Meta(object):
        db_table = 'partner_transaction_item'


class PartnerAddress(TimeStampedModel, PartnerCleanse):
    ADDRESS_TYPE_CHOICES = (
        ('home_1', 'home_1'),
        ('home_2', 'home_2'),
        ('work_1', 'work_1'),
        ('work_2', 'work_2'))

    id = models.AutoField(db_column='partner_address_id', primary_key=True)

    partner_referral = models.ForeignKey(
        'PartnerReferral', models.DO_NOTHING,
        related_name='addresses',
        db_column='partner_referral_id',
        blank=True, null=True)

    partner_transaction = models.OneToOneField(
        PartnerTransaction, models.DO_NOTHING,
        related_name='address',
        db_column='partner_transaction_id',
        blank=True, null=True)

    address_type = models.CharField(
        choices=ADDRESS_TYPE_CHOICES,
        null=True,
        blank=True,
        max_length=50)

    address_street_num = models.CharField(null=True, blank=True, max_length=100)
    address_provinsi = models.CharField(null=True, blank=True, max_length=100)
    address_kabupaten = models.CharField(null=True, blank=True, max_length=100)
    address_kecamatan = models.CharField(null=True, blank=True, max_length=100)
    address_kelurahan = models.CharField(null=True, blank=True, max_length=100)
    address_kodepos = models.CharField(
        null=True,
        blank=True,
        max_length=5,
        validators=[
            RegexValidator(
                regex='^[0-9]{5}$',
                message='Kode pos has to be 5 numeric digits')
        ]
    )

    class Meta(object):
        db_table = 'partner_address'


class AppVersionHistory(TimeStampedModel):
    id = models.AutoField(db_column='app_version_history_id', primary_key=True)

    build_number = models.IntegerField()
    version_name = models.CharField(max_length=10)
    is_critical = models.NullBooleanField()

    class Meta(object):
        db_table = 'app_version_history'


class SmsHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class SmsHistory(TimeStampedModel):
    id = models.AutoField(db_column='sms_history_id', primary_key=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', blank=True, null=True)

    status = models.CharField(max_length=30, default='sent_to_provider')
    delivery_error_code = models.IntegerField(blank=True, null=True)
    message_id = models.CharField(max_length=50, blank=True, null=True)
    message_content = models.TextField(blank=True, null=True)
    template_code = models.CharField(max_length=50, null=True, blank=True)
    to_mobile_phone = PhoneNumberField()
    phone_number_type = models.CharField(max_length=50, null=True, blank=True)
    category = models.CharField(max_length=20, null=True, blank=True)
    comms_provider = models.ForeignKey(
        'CommsProviderLookup', models.DO_NOTHING,
        blank=True, null=True, db_column='comms_provider_id')
    is_otp = models.BooleanField(default=False)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    source = models.TextField(blank=True, null=True)
    partnership_customer_data = models.ForeignKey(
        'partnership.PartnershipCustomerData',
        on_delete=models.DO_NOTHING, db_column='partnership_customer_data_id',
        null=True, blank=True
    )
    tsp = models.TextField(blank=True, null=True)
    objects = SmsHistoryManager()

    class Meta(object):
        db_table = 'sms_history'
        index_together = [
            ["to_mobile_phone", "cdate", "status"],
        ]


class EmailHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class EmailHistory(TimeStampedModel):
    id = models.AutoField(db_column='email_history_id', primary_key=True)

    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id', blank=True, null=True)
    payment = models.ForeignKey(
        Payment,
        models.DO_NOTHING,
        db_column='payment_id',
        blank=True, null=True)
    application = models.ForeignKey(Application, models.DO_NOTHING,
                                    db_column='application_id',
                                    blank=True, null=True)
    status = models.CharField(max_length=20, default='pending')
    sg_message_id = models.CharField(max_length=150, blank=True, null=True)
    to_email = models.TextField(blank=True, null=True)
    cc_email = models.EmailField(blank=True, null=True)
    subject = models.CharField(max_length=250, blank=True, null=True)
    pre_header = models.CharField(max_length=250, blank=True, null=True)
    category = models.CharField(max_length=20, null=True, blank=True)
    message_content = models.TextField(blank=True, null=True)
    template_code = models.CharField(max_length=250, null=True, blank=True)
    partner = models.ForeignKey(Partner, models.DO_NOTHING,
                                db_column='partner_id', blank=True, null=True)
    lender = models.ForeignKey('followthemoney.LenderCurrent',
                               models.DO_NOTHING, db_column='lender_id', blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    source = models.TextField(blank=True, null=True)
    campaign_id = models.TextField(blank=True, null=True)
    collection_hi_season_campaign_comms_setting = models.ForeignKey(
        'collection_hi_season.CollectionHiSeasonCampaignCommsSetting',
        models.DO_NOTHING,
        db_column='collection_hi_season_campaign_comms_setting_id',
        blank=True, null=True)

    objects = EmailHistoryManager()

    class Meta(object):
        db_table = 'email_history'
        index_together = [
            ['cdate'],
        ]


class EmailAttachments(TimeStampedModel):
    id = models.AutoField(db_column='email_attachment_id', primary_key=True)
    attachment = models.FileField(upload_to='uploads/')
    email = models.ForeignKey(EmailHistory)


class WhatsappHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class WhatsappHistory(TimeStampedModel):
    id = models.AutoField(db_column='whatsapp_history_id', primary_key=True)
    xid = models.TextField(db_column='whatsapp_history_xid', default=uuid.uuid4, unique=True)
    umid = models.TextField(db_column='whatsapp_history_umid', blank=True, null=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', blank=True, null=True)

    status = models.CharField(max_length=25, default='SENT')
    error = models.TextField(blank=True, null=True)
    message_content = models.TextField()
    template_code = models.CharField(max_length=50, null=True, blank=True)
    to_mobile_phone = models.TextField()

    objects = WhatsappHistoryManager()

    class Meta(object):
        db_table = 'whatsapp_history'


class SkiptraceManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class Skiptrace(PIIVaultModel):
    PII_FIELDS = ['phone_number', 'contact_name']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = CollectionQueue.TOKENIZED_QUEUE

    id = models.AutoField(db_column='skiptrace_id', primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id', null=True, blank=True)
    application = models.ForeignKey(Application, models.DO_NOTHING,
                                    db_column='src_application_id', null=True, blank=True)
    contact_name = models.TextField(null=True, blank=True)
    contact_source = models.TextField(null=True, blank=True)
    phone_number = NoValidatePhoneNumberField(null=True, blank=True)
    phone_operator = models.TextField(null=True, blank=True)
    effectiveness = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    recency = models.DateTimeField(null=True, blank=True)
    frequency = models.IntegerField(null=True, blank=True)
    is_guarantor = models.BooleanField(default=False)
    phone_number_tokenized = models.TextField(blank=True, null=True)
    contact_name_tokenized = models.TextField(null=True, blank=True)

    objects = SkiptraceManager()

    class Meta(object):
        db_table = 'skiptrace'
        unique_together = ('customer', 'phone_number')

    def save(self, *args, **kwargs):
        if self.application:
            self.customer = self.application.customer
        if self.phone_number:
            telco_code = self.phone_number.as_national[:4]
            if telco_code in telco_operator_codes:
                self.phone_operator = telco_operator_codes[telco_code]
        try:
            super(Skiptrace, self).save(*args, **kwargs)
        except IntegrityError as e:
            logger.info({"skiptrace": "duplicate number for customer",
                         "customer_id": self.customer_id,
                         "phone_number": str(self.phone_number),
                         "error": str(e)})

    @property
    def age_string(self):
        years, months, days = get_age_from_timestamp(self.cdate)
        parts = []
        if years > 0:
            parts.append(f"{years} Year{'s' if years > 1 else ''}")
        if months > 0:
            parts.append(f"{months} Month{'s' if months > 1 else ''}")
        if days > 0:
            parts.append(f"{days} Day{'s' if days > 1 else ''}")
        return " ".join(parts)


class SkiptraceHistoryQuerySet(CustomQuerySet):

    def get_non_contact_bucket(self, range1, range2, is_julo_one=False):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)

        if not is_julo_one:
            if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
                return self.filter(
                    cdate=None,
                    payment_id__isnull=False
                )
            else:
                return self.filter(payment__due_date__range=[range2_ago, range1_ago],
                                   excluded_from_bucket=True) \
                    .order_by('loan', '-cdate').distinct('loan')
        else:
            if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
                return self.filter(
                    cdate=None,
                    account_payment_id__isnull=False
                )
            else:
                return self.filter(account_payment__due_date__range=[range2_ago, range1_ago],
                                   excluded_from_bucket=True) \
                    .order_by('account', '-cdate').distinct('account')

    def get_non_contact_bucket_wo_paid(self, range1, range2, is_julo_one=False):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)

        if not is_julo_one:
            return self.filter(payment__due_date__range=[range2_ago, range1_ago],
                               excluded_from_bucket=True,
                               application__product_line_id__in=ProductLineCodes.lended_by_jtp()) \
                .values_list('application_id', flat=True) \
                .distinct('application')
        else:
            return self.filter(account_payment__due_date__range=[range2_ago, range1_ago],
                               excluded_from_bucket=True,
                               application__product_line_id__in=ProductLineCodes.lended_by_jtp()) \
                .values_list('application_id', flat=True) \
                .distinct('application')


class SkiptraceHistoryManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return SkiptraceHistoryQuerySet(self.model)

    def not_paid_active(self, is_julo_one=False):
        if not is_julo_one:
            return self.get_queryset() \
                       .filter(
                           payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
                           payment__account_payment_id__isnull=True
            ) \
                .exclude(payment__is_restructured=True)
        else:
            return self.get_queryset()\
                       .filter(
                           account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            )

    def get_non_contact_bucket1(self, is_julo_one=False):
        return self.not_paid_active(is_julo_one).get_non_contact_bucket(
            BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to'], is_julo_one

        )

    def get_non_contact_bucket2(self, is_julo_one=False):
        return self.not_paid_active(is_julo_one).get_non_contact_bucket(
            BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to'], is_julo_one
        )

    def get_non_contact_bucket3(self, is_julo_one=False):
        return self.not_paid_active(is_julo_one).get_non_contact_bucket(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to'], is_julo_one
        )

    def get_non_contact_bucket4(self, is_julo_one=False):
        return self.not_paid_active(is_julo_one).get_non_contact_bucket(
            BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to'], is_julo_one
        )

    def get_non_contact_bucket_234_wo_paid(self, is_julo_one=False):
        return self.not_paid_active(is_julo_one).get_non_contact_bucket_wo_paid(11, 100, is_julo_one)

    def get_non_contact_grab(self, is_grab):
        return self.not_paid_active(is_julo_one=is_grab).get_non_contact_bucket()

    def get_last_collection_account_calls(self, account_id, is_crm=None):
        qs = self.get_queryset().filter(
            Q(application__account_id=account_id),
            Q(account_payment__isnull=False) | Q(payment__isnull=False)
        ).distinct(
            'application__account_id'
        ).order_by('application__account_id', '-cdate')

        if is_crm is None:
            qs = qs.filter(Q(source='CRM') | Q(source__isnull=True) | Q(source='Intelix'))
        elif is_crm:
            qs = qs.filter(Q(source='CRM') | Q(source__isnull=True))
        else:
            qs = qs.filter(source='Intelix')

        return list(qs)

    def get_last_collection_account_payment_calls(self, account_payment_ids):
        account_payment_ids = account_payment_ids if isinstance(account_payment_ids, Iterable) else \
            [account_payment_ids]
        qs = self.get_queryset().filter(
            Q(account_payment_id__in=account_payment_ids),
            Q(source='CRM') | Q(source__isnull=True) | Q(source='Intelix')
        ).distinct(
            'account_payment_id'
        ).order_by('account_payment_id', '-cdate')

        return list(qs)


class SkiptraceHistory(TimeStampedModel):
    id = models.AutoField(db_column='skiptrace_history_id', primary_key=True)

    skiptrace = models.ForeignKey(Skiptrace, models.DO_NOTHING,
                                  db_column='skiptrace_id')
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField(blank=True, null=True)
    agent = CurrentUserField(related_name="skiptrace_call_history")
    agent_name = models.TextField(null=True, blank=True)
    spoke_with = models.TextField(null=True, blank=True)
    call_result = models.ForeignKey('SkiptraceResultChoice',
                                    db_column='skiptrace_result_choice_id')
    application = models.ForeignKey(Application, models.DO_NOTHING,
                                    db_column='application_id', null=True, blank=True)
    application_status = models.IntegerField(null=True, blank=True)
    old_application_status = models.IntegerField(null=True, blank=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING,
                             db_column='loan_id', null=True, blank=True)
    loan_status = models.IntegerField(null=True, blank=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING,
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
        'StatusLookup', models.DO_NOTHING, null=True, blank=True)
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
    external_unique_identifier = models.TextField(null=True, blank=True, unique=True, db_index=True)
    external_task_identifier = models.TextField(null=True, blank=True, db_index=True)

    class Meta(object):
        db_table = 'skiptrace_history'

    def __init__(self, *args, **kwargs):
        from juloserver.pii_vault.collection.services import mask_phone_number_sync

        super(SkiptraceHistory, self).__init__(*args, **kwargs)
        if self.notes:
            self.notes = mask_phone_number_sync(self.notes)

    def save(self, *args, **kwargs):
        if self.loan:
            bucket1 = SkiptraceHistory.objects.get_non_contact_bucket1().filter(
                loan_id=self.loan).last()
            bucket2 = SkiptraceHistory.objects.get_non_contact_bucket2().filter(
                loan_id=self.loan).last()
            bucket3 = SkiptraceHistory.objects.get_non_contact_bucket3().filter(
                loan_id=self.loan).last()
            bucket4 = SkiptraceHistory.objects.get_non_contact_bucket4().filter(
                loan_id=self.loan).last()
            bucket = (bucket1, bucket2, bucket3, bucket4)
            for i in bucket:
                if i and str(i.loan_id) in str(self.loan):
                    self.excluded_from_bucket = True
        super(SkiptraceHistory, self).save(*args, **kwargs)


class SkiptraceResultChoiceManager(GetInstanceMixin, JuloModelManager):

    def excluded_from_late_dpd_experiment_result_choice_ids(self):
        return self.filter(
            name__in=(
                'WPC', 'RPC', 'PTPR', 'RPC - Regular', 'RPC - PTP',
                'RPC - HTP', 'RPC - Broken Promise', 'RPC - Call Back',
                'WPC - Regular', 'WPC - Left Message'
            )
        ).values_list('id', flat=True)


class SkiptraceResultChoice(TimeStampedModel):
    id = models.AutoField(db_column='skiptrace_result_choice_id',
                          primary_key=True)

    name = models.TextField()
    weight = models.IntegerField()
    customer_reliability_score = models.IntegerField(blank=True, null=True)
    objects = SkiptraceResultChoiceManager()

    class Meta(object):
        db_table = 'skiptrace_result_choice'


class DokuTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class DokuTransaction(TimeStampedModel):
    id = models.AutoField(db_column='doku_transaction_id', primary_key=True)

    transaction_id = models.CharField(max_length=20, unique=True)
    reference_id = models.CharField(max_length=100, unique=True)
    account_id = models.CharField(max_length=50)
    transaction_date = models.DateTimeField()
    amount = models.BigIntegerField()
    transaction_type = models.CharField(max_length=10)
    is_processed = models.NullBooleanField()

    objects = DokuTransactionManager()

    class Meta(object):
        db_table = 'doku_transaction'


class BankVirtualAccountManager(GetInstanceMixin, JuloModelManager):
    pass


class BankVirtualAccount(TimeStampedModel):
    id = models.AutoField(db_column='bank_virtual_account_id', primary_key=True)
    virtual_account_number = models.CharField(
        max_length=50,
        blank=True,
        validators=[RegexValidator(
            regex='^[0-9]+$', message='Bank account number has to be numeric digits')
        ]
    )
    loan = models.ForeignKey(
        Loan, models.DO_NOTHING, db_column='loan_id', null=True, blank=True)
    bank_code = models.ForeignKey(
        PaymentMethodLookup, models.DO_NOTHING, db_column='bank_code')

    objects = BankVirtualAccountManager()

    class Meta(object):
        db_table = 'bank_virtual_account'

    def __str__(self):
        """Visual identification"""
        return "%s %s" % (self.bank_code, self.virtual_account_number)


class ApplicationCheckListManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationCheckList(TimeStampedModel):
    id = models.AutoField(db_column='application_check_list_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    field_name = models.TextField()
    sd = models.NullBooleanField()
    dv = models.NullBooleanField()
    pv = models.NullBooleanField()
    ca = models.NullBooleanField()
    fin = models.NullBooleanField()
    coll = models.NullBooleanField()

    objects = ApplicationCheckListManager()

    class Meta(object):
        db_table = 'application_check_list'


class ApplicationCheckListHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationCheckListHistory(TimeStampedModel):
    id = models.AutoField(db_column='application_check_list_history_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    field_name = models.TextField()
    changed_to = models.NullBooleanField()
    changed_from = models.NullBooleanField()
    group = models.CharField(max_length=5)
    agent = CurrentUserField()

    objects = ApplicationCheckListHistoryManager()

    class Meta(object):
        db_table = 'application_check_list_history'


class ApplicationFieldChangeManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class ApplicationFieldChange(PIIVaultModel):
    id = models.AutoField(db_column='application_field_change_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    field_name = models.TextField()
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    old_value_tokenized = models.TextField(null=True, blank=True)
    new_value_tokenized = models.TextField(null=True, blank=True)
    agent = CurrentUserField()
    PII_FIELDS = ['old_value','new_value']
    PII_TYPE = PIIType.KV
    objects = ApplicationFieldChangeManager()

    class Meta(object):
        db_table = 'application_field_change'


class ApplicationCheckListCommentManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationCheckListComment(TimeStampedModel):
    id = models.AutoField(db_column='application_check_list_comment_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    field_name = models.TextField()
    comment = models.TextField()
    group = models.CharField(max_length=5)
    agent = CurrentUserField()

    objects = ApplicationCheckListCommentManager()

    class Meta(object):
        db_table = 'application_check_list_comment'


class AdditionalExpenseManager(GetInstanceMixin, JuloModelManager):
    pass


class AdditionalExpense(TimeStampedModel):
    id = models.AutoField(db_column='additional_expense_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    field_name = models.TextField()
    description = models.TextField()
    amount = models.BigIntegerField()
    is_deleted = models.BooleanField(default=False)
    group = models.CharField(max_length=5)
    agent = CurrentUserField()

    objects = AdditionalExpenseManager()

    class Meta(object):
        db_table = 'additional_expense'


class AdditionalExpenseHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class AdditionalExpenseHistory(TimeStampedModel):
    id = models.AutoField(db_column='additional_expense_history_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    additional_expense = models.ForeignKey(
        AdditionalExpense, models.DO_NOTHING, db_column='additional_expense_id',
        null=True, blank=True)
    field_name = models.TextField()
    old_description = models.TextField()
    old_amount = models.BigIntegerField()
    new_description = models.TextField()
    new_amount = models.BigIntegerField()
    group = models.CharField(max_length=5)
    agent = CurrentUserField()

    objects = AdditionalExpenseHistoryManager()

    class Meta(object):
        db_table = 'additional_expense_history'


class OriginalPassword(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='auth_user_id')

    original_password = models.CharField(max_length=128)
    temporary_password = models.CharField(blank=True, null=True, max_length=8)

    class Meta(object):
        db_table = 'original_password'

    def __str__(self):
        """Visual identification"""
        return str(self.user)


class CollateralManager(GetInstanceMixin, JuloModelManager):
    pass


class Collateral(TimeStampedModel):
    id = models.AutoField(db_column='collateral_id', primary_key=True)
    application = models.OneToOneField(
        Application, models.DO_NOTHING, db_column='application_id')
    partner = models.ForeignKey(
        Partner, models.DO_NOTHING, db_column='partner_id')
    collateral_type = models.CharField(max_length=50, validators=[ascii_validator])
    collateral_model_name = models.CharField(max_length=50, validators=[ascii_validator])
    collateral_model_year = models.CharField(max_length=10, validators=[ascii_validator])

    objects = CollateralManager()

    class Meta(object):
        db_table = 'collateral'


class PartnerLoanManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnerLoan(TimeStampedModel):
    id = models.AutoField(db_column='partner_loan_id', primary_key=True)
    application = models.OneToOneField(
        Application, models.DO_NOTHING, db_column='application_id')
    partner = models.ForeignKey(
        Partner, models.DO_NOTHING, db_column='partner_id')
    agreement_number = models.CharField(max_length=100,
                                        validators=[ascii_validator],
                                        null=True, blank=True)
    approval_status = models.CharField(max_length=20, validators=[ascii_validator])
    approval_date = models.DateTimeField(null=True, blank=True)
    loan_amount = models.BigIntegerField(null=True, blank=True)

    objects = PartnerLoanManager()

    class Meta(object):
        db_table = 'partner_loan'


class AutoDialerRecordManager(GetInstanceMixin, JuloModelManager):
    pass


class AutoDialerRecord(TimeStampedModel):
    id = models.AutoField(db_column='autodialer_record_id', primary_key=True)
    call_id = models.CharField(max_length=250, validators=[ascii_validator])
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id')
    skiptrace = models.ForeignKey(Skiptrace, models.DO_NOTHING, db_column='skiptrace_id')
    time_of_call = models.DateTimeField(null=True)
    call_status = models.CharField(max_length=20)
    call_duration = models.IntegerField(null=True)
    attempt_number = models.IntegerField(null=True)

    objects = AutoDialerRecordManager()

    class Meta(object):
        db_table = 'autodialer_record'


class DisbursementManager(GetInstanceMixin, JuloModelManager):
    pass


class Disbursement(TimeStampedModel):
    id = models.AutoField(db_column='disbursement_id', primary_key=True)
    validation_status = models.CharField(max_length=50, null=True)
    validation_id = models.CharField(max_length=250, null=True)
    validated_name = models.CharField(max_length=250, null=True)
    bank_code = models.CharField(max_length=50, null=True)
    bank_number = models.CharField(max_length=50, blank=True, null=True)
    disburse_status = models.CharField(max_length=50, null=True)
    disburse_id = models.CharField(max_length=250, null=True)
    disburse_amount = models.BigIntegerField(null=True)
    external_id = models.BigIntegerField(blank=True, null=True)
    retry_times = models.IntegerField(default=0, blank=True, null=True)

    loan = models.OneToOneField(Loan, models.DO_NOTHING, db_column='loan_id')

    objects = DisbursementManager()

    class Meta(object):
        db_table = 'disbursement'


class MantriManager(GetInstanceMixin, JuloModelManager):
    pass


class Mantri(TimeStampedModel):
    # columns go here
    id = models.AutoField(db_column='mantri_id', primary_key=True)
    code = models.CharField(max_length=20, null=True)

    objects = MantriManager()

    class Meta(object):
        db_table = 'mantri'


class FasPayTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class FasPayTransaction(TimeStampedModel):
    id = models.AutoField(db_column='faspay_transaction_id', primary_key=True)
    transaction_id = models.CharField(max_length=16, unique=True, blank=True, null=True)
    amount = models.BigIntegerField(blank=True, null=True)
    is_processed = models.NullBooleanField(default=False)
    status_code = models.IntegerField(blank=True, null=True)
    status_desc = models.CharField(max_length=60, blank=True, null=True)
    transaction_date = models.DateTimeField(blank=True, null=True)

    objects = FasPayTransactionManager()

    class Meta(object):
        db_table = 'faspay_transaction'


class PaybackTransactionManager(GetInstanceMixin, JuloModelManager, PIIVaultModelManager):
    pass


class PaybackTransaction(PIIVaultModel):
    PII_FIELDS = ['virtual_account']
    PII_TYPE = PIIType.KV
    PAYBACK_SERVICES = (
        ('faspay', 'Faspay'),
        ('gopay', 'GoPay'),
    )
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = models.AutoField(db_column='payback_transaction_id', primary_key=True)
    transaction_id = models.TextField(unique=True, blank=True, null=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id', null=True, blank=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING,
                                db_column='payment_id', blank=True, null=True)
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING, db_column='loan_id',
                             blank=True, null=True)
    payment_method = models.ForeignKey(
        PaymentMethod, models.DO_NOTHING, db_column='payment_method_id',
        blank=True, null=True)
    payback_service = models.TextField(null=True, blank=True)
    amount = models.BigIntegerField(blank=True, null=True)
    is_processed = models.NullBooleanField(default=False)
    status_code = models.IntegerField(blank=True, null=True)
    status_desc = models.CharField(max_length=60, blank=True, null=True)
    transaction_date = models.DateTimeField(blank=True, null=True)
    virtual_account = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        validators=[RegexValidator(
            regex='^[0-9]+$', message='Virtual account has to be numeric digits')
        ]
    )
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True)
    virtual_account_tokenized = models.TextField(blank=True, null=True)
    inquiry_request_id = models.TextField(blank=True, null=True)

    objects = PaybackTransactionManager()

    class Meta(object):
        db_table = 'payback_transaction'


class PaybackTransactionStatusHistory(TimeStampedModel):
    id = models.AutoField(db_column='payback_transaction_status_history_id', primary_key=True)
    payback_transaction = models.ForeignKey(
        PaybackTransaction, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    old_status_code = models.IntegerField(blank=True, null=True)
    new_status_code = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'payback_transaction_status_history'


class BankLookupManager(GetInstanceMixin, JuloModelManager):
    pass


class BankLookup(TimeStampedModel):
    id = models.AutoField(db_column='internal_bank_id', primary_key=True)
    bank_code = models.CharField(max_length=3)
    bank_name = models.TextField()
    xendit_bank_code = models.TextField()
    swift_bank_code = models.CharField(max_length=8)

    objects = BankLookupManager()

    class Meta(object):
        db_table = 'bank_lookup'


class OtpRequestDataManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class OtpRequest(PIIVaultModel):
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'platform_pii_vault'
    # base 32 secret key
    EXP_IN_MINUTES = 5

    id = models.AutoField(db_column='otp_request_id', primary_key=True)
    customer = models.ForeignKey('Customer', models.DO_NOTHING, db_column='customer_id',
                                 blank=True, null=True)
    partnership_customer_data = models.ForeignKey(
        'partnership.PartnershipCustomerData',
        on_delete=models.DO_NOTHING, db_column='partnership_customer_data_id',
        null=True, blank=True
    )
    application = models.ForeignKey(
        'Application', models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    sms_history = models.OneToOneField(
        'SmsHistory', models.DO_NOTHING, db_column='sms_history_id', blank=True, null=True)
    miscall_otp = models.OneToOneField(
        'otp.MisCallOTP', models.DO_NOTHING, db_column='miscall_otp_id', blank=True, null=True)
    email_history = models.OneToOneField(
        'EmailHistory', models.DO_NOTHING, db_column='email_history_id', blank=True, null=True)
    request_id = models.CharField(max_length=50)
    otp_token = models.CharField(max_length=6, blank=True, null=True)
    is_used = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    otp_service_type = models.CharField(max_length=50, blank=True, null=True)
    retry_validate_count = models.SmallIntegerField(default=0)
    email = models.CharField(max_length=255, blank=True, null=True)
    action_type = models.CharField(max_length=100, blank=True, null=True)
    android_id_requestor = models.CharField(max_length=200, blank=True, null=True)
    android_id_user = models.CharField(max_length=200, blank=True, null=True)
    otpless_reference_id = models.CharField(max_length=50, blank=True, null=True)
    whatsapp_xid = models.CharField(max_length=50, blank=True, null=True)
    otp_session_id = models.CharField(max_length=16, blank=True, null=True)
    reported_delivered_time = models.DateTimeField(blank=True, null=True)
    used_time = models.DateTimeField(blank=True, null=True)
    phone_number_tokenized = models.TextField(blank=True, null=True)
    ios_id_requestor = models.TextField(blank=True, null=True)
    ios_id_user = models.TextField(blank=True, null=True)

    objects = OtpRequestDataManager()

    class Meta(object):
        db_table = 'otp_request'
        index_together = [
            ["otp_token", "customer", "is_used", "request_id"],
        ]

    def full_clean(self, exclude=None, validate_unique=True):
        if all([self.customer is None, self.partnership_customer_data is None,
                self.action_type not in SessionTokenAction.NON_CUSTOMER_ACTIONS]):
            raise ValidationError({
                "message": "Customer and partnership_customer_data cannot be Null"
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super(OtpRequest, self).save(*args, **kwargs)

    @property
    def is_active(self):
        """
            Only use for otp feature that still use the mobile_phone_1_otp feature setting
        """
        active = True
        curr_time = timezone.localtime(timezone.now())

        otp_wait_seconds = 180
        mfs = MobileFeatureSetting.objects.get_or_none(
            feature_name='mobile_phone_1_otp')
        if mfs is not None and mfs.parameters is not None:
            otp_wait_seconds = mfs.parameters['wait_time_seconds']

        exp_time = timezone.localtime(self.cdate) + timedelta(seconds=otp_wait_seconds)

        if curr_time > exp_time:
            active = False
        logger.debug({
            'expiration_time': str(exp_time),
            'now': str(curr_time),
            'expired': not active
        })
        return active

    def is_active_by_sms_history(self, otp_wait_seconds=180):
        active = True
        now = timezone.localtime(timezone.now())

        exp_time = timezone.localtime(self.sms_history.cdate) + timedelta(seconds=otp_wait_seconds)

        if now > exp_time:
            active = False
        logger.debug({
            'expiration_time': str(exp_time),
            'now': str(now),
            'expired': not active
        })
        return active

    @property
    def is_expired(self):
        """
            Only use for email otp feature setting
        """
        expired = False
        curr_time = timezone.localtime(timezone.now())

        otp_wait_seconds = 200
        fs = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.EMAIL_OTP)
        if fs is not None and fs.parameters is not None:
            otp_wait_seconds = fs.parameters['wait_time_seconds']

        exp_time = timezone.localtime(self.cdate) + timedelta(seconds=otp_wait_seconds)

        if curr_time > exp_time:
            expired = True
        logger.debug({
            'expiration_time': str(exp_time),
            'now': str(curr_time),
            'expired': expired
        })
        return expired


class CreditScoreManager(GetInstanceMixin, JuloModelManager):
    pass


class CreditScore(TimeStampedModel):
    id = models.AutoField(db_column='credit_score_id', primary_key=True)
    application = models.OneToOneField(
        'Application', models.DO_NOTHING, db_column='application_id', null=True)

    score = models.TextField()
    message = models.TextField()
    products_str = models.TextField()
    income_prediction_score = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True)
    thin_file_score = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    inside_premium_area = models.BooleanField(default=True)
    score_tag = models.CharField(max_length=60, blank=True, null=True)
    credit_limit = models.BigIntegerField(null=True, blank=True)
    failed_checks = ArrayField(models.CharField(max_length=200), blank=True, null=True)
    model_version = models.CharField(max_length=200, null=True, default=None)
    credit_matrix_version = models.IntegerField(default=None, null=True, blank=True)
    fdc_inquiry_check = models.NullBooleanField()
    credit_matrix_id = models.CharField(default=None, blank=True, null=True, max_length=10)

    objects = CreditScoreManager()

    class Meta(object):
        db_table = 'credit_score'

    @property
    def products(self):
        return json.loads(self.products_str)

    def __str__(self):
        return "%s - %s" % (self.application.id, self.score)


class KycRequestManager(GetInstanceMixin, JuloModelManager):
    pass


class KycRequest(TimeStampedModel):
    id = models.AutoField(db_column='kyc_request_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    eform_voucher = models.CharField(max_length=60, unique=True, blank=True, null=True)
    expiry_time = models.DateTimeField(blank=True, null=True)
    is_processed = models.NullBooleanField(default=False)

    objects = KycRequestManager()

    class Meta(object):
        db_table = 'kyc_request'

    @property
    def is_expired(self):
        return timezone.localtime(timezone.now()) >= timezone.localtime(self.expiry_time)

    @property
    def days_before_expired(self):
        start_date = timezone.localtime(timezone.now())
        end_date = timezone.localtime(self.expiry_time)
        range_time = start_date - end_date
        range_day = range_time.days
        return range_day


class BankApplicationManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class BankApplication(PIIVaultModel):
    PII_FIELDS = ['mailing_address']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    MAILING_ADDRESS_CHOICES = (('Alamat Identitas', 'Alamat Identitas'),
                               ('Alamat tempat kerja', 'Alamat tempat kerja'),
                               ('Alamat domisili', 'Alamat domisili'))
    INCOME_SOURCE_CHOICES = (('Gaji', 'Gaji'),
                             ('Hasil Usaha', 'Hasil Usaha'),
                             ('Lainnya', 'Lainnya'))
    id = models.AutoField(db_column='bank_application_id', primary_key=True)
    application = models.OneToOneField(
        Application, models.DO_NOTHING, db_column='application_id')
    mailing_address = models.CharField(
        choices=MAILING_ADDRESS_CHOICES, null=True, blank=True, max_length=50)
    kkbri = models.NullBooleanField()
    daily_transaction = models.BigIntegerField(blank=True, null=True)
    income_source = models.CharField(
        choices=INCOME_SOURCE_CHOICES, null=True, blank=True, max_length=50)
    company_address_kelurahan = models.CharField(max_length=100, blank=True, null=True)
    company_address_kecamatan = models.CharField(max_length=100, blank=True, null=True)
    company_address_kabupaten = models.CharField(max_length=100, blank=True, null=True)
    company_address_provinsi = models.CharField(max_length=100, blank=True, null=True)
    uker_name = models.CharField(max_length=100, blank=True, null=True)
    mailing_address_tokenized = models.CharField(null=True, blank=True, max_length=225)

    objects = BankApplicationManager()

    class Meta(object):
        db_table = 'bank_application'


class ScrapingButtonManager(GetInstanceMixin, JuloModelManager):
    pass


class ScrapingButton(TimeStampedModel):
    id = models.AutoField(db_column='scraping_button_id', primary_key=True)
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    tag = models.IntegerField(null=True)
    is_shown = models.BooleanField(default=True)
    objects = ScrapingButtonManager()

    class Meta(object):
        db_table = 'scraping_buttons'


class DisbursementTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class DisbursementTransaction(TimeStampedModel):
    id = models.AutoField(db_column='loan_transaction_id', primary_key=True)
    partner = models.ForeignKey(Partner,
                                models.DO_NOTHING, db_column='partner_id')
    customer = models.ForeignKey(Customer,
                                 models.DO_NOTHING, db_column='customer_id')
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING, db_column='loan_id')
    lender_disbursed = models.BigIntegerField(default=0)
    borrower_received = models.BigIntegerField(default=0)
    total_provision_received = models.BigIntegerField(default=0)
    julo_provision_received = models.BigIntegerField(default=0)
    lender_provision_received = models.BigIntegerField(default=0)
    lender_balance_before = models.BigIntegerField(default=0)
    lender_balance_after = models.BigIntegerField(default=0)
    objects = DisbursementTransactionManager()

    class Meta(object):
        db_table = 'disbursement_transaction'


class RepaymentTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class RepaymentTransaction(TimeStampedModel):
    REPAYMENT_SOURCE_CHOICES = (('borrower_bank', 'borrower_bank'),
                                ('borrower_wallet', 'borrower_wallet'))
    id = models.AutoField(db_column='repayment_transaction_id', primary_key=True)
    partner = models.ForeignKey(Partner,
                                models.DO_NOTHING, db_column='partner_id')
    customer = models.ForeignKey(Customer,
                                 models.DO_NOTHING, db_column='customer_id')
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING, db_column='loan_id')
    payment = models.ForeignKey(Payment,
                                models.DO_NOTHING, db_column='payment_id')
    payment_method = models.ForeignKey(
        PaymentMethod, models.DO_NOTHING, db_column='payment_method_id',
        blank=True, null=True)
    event_date = models.DateField(null=True, blank=True)
    repayment_source = models.CharField(
        choices=REPAYMENT_SOURCE_CHOICES, null=True, blank=True, max_length=50)
    borrower_repaid = models.BigIntegerField(default=0)
    borrower_repaid_principal = models.BigIntegerField(default=0)
    borrower_repaid_interest = models.BigIntegerField(default=0)
    borrower_repaid_late_fee = models.BigIntegerField(default=0)
    lender_received = models.BigIntegerField(default=0)
    lender_received_principal = models.BigIntegerField(default=0)
    lender_received_interest = models.BigIntegerField(default=0)
    lender_received_late_fee = models.BigIntegerField(default=0)
    julo_fee_received = models.BigIntegerField(default=0)
    julo_fee_received_principal = models.BigIntegerField(default=0)
    julo_fee_received_interest = models.BigIntegerField(default=0)
    julo_fee_received_late_fee = models.BigIntegerField(default=0)
    due_amount_before = models.BigIntegerField(default=0)
    due_amount_after = models.BigIntegerField(default=0)
    lender_balance_before = models.BigIntegerField(default=0)
    lender_balance_after = models.BigIntegerField(default=0)
    payment_receipt = models.CharField(max_length=50, null=True, blank=True)
    added_by = CurrentUserField(related_name="repayment_transactions")
    objects = RepaymentTransactionManager()

    class Meta(object):
        db_table = 'repayment_transaction'


class LenderBalanceManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderBalance(TimeStampedModel):
    id = models.AutoField(db_column='lender_balance_id', primary_key=True)
    lender = models.OneToOneField(
        'followthemoney.LenderCurrent', models.DO_NOTHING, db_column='lender_id',
        blank=True, null=True)
    partner = models.OneToOneField(Partner,
                                   on_delete=models.CASCADE,
                                   db_column='partner_id',
                                   blank=True, null=True)
    total_deposit = models.BigIntegerField(default=0)
    total_withdrawal = models.BigIntegerField(default=0)
    total_disbursed_principal = models.BigIntegerField(default=0)
    total_received = models.BigIntegerField(default=0)
    total_received_principal = models.BigIntegerField(default=0)
    total_received_interest = models.BigIntegerField(default=0)
    total_received_late_fee = models.BigIntegerField(default=0)
    total_received_provision = models.BigIntegerField(default=0)
    total_paidout = models.BigIntegerField(default=0)
    total_paidout_principal = models.BigIntegerField(default=0)
    total_paidout_interest = models.BigIntegerField(default=0)
    total_paidout_late_fee = models.BigIntegerField(default=0)
    total_paidout_provision = models.BigIntegerField(default=0)
    available_balance = models.BigIntegerField(default=0)
    outstanding_principal = models.BigIntegerField(default=0)
    objects = LenderBalanceManager()

    class Meta(object):
        db_table = 'lender_balance'


class LenderBalanceEventManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderBalanceEvent(TimeStampedModel):
    TYPE_CHOICES = (('deposit', 'deposit'),
                    ('withdraw', 'withdraw'))
    id = models.AutoField(db_column='lender_balance_event_id', primary_key=True)
    lender_balance = models.ForeignKey(
        LenderBalance, models.DO_NOTHING, db_column='lender_balance_id')
    amount = models.BigIntegerField()
    before_amount = models.BigIntegerField()
    after_amount = models.BigIntegerField()
    type = models.CharField(
        choices=TYPE_CHOICES, max_length=50)
    objects = LenderBalanceEventManager()

    class Meta(object):
        db_table = 'lender_balance_event'


class LenderServiceRateManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderServiceRate(TimeStampedModel):
    id = models.AutoField(db_column='lender_service_rate_id', primary_key=True)
    lender = models.ForeignKey(
        'followthemoney.LenderCurrent', models.DO_NOTHING, db_column='lender_id',
        blank=True, null=True)
    partner = models.OneToOneField(Partner,
                                   on_delete=models.CASCADE,
                                   db_column='partner_id',
                                   blank=True, null=True)
    provision_rate = models.FloatField()
    principal_rate = models.FloatField()
    interest_rate = models.FloatField()
    late_fee_rate = models.FloatField()
    objects = LenderServiceRateManager()

    class Meta(object):
        db_table = 'lender_service_rate'


class CustomerAppActionManager(GetInstanceMixin, JuloModelManager):
    pass


class CustomerAppAction(TimeStampedModel):
    id = models.AutoField(db_column='customer_app_action_id', primary_key=True)
    customer = models.ForeignKey(
        'Customer', models.DO_NOTHING, db_column='customer_id')
    action = models.CharField(max_length=100)
    is_completed = models.BooleanField(default=False)

    objects = CustomerAppActionManager()

    class Meta(object):
        db_table = 'customer_app_action'

    def mark_as_completed(self):
        if not self.is_completed:
            logger.info({
                "customer": self.customer.id,
                "customer_app_action": self.action,
                "action": "mark_as_completed",
            })
            self.is_completed = True


class AppVersionManager(GetInstanceMixin, JuloModelManager):
    def latest_version(self):
        return self.get_queryset().filter(status='latest').last()


class AppVersion(TimeStampedModel):
    APPVER_STATUS_CHOICES = (('supported', 'supported'),
                             ('deprecated', 'deprecated'),
                             ('not_supported', 'not_supported'),
                             ('latest', 'latest'))
    id = models.AutoField(db_column='app_version_id', primary_key=True)
    app_version = models.CharField(max_length=50)
    status = models.CharField(
        choices=APPVER_STATUS_CHOICES, max_length=50)

    objects = AppVersionManager()

    class Meta(object):
        db_table = 'app_version'

    def is_latest(self):
        return self.status == 'latest'


class AutodialerSessionStatusManager(GetInstanceMixin, JuloModelManager):
    pass


class AutodialerSessionStatus(TimeStampedModel):
    id = models.AutoField(db_column='autodialer_session_status_id', primary_key=True)
    failed_count = models.IntegerField(default=0)
    next_session_ts = models.DateTimeField(blank=True, null=True)
    application_history = models.OneToOneField(
        ApplicationHistory, models.DO_NOTHING, db_column='application_history_id')

    objects = AutodialerSessionStatusManager()

    class Meta(object):
        db_table = 'autodialer_session_status'


class DashboardBuckets(models.Model):
    # To-Do
    app_0_turbo = models.IntegerField(default=0)
    app_agent_assisted_100 = models.IntegerField(default=0)
    app_120 = models.IntegerField(default=0)
    app_121 = models.IntegerField(default=0)
    app_121_grab = models.IntegerField(default=0)
    app_121_jstarter_wh = models.IntegerField(default=0)
    app_121_jstarter_nwh = models.IntegerField(default=0)
    app_121_jstarter = models.IntegerField(default=0)
    app_122 = models.IntegerField(default=0)
    app_1220 = models.IntegerField(default=0)
    app_123 = models.IntegerField(default=0)
    app_125 = models.IntegerField(default=0)
    app_124 = models.IntegerField(default=0)
    app_124_j1 = models.IntegerField(default=0)
    app_1240 = models.IntegerField(default=0)
    app_126 = models.IntegerField(default=0)
    app_127_j1 = models.IntegerField(default=0)
    app_128_j1 = models.IntegerField(default=0)
    app_130 = models.IntegerField(default=0)
    app_130_j1 = models.IntegerField(default=0)
    app_132 = models.IntegerField(default=0)
    app_132_grab = models.IntegerField(default=0)
    app_134 = models.IntegerField(default=0)
    app_141 = models.IntegerField(default=0)
    app_141_j1 = models.IntegerField(default=0)
    app_144 = models.IntegerField(default=0)
    app_145 = models.IntegerField(default=0)
    app_163 = models.IntegerField(default=0)
    app_164 = models.IntegerField(default=0)
    app_165 = models.IntegerField(default=0)
    app_150 = models.IntegerField(default=0)
    app_150_j1 = models.IntegerField(default=0)
    app_153 = models.IntegerField(default=0)
    app_155 = models.IntegerField(default=0)
    app_170 = models.IntegerField(default=0)
    app_175 = models.IntegerField(default=0)
    app_175_j1 = models.IntegerField(default=0)
    app_175_mtl = models.IntegerField(default=0)
    app_177 = models.IntegerField(default=0)
    app_179 = models.IntegerField(default=0)
    app_180 = models.IntegerField(default=0)
    app_181 = models.IntegerField(default=0)
    app_185 = models.IntegerField(default=0)
    app_186 = models.IntegerField(default=0)
    app_190 = models.IntegerField(default=0)
    app_191_jstarter = models.IntegerField(default=0)
    app_cashback_request = models.IntegerField(default=0)
    app_cashback_pending = models.IntegerField(default=0)
    app_cashback_failed = models.IntegerField(default=0)
    app_overpaid_verification = models.IntegerField(default=0)

    # To Follow Up
    app_141 = models.IntegerField(default=0)
    app_105 = models.IntegerField(default=0)
    app_110 = models.IntegerField(default=0)
    app_131 = models.IntegerField(default=0)
    app_138 = models.IntegerField(default=0)
    app_1380 = models.IntegerField(default=0)
    app_140 = models.IntegerField(default=0)
    app_160 = models.IntegerField(default=0)
    app_162 = models.IntegerField(default=0)
    app_172 = models.IntegerField(default=0)
    app_181 = models.IntegerField(default=0)
    app_courtesy_call = models.IntegerField(default=0)

    # Partner App
    app_129 = models.IntegerField(default=0)
    app_189 = models.IntegerField(default=0)
    app_partnership_agent_assisted_100 = models.IntegerField(default=0)

    # Graveyard
    app_106 = models.IntegerField(default=0)
    app_111 = models.IntegerField(default=0)
    app_133 = models.IntegerField(default=0)
    app_135 = models.IntegerField(default=0)
    app_136 = models.IntegerField(default=0)
    app_137 = models.IntegerField(default=0)
    app_139 = models.IntegerField(default=0)
    app_142 = models.IntegerField(default=0)
    app_143 = models.IntegerField(default=0)
    app_161 = models.IntegerField(default=0)
    app_171 = models.IntegerField(default=0)

    # app priority To-Do
    app_priority_120 = models.IntegerField(default=0)
    app_priority_121 = models.IntegerField(default=0)
    app_priority_122 = models.IntegerField(default=0)
    app_priority_1220 = models.IntegerField(default=0)
    app_priority_123 = models.IntegerField(default=0)
    app_priority_125 = models.IntegerField(default=0)
    app_priority_124 = models.IntegerField(default=0)
    app_priority_1240 = models.IntegerField(default=0)
    app_priority_126 = models.IntegerField(default=0)
    app_priority_130 = models.IntegerField(default=0)
    app_priority_132 = models.IntegerField(default=0)
    app_priority_134 = models.IntegerField(default=0)
    app_priority_141 = models.IntegerField(default=0)
    app_priority_163 = models.IntegerField(default=0)
    app_priority_164 = models.IntegerField(default=0)
    app_priority_165 = models.IntegerField(default=0)
    app_priority_170 = models.IntegerField(default=0)
    app_priority_175 = models.IntegerField(default=0)
    app_priority_177 = models.IntegerField(default=0)
    app_priority_180 = models.IntegerField(default=0)
    app_priority_181 = models.IntegerField(default=0)
    app_priority_190 = models.IntegerField(default=0)
    app_priority_cashback_request = models.IntegerField(default=0)

    # To Follow Up
    app_priority_141 = models.IntegerField(default=0)
    app_priority_105 = models.IntegerField(default=0)
    app_priority_110 = models.IntegerField(default=0)
    app_priority_131 = models.IntegerField(default=0)
    app_priority_138 = models.IntegerField(default=0)
    app_priority_1380 = models.IntegerField(default=0)
    app_priority_140 = models.IntegerField(default=0)
    app_priority_160 = models.IntegerField(default=0)
    app_priority_162 = models.IntegerField(default=0)
    app_priority_172 = models.IntegerField(default=0)
    app_priority_181 = models.IntegerField(default=0)
    app_priority_courtesy_call = models.IntegerField(default=0)

    # Partner App
    app_priority_129 = models.IntegerField(default=0)
    app_priority_189 = models.IntegerField(default=0)

    # Graveyard
    app_priority_106 = models.IntegerField(default=0)
    app_priority_111 = models.IntegerField(default=0)
    app_priority_133 = models.IntegerField(default=0)
    app_priority_135 = models.IntegerField(default=0)
    app_priority_136 = models.IntegerField(default=0)
    app_priority_137 = models.IntegerField(default=0)
    app_priority_139 = models.IntegerField(default=0)
    app_priority_142 = models.IntegerField(default=0)
    app_priority_143 = models.IntegerField(default=0)
    app_priority_161 = models.IntegerField(default=0)
    app_priority_171 = models.IntegerField(default=0)

    # Loan
    loan_210 = models.IntegerField(default=0)
    loan_210_j1 = models.IntegerField(default=0)
    loan_211 = models.IntegerField(default=0)
    loan_212 = models.IntegerField(default=0)
    loan_213 = models.IntegerField(default=0)
    loan_215 = models.IntegerField(default=0)
    loan_216 = models.IntegerField(default=0)
    loan_218 = models.IntegerField(default=0)
    loan_220 = models.IntegerField(default=0)
    loan_220_j1 = models.IntegerField(default=0)
    loan_240 = models.IntegerField(default=0)
    loan_250 = models.IntegerField(default=0)
    loan_cycle_day_requested = models.IntegerField(default=0)

    # Payment
    payment_330 = models.IntegerField(default=0)
    payment_331 = models.IntegerField(default=0)
    payment_332 = models.IntegerField(default=0)
    payment_T531 = models.IntegerField(default=0)
    payment_Tminus5 = models.IntegerField(default=0)
    payment_Tminus3 = models.IntegerField(default=0)
    payment_Tminus1 = models.IntegerField(default=0)
    payment_T0 = models.IntegerField(default=0)
    payment_T1to4 = models.IntegerField(default=0)
    payment_T5to30 = models.IntegerField(default=0)
    payment_Tplus30 = models.IntegerField(default=0)
    payment_TnotCalled = models.IntegerField(default=0)
    payment_PTP = models.IntegerField(default=0)
    payment_T5 = models.IntegerField(default=0)
    payment_T1 = models.IntegerField(default=0)
    payment_grab = models.IntegerField(default=0)
    payment_whatsapp = models.IntegerField(default=0)
    payment_Tminus5Robo = models.IntegerField(default=0)
    payment_Tminus3Robo = models.IntegerField(default=0)
    payment_whatsapp_blasted = models.IntegerField(default=0)


class PartnerReportEmailManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnerReportEmail(TimeStampedModel):
    id = models.AutoField(db_column='partner_report_email_id', primary_key=True)
    sql_query = models.TextField(blank=True, null=True)
    email_subject = models.TextField(blank=True, null=True)
    email_content = models.TextField(blank=True, null=True)
    email_recipients = models.TextField(blank=True, null=True)
    partner = models.OneToOneField(
        Partner, models.DO_NOTHING, db_column='partner_id')
    is_active = models.BooleanField(default=True)

    objects = PartnerReportEmailManager()

    class Meta(object):
        db_table = 'partner_report_email'


class PaymentAutodialerSessionManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentAutodialerSession(TimeStampedModel):
    id = models.AutoField(db_column='payment_autodialer_session_id', primary_key=True)
    failed_count = models.IntegerField(default=0)
    next_session_ts = models.DateTimeField(blank=True, null=True)
    dpd_code = models.IntegerField(blank=True, null=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id')

    objects = PaymentAutodialerSessionManager()

    class Meta(object):
        db_table = 'payment_autodialer_session'


class PaymentAutodialerActivityManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentAutodialerActivity(TimeStampedModel):
    id = models.AutoField(db_column='payment_autodialer_activity_id', primary_key=True)
    agent = CurrentUserField()
    action = models.CharField(max_length=100)
    payment_autodialer_session = models.ForeignKey(
        PaymentAutodialerSession, models.DO_NOTHING, db_column='payment_autodialer_session_id')

    objects = PaymentAutodialerActivityManager()

    class Meta(object):
        db_table = 'payment_autodialer_activity'


class BannerManager(GetInstanceMixin, JuloModelManager):
    pass


class Banner(TimeStampedModel):
    BANNER_TYPE = (
        ('DEEP_LINK', 'DEEP_LINK'),
        ('WEB_VIEW', 'WEB_VIEW'))

    id = models.AutoField(db_column='banner_id', primary_key=True)
    name = models.CharField(max_length=100)
    click_action = models.CharField(max_length=250, blank=True, null=True)
    banner_type = models.CharField(max_length=100, choices=BANNER_TYPE)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    is_permanent = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    display_order = models.IntegerField(blank=True, null=True)

    objects = BannerManager()

    class Meta(object):
        db_table = 'banner'
        app_label = 'androidcard'

    def __str__(self):
        """Visual identification"""
        return self.name

    def get_setting(self, reference_type):
        return self.bannersetting_set.filter(
            reference_type=reference_type
        ).all().values_list('reference_id', flat=True)

    @property
    def image_url(self):
        image = Image.objects.filter(
            image_source=self.id, image_type="banner_image"
        ).order_by('-id').first()
        if image:
            return image.image_url

        return None


class BannerGroupManager(GetInstanceMixin, JuloModelManager):
    pass


class BannerGroup(TimeStampedModel):
    id = models.AutoField(db_column='banner_group_id', primary_key=True)
    banner = models.ForeignKey(
        'Banner', models.DO_NOTHING, db_column='banner_id', blank=True, null=True)
    partner = ArrayField(models.CharField(max_length=200), blank=True, null=True)
    product_line = ArrayField(models.IntegerField(), blank=True, null=True)
    status = models.BooleanField(default=False)

    objects = BannerGroupManager()

    class Meta(object):
        db_table = 'banner_group'
        app_label = 'androidcard'


class BannerSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class BannerSetting(TimeStampedModel):
    REFERENCE_TYPE = (
        ('PRODUCT', 'PRODUCT'),
        ('PARTNER', 'PARTNER'),
        ('APPLICATION_STATUS', 'APPLICATION_STATUS'),
        ('LOAN_STATUS', 'LOAN_STATUS'),
        ('DUE_DATE_PAYMENT', 'DUE_DATE_PAYMENT'),
        ('PAYMENT_STATUS', 'PAYMENT_STATUS'),
        ('DPD_LOAN', 'DPD_LOAN'),
        ('DPD_PAYMENT', 'DPD_PAYMENT'),
        ('CREDIT_SCORE', 'CREDIT_SCORE'))

    REFERENCE_MODEL = (
        ('ProductLine', 'ProductLine'),
        ('Partner', 'Partner'),
        ('StatusLookup', 'StatusLookup'),
        ('Payment', 'Payment'),
        ('Loan', 'Loan'),
        ('CreditScore', 'CreditMatrix'))

    id = models.AutoField(db_column='banner_setting_id', primary_key=True)
    banner = models.ForeignKey(Banner, models.DO_NOTHING,
                               db_column='banner_id', blank=True, null=True)
    reference_model = models.CharField(
        max_length=100, choices=REFERENCE_MODEL, blank=True, null=True)
    reference_type = models.CharField(max_length=100, choices=REFERENCE_TYPE, blank=True, null=True)
    reference_id = models.CharField(max_length=100, blank=True, null=True)

    objects = BannerSettingManager()

    class Meta(object):
        db_table = 'banner_setting'


class ExperimentQuerySet(CustomQuerySet):

    def active(self):
        today_ts = timezone.localtime(timezone.now())
        return self.filter(date_start__lte=today_ts, date_end__gt=today_ts, is_active=True)


class ExperimentManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return ExperimentQuerySet(self.model)


class Experiment(TimeStampedModel):
    id = models.AutoField(db_column='experiment_id', primary_key=True)
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=400)  # use code value if not provided
    description = models.TextField(blank=True, null=True)
    status_old = models.IntegerField()
    status_new = models.IntegerField()
    date_start = models.DateTimeField()
    date_end = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=400)

    objects = ExperimentManager()

    class Meta(object):
        db_table = 'experiment'
        index_together = [
            ["status_old", "status_new", "is_active"],
        ]

    def __str__(self):
        return "%s (%s)" % (self.name, self.code)


class ExperimentTestGroupManager(GetInstanceMixin, JuloModelManager):
    pass


class ExperimentTestGroup(TimeStampedModel):
    TYPELIST = {
        'APPID': 'APPLICATION_ID',
        'PRODUCT': 'PRODUCT',
        'CSCORE': 'CREDIT_SCORE',
        'REASON': 'REASON_LAST_CHANGE_STATUS',
        'IPSCORE': 'INCOME_PREDICTION_SCORE',
        'TFSCORE': 'THIN_FILE_SCORE',
        'LOANCOUNT': 'LOAN_COUNT',
    }

    id = models.AutoField(db_column='experiment_test_group_id', primary_key=True)
    experiment = models.ForeignKey(Experiment, models.DO_NOTHING, db_column='experiment_id')
    type = models.CharField(max_length=100)
    value = models.CharField(max_length=500)

    objects = ExperimentTestGroupManager()

    class Meta(object):
        db_table = 'experiment_test_group'

    def __str__(self):
        return "%s: %s" % (self.type, self.value)


class ExperimentActionManager(GetInstanceMixin, JuloModelManager):
    pass


class ExperimentAction(TimeStampedModel):
    TYPELIST = {
        'CHANGE_STATUS': 'CHANGE_STATUS',
        'ADD_NOTE': 'ADD_NOTE',
        'CHANGE_CREDIT': 'CHANGE_CREDIT',
    }

    id = models.AutoField(db_column='experiment_action_id', primary_key=True)
    experiment = models.ForeignKey(Experiment, models.DO_NOTHING, db_column='experiment_id')
    type = models.CharField(max_length=100)
    value = models.CharField(max_length=500)

    objects = ExperimentTestGroupManager()

    class Meta(object):
        db_table = 'experiment_action'

    def __str__(self):
        return "%s: %s" % (self.type, self.value)


class ApplicationExperimentManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationExperiment(TimeStampedModel):
    id = models.AutoField(db_column='application_experiment_id', primary_key=True)
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    experiment = models.ForeignKey(Experiment, models.DO_NOTHING, db_column='experiment_id')

    objects = ApplicationExperimentManager()

    class Meta(object):
        db_table = 'application_experiment'


class LenderDisburseCounterManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderDisburseCounter(TimeStampedModel):
    id = models.AutoField(db_column='lender_disburse_counter_id', primary_key=True)
    lender = models.OneToOneField('followthemoney.LenderCurrent',
                                  models.DO_NOTHING,
                                  db_column='lender_id',
                                  blank=True, null=True)
    partner = models.OneToOneField(Partner,
                                   on_delete=models.CASCADE,
                                   db_column='partner_id',
                                   blank=True, null=True)
    actual_count = models.BigIntegerField(default=0)
    rounded_count = models.IntegerField(default=0)

    objects = LenderDisburseCounterManager()

    class Meta(object):
        db_table = 'lender_counter'


# model for dynamic statuses
class WorkflowStatusPathManager(GetInstanceMixin, JuloModelManager):
    pass


class WorkflowStatusPath(TimeStampedModel):
    TYPE_CHOICES = (
        ('happy', 'happy'),
        ('detour', 'detour'),
        ('graveyard', 'graveyard'),
        ('force', 'force'),
    )

    id = models.AutoField(db_column='workflow_status_path_id', primary_key=True)
    status_previous = models.IntegerField(db_column='status_previous_code')
    status_next = models.IntegerField(db_column='status_next_code')
    type = models.CharField(max_length=50, null=True, blank=True,
                            choices=TYPE_CHOICES)  # happy, correctional, graveyard
    is_active = models.BooleanField(default=True)
    workflow = models.ForeignKey(
        'Workflow', models.DO_NOTHING, db_column='workflow_id')
    customer_accessible = models.BooleanField(default=False)
    agent_accessible = models.BooleanField(default=True)

    objects = WorkflowStatusPathManager()

    class Meta(object):
        db_table = 'workflow_status_path'


class WorkflowStatusNodeManager(GetInstanceMixin, JuloModelManager):
    pass


class WorkflowStatusNode(TimeStampedModel):
    id = models.AutoField(db_column='workflow_status_node_id', primary_key=True)
    status_node = models.IntegerField()
    workflow = models.ForeignKey(
        'Workflow', models.DO_NOTHING, db_column='workflow_id')
    # Class of actions will be executed
    handler = models.CharField(max_length=100, null=True, blank=True)

    objects = WorkflowStatusNodeManager()

    class Meta(object):
        db_table = 'workflow_status_node'


class WorkflowManager(GetInstanceMixin, JuloModelManager):
    pass


class Workflow(TimeStampedModel):
    id = models.AutoField(db_column='workflow_id', primary_key=True)
    name = models.CharField(max_length=50)
    desc = models.TextField(blank=True, null=True)  # Optional longer description
    is_active = models.BooleanField(default=True)
    # Class of actions will be executed
    handler = models.CharField(max_length=100, null=True, blank=True)

    objects = WorkflowManager()

    class Meta(object):
        db_table = 'workflow'

    def __str__(self):
        return self.name


class ChangeReasonManager(GetInstanceMixin, JuloModelManager):
    pass


class ChangeReason(TimeStampedModel):
    id = models.AutoField(db_column='change_reason_id', primary_key=True)
    reason = models.TextField()
    status = models.ForeignKey('StatusLookup', models.DO_NOTHING, db_column='change_reason_status')
    objects = ChangeReasonManager()

    class Meta(object):
        db_table = 'change_reason'


class WorkflowFailureActionManager(GetInstanceMixin, JuloModelManager):
    pass


class WorkflowFailureAction(TimeStampedModel):
    id = models.AutoField(db_column='workflow_failure_action_id', primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    action_name = models.CharField(max_length=200)
    action_type = models.CharField(max_length=100)
    arguments = ArrayField(models.CharField(max_length=300))
    task_id = models.CharField(max_length=200, null=True)
    error_message = models.TextField(null=True)
    is_recalled_succeed = models.NullBooleanField()
    recalled_counter = models.IntegerField(default=0, null=True)

    objects = WorkflowFailureActionManager()

    class Meta(object):
        db_table = 'workflow_failure_action'
        managed = False


class ApplicationWorkflowSwitchHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationWorkflowSwitchHistory(TimeStampedModel):
    id = models.AutoField(db_column='application_workflow_switch_history_id', primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    workflow_old = models.CharField(max_length=200)
    workflow_new = models.CharField(max_length=200)
    # maintainer for help
    changed_by = CurrentUserField()
    change_reason = models.TextField(default="system_triggered")

    objects = ApplicationWorkflowSwitchHistoryManager()

    class Meta(object):
        db_table = 'application_workflow_switch_history'
        managed = False


class LoanPurposeManager(GetInstanceMixin, JuloModelManager):
    pass


class LoanPurpose(TimeStampedModel):
    id = models.AutoField(db_column='loan_purpose_id', primary_key=True)
    version = models.CharField(max_length=20)
    purpose = models.CharField(max_length=200)
    product_lines = models.ManyToManyField(
        'ProductLine', through='ProductLineLoanPurpose', related_name='loan_purposes')

    objects = LoanPurposeManager()

    class Meta(object):
        db_table = 'loan_purpose'

    def __str__(self):
        return self.purpose


class ProductLineLoanPurposeManager(GetInstanceMixin, JuloModelManager):
    pass


class ProductLineLoanPurpose(models.Model):
    product_line = models.ForeignKey('ProductLine', db_column='product_line_id')
    loan_purpose = models.ForeignKey('LoanPurpose', db_column='loan_purpose_id')

    objects = ProductLineLoanPurposeManager()

    class Meta(object):
        db_table = 'product_line_loan_purpose'

    def __str__(self):
        return str(self.product_line) + " --> " + self.loan_purpose.purpose


class CustomerWalletNote(TimeStampedModel):
    id = models.AutoField(db_column='customer_wallet_note_id', primary_key=True)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')
    customer_wallet_history = models.ForeignKey(
        CustomerWalletHistory, models.DO_NOTHING, db_column='customer_wallet_history_id',
        blank=True, null=True)
    note_text = models.TextField()
    added_by = CurrentUserField()

    class Meta(object):
        db_table = 'customer_wallet_note'


class CrmNavlog(TimeStampedModel):
    id = models.AutoField(db_column='crm_navlog_id', primary_key=True)
    page_url = models.TextField(blank=True, null=True)
    referrer_url = models.TextField(blank=True, null=True)
    user = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(blank=True, null=True)
    element = models.TextField(blank=True, null=True)
    path = models.TextField(blank=True, null=True)
    event = models.CharField(max_length=100, blank=True, null=True)

    class Meta(object):
        db_table = 'crm_navlog'


class StatusLabelManager(GetInstanceMixin, JuloModelManager):
    pass


class StatusLabel(TimeStampedModel):
    id = models.AutoField(db_column='status_label_id', primary_key=True)
    status = models.IntegerField()
    label_name = models.CharField(max_length=100)
    label_colour = models.CharField(max_length=100)

    objects = StatusLabelManager()

    class Meta(object):
        db_table = 'status_label'

    def __str__(self):
        return " - ".join([str(self.status), self.label_name])


class VoiceCallRecordQuerySet(CustomQuerySet):
    def by_identifier(self, voice_identifier):
        return self.filter(payment_id=voice_identifier)

    def by_date(self, date):
        return self.filter(cdate__date=date)


class VoiceCallRecordManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return VoiceCallRecordQuerySet(self.model)

    def identifier_count_by_date(self, voice_identifier, date):
        return self.get_queryset().by_identifier(voice_identifier).by_date(date).count()

    def get_last_account_calls_with_event_type(self, account_id):
        queryset = self.get_queryset().filter(
            application__account_id=account_id
        ).distinct(
            'application__account_id', 'event_type'
        ).order_by(
            'application__account_id', 'event_type', '-udate'
        ).all()
        return list(queryset)

    def get_last_account_payment_calls(self, account_payment_ids):
        account_payment_ids = account_payment_ids if isinstance(account_payment_ids, list) else \
            [account_payment_ids]
        qs = self.get_queryset().filter(
            account_payment_id__in=account_payment_ids
        ).distinct(
            'account_payment_id',
        ).order_by(
            'account_payment_id', '-udate'
        ).all()
        return list(qs)

    def get_last_call_by_template(self, template_code, account_payment_id):
        return (
            self.get_queryset()
            .filter(
                account_payment_id=account_payment_id,
                template_code=template_code,
                conversation_uuid__isnull=False,
            )
            .last()
        )


class VoiceCallRecord(PIIVaultModel):
    PII_FIELDS = ['call_to']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = CollectionQueue.TOKENIZED_QUEUE

    id = models.AutoField(db_column='voice_call_id', primary_key=True)
    event_type = models.TextField(blank=True, null=True)
    voice_identifier = models.BigIntegerField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    direction = models.TextField(blank=True, null=True)
    uuid = models.TextField()
    conversation_uuid = models.TextField(db_index=True)
    call_from = models.TextField(blank=True, null=True)
    call_to = models.TextField(blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    duration = models.TextField(blank=True, null=True)
    call_rate = models.TextField(blank=True, null=True)
    call_price = models.TextField(blank=True, null=True)
    answer = models.TextField(blank=True, null=True)
    is_experiment = models.NullBooleanField(default=False, blank=True, null=True)
    experiment_id = models.IntegerField(null=True)
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column='application_number',
                                    blank=True, null=True)
    success_threshold = models.CharField(max_length=10, blank=True, null=True)
    template_code = models.CharField(max_length=250, null=True, blank=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    voice_style_id = models.SmallIntegerField(blank=True, null=True)
    comms_provider = models.ForeignKey('CommsProviderLookup', models.DO_NOTHING,
                                       db_column='comms_provider_lookup_id', blank=True, null=True)
    call_to_tokenized = models.TextField(blank=True, null=True)

    objects = VoiceCallRecordManager()

    class Meta(object):
        db_table = 'voice_call_record'

    def save(self, *args, **kwargs):
        # before create
        if not self.pk:
            payment = Payment.objects.get_or_none(pk=self.voice_identifier)
            if payment:
                self.application = payment.loan.application
        super(VoiceCallRecord, self).save(*args, **kwargs)


class PrimoDialerRecordManager(GetInstanceMixin, JuloModelManager):
    pass


class PrimoDialerRecord(TimeStampedModel):
    id = models.AutoField(db_column='primo_dialer_record_id', primary_key=True)
    application = models.ForeignKey('Application', models.DO_NOTHING,
                                    db_column='application_id', blank=True, null=True)
    payment = models.ForeignKey('Payment', models.DO_NOTHING, db_column='payment_id',
                                blank=True, null=True)
    call_status = models.CharField(max_length=20, blank=True, null=True)
    application_status = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='application_status_code',
        blank=True, null=True)
    payment_status = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='payment_status_code',
        related_name='payment_status_code', blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    agent = models.CharField(max_length=20, blank=True, null=True)
    lead_status = models.CharField(null=True, blank=True, max_length=20)
    lead_id = models.IntegerField(null=True)
    list_id = models.IntegerField(null=True)
    retry_times = models.IntegerField(null=True, default=0)
    skiptrace = models.ForeignKey(
        'Skiptrace', on_delete=models.DO_NOTHING, db_column='skiptrace_id', null=True)

    objects = PrimoDialerRecordManager()

    class Meta(object):
        db_table = 'primo_dialer_record'

    def __str__(self):
        """Visual identification"""
        return " - ".join([str(self.id), self.phone_number])


class PartnerAccountAttributionManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnerAccountAttribution(TimeStampedModel):
    id = models.AutoField(db_column='partner_account_attribution_id', primary_key=True)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')
    partner = models.ForeignKey(
        Partner, models.DO_NOTHING, db_column='partner_id')
    partner_referral = models.ForeignKey(
        PartnerReferral, models.DO_NOTHING, db_column='partner_referral_id',
        blank=True, null=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    partner_account_id = models.CharField(null=True, blank=True, max_length=50)

    objects = PartnerAccountAttributionManager()

    def get_rules_is_blank(self):
        return self.partner.partneraccountattributionsetting_set.first().is_blank

    class Meta(object):
        db_table = 'partner_account_attribution'


class PartnerAccountAttributionSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnerAccountAttributionSetting(TimeStampedModel):
    id = models.AutoField(db_column='partner_account_attribution_setting_id', primary_key=True)
    partner = models.ForeignKey(
        Partner, models.DO_NOTHING, db_column='partner_id')
    is_uniqe = models.BooleanField(default=True)
    is_blank = models.BooleanField(default=True)

    objects = PartnerAccountAttributionSettingManager()

    class Meta(object):
        db_table = 'partner_account_attribution_setting'


class ApplicationScrapeAction(TimeStampedModel):
    id = models.AutoField(db_column='application_scrape_action_id', primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    url = models.CharField(max_length=100)
    scrape_type = models.CharField(max_length=10)

    class Meta(object):
        db_table = 'application_scrape_action'
        managed = False


class BcaTransactionRecordManager(GetInstanceMixin, JuloModelManager):
    pass


class BcaTransactionRecord(TimeStampedModel):
    id = models.AutoField(db_column='bca_transaction_id', primary_key=True)
    transaction_date = models.DateField()
    reference_id = models.CharField(max_length=20)
    currency_code = models.CharField(max_length=10)
    amount = models.IntegerField()
    beneficiary_account_number = models.CharField(max_length=100)
    remark1 = models.CharField(max_length=100)
    status = models.CharField(max_length=100, null=True, blank=True)
    error_code = models.CharField(max_length=50, null=True, blank=True)

    objects = BcaTransactionRecordManager()

    class Meta(object):
        db_table = 'bca_transaction_record'


class MobileFeatureSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class MobileFeatureSetting(TimeStampedModel):
    id = models.AutoField(db_column='mobile_feature_setting_id', primary_key=True)

    feature_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    parameters = JSONField(blank=True, null=True)

    objects = MobileFeatureSettingManager()

    class Meta(object):
        db_table = 'mobile_feature_setting'

    def __str__(self):
        return self.feature_name


class FeatureSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class FeatureSetting(TimeStampedModel):
    id = models.AutoField(db_column='feature_setting_id', primary_key=True)

    feature_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)
    parameters = JSONField(blank=True, null=True)
    category = models.CharField(max_length=100)
    description = models.CharField(max_length=200)

    objects = FeatureSettingManager()

    class Meta(object):
        db_table = 'feature_setting'

    def clean(self):
        if self.feature_name == FeatureNameConst.MYCROFT_SCORE_CHECK and self.is_active:
            if not MycroftThreshold.objects.filter(is_active=True).exists():
                raise ValidationError(
                    'Cannot activate feature. At least one active MycroftThreshold is required.')

        if self.category == 'traffic_ratio':
            if not self.parameters:
                raise Exception('for traffic ratio caegory parameters could not be empty')
            ratio_type = 'multiplier'
            sum_ratio = 0
            for key, val in list(self.parameters.items()):
                sum_ratio += val
            if sum_ratio > 1 or sum_ratio < 1:
                raise Exception('sum of ratio in the parameter should be 1')

    def save(self, *args, **kwargs):
        self.clean()
        super(FeatureSetting, self).save(*args, **kwargs)  # Call the "real"

    @classmethod
    def fetch_feature_state(cls, feature_name: str):
        return cls.objects.get(feature_name=feature_name).is_active

    def __str__(self):
        return self.feature_name


class AgentAssignmentManager(GetInstanceMixin, JuloModelManager):
    pass


class AgentAssignmentOld(TimeStampedModel):
    id = models.AutoField(db_column='agent_assignment_id', primary_key=True)
    application = models.ForeignKey('Application',
                                    models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    payment = models.ForeignKey('Payment',
                                models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    loan = models.ForeignKey('Loan',
                             models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                              on_delete=models.CASCADE, db_column='agent_id', blank=True, null=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='collected_by', related_name='collected_by', blank=True, null=True)
    collect_date = models.DateField(blank=True, null=True)
    assign_time = models.DateTimeField(blank=True, null=True)
    unassign_time = models.DateTimeField(blank=True, null=True, db_index=True)
    type = models.CharField(max_length=50, blank=True, null=True)

    objects = AgentAssignmentManager()

    class Meta(object):
        db_table = 'agent_assignment_old'


class CollectionAgentAssignmentManager(GetInstanceMixin, JuloModelManager):
    pass


class CollectionAgentAssignment(TimeStampedModel):
    """
        Agent Assignment 2.0
        Keeps log of agent assignments
    """
    id = models.AutoField(db_column='collection_agent_assignment_id', primary_key=True)
    loan = models.ForeignKey('Loan',
                             models.DO_NOTHING,
                             db_column='loan_id',
                             blank=True,
                             null=True)
    payment = models.ForeignKey('Payment',
                                models.DO_NOTHING,
                                db_column='payment_id',
                                blank=True,
                                null=True)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                              on_delete=models.CASCADE,
                              db_column='agent_id',
                              blank=True,
                              null=True)
    assign_time = models.DateTimeField(blank=True, null=True)
    unassign_time = models.DateTimeField(blank=True, null=True, db_index=True)
    type = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    on_delete=models.CASCADE,
                                    related_name="assigned_by",
                                    db_column='assigned_by',
                                    blank=True,
                                    null=True)

    objects = CollectionAgentAssignmentManager()

    class Meta(object):
        db_table = 'collection_agent_assignment'

    def __str__(self):
        return "{loan}:{user}:{type}".format(loan=self.loan.id,
                                             user=self.agent.username,
                                             type=self.type)


class SphpTemplate(TimeStampedModel):
    sphp_template = models.TextField(blank=True, null=True)
    product_name = models.CharField(max_length=100)


class Autodialer122QueueManager(GetInstanceMixin, JuloModelManager):
    def get_uncalled_app(self):
        autodialer122 = Autodialer122Queue.objects.filter(
            is_agent_called=False,
            auto_call_result_status__in=['answered', 'busy'])
        return autodialer122


class Autodialer122Queue(TimeStampedModel):
    id = models.AutoField(db_column='autodialer_122_queue_id', primary_key=True)
    application = models.OneToOneField('Application',
                                       models.DO_NOTHING,
                                       db_column='application_id',
                                       blank=True,
                                       null=True)
    company_phone_number = models.CharField(
        max_length=50, blank=True, null=True, validators=[ascii_validator])
    auto_call_result_status = models.CharField(max_length=50, blank=True, null=True)
    is_agent_called = models.BooleanField(default=False)
    attempt = models.IntegerField(blank=True, null=True)
    conversation_uuid = models.CharField(max_length=150, blank=True, null=True)

    objects = Autodialer122QueueManager()

    class Meta(object):
        db_table = 'autodialer_122_queue'


class NexmoAutocallHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class NexmoAutocallHistory(TimeStampedModel):
    id = models.AutoField(db_column='nexmo_autocall_history_id', primary_key=True)
    application_history = models.ForeignKey('ApplicationHistory',
                                            models.DO_NOTHING,
                                            db_column='application_history_id',
                                            blank=True,
                                            null=True)
    company_phone_number = models.CharField(
        max_length=50, blank=True, null=True, validators=[ascii_validator])
    auto_call_result_status = models.CharField(max_length=50, blank=True, null=True)
    conversation_uuid = models.CharField(max_length=150, blank=True, null=True)

    objects = NexmoAutocallHistoryManager()

    class Meta(object):
        db_table = 'nexmo_autocall_history'


class AutodialerSessionQueryset(CustomQuerySet):
    pass


class AutodialerSessionManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return AutodialerSessionQueryset(self.model)


class AutodialerSession(TimeStampedModel):
    id = models.AutoField(db_column='autodialer_session_id', primary_key=True)
    failed_count = models.IntegerField(default=0)
    next_session_ts = models.DateTimeField(blank=True, null=True)
    status = models.IntegerField()
    application = models.ForeignKey(Application,
                                    models.DO_NOTHING,
                                    db_column='application_id')

    objects = AutodialerSessionManager()

    class Meta(object):
        db_table = 'autodialer_session'
        unique_together = ('application', 'status')


class AutodialerCallResultManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class AutodialerCallResult(PIIVaultModel):
    id = models.AutoField(db_column='autodialer_call_result_id', primary_key=True)
    agent = CurrentUserField()
    action = models.CharField(max_length=100)
    autodialer_session = models.ForeignKey(
        AutodialerSession, models.DO_NOTHING, db_column='autodialer_session_id')
    phone_number = NoValidatePhoneNumberField(null=True, blank=True)

    # PII attributes
    phone_number_tokenized = models.TextField(null=True, blank=True)
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV

    objects = AutodialerCallResultManager()

    class Meta(object):
        db_table = 'autodialer_call_result'


class AutodialerActivityHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class AutodialerActivityHistory(TimeStampedModel):
    id = models.AutoField(db_column='autodialer_activity_history_id', primary_key=True)
    agent = CurrentUserField()
    action = models.CharField(max_length=100)
    autodialer_session_status = models.ForeignKey(AutodialerSessionStatus,
                                                  models.DO_NOTHING,
                                                  db_column='autodialer_session_status_id',
                                                  null=True,
                                                  blank=True)
    autodialer_session = models.ForeignKey(AutodialerSession,
                                           models.DO_NOTHING,
                                           db_column='autodialer_session_id',
                                           null=True,
                                           blank=True)

    objects = AutodialerActivityHistoryManager()

    class Meta(object):
        db_table = 'autodialer_activity_history'


class MassMoveApplicationsHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class MassMoveApplicationsHistory(TimeStampedModel):
    id = models.AutoField(db_column='mass_move_applications_history_id', primary_key=True)
    filename = models.CharField(max_length=200, unique=True)
    agent = CurrentUserField()
    result = JSONField(blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    objects = MassMoveApplicationsHistoryManager()

    class Meta(object):
        db_table = 'mass_move_applications_history_id'


class WarningUrl(TimeStampedModel):
    id = models.AutoField(db_column='warning_url_id', primary_key=True)

    customer = models.ForeignKey('Customer',
                                 models.DO_NOTHING, db_column='customer_id')
    url = models.CharField(max_length=300, blank=True, null=True)
    warning_method = models.IntegerField(default=1)
    is_enabled = models.BooleanField(default=True)
    url_type = models.CharField(
        max_length=10,
        choices=(("email", "email"), ("sms", "sms")),
        default="email", )

    @property
    def short_url(self):
        return truncatechars(self.url, 30)


class PaymentReminderCallLogsQuerySet(CustomQuerySet):
    def success(self, payment_id):
        return self.filter(payment_id=payment_id, answer='1')

    def by_date(self, date):
        return self.filter(cdate__date=date)


class PaymentReminderCallLogsManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return PaymentReminderCallLogsQuerySet(self.model)

    def success_count_by_date(self, payment_id, date):
        return self.get_queryset().success(payment_id).by_date(date).count()


class PaymentReminderCallLogs(TimeStampedModel):
    id = models.AutoField(db_column='payment_reminder_call_log_id', primary_key=True)
    payment = models.ForeignKey('Payment', models.DO_NOTHING)
    call_id = models.CharField(max_length=300, blank=True, null=True)
    answer = models.CharField(max_length=300, blank=True, null=True)


class PredictiveMissedCallManager(GetInstanceMixin, JuloModelManager):
    def get_uncalled_app(self, status):
        queues = self.filter(
            is_agent_called=False,
            auto_call_result_status__in=['answered', 'busy'],
            application_status=status
        )
        return queues


class PredictiveMissedCall(TimeStampedModel):
    id = models.AutoField(db_column='predictive_missed_call_id', primary_key=True)
    application = models.ForeignKey('Application',
                                    models.DO_NOTHING,
                                    db_column='application_id',
                                    blank=True,
                                    null=True)
    phone_number = models.CharField(max_length=50, blank=True,
                                    null=True, validators=[ascii_validator])
    auto_call_result_status = models.CharField(max_length=50, blank=True, null=True)
    is_agent_called = models.BooleanField(default=False)
    attempt = models.IntegerField(blank=True, null=True)
    conversation_uuid = models.CharField(max_length=150, blank=True, null=True)
    application_status = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='application_status_id',
        blank=True, null=True)
    objects = PredictiveMissedCallManager()

    class Meta(object):
        db_table = 'predictive_missed_call'

    @property
    def moved_statuses(self):
        return []  # requirement updated

    @property
    def unmoved_statuses(self):
        return [124, 141, 172]  # requirement updated

    def moved_status_destinations(self, current_status):
        # if current_status in [124, 141, 172]: #requirement updated
        #     return 138
        return None


class ExperimentSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class ExperimentSetting(TimeStampedModel):
    TYPELIST = {
        'application': 'application',
        'loan': 'loan',
        'payment': 'payment',
        'firebase': 'firebase',
    }
    id = models.AutoField(db_column='experiment_setting_id', primary_key=True)
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=250)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    schedule = models.CharField(max_length=10, blank=True, null=True)
    action = models.CharField(max_length=255, blank=True, null=True)
    type = CharField(max_length=50)
    criteria = JSONField()
    is_active = models.BooleanField(default=False)
    is_permanent = models.BooleanField(default=False)

    objects = ExperimentSettingManager()

    class Meta(object):
        db_table = 'experiment_setting'


class PaymentExperiment(TimeStampedModel):
    id = models.AutoField(db_column='payment_experiment_id', primary_key=True)
    experiment_setting = models.ForeignKey('ExperimentSetting',
                                           models.DO_NOTHING,
                                           db_column='experiment_setting_id')
    payment = models.ForeignKey('Payment',
                                models.DO_NOTHING,
                                db_column='payment_id')
    note_text = models.TextField()

    class Meta(object):
        db_table = 'payment_experiment'


class PartnerBankAccount(TimeStampedModel):
    id = models.AutoField(db_column='partner_bank_account_id', primary_key=True)
    partner = models.ForeignKey(
        Partner, models.DO_NOTHING, db_column='partner_id')
    bank_name = models.CharField(max_length=250,
                                 validators=[ascii_validator],
                                 blank=True, null=True)
    bank_branch = models.CharField(max_length=100,
                                   validators=[ascii_validator],
                                   blank=True, null=True)
    bank_account_number = models.CharField(max_length=50,
                                           validators=[ascii_validator],
                                           blank=True, null=True)
    name_in_bank = models.CharField(max_length=100,
                                    validators=[ascii_validator],
                                    blank=True, null=True)
    phone_number = NoValidatePhoneNumberField()
    distribution = models.FloatField(blank=True, null=True)
    distributor_id = models.IntegerField(null=True, blank=True)
    name_bank_validation_id = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'partner_bank_account'


class LoanDisburseInvoices(TimeStampedModel):
    id = models.AutoField(db_column='loan_disburse_invoices_id', primary_key=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    disbursement_id = models.BigIntegerField(null=True, blank=True)
    name_bank_validation_id = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'loan_disburse_invoices'


class FaqSection(TimeStampedModel):
    id = models.AutoField(db_column='faq_section_id', primary_key=True)
    title = models.CharField(max_length=250)
    order_priority = models.IntegerField(default=0)
    visible = models.BooleanField(default=True)
    is_security_faq = models.BooleanField(default=False)

    class Meta(object):
        ordering = ('order_priority', 'visible',)
        db_table = 'faq_section'

    def __str__(self):
        return "%s, %s" % (self.order_priority, self.title)


class FaqItemManager(GetInstanceMixin, JuloModelManager):
    pass


class FaqItem(GetInstanceMixin, TimeStampedModel):
    id = models.AutoField(db_column='faq_item_id', primary_key=True)
    section = models.ForeignKey(FaqSection, related_name="faq_items")
    question = models.CharField(max_length=250)
    link_url = models.URLField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    rich_text = RichTextField(blank=True, null=True)
    sub_title = models.CharField(max_length=250, blank=True, null=True)
    order_priority = models.IntegerField(default=0)
    visible = models.BooleanField(default=True)
    show_security_faq_report_button = models.BooleanField(default=False)
    objects = FaqItemManager()

    class Meta(object):
        ordering = ('order_priority', 'visible',)
        db_table = 'faq_item'

    def __str__(self):
        return "%s, %s" % (self.order_priority, self.question)


class FaqSubTitle(TimeStampedModel):
    id = models.AutoField(db_column='faq_subtitle_id', primary_key=True)
    faq = models.ForeignKey(FaqItem, related_name="sub_titles")
    title = models.CharField(max_length=250)
    link_url = models.URLField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    rich_text = RichTextField(blank=True, null=True)
    order_priority = models.IntegerField(default=0)
    visible = models.BooleanField(default=True)

    class Meta(object):
        ordering = ('order_priority', 'visible',)
        db_table = 'faq_subtitle'

    def __str__(self):
        return "%s, %s visible:%s" % (self.order_priority, self.title, self.visible)


class JuloContactDetail(TimeStampedModel):
    id = models.AutoField(db_column='julo_contact_details_id', primary_key=True)
    section = models.ForeignKey(FaqSection, related_name="faq_contact", blank=True, null=True)
    title = models.CharField(max_length=250)
    link_url = models.URLField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    show_image = models.BooleanField(default=True)
    description = models.TextField()
    rich_text = RichTextField(blank=True, null=True)
    chat_availability = JSONField(blank=True, null=True)
    email_ids = ArrayField(models.EmailField(), blank=True, null=True)
    phone_numbers = ArrayField(models.CharField(max_length=50, validators=[
                               ascii_validator]), blank=True, null=True)
    contact_us_text = models.CharField(max_length=250, blank=True, null=True)
    address = models.CharField(max_length=250, blank=True, null=True)
    order_priority = models.IntegerField(default=0)
    visible = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'julo_contact_detail'

    def __str__(self):
        return "Julo Contact Detail"


# table partner purchase items for laku6
class PartnerPurchaseItem(TimeStampedModel):
    id = models.AutoField(db_column='partner_bank_account_id', primary_key=True)
    partner = models.ForeignKey(
        Partner, models.DO_NOTHING, db_column='partner_id')
    application_xid = models.BigIntegerField(blank=True, null=True)
    device_name = models.CharField(max_length=250, validators=[
                                   ascii_validator], blank=True, null=True)
    device_price = models.CharField(max_length=50, validators=[
                                    ascii_validator], blank=True, null=True)
    device_trade = models.CharField(max_length=100, validators=[
                                    ascii_validator], blank=True, null=True)
    down_payment = models.CharField(max_length=50, validators=[
                                    ascii_validator], blank=True, null=True)
    admin_fee = models.CharField(max_length=50, validators=[ascii_validator], blank=True, null=True)
    agent_id = models.CharField(max_length=50, validators=[ascii_validator], blank=True, null=True)
    store_id = models.CharField(max_length=50, validators=[ascii_validator], blank=True, null=True)
    invoices = models.CharField(max_length=50, validators=[ascii_validator], blank=True, null=True)
    package_name = models.CharField(max_length=50, validators=[
                                    ascii_validator], blank=True, null=True)
    package_price = models.CharField(max_length=50, validators=[
                                     ascii_validator], blank=True, null=True)
    insurance_name = models.CharField(max_length=50, validators=[
                                      ascii_validator], blank=True, null=True)
    insurance_price = models.CharField(max_length=50, validators=[
                                       ascii_validator], blank=True, null=True)
    e_policy_number = models.CharField(max_length=50, validators=[
                                       ascii_validator], blank=True, null=True)
    imei_number = models.CharField(max_length=50, validators=[
                                   ascii_validator], blank=True, null=True)
    phone_number = models.CharField(max_length=50, validators=[
                                    ascii_validator], blank=True, null=True)
    contract_number = models.CharField(max_length=50, validators=[
                                       ascii_validator], blank=True, null=True)

    class Meta(object):
        db_table = 'partner_purchase_item'
        unique_together = (('id', 'partner', 'application_xid'),)

class InAppPTPHistory(TimeStampedModel):
    id = models.AutoField(db_column='in_app_ptp_history_id', primary_key=True)
    card_appear_dpd = models.IntegerField(blank=True, null=True)
    dpd = models.IntegerField(blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    payment_method = models.ForeignKey(
        PaymentMethod, models.DO_NOTHING,
        db_column='payment_method_id',
        blank=True,
        null=True)

    class Meta(object):
        db_table = 'in_app_ptp_history'

class PTP(TimeStampedModel):
    PTP_STATUS_CHOICES = (
        ('Paid', 'Paid'),
        ('Paid after ptp date', 'Paid after ptp date'),
        ('Partial', 'Partial'),
        ('Not Paid', 'Not Paid'))
    id = models.AutoField(db_column='ptp_id', primary_key=True)

    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    ptp_status = models.CharField(

        max_length=50, blank=True, null=True, choices=PTP_STATUS_CHOICES)
    agent_assigned = models.ForeignKey(settings.AUTH_USER_MODEL,
                                       on_delete=models.CASCADE, db_column='agent_id', blank=True, null=True)
    ptp_date = models.DateField(blank=True, null=True)
    ptp_amount = models.BigIntegerField(blank=True, default=0)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING,
        db_column='payment_id',
        blank=True,
        null=True)
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
    in_app_ptp_history = models.ForeignKey(
        InAppPTPHistory, models.DO_NOTHING,
        db_column='in_app_ptp_history_id',
        blank=True,
        null=True)
    ptp_parent = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True)

    class Meta(object):
        db_table = 'ptp'


class CreditScoreExperimentManager(GetInstanceMixin, JuloModelManager):
    pass


class CreditScoreExperiment(TimeStampedModel):
    id = models.AutoField(db_column='credit_score_experiment_id', primary_key=True)
    credit_score = models.ForeignKey(CreditScore, models.DO_NOTHING, db_column='credit_score_id')
    experiment = models.ForeignKey(Experiment, models.DO_NOTHING, db_column='experiment_id')
    objects = CreditScoreExperimentManager()

    class Meta(object):
        db_table = 'credit_score_experiment'


class FrontendView(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)
    label_name = models.CharField(max_length=200)
    label_value = models.CharField(max_length=200)
    label_code = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = 'frontend_view'


class EmailSetting(TimeStampedModel):
    id = models.AutoField(db_column='email_setting_id', primary_key=True)
    status_code = models.CharField(max_length=10, blank=True, null=True)
    partner_email_content = HTMLField(blank=True, null=True)
    customer_email_content = HTMLField(blank=True, null=True)
    enabled = models.BooleanField(default=False)
    objects = ModelExtensionManager()

    class Meta(object):
        db_table = 'email_setting'

    def __str__(self):
        return "trigger_status: %s, enabled: %s" % (self.status_code, self.enabled, )


class JuloCustomerEmailSetting(TimeStampedModel):
    id = models.AutoField(db_column='julo_customer_email_setting_id', primary_key=True)
    email_setting_link = models.OneToOneField(
        'EmailSetting', models.DO_NOTHING, db_column='email_setting_id',
        blank=True, null=True)
    send_email = models.BooleanField(default=False)
    attach_sphp = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    objects = ModelExtensionManager()

    class Meta(object):
        db_table = 'julo_customer_email_setting'

    def __str__(self):
        return "send_email: %s, attach_sphp: %s enabled: %s" % (self.send_email, self.attach_sphp, self.enabled,)


class PartnerEmailSetting(TimeStampedModel):
    id = models.AutoField(db_column='partner_email_setting_id', primary_key=True)
    email_setting_link = models.ForeignKey(
        'EmailSetting', models.DO_NOTHING, db_column='email_setting_id',
        blank=True, null=True)
    partner = models.ForeignKey(
        'Partner', models.DO_NOTHING, db_column='partner_id',
        blank=True, null=True)
    send_to_partner_customer = models.BooleanField(default=False)
    send_to_partner = models.BooleanField(default=False)
    partner_email_list = ArrayField(models.EmailField(), blank=True, null=True)
    attach_sphp_partner_customer = models.BooleanField(default=False)
    attach_sphp_partner = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    objects = ModelExtensionManager()

    class Meta(object):
        db_table = 'partner_email_setting'

    def __str__(self):
        return "%s, send_to_partner_customer: %s, send_to_partner: %s, enabled: %s" % (
            self.partner, self.send_to_partner_customer, self.send_to_partner, self.enabled, )


class PaymentHistory(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)
    application = models.ForeignKey('Application',
                                    models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING,
                                db_column='payment_id', blank=True, null=True)
    payment_number = models.IntegerField(blank=True, null=True)
    loan_old_status_code = models.IntegerField(blank=True, null=True)
    loan_new_status_code = models.IntegerField(blank=True, null=True)
    payment_old_status_code = models.IntegerField(blank=True, null=True)
    payment_new_status_code = models.IntegerField(blank=True, null=True)
    paid_amount = models.BigIntegerField(blank=True, null=True)
    due_amount = models.BigIntegerField(blank=True, null=True)
    paid_date = models.DateTimeField(blank=True, null=True)
    due_date = models.DateTimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'payment_history'


class WarningLetterHistory(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id', blank=True, null=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING,
                                db_column='payment_id', blank=True, null=True)
    warning_number = models.IntegerField(blank=True, null=True)
    loan_status_code = models.IntegerField(blank=True, null=True)
    payment_status_code = models.IntegerField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)

    total_due_amount = models.BigIntegerField(blank=True, null=True)
    event_type = models.CharField(max_length=75, blank=True, null=True)
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
    account_payment_status_code = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='account_payment_status_code',
        blank=True,
        null=True,
        related_name='account_payment_status_code'
    )
    account_status_code = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='account_status_code',
        blank=True,
        null=True,
        related_name='account_status_code'
    )
    warning_letter_number = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'warning_letter_history'


class VendorDataHistory(TimeStampedModel):
    id = models.AutoField(db_column='comms_data_id', primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id',
                                 blank=True,
                                 null=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING,
                             db_column='loan_id',
                             blank=True,
                             null=True)
    loan_status_code = models.IntegerField(blank=True, null=True)
    payment = models.ForeignKey(Payment,
                                models.DO_NOTHING,
                                db_column='payment_id',
                                blank=True,
                                null=True)
    reminder_type = models.CharField(max_length=100, blank=True, null=True)
    payment_status_code = models.IntegerField(blank=True, null=True)
    template_code = models.CharField(max_length=200, blank=True, null=True)
    vendor = models.CharField(max_length=100, blank=True, null=True, db_column='provider')
    called_at = models.BigIntegerField(blank=True, null=True)
    partner = models.ForeignKey(Partner, models.DO_NOTHING, db_column='partner_id',
                                blank=True, null=True)
    product = models.ForeignKey(ProductLine, models.DO_NOTHING, db_column='product_line_id',
                                blank=True, null=True)
    statement = models.ForeignKey('paylater.Statement', models.DO_NOTHING, db_column='statement_id',
                                  blank=True, null=True)
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
    account_payment_status_code = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'comms_data_history'


class WlLevelConfig(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)
    late_installment_count = models.IntegerField()
    wl_level = models.IntegerField()

    class Meta(object):
        db_table = 'wl_level_config'


class CustomerFieldChangeManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class CustomerFieldChange(PIIVaultModel):

    id = models.AutoField(db_column='customer_field_change_id', primary_key=True)
    customer = models.ForeignKey('Customer', models.DO_NOTHING, db_column='customer_id')
    field_name = models.CharField(max_length=100)
    old_value = models.CharField(max_length=200, blank=True, null=True)
    new_value = models.CharField(max_length=200, blank=True, null=True)
    old_value_tokenized = models.TextField(null=True, blank=True)
    new_value_tokenized = models.TextField(null=True, blank=True)
    changed_by = CurrentUserField()
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column='application_id',
                                    blank=True, null=True)
    PII_FIELDS = ['old_value','new_value']
    PII_TYPE = PIIType.KV
    objects = CustomerFieldChangeManager()

    class Meta(object):
        db_table = 'customer_field_change'


class AuthUserFieldChangeManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class AuthUserFieldChange(PIIVaultModel):
    id = models.AutoField(db_column='auth_user_field_change_id', primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.DO_NOTHING,
        db_column='auth_user_id')
    customer = models.ForeignKey('Customer', models.DO_NOTHING, db_column='customer_id')
    field_name = models.CharField(max_length=100)
    old_value = models.CharField(max_length=200, blank=True, null=True)
    new_value = models.CharField(max_length=200, blank=True, null=True)
    old_value_tokenized = models.TextField(null=True, blank=True)
    new_value_tokenized = models.TextField(null=True, blank=True)
    changed_by = CurrentUserField(related_name="user_changes")
    PII_FIELDS = ['old_value','new_value']
    PII_TYPE = PIIType.KV
    objects = AuthUserFieldChangeManager()

    class Meta(object):
        db_table = 'auth_user_field_change'


class SkiptraceHistoryCentereix(TimeStampedModel):
    id = models.AutoField(db_column='skiptrace_history_centereix_id', primary_key=True)
    campaign_name = models.TextField(null=True, blank=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING,
                                db_column='payment_id', blank=True, null=True)
    application = models.ForeignKey(Application,
                                    models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    statement = models.BigIntegerField(blank=True, null=True)
    loan_status = models.IntegerField(db_column='loan_status_code', null=True, blank=True)
    payment_status = models.IntegerField(db_column='payment_status_code', blank=True, null=True)
    contact_source = models.TextField(null=True, blank=True)
    phone_number = NoValidatePhoneNumberField(null=True, blank=True)
    status_group = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField(blank=True, null=True)
    agent_name = models.TextField(null=True, blank=True)
    spoke_with = models.TextField(null=True, blank=True)
    callback_time = models.CharField(max_length=12, blank=True, null=True)
    application_status = models.IntegerField(
        db_column='application_status_code', blank=True, null=True)
    non_payment_reason = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'skiptrace_history_centereix'


class DigisignConfiguration(TimeStampedModel):
    id = models.AutoField(db_column='digisign_configuration_id', primary_key=True)
    product_selection = models.CharField(max_length=50)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'digisign_configuration'


class DigisignConfigurationHistory(TimeStampedModel):
    id = models.AutoField(db_column='digisign_configuration_history_id', primary_key=True)
    product_selection = models.CharField(max_length=50)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'digisign_configuration_history'


class SignatureMethodHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class SignatureMethodHistory(TimeStampedModel):
    PRODUCT_SELECTIONS = (
        ("-", "-"),
        ("JULO", "JULO"),
        ("Digisign", "Digisign"),
    )
    id = models.AutoField(db_column='signature_method_history_id', primary_key=True)
    application = models.ForeignKey(Application,
                                    models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    signature_method = models.CharField(max_length=50, choices=PRODUCT_SELECTIONS, default="-")
    is_used = models.BooleanField(default=True)
    partner_id = models.ForeignKey(Partner,
                                   models.DO_NOTHING, db_column='partner_id',
                                   blank=True, null=True)
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    objects = SignatureMethodHistoryManager()

    class Meta(object):
        db_table = 'signature_method_history'


class BankManager(GetInstanceMixin, JuloModelManager):
    def regular_bank(self):
        return self.exclude(bank_code='gopay').exclude(is_active=False)

    def get_bank_names_and_xfers_bank_code(self):
        return self.values('bank_name', 'xfers_bank_code')


class Bank(TimeStampedModel):
    id = models.AutoField(db_column='bank_id', primary_key=True)
    bank_code = models.CharField(max_length=50, blank=True, null=True)
    bank_name = models.CharField(max_length=150, blank=True, null=True)
    min_account_number = models.IntegerField(blank=True, null=True)
    xendit_bank_code = models.CharField(max_length=100, blank=True, null=True)
    instamoney_bank_code = models.CharField(max_length=100, blank=True, null=True)
    xfers_bank_code = models.CharField(max_length=100, blank=True, null=True)
    swift_bank_code = models.CharField(max_length=100, blank=True, null=True)
    order_position = models.IntegerField(blank=True, null=True)
    bank_name_frontend = models.CharField(max_length=150, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    objects = BankManager()

    class Meta(object):
        db_table = 'bank'

    @property
    def bank_logo(self):
        if self.xfers_bank_code not in BankNameWithLogo.LIST_BANK:
            return
        return settings.BANK_LOGO_STATIC_FILE_PATH + '{}.png'.format(self.xfers_bank_code)

    def __repr__(self) -> str:
        return f'{self.bank_name} -- id: {self.id}'

    def __str__(self):
        return f'{self.bank_name}'


class NotificationTemplate(TimeStampedModel):
    id = models.AutoField(db_column='notification_id', primary_key=True)
    title = models.CharField(max_length=100)
    body = models.TextField()
    LIST_DESTINATION_PAGE = [
        ('com.julofinance.juloapp_HOME| ', 'Home Screen'),
        ('com.julofinance.juloapp_HOME|activity_loan', 'Activity Screen - activity_loan'),
        ('com.julofinance.juloapp_HOME|loc_installment', 'Activity Screen - loc_installment'),
        ('com.julofinance.juloapp_HOME|scrape_status', 'Product selection - scrape_status'),
        ('com.julofinance.juloapp_HOME|product_selection', 'Product selection - product_selection'),
        ('com.julofinance.juloapp_CASHBACK_RESULT|cashback_transaction', 'Cashback Activity'),
        ('com.julofinance.juloapp_HOME|rating_page', 'Rating popup Home Screen'),
        ('com.julofinance.juloapp_REGISTER_V3|register_v3', 'Application v3 Main Page'),
        ('com.julofinance.juloapp_HOME|sphp_page', 'SPHP'),
        ('com.julofinance.juloapp_HOME|document_v3', 'Document Submission'),
        ('com.julofinance.juloapp_HOME|rating_playstore', 'Rating popup Play Store'),
    ]
    click_action = models.CharField(max_length=200, blank=True,
                                    default='com.julofinance.juloapp_HOME')
    destination_page = models.CharField(max_length=100, choices=LIST_DESTINATION_PAGE)
    notification_code = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = 'notification_templates'

    def save(self):
        # first index for click action second one for destination page
        action_page = self.destination_page.split('|')
        self.click_action = action_page[0]
        self.destination_page = action_page[1]
        super(NotificationTemplate, self).save()

    def __str__(self):
        """Visual identification"""
        return self.title


class ReferralCampaign(TimeStampedModel):
    id = models.AutoField(db_column='referral_campaign_id', primary_key=True)
    referral_code = models.CharField(max_length=20, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    class Meta(object):
        db_table = 'referral_campaign'


class OpsTeamLeadStatusChangeManager(GetInstanceMixin, JuloModelManager):
    pass


class OpsTeamLeadStatusChange(TimeStampedModel):
    id = models.AutoField(db_column='ops_team_lead_status_change_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, models.DO_NOTHING,
        db_column='auth_user_id')
    change_reason = models.CharField(default="system_triggered", max_length=100)
    change_reason_detail = models.CharField(default="system_triggered", max_length=255)

    objects = OpsTeamLeadStatusChangeManager()

    class Meta(object):
        db_table = 'ops_team_lead_status_change'

    def __str__(self):
        """Visual identification"""
        return "%s %s" % (self.application, self.change_reason)


class ReferralSystem(TimeStampedModel):
    id = models.AutoField(db_column='referral_system_id', primary_key=True)
    product_code = ArrayField(models.IntegerField(), blank=True, null=True)
    partners = ArrayField(models.CharField(max_length=200), blank=True, null=True)
    caskback_amount = models.BigIntegerField(blank=True, null=True)
    referee_cashback_amount = models.BigIntegerField(blank=True, null=True, default=0)
    is_active = models.BooleanField(default=False)
    name = models.CharField(max_length=50, blank=True, null=True)
    activate_referee_benefit = models.BooleanField(default=False)
    extra_data = JSONField(null=True, blank=True)
    minimum_transaction_amount = models.BigIntegerField(default=0)
    extra_params = JSONField(default=dict)
    referral_bonus_limit = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'referral_system'

    @property
    def promoImage(self):
        image = Image.objects.filter(
            image_source=self.id, image_type="referral_promo"
        ).last()
        if image:
            return image.image_url

        return None

    @property
    def banner_static_url(self):
        image = Image.objects.filter(
            image_source=self.id, image_type="referral_promo"
        ).last()
        if image:
            return image.static_image_url

        return None


class CommsProviderLookupManager(GetInstanceMixin, JuloModelManager):
    pass


class CommsProviderLookup(TimeStampedModel):
    id = models.CharField(max_length=50, db_column='comms_provider_id', primary_key=True)
    provider_name = models.CharField(max_length=100, null=True,
                                     blank=True, db_column='comms_provider_name')

    objects = CommsProviderLookupManager()

    class Meta(object):
        db_table = 'comms_provider_lookup'

    def __str__(self):
        """Visual identification"""
        return self.provider_name


class RefereeMapping(TimeStampedModel):
    id = models.AutoField(db_column='referee_mapping_id', primary_key=True)
    referrer = models.ForeignKey(
        'Customer', models.DO_NOTHING, db_column='referrer_id', related_name='referrer_id')
    referee = models.ForeignKey(
        'Customer', models.DO_NOTHING, db_column='referee_id', related_name='referee_id')

    class Meta(object):
        db_table = 'referee_mapping'


class AffordabilityHistory(TimeStampedModel):
    id = models.AutoField(db_column='affordability_history_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    application_status = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='application_status_code',
        blank=True, null=True)
    affordability_value = models.BigIntegerField()
    affordability_type = models.CharField(max_length=300, blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    bpjs_median_income = models.BigIntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'affordability_history'


class CreditMatrixManager(GetInstanceMixin, JuloModelManager):
    def get_current_version(self, score, score_tag):
        """return the highest version in DB"""
        credit_matrix_obj = self.filter(score_tag=score_tag, score=score, version__isnull=False)\
            .order_by('-version').first()
        if credit_matrix_obj:
            return credit_matrix_obj.version
        return None

    def get_current_matrix(self, score, score_tag):
        """return the highest version in DB"""
        return self.filter(score_tag=score_tag, score=score, version__isnull=False)\
            .order_by('-version').first()

    def next_version(self):
        """return the next version in DB"""
        latest_version = self.aggregate(Max('version')).get('version__max') or 0
        return latest_version + 1

    def get_current_matrix_for_matrix_type(self, score, score_tag, credit_matrix_type='julo1'):
        """return the highest version in DB"""
        return self.filter(score_tag=score_tag, score=score, version__isnull=False, credit_matrix_type=credit_matrix_type)\
            .order_by('-version').first()


class CreditMatrix(TimeStampedModel):
    id = models.AutoField(db_column='credit_matrix_id', primary_key=True)

    score = models.CharField(max_length=5)
    min_threshold = models.FloatField()
    max_threshold = models.FloatField()
    score_tag = models.CharField(max_length=50, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    is_premium_area = models.BooleanField(default=True)
    is_salaried = models.BooleanField(default=True)
    is_fdc = models.BooleanField(default=False)
    credit_matrix_type = models.CharField(
        max_length=50, choices=CreditMatrixType.CREDIT_MATRIX_CHOICES)
    version = models.IntegerField(default=None, null=True, blank=True)
    parameter = models.TextField(default=None, null=True, blank=True)
    priority = models.CharField(default=None, blank=True, null=True, max_length=5)
    transaction_type = models.CharField(default=None, null=True, blank=True, max_length=50)
    product = models.ForeignKey('ProductLookup',
                                models.DO_NOTHING,
                                db_column='product_code',
                                blank=True, null=True)

    objects = CreditMatrixManager()

    class Meta(object):
        db_table = 'credit_matrix'

    def __str__(self):
        """Visual identification"""
        return self.score

    @property
    def list_product_lines(self):
        return list(CreditMatrixProductLine.objects.values_list(
            'product', flat=True
        ).filter(credit_matrix=self))

    @property
    def product_lines(self):
        return CreditMatrixProductLine.objects.filter(credit_matrix=self)


class CreditMatrixProductLineManager(GetInstanceMixin, JuloModelManager):
    pass


class CreditMatrixProductLine(TimeStampedModel):
    id = models.AutoField(db_column='credit_matrix_product_line_id', primary_key=True)

    credit_matrix = models.ForeignKey(CreditMatrix,
                                      models.DO_NOTHING, db_column='credit_matrix_id', blank=True, null=True)
    product = models.ForeignKey(ProductLine,
                                models.DO_NOTHING, db_column='product_line_id', blank=True, null=True)
    interest = models.FloatField()
    min_loan_amount = models.BigIntegerField()
    max_loan_amount = models.BigIntegerField()
    max_duration = models.IntegerField()
    min_duration = models.IntegerField(null=True)

    objects = CreditMatrixProductLineManager()

    class Meta(object):
        db_table = 'credit_matrix_product_line'

    def __str__(self):
        return str(self.product)

    def get_product_lookup(self, interest):
        product = self.credit_matrix.product
        if not product or interest != self.interest:
            interest_rate = py2round(interest * 12, 2)
            product = ProductLookup.objects.filter(
                interest_rate=interest_rate,
                product_line_id=self.product_id
            ).first()
        return product


class CreditMatrixRepeat(TimeStampedModel):
    id = models.AutoField(db_column='credit_matrix_repeat_id', primary_key=True)
    is_active = models.BooleanField(default=True)
    customer_segment = models.CharField(
        max_length=50,
        default=None,
        null=True,
        blank=True,
        db_index=True,
    )
    product_line = models.ForeignKey(
        ProductLine,
        models.DO_NOTHING,
        db_column='product_line_id',
    )
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod',
        models.DO_NOTHING,
        db_column='transaction_method_id',
    )
    provision = models.FloatField()
    max_tenure = models.IntegerField(null=True, blank=True)
    min_tenure = models.IntegerField(null=True, blank=True)
    show_tenure = ArrayField(models.IntegerField(), default=list)
    interest = models.FloatField()
    repeat_level = models.CharField(
        max_length=10,
        default=None,
        null=True,
        blank=True,
    )
    total_utilization_rate = models.CharField(
        max_length=10,
        default=None,
        null=True,
        blank=True,
    )
    aging = models.IntegerField(
        default=None,
        null=True,
        blank=True,
    )
    fdc_status = models.CharField(
        max_length=50,
        default=None,
        null=True,
        blank=True,
    )
    version = IntegerField(default=1)

    class Meta(object):
        db_table = 'credit_matrix_repeat'


class CreditMatrixRepeatLoan(TimeStampedModel):
    id = BigAutoField(db_column='id', primary_key=True)
    credit_matrix_repeat = models.ForeignKey(
        CreditMatrixRepeat,
        models.DO_NOTHING,
        db_column='credit_matrix_repeat_id',
    )
    loan = BigForeignKey(
        Loan,
        models.DO_NOTHING,
        db_column='loan_id',
        unique=True,
    )

    class Meta(object):
        db_table = 'credit_matrix_repeat_loan'


class JobTypeManager(GetInstanceMixin, JuloModelManager):
    pass


class JobType(TimeStampedModel):
    id = models.AutoField(db_column='job_type_id', primary_key=True)

    job_type = models.CharField(max_length=100)
    is_salaried = models.BooleanField(default=True)

    objects = JobTypeManager()

    class Meta(object):
        db_table = 'job_type'

    def __str__(self):
        """Visual identification"""
        return self.job_type

    def salaried(self):
        return self.objects.filter(is_salaried=True)

    def non_salaried(self):
        return self.objects.filter(is_salaried=False)


class AppsFlyerLogs(TimeStampedModel):
    log_id = models.AutoField(db_column='appsflyer_logs_id', primary_key=True)
    status_new = models.IntegerField(blank=True, null=True)
    status_old = models.IntegerField(blank=True, null=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    appsflyer_device_id = models.CharField(max_length=50, blank=True, null=True)
    appsflyer_customer_id = models.CharField(max_length=50, blank=True, null=True)
    appsflyer_log_code = models.CharField(max_length=50, blank=True, null=True)
    event_name = models.CharField(max_length=50, blank=True, null=True)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True
    )

    class Meta(object):
        db_table = 'appsflyer_logs'

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.log_id)


class CenterixCallbackResults(TimeStampedModel):
    id = models.AutoField(db_column='centerix_callback_results_id', primary_key=True)
    campaign_code = models.CharField(max_length=100, blank=True, null=True)
    application_id = models.BigIntegerField(blank=True, null=True)
    payment_id = models.BigIntegerField(blank=True, null=True)
    start_ts = models.DateTimeField(blank=True, null=True)
    end_ts = models.DateTimeField(blank=True, null=True)
    error_msg = models.TextField(null=True, blank=True)
    result = models.TextField(null=True, blank=True)
    parameters = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'centerix_callback_results'


class SignatureVendorLog(TimeStampedModel):
    id = models.AutoField(db_column='signature_vendor_log_id', primary_key=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    document = models.ForeignKey(Document, models.DO_NOTHING,
                                 db_column='document_id', blank=True, null=True)
    vendor = models.CharField(max_length=100)
    event = models.CharField(max_length=200)
    response_code = models.IntegerField()
    response_string = JSONField(blank=True, null=True)
    request_string = JSONField()
    application = models.ForeignKey(Application, models.DO_NOTHING,
                                    db_column='application_id', blank=True, null=True)
    partner_id = models.ForeignKey(Partner,
                                   models.DO_NOTHING, db_column='partner_id', blank=True, null=True)

    class Meta(object):
        db_table = 'signature_vendor_log'


class CootekRobocallManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    def get_last_account_call(self, account_id):
        qs = self.get_queryset().filter(
            account_payment__account_id=account_id,
            task_status__in=['calling', 'finished']
        ).exclude(call_status__isnull=True).distinct(
            'account_payment__account_id'
        ).order_by('account_payment__account_id', '-udate')
        return qs.first()

    def get_last_account_payment_calls(self, account_payment_ids):
        account_payment_ids = account_payment_ids if isinstance(account_payment_ids, Iterable) else \
            [account_payment_ids]
        qs = self.get_queryset().filter(
            account_payment_id__in=account_payment_ids,
            task_status__in=['calling', 'finished']
        ).exclude(call_status__isnull=True).distinct(
            'account_payment_id'
        ).order_by('account_payment_id', '-udate')
        return list(qs)


class CootekRobocall(PIIVaultModel):
    PII_FIELDS = ['call_to']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = CollectionQueue.TOKENIZED_QUEUE

    id = models.AutoField(db_column='cootek_event_id', primary_key=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    statement = models.ForeignKey(
        'paylater.Statement', models.DO_NOTHING, db_column='statement_id', blank=True, null=True)
    loan_status_code = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='loan_status_code',
        blank=True, null=True, related_name="+")
    payment_status_code = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='payment_status_code',
        blank=True, null=True, related_name="+")
    # remaining loan
    arrears = models.BigIntegerField(blank=True, null=True)
    cootek_event_type = models.CharField(max_length=50, blank=True, null=True)
    cootek_event_date = models.DateTimeField(blank=True, null=True, default=timezone.now)
    task_id = models.CharField(max_length=50, blank=True, null=True)
    call_to = models.CharField(max_length=50, blank=True, null=True)
    task_status = models.CharField(max_length=50, blank=True, null=True)
    called_at = models.BigIntegerField(blank=True, null=True)
    round = models.BigIntegerField(blank=True, null=True, default=0)
    ring_type = models.CharField(max_length=50, blank=True, null=True)
    robot_type = models.CharField(max_length=50, blank=True, null=True)
    cootek_robot = models.ForeignKey('cootek.CootekRobot', models.DO_NOTHING,
                                     db_column='cootek_robot_id', blank=True, null=True)
    exact_robot_id = models.CharField(max_length=50, blank=True, null=True)
    intention = models.CharField(max_length=50, blank=True, null=True)
    # length of call in seconds
    duration = models.BigIntegerField(blank=True, null=True, default=0)
    campaign_or_strategy = models.TextField(blank=True, null=True)
    hang_type = models.CharField(max_length=50, blank=True, null=True)
    call_status = models.CharField(max_length=50, blank=True, null=True)
    loan_refinancing_offer = models.ForeignKey(
        'loan_refinancing.LoanRefinancingOffer', models.DO_NOTHING,
        db_column='loan_refinancing_offer', blank=True, null=True)
    task_type = models.CharField(max_length=200, null=True, default=None)
    time_to_start = models.TimeField(default=None, null=True)
    product = models.CharField(max_length=10, null=True, default=None)
    partner = models.ForeignKey(Partner, models.DO_NOTHING,
                                db_column='partner_id', blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    multi_intention = models.TextField(blank=True, null=True)
    time_to_end = models.TimeField(default=None, null=True)
    call_to_tokenized = models.TextField(blank=True, null=True)

    objects = CootekRobocallManager()

    class Meta(object):
        db_table = 'cootek_robocall'


class PartnerOriginationDataManager(GetInstanceMixin, JuloModelManager):
    pass


class PartnerOriginationData(TimeStampedModel):
    id = models.IntegerField(db_column='partner_origination_data_id',
                             primary_key=True, verbose_name='partner origination data id')
    distributor_name = models.CharField(default='-', max_length=100)
    origination_fee = models.FloatField(default=0.01)
    partner = models.ForeignKey(Partner, models.DO_NOTHING,
                                db_column='partner_id', blank=True, null=True)

    objects = PartnerOriginationDataManager()

    class Meta(object):
        db_table = 'partner_origination_data'


class FDCDelivery(TimeStampedModel):
    id = models.AutoField(db_column='fdc_delivery_id', primary_key=True)
    count_of_record = models.BigIntegerField(blank=True, null=True)
    status = models.CharField(max_length=100, default='pending')
    generated_filename = models.CharField(max_length=100)
    error = models.CharField(max_length=100, blank=True, null=True)

    class Meta(object):
        db_table = 'fdc_delivery'


class FDCValidationError(TimeStampedModel):
    id = models.AutoField(db_column='fdc_validation_error_id', primary_key=True)
    row_number = models.BigIntegerField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    id_borrower = models.BigIntegerField(blank=True, null=True)
    id_pinjaman = models.BigIntegerField(blank=True, null=True)
    filename = models.CharField(max_length=100)

    class Meta(object):
        db_table = 'fdc_validation_error'


class FDCDataAsView(models.Model):
    fdc_data_as_view_id = models.BigIntegerField(primary_key=True)
    id_penyelenggara = models.IntegerField(blank=True, null=True)
    id_borrower = models.BigIntegerField(blank=True, null=True)
    jenis_pengguna = models.IntegerField(blank=True, null=True)
    nama_borrower = models.CharField(max_length=100)
    no_identitas = models.CharField(max_length=100)
    no_npwp = models.TextField(null=True, blank=True)
    id_pinjaman = models.BigIntegerField(blank=True, null=True)
    tgl_perjanjian_borrower = models.TextField(null=True, blank=True)
    tgl_penyaluran_dana = models.TextField(null=True, blank=True)
    nilai_pendanaan = models.BigIntegerField(blank=True, null=True)
    tgl_pelaporan_data = models.TextField(null=True, blank=True)
    sisa_pinjaman_berjalan = models.BigIntegerField(blank=True, null=True)
    tgl_jatuh_tempo_pinjaman = models.TextField(null=True, blank=True)
    id_kualitas_pinjaman = models.IntegerField(blank=True, null=True)
    status_pinjaman_dpd = models.IntegerField(blank=True, null=True)
    status_pinjaman_max_dpd = models.IntegerField(blank=True, null=True)
    status_pinjaman = models.TextField(null=True, blank=True)
    pendanaan_syariah = models.NullBooleanField()
    tipe_pinjaman = models.TextField(null=True, blank=True)
    sub_tipe_pinjaman = models.TextField(null=True, blank=True)
    penyelesaian_w_oleh = models.TextField(null=True, blank=True)
    reference = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'fdc_data_as_view'
        managed = False


class FDCDataAsViewV2(models.Model):
    fdc_data_as_view_id = models.BigIntegerField(primary_key=True)
    id_penyelenggara = models.IntegerField(blank=True, null=True)
    id_borrower = models.BigIntegerField(blank=True, null=True)
    jenis_pengguna = models.IntegerField(blank=True, null=True)
    nama_borrower = models.CharField(max_length=100)
    no_identitas = models.CharField(max_length=100)
    no_npwp = models.TextField(null=True, blank=True)
    id_pinjaman = models.BigIntegerField(blank=True, null=True)
    tgl_perjanjian_borrower = models.TextField(null=True, blank=True)
    tgl_penyaluran_dana = models.TextField(null=True, blank=True)
    nilai_pendanaan = models.BigIntegerField(blank=True, null=True)
    tgl_pelaporan_data = models.TextField(null=True, blank=True)
    sisa_pinjaman_berjalan = models.BigIntegerField(blank=True, null=True)
    tgl_jatuh_tempo_pinjaman = models.TextField(null=True, blank=True)
    id_kualitas_pinjaman = models.IntegerField(blank=True, null=True)
    status_pinjaman_dpd = models.IntegerField(blank=True, null=True)
    status_pinjaman_max_dpd = models.IntegerField(blank=True, null=True)
    status_pinjaman = models.TextField(null=True, blank=True)
    pendanaan_syariah = models.NullBooleanField()
    tipe_pinjaman = models.TextField(null=True, blank=True)
    sub_tipe_pinjaman = models.TextField(null=True, blank=True)
    penyelesaian_w_oleh = models.TextField(null=True, blank=True)
    reference = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'fdc_data_as_view_v2'
        managed = False


class FDCDataAsViewV3(models.Model):
    fdc_data_as_view_id = models.BigIntegerField(primary_key=True)
    id_penyelenggara = models.IntegerField(blank=True, null=True)
    id_borrower = models.BigIntegerField(blank=True, null=True)
    jenis_pengguna = models.IntegerField(blank=True, null=True)
    nama_borrower = models.CharField(max_length=100)
    no_identitas = models.CharField(max_length=100)
    no_npwp = models.TextField(null=True, blank=True)
    id_pinjaman = models.BigIntegerField(blank=True, null=True)
    tgl_perjanjian_borrower = models.TextField(null=True, blank=True)
    tgl_penyaluran_dana = models.TextField(null=True, blank=True)
    nilai_pendanaan = models.BigIntegerField(blank=True, null=True)
    tgl_pelaporan_data = models.TextField(null=True, blank=True)
    sisa_pinjaman_berjalan = models.BigIntegerField(blank=True, null=True)
    tgl_jatuh_tempo_pinjaman = models.TextField(null=True, blank=True)
    id_kualitas_pinjaman = models.IntegerField(blank=True, null=True)
    status_pinjaman_dpd = models.IntegerField(blank=True, null=True)
    status_pinjaman_max_dpd = models.IntegerField(blank=True, null=True)
    status_pinjaman = models.TextField(null=True, blank=True)
    pendanaan_syariah = models.NullBooleanField()
    tipe_pinjaman = models.TextField(null=True, blank=True)
    sub_tipe_pinjaman = models.TextField(null=True, blank=True)
    penyelesaian_w_oleh = models.TextField(null=True, blank=True)
    reference = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'fdc_data_as_view_v3'
        managed = False


class FDCDataAsViewV5(models.Model):
    fdc_data_as_view_id = models.BigIntegerField(primary_key=True)
    id_penyelenggara = models.IntegerField(blank=True, null=True)
    id_borrower = models.BigIntegerField(blank=True, null=True)
    jenis_pengguna = models.IntegerField(blank=True, null=True)
    nama_borrower = models.CharField(max_length=100)
    no_identitas = models.CharField(max_length=100)
    no_npwp = models.TextField(null=True, blank=True)
    id_pinjaman = models.BigIntegerField(blank=True, null=True)
    tgl_perjanjian_borrower = models.TextField(null=True, blank=True)
    tgl_penyaluran_dana = models.TextField(null=True, blank=True)
    nilai_pendanaan = models.BigIntegerField(blank=True, null=True)
    tgl_pelaporan_data = models.TextField(null=True, blank=True)
    sisa_pinjaman_berjalan = models.BigIntegerField(blank=True, null=True)
    tgl_jatuh_tempo_pinjaman = models.TextField(null=True, blank=True)
    kualitas_pinjaman = models.IntegerField(blank=True, null=True)
    dpd_terakhir = models.IntegerField(blank=True, null=True)
    dpd_max = models.IntegerField(blank=True, null=True)
    status_pinjaman = models.TextField(null=True, blank=True)
    penyelesaian_w_oleh = models.TextField(null=True, blank=True)
    syariah = models.NullBooleanField()
    tipe_pinjaman = models.TextField(null=True, blank=True)
    sub_tipe_pinjaman = models.TextField(null=True, blank=True)
    reference = models.TextField(null=True, blank=True)
    no_hp = models.TextField(null=True, blank=True)
    email = models.TextField(null=True, blank=True)
    agunan = models.TextField(null=True, blank=True)
    tgl_agunan = models.TextField(null=True, blank=True)
    nama_penjamin = models.TextField(null=True, blank=True)
    no_agunan = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'fdc_data_as_view_v5'
        managed = False


class FDCDeliveryTemp(models.Model):
    id = models.AutoField(db_column='fdc_delivery_id', primary_key=True)
    dpd_max = models.IntegerField(blank=True, null=True)
    dpd_terakhir = models.IntegerField(blank=True, null=True)
    id_penyelenggara = models.IntegerField(blank=True, null=True)
    jenis_pengguna = models.IntegerField(blank=True, null=True)
    kualitas_pinjaman = models.IntegerField(blank=True, null=True)
    nama_borrower = models.CharField(max_length=100, blank=True, null=True)
    nilai_pendanaan = models.BigIntegerField(blank=True, null=True)
    no_identitas = models.CharField(max_length=16, blank=True, null=True, db_index=True)
    no_npwp = models.TextField(null=True, blank=True)
    sisa_pinjaman_berjalan = models.BigIntegerField(blank=True, null=True)
    status_pinjaman = models.TextField(null=True, blank=True)
    tgl_jatuh_tempo_pinjaman = models.TextField(null=True, blank=True)
    tgl_pelaporan_data = models.TextField(null=True, blank=True)
    tgl_penyaluran_dana = models.TextField(null=True, blank=True)
    tgl_perjanjian_borrower = models.TextField(null=True, blank=True)
    no_hp = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    agunan = models.CharField(max_length=100, blank=True, null=True)
    tgl_agunan = models.TextField(blank=True, null=True)
    nama_penjamin = models.CharField(max_length=100, blank=True, null=True)
    no_agunan = models.CharField(max_length=100, blank=True, null=True)
    pendapatan = models.BigIntegerField(blank=True, null=True)

    nama_borrower_tokenized = models.CharField(max_length=50, null=True, blank=True)
    no_identitas_tokenized = models.CharField(max_length=50, null=True, blank=True)
    no_npwp_tokenized = models.CharField(max_length=50, null=True, blank=True)
    no_hp_tokenized = models.CharField(max_length=50, null=True, blank=True)
    email_tokenized = models.CharField(max_length=50, null=True, blank=True)
    nama_penjamin_tokenized = models.CharField(max_length=50, null=True, blank=True)

    PII_FIELDS = ['nama_borrower', 'no_identitas', 'no_npwp', 'no_hp', 'email', 'nama_penjamin']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'onboarding_pii_vault'
    is_not_timestamp_model = True
    #
    # objects = PIIVaultModelManager()

    class Meta(object):
        db_table = 'fdc_delivery_temp'


class FDCInquiryRun(TimeStampedModel):
    id = models.AutoField(db_column='fdc_inquiry_run_id', primary_key=True)

    class Meta(object):
        db_table = 'fdc_inquiry_run'


class FDCInquiry(PIIVaultModel):
    id = models.AutoField(db_column='fdc_inquiry_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', null=True, db_constraint=False)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', null=True, db_constraint=False)
    fdc_inquiry_run = models.ForeignKey(
        FDCInquiryRun, models.DO_NOTHING, db_column='fdc_inquiry_run_id',
        blank=True, null=True)
    inquiry_reason = models.CharField(max_length=150, blank=True, null=True)
    nik = models.CharField(max_length=16, blank=True, null=True)
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    inquiry_status = models.CharField(max_length=50, default="pending", blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    application_status_code = models.IntegerField(blank=True, null=True)
    loan_status_code = models.IntegerField(blank=True, null=True)
    inquiry_date = models.DateTimeField(blank=True, null=True, default=None)
    retry_count = models.IntegerField(default=None, blank=True, null=True)
    mobile_phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    inquiry_history = JSONField(blank=True, null=True)
    nik_tokenized = models.CharField(max_length=50, null=True, blank=True)
    mobile_phone_tokenized = models.CharField(max_length=50, null=True, blank=True)
    email_tokenized = models.CharField(max_length=50, null=True, blank=True)

    PII_FIELDS = ['email', 'mobile_phone', 'nik']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'onboarding_pii_vault'

    objects = PIIVaultModelManager()

    class Meta(object):
        db_table = 'fdc_inquiry'
        index_together = [('id', 'application')]


class FDCInquiryLoan(PIIVaultModel):
    id = models.AutoField(db_column='fdc_inquiry_loan_id', primary_key=True)
    fdc_inquiry = models.ForeignKey(
        FDCInquiry, models.DO_NOTHING, db_column='fdc_inquiry_id')
    dpd_max = models.IntegerField(blank=True, null=True)
    dpd_terakhir = models.IntegerField(blank=True, null=True)
    id_penyelenggara = models.CharField(max_length=50, blank=True, null=True)
    jenis_pengguna = models.CharField(max_length=50, blank=True, null=True)
    kualitas_pinjaman = models.CharField(max_length=50, blank=True, null=True)
    nama_borrower = models.CharField(max_length=100, blank=True, null=True)
    nilai_pendanaan = models.BigIntegerField(blank=True, null=True)
    no_identitas = models.CharField(max_length=16, blank=True, null=True)
    no_npwp = models.CharField(max_length=20, blank=True, null=True)
    sisa_pinjaman_berjalan = models.BigIntegerField(blank=True, null=True)
    status_pinjaman = models.CharField(max_length=20, blank=True, null=True)
    tgl_jatuh_tempo_pinjaman = models.DateField(blank=True, null=True)
    tgl_pelaporan_data = models.DateField(blank=True, null=True)
    tgl_penyaluran_dana = models.DateField(blank=True, null=True)
    tgl_perjanjian_borrower = models.DateField(blank=True, null=True)
    is_julo_loan = models.NullBooleanField()
    penyelesaian_w_oleh = models.CharField(max_length=100, blank=True, null=True)
    pendanaan_syariah = models.NullBooleanField()
    tipe_pinjaman = models.CharField(max_length=100, blank=True, null=True)
    sub_tipe_pinjaman = models.CharField(max_length=100, blank=True, null=True)
    fdc_id = models.CharField(max_length=100, blank=True, null=True)
    reference = models.CharField(max_length=100, blank=True, null=True)
    no_hp = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    agunan = models.CharField(max_length=100, blank=True, null=True)
    tgl_agunan = models.DateField(blank=True, null=True)
    nama_penjamin = models.CharField(max_length=100, blank=True, null=True)
    no_agunan = models.CharField(max_length=100, blank=True, null=True)
    pendapatan = models.BigIntegerField(blank=True, null=True)

    nama_borrower_tokenized = models.CharField(max_length=50, null=True, blank=True)
    no_identitas_tokenized = models.CharField(max_length=50, null=True, blank=True)
    no_npwp_tokenized = models.CharField(max_length=50, null=True, blank=True)
    no_hp_tokenized = models.CharField(max_length=50, null=True, blank=True)
    email_tokenized = models.CharField(max_length=50, null=True, blank=True)
    nama_penjamin_tokenized = models.CharField(max_length=50, null=True, blank=True)

    PII_FIELDS = ['nama_borrower', 'no_identitas', 'no_npwp', 'no_hp', 'email', 'nama_penjamin']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'onboarding_pii_vault'

    objects = PIIVaultModelManager()


    class Meta(object):
        db_table = 'fdc_inquiry_loan'


class FDCActiveLoanChecking(TimeStampedModel):
    id = models.AutoField(db_column='fdc_active_loan_checking_id', primary_key=True)
    customer = models.OneToOneField('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    last_access_date = models.DateField(auto_now_add=True)
    number_of_other_platforms = models.IntegerField(blank=True, null=True)
    last_updated_time = models.DateTimeField(blank=True, null=True)
    nearest_due_date = models.DateField(null=True, blank=True)
    product_line = models.ForeignKey(
        'ProductLine', models.DO_NOTHING, db_column='product_line_code', blank=True, null=True)

    class Meta(object):
        db_table = 'fdc_active_loan_checking'


class FDCInquiryCheck(TimeStampedModel):
    id = models.AutoField(db_column='fdc_inquiry_check_id', primary_key=True)
    is_active = models.BooleanField(default=False)
    min_threshold = models.FloatField()
    max_threshold = models.FloatField()
    min_tidak_lancar = models.IntegerField(default=0)
    min_macet_pct = models.FloatField(default=0)
    max_paid_pct = models.FloatField(default=0)

    class Meta(object):
        db_table = 'fdc_inquiry_check'


class AAIBlacklistLogManager(PIIVaultModelManager):
    pass


class AAIBlacklistLog(PIIVaultModel):
    id = models.AutoField(db_column='aai_blacklist_log_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    response_status_code = models.CharField(max_length=50, blank=True, null=True)
    request_string = JSONField(blank=True, null=True)
    response_string = JSONField(blank=True, null=True)

    # PII attributes
    request_string_tokenized = models.TextField(blank=True, null=True)
    PII_FIELDS = ['request_string']
    PII_TYPE = PIIType.KV

    objects = AAIBlacklistLogManager()

    class Meta(object):
        db_table = 'aai_blacklist_log'


class FraudModelExperiment(TimeStampedModel):
    id = models.AutoField(db_column='fraud_model_experiment_id', primary_key=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')
    fraud_model_check = models.BooleanField(default=False)
    advance_ai_blacklist = models.BooleanField(default=False)
    fraud_model_value = models.FloatField(null=True, blank=True)
    is_fraud_experiment_period = models.BooleanField(default=False)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')

    class Meta(object):
        db_table = 'fraud_model_experiment'


class BlacklistCustomerManager(PIIVaultModelManager):
    pass


class BlacklistCustomer(PIIVaultModel):
    PII_FIELDS = ['name', 'fullname_trim']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = models.AutoField(db_column='blacklist_customer_id', primary_key=True)
    source = models.TextField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)
    citizenship = models.TextField(null=True, blank=True)
    dob = models.TextField(null=True, blank=True)
    fullname_trim = models.TextField(null=True, blank=True)
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)
    name_tokenized = models.TextField(blank=True, null=True)
    fullname_trim_tokenized = models.TextField(blank=True, null=True)

    objects = BlacklistCustomerManager()

    class Meta(object):
        db_table = 'blacklist_customer'

    def validate_name_field(self):
        # Check if there is another object with the same name or if name is empty
        if not self.name:
            raise exceptions.ValidationError('Field "name" cannot be empty')

        if BlacklistCustomer.objects.filter(name=self.name).exclude(id=self.id).exists():
            raise exceptions.ValidationError('Another object with this name already exists.')

    def clean(self):
        super().clean()
        self.validate_name_field()

    def save(self, *args, **kwargs):
        from juloserver.julo.utils import trim_name
        fullname = trim_name(self.name)
        self.fullname_trim = fullname
        super(BlacklistCustomer, self).save(*args, **kwargs)


class ProductivityCenterixSummary(TimeStampedModel):
    id = models.AutoField(db_column='productivity_centerix_summary_id', primary_key=True)
    event_date = models.DateTimeField(blank=True, null=True)
    agent_name = models.TextField(null=True, blank=True)
    leader_name = models.TextField(null=True, blank=True)
    outbond_calls_initiated = models.IntegerField(blank=True, null=True)
    outbond_calls_connected = models.IntegerField(blank=True, null=True)
    outbond_calls_not_connected = models.IntegerField(blank=True, null=True)
    outbond_talk_time_duration = models.TimeField(blank=True, null=True)
    outbond_acw_time_duration = models.TimeField(blank=True, null=True)
    outbond_handling_time_duration = models.TimeField(blank=True, null=True)
    outbond_logged_in_time_duration = models.TimeField(blank=True, null=True)
    outbond_available_in_time_duration = models.TimeField(blank=True, null=True)
    outbond_busy_in_time_duration = models.TimeField(blank=True, null=True)
    outbond_aux_in_time_duration = models.TimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'productivity_centerix_summary'


class XidLookup(models.Model):
    xid = models.BigIntegerField(db_column='xid', null=False,
                                 primary_key=True, unique=True, db_index=True)
    is_used_application = models.BooleanField(db_column='is_used_application', default=False)

    class Meta(object):
        db_table = 'xid_lookup'

    @classmethod
    def get_new_xid(cls, retry_times=0):
        import time

        max_offset = 300
        max_sleep_time = 10
        max_retries = 10
        retry_times += 1

        if retry_times >= max_retries:
            raise Exception('Max Retry Reached')

        try:
            with transaction.atomic():
                # get random value by index between 0 and 300
                offset = random.randint(0, max_offset)

                xid_lookup = cls.objects.filter(is_used_application=False).order_by('pk')[
                    offset:offset + 1]
                obj = cls.objects.select_for_update(nowait=True).filter(
                    xid__in=xid_lookup
                ).first()

                if obj:
                    result = cls.objects.filter(
                        pk=obj.pk, is_used_application=False
                    ).update(is_used_application=True)
                    if result:
                        return obj.xid

                logger.warn({
                    'msg': 'get_new_xid failed',
                    'data': {'offset': offset, 'retry_times': retry_times}
                })
        except (DatabaseError, OperationalError) as error:
            logger.error({
                'msg': 'get_new_xid has exception',
                'error': str(error)
            })

        time.sleep(random.randint(0, max_sleep_time) / 100)  # from 0 to 100ms
        return cls.get_new_xid(retry_times)


class MarginOfErrorManager(GetInstanceMixin, JuloModelManager):
    pass


class MarginOfError(TimeStampedModel):
    id = models.AutoField(db_column='margin_of_error_id', primary_key=True)

    min_threshold = models.BigIntegerField()
    max_threshold = models.BigIntegerField()
    mae = models.BigIntegerField()

    objects = MarginOfErrorManager()

    class Meta(object):
        db_table = 'margin_of_error'

    def __str__(self):
        """Visual identification"""
        return "{} <= monthly_income < {} MAE {}".format(self.min_threshold,
                                                         self.max_threshold, self.mae)


class UserFeedback(TimeStampedModel):
    id = models.AutoField(db_column='user_feedback_id', primary_key=True)
    rating = models.IntegerField()
    feedback = models.TextField(null=True, blank=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')

    class Meta(object):
        db_table = 'user_feedback'


# Table model to keep track of user installation and uninstallations
class ApplicationInstallHistory(TimeStampedModel):

    # Table row id
    id = models.AutoField(db_column='application_install_history_id', primary_key=True)

    # Customer id from table "Customers"
    customer_id = models.BigIntegerField(db_column='customer_id', blank=True, null=True)

    # appsflyer id provided by appsflyer, a new one is created every app installation
    appsflyer = models.CharField(db_column='appsflyer_id', blank=True, max_length=100, null=True)

    # time of app event
    event_time = models.DateTimeField()

    # specifies whether the event is install or uninstalls
    event_name = models.CharField(blank=True, max_length=100, null=True)

    # partner name
    partner = models.CharField(blank=True, max_length=100, null=True)

    # Media Source
    media_source = models.CharField(blank=True, max_length=100, null=True)

    # campaign code for each installation
    campaign = models.CharField(blank=True, max_length=100, null=True)

    # Table name
    class Meta(object):
        db_table = 'application_install_history'
        unique_together = [['appsflyer', 'event_name']]
        managed = False


class HighScoreFullBypassManager(GetInstanceMixin, JuloModelManager):
    pass


class HighScoreFullBypass(TimeStampedModel):
    id = models.AutoField(db_column='high_score_full_bypass_id', primary_key=True)

    cm_version = models.CharField(max_length=200, null=True, default=None)
    threshold = models.FloatField()
    is_premium_area = models.BooleanField(default=True)
    is_salaried = models.BooleanField(default=True)
    bypass_dv_x121 = models.BooleanField(default=False)
    customer_category = models.CharField(
        max_length=50, choices=CreditMatrixType.CREDIT_MATRIX_CHOICES)
    parameters = JSONField(blank=True, null=True)

    objects = HighScoreFullBypassManager()

    class Meta(object):
        db_table = 'high_score_full_bypass'
        verbose_name_plural = "High Score Full Bypass"

    def __str__(self):
        return self.cm_version


class ITIConfigurationManager(GetInstanceMixin, JuloModelManager):
    pass


class ITIConfiguration(TimeStampedModel):
    id = models.AutoField(db_column='iti_configuration_id', primary_key=True)

    iti_version = models.IntegerField()
    min_threshold = models.FloatField()
    max_threshold = models.FloatField()
    min_income = models.BigIntegerField()
    max_income = models.BigIntegerField()
    is_active = models.BooleanField(default=False)
    is_premium_area = models.BooleanField(default=True)
    is_salaried = models.BooleanField(default=True)
    customer_category = models.CharField(
        default='julo',
        max_length=50,
        choices=CreditMatrixType.CREDIT_MATRIX_CHOICES)
    parameters = JSONField(blank=True, null=True)

    objects = ITIConfigurationManager()

    class Meta(object):
        db_table = 'iti_configuration'
        verbose_name_plural = "ITI Configuration"

    def __str__(self):
        return "{}".format(self.iti_version)


class SiteMapContentManager(GetInstanceMixin, JuloModelManager):
    pass


class SiteMapJuloWeb(TimeStampedModel):
    id = models.AutoField(db_column='julo_article_id', primary_key=True)

    label_name = models.TextField()
    label_url = models.TextField()

    objects = SiteMapContentManager()

    class Meta(object):
        db_table = 'sitemap_julo_web'
        verbose_name_plural = "Sitemap Julo Web"

    def __str__(self):
        return self.label_name


class DigitalSignatureFaceResult(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='digital_signature_face_result_id')
    face_recognition_provider = models.CharField(max_length=100)
    digital_signature_provider = models.CharField(max_length=100, blank=True, null=True)
    is_used_for_registration = models.NullBooleanField()
    is_passed = models.NullBooleanField()

    class Meta(object):
        db_table = 'digital_signature_face_result'


class AwsFaceRecogLogManager(GetInstanceMixin, JuloModelManager):
    pass


class AwsFaceRecogLog(TimeStampedModel):
    id = models.AutoField(db_column='aws_face_recog_log_id', primary_key=True)
    image = models.ForeignKey(Image, models.DO_NOTHING, db_column='image_id', blank=True, null=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id', blank=True, null=True)
    application = models.ForeignKey(Application, models.DO_NOTHING,
                                    db_column='application_id', blank=True, null=True)
    face_id = JSONField(blank=True, null=True, db_column='face_id')
    raw_response = JSONField(db_column='raw_response')
    is_indexed = models.NullBooleanField(blank=True, null=True, db_column='is_indexed')
    is_quality_check_passed = models.NullBooleanField(
        blank=True, null=True, db_column='is_quality_check_passed')
    brightness_threshold = models.IntegerField()
    sharpness_threshold = models.IntegerField()
    digital_signature_face_result = models.ForeignKey(DigitalSignatureFaceResult,
                                                      db_column='digital_signature_face_result_id', blank=True,
                                                      null=True)

    objects = AwsFaceRecogLogManager()

    class Meta(object):
        db_table = 'aws_face_recog_log'


class FaceRecognitionManager(GetInstanceMixin, JuloModelManager):
    pass


class FaceRecognition(TimeStampedModel):
    QUALITY_FILTER_CHOICES = (
        ('LOW', 'LOW'),
        ('MEDIUM', 'MEDIUM'),
        ('HIGH', 'HIGH'),
    )
    id = models.AutoField(db_column='face_recognition_id', primary_key=True)
    feature_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    quality_filter = models.CharField(
        max_length=10, choices=QUALITY_FILTER_CHOICES, blank=True, null=True)
    sharpness = models.IntegerField(blank=True, null=True)
    brightness = models.IntegerField(blank=True, null=True)

    objects = FaceRecognitionManager()

    class Meta(object):
        db_table = 'face_recognition'


class PartnerSignatureMode(TimeStampedModel):
    id = models.AutoField(db_column='partner_signature_mode_id', primary_key=True)
    partner = models.ForeignKey(Partner, models.DO_NOTHING, db_column='partner_id')
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'partner_signature_mode'

    def save(self, *args, **kwargs):
        super(PartnerSignatureMode, self).save(*args, **kwargs)
        PartnerSignatureModeHistory.objects.create(
            partner_signature_mode_id=self.id, is_active=self.is_active
        )


class PartnerSignatureModeHistory(TimeStampedModel):
    id = models.AutoField(db_column='partner_signature_mode_history_id', primary_key=True)
    partner_signature_mode = models.ForeignKey(
        PartnerSignatureMode, models.DO_NOTHING,
        db_column='partner_signature_mode_id', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'partner_signature_mode_history'


class CampaignSetting(TimeStampedModel):
    id = models.AutoField(db_column='campaign_setting_id', primary_key=True)
    campaign_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)
    parameters = JSONField(blank=True, null=True)
    description = models.CharField(max_length=200)

    class Meta(object):
        db_table = 'campaign_setting'


class CustomerCampaignParameter(TimeStampedModel):
    id = models.AutoField(db_column='customer_campaign_parameter_id', primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING,
                                 db_column='customer_id', blank=True, null=True)
    campaign_setting = models.ForeignKey(CampaignSetting, models.DO_NOTHING, db_column='campaign_setting_id',
                                         blank=True, null=True)
    effective_date = models.DateField(blank=True, null=True)

    class Meta(object):
        db_table = 'customer_campaign_parameters'


class AgentProductivity(TimeStampedModel):
    id = models.AutoField(db_column='agent_productivity_id', primary_key=True)
    agent_name = models.TextField(null=True, blank=True)
    hourly_interval = models.TextField(blank=True, null=True)
    calling_date = models.DateTimeField(null=True, blank=True)
    inbound_calls_offered = models.IntegerField(blank=True, null=True)
    inbound_calls_answered = models.IntegerField(blank=True, null=True)
    inbound_calls_not_answered = models.IntegerField(blank=True, null=True)
    outbound_calls_initiated = models.IntegerField(blank=True, null=True)
    outbound_calls_connected = models.IntegerField(blank=True, null=True)
    outbound_calls_not_connected = models.IntegerField(blank=True, null=True)
    outbound_calls_offered = models.IntegerField(blank=True, null=True)
    outbound_calls_answered = models.IntegerField(blank=True, null=True)
    outbound_calls_not_answered = models.IntegerField(blank=True, null=True)
    manual_in_calls_offered = models.IntegerField(blank=True, null=True)
    manual_in_calls_answered = models.IntegerField(blank=True, null=True)
    manual_in_calls_not_answered = models.IntegerField(blank=True, null=True)
    manual_out_calls_initiated = models.IntegerField(blank=True, null=True)
    manual_out_calls_connected = models.IntegerField(blank=True, null=True)
    manual_out_calls_not_connected = models.IntegerField(blank=True, null=True)
    internal_in_calls_offered = models.IntegerField(blank=True, null=True)
    internal_in_calls_answered = models.IntegerField(blank=True, null=True)
    internal_in_calls_not_answered = models.IntegerField(blank=True, null=True)
    internal_out_calls_initiated = models.IntegerField(blank=True, null=True)
    internal_out_calls_connected = models.IntegerField(blank=True, null=True)
    internal_out_calls_not_connected = models.IntegerField(blank=True, null=True)
    inbound_talk_time = models.TextField(blank=True, null=True)
    inbound_hold_time = models.TextField(blank=True, null=True)
    inbound_acw_time = models.TextField(blank=True, null=True)
    inbound_handling_time = models.TextField(blank=True, null=True)
    outbound_talk_time = models.TextField(blank=True, null=True)
    outbound_hold_time = models.TextField(blank=True, null=True)
    outbound_acw_time = models.TextField(blank=True, null=True)
    outbound_handling_time = models.TextField(blank=True, null=True)
    manual_out_call_time = models.TextField(blank=True, null=True)
    manual_in_call_time = models.TextField(blank=True, null=True)
    internal_out_call_time = models.TextField(blank=True, null=True)
    internal_in_call_time = models.TextField(blank=True, null=True)
    logged_in_time = models.TextField(blank=True, null=True)
    available_time = models.TextField(blank=True, null=True)
    aux_time = models.TextField(blank=True, null=True)
    busy_time = models.TextField(blank=True, null=True)
    login_ts = models.DateTimeField(null=True, blank=True)
    logout_ts = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = 'agent_productivity'


class PaymentPreRefinancing(TimeStampedModel):
    id = models.AutoField(db_column='payment_pre_refinancing_id', primary_key=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id')
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    payment_status = models.ForeignKey(
        'StatusLookup', models.DO_NOTHING, db_column='payment_status_code')

    payment_number = models.IntegerField()
    due_date = models.DateField(null=True)
    ptp_date = models.DateField(blank=True, null=True)
    ptp_robocall_template = models.ForeignKey('RobocallTemplate',
                                              models.DO_NOTHING,
                                              db_column='robocall_template_id',
                                              null=True,
                                              blank=True)
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
    loan_refinancing_request = models.ForeignKey(
        'loan_refinancing.LoanRefinancingRequest',
        models.DO_NOTHING,
        db_column='loan_refinancing_request_id',
        blank=True, null=True
    )

    class Meta(object):
        db_table = 'payment_pre_refinancing'


class FDCRiskyHistory(TimeStampedModel):
    """
    We already moved this table to separate DB server instance. There is no longer foreign key for
    application, loan and account.
    """
    id = models.AutoField(db_column='fdc_risky_history_id', primary_key=True)
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column='application_id', db_constraint=False)
    loan = models.ForeignKey(
        Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True, db_constraint=False)
    dpd = models.IntegerField(blank=True, null=True)
    is_fdc_risky = models.NullBooleanField()
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True,
        db_constraint=False
    )

    class Meta(object):
        db_table = 'fdc_risky_history'


class EarlyPaybackOffer(TimeStampedModel):
    id = models.AutoField(db_column='early_payback_offer_id', primary_key=True)
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    is_fdc_risky = models.NullBooleanField()
    cycle_number = models.IntegerField()
    promo_date = models.DateField()
    dpd = models.IntegerField(blank=True, null=True)
    email_status = models.CharField(max_length=50)
    paid_off_indicator = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'early_payback_offer'


class GlobalPaymentMethodManager(GetInstanceMixin, JuloModelManager):
    pass


class GlobalPaymentMethod(TimeStampedModel):
    id = models.AutoField(db_column='global_payment_method_id', primary_key=True)
    feature_name = models.CharField(max_length=200)
    payment_method_code = models.CharField(max_length=10)
    payment_method_name = models.CharField(max_length=50, default='')
    is_active = models.BooleanField(default=False)
    is_priority = models.BooleanField(default=False)
    parameters = JSONField(blank=True, null=True)
    impacted_type = models.CharField(max_length=50, null=True)

    objects = GlobalPaymentMethodManager()

    class Meta(object):
        db_table = 'global_payment_method'

    def __str__(self):
        return '{}_{}'.format(self.id, self.feature_name)


class AccountingCutOffDate(TimeStampedModel):
    id = models.AutoField(db_column='accounting_cut_off_date_id', primary_key=True)
    accounting_period = models.CharField(max_length=50)
    cut_off_date = models.DateField(blank=True, null=True)
    cut_off_date_last_change_ts = models.DateTimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'accounting_cut_off_date'


class LoanHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class LoanHistory(TimeStampedModel):
    id = models.AutoField(db_column="loan_history_id", primary_key=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    status_old = models.IntegerField()
    status_new = models.IntegerField()
    change_reason = models.TextField(default="system_triggered")
    change_by_id = models.IntegerField(blank=True, null=True)

    objects = LoanHistoryManager()

    class Meta(object):
        db_table = 'loan_history'


class CommsBlocked(TimeStampedModel):
    id = models.AutoField(db_column='comm_block_id', primary_key=True)
    is_email_blocked = models.BooleanField(default=False)
    is_sms_blocked = models.BooleanField(default=False)
    is_robocall_blocked = models.BooleanField(default=False)
    is_cootek_blocked = models.BooleanField(default=False)
    is_pn_blocked = models.BooleanField(default=False)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                              on_delete=models.CASCADE, db_column='agent_id', blank=True, null=True)
    block_until = models.IntegerField()
    product = models.ForeignKey(ProductLine,
                                models.DO_NOTHING, db_column='product_line_id', blank=True,
                                null=True)
    loan = BigForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id',
                                blank=True, null=True)
    impacted_payments = ArrayField(models.BigIntegerField(), blank=True, null=True)

    class Meta(object):
        db_table = 'comms_blocked'


class SecurityNote(TimeStampedModel):
    id = models.AutoField(db_column='security_note_id', primary_key=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')
    note_text = models.TextField()
    added_by = CurrentUserField(related_name="security_notes")

    class Meta(object):
        db_table = 'security_note'


class VPNDetection(TimeStampedModel):
    id = models.AutoField(db_column='vpn_detection_id', primary_key=True)

    ip_address = models.TextField(db_index=True)
    is_vpn_detected = models.NullBooleanField()
    extra_data = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'vpn_detection'


class DeviceAppAction(TimeStampedModel):
    id = models.AutoField(db_column='device_app_action_id', primary_key=True)
    device = models.ForeignKey('julo.Device', models.DO_NOTHING, db_column='device_id')
    action = models.CharField(max_length=100)
    is_completed = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'device_app_action'

    def mark_as_completed(self):
        if not self.is_completed:
            logger.info({
                "device": self.device.id,
                "device_app_action": self.action,
                "action": "mark_as_completed",
            })
            self.is_completed = True


class FraudNote(TimeStampedModel):
    id = models.AutoField(db_column='fraud_note_id', primary_key=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')
    note_text = models.TextField()
    added_by = CurrentUserField(related_name="fraud_notes")
    status_change = models.OneToOneField(
        'account.AccountStatusHistory', models.DO_NOTHING,
        db_column='account_status_history_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'fraud_note'


class FraudCrmForm(TimeStampedModel):
    id = models.AutoField(db_column='fraud_crm_form_id', primary_key=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True)
    saved_value = JSONField(default=dict)

    class Meta(object):
        db_table = 'fraud_crm_form'


def upload_async_state_upload_to(instance, filename):
    return 'upload_async_state/{0}/{1}'.format(instance.pk, filename)


class UploadAsyncStateManager(GetInstanceMixin, JuloModelManager):
    pass


class UploadAsyncState(S3ObjectModel):
    id = models.AutoField(db_column='upload_async_state_id', primary_key=True)
    task_status = models.CharField(max_length=50)
    task_type = models.CharField(max_length=255)
    url = models.CharField(max_length=200, blank=True, null=True)
    SERVICE_CHOICES = (
        ('s3', 's3'),
        ('oss', 'oss')
    )
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES, default='oss')
    agent = models.ForeignKey(
        Agent, models.DO_NOTHING, db_column='agent_id', blank=True, null=True
    )
    file = models.FileField(
        db_column='internal_path', blank=True, null=True, upload_to=upload_async_state_upload_to
    )
    objects = UploadAsyncStateManager()

    class Meta(object):
        db_table = 'upload_async_state'

    @staticmethod
    def full_upload_name(csv_name):
        path_and_name, extension = os.path.splitext(csv_name)
        if not extension:
            extension = '.csv'
        return path_and_name + extension

    @property
    def remote_upload_name(self):
        if not self.url:
            return None
        path_and_name, extension = os.path.splitext(self.url)
        if not extension:
            extension = '.csv'
        file_name_elements = path_and_name.split('/')
        return file_name_elements[-1] + extension

    @property
    def download_url(self):
        return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url)

    @property
    def error_detail(self):
        if self.task_status == UploadAsyncStateStatus.COMPLETED:
            return "All records are correct"
        else:
            return "Data invalid please check"


class ReminderEmailSettingManager(GetInstanceMixin, JuloModelManager):
    pass


class ReminderEmailSetting(TimeStampedModel):
    import datetime as dt
    EMAIL_REMINDER_MODULE_TYPE_CHOICES = (
        (EmailReminderModuleType.EMPLOYEE_FINANCING, 'Employee Financing'),
        (EmailReminderModuleType.OTHER, 'Other'),
    )

    EMAIL_REMINDER_TYPE_CHOICES = (
        (EmailReminderType.REPAYMENT, 'Repayment'),
        (EmailReminderType.OTHER, 'Other'),
    )

    id = models.AutoField(db_column='reminder_email_setting_id', primary_key=True)
    module_type = models.CharField("Tipe Modul",
                                   choices=EMAIL_REMINDER_MODULE_TYPE_CHOICES,
                                   max_length=20,
                                   default=EmailReminderModuleType.EMPLOYEE_FINANCING)
    email_type = models.CharField("Tipe Reminder",
                                  choices=EMAIL_REMINDER_TYPE_CHOICES,
                                  max_length=20,
                                  default=EmailReminderType.REPAYMENT)
    day_before = models.IntegerField(
        validators=[
            MinValueValidator(1, message='Harus lebih besar atau sama dengan 1'),
            MaxValueValidator(31, message='Harus lebih kecil atau sama dengan 31')],
        default=3
    )
    days_before = ArrayField(models.IntegerField(), default=[3, 15, 31],
                             help_text="please insert like this format: 3, 15, 31")
    days_after = ArrayField(models.IntegerField(), default=[3, 15, 31],
                            help_text="please insert like this format: 3, 15, 31")
    sender = EmailLowerCaseField(null=True, blank=True)
    recipients = models.TextField(
        blank=True, null=True, help_text="please insert like this format: julo@julofinance.com, julo2@finance.com")
    time_scheduled = models.TimeField(default=dt.time(10, 0))
    content = RichTextField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    objects = ReminderEmailSettingManager()

    class Meta(object):
        db_table = 'reminder_email_setting'
        unique_together = ('module_type', 'email_type',)

    def __str__(self):
        return "%s - %s" % (self.module_type, self.email_type)


class DjangoAdminLogChangesManager(GetInstanceMixin, JuloModelManager):
    pass


class DjangoAdminLogChanges(TimeStampedModel):
    id = models.AutoField(primary_key=True)
    group_uuid = models.TextField()
    model_name = models.TextField()
    item_changed = models.TextField()
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'django_admin_log_changes'
        verbose_name = 'Django Admin Log Change'
        verbose_name_plural = 'Django Admin Log Changes'

    objects = DjangoAdminLogChangesManager()


class FaqCheckout(TimeStampedModel):
    id = models.AutoField(db_column='faq_checkout_id', primary_key=True)
    title = models.CharField(max_length=250)
    image_url = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    order_priority = models.IntegerField(default=0)
    visible = models.BooleanField(default=True)

    class Meta(object):
        ordering = ('order_priority', 'visible')
        db_table = 'faq_checkout'

    def __str__(self):
        return "%s, %s" % (self.order_priority, self.title)


class Onboarding(TimeStampedModel):
    id = models.AutoField(db_column='onboarding_id', primary_key=True)

    description = models.CharField(max_length=200)
    status = models.NullBooleanField()

    class Meta(object):
        db_table = 'onboarding'


class MasterAgreementTemplate(TimeStampedModel):
    id = models.AutoField(db_column='master_agreement_template_id', primary_key=True)

    is_active = models.BooleanField(default=False)
    parameters = RichTextField(blank=True, null=True)
    product_name = models.CharField(max_length=100)

    class Meta(object):
        db_table = 'master_agreement_template'


class PotentialCashbackHistory(TimeStampedModel):
    id = models.AutoField(db_column='potential_cashback_id', primary_key=True)
    account_payment = BigForeignKey(
        'account_payment.AccountPayment', models.DO_NOTHING,
        db_column='account_payment_id', blank=True, null=True)
    loan = BigForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = BigForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    amount = models.IntegerField(blank=True, null=True)
    is_pn_sent = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'potential_cashback_history'


class CustomerWalletNegativeLog(TimeStampedModel):
    id = models.AutoField(primary_key=True)
    accuring_amount = models.BigIntegerField()
    available_amount = models.BigIntegerField()
    customer_wallet_history = models.ForeignKey(
        'julo.CustomerWalletHistory',
        models.DO_NOTHING, db_column='customer_wallet_history_id', blank=True, null=True)

    class Meta(object):
        db_table = 'customer_wallet_negative_log'


class CustomerRemoval(PIIVaultModel):
    PII_FIELDS = ['nik', 'email', 'phone']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'cx_pii_vault'

    class Meta(object):
        db_table = 'customer_removal'

    id = models.AutoField(db_column='customer_removal_id', primary_key=True)
    customer = BigForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    application = BigForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', null=True, blank=True
    )
    user = BigForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, db_column='user_id')
    reason = models.TextField(blank=False, null=False)
    added_by = CurrentUserField(related_name="added_by", db_column='added_by_user_id')
    nik = models.CharField(max_length=16, blank=True, null=True, db_index=True)
    email = models.EmailField(null=True, blank=True, db_index=True)
    phone = models.CharField(null=True, blank=True, max_length=15, db_index=True,
    validators=[
                ascii_validator,
                RegexValidator(
                    regex='^\+?\d{10,15}$',
                    message='phone has to be 10 to 15 numeric digits'
                )
    ])
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_tokenized = models.TextField(blank=True, null=True)
    product_line = models.ForeignKey(
        'ProductLine', models.DO_NOTHING, db_column='product_line_code', blank=True, null=True
    )

    class Meta(object):
        db_table = 'customer_removal'

    @property
    def registered_customer_date(self):
        return self.customer.cdate

    @property
    def registered_customer_phone(self):
        return self.customer.phone

    @property
    def registered_customer_email(self):
        return self.customer.email


class FraudHotspotManager(GetInstanceMixin, JuloModelManager):
    pass


class FraudHotspot(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='fraud_hotspot_id')
    geohash = models.TextField(blank=True, null=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius = models.FloatField()
    count_of_application = models.BigIntegerField(blank=True, null=True)
    addition_date = models.DateField(default=datetime_module.date.today)

    objects = FraudHotspotManager()

    class Meta(object):
        db_table = 'fraud_hotspot'


class OnboardingEligibilityChecking(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='onboarding_eligibility_checking_id')
    customer = models.ForeignKey(
        'Customer', models.DO_NOTHING, db_column='customer_id')
    fdc_inquiry = models.ForeignKey(
        'FDCInquiry', models.DO_NOTHING, db_column='fdc_inquiry_id', blank=True, null=True,
        db_constraint=False
    )
    bpjs_api_log = models.ForeignKey(
        'bpjs.BpjsAPILog', models.DO_NOTHING, db_column='bpjs_api_log_id', blank=True, null=True
    )
    fdc_check = models.SmallIntegerField(null=True)
    bpjs_check = models.SmallIntegerField(null=True)
    application = BigForeignKey(Application, models.DO_NOTHING,
                                db_column='application_id', null=True, blank=True)
    dukcapil_check = models.SmallIntegerField(null=True)
    dukcapil_response = models.ForeignKey(
        'personal_data_verification.DukcapilResponse',
        models.DO_NOTHING,
        db_column='dukcapil_response_id',
        null=True,
        blank=True,
    )
    bpjs_holdout_log = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'onboarding_eligibility_checking'


class MandiriVirtualAccountSuffixManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class MandiriVirtualAccountSuffix(PIIVaultModel):
    PII_FIELDS = ['mandiri_virtual_account_suffix']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = models.AutoField(db_column='mandiri_virtual_account_suffix_id', primary_key=True)
    mandiri_virtual_account_suffix = models.CharField(
        max_length=8,
        blank=True,
        validators=[RegexValidator(
            regex='^[0-9]+$', message='Mandiri virtual account suffix has to be numeric digits')
        ],
        unique=True
    )
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True)
    mandiri_virtual_account_suffix_tokenized = models.TextField(blank=True, null=True)
    objects = MandiriVirtualAccountSuffixManager()

    class Meta(object):
        db_table = 'mandiri_virtual_account_suffix'


class PTPLoan(TimeStampedModel):
    ptp = models.ForeignKey('PTP', models.DO_NOTHING, db_column='ptp_id')
    loan = BigForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')

    class Meta(object):
        db_table = 'ptp_loan'


class CallLogPocAiRudderPds(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)

    skiptrace_history = models.ForeignKey(
        SkiptraceHistory,
        models.DO_NOTHING,
        db_column='skiptrace_history_id',
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

    class Meta(object):
        db_table = 'call_log_poc_airudder_pds'


class ApplicationUpgradeManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationUpgrade(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='application_upgrade_id')
    application_id = models.BigIntegerField()
    application_id_first_approval = models.BigIntegerField()
    is_upgrade = models.SmallIntegerField(default=0)

    objects = ApplicationUpgradeManager()

    class Meta(object):
        db_table = 'application_upgrade'
        managed = False


class BniVirtualAccountSuffixManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class BniVirtualAccountSuffix(PIIVaultModel):
    PII_FIELDS = ['bni_virtual_account_suffix']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = models.AutoField(db_column='bni_virtual_account_suffix_id', primary_key=True)
    bni_virtual_account_suffix = models.CharField(
        max_length=7,
        blank=True,
        validators=[RegexValidator(
            regex='^[0-9]+$', message='bni virtual account suffix has to be numeric digits')
        ],
        unique=True
    )
    account_id = models.BigIntegerField(db_column='account_id', null=True, blank=True)
    bni_virtual_account_suffix_tokenized = models.TextField(blank=True, null=True)
    objects = BniVirtualAccountSuffixManager()

    class Meta(object):
        db_table = 'bni_virtual_account_suffix'
        managed = False


class ApplicationInfoCardSessionManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationInfoCardSession(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='application_infocard_session_id')
    application = models.OneToOneField(
        Application,
        models.DO_NOTHING,
        db_column='application_id'
    )
    session_daily = models.IntegerField(null=True, blank=True)
    session_limit = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    stream_lined_communication = models.ForeignKey(
        'streamlined_communication.StreamlinedCommunication', models.DO_NOTHING,
        db_column='stream_lined_communication_id', null=True, blank=True
    )
    objects = ApplicationInfoCardSessionManager()

    class Meta(object):
        db_table = 'application_infocard_session'


class CallLogPocAiRudderPds(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)

    skiptrace_history = models.ForeignKey(
        SkiptraceHistory,
        models.DO_NOTHING,
        db_column='skiptrace_history_id',
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

    class Meta(object):
        db_table = 'call_log_poc_airudder_pds'


class SuspiciousDomain(TimeStampedModel):
    id = models.AutoField(db_column='suspicious_domain_id', primary_key=True)
    email_domain = models.TextField()
    reason = models.TextField()
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)


    class Meta(object):
        managed = False
        db_table = 'suspicious_domain'


class AgentProductivityV2(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)
    type = models.TextField(blank=True, null=True)
    agent_name = models.TextField(db_column='agent', blank=True, null=True)
    local_time_convert = models.DateTimeField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    duration = models.TimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'agent_productivity_v2'


class HelpCenterManager(GetInstanceMixin, JuloModelManager):
    pass


class HelpCenterSection(TimeStampedModel):
    id = models.AutoField(db_column='help_center_section_id', primary_key=True)
    title = models.CharField(max_length=250)
    visible = models.BooleanField(default=True)
    slug = models.SlugField(
        max_length=50, db_index=True, unique=True)


    class Meta(object):
        db_table = 'help_center_section'

    def __str__(self):
        return self.title


class HelpCenterActionButtonEnum(Enum):
    unknown = None
    reset_phone_number = 'reset_phone_number'

    @classmethod
    def _missing_(cls, value):
        return cls.unknown

    @classmethod
    def choices(cls):
        return tuple((i.name, i.value) for i in cls)


class HelpCenterItem(GetInstanceMixin, TimeStampedModel):
    id = models.AutoField(db_column='help_center_item_id', primary_key=True)
    section = models.ForeignKey(HelpCenterSection, models.DO_NOTHING, related_name='help_center_items')
    question = models.CharField(max_length=250, blank=True, null=True)
    description = RichTextField(blank=True, null=True)
    alert_message = models.TextField(blank=True, null=True)
    action_button = models.CharField(max_length=50, blank=True, null=True, choices=HelpCenterActionButtonEnum.choices())
    visible = models.BooleanField(default=True)
    show_phone_number = models.BooleanField(default=False)
    objects = HelpCenterManager()


    class Meta(object):
        db_table = 'help_center_item'


class BankStatementSubmit(TimeStampedModel):
    id = models.AutoField(db_column='bank_statement_submit_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    name_in_bank = models.TextField(blank=True, null=True)
    vendor = models.TextField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    report_path = models.CharField(max_length=255, null=True, blank=True)
    is_fraud = models.NullBooleanField()

    class Meta(object):
        db_table = 'bank_statement_submit'
        managed = False

    @property
    def report_url(self):
        report_url = None
        if self.report_path:
            report_url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.report_path)
        return report_url


class BankStatementSubmitBalance(TimeStampedModel):
    id = models.AutoField(db_column='bank_statement_submit_balance_id', primary_key=True)
    bank_statement_submit = models.ForeignKey(
        BankStatementSubmit, models.DO_NOTHING, db_column='bank_statement_submit_id')
    balance_date = models.DateTimeField(blank=True, null=True)
    minimum_eod_balance = models.FloatField(default=0)
    average_eod_balance = models.FloatField(default=0)
    eom_balance = models.FloatField(default=0, blank=True, null=True)

    class Meta(object):
        db_table = 'bank_statement_submit_balance'
        managed = False


class FormAlertMessageConfig(TimeStampedModel):
    SCREEN_BIODATA = 1
    SCREEN_FAMILY = 2
    SCREEN_JOB_INFO = 3
    SCREEN_JOB_TYPE = 4
    SCREEN_FIELD_OF_WORK = 5
    SCREEN_JOB_POSITION = 6
    SCREEN_FINANCE = 7
    SCREEN_REVIEW = 8
    SCREEN_FINANCE_TOTAL_MONTHLY_INCOME = 9
    SCREEN_FINANCE_TOTAL_MONTHLY_HOUSEHOLD_EXPENSE = 10
    SCREEN_FINANCE_TOTAL_MONTHLY_DEBT = 11
    SCREEN_TURBO_FORM_MONTHLY_INCOME = 12
    SCREEN_UPGRADE_MONTHLY_EXPENSE = 13
    SCREEN_TURBO_FORM_BANK_ACCOUNT_NUMBER = 14
    SCREEN_TURB_FORM_JOB_INFO = 15

    FORM_SCREEN_CHOICES = (
        (SCREEN_BIODATA, "biodata"),
        (SCREEN_FAMILY, "family"),
        (SCREEN_JOB_INFO, "job info"),
        (SCREEN_JOB_TYPE, "job type"),
        (SCREEN_FIELD_OF_WORK, "field of work"),
        (SCREEN_JOB_POSITION, "job position"),
        (SCREEN_FINANCE, "finance"),
        (SCREEN_REVIEW, "review"),
        (SCREEN_FINANCE_TOTAL_MONTHLY_INCOME, "finance total monthly income"),
        (SCREEN_FINANCE_TOTAL_MONTHLY_HOUSEHOLD_EXPENSE, "finance total monthly household expense"),
        (SCREEN_FINANCE_TOTAL_MONTHLY_DEBT, "finance total monthly debt"),
        (SCREEN_TURBO_FORM_MONTHLY_INCOME, "turbo form monthly income"),
        (SCREEN_UPGRADE_MONTHLY_EXPENSE, "upgrade form monthly expense"),
        (SCREEN_TURBO_FORM_BANK_ACCOUNT_NUMBER, "turbo form bank account number"),
        (SCREEN_TURB_FORM_JOB_INFO, "turbo additional form job info")
    )

    id = models.AutoField(db_column='form_alert_message_id', primary_key=True)
    title = models.CharField(max_length=250, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    screen = models.PositiveSmallIntegerField(choices=FORM_SCREEN_CHOICES, blank=True, null=True)

    class Meta(object):
        db_table = 'form_alert_message'


class CashbackCounterHistory(TimeStampedModel):
    id = models.AutoField(db_column='cashback_counter_history_id', primary_key=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment', models.DO_NOTHING, db_column='account_payment_id',
        blank=True, null=True
    )
    payment = BigForeignKey(
        'julo.Payment', models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    cashback_percentage = models.FloatField(blank=True, null=True)
    customer_wallet_history = models.ForeignKey(
        'julo.CustomerWalletHistory',
        models.DO_NOTHING, db_column='customer_wallet_history_id', blank=True, null=True)
    consecutive_payment_number = models.IntegerField(null=True, blank=True)
    counter = models.IntegerField(default=0)
    reason = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'cashback_counter_history'
        index_together = [
            ['cdate'],
        ]


class FaqFeature(TimeStampedModel):
    id = models.AutoField(db_column='faq_feature_id', primary_key=True)
    title = models.TextField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    order_priority = models.IntegerField(default=0)
    visible = models.BooleanField(default=True)
    section_name = models.TextField(blank=True, null=True)

    class Meta(object):
        ordering = ('section_name', 'order_priority')
        db_table = 'faq_feature'

    def __str__(self):
        return "%s" % (self.title)


class AuthUserPiiData(TimeStampedModel):
    id = models.AutoField(db_column='auth_user_pii_data_id', primary_key=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='auth_user_id')
    email_tokenized = models.CharField(max_length=50, blank=True, null=True)

    class Meta(object):
        db_table = 'auth_user_pii_data'


class AuthUserManager(PIIVaultModelManager, UserManager):
    pass


class AuthUser(PIIVaultPrimeModel, User):
    PII_FIELDS = ['email']
    is_not_timestamp_model = True

    objects = AuthUserManager()

    class Meta(AbstractUser.Meta):
        db_table = 'auth_user'
        proxy = True


class CommsRetryFlag(TimeStampedModel):

    RETRY_FLAG_STATUS_CHOICES = (
        (CommsRetryFlagStatus.START, 'Start'),
        (CommsRetryFlagStatus.ITERATION, 'Iteration'),
        (CommsRetryFlagStatus.FINISH, 'Finish')
    )

    id = models.AutoField(db_column='comms_retry_flag_id', primary_key=True)
    flag_key = models.TextField(db_index=True)
    flag_status = models.IntegerField(
        blank=True, null=True, choices=RETRY_FLAG_STATUS_CHOICES, default=CommsRetryFlagStatus.START)
    expires_at = models.DateTimeField()

    class Meta(object):
        db_table = 'comms_retry_flag'

    def __str__(self):
        return "%s" % self.id

    @property
    def is_flag_expired(self):
        """
            Returns True if flag expired.
        """
        curr_time = timezone.localtime(timezone.now())
        return self.expires_at < curr_time

    def calculate_expires_at(self, minutes):
        """
          Calculate the expiration time based on the current time
        """
        current_time = timezone.localtime(timezone.now())
        return current_time + timezone.timedelta(minutes=minutes)

    @property
    def is_valid_for_alert(self):
        """
        Check if the RetryFlag is valid for a Slack alert based on certain conditions.
        """
        today = timezone.localtime(timezone.now())

        return (
            self.flag_status in [CommsRetryFlagStatus.START, CommsRetryFlagStatus.ITERATION] and
            self.expires_at.date() == today.date()
        )


class VariableStorageManager(GetInstanceMixin, JuloModelManager):
    pass


class VariableStorage(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='variable_storage_id')
    variable_key = models.TextField(db_index=True)
    parameters = JSONField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    objects = VariableStorageManager()

    class Meta(object):
        db_table = 'variable_storage'

    def __str__(self):
        return self.variable_key

class OtpLessHistoryManager(GetInstanceMixin, JuloModelManager):
    pass

class OtpLessHistory(TimeStampedModel):
    id = models.AutoField(db_column='otpless_history_id', primary_key=True)

    status = models.CharField(max_length=30, default='sent')
    otpless_reference_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    phone_number = models.CharField(max_length=50, blank=True,
                                    null=True, validators=[ascii_validator])
    channel = models.CharField(max_length=50, blank=True, null=True)
    is_confirmed_used = models.BooleanField(default=False)
    error_code = models.CharField(max_length=50, blank=True, null=True)
    error_message = models.CharField(max_length=50, blank=True, null=True)
    objects = OtpLessHistoryManager()

    class Meta(object):
        db_table = 'otpless_history'


class FDCRejectLoanTracking(TimeStampedModel):
    id = models.AutoField(db_column='fdc_reject_loan_tracking_id', primary_key=True)
    rejected_date = models.DateField(null=True, blank=True, db_index=True)
    number_of_other_platforms = models.IntegerField(blank=True, null=True)
    fdc_inquiry = models.ForeignKey(
        FDCInquiry, models.DO_NOTHING, db_column='fdc_inquiry_id', db_constraint=False
    )
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')

    class Meta(object):
        db_table = 'fdc_reject_loan_tracking'


class TokenRefreshStorage(TimeStampedModel):
    id = models.AutoField(db_column='token_refresh_storage_id', primary_key=True)
    scope = models.TextField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)
    token = JSONField(null=True, blank=True)

    class Meta(object):
        db_table = 'token_refresh_storage'


class CollectionPrimaryPTP(TimeStampedModel):
    PTP_STATUS_CHOICES = (
        ('Paid', 'Paid'),
        ('Paid after ptp date', 'Paid after ptp date'),
        ('Partial', 'Partial'),
        ('Not Paid', 'Not Paid'),
    )
    id = models.AutoField(db_column='primary_ptp_id', primary_key=True)
    ptp_status = models.CharField(max_length=50, blank=True, null=True, choices=PTP_STATUS_CHOICES)
    agent_assigned = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column='agent_id',
        blank=True,
        null=True,
    )
    ptp_date = models.DateField(blank=True, null=True)
    ptp_amount = models.BigIntegerField(blank=True, default=0)
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
    in_app_ptp_history = models.ForeignKey(
        InAppPTPHistory, models.DO_NOTHING, db_column='in_app_ptp_history_id', blank=True, null=True
    )
    paid_amount = models.BigIntegerField(blank=True, default=0)
    latest_paid_date = models.DateField(blank=True, null=True)
    ptp = models.ForeignKey(PTP, models.DO_NOTHING, db_column='ptp_id', blank=True, null=True)

    class Meta(object):
        db_table = 'collection_primary_ptp'


class UnderwritingRunner(TimeStampedModel):
    id = models.AutoField(db_column='underwriting_runner_id', primary_key=True)
    application_xid = models.IntegerField(db_index=True)
    decision_id = models.CharField(max_length=50, blank=True, null=True)
    http_status_code = models.IntegerField()
    error = JSONField(blank=True, null=True)
    status_code = models.IntegerField()
    status_code_history = JSONField(blank=True, null=True)
    reason = models.CharField(max_length=50, blank=True, null=True)
    credit_status = models.CharField(max_length=50, blank=True, null=True)
    credit_score = models.FloatField()
    credit_limit = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'underwriting_runner'
        managed = False


class PaymentDetailUrlLog(TimeStampedModel):
    id = BigAutoField(db_column='payment_detail_url_log_id', primary_key=True)
    source = models.TextField(db_index=True)
    warning_letter_history = models.ForeignKey(
        'julo.WarningLetterHistory',
        models.DO_NOTHING,
        db_column='warning_letter_history_id',
        blank=True,
        null=True,
    )

    class Meta(object):
        db_table = 'payment_detail_url_log'


class RedisWhiteListUploadHistory(TimeStampedModel):
    """
    Whitelist customer_ids/applications_ids intented for redis storage
    """

    CLOUD_STORAGE_CHOICES = (
        (CloudStorage.GCS, CloudStorage.GCS),
        (CloudStorage.OSS, CloudStorage.OSS),
        (CloudStorage.S3, CloudStorage.S3),
    )

    STATUS_CHOICES = (
        (RedisWhiteList.Status.PENDING, RedisWhiteList.Status.PENDING),
        (RedisWhiteList.Status.UPLOAD_SUCCESS, RedisWhiteList.Status.UPLOAD_SUCCESS),
        (RedisWhiteList.Status.UPLOAD_FAILED, RedisWhiteList.Status.UPLOAD_FAILED),
        (RedisWhiteList.Status.WHITELIST_SUCCESS, RedisWhiteList.Status.WHITELIST_SUCCESS),
        (RedisWhiteList.Status.WHITELIST_FAILED, RedisWhiteList.Status.WHITELIST_FAILED),
        (RedisWhiteList.Status.GENERAL_FAILED, RedisWhiteList.Status.GENERAL_FAILED),
    )

    id = models.AutoField(db_column='redis_whitelist_upload_history_id', primary_key=True)
    user = models.ForeignKey(
        to=settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        db_column='user_id',
    )
    whitelist_name = models.CharField(
        max_length=50, db_index=True, help_text='name of the whitelist'
    )
    cloud_storage = models.CharField(
        choices=CLOUD_STORAGE_CHOICES, default=CloudStorage.OSS, max_length=20
    )
    remote_bucket = models.TextField(null=True, blank=True)
    remote_file_path = models.TextField(null=True, blank=True)
    len_ids = models.IntegerField(null=True, blank=True, help_text="length of ids set on redis")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=RedisWhiteList.Status.PENDING,
    )
    is_latest_success = models.BooleanField(
        default=False, help_text="is latest success upload or not"
    )

    class Meta(object):
        db_table = 'redis_whitelist_upload_history'


class SkiptraceStatsModelManager(GetInstanceMixin, JuloModelManager):
    pass


class SkiptraceStatsManager(SkiptraceStatsModelManager):
    def base_upsert(self, params, values, updated=[]):
        now = timezone.localtime(timezone.now())
        num_columns = len(params) + 2

        flattened_values = []
        for row in values:
            row_values = [now, now, *row]
            flattened_values.extend(row_values)

        if not updated:
            updated = params

        q = """
        INSERT INTO ops.skiptrace_stats (cdate, udate, {params})
        VALUES {values}
        ON CONFLICT (skiptrace_id) DO UPDATE
        SET udate = EXCLUDED.udate,
            {updated}
        RETURNING skiptrace_id;
        """.format(
            params=", ".join(params),
            values=(", ".join(["(" + ", ".join(["%s"] * num_columns) + ")"] * len(values))),
            updated=", ".join(["{col} = EXCLUDED.{col}".format(col=col) for col in updated]),
        )

        with connection.cursor() as cursor:
            cursor.execute(q, flattened_values)
            returned_ids = [row[0] for row in cursor.fetchall()]

        return returned_ids

class SkiptraceStats(TimeStampedModel):
    id = BigAutoField(db_column='skiptrace_stats_id', primary_key=True)

    skiptrace = BigOneToOneField(
        Skiptrace,
        models.DO_NOTHING,
        db_column='skiptrace_id',
        related_name='skiptracestats',
    )
    skiptrace_history = BigForeignKey(
        SkiptraceHistory, models.DO_NOTHING, db_column='skiptrace_history_id', blank=True, null=True
    )
    last_rpc_ts = models.DateTimeField(blank=True, null=True)
    attempt_count = models.IntegerField(null=False, blank=False, default=0)
    rpc_count = models.IntegerField(null=False, blank=False, default=0)
    rpc_rate = models.FloatField(blank=True, null=True, default=0)
    calculation_start_date = models.DateField(blank=True, null=True)
    calculation_end_date = models.DateField(blank=True, null=True)

    objects = SkiptraceStatsManager()

    @property
    def last_rpc_string(self):
        if not self.last_rpc_ts:
            return "-"

        days = (timezone.localtime(timezone.now()) - self.last_rpc_ts).days
        return f"{days} Day{'s' if days > 1 else ''}"

    @property
    def rpc_rate_string(self):
        if self.rpc_rate == 0 and self.rpc_count == 0:
            description = "Never RPC"
        elif self.rpc_rate < 0.5:
            description = "Rarely RPC"
        elif self.rpc_rate < 1:
            description = "Often RPC"
        else:
            description = "Always RPC"

        return "%.3f%% (%s)" % (self.rpc_rate * 100, description)

    class Meta(object):
        db_table = 'skiptrace_stats'


class SkiptraceHistoryPDSDetail(TimeStampedModel):
    id = BigAutoField(db_column='skiptrace_history_detail_pds_id', primary_key=True)
    skiptrace_history_id = models.BigIntegerField(null=False, blank=False, unique=True)
    call_result_type = models.TextField(null=True, blank=True)
    nth_call = models.IntegerField(null=True, blank=True)
    ringtime = DateTimeField(blank=True, null=True)
    answertime = DateTimeField(blank=True, null=True)
    talktime = DateTimeField(blank=True, null=True)
    customize_results = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'skiptrace_history_pds_detail'
        managed = False


class LoanDurationUnit(TimeStampedModel):
    id = BigAutoField(db_column='loan_duration_unit_id', primary_key=True)
    duration_unit = models.CharField(max_length=10, null=True, blank=True)
    payment_frequency = models.CharField(max_length=15, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'loan_duration_unit'
