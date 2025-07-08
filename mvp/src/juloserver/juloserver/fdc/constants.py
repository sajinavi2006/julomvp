from builtins import object
from django.conf import settings


class FDCTaskConst(object):
    RETRY_INTERVAL = 3600 * 3  # 3 hours
    MAX_RETRY_COUNT = 3
    MAX_PERCENTAGE = 0.05


class FDCConstant(object):
    ID_PENYELENGGARA = '810069'
    DATA_LEN = 10
    TIME_OUT_MINS_DEFAULT = 15
    REGEX_QUEUE_CHECK = (
        '^rabbitmq_queue_messages{.*queue="fdc_inquiry".*%s.}' % settings.RABBITMQ_VHOST
    )


class FDCStatus(object):
    FOUND = 'found'
    NOT_FOUND = 'not found'
    PLEASE_USE_REASON_2 = 'please use reason 2'
    NO_IDENTITAS_REPORTED = 'noIdentitas has not been reported'


class FDCInquiryStatus(object):
    SUCCESS = 'success'


class FDCFailureReason(object):
    REASON_FILTER = {1: '1 - Applying loan via Platform', 2: '2 - Monitor Outstanding Borrower'}


class FDCFileSIKConst:
    ROW_LIMIT = 500000
    RETRY_LIMIT = 3
    HOUR_UPLOAD_LIMIT = 3


class FDCLoanStatus:
    FULLY_PAID = 'Fully Paid'
    OUTSTANDING = 'Outstanding'


RUN_FDC_INQUIRY_LABEL = ("Run FDC Inquiry Check", "Run FDC Inquiry Check Key")

RUN_FDC_INQUIRY_PATH = (
    'excel/run_fdc_inquiry/run_fdc_inquiry.csv',
    'excel/run_fdc_inquiry/run_fdc_inquiry.csv',
)

RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS = [
    ("application_xid", "application_xid"),
    ("nik_spouse", "nik_spouse"),
]

RUN_FDC_INQUIRY_HEADERS = ["application_xid", "nik_spouse"]


class FDCReasonConst:
    REASON_APPLYING_LOAN = 1
    REASON_MONITOR_OUTSTANDING_BORROWER = 2


class FDCLoanQualityConst:
    TIDAK_LANCAR = ['Tidak Lancar (30 sd 90 hari)', 'Kurang Lancar', 'Diragukan']
    LANCAR = ['Lancar (<30 hari)', 'Lancar', 'Dalam Perhatian Khusus']
    MACET = ['Macet (>90)', 'Macet']
