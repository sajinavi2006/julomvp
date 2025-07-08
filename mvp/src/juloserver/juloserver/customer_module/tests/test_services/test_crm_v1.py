from django.test import TestCase
from juloserver.julo.tests.factories import (
    CustomerFactory,
)
from mock import patch

from juloserver.customer_module.services.crm_v1 import (
    force_logout_user,
)


class TestForceLogoutUser(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_success(self, mock_generate_new_token):
        force_logout_user(self.customer)

        mock_generate_new_token.assert_called_once_with(self.customer.user)