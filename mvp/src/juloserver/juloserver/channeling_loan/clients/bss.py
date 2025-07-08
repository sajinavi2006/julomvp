from builtins import object
from builtins import str
import hashlib
import logging
import requests  # noqa

from juloserver.julo.models import FeatureSetting

from juloserver.channeling_loan.constants import (
    BSSChannelingConst,
    ChannelingStatusConst,
)
from juloserver.channeling_loan.models import ChannelingLoanAPILog

from juloserver.julo.clients import get_julo_sentry_client


logger = logging.getLogger(__name__)

BSS_TIME_OUT_SEC = 60


class BSSChannelingClient(object):
    def __init__(self, base_url):
        self.base_url = base_url
        self.user = BSSChannelingConst.USER
        sign_value = (self.user * 3).encode('utf-8')
        hashcode = hashlib.md5(sign_value).hexdigest()
        self.hashcode = hashcode

    def send_request(self, request_path, request_type, loan, data=None, params=None):
        """
        Send API request to BSS Channeling Client
        :param request_path: Channeling's route url
        :param request_type: Request type [get, post]
        :param loan: Loan that wanna sent to BSS
        :param data: Dictionary contains data using for requests body usually using by [POST]
        :param params: Dictionary contains data using for requests params usually using by [GET]
        :return: object response.json
        """
        sentry_client = get_julo_sentry_client()

        api_type = "[{}] {}".format(request_type, request_path)

        if data:
            if 'user' in data:
                data['user'] = self.user
            if 'hashcode' in data:
                data['hashcode'] = self.hashcode

        request_params = dict(
            url=self.base_url + request_path,
            data=data,
            params=params,
            timeout=BSS_TIME_OUT_SEC,
        )

        try:
            if request_type == "post":
                response = requests.post(**request_params)
            else:
                response = requests.get(**request_params)
            response.raise_for_status()
            return_response = response.json()
            error_message = None
        except Exception as error:
            sentry_client.captureException()
            error_message = str(error)
            return_response = {"error": error}
            response = error

        mock_response = None
        bss_mock_response = FeatureSetting.objects.get_or_none(
            is_active=True, feature_name="bss_channeling_mock_response"
        )
        str_app_id = str(loan.get_application.id)
        mock_response_key = '%s%s' % (request_path, data.get("trxtype", ""))
        if bss_mock_response and str_app_id in bss_mock_response.parameters:
            parameters = bss_mock_response.parameters.get(str_app_id, None)
            if parameters and parameters.get(mock_response_key):
                mock_response = self.mock_response(
                    parameters.get(mock_response_key), mock_response_key
                )
                return_response = mock_response
        self.channeling_response_logger(
            "BSS", api_type, response, error_message, loan, mock_response)

        return return_response

    def channeling_response_logger(
            self, channeling_type, request_type, response, error_message, loan, mock_response):
        status = ChannelingStatusConst.FAILED
        if error_message:
            status_code = 404
            request = None
        else:
            if response.status_code in [200, 201]:
                status = ChannelingStatusConst.SUCCESS
            status_code = response.status_code
            request = response.request.__dict__
            response = response.json()

        application = loan.get_application
        logger.info({
            'action': 'channeling_response_logger - {}'.format(request_type),
            'response_status': status_code,
            'loan_xid': loan.loan_xid,
            'application_xid': application.application_xid,
            'error': error_message,
            'request': request,
            'response': mock_response if mock_response else response,
            'status': status,
        })

        ChannelingLoanAPILog.objects.create(
            channeling_type=channeling_type,
            application=application,
            loan=loan,
            request_type=request_type,
            http_status_code=status_code,
            request=request,
            response=mock_response if mock_response else response,
            error_message=error_message,
        )

    def mock_response(self, response_code, response_key):
        # this function only for testing purpose
        # handle by bss_channeling_mock_response feature_setting
        if response_key in ("disburse", ""):
            if response_code == BSSChannelingConst.SUCCESS_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "00",
                            "responseDescription": "SUCCESS",
                            "refno": "002_0464_0464002032",
                            "namanasabah": "Iswanto",
                            "nodokumen": "PM20010303244613",
                            "nodisburse": "DS1910000002",
                            "principaltotal": "2000000",
                            "description": "tes disburse rekening",
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }

            if response_code == BSSChannelingConst.DATA_FAILED_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "10",
                            "responseDescription": (
                                "Total principal tidak sesuai dengan data di "
                                "schedule, nilai interest : 0 tidak sesuai pada "
                                "duedate 11/12/2019, Jumlah tenor tidak sesuai "
                                "dengan data dischedule, nilai orientationofuseid "
                                "tidak sesuai"
                            )
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }

            if response_code == BSSChannelingConst.SCHEDULE_FAILED_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "20",
                            "responseDescription": (
                                "Total tenor tidak sesuai dengan data di schedule, "
                                "umur pinjaman melebihi batas maksimal, "
                                "ltv melebihi batas maksimal, tenor kurang dari "
                                "batas minimal, Total principal tidak sesuai "
                                "dengan data di schedule, ratio kemempuan bayar "
                                "melebihi batas maksimal"
                            )
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }

            if response_code == BSSChannelingConst.BANK_FAILED_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "30",
                            "responseDescription": "dhn: Not Ok, slik: Not Ok, dukcapil: Not Ok"
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }

            if response_code == BSSChannelingConst.ONPROGRESS_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "40",
                            "responseDescription": "Transaction in Process"
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }

            if response_code == BSSChannelingConst.UNDEFINED_STATUS_CODE:
                return {
                    "error": "undefined condition",
                    "status": BSSChannelingConst.NOT_OK_STATUS
                }
        else:
            if response_code == BSSChannelingConst.TRANSFER_OUT_SUCCESS_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "00",
                            "responseDescription": "Sukses"
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }

            if response_code == BSSChannelingConst.TRANSFER_OUT_PENDING_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "01",
                            "responseDescription": "Pending"
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }

            if response_code == BSSChannelingConst.TRANSFER_OUT_FAILED_STATUS_CODE:
                return {
                    "data": {
                        "result": {
                            "responseCode": "02",
                            "responseDescription": "Gagal"
                        }
                    },
                    "status": BSSChannelingConst.OK_STATUS
                }
