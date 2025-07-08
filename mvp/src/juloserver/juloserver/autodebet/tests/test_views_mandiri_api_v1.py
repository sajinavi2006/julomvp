from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from juloserver.autodebet.tests.factories import (
    AutodebetMandiriAccountFactory,
    AutodebetMandiriTransactionFactory,
    AutodebetAccountFactory,
)
from juloserver.autodebet.constants import AutodebetVendorConst

from juloserver.account.tests.factories import AccountFactory

from juloserver.julo.models import PaybackTransaction
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
)
from juloserver.autodebet.services.task_services import get_autodebet_payment_method


class TestPurchaseNotificationView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/webhook/autodebet/mandiri/v1/purchase_notification"
        self.customer = CustomerFactory(customer_xid=843757867)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(account=self.account, customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True
        )
        self.autodebet_mandiri = AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account
        )
        self.autodebet_mandiri_transaction = AutodebetMandiriTransactionFactory(
            autodebet_mandiri_account=self.autodebet_mandiri
        )
        self.client.credentials(
            HTTP_X_PARTNER_ID="partner_id",
            HTTP_X_TIMESTAMP=timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S+07:00"),
            HTTP_X_SIGNATURE="signature",
            HTTP_X_EXTERNAL_ID='1',
        )
        self.data = {
            "responseCode": "2005600",
            "responseMessage": "SUCCESSFUL",
            "originalPartnerReferenceNo": self.autodebet_mandiri_transaction.original_partner_reference_no,
            "latestTransactionStatus": "00",
            "transactionStatusDesc": "Success",
        }

    @patch("juloserver.autodebet.views.views_mandiri_api_v1.process_mandiri_autodebet_repayment")
    @patch("juloserver.autodebet.views.views_mandiri_api_v1.verify_asymmetric_signature")
    def test_post_success(self, mock_verify_asymmetric_signature,
                          mock_process_mandiri_autodebet_repayment):
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"responseCode": "2005600", "responseMessage": "SUCCESS"})
        self.assertTrue(PaybackTransaction.objects.filter(
            transaction_id=self.data["originalPartnerReferenceNo"]
        ).exists())
        mock_process_mandiri_autodebet_repayment.assert_called_once()

    @patch("juloserver.autodebet.views.views_mandiri_api_v1.verify_asymmetric_signature")
    def test_post_invalid_data(self, mock_verify_asymmetric_signature):
        mock_verify_asymmetric_signature.return_value = True
        self.data["originalPartnerReferenceNo"] = "invalid_reference_no"
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json(),
                         {"responseCode": "4045600", "responseMessage": "TRANSACTION NOT FOUND"})

    @patch("juloserver.autodebet.views.views_mandiri_api_v1.verify_asymmetric_signature")
    def test_post_already_processed(self, mock_verify_asymmetric_signature):
        mock_verify_asymmetric_signature.return_value = True
        vendor = self.autodebet_account.vendor
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=True,
            customer=self.account.customer,
            payback_service='autodebet',
            status_desc='Autodebet {}'.format(vendor),
            transaction_id=self.data["originalPartnerReferenceNo"],
            transaction_date=timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S+07:00"),
            amount=self.autodebet_mandiri_transaction.amount,
            account=self.account,
            payment_method=get_autodebet_payment_method(
                self.account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
            ),
        )
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json(), {"responseCode": "400560",
                                           "responseMessage": "TRANSACTION ALREADY PROCESSED"})
        payback_transaction.refresh_from_db()
        self.assertTrue(payback_transaction.is_processed)

    @patch("juloserver.autodebet.views.views_mandiri_api_v1.process_mandiri_autodebet_repayment")
    @patch("juloserver.autodebet.views.views_mandiri_api_v1.verify_asymmetric_signature")
    def test_post_internal_server_error(self, mock_verify_asymmetric_signature,
                                        mock_process_mandiri_autodebet_repayment):
        mock_process_mandiri_autodebet_repayment.side_effect = Exception("Something went wrong")
        mock_verify_asymmetric_signature.return_value = True
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, 500, response.content)
        self.assertEqual(response.json(),
                         {"responseCode": "5005600", "responseMessage": "INTERNAL SERVER ERROR"})
        mock_process_mandiri_autodebet_repayment.assert_called_once()

    @patch("juloserver.autodebet.views.views_mandiri_api_v1.process_mandiri_autodebet_repayment")
    @patch("juloserver.autodebet.views.views_mandiri_api_v1.verify_asymmetric_signature")
    def test_dispatch(self, mock_verify_asymmetric_signature,
                      mock_process_mandiri_autodebet_repayment):
        mock_verify_asymmetric_signature.return_value = True
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNotNone(response._headers["x-timestamp"])
        self.assertIsNotNone(response._headers["x-signature"])
        self.assertIsNotNone(response._headers["x-partner-id"])
        self.assertIsNotNone(response._headers["x-external-id"])
