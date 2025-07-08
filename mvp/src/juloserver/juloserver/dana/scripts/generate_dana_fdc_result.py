import time
from typing import List, Optional

from juloserver.dana.constants import DanaFDCStatusSentRequest
from juloserver.dana.models import DanaFDCResult, DanaCustomerData
from juloserver.dana.onboarding.services import update_dana_fdc_result
from juloserver.julo.exceptions import JuloException


def generate_dana_fdc_result(application_ids: List, limit: Optional[int]) -> None:
    application_id_list = list(set(application_ids))  # remove duplicate id

    if limit:
        application_id_list = application_id_list[:limit]

    for application_id in application_id_list:
        dana_customer_data = DanaCustomerData.objects.filter(application_id=application_id).last()

        if not dana_customer_data:
            print('Failed create fdc result, application_id {} not found'.format(application_id))
            continue

        try:
            # Set status to cancel because this fdc result will not send to dana
            dana_fdc_result, created = DanaFDCResult.objects.get_or_create(
                application_id=application_id,
                defaults={
                    'dana_customer_identifier': dana_customer_data.dana_customer_identifier,
                    'status': DanaFDCStatusSentRequest.CANCEL,
                    'lender_product_id': dana_customer_data.lender_product_id,
                },
            )

            if created:
                update_dana_fdc_result(
                    dana_customer_identifier=dana_customer_data.dana_customer_identifier,
                    customer_id=dana_customer_data.customer.id,
                    dana_fdc_result=dana_fdc_result,
                )

            print('Success create fdc result for application_id {}'.format(application_id))

        except JuloException as err:
            print(
                'Failed create fdc result for application_id {}. Error: {}'.format(
                    application_id, err
                )
            )

        time.sleep(1)
