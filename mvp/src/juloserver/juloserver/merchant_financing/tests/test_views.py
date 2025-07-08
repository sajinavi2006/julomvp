import mock
import copy
from datetime import timedelta
from unittest.mock import MagicMock
from mock.mock import ANY, patch

from rest_framework.test import APIClient, APITestCase
from rest_framework import status
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from juloserver.payment_point.models import TransactionMethod
from juloserver.sdk.models import AxiataCustomerData
from juloserver.julo.models import (
    ProductLine,
    Partner,
    StatusLookup,
)
from juloserver.julo.models import Loan
from juloserver.julocore.python2.utils import py2round
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.merchant_financing.constants import AXIATA_FEE_RATE, LoanDurationUnit
from django.contrib.auth.models import Group
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ProductLookupFactory,
    WorkflowFactory,
    ProductProfileFactory,
    ProductLineFactory,
    ApplicationFactory,
    StatusLookupFactory,
    PartnerFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
    FeatureSettingFactory,
)
from juloserver.partnership.tests.factories import (
    DistributorFactory, MerchantDistributorCategoryFactory, PartnershipTypeFactory,
    MerchantHistoricalTransactionFactory, PartnershipUserOTPActionFactory,
    PartnershipConfigFactory
)
from juloserver.partnership.constants import ErrorMessageConst, PartnershipTypeConstant
from juloserver.julo.constants import WorkflowConst
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.merchant_financing.tests.factories import (
    MerchantFactory, MasterPartnerConfigProductLookupFactory,
    HistoricalPartnerConfigProductLookupFactory
)
from juloserver.partnership.models import CustomerPinVerify, PartnershipConfig

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory

from juloserver.julo.partners import PartnerConstant
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.pin.constants import ResetMessage
from juloserver.account.constants import AccountConstant
from juloserver.merchant_financing.services import get_partner_loan_amount_by_transaction_type


def fake_send_task(task_name, param, **kargs):
    eval(task_name)(*param)


class TestPartnerApplicationView(APITestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_lookup = ProductLookupFactory(
            product_line=ProductLine.objects.get(pk=ProductLineCodes.AXIATA1),
            interest_rate=0.10,
            origination_fee_pct=0.10,
            admin_fee=1000,
            late_fee_pct=AXIATA_FEE_RATE,
        )
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def generate_post_data(self):
        return {
            'partner_application_id': 'partner_app_id',
            'partner_merchant_code': 'merchant_code',
            'owner_name': 'owner name',
            'email': 'email@testing.com',
            'address': 'test address',
            'phone_number': '6281234567890',
            'nik': '1234561212000001',
            'type_of_business': 'test type_of_business',
            'shop_name': 'test shop_name',
            'partner_distributor_id': 1,
            'provision': 10,
            'interest': 10,
            'admin_fee': 1000,
            'loan_amount': 100000,
            'monthly_instalment_amount': 100000,
            'loan_duration': 1,
            'loan_duration_unit': LoanDurationUnit.MONTHLY,
            'date_of_establishment': '2021-09-09',
            'selfie_image': '',
            'ktp_image': '',
            'shop_number': 1,
        }

    def update_to_application_data(self, post_data):
        app_data = copy.deepcopy(post_data)
        app_data['account_number'] = app_data.pop('partner_merchant_code')
        app_data['brand_name'] = app_data.pop('shop_name')
        app_data['ktp'] = app_data.pop('nik')
        app_data['interest_rate'] = app_data.pop('interest')
        app_data['shops_number'] = app_data.pop('shop_number')
        app_data['distributor'] = app_data.pop('partner_distributor_id')
        app_data['origination_fee'] = app_data.pop('provision')
        app_data['fullname'] = app_data.pop('owner_name')
        app_data['address_street_num'] = app_data.pop('address')
        app_data['monthly_installment'] = app_data.pop('monthly_instalment_amount')
        if not app_data['date_of_establishment']:
            app_data.pop('date_of_establishment')
        return app_data

    def test_post_application(self):
        """
        Integration Test
        """
        post_data = self.generate_post_data()
        url = '/merchant_financing/api/application/status'
        response = self.client.post(url, data=post_data, format='json')

        expected_resp_data = {
            'partner_application_id': 'partner_app_id',
            'status': 'Success'
        }

        # Checking expected response
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(expected_resp_data, response.json()['data'])

        axiata_customer_data_obj = AxiataCustomerData.objects \
            .filter(partner_application_id=post_data['partner_application_id']).last()
        self.assertIsNotNone(axiata_customer_data_obj)
        self.assertIsNone(axiata_customer_data_obj.application)
        self.assertEqual(post_data['email'], axiata_customer_data_obj.email)

    @patch('juloserver.merchant_financing.tasks.task_process_partner_application_async.delay')
    def test_post_application_uppercase_email(self, mock_task_process_partner_application_async):
        """
        Integration Test
        """
        expected_email = 'email@testing.com'
        post_data = self.generate_post_data()
        post_data['email'] = 'EmAIL@teSTing.cOM '
        url = '/merchant_financing/api/application/status'
        response = self.client.post(url, data=post_data, format='json')

        expected_resp_data = {
            'partner_application_id': 'partner_app_id',
            'status': 'Success'
        }

        # Checking expected response
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(expected_resp_data, response.json()['data'])

        axiata_customer_data_obj = AxiataCustomerData.objects \
            .filter(partner_application_id=post_data['partner_application_id']).last()
        self.assertIsNotNone(axiata_customer_data_obj)
        self.assertIsNone(axiata_customer_data_obj.application)
        self.assertEqual(expected_email, axiata_customer_data_obj.email)

        expected_application_data = self.update_to_application_data(post_data)
        expected_application_data['email'] = expected_email
        mock_task_process_partner_application_async.assert_called_once_with(
            expected_application_data, ANY)


def register_partner_merchant_financing(client):
    product_line_type = 'MF'
    product_line_code = 300
    ProductLineFactory(
        product_line_type=product_line_type,
        product_line_code=product_line_code
    )
    ProductProfileFactory(
        name=product_line_type,
        code=product_line_code,
    )
    group = Group(name="julo_partners")
    group.save()
    partnership_type = PartnershipTypeFactory(partner_type_name='Merchant financing')

    data_partner = {
        'username': 'partner_merchant_financing',
        'email': 'partnermerchantfinancing@gmail.com',
        'partnership_type': partnership_type.id,
        'cutoff_business_rules_threshold': 0.5
    }
    response = client.post('/api/partnership/v1/merchant-partner',
                           data=data_partner)
    return response


class TestLoanMerchantFinancing(APITestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing(self.client)
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf.json()['data']['secret_key'],
            HTTP_USERNAME=response_register_partner_mf.json()['data']['partner_name'],
        )
        self.partner = Partner.objects.first()
        self.partnership_config = PartnershipConfig.objects.filter(
            partner=self.partner,
            partnership_type__partner_type_name=PartnershipTypeConstant.MERCHANT_FINANCING
        ).last()
        self.partnership_config.is_validation_otp_checking = False
        self.partnership_config.is_loan_amount_adding_mdr_ppn = False
        self.partnership_config.save()
        self.distributor = DistributorFactory(
            partner=self.partner,
            user=self.partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        self.status_lookup = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.merchant_1 = MerchantFactory(
            nik='3203020101910011',
            shop_name='merchant 1',
            distributor=self.distributor,
            merchant_xid=2554367997,
            business_rules_score=0.5
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=2554367666,
        )
        today_date = timezone.localtime(timezone.now()).date()
        MerchantHistoricalTransactionFactory(
            merchant=self.application.merchant,
            type='debit',
            transaction_date=today_date,
            booking_date=today_date,
            payment_method='verified',
            amount=10000,
            term_of_payment=1,
            is_using_lending_facilities=False
        )
        now = timezone.localtime(timezone.now())
        self.customer_pin = CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        user.set_password('159357')
        user.save()
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='Merchant Financing',
            payment_frequency='weekly'
        )
        self.account = AccountFactory(
            customer=customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.save()
        self.application.refresh_from_db()
        self.account_limit = AccountLimitFactory(account=self.account,
                                                 available_limit=4770000)
        self.product_line = ProductLineFactory()
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line,
            interest_rate=0.10,
            origination_fee_pct=0.05,
            late_fee_pct=0.05,
        )
        self.master_partner_config_product_lookup = MasterPartnerConfigProductLookupFactory(
            partner=self.distributor.partner,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.historical_partner_config_product_lookup = HistoricalPartnerConfigProductLookupFactory(
            master_partner_config_product_lookup=self.master_partner_config_product_lookup,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.merchant_1.historical_partner_config_product_lookup = \
            self.historical_partner_config_product_lookup
        self.merchant_1.save()
        today = timezone.localtime(timezone.now()).date()
        self.start_date = today - relativedelta(days=3)
        self.end_date = today + relativedelta(days=50)
        self.start_date1 = today + relativedelta(days=30)
        self.end_date1 = today - relativedelta(days=5)
        self.is_paid_off = True
        self.filter_type = 'due_date'
        self.url_range_loan_amount = '/api/merchant-financing/v1/range-loan-amount'
        self.url_loan_duration = '/api/merchant-financing/v1/loan-duration'

    def test_loan_duration(self):
        res = self.client.get('/api/merchant-financing/v1/loan-duration?application_xid={}&loan_amount_request=3000000'.
                              format(self.application.application_xid))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_loan_duration_with_invalid_account_status(self):
        self.account.status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended)
        self.account.save()
        res = self.client.get('{}?application_xid={}&loan_amount_request=3000000'.
                              format(self.url_loan_duration, self.application.application_xid))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['success'], False)
        self.assertEqual(res.json()['errors'], ['akun belum dapat mengajukan loan'])

    def test_loan_duration_with_empty_account(self):
        self.application.account = None
        self.application.save()
        res = self.client.get('{}?application_xid={}&loan_amount_request=3000000'.
                              format(self.url_loan_duration, self.application.application_xid))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['success'], False)
        self.assertEqual(res.json()['errors'], [ErrorMessageConst.ACCOUNT_NOT_FOUND])

    def test_range_loan_amount_with_empty_account(self):
        self.application.account = None
        self.application.save()
        res = self.client.get('{}?application_xid={}'.
                              format(self.url_range_loan_amount, self.application.application_xid))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['success'], False)
        self.assertEqual(res.json()['errors'], [ErrorMessageConst.ACCOUNT_NOT_FOUND])

    def test_range_loan_amount(self):
        res = self.client.get('/api/merchant-financing/v1/range-loan-amount?application_xid={}'.
                              format(self.application.application_xid))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_range_loan_amount_with_invalid_account_status(self):
        self.account.status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended)
        self.account.save()
        res = self.client.get('{}?application_xid={}'.
                              format(self.url_range_loan_amount, self.application.application_xid))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['success'], False)
        self.assertEqual(res.json()['errors'], ['akun belum dapat mengajukan loan'])

    def test_account_payment(self):
        res = self.client.get('/api/merchant-financing/v1/account-payment?application_xid={}'
                              '&filter_type={}&start_date={}&end_date={}&is_paid_off={}'.
                              format(self.application.application_xid,
                                     self.filter_type,
                                     self.start_date,
                                     self.end_date,
                                     self.is_paid_off))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        res = self.client.get('/api/merchant-financing/v1/account-payment?application_xid={}'
                              '&filter_type={}&start_date={}&end_date={}&is_paid_off={}'.
                              format(self.application.application_xid,
                                     self.filter_type,
                                     self.start_date1,
                                     self.end_date1,
                                     self.is_paid_off))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(res.json()['data'])

    def test_create_loan_need_validation_otp(self) -> None:
        self.partnership_config.is_validation_otp_checking = True
        self.partnership_config.save(update_fields=['is_validation_otp_checking'])

        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="mobile_phone_1_otp",
            is_active=True,
        )
        expiry_time = timezone.now() + timedelta(days=1)
        CustomerPinVerify.objects.create(
            customer=self.application.customer,
            is_pin_used=False,
            customer_pin=self.customer_pin,
            expiry_time=expiry_time
        )
        otp_request = OtpRequestFactory()
        create_loan_data = {
            "loan_amount_request": 1500000,
            "loan_duration_in_days": 3,
            "application_xid": self.application.application_xid
        }

        # failed because user not found otp request
        res = self.client.post('/api/merchant-financing/v1/loan', data=create_loan_data)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['success'], False)
        self.assertEqual(res.json()['errors'], ['harus verifikasi otp terlebih dahulu'])

        otp_request.customer = self.application.customer
        otp_request.is_used = False
        otp_request.save()

        # Failed because user found, but not validation otp
        res = self.client.post('/api/merchant-financing/v1/loan', data=create_loan_data)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['success'], False)
        self.assertEqual(res.json()['errors'], ['harus verifikasi otp terlebih dahulu'])

        # Failed otp_request is valid, but partnership otp_action is already used
        otp_request.customer = self.application.customer
        otp_request.is_used = True
        otp_request.save()

        partnership_user_otp_action = PartnershipUserOTPActionFactory(
            otp_request=otp_request.id, is_used=True
        )
        res = self.client.post('/api/merchant-financing/v1/loan', data=create_loan_data)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['success'], False)
        self.assertEqual(res.json()['errors'], ['harus verifikasi otp terlebih dahulu'])

        otp_request.customer = self.application.customer
        otp_request.is_used = True
        otp_request.save()

        # Success, otp action found and not used
        partnership_user_otp_action.is_used = False
        partnership_user_otp_action.save(update_fields=['is_used'])
        res = self.client.post('/api/merchant-financing/v1/loan', data=create_loan_data)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()['success'], True)

        # partnership_user_otp_action.is_used = True
        # will cannot be used again, must be re-request otp
        partnership_user_otp_action.refresh_from_db()
        self.assertEqual(partnership_user_otp_action.is_used, True)

    def test_create_loan_with_caluclate_mdr_ppn(self) -> None:
        self.partnership_config.is_validation_otp_checking = True
        self.partnership_config.is_loan_amount_adding_mdr_ppn = True
        self.partnership_config.save(
            update_fields=['is_validation_otp_checking', 'is_loan_amount_adding_mdr_ppn']
        )

        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="mobile_phone_1_otp",
            is_active=True,
        )
        expiry_time = timezone.now() + timedelta(days=1)
        CustomerPinVerify.objects.create(
            customer=self.application.customer,
            is_pin_used=False,
            customer_pin=self.customer_pin,
            expiry_time=expiry_time
        )
        otp_request = OtpRequestFactory(customer=self.application.customer,
                                        is_used=True)
        create_loan_data = {
            "loan_amount_request": 1500000,
            "loan_duration_in_days": 3,
            "application_xid": self.application.application_xid
        }

        # Create loan_should be disburse
        loan_amount = create_loan_data['loan_amount_request']

        # there is some formula in get_loan_amount_by_transaction_type using to create loan
        # int(py2round(old_div(loan_amount, (1 - origination_fee_percentage))))
        # int(py2round(old_div(1_500_000, (1 - 0.05))))
        # should be 1_578_947
        get_loan_amount = get_partner_loan_amount_by_transaction_type(
            loan_amount, self.product_lookup.origination_fee_pct, False
        )
        self.assertEqual(get_loan_amount, 1_578_947)

        # if true still using value amount 1_500_000
        get_loan_amount = get_partner_loan_amount_by_transaction_type(
            loan_amount, self.product_lookup.origination_fee_pct, True
        )
        self.assertEqual(get_loan_amount, 1_500_000)

        # adding MDR + ppn in origination fee
        # MDR 0.01(1%) + mdr_ppn = 0.11(11%)
        origination_fee_with_ppn_mdr = (0.05 + 0.01 + 0.11)
        self.product_lookup.origination_fee_pct = origination_fee_with_ppn_mdr
        self.product_lookup.save()
        self.product_lookup.refresh_from_db()

        expected_loan_disbursement_amount = py2round(
            get_loan_amount - (get_loan_amount * self.product_lookup.origination_fee_pct)
        )

        PartnershipUserOTPActionFactory(otp_request=otp_request.id, is_used=False)
        res = self.client.post('/api/merchant-financing/v1/loan', data=create_loan_data)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()['success'], True)

        # provision_fee = (0.05 + 0.01 + 0.11) or equals 17%
        # 1_500_000 - (1_500_000 * (0.05 + 0.01 + 0.11))
        # Expected: 1_245_000
        self.assertEqual(res.json()['data']['disbursement_amount'], 1_245_000)
        self.assertEqual(res.json()['data']['disbursement_amount'], int(expected_loan_disbursement_amount))
        loan = Loan.objects.filter(loan_xid=res.json()['data']['loan_xid']).last()
        partner_loan_request = loan.partnerloanrequest_set.last()

        # Loan original amount stored in PartnerLoanRequest
        self.assertEqual(partner_loan_request.loan_original_amount, create_loan_data['loan_amount_request'])


class TestMerchantApplicationStatus(APITestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)

        product_line_type = 'MF'
        product_line_code = 300
        self.product_line = ProductLineFactory(
            product_line_type=product_line_type,
            product_line_code=product_line_code
        )
        ProductProfileFactory(
            name=product_line_type,
            code=product_line_code,
        )
        group = Group(name="julo_partners")
        group.save()

        self.response_register_partner_mf_1 = self.register_partner(
            self.client, 'partner_merchant_financing_1', 'emailtest1@gmail.com'
        )
        self.response_register_partner_mf_2 = self.register_partner(
            self.client, 'partner_merchant_financing_2', 'emailtest@gmail.com'
        )

        partner = Partner.objects.get(name='partner_merchant_financing_2')
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        self.status_lookup = StatusLookupFactory()
        self.merchant_1 = MerchantFactory(
            nik='3203020101910011',
            shop_name='merchant 1',
            distributor=self.distributor,
            merchant_xid=2554367997,
            business_rules_score=0.5
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=2554367666,
        )
        self.application1 = ApplicationFactory(
            customer=customer,
            workflow=workflow,
            merchant=self.merchant_1,
            application_xid=2554367666,
        )
        today_date = timezone.localtime(timezone.now()).date()
        MerchantHistoricalTransactionFactory(
            merchant=self.application.merchant,
            type='debit',
            transaction_date=today_date,
            booking_date=today_date,
            payment_method='verified',
            amount=10000,
            term_of_payment=1,
            is_using_lending_facilities=False
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='Merchant Financing',
            payment_frequency='weekly'
        )

        self.account = AccountFactory(
            customer=customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.save()
        self.application.refresh_from_db()
        self.account_limit = AccountLimitFactory(account=self.account,
                                                 available_limit=4770000)
        self.product_line = ProductLineFactory()
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line,
            interest_rate=0.10,
            origination_fee_pct=0.30,
            late_fee_pct=0.05,
        )
        self.master_partner_config_product_lookup = MasterPartnerConfigProductLookupFactory(
            partner=self.distributor.partner,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.historical_partner_config_product_lookup = HistoricalPartnerConfigProductLookupFactory(
            master_partner_config_product_lookup=self.master_partner_config_product_lookup,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.customer = customer
        self.user = user
        self.workflow = workflow
        self.partner = partner

    def register_partner(self, client, username, email):
        partnership_type = PartnershipTypeFactory(partner_type_name='Merchant financing')

        data_partner = {
            'username': username,
            'email': email,
            'partnership_type': partnership_type.id,
            'cutoff_business_rules_threshold': 0.5
        }
        response = client.post('/api/partnership/v1/merchant-partner', data=data_partner)
        return response

    def test_wrong_merchant_ownership(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf_1.json()['data']['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf_1.json()['data']['partner_name'],
        )
        res = self.client.get('/api/merchant-financing/v1/merchant/status/{}'.
                              format(self.merchant_1.merchant_xid))
        response_data = res.json()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertListEqual(response_data['errors'], ['Merchant bukan milik partner'])

    def test_get_merchant_application(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf_2.json()['data']['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf_2.json()['data']['partner_name'],
        )
        res = self.client.get('/api/merchant-financing/v1/merchant/status/{}'.
                              format(self.merchant_1.merchant_xid))
        response_data = res.json()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertNotEqual(response_data['data'], [])
        self.assertEqual(response_data['errors'], [])

    def test_get_merchant_loan_agreement_content_failure(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf_2.json()['data']['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf_2.json()['data']['partner_name'],
        )
        self.application1.partner = None
        self.application1.save()
        loan = LoanFactory(account=self.account, customer=self.customer,
                           application=self.application1,
                           loan_amount=10000000, loan_xid=1001020524)
        res = self.client.get('/api/merchant-financing/v1/agreement/content?loan_xid={}'.
                              format(loan.loan_xid))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_merchant_loan_agreement_content_success(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf_2.json()['data']['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf_2.json()['data']['partner_name'],
        )

        self.application2 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            merchant=self.merchant_1,
            partner=self.partner,
            application_xid=2154367666,
            email='testing2_email@gmail.com',
            account=self.account
        )
        loan = LoanFactory(account=self.account, customer=self.customer,
                           loan_amount=10000000, loan_xid=1001020524)
        res = self.client.get('/api/merchant-financing/v1/agreement/content?loan_xid={}'.
                              format(loan.loan_xid))
        self.assertEqual(res.status_code, status.HTTP_200_OK)


class TestAxiataDailyReportView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        PartnerFactory(user=user, name=PartnerConstant.AXIATA_PARTNER)
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)

    @patch('juloserver.merchant_financing.views.get_urls_axiata_report')
    def test_success_response_axiata_daily_report(self, mock_get_urls_axiata_report):
        axiata_repayment_report_url = 'https://www.julo.co.id/product'
        axiata_disbursement_report_url = 'https://www.julo.co.id/'
        mock_get_urls_axiata_report.return_value = {
            'axiata_disbursement_report_url': axiata_disbursement_report_url,
            'axiata_repayment_report_url': axiata_repayment_report_url
        }
        res = self.client.get('/merchant_financing/api/report?report_date=2022-01-01')
        response_data = res.json()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertNotEqual(response_data['data'], [])
        self.assertEqual(response_data['data']['axiata_disbursement_report_url'],
                         axiata_disbursement_report_url)
        self.assertEqual(response_data['data']['axiata_repayment_report_url'],
                         axiata_repayment_report_url)
        self.assertEqual(response_data['errors'], [])

    @patch('juloserver.merchant_financing.views.get_urls_axiata_report')
    def test_failed_response_axiata_daily_report(self, mock_get_urls_axiata_report):
        # invalid report_date
        res = self.client.get('/merchant_financing/api/report?report_date=2022-22-01')
        response_data = res.json()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(ErrorMessageConst.INVALID_DATE, response_data['errors'][0])

        # url not found
        mock_get_urls_axiata_report.return_value = None
        res = self.client.get('/merchant_financing/api/report?report_date=2022-02-01')
        response_data = res.json()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(ErrorMessageConst.NOT_FOUND, response_data['errors'][0])


class TestMFResetPinAPI(APITestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()

    def test_reset_pin_empty_data(self):
        response = self.client_wo_auth.post('/api/merchant-financing/v1/reset-pin', data={})
        assert response.status_code == 400

    def test_reset_pin_invalid_email(self):
        data = {
            "email": "asssdf123345@sdfgmail.cosdfm"
        }
        response = self.client_wo_auth.post('/api/merchant-financing/v1/reset-pin', data=data)
        assert response.status_code == 200
        assert response.json()['data'] == ResetMessage.PIN_RESPONSE

    def test_reset_pin_email_not_found(self):
        data = {
            "email": "asssdf123345@gmail.com"
        }
        response = self.client_wo_auth.post('/api/merchant-financing/v1/reset-pin', data=data)
        assert response.status_code == 200
        assert response.json()['data'] == ResetMessage.PIN_RESPONSE

    @patch.object(JuloEmailClient,
                  'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}])
    def test_reset_pin_by_email(self, mock_email):
        data = {
            "email": "asdf123345@gmail.com"
        }
        response = self.client_wo_auth.post('/api/merchant-financing/v1/reset-pin', data=data)
        assert response.status_code == 200
        assert response.json()['data'] == ResetMessage.PIN_RESPONSE


class TestChangeLoanAgreementStatus(APITestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing(self.client)
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf.json()['data']['secret_key'],
            HTTP_USERNAME=response_register_partner_mf.json()['data']['partner_name'],
        )
        partner = Partner.objects.first()
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        self.status_lookup = StatusLookupFactory()
        self.merchant_1 = MerchantFactory(
            nik='3203020101910011',
            shop_name='merchant 1',
            distributor=self.distributor,
            merchant_xid=2554367997,
            business_rules_score=0.5
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=2554367666,
        )
        today_date = timezone.localtime(timezone.now()).date()
        MerchantHistoricalTransactionFactory(
            merchant=self.application.merchant,
            type='debit',
            transaction_date=today_date,
            booking_date=today_date,
            payment_method='verified',
            amount=10000,
            term_of_payment=1,
            is_using_lending_facilities=False
        )
        now = timezone.localtime(timezone.now())
        self.customer_pin = CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        user.set_password('159357')
        user.save()
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='Merchant Financing',
            payment_frequency='weekly'
        )

        self.account = AccountFactory(
            customer=customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.save()
        self.application.refresh_from_db()
        self.account_limit = AccountLimitFactory(account=self.account,
                                                 available_limit=4770000)
        self.product_line = ProductLineFactory()
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line,
            interest_rate=0.10,
            origination_fee_pct=0.30,
            late_fee_pct=0.05,
        )
        self.master_partner_config_product_lookup = MasterPartnerConfigProductLookupFactory(
            partner=self.distributor.partner,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.historical_partner_config_product_lookup = HistoricalPartnerConfigProductLookupFactory(
            master_partner_config_product_lookup=self.master_partner_config_product_lookup,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.merchant_1.historical_partner_config_product_lookup = \
            self.historical_partner_config_product_lookup
        self.merchant_1.save()
        self.loan = LoanFactory(
            account=self.account,
            customer=customer,
            application=self.application,
            loan_amount=10000000,
            loan_xid=1987131908,
            transaction_method=TransactionMethod.objects.get(id=1),
        )

        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=210, status_next=211, workflow=self.workflow)
        self.feature_setting = FeatureSettingFactory(
            feature_name='swift_limit_drainer',
            parameters={'jail_days': 0},
            is_active=False,
        )

    def test_change_aggrement_status_loan_not_found(self) -> None:
        data = {
            "status": "approve",
            "loan_xid": 3190408253
        }
        response = self.client.post('/api/merchant-financing/v1/loan/agreement', data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Loan tidak ditemukan'])

    def test_test_change_aggrement_status_loan_xid_required(self) -> None:
        data = {
            "status": "approve",
        }
        response = self.client.post('/api/merchant-financing/v1/loan/agreement', data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Loan_xid tidak boleh kosong'])

    def test_change_aggrement_status_loan_not_inactive(self) -> None:
        data = {
            "status": "approve",
            "loan_xid": self.loan.loan_xid
        }
        response = self.client.post('/api/merchant-financing/v1/loan/agreement', data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Loan tidak ditemukan'])

    @patch('juloserver.loan.views.views_api_v1.accept_julo_sphp')
    def test_change_aggrement_status_loan_success(self, _: MagicMock) -> None:
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.save()
        data = {
            "status": "approve",
            "loan_xid": self.loan.loan_xid
        }
        response = self.client.post('/api/merchant-financing/v1/loan/agreement', data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.json()['data']['status'], 'LOAN_WAITING_FOR_APPROVAL')
        self.assertEqual(response.json()['data']['loan_xid'], self.loan.loan_xid)
