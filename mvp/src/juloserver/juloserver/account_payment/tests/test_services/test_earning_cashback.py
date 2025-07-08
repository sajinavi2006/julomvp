import mock
from django.test import TestCase
from juloserver.account_payment.services.earning_cashback import *
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ImageFactory,
    PaymentFactory,
    LoanFactory,
    ExperimentSettingFactory,
    WorkflowFactory,
    ApplicationFactory,
    ProductLineFactory,
    ProductLookupFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    ExperimentGroupFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account_payment.models import AccountPaymentStatusHistory
from juloserver.julo.models import StatusLookup
from juloserver.julo.models import CustomerWalletHistory, CashbackCounterHistory
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.payback.constants import WaiverConst
from juloserver.waiver.tests.factories import WaiverRequestFactory
from juloserver.payback.tests.factories import WaiverTempFactory, WaiverPaymentTempFactory
from datetime import datetime, date, timedelta
from juloserver.minisquad.constants import ExperimentConst as MinisqiadExperimentConstant
from juloserver.julo.constants import WorkflowConst
from juloserver.account.constants import AccountLookupNameConst


class TestEarningCashback(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=AccountLookupNameConst.JULO1)
        self.account = AccountFactory(
            id=12345,
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.product_line = ProductLineFactory(
            product_line_code=1,
            product_line_type='J1'
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000,
            product=ProductLookupFactory(product_line=self.product_line, cashback_payment_pct=0.05)
        )
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow
        )
        self.cashback_exp = ExperimentSettingFactory(
            is_active=False,
            code=MinisqiadExperimentConstant.CASHBACK_NEW_SCHEME,
            is_permanent=False,
            criteria={
                "account_id_tail": {
                    "control": [0, 1, 2, 3, 4],
                    "experiment": [5, 6, 7, 8, 9]
                }
            }
        )

    @mock.patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_j1_update_cashback_earned(self, mock_cashback_experiment):
        mock_cashback_experiment.retrun_value = True
        j1_update_cashback_earned(self.payment)
        assert CustomerWalletHistory.objects.count() == 1

    def test_make_cashback_available(self):
        make_cashback_available(self.loan)
    
    def test_reverse_cashback_available(self):
        reverse_cashback_available(self.loan)

    @mock.patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_j1_update_cashback_earned_waiver(self, mock_cashback_experiment):
        account_payment_waiver = AccountPaymentFactory(account=self.account)
        payment_waiver = PaymentFactory(
            payment_status=account_payment_waiver.status,
            due_date=account_payment_waiver.due_date,
            account_payment=account_payment_waiver,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        mock_cashback_experiment.retrun_value = True
        j1_update_cashback_earned(payment_waiver)
        assert CustomerWalletHistory.objects.filter(
            account_payment=account_payment_waiver).count() == 1

        account_payment_waiver_1 = AccountPaymentFactory(account=self.account)
        payment_waiver_1 = PaymentFactory(
            payment_status=account_payment_waiver_1.status,
            due_date=account_payment_waiver_1.due_date,
            account_payment=account_payment_waiver_1,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        waiver_request = WaiverRequestFactory(
            final_approved_waiver_program="r4",
            program_name="General Paid Waiver",
            first_waived_account_payment=account_payment_waiver_1,
            last_waived_account_payment=account_payment_waiver_1,
        )
        waiver_temp = WaiverTempFactory(
            account=self.account,
            status=WaiverConst.ACTIVE_STATUS,
            waiver_request=waiver_request,
            payment=None,
        )
        waiver_payment_temp_1 = WaiverPaymentTempFactory()
        waiver_payment_temp_1.account_payment = account_payment_waiver_1
        waiver_payment_temp_1.save()
        j1_update_cashback_earned(payment_waiver_1)
        assert CustomerWalletHistory.objects.filter(
            account_payment=account_payment_waiver_1).count() == 1

        account_payment_waiver_2 = AccountPaymentFactory(account=self.account)
        payment_waiver_2 = PaymentFactory(
            payment_status=account_payment_waiver_2.status,
            due_date=account_payment_waiver_2.due_date,
            account_payment=account_payment_waiver_2,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        waiver_payment_temp_1 = WaiverTempFactory()
        waiver_payment_temp_1.account_payment = account_payment_waiver_2
        waiver_payment_temp_1.account = self.account
        waiver_payment_temp_1.save()
        j1_update_cashback_earned(payment_waiver_2)
        assert CustomerWalletHistory.objects.filter(
            account_payment=account_payment_waiver_2).count() == 1

        account_payment_waiver_3 = AccountPaymentFactory(account=self.account)
        payment_waiver_3 = PaymentFactory(
            payment_status=account_payment_waiver_3.status,
            due_date=account_payment_waiver_3.due_date,
            account_payment=account_payment_waiver_3,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        waiver_request = WaiverRequestFactory(
            final_approved_waiver_program="General Paid Waiver",
            first_waived_account_payment=account_payment_waiver_3,
            last_waived_account_payment=account_payment_waiver_3,
            account=self.account
        )
        j1_update_cashback_earned(payment_waiver_3)
        assert CustomerWalletHistory.objects.filter(
            account_payment=account_payment_waiver_3).count() == 0

    @mock.patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_cashback_new_scheme(self, mock_cashback_experiment):
        self.cashback_exp.is_active = True
        self.cashback_exp.save()
        mock_cashback_experiment.return_value = True
        j1_update_cashback_earned(
            self.payment,
            dict(
                is_eligible_new_cashback=True,
                percentage_mapping={'1': 1, '2': 1, '3': 2, '4': 2, '5': 4},
            ),
        )
        assert CashbackCounterHistory.objects.count() == 1
