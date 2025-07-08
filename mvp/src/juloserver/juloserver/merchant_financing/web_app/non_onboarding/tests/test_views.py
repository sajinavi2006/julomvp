from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from unittest.mock import patch

from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory


class TestWebAppNonOnboardingUpdateLoan(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

    @patch('juloserver.merchant_financing.web_app.utils.verify_access_token')
    @patch('juloserver.merchant_financing.web_app.utils.decode_jwt_token')
    @patch('juloserver.merchant_financing.web_app.utils.verify_token_is_active')
    @patch('juloserver.merchant_financing.web_app.utils.get_user_from_token')
    def test_failed_loan_update_funder_not_found(
        self,
        mock_get_user_from_token,
        mock_verify_token_is_active,
        mock_decode_jwt_token,
        mock_verify_access_token,
    ):
        mock_verify_access_token.return_value = "dummy_access_token"
        mock_decode_jwt_token.return_value = {"dummy_key": "dummy_value"}
        mock_verify_token_is_active.return_value = True
        mock_get_user_from_token.return_value = self.user

        data = {"distributor_code": "012", "interest_rate": 0.36, "provision_rate": 0.05}

        with patch(
            "juloserver.merchant_financing.web_app.non_onboarding.services.update_merchant_financing_webapp_loan"
        ) as mock_update_loan:
            mock_update_loan.return_value = (False, "Invalid interest rate")
            response = self.client.put(
                '/api/merchant-financing/dashboard/loan/1001020752', data=data, format='json'
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('juloserver.merchant_financing.web_app.utils.verify_access_token')
    @patch('juloserver.merchant_financing.web_app.utils.decode_jwt_token')
    @patch('juloserver.merchant_financing.web_app.utils.verify_token_is_active')
    @patch('juloserver.merchant_financing.web_app.utils.get_user_from_token')
    @patch(
        'juloserver.merchant_financing.web_app.non_onboarding.services.update_merchant_financing_webapp_loan'
    )
    def test_success_loan_update(
        self,
        mock_update_loan,
        mock_get_user_from_token,
        mock_verify_token_is_active,
        mock_decode_jwt_token,
        mock_verify_access_token,
    ):
        mock_verify_access_token.return_value = "dummy_access_token"
        mock_decode_jwt_token.return_value = {"dummy_key": "dummy_value"}
        mock_verify_token_is_active.return_value = True
        mock_get_user_from_token.return_value = self.user
        mock_update_loan.return_value = (True, "")

        # Define data for update_loan function
        data = {
            "distributor_code": "012",
            "funder_name": "JULO",
            "interest_rate": 0.36,
            "provision_rate": 0.05,
        }

        with patch(
            "juloserver.merchant_financing.web_app.non_onboarding.services.update_merchant_financing_webapp_loan"
        ) as mock_update_loan:
            mock_update_loan.return_value = (True, "")
            self.client.put(
                '/api/merchant-financing/dashboard/loan/1001020752', data=data, format='json'
            )

    @patch('juloserver.merchant_financing.web_app.utils.verify_access_token')
    @patch('juloserver.merchant_financing.web_app.utils.decode_jwt_token')
    @patch('juloserver.merchant_financing.web_app.utils.verify_token_is_active')
    @patch('juloserver.merchant_financing.web_app.utils.get_user_from_token')
    def test_failed_loan_update_interest_rate_not_number(
        self,
        mock_get_user_from_token,
        mock_verify_token_is_active,
        mock_decode_jwt_token,
        mock_verify_access_token,
    ):
        mock_verify_access_token.return_value = "dummy_access_token"
        mock_decode_jwt_token.return_value = {"dummy_key": "dummy_value"}
        mock_verify_token_is_active.return_value = True
        mock_get_user_from_token.return_value = self.user

        data = {
            "distributor_code": "012",
            "funder_name": "JULO",
            "interest_rate": "E36",
            "provision_rate": 0.05,
        }

        with patch(
            "juloserver.merchant_financing.web_app.non_onboarding.services.update_merchant_financing_webapp_loan"
        ) as mock_update_loan:
            mock_update_loan.return_value = (False, "Invalid interest rate")
            response = self.client.put(
                '/api/merchant-financing/dashboard/loan/1001020752', data=data, format='json'
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestWebAppNonOnboardingLoanListView(APITestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

    @patch("juloserver.merchant_financing.web_app.utils.verify_access_token")
    @patch("juloserver.merchant_financing.web_app.utils.decode_jwt_token")
    @patch("juloserver.merchant_financing.web_app.utils.verify_token_is_active")
    @patch("juloserver.merchant_financing.web_app.utils.get_user_from_token")
    def test_success_get_loan_list(
        self,
        mock_get_user_from_token,
        mock_verify_token_is_active,
        mock_decode_jwt_token,
        mock_verify_access_token,
    ):
        mock_verify_access_token.return_value = "dummy_access_token"
        mock_decode_jwt_token.return_value = {"dummy_key": "dummy_value"}
        mock_verify_token_is_active.return_value = True
        mock_get_user_from_token.return_value = self.user

        response = self.client.get(
            "/api/merchant-financing/web-app/loan/?loan_status=DONE&limit=10&page=1",
            format="json",
        )

    def test_failed_authorization_get_loan_list(self):
        response = self.client.get(
            "/api/merchant-financing/web-app/loan/?loan_status=DONE&limit=10&page=1",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
