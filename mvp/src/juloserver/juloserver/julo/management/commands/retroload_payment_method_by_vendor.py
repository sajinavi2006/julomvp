from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, Max
from django.db.models.functions import Coalesce

from juloserver.julo.constants import WorkflowConst
from juloserver.julo.services2.payment_method import get_application_primary_phone
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.julo.models import Application
from juloserver.julo.models import PaymentMethod
from juloserver.julo.utils import format_mobile_phone


class Command(BaseCommand):
    help = 'Helps to retroload payment method'

    def add_arguments(self, parser):
        parser.add_argument('--prod_test', type=bool, help='Define production testing or not')
        parser.add_argument('--customer_id', type=list, help='List of customer IDs')
        parser.add_argument('--payment_method_name', type=str, help='Define payment method name')
        parser.add_argument('--payment_method_code', type=str, help='Define payment method code')
        parser.add_argument('--bank_code', type=str, help='Define payment bank code')

    def handle(self, *args, **options):
        is_prod_test = options.get('prod_test')
        customer_list = options.get('customer_id')
        payment_method_name = options.get('payment_method_name')
        payment_method_code = options.get('payment_method_code')
        bank_code = options.get('bank_code')

        if not payment_method_name or not payment_method_code:
            raise CommandError('Must provide payment_method_name or payment_method_code')

        if is_prod_test and customer_list:
            customer_list = customer_list
        else:
            workflow_141_conditions = Q(
                account_id__account_lookup__workflow__name=WorkflowConst.JULO_ONE
            ) & Q(application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER)

            workflow_109_conditions = Q(
                account_id__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
            ) & Q(application_status__gte=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)

            customer_list = (
                Application.objects.filter(workflow_141_conditions | workflow_109_conditions)
                .distinct('customer_id')
                .values_list('customer_id', flat=True)
            )

        batch_size = 100
        num_batches = (len(customer_list) + batch_size - 1) // batch_size
        for i in range(num_batches):
            start_index = i * batch_size
            end_index = (i + 1) * batch_size
            batch_data = customer_list[start_index:end_index]
            pm_data = []

            for customer_id in batch_data:
                payment_method = PaymentMethod.objects.filter(
                    payment_method_name=payment_method_name, customer_id=customer_id
                ).exists()

                if not payment_method:
                    max_sequence = PaymentMethod.objects.filter(customer_id=customer_id).aggregate(
                        sequence_max=Coalesce(Max('sequence'), 0)
                    )

                    application = Application.objects.filter(customer_id=customer_id).last()
                    mobile_phone_1 = get_application_primary_phone(application)
                    if mobile_phone_1:
                        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
                        if application.is_merchant_flow():
                            mobile_phone_1 = mobile_phone_1[0] + '1' + mobile_phone_1[2:]
                        if payment_method_code[-1] == '0':
                            mobile_phone_1 = mobile_phone_1[1:]
                        virtual_account = "".join([payment_method_code, mobile_phone_1])

                        sequence = max_sequence['sequence_max'] + 1
                        pm_data.append(
                            PaymentMethod(
                                payment_method_code=payment_method_code,
                                payment_method_name=payment_method_name,
                                customer_id=customer_id,
                                is_shown=True,
                                is_primary=False,
                                is_preferred=False,
                                virtual_account=virtual_account,
                                sequence=sequence,
                                bank_code=bank_code,
                            )
                        )
            PaymentMethod.objects.bulk_create(pm_data)
