from mock import patch

from django.test.testcases import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account.models import ExperimentGroup

from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.julo.constants import ExperimentConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    ExperimentSettingFactory,
)
from juloserver.julo.exceptions import JuloException

from juloserver.ovo.tests.factories import OvoRepaymentTransactionFactory
from juloserver.ovo.tasks import (
    send_payment_success_event_to_firebase,
    store_experiment_data,
)
from juloserver.ovo.constants import OvoPaymentStatus


class TestSendPaymentSuccessEventToFirebase(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account
        )
        self.account_payment = AccountPaymentFactory(account=self.account, account_payment_xid=12)
        self.ovo_repayment_transaction = OvoRepaymentTransactionFactory(
            account_payment_xid=self.account_payment,
            transaction_id=1,
            amount=1000,
        )

    @patch('juloserver.ovo.tasks.send_event_to_ga_task_async.apply_async')
    def test_send_payment_success_event_to_firebase_should_success(
            self, mock_send_event_to_ga_task_async
    ):
        send_payment_success_event_to_firebase(
            transaction_id=self.ovo_repayment_transaction.transaction_id,
        )
        self.assertTrue(
            mock_send_event_to_ga_task_async.called
        )

    @patch('juloserver.ovo.tasks.send_event_to_ga_task_async.apply_async')
    def test_send_payment_success_event_to_firebase_should_failed_when_invalid_transaction_id(
            self, mock_send_event_to_ga_task_async
    ):
        send_payment_success_event_to_firebase(
            transaction_id=2,
        )
        self.assertFalse(
            mock_send_event_to_ga_task_async.called
        )


class TestStoreExperimentData(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.OVO_NEW_FLOW_EXPERIMENT,
            is_active=True,
        )

    def test_store_experiment_data_should_success_created_control(self):
        store_experiment_data(self.customer.id, 1)
        experiment_group = ExperimentGroup.objects.first()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, 'control')
        # test add store same group
        store_experiment_data(self.customer.id, 1)
        self.assertEqual(ExperimentGroup.objects.all().count(), 1)
        # test add store different group
        store_experiment_data(self.customer.id, 2)
        self.assertEqual(ExperimentGroup.objects.all().count(), 2)

    def test_store_experiment_data_should_success_created_experiment(self):
        store_experiment_data(self.customer.id, 2)
        experiment_group = ExperimentGroup.objects.first()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, 'experiment')

    def test_store_experiment_data_should_failed_when_invalid_flow_id(self):
        with self.assertRaises(JuloException):
            store_experiment_data(self.customer.id, 82734)
            store_experiment_data(self.customer.id, None)
            store_experiment_data(self.customer.id, '82734')
        self.assertFalse(ExperimentGroup.objects.exists())

    def test_store_experiment_data_should_failed_when_experiment_is_turned_off(self):
        self.experiment_setting.update_safely(is_active=False)
        self.experiment_setting.refresh_from_db()
        store_experiment_data(self.customer.id, 1)
        self.assertFalse(ExperimentGroup.objects.exists())
