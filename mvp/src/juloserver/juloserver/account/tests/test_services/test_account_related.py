import datetime
from builtins import object
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from factory import Iterator
from collections import namedtuple

from juloserver.account.constants import (
    AccountConstant,
    AccountStatus430CardColorDpd,
    FeatureNameConst,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_vendor.tests.factories import (
    SkiptraceHistoryFactory,
    SkiptraceResultChoiceFactory,
)
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst, WorkflowConst
from juloserver.account.models import AccountStatusHistory
from juloserver.account.services.account_related import (
    get_dpd_and_lock_colour_by_account,
    get_latest_application_dict_by_account_ids,
    get_latest_loan_dict_by_account_ids,
    get_loan_amount_dict_by_account_ids,
    is_account_limit_sufficient,
    is_account_hardtoreach,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountwithApplicationFactory,
    WorkflowFactory,
)
from juloserver.autodebet.tests.factories import (
    AutodebetAccountFactory,
    AutodebetBenefitFactory,
)
from juloserver.julo.models import MobileFeatureSetting, EmailHistory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    LoanFactory,
    ProductLineFactory,
    StatusLookupFactory,
    AuthUserFactory,
    CustomerFactory,
    DeviceFactory,
)
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.payback.constants import WaiverConst
from juloserver.payback.tests.factories import WaiverTempFactory
from juloserver.account.services.account_related import (
    process_change_account_status,
    get_suspension_email_context,
    trigger_send_email_suspension,
    trigger_send_email_reactivation,
)
from juloserver.fraud_security.constants import FraudFlagSource, FraudFlagTrigger, FraudFlagType
from juloserver.fraud_security.models import FraudFlag
from juloserver.user_action_logs.models import MobileUserActionLog
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.account.services.account_related import risky_change_phone_activity_check
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account.tasks.account_task import (
    process_account_reactivation,
    send_pn_reactivation_success,
)


event_response = namedtuple('Response', ['status_code'])


class DummyAccount(object):
    def __init__(self, status_id, dpd):
        self.status_id = status_id
        self.dpd = dpd


class TestAccountRelatedServices(TestCase):
    def setUp(self):
        self.parameter = {
            'dpd_color': {
                AccountStatus430CardColorDpd.FIVE_TO_TEN: '#F59539',
                AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN: '#DB4D3D',
            },
            'lock_color': {
                AccountStatus430CardColorDpd.FIVE_TO_TEN: '#F59539',
                AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN: '#DB4D3D',
            },
        }
        self.setting = MobileFeatureSetting.objects.create(
            is_active=True,
            feature_name=FeatureNameConst.ACCOUNT_STATUS_X430_COLOR,
            parameters=self.parameter,
        )
        self.account_430 = DummyAccount(status_id=AccountConstant.STATUS_CODE.suspended, dpd=6)
        self.account_420 = DummyAccount(status_id=AccountConstant.STATUS_CODE.active, dpd=0)

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.customer.appsflyer_device_id = "new_appsflyer_id"
        self.customer.app_instance_id = "appinstanceid"
        self.customer.save()

    def test_get_dpd_and_lock_colour_by_account_setting_off_430(self):
        self.setting.is_active = False
        self.setting.save()
        dpd_color, lock_color = get_dpd_and_lock_colour_by_account(self.account_430)
        self.assertIsNone(dpd_color)
        self.assertIsNone(lock_color)

    def test_get_dpd_and_lock_colour_by_account_setting_on_420(self):
        dpd_color, lock_color = get_dpd_and_lock_colour_by_account(self.account_420)
        self.assertIsNone(dpd_color)
        self.assertIsNone(lock_color)

    def test_get_dpd_and_lock_colour_by_account_setting_on_status_430_dpd_less_than_5(self):
        self.account_430.dpd = 2
        dpd_color, lock_color = get_dpd_and_lock_colour_by_account(self.account_430)
        self.assertIsNone(dpd_color)
        self.assertIsNone(lock_color)

    def test_get_dpd_and_lock_colour_by_account_setting_on_status_430_dpd_5_10(self):
        self.account_430.dpd = 7
        dpd_color, lock_color = get_dpd_and_lock_colour_by_account(self.account_430)
        self.assertEqual(
            dpd_color, self.parameter['dpd_color'][AccountStatus430CardColorDpd.FIVE_TO_TEN]
        )
        self.assertEqual(
            dpd_color, self.parameter['lock_color'][AccountStatus430CardColorDpd.FIVE_TO_TEN]
        )

    def test_get_dpd_and_lock_colour_by_account_setting_on_status_430_dpd_more_than_11(self):
        self.account_430.dpd = 12
        dpd_color, lock_color = get_dpd_and_lock_colour_by_account(self.account_430)
        self.assertEqual(
            dpd_color,
            self.parameter['dpd_color'][AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN],
        )
        self.assertEqual(
            dpd_color,
            self.parameter['lock_color'][AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN],
        )

    def test_get_dpd_and_lock_colour_by_account_setting_on_status_430_dpd_equal_to_11(self):
        self.account_430.dpd = 11
        dpd_color, lock_color = get_dpd_and_lock_colour_by_account(self.account_430)
        self.assertEqual(
            dpd_color,
            self.parameter['dpd_color'][AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN],
        )
        self.assertEqual(
            dpd_color,
            self.parameter['lock_color'][AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN],
        )

    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    def test_account_status_change_events_triggering_420(
        self,
        mock_get_appsflyer_service,
        mock_send_event_to_ga,
    ):
        mock_get_appsflyer_service.return_value = event_response(status_code=200)
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.inactive)
        self.account = AccountFactory(customer=self.customer, status=status_code)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()
        process_change_account_status(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.active,
            change_reason='activate test account',
        )
        force_run_on_commit_hook()
        mock_get_appsflyer_service.assert_called_once()
        mock_send_event_to_ga.assert_called_once()

    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    def test_account_status_change_events_triggering_421(
        self, mock_get_appsflyer_service, mock_send_event_to_ga
    ):
        mock_get_appsflyer_service.return_value = event_response(status_code=200)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()

        process_change_account_status(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.active_in_grace,
            change_reason='activate test account',
        )
        force_run_on_commit_hook()
        mock_get_appsflyer_service.assert_called_once()
        mock_send_event_to_ga.assert_called_once()

    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    def test_account_status_change_events_triggering_430(
        self, mock_get_appsflyer_service, mock_send_event_to_ga
    ):
        mock_get_appsflyer_service.return_value = event_response(status_code=200)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()

        process_change_account_status(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.suspended,
            change_reason='suspend test account',
        )
        force_run_on_commit_hook()
        mock_get_appsflyer_service.assert_called_once()
        mock_send_event_to_ga.assert_called_once()


class TestAccountProperty(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.waivertemp = WaiverTempFactory(account=self.account)
        self.account_application = AccountwithApplicationFactory()
        self.autodebet_account = AutodebetAccountFactory(account=self.account_application)
        self.autodebet_benefit = AutodebetBenefitFactory(
            account_id=self.autodebet_account.account.id
        )

    def test_is_account_ever_suspeneded_true(self):
        AccountStatusHistory.objects.create(
            status_new_id=AccountConstant.STATUS_CODE.suspended,
            status_old_id=AccountConstant.STATUS_CODE.active,
            account=self.account,
        )
        assert self.account.is_account_ever_suspeneded() == True

    def test_is_account_ever_suspeneded_false(self):
        AccountStatusHistory.objects.create(
            status_new_id=AccountConstant.STATUS_CODE.active,
            status_old_id=AccountConstant.STATUS_CODE.inactive,
            account=self.account,
        )
        assert self.account.is_account_ever_suspeneded() == False

    def test_waiver_is_active_true(self):
        assert self.account.waiver_is_active() == True
        self.waivertemp.status = WaiverConst.IMPLEMENTED_STATUS
        self.waivertemp.save()
        assert self.account.waiver_is_active() == True

    def test_waiver_is_active_false(self):
        self.waivertemp.status = WaiverConst.EXPIRED_STATUS
        self.waivertemp.save()
        assert self.account.waiver_is_active() == False

    def test_is_account_eligible_to_hit_channeling_api_true(self):
        assert self.autodebet_account.account.is_account_eligible_to_hit_channeling_api() == True
        self.autodebet_account.is_use_autodebet = True
        self.autodebet_account.save()
        self.autodebet_benefit.benefit_type = 'cashback'
        self.autodebet_benefit.save()
        assert self.autodebet_account.account.is_account_eligible_to_hit_channeling_api() == True

    def test_is_account_eligible_to_hit_channeling_api_false(self):
        self.autodebet_account.is_use_autodebet = True
        self.autodebet_account.save()
        self.autodebet_benefit.benefit_type = 'waive_interest'
        self.autodebet_benefit.save()
        assert self.autodebet_account.account.is_account_eligible_to_hit_channeling_api() == False


class TestIsAccountLimitSufficient(TestCase):
    def setUp(self):
        self.account = AccountFactory()

    def test_is_account_limit_sufficient_true(self):
        AccountLimitFactory(account=self.account, available_limit=10000)

        test_loan_amounts = [10000, 9999]
        for loan_amount in test_loan_amounts:
            ret_val = is_account_limit_sufficient(loan_amount, self.account.id)
            self.assertTrue(ret_val)

    def test_is_account_limit_sufficient_false(self):
        AccountLimitFactory(account=self.account, available_limit=10000)

        ret_val = is_account_limit_sufficient(10001, self.account.id)
        self.assertFalse(ret_val)


class TestGetLoanAmountDictByAccountIds(TestCase):
    def test_get_loan_amount_dict_by_account_ids(self):
        accounts = AccountFactory.create_batch(3)
        LoanFactory.create_batch(
            9,
            account=Iterator(accounts),
            loan_amount=Iterator([10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000, 90000]),
        )

        ret_val = get_loan_amount_dict_by_account_ids([accounts[0], accounts[1]])
        self.assertEqual(
            {
                accounts[0].id: 120000,
                accounts[1].id: 150000,
            },
            ret_val,
        )


class TestGetLatestLoanDictByAccountIds(TestCase):
    def test_get_latest_loan_dict_by_account_ids(self):
        accounts = AccountFactory.create_batch(3)
        loans = LoanFactory.create_batch(6, account=Iterator(accounts), loan_amount=10000)

        ret_val = get_latest_loan_dict_by_account_ids(
            [accounts[0], accounts[1]], fields=['loan_amount']
        )

        self.assertIsNotNone(ret_val.get(accounts[0].id))
        self.assertEquals(loans[3].id, ret_val[accounts[0].id].id)
        self.assertIsNotNone(ret_val.get(accounts[1].id))
        self.assertEquals(loans[4].id, ret_val[accounts[1].id].id)
        self.assertIsNone(ret_val.get(accounts[2].id))


class TestGetLatestApplicationDictByAccountIds(TestCase):
    def test_get_latest_application_dict_by_account_ids(self):
        accounts = AccountFactory.create_batch(3)
        applications = ApplicationFactory.create_batch(
            6, account=Iterator(accounts), product_line=ProductLineFactory(product_line_code=1)
        )

        ret_val = get_latest_application_dict_by_account_ids(
            [accounts[0], accounts[1]],
            fields=['ktp', 'product_line_id'],
            select_related=['product_line'],
        )

        self.assertIsNotNone(ret_val.get(accounts[0].id))
        self.assertEquals(applications[3].id, ret_val[accounts[0].id].id)
        self.assertIsNotNone(ret_val.get(accounts[1].id))
        self.assertEquals(applications[4].id, ret_val[accounts[1].id].id)
        self.assertIsNone(ret_val.get(accounts[2].id))

        with self.assertNumQueries(0):
            self.assertEqual(1, ret_val[accounts[0].id].product_line.product_line_code)


class TestRiskyChangePhoneActivityCheck(TestCase):
    def setUp(self):
        self.feature = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.RISKY_CHANGE_PHONE_ACTIVITY_CHECK, is_active=True
        )
        self.account = AccountwithApplicationFactory()
        self.application = self.account.application_set.last()
        self.application.application_status_id = 190
        self.application.customer = self.account.customer
        self.application.save()
        inactive_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            customer=self.account.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
            loan_status=inactive_status,
        )
        self.log = MobileUserActionLog.objects.create(
            activity='ChangePhoneActivity',
            customer_id=self.account.customer.id,
            android_api_level=1,
            activity_counter=2,
            log_ts=datetime.datetime.now(),
        )
        self.fraud_flag = FraudFlag.objects.create(
            customer=self.application.customer,
            fraud_type=FraudFlagType.CHANGE_PHONE_ACTIVITY,
            trigger=FraudFlagTrigger.CHANGE_PHONE_ACTIVITY,
            flag_source_type=FraudFlagSource.CUSTOMER,
            flag_source_id=str(self.application.customer.id),
        )

    @patch('juloserver.loan.services.loan_related.update_loan_status_and_loan_history')
    def test_risky_change_phone_activity_check_detected(self, mock_update_215):
        result = risky_change_phone_activity_check(self.loan, self.application)
        mock_update_215.assert_called()
        self.assertEqual(result, True)

    @patch('juloserver.loan.services.loan_related.update_loan_status_and_loan_history')
    def test_risky_change_phone_activity_check_not_detected(self, mock_update_215):
        self.fraud_flag.delete()
        result = risky_change_phone_activity_check(self.loan, self.application)
        mock_update_215.assert_not_called()
        self.assertEqual(result, False)

    @patch('juloserver.loan.services.loan_related.update_loan_status_and_loan_history')
    def test_risky_change_phone_activity_check_feature_off(self, mock_update_215):
        self.feature.is_active = False
        self.feature.save()
        result = risky_change_phone_activity_check(self.loan, self.application)
        mock_update_215.assert_not_called()
        self.assertEqual(result, False)


class TestAccountHardToReach(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)

    def test_no_payments_exist(self):
        account_id = 1
        self.assertFalse(is_account_hardtoreach(account_id))

    def test_last_payment_paid_on_time(self):
        self.account_payment.status_id = PaymentStatusCodes.PAID_ON_TIME
        self.account_payment.save()

        self.assertFalse(is_account_hardtoreach(self.account_payment.account_id))

    def test_no_skiptrace_history_call_dates(self):
        self.account_payment.status_id = PaymentStatusCodes.PAID_ON_TIME
        self.account_payment.save()

        self.assertFalse(is_account_hardtoreach(self.account_payment.account_id))

    def test_skiptrace_history_call_results_exist_within_date_range(self):
        self.account_payment.status_id = PaymentStatusCodes.PAID_LATE
        self.account_payment.save()

        for _ in range(3):
            SkiptraceHistoryFactory(
                account=self.account,
                start_ts=timezone.now() - timedelta(days=2),
            )
        self.assertFalse(is_account_hardtoreach(self.account_payment.account_id))

    def test_account_is_hard_to_reach(self):
        self.account_payment.status_id = PaymentStatusCodes.PAID_LATE
        self.account_payment.save()

        SkiptraceHistoryFactory(
            account=self.account,
            start_ts=timezone.now() - timedelta(days=100),
            call_result=SkiptraceResultChoiceFactory(name="No Answer"),
        )
        self.assertTrue(is_account_hardtoreach(self.account_payment.account_id))


class TestAccountSuspensionEmail(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )
        self.feature = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.ACCOUNT_REACTIVATION_SETTING,
            is_active=True,
        )

    def test_get_suspension_email_context(self):
        context = get_suspension_email_context(self.account)
        customer_fullname = self.customer.fullname
        self.assertEqual(context['fullname'], customer_fullname)

    @patch('juloserver.account.services.account_related.get_julo_email_client')
    def test_trigger_send_email_suspension(
        self,
        mock_get_julo_email_client,
    ):
        mock_subject = 'Maaf, Limit Kredit JULOmu Dinonaktifkan'
        mock_get_julo_email_client().email_notify_loan_suspension_j1.return_value = (
            200,
            {'X-Message-Id': 'test'},
            mock_subject,
            '',
            '',
        )
        trigger_send_email_suspension(self.account)

        mock_get_julo_email_client.assert_called()
        email_history = EmailHistory.objects.filter(customer=self.customer).last()
        self.assertEqual(email_history.subject, mock_subject)
        self.assertEqual(email_history.template_code, "julo_risk_suspension_email_information.html")


class TestReactivationEmailPn(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )
        self.feature = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.ACCOUNT_REACTIVATION_SETTING,
            is_active=True,
        )
        self.device = DeviceFactory(customer=self.customer)

    @patch('juloserver.account.services.account_related.get_julo_email_client')
    def test_trigger_send_email_reactivation(
        self,
        mock_get_julo_email_client,
    ):
        mock_subject = 'Kamu Udah Bisa Transaksi di JULO Lagi, Lho!'
        mock_get_julo_email_client().email_notify_loan_reactivation_j1.return_value = (
            200,
            {'X-Message-Id': 'test'},
            mock_subject,
            '',
            '',
        )
        trigger_send_email_reactivation(self.account.id)

        mock_get_julo_email_client.assert_called()
        email_history = EmailHistory.objects.filter(customer=self.customer).last()
        self.assertEqual(email_history.subject, mock_subject)
        self.assertEqual(email_history.template_code, "email_notify_back_to_420.html")

    @patch('juloserver.account.services.account_related.get_julo_email_client')
    def test_trigger_send_email_reactivation_jturbo(
        self,
        mock_get_julo_email_client,
    ):
        # create jturbo account
        jturbo_customer = CustomerFactory()
        jturbo_account = AccountFactory(
            customer=jturbo_customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended),
            ever_entered_B5=True,
        )
        jturbo_application = ApplicationFactory(
            customer=jturbo_customer,
            account=jturbo_account,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        jturbo_loan = LoanFactory(
            account=jturbo_account,
            customer=jturbo_customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )
        jturbo_application_jturbo = ApplicationFactory(
            customer=jturbo_customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
            product_line=ProductLineFactory(product_line_code=2),
        )
        mock_subject = 'Kamu Udah Bisa Transaksi di JULO Lagi, Lho!'
        mock_get_julo_email_client().email_notify_loan_reactivation_j1.return_value = (
            200,
            {'X-Message-Id': 'test'},
            mock_subject,
            '',
            '',
        )
        trigger_send_email_reactivation(self.account.id)

        mock_get_julo_email_client.assert_called()
        email_history = EmailHistory.objects.filter(customer=self.customer).last()
        self.assertEqual(email_history.subject, mock_subject)
        self.assertEqual(email_history.template_code, "email_notify_back_to_420.html")

    @patch('juloserver.julo.clients.pn.JuloPNClient.pn_reactivation_success')
    def test_send_pn(self, mock_pn_reactivation_success):
        send_pn_reactivation_success(self.application.customer)
        mock_pn_reactivation_success.assert_called_once()
