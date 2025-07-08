from django.core.management.base import BaseCommand

from juloserver.julo.models import SepulsaProduct

from juloserver.sdk.services import xls_to_dict


class Command(BaseCommand):
    help = 'retroload_sepulsa_product'

    def handle(self, *args, **options):
        data = xls_to_dict('misc_files/excel/data_sepulsa_product.xlsx')

        product_list = data['Sheet1']

        for idx, product in enumerate(product_list):

            product_nominal = product['product_nominal'] if 'product_nominal' in product else None
            partner_price = product['partner_price'] if 'partner_price' in product else None
            customer_price = product['customer_price'] if 'customer_price' in product else None
            customer_price_regular = product[
                'customer_price_regular'] if 'customer_price_regular' in product else None
            collection_fee = product['collection_fee'] if 'collection_fee' in product else None
            service_fee = product['service_fee'] if 'service_fee' in product else None
            admin_fee = product['admin_fee'] if 'admin_fee' in product else None

            self.stdout.write(
                'Product id {}, product name {}, type {}, category {}'.format(
                    product['product_id'], product['product_name'],
                    product['type'], product['category']))

            filter_data = dict(
                product_id=product['product_id'],
                type=product['type'],
                category=product['category'],
            )

            existing = SepulsaProduct.objects.filter(**filter_data)

            if existing:
                self.stdout.write(self.style.WARNING("already exists!"))
                continue

            is_active = True
            is_not_blocked = True
            if product['category'] == 'GoPay_driver':
                is_active = False
                is_not_blocked = False

            SepulsaProduct.objects.create(
                product_name=product['product_name'],
                product_nominal=product_nominal,
                partner_price=partner_price,
                customer_price=customer_price,
                customer_price_regular=customer_price_regular,
                collection_fee=collection_fee,
                service_fee=service_fee,
                admin_fee=admin_fee,
                is_not_blocked=is_not_blocked,
                is_active=is_active,
                **filter_data
            )

        self.stdout.write(
            self.style.SUCCESS('Successfully retroload sepulsa product'))
