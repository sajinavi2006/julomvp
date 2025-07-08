import logging
from celery.task import task
from datetime import datetime
from typing import List

from django.conf import settings
from django.utils import timezone

from juloserver.julo.models import FeatureSetting
from juloserver.julo.exceptions import JuloException

from juloserver.monitors.notifications import send_slack_bot_message

from juloserver.sales_ops_pds.constants import (
    SalesOpsPDSDataStoreType,
    SalesOpsPDSAlert,
    FeatureNameConst,
)
from juloserver.sales_ops_pds.models import (
    AIRudderDialerTaskUpload,
    AIRudderDialerTaskDownload
)

logger = logging.getLogger(__name__)


@task(queue='loan_high')
def init_create_sales_ops_pds_task():
    from juloserver.sales_ops_pds.services.general_services import check_create_task_fs
    from juloserver.sales_ops_pds.services.upload_data_services import SalesOpsPDSUploadTask

    if check_create_task_fs():
        SalesOpsPDSUploadTask().init_create_sales_ops_pds_task()


@task(queue='loan_normal')
def create_sales_ops_pds_task_subtask(
    dialer_task_group_id: int, sub_account_ids: List[int], batch_number: int
):
    from juloserver.sales_ops_pds.services.upload_data_services import SalesOpsPDSUploadTask

    SalesOpsPDSUploadTask().create_sales_ops_pds_task_per_group_per_batch(
        dialer_task_group_id=dialer_task_group_id,
        sub_account_ids=sub_account_ids,
        batch_number=batch_number
    )


@task(queue='loan_normal', bind=True)
def send_create_task_request_to_airudder(self, dialer_task_upload_id: int):
    from juloserver.sales_ops_pds.services.upload_data_services import (
        SalesOpsPDSUploadTask,
        AIRudderPDSUploadService,
        AIRudderPDSUploadManager
    )

    dialer_task_upload = AIRudderDialerTaskUpload.objects.filter(
        pk=dialer_task_upload_id
    ).last()
    if not dialer_task_upload:
        raise JuloException(
            "Not found dialer task upload ID {id}".format(id=dialer_task_upload_id)
        )

    dialer_task_group = dialer_task_upload.dialer_task_group
    uploaded_data = SalesOpsPDSUploadTask().load_data_from_oss_file(
        dialer_task_upload=dialer_task_upload
    )
    strategy_config = SalesOpsPDSUploadTask().get_airudder_task_strategy_config(
        group_mapping=dialer_task_group.agent_group_mapping
    )

    airudder_upload_service = AIRudderPDSUploadService(
        bucket_code=dialer_task_group.bucket_code,
        customer_type=dialer_task_group.customer_type,
        customer_list=uploaded_data,
        strategy_config=strategy_config,
        batch_number=dialer_task_upload.batch_number
    )
    airudder_upload_manager = AIRudderPDSUploadManager(
        airudder_upload_service=airudder_upload_service
    )
    try:
        task_id, error_uploaded_data = airudder_upload_manager.create_task()
    except AIRudderPDSUploadManager.NeedRetryException as error:
        self.retry(countdown=300, max_retries=3, exc=error)
        raise error

    total_uploaded = len(uploaded_data)
    total_failed = len(error_uploaded_data)
    total_successful = total_uploaded - total_failed

    SalesOpsPDSUploadTask().record_uploaded_sales_ops_pds_data(
        dialer_task_upload=dialer_task_upload,
        total_successful=total_successful,
        total_failed=total_failed,
        task_id=task_id,
        error_uploaded_data=error_uploaded_data
    )


@task(queue="loan_high")
def init_download_sales_ops_pds_call_result_task():
    from juloserver.sales_ops_pds.services.general_services import check_download_call_result_fs
    from juloserver.sales_ops_pds.services.download_data_services import SalesOpsPDSDownloadTask

    if check_download_call_result_fs():
        SalesOpsPDSDownloadTask().init_download_sales_ops_pds_call_result()


@task(queue='loan_normal', bind=True)
def send_get_total_request_to_airudder(
    self, dialer_task_upload_id: int, start_time: datetime, end_time: datetime
):
    from juloserver.sales_ops_pds.services.download_data_services import (
        SalesOpsPDSDownloadTask,
        AIRudderPDSDownloadService,
        AIRudderPDSDownloadManager
    )

    dialer_task_upload = AIRudderDialerTaskUpload.objects.filter(
        pk=dialer_task_upload_id
    ).last()
    if not dialer_task_upload:
        raise JuloException(
            "Not found dialer task upload ID {id}".format(id=dialer_task_upload_id)
        )

    airudder_download_service = AIRudderPDSDownloadService(
        task_id=dialer_task_upload.task_id,
        start_time=start_time,
        end_time=end_time
    )
    airudder_download_manager = AIRudderPDSDownloadManager(
        airudder_download_service=airudder_download_service
    )
    try:
        total = airudder_download_manager.get_total()
    except AIRudderPDSDownloadManager.NeedRetryException as error:
        self.retry(countdown=300, max_retries=3, exc=error)
        raise error

    if total:
        SalesOpsPDSDownloadTask().init_download_call_result_per_task(
            dialer_task_upload=dialer_task_upload,
            total_downloaded=total,
            start_time=start_time,
            end_time=end_time
        )


@task(queue='loan_normal', bind=True)
def send_get_call_list_request_to_airudder(
    self, dialer_task_download_id: int, start_time: datetime, end_time: datetime
):
    from juloserver.sales_ops_pds.services.download_data_services import (
        SalesOpsPDSDownloadTask,
        AIRudderPDSDownloadService,
        AIRudderPDSDownloadManager
    )
    from juloserver.sales_ops_pds.services.store_data_services import (
        StoreSalesOpsPDSDownloadData,
        StoreSalesOpsPDSRecordingFile,
    )
    from juloserver.sales_ops_pds.services.general_services import check_download_recording_file_fs

    dialer_task_download = AIRudderDialerTaskDownload.objects.filter(
        pk=dialer_task_download_id
    ).last()
    if not dialer_task_download:
        raise JuloException(
            "Not found dialer task download ID {id}".format(id=dialer_task_download_id)
        )

    airudder_download_service = AIRudderPDSDownloadService(
        task_id=dialer_task_download.dialer_task_upload.task_id,
        start_time=start_time,
        end_time=end_time
    )
    airudder_download_manager = AIRudderPDSDownloadManager(
        airudder_download_service=airudder_download_service
    )
    try:
        call_list = airudder_download_manager.get_call_list(
            offset=dialer_task_download.offset,
            limit=dialer_task_download.limit
        )
    except AIRudderPDSDownloadManager.NeedRetryException as error:
        self.retry(countdown=300, max_retries=3, exc=error)
        raise error

    if call_list:
        SalesOpsPDSDownloadTask().capture_call_result_data_to_sales_ops(
            call_list=call_list
        )
        StoreSalesOpsPDSDownloadData(
            data=call_list,
            store_type=SalesOpsPDSDataStoreType.DOWNLOAD_FROM_AIRUDDER,
            dialer_task_download_id=dialer_task_download_id
        ).store_downloaded_data()

        if check_download_recording_file_fs():
            StoreSalesOpsPDSRecordingFile().retrieve_call_result_recordings(
                call_list=call_list,
                dialer_task_upload_id=dialer_task_download.dialer_task_upload.pk,
            )

    logger.info({
        'action': 'send_get_call_list_request_to_airudder',
        'message': 'Done capturing AIRudder call results to Sales Ops',
        'data': {
            'dialer_task_download_id': dialer_task_download_id,
            'total_record': len(call_list)
        }
    })


@task(queue='loan_normal')
def send_slack_notification():
    sales_ops_alert_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SALES_OPS_PDS_ALERT, is_active=True
    ).last()
    if not sales_ops_alert_fs:
        return

    parameters = sales_ops_alert_fs.parameters
    channel = parameters.get('channel', SalesOpsPDSAlert.CHANNEL)

    today = timezone.localtime(timezone.now()).date()
    dialer_task_uploads = (
        AIRudderDialerTaskUpload.objects
        .filter(cdate__date=today)
        .order_by(
            "dialer_task_group__bucket_code",
            "dialer_task_group__customer_type",
            "batch_number"
        )
        .select_related("dialer_task_group")
    )

    message = parameters.get('message', SalesOpsPDSAlert.MESSAGE).format(
        date=today.isoformat()
    )
    message += '\n On *{env}* environment:'.format(env=settings.ENVIRONMENT)
    for dialer_task_upload in dialer_task_uploads:
        message += (
            '\n  - Bucket: *{bucket_code}* - Type: *{customer_type}*'
            ' - Batch number: *{batch_number}* - Uploaded: *{total_uploaded}*'
            ' - Successful: *{total_successful}* - Failed: *{total_failed}*'
        ).format(
            bucket_code=dialer_task_upload.dialer_task_group.bucket_code,
            customer_type=dialer_task_upload.dialer_task_group.customer_type,
            batch_number=dialer_task_upload.batch_number,
            total_uploaded=dialer_task_upload.total_uploaded,
            total_successful=dialer_task_upload.total_successful,
            total_failed=dialer_task_upload.total_failed
        )

    send_slack_bot_message(channel, message)


@task(queue='loan_normal', bind=True)
def process_recording_file_task(self, call_result: dict, dialer_task_upload_id: int):
    from juloserver.sales_ops_pds.services.store_data_services import (
        StoreSalesOpsPDSRecordingFile,
        SalesOpsPDSRecordingFileManager,
    )

    sales_ops_pds_recording_file = StoreSalesOpsPDSRecordingFile()
    sales_ops_pds_recording_file_manager = SalesOpsPDSRecordingFileManager(
        sales_ops_pds_recording_file=sales_ops_pds_recording_file
    )

    try:
        local_filepath = sales_ops_pds_recording_file_manager.fetch_recording_file(
            reclink=call_result['reclink']
        )
    except SalesOpsPDSRecordingFileManager.NeedRetryException as error:
        self.retry(countdown=300, max_retries=3, exc=error)
        raise error

    if local_filepath:
        sales_ops_pds_recording_file.store_and_upload_recording_file(
            call_result=call_result,
            local_filepath=local_filepath,
            dialer_task_upload_id=dialer_task_upload_id
        )
