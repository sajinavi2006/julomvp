import json
import logging
import os

from celery import task
from django.conf import settings

from juloserver.julo.services2 import get_redis_client
from juloserver.minisquad.clients.google_cloud_storage import GoogleCloudService
from juloserver.minisquad.constants import (
    DialerTaskType,
    DialerTaskStatus,
    RedisKey,
)
from juloserver.minisquad.models import DialerTask
from juloserver.minisquad.services2.intelix import create_history_dialer_task_event
from juloserver.minisquad.services2.koleko import (
    get_total_batch_grab_data_for_koleko,
    get_grab_data_for_koleko,
    construct_data_koleko_format,
    generate_csv_file_for_koleko,
    process_next_batch_koleko_data_to_csv_file,
)

logger = logging.getLogger(__name__)


@task(queue='collection_dialer_high')
def trigger_upload_grab_data_collection():
    """
        process description :
        - count total data and batch
        - send to worker for processing format data for koleko will generate 3 files
            (CPCRD_NEW_FILE, CPCRD_EXT_FILE, AND CPCRD_PAYMENT_FILE)
        - create csv files and stored in /media/
        - save file path to redis for each file
        - upload all files to S3 bucket depend on environment
        - delete generated csv file from local and delete file path from redis
    """
    dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_GRAB_KOLEKO)
    create_history_dialer_task_event(dict(dialer_task=dialer_task))
    total_data_count, total_batch = get_total_batch_grab_data_for_koleko()
    if not total_batch:
        error_message = "total batch is null or 0"
        logger.error({
            "action": "trigger_upload_grab_data_collection",
            "error": error_message,
        })
        create_history_dialer_task_event(
            param=dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE),
            error_message=error_message
        )
        return

    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.PROCESSED,
             data_count=total_data_count)
    )
    generate_csv_batched_grab_data_collection.delay(
        dialer_task_id=dialer_task.id, total_page=total_batch)


@task(queue='collection_dialer_high')
def generate_csv_batched_grab_data_collection(
        dialer_task_id, total_page, current_page=0, last_payment_id=None):
    grab_data = get_grab_data_for_koleko(last_payment_id)
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    if not grab_data:
        if not current_page:
            error_message = "grab_data batch is null or 0"
            logger.error({
                "action": "generate_csv_batch_collection_grab_data",
                "batch": current_page,
                "error": error_message,
            })
            create_history_dialer_task_event(
                param=dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE),
                error_message=error_message
            )
            return
        # sent data even thought not complete yet
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PARTIAL_PROCESSED,
                 ),
            error_message="cannot found next iter of last payment id {}".format(last_payment_id)
        )
        upload_grab_collection_csv_file_to_koleko.delay(dialer_task_id)
        return

    total_data = len(grab_data)
    cpcrd_new_data, cpcrd_ext_data, cpcrd_payment_data = construct_data_koleko_format(grab_data)
    if current_page == 0:
        generate_csv_file_for_koleko(cpcrd_new_data, cpcrd_ext_data, cpcrd_payment_data)
    else:
        process_next_batch_koleko_data_to_csv_file(
            cpcrd_new_data, cpcrd_ext_data, cpcrd_payment_data)
    processed_page = current_page + 1
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status='{}_{}/{}'.format(DialerTaskStatus.PROCESSED, processed_page, total_page),
             data_count=total_data
             )
    )
    if processed_page < total_page:
        # generate next batch to csv
        generate_csv_batched_grab_data_collection.delay(
            dialer_task_id, total_page, current_page=processed_page,
            last_payment_id=grab_data[total_data-1].id
        )
    else:
        # upload
        upload_grab_collection_csv_file_to_koleko.delay(dialer_task_id)


@task(queue='collection_dialer_high')
def upload_grab_collection_csv_file_to_koleko(dialer_task_id):
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.UPLOADING,
             )
    )
    redis_client = get_redis_client()
    files_path = (
        redis_client.get(RedisKey.KOLEKO_CPCRD_NEW_FILE_PATH),
        redis_client.get(RedisKey.KOLEKO_CPCRD_EXT_FILE_PATH),
        redis_client.get(RedisKey.KOLEKO_CPCRD_PAYMENT_FILE_PATH),
    )
    if None in files_path:
        error_message = "file not completed"
        logger.error({
            "action": "upload_grab_collection_csv_file_to_koleko",
            "error": error_message,
            "files": files_path
        })
        create_history_dialer_task_event(
            param=dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE),
            error_message=error_message
        )
        return

    # upload
    google_cloud_client = GoogleCloudService()
    for file_path in files_path:
        file_name = file_path.split('/')[-1]
        destination_file_name = "{}{}".format(settings.KOLEKO_DIRECTORY_PATH, file_name)
        google_cloud_client.upload_file(
            settings.KOLEKO_BUCKET, file_path, destination_file_name
        )
        # delete after uploaded
        if os.path.isfile(file_path):
            os.remove(file_path)

    # remove file path from redis
    redis_client.delete_key(RedisKey.KOLEKO_CPCRD_NEW_FILE_PATH)
    redis_client.delete_key(RedisKey.KOLEKO_CPCRD_EXT_FILE_PATH)
    redis_client.delete_key(RedisKey.KOLEKO_CPCRD_PAYMENT_FILE_PATH)

    create_history_dialer_task_event(
        param=dict(dialer_task=dialer_task, status=DialerTaskStatus.SUCCESS)
    )
