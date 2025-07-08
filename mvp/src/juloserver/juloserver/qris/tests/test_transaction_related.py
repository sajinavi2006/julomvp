from uuid import uuid4
from django.utils import timezone
from unittest.mock import patch
from mock import MagicMock
from rest_framework import status
from rest_framework.test import APIClient
from django.test.testcases import TestCase
from juloserver.account.constants import AccountConstant
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CustomerFactory,
    FeatureSettingFactory,
    PartnerFactory,
    LoanFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    ApplicationFactory,
    ProductLineFactory,
)
from django.db.utils import DatabaseError
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.models import LoanErrorLog
from juloserver.loan.services.loan_creation import BaseLoanCreationSubmitData
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.qris.exceptions import HasNotSignedWithLender, NoQrisLenderAvailable, QrisMerchantBlacklisted
from juloserver.qris.services.transaction_related import TransactionConfirmationService
from juloserver.qris.constants import QrisProductName, QrisLinkageStatus
from juloserver.qris.models import QrisUserState, QrisPartnerLinkage, QrisPartnerTransaction
from juloserver.qris.serializers import QRISTransactionSerializer
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.loan.constants import LoanErrorCodes, LoanFeatureNameConst, LoanLogIdentifierType
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    ProductLockException,
    LoanTransactionLimitExceeded,
    TransactionAmountExceeded,
    TransactionAmountTooLow,
)
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory, LenderCurrentFactory
from juloserver.followthemoney.constants import LenderName
from juloserver.julo.product_lines import ProductLineCodes


class TransactionConfirmationServiceTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=420)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=10000000,
            set_limit=1000000,
            available_limit=1000000,
            used_limit=0,
        )
        self.partner_xid = "Amar123321"
        self.partner = PartnerFactory(
            user=self.user, name=PartnerNameConstant.AMAR, partner_xid=self.partner_xid
        )
        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
            user=self.user,
        )
        self.qris_partner_linkage = QrisPartnerLinkage.objects.create(
            partner_id=self.partner.id,
            customer_id=self.customer.id,
            status=QrisLinkageStatus.SUCCESS,
        )
        self.qris_user_state = QrisUserState.objects.create(
            qris_partner_linkage=self.qris_partner_linkage,
        )
        self.request_data = {
            "partnerUserId": str(self.qris_partner_linkage.to_partner_user_xid),
            "totalAmount": 150000,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionId": "PARTNER-" + str(uuid4())[:8],
            "transactionDetail": {
                "feeAmount": 1500,
                "tipAmount": 5000,
                "transactionAmount": 143500,
                "merchantName": "Warung Padang Sederhana",
                "merchantCity": "Jakarta",
                "merchantCategoryCode": "5812",
                "merchantCriteria": "UMI",
                "acquirerId": "93600014",
                "acquirerName": "PT Bank Central Asia Tbk",
                "terminalId": "ID000123456",
            },
        }
        self.serializer = QRISTransactionSerializer(data=self.request_data)
        self.serializer.is_valid(raise_exception=True)
        self.validated_data = self.serializer.validated_data
        self.service = TransactionConfirmationService(self.validated_data, self.partner.id)
        self.url = '/api/qris/v1/transaction-confirmation'
        self.headers = {'HTTP_PARTNERXID': self.partner_xid}

        self.qris_error_log_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_ERROR_LOG,
            is_active=True,
        )

    @patch('juloserver.qris.services.transaction_related.execute_after_transaction_safely')
    @patch.object(TransactionConfirmationService, 'check_lender_eligibility')
    @patch('juloserver.qris.services.transaction_related.BaseLoanCreationService')
    def test_process_transaction_confirmation(
        self,
        mock_base_loan_creation_service,
        mock_check_lender_eligibility,
        mock_execute_after_transaction_safely,
    ):
        # mock
        mock_loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            loan_amount=151000,
            loan_duration=1,
        )
        mock_loan_creation_service = MagicMock()
        mock_base_loan_creation_service.return_value = mock_loan_creation_service
        mock_loan_creation_service.process_loan_creation.return_value = mock_loan
        mock_check_lender_eligibility.return_value = self.lender
        # run service
        result = self.service.process_transaction_confirmation()

        # assert
        mock_base_loan_creation_service.assert_called_once_with(
            customer=self.customer,
            submit_data=self.service.construct_data_for_loan_creation(),
        )
        mock_loan_creation_service.check_eligibility.assert_called_once()
        mock_loan_creation_service.process_loan_creation.assert_called_once_with(lender=self.lender)
        qris_partner_transaction = QrisPartnerTransaction.objects.filter(
            qris_partner_linkage=self.qris_partner_linkage,
            loan_id=mock_loan.pk,
        ).last()
        assert qris_partner_transaction is not None
        assert qris_partner_transaction.partner_transaction_request == self.request_data
        assert (
            qris_partner_transaction.merchant_name
            == self.request_data['transactionDetail']['merchantName']
        )
        assert qris_partner_transaction.total_amount == self.request_data['totalAmount']
        mock_loan.refresh_from_db()
        assert mock_loan.loan_status_id == LoanStatusCodes.FUND_DISBURSAL_ONGOING
        mock_execute_after_transaction_safely.assert_called()
        self.assertEqual(mock_execute_after_transaction_safely.call_count, 2)

        self.assertEqual(
            result,
            {
                "transactionInfo": {
                    "cdate": timezone.localtime(mock_loan.cdate),
                    "loanAmount": mock_loan.loan_amount,
                    "currency": "IDR",
                    "loanDuration": mock_loan.loan_duration,
                    "productId": self.request_data['productId'],
                    "productName": self.request_data['productName'],
                    "loanXID": mock_loan.loan_xid,
                    "totalAmount": self.request_data['totalAmount'],
                    "transactionId": qris_partner_transaction.to_partner_transaction_xid,
                    "partnerTransactionId": qris_partner_transaction.from_partner_transaction_xid,
                }
            },
        )
        with self.assertRaises(DatabaseError):
            result = self.service.process_transaction_confirmation()

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_successful_transaction(self, mock_process):
        expected_response = {
            "transactionInfo": {
                "cdate": "2024-02-20T00:00:00Z",
                "loanAmount": 151000,
                "currency": "IDR",
                "loanDuration": 1,
                "productId": 1,
                "productName": "QRIS",
                "loanXID": "1234567890",
                "totalAmount": 150000,
                "transactionId": "QRIS-12345678",
                "partnerTransactionId": "PARTNER-12345678",
            }
        }
        mock_process.return_value = expected_response
        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'], expected_response)
        self.assertEqual(response.data['success'], True)
        self.assertEqual(response.data['errorCode'], None)
        self.assertEqual(response.data['errors'], [])

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_account_limit_exceeded(self, mock_process):
        mock_process.side_effect = AccountLimitExceededException()

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.LIMIT_EXCEEDED.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.LIMIT_EXCEEDED.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.LIMIT_EXCEEDED.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.LIMIT_EXCEEDED.name)
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_blacklist_merchant(self, mock_process):
        mock_process.side_effect = QrisMerchantBlacklisted()

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.MERCHANT_BLACKLISTED.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.MERCHANT_BLACKLISTED.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.MERCHANT_BLACKLISTED.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.MERCHANT_BLACKLISTED.name)
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_product_locked(self, mock_process):
        mock_process.side_effect = ProductLockException()

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.PRODUCT_LOCKED.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.PRODUCT_LOCKED.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.PRODUCT_LOCKED.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.PRODUCT_LOCKED.name)
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_transaction_limit_exceeded(self, mock_process):
        mock_process.side_effect = LoanTransactionLimitExceeded()

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.TRANSACTION_LIMIT_EXCEEDED.code)
        self.assertEqual(
            response.data['errors'][0], LoanErrorCodes.TRANSACTION_LIMIT_EXCEEDED.message
        )

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.TRANSACTION_LIMIT_EXCEEDED.code)
        self.assertEqual(
            qris_error_log.error_detail, LoanErrorCodes.TRANSACTION_LIMIT_EXCEEDED.name
        )
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_general_exception(self, mock_process):
        error_info = "Unexpected error"
        mock_process.side_effect = Exception(error_info)

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.GENERAL_ERROR.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.GENERAL_ERROR.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.GENERAL_ERROR.code)
        self.assertEqual(
            qris_error_log.error_detail,
            error_info,
        )
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_duplicate_transaction(self, mock_process):
        mock_process.side_effect = DatabaseError

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.DUPLICATE_TRANSACTION.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.DUPLICATE_TRANSACTION.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.DUPLICATE_TRANSACTION.code)
        self.assertEqual(
            qris_error_log.error_detail,
            LoanErrorCodes.DUPLICATE_TRANSACTION.name,
        )
        self.assertEqual(qris_error_log.http_status_code, 400)

    def test_invalid_payload(self):
        invalid_payload = {
            'totalAmount': 'not a number',
            'productId': 'not a number',
        }
        response = self.client.post(self.url, invalid_payload, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_qris_transaction_amount_exceeded(self, mock_process_transaction):
        mock_process_transaction.side_effect = TransactionAmountExceeded

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['errorCode'], LoanErrorCodes.TRANSACTION_AMOUNT_EXCEEDED.code
        )
        self.assertEqual(
            response.data['errors'][0], LoanErrorCodes.TRANSACTION_AMOUNT_EXCEEDED.message
        )

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.TRANSACTION_AMOUNT_EXCEEDED.code)
        self.assertEqual(
            qris_error_log.error_detail, LoanErrorCodes.TRANSACTION_AMOUNT_EXCEEDED.name
        )
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_qris_no_lender_available(self, mock_process_transaction):
        mock_process_transaction.side_effect = NoQrisLenderAvailable

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.NO_LENDER_AVAILABLE.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.NO_LENDER_AVAILABLE.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.NO_LENDER_AVAILABLE.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.NO_LENDER_AVAILABLE.name)
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_qris_user_not_signed_to_lender(self, mock_process_transaction):
        mock_process_transaction.side_effect = HasNotSignedWithLender

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.LENDER_NOT_SIGNED.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.LENDER_NOT_SIGNED.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.LENDER_NOT_SIGNED.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.LENDER_NOT_SIGNED.name)
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'process_transaction_confirmation')
    def test_qris_transaction_amount_too_low(self, mock_process_transaction):
        mock_process_transaction.side_effect = TransactionAmountTooLow

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.code)
        self.assertEqual(
            response.data['errors'][0], LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.message
        )

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.code)
        self.assertEqual(
            qris_error_log.error_detail, LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.name
        )
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'get_qris_partner_linkage')
    def test_qris_linkage_not_success(self, mock_get_partner_linkage):
        # CASE LINKAGE NOT SUCCESS
        self.qris_partner_linkage.status = QrisLinkageStatus.FAILED
        self.qris_partner_linkage.save()
        mock_get_partner_linkage.return_value = self.qris_partner_linkage

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.qris_partner_linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.name)
        self.assertEqual(qris_error_log.http_status_code, 400)

    @patch.object(TransactionConfirmationService, 'get_qris_partner_linkage')
    def test_qris_linkage_not_exist(self, mock_get_partner_linkage):
        # CASE LINKAGE DOESN'T EXIST
        mock_get_partner_linkage.return_value = None

        response = self.client.post(self.url, self.request_data, format='json', **self.headers)

        print('response', response)
        print(response.content)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errorCode'], LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.message)

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=str(self.request_data['partnerUserId']),
            identifier_type=LoanLogIdentifierType.TO_AMAR_USER_XID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, self.url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.name)
        self.assertEqual(qris_error_log.http_status_code, 400)


class TestTransactionConfirmationService(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=420)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=10000000,
            set_limit=1000000,
            available_limit=1000000,
            used_limit=0,
        )
        self.partner = PartnerFactory(
            user=self.user,
            name=PartnerNameConstant.AMAR,
        )
        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
            user=self.user,
        )
        self.lender_balance = LenderBalanceCurrentFactory(
            lender=self.lender,
            available_balance=10_000_000,
        )
        self.qris_partner_linkage = QrisPartnerLinkage.objects.create(
            partner_id=self.partner.id,
            customer_id=self.customer.id,
            status=QrisLinkageStatus.SUCCESS,
        )
        self.qris_user_state = QrisUserState.objects.create(
            qris_partner_linkage=self.qris_partner_linkage,
        )

        self.tenure_from_loan_range_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_TENURE_FROM_LOAN_AMOUNT,
            parameters={
                "loan_amount_tenure_map": [
                    (0, 500_000, 1),
                    (500_000, 1_000_000, 2),
                ]
            },
            is_active=True,
        )

        self.max_qris_requested_amount = 3_000_000
        self.min_qris_requested_amount = 5000
        self.qris_loan_eligibility_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_LOAN_ELIGIBILITY_SETTING,
            parameters={
                "max_requested_amount": self.max_qris_requested_amount,
                "min_requested_amount": self.max_qris_requested_amount,
            },
            is_active=True,
        )
        self.qris_1_method = TransactionMethodFactory.qris_1()

        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(
            product=self.product,
        )
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=2,
        )
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=10_000_000)

        self.multi_lender_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_MULTIPLE_LENDER,
            parameters={
                "out_of_balance_threshold": 0,
                "lender_names_ordered_by_priority": [
                    self.lender.lender_name,
                ],
            },
        )

    def test_loan_tenure(self):
        total_amount = 500_000
        request_data = {
            "partnerUserId": str(self.qris_partner_linkage.to_partner_user_xid),
            "totalAmount": total_amount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionId": "12038201498",
            "transactionDetail": {
                "feeAmount": 1500,
                "tipAmount": 5000,
                "transactionAmount": 143500,
                "merchantName": "Warung Padang Sederhana",
                "merchantCity": "Jakarta",
                "merchantCategoryCode": "5812",
                "merchantCriteria": "UMI",
                "acquirerId": "93600014",
                "acquirerName": "PT Bank Central Asia Tbk",
                "terminalId": "ID000123456",
            },
        }

        expected_result = BaseLoanCreationSubmitData(
            loan_amount_request=total_amount,
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_duration=1,
        )
        result = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        ).construct_data_for_loan_creation()

        self.assertEqual(expected_result, result)

        # case > 500_000
        total_amount += 1
        request_data['totalAmount'] = total_amount

        expected_result = BaseLoanCreationSubmitData(
            loan_amount_request=total_amount,
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_duration=2,
        )
        result = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        ).construct_data_for_loan_creation()

        self.assertEqual(expected_result, result)

        # case out of range, default duration
        total_amount = 999_999_999
        request_data['totalAmount'] = total_amount

        expected_result = BaseLoanCreationSubmitData(
            loan_amount_request=total_amount,
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_duration=1,
        )
        result = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        ).construct_data_for_loan_creation()

        self.assertEqual(expected_result, result)

    @patch('juloserver.qris.services.transaction_related.has_linkage_signed_with_current_lender')
    @patch('juloserver.loan.services.loan_creation.get_credit_matrix_repeat')
    @patch(
        'juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_qris_loan_eligibility_max_requested_amount(self, mock_get_cm, mock_get_cm_repeat, mock_has_signed):
        mock_get_cm.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_get_cm_repeat.return_value = None
        mock_has_signed.return_value = True, self.lender

        total_amount = self.max_qris_requested_amount + 1000
        request_data = {
            "partnerUserId": str(self.qris_partner_linkage.to_partner_user_xid),
            "totalAmount": total_amount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionId": "12038201498",
            "transactionDetail": {
                "feeAmount": 1500,
                "tipAmount": 5000,
                "transactionAmount": 143500,
                "merchantName": "Warung Padang Sederhana",
                "merchantCity": "Jakarta",
                "merchantCategoryCode": "5812",
                "merchantCriteria": "UMI",
                "acquirerId": "93600014",
                "acquirerName": "PT Bank Central Asia Tbk",
                "terminalId": "ID000123456",
            },
        }

        service = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        )

        # not active fs
        self.qris_loan_eligibility_fs.is_active = False
        self.qris_loan_eligibility_fs.save()

        # expect no error
        service.process_transaction_confirmation()

        # fs active
        self.qris_loan_eligibility_fs.is_active = True
        self.qris_loan_eligibility_fs.save()

        service = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        )

        with self.assertRaises(TransactionAmountExceeded):
            service.process_transaction_confirmation()

    @patch('juloserver.qris.services.transaction_related.has_linkage_signed_with_current_lender')
    def test_check_lender_eligibility(self, mock_has_linkage_signed):
        total_amount = self.max_qris_requested_amount - 100
        request_data = {
            "partnerUserId": str(self.qris_partner_linkage.to_partner_user_xid),
            "totalAmount": total_amount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionId": "12038201498",
            "transactionDetail": {
                "feeAmount": 1500,
                "tipAmount": 5000,
                "transactionAmount": 143500,
                "merchantName": "Warung Padang Sederhana",
                "merchantCity": "Jakarta",
                "merchantCategoryCode": "5812",
                "merchantCriteria": "UMI",
                "acquirerId": "93600014",
                "acquirerName": "PT Bank Central Asia Tbk",
                "terminalId": "ID000123456",
            },
        }

        service = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        )

        expected_is_signed = True
        mock_has_linkage_signed.return_value = expected_is_signed, self.lender

        lender_result = service.check_lender_eligibility()
        self.assertEqual(self.lender, lender_result)

        # case not signed, throw error
        expected_is_signed = False
        mock_has_linkage_signed.return_value = expected_is_signed, self.lender

        with self.assertRaises(HasNotSignedWithLender):
            service.check_lender_eligibility()

    @patch('juloserver.qris.services.transaction_related.has_linkage_signed_with_current_lender')
    @patch('juloserver.loan.services.loan_creation.get_credit_matrix_repeat')
    @patch(
        'juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_qris_loan_eligibility_min_requested_amount(self, mock_get_cm, mock_get_cm_repeat, mock_has_signed):
        mock_get_cm.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_get_cm_repeat.return_value = None
        mock_has_signed.return_value = True, self.lender

        total_amount = self.min_qris_requested_amount - 1000
        request_data = {
            "partnerUserId": str(self.qris_partner_linkage.to_partner_user_xid),
            "totalAmount": total_amount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionId": "12038201498",
            "transactionDetail": {
                "feeAmount": 1500,
                "tipAmount": 5000,
                "transactionAmount": 143500,
                "merchantName": "Warung Padang Sederhana",
                "merchantCity": "Jakarta",
                "merchantCategoryCode": "5812",
                "merchantCriteria": "UMI",
                "acquirerId": "93600014",
                "acquirerName": "PT Bank Central Asia Tbk",
                "terminalId": "ID000123456",
            },
        }

        service = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        )

        # not active fs
        self.qris_loan_eligibility_fs.is_active = False
        self.qris_loan_eligibility_fs.save()

        # expect no error
        service.process_transaction_confirmation()

        # fs active
        self.qris_loan_eligibility_fs.is_active = True
        self.qris_loan_eligibility_fs.save()

        service = TransactionConfirmationService(
            request_data=request_data,
            partner_id=self.partner.id,
        )

        with self.assertRaises(TransactionAmountTooLow):
            service.process_transaction_confirmation()
