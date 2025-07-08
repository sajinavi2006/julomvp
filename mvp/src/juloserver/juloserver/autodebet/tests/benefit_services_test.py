from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.autodebet.constants import AutodebetStatuses, FeatureNameConst
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.autodebet.models import AutodebetBenefit
from juloserver.autodebet.services.benefit_services import (
    construct_benefit_autodebet_list,
    construct_tutorial_benefit_data,
    get_autodebet_benefit_message,
    get_random_autodebet_benefit,
    set_default_autodebet_benefit,
    get_benefit_waiver_amount,
)
from juloserver.autodebet.tests.factories import (
    AutodebetAccountFactory,
    AutodebetBenefitCounterFactory,
    AutodebetBenefitFactory,
)
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    LoanFactory,
)


class TestAutodebetBenefitServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.current_ts = timezone.localtime(timezone.now())
        cls.feature_setting = FeatureSettingFactory(feature_name=FeatureNameConst.AUTODEBET_BCA)
        cls.account = AccountFactory()
        cls.application = ApplicationFactory(account=cls.account)
        active_loan_status = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        cls.loan = LoanFactory(account=cls.account, loan_status=active_loan_status)
        cls.cashback_benefit = AutodebetBenefitCounterFactory(name="cashback")
        cls.waiver_benefit = AutodebetBenefitCounterFactory(name="waive_interest")

    def setUp(self):
        self.autodebet_account = AutodebetAccountFactory(account=self.account)
        self.application.application_xid = "1234567899"
        self.application.save()
        self.callback_data = {
            "request_id": "uniquerequestid",
            "customer_id_merchant": self.application.application_xid,
            "customer_name": self.application.fullname,
            "db_account_no": "1234567890",
            "status": "01",
            "reason": "success",
        }
        self.benefit_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.BENEFIT_AUTODEBET_BCA,
            parameters=[
                {
                    "type": "cashback", "amount": 20000, "status": "active",
                    "message": "Aktifkan sekarang, dapat cashback {}", "percentage": 0
                },
                {
                    "type": "waive_interest", "amount": 0, "status": "active",
                    "message": "Aktifkan sekarang, gratis bunga di cicilan pertama Anda.",
                    "percentage": 100
                }
            ]
        )
        self.benefit_control_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.AUTODEBET_BENEFIT_CONTROL,
            parameters={
                'campaign_duration': {
                    'start_date': '',
                    'end_date': ''
                },
                'activation_duration': {
                    'start_date': '',
                    'end_date': ''
                },
                'message': {
                    'cashback': 'cashback',
                    'waive_interest': 'waive',
                    'Cashback benefit message': 'Cashback benefit message'
                },
                'cashback': {
                    'first': 5000,
                    'second': 10000,
                    'third': 15000
                },
                'waive_interest': {
                    'first': {
                        'percentage': 50,
                        'max': 10000
                    },
                    'second': {
                        'percentage': 100,
                        'max': 10000
                    },
                    'third': {
                        'percentage': 100,
                        'max': 10000
                    }
                }
            }
        )
        today = timezone.localtime(timezone.now()).date()
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=today)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.account_payment.refresh_from_db()

    def test_construct_benefit_autodebet_list(self):
        self.assertEqual(len(construct_benefit_autodebet_list()), 2)

        self.benefit_setting.is_active = False
        self.benefit_setting.save()
        self.assertEqual(len(construct_benefit_autodebet_list()), 0)

    @patch("juloserver.autodebet.services.benefit_services.get_random_autodebet_benefit")
    def test_get_autodebet_benefit_message(self, mock_random_benefit):
        mock_random_benefit.return_value = (None, None, {"message": "Cashback benefit message"})
        mock_random_benefit.return_value = (
            None,
            None,
            {
                "message": "Cashback benefit message",
                "type": "Cashback benefit message"
            }
        )
        self.autodebet_account.status = AutodebetStatuses.FAILED_REGISTRATION
        self.autodebet_account.save()
        message = get_autodebet_benefit_message(self.account)
        self.assertEqual(message, "Cashback benefit message")

        mock_random_benefit.return_value = (None, None, None)
        message = get_autodebet_benefit_message(self.account)
        self.assertEqual(message, "")

        self.autodebet_account.activation_ts = self.current_ts
        self.autodebet_account.save()
        message = get_autodebet_benefit_message(self.account)
        self.assertEqual(message, "")

    def test_set_default_autodebet_benefit(self):
        self.assertIsNone(set_default_autodebet_benefit(self.account, None))

    def test_get_random_autodebet_benefit(self):
        benefits, benefit_name, benefit = get_random_autodebet_benefit(self.account)
        self.assertEqual(len(benefits), 2)
        self.assertEqual(benefit_name, "cashback")

        self.loan.delete()
        self.waiver_benefit.counter = 1
        self.waiver_benefit.save()
        self.cashback_benefit.counter = 2
        self.cashback_benefit.save()
        benefits, benefit_name, benefit = get_random_autodebet_benefit(self.account)
        self.assertEqual(len(benefits), 2)
        self.assertEqual(benefit_name, "waive_interest")

        self.benefit_setting.is_active = False
        self.benefit_setting.save()
        benefits, benefit_name, benefit = get_random_autodebet_benefit(self.account)
        self.assertEqual(len(benefits), 0)
        self.assertIsNone(benefit_name)

    def test_construct_tutorial_benefit_data(self):
        data = construct_tutorial_benefit_data(self.account)
        self.assertNotEqual(data["message"], "")

        AutodebetBenefitFactory(account_id=self.account.id, benefit_type="cashback")
        data = construct_tutorial_benefit_data(self.account)
        self.assertNotEqual(data["message"], "")

        self.benefit_setting.delete()
        data = construct_tutorial_benefit_data(self.account)
        self.assertEqual(data["message"], "")

    def test_get_benefit_waiver_amount(self):
        AutodebetBenefitFactory(
            account_id=self.account.id,
            benefit_type="waive_interest",
            benefit_value='{"percentage": 10, "max": 10000}'
        )
        amount = get_benefit_waiver_amount(self.account_payment)
        self.assertNotEqual(amount, 0)

        autodebet_benefit = AutodebetBenefit.objects.get(account_id=self.account.id)
        autodebet_benefit.delete()
        AutodebetBenefitFactory(
            account_id=self.account.id,
            benefit_type="cashback",
        )
        amount = get_benefit_waiver_amount(self.account_payment)
        self.assertEqual(amount, 0)
