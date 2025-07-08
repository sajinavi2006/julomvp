from mock import patch, MagicMock

from django.test import TestCase
from django.test.utils import override_settings
from juloserver.disbursement.services import PaymentGatewayDisbursementProcess
from juloserver.disbursement.services.payment_gateway import PaymentGatewayService
from juloserver.grab.models import (
    PaymentGatewayVendor,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLookupFactory,
    ProductLineFactory,
)
from juloserver.disbursement.constants import (
    DisbursementStatus,
    NameBankValidationStatus,
    DisbursementVendors,
)
from juloserver.disbursement.tests.factories import (
    DisbursementFactory,
    NameBankValidationFactory,
)
from juloserver.disbursement.clients.payment_gateway import InquiryResponse, TransferResponse
from juloserver.payment_gateway.constants import Vendor
from faker import Faker

fake = Faker()


@override_settings(
    PAYMENT_GATEWAY_BASE_URL='http://127.0.0.1:8000',
    PAYMENT_GATEWAY_CLIENT_SECRET='PAYMENT_GATEWAY_CLIENT_SECRET',
)
class TestPaymentGatewayServices(TestCase):
    def setUp(self):
        self.doku_payment_gateway_vendor = PaymentGatewayVendor.objects.create(name="doku")
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.grab_pg_service = PaymentGatewayService('GRABDUMMYCLIENT', 'GRABDUMMYAPI')

    @patch('juloserver.disbursement.services.PaymentGatewayService')
    def test_disburse_j1_success(self, mock_pg_service):
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            ),
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE', validation_status=NameBankValidationStatus.SUCCESS
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid, name_bank_validation=name_bank_validation
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        pg_disbursement_service = PaymentGatewayDisbursementProcess(disbursement)
        # first one is creating
        # mock callback already called (status updated to active)

        mock_pg_service().disburse.return_value = {
            'status': 'PENDING',
            'reason': 'disbursement created',
            'id': 123123,
        }
        status = pg_disbursement_service.disburse_j1()
        self.assertTrue(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)
        self.assertEqual(disbursement.reason, 'disbursement created')
        self.assertEqual(disbursement.disburse_id, '123123')

    @patch('juloserver.julo.models.XidLookup.get_new_xid')
    @patch('juloserver.disbursement.services.PaymentGatewayService')
    def test_disburse_grab_success(self, mock_pg_service, mock_get_new_xid):
        mock_get_new_xid.return_value = '1221'
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        product = ProductLookupFactory(product_line=product_line)

        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=product
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE', validation_status=NameBankValidationStatus.SUCCESS
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid, name_bank_validation=name_bank_validation
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        pg_disbursement_service = PaymentGatewayDisbursementProcess(disbursement)
        # first one is creating
        # mock callback already called (status updated to active)

        mock_pg_service().disburse.return_value = {
            'status': 'PENDING',
            'reason': 'disbursement created',
            'id': 123123,
        }
        status = pg_disbursement_service.disburse()
        self.assertTrue(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)
        self.assertEqual(disbursement.reason, 'disbursement created')
        self.assertEqual(disbursement.disburse_id, '123123')

    def test_process_callback_disbursement(self):
        # test INSUFFICIENT_BALANCE callback for J1
        pg_service = PaymentGatewayService('213123', 'dasdasdas')
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            ),
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            disburse_id='6dab30c9e5554a31ac18ee9a03deb5c9',
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        callback_data = {
            "transaction_id": 12323,
            "transaction_date": "2025-01-01 00:00:00",
            "bank_account": "08829393020",
            "bank_code": "002",
            "bank_account_name": "John Doe",
            "preferred_pg": "doku",
            "amount": "100000",
            "status": "success",
            "can_retry": False,
            "message": "successfully",
        }
        response_disbursement = pg_service.process_callback_disbursement(callback_data)
        self.assertEqual(response_disbursement['status'], DisbursementStatus.COMPLETED)
        self.assertEqual(response_disbursement['reason'], 'successfully')

    @patch('juloserver.julo.models.XidLookup.get_new_xid')
    def test_process_callback_disbursement_grab(self, mock_get_new_xid):
        mock_get_new_xid.return_value = '1221'
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        product = ProductLookupFactory(product_line=product_line)

        pg_service = PaymentGatewayService('213123', 'dasdasdas')
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=product
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            disburse_id='6dab30c9e5554a31ac18ee9a03deb5c9',
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        callback_data = {
            "transaction_id": 12323,
            "transaction_date": "2025-01-01 00:00:00",
            "bank_account": "08829393020",
            "bank_code": "002",
            "bank_account_name": "John Doe",
            "preferred_pg": "doku",
            "amount": "100000",
            "status": "success",
            "can_retry": False,
            "message": "successfully",
        }
        response_disbursement = pg_service.process_callback_disbursement(callback_data)
        self.assertEqual(response_disbursement['status'], DisbursementStatus.COMPLETED)
        self.assertEqual(response_disbursement['reason'], 'successfully')

    @patch('juloserver.disbursement.services.payment_gateway.get_payment_gateway_client')
    def test_create_disbursement(self, mock_get_payment_gateway_client):
        pg_service = PaymentGatewayService('213123', 'dasdasdas')
        resp = {'transaction': {"status": 1}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = resp
        mock_get_payment_gateway_client().create_disbursement.return_value = {
            'response': TransferResponse(
                **{
                    "bank_account": '1234567890',
                    "bank_account_name": "John Doe",
                    "transaction_id": 12322,
                    "transaction_date": "2024-12-12 00:00:11",
                    "bank_code": '002',
                    "preferred_pg": "doku",
                    "amount": "100000",
                    "status": "pending",
                    "message": "Transaction in progress",
                    "can_retry": False,
                    "object_transfer_type": "loan",
                    "object_transfer_id": "12333",
                    "bank_id": 1,
                }
            ),
            'error': None,
            'is_error': None,
        }

        loan = LoanFactory()

        data = {
            'amount': '1111111',
            'bank_account': 'account_number',
            'bank_account_name': 'name_in_bank',
            'bank_code': 'bank_code',
            'object_transfer_type': 'loan',
            'object_transfer_id': loan.id,
            'callback_url': 'http:lc/callbacks/v1/payment-gateway-disburse',
        }

        # log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        response = pg_service.create_disbursement(data)
        self.assertEqual(response.get('status'), DisbursementStatus.PENDING)

    @patch(
        'juloserver.disbursement.clients.payment_gateway.PaymentGatewayClient.validate_bank_account'
    )
    def test_success_validate_grab_name_bank_validation(self, mock_client_validate_bank_account):
        name_bank_validation = NameBankValidationFactory(
            bank_id=fake.numerify(text="#%#%"),
            bank_code=fake.numerify(text="#%#%"),
            name_in_bank=fake.name(),
        )
        mocked_client_validate_bank_account_response = {
            'response': InquiryResponse(
                bank_id=name_bank_validation.bank_id,
                bank_account=name_bank_validation.account_number,
                bank_account_name=name_bank_validation.name_in_bank,
                bank_code=name_bank_validation.bank_code,
                preferred_pg=Vendor.DOKU,
                validation_result={
                    'status': 'success',
                    'bank_account_info': {
                        'bank_account': name_bank_validation.account_number,
                        'bank_account_name': name_bank_validation.name_in_bank,
                        'bank_code': name_bank_validation.bank_code,
                    },
                    'message': 'Successful',
                },
            ),
            'error': None,
            'is_error': False,
        }

        mock_client_validate_bank_account.return_value = (
            mocked_client_validate_bank_account_response
        )

        response_validate = self.grab_pg_service.validate_grab(name_bank_validation)
        expected_result = {
            'id': name_bank_validation.bank_id,
            'status': NameBankValidationStatus.SUCCESS,
            'validated_name': name_bank_validation.name_in_bank,
            'reason': 'success',
            'error_message': None,
            'account_no': name_bank_validation.account_number,
            'bank_abbrev': name_bank_validation.bank_code,
        }
        self.assertEqual(response_validate, expected_result)

    @patch(
        'juloserver.disbursement.clients.payment_gateway.PaymentGatewayClient.validate_bank_account'
    )
    def test_success_name_bank_validation_with_error_validation_result(
        self, mock_client_validate_bank_account
    ):
        name_bank_validation = NameBankValidationFactory(
            bank_code=fake.numerify(text="#%#%"), name_in_bank=fake.name()
        )
        mocked_client_validate_bank_account_response = {
            'response': InquiryResponse(
                bank_id=name_bank_validation.bank_id,
                bank_account=name_bank_validation.account_number,
                bank_account_name=name_bank_validation.name_in_bank,
                bank_code=name_bank_validation.bank_code,
                preferred_pg=Vendor.DOKU,
                validation_result={
                    "status": "failed",
                    "bank_account_info": {
                        "bank_account_name": "JAMES BOND",
                        "bank_account": name_bank_validation.account_number,
                        "bank_code": name_bank_validation.bank_code,
                    },
                    "message": "Bank account info are different: ['bank_account_name']",
                },
            ),
            'error': None,
            'is_error': False,
        }

        mock_client_validate_bank_account.return_value = (
            mocked_client_validate_bank_account_response
        )

        validate_result = self.grab_pg_service.validate_grab(name_bank_validation)
        expected_result = {
            'id': None,
            'status': NameBankValidationStatus.NAME_INVALID,
            'validated_name': "JAMES BOND",
            'reason': 'Failed to add bank account',
            'error_message': mocked_client_validate_bank_account_response.get(
                "response"
            ).validation_result.get("message"),
            'account_no': name_bank_validation.account_number,
            'bank_abbrev': name_bank_validation.bank_code,
        }
        self.assertEqual(validate_result, expected_result)

    @patch(
        'juloserver.disbursement.clients.payment_gateway.PaymentGatewayClient.validate_bank_account'
    )
    def test_failed_name_bank_validation(self, mock_client_validate_bank_account):
        name_bank_validation = NameBankValidationFactory(
            bank_code=fake.numerify(text="#%#%"), name_in_bank=fake.name()
        )
        mocked_client_validate_bank_account_response = {
            'response': {},
            'error': ["Invalid params"],
            'is_error': True,
        }

        mock_client_validate_bank_account.return_value = (
            mocked_client_validate_bank_account_response
        )

        validate_result = self.grab_pg_service.validate_grab(name_bank_validation)
        expected_result = {
            'id': None,
            'status': NameBankValidationStatus.NAME_INVALID,
            'validated_name': None,
            'reason': 'Failed to add bank account',
            'error_message': None,
            'account_no': None,
            'bank_abbrev': None,
        }
        self.assertEqual(validate_result, expected_result)

    @patch('juloserver.disbursement.services.PaymentGatewayService')
    def test_disburse_grab_success(self, mock_pg_service):
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
            ),
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE', validation_status=NameBankValidationStatus.SUCCESS
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid, name_bank_validation=name_bank_validation
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        pg_disbursement_service = PaymentGatewayDisbursementProcess(disbursement)
        # first one is creating
        # mock callback already called (status updated to active)
        fake_id = fake.numerify(text="#%#%")
        mock_pg_service().disburse.return_value = {
            'status': 'PENDING',
            'reason': 'disbursement created',
            'id': fake_id,
        }
        status = pg_disbursement_service.disburse_grab()
        self.assertTrue(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)
        self.assertEqual(disbursement.reason, 'disbursement created')
        self.assertEqual(disbursement.disburse_id, fake_id)
