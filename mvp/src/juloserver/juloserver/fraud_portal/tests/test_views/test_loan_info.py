from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase
from mock.mock import patch

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    StatusLookupFactory,
    LoanFactory,
    PaymentFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes


class TestLoanInfo(APITestCase):
    def setUp(self):
        self.maxDiff = None
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.application = ApplicationFactory(customer=self.customer)

    @patch('juloserver.fraud_portal.services.loan_info.get_fdc_data_history')
    @patch('juloserver.fraud_portal.services.loan_info.get_diabolical')
    def test_get_loan_info(self, mock_get_diabolical, mock_get_fdc_data_history):
        mock_get_fdc_data_history.return_value = True
        mock_get_diabolical.return_value = "Yes (Diabolical 5 and 40)"
        self.status_lookup = StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF)
        self.loan = LoanFactory(
            application=self.application,
            customer=self.customer
        )
        self.payment = PaymentFactory(
            loan=self.loan,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME),
        )
        url = '/api/fraud-portal/loan-info/?application_id={0}'.format(self.application.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()['data'][0]
        self.assertEqual(data['application_id'], self.application.id)
        self.assertEqual(data['application_fullname'], self.application.fullname)
        self.assertTrue(data['fdc_data_history'])
        self.assertEqual(data['diabolical'], "Yes (Diabolical 5 and 40)")
        loan_information = data['loan_information'][0]
        self.assertEqual(loan_information['loan_id'], self.loan.id)
        self.assertEqual(loan_information['loan_amount'], self.loan.loan_amount)
        self.assertIsNotNone(loan_information['loan_date'])
        self.assertIsNotNone(loan_information['loan_status'])
        self.assertIsNotNone(loan_information['repayment_history'])
        self.assertTrue(len(loan_information['repayment_history']) > 0)

    def test_failed_invalid_application_get_loan_info(self):
        invalid_application_id = self.application.id + 2024
        url = '/api/fraud-portal/loan-info/?application_id={0}'.format(invalid_application_id)
        response = self.client.get(url)
        expected_response = {
            "success": False,
            "data": None,
            "errors": ["Application matching query does not exist."],
        }
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), expected_response)
