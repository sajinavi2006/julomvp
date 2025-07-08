from django.conf import settings
from django.db import models

from juloserver.julocore.customized_psycopg2.models import BigAutoField

from juloserver.julo.models import TimeStampedModel
from juloserver.julo.utils import get_oss_presigned_url
from juloserver.sales_ops.constants import CustomerType


class AIRudderAgentGroupMapping(TimeStampedModel):
    id = BigAutoField(db_column='agent_group_mapping_id', primary_key=True)
    bucket_code = models.CharField(max_length=100)
    customer_type = models.CharField(choices=CustomerType.choices(), max_length=100)
    agent_group_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'airudder_agent_group_mapping'
        managed = False

    def __str__(self):
        return str(self.id)


class AIRudderDialerTaskGroup(TimeStampedModel):
    id = BigAutoField(db_column='dialer_task_group_id', primary_key=True)
    bucket_code = models.CharField(max_length=100)
    customer_type = models.CharField(choices=CustomerType.choices(), max_length=100)
    agent_group_mapping = models.ForeignKey(
        AIRudderAgentGroupMapping, db_column="agent_group_mapping_id",
        on_delete=models.SET_NULL, null=True, blank=True
    )
    total = models.IntegerField()

    class Meta:
        db_table = 'airudder_dialer_task_group'
        managed = False

    def __str__(self):
        return str(self.id)


class AIRudderDialerTaskUpload(TimeStampedModel):
    id = BigAutoField(
        db_column='dialer_task_upload_id', primary_key=True
    )
    dialer_task_group = models.ForeignKey(
        AIRudderDialerTaskGroup, db_column="dialer_task_group_id",
        on_delete=models.CASCADE
    )
    total_uploaded = models.IntegerField()
    total_successful = models.IntegerField(null=True, blank=True)
    total_failed = models.IntegerField(null=True, blank=True)
    batch_number = models.IntegerField()
    upload_file_url = models.TextField(null=True, blank=True)
    result_file_url = models.TextField(null=True, blank=True)
    task_id = models.TextField(null=True, blank=True)

    @property
    def upload_file_oss_url(self):
        upload_file_url = '' or self.upload_file_url
        return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, upload_file_url)

    @property
    def result_file_oss_url(self):
        result_file_url = '' or self.result_file_url
        return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, result_file_url)

    class Meta:
        db_table = 'airudder_dialer_task_upload'
        managed = False

    def __str__(self):
        return str(self.id)


class AIRudderDialerTaskDownload(TimeStampedModel):
    id = BigAutoField(
        db_column='dialer_task_download_id', primary_key=True
    )
    dialer_task_upload = models.ForeignKey(
        AIRudderDialerTaskUpload, db_column="dialer_task_upload_id",
        on_delete=models.CASCADE
    )
    total_downloaded = models.IntegerField()
    download_file_url = models.TextField(null=True, blank=True)
    time_range = models.CharField(max_length=100)
    limit = models.IntegerField()
    offset = models.IntegerField()

    @property
    def download_file_oss_url(self):
        download_file_url = '' or self.download_file_url
        return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, download_file_url)

    class Meta:
        db_table = 'airudder_dialer_task_download'
        managed = False

    def __str__(self):
        return str(self.id)


class AIRudderVendorRecordingDetail(TimeStampedModel):
    id = BigAutoField(
        db_column='vendor_recording_detail_id', primary_key=True
    )
    bucket_code = models.CharField(max_length=100)
    call_to = models.TextField()
    call_start = models.TextField()
    call_end = models.TextField()
    duration = models.IntegerField()
    recording_url = models.TextField(null=True, blank=True)
    call_id = models.TextField()
    agent_id = models.BigIntegerField()
    customer_id = models.BigIntegerField()
    dialer_task_upload = models.ForeignKey(
        AIRudderDialerTaskUpload, db_column='dialer_task_upload_id',
        on_delete=models.CASCADE
    )

    @property
    def recording_file_oss_url(self):
        recording_file_url = '' or self.recording_url
        return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, recording_file_url)

    class Meta:
        db_table = 'airudder_vendor_recording_detail'
        managed = False

    def __str__(self):
        return str(self.id)


class SalesOpsLineupAIRudderData(TimeStampedModel):
    id = BigAutoField(db_column="sales_ops_lineup_airudder_data_id", primary_key=True)
    bucket_code = models.TextField()
    mobile_phone_1 = models.TextField()
    gender = models.TextField()
    fullname = models.TextField()
    available_limit = models.BigIntegerField()
    set_limit = models.BigIntegerField()
    customer_type = models.TextField()
    application_history_x190_cdate = models.DateTimeField(null=True, blank=True)
    latest_loan_fund_transfer_ts = models.DateTimeField(null=True, blank=True)
    is_12m_user = models.TextField(null=True, blank=True)
    is_high_value_user = models.TextField(null=True, blank=True)
    kode_voucher = models.TextField(null=True, blank=True)
    scheme = models.TextField(null=True, blank=True)
    biaya_admin_sebelumnya = models.FloatField(null=True, blank=True)
    biaya_admin_baru = models.FloatField(null=True, blank=True)
    bunga_cicilan_sebelumnya = models.FloatField(null=True, blank=True)
    bunga_cicilan_baru = models.FloatField(null=True, blank=True)
    r_score = models.IntegerField(null=True, blank=True)
    m_score = models.IntegerField(null=True, blank=True)
    latest_active_dates = models.DateField(null=True, blank=True)
    customer_id = models.BigIntegerField()
    application_id = models.BigIntegerField()
    account_id = models.BigIntegerField()
    data_date = models.DateField(null=True, blank=True)
    partition_date = models.DateField(null=True, blank=True)
    customer_segment = models.TextField(null=True, blank=True)
    schema_amount = models.TextField(null=True, blank=True)
    schema_loan_duration = models.IntegerField(null=True, blank=True)
    cicilan_per_bulan_sebelumnya = models.TextField(null=True, blank=True)
    cicilan_per_bulan_baru = models.TextField(null=True, blank=True)
    saving_overall_after_np = models.TextField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."sales_ops_lineup_airudder_data"'
        managed = False
