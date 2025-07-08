from django.core.management.base import BaseCommand
from django_bulk_update.helper import bulk_update

from juloserver.julo.models import PaymentMethodLookup


class Command(BaseCommand):
    help = 'Helps to add new image logo url in payment method lookup table'

    def handle(self, *args, **options):
        payment_method_lookups = PaymentMethodLookup.objects.all()
        payment_method_lookup_data = []
        base_url = 'https://statics.julo.co.id/payment_methods/'
        for payment_method_lookup in payment_method_lookups.iterator():
            if payment_method_lookup.name == 'Bank BCA':
                payment_method_lookup.image_logo_url_v2 = base_url + 'bca_logo.png'
            elif payment_method_lookup.name == 'Bank BRI':
                payment_method_lookup.image_logo_url_v2 = base_url + 'bri_logo.png'
            elif payment_method_lookup.name == 'Bank BNI':
                payment_method_lookup.image_logo_url_v2 = base_url + 'bni_logo.png'
            elif payment_method_lookup.name == 'Bank MAYBANK':
                payment_method_lookup.image_logo_url_v2 = base_url + 'maybank_logo.png'
            elif payment_method_lookup.name == 'PERMATA Bank':
                payment_method_lookup.image_logo_url_v2 = base_url + 'permata_logo.png'
            elif payment_method_lookup.name == 'Bank MANDIRI':
                payment_method_lookup.image_logo_url_v2 = base_url + 'mandiri_logo.png'
            elif payment_method_lookup.name == 'ALFAMART':
                payment_method_lookup.image_logo_url_v2 = base_url + 'alfamart_logo.png'
            elif payment_method_lookup.name == 'INDOMARET':
                payment_method_lookup.image_logo_url_v2 = base_url + 'indomaret_logo.png'
            elif payment_method_lookup.name == 'OVO':
                payment_method_lookup.image_logo_url_v2 = base_url + 'ovo_logo.png'
            elif payment_method_lookup.name == 'Gopay' or payment_method_lookup.name == 'GoPay Tokenization':
                payment_method_lookup.image_logo_url_v2 = base_url + 'gopay_logo.png'

            payment_method_lookup_data.append(payment_method_lookup)

        bulk_update(payment_method_lookup_data, update_fields=['image_logo_url_v2'])
