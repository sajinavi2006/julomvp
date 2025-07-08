from django.test.testcases import TestCase
from django.utils import timezone
from django.db.models import signals

from juloserver.account.tests.factories import AccountwithApplicationFactory

from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
)
from juloserver.channeling_loan.tasks import process_channeling_repayment_task
from juloserver.channeling_loan.tests.factories import (
    ChannelingLoanPaymentFactory,
)
from juloserver.julo.models import PaymentEvent
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tests.factories import (
    PaymentEventFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
)
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
)
from juloserver.channeling_loan.models import ChannelingPaymentEvent
from juloserver.channeling_loan.signals import create_channeling_payment_event


class TestChannelingPaymentServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        signals.post_init.disconnect(create_channeling_payment_event, sender=PaymentEvent)

        rac = {
            "TENOR": "Monthly",
            "MAX_AGE": 59,
            "MIN_AGE": 17,
            "JOB_TYPE": [],
            "MAX_LOAN": 20000000,
            "MIN_LOAN": 1000000,
            "MAX_RATIO": None,
            "MAX_TENOR": None,
            "MIN_TENOR": None,
            "MIN_INCOME": None,
            "MIN_WORKTIME": 24,
            "INCOME_PROVE": True,
            "HAS_KTP_OR_SELFIE": True,
            "MOTHER_MAIDEN_NAME": True,
            "VERSION": 2,
        }

        cutoff = {
            "is_active": True,
            "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
            "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
            "INACTIVE_DATE": [],
            "INACTIVE_DAY": ["Saturday", "Sunday"],
            "LIMIT": 1,
        }

        cls.account = AccountwithApplicationFactory()
        cls.app = cls.account.application_set.last()
        cls.current_ts = timezone.localtime(timezone.now())
        cls.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                "fake": {"general": {"LENDER_NAME": "lender_name"}},
                ChannelingConst.PERMATA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "permata_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": rac,
                    "cutoff": cutoff,
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": rac,
                    "cutoff": cutoff,
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
            },
        )
        cls.target_lender = LenderCurrentFactory(lender_name="permata_channeling")
        cls.blank_lender = LenderCurrentFactory(lender_name="fama_channeling")

    def setUp(self):
        self.payment_event = PaymentEventFactory(event_payment=100000)
        self.payment = self.payment_event.payment
        self.payment.payment_status = StatusLookupFactory(
            status_code=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        self.payment.save()

        self.loan = self.payment_event.payment.loan
        self.loan.lender = self.target_lender
        self.loan.account = self.account
        self.loan.application_id2 = self.app.id
        self.loan.save()

        self.channeling_payment = ChannelingLoanPaymentFactory(
            payment=self.payment,
            interest_amount=50000,
            principal_amount=60000,
            due_amount=110000,
            channeling_type=ChannelingConst.PERMATA,
        )

    def test_process_channeling_repayment_general_cases(self):
        # fs disable
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.assertIsNone(process_channeling_repayment_task(None))
        self.assertIsNone(process_channeling_repayment_task([1]))

        # fs enable
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.assertEqual(True, process_channeling_repayment_task([self.payment_event.id]))

        # valid list payment event
        payment_event = PaymentEventFactory(event_payment=500000, payment=self.payment)
        self.assertEqual(True, process_channeling_repayment_task([payment_event.id]))

        # empty payment event list
        self.assertIsNone(process_channeling_repayment_task([]))

        # non-existent payment event IDs
        current_count_cpe = ChannelingPaymentEvent.objects.count()
        result = process_channeling_repayment_task([9999])
        self.assertTrue(result)
        # no new channeling payment events created
        self.assertEqual(ChannelingPaymentEvent.objects.count(), current_count_cpe)

    def test_channeling_repayment_adjustment(self):
        """
        1. Test happy path for loan is paid all and lender is permata
        2. loan is all paid but the lender is not permata, so it won't be adjusted
        3. loan is permata but not all paid
        """
        self.payment.due_amount = 0
        self.payment.save()
        self.payment_event.event_payment = 50_000
        self.payment_event.save()
        self.channeling_payment.channeling_type = ChannelingConst.PERMATA
        self.channeling_payment.save()
        process_channeling_repayment_task([self.payment_event.id])

        result = ChannelingPaymentEvent.objects.filter(payment_id=self.payment.id).last()

        self.assertEqual(result.paid_interest, 50_000)
        self.assertEqual(result.paid_principal, 60_000)
        self.assertEqual(result.payment_amount, 110_000)
        self.assertEqual(result.outstanding_amount, 0)
        self.assertEqual(result.outstanding_principal, 0)
        self.assertEqual(result.outstanding_interest, 0)

        ChannelingPaymentEvent.objects.all().delete()
        self.loan.lender = self.blank_lender
        self.loan.save()
        self.channeling_payment.channeling_type = ChannelingConst.FAMA
        self.channeling_payment.save()
        process_channeling_repayment_task([self.payment_event.id])
        result = ChannelingPaymentEvent.objects.filter(payment_id=self.payment.id).last()
        self.assertNotEqual(result.payment_amount, 110_000)
        self.assertNotEqual(result.outstanding_amount, 0)

        ChannelingPaymentEvent.objects.all().delete()
        self.loan.lender = self.target_lender
        self.loan.save()
        self.channeling_payment.channeling_type = ChannelingConst.PERMATA
        self.channeling_payment.save()
        self.payment.due_amount = 50_000
        self.payment.save()
        process_channeling_repayment_task([self.payment_event.id])
        result = ChannelingPaymentEvent.objects.filter(payment_id=self.payment.id).last()
        self.assertNotEqual(result.payment_amount, 110_000)
        self.assertNotEqual(result.outstanding_amount, 0)

    def test_process_channeling_repayment_task_full_payment(self):
        total_amount = 110000  # 50000 interest + 60000 principal

        # Create a payment event for full payment
        payment_event = PaymentEventFactory(
            payment=self.payment,
            event_payment=total_amount,  # Full payment
            event_due_amount=total_amount,
        )

        # Update payment to reflect it's been paid
        self.payment.paid_amount = total_amount
        self.payment.status_id = PaymentStatusCodes.PAID_ON_TIME
        self.payment.save()

        # Call the function with our payment event ID
        result = process_channeling_repayment_task([payment_event.id])

        # Check function returned True
        self.assertTrue(result)

        # Refresh the channeling loan payment from DB
        self.channeling_payment.refresh_from_db()

        # Verify channeling loan payment was updated correctly
        self.assertEqual(self.channeling_payment.paid_interest, 50000)
        self.assertEqual(self.channeling_payment.paid_principal, 60000)
        self.assertEqual(self.channeling_payment.due_amount, 0)

        # Verify a channeling payment event was created
        channeling_payment_event = ChannelingPaymentEvent.objects.filter(
            payment_event=payment_event
        ).first()

        self.assertIsNotNone(channeling_payment_event)
        self.assertEqual(channeling_payment_event.installment_amount, total_amount)
        self.assertEqual(channeling_payment_event.payment_amount, total_amount)
        self.assertEqual(channeling_payment_event.paid_interest, 50000)
        self.assertEqual(channeling_payment_event.paid_principal, 60000)
        self.assertEqual(channeling_payment_event.outstanding_amount, 0)
        self.assertEqual(channeling_payment_event.outstanding_interest, 0)
        self.assertEqual(channeling_payment_event.outstanding_principal, 0)

    def test_process_channeling_repayment_task_partial_payment_interest_only(self):
        # Create a payment event for partial payment (interest only)
        payment_event = PaymentEventFactory(
            payment=self.payment,
            event_payment=50000,  # Only covers interest
            event_due_amount=110000,
        )

        # Update payment to reflect partial payment
        self.payment.paid_amount = 50000
        self.payment.save()

        # Call the function with our payment event ID
        result = process_channeling_repayment_task([payment_event.id])

        # Check function returned True
        self.assertTrue(result)

        # Refresh the channeling loan payment from DB
        self.channeling_payment.refresh_from_db()

        # Verify channeling loan payment was updated correctly
        self.assertEqual(self.channeling_payment.paid_interest, 50000)
        self.assertEqual(self.channeling_payment.paid_principal, 0)
        self.assertEqual(self.channeling_payment.due_amount, 60000)

        # Verify a channeling payment event was created with correct values
        channeling_payment_event = ChannelingPaymentEvent.objects.filter(
            payment_event=payment_event
        ).first()

        self.assertIsNotNone(channeling_payment_event)
        self.assertEqual(channeling_payment_event.installment_amount, 110000)
        self.assertEqual(channeling_payment_event.payment_amount, 50000)
        self.assertEqual(channeling_payment_event.paid_interest, 50000)
        self.assertEqual(channeling_payment_event.paid_principal, 0)
        self.assertEqual(channeling_payment_event.outstanding_amount, 60000)
        self.assertEqual(channeling_payment_event.outstanding_interest, 0)
        self.assertEqual(channeling_payment_event.outstanding_principal, 60000)

    def test_process_channeling_repayment_task_partial_payment_with_principal(self):
        # Create a payment event for partial payment (covering interest and some principal)
        payment_event = PaymentEventFactory(
            payment=self.payment,
            event_payment=80000,  # Covers interest (50000) and some principal (30000)
            event_due_amount=110000,
        )

        # Update payment to reflect partial payment
        self.payment.paid_amount = 80000
        self.payment.save()

        # Call the function with our payment event ID
        result = process_channeling_repayment_task([payment_event.id])

        # Check function returned True
        self.assertTrue(result)

        # Refresh the channeling loan payment from DB
        self.channeling_payment.refresh_from_db()

        # Verify channeling loan payment was updated correctly
        self.assertEqual(self.channeling_payment.paid_interest, 50000)
        self.assertEqual(self.channeling_payment.paid_principal, 30000)
        self.assertEqual(self.channeling_payment.due_amount, 30000)

        # Verify a channeling payment event was created with correct values
        channeling_payment_event = ChannelingPaymentEvent.objects.filter(
            payment_event=payment_event
        ).first()

        self.assertIsNotNone(channeling_payment_event)
        self.assertEqual(channeling_payment_event.installment_amount, 110000)
        self.assertEqual(channeling_payment_event.payment_amount, 80000)
        self.assertEqual(channeling_payment_event.paid_interest, 50000)
        self.assertEqual(channeling_payment_event.paid_principal, 30000)
        self.assertEqual(channeling_payment_event.outstanding_amount, 30000)
        self.assertEqual(channeling_payment_event.outstanding_interest, 0)
        self.assertEqual(channeling_payment_event.outstanding_principal, 30000)

    def test_process_channeling_repayment_task_multiple_payments(self):
        # First payment: partial (interest only)
        first_payment_event = PaymentEventFactory(
            payment=self.payment,
            event_payment=50000,  # Only covers interest
            event_due_amount=110000,
        )

        # Update payment to reflect first payment
        self.payment.paid_amount = 50000
        self.payment.save()

        # Process the first payment event
        process_channeling_repayment_task([first_payment_event.id])

        # Second payment: partial (some principal)
        second_payment_event = PaymentEventFactory(
            payment=self.payment,
            event_payment=30000,  # Covers some principal
            event_due_amount=60000,
        )

        # Update payment to reflect second payment
        self.payment.paid_amount = 80000
        self.payment.save()

        # Process the second payment event
        process_channeling_repayment_task([second_payment_event.id])

        # Refresh the channeling loan payment from DB
        self.channeling_payment.refresh_from_db()

        # Verify channeling loan payment was updated correctly after both payments
        self.assertEqual(self.channeling_payment.paid_interest, 50000)
        self.assertEqual(self.channeling_payment.paid_principal, 30000)
        self.assertEqual(self.channeling_payment.due_amount, 30000)

        # Verify the second channeling payment event was created with correct values
        second_channeling_payment_event = ChannelingPaymentEvent.objects.filter(
            payment_event=second_payment_event
        ).first()

        self.assertIsNotNone(second_channeling_payment_event)
        self.assertEqual(second_channeling_payment_event.installment_amount, 60000)
        self.assertEqual(second_channeling_payment_event.payment_amount, 30000)
        self.assertEqual(
            second_channeling_payment_event.paid_interest, 0
        )  # Interest already fully paid
        self.assertEqual(second_channeling_payment_event.paid_principal, 30000)
        self.assertEqual(second_channeling_payment_event.outstanding_amount, 30000)
        self.assertEqual(second_channeling_payment_event.outstanding_interest, 0)
        self.assertEqual(second_channeling_payment_event.outstanding_principal, 30000)
