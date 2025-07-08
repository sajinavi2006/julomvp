from builtins import object

from django.conf import settings


class TongdunCodes(object):
    TONGDUN_TASK_SUBMIT_SUCCESS_CODE = 137
    TONGDUN_TASK_SUCCESS_CODE = 0


class JuloRedirectUrls(object):
    ANDROID_REDIRECT_URL = "https://www.julo.co.id/"
    BPJS_WEB_REDIRECT_URL = settings.BPJS_WEB_REDIRECT_URL


class BrickCodes(object):
    BRICK_GET_INFO_SUCCESS_CODE = 200


class BrickAPITypes(object):
    BRICK_API_TYPE_INFORMATION = "GET"


class BrickSetupClient(object):
    BRICK_MAX_RETRY_PROCESS = 3

    BRICK_WIDGET_BASE_URL = settings.BRICK_WIDGET_BASE_URL
    JULO_PATH_CALLBACK = '/api/bpjs/v2/applications/{}/brick-callback'


class BpjsDirectConstants(object):
    SERVICE_NAME = 'bpjs_direct'
    BPJS_DIRECT_RANGE_SALARY = [
        [0, 2500000, "0-2.5JT"],
        [2500000, 3500000, "2.5-3.5JT"],
        [3500000, 4500000, "3.5-4.5JT"],
        [4500000, 5500000, "4.5-5.5JT"],
        [5500000, 6500000, "5.5-6.5JT"],
        [6500000, 7500000, "6.5-7.5JT"],
        [7500000, 8500000, "7.5-8.5JT"],
        [8500000, 12500000, "8.5-12.5JT"],
        [12500000, 20500000, "12.5-20.5JT"],
        [20500000, None, ">20.5JT"],
    ]

    BPJS_BYPASS_TRESHOLD = 0.65
    BPJS_NO_FDC_EL_LOWER_TRESHOLD = 0.65
    BPJS_NO_FDC_EL_UPPER_TRESHOLD = 0.85
    BPJS_EL_TRESHOLD = 0.8
