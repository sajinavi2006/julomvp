import logging

import juloocr
from celery import task
from django.db import transaction

from .services import (
    create_or_update_ocr_process,
    store_object_detector,
    store_object_detector_request,
    store_text_recognition,
    store_text_recognition_request,
    trigger_new_ocr_process,
)
from juloserver.julo.tasks import upload_image

logger = logging.getLogger(__name__)


@task(queue='application_high')
@transaction.atomic
def store_ocr_data(
    ocr_image_result_id,
    object_detector_response,
    object_detector_result,
    text_recognition_response,
    text_recognition_result,
    status_msg,
    ocr_config,
    application_id,
    image_id,
):

    ocr_process_data = {
        'detection_latency_ms': object_detector_result.get('logic_latency'),
        'transcription_latency_ms': text_recognition_result.get('logic_latency'),
        'juloocr_version': juloocr.__version__,
        'detection_version': object_detector_response[2],
        'transcription_version': text_recognition_response[2],
        'detection_logic_version': object_detector_result.get('logic_version'),
        'transcription_logic_version': text_recognition_result.get('logic_version'),
        'ocr_config': ocr_config,
        'status': status_msg,
    }

    ocr_process_id = create_or_update_ocr_process(ocr_process_data)
    # store automl request data
    if object_detector_response[1] != 0:
        object_detector_request_id = store_object_detector_request(
            ocr_image_result_id, object_detector_response, ocr_process_id, application_id, image_id
        )
        # store object detector result
        if object_detector_result:
            object_detector_ids = store_object_detector(
                object_detector_request_id, object_detector_result
            )
            # store gvocr request data
            if text_recognition_response[1] != 0:
                text_recognition_request_id = store_text_recognition_request(
                    ocr_image_result_id,
                    text_recognition_response,
                    ocr_process_id,
                    application_id,
                    image_id,
                )
                # store text recognition result
                if text_recognition_result:
                    store_text_recognition(
                        text_recognition_request_id, object_detector_ids, text_recognition_result
                    )


@task(queue='application_high')
def upload_ktp_image_and_trigger_ocr(
    image_id, can_process, thumbnail=True, deleted_if_last_image=False, ocr_params=None
):
    logger.info(
        "start_upload_ktp_image_and_trigger_ocr|"
        "image={}, can_process={}".format(image_id, can_process)
    )
    upload_image(image_id, thumbnail, deleted_if_last_image)
    if can_process:
        trigger_new_ocr_process(image_id, ocr_params)
