from unittest import skip

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
)
from juloserver.channeling_loan.services.views_services import (
    construct_fama_reconciliation
)
from juloserver.channeling_loan.tests.factories import (
    ChannelingLoanPaymentFactory,
)

from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    LoanFactory,
    LoanHistoryFactory,
)
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
)

from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.julo.statuses import LoanStatusCodes


class TestPaymentServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.current_ts = timezone.localtime(timezone.now())
        cls.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=False,
            parameters={
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "whitelist": {
                        "is_active": False,
                        "APPLICATIONS": []
                    }
                }
            }
        )
        cls.disbursement = DisbursementFactory()
        cls.lender = LenderCurrentFactory(lender_name="fama_channeling")
        cls.loan = LoanFactory(
            application=None,
            lender=cls.lender,
            disbursement_id=cls.disbursement.id,
            fund_transfer_ts=cls.current_ts,
        )
        cls.loan.loan_status_id = LoanStatusCodes.PAID_OFF
        cls.loan.save()
        LoanHistoryFactory(
            loan=cls.loan,
            status_old=LoanStatusCodes.CURRENT,
            status_new=LoanStatusCodes.PAID_OFF,
        )

    @skip(reason="Maybe no longer use. Need to check the code sync between staging and UAT")
    def test_fama_reconciliation(self):
        self.assertIsNone(construct_fama_reconciliation())
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.assertEqual(True, construct_fama_reconciliation())
        for payment in self.loan.payment_set.all():
            ChannelingLoanPaymentFactory(
                payment=payment
            )
        self.assertEqual(True, construct_fama_reconciliation())
        self.assertEqual(True, construct_fama_reconciliation(encrypt=False))
        self.assertEqual(True, construct_fama_reconciliation(encrypt=False, file_type="csv"))
        self.loan.payment_set.all().delete()
        self.assertEqual(True, construct_fama_reconciliation())
