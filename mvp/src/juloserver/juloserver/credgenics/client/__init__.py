from django.conf import settings
from juloserver.credgenics.client.http_client import HTTPClient
from juloserver.credgenics.client.aws_client import S3Client


def get_credgenics_http_client() -> HTTPClient:
    return HTTPClient(
        settings.CREDGENICS_BASE_URL,
        settings.CREDGENICS_AUTH_TOKEN,
        settings.CREDGENICS_COMPANY_ID,
    )


def get_credgenics_s3_client() -> S3Client:
    return S3Client(
        settings.CREDGENICS_AWS_ACCESS_KEY_ID,
        settings.CREDGENICS_AWS_SECRET_ACCESS_KEY,
        settings.CREDGENICS_AWS_REGION_NAME,
        settings.CREDGENICS_AWS_BUCKET_NAME,
        settings.CREDGENICS_AWS_BUCKET_PATH,
    )
