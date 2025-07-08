from django.core.management.base import BaseCommand

from django.conf import settings

from juloserver.julo.banks import BankCodes
from juloserver.julo.models import BankVirtualAccount
from juloserver.julo.models import Loan
from juloserver.julo.models import PaymentEvent
from juloserver.julo.models import PaymentMethod
from juloserver.julo.models import PaymentMethodLookup
from juloserver.julo.models import VirtualAccountSuffix
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.payment_methods import PaymentMethodCodes, PaymentMethodManager
from juloserver.julo.statuses import LoanStatusCodes
from django.utils import timezone


class Command(BaseCommand):
    help = 'retroactively update (assign paymnet method) for existing payment event '

    def handle(self, *args, **options):
        query = PaymentEvent.objects.filter(payment_method=None, event_type='payment')
        for payment_event in query:
            loan = payment_event.payment.loan
            virtual_account = loan.julo_bank_account_number
            payment_method = PaymentMethod.objects.filter(loan=loan,
                virtual_account=virtual_account).first()
            payment_event.payment_receipt = virtual_account
            payment_event.payment_method = payment_method
            payment_event.save()

        self.stdout.write(self.style.SUCCESS('Successfully update retroactive payment event'))
