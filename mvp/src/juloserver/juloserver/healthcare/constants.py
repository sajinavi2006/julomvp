from collections import namedtuple
from django.conf import settings


class HealthcareConst(object):
    DOCUMENT_TYPE_INVOICE = 'healthcare_invoice'
    EMAIL_TEMPLATE_CODE = 'healthcare_invoice_template'
    TEMPLATE_PATH = "{}/juloserver/healthcare/templates/".format(settings.BASE_DIR)


REDIS_HEALTHCARE_PLATFORM_AUTO_COMPLETE_HASH_TABLE_NAME = 'healthcare_platform_ac'


class UploadStatusMessage(object):
    Status = namedtuple('Status', ['level', 'message'])

    SUCCESS = Status("SUCCESS", "Your xls file has been imported")
    WARNING = Status("WARNING", "Upload success but no data imported")
    FILE_NOT_FOUND = Status("ERROR", "File not found, choose file first")


class FeatureNameConst(object):
    HEALTHCARE_FAQ = 'healthcare_faq'
    ALLOW_ADD_NEW_HEALTHCARE_PLATFORM = 'allow_add_new_healthcare_platform'
    SEARCH_HEALTHCARE_PLATFORM_IN_REDIS = 'search_healthcare_platform_in_redis'


class SuccessMessage:
    DELETE_SUCCESS = 'Data successfully deleted'
