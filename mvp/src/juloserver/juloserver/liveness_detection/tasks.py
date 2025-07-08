import base64
import logging

from celery import task
from django.conf import settings

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Image
from juloserver.julo.utils import get_file_from_oss
from juloserver.liveness_detection.constants import (
    LivenessCheckStatus,
    LivenessErrorCode,
)
from juloserver.liveness_detection.models import PassiveLivenessDetection

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


@task(queue='application_high')
def check_passive_liveness_async(
    image_id: int, application_id: int, liveness_detection_id: int, configs: dict
):
    from juloserver.liveness_detection.services import detect_face

    image = Image.objects.get(pk=image_id)
    remote_filepath = image.image_url
    if not remote_filepath:
        logger.error(
            'check_passive_liveness_async_remote_file_path_is_not_found|'
            'image_id={}, application_id={}'.format(image_id, application_id)
        )
    liveness_detection = PassiveLivenessDetection.objects.get(pk=liveness_detection_id)
    try:
        image_file = get_file_from_oss(settings.OSS_MEDIA_BUCKET, image.url)
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
    except Exception:
        sentry_client.captureException()
        liveness_detection.update_safely(
            status=LivenessCheckStatus.ERROR, error_code=LivenessErrorCode.REMOTE_FILE_NOT_FOUND
        )
        return

    try:
        result, data = detect_face(liveness_detection, base64_image, configs, application_id)
    except Exception as error:
        sentry_client.captureException()
        logger.warning('check_passive_liveness_async_unkown_error|error={}'.format(str(error)))
