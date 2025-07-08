from unittest.mock import Mock, patch

import pytest
from django.test import TestCase
from requests.models import Response

from juloserver.bpjs import get_bpjs_direct_client
from juloserver.julo.models import Application
from juloserver.bpjs.models import BpjsAPILog
from juloserver.bpjs.services.bpjs_direct import retrieve_and_store_bpjs_direct
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
)

requests = Mock()


class TestBPJSDirectService(TestCase):
    def setUp(self):

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

    @patch("juloserver.bpjs.clients.BPJSDirectClient.retrieve_bpjs_direct_data")
    def test_success_bpjs_direct(self, mock_post):
        """
        Success scenario save all data with correct application id
        """

        response = Response()
        response.status_code = 200
        response.url = "/test/bpjs-direct/retrieve-data"
        response._content = (
            b"{'ret': '0', 'msg': 'Sukses',"
            b"'score': {'namaLengkap': 'TIDAK SESUAI',"
            b"'nomorIdentitas': 'SESUAI', 'tglLahir': 'TIDAK SESUAI',"
            b"'jenisKelamin': 'SESUAI', 'handphone': '', 'email': '',"
            b"'namaPerusahaan': 'TIDAK SESUAI', 'paket': 'SESUAI',"
            b"'upahRange': 'TIDAK SESUAI', 'blthUpah': 'TIDAK SESUAI'},"
            b"'CHECK_ID': '22110800574994'}"
        )

        mock_post.return_value = response
        result = retrieve_and_store_bpjs_direct(self.application.pk)

        assert mock_post.called

    @patch("juloserver.bpjs.clients.BPJSDirectClient.retrieve_bpjs_direct_data")
    def test_failed_bpjs_direct(self, mock_post):
        response = Response()
        response.status_code = 400
        response.url = "/test/bpjs-direct/retrieve-data"

        mock_post.return_value = response
        result = retrieve_and_store_bpjs_direct(self.application.pk)

        assert mock_post.called
