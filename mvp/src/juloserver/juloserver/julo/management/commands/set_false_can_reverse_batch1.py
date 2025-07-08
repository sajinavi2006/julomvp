from django.core.management.base import BaseCommand
from ...models import PaymentEvent


class Command(BaseCommand):

    help = 'Set False Can Reverse Payment Event Batch 1'

    def handle(self, *args, **options):
        payment_events = PaymentEvent.objects.filter(event_type__in=['due_date_adjustment',
                                                                     'late_fee_void',
                                                                     'lebaran_promo',
                                                                     'lebran_prmo_void',
                                                                     'tokped_0interest',
                                                                     'tokped_0intrst'])
        for payment_event in payment_events:
            payment_event.can_reverse = False
            payment_event.save()
        self.stdout.write(self.style.SUCCESS('Successfully Set False Can Reverse Payment Event Batch 1.'))
