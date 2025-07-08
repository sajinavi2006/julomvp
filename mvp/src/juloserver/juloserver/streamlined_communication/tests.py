from django.test import TestCase
from datetime import timedelta, datetime

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountPropertyFactory,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tests.factories import ExperimentSettingFactory
from juloserver.streamlined_communication.services import \
    exclude_experiment_excellent_customer_from_robocall


class TestExcellentCustomerExperiment(TestCase):
    def setUp(self):
        self.today_date = datetime.today().date()
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.EXCELLENT_CUSTOMER_EXPERIMENT,
            start_date=self.today_date,
            end_date=self.today_date + timedelta(days=50),
            is_active=False,
            is_permanent=True,
            criteria={"account_id": "#digit:2:0,1,2,3,4"}
        )

    def test_exclude_excellent_customer_from_robocall(self):
        experiment_account = AccountFactory(id=999889913)
        AccountPropertyFactory(account=experiment_account)
        control_account = AccountFactory(id=999889961)
        AccountPropertyFactory(account=control_account)
        experiment_account_payment = AccountPaymentFactory(account=experiment_account)
        paid_experiment_account_payment = AccountPaymentFactory(
            account=experiment_account, due_amount=0, paid_date=self.today_date, paid_amount=20000,
            status_id=PaymentStatusCodes.PAID_ON_TIME
        )
        control_account_payment = AccountPaymentFactory(account=control_account)
        paid_control_account_payment = AccountPaymentFactory(
            account=control_account, due_amount=0, paid_date=self.today_date, paid_amount=20000,
            status_id=PaymentStatusCodes.PAID_ON_TIME
        )
        account_payments = AccountPayment.objects.filter(
            id__in=[experiment_account_payment.id, control_account_payment.id])
        will_call_account_payments = exclude_experiment_excellent_customer_from_robocall(
            account_payments=account_payments)
        assert experiment_account_payment.id not in will_call_account_payments
