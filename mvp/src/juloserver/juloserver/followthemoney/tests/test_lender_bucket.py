from mock import patch
from rest_framework.test import APITestCase
from rest_framework.reverse import reverse
from rest_framework import status
from juloserver.julo.tests.factories import PartnerFactory, AuthUserFactory
from ..factories import LenderCurrentFactory, LenderBucketFactory, LenderBalanceCurrentFactory


class TestLenderBucket(APITestCase):

    def create_user(self):
        user = AuthUserFactory(username='test')
        self.client.force_authenticate(user)
        partner = PartnerFactory(user=user)
        return user, partner

    def test_list_lender_bucket_login(self):
        data = dict()
        url = reverse('list_lender_bucket')
        user = AuthUserFactory(username='test1')
        self.client.force_authenticate(user)
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        PartnerFactory(user=user)
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cancel_bucket_views(self):
        data = dict(bucket=dict(id=1))
        url = reverse('cancel_lender_bucket')
        user = AuthUserFactory(username='test1')
        self.client.force_authenticate(user)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        partner = PartnerFactory(user=user)
        lender = LenderBucketFactory(partner=partner)
        data['bucket']['id'] = lender.id
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_lender_bucket_login(self):
        data = dict(application_ids={"approved": ['2000000141'], "rejected": ['2000000146']})
        url = reverse('create_lender_bucket')
        user, partner = self.create_user()
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_summary_views(self):
        url = reverse('followthemoney_summary')
        self.create_user()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_report_views(self):
        url = reverse('followthemoney_report')
        self.create_user()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.followthemoney.views.application_views.get_total_outstanding_for_lender')
    def test_performance_summary(self, mock_get_total_outstanding_for_lender):
        mock_get_total_outstanding_for_lender.return_value = 123
        url = reverse('performance_summary')
        user, partner = self.create_user()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        lender = LenderCurrentFactory(user=user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        LenderBalanceCurrentFactory(lender=lender)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_available_balance(self):
        url = reverse('available_balance')
        user, partner = self.create_user()
        lender = LenderCurrentFactory(user=user)
        LenderBalanceCurrentFactory(lender=lender)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
