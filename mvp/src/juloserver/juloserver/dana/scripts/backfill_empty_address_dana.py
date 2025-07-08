from juloserver.dana.models import DanaCustomerData
from django_bulk_update.helper import bulk_update


def backfill_empty_address_dana(limiter: int = 500) -> None:
    dana_customers = DanaCustomerData.objects.select_related(
        'application',
    ).filter(application__address_street_num__isnull=True)

    data_list = []

    for dana_customer in dana_customers.iterator():
        dana_customer.application.address_street_num = dana_customer.address
        data_list.append(dana_customer.application)
        if len(data_list) == limiter:
            bulk_update(data_list, update_fields=['address_street_num'], batch_size=limiter)
            print("Success update {} application.address_street_num".format(len(data_list)))
            data_list = []

    bulk_update(data_list, update_fields=['address_street_num'])
    print("Success update {} application.address_street_num".format(len(data_list)))
