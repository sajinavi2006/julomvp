from __future__ import unicode_literals

from builtins import object

from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models

from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)


class SdBankAccount(TimeStampedModel):
    id = models.BigIntegerField(db_column='sd_bank_account_id', primary_key=True)
    etl_job_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    bank_name = models.TextField(null=True, blank=True)
    customer_name = models.TextField(null=True, blank=True)
    account_number = models.TextField(null=True, blank=True)
    last_login_ts = models.DateTimeField(null=True, blank=True)
    last_login_dt = models.DateField(null=True, blank=True, db_index=True)  # add date inplace
    username_bank = models.CharField(max_length=32, null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."sd_bank_account"'
        managed = False


class SdBankStatementDetail(TimeStampedModel):
    id = models.BigIntegerField(db_column='sd_bank_statement_detail_id', primary_key=True)

    etl_job_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    posting_date = models.DateField(null=True, blank=True, db_index=True)  # add index inplace
    branch = models.TextField(null=True, blank=True)
    transaction_desc = models.TextField(null=True, blank=True)
    transaction_type = models.TextField(null=True, blank=True)
    transaction_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    debit_credit = models.TextField(null=True, blank=True)
    ending_balance = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    sd_bank_account = models.ForeignKey(
        'SdBankAccount', models.DO_NOTHING, db_column='sd_bank_account_id'
    )

    class Meta(object):
        db_table = '"ana"."sd_bank_statement_detail"'
        managed = False


class PdBankScrapeModelResultManager(GetInstanceMixin, JuloModelManager):
    pass


class PdBankScrapeModelResult(TimeStampedModel):
    id = models.BigIntegerField(db_column='pd_bank_scrape_model_result_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    sd_bank_statement_detail_id = models.BigIntegerField()
    probability_is_salary = models.FloatField()
    model_version = models.CharField(null=True, blank=True, max_length=200)
    model_threshold = models.FloatField(null=True, blank=True)
    model_selection_version = models.BigIntegerField(null=True, blank=True)
    transaction_amount = models.BigIntegerField(null=True, blank=True)
    stated_income = models.BigIntegerField(null=True, blank=True)
    max_deviation_income = models.FloatField(null=True, blank=True)
    processed_income = models.BigIntegerField(null=True, blank=True)

    objects = PdBankScrapeModelResultManager()

    class Meta(object):
        db_table = '"ana"."pd_bank_scrape_model_result"'
        managed = False


class EtlRepeatStatus(TimeStampedModel):
    id = BigAutoField(db_column='etl_repeat_status_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    started_tasks = ArrayField(models.CharField(max_length=100), default=list)
    executed_tasks = ArrayField(models.CharField(max_length=100), default=list)
    errors = JSONField(default=dict)
    meta_data = JSONField(default=dict)
    repeat_number = models.BigIntegerField(db_column='repeat_number')

    class Meta:
        db_table = '"ana"."etl_repeat_status"'
        managed = False


class PdCustomerSegmentModelResult(TimeStampedModel):
    id = models.AutoField(db_column='pd_customer_segment_model_result_id', primary_key=True)
    partition_date = models.DateField()
    customer_id = models.BigIntegerField()
    customer_segment = models.TextField(null=True, blank=True)
    model_version = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."pd_customer_segment_model_result"'
        managed = False


class PdApplicationFraudModelResultManager(GetInstanceMixin, JuloModelManager):
    pass


class PdApplicationFraudModelResult(TimeStampedModel):
    """
    This class model is used for Mycroft Scoring (despite the general-sounding name).
    """

    id = BigAutoField(db_column='pd_application_fraud_model_result_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    customer_id = models.BigIntegerField(db_index=True)

    pgood = models.FloatField()
    model_version = models.CharField(max_length=255)
    label = models.CharField(max_length=255)

    objects = PdApplicationFraudModelResultManager()

    class Meta:
        db_table = '"ana"."pd_application_fraud_model_result"'
        managed = False


class PdChurnModelResult(TimeStampedModel):
    id = BigAutoField(db_column='pd_churn_model_result_id', primary_key=True)
    predict_date = models.DateField()
    customer_id = models.BigIntegerField()
    model_version = models.CharField(max_length=50)
    pchurn = models.FloatField()
    experiment_group = models.CharField(max_length=255)

    class Meta:
        db_table = '"ana"."pd_churn_model_result"'
        managed = False


class ZeroInterestExclude(TimeStampedModel):
    id = BigAutoField(db_column='zero_interest_exclude_id', primary_key=True)
    customer_id = models.BigIntegerField()

    class Meta:
        db_table = '"ana"."zero_interest_exclude"'
        managed = False


class SdDevicePhoneDetail(TimeStampedModel):
    id = BigAutoField(db_column='sd_device_phone_detail_id', primary_key=True)
    customer_id = models.BigIntegerField()
    application_id = models.BigIntegerField()
    product = models.CharField(max_length=100)
    user = models.CharField(max_length=100)
    device = models.CharField(max_length=100)
    osapilevel = models.CharField(max_length=100)
    version = models.CharField(max_length=100)
    manufacturer = models.CharField(max_length=100)
    serial = models.CharField(max_length=100)
    device_type = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    phone_device_id = models.CharField(max_length=100)
    sdk = models.IntegerField()
    brand = models.CharField(max_length=100)
    display = models.CharField(max_length=100)
    device_id = models.IntegerField()
    repeat_number = models.CharField(max_length=100)

    class Meta:
        db_table = '"ana"."sd_device_phone_detail"'
        managed = False


class EligibleCheck(TimeStampedModel):
    id = BigAutoField(db_column='eligible_check_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    check_name = models.CharField(max_length=200)

    is_okay = models.BooleanField()
    version = models.CharField(max_length=10)
    parameter = JSONField(blank=True, null=True)

    class Meta:
        db_table = '"ana"."eligible_check"'
        managed = False


class DynamicCheck(TimeStampedModel):
    id = BigAutoField(db_column='dynamic_check_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    is_okay = models.BooleanField()
    is_holdout = models.BooleanField()
    check_name = models.CharField(max_length=100, null=True, blank=True)
    version = models.CharField(max_length=10, null=True, blank=True)

    class Meta:
        db_table = '"ana"."dynamic_check"'
        managed = False


class FDCPlatformCheckBypass(TimeStampedModel):
    id = BigAutoField(db_column='fdc_platform_check_bypass_id', primary_key=True)
    application_id = models.BigIntegerField()

    class Meta:
        db_table = '"ana"."fdc_platform_check_bypass"'
        managed = False


class CustomerSegmentationComms(TimeStampedModel):
    id = BigAutoField(db_column='customer_segmentation_comms_id', primary_key=True)
    customer_id = models.BigIntegerField(db_index=True)
    customer_segment = models.CharField(max_length=200)
    schema_amount = models.CharField(max_length=200)
    default_monthly_installment = models.CharField(max_length=200)
    np_monthly_installment = models.CharField(max_length=200)
    np_provision_amount = models.CharField(max_length=200)
    np_monthly_interest_amount = models.CharField(max_length=200)
    promo_code_churn = models.CharField(max_length=200)
    is_np_lower = models.CharField(max_length=200)
    is_create_loan = models.CharField(max_length=200)
    customer_segment_group = models.CharField(max_length=200)
    churn_group = models.CharField(max_length=200)
    extra_params = JSONField(default=dict())

    class Meta:
        db_table = '"ana"."customer_segmentation_comms"'
        managed = False


class FDCLoanDataUpload(TimeStampedModel):
    fdc_loan_data_upload_id = models.BigIntegerField(primary_key=True)
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
    pendapatan = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = '"ana"."fdc_loan_data_upload"'
        managed = False


class FDCInquiryPrioritizationReason2(TimeStampedModel):
    id = BigAutoField(db_column='fdc_inquiry_prioritization_reason_2_id', primary_key=True)
    serving_date = models.DateField(null=True, blank=True)
    customer_id = models.BigIntegerField()
    ktp = models.TextField()
    priority_bin = models.IntegerField(default=0)
    priority_rank = models.BigIntegerField(default=0)

    class Meta:
        db_table = '"ana"."fdc_inquiry_prioritization_reason_2"'
        managed = False


class LoanLenderTaggingDpd(TimeStampedModel):
    id = BigAutoField(db_column='loan_lender_tagging_loan_dpd_id', primary_key=True)
    loan_id = models.BigIntegerField(db_index=True)
    loan_dpd = models.IntegerField()

    class Meta:
        db_table = '"ana"."loan_lender_tagging_loan_dpd"'
        managed = False


class CustomerHighLimitUtilization(TimeStampedModel):
    id = models.AutoField(db_column='customer_high_limit_utilization_id', primary_key=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    is_high = models.BooleanField(default=False)

    class Meta(object):
        db_table = '"ana"."customer_high_limit_utilization"'
        managed = False


class PdCreditEarlyModelResult(TimeStampedModel):
    id = models.AutoField(db_column='pd_credit_early_model_result_id', primary_key=True)
    application_id = models.BigIntegerField()
    customer_id = models.BigIntegerField()
    model_version = models.CharField(max_length=200)
    pgood = models.FloatField()
    label = models.CharField(max_length=200)

    class Meta:
        db_table = '"ana"."pd_credit_early_model_result"'
        managed = False


class CredgenicsPoC(TimeStampedModel):
    id = models.AutoField(db_column='credgenics_poc_id', primary_key=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    account_id = models.BigIntegerField(null=True, blank=True)
    bucket = models.CharField(max_length=200, null=True, blank=True)
    cycle_batch = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."credgenics_poc"'
        managed = False


class CollectionB5(TimeStampedModel):
    id = models.AutoField(db_column='collection_b5_id', primary_key=True)
    assigned_to = models.CharField(max_length=200, null=True, blank=True)
    assignment_datetime = models.DateTimeField(null=True, blank=True)
    assignment_generated_date = models.DateField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    account_payment_id = models.BigIntegerField(null=True, blank=True)
    nama_customer = models.CharField(max_length=200, null=True, blank=True)
    nama_perusahaan = models.CharField(max_length=200, null=True, blank=True)
    posisi_karyawan = models.CharField(max_length=200, null=True, blank=True)
    dpd = models.IntegerField(null=True, blank=True)
    total_denda = models.IntegerField(null=True, blank=True)
    total_due_amount = models.IntegerField(null=True, blank=True)
    total_outstanding = models.IntegerField(null=True, blank=True)
    angsuran_ke = models.IntegerField(null=True, blank=True)
    tanggal_jatuh_tempo = models.DateField(null=True, blank=True)
    nama_pasangan = models.CharField(max_length=200, null=True, blank=True)
    nama_kerabat = models.CharField(max_length=200, null=True, blank=True)
    hubungan_kerabat = models.CharField(max_length=200, null=True, blank=True)
    alamat = models.CharField(max_length=200, null=True, blank=True)
    kota = models.CharField(max_length=200, null=True, blank=True)
    jenis_kelamin = models.CharField(max_length=200, null=True, blank=True)
    tgl_lahir = models.DateField(null=True, blank=True)
    tgl_gajian = models.IntegerField(null=True, blank=True)
    tujuan_pinjaman = models.CharField(max_length=200, null=True, blank=True)
    tgl_upload = models.DateField(null=True, blank=True)
    va_bca = models.CharField(max_length=200, null=True, blank=True)
    va_permata = models.CharField(max_length=200, null=True, blank=True)
    va_maybank = models.CharField(max_length=200, null=True, blank=True)
    va_alfamart = models.CharField(max_length=200, null=True, blank=True)
    va_indomaret = models.CharField(max_length=200, null=True, blank=True)
    va_mandiri = models.CharField(max_length=200, null=True, blank=True)
    tipe_produk = models.CharField(max_length=200, null=True, blank=True)
    last_pay_date = models.CharField(max_length=200, null=True, blank=True)
    last_pay_amount = models.CharField(max_length=200, null=True, blank=True)
    partner_name = models.CharField(max_length=200, null=True, blank=True)
    last_agent = models.CharField(max_length=200, null=True, blank=True)
    last_call_status = models.CharField(max_length=200, null=True, blank=True)
    refinancing_status = models.CharField(max_length=200, null=True, blank=True)
    activation_amount = models.CharField(max_length=200, null=True, blank=True)
    program_expiry_date = models.CharField(max_length=200, null=True, blank=True)
    address_kodepos = models.CharField(max_length=200, null=True, blank=True)
    phonenumber = models.CharField(max_length=200, null=True, blank=True)
    mobile_phone_2 = models.CharField(max_length=200, null=True, blank=True)
    no_telp_pasangan = models.CharField(max_length=200, null=True, blank=True)
    telp_perusahaan = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        db_table = '"ana"."collection_b5"'
        managed = False


class B2ExcludeFieldCollection(TimeStampedModel):
    id = models.AutoField(db_column='b2_exclude_field_collection_id', primary_key=True)
    account_payment_id = models.BigIntegerField(null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    assignment_date = models.DateField(null=True, blank=True)
    dab_dpd = models.TextField(null=True, blank=True)
    dab_bucket = models.TextField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."b2_exclude_field_collection"'
        managed = False


class B3ExcludeFieldCollection(TimeStampedModel):
    id = models.AutoField(db_column='b3_exclude_field_collection_id', primary_key=True)
    account_payment_id = models.BigIntegerField(null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    assignment_date = models.DateField(null=True, blank=True)
    dab_dpd = models.TextField(null=True, blank=True)
    dab_bucket = models.TextField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."b3_exclude_field_collection"'
        managed = False


class MLMjolnirResult(TimeStampedModel):
    id = models.AutoField(db_column='ml_mjolnir_result_id', primary_key=True)
    recording_report_id = models.BigIntegerField()
    model_version = models.TextField()
    call_summary = models.TextField()
    call_summary_personal = models.TextField()
    call_summary_company = models.TextField()
    call_summary_kin = models.TextField()

    class Meta:
        db_table = '"ana"."ml_mjolnir_result"'
        managed = False


class CollectionB6(TimeStampedModel):
    id = models.AutoField(db_column='collection_b6_id', primary_key=True)
    assigned_to = models.CharField(max_length=200, null=True, blank=True)
    assignment_datetime = models.DateTimeField(null=True, blank=True)
    assignment_generated_date = models.DateField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    account_payment_id = models.BigIntegerField(null=True, blank=True)
    nama_customer = models.CharField(max_length=200, null=True, blank=True)
    nama_perusahaan = models.CharField(max_length=200, null=True, blank=True)
    posisi_karyawan = models.CharField(max_length=200, null=True, blank=True)
    dpd = models.IntegerField(null=True, blank=True)
    total_denda = models.IntegerField(null=True, blank=True)
    total_due_amount = models.IntegerField(null=True, blank=True)
    total_outstanding = models.IntegerField(null=True, blank=True)
    angsuran_ke = models.IntegerField(null=True, blank=True)
    tanggal_jatuh_tempo = models.DateField(null=True, blank=True)
    nama_pasangan = models.CharField(max_length=200, null=True, blank=True)
    nama_kerabat = models.CharField(max_length=200, null=True, blank=True)
    hubungan_kerabat = models.CharField(max_length=200, null=True, blank=True)
    alamat = models.CharField(max_length=200, null=True, blank=True)
    kota = models.CharField(max_length=200, null=True, blank=True)
    jenis_kelamin = models.CharField(max_length=200, null=True, blank=True)
    tgl_lahir = models.DateField(null=True, blank=True)
    tgl_gajian = models.IntegerField(null=True, blank=True)
    tujuan_pinjaman = models.CharField(max_length=200, null=True, blank=True)
    tgl_upload = models.DateField(null=True, blank=True)
    va_bca = models.CharField(max_length=200, null=True, blank=True)
    va_permata = models.CharField(max_length=200, null=True, blank=True)
    va_maybank = models.CharField(max_length=200, null=True, blank=True)
    va_alfamart = models.CharField(max_length=200, null=True, blank=True)
    va_indomaret = models.CharField(max_length=200, null=True, blank=True)
    va_mandiri = models.CharField(max_length=200, null=True, blank=True)
    tipe_produk = models.CharField(max_length=200, null=True, blank=True)
    last_pay_date = models.CharField(max_length=200, null=True, blank=True)
    last_pay_amount = models.CharField(max_length=200, null=True, blank=True)
    partner_name = models.CharField(max_length=200, null=True, blank=True)
    last_agent = models.CharField(max_length=200, null=True, blank=True)
    last_call_status = models.CharField(max_length=200, null=True, blank=True)
    refinancing_status = models.CharField(max_length=200, null=True, blank=True)
    activation_amount = models.CharField(max_length=200, null=True, blank=True)
    program_expiry_date = models.CharField(max_length=200, null=True, blank=True)
    address_kodepos = models.CharField(max_length=200, null=True, blank=True)
    phonenumber = models.CharField(max_length=200, null=True, blank=True)
    mobile_phone_2 = models.CharField(max_length=200, null=True, blank=True)
    no_telp_pasangan = models.CharField(max_length=200, null=True, blank=True)
    telp_perusahaan = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        db_table = '"ana"."collection_b6"'
        managed = False


class ICareAccountListExperimentPOC(TimeStampedModel):
    id = models.AutoField(db_column='icare_account_list_experiment_poc_id', primary_key=True)
    generated_date = models.DateField(db_column='date_key', null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    experiment_group = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."icare_account_list_experiment_poc"'
        managed = False


class B2AdditionalAgentExperiment(TimeStampedModel):
    id = models.AutoField(db_column='b2_additional_agent_experiment_id', primary_key=True)
    date_key = models.DateField(db_column='date_key', null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    dpd = models.IntegerField(null=True, blank=True)
    bucket = models.TextField(null=True, blank=True)
    due_amount = models.IntegerField(null=True, blank=True)
    account_payment_id = models.IntegerField(null=True, blank=True)
    installment_number = models.IntegerField(null=True, blank=True)
    pgood = models.FloatField(null=True, blank=True)
    rownum = models.IntegerField(null=True, blank=True)
    experiment_group = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."b2_additional_agent_experiment"'
        managed = False


class EarlyHiSeasonTicketCount(TimeStampedModel):
    id = models.AutoField(db_column='early_hi_season_ticket_count_id', primary_key=True)
    campaign_period = models.TextField(null=True, blank=True)
    campaign_start_date = models.DateField(null=True, blank=True)
    campaign_end_date = models.DateField(null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    total_ticket_count = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."early_hi_season_ticket_count"'
        managed = False


class QrisFunnelLastLog(TimeStampedModel):
    id = models.AutoField(db_column='qris_funnel_last_log_id', primary_key=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    visit_lending_page_date = models.DateField(null=True, blank=True)
    open_master_agreement_date = models.DateField(null=True, blank=True)
    read_master_agreement_date = models.DateField(null=True, blank=True)
    sign_master_agreement_date = models.DateField(null=True, blank=True)
    input_pin_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."qris_funnel_last_log"'
        managed = False
