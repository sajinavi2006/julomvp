import mock
from django.contrib.auth.hashers import make_password
from rest_framework.test import APITestCase
from rest_framework.reverse import reverse
from rest_framework import status
from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
)
from juloserver.julo.tests.factories import (
    PartnerFactory,
    AuthUserFactory,
    FeatureSettingFactory,
)
from ..factories import LenderCurrentFactory, InventorUserWithEmailFactory, InventorUserFactory


class TestLenderAuthentication(APITestCase):
    def setUp(self):
        self.all_feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {
                        "is_active": False,
                        "APPLICATIONS": []
                    }
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "whitelist": {
                        "is_active": False,
                        "APPLICATIONS": []
                    }
                }
            }
        )

    def test_lender_login(self):
        data = {'username': 'test', 'password': 'password@123'}
        url = reverse('lender_login')
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        user = InventorUserFactory(username='test', password=make_password('password@123'))
        PartnerFactory(user=user)
        LenderCurrentFactory(user=user)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data['password'] = 'password'
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch('juloserver.followthemoney.tasks.send_email_set_password')
    def test_forgot_password_view(self, mock_send_email_set_password):
        url = reverse('lender_forgot_password')
        data = {'email': 'test@gmail.com'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        user = InventorUserWithEmailFactory()
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        LenderCurrentFactory(user=user)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_change_password_view(self):
        url = reverse('lender_change_password')
        data = {'new_password': 'password@123'}
        user = AuthUserFactory(username='test1')
        self.client.force_authenticate(user)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_channeling_login(self):
        data = {'username': 'test', 'password': 'password@123'}
        url = reverse('lender_login')
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        user = InventorUserFactory(username='test', password=make_password('password@123'))
        PartnerFactory(user=user, name='bss_channeling')
        LenderCurrentFactory(user=user, lender_name='bss_channeling')
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data['password'] = 'password'
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
