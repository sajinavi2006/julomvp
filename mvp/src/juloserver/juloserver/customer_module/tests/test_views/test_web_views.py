from django.test.testcases import TestCase
from mock import patch
from rest_framework.test import APIClient

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
)


class TestCreditInfoWebApi(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.credit_score = CreditScoreFactory(application_id=self.application.id, score='B-')
        self.loan = LoanFactory(account=self.account)
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action",
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self",
                },
                "bottom_right": {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman",
                },
            },
        )

    def test_credit_info(self):
        response = self.client.get('/api/customer-module/web/v1/credit-info/')
        assert response.status_code == 200
