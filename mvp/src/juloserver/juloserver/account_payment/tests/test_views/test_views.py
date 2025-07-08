import mock
from django.test import TestCase
from rest_framework.test import APIClient
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    PaymentFactory,
    LoanFactory,
    ApplicationFactory,
    PaymentMethodFactory,
    GlobalPaymentMethodFactory,
    ExperimentSettingFactory,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
    CheckoutRequestFactory,
    PaymentMethodInstructionFactory,
)
from datetime import datetime, timedelta
from juloserver.julo.models import StatusLookup
from juloserver.julo.constants import ExperimentConst
from juloserver.account.models import ExperimentGroup


class TestPaymentMethodRetrieveView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.ptp_date = datetime.today() - timedelta(days=10)
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                                initial_cashback=2000)
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(customer=self.customer,
                                                   virtual_account=self.virtual_account)

    @mock.patch('juloserver.account_payment.views.views_api_v1.aggregate_payment_methods')
    def test_payment_method_retrieve_view(self, mock_aggregate_payment_methods):
        data = {
            'loan_id': self.loan.id,
        }
        expected_response = {'results': True}
        mock_aggregate_payment_methods.return_value = True
        response = self.client.get('/api/account_payment/v1/payment_methods/', data)
        self.assertEqual(response.status_code, 200)
        response = self.client.get('/api/account_payment/v1/payment_methods/', {'loan_xid': 122})
        response = self.client.get('/api/account_payment/v1/payment_methods/', {'loan_id': 523})
        self.loan.account = None
        self.loan.save()
        response = self.client.get('/api/account_payment/v1/payment_methods/', data)


class TestPaymentMethodUpdateView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.ptp_date = datetime.today() - timedelta(days=10)
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                                initial_cashback=2000)
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(customer=self.customer,
                                                   virtual_account=self.virtual_account,
                                                   is_primary=False)

    def test_payment_method_udpate_view(self):
        # payment not found
        response = self.client.put('/api/account_payment/v1/payment_methods/{}/'.format(111111111))
        self.assertEqual(response.status_code, 400)
        # customer is none
        payment_method_primary = PaymentMethodFactory(
            virtual_account=self.virtual_account,
            customer=None
        )
        response = self.client.put('/api/account_payment/v1/payment_methods/{}/'.format(
            payment_method_primary.id
        ))
        self.assertEqual(response.status_code, 400)

        # wrong customer
        customer = CustomerFactory()
        self.payment_method.customer = customer
        self.payment_method.save()
        response = self.client.put('/api/account_payment/v1/payment_methods/{}/'.format(
            self.payment_method.id))
        self.assertEqual(response.status_code, 403)

        # success
        self.payment_method.customer = self.customer
        self.payment_method.save()
        payment_method_primary.customer = self.customer
        payment_method_primary.save()
        response = self.client.put('/api/account_payment/v1/payment_methods/{}/'.format(
            self.payment_method.id))
        self.assertEqual(response.status_code, 200)
        self.payment_method.refresh_from_db()
        payment_method_primary.refresh_from_db()
        self.assertEqual(self.payment_method.is_primary, True)
        self.assertEqual(payment_method_primary.is_primary, False)


class TestPaymentCheckoutView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(id=11, account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(id=10, customer=self.customer,
                                                   virtual_account=self.virtual_account,
                                                   is_primary=False)

    def test_not_found_payment_method(self):
        data = {
            "account_payment_id": [
                11
            ],
            "payment_method_id": 11,
            "redeem_cashback": False
        }
        response = self.client.post('/api/account_payment/v2/payment_checkout', data=data, format='json')
        self.assertEqual(response.status_code, 404)

    def test_not_found_account_payment(self):
        data = {
            "account_payment_id": [
                12
            ],
            "payment_method_id": 10,
            "redeem_cashback": False
        }
        response = self.client.post('/api/account_payment/v2/payment_checkout', data=data, format='json')
        self.assertEqual(response.status_code, 404)

    def test_success(self):
        data = {
            "account_payment_id": [
                11
            ],
            "payment_method_id": 10,
            "redeem_cashback": False
        }
        response = self.client.post('/api/account_payment/v2/payment_checkout', data=data, format='json')
        self.assertEqual(response.status_code, 200)


class TestUpdateCheckoutRequestStatus(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(id=11, account=self.account)
        self.checkout = CheckoutRequestFactory(
            id=1,
            account_id=self.account,
            total_payments=1000
        )

    def test_invalid_request(self):
        data = {
            "checkout_id": "test",
            "status": 11
        }
        response = self.client.post('/api/account_payment/v2/payment_status', data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_checkout_not_found(self):
        data = {
            "checkout_id": 2,
            "status": "cancel"
        }
        response = self.client.post('/api/account_payment/v2/payment_status', data=data, format='json')
        self.assertEqual(response.status_code, 404)


    def test_checkout_forbidden(self):
        self.account.id = 99999
        self.account.save()
        data = {
            "checkout_id": 1,
            "status": "cancel"
        }
        response = self.client.post('/api/account_payment/v2/payment_status', data=data, format='json')
        self.assertEqual(response.status_code, 403)

    def test_invalid_update_status(self):
        data = {
            "checkout_id": 1,
            "status": "finish"
        }
        response = self.client.post('/api/account_payment/v2/payment_status', data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_update_status(self):
        data = {
            "checkout_id": 1,
            "status": "cancel"
        }
        response = self.client.post('/api/account_payment/v2/payment_status', data=data, format='json')
        self.checkout.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.checkout.status, 'canceled')

    def test_in_process(self):
        self.checkout.status = 'redeemed'
        self.checkout.save()
        data = {
            "checkout_id": 1,
            "status": "cancel"
        }
        response = self.client.post('/api/account_payment/v2/payment_status', data=data, format='json')
        self.assertEqual(response.status_code, 400)


class TestUploadCheckoutReceipt(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(id=11, account=self.account)
        self.checkout = CheckoutRequestFactory(
            id=1,
            account_id=self.account,
            total_payments=1000
        )

    def test_invalid_request(self):
        data = {
            "checkout_id": "test",
            "status": 11
        }
        response = self.client.post('/api/account_payment/v2/checkout_receipt', data=data, format='json')
        self.assertEqual(response.status_code, 400)


class TestPaymentMethodInstruction(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.payment_method_name = 'PERMATA Bank'
        self.global_payment_method = GlobalPaymentMethodFactory(
            payment_method_code='013',
            feature_name='Permata',
            payment_method_name=self.payment_method_name
        )
        PaymentMethodInstructionFactory(
            global_payment_method=self.global_payment_method,
            title='atm',
            content='content',
            is_active=True
        )
        PaymentMethodInstructionFactory(
            global_payment_method=self.global_payment_method,
            title='moblie banking',
            content='content',
            is_active=True
        )
        self.url = '/api/account_payment/v1/payment-method-instruction'

    def test_success_payment_method_instruction(self) -> None:
        data = {
            'payment_method_name': self.payment_method_name
        }
        response = self.client.get(self.url, data)
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        expected_result = [
            {
                'payment_method': self.global_payment_method.payment_method_name,
                'payment_instructions': [
                    {
                        'title': 'atm',
                        'content': 'content',
                    },
                    {
                        'title': 'moblie banking',
                        'content': 'content',
                    },
                ]
            }
        ]
        self.assertEqual(expected_result, response['data'])

    def test_payment_method_instruction_fail_when_payment_method_name_wrong(self) -> None:
        data = {
            'payment_method_name': 'adwdqwd'
        }
        response = self.client.get(self.url, data)
        self.assertEqual(response.status_code, 400, response.content)

    def test_payment_method_instruction_fail_when_payment_method_name_null(self) -> None:
        data = {
            'payment_method_name': None
        }
        response = self.client.get(self.url, data)
        self.assertEqual(response.status_code, 400, response.content)


class TestPaymentMethodExperimentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        mobile_phone_1 = '081234567890'
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            mobile_phone_1=mobile_phone_1
        )
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.PAYMENT_METHOD_EXPERIMENT,
            is_active=True,
        )
        self.url = "/api/account_payment/v1/payment-method-experiment"

    def test_payment_method_should_success(self):
        response = self.client.post(self.url, data={"experiment_id": 1})
        self.assertEqual(response.status_code, 200)
        experiment_group = ExperimentGroup.objects.last()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, "control")
        response = self.client.post(self.url, data={"experiment_id": 2})
        self.assertEqual(response.status_code, 200)
        experiment_group = ExperimentGroup.objects.last()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, "experiment")

    def test_payment_method_should_failed_when_experiment_turned_off(self):
        self.experiment_setting.update_safely(is_active=False)
        response = self.client.post(self.url, data={"experiment_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExperimentGroup.objects.exists())

    def test_payment_method_should_not_stored_when_experiment_not_found(self):
        self.experiment_setting.delete()
        response = self.client.post(self.url, data={"experiment_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExperimentGroup.objects.exists())

    def test_payment_method_should_failed_when_experiment_id_invalid(self):
        response = self.client.post(self.url, data={"experiment_id": 3})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ExperimentGroup.objects.exists())
