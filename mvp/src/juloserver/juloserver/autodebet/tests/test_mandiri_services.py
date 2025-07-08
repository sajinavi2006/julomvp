from django.utils import timezone
import pytest
from mock import patch
from django.test.testcases import (
    TestCase,
    override_settings,
)
from django.db.models import signals
from django.db.models import Sum
import factory
from datetime import date, timedelta

from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    FeatureSettingFactory
)
from juloserver.account.tests.factories import AccountFactory

from juloserver.autodebet.services.mandiri_services import (
    mandiri_autodebet_deactivation,
    is_mandiri_request_otp_success,
    is_mandiri_verify_otp_success,
    process_mandiri_activation, check_mandiri_callback_activation,
)
from juloserver.autodebet.tests.factories import (
    AutodebetMandiriAccountFactory,
    AutodebetAccountFactory,
    AutodebetAPILogFactory,
    AutodebetMandiriTransactionFactory,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.autodebet.models import AutodebetMandiriTransaction, AutodebetMandiriAccount
from juloserver.autodebet.tasks import collect_mandiri_autodebet_account_maximum_limit_collections_task
from juloserver.autodebet.services.task_services import (
    create_debit_payment_process_mandiri,
    create_debit_payment_process_mandiriv2,
    check_and_create_debit_payment_process_after_callback_mandiriv2,
)
from rest_framework.test import APIClient
from juloserver.autodebet.constants import AutodebetMandiriPaymentResultStatusConst


class TestDeactivation(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory(customer_xid=843757867)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(account=self.account, customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, vendor="MANDIRI"
        )

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.registration_card_unbind')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_revocation_mandiri_autodebet(self, mock_access_token, mock_registration_unbind_card):
        self.autodebet_mandiri_account = AutodebetMandiriAccountFactory()
        self.autodebet_mandiri_account.autodebet_account = self.autodebet_account
        self.autodebet_mandiri_account.save()
        mock_registration_unbind_card.return_value = ({
                "responseCode": "2000500",
                "responseMessage": "Request has been processed successfully",
                "referenceNo": "908718002198"
        }, None)
        current_ts = timezone.localtime(timezone.now())
        self.autodebet_account.is_use_autodebet = True
        self.autodebet_account.vendor = 'MANDIRI'
        self.autodebet_account.status = 'registered'
        self.autodebet_account.activation_ts = current_ts
        self.autodebet_account.save()

        message, status = mandiri_autodebet_deactivation(self.account)
        self.assertEqual(message, 'Nonaktifkan Autodebet Mandiri berhasil')


class TestAutodebetMandiriPurchaseSubmit(TestCase):
    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def setUp(self):
        self.customer = CustomerFactory(customer_xid='56338192560570')
        self.account = AccountFactory(customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True, vendor='MANDIRI'
        )
        self.autodebet_mandiri_account = AutodebetMandiriAccountFactory()
        self.max_limit_settings = FeatureSettingFactory(
            feature_name = 'autodebet_mandiri_max_limit_deduction_day',
            parameters = {
                'maximum_amount': 5000000,
            }
        )
        FeatureSettingFactory(
            feature_name = 'autodebet_mandiri',
            is_active = True
        )

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    @pytest.mark.skip(reason="Flaky")
    def test_create_debit_payment_process_mandiri(
        self, mock_access_token, mock_create_payment_purchase_submit):
        account_payment_1 = AccountPaymentFactory(
            account=self.account,
            due_date=date.today(),
            due_amount=400000
        )
        account_payments = AccountPayment.objects.filter(account=self.account).order_by('due_date')
        create_debit_payment_process_mandiri(account_payments)
        self.assertFalse(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment_1,
            amount=account_payment_1.due_amount,
        ).exists())

        self.autodebet_mandiri_account.autodebet_account=self.autodebet_account
        self.autodebet_mandiri_account.save()
        mock_create_payment_purchase_submit.return_value = (
            {
                'responseCode': '505400',
                'responseMessage': 'GENERAL ERROR',
            },
            None
        )
        create_debit_payment_process_mandiri(account_payments)
        self.assertFalse(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment_1,
            amount=account_payment_1.due_amount,
        ).exists())

        mock_create_payment_purchase_submit.return_value = (
            {
                'responseCode': '2025400',
                'responseMessage': 'SUCCESSFUL'
            },
            None
        )
        create_debit_payment_process_mandiri(account_payments)
        self.assertTrue(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment_1,
            amount=account_payment_1.due_amount,
        ).exists())

        account_payment_1.due_amount = 6000000
        account_payment_1.save()
        create_debit_payment_process_mandiri(account_payments)
        self.assertFalse(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment_1,
            amount=account_payment_1.due_amount,
        ).exists())
        self.assertTrue(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment_1,
            amount=5000000,
        ).exists())

        account_payment_2 = AccountPaymentFactory(
            account=self.account,
            due_date=date.today(),
            due_amount=600000
        )
        account_payment_1.due_amount = 400000
        account_payment_1.save()
        create_debit_payment_process_mandiri(account_payments)
        self.assertTrue(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment_2,
            amount=account_payment_1.due_amount + account_payment_2.due_amount,
        ).exists())

    @patch('juloserver.autodebet.tasks.is_autodebet_feature_disable')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_collect_mandiri_autodebet_account_maximum_limit_collections_task(
        self,
        mock_access_token,
        mock_create_payment_purchase_submit,
        mock_is_autodebet_feature_disable
    ):
        account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + timedelta(days=1),
            due_amount=6000000
        )
        self.autodebet_mandiri_account.autodebet_account=self.autodebet_account
        self.autodebet_mandiri_account.save()
        collect_mandiri_autodebet_account_maximum_limit_collections_task()
        self.assertFalse(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment,
            amount=account_payment.due_amount,
        ).exists())

        self.max_limit_settings.parameters['deduction_dpd'] = [-1]
        self.max_limit_settings.save()
        mock_create_payment_purchase_submit.return_value = (
            {
                'responseCode': '505400',
                'responseMessage': 'GENERAL ERROR',
            },
            None
        )
        collect_mandiri_autodebet_account_maximum_limit_collections_task()
        self.assertFalse(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment,
            amount=account_payment.due_amount,
        ).exists())

        mock_is_autodebet_feature_disable.retrun_value = True
        mock_create_payment_purchase_submit.return_value = (
            {
                'responseCode': '2025400',
                'responseMessage': 'SUCCESSFUL'
            },
            None
        )
        collect_mandiri_autodebet_account_maximum_limit_collections_task()
        self.assertFalse(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment,
            amount=5000000,
        ).exists())

        mock_is_autodebet_feature_disable.return_value = False
        collect_mandiri_autodebet_account_maximum_limit_collections_task()
        self.assertTrue(AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=account_payment,
            amount=5000000,
        ).exists())


class TestAutodebetMandiriPurchaseSubmitV2(TestCase):
    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def setUp(self):
        self.customer = CustomerFactory(customer_xid='56338192560570')
        self.account = AccountFactory(customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True, vendor='MANDIRI'
        )
        AccountPaymentFactory(account=self.account, due_date=date.today(), due_amount=1000000)
        AccountPaymentFactory(
            account=self.account, due_date=date.today() - timedelta(days=30), due_amount=1000000
        )
        AccountPaymentFactory(
            account=self.account, due_date=date.today() - timedelta(days=60), due_amount=1000000
        )
        AccountPaymentFactory(
            account=self.account, due_date=date.today() - timedelta(days=90), due_amount=500000
        )
        self.autodebet_mandiri_account = AutodebetMandiriAccountFactory()

        self.customer2 = CustomerFactory(customer_xid='56338192560570')
        self.account2 = AccountFactory(customer=self.customer2)
        self.autodebet_account2 = AutodebetAccountFactory(
            account=self.account2, is_use_autodebet=True, is_suspended=False, vendor='MANDIRI'
        )
        self.autodebet_mandiri_account2 = AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account2,
        )
        self.account_payment1 = AccountPaymentFactory(
            account=self.account2, due_date=date.today(), due_amount=2000000
        )
        self.account_payment2 = AccountPaymentFactory(
            account=self.account2,
            due_date=date.today() - timedelta(days=30),
            due_amount=0,
            paid_amount=2000000,
        )
        AutodebetMandiriTransactionFactory(
            autodebet_mandiri_account=self.autodebet_mandiri_account2,
            amount=2000000,
            account_payment=self.account_payment2,
            status=AutodebetMandiriPaymentResultStatusConst.SUCCESS,
        )

        self.customer3 = CustomerFactory(customer_xid='56338192560571')
        self.account3 = AccountFactory(customer=self.customer3)
        self.autodebet_account3 = AutodebetAccountFactory(
            account=self.account3, is_use_autodebet=True, is_suspended=False, vendor='MANDIRI'
        )
        self.autodebet_mandiri_account3 = AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account3,
        )
        self.account_payment3 = AccountPaymentFactory(
            account=self.account3,
            due_date=date.today() - timedelta(days=29),
            due_amount=2000000,
        )
        self.account_payment4 = AccountPaymentFactory(
            account=self.account3, due_date=date.today() + timedelta(days=1), due_amount=1000000
        )

        self.max_limit_settings = FeatureSettingFactory(
            feature_name='autodebet_mandiri_max_limit_deduction_day',
            parameters={'maximum_amount': 3500000, 'deduction_dpd': [-1]},
        )
        FeatureSettingFactory(feature_name='autodebet_mandiri', is_active=True)

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_create_debit_payment_process_mandiri_error(
        self, mock_access_token, mock_create_payment_purchase_submit
    ):
        account_payments = AccountPayment.objects.filter(account=self.account).order_by('due_date')
        create_debit_payment_process_mandiriv2(account_payments)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
            ).count(),
            0,
        )

        self.autodebet_mandiri_account.autodebet_account = self.autodebet_account
        self.autodebet_mandiri_account.save()
        mock_create_payment_purchase_submit.return_value = (
            {
                'responseCode': '505400',
                'responseMessage': 'GENERAL ERROR',
            },
            'GENERAL ERROR',
        )
        create_debit_payment_process_mandiriv2(account_payments)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
            ).count(),
            0,
        )

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_create_debit_payment_process_mandiri_success_first_deduction(
        self, mock_access_token, mock_create_payment_purchase_submit
    ):
        account_payments = AccountPayment.objects.filter(account=self.account).order_by('due_date')

        self.autodebet_mandiri_account.autodebet_account = self.autodebet_account
        self.autodebet_mandiri_account.save()
        mock_create_payment_purchase_submit.return_value = (
            {'responseCode': '2025400', 'responseMessage': 'SUCCESSFUL'},
            None,
        )
        create_debit_payment_process_mandiriv2(account_payments)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
            ).count(),
            1,
        )
        total_amount_deducted = (
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
                status__in=(
                    AutodebetMandiriPaymentResultStatusConst.SUCCESS,
                    AutodebetMandiriPaymentResultStatusConst.PENDING,
                ),
                cdate__date=date.today(),
            ).aggregate(amount_sum=Sum("amount"))["amount_sum"]
            or 0
        )
        self.assertEqual(total_amount_deducted, 500000)

    @patch('juloserver.autodebet.services.task_services.determine_best_deduction_day')
    @patch('juloserver.autodebet.services.task_services.is_account_eligible_for_fund_collection')
    @patch('juloserver.autodebet.services.task_services.is_autodebet_feature_disable')
    @patch('juloserver.autodebet.services.task_services.is_autodebet_mandiri_feature_active')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_create_debit_payment_process_mandiri_success_second_deduction(
        self,
        mock_access_token,
        mock_create_payment_purchase_submit,
        mock_is_autodebet_mandiri_feature_active,
        mock_is_autodebet_feature_disable,
        mock_is_account_eligible_for_fund_collection,
        mock_determine_best_deduction_day,
    ):
        mock_create_payment_purchase_submit.return_value = (
            {'responseCode': '2025400', 'responseMessage': 'SUCCESSFUL'},
            None,
        )
        mock_is_autodebet_mandiri_feature_active.return_value = True
        mock_is_autodebet_feature_disable.return_value = False
        mock_is_account_eligible_for_fund_collection.return_value = True
        mock_determine_best_deduction_day.return_value = 1

        check_and_create_debit_payment_process_after_callback_mandiriv2(self.account2)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account2,
            ).count(),
            2,
        )

        total_amount_deducted = (
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account2,
                status__in=(
                    AutodebetMandiriPaymentResultStatusConst.SUCCESS,
                    AutodebetMandiriPaymentResultStatusConst.PENDING,
                ),
                cdate__date=date.today(),
            ).aggregate(amount_sum=Sum("amount"))["amount_sum"]
            or 0
        )
        self.assertEqual(total_amount_deducted, 3500000)

    @patch('juloserver.autodebet.services.task_services.determine_best_deduction_day')
    @patch('juloserver.autodebet.services.task_services.is_account_eligible_for_fund_collection')
    @patch('juloserver.autodebet.services.task_services.is_autodebet_feature_disable')
    @patch('juloserver.autodebet.services.task_services.is_autodebet_mandiri_feature_active')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_create_debit_payment_process_mandiri_success_from_max_limit_deduction(
        self,
        mock_access_token,
        mock_create_payment_purchase_submit,
        mock_is_autodebet_mandiri_feature_active,
        mock_is_autodebet_feature_disable,
        mock_is_account_eligible_for_fund_collection,
        mock_determine_best_deduction_day,
    ):
        mock_create_payment_purchase_submit.return_value = (
            {'responseCode': '2025400', 'responseMessage': 'SUCCESSFUL'},
            None,
        )
        mock_is_autodebet_mandiri_feature_active.return_value = True
        mock_is_autodebet_feature_disable.return_value = False
        mock_is_account_eligible_for_fund_collection.return_value = True
        mock_determine_best_deduction_day.return_value = 1

        check_and_create_debit_payment_process_after_callback_mandiriv2(self.account3)
        self.account_payment3.due_amount = 0
        self.account_payment3.paid_amount = 2000000
        self.account_payment3.status_id = 330
        self.account_payment3.save()

        check_and_create_debit_payment_process_after_callback_mandiriv2(self.account3)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account3,
            ).count(),
            2,
        )

        total_amount_deducted = (
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account3,
                status__in=(
                    AutodebetMandiriPaymentResultStatusConst.SUCCESS,
                    AutodebetMandiriPaymentResultStatusConst.PENDING,
                ),
                cdate__date=date.today(),
            ).aggregate(amount_sum=Sum("amount"))["amount_sum"]
            or 0
        )
        self.assertEqual(total_amount_deducted, 3000000)


@override_settings(SUSPEND_SIGNALS=True)
class TestRequestOtp(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory(customer_xid=843757867)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(account=self.account, customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True
        )
        AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account,
            bank_card_token="1",
            charge_token="2",
        )

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.request_otp')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_request_otp_should_success(self, mock_access_token, mock_request_otp) -> None:
        mock_request_otp.return_value = (
            {
                "responseCode": "2008100"
            },
            None
        )
        message, status = is_mandiri_request_otp_success(self.account)
        self.assertTrue(status)

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.request_otp')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_request_otp_should_failed_when_response_code_is_not_success(
            self, mock_access_token, mock_request_otp
    ) -> None:
        mock_request_otp.return_value = (
            {
                "responseCode": "2000401"
            },
            None
        )
        message, status = is_mandiri_request_otp_success(self.account)
        self.assertFalse(status)


@override_settings(SUSPEND_SIGNALS=True)
class TestVerifyOtp(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory(customer_xid=843757867)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(account=self.account, customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True
        )
        AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account,
            bank_card_token="1",
            charge_token="2",
        )

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.verify_otp')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_verify_otp_should_success(self, mock_access_token, mock_verify_otp) -> None:
        mock_verify_otp.return_value = (
            {
                "responseCode": "2000400",
                "bankCardToken": "123456"
            },
            None
        )
        message, status = is_mandiri_verify_otp_success('123456', self.account)
        self.assertTrue(status)

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.verify_otp')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_verify_otp_should_failed_when_response_code_is_not_success(
            self, mock_access_token, mock_verify_otp
    ) -> None:
        mock_verify_otp.return_value = (
            {
                "responseCode": "20004Z0"
            },
            None
        )
        message, status = is_mandiri_verify_otp_success('123456', self.account)
        self.assertFalse(status)


class TestActivation(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory(customer_xid=843757867)
        self.account = AccountFactory(customer=self.customer)
        self.client = APIClient()
        
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.registration_bind_card')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def test_process_mandiri_activation(self, mock_access_token, mock_registration_bind_card):
        mock_registration_bind_card.return_value = (
            {
                "responseCode":"00",
                "responseMessage":"In Progress"
            }, None, "1231231243435345345"
        )
        data = {
                "bankCardNo": "4097662150168642",
                "expiryDate": "2809"
            }
        message, status, journey_id = process_mandiri_activation(self.account, data)
        self.assertTrue(status)
    
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.registration_bind_card')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_process_mandiri_failed_activation(self, mock_access_token, mock_registration_bind_card):
        mock_registration_bind_card.return_value = (
            {
                "responseCode":"99",
                "responseMessage":"Failed"
            }, None, None
        )
        data = {
                "bankCardNo": "4097662150168642",
                "expiryDate": "2809"
            }

        message, status, _ = process_mandiri_activation(self.account, data)
        self.assertFalse(status)

    @pytest.mark.skip(reason="Flaky")
    def test_notification_callback(self):
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, vendor="MANDIRI"
        )
        AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account,
            journey_id="202309251004222347462384242"
        )
        data = {"responseCode":"2000100","responseMessage":"SUCCESSFUL","journeyID":"202309251004222347462384242","referenceNo":"326834049094","chargeToken":"326858017179","additionalInfo":{"bankCode":"008","bankName":"BANK MANDIRI","mobileNumber":"*******9889","verificationMethod":"OTP"}}

        self.client.credentials(HTTP_X_SIGNATURE="fad6ae2e10cc7331f4041fd4892fc732972bb9d4c4873a16d7a33c0018abfb6d04d2f5143f391c138b16f5355d8e1b1c205258f35a7a9b7dd12718f6156f0647")
        response = self.client.post('/webhook/autodebet/mandiri/v1/binding_notification', data=data, format='json')
        
        autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
            journey_id="202309251004222347462384242"
        ).last()
        autodebet_mandiri_account.refresh_from_db()
        self.assertEqual('326858017179', autodebet_mandiri_account.charge_token)
        self.assertEqual(response.data['data'], '{"responseCode":"2000100","responseMessage":"SUCCESS"}')

    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def test_check_mandiri_callback_activation(self):
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, vendor="MANDIRI", status="pending_registration"
        )
        self.autodebet_api_log = AutodebetAPILogFactory(
            account_id=self.account.id,
            request_type='[POST] /WEBHOOK/MANDIRI/V1/BINDING_NOTIFICATION',
            request="{'responseCode': '2000100', 'responseMessage': 'SUCCESSFUL', 'journeyID': '2023092620383299432653564223', 'referenceNo': '326944049138', 'chargeToken': '326968017209', 'additionalInfo': {'bankCode': '008', 'bankName': 'BANK MANDIRI', 'mobileNumber': '********2524', 'verificationMethod': 'OTP'}}",
            vendor='MANDIRI'
        )
        self.autodebet_mandiri_account = AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account,
            journey_id='2023092620383299432653564223'
        )
        message, status = check_mandiri_callback_activation(self.account)
        self.assertTrue(status)

    def test_check_mandiri_callback_activation_log_not_found(self):
        message, status = check_mandiri_callback_activation(self.account)
        self.assertFalse(status)

    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def test_check_mandiri_callback_activation_request_error(self):
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, vendor="MANDIRI"
        )
        self.autodebet_api_log = AutodebetAPILogFactory(
            account_id=self.account.id,
            request_type='[POST] /WEBHOOK/MANDIRI/V1/BINDING_NOTIFICATION',
            request="{'responseCode': '4040111', 'responseMessage': 'INVALID CARD', 'journeyID': '2023100213383221593658774431', 'referenceNo': '327537049173'}",
            vendor='MANDIRI'
        )
        message, status = check_mandiri_callback_activation(self.account)
        self.assertFalse(status)
