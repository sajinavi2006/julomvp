import json
import logging
import time
from builtins import object, str

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

# from rest_framework import status
from juloserver.api_token.models import ExpiryToken as Token
from juloserver.apiv1.dropdown.loan_purposes import LoanPurposeDropDown

# from rest_framework.test import APITestCase


USERNAME_PREFIX = 'test_user'
PASSWORD = 'testPa$$word'
EMAIL = 'test@email.com'

logger = logging.getLogger(__name__)


@pytest.mark.django_db
class TestTokenModel(object):

    # GIVEN accessed from the API

    def test_token_created_when_user_created(self):

        # WHEN a django user is created
        username = '_'.join([USERNAME_PREFIX, str(time.time())])
        user = User.objects.create(username=username, password=PASSWORD, email=EMAIL)
        logging.info("user=%s created" % username)

        # THEN token is automatically created
        tokens = Token.objects.filter(user=user)
        assert len(tokens) > 0
        assert tokens[0].user.username == username


# @pytest.mark.django_db
# class AccountTests(APITestCase):
#     def test_create_account(self):
#         """
#         Ensure we can create a new account object.
#         """
#         url = 'api/v1/api-token/'
#         data = {'name': 'DabApps'}
#         response = self.client.post(url, data, format='json')
#         self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestOrderbyInDropdownLoanPurpose(TestCase):
    def setUp(self):
        pass

    def testorderby(self):
        expected_data = [
            "Modal usaha",
            "Kebutuhan sehari-hari",
            "Membayar hutang lainnya",
            "Biaya pendidikan",
            "Biaya kesehatan",
            "Belanja online",
            "Membeli elektronik",
            "Membeli kendaraan",
            "Biaya liburan / umroh",
            "Renovasi Rumah",
            "Transfer ke Keluarga/Teman",
        ]
        dropdown = LoanPurposeDropDown(10)
        return_value = dropdown._get_data(10)
        self.assertIsNotNone(return_value)
        self.assertEqual(expected_data, json.loads(return_value)['data'])
