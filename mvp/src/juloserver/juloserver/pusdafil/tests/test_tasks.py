from datetime import timedelta

import mock
import pytest
from django.test.testcases import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Application
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationJ1Factory,
    CleanLoanFactory,
    FeatureSettingFactory,
    LoanFactory,
    PaymentEventFactory,
    PaymentFactory,
    StatusLookupFactory,
)
from juloserver.pusdafil.tasks import (
    task_daily_activate_pusdafil,
    task_daily_sync_pusdafil_loan,
    task_daily_sync_pusdafil_payment,
    task_report_new_application_registration,
    task_report_new_borrower_registration,
    task_report_new_lender_registration,
    task_report_new_loan_approved,
    task_report_new_loan_payment_creation,
    task_report_new_loan_registration,
    task_report_new_user_registration,
)


@pytest.mark.django_db
class TestFuncPusdafilTasks(TestCase):
    def setUp(self):
        pass

    @mock.patch("juloserver.pusdafil.services.PusdafilService.report_new_user_registration")
    def test_task_report_new_user_registration(self, mocked_pusdafil_service):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        customer_id = 1

        task_report_new_user_registration(customer_id)

        mocked_pusdafil_service.assert_called_with(customer_id, False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.report_new_lender_registration")
    def test_task_report_new_lender_registration(self, mocked_pusdafil_service):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        lender_id = 2

        task_report_new_lender_registration(lender_id)

        mocked_pusdafil_service.assert_called_with(lender_id)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.report_new_borrower_registration")
    def test_task_report_new_borrower_registration(self, mocked_pusdafil_service):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        customer_id = 3

        task_report_new_borrower_registration(customer_id)

        mocked_pusdafil_service.assert_called_with(customer_id, False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.report_new_application_registration")
    def test_task_report_new_application_registration(self, mocked_pusdafil_service):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        application_id = 4

        task_report_new_application_registration(application_id)

        mocked_pusdafil_service.assert_called_with(application_id, False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.report_new_loan_registration")
    def test_task_report_new_loan_registration(self, mocked_pusdafil_service):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        loan_id = 5

        task_report_new_loan_registration(loan_id)

        mocked_pusdafil_service.assert_called_with(loan_id, False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.report_new_loan_approved")
    def test_task_report_new_loan_creation(self, mocked_pusdafil_service):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        loan_id = 6

        task_report_new_loan_approved(loan_id)

        mocked_pusdafil_service.assert_called_with(loan_id, False)

    @mock.patch("juloserver.pusdafil.services.PusdafilService.report_new_loan_payment_creation")
    def test_task_report_new_loan_payment_creation(self, mocked_pusdafil_service):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil',
        )
        payment_id = 7

        task_report_new_loan_payment_creation(payment_id)

        mocked_pusdafil_service.assert_called_with(payment_id)


@mock.patch('juloserver.pusdafil.tasks.task_daily_sync_pusdafil_loan.delay')
@mock.patch('juloserver.pusdafil.tasks.task_daily_sync_pusdafil_payment.delay')
class TestTaskDailyActivatePusdafil(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            is_active=False,
            feature_name=FeatureNameConst.PUSDAFIL,
        )

    @override_settings(ENVIRONMENT='testing')
    def test_daily_activate_pusdafil_non_prod_setting(self, mock_daily_payment, mock_daily_loan):
        task_daily_activate_pusdafil()

        self.setting.refresh_from_db()
        self.assertTrue(self.setting.is_active)

        mock_daily_loan.assert_not_called()
        mock_daily_payment.assert_not_called()

    @override_settings(ENVIRONMENT='prod')
    def test_daily_activate_pusdafil_prod_setting(self, mock_daily_payment, mock_daily_loan):
        task_daily_activate_pusdafil()

        self.setting.refresh_from_db()
        self.assertTrue(self.setting.is_active)

        mock_daily_loan.assert_called_once_with(7)
        mock_daily_payment.assert_called_once_with(7)


@mock.patch('juloserver.pusdafil.tasks.bunch_of_loan_creation_tasks.delay')
class TestTaskDailySyncPusdafilLoan(TestCase):
    def create_account_loan_by_date(self, datetime, total_loan=1, **loan_data):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime
            application = ApplicationJ1Factory(
                application_status=StatusLookupFactory(status_code=190),
            )
            batch_data = {}
            batch_data.update(
                customer=application.customer,
                account=application.account,
                application=None,
                loan_status=StatusLookupFactory(status_code=220),
            )
            batch_data.update(**loan_data)
            return CleanLoanFactory.create_batch(
                total_loan,
                **batch_data,
            )

    def create_application_loan_by_date(self, datetime, total_loan=1, **loan_data):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime
            application = ApplicationJ1Factory(
                application_status=StatusLookupFactory(status_code=180),
            )
            batch_data = {}
            batch_data.update(
                customer=application.customer,
                application=application,
                account=None,
                loan_status=StatusLookupFactory(status_code=220),
            )
            batch_data.update(**loan_data)
            return CleanLoanFactory.create_batch(
                total_loan,
                **batch_data,
            )

    def test_account_based_loans(self, mock_loan_creation_task):
        now = timezone.now()
        today_loan = self.create_account_loan_by_date(now)[0]
        prev_day_loan = self.create_account_loan_by_date(now - timedelta(days=1))[0]

        # skipped loans
        self.create_account_loan_by_date(now, loan_status=StatusLookupFactory(status_code=212))
        self.create_account_loan_by_date(now, loan_status=StatusLookupFactory(status_code=2181))
        self.create_account_loan_by_date(now - timedelta(days=2))

        task_daily_sync_pusdafil_loan(1)

        self.assertEqual(2, mock_loan_creation_task.call_count)
        mock_loan_creation_task.has_calls(
            any_order=True,
            calls=[
                mock.call(
                    user_id=today_loan.customer.user_id,
                    customer_id=today_loan.customer_id,
                    application_id=Application.objects.get(customer_id=today_loan.customer_id).id,
                    loan_id=today_loan.id,
                ),
                mock.call(
                    user_id=prev_day_loan.customer.user_id,
                    customer_id=prev_day_loan.customer_id,
                    application_id=Application.objects.get(customer_id=prev_day_loan.customer_id).id,
                    loan_id=prev_day_loan.id,
                ),
            ]
        )

    def test_application_based_loans(self, mock_loan_creation_task):
        now = timezone.now()
        today_loan = self.create_application_loan_by_date(now)[0]
        prev_day_loan = self.create_application_loan_by_date(now - timedelta(days=1))[0]

        # skipped loans
        self.create_application_loan_by_date(now, loan_status=StatusLookupFactory(status_code=212))
        self.create_application_loan_by_date(now, loan_status=StatusLookupFactory(status_code=2181))
        self.create_application_loan_by_date(now - timedelta(days=2))

        task_daily_sync_pusdafil_loan(1)

        self.assertEqual(2, mock_loan_creation_task.call_count)
        mock_loan_creation_task.has_calls(
            any_order=True,
            calls=[
                mock.call(
                    user_id=today_loan.customer.user_id,
                    customer_id=today_loan.customer_id,
                    application_id=Application.objects.get(customer_id=today_loan.customer_id).id,
                    loan_id=today_loan.id,
                ),
                mock.call(
                    user_id=prev_day_loan.customer.user_id,
                    customer_id=prev_day_loan.customer_id,
                    application_id=Application.objects.get(customer_id=prev_day_loan.customer_id).id,
                    loan_id=prev_day_loan.id,
                ),
            ]
        )


@mock.patch('juloserver.pusdafil.tasks.task_report_new_loan_payment_creation.delay')
class TestTaskDailySyncPusdafilPayment(TestCase):
    def create_payment_by_date(self, datetime, total_data=1, **model_data):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime
            batch_data = {}
            batch_data.update(
                loan=CleanLoanFactory(),
                due_amount=0,
                payment_status=StatusLookupFactory(status_code=330),
            )
            batch_data.update(**model_data)
            return PaymentFactory.create_batch(
                total_data,
                **batch_data,
            )

    def test_daily_task(self, mock_payment_creation_task):
        now = timezone.now()
        today_event = self.create_payment_by_date(now)[0]
        prev_day_event = self.create_payment_by_date(now - timedelta(days=1))[0]

        # skipped loans
        self.create_payment_by_date(now, payment_status=StatusLookupFactory(status_code=310))
        self.create_payment_by_date(now, due_amount=10)
        self.create_payment_by_date(now - timedelta(days=2))

        task_daily_sync_pusdafil_payment(1)

        self.assertEqual(2, mock_payment_creation_task.call_count)
        mock_payment_creation_task.has_calls(
            any_order=True,
            calls=[
                mock.call(today_event.id),
                mock.call(prev_day_event.id),
            ]
        )
