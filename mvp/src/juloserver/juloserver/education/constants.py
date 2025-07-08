from collections import namedtuple
from django.conf import settings


REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME = 'school_ac'


class EducationConst(object):
    DOCUMENT_TYPE = 'education_invoice'
    EMAIL_TEMPLATE_CODE = 'education_invoice_template'
    TEMPLATE_PATH = "{}/juloserver/education/templates/".format(settings.BASE_DIR)


class ErrorMessage(object):
    APPLICATION_STATUS_MUST_BE_190 = 'Application status must be 190'
    APPLICATION_STATUS_AT_LEAST_109 = 'Application status at least 109'
    ACCOUNT_STATUS_MUST_BE_420 = 'Account status must be 420'


class SuccessMessage(object):
    DELETE_SUCCESS = 'Data successfully deleted'


class UploadStatusMessage:
    Status = namedtuple('Status', ['level', 'message'])

    SUCCESS = Status("SUCCESS", "Your xls file has been imported")
    WARNING = Status("WARNING", "Upload success but no data imported")
    FILE_NOT_FOUND = Status("ERROR", "File not found, choose file first")


class FeatureNameConst(object):
    EDUCATION_FAQ = 'education_faq'
    ALLOW_ADD_NEW_SCHOOL = 'allow_add_new_school'
    SEARCH_SCHOOL_IN_REDIS = 'search_school_in_redis'
