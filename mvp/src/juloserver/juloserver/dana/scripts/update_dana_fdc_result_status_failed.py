from bulk_update.helper import bulk_update
from django.utils import timezone

from juloserver.dana.constants import DanaFDCStatusSentRequest
from juloserver.dana.models import DanaFDCResult


def update_dana_fdc_result_status_failed(fdc_result_status=DanaFDCStatusSentRequest.FAIL) -> None:
    dana_fdc_results = DanaFDCResult.objects.filter(status=fdc_result_status).all()

    dana_fdc_result_updated_data = []
    update_date = timezone.localtime(timezone.now())

    for dana_fdc_result in dana_fdc_results.iterator():
        dana_fdc_result.status = DanaFDCStatusSentRequest.PENDING
        dana_fdc_result.udate = update_date
        dana_fdc_result_updated_data.append(dana_fdc_result)

    bulk_update(
        dana_fdc_result_updated_data,
        update_fields=['udate', 'status'],
        batch_size=100,
    )

    print("Successfully updated {} Dana FDC results to pending".format(len(dana_fdc_results)))
