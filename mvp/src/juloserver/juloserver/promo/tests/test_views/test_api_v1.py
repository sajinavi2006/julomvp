import json
from datetime import datetime

from django.utils import timezone
from unittest.mock import patch
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    ApplicationFactory,
)
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeMessage,
    PromoCodeTypeConst,
    PromoCMSRedisConstant,
    PromoCMSCategory,
    PromoCodeTimeConst,
)
from juloserver.promo.tests.factories import (
    PromoCodeBenefitFactory,
    PromoCodeCriteriaFactory,
    PromoCodeFactory,
    PromoPageFactory,
    PromoEntryPageFeatureSetting,
)


class TestLoanPromoCodeCheckV1(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.fixed_cash_benefit = PromoCodeBenefitFactory(
            name="You bring me more meth, that's brilliant!",
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value = {
                'amount': 20000,
            },
        )
        self.promo_code = PromoCodeFactory(
            promo_code_benefit=self.fixed_cash_benefit,
            promo_code="You've got one part of that wrong...",
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            promo_code_daily_usage_count=5,
            promo_code_usage_count=5,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=1000000,
        )
        PromoPageFactory.tnc_cashback()

    def test_case_wrong_data_format(self):
        data = {
            'walter': self.loan.loan_xid,
            'white': self.promo_code.promo_code,
        }
        response = self.client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_case_invalid_loan(self):
        data = {
            'loan_xid': "0129380219",
            'promo_code': self.promo_code.promo_code,
        }
        response = self.client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_case_user_not_allowed(self):
        user = AuthUserFactory()
        new_client = APIClient()
        new_client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': self.promo_code.promo_code,
        }
        response = new_client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_case_not_exist_promo_code(self):
        self.promo_code.is_active = False
        self.promo_code.save()
        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': self.promo_code.promo_code,
        }
        response = self.client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errors'][0], PromoCodeMessage.ERROR.WRONG)

    @patch('juloserver.promo.views.check_promo_code_and_get_message')
    def test_case_good(self, mock_check_promo_code):
        message = "This, is not meth."
        mock_check_promo_code.return_value = True, message

        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': self.promo_code.promo_code,
        }

        response = self.client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_200_OK)

    def test_promo_code_criteria_limit_per_promo_code_success_case(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 6,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        self.promo_code.criteria = [
            criteria.id,
        ]
        self.promo_code.save()

        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': self.promo_code.promo_code,
        }
        resp = self.client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(HTTP_200_OK, resp.status_code)

    def test_promo_code_criteria_limit_per_promo_code_fail_tc1(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 5,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        self.promo_code.criteria = [
            criteria.id,
        ]
        self.promo_code.save()

        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': self.promo_code.promo_code,
        }
        resp = self.client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(HTTP_400_BAD_REQUEST, resp.status_code)
        self.assertEqual(resp.data['errors'][0], PromoCodeMessage.ERROR.LIMIT_PER_PROMO_CODE)

    def test_promo_code_criteria_limit_per_promo_code_fail_tc2(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 4,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        self.promo_code.criteria = [
            criteria.id,
        ]
        self.promo_code.save()

        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': self.promo_code.promo_code,
        }
        resp = self.client.post(
            path='/api/promo/v1/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(HTTP_400_BAD_REQUEST, resp.status_code)
        self.assertEqual(resp.data['errors'][0], PromoCodeMessage.ERROR.LIMIT_PER_PROMO_CODE)


class TestLoanPromoCodeTnC(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.fixed_cash_benefit = PromoCodeBenefitFactory(
            name="You bring me more meth, that's brilliant!",
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value = {
                'amount': 20000,
            },
            promo_page=PromoPageFactory.tnc_cashback()
        )
        self.promo_code = PromoCodeFactory(
            promo_code_benefit=self.fixed_cash_benefit,
            promo_code="TEST123",
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            promo_code_usage_count=5,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=1000000,
        )

    def test_get_tnc_from_promo_code(self):
        response = self.client.get(
            path= '/api/promo/v1/promo-code/tnc/{}/'.format(self.promo_code.promo_code),
        )
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertIsNotNone(data['data']['terms'])

    def test_promo_code_not_exist(self):
        response = self.client.get(
            path= '/api/promo/v1/promo-code/tnc/{}123/'.format(self.promo_code.promo_code),
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_get_min_transaction_in_response(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT,
            value={
                 'limit_per_promo_code': 4,
                 'minimum_loan_amount': 400000
            }
        )
        self.promo_code.criteria = [criteria.pk]
        self.promo_code.save()
        response = self.client.get(
            path= '/api/promo/v1/promo-code/tnc/{}/'.format(self.promo_code.promo_code),
        )
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertIsNotNone(data['data']['terms'])
        self.assertIsNotNone(data['data']['min_transaction'])


class TestPromoCMS(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user, id=123123123)
        self.feature_setting = PromoEntryPageFeatureSetting(
            parameters={
                'search_categories': [
                    {
                        'category': PromoCMSCategory.ALL,
                        'is_active': True
                    },
                    {
                        'category': PromoCMSCategory.AVAILABLE,
                        'is_active': True
                    },
                    {
                        'category': PromoCMSCategory.EXPIRED,
                        'is_active': True
                    }
                ]
            }
        )
        self.fake_redis = MockRedisHelper()
        self.header = {
            'info_title': 'Cek Info Menarik Untukmu!',
            'banner': 'https://cms-static.julo.co.id/media/651166f542a75_promo3.webp',
            'info_link': 'https://www.julo.co.id/',
            'content_type': 'image'
        }

    @patch('juloserver.promo.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_get_promo_list_berlangsung(self, mock_now, mock_get_client):
        mock_now.return_value = timezone.localtime(datetime(
            year=2022, month=10, day=15, hour=23, minute=59, second=59
        ))
        mock_get_client.return_value = self.fake_redis
        mock_redis_promo_list = {
            'header': self.header,
            'promo_codes': [
                {
                    'nid': 55,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                    'start_date': '2022-09-30 00:00:00',
                    'end_date': '2022-10-30 00:00:00',
                    'promo_code': 'habunkan'
                },
                {
                    'nid': 60,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 50.002!',
                    'start_date': '2022-09-30 00:00:00',
                    'end_date': '2022-10-25 00:00:00',
                    'promo_code': 'simplecode'
                },
                {
                    'nid': 65,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 40.002!',
                    'start_date': '2022-09-30 00:00:00',
                    'end_date': '2022-11-05 00:00:00',
                    'promo_code': 'lastpromocode'
                }
            ]
        }
        self.fake_redis.set(PromoCMSRedisConstant.PROMO_CMS_LIST, json.dumps(mock_redis_promo_list))

        url = '/api/promo/v1/promo-code/cms/promo_list?category=berlangsung'
        expected_response = {
            "header": self.header,
            "promo_codes": [
                {
                    "nid": 60,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 50.002!",
                    "start_date": "2022-09-30 00:00:00",
                    "end_date": "2022-10-25 00:00:00",
                    "promo_code": "simplecode"
                },
                {
                    "nid": 55,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
                    "start_date": "2022-09-30 00:00:00",
                    "end_date": "2022-10-30 00:00:00",
                    "promo_code": "habunkan"
                },
                {
                    "nid": 65,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 40.002!",
                    "start_date": "2022-09-30 00:00:00",
                    "end_date": "2022-11-05 00:00:00",
                    "promo_code": "lastpromocode"
                }
            ]
        }
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data'], expected_response
        )

    @patch('juloserver.promo.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_get_promo_list_berakhir(self, mock_now, mock_get_client):
        # test case berlangsung promo expired but expired date <= 30 days
        mock_now.return_value = timezone.localtime(datetime(
            year=2022, month=9, day=15, hour=23, minute=59, second=59
        ))
        mock_get_client.return_value = self.fake_redis
        mock_redis_promo_list = {
            'header': self.header,
            'promo_codes': [
                {
                    'nid': 55,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                    'start_date': '2022-08-01 00:00:00',
                    'end_date': '2022-09-05 00:00:00',
                    'promo_code': 'habunkan'
                },
                {
                    'nid': 60,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 50.002!',
                    'start_date': '2022-08-01 00:00:00',
                    'end_date': '2022-09-01 00:00:00',
                    'promo_code': 'simplecode'
                },
                {
                    'nid': 65,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 40.002!',
                    'start_date': '2022-08-01 00:00:00',
                    'end_date': '2022-08-25 00:00:00',
                    'promo_code': 'finalcode'
                }
            ]
        }
        self.fake_redis.set(PromoCMSRedisConstant.PROMO_CMS_LIST, json.dumps(mock_redis_promo_list))

        url = '/api/promo/v1/promo-code/cms/promo_list?category=berakhir'
        expected_response = {
            "header": self.header,
            "promo_codes": [
                {
                    "nid": 65,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 40.002!",
                    "start_date": "2022-08-01 00:00:00",
                    "end_date": "2022-08-25 00:00:00",
                    "promo_code": "finalcode"
                },
                {
                    "nid": 60,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 50.002!",
                    "start_date": "2022-08-01 00:00:00",
                    "end_date": "2022-09-01 00:00:00",
                    "promo_code": "simplecode"
                },
                {
                    "nid": 55,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
                    "start_date": "2022-08-01 00:00:00",
                    "end_date": "2022-09-05 00:00:00",
                    "promo_code": "habunkan"
                }
            ]
        }
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data'], expected_response
        )

        # test case berlangsung promo expired but # expire > day expire + 30
        mock_redis_promo_list = {
            'header': self.header,
            'promo_codes': [{
                'nid': 55,
                'promo_type': 'undian',
                'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                'start_date': '2022-05-30 00:00:00',
                'end_date': '2022-06-30 00:00:00',
                'promo_code': 'habunkan'
            }]
        }
        self.fake_redis.set(PromoCMSRedisConstant.PROMO_CMS_LIST, json.dumps(mock_redis_promo_list))
        expected_response = {
            "header": self.header,
            "promo_codes": []
        }
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data'], expected_response
        )

    @patch('juloserver.promo.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_get_promo_list_semua(self, mock_now, mock_get_client):
        # test case berlangsung
        mock_now.return_value = timezone.localtime(datetime(
            year=2022, month=10, day=15, hour=23, minute=59, second=59
        ))
        mock_get_client.return_value = self.fake_redis
        mock_redis_promo_list = {
            'header': self.header,
            'promo_codes': [
                {
                    'nid': 55,  # expire > day expire + 30
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                    'start_date': '2022-10-10 00:00:00',
                    'end_date': '2022-10-11 00:00:00',
                    'promo_code': 'habunkan'
                },
                {
                    'nid': 65,  # expire > day expire + 30
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.004!',
                    'start_date': '2022-10-01 00:00:00',
                    'end_date': '2022-10-02 00:00:00',
                    'promo_code': 'habunkan2'
                },
                {
                    'nid': 56,  # available
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                    'start_date': '2022-09-20 00:00:00',
                    'end_date': '2022-10-20 00:00:00',
                    'promo_code': 'habunkan'
                },
                {
                    'nid': 66,  # available
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.004!',
                    'start_date': '2022-09-25 00:00:00',
                    'end_date': '2022-10-25 00:00:00',
                    'promo_code': 'habunkan2'
                },
                {
                    'nid': 57,  # expire < day expire + 30
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                    'start_date': '2018-09-30 00:00:00',
                    'end_date': '2019-10-30 00:00:00',
                    'promo_code': 'habunkan'
                },
                {
                    'nid': 67,  # expire < day expire + 30
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.004!',
                    'start_date': '2018-09-30 00:00:00',
                    'end_date': '2019-12-30 00:00:00',
                    'promo_code': 'habunkan2'
                }
            ]
        }
        self.fake_redis.set(PromoCMSRedisConstant.PROMO_CMS_LIST, json.dumps(mock_redis_promo_list))

        url = '/api/promo/v1/promo-code/cms/promo_list?category=semua'
        expected_response = {
            "header": self.header,
            "promo_codes": [
                {
                    "nid": 56,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
                    "start_date": "2022-09-20 00:00:00",
                    "end_date": "2022-10-20 00:00:00",
                    "promo_code": "habunkan"
                },
                {
                    "nid": 66,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.004!",
                    "start_date": "2022-09-25 00:00:00",
                    "end_date": "2022-10-25 00:00:00",
                    "promo_code": "habunkan2"
                },
                {
                    "nid": 65,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.004!",
                    "start_date": "2022-10-01 00:00:00",
                    "end_date": "2022-10-02 00:00:00",
                    "promo_code": "habunkan2"
                },
                {
                    "nid": 55,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
                    "start_date": "2022-10-10 00:00:00",
                    "end_date": "2022-10-11 00:00:00",
                    "promo_code": "habunkan"
                }
            ]
        }
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data'], expected_response
        )

    @patch('juloserver.promo.services.sentry_client')
    @patch('juloserver.promo.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_get_promo_list_empty_date(self, mock_now, mock_get_client, mock_sentry_client):
        mock_now.return_value = timezone.localtime(datetime(
            year=2022, month=9, day=15, hour=23, minute=59, second=59
        ))
        mock_get_client.return_value = self.fake_redis
        mock_redis_promo_list = {
            'header': self.header,
            'promo_codes': [
                {
                    'nid': 55,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                    'start_date': '',
                    'end_date': '2022-09-05 00:00:00',
                    'promo_code': 'habunkan'
                },
                {
                    'nid': 60,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 50.002!',
                    'start_date': '2022-08-01 00:00:00',
                    'end_date': '',
                    'promo_code': 'simplecode'
                },
                {
                    'nid': 65,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 40.002!',
                    'start_date': '',
                    'end_date': '',
                    'promo_code': 'finalcode'
                }
            ]
        }
        self.fake_redis.set(
            PromoCMSRedisConstant.PROMO_CMS_LIST, json.dumps(mock_redis_promo_list)
        )

        url = '/api/promo/v1/promo-code/cms/promo_list'
        expected_response = {
            "header": self.header,
            "promo_codes": []
        }
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data'], expected_response
        )
        mock_sentry_client.captureException.assert_called()

    @patch('juloserver.promo.services.sentry_client')
    @patch('juloserver.promo.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_get_promo_list_invalid_format_date(self, mock_now, mock_get_client, mock_sentry_client):
        mock_now.return_value = timezone.localtime(datetime(
            year=2022, month=9, day=15, hour=23, minute=59, second=59
        ))
        mock_get_client.return_value = self.fake_redis
        mock_redis_promo_list = {
            'header': self.header,
            'promo_codes': [
                {
                    'nid': 55,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                    'start_date': '2022/08/01 00:00:00',
                    'end_date': '2022/09/05 00:00:00',
                    'promo_code': 'habunkan'
                },
                {
                    'nid': 60,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 50.002!',
                    'start_date': '2022/08/01 00:00:00',
                    'end_date': '2022/09/01 00:00:00',
                    'promo_code': 'simplecode'
                },
                {
                    'nid': 65,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 40.002!',
                    'start_date': '2022-08-01 00:00:00',
                    'end_date': '2022-08-25 00:00:00',
                    'promo_code': 'finalcode'
                }
            ]
        }
        self.fake_redis.set(
            PromoCMSRedisConstant.PROMO_CMS_LIST, json.dumps(mock_redis_promo_list)
        )

        url = '/api/promo/v1/promo-code/cms/promo_list'
        expected_response = {
            "header": self.header,
            "promo_codes": [
                {
                    'nid': 65,
                    'promo_type': 'undian',
                    'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                    'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 40.002!',
                    'start_date': '2022-08-01 00:00:00',
                    'end_date': '2022-08-25 00:00:00',
                    'promo_code': 'finalcode'
                }
            ]
        }
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data'], expected_response
        )
        mock_sentry_client.captureException.assert_called()

    @patch('juloserver.promo.services.get_redis_client')
    def test_get_promo_detail(self, mock_get_client):
        mock_get_client.return_value = self.fake_redis

        mock_redis_promo_detail = {
            'general': {
                'nid': 55,
                'promo_type': 'undian',
                'promo_image': 'https://cms-static.julo.co.id/Promo%20sample.png',
                'promo_title': 'Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!',
                'start_date': '2022-09-30 00:00:00',
                'end_date': '2023-09-30 00:00:00',
                'promo_code': 'habunkan',
            },
            'detail': {
                "info_alert": "info alert",
                "detail_contents": [
                    {
                        "order_number": 1,
                        "title": "promo title",
                        "content": "content could be HTML",
                        "icon": "image link"
                    },
                ],
                "share_promo": {
                    "title": "share title ",
                    "description": "description",
                    "url": "add url here"
                }
            }
        }
        self.fake_redis.set(
            PromoCMSRedisConstant.PROMO_CMS_DETAIL.format(55),
            json.dumps(mock_redis_promo_detail)
        )

        url = '/api/promo/v1/promo-code/cms/promo_detail?nid=55'
        response = self.client.get(url)
        # promo code does not exist => response transaction method None
        self.assertIsNone(response.json()['data']['transaction_method_id'])

        expected_response = {
            "nid": 55,
            "promo_type": "undian",
            "promo_image": "https://cms-static.julo.co.id/Promo%20sample.png",
            "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
            "start_date": "2022-09-30 00:00:00",
            "end_date": "2023-09-30 00:00:00",
            "promo_code": "habunkan",
            "transaction_method_id": 1,
            "detail": {
                "info_alert": "info alert",
                "detail_contents": [{
                    "order_number": 1,
                    "title": "promo title",
                    "content": "content could be HTML",
                    "icon": "image link"
                }],
                "share_promo": {
                    "title": "share title ",
                    "description": "description",
                    "url": "add url here"
                }
            }
        }
        self.criterion_transaction_method = PromoCodeCriteriaFactory(
            name='promo list page!',
            type=PromoCodeCriteriaConst.TRANSACTION_METHOD,
            value={"transaction_method_ids": [1]},
        )
        promo_code = PromoCodeFactory(promo_code='habunkan', type='loan')
        promo_code.criteria = [self.criterion_transaction_method.id]
        promo_code.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data'], expected_response
        )

        self.criterion_transaction_method.update_safely(value={"transaction_method_ids": [1, 2]})
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNone(response.json()['data']['transaction_method_id'])

        # case multiple transaction method criteria
        self.criterion_transaction_method_2 = PromoCodeCriteriaFactory(
            name='promo list page!',
            type=PromoCodeCriteriaConst.TRANSACTION_METHOD,
            value={"transaction_method_ids": [2]},
        )
        promo_code = PromoCodeFactory(promo_code='habunkan', type='loan')
        promo_code.criteria = [
            self.criterion_transaction_method.id,
            self.criterion_transaction_method_2.id
        ]
        promo_code.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNone(response.json()['data']['transaction_method_id'])

    def test_get_search_categories(self):
        parameters = self.feature_setting.parameters or {}
        parameters['search_categories'] = [
            {
                'category': PromoCMSCategory.ALL,
                'is_active': True
            }
        ]
        self.feature_setting.update_safely(parameters=parameters)
        url = '/api/promo/v1/promo-code/cms/get_search_categories/'
        response = self.client.get(url)
        self.assertEqual(response.json()['data'], ['semua'])
