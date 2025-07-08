from django.conf import settings
from juloserver.julo.utils import (
    put_public_file_to_oss,
    get_oss_public_url,
)
import csv
import requests
from io import StringIO


def upload_file_to_oss(banner_bytes, remote_name):
    url = None
    try:
        put_public_file_to_oss(settings.OSS_PUBLIC_ASSETS_BUCKET, banner_bytes, remote_name)
        url = get_oss_public_url(settings.OSS_PUBLIC_ASSETS_BUCKET, remote_name)
    except Exception as e:
        raise Exception(str(e))

    return url


def download_cohort_campaign_csv(url):
    response = requests.get(url)
    if response.status_code != 200:
        return None
    csv_file = StringIO(response.text)
    csv_rows = csv.DictReader(csv_file)
    rows = [r for r in csv_rows]
    return rows
