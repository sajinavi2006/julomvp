import datetime
from unittest import mock
from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory, AccountPropertyFactory, \
    AccountLimitFactory
from juloserver.early_limit_release.constants import (
    ExperimentOption,
    ReleaseTrackingType,
    FeatureNameConst
)
from juloserver.early_limit_release.exceptions import PaymentNotMatchException
from juloserver.early_limit_release.tasks import (
    check_and_release_early_limit_per_loan, rollback_early_limit_release_per_loan
)
from juloserver.early_limit_release.tests.factories import (
    EarlyReleaseExperimentFactory,
    ReleaseTrackingFactory,
    EarlyReleaseLoanMappingFactory,
)
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    FDCInquiryFactory,
    FDCInquiryCheckFactory,
    FDCInquiryLoanFactory,
    FeatureSettingFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLineFactory,
    LoanHistoryFactory,
)
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes
from juloserver.julo.models import Payment
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.early_limit_release.models import (
    ReleaseTracking,
    ReleaseTrackingHistory,
)


class TestCheckAndReleaseEarlyLimit(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account.id = int(str(self.account.id) + '00')
        self.account.save()
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.save()
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=5000000)

        self.loan0 = LoanFactory(
            account=self.account,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=220),
            loan_duration=5,
            fund_transfer_ts=datetime.datetime.now(),
        )
        self.loan0.save()
        init_payment = Payment.objects.filter(loan=self.loan0, payment_number=1).first()
        init_payment.update_safely(paid_date=datetime.datetime(2023, 3, 4).date())

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=220),
            loan_duration=6,
        )
        self.loan.save()
        self.loan_history = LoanHistoryFactory(
            loan=self.loan, status_old=220, status_new=220
        )
        self.payments = Payment.objects.filter(loan=self.loan)

        self.experiment = EarlyReleaseExperimentFactory(
            option=ExperimentOption.OPTION_2,
            criteria={
                'last_cust_digit': {'from': '00', 'to': '19'},
                'loan_duration_payment_rules': {'5': 3, '6': 3, '9': 2},
            }
        )

        self.fdc_inquiry = FDCInquiryFactory()
        self.fdc_inquiry_check = FDCInquiryCheckFactory()
        self.fdc_inquiry_loan = FDCInquiryLoanFactory()
        self.feature_setting = FeatureSettingFactory(
            feature_name='fdc_inquiry_check', is_active=True
        )
        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = datetime.date(2020, 1, 1)
        self.fdc_inquiry.save()

        self.fdc_inquiry_check.min_threshold = 0.8
        self.fdc_inquiry_check.max_threshold = 1.1
        self.fdc_inquiry_check.is_active = True

        FeatureSettingFactory(
            feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE, is_active=True, parameters={
                'minimum_used_limit': 50
            }
        )

    def test_check_and_release_success(self):
        self.payments.filter(payment_number__lte=4).update(
            due_amount=0,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME),
        )
        payment_ids = list(self.payments.order_by('payment_number').values_list('id', flat=True))

        check_and_release_early_limit_per_loan(loan_payments={
            'loan_id': self.loan.id, 'payment_ids': payment_ids[:4]
        })

        tracking_count = ReleaseTracking.objects.filter(
            loan_id=self.loan.id, type=ReleaseTrackingType.EARLY_RELEASE
        ).count()
        # Because we use Option 2, so we do early release from 3rd payment
        # Expected: payment_id: 8, 9
        self.assertEqual(tracking_count, 2)

    # @mock.patch('juloserver.early_limit_release.services.execute_after_transaction_safely')
    # @mock.patch('juloserver.early_limit_release.services.send_user_attributes_to_moengage_for_early_limit_release')
    # def test_check_and_release_fail_1(self, mock_send_moengage, mock_execute_after_transaction_safely):
    #     self.payments.filter(payment_number__lte=3).update(
    #         payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
    #     )
    #     payment_ids = list(self.payments.order_by('payment_number').values_list('id', flat=True))
    #     check_and_release_early_limit_per_loan(loan_payments={
    #         'loan_id': self.loan.id, 'payment_ids': payment_ids[:3]
    #     })
    #
    #     check_and_release_early_limit_per_loan(loan_payments={
    #         'loan_id': self.loan.id, 'payment_ids': payment_ids[:3]
    #     })
    #     tracking_count = ReleaseTracking.objects.filter(
    #         loan_id=self.loan.id, type=ReleaseTrackingType.EARLY_RELEASE
    #     ).count()
    #     self.assertEqual(tracking_count, 1)
    #
    # @mock.patch('juloserver.early_limit_release.services.execute_after_transaction_safely')
    # @mock.patch('juloserver.early_limit_release.services.send_user_attributes_to_moengage_for_early_limit_release')
    # def test_check_and_release_fail_2(self, mock_send_moengage, mock_execute_after_transaction_safely):
    #     self.payments.filter(payment_number__lte=5).update(
    #         payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
    #     )
    #     payment_ids = list(self.payments.order_by('payment_number').values_list('id', flat=True))
    #     check_and_release_early_limit_per_loan(loan_payments={
    #         'loan_id': self.loan.id, 'payment_ids': payment_ids[:3]
    #     })
    #
    #     check_and_release_early_limit_per_loan(loan_payments={
    #         'loan_id': self.loan.id, 'payment_ids': payment_ids[:5]
    #     })
    #
    #     tracking_count = ReleaseTracking.objects.filter(
    #         loan_id=self.loan.id, type=ReleaseTrackingType.EARLY_RELEASE
    #     ).count()
    #     self.assertEqual(tracking_count, 3)

    @mock.patch('juloserver.early_limit_release.tasks.send_user_attributes_to_moengage_for_early_limit_release')
    def test_check_and_release_fail_3(self, mock_send_moengage):
        self.payments.filter(payment_number__lte=3).update(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        )
        payment_ids = list(self.payments.order_by('payment_number').values_list('id', flat=True))
        with self.assertRaises(PaymentNotMatchException):
            check_and_release_early_limit_per_loan(loan_payments={
                'loan_id': self.loan0.id, 'payment_ids': payment_ids[:3]
            })
            tracking = ReleaseTracking.objects.filter(
                loan_id=self.loan.id, payment_id=payment_ids[2], type=ReleaseTrackingType.EARLY_RELEASE
            )
            self.assertFalse(tracking.exists())

    @mock.patch('juloserver.early_limit_release.services.get_julo_sentry_client')
    def test_check_loan_release_manually(self, mock_sentry):
        self.payments.filter(payment_number__lte=5).update(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        )
        payment_ids = list(self.payments.order_by('payment_number').values_list('id', flat=True))
        EarlyReleaseLoanMappingFactory(
            loan=self.loan, experiment=self.experiment, is_auto=False
        )

        with mock.patch('logging.Logger.info') as mock_info:
            check_and_release_early_limit_per_loan(loan_payments={
                'loan_id': self.loan.id, 'payment_ids': payment_ids[:5]
            })
            mock_info.assert_called_once()


class TestRollbackLimit(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.save()
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=9000000,
            used_limit=9000000,
            available_limit=50000
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=220),
            loan_duration=5
        )
        self.loan_history = LoanHistoryFactory(
            loan=self.loan, status_old=220, status_new=220
        )
        self.payments = Payment.objects.filter(loan=self.loan)
        self.experiment = EarlyReleaseExperimentFactory(
            option=ExperimentOption.OPTION_2,
            criteria={
                'last_cust_digit': {'from': '00', 'to': '19'},
                'loan_duration_payment_rules': {'5': 3, '6': 3, '9': 2},
            }
        )

    @mock.patch('juloserver.early_limit_release.tasks.sentry_client')
    def test_invalid_loan_payments_input(self, mock_sentry_client):
        # missing input
        input_params = [
            {
                "payment_ids": [0],
            }
        ]
        with self.assertRaises(AttributeError):
            rollback_early_limit_release_per_loan(input_params)
            mock_sentry_client.captureException.assert_called()

    def test_rollback_with_available_limit_lt_release_limit_amount(self):
        self.payments.filter(payment_number__lte=4).update(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        payment = self.payments.get(payment_number=3)
        ReleaseTrackingFactory(
            limit_release_amount=100000, payment=payment, loan=self.loan, account=self.account,
            type=ReleaseTrackingType.EARLY_RELEASE
        )
        self.account_limit.update_safely(available_limit=50000)  # use limit after release
        input_params = {
            "loan_id": self.loan.id,
            "payment_ids": [payment.id],
        }

        rollback_early_limit_release_per_loan(input_params)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.available_limit, -50000)

    @mock.patch('juloserver.early_limit_release.tasks.send_user_attributes_to_moengage_for_early_limit_release')
    def test_rollback_with_release_limit_amount_success(self, mock_send_moengage):
        self.account_limit.update_safely(available_limit=200000)
        self.payments.filter(payment_number__lte=4).update(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        payment = self.payments.get(payment_number=3)
        ReleaseTrackingFactory(
            limit_release_amount=100000, payment=payment, loan=self.loan, account=self.account,
            type=ReleaseTrackingType.EARLY_RELEASE
        )
        input_params = {
            "loan_id": self.loan.id,
            "payment_ids": [payment.id],
        }

        rollback_early_limit_release_per_loan(input_params)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.available_limit, 100000)
        reverse_tracking = ReleaseTracking.objects.get(
            payment_id=payment.id, loan_id=self.loan.id, limit_release_amount=0,
            account_id=self.account.id, type=ReleaseTrackingType.EARLY_RELEASE
        )
        self.assertIsNotNone(reverse_tracking)
        mock_send_moengage.delay.assert_called()

    @mock.patch('juloserver.early_limit_release.tasks.send_user_attributes_to_moengage_for_early_limit_release')
    def test_rollback_success_with_extra_release(self, mock_send_moengage):
        loan_status_220 = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.loan.update_safely(loan_status=loan_status_220)
        self.loan_history = LoanHistoryFactory(
            loan=self.loan, status_old=250, status_new=220
        )
        self.payments.filter(payment_number=5).update(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        last_payment = self.payments.get(payment_number=5)
        ReleaseTrackingFactory(
            limit_release_amount=100000, payment=last_payment, loan=self.loan, account=self.account,
            type=ReleaseTrackingType.EARLY_RELEASE
        )
        ReleaseTrackingFactory(
            limit_release_amount=50000, loan=self.loan, account=self.account,
            type=ReleaseTrackingType.LAST_RELEASE
        )
        input_params = {
            'loan_id': self.loan.id, 'payment_ids': [last_payment.id]
        }
        rollback_early_limit_release_per_loan(input_params)
        reverse_tracking = ReleaseTracking.objects.get(
            payment_id=last_payment.id, loan_id=self.loan.id, limit_release_amount=0,
            account_id=self.account.id, type=ReleaseTrackingType.EARLY_RELEASE
        )
        self.assertEqual(reverse_tracking.limit_release_amount, 0)
        self.assertEqual(reverse_tracking.type, ReleaseTrackingType.EARLY_RELEASE)
        last_tracking = ReleaseTracking.objects.get(
            loan_id=self.loan.id, limit_release_amount=0,
            account_id=self.account.id, type=ReleaseTrackingType.LAST_RELEASE
        )
        self.assertEqual(last_tracking.limit_release_amount, 0)
        self.assertEqual(last_tracking.type, ReleaseTrackingType.LAST_RELEASE)

    def test_rollback_has_no_last_release_in_tracking(self):
        loan_status_220 = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.loan.update_safely(loan_status=loan_status_220)
        self.account_limit.update_safely(available_limit=10000000)
        old_available_limit = 10000000
        self.loan_history = LoanHistoryFactory(
            loan=self.loan, status_old=250, status_new=220
        )
        self.payments.filter(payment_number__in=[3, 4, 5]).update(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        payment_3 = self.payments.get(payment_number=3)
        ReleaseTrackingFactory(
            limit_release_amount=1620000, payment=payment_3, loan=self.loan, account=self.account,
            type=ReleaseTrackingType.EARLY_RELEASE
        )
        payment_4 = self.payments.get(payment_number=4)
        ReleaseTrackingFactory(
            limit_release_amount=1620000, payment=payment_4, loan=self.loan, account=self.account,
            type=ReleaseTrackingType.EARLY_RELEASE
        )
        payment_5 = self.payments.get(payment_number=5)
        ReleaseTrackingFactory(
            limit_release_amount=1620000, payment=payment_5, loan=self.loan, account=self.account,
            type=ReleaseTrackingType.EARLY_RELEASE
        )
        # payment 3,4,5 released
        # loan_amount = 9.000.000
        # rollback payment 5 => 1.620.000
        input_params = {
            'loan_id': self.loan.id, 'payment_ids': [payment_5.id]
        }
        rollback_early_limit_release_per_loan(input_params)
        self.account_limit.refresh_from_db()
        last_release = 9000000 - 1620000 * 3
        new_available_limit = old_available_limit - last_release - 1620000
        db_available_limit = self.account_limit.available_limit
        self.assertEqual(db_available_limit, new_available_limit)

        release_tracking = ReleaseTracking.objects.get(payment_id=payment_5.id)
        tracking_history = ReleaseTrackingHistory.objects.get(release_tracking=release_tracking)
        self.assertEqual(tracking_history.value_old, '1620000')
        self.assertEqual(tracking_history.value_new, '0')
        self.assertEqual(tracking_history.field_name, 'limit_release_amount')
