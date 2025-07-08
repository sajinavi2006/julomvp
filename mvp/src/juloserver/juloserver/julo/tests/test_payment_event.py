"""
"""
from __future__ import absolute_import

from datetime import timedelta, datetime, date
import pytest
import mock
from django.test.testcases import TestCase, override_settings
from .factories import (AuthUserFactory,
                       CustomerFactory,
                       ApplicationFactory,
                       ProductLookupFactory,
                       ProductLine,
                       LoanFactory,
                       PaymentFactory,
                       PaymentEventFactory)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import PaymentEvent
from ..services2.payment_event import waiver_ops_recovery_campaign_promo
from juloserver.promo.tests.factories import WaivePromoFactory



@pytest.mark.django_db
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestPaymentEvent(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.payment1 = PaymentFactory(
            installment_principal=2000,
            installment_interest=200,
            late_fee_amount=20,
            paid_interest=200,
            paid_principal=2000,
            payment_number=1,
            due_amount=0,
            loan=self.loan
        )
        self.payment2 = PaymentFactory(
            installment_principal=2000,
            installment_interest=200,
            late_fee_amount=20,
            paid_interest=0,
            payment_number=2,
            paid_principal=0,
            due_amount=40,
            loan=self.loan
        )
        self.payment3 = PaymentFactory(
            installment_principal=2000,
            installment_interest=200,
            late_fee_amount=20,
            paid_interest=0,
            payment_number=3,
            paid_principal=0,
            due_amount=10,
            loan=self.loan
        )
        WaivePromoFactory(
            loan=self.loan,
            payment=self.payment1,
            promo_event_type='OSP_RECOVERY_APR_2020',
            remaining_installment_principal=1000,
            remaining_installment_interest=100,
        )
        WaivePromoFactory(
            loan=self.loan,
            payment=self.payment2,
            promo_event_type='OSP_RECOVERY_APR_2020',
            remaining_installment_principal=1000,
            remaining_installment_interest=100,
        )
        WaivePromoFactory(
            loan=self.loan,
            payment=self.payment3,
            promo_event_type='OSP_RECOVERY_APR_2020',
            remaining_installment_principal=0,
            remaining_installment_interest=0,
        )
        PaymentEventFactory(
            payment=self.payment1,
            event_payment=1000,
            cdate=datetime.now()
        )
        self.payment_event2 = PaymentEventFactory(
            payment=self.payment2,
            event_payment=1000,
            cdate=datetime.now()
        )

    @mock.patch('juloserver.julo.services2.payment_event.send_pn_notify_cashback')
    def test_waiver_ops_recovery_campaign_promo_single_installment(
        self, mock_send_pn_notify_cashback):
        event_type = 'promo waive late fee'
        campaign_start_date = datetime.now().date()
        campaign_end_date = datetime.now().date() + timedelta(days=10)
        cashback_earned_total = 10
        result = waiver_ops_recovery_campaign_promo(self.loan.id, event_type, campaign_start_date, campaign_end_date)
        assert cashback_earned_total == result
        check_existed = PaymentEvent.objects.filter(payment_id=self.payment2.id, event_payment=20).exists()
        assert check_existed == True

    @mock.patch('juloserver.julo.services2.payment_event.send_pn_notify_cashback')
    def test_waiver_ops_recovery_campaign_promo_full_installment(self, mock_send_pn_notify_cashback):
        self.payment_event2.event_payment=1200
        self.payment_event2.save()
        event_type = 'promo waive late fee'
        campaign_start_date = datetime.now() - timedelta(hours=1)
        campaign_end_date = datetime.now() + timedelta(days=10)
        cashback_earned_total = 80
        result = waiver_ops_recovery_campaign_promo(self.loan.id, event_type, campaign_start_date, campaign_end_date)
        assert cashback_earned_total == result
        check_existed = PaymentEvent.objects.filter(payment_id=self.payment2.id, event_payment=40).exists()
        assert check_existed == True


    @mock.patch('juloserver.julo.services2.payment_event.send_pn_notify_cashback')
    def test_waiver_ops_recovery_campaign_promo_all_installment_case_2(self, mock_send_pn_notify_cashback):
        """due amount greater than waive late fee"""
        self.payment_event2.event_payment=1200
        self.payment_event2.save()

        self.payment2.due_amount=30
        self.payment2.save()
        event_type = 'promo waive late fee'
        campaign_start_date = datetime.now() - timedelta(hours=1)
        campaign_end_date = datetime.now() + timedelta(days=10)
        cashback_earned_total = 80
        result = waiver_ops_recovery_campaign_promo(self.loan.id, event_type, campaign_start_date, campaign_end_date)
        assert cashback_earned_total == result
        check_existed_1 = PaymentEvent.objects.filter(payment_id=self.payment2.id, event_payment=30).exists()
        check_existed_2 = PaymentEvent.objects.filter(payment_id=self.payment3.id, event_payment=10).exists()
        assert check_existed_1 == True
        assert check_existed_2 == True
