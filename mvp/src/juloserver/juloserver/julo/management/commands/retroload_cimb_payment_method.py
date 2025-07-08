import math

from django.core.management.base import BaseCommand
from django.db.models import Q
from bulk_update.helper import bulk_update

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import Application
from juloserver.julo.models import PaymentMethod
from juloserver.julo.banks import BankCodes
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.services2.payment_method import get_application_primary_phone
from juloserver.julo.utils import format_mobile_phone
    

class Command(BaseCommand):
    help = 'Helps to retroload cimb payment method'

    def handle(self, *args, **options):
        batch_size = 2000

        #BULK UPDATE ALL EXISTING CIMB
        payment_methods = PaymentMethod.objects.filter(
            Q(payment_method_name='Bank CIMB Niaga')
            & ~Q(payment_method_code=PaymentMethodCodes.CIMB_NIAGA)
        )
        
        while True:
            payment_method_batch = payment_methods[:batch_size]

            if not payment_method_batch.exists():
                #stop updating
                break

            #UPDATE PAYMENT METHOD
            cimb_payments_update = []
            for payment_method in payment_method_batch:
                application = payment_method.customer.application_set.last()
                virtual_account = payment_method.virtual_account
                mobile_phone_1 = get_application_primary_phone(application)
                if mobile_phone_1:
                    mobile_phone_1 = format_mobile_phone(mobile_phone_1)
                    if application.is_merchant_flow():
                        mobile_phone_1 = mobile_phone_1[0] + '1' + mobile_phone_1[2:]
                    virtual_account = "".join([
                        PaymentMethodCodes.CIMB_NIAGA,
                        mobile_phone_1
                    ])
                
                payment_method.payment_method_code = PaymentMethodCodes.CIMB_NIAGA
                payment_method.virtual_account = virtual_account

                cimb_payments_update.append(payment_method)

            bulk_update(
                cimb_payments_update,
                update_fields=['payment_method_code', 'virtual_account'],
                batch_size=500,
            )

            #UPDATE IS PRIMARY
            julo_one_query = Q(
                customer__account__account_lookup__workflow__name=WorkflowConst.JULO_ONE
            ) & Q(customer__application__application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER)
            julo_turbo_query = Q(
                customer__account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
            ) & Q(customer__application__application_status__gte=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)

            is_primary_customers = payment_methods.filter(
                (julo_one_query | julo_turbo_query)
                    & Q(customer__application__product_line_id__in=[1, 2])
                    & Q(customer__application__bank_name='BANK CIMB NIAGA, Tbk')
            ).distinct("customer_id").values_list("customer_id", flat=True)[:batch_size]

            #SET PRIMARY
            #remove all primary payments
            PaymentMethod.objects.filter(
                customer_id__in=is_primary_customers,
                is_primary=True
            ).update(
                is_primary=False
            )
            #add primary to cimb
            PaymentMethod.objects.filter(
                customer_id__in=is_primary_customers,
                payment_method_name='Bank CIMB Niaga',
            ).update(
                is_primary=True
            )
        
        # BULK CREATE
        julo_one_query = Q(
            account_id__account_lookup__workflow__name=WorkflowConst.JULO_ONE
        ) & Q(application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER)
        julo_turbo_query = Q(
            account_id__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
        ) & Q(application_status__gte=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)

        applications = (
            Application.objects.filter(
                (julo_one_query | julo_turbo_query) & Q(product_line_id__in=[1, 2])
            ).distinct('customer_id')
        )
        application_size = applications.count()
        batch_num = math.ceil(application_size / batch_size)
        for i in range(batch_num):
            start_index = i * batch_size
            end_index = (i + 1) * batch_size
            application_batch = applications[start_index:end_index]

            if not application_batch.exists():
                #stop creating
                break

            cimb_payments = []
            is_primary_customers = []
            for application in application_batch:
                other_payment_methods = PaymentMethod.objects.filter(
                    customer=application.customer
                )
                payment_method = PaymentMethod.objects.filter(
                    payment_method_name='Bank CIMB Niaga',
                    customer=application.customer
                ).first()
                
                if not payment_method:
                    mobile_phone_1 = get_application_primary_phone(application)
                    if mobile_phone_1:
                        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
                        if application.is_merchant_flow():
                            mobile_phone_1 = mobile_phone_1[0] + '1' + mobile_phone_1[2:]
                        virtual_account = "".join([
                            PaymentMethodCodes.CIMB_NIAGA,
                            mobile_phone_1
                        ])
                
                        last_sequence = 0
                        last_sequence_payment = other_payment_methods.filter(
                            sequence__isnull=False,
                        ).order_by("sequence").values("sequence").last()
                        if last_sequence_payment:
                            last_sequence = last_sequence_payment["sequence"]

                        is_primary = False
                        if application.bank_name == 'BANK CIMB NIAGA, Tbk':
                            is_primary = True
                            is_primary_customers.append(application.customer_id)

                        payment_method = PaymentMethod(
                            payment_method_code=PaymentMethodCodes.CIMB_NIAGA,
                            bank_code=BankCodes.CIMB_NIAGA,
                            payment_method_name='Bank CIMB Niaga',
                            customer=application.customer,
                            sequence=last_sequence + 1,
                            virtual_account=virtual_account,
                            is_shown=True,
                            is_primary=is_primary,
                            is_preferred=False
                        )

                        cimb_payments.append(payment_method)

            PaymentMethod.objects.bulk_create(cimb_payments, batch_size=500)

            #UPDATE IS_RPIMARY
            #SET PRIMARY 
            #remove all primary payments
            PaymentMethod.objects.filter(
                Q(customer_id__in=is_primary_customers)
                & Q(is_primary=True)
                & ~Q(payment_method_name='Bank CIMB Niaga')
            ).update(
                is_primary=False
            )
            #add primary to cimb (ALREADY SET ON CREATION)
