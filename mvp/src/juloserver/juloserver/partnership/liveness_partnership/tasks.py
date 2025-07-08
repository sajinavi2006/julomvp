import logging

from celery import task
from django.conf import settings

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import upload_file_as_bytes_to_oss

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='partnership_global')
def upload_liveness_image_async(
    liveness_image_byte: bytes,
    url_file: str,
) -> None:
    try:
        upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, liveness_image_byte, url_file)
        return
    except Exception as error:
        logger.warning(
            {
                'action': 'upload_liveness_image_async',
                'message': "failed upload_liveness_image_async to oss",
                'file_path': liveness_image_byte,
                'url_file': url_file,
                'errors': str(error),
            }
        )
        return
