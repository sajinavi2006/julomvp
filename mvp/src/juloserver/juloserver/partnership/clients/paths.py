from django.conf import settings


class LinkAjaApiUrls(object):
    # LinkAja URL Paths
    GET_AUTH = "/v1/oauth/create"
    REFRESH_TOKEN = "/v1/oauth/refresh"
    VERIFY_CUSTOMER = "/v1/custbind/verify/sessionid"
    CASH_IN_INQUIRY = "/v1/cashin/inquiry"
    CASH_IN_CONFIRMATION = "/v1/cashin/confirm"
    CHECK_TRANSACTION_STATUS = "/v1/cashin/check"

    @staticmethod
    def build_url(path, http_method, additional_params=""):
        url = settings.LINKAJA_API_BASE_URL + path
        uri_path = path + (additional_params if http_method == "GET" else "")

        return url, uri_path
