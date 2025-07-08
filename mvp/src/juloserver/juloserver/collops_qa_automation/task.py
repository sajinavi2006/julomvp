import logging
import os

from celery.task import task
from django.conf import settings
from django.utils import timezone

from juloserver.collops_qa_automation.clients import get_julo_qa_airudder
from juloserver.collops_qa_automation.constant import (
    QAAirudderResponse, QAAirudderAPIPhase)
from juloserver.collops_qa_automation.models import RecordingReport
from juloserver.collops_qa_automation.services import (
    construct_task_for_airudder, record_airudder_upload_history)
from juloserver.collops_qa_automation.utils import (
    file_to_base64, delete_local_file_after_upload, extract_bucket_name_dialer)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.models import VendorRecordingDetail
from juloserver.monitors.notifications import send_message_normal_format
from juloserver.minisquad.constants import AiRudder

logger = logging.getLogger(__name__)


@task(queue="collection_dialer_normal")
def upload_recording_file_to_airudder_task(vendor_recording_detail_id, recording_file_path):
    logger.info({
        'action': 'upload_recording_file_to_airudder',
        'message': 'task begin',
        'vendor_recording_detail_id': vendor_recording_detail_id,
    })
    sending_recording_configuration = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.SENDING_RECORDING_CONFIGURATION
    ).last()
    if not sending_recording_configuration:
        logger.info({
            'action': 'upload_recording_file_to_airudder',
            'message': 'not send to airudder because feature is off',
            'vendor_recording_detail_id': vendor_recording_detail_id,
        })
        delete_local_file_after_upload(recording_file_path)
        return

    recording_detail = VendorRecordingDetail.objects.get(pk=vendor_recording_detail_id)
    if not recording_detail:
        logger.info({
            'action': 'upload_recording_file_to_airudder',
            'message': 'not send to airudder because not found recording detail',
            'vendor_recording_detail_id': vendor_recording_detail_id,
        })
        delete_local_file_after_upload(recording_file_path)
        return

    send_criteria = sending_recording_configuration.parameters
    criteria_recording_resources = send_criteria['recording_resources']
    criteria_buckets = send_criteria['buckets']
    criteria_call_result_ids = [int(id) for id in send_criteria['call_result_ids']]
    criteria_duration_type = send_criteria['recording_duration_type']
    criteria_duration = send_criteria['recording_duration']

    if criteria_recording_resources and recording_detail.source not in criteria_recording_resources:
        logger.info({
            'action': 'upload_recording_file_to_airudder',
            'message': 'not send to airudder because resource not in configuration',
            'vendor_recording_detail_id': vendor_recording_detail_id,
            'resource_criteria': criteria_recording_resources
        })
        delete_local_file_after_upload(recording_file_path)
        return

    bucket_name = recording_detail.bucket
    is_eligible_to_send = False
    for bucket in criteria_buckets:
        is_eligible_to_send = bucket in bucket_name
        if is_eligible_to_send:
            break
    if criteria_buckets and not is_eligible_to_send:
        logger.info({
            'action': 'upload_recording_file_to_airudder',
            'message': 'not send to airudder because bucket not in configuration',
            'vendor_recording_detail_id': vendor_recording_detail_id,
            'bucket': bucket_name
        })
        delete_local_file_after_upload(recording_file_path)
        return

    if criteria_call_result_ids and recording_detail.call_status.id not in criteria_call_result_ids:
        logger.info({
            'action': 'upload_recording_file_to_airudder',
            'message': 'not send to airudder because call result not in configuration',
            'vendor_recording_detail_id': vendor_recording_detail_id,
            'call_result_id': recording_detail.call_status.id
        })
        delete_local_file_after_upload(recording_file_path)
        return

    if criteria_duration_type:
        if criteria_duration_type == 'between':
            if not (criteria_duration[0] <= recording_detail.duration <= criteria_duration[1]):
                logger.info({
                    'action': 'upload_recording_file_to_airudder',
                    'message': 'not send to airudder because duration not meet requirement',
                    'vendor_recording_detail_id': vendor_recording_detail_id,
                })
                delete_local_file_after_upload(recording_file_path)
                return
        elif criteria_duration_type == 'lte':
            if not (recording_detail.duration <= criteria_duration[0]):
                logger.info({
                    'action': 'upload_recording_file_to_airudder',
                    'message': 'not send to airudder because duration not meet requirement',
                    'vendor_recording_detail_id': vendor_recording_detail_id,
                })
                delete_local_file_after_upload(recording_file_path)
                return
        elif criteria_duration_type == 'gte':
            if not (recording_detail.duration >= criteria_duration[0]):
                logger.info({
                    'action': 'upload_recording_file_to_airudder',
                    'message': 'not send to airudder because duration not meet requirement',
                    'vendor_recording_detail_id': vendor_recording_detail_id,
                })
                delete_local_file_after_upload(recording_file_path)
                return

    # create Task
    airudder_upload_id = record_airudder_upload_history(
        recording_detail.id, QAAirudderAPIPhase.INITIATED
    )
    qa_airudder_client = get_julo_qa_airudder()
    record_airudder_upload_history(
        recording_detail.id, QAAirudderAPIPhase.OBTAIN_TOKEN,
        airudder_upload_id=airudder_upload_id,
        airudder_response_code=200, airudder_response_status=QAAirudderResponse.OK
    )
    today = timezone.localtime(timezone.now())
    task_name = 'QA_TASK' + recording_detail.unique_call_id[-6:] + today.strftime("%d%m%H%M%S%f")
    logger.info({
        'action': 'upload_recording_file_to_airudder',
        'message': 'starting create task',
        'vendor_recording_detail_id': vendor_recording_detail_id,
        'task_name': task_name,
    })
    data_to_send_recording_details = [
        {
            'RecordingID': recording_detail.id,
            'RecordingName': recording_detail.oss_recording_file_name,
            'Recordingfile': file_to_base64(recording_file_path)
        }
    ]
    task_id = construct_task_for_airudder(
        qa_airudder_client,
        task_name,
        data_to_send_recording_details, airudder_upload_id
    )
    if not task_id:
        logger.error({
            'action': 'upload_recording_file_to_airudder',
            'message': 'cant upload file to airudder',
            'vendor_recording_detail_id': vendor_recording_detail_id,
        })
        delete_local_file_after_upload(recording_file_path)
        return
    start_task_response = qa_airudder_client.start_task(
        task_id=task_id)
    record_airudder_upload_history(
        recording_detail.id, QAAirudderAPIPhase.START_TASK,
        airudder_upload_id=airudder_upload_id,
        task_id=task_id, airudder_response_status=start_task_response['status'],
        airudder_response_code=start_task_response['code']
    )
    if start_task_response['status'] != QAAirudderResponse.OK:
        retry_times = 0
        while retry_times < 3:
            # recreate task and reupload to airudder
            task_id = construct_task_for_airudder(
                qa_airudder_client,
                task_name,
                data_to_send_recording_details,
                airudder_upload_id
            )
            start_task_response = qa_airudder_client.start_task(
                task_id=task_id)
            record_airudder_upload_history(
                recording_detail.id, QAAirudderAPIPhase.START_TASK,
                airudder_upload_id=airudder_upload_id,
                task_id=task_id, airudder_response_status=start_task_response['status'],
                airudder_response_code=start_task_response['code']
            )
            if start_task_response['status'] == QAAirudderResponse.OK:
                break

            retry_times += 1
    # delete local juloserver file after upload to oss and airudder
    logger.info({
        'action': 'upload_recording_file_to_airudder',
        'message': 'task finish',
        'vendor_recording_detail_id': vendor_recording_detail_id,
        'task_name': task_name,
    })
    delete_local_file_after_upload(recording_file_path)


@task(queue='collection_dialer_low')
def slack_alert_negative_words(recording_report_ids):
    recording_reports = RecordingReport.objects.filter(
        id__in=recording_report_ids
    )
    if not recording_reports:
        return

    slack_negative_words_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.SLACK_NOTIFICATION_NEGATIVE_WORDS_THRESHOLD
    ).last()
    if not slack_negative_words_setting:
        logger.info({
            'action': 'slack_alert_negative_words',
            'message': 'not send to slack because feature is off',
        })
        return

    negative_words_threshold = slack_negative_words_setting.parameters['negative_words_threshold']
    slack_channel = slack_negative_words_setting.parameters['channel']
    for recording_report in recording_reports:
        negative_words = recording_report.r_channel_negative_score_amount
        if not negative_words or negative_words < negative_words_threshold:
            continue

        recording_detail_id = recording_report.airudder_recording_upload.vendor_recording_detail.id
        slack_messages = "Terdapat {} kata kasar dalam kalimat " \
                         "pembicaraan pada recording id {}. Silahkan lakukan pengecekan" \
                         " lebih lanjut".format(negative_words, recording_detail_id)

        if settings.ENVIRONMENT != 'prod':
            header = "Testing Purpose from {} \n".format(settings.ENVIRONMENT)
            slack_messages = header + slack_messages

        send_message_normal_format(slack_messages, channel=slack_channel)
