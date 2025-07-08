import csv
import urllib.request
from django.conf import settings
from juloserver.julo.utils import get_oss_presigned_url


def read_csv_file_by_csv_reader(upload_url):
    download_url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, upload_url)
    f = urllib.request.urlopen(download_url)
    f = f.read().decode('utf-8').splitlines()
    csv_reader = csv.reader(f)
    return csv_reader
