from builtins import str
import mock
from rest_framework import status
from django.utils import timezone
from django.test.testcases import TestCase, override_settings
from datetime import timedelta, datetime
from django.db.models import Sum

from juloserver.payback.tests.factories import WaiverTempFactory, WaiverPaymentTempFactory

from juloserver.payback.constants import WaiverConst
from juloserver.payback.models import WaiverTemp, WaiverPaymentTemp
from juloserver.payback.services.waiver import (
    get_remaining_principal,
    get_existing_waiver_temp,
    process_waiver_before_payment,
    waive_late_fee_unpaid,
    waive_interest_unpaid,
    waive_principal_unpaid,
    check_any_paid_payment, get_remaining_interest, process_waiver_after_payment
)

from juloserver.julo.services2.payment_event import PaymentEventServices
from juloserver.julo.tests.factories import (
    PaymentFactory,
    LoanFactory,
)
from juloserver.julo.models import PaymentEvent


@override_settings(SUSPEND_SIGNALS=True)
class TestWaiverServices(TestCase):


    def setUp(self):
        self.today = timezone.localtime(timezone.now())
        self.loan = LoanFactory(loan_amount=1000000, loan_duration=4)
        self.waiver_temp = WaiverTempFactory(loan=self.loan, payment=self.loan.payment_set.first())
        self.payment = self.waiver_temp.waiver_payment_temp.first().payment

    def test_get_existing_waiver_temp(self):
        waiver_temp = get_existing_waiver_temp(self.payment)
        self.assertEqual(waiver_temp, self.waiver_temp)

        self.waiver_temp.status = WaiverConst.EXPIRED_STATUS
        self.waiver_temp.save()
        waiver_temp = get_existing_waiver_temp(self.payment)
        self.assertEqual(waiver_temp, None)

    def test_process_waiver_before_payment(self):
        # Missing lines  579,586-587
        self.waiver_temp.status = WaiverConst.EXPIRED_STATUS
        self.waiver_temp.save()
        process_waiver_before_payment(self.payment, 0, self.today.date())
        self.waiver_temp.refresh_from_db()
        self.assertEqual(self.waiver_temp.status, WaiverConst.EXPIRED_STATUS)

        self.waiver_temp.status = WaiverConst.ACTIVE_STATUS
        self.waiver_temp.save()
        process_waiver_before_payment(
            self.payment, 0, self.today.date() + timedelta(days=3))
        self.waiver_temp.refresh_from_db()
        self.assertEqual(self.waiver_temp.status, WaiverConst.ACTIVE_STATUS)

        process_waiver_before_payment(self.payment, 500, self.today.date())
        PaymentEvent.objects.create(
            event_type="payment",
            cdate=timezone.localtime(timezone.now()),
            payment=self.payment,
            event_date=timezone.localtime(timezone.now()).date(),
            event_payment=500,
            event_due_amount=self.payment.due_amount
        )
        self.waiver_temp.refresh_from_db()
        self.assertEqual(self.waiver_temp.status, WaiverConst.ACTIVE_STATUS)

        process_waiver_before_payment(self.payment, 200, self.today.date())
        PaymentEvent.objects.create(
            event_type="payment",
            cdate=timezone.localtime(timezone.now()),
            payment=self.payment,
            event_date=timezone.localtime(timezone.now()).date(),
            event_payment=200,
            event_due_amount=self.payment.due_amount
        )
        PaymentEvent.objects.create(
            event_type="payment_void",
            cdate=timezone.localtime(timezone.now()),
            payment=self.payment,
            event_date=timezone.localtime(timezone.now()).date(),
            event_payment=-200,
            event_due_amount=self.payment.due_amount
        )
        self.waiver_temp.refresh_from_db()
        self.assertEqual(self.waiver_temp.status, WaiverConst.ACTIVE_STATUS)

        status = process_waiver_before_payment(self.payment, 700, self.today.date())
        self.waiver_temp.refresh_from_db()
        self.assertEqual(self.waiver_temp.status, WaiverConst.IMPLEMENTED_STATUS)

    @mock.patch('juloserver.payback.services.waiver.waive_late_fee_paid')
    @mock.patch('juloserver.payback.services.waiver.waive_interest_paid')
    @mock.patch('juloserver.payback.services.waiver.waive_principal_paid')
    def test_process_waiver_before_payment_failed(
            self, mock_late_fee_paid, mock_interest_paid, mock_principal_paid):
        mock_late_fee_paid.return_value = False, "mock error"
        mock_interest_paid.return_value = False, "mock error"
        mock_interest_paid.return_value = False, "mock error"
        self.waiver_temp.status = WaiverConst.ACTIVE_STATUS
        self.waiver_temp.save()
        process_waiver_before_payment(self.payment, 100, self.today.date())
        self.waiver_temp.refresh_from_db()
        self.assertEqual(self.waiver_temp.status, WaiverConst.ACTIVE_STATUS)

    def test_waive_late_fee_unpaid(self):
        payment = PaymentFactory()
        status, message = waive_late_fee_unpaid(
            payment, 10000, "late_fee note", payment.payment_number, self.today.date())
        self.assertEqual(status, True)
        self.assertEqual(message, "Payment event waive_late_fee berhasil dibuat")

        status, message = waive_interest_unpaid(
            payment, 10000, "interest note", payment.payment_number, self.today.date())

        status, message = waive_principal_unpaid(
            payment, 10000, "principal note", payment.payment_number, self.today.date())

        status, message = waive_late_fee_unpaid(
            payment, 10000, "late_fee note update", payment.payment_number, self.today.date())
        self.assertEqual(status, True)
        self.assertEqual(message, "Payment event waive_late_fee berhasil diubah")

    def test_waive_interest_unpaid(self):
        payment = PaymentFactory()
        status, message = waive_interest_unpaid(
            payment, 10000, "interest note", payment.payment_number, self.today.date())
        self.assertEqual(status, True)
        self.assertEqual(message, "Payment event waive_interest berhasil dibuat")

        status, message = waive_late_fee_unpaid(
            payment, 10000, "late_fee note", payment.payment_number, self.today.date())

        status, message = waive_principal_unpaid(
            payment, 10000, "principal note", payment.payment_number, self.today.date())

        status, message = waive_interest_unpaid(
            payment, 10000, "interest note update", payment.payment_number, self.today.date())
        self.assertEqual(status, True)
        self.assertEqual(message, "Payment event waive_interest berhasil diubah")

    def test_waive_principal_unpaid(self):
        payment = PaymentFactory()
        status, message = waive_principal_unpaid(
            payment, 10000, "principal note", payment.payment_number, self.today.date())
        self.assertEqual(status, True)
        self.assertEqual(message, "Payment event waive_principal berhasil dibuat")

        status, message = waive_late_fee_unpaid(
            payment, 10000, "late_fee note", payment.payment_number, self.today.date())

        status, message = waive_interest_unpaid(
            payment, 10000, "interest note", payment.payment_number, self.today.date())

        status, message = waive_principal_unpaid(
            payment, 10000, "principal note update", payment.payment_number, self.today.date())
        self.assertEqual(status, True)
        self.assertEqual(message, "Payment event waive_principal berhasil diubah")

    def test_get_remaining_principal(self):
        # payment.due_amount is 250000
        # payment.installment_principal is 225000
        # payment.installment_interest is 25000
        remaining_principal = get_remaining_principal(self.payment, is_unpaid=False)
        self.assertEqual(remaining_principal, 225000)

    def test_waiver_temp_payment_ids(self):
        payment_ids = self.waiver_temp.payment_ids
        self.assertEqual(payment_ids, str(self.payment.id))

        self.waiver_temp.waiver_payment_temp.all().delete()
        self.waiver_temp.refresh_from_db()
        payment_ids = self.waiver_temp.payment_ids
        self.assertEqual(payment_ids, None)

    @mock.patch('juloserver.julo.services2.payment_event.PaymentEventServices.waiver_validation')
    def test_payment_event_late_fee(self, mock_waiver_validation):
        mock_waiver_validation.return_value = True, "bypass validation"
        payment_event_service = PaymentEventServices()
        payment = PaymentFactory()
        data = dict(
            event_type='waive_late_fee_unpaid',
            waive_late_fee_amount="0",
            max_payment_number=str(self.payment.payment_number),
            waive_validity_date=str(self.today.strftime("%d-%m-%Y")),
            note="note"
        )
        payment.installment_principal = 0
        payment.paid_principal = 0
        payment.installment_interest = 0
        payment.paid_interest = 0
        payment.save()
        result, message = payment_event_service.process_event_type_waive_late_fee(payment, data, list())
        # self.assertEqual(result, True)
        self.assertEqual(message, "Payment event waive_late_fee berhasil dibuat")

        data["event_type"] = "waive_late_fee_paid"
        result, message = payment_event_service.process_event_type_waive_late_fee(payment, data, list())
        # self.assertEqual(result, True)
        self.assertEqual(message, "Payment event waive_late_fee success")

    def test_check_any_paid_payment(self):
        result, message = check_any_paid_payment(self.payment)
        self.assertEqual(result, False)
        self.payment.payment_status_id = 330
        self.payment.save()
        result, message = check_any_paid_payment(self.payment)
        self.assertEqual(result, True)

    def test_get_remaining_interest(self):
        result = get_remaining_interest(self.payment)
        self.assertNotEqual(result, 0)

    def test_process_waiver_after_payment(self):
        # waiver temp is expired
        self.waiver_temp.status = 'expired'
        self.waiver_temp.save()
        today = timezone.localtime(timezone.now()).date()
        result = process_waiver_after_payment(self.payment, 0, today)
        self.assertEqual(result, None)

        # paid date is invalid
        self.waiver_temp.status = 'active'
        self.waiver_temp.valid_until = today - timedelta(days=1)
        self.waiver_temp.save()
        result = process_waiver_after_payment(self.payment, 0, today)
        self.assertEqual(result, None)

        # total paid amount >= total waive and pay
        self.waiver_temp.valid_until = today + timedelta(days=1)
        self.waiver_temp.save()
        result = process_waiver_after_payment(self.payment, 20000000, today)
        self.assertEqual(result, None)

        # total paid amount >= waiver temp need to pay
        ## overpaid
        ### waive late fee
        self.waiver_temp.status = 'active'
        self.waiver_temp.save()
        result = process_waiver_after_payment(self.payment, 30000, today)
        self.assertEqual(result, None)
        ### waive interest, principal
        self.waiver_temp.late_fee_waiver_amt = 10000
        self.waiver_temp.interest_waiver_amt = 10000
        self.waiver_temp.principal_waiver_amt = 10000
        self.waiver_temp.need_to_pay = 1000
        self.waiver_temp.save()
        result = process_waiver_after_payment(self.payment, 1000, today)
        self.assertEqual(result, None)
