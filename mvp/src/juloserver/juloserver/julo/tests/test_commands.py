from __future__ import absolute_import

import base64
from io import StringIO

import pytest
import datetime
import mock
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import (
    algorithms,
    Cipher,
    modes,
)
from mock import patch

from django.test.testcases import TestCase
from django.test import Client
from django.contrib.auth.models import User
from urllib.parse import urlencode
from .factories import (ApplicationFactory,
                       DocumentFactory,
                       StatusLookupFactory,
                       ProductLineFactory,
                       LoanFactory,
                       HighScoreFullBypassFactory)
from juloserver.julo.models import Document, StatusLookup, ProductLine, HighScoreFullBypass
from juloserver.julo.management.commands import retroload_sphp_julo,retroload_hsfb_configuration
from juloserver.julo.constants import ApplicationStatusCodes, ProductLineCodes
from juloserver.julo.management.commands import (
    call_pusdafil_api_for_ojk_license,
    call_pusdafil_api_for_ojk_live_data,
)


class TestRetroloadSphpJulo(TestCase):
    def setUp(self):
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = ProductLineCodes.MTL1
        self.product_line.save()
        self.status_lookup = StatusLookupFactory()
        self.status_lookup.status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        self.status_lookup.save()
        self.application = ApplicationFactory()
        self.application.product_line = self.product_line
        self.application.application_status = self.status_lookup
        self.application.address_kodepos = ''
        self.application.save()
        self.document = DocumentFactory()
        self.document.document_source = self.application.id
        self.document.document_type = 'sphp_julo'
        self.document.save()
        self.loan = LoanFactory(application=self.application)

    def test_retroload_sphp_julo_application_not_found(self):
        self.application.address_kodepos = '432'
        self.application.save()
        retroload_sphp_julo.Command().handle()
        self.assertEqual(1, Document.objects.all().count())

    def test_retroload_sphp_julo_document_not_found(self):
        self.document.document_type = 'lender_sphp'
        self.document.save()
        retroload_sphp_julo.Command().handle()
        self.assertEqual(1, Document.objects.all().count())

    def test_retroload_sphp_julo_template(self):
        retroload_sphp_julo.Command().handle()
        self.assertEqual(int, type(Document.objects.all().count()))


class TestHighScoreFullBypass(TestCase):
    def setUp(self):
        hsfb = HighScoreFullBypassFactory(
            cm_version='31',
            threshold=0.92,
            is_premium_area=True,
            is_salaried=True,
            customer_category='webapp',
        )
        self.username = 'djasen'
        self.password = 'tjendry123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = hsfb.id

    def test_retroload_high_score_full_bypass(self):
        opts = {'old_version': '31', 'new_version': '322'}
        retroload_hsfb_configuration.Command().handle(**opts)
        self.assertEqual(2, HighScoreFullBypass.objects.all().count())

    def test_retroload_high_score_full_bypass_old_version_not_found(self):
        HighScoreFullBypass.objects.all().delete()
        opts = {'old_version': '31', 'new_version': '322'}
        retroload_hsfb_configuration.Command().handle(**opts)
        self.assertEqual(0, HighScoreFullBypass.objects.all().count())

    def test_retroload_high_score_full_bypass_not_pass_parameter(self):
        retroload_hsfb_configuration.Command().handle()
        self.assertEqual(1, HighScoreFullBypass.objects.all().count())

    def test_update_special_feature_setting_case_1(self):
        data = urlencode({
                  "job_type": [
                    "Pegawai swasta",
                    "Pegawai negeri"
                  ],
                  "province": [
                    "DKI Jakarta"
                  ],
                  "cm_version": "31",
                  "is_salaried": True,
                  "job_industry": [
                    "Admin / Finance / HR"
                  ],
                  "bypass_dv_x121": True,
                  "is_premium_area": True,
                  "job_description": [
                    "HR",
                    "Admin / Finance / HR:All"
                  ],
                  "customer_category": "webapp"
                })
        response = self.client.post(
            "/xgdfat82892ddn/julo/highscorefullbypass/%s/change/" % self.special_event_config,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200


class TestCallPusdafilApiForOjkLicense(TestCase):
    def test_encrypt(self):
        expected_data = '123456789'
        key = b'4bd393e7a457f9023d9ba95fffb5a2e1'
        iv = b'ijzh84t1w9xa56s9'

        result = call_pusdafil_api_for_ojk_license.encrypt(expected_data)

        result_io = base64.b64decode(result)
        res_encrypt, res_iv = result_io.split(b'::')
        res_encrypt = base64.b64decode(res_encrypt)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), default_backend())
        decryptor = cipher.decryptor()
        res_decrypt = decryptor.update(res_encrypt)
        res_decrypt = res_decrypt.decode('UTF-8').strip('\x07')  # remove the padding

        self.assertEqual(expected_data, res_decrypt)
        self.assertEqual(iv, res_iv)


class TestCallPusdafilApiForOjkLiveData(TestCase):
    def test_encrypt(self):
        expected_data = '123456789'
        key = b'WmZq3t6w9z$C&F)J@NcRfUjXn2r5u7x!'
        iv = b'ijzh84t1w9xa56s9'

        result = call_pusdafil_api_for_ojk_live_data.encrypt(expected_data)

        result_io = base64.b64decode(result)
        res_encrypt, res_iv = result_io.split(b'::')
        res_encrypt = base64.b64decode(res_encrypt)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), default_backend())
        decryptor = cipher.decryptor()
        res_decrypt = decryptor.update(res_encrypt)
        res_decrypt = res_decrypt.decode('UTF-8').strip('\x07')  # remove the padding

        self.assertEqual(expected_data, res_decrypt)
        self.assertEqual(iv, res_iv)
