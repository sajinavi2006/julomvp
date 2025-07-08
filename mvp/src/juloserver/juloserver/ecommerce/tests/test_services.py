import uuid
from importlib import import_module
from unittest.mock import patch
from mock import mock

import requests
from cuser.middleware import CuserMiddleware
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase

from juloserver.account.constants import TransactionType
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.cfs.tests.factories import CfsActionPointsFactory
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.ecommerce.clients.juloshop import JuloShopClient
from juloserver.ecommerce.constants import (
    EcommerceConstant,
    CategoryType,
    IpriceTransactionStatus,
    JuloShopTransactionStatus
)
from juloserver.ecommerce.models import (
    IpriceStatusHistory,
    IpriceTransaction,
    JuloShopStatusHistory,
)
from juloserver.ecommerce.services import (
    _get_iprice_client,
    PACKAGE_NAME,
    _reset_iprice_client,
    send_invoice_callback,
    update_iprice_transaction_loan,
    update_iprice_transaction_status,
    update_iprice_transaction_by_loan,
    create_iprice_transaction,
    get_iprice_bank_destination,
    get_iprice_transaction,
    prepare_ecommerce_data,
    check_account_limit,
)
from juloserver.ecommerce.tests.factories import (
    IpriceTransactionFactory,
    EcommerceConfigurationFactory,
    EcommerceBankConfigurationFactory, JuloShopTransactionFactory
)
from juloserver.followthemoney.factories import LenderCurrentFactory, LenderBalanceCurrentFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    LoanFactory,
    CustomerFactory,
    StatusLookupFactory,
    AuthUserFactory,
    ApplicationFactory,
    BankFactory,
    ProductLineFactory,
    ApplicationJ1Factory,
    AccountingCutOffDateFactory,
    WorkflowFactory,
)
from juloserver.loan.tasks import julo_one_disbursement_trigger_task
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo.constants import WorkflowConst
from product_profile.tests.test_product_profile_services import ProductProfileFactory


class TestEcommerceService(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.base_url = settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        self.iprice_url = 'https://julo-id.iprice.mx/'
        self.iprice = EcommerceConfigurationFactory(
            id=1,
            ecommerce_name=EcommerceConstant.IPRICE,
            selection_logo=f'{self.base_url}/iprice_logo',
            background_logo=f'{self.base_url}/iprice_background_logo',
            text_logo=f'{self.base_url}/iprice_text_logo',
            color_scheme='#00FF10',
            url=self.iprice_url,
            is_active=True,
            category_type=CategoryType.MARKET,
        )

        self.shoppe = EcommerceConfigurationFactory(
            id=2,
            ecommerce_name=EcommerceConstant.SHOPEE,
            selection_logo=f'{self.base_url}/shoppe_selection_logo',
            background_logo=f'{self.base_url}/shoppe_background_logo',
            text_logo=f'{self.base_url}/shoppe_text_logo',
            color_scheme='#00FF11',
            url='https://shoppe.com',
            is_active=True,
            category_type=CategoryType.ECOMMERCE,
        )

    def test_prepare_ecommerce_data(self):
        category_data, marketplace_data = prepare_ecommerce_data(self.customer)
        self.assertEqual(category_data[0], self.shoppe)
        self.assertEqual(marketplace_data[0], self.iprice)

        self.assertEqual(
            marketplace_data[0].url,
            "{}?partner_user_id={}".format(self.iprice_url, self.application.application_xid)
        )

        ## case url has params
        self.iprice_url = 'https://julo-id.iprice.mx/?a=123'
        self.iprice.url = self.iprice_url
        self.iprice.save()
        category_data, marketplace_data = prepare_ecommerce_data(self.customer)
        self.assertEqual(
            marketplace_data[0].url,
            "{}&partner_user_id={}".format(self.iprice_url, self.application.application_xid)
        )

    def test_get_ecommerce_case_not_active(self):
        # no martket place item is active
        self.iprice.is_active = False
        self.iprice.save()

        # no category AND market place item is active
        self.shoppe.is_active = False
        self.shoppe.save()

        category_data, marketplace_data = prepare_ecommerce_data(self.customer)
        self.assertEqual(len(category_data), 0)
        self.assertEqual(len(marketplace_data), 0)


class TestGetIpriceClient(SimpleTestCase):
    def setUp(self):
        _reset_iprice_client()

    def tearDown(self):
        _reset_iprice_client()

    def test_init_iprice_client(self):
        settings = {
            'IPRICE_BASE_URL': 'http://iprice.com',
            'IPRICE_PID': '1234567890'
        }
        with self.settings(**settings):
            iprice_client = _get_iprice_client()

        self.assertEqual('http://iprice.com', iprice_client.base_url)
        self.assertEqual('1234567890', iprice_client.pid)

    @patch('{}.IpriceClient'.format(PACKAGE_NAME))
    def test_singleton(self, mock_init_client):
        mock_init_client.return_value = 'iprice_client'
        _reset_iprice_client()

        _get_iprice_client()
        iprice_client = _get_iprice_client()

        self.assertEqual('iprice_client', iprice_client)
        mock_init_client.assert_called_once()


@patch('{}.logger'.format(PACKAGE_NAME))
@patch('{}._get_iprice_client'.format(PACKAGE_NAME))
class TestSendInvoiceCallback(TestCase):
    def setUp(self):
        self.iprice_transaction_xid = uuid.uuid4()
        self.application = ApplicationFactory(application_xid=1234567890)
        self.loan = LoanFactory(loan_xid=1234567891)
        self.iprice_transaction = IpriceTransactionFactory(
            loan=self.loan,
            application=self.application,
            iprice_order_id='1234567892',
            current_status=IpriceTransactionStatus.PROCESSING,
            iprice_transaction_xid=self.iprice_transaction_xid,
        )
        self.valid_request_body = {
            'iprice_order_id': "1234567892",
            'application_id': self.application.application_xid,
            'loan_id': self.loan.loan_xid,
            'transaction_status': "processing"
        }

    def test_true_with_confirmation_ok(self, mock_get_iprice_client, mock_logger):
        mock_get_iprice_client.return_value.post_invoice_callback.return_value = {
            'confirmation_status': 'OK'
        }

        ret_val = send_invoice_callback(self.iprice_transaction)

        self.assertTrue(ret_val)
        mock_logger.warning.assert_not_called()
        mock_get_iprice_client.return_value.post_invoice_callback.assert_called_once_with(
            data=self.valid_request_body
        )

    def test_false_with_confirmation_not_ok(self, mock_get_iprice_client, mock_logger):
        mock_get_iprice_client.return_value.post_invoice_callback.return_value = {
            'confirmation_status': 'Not OK'
        }

        ret_val = send_invoice_callback(self.iprice_transaction)

        self.assertFalse(ret_val)
        mock_logger.warning.assert_called_once_with({
            'action': '{}.send_invoice_callback'.format(PACKAGE_NAME),
            'message': 'iPrice invoice callback status is not OK',
            'data': self.valid_request_body,
            'response_data': {
                'confirmation_status': 'Not OK'
            },
        })

    def test_no_loan(self, mock_get_iprice_client, mock_logger):
        iprice_transaction = IpriceTransactionFactory(
            application=self.application,
            iprice_order_id='1234567892',
            current_status=IpriceTransactionStatus.LOAN_REJECTED,
            iprice_transaction_xid=uuid.uuid4(),
        )
        expected_request_body = {
            'iprice_order_id': "1234567892",
            'application_id': self.application.application_xid,
            'loan_id': None,
            'transaction_status': "loan_rejected"
        }
        mock_get_iprice_client.return_value.post_invoice_callback.return_value = {
            'confirmation_status': 'OK'
        }

        ret_val = send_invoice_callback(iprice_transaction)

        self.assertTrue(ret_val)
        mock_logger.warning.assert_not_called()
        mock_get_iprice_client.return_value.post_invoice_callback.assert_called_once_with(
            data=expected_request_body
        )


class TestUpdateIpriceTransactionLoan(TestCase):
    def test_update_loan_data(self):
        customer = CustomerFactory()
        loan = LoanFactory(
            customer=customer,
            loan_amount=12000,
            loan_disbursement_amount=10000,
        )
        iprice_transaction = IpriceTransactionFactory(
            loan=None, customer=customer, current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=10000
        )

        with self.assertNumQueries(3):
            ret_val = update_iprice_transaction_loan(iprice_transaction.id, loan)

            self.assertEqual(loan.id, ret_val.loan_id)
            self.assertEqual(2000, ret_val.admin_fee)
            self.assertEqual(12000, ret_val.transaction_total_amount)

    def test_loan_different_customer(self):
        loan = LoanFactory(
            customer=CustomerFactory(),
            loan_amount=12000,
            loan_disbursement_amount=10000,
        )
        iprice_transaction = IpriceTransactionFactory(
            loan=None, customer=CustomerFactory(), current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=10000
        )

        with self.assertRaises(IpriceTransaction.DoesNotExist):
            update_iprice_transaction_loan(iprice_transaction.id, loan)

    def test_has_loan(self):
        customer = CustomerFactory()
        loan = LoanFactory(
            customer=customer,
            loan_amount=12000,
            loan_disbursement_amount=10000,
        )
        iprice_transaction = IpriceTransactionFactory(
            loan=LoanFactory(), customer=customer, current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=10000
        )

        ret_val = update_iprice_transaction_loan(iprice_transaction.id, loan)

        self.assertEqual(loan.id, ret_val.loan_id)
        self.assertEqual(2000, ret_val.admin_fee)
        self.assertEqual(12000, ret_val.transaction_total_amount)

    def test_not_draft(self):
        loan = LoanFactory(
            customer=CustomerFactory(),
            loan_amount=12000,
            loan_disbursement_amount=10000,
        )
        iprice_transaction = IpriceTransactionFactory(
            loan=None, customer=CustomerFactory(), iprice_total_amount=10000,
            current_status=IpriceTransactionStatus.PROCESSING)

        with self.assertRaises(IpriceTransaction.DoesNotExist):
            update_iprice_transaction_loan(iprice_transaction.id, loan)

    def test_invalid_loan_disburse(self):
        loan = LoanFactory(
            customer=CustomerFactory(),
            loan_amount=12000,
            loan_disbursement_amount=10000,
        )
        iprice_transaction = IpriceTransactionFactory(
            loan=None, customer=CustomerFactory(), iprice_total_amount=12000,
            current_status=IpriceTransactionStatus.PROCESSING)

        with self.assertRaises(Exception):
            update_iprice_transaction_loan(iprice_transaction.id, loan)

@patch('{}.send_invoice_callback'.format(PACKAGE_NAME))
class TestUpdateIpriceTransactionStatus(TestCase):
    def tearDown(self):
        CuserMiddleware.del_user()

    def test_status_changed(self, mock_send_invoice_callback):
        iprice_transaction = IpriceTransactionFactory(current_status=IpriceTransactionStatus.DRAFT)

        # 2x for db transaction
        # 1x for get iprice_transaction
        # 2x for update_safely
        # 1x for create IpriceStatusHistory
        with self.assertNumQueries(6):
            update_iprice_transaction_status(iprice_transaction.id, IpriceTransactionStatus.PROCESSING, 'test reason')

        iprice_transaction.refresh_from_db()

        iprice_status_history = IpriceStatusHistory.objects.filter(
            iprice_transaction_id=iprice_transaction.id,
            status_old=IpriceTransactionStatus.DRAFT,
            status_new=IpriceTransactionStatus.PROCESSING,
            change_reason='test reason',
            changed_by__isnull=True,
        ).first()
        self.assertIsNotNone(iprice_status_history)

        mock_send_invoice_callback.assert_called_once_with(iprice_transaction)

    @patch('{}.logger'.format(PACKAGE_NAME))
    def test_status_not_changed(self, mock_logger, mock_send_invoice_callback):
        iprice_transaction = IpriceTransactionFactory(current_status=IpriceTransactionStatus.DRAFT)

        # 1x for get iprice_transaction
        with self.assertNumQueries(1):
            update_iprice_transaction_status(iprice_transaction.id, IpriceTransactionStatus.DRAFT, 'test reason')

        iprice_transaction.refresh_from_db()
        self.assertEqual(IpriceTransactionStatus.DRAFT, iprice_transaction.current_status)

        iprice_status_history = IpriceStatusHistory.objects.filter(
            iprice_transaction_id=iprice_transaction.id,
            change_reason='test reason',
            changed_by__isnull=True,
        ).first()
        self.assertIsNone(iprice_status_history)

        mock_logger.info.assert_called_once_with({
            'action': '{}.update_iprice_transaction_status'.format(PACKAGE_NAME),
            'message': 'iPrice transaction status is already {}'.format(IpriceTransactionStatus.DRAFT),
            'old_status': IpriceTransactionStatus.DRAFT,
            'new_status': IpriceTransactionStatus.DRAFT,
            'iprice_transaction': iprice_transaction,
            'change_reason': 'test reason',
        })
        mock_send_invoice_callback.assert_not_called()

    def test_status_changed_by_user(self, _mock_send_invoice_callback):
        user = AuthUserFactory()
        iprice_transaction = IpriceTransactionFactory(current_status=IpriceTransactionStatus.DRAFT)
        CuserMiddleware.set_user(user)

        update_iprice_transaction_status(iprice_transaction.id,
                                         IpriceTransactionStatus.PROCESSING, 'test reason')

        iprice_transaction.refresh_from_db()
        iprice_status_history = IpriceStatusHistory.objects.filter(
            iprice_transaction_id=iprice_transaction.id,
            status_old=IpriceTransactionStatus.DRAFT,
            status_new=IpriceTransactionStatus.PROCESSING,
            change_reason='test reason',
            changed_by_id=user.id,
        ).first()
        self.assertIsNotNone(iprice_status_history)

    def test_status_changed_by_anonymous_user(self, _mock_send_invoice_callback):
        iprice_transaction = IpriceTransactionFactory(current_status=IpriceTransactionStatus.DRAFT)
        CuserMiddleware.set_user(AnonymousUser())

        update_iprice_transaction_status(iprice_transaction.id,
                                         IpriceTransactionStatus.PROCESSING, 'test reason')

        iprice_transaction.refresh_from_db()
        iprice_status_history = IpriceStatusHistory.objects.filter(
            iprice_transaction_id=iprice_transaction.id,
            status_old=IpriceTransactionStatus.DRAFT,
            status_new=IpriceTransactionStatus.PROCESSING,
            change_reason='test reason',
            changed_by__isnull=True,
        ).first()
        self.assertIsNotNone(iprice_status_history)


@patch('{}.update_iprice_transaction_status'.format(PACKAGE_NAME))
class TestUpdateIpriceTransactionByLoan(TestCase):
    def test_iprice_transaction_not_exist(self, mock_update_iprice_transaction_status):
        loan = LoanFactory(loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE))

        update_iprice_transaction_by_loan(loan, LoanStatusCodes.CURRENT, 'test reason')

        mock_update_iprice_transaction_status.assert_not_called()

    def test_current_loan_is_220(self, mock_update_iprice_transaction_status):
        loan = LoanFactory(loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT))
        IpriceTransactionFactory(loan=loan)

        update_iprice_transaction_by_loan(loan, LoanStatusCodes.LOAN_1DPD, 'test reason')

        mock_update_iprice_transaction_status.assert_not_called()

    def test_update_with_valid_loan_status(self, mock_update_iprice_transaction_status):
        loan = LoanFactory(loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE))
        iprice_transaction = IpriceTransactionFactory(loan=loan, current_status=IpriceTransactionStatus.DRAFT)

        # 1x for get iprice_transaction by loan
        with self.assertNumQueries(1):
            update_iprice_transaction_by_loan(loan, LoanStatusCodes.CURRENT, 'test reason')

        mock_update_iprice_transaction_status.assert_called_once_with(
            iprice_transaction.id,
            IpriceTransactionStatus.LOAN_APPROVED,
            'test reason',
        )


class TestIpriceServices(TestCase):
    RETROLOAD_PACKAGE_NAME = 'juloserver.retroloads.164024289081__ecommerce__add_new_partner_iprice'
    retroload = import_module(
        name='.164024289081__ecommerce__add_new_partner_iprice',
        package='juloserver.retroloads',
    )

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer, application_xid=123123123)

        # run retroload function to add iprice
        Group.objects.create(name='julo_partners')
        BankAccountCategoryFactory(
            category=BankAccountCategoryConst.ECOMMERCE,
            parent_category_id=1,
        )

        with patch('{}.ValidationProcess'.format(self.RETROLOAD_PACKAGE_NAME)) as mock_process:
            mock_process_obj = mock_process.return_value
            self.retroload.add_new_partner_iprice(None, None)
            mock_process_obj.validate.assert_called_once()

    def test_create_iprice_transaction(self):
        iprice_data = {
            "partnerUserId": self.application.application_xid,
            "paymentType": "JULO_LOAN_FINANCING",
            "externalId": "b113650m",
            "grandAmount": 1620000,
            "address": "tmn melati, tmn melati, , tmn melati",
            "province": "Kepulauan Bangka Belitung",
            "city": "Pangkal Pinang",
            "email": "salam.abdoul4543453@gmail.com",
            "firstName": "Abdoul",
            "lastName": "Salam",
            "mobile": "0801234567891",
            "postcode": "53100",
            "items": [
                {
                    "id": "AJ0-70000-00001",
                    "url": "https://dev-julo-id.iprice.mx/r/pc/?_id=13321637ac8359824108378cd011ef5a1bbd898e",
                    "imageUrl": "https://p.ipricegroup.com/13321637ac8359824108378cd011ef5a1bbd898e_0.jpg",
                    "name": "Vivo Y12 Ram 3 32 Gb New Y12 Garansi Resmi Merah",
                    "price": 1600000,
                    "quantity": 1,
                    "category": "ponsel-tablet",
                    "brandName": "Vivo",
                    "merchantName": "Tokopedia"
                }
            ],
            "successRedirectUrl": "https://dev-julo-id.iprice.mx/checkout/success/",
            "failRedirectUrl": "https://dev-julo-id.iprice.mx/checkout/fail/"
        }
        transaction = create_iprice_transaction(iprice_data)
        iprice_status_history = IpriceStatusHistory.objects.filter(
            iprice_transaction=transaction,
            status_new=IpriceTransactionStatus.DRAFT,
        ).first()

        expected_checkout_info = {
            "partnerUserId": iprice_data['partnerUserId'],
            "paymentType": iprice_data['paymentType'],
            "address": iprice_data['address'],
            "province": iprice_data['province'],
            "city": iprice_data['city'],
            "email": iprice_data['email'],
            "firstName": iprice_data['firstName'],
            "lastName": iprice_data['lastName'],
            "mobile": iprice_data['mobile'],
            "postcode": iprice_data['postcode'],
            "items": iprice_data['items'],
        }
        self.assertIsNotNone(iprice_status_history)
        self.assertEqual(transaction.customer, self.customer)
        self.assertEqual(transaction.current_status, IpriceTransactionStatus.DRAFT)
        self.assertEqual(transaction.application, self.application)
        self.assertEqual(transaction.iprice_total_amount, iprice_data['grandAmount'])
        self.assertEqual(transaction.checkout_info, expected_checkout_info)
        self.assertEqual(transaction.iprice_order_id, iprice_data['externalId'])
        self.assertEqual(transaction.fail_redirect_url, iprice_data['failRedirectUrl'])
        self.assertEqual(transaction.success_redirect_url, iprice_data['successRedirectUrl'])

    def test_get_iprice_transaction(self):
        transaction = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
        )
        t1 = get_iprice_transaction(self.customer, transaction.iprice_transaction_xid, use_xid=True)
        self.assertIsNotNone(t1)

        t2 = get_iprice_transaction(self.customer, transaction.id, use_xid=False)
        self.assertIsNotNone(t2)

        t3 = get_iprice_transaction(self.customer, transaction.iprice_transaction_xid, use_xid=False)
        self.assertIsNone(t3)

        new_user_auth = AuthUserFactory()
        new_customer = CustomerFactory(user=new_user_auth)
        t4 = get_iprice_transaction(new_customer, transaction.id, use_xid=False)
        self.assertIsNone(t4)

        self.assertRaises(ValueError, get_iprice_transaction, self.customer, "9238ur", use_xid=True)

    def test_get_iprice_bank_destination(self):
        bank_des = get_iprice_bank_destination()
        self.assertIsNotNone(bank_des)


@patch(f'{PACKAGE_NAME}.update_iprice_transaction_status')
@patch(f'{PACKAGE_NAME}.calculate_loan_amount')
@patch(f'{PACKAGE_NAME}.is_account_limit_sufficient')
class TestCheckAccountLimit(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.application = ApplicationFactory(account=self.account)

    def test_check_account_limit(
        self, mock_is_account_limit_sufficient, mock_calculate_loan_amount,
        mock_update_iprice_transaction_status,
    ):
        iprice_transaction = IpriceTransactionFactory(
            iprice_total_amount=10000, application=self.application
        )
        mock_is_account_limit_sufficient.return_value = True
        mock_calculate_loan_amount.return_value = 110000, None, None

        ret_val = check_account_limit(iprice_transaction)

        self.assertTrue(ret_val)
        mock_update_iprice_transaction_status.assert_not_called()
        mock_calculate_loan_amount.assert_called_once_with(
            application=self.application,
            loan_amount_requested=10000,
            transaction_type=TransactionType.ECOMMERCE
        )
        mock_is_account_limit_sufficient.assert_called_once_with(110000, self.account.id)

    def test_check_account_limit_insufficient(
        self, mock_is_account_limit_sufficient, mock_calculate_loan_amount,
        mock_update_iprice_transaction_status,
    ):
        iprice_transaction = IpriceTransactionFactory(
            iprice_total_amount=10000, application=self.application
        )
        mock_is_account_limit_sufficient.return_value = False
        mock_calculate_loan_amount.return_value = 110000, None, None

        ret_val = check_account_limit(iprice_transaction)

        self.assertFalse(ret_val)
        mock_update_iprice_transaction_status.assert_called_once_with(
            iprice_transaction,
            IpriceTransactionStatus.LOAN_REJECTED,
            change_reason="Insufficient credit limit"
        )
        mock_calculate_loan_amount.assert_called_once_with(
            application=self.application,
            loan_amount_requested=10000,
            transaction_type=TransactionType.ECOMMERCE
        )
        mock_is_account_limit_sufficient.assert_called_once_with(110000, self.account.id)


class TestEcommerceBankConfiguration(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.bank = BankFactory(
            bank_code='012',
            bank_name='BCA',
            xendit_bank_code='BCA',
            swift_bank_code='01'
        )
        self.ecommerce_configuration = EcommerceConfigurationFactory()
        self.ecommerce_bank_configuration = EcommerceBankConfigurationFactory(
            id=200,
            bank=self.bank,
            ecommerce_configuration=self.ecommerce_configuration,
            prefix=[233211],
            is_active = True,
        )

    def test_TestEcommerceBankConfiguration(self):
        self.ecommerce_bank_configuration.is_active = False
        self.ecommerce_bank_configuration.save()


class TestDisbursementEcommerce(TestCase):
    def setUp(self):
        self.j1_product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
            product_profile=ProductProfileFactory()
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='SUCCESS',
            mobile_phone='08674734',
            attempt=0,
        )
        self.application = ApplicationJ1Factory(
            account=self.account, customer=self.customer,
            name_bank_validation=name_bank_validation
        )
        self.lender = LenderCurrentFactory(lender_name='test-lender')
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
            transaction_method_id=TransactionMethodCode.E_COMMERCE.code,
            lender=self.lender
        )
        self.lender_balance_current = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=self.loan.loan_amount
        )
        bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        bank = BankFactory(
            bank_code='012', bank_name='BCA', xendit_bank_code='BCA', swift_bank_code='01'
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        self.loan.name_bank_validation_id = name_bank_validation.id
        self.loan.transaction_method_id = TransactionMethodCode.E_COMMERCE.code
        self.loan.bank_account_destination = bank_account_destination
        self.loan.save()
        self.juloshop_transaction = JuloShopTransactionFactory(
            loan=self.loan, application=self.application, customer=self.customer,
            status=JuloShopTransactionStatus.DRAFT
        )
        for i in range(1, 11):
            CfsActionPointsFactory(id=i, multiplier=0.001, floor=5, ceiling=25, default_expiry=180)
        AccountingCutOffDateFactory()
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=211, status_next=212, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=215, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=220, workflow=self.workflow)

    @patch('juloserver.ecommerce.juloshop_service.get_juloshop_client')
    @patch('juloserver.loan.services.lender_related.julo_one_loan_disbursement_failed')
    def test_julo_one_disbursement_trigger_task_success(self,
                                                        mock_julo_one_loan_disbursement_failed,
                                                        mock_juloshop_client):
        mock_juloshop_client.return_value.sent_order_confirmation.return_value = True, None
        julo_one_disbursement_trigger_task(self.loan.id)
        mock_julo_one_loan_disbursement_failed.assert_not_called()
        self.juloshop_transaction.refresh_from_db()
        self.assertEqual(self.juloshop_transaction.status, JuloShopTransactionStatus.SUCCESS)

        history = JuloShopStatusHistory.objects.filter(transaction=self.juloshop_transaction).last()
        self.assertEqual(history.status_old, JuloShopTransactionStatus.PROCESSING)
        self.assertEqual(history.status_new, JuloShopTransactionStatus.SUCCESS)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 220)

    @patch('juloserver.ecommerce.juloshop_service.get_juloshop_client')
    @patch('juloserver.loan.services.lender_related.julo_one_loan_disbursement_success')
    @patch('juloserver.loan.services.lender_related.return_lender_balance_amount')
    def test_julo_one_disbursement_trigger_task_failed(self,
                                                       mock_return_lender_balance_amount,
                                                       mock_julo_one_loan_disbursement_success,
                                                       mock_juloshop_client):
        mock_juloshop_client.return_value.sent_order_confirmation.return_value = \
            False, ['order can not create']
        julo_one_disbursement_trigger_task(self.loan.id)
        mock_julo_one_loan_disbursement_success.assert_not_called()
        mock_return_lender_balance_amount.assert_called()
        self.juloshop_transaction.refresh_from_db()
        self.assertEqual(self.juloshop_transaction.status, JuloShopTransactionStatus.FAILED)
        history = JuloShopStatusHistory.objects.filter(transaction=self.juloshop_transaction).last()
        self.assertEqual(history.status_old, JuloShopTransactionStatus.PROCESSING)
        self.assertEqual(history.status_new, JuloShopTransactionStatus.FAILED)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 215)

    @patch('juloserver.ecommerce.juloshop_service.get_juloshop_client')
    @patch('juloserver.loan.services.lender_related.return_lender_balance_amount')
    @patch('juloserver.ecommerce.clients.juloshop.requests.post')
    def test_julo_one_disbursement_trigger_task_exception(self,
                                                          mock_requests,
                                                          mock_return_lender_balance_amount,
                                                          mock_juloshop_client
                                                          ):
        mock_response = mock.Mock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError
        mock_requests.return_value = mock_response
        mock_juloshop_client.return_value = JuloShopClient(
            base_url='http://localhost.vospay/api', juloshop_token='secret_key'
        )
        julo_one_disbursement_trigger_task(self.loan.id)
        mock_return_lender_balance_amount.assert_called()
        self.juloshop_transaction.refresh_from_db()
        self.assertEqual(self.juloshop_transaction.status, JuloShopTransactionStatus.FAILED)
        history = JuloShopStatusHistory.objects.filter(transaction=self.juloshop_transaction).last()
        self.assertEqual(history.status_old, JuloShopTransactionStatus.PROCESSING)
        self.assertEqual(history.status_new, JuloShopTransactionStatus.FAILED)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 215)


class TestLoanJuloShop(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(account=self.account, customer=self.customer)
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            transaction_method_id=TransactionMethodCode.E_COMMERCE.code,
        )
        self.juloshop_transaction = JuloShopTransactionFactory(
            loan=self.loan, application=self.application, customer=self.customer,
            status=JuloShopTransactionStatus.DRAFT
        )
        AccountingCutOffDateFactory()

    def test_transaction_detail_show_on_crm(self):
        self.assertEqual(self.loan.fund_id, self.juloshop_transaction.transaction_xid)
        self.assertEqual(self.loan.transaction_detail, 'juloshop, jd.id')
