from juloserver.dana.models import DanaCustomerData
from juloserver.julo.models import Skiptrace
from juloserver.julo.utils import format_e164_indo_phone_number


def create_dana_skiptrace():

    dana_customers = DanaCustomerData.objects.select_related(
        'application',
        'customer',
    ).filter(application__customer__skiptrace__isnull=True)

    skiptrace_data_list = []
    counter = 0

    for dana_customer in dana_customers.iterator():
        counter += 1
        skiptrace = Skiptrace(
            contact_name=dana_customer.full_name,
            customer=dana_customer.customer,
            application=dana_customer.application,
            phone_number=format_e164_indo_phone_number(dana_customer.mobile_number),
        )
        skiptrace_data_list.append(skiptrace)
        print('Row {}, Process Application ID: {}'.format(counter, dana_customer.application.id))

    Skiptrace.objects.bulk_create(skiptrace_data_list, batch_size=100)
    print("Success create Dana skiptrace")
