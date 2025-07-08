from django.test import TestCase
from juloserver.account_payment.services.collection_related import update_ptp_for_paid_off_account_payment
from juloserver.account_payment.services.collection_related import ptp_update_for_j1
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             ImageFactory, LoanFactory, PaymentFactory)
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account_payment.models import AccountPaymentStatusHistory
from juloserver.julo.tests.factories import PTPFactory
from datetime import datetime, timedelta
from juloserver.julo.models import (
    PTP,
    Payment)

class TestCollectionRelated(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.ptp_date = datetime.today() - timedelta(days=10)
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account,
                                paid_date=datetime.today().date(), paid_amount=1000, status_id=330,
                                ptp_date=self.ptp_date.date())
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                                initial_cashback=2000)
        self.payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                change_due_date_interest=0,
                paid_date=datetime.today().date(),
                paid_amount=10000
            )
        self.image_type = 'RECEIPT_{}'.format(self.account_payment.id)
        self.image = ImageFactory(image_type=self.image_type,
                                  image_source='1234',
                                  image_status=0)
        self.ptp = PTPFactory(account_payment=self.account_payment, account=self.account,
                                ptp_date=self.ptp_date.date(), ptp_status=None, payment=self.payment)
    
    def test_ptp_update_for_j1(self):
        result = ptp_update_for_j1(self.account_payment.id, self.ptp.ptp_date)
        self.ptp.refresh_from_db()
        ptp_count = PTP.objects.filter().count()
        assert ptp_count == 1
        assert self.ptp.ptp_status != None

    def test_update_ptp_for_paid_off_account_payment(self):
        result = update_ptp_for_paid_off_account_payment(self.account_payment)
        self.account_payment.refresh_from_db()
        self.account_payment.due_date = None
        self.account_payment.paid_date = None
        update_ptp_for_paid_off_account_payment(self.account_payment)
