import mock
from datetime import timedelta
from mock import patch


from django.utils import timezone
from django.test.testcases import TestCase, override_settings

from juloserver.julo.tests.factories import LoanFactory, ProductLineFactory, PaymentEventFactory, PaymentFactory
from .factories import (
    LoanRefinancingMainReasonFactory,
    LoanRefinancingFactory,
    LoanRefinancingRequestFactory,
    LoanRefinancingOfferFactory,
    CovidRefinancingFeatureSettingFactory,
    CollectionOfferExtensionConfigurationFactory,
    WaiverRequestFactory, LoanRefinancingScoreFactory)
from ..models import WaiverRequest
from ..services.loan_related import *
from ..services.loan_related2 import *
from ..constants import CovidRefinancingConst, NEW_WAIVER_APPROVER_GROUPS
from ...account.tests.factories import AccountFactory
from ...account_payment.tests.factories import AccountPaymentFactory


@override_settings(SUSPEND_SIGNALS=True)
class TestLoanServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localtime(timezone.now()).date()
        cls.loan = LoanFactory(loan_amount=9000000, loan_duration=4)
        cls.feature_settings = CovidRefinancingFeatureSettingFactory()
        cls.user = cls.loan.customer.user
        application = cls.loan.application
        application.product_line_id = 10
        application.save()
        cls.application = application
        cls.main_reason = LoanRefinancingMainReasonFactory()
        cls.loan_refinancing = LoanRefinancingFactory(
            loan=cls.loan,
            refinancing_request_date=today,
            refinancing_active_date=None)
        cls.waiver_request = WaiverRequestFactory()

    def setUp(self):
        CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=2,
            max_extension=3,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )
        CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=6,
            max_extension=4,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )
        CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=4,
            max_extension=4,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )
        LoanRefinancingMainReasonFactory(
            reason='Dirumahkan gaji minim',
            is_active=True,
        )
        self.loan.refresh_from_db()
        self.main_reason.refresh_from_db()
        self.loan_refinancing.refresh_from_db()

    def test_get_loan_from_application_id_success(self):
        loan = get_loan_from_application_id(self.application.id)
        self.assertEqual(loan.id, self.loan.id)

    def test_get_loan_from_application_id_application_id_not_found(self):
        application_id = 12313123132131
        loan = get_loan_from_application_id(application_id)
        self.assertEqual(False, loan)

    def test_get_current_payment_structures(self):
        payments = get_current_payment_structures(self.loan)

        for payment in payments:
            testRemainingPrincipal =  True if 'remaining_principal' in payment else False
            self.assertEqual(True, testRemainingPrincipal)

    @mock.patch('juloserver.loan_refinancing.services.loan_related.generate_new_tenure_extension_probabilities')
    def test_generate_new_tenure_offers_success(self, mock_data):
        today = timezone.localtime(timezone.now()).date()
        first_payment_due_date = today + timedelta(days=5)
        mock_data.return_value = 6
        tenure_dict = generate_new_tenure_offers(self.loan)
        is_tenure_dict = isinstance(tenure_dict, dict)
        tenure_extension_duration_list = [4, 5, 6]
        all_tenure_exists = True if all(
            key in tenure_dict for key in tenure_extension_duration_list)\
            else False
        self.assertEqual(first_payment_due_date, tenure_dict[4][0]['due_date'])
        self.assertEqual(True, is_tenure_dict)
        self.assertEqual(True, all_tenure_exists)

    def test_get_unpaid_payments_without_order_by(self):
        payments = get_unpaid_payments(self.loan)
        self.assertEqual(4, payments.count())

    def test_get_unpaid_payments_with_order_by(self):
        payments = get_unpaid_payments(self.loan, order_by='payment_number')
        self.assertEqual(4, payments.count())
        self.assertEqual(1, payments[0].payment_number)

    def test_get_sum_of_principal_paid_and_late_fee_amount_success(self):
        payments = get_unpaid_payments(self.loan)
        total_dict = get_sum_of_principal_paid_and_late_fee_amount(payments)
        mandatory_total_keys = [
            'paid_principal__sum',
            'paid_interest__sum',
            'installment_principal__sum',
            'installment_interest__sum',
            'late_fee_amount__sum']
        all_tenure_exists = True if all(
            key in total_dict for key in mandatory_total_keys)\
            else False

        self.assertEqual(True, all_tenure_exists)

    def test_get_unpaid_payment_due_date_probabilities_success(self):
        tenure_extension = 6
        unpaid_payments = get_unpaid_payments(self.loan, order_by='payment_number')
        due_date_list = get_unpaid_payment_due_date_probabilities(
            unpaid_payments,
            tenure_extension)
        self.assertEqual(6, len(due_date_list))

    def test_generate_new_tenure_extension_probabilities_not_found(self):
        loan_duration = 99
        new_tenure_duration = generate_new_tenure_extension_probabilities(loan_duration)
        self.assertEqual(102, new_tenure_duration)

    def test_generate_new_tenure_extension_probabilities_success(self):
        loan_duration = 4
        new_tenure_duration = generate_new_tenure_extension_probabilities(loan_duration)
        self.assertEqual(6, new_tenure_duration)

    def test_get_main_reason_obj(self):
        created_main_reason = self.main_reason
        main_reason = get_main_reason_obj(created_main_reason.reason)
        self.assertEqual(created_main_reason.reason, main_reason.reason)

    def test_get_sub_reason_obj(self):
        created_sub_reason = self.main_reason.loanrefinancingsubreason_set.last()
        sub_reason = get_sub_reason_obj(created_sub_reason.reason)
        self.assertEqual(created_sub_reason.reason, sub_reason.reason)

    @mock.patch('juloserver.loan_refinancing.services.loan_related.get_main_reason_obj')
    @mock.patch('juloserver.loan_refinancing.services.loan_related.get_sub_reason_obj')
    def test_construct_refinancing_request_dict_success(self, mock1, mock2):
        mock1.return_value = self.main_reason
        mock2.return_value = self.main_reason.loanrefinancingsubreason_set.last()
        data = {
            'loan': self.loan,
            'loan_duration': 6,
            'tenure_extension': 4,
            'due_amount': 200000,
            'late_fee_amount': 10000,
            'dpd': 10,
            'additional_reason': 'any random reason',
            'main_reason': 'faked_reason',
            'sub_reason': 'faked_reason'
        }

        today = timezone.localtime(timezone.now()).date()
        expected_dict = {
            'loan': data['loan'],
            'original_tenure': data['loan_duration'],
            'tenure_extension': data['tenure_extension'],
            'new_installment': data['due_amount'],
            'refinancing_request_date': today,
            'status': LoanRefinancingStatus.REQUEST,
            'total_latefee_discount': data['late_fee_amount'],
            'loan_level_dpd': data['dpd'],
            'loan_refinancing_main_reason': self.main_reason,
            'loan_refinancing_sub_reason': self.main_reason.loanrefinancingsubreason_set.last(),
            'additional_reason': data['additional_reason']
        }
        request_dict = construct_refinancing_request_dict(data)
        list_mandatory_keys = list(expected_dict.keys())
        all_key_exists = True if all(
            key in request_dict for key in list_mandatory_keys)\
            else False
        self.assertEqual(True, all_key_exists)

    @mock.patch('juloserver.loan_refinancing.services.loan_related.get_main_reason_obj')
    @mock.patch('juloserver.loan_refinancing.services.loan_related.get_sub_reason_obj')
    def test_construct_refinancing_request_dict_success_failed_missing_key(self, mock1, mock2):
        mock1.return_value = self.main_reason
        mock2.return_value = self.main_reason.loanrefinancingsubreason_set.last()
        data = {
            'loan': self.loan,
            'loan_duration': 6,
            'due_amount': 200000,
            'late_fee_amount': 10000,
            'dpd': 10,
            'additional_reason': 'any random reason',
            'main_reason': 'faked_reason',
            'sub_reason': 'faked_reason'
        }
        request_dict = construct_refinancing_request_dict(data)
        self.assertEqual(False, request_dict)

    def test_get_loan_refinancing_request_info(self):
        loan_refinancing = get_loan_refinancing_request_info(self.loan)
        self.assertEqual(self.loan.id, loan_refinancing.loan.id)
        self.assertEqual(LoanRefinancingStatus.REQUEST, loan_refinancing.status)

    @patch('juloserver.loan_refinancing.services.loan_related.upload_addendum_pdf_to_oss')
    @patch('juloserver.loan_refinancing.services.loan_related.send_loan_refinancing_success_email')
    @patch('juloserver.loan_refinancing.services.loan_related.create_payment_event_to_waive_late_fee')
    def test_activate_loan_refinancing(self, mocking_payment_event, mock_send_loan, mock_upload):
        tested_payment = self.loan.payment_set.first()
        mocking_payment_event.return_value = PaymentEventFactory(payment=tested_payment, event_type='payment')
        result = activate_loan_refinancing(tested_payment, self.loan_refinancing)
        self.assertEqual(True, result)

    def test_mark_old_payments_as_restructured_success(self):
        ordered_unpaid_payments = get_unpaid_payments(self.loan, order_by='payment_number')
        mark_old_payments_as_restructured(ordered_unpaid_payments)
        self.assertEqual(True, ordered_unpaid_payments[0].is_restructured)

    def test_create_loan_refinancing_payments_based_on_new_tenure_success(self):
        today = timezone.localtime(timezone.now()).date()
        mocked_data = [
            {'payment_number': 5, 'due_date': today, 'due_amount': 10000,
             'principal_amount': 100000, 'interest_amount': 200000},
            {'payment_number': 6, 'due_date': today, 'due_amount': 10000,
             'principal_amount': 100000, 'interest_amount': 200000}]
        create_loan_refinancing_payments_based_on_new_tenure(mocked_data, self.loan)
        payments = self.loan.payment_set.all()
        self.assertEqual(6, payments.count())

    def test_construct_tenure_probabilities_success_when_amount_is_not_divided_out_by_tenure(self):
        payments = get_unpaid_payments(self.loan, order_by='payment_number')
        result_dict = construct_tenure_probabilities(payments, 6)
        list_mandatory_keys = ['payment_number', 'principal_amount',
                               'due_amount', 'interest_amount', 'due_date']
        all_key_exists = True if all(
            key in result_dict[6][-1] for key in list_mandatory_keys)\
            else False
        self.assertEqual(4, len(list(result_dict.keys())))
        self.assertEqual(220000, result_dict['late_fee_amount'])
        # each payment.installment_principal is 2025000*4/6=1350000
        self.assertEqual(1350000, result_dict[6][-1]['principal_amount'])
        # each payment.installment_interest is 225000*4/6=150000
        self.assertEqual(150000, result_dict[6][-1]['interest_amount'])
        self.assertEqual(True, all_key_exists)

    @patch('juloserver.loan_refinancing.tasks.send_email_covid_refinancing_opt')
    def test_store_covid_refinancing_data(self, mock_task):
        feature_params = self.feature_settings.parameters
        valid_data = [{
            "email_address": "test@mail.com",
            "loan_id": self.loan.id,
            "new_affordability": None,
            "new_income": None,
            "new_expense": None,
            "tenure_extension": None,
            "new_employment_status": "tetap bekerja, gaji minim",
            "covid_product": None
        }]
        store_covid_refinancing_data(valid_data, feature_params)

    def test_regenerate_loan_refinancing_offer(self):
        loan_refinancing_request = LoanRefinancingRequestFactory(
            loan=self.loan,
            status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer,
            new_income=5000000,
            new_expense=1000000
        )
        LoanRefinancingOfferFactory(
            loan_refinancing_request=loan_refinancing_request,
            product_type="R1"
        )
        LoanRefinancingOfferFactory(
            loan_refinancing_request=loan_refinancing_request,
            product_type="R4"
        )
        regenerate_loan_refinancing_offer(self.loan)

    def test_success_get_data_for_agent_portal(self):
        param = {}
        data = get_data_for_agent_portal(param, self.loan.id)
        self.assertEqual(True, data['show'])

    def test_success_get_data_for_agent_portal_pede(self):
        self.application.product_line_id = ProductLineCodes.PEDEMTL1
        self.application.save()
        ProductLineFactory(product_line_code=ProductLineCodes.PEDEMTL1)

        param = {}
        data = get_data_for_agent_portal(param, self.loan.id)
        self.assertEqual(True, data['show'])

    def test_success_get_data_for_agent_portal_laku6(self):
        self.application.product_line_id = ProductLineCodes.LAKU1
        self.application.save()
        param = {}
        data = get_data_for_agent_portal(param, self.loan.id)
        self.assertEqual(True, data['show'])

    def test_success_get_data_for_agent_portal_icare(self):
        self.application.product_line_id = ProductLineCodes.ICARE1
        self.application.save()
        param = {}
        data = get_data_for_agent_portal(param, self.loan.id)
        self.assertEqual(True, data['show'])

    def test_success_get_data_for_agent_portal_selected(self):
        LoanRefinancingScoreFactory(loan=self.loan, application_id=self.loan.application.id)
        LoanRefinancingRequestFactory(
            loan=self.loan,
            status=CovidRefinancingConst.STATUSES.approved,
            new_income=5000000,
            new_expense=1000000,
            product_type='R4'
        )
        param = {}
        data = get_data_for_agent_portal(param, self.loan.id)
        self.assertEqual(True, data['show'])

    def test_get_loan_ids_for_bucket_tree(self):
        groups = [item for item in NEW_WAIVER_APPROVER_GROUPS if item not in TOP_LEVEL_WAIVER_APPROVERS]
        loan = get_loan_ids_for_bucket_tree(groups)
        self.assertIsNotNone(loan)

    def test_get_loan_ids_for_bucket_tree_spv(self):
        groups = [WAIVER_SPV_APPROVER_GROUP]
        loan = get_loan_ids_for_bucket_tree(groups)
        self.assertIsNotNone(loan)

    def test_get_loan_ids_for_bucket_tree_coll_head(self):
        groups = [WAIVER_COLL_HEAD_APPROVER_GROUP]
        loan = get_loan_ids_for_bucket_tree(groups)
        self.assertIsNotNone(loan)

    def test_get_loan_ids_for_bucket_tree_fraud(self):
        groups = [WAIVER_FRAUD_APPROVER_GROUP]
        loan = get_loan_ids_for_bucket_tree(groups)
        self.assertIsNotNone(loan)

    def test_get_loan_ids_for_bucket_tree_ops_tl(self):
        groups = [WAIVER_OPS_TL_APPROVER_GROUP]
        loan = get_loan_ids_for_bucket_tree(groups)
        self.assertIsNotNone(loan)


@override_settings(SUSPEND_SIGNALS=True)
class TestLoanEligibleForCashback(TestCase):
    def setUp(self):
        self.account = AccountFactory(
            id=1998
        )
        self.account_payment = AccountPaymentFactory(
            account=self.account
        )
        self.loan = LoanFactory(
            account=self.account,
            is_restructured=True
        )
        PaymentFactory(
            loan=self.loan,
            account_payment=self.account_payment
        )
        self.payment = self.loan.payment_set.first()
        self.loan_not_restructured = LoanFactory(
            account=self.account,
            is_restructured=False
        )
        PaymentFactory(
            loan=self.loan_not_restructured,
            account_payment=self.account_payment
        )
        self.payment_not_restructured = self.loan_not_restructured.payment_set.first()


class TestGetOnGoingRefinancingbyAccountId(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account,
        )

    def test_there_on_going_refinancing(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.approved
        self.loan_refinancing_request.save()

        result = is_cashback_blocked_by_collection_repayment_reason(self.account.id)
        self.assertEqual(result, True)

    def test_there_no_on_going_refinancing(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.activated
        self.loan_refinancing_request.save()

        result = is_cashback_blocked_by_collection_repayment_reason(self.account.id)
        self.assertEqual(result, False)
