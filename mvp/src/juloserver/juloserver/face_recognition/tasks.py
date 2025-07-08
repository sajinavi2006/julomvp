import logging

from celery import task
from django.db import transaction
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.julo.models import (
    Application,
    Image,
)

from juloserver.face_recognition.models import (
    AwsRecogResponse,
    FaceCollection,
    FaceImageResult,
    FaceSearchProcess,
    FaceSearchResult,
    FraudFaceSearchResult,
    FraudFaceSearchProcess,
)
from juloserver.face_recognition.constants import (
    FaceMatchingCheckConst,
)
from juloserver.face_recognition.services import (
    do_all_face_matching,
    do_face_matching,
    mark_face_matching_failed,
    store_fraud_face,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='application_high')
@transaction.atomic
def store_aws_response_data(image_id, response, raw_response_type):
    image = Image.objects.get_or_none(pk=image_id)

    if image:
        AwsRecogResponse.objects.create(
            image_id=image, raw_response=response, raw_response_type=raw_response_type
        )


@task(queue='application_high')
@transaction.atomic
def store_matched_faces_data(
    service_response,
    service_latency,
    service_configs,
    face_search_process_id,
    face_collection_id,
    face_image_result_id,
    customer_id,
):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    face_image_result = FaceImageResult.objects.filter(pk=face_image_result_id).last()
    face_collection = FaceCollection.objects.filter(pk=face_collection_id).last()
    face_search_process = FaceSearchProcess.objects.filter(pk=face_search_process_id).last()

    face_search_results = []
    if face_image_result and face_collection and face_search_process:
        for face_matched in service_response['matched_faces']:
            matched_image = Image.objects.get_or_none(pk=face_matched['image_id'])
            if matched_image:
                matched_application = Application.objects.get_or_none(pk=matched_image.image_source)
                if matched_application.customer_id != customer_id:
                    face_search_results.append(
                        FaceSearchResult(
                            searched_face_image_id=face_image_result,
                            matched_face_image_id=matched_image,
                            search_face_confidence=face_matched['confidence'],
                            similarity=face_matched['similarity'],
                            face_collection=face_collection,
                            latency=service_latency,
                            configs=service_configs,
                            face_search_process=face_search_process,
                        )
                    )

    face_search_process.refresh_from_db()

    if not face_search_results:
        face_search_process.update_safely(status='not_found')
        application_tag_tracking_task(
            matched_application.id, None, None, None, 'is_similar_face', -1
        )
    else:
        face_search_process.update_safely(status='found')
        application_tag_tracking_task(
            matched_application.id, None, None, None, 'is_similar_face', 1
        )
        FaceSearchResult.objects.bulk_create(face_search_results)


@task(queue='application_high')
def upload_face_recognition_image(
    image_id, face_collection_id, application_id, customer_id, parameters, thumbnail=True
):
    from juloserver.julo.services import process_image_upload
    from juloserver.face_recognition.services import process_indexed_face

    image = Image.objects.get_or_none(pk=image_id)
    if not image:
        logger.error({"image": image_id, "status": "not_found"})
    process_image_upload(image, thumbnail)
    process_indexed_face(image_id, face_collection_id, application_id, customer_id, parameters)


@task(queue='fraud')
@transaction.atomic
def store_matched_fraud_faces_data(
    service_response,
    service_latency,
    service_configs,
    fraud_face_search_process_id,
    face_collection_id,
    face_image_result_id,
    customer_id,
    application_id,
):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    face_image_result = FaceImageResult.objects.filter(pk=face_image_result_id).last()
    face_collection = FaceCollection.objects.filter(pk=face_collection_id).last()
    fraud_face_search_process = FraudFaceSearchProcess.objects.filter(
        pk=fraud_face_search_process_id
    ).last()

    fraud_face_search_results = []
    if face_image_result and face_collection and fraud_face_search_process:
        for face_matched in service_response['matched_faces']:
            matched_image = Image.objects.get_or_none(pk=face_matched['image_id'])
            if matched_image:
                matched_application = Application.objects.get_or_none(pk=matched_image.image_source)
                if matched_application.customer_id != customer_id:
                    fraud_face_search_results.append(
                        FraudFaceSearchResult(
                            searched_face_image_id=face_image_result,
                            matched_face_image_id=matched_image,
                            search_face_confidence=face_matched['confidence'],
                            similarity=face_matched['similarity'],
                            face_collection=face_collection,
                            latency=service_latency,
                            configs=service_configs,
                            face_search_process=fraud_face_search_process,
                        )
                    )

    fraud_face_search_process.refresh_from_db()

    if not fraud_face_search_results:
        fraud_face_search_process.update_safely(status='not_found')
        application_tag_tracking_task(application_id, None, None, None, 'is_fraud_face_match', -1)
    else:
        fraud_face_search_process.update_safely(status='found')
        application_tag_tracking_task(
            matched_application.id, None, None, None, 'is_fraud_face_match', 1
        )
        FraudFaceSearchResult.objects.bulk_create(fraud_face_search_results)


@task(queue='fraud')
def process_single_row_data(row_number, row, face_collection, aws_settings):
    from juloserver.face_recognition.services import process_fraud_indexed_face

    image = Image.objects.get_or_none(pk=row[2])
    if not image:
        logger.error({'action': 'process_single_row_data', "image": row[2], "status": "not_found"})
        return
    process_fraud_indexed_face(
        image_id=image.id,
        face_collection_id=face_collection.id,
        application_id=row[1],
        customer_id=row[0],
        aws_settings=aws_settings,
    )


@task(queue='face_matching')
def face_matching_task(
    application_id: int,
    times_retried: int = 0,
    process: FaceMatchingCheckConst.Process = None,
) -> None:
    """
    Perform face matching task for the given application ID.

    Args:
        application_id (int): The ID of the application.
        times_retried (int, optional): The number of times the task has been retried. Defaults to 0.
        process (str, optional): To specify which process to be executed/retried

    Returns:
        None

    Retry Mechanism:
    - The task will be retried if it fails and the maximum number of retries has not been reached.
    - Each retry will be scheduled with an increasing countdown time.
    - The countdown time is calculated as 60 seconds multiplied by the number of retries.
    - The maximum number of retries is set to 3.
    """
    if not process:
        liveness_x_ktp_success, liveness_x_selfie_success = do_all_face_matching(application_id)
        if not liveness_x_ktp_success:
            face_matching_task.apply_async(
                args=[
                    application_id,
                    times_retried + 1,
                    FaceMatchingCheckConst.Process.liveness_x_ktp,
                ],
                countdown=60 * (times_retried + 1),
            )
        if not liveness_x_selfie_success:
            face_matching_task.apply_async(
                args=[
                    application_id,
                    times_retried + 1,
                    FaceMatchingCheckConst.Process.liveness_x_selfie,
                ],
                countdown=60 * (times_retried + 1),
            )
    else:
        success = do_face_matching(application_id, process)
        if not success and times_retried < 3:  # TODO: make retry mechanism configurable
            face_matching_task.apply_async(
                args=[application_id, times_retried + 1, process],
                countdown=60 * (times_retried + 1),
            )
        elif not success and times_retried >= 3:
            mark_face_matching_failed(application_id, process, 'exceeded maximum retries')
            logger.exception(
                'do_face_matching_error | app_id={} | err={}'.format(
                    str(application_id), 'exceeded maximum retries'
                )
            )


@task(queue='fraud')
def store_fraud_face_task(
    application_id: int,
    customer_id: int = None,
    change_reason: str = None,
    times_retried: int = 0,
) -> None:
    """
    Save applicant's face to fraud face collection.

    Args:
        application_id (int): The ID of the application.
        customer_id (int, optional): The ID of the customer. Defaults to None.
        change_reason (str, optional): The reason for storing the face. Defaults to None.
        times_retried (int, optional): The number of times the task has been retried. Defaults to 0.

    Returns:
        None

    Retry Mechanism:
    - The task will be retried if it fails and the maximum number of retries has not been reached.
    - Each retry will be scheduled with an increasing countdown time.
    - The countdown time is calculated as 60 seconds multiplied by the number of retries.
    - The maximum number of retries is set to 3.

    TODO:
    - decouple call by application_id and customer_id
    """

    success = store_fraud_face(application_id, customer_id, change_reason)
    if not success and times_retried < 3:
        store_fraud_face_task.apply_async(
            args=[application_id, change_reason, times_retried + 1],
            countdown=60 * (times_retried + 1),
        )
    elif not success and times_retried >= 3:
        logger.exception('asdads')
        raise Exception(
            'store_fraud_face_error | app_id={} | err={}'.format(
                str(application_id), str('exceeded maximum retries')
            )
        )

    return
