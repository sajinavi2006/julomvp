import json
from mock import patch, Mock

from django.test import TestCase, override_settings

from juloserver.tokopedia.models import TokoScoreResult
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    WorkflowFactory,
    ProductLineFactory,
)
from juloserver.julo.constants import (
    WorkflowConst,
    ProductLineCodes,
    ApplicationStatusCodes,
)
from juloserver.tokopedia.services.clients import get_request_tokoscore
from juloserver.tokopedia.constants import TokoScoreConst
from juloserver.tokopedia.services.common_service import (
    reformat_phone_number,
    get_score,
)


def mock_response_toko_score(*args, **kwargs):
    """
    Mock with define with different endpoints
    """

    class MockResponseTokoScore:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'oauth/token?grant_type=client_credentials' in args[0]:
        return MockResponseTokoScore(
            {
                'access_token': 'xxxx',
                'expires_in': 3600,
                'token_type': 'Bearer',
            },
            200,
        )
    elif 'api/v1/partner/score' in args[0]:
        return MockResponseTokoScore(
            {
                "code": "200000",
                "latency": "242.42 ms",
                "data": {
                    "message_id": "20231127.TEST_SCORE_06",
                    "score_id": 160,
                    "score": "AvIcbZLCiSc+S2X6eb0/AJbxNwS9hwN+CV1KJ4ZoSKmhypopX6L0AaIxgkH8Tg8WZ"
                    "9IxWa6jz6rfuX8LhR3XG17qrXZYtDgCMnBSs7LQsC5+BYoy78K5oOd9zjQTTUEHDV4/S4i4k/M6E81NBYIds"
                    "Tp+5P0USgYoWNImO5WxJtTn6bSPMBERN+ptUCo5ecm3rq/Bp1IBf7OpJZnYPl69DIxLwCSdxZBCnQEsQqhgrFbeG"
                    "bPnNmSutEqEcvXq86FlWcoEz/bSrUmvvfeMogkIUJVXcboyWZ1k8N2uniipT2exIxK6MLW+tBWTXOkrc4RrbkVOcmQ"
                    "MX3F8+wq9SyjTvwQRRSHhvozA/XcOTee4JovKgQcVNZKVOW43ecmQqD1WCkBJoN8MgfV9vvnhBzdzrix+2GNwhzKs"
                    "VTJcV5r06Ve9mynaylBp4hlorK2vakuP/YFELwfgZy3lVETZwMGutJH8MmvUhfJSz6kyliKr55wKKozsa6uJS+plR"
                    "d0SmcV2cHDVlDMrfaLH93dTr7tUaPF+emxOLvuH9EJc8AU6Tc3wFAiHXc9Tzbp/RTTOzPmRWHByWJRN+g3Ii02Oy4"
                    "kKfFzuSHVP1VgdTrebjMDhorU3xRcYWtDuCfYNZ36+GF579Xzbp/QS98J4Cj+TrUQvw1JsgML3fI9wIOsbAO68BJc=",
                    "no_pg_dg": False,
                    "response_timestamp": "2023-11-27T13:46:14.498544457+07:00",
                },
            },
            200,
        )


class TestClientService(TestCase):

    private_key_dummy = """-----BEGIN RSA PRIVATE KEY-----
            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
            -----END RSA PRIVATE KEY-----"""

    public_key_dummy = """-----BEGIN PUBLIC KEY-----
           MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEArAeZdwSnYY0X//BusSDl
           eoXAOcsFebPTOCuVScHs00pbhvrjcL2Dt57yu0m6J0tmlDQkAPrhYzxjal4lkhvr
           nA6QHeoNoqNgsjrOCclRSEHjb8MCk17OPI4RPkBXSZ0cstgpHo+crNI4TqkNu5W5
           Ob74YIIr4pRjRXQfDdQP4SQfk7HW5gyiYrpbl66kbOnFcUgSB5Fj8AQ2/SS48tEk
           48ChGSp/4GGBD8WW7LUPWDm5ncar2eXL7nm8y8EaYQKqDXvs5hg1AFZI6Ru+I6Gw
           CJx2Pg8COAZglGa4ZRD3FqA2onVPKIDFrRpR+Sbh6WApI3DQfpoXSyzV7DCXa9mX
           l7vothPx4X/bPvNf5HDRNUUZnhlkqW9lyhGhHOzUF5wlH4WDK9v2xbNJV8AdgWFG
           0jpimvIe/b46B9b0N/pvPLWnk24saax6vb1cu8v4iZ9FLcVQMWKnkTiUIeI9M0Uz
           NrCpgXjKfO51/hPjnAOblQ2FbHANPXQzg1RpxvkAUzvXga+hlTlNVzd4DJAmI7Zf
           H9tPAs5+NqD90AFCFPUAVPIV2qYpvD7we9A5rg8rRYbhp8uskiT955vQ6ZeSO1SS
           wFbwycJ6gW/PXLc+4LsJY1Gps0HHceP9K02zoDHQUR1cUmYv6XEbh8Y1D7RMznxn
           YBqac1tL9ozU7B2FabkAwH0CAwEAAQ==
           -----END PUBLIC KEY-----"""

    @override_settings(TOKOSCORE_BASE_URL='https://apitesting.test')
    @override_settings(TOKOSCORE_PRIVATE_KEY=private_key_dummy)
    @override_settings(TOKOSCORE_PUBLIC_KEY=public_key_dummy)
    @override_settings(TOKOSCORE_CLIENT_ID='123131asdadas112313')
    @override_settings(TOKOSCORE_CLIENT_SECRET='12313ADADAq113qsq12')
    def setUp(self):

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            id=1,
            customer=self.customer,
            workflow=self.workflow,
            email='testing@julofinance.com',
            mobile_phone_1='083822825220',
        )
        self.application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL)
        self.toko_score_client = get_request_tokoscore()

    @override_settings(TOKOSCORE_BASE_URL='https://apitesting.test')
    @override_settings(TOKOSCORE_PRIVATE_KEY=private_key_dummy)
    @override_settings(TOKOSCORE_PUBLIC_KEY=public_key_dummy)
    @override_settings(TOKOSCORE_CLIENT_ID='123131asdadas112313')
    @override_settings(TOKOSCORE_CLIENT_SECRET='12313ADADAq113qsq12')
    @patch('requests.post', side_effect=mock_response_toko_score)
    def test_scenario_main_function(self, mock_get_token):

        _ = get_score(self.application.id)
        toko_score_data = TokoScoreResult.objects.filter(application_id=self.application.id).last()
        self.assertIsNotNone(toko_score_data)
        self.assertEqual(toko_score_data.request_status, TokoScoreConst.FLAG_REQUEST_IS_SUCCESS)
        self.assertEqual(toko_score_data.score, str(100))
        self.assertEqual(toko_score_data.is_active, True)
        self.assertEqual(toko_score_data.is_match, True)
        self.assertIsNotNone(toko_score_data.response_time)
        self.assertIsNotNone(toko_score_data.request_message_id)
        self.assertIsNotNone(toko_score_data.request_score_id)

    def test_build_personal_information_encrypt_decrypt(self):

        mobile_phone = self.application.mobile_phone_1
        email = self.application.email

        plain_payload = {
            TokoScoreConst.KEY_PAYLOAD_PHONE_NUMBER: reformat_phone_number(mobile_phone),
            TokoScoreConst.KEY_PAYLOAD_EMAIL: email,
        }

        # result encrypted
        encrypted_data = self.toko_score_client.build_personal_information(
            mobile_phone_number=mobile_phone,
            email=email,
        )
        # to decrypt the result
        payload_decrypt = self.toko_score_client.do_decrypt(encrypted_data)
        self.assertIsNotNone(encrypted_data)
        self.assertEqual(plain_payload, json.loads(payload_decrypt))

    def test_build_auth_token(self):

        token_request = self.toko_score_client.build_auth_token()
        self.assertIsNotNone(token_request)

    def test_reformat_phone_number(self):

        data = '08383292839283'
        self.assertEqual(reformat_phone_number(data), '628383292839283')
        data = '628383292839283'
        self.assertEqual(reformat_phone_number(data), '628383292839283')
        data = None
        self.assertIsNone(reformat_phone_number(data))
