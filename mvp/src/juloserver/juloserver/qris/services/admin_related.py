import logging

from django.conf import settings

from juloserver.julo.constants import CloudStorage
from juloserver.julo.models import RedisWhiteListUploadHistory
from juloserver.julo.utils import upload_file_as_bytes_to_oss
from juloserver.julocore.constants import RedisWhiteList
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.qris.tasks import retrieve_and_set_qris_redis_whitelist_csv


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def upload_qris_customer_whitelist_csv(file_bytes: bytes, user_id: int = None):
    """
    - Upload set value to Redis
    - Upload file to cloud storage
    """
    remote_basedir = RedisWhiteList.BASE_WHITELIST_CSV_DIR
    remote_filename = RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST
    remote_filepath = f"{remote_basedir}/{remote_filename}.csv"

    history = RedisWhiteListUploadHistory.objects.create(
        user_id=user_id,
        whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
        remote_file_path=remote_filepath,
        cloud_storage=CloudStorage.OSS,
        remote_bucket=settings.OSS_MEDIA_BUCKET,
    )

    try:
        upload_file_as_bytes_to_oss(
            bucket_name=settings.OSS_MEDIA_BUCKET,
            file_bytes=file_bytes,
            remote_filepath=remote_filepath,
        )
    except Exception as e:
        sentry_client.captureException()
        history.status = RedisWhiteList.Status.UPLOAD_FAILED
        history.save()
        return

    history.status = RedisWhiteList.Status.UPLOAD_SUCCESS
    history.save(update_fields=['status'])

    # async set redis value
    retrieve_and_set_qris_redis_whitelist_csv.delay()
