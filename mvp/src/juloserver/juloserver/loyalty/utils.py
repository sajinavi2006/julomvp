import csv
import math
import urllib.request
from django.conf import settings
from juloserver.julo.models import FeatureSetting

from juloserver.julo.utils import get_oss_presigned_url
from juloserver.loyalty.constants import BULK_SIZE_DEFAULT, FeatureNameConst, \
    DEFAULT_POINT_CONVERT_TO_RUPIAH


def chunker(seq, size=BULK_SIZE_DEFAULT):
    res = []
    for el in seq:
        res.append(el)
        if len(res) == size:
            yield res
            res = []
    if res:
        yield res


def read_csv_file_by_csv_reader(upload_url):
    download_url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, upload_url)
    f = urllib.request.urlopen(download_url)
    f = f.read().decode('utf-8').splitlines()
    csv_reader = csv.reader(f)
    return csv_reader


def convert_size_unit(bytes, to_unit, b_size=1024):
    """
    Convert B to KB, MB, GB, TB
    """
    exponential = {
        "KB": 1,
        "MB": 2,
        "GB": 3,
        "TB": 4
    }
    if to_unit not in exponential:
        raise ValueError("Invalid converted unit")
    return f"{round(bytes / (b_size ** exponential[to_unit]), 1)} {to_unit}"


def get_convert_rate_from_point_to_rupiah():
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.POINT_CONVERT,
        is_active=True
    )
    parameters = fs.parameters if fs else {}
    from_point_to_rupiah = parameters.get("from_point_to_rupiah", DEFAULT_POINT_CONVERT_TO_RUPIAH)
    return from_point_to_rupiah


def convert_point_to_rupiah(point_amount):
    from_point_to_rupiah = get_convert_rate_from_point_to_rupiah()
    return math.floor(point_amount * from_point_to_rupiah)


def convert_rupiah_to_point(rupiah_amount):
    from_point_to_rupiah = get_convert_rate_from_point_to_rupiah()
    return math.ceil(rupiah_amount / from_point_to_rupiah)
