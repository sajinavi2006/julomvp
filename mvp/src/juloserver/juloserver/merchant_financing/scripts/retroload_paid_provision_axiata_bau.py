from django_bulk_update.helper import bulk_update
from juloserver.partnership.models import PartnerLoanRequest
from juloserver.application_flow.constants import PartnerNameConstant


def retroload_paid_provision_axiata_bau(start_date, end_date, batch_size: int = 100):
    obj = "PartnerLoanRequest"
    print("Fetching {}...".format(obj))
    partner_loan_requests = PartnerLoanRequest.objects.select_related('partner').filter(
        cdate__range=(start_date, end_date), partner__name=PartnerNameConstant.AXIATA_WEB
    )

    data_to_update_list = []

    for data in partner_loan_requests.iterator():
        if not data.provision_rate:
            print(
                "INFO - Zero partner_loan_request.provision_rate - loan_id = " + str(data.loan_id)
            )

        provision_amount = data.loan_amount * data.provision_rate
        data.provision_amount = provision_amount
        data.paid_provision_amount = provision_amount
        data_to_update_list.append(data)

        if len(data_to_update_list) == batch_size:
            print("Updating with batch_size {}...".format(batch_size))
            bulk_update(
                data_to_update_list,
                update_fields=['provision_amount', 'paid_provision_amount'],
                batch_size=batch_size,
            )
            data_to_update_list = []
            print("SUCCESS - update {} {}".format(batch_size, obj))

    if data_to_update_list:
        count_rest_data = len(data_to_update_list)
        print("Updating the rest {} data...".format(count_rest_data))
        bulk_update(
            data_to_update_list,
            update_fields=['provision_amount', 'paid_provision_amount'],
            batch_size=count_rest_data,
        )
        print("SUCCESS - update {} {}".format(count_rest_data, obj))
    else:
        print("No update -> all data already correct")
    print("---------Finish update {}---------".format(obj))
