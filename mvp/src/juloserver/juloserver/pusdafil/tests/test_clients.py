import json
from builtins import str

import mock
import pytest
from django.test.testcases import TestCase

from juloserver.core.utils import ObjectMock
from juloserver.pusdafil.clients import get_pusdafil_client
from juloserver.pusdafil.constants import PUSDAFIL_ORGANIZER_ID


@pytest.mark.django_db
class TestObjectPusdafilClient(TestCase):
    def setUp(self):
        self.data = dict(
            id_negara_domisili=0,
            id_pengguna='514133',
            id_lender='1',
            sumber_dana='Lain-lain',
            id_kewarganegaraan=None,
            id_penyelenggara=PUSDAFIL_ORGANIZER_ID,
        )

        self.mocked_response = ObjectMock(
            status_code=200,
            content=json.dumps(
                dict(
                    request_status=200,
                    data=[
                        dict(request_status=200, error=False),
                        dict(request_status=200, error=False),
                    ],
                )
            ),
        )

    @mock.patch("juloserver.pusdafil.clients.requests.post")
    def test_success_send(self, mocked_pusdafil_client):
        pusdafil_client = get_pusdafil_client()

        mocked_pusdafil_client.return_value = self.mocked_response

        status_code, response_body = pusdafil_client.send("reg_lender", self.data)

        self.assertEqual(status_code, 200)
        self.assertEqual(response_body["request_status"], 200)
        self.assertEqual(response_body["data"][1]["error"], False)

    @mock.patch("juloserver.pusdafil.clients.requests.post")
    def test_exception_send(self, mocked_pusdafil_client):
        pusdafil_client = get_pusdafil_client()

        error_message = "Going to exception flow"

        mocked_pusdafil_client.return_value = self.mocked_response
        mocked_pusdafil_client.side_effect = Exception(error_message)

        with self.assertRaises(Exception) as context:
            pusdafil_client.send("reg_lender", self.data)

        self.assertTrue(error_message in str(context.exception))
