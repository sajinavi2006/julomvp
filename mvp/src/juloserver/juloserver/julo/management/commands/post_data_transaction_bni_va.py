from django.core.management import BaseCommand

from juloserver.julo.models import Application, PaymentMethod
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.integapiv1.tasks import update_va_bni_transaction


class Command(BaseCommand):
    help = 'Helps to post data bni va'

    def handle(self, *args, **options):
        eligible_product_line_codes = [ProductLineCodes.J1, ProductLineCodes.JULO_STARTER]
        query_filter = {
            'product_line__in': eligible_product_line_codes,
            'application_status__gte': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            'bank_name__contains': 'BNI'
        }
        application_data_141_bni = Application.objects.filter(**query_filter).distinct(
            'customer_id')

        for application in application_data_141_bni.iterator():
            payment_method_bni = PaymentMethod.objects.filter(
                payment_method_name='Bank BNI',
                customer_id=application.customer_id
            ).last()

            if not payment_method_bni:
                continue

            if not payment_method_bni.virtual_account:
                continue

            update_va_bni_transaction.delay(
                application.account.id,
                'julo.management.commands.post_data_transaction_bni_va'
            )
