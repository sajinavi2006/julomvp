import logging
import boto3

from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class S3Client:
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        region_name: str,
        bucket_name: str,
        bucket_path: str = None,
    ):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.region_name = region_name
        self.bucket_name = bucket_name
        self.bucket_path = bucket_path
        self.type = 's3'

    def _new_client(self) -> boto3.client:
        return boto3.client(
            self.type,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region_name,
        )

    def upload(
        self,
        file_data_bytes: bytes,
        file_name: str,
    ) -> bool:
        """
        Upload a file to the S3 bucket.
        """

        try:
            client = self._new_client()

            s3_key: str
            if self.bucket_path:
                s3_key = "{}/{}".format(self.bucket_path, file_name)
            else:
                s3_key = file_name

            response = client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_data_bytes,
            )

            logger.info(
                {
                    'action': 'credgenics_upload',
                    'status': 'success',
                    'bucket': self.bucket_name,
                    'key': s3_key,
                    'response': response,
                }
            )

        except Exception as e:
            logger.error(
                {
                    'action': 'credgenics_upload',
                    'status': 'failure',
                    'error': str(e),
                }
            )
            sentry_client.capture_exception()  # TODO: pager this somehow; critical error
            return False

        return True
