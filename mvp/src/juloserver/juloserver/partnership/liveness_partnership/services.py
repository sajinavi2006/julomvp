import logging
import os
import ulid
import base64

from typing import Tuple, Dict, Union

from django.conf import settings
from django.core.files import File
from django.db import transaction

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import upload_file_as_bytes_to_oss
from juloserver.partnership.models import (
    LivenessConfiguration,
    LivenessResult,
    LivenessResultMetadata,
    LivenessImage,
)
from juloserver.partnership.liveness_partnership.clients.dot_digital_identity import (
    PartnershipDotDigitalIdentityClient,
)
from juloserver.partnership.liveness_partnership.constants import (
    LivenessType,
    LivenessImageStatus,
    ImageLivenessType,
    LivenessResultStatus,
    LivenessHTTPGeneralErrorMessage,
)
from juloserver.partnership.liveness_partnership.tasks import upload_liveness_image_async
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def upload_liveness_image(
    liveness_image: File, liveness_type: str, liveness_result: LivenessResult
) -> Tuple[Union[Dict, str], bool]:
    liveness_result_id = liveness_result.id
    reference_id = liveness_result.reference_id
    is_upload_image_async = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.LIVENESS_ENABLE_IMAGE_ASYNC, is_active=True
    ).exists()
    try:
        _, file_extension = os.path.splitext(liveness_image.name)
        filename = "liveness-{}-{}{}".format(liveness_type, reference_id, file_extension)
        url_file = "partnership_liveness_{}/application_{}/{}".format(
            liveness_result.reference_id, liveness_result.id, filename
        )
        with transaction.atomic(using='partnership_onboarding_db'):
            file_data = LivenessImage.objects.create(
                image_source=liveness_result_id,
                image_type=liveness_type,
                image_status=LivenessImageStatus.ACTIVE,
                url=url_file,
            )
            liveness_result.image_ids.update({liveness_type: file_data.id})
            liveness_result.save(update_fields=['image_ids'])

        # Rewind file pointer, required before reading the file.
        liveness_image.file.seek(0)
        liveness_image_byte = liveness_image.file.read()
        base64_image = base64.b64encode(liveness_image_byte).decode("utf-8")

        if is_upload_image_async:
            # asynchronous upload image to oss
            upload_liveness_image_async.delay(
                liveness_image_byte=liveness_image_byte,
                url_file=file_data.url,
            )
            return base64_image, True

        # synchronous upload image to oss
        upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, liveness_image_byte, url_file)
        return base64_image, True

    except Exception:
        sentry_client.captureException()
        message = 'File tidak dapat diproses, silahkan coba beberapa saat lagi'
        return message, False


def process_smile_liveness(
    liveness_configuration: LivenessConfiguration,
    neutral_image: File,
    smile_image: File,
) -> Tuple[Union[Dict, str], bool]:
    liveness_configuration_id = liveness_configuration.id
    client_id = liveness_configuration.client_id
    platform = liveness_configuration.platform
    partner_id = liveness_configuration.partner_id
    # Create customer data for API liveness
    try:
        api_client = PartnershipDotDigitalIdentityClient()
        result_create_customer_innovatrics, _ = api_client.create_customer_innovatrics()
        api_client.customer_id = result_create_customer_innovatrics.get('id')
    except Exception:
        sentry_client.captureException()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False
    # Create data liveness_result and liveness_result_metadata
    liveness_result = LivenessResult.objects.create(
        liveness_configuration_id=liveness_configuration_id,
        client_id=client_id,
        platform=platform,
        detection_types=LivenessType.SMILE,
        reference_id=ulid.new().uuid,
        image_ids={},
    )
    liveness_result_metadata = LivenessResultMetadata.objects.create(
        liveness_result_id=liveness_result.id,
        config_applied={
            'liveness_configuration': {
                'liveness_configuration_id': liveness_configuration_id,
                'detection_types': liveness_configuration.detection_types,
                'provider': liveness_configuration.provider,
            }
        },
        response_data={},
    )
    # Upload Image and Mapping Image to table liveness_result
    # upload neutral_image to oss
    result_upload_neutral_image, status_upload_neutral_image = upload_liveness_image(
        neutral_image,
        ImageLivenessType.NEUTRAL,
        liveness_result,
    )

    if not status_upload_neutral_image:
        logger.warning(
            {
                'action': 'failed_process_smile_liveness',
                'message': "failed upload_neutral_image to oss",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'errors': result_upload_neutral_image,
            }
        )
        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])

        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # upload smile_image to oss
    result_upload_smile_image, status_upload_smile_image = upload_liveness_image(
        smile_image,
        ImageLivenessType.SMILE,
        liveness_result,
    )
    if not status_upload_smile_image:
        logger.warning(
            {
                'action': 'failed_process_smile_liveness',
                'message': "failed upload_smile_image to oss",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'errors': result_upload_neutral_image,
            }
        )
        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])

        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # create customer liveness innovatric
    try:
        result_create_customer_liveness, _ = api_client.create_customer_liveness()
        logger.info(
            {
                'action': 'process_smile_liveness',
                'message': "success create customer liveness",
                'partner_id': partner_id,
                'client_id': str(client_id),
            }
        )
    except Exception:
        sentry_client.captureException()

        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])

        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # submit neutral image
    try:
        result_submit_neutral_image, elapsed_upload_neutral_image = api_client.submit_neutral_image(
            image=result_upload_neutral_image
        )
        logger.info(
            {
                'action': 'process_smile_liveness',
                'message': "success submit_neutral_image",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'elapsed': "{} Millisecond".format(elapsed_upload_neutral_image),
            }
        )
    except Exception:
        sentry_client.captureException()

        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])

        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # submit smile image
    try:
        result_submit_smile_image, elapsed_upload_smile_image = api_client.submit_smile_image(
            image=result_upload_smile_image
        )
        logger.info(
            {
                'action': 'process_smile_liveness',
                'message': "success submit_smile_image",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'elapsed': "{} Millisecond".format(elapsed_upload_smile_image),
            }
        )
    except Exception:
        sentry_client.captureException()

        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])
        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # evaluate result
    try:
        evaluate_result, elapsed_upload_smile_image = api_client.evaluate_smile()
        logger.info(
            {
                'action': 'process_smile_liveness',
                'message': "success evaluate_smile liveness",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'elapsed': "{} Millisecond".format(elapsed_upload_smile_image),
            }
        )

        if evaluate_result.get('score'):
            liveness_result.status = LivenessResultStatus.SUCCESS
            liveness_result.score = evaluate_result.get('score')
            liveness_result.save(update_fields=['status', 'score'])
        else:
            # this handle case failed get score because no face detected
            # in image we set score 0 and set liveness result is failed
            liveness_result.status = LivenessResultStatus.FAILED
            liveness_result.score = 0.0
            liveness_result.save(update_fields=['status', 'score'])

        liveness_result_metadata.response_data.update(
            {
                'result_create_customer_innovatrics': result_create_customer_innovatrics,
                'result_create_customer_liveness': result_create_customer_liveness,
                'result_submit_neutral_image': result_submit_neutral_image,
                'result_submit_smile_image': result_submit_smile_image,
                'evaluate_smile': evaluate_result,
            }
        )
        liveness_result_metadata.save(update_fields=['response_data'])
    except Exception:
        sentry_client.captureException()

        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])
        # delete customers innovatric
        api_client.delete_customer_innovatrics()

        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    api_client.delete_customer_innovatrics()
    return liveness_result, True


def process_passive_liveness(
    liveness_configuration: LivenessConfiguration,
    neutral_image: File,
) -> Tuple[Union[Dict, str], bool]:
    liveness_configuration_id = liveness_configuration.id
    client_id = liveness_configuration.client_id
    platform = liveness_configuration.platform
    partner_id = liveness_configuration.partner_id
    # Create customer data for API liveness
    try:
        api_client = PartnershipDotDigitalIdentityClient()
        result_create_customer_innovatrics, _ = api_client.create_customer_innovatrics()
        api_client.customer_id = result_create_customer_innovatrics.get('id')
    except Exception:
        sentry_client.captureException()

        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # Create data liveness_result and liveness_result_metadata
    liveness_result = LivenessResult.objects.create(
        liveness_configuration_id=liveness_configuration_id,
        client_id=client_id,
        platform=platform,
        detection_types=LivenessType.PASSIVE,
        reference_id=ulid.new().uuid,
        image_ids={},
    )
    liveness_result_metadata = LivenessResultMetadata.objects.create(
        liveness_result_id=liveness_result.id,
        config_applied={
            'liveness_configuration': {
                'liveness_configuration_id': liveness_configuration_id,
                'detection_types': liveness_configuration.detection_types,
                'provider': liveness_configuration.provider,
            }
        },
        response_data={},
    )
    # Upload Image and Mapping Image to table liveness_result
    # upload neutral_image to oss
    result_upload_neutral_image, status_upload_neutral_image = upload_liveness_image(
        neutral_image,
        ImageLivenessType.NEUTRAL,
        liveness_result,
    )

    if not status_upload_neutral_image:
        logger.warning(
            {
                'action': 'failed_process_passive_liveness',
                'message': "failed upload_neutral_image to oss",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'errors': result_upload_neutral_image,
            }
        )
        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])
        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # create customer liveness innovatric
    try:
        result_create_customer_liveness, _ = api_client.create_customer_liveness()
        logger.info(
            {
                'action': 'process_passive_liveness',
                'message': "success create customer liveness",
                'partner_id': partner_id,
                'client_id': str(client_id),
            }
        )
    except Exception:
        sentry_client.captureException()

        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])
        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # submit passive image. for passive liveness we using "neutral" image
    try:
        (
            result_submit_passive_image,
            elapsed_upload_passive_image,
        ) = api_client.submit_passive_image(image=result_upload_neutral_image)
        logger.info(
            {
                'action': 'process_passive_liveness',
                'message': "success upload_neutral_image",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'elapsed': "{} Millisecond".format(elapsed_upload_passive_image),
            }
        )
    except Exception:
        sentry_client.captureException()

        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])
        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # evaluate result passive liveness
    try:
        evaluate_result, elapsed_upload_smile_image = api_client.evaluate_passive()
        logger.info(
            {
                'action': 'process_passive_liveness',
                'message': "success evaluate_passive livenes",
                'partner_id': partner_id,
                'client_id': str(client_id),
                'elapsed': "{} Millisecond".format(elapsed_upload_smile_image),
            }
        )

        if evaluate_result.get('score'):
            liveness_result.status = LivenessResultStatus.SUCCESS
            liveness_result.score = evaluate_result.get('score')
            liveness_result.save(update_fields=['status', 'score'])
        else:
            # this handle case failed get score because no face detected
            # in image we set score 0 and set liveness result is failed
            liveness_result.status = LivenessResultStatus.FAILED
            liveness_result.score = 0.0
            liveness_result.save(update_fields=['status', 'score'])
        # save response API to metadata
        liveness_result_metadata.response_data.update(
            {
                'result_create_customer_innovatrics': result_create_customer_innovatrics,
                'result_create_customer_liveness': result_create_customer_liveness,
                'result_submit_passive_image': result_submit_passive_image,
                'evaluate_passive': evaluate_result,
            }
        )
        liveness_result_metadata.save(update_fields=['response_data'])
    except Exception:
        sentry_client.captureException()

        liveness_result.status = LivenessResultStatus.FAILED
        liveness_result.save(update_fields=['status'])
        # delete customers innovatric
        api_client.delete_customer_innovatrics()
        return LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR, False

    # delete customers innovatric
    api_client.delete_customer_innovatrics()
    return liveness_result, True
