from django.core.management.base import BaseCommand

from django.conf import settings

from juloserver.julo.models import PaymentMethod

class Command(BaseCommand):
    help = 'retroactively payment method suffix'

    def handle(self, *args, **options):
        payment_method = PaymentMethod.objects.all()
        for payment in payment_method:
            if payment.payment_method_code == '444400':
                payment.payment_method_code = settings.FASPAY_PREFIX_PERMATA
                va = payment.virtual_account[6:]
                payment.virtual_account =  settings.FASPAY_PREFIX_PERMATA + va
                payment.payment_method_name = 'Bank PERMATA'
                payment.save(update_fields=['payment_method_code',
                                            'virtual_account',
                                            'payment_method_name',
                                            'udate'])
            elif payment.payment_method_code == '333300':
                payment.payment_method_code = settings.FASPAY_PREFIX_MANDIRI
                va = payment.virtual_account[6:]
                payment.virtual_account = settings.FASPAY_PREFIX_MANDIRI + va
                payment.save(update_fields=['payment_method_code',
                                            'virtual_account',
                                            'udate'])
            elif payment.payment_method_code == '777700':
                payment.payment_method_code = settings.FASPAY_PREFIX_ALFAMART
                va = payment.virtual_account[6:]
                payment.virtual_account = settings.FASPAY_PREFIX_ALFAMART + va
                payment.save(update_fields=['payment_method_code',
                                            'virtual_account',
                                            'udate'])

        self.stdout.write(self.style.SUCCESS('Successfully payment method suffix'))
