from __future__ import unicode_literals

import logging
from builtins import object, str

from django.contrib.postgres.fields.array import ArrayField
from django.contrib.postgres.fields.jsonb import JSONField
from django.db import models
from django.db.models import F
from django.db.utils import IntegrityError
from django.utils import timezone

from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_s3_url,
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel

logger = logging.getLogger(__name__)


class EtlStatus(models.Model):
    id = models.BigIntegerField(db_column='etl_status_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    started_tasks = ArrayField(models.CharField(max_length=100), default=list)
    executed_tasks = ArrayField(models.CharField(max_length=100), default=list)
    errors = JSONField(default=dict)
    meta_data = JSONField(default=dict)

    class Meta(object):
        db_table = '"ana"."etl_status"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class EtlJob(TimeStampedModel):
    INITIATED = 'initiated'
    SCRAPE_SUCCESS = 'scrape_success'
    SCRAPE_FAILED = 'scrape_failed'
    LOAD_SUCCESS = 'load_success'
    LOAD_FAILED = 'load_failed'
    AUTH_FAILED = 'auth_failed'
    AUTH_SUCCESS = 'auth_success'
    FAILED = 'failed'
    DONE = 'done'
    ETL_JOB_STATUS_CHOICES = (
        (INITIATED, 'ETL job started'),
        (AUTH_FAILED, 'authentication/login failed'),
        (AUTH_SUCCESS, 'authentication/login success'),
        (FAILED, 'ETL job failed'),
        (DONE, 'ETL job done'),
    )

    id = models.BigIntegerField(db_column='etl_job_id', primary_key=True)
    application_id = models.BigIntegerField()
    customer_id = models.BigIntegerField()

    status = models.CharField(max_length=50, choices=ETL_JOB_STATUS_CHOICES, default='initiated')
    error = models.TextField(null=True, blank=True)

    DATA_TYPE_CHOICES = (
        ('dsd', 'Device scraped data'),
        ('gmail', 'Emails from gmail'),
        ('mandiri', 'Transactions from Mandiri'),
        ('bca', 'Transactions from BCA'),
        (
            'ktp',
            'KTP OCR',
        ),
    )
    data_type = models.CharField(max_length=50, choices=DATA_TYPE_CHOICES)

    dsd_id = models.BigIntegerField(null=True, blank=True)
    temp_dir = models.CharField(max_length=200, null=True, blank=True)
    s3_url_raw = models.CharField(max_length=200, null=True, blank=True)
    s3_url_report = models.CharField(max_length=200, null=True, blank=True)
    s3_url_bank_report = models.CharField(max_length=200, null=True, blank=True)
    job_type = models.CharField(max_length=200, default='normal')

    class Meta(object):
        db_table = '"ana"."etl_job"'
        managed = False

    def get_bank_report_url(self):
        if self.s3_url_bank_report:
            bucket = self.s3_url_bank_report.split('/')[0] if self.s3_url_bank_report else ''
            maxsplit = 1
            url_parts = (
                self.s3_url_bank_report.split('/', maxsplit) if self.s3_url_bank_report else ''
            )
            if len(url_parts) < 2:
                object_path = ''
            else:
                object_path = url_parts[1]
            if object_path and bucket:
                url = get_s3_url(bucket, object_path)
                return url


class PdIncomeVerification(TimeStampedModel):
    id = models.BigIntegerField(db_column='pd_income_verification_id', primary_key=True)

    etl_job_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    estimated_salary = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    monthly_income = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    yes_no_income = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."pd_income_verification"'
        managed = False


class PdFraudDetection(TimeStampedModel):
    id = models.BigIntegerField(db_column='pd_fraud_detection_id', primary_key=True)

    etl_job_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    self_email = models.TextField(null=True, blank=True)
    self_field_name = models.TextField(null=True, blank=True)
    matching_value = models.TextField(null=True, blank=True)
    matched_field_name = models.TextField(null=True, blank=True)
    matched_email = models.TextField(null=True, blank=True)
    matched_appl_id = models.BigIntegerField(null=True, blank=True)
    matched_appl_status_code = models.IntegerField(null=True, blank=True)
    matched_appl_status = models.TextField(null=True, blank=True)
    matched_appl_status_reason = models.TextField(null=True, blank=True)
    matched_appl_udate = models.DateField(null=True, blank=True)
    matched_loan_status = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."pd_fraud_detection"'
        managed = False


class PdCreditModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_credit_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.PositiveIntegerField()
    probability_fpd = models.FloatField()
    product = models.CharField(max_length=20, null=True, blank=True)
    credit_score_type = models.CharField(null=True, blank=True, max_length=200)
    pgood = models.FloatField(null=True, blank=True)
    has_fdc = models.NullBooleanField(default=None)

    class Meta(object):
        db_table = '"ana"."pd_credit_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdWebModelResult(models.Model):
    """model to store credit score of Web app"""

    id = models.BigIntegerField(db_column='pd_web_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.CharField(null=True, blank=True, max_length=200)
    probability_fpd = models.FloatField()
    pgood = models.FloatField(null=True, blank=True)
    has_fdc = models.NullBooleanField(null=True, default=None)

    class Meta(object):
        db_table = '"ana"."pd_web_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdBukalapakModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_bukalapak_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)
    version = models.CharField(max_length=200)
    probability_fpd = models.FloatField()
    score = models.CharField(max_length=200)

    class Meta(object):
        db_table = '"ana"."pd_bukalapak_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdBukalapakUnsupervisedModelResult(models.Model):
    id = models.BigIntegerField(
        db_column='pd_bukalapak_unsupervised_model_result_id', primary_key=True
    )

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)
    version = models.CharField(max_length=200)
    cluster = models.FloatField()
    cluster_type = models.CharField(max_length=200)

    class Meta(object):
        db_table = '"ana"."pd_bukalapak_unsupervised_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdThinFileModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_thin_file_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.PositiveIntegerField()
    probability_fpd = models.FloatField()

    class Meta(object):
        db_table = '"ana"."pd_thin_file_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdIncomePredictModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_income_predict_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.PositiveIntegerField()
    value = models.FloatField()

    class Meta(object):
        db_table = '"ana"."pd_income_predict_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdIncomeTrustModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_income_trust_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.PositiveIntegerField()
    value = models.FloatField()
    predicted_income = models.FloatField(null=True, blank=True)
    tier = models.IntegerField(blank=True, null=True)
    mae = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."pd_income_trust_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdExpensePredictModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_expense_predict_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.PositiveIntegerField()
    value = models.FloatField()

    class Meta(object):
        db_table = '"ana"."pd_expense_predict_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class AutoDataCheck(models.Model):
    """
    models for auto_data_check table which is on ana schema
    """

    id = models.BigIntegerField(db_column='data_check_id', primary_key=True)
    timestamp = models.DateTimeField(auto_now=True)
    application_id = models.BigIntegerField(db_index=True)

    check_set = models.CharField(max_length=50)
    data_to_check = models.CharField(max_length=100)
    description = models.CharField(max_length=200)

    is_okay = models.BooleanField()
    text_value = models.CharField(null=True, blank=True, max_length=150)
    number_value = models.BigIntegerField(null=True, blank=True)
    latest = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'ana\".\"auto_data_check'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class FinfiniStatus(TimeStampedModel):
    id = models.BigIntegerField(db_column='finfini_status_id', primary_key=True)

    name = models.CharField(max_length=200)
    status = models.CharField(max_length=200)
    vendor_type = models.CharField(max_length=200)

    class Meta(object):
        db_table = '"ana"."finfini_status"'
        managed = False


class SdDeviceApp(TimeStampedModel):
    id = models.BigIntegerField(db_column='sd_device_app_id', primary_key=True)

    etl_job_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    app_name = models.TextField(null=True, blank=True)
    app_package_name = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."sd_device_app"'
        managed = False


class PdOperationBypassModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_operation_bypass_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.PositiveIntegerField()
    probability_fpd = models.FloatField()

    product = models.CharField(null=True, blank=True, max_length=20)

    class Meta(object):
        db_table = '"ana"."pd_operation_bypass_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdPartnerModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_partner_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.PositiveIntegerField()
    probability_fpd = models.FloatField()
    pgood = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."pd_partner_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PublicFile(TimeStampedModel):
    id = models.AutoField(db_column='public_file_id', primary_key=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    file_url = models.URLField(null=True, blank=True)

    class Meta(object):
        db_table = 'public_file'

    def __str__(self):
        return "%s: %s, %s" % (
            self.id,
            self.name,
            self.file_url,
        )


class PdCollectionModelResultManager(JuloModelManager):
    def filter_risky_payment_on_dpd_minus(self, payment_ids):
        result = list(payment_ids)
        today = timezone.localtime(timezone.now()).date()

        risky_payment = (
            self.get_queryset()
            .annotate(dpd_payment=today - F('payment__due_date'))
            .filter(
                payment__in=payment_ids,
                prediction_date=today,
                model_version__contains='Now or Never',
            )
        )
        risk_payment_data = []

        for pd_collection in risky_payment:

            if (
                pd_collection.dpd_payment < 0
                and str(pd_collection.dpd_payment) == pd_collection.range_from_due_date
            ):
                result.remove(pd_collection.payment_id)

                risk_payment_data.append(
                    [
                        pd_collection.payment_id,
                        pd_collection.range_from_due_date,
                        pd_collection.model_version,
                    ]
                )

        return result, risk_payment_data

    def filter_risky_account_payment_on_dpd_minus(self, account_payment_ids):
        from juloserver.nexmo.models import IsRiskyExcludedDetail

        result = list(account_payment_ids)
        today = timezone.localtime(timezone.now()).date()

        risky_account_payment = (
            self.get_queryset()
            .annotate(dpd_account_payment=today - F('account_payment__due_date'))
            .filter(
                account_payment__in=result,
                prediction_date=today,
                model_version__contains='Now or Never',
            )
            .distinct('account_payment_id')
        )

        risky_account_payment_list = []
        for pd_collection in risky_account_payment:
            if (
                pd_collection.dpd_account_payment < 0
                and str(pd_collection.dpd_account_payment) == pd_collection.range_from_due_date
            ):
                result.remove(pd_collection.account_payment_id)

                is_risky_added = IsRiskyExcludedDetail.objects.filter(
                    account_payment_id=pd_collection.account_payment_id,
                    dpd=pd_collection.range_from_due_date,
                    model_version=pd_collection.model_version,
                    cdate__date=today,
                ).last()

                if not is_risky_added:
                    risky_account_payment_list.append(
                        IsRiskyExcludedDetail(
                            account_payment_id=pd_collection.account_payment_id,
                            dpd=pd_collection.range_from_due_date,
                            model_version=pd_collection.model_version,
                        )
                    )

        if risky_account_payment_list:
            try:
                IsRiskyExcludedDetail.objects.bulk_create(risky_account_payment_list)
            except IntegrityError as e:
                logger.warning(
                    {'action': 'filter_risky_account_payment_on_dpd_minus', 'error': str(e)},
                    exc_info=True,
                )
                get_julo_sentry_client().captureExceptions()

        return result


class PdCollectionModelResult(models.Model):
    id = models.AutoField(db_column='pd_collection_model_result_id', primary_key=True)
    cdate = models.DateTimeField(auto_now=True)
    payment = models.ForeignKey(
        'julo.Payment', models.DO_NOTHING, db_column='payment_id', blank=True, null=True
    )
    model_version = models.CharField(max_length=500)
    prediction_before_call = models.FloatField(db_column='prediction_before_call')
    prediction_after_call = models.FloatField(db_column='prediction_after_call')
    due_amount = models.BigIntegerField()
    range_from_due_date = models.CharField(max_length=10)
    sort_rank = models.IntegerField()
    objects = PdCollectionModelResultManager()
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
    sort_method = models.TextField(blank=True, null=True)
    prediction_date = models.DateField(db_column='predict_date', blank=True, null=True)
    experiment_group = models.TextField(blank=True, null=True)
    prediction_source = models.CharField(null=True, blank=True, max_length=200)
    segment_name = models.CharField(null=True, blank=True, max_length=200)

    class Meta(object):
        db_table = '"ana"."pd_collection_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdFraudModelResult(models.Model):
    id = models.AutoField(db_column='pd_fraud_model_result_id', primary_key=True)
    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    version = models.CharField(null=True, blank=True, max_length=200)
    probability_fpd = models.FloatField()

    class Meta(object):
        db_table = '"ana"."pd_fraud_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdAffordabilityModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_affordability_model_result_id', primary_key=True)
    cdate = models.DateTimeField(auto_now_add=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    model_version = models.CharField(null=True, blank=True, max_length=200)
    predicted_affordability = models.FloatField(db_column='predicted_affordability')
    lookup_affordability = models.FloatField(db_column='lookup_affordability')
    iqr_lower_bound = models.FloatField(db_column='iqr_lower_bound')
    iqr_upper_bound = models.FloatField(db_column='iqr_upper_bound')
    udate = models.DateTimeField(auto_now=True)
    affordability_threshold = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."pd_affordability_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class SdDeviceNavlog(models.Model):
    id = models.BigIntegerField(db_column='sd_device_navlog_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)

    etl_job_id = models.BigIntegerField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    app_version = models.TextField()
    android_id = models.TextField()
    gcm_reg_id = models.TextField(null=True, blank=True)
    device_model_name = models.TextField(blank=True, null=True)
    page_id = models.TextField()
    action = models.TextField()
    type = models.TextField(null=True, blank=True)
    nav_log_ts = models.DateTimeField()
    nav_log_dt = models.DateField(blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."sd_device_navlog"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class LoanRefinancingScore(models.Model):
    application_id = models.BigIntegerField(db_column='application_id', primary_key=True)
    loan = models.ForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    fullname = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    monthly_income = models.BigIntegerField(default=0)
    total_expense = models.BigIntegerField(default=0)
    total_due_amt = models.BigIntegerField(default=0)
    outstanding_principal = models.BigIntegerField(default=0)
    outstanding_interest = models.BigIntegerField(default=0)
    outstanding_latefee = models.BigIntegerField(default=0)
    rem_installment = models.IntegerField(db_column='rem_installment')
    ability_score = models.FloatField(db_column='ability_score')
    willingness_score = models.FloatField(db_column='willingness_score')
    oldest_payment_num = models.IntegerField(db_column='oldest_payment_num')
    oldest_due_date = models.DateField(blank=True, null=True)
    is_covid_risky = models.NullBooleanField()
    bucket = models.CharField(max_length=254)

    class Meta(object):
        db_table = '"ana"."loan_refinancing_score"'
        managed = False

    @property
    def is_covid_risky_boolean(self):
        return True if self.is_covid_risky == 'yes' else False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class LoanRefinancingScoreJ1(TimeStampedModel):
    id = models.BigIntegerField(db_column='loan_refinancing_score_j1_id', primary_key=True)
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id')
    ability_score = models.FloatField(db_column='ability_score')
    willingness_score = models.FloatField(db_column='willingness_score')
    is_covid_risky = models.NullBooleanField()
    bucket = models.TextField()

    class Meta(object):
        db_table = '"ana"."loan_refinancing_score_j1"'
        managed = False

    @property
    def is_covid_risky_boolean(self):
        return True if self.is_covid_risky == 'yes' else False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdClcsPrimeResult(models.Model):
    id = models.AutoField(db_column='pd_clcs_prime_result_id', primary_key=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    partition_date = models.DateField(blank=True, null=True)
    clcs_prime_score = models.FloatField()
    a_score = models.FloatField()
    a_score_version = models.CharField(null=True, blank=True, max_length=256)
    b_score = models.FloatField(null=True)
    b_score_version = models.CharField(null=True, blank=True, max_length=256)

    class Meta(object):
        db_table = '"ana"."pd_clcs_prime_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdBTTCModelResult(models.Model):
    id = models.AutoField(db_column='pd_bttc_model_result_id', primary_key=True)
    cdate = models.DateTimeField(auto_now=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id', blank=True, null=True
    )
    payment = models.ForeignKey(
        'julo.Payment', models.DO_NOTHING, db_column='payment_id', blank=True, null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )
    model_version = models.CharField(max_length=250)
    probability_range_a = models.FloatField()
    probability_range_b = models.FloatField()
    probability_range_c = models.FloatField()
    probability_range_d = models.FloatField()
    threshold = models.CharField(max_length=500)
    is_range_a = models.BooleanField()
    is_range_b = models.BooleanField()
    is_range_c = models.BooleanField()
    is_range_d = models.BooleanField()
    prediction_date = models.BigIntegerField()
    range_from_due_date = models.BigIntegerField()
    is_active = models.BooleanField()
    experiment_group = models.TextField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    predict_date = models.DateField(blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."pd_bttc_model_result"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class GAAppActivity(models.Model):
    id = models.AutoField(db_column='ga_app_activity_id', primary_key=True)
    cdate = models.DateTimeField(auto_now=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    event_name = models.TextField(blank=True, null=True)
    event_date = models.DateTimeField(blank=True, null=True)
    ga_batch_download_task_id = models.IntegerField(blank=True, null=True)
    app_version = models.TextField(blank=True, null=True)
    device_id = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."ga_app_activity"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdCollectionModelResultExcludeManager(JuloModelManager):
    pass


class PdCollectionModelResultExclude(models.Model):
    id = models.AutoField(db_column='pd_collection_model_result_exclude_id', primary_key=True)
    cdate = models.DateTimeField(auto_now=True)
    payment = BigForeignKey(
        'julo.Payment', models.DO_NOTHING, db_column='payment_id', blank=True, null=True
    )
    model_version = models.TextField(blank=True, null=True)
    prediction_before_call = models.FloatField(db_column='prediction_before_call')
    prediction_after_call = models.FloatField(db_column='prediction_after_call')
    due_amount = models.BigIntegerField()
    range_from_due_date = models.TextField(blank=True, null=True)
    excluded_from_bucket = models.BooleanField()
    sort_method = models.TextField(blank=True, null=True)
    sort_rank = models.IntegerField()
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
    prediction_date = models.DateField(db_column='predict_date', blank=True, null=True)
    customer = BigForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id', blank=True, null=True
    )

    objects = PdCollectionModelResultExcludeManager()

    class Meta(object):
        db_table = '"ana"."pd_collection_model_result_exclude"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PdIncomeModelResult(models.Model):
    id = models.AutoField(db_column='pd_income_model_result_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)
    model_version = models.CharField(max_length=200)
    income_value = models.FloatField()
    income_value_adjusted = models.FloatField()
    label = models.CharField(max_length=200)
    is_active = models.BooleanField()

    class Meta(object):
        db_table = '"ana"."pd_income_model_result"'
        managed = False


class PdCustomerLifetimeModelResult(models.Model):
    id = models.AutoField(db_column='pd_customer_lifetime_model_result_id', primary_key=True)
    cdate = models.DateTimeField(auto_now_add=True)
    udate = models.DateTimeField(auto_now=True)
    predict_date = models.DateField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)
    lifetime_value = models.CharField(max_length=50)
    has_transact_in_range_date = models.IntegerField()
    model_version = models.CharField(max_length=50)
    range_from_x190_date = models.IntegerField()

    class Meta(object):
        db_table = '"ana"."pd_customer_lifetime_model_result"'
        managed = False


class PdBscoreModelResult(TimeStampedModel):
    id = models.AutoField(db_column='pd_bscore_model_result_id', primary_key=True)
    predict_date = models.DateField(blank=True, null=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    pgood = models.FloatField(null=True)
    model_version = models.CharField(null=True, blank=True, max_length=256)

    class Meta(object):
        db_table = '"ana"."pd_bscore_model_result"'
        managed = False


class PdClikModelResult(models.Model):
    id = models.BigIntegerField(db_column='pd_clik_model_result_id', primary_key=True)

    cdate = models.DateTimeField(auto_now_add=True)
    application_id = models.BigIntegerField(db_index=True)
    model_version = models.CharField(max_length=50)
    pgood = models.FloatField(null=True, blank=True)
    clik_flag_matched = models.NullBooleanField(default=None)

    class Meta(object):
        db_table = '"ana"."pd_clik_model_result"'
        managed = False

        managed = False


class CollectionCallPriority(models.Model):
    id = models.AutoField(db_column='collection_call_priority_id', primary_key=True)
    partition_date = models.DateField(blank=True, null=True)
    customer_id = models.BigIntegerField(db_index=True)
    skiptrace_id = models.BigIntegerField(blank=True, null=True)
    phone_number = models.TextField(blank=True, null=True)
    contact_source = models.TextField(blank=True, null=True)
    version = models.TextField(blank=True, null=True)
    experiment_group = models.TextField(blank=True, null=True)
    sort_rank = models.IntegerField()

    class Meta(object):
        db_table = '"ana"."collection_call_priority"'
        managed = False
