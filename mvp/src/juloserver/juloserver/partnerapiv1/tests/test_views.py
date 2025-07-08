from http import HTTPStatus

from django.test.testcases import TestCase
from rest_framework.test import APIClient

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    GroupFactory,
    PartnerFactory,
)


class TestReferralCreateView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        PartnerFactory(user=self.user, is_active=True)
        group_factory = GroupFactory(name='julo_partners')
        self.user.groups.add(group_factory)

    def test_invalid_auth(self):
        response = self.client.post('/api/partner/v1/referrals/')
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    def test_success_create_parentreferral(self):
        self.client.force_authenticate(user=self.user)
        data = {'cust_email': 'testuser@julofinance.com', 'cust_nik': '1604900506000001'}
        response = self.client.post('/api/partner/v1/referrals/', data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.CREATED)

    def test_success_lower_case_cust_email(self):
        self.client.force_authenticate(user=self.user)
        data = {'cust_email': 'TeStuSer1@julofinance.com', 'cust_nik': '1604900506000002'}
        response = self.client.post('/api/partner/v1/referrals/', data=data, format='json')
        lower_case_email = data['cust_email'].lower()
        response_data = response.json()
        self.assertEqual(lower_case_email, response_data['cust_email'])
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
