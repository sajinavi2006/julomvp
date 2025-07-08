from datetime import timedelta

from django.utils import timezone
from juloserver.fdc.constants import FDCConstant, RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS


def create_fdc_filename(new_version_number):
    today = timezone.localtime(timezone.now()).date()
    today_minus_1 = today - timedelta(days=1)
    reporting_date = today_minus_1.strftime("%Y%m%d")

    id_penyelenggara = FDCConstant.ID_PENYELENGGARA
    return id_penyelenggara + reporting_date + 'V5-SIK' + "%02d" % (new_version_number,)


def run_fdc_inquiry_format_data(raw_data):
    formated_data = {}

    for raw_field, formated_field in RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS:
        formated_data[formated_field] = raw_data.get(raw_field)

    return formated_data
