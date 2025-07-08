from rest_framework.test import APITestCase
from rest_framework.reverse import reverse
from rest_framework import status
from juloserver.julo.tests.factories import PartnerFactory, AuthUserFactory
from ..factories import LenderBucketFactory


class TestApplicationLender(APITestCase):
    def test_list_application(self):
        data = {}
        url = reverse('list_application')
        user = AuthUserFactory(username='test1')
        self.client.force_authenticate(user)
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        partner = PartnerFactory(user=user)
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        LenderBucketFactory(partner=partner)
        data = {'application_id': 1, 'last_application_id': 1}
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_application_past_view(self):
        url = reverse('list_application_past')
        user = AuthUserFactory(username='test1')
        self.client.force_authenticate(user)
        PartnerFactory(user=user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
