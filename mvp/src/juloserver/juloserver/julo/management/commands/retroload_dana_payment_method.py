from django.core.management.base import BaseCommand
from django.db.models import Q, Max
from django.db.models.functions import Coalesce

from juloserver.julo.constants import WorkflowConst
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.services2.payment_method import get_application_primary_phone
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.julo.models import Application
from juloserver.julo.models import PaymentMethod
from juloserver.julo.utils import format_mobile_phone


class Command(BaseCommand):
    help = 'Helps to retroload DANA payment method'

    def handle(self, *args, **options):
        workflow_141_conditions = Q(
            account_id__account_lookup__workflow__name=WorkflowConst.JULO_ONE
        ) & Q(
            application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )

        workflow_109_conditions = Q(
            account_id__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
        ) & Q(
            application_status__gte=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
        )

        application_list = Application.objects.filter(
            workflow_141_conditions | workflow_109_conditions
        ).distinct('customer_id')

        batch_size = 100
        num_batches = (len(application_list) + batch_size - 1)
        for i in range(num_batches):
            start_index = i * batch_size
            end_index = (i + 1) * batch_size
            batch_data = application_list[start_index:end_index]
            pm_data = []

            for application in batch_data:
                payment_method = PaymentMethod.objects.filter(
                    payment_method_name='DANA',
                    customer_id=application.customer_id
                ).exists()

                if not payment_method:
                    max_sequence = PaymentMethod.objects.filter(
                        customer_id=application.customer_id
                    ).aggregate(sequence_max=Coalesce(Max('sequence'), 0))

                    mobile_phone_1 = get_application_primary_phone(application)
                    if mobile_phone_1:
                        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
                        if application.is_merchant_flow():
                            mobile_phone_1 = mobile_phone_1[0] + '1' + mobile_phone_1[2:]
                        virtual_account = "".join([
                            PaymentMethodCodes.DANA,
                            mobile_phone_1
                        ])

                        sequence = max_sequence['sequence_max'] + 1
                        pm_data.append(
                            PaymentMethod(
                                payment_method_code=PaymentMethodCodes.DANA,
                                payment_method_name='DANA',
                                customer_id=application.customer_id,
                                is_shown=True,
                                is_primary=False,
                                is_preferred=False,
                                virtual_account=virtual_account,
                                sequence=sequence
                            )
                        )
            PaymentMethod.objects.bulk_create(pm_data)
