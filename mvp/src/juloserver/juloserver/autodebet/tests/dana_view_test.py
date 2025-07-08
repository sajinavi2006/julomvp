from mock import ANY, patch
from rest_framework.test import APIClient, APITestCase

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.autodebet.constants import AutodebetDanaResponseMessage


class DanaDeactivationAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.account = AccountFactory(customer=self.customer)

    @patch('juloserver.autodebet.views.views_dana_api_v1.dana_autodebet_deactivation')
    def test_dana_deactivation_success(self, mock_dana_autodebet_deactivation):
        url = '/api/autodebet/dana/v1/deactivation'
        mock_dana_autodebet_deactivation.return_value = (
            AutodebetDanaResponseMessage.SUCCESS_DEACTIVATION,
            True,
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.autodebet.views.views_dana_api_v1.dana_autodebet_deactivation')
    def test_dana_deactivation_failed(self, mock_dana_autodebet_deactivation):
        url = '/api/autodebet/dana/v1/deactivation'
        mock_dana_autodebet_deactivation.return_value = (
            AutodebetDanaResponseMessage.AUTODEBET_NOT_FOUND,
            False,
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
