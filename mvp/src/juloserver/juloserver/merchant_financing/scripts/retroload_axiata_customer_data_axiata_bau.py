from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import Loan
from juloserver.sdk.models import AxiataCustomerData
from juloserver.merchant_financing.web_app.services import generate_axiata_customer_data
from django_bulk_update.helper import bulk_update


def retroload_axiata_customer_data_axiata_bau(start_date, end_date, batch_size: int = 100):
    obj = "Loan"
    print("Fetching {}...".format(obj))
    loans = Loan.objects.select_related("product",).filter(
        cdate__range=(start_date, end_date),
        product__product_line=ProductLineCodes.AXIATA_WEB,
    )

    print("Fetched {} {}".format(len(loans), obj))
    if not loans:
        print("No Update {}".format(obj))
        return

    axiata_customer_data_create_list = []
    update_disbursement_date = []
    for loan in loans.iterator():
        new_axiata_customer_data, err = generate_axiata_customer_data(loan)
        if err:
            print("Skipped loan_id {} - {}".format(loan.id, err))
            continue

        axiata_customer_data_create_list.append(new_axiata_customer_data)
        if not loan.fund_transfer_ts:
            update_disbursement_date.append(loan.loan_xid)

        if axiata_customer_data_create_list == batch_size:
            try:
                print("Create Axiata Customer Data with batch_size {}...".format(batch_size))
                created_datas = AxiataCustomerData.objects.bulk_create(
                    axiata_customer_data_create_list,
                    batch_size=batch_size,
                )
                acd_to_update = []
                for acd in created_datas:
                    if acd.loan_xid in update_disbursement_date:
                        acd.disbursement_date = None
                        acd.disbursement_time = None
                        acd_to_update.append(acd)
                bulk_update(
                    acd_to_update,
                    update_fields=['disbursement_date', 'disbursement_time'],
                    batch_size=batch_size,
                )
                acd_to_update = []
                axiata_customer_data_create_list = []
                print("SUCCESS - Created {} Axiata Customer Data".format(batch_size))
            except Exception as e:
                print("ERROR Exception - {}".format(e))
                return

    if axiata_customer_data_create_list:
        remaining_data_count = len(axiata_customer_data_create_list)
        print(
            "batch_size not reached - Process the {} remaining data...".format(remaining_data_count)
        )
        try:
            created_datas = AxiataCustomerData.objects.bulk_create(
                axiata_customer_data_create_list,
                batch_size=remaining_data_count,
            )
            acd_to_update = []
            for acd in created_datas:
                if acd.loan_xid in update_disbursement_date:
                    acd.disbursement_date = None
                    acd.disbursement_time = None
                    acd_to_update.append(acd)
            bulk_update(
                acd_to_update,
                update_fields=['disbursement_date', 'disbursement_time'],
                batch_size=remaining_data_count,
            )
            acd_to_update = []
            axiata_customer_data_create_list = []
            print("SUCCESS - Created {} Axiata Customer Data".format(remaining_data_count))
        except Exception as e:
            print("ERROR Exception - {}".format(e))
            return

    print("DONE.")
