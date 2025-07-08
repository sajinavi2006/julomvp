from django.core.management.base import BaseCommand

from django.conf import settings

from juloserver.julo.models import PaymentMethod

class Command(BaseCommand):
    help = 'revert permata prefix'

    def handle(self, *args, **options):
        payment_method = PaymentMethod.objects.filter(payment_method_code=settings.FASPAY_PREFIX_PERMATA_NEW)
        self.stdout.write(
            self.style.WARNING(
                '=======Begin Rever {} prefix va permata ==========='.format(payment_method.count())
            )
        )

        for payment in payment_method:
            payment.payment_method_code = settings.FASPAY_PREFIX_PERMATA
            va = payment.virtual_account[6:]
            payment.virtual_account =  settings.FASPAY_PREFIX_PERMATA + va
            payment.save(update_fields=['payment_method_code',
                                        'virtual_account',
                                        'udate'])
        self.stdout.write(
            self.style.SUCCESS(
                'Successfully revert permata prefix from {} to {} total: {}'.format(
            settings.FASPAY_PREFIX_PERMATA_NEW, settings.FASPAY_PREFIX_PERMATA, payment_method.count())))
