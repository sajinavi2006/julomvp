from rest_framework.status import HTTP_200_OK
from rest_framework.test import APIClient
from django.test.testcases import TestCase
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
)
from juloserver.faq.tests.factories import (
    FaqFactory,
)


class FaqTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.faq1 = FaqFactory(feature_name='loyalty', question='first question', answer='test', order_priority=1)
        self.faq3 = FaqFactory(feature_name='loyalty', question='third question', answer='test', order_priority=3)
        self.faq4 = FaqFactory(feature_name='loyalty', question='fourth question', answer='test', order_priority=4, is_active=False)
        self.faq2 = FaqFactory(feature_name='loyalty', question='second question', answer='test', order_priority=2)

        self.get_faq_url = '/api/faq/v1/questions/'

      # get success first day
    def test_get_success(self):
        response = self.client.get(self.get_faq_url+'loyalty')
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        
        self.assertIsNotNone(resp_data['faq'])
        self.assertEqual(resp_data['faq'][0]['question'], 'first question')
        self.assertEqual(resp_data['faq'][1]['question'], 'second question')
