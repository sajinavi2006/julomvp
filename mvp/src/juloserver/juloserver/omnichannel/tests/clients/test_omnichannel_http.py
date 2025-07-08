import unittest
from unittest.mock import patch
from juloserver.omnichannel.clients.omnichannel_http import OmnichannelHTTPClient
from juloserver.omnichannel.models import (
    OmnichannelCustomer,
    CustomerAttribute,
    AccountPaymentAttribute,
)
import json
from datetime import date
import copy

base_account_payment = AccountPaymentAttribute(
    account_payment_id=1,
    account_payment_xid="xid1",
    account_id=1001,
    due_date=date(2024, 12, 1),
    due_amount=1000,
    late_fee_amount=0,
    interest_amount=50,
    principal_amount=950,
    paid_amount=1000,
    paid_late_fee_amount=0,
    paid_interest_amount=50,
    paid_principal_amount=950,
    paid_date=date(2024, 12, 1),
    ptp_date=date(2024, 12, 2),
    status_code=1,
    ptp_amount=1000,
    ptp_robocall_phone_number="1234567890",
    is_restructured=False,
    autodebet_retry_count=0,
    is_collection_called=True,
    is_ptp_robocall_active=False,
    is_reminder_called=False,
    is_success_robocall=True,
    is_robocall_active=False,
    paid_during_refinancing=False,
    late_fee_applied=0,
    is_paid_within_dpd_1to10=True,
    potential_cashback=0,
    month_due_date="12",
    year_due_date="2024",
    due_date_long="2024-12-01",
    due_date_short="12-01",
    sms_payment_details_url="http://example.com/payment",
    formatted_due_amount="1000",
    sort_order=float('nan'),
)

class TestOmnichannelHTTPClient(unittest.TestCase):
    def setUp(self):
        self.client = OmnichannelHTTPClient('http://baseurl.com', 'token')

    @patch('requests.post')
    def test_update_customers(self, mock_post):
        # Arrange
        mock_response = mock_post.return_value
        mock_response.raise_for_status.return_value = None
        customers = [
            OmnichannelCustomer(
                customer_id=str(1),
            ),
            OmnichannelCustomer(
                customer_id=str(2),
            ),
        ]

        # Act
        response = self.client.update_customers(customers)

        # Assert
        mock_post.assert_called_once()
        self.assertEqual(response, mock_response)

    @patch('requests.post')
    def test_update_customers_float_conversion(self, mock_post):
        mock_response = mock_post.return_value
        mock_response.raise_for_status.return_value = None

        customers = [
            OmnichannelCustomer(
                customer_id="1",
                customer_attribute=CustomerAttribute(
                    account_payment=[base_account_payment]  # Use the mock object
                ),
            ),
            OmnichannelCustomer(
                customer_id="2",
                customer_attribute=CustomerAttribute(
                    account_payment=[
                        copy.deepcopy(base_account_payment)
                    ]  # Use the same mock object
                ),
            ),
            OmnichannelCustomer(
                customer_id="3",
                customer_attribute=CustomerAttribute(
                    account_payment=[
                        copy.deepcopy(base_account_payment)
                    ]  # Use the same mock object
                ),
            ),
        ]

        # Modify
        customers[0].customer_attribute.account_payment[0].sort_order = float(
            'nan'
        )  # NaN for the first customer
        customers[1].customer_attribute.account_payment[0].sort_order = float(
            'inf'
        )  # Infinity for the second customer
        customers[2].customer_attribute.account_payment[
            0
        ].sort_order = 0.0  # Valid float for the third customer

        # Act
        self.client.update_customers(customers)

        # Assert
        mock_post.assert_called_once()

        # Extract
        sent_data = json.loads(mock_post.call_args[1]['data'])

        self.assertEqual(
            sent_data[0]['customer_attribute']['account_payment'][0]['sort_order'], None
        )
        self.assertEqual(
            sent_data[1]['customer_attribute']['account_payment'][0]['sort_order'], None
        )
        self.assertEqual(
            sent_data[2]['customer_attribute']['account_payment'][0]['sort_order'], 0.0
        )
