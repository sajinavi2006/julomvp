from django.db import transaction
from juloserver.paylater.models import DisbursementSummary
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.exceptions import JuloException


@transaction.atomic()
def application_bulk_disbursement(disbursement_id, new_status_code, note):
    if not disbursement_id:
        raise JuloException('disbursement_id not found')

    disbursement_summary = DisbursementSummary.objects.filter(
        disbursement=disbursement_id).last()
    if not disbursement_summary:
        return

    if disbursement_summary.product_line_id not in ProductLineCodes.bulk_disbursement():
        return

    for application_id in disbursement_summary.transaction_ids:
        process_application_status_change(
            application_id, new_status_code,
            'change by bulk disbursement', note)
