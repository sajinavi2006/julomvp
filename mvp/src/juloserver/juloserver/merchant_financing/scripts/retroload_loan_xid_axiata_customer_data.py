from django.db import transaction
from django_bulk_update.helper import bulk_update
from juloserver.sdk.models import AxiataCustomerData


def retroload_loan_xid_axiata_customer_data(start_date, end_date, batch_size: int = 100):
    obj = "AxiataCustomerData"
    print("Fetching {}...".format(obj))
    axiata_customer_data = (
        AxiataCustomerData.objects.select_related(
            "application",
            "application__loan",
        )
        .filter(cdate__range=(start_date, end_date))
        .exclude(loan_xid__isnull=False)
    )

    print("Fetched {} {}".format(len(axiata_customer_data), obj))
    if not axiata_customer_data:
        print("No Update {}".format(obj))
        return

    acd_to_update_list = []
    loan_to_update_list = []
    data_count = 0

    for data in axiata_customer_data.iterator():
        if not hasattr(data, 'application') or not data.application:
            print("Skipped axiata_customer_data_id({}) - application not found".format(data.id))
            continue
        application = data.application
        if not hasattr(application, 'loan'):
            print("Skipped axiata_customer_data_id({}) - loan not found".format(data.id))
            continue

        loan = application.loan
        loan_xid = loan.loan_xid
        if not loan_xid:
            loan_xid = loan.generate_xid()
            loan.loan_xid = loan_xid
            loan_to_update_list.append(data)

        data.loan_xid = loan_xid
        acd_to_update_list.append(data)
        data_count += 1

        if data_count == batch_size:
            try:
                with transaction.atomic():
                    print("Updating with batch_size {}...".format(batch_size))
                    bulk_update(
                        acd_to_update_list,
                        update_fields=['loan_xid'],
                        batch_size=batch_size,
                    )
                    acd_to_update_list = []
                    bulk_update(
                        loan_to_update_list,
                        update_fields=['loan_xid'],
                        batch_size=batch_size,
                    )
                    loan_to_update_list = []
                    data_count = 0
                    print("SUCCESS - update {} {}".format(batch_size, obj))
            except Exception as e:
                print("ERROR Exception - {}".format(e))
                return

    if data_count:
        print("Updating with batch_size {}...".format(data_count))
        try:
            with transaction.atomic():
                bulk_update(
                    acd_to_update_list,
                    update_fields=['loan_xid'],
                    batch_size=data_count,
                )
                acd_to_update_list = []
                bulk_update(
                    loan_to_update_list,
                    update_fields=['loan_xid'],
                    batch_size=data_count,
                )
                loan_to_update_list = []
                print("SUCCESS - update {} {}".format(data_count, obj))
        except Exception as e:
            print("ERROR Exception - {}".format(e))
            return

    print("---------Finish update {}---------".format(obj))
