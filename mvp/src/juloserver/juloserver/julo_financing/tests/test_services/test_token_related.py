from mock import patch
from datetime import datetime

from django.conf import settings
from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import ApplicationJ1Factory, CustomerFactory
from juloserver.julo_financing.services.token_related import JFinancingToken, TokenData


class TestJFinancingTokenService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)

        settings.J_FINANCING_SECRET_KEY_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        self.token_obj = JFinancingToken()
        self.jfinancing_token = self.token_obj.generate_token(
            self.customer.id,
            token_expired_hours=24 * 30,  # a month
        )

    def test_is_valid_token(self):
        input_token_data = TokenData(
            customer_id=self.customer.id,
            event_time=datetime.strptime("3000-01-01", "%Y-%m-%d").timestamp(),
            expiry_time=datetime.strptime("3000-02-01", "%Y-%m-%d").timestamp(),
        )
        token = self.token_obj.encrypt(input_token_data)

        # happy case
        is_valid, token_data = self.token_obj.is_token_valid(token=token)
        assert is_valid == True
        assert input_token_data == token_data

        # case invalid token
        nonsense_token = "wackwack"
        is_valid, token_data = self.token_obj.is_token_valid(token=nonsense_token)

        assert is_valid == False
        assert token_data is None

        # case time expired
        input_token_data = TokenData(
            customer_id=self.customer.id,
            event_time=datetime.strptime("1000-01-01", "%Y-%m-%d").timestamp(),
            expiry_time=datetime.strptime("1000-02-01", "%Y-%m-%d").timestamp(),  # in the past
        )
        token = self.token_obj.encrypt(input_token_data)
        is_valid, token_data = self.token_obj.is_token_valid(token=token)
        assert is_valid == False
        assert token_data is None
