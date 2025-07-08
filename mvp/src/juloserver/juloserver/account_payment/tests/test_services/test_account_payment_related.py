import re

import mock
from unittest import result
from django.test import TestCase
from datetime import datetime, timedelta, date
from django.utils import timezone
import json
from factory import (
    Iterator,
    SubFactory,
)

from juloserver.account_payment.services.account_payment_related import (
    construct_loan_in_account_payment_list,
    get_image_by_account_payment_id,
    get_account_payment_events_transaction_level,
    is_account_loan_paid_off,
    get_unpaid_account_payment,
    update_payment_installment,
    change_due_dates,
    get_cashback_earned_dict_by_account_payment_ids,
    get_on_processed_loan_refinancing_by_account_id,
    get_potential_cashback_by_account_payment,
    get_late_fee_amount_by_account_payment,
    construct_last_checkout_request,
    get_checkout_xid_by_paid_off_accout_payment,
    get_checkout_experience_setting,
    update_checkout_experience_status_to_cancel,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    PaymentFactory,
    ApplicationFactory,
    StatusLookupFactory,
    PaymentMethodLookupFactory,
    PaymentMethodFactory,
    PaymentEventFactory,
    ExperimentSettingFactory,
    FeatureSettingFactory,
    ProductLineFactory,
    WorkflowFactory,
    PaybackTransactionFactory,
    ProductLookupFactory,
)
from juloserver.julo.models import (
    StatusLookup,
    LoanStatusCodes,
    PaymentEvent,
    Payment,
    PaymentStatusCodes,
    PaymentMethod,
    ProductLookup,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    LateFeeRuleFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory, CheckoutRequestFactory
from juloserver.account_payment.models import AccountPaymentStatusHistory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.julo.constants import ExperimentConst, FeatureNameConst, WorkflowConst
from juloserver.account.models import AccountCycleDayHistory
from juloserver.account.constants import LDDEReasonConst
from juloserver.account_payment.services.account_payment_related import update_latest_payment_method
from juloserver.julo.payment_methods import PaymentMethodCodes


class TestAccountPaymentRelated(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000,
            disbursement_id=self.disbursement.id,
        )
        self.account_payment.refresh_from_db()
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000,
        )

    def test_construct_loan_in_account_payment_list(self):
        result = construct_loan_in_account_payment_list(self.account_payment.id, False)
        assert isinstance(result, list) == True

    def test_get_image_by_account_payment_id(self):
        result = get_image_by_account_payment_id(self.account_payment.id)

    def test_get_unpaid_account_payment(self):
        get_unpaid_account_payment(self.account.id)

    def test_is_account_loan_paid_off(self):
        is_account_loan_paid_off(self.account)

    def test_get_account_payment_events_transaction_level(self):
        user_groups = self.user_auth.groups.values_list('name', flat=True).all()
        get_account_payment_events_transaction_level(
            self.account_payment, self.user_auth, user_groups
        )

    def test_update_payment_installment(self):
        payments = Payment.objects.by_loan(self.loan).not_paid().exclude(pk=self.payment.id)
        payments.update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        today = timezone.localtime(timezone.now()).date()
        new_due_date = today + timedelta(days=1)
        update_payment_installment(self.payment.account_payment, new_due_date)
        self.assertTrue(PaymentEvent.objects.filter(payment=self.payment).exists())

    def test_change_cycle_day(self):
        payments = Payment.objects.by_loan(self.loan).not_paid().exclude(pk=self.payment.id)
        payments.update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        today = timezone.localtime(timezone.now()).date()
        new_due_date = today + timedelta(days=1)
        change_due_dates(self.payment.account_payment, new_due_date)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.cycle_day, new_due_date.day)
        history = AccountCycleDayHistory.objects.filter(
            account_id=self.payment.account_payment.account_id,
            reason=LDDEReasonConst.Manual,
            latest_flag=True
        ).first()
        assert history == None

    def test_change_cycle_day_and_create_cycle_day_history_for_j1_and_starter(self):
        old_cycle_day = 20
        self.account.cycle_day = old_cycle_day
        self.account.save()
        product_line_j1 =ProductLineFactory(product_line_code=ProductLineCodes.J1)
        workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.workflow = workflow_j1
        self.application.product_line = product_line_j1
        self.application.save()

        today = datetime(2023, 12, 11)
        new_due_date = today + timedelta(days=1)

        payments = Payment.objects.by_loan(self.loan).not_paid().exclude(pk=self.payment.id)
        payments.update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)

        change_due_dates(self.payment.account_payment, new_due_date)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.cycle_day, new_due_date.day)
        history = AccountCycleDayHistory.objects.filter(
            account_id=self.payment.account_payment.account_id,
            reason=LDDEReasonConst.Manual,
            latest_flag=True
        ).first()

        assert history.old_cycle_day == old_cycle_day
        assert history.new_cycle_day == new_due_date.day
        assert history.application == self.account.get_active_application()
        assert json.loads(history.parameters) == {}
        assert history.reason == LDDEReasonConst.Manual


class TestGetCashbackEarnedDictByAccountPaymentIds(TestCase):
    def test_get_cashback_earned_dict_by_account_payment_ids(self):
        account_payments = AccountPaymentFactory.create_batch(3)
        PaymentFactory.create_batch(
            9,
            loan=SubFactory(LoanFactory),
            payment_status=SubFactory(StatusLookupFactory),
            account_payment=Iterator(account_payments),
            cashback_earned=Iterator([100, 200, 300, 400, 500, 600, 700, 800, 900]),
        )

        ret_val = get_cashback_earned_dict_by_account_payment_ids(
            [account_payments[0], account_payments[1]]
        )

        self.assertEqual(
            {
                account_payments[0].id: 1200,
                account_payments[1].id: 1500,
            },
            ret_val,
        )


class TestGetOnProcessedLoanRefinancingByAccountId(TestCase):
    def setUp(self):
        self.account = AccountFactory(id=4001)
        self.loan = LoanFactory(account=self.account)
        self.loan_refinancing = LoanRefinancingRequestFactory(
            account=self.account, loan=self.loan, status='Approved'
        )

    def test_get_on_processed_loan_refinancing_by_account_id_true(self):
        result = get_on_processed_loan_refinancing_by_account_id(self.account)
        self.assertEqual(result, True)

    def test_get_on_processed_loan_refinancing_by_account_id_false(self):
        self.loan_refinancing.status = 'Expired'
        self.loan_refinancing.save()
        result = get_on_processed_loan_refinancing_by_account_id(self.account)
        self.assertEqual(result, False)


class TestGetPotentialCashbackByAccountPayment(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(due_date=date.today() + timedelta(days=4))
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            loan_amount=30000,
            loan_duration=3,
        )
        self.payment = PaymentFactory(
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            payment_status=StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_180DPD),
            due_amount=10000,
        )
        self.cashback_parameters = dict(
            is_eligible_new_cashback=self.account.is_eligible_for_cashback_new_scheme,
            due_date=-3,
            percentage_mapping={'1': 1, '2': 2, '3': 3, '4': 4, '5': 5},
            account_status=self.account.status_id,
        )

    @mock.patch('juloserver.julo.models.Payment.maximum_cashback', new_callable=mock.PropertyMock)
    @mock.patch('juloserver.julo.models.Loan.cashback_monthly', new_callable=mock.PropertyMock)
    @mock.patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_get_potential_cashback_by_account_payment(
        self, mock_cashback_experiment, mock_cashback_monthly, mock_maximum_cashback
    ):
        mock_maximum_cashback.return_value = 1000
        mock_cashback_monthly.return_value = 500
        mock_cashback_experiment.return_value = False

        get_potential_cashback_by_account_payment(
            self.account_payment, 0, cashback_parameters=self.cashback_parameters
        )

    def test_get_potential_cashback_by_account_payment_exceed_due_date(self):
        self.account_payment.due_date = date.today() - timedelta(days=4)
        self.account_payment.save()
        result = get_potential_cashback_by_account_payment(
            self.account_payment, 0, cashback_parameters=self.cashback_parameters
        )
        self.assertEqual(result, 0)


class TestGetLateFeeAmountByAccountPayment(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.j1_product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.jturbo_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JTURBO)
        self.mtl1_product_line = ProductLineFactory(product_line_code=ProductLineCodes.MTL1)
        self.mtl2_product_line = ProductLineFactory(product_line_code=ProductLineCodes.MTL2)
        self.j1_product = ProductLookupFactory(
            product_line=self.j1_product_line,
        )
        ProductLookupFactory(
            product_line=self.jturbo_product_line,
        )
        ProductLookupFactory(
            product_line=self.mtl1_product_line,
        )
        ProductLookupFactory(
            product_line=self.mtl2_product_line,
        )
        self.account_payment = AccountPaymentFactory(
            late_fee_amount=3500,
            due_date=date.today() + timedelta(days=2),
            paid_late_fee=1000,
            late_fee_applied = 0
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            loan_amount=30000,
            loan_duration=3,
            late_fee_amount=5000,
            product=self.j1_product,
        )
        self.payment = PaymentFactory(
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            payment_status=StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_180DPD),
            due_amount=10000,
        )
        self.late_fee_rule_fs = FeatureSettingFactory(
            feature_name='late_fee_rule',
            parameters={
                "1": 0.111,
                "2": 0.109,
                "3": 0.074,
                "4": 0.144,
                "5": 0.059,
                "6": 0.142,
                "7": 0.109,
                "8": 0.096,
                "9": 0.118,
                "10": 0.096,
            },
            is_active=True,
        )
        product_lookups = ProductLookup.objects.filter(
            product_line_id__in=[
                ProductLineCodes.J1,
                ProductLineCodes.JTURBO,
                ProductLineCodes.MTL1,
                ProductLineCodes.MTL2,
            ],
        )
        max_late_fee = max(list(self.late_fee_rule_fs.parameters.values()))
        today = timezone.localtime(timezone.now())
        late_fee_product_name = "L." + str(max_late_fee).replace(".", "").zfill(3)
        for product_lookup in product_lookups:
            product_lookup.cdate = today
            product_lookup.udate = today
            product_lookup.product_name = re.sub(
                r"L\.\d{3}", late_fee_product_name, product_lookup.product_name
            )
            product_lookup.late_fee_pct = max_late_fee
            product_lookup.save()
            for dpd, late_fee_pct in self.late_fee_rule_fs.parameters.items():
                LateFeeRuleFactory(
                    dpd=int(dpd),
                    late_fee_pct=late_fee_pct,
                    product_lookup=product_lookup,
                )

    def test_get_late_fee_amount_by_account_payment_is_paid_off(self):
        result, grace_period = get_late_fee_amount_by_account_payment(self.account_payment, True)
        self.assertEqual(result, 3500)
        self.assertEqual(grace_period, 0)

    def test_get_late_fee_amount_by_account_payment_dpd_gt_5(self):
        self.account_payment.due_date = date.today() - timedelta(days=7)
        self.account_payment.save()
        result, grace_period = get_late_fee_amount_by_account_payment(self.account_payment, False)
        self.assertEqual(result, 2500)
        self.assertEqual(grace_period, 0)

    @mock.patch('juloserver.julo.models.Loan.late_fee_amount')
    def test_get_late_fee_amount_by_account_payment_dpd_gte_0_lt_5(self, mock_late_fee_amount):
        self.account_payment.due_date = date.today() - timedelta(days=3)
        self.account_payment.save()
        mock_late_fee_amount.return_value = 5000
        _, grace_period = get_late_fee_amount_by_account_payment(self.account_payment, False)
        self.assertEqual(grace_period, 2)

    def test_get_late_fee_amount_by_account_payment_dpd_minus(self):
        self.account_payment.due_date = date.today() + timedelta(days=7)
        self.account_payment.save()
        result, grace_period = get_late_fee_amount_by_account_payment(self.account_payment, False)
        self.assertEqual(result, 0)
        self.assertEqual(grace_period, 0)


class TestConstructLastCheckoutRequest(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            payment_method_name='BCA', customer=self.customer, virtual_account=self.virtual_account
        )
        self.payment_method_lookup = PaymentMethodLookupFactory(
            image_logo_url='test.jpg', name=self.payment_method.payment_method_name
        )
        self.account_payment = AccountPaymentFactory(
            id=4001,
            principal_amount=50000,
            interest_amount=5000,
            late_fee_amount=3500,
            paid_amount=10000,
            due_amount=10000,
        )
        self.checkout = CheckoutRequestFactory(
            id=1,
            account_id=self.account,
            total_payments=1000,
            checkout_payment_method_id=self.payment_method,
            account_payment_ids=[self.account_payment.id],
        )

    def test_construct_last_checkout_request(self):
        construct_last_checkout_request(self.checkout, self.payment_method)


class TestGetCheckoutXidByPaidOffAccoutPayment(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(
            id=4001,
            principal_amount=50000,
            interest_amount=5000,
            late_fee_amount=3500,
            paid_amount=10000,
            due_amount=10000,
            account=self.account,
        )
        self.account_payment_2 = AccountPaymentFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory(
            account_payment=self.account_payment,
            loan=self.loan,
            payment_status=StatusLookup.objects.get(pk=PaymentStatusCodes.PAID_ON_TIME),
        )
        self.payment_event = PaymentEventFactory(payment=self.payment)
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            payment_method_name='BCA', customer=self.customer, virtual_account=self.virtual_account
        )
        self.checkout = CheckoutRequestFactory(
            id=1,
            account_id=self.account,
            total_payments=1000,
            checkout_payment_method_id=self.payment_method,
            account_payment_ids=[self.account_payment.id],
            payment_event_ids=[self.payment_event],
            checkout_request_xid='test_xid',
        )

    def test_get_checkout_xid_by_paid_off_accout_payment_not_paid_parameter(self):
        result = get_checkout_xid_by_paid_off_accout_payment(False, self.account_payment)
        self.assertIsNone(result)

    def test_get_checkout_xid_by_paid_off_accout_payment_invalid_account_payment(self):
        result = get_checkout_xid_by_paid_off_accout_payment(True, self.account_payment_2)
        self.assertIsNone(result)

    def test_get_checkout_xid_by_paid_off_accout_payment(self):
        result = get_checkout_xid_by_paid_off_accout_payment(True, self.account_payment)
        self.assertEqual(result, self.checkout.checkout_request_xid)


class TestGetCheckoutExperienceSetting(TestCase):
    def setUp(self):
        self.account = AccountFactory(id=4001)
        self.loan = LoanFactory(account=self.account)
        self.loan_refinancing = LoanRefinancingRequestFactory(
            account=self.account, loan=self.loan, status='Approved'
        )
        self.account_payment = AccountPaymentFactory(
            id=4001,
            principal_amount=50000,
            interest_amount=5000,
            late_fee_amount=3500,
            paid_amount=10000,
            due_amount=10000,
        )
        self.experiment_setting = ExperimentSettingFactory(
            is_active=False,
            code=ExperimentConst.CHECKOUT_EXPERIENCE_EXPERIMENT,
            is_permanent=False,
            criteria={
                "account_id_tail": {
                    "control_group": [0, 2, 3],
                    "experiment_group_1": [4, 5, 6],
                    "experiment_group_2": [7, 8, 9, 1],
                }
            },
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.CHECKOUT_EXPERIENCE, is_active=True
        )

    def test_get_checkout_experience_setting_have_on_processed_refinancing(self):
        result = get_checkout_experience_setting(self.account.id)
        self.assertEqual(result[0], False)
        self.assertEqual(result[1], True)

    def test_get_checkout_experience_setting_not_active_experiment(self):
        self.loan_refinancing.status = 'Expired'
        self.loan_refinancing.save()
        result = get_checkout_experience_setting(self.account.id)
        self.assertEqual(result[0], True)
        self.assertEqual(result[1], True)

    def test_get_checkout_experience_setting(self):
        self.loan_refinancing.status = 'Expired'
        self.loan_refinancing.save()
        self.experiment_setting.is_active = True
        self.experiment_setting.is_permanent = True
        self.experiment_setting.save()
        result = get_checkout_experience_setting(self.account.id)
        self.assertEqual(result[0], True)
        self.assertEqual(result[1], False)


class TestUpdateCheckoutExperienceStatusToCancel(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_payment = AccountPaymentFactory()
        self.checkout = CheckoutRequestFactory(
            account_id=self.account, status='active', account_payment_ids=[self.account_payment.id]
        )

    def test_update_checkout_experience_status_to_cancel(self):
        update_checkout_experience_status_to_cancel(self.account.id)
        self.checkout.refresh_from_db()
        self.assertEqual(self.checkout.status, 'canceled')


class TestUpdateLatestPaymentMethod(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, account_lookup=AccountLookupFactory(name="JULO1"),
            app_version="8.19.1"
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.payment_method_dana = PaymentMethodFactory(
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.DANA,
            is_latest_payment_method=True,
            loan=None,
        )
        self.payment_method_bca = PaymentMethodFactory(
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.BCA,
            is_latest_payment_method=False,
            loan=None,
        )
        self.payback_transaction = PaybackTransactionFactory(
            customer=self.customer,
            account=self.account,
            payment_method=self.payment_method_bca,
            loan=None,
            payment=None,
        )

    def test_update_latest_payment_method(self):
        update_latest_payment_method(self.payback_transaction.id)

        updated_payment_method = PaymentMethod.objects.get(
            pk=self.payback_transaction.payment_method_id
        )
        self.assertTrue(updated_payment_method.is_latest_payment_method)
        self.payment_method_dana.refresh_from_db()
        self.assertFalse(self.payment_method_dana.is_latest_payment_method)

    @mock.patch('juloserver.account_payment.services.account_payment_related.logger.warning')
    def test_update_latest_payment_method_payback_transaction_not_found(self, mock_logger_warning):
        update_latest_payment_method(self.payback_transaction.id + 3145)

        mock_logger_warning.assert_called_with({
            "action": "juloserver.account_payment.services."
                      "account_payment_related.update_primary_payment_method",
            "message": "payback transaction not found",
            "payback_transaction_id": self.payback_transaction.id + 3145,
        })
        self.payment_method_dana.refresh_from_db()
        self.payment_method_bca.refresh_from_db()
        self.assertTrue(self.payment_method_dana.is_latest_payment_method)
        self.assertFalse(self.payment_method_bca.is_latest_payment_method)

    @mock.patch('juloserver.account_payment.services.account_payment_related.logger.warning')
    def test_update_latest_payment_method_already_latest_payment_method(self, mock_logger_warning):
        self.payback_transaction.payment_method.update_safely(is_latest_payment_method=True)
        update_latest_payment_method(self.payback_transaction.id)

        mock_logger_warning.assert_called_with({
            "action": "juloserver.account_payment.services."
                      "account_payment_related.update_primary_payment_method",
            "message": "already latest payment method",
            "account_id": self.account.id,
            "payback_transaction_id": self.payback_transaction.id,
        })
        self.payment_method_dana.refresh_from_db()
        self.assertTrue(self.payment_method_dana.is_latest_payment_method)

    @mock.patch('juloserver.account_payment.services.account_payment_related.logger.warning')
    def test_update_latest_payment_method_dana_payment_method_not_found(self, mock_logger_warning):
        self.payback_transaction.update_safely(payment_method=PaymentMethodFactory(
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.DANA_BILLER,
            is_latest_payment_method=False,
            loan=None,
        ))
        PaymentMethod.objects.filter(
            payment_method_code=PaymentMethodCodes.DANA,
            customer=self.customer
        ).delete()
        update_latest_payment_method(self.payback_transaction.id)

        mock_logger_warning.assert_called_with({
            "action": "juloserver.account_payment.services."
                      "account_payment_related.update_primary_payment_method",
            "message": "dana payment method not found",
            "account_id": self.account.id,
            "payback_transaction_id": self.payback_transaction.id,
        })
        self.payment_method_bca.refresh_from_db()
        self.assertFalse(self.payment_method_bca.is_latest_payment_method)
