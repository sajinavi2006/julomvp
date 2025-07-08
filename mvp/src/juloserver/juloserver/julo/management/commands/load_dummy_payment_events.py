from django.core.management.base import BaseCommand
from juloserver.julo.models import Payment, PaymentEvent
from django.utils import timezone


class Command(BaseCommand):
    help = 'retroactively create payment histories (covers complete paid payment)'

    def handle(self, *args, **options):
        query = Payment.objects.filter(paymentevent__isnull=True, due_amount=0)
        for payment in query:
            PaymentEvent.objects.create(payment=payment,
                                        event_payment=payment.paid_amount,
                                        event_due_amount=payment.paid_amount,
                                        event_date=timezone.now().date(),
                                        event_type='payment_retroactive')
        self.stdout.write(self.style.SUCCESS('Successfully created retroactive payment histories'))
