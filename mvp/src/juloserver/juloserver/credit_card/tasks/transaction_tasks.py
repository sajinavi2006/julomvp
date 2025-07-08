import logging
from celery import task
from datetime import timedelta

from django.utils import timezone

from juloserver.credit_card.services.transaction_related import assign_loan_credit_card_to_lender
from juloserver.julo.models import (
    Document,
    Loan
)
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.payment_point.constants import TransactionMethodCode

logger = logging.getLogger(__name__)


@task(queue="loan_high")
def assign_loan_credit_card_to_lender_task(loan_id):
    assign_loan_credit_card_to_lender(loan_id)


@task(queue="loan_high")
def upload_sphp_loan_credit_card_to_oss(loan_id):
    from juloserver.followthemoney.tasks import generate_julo_one_loan_agreement

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info({
            "task": "juloserver.credit_card.tasks.transaction_tasks."
                    "upload_sphp_loan_credit_card_to_oss",
            "loan_id": loan_id
        })
        return
    document_sphp_count = Document.objects.filter(
        document_source=loan.id,
        loan_xid=loan.loan_xid,
        document_type__in=("sphp_julo")
    ).count()
    is_payment_restructured = loan.payment_set.filter(is_restructured=True).exists()
    if document_sphp_count == 0 or (document_sphp_count < 2 and is_payment_restructured):
        generate_julo_one_loan_agreement.delay(loan.id)


@task(queue='loan_high')
def check_loan_credit_card_stuck():
    today_ts = timezone.localtime(timezone.now())
    five_minutes_ago_ts = today_ts - timedelta(minutes=5)
    loan_ids_stuck = set(Loan.objects.filter(
        transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
        loan_status_id=LoanStatusCodes.INACTIVE,
        cdate__lt=five_minutes_ago_ts
    ).values_list('id', flat=True))
    loan_ids_stuck_after_sphp = set(Document.objects.filter(
        document_source__in=loan_ids_stuck
    ).values_list('document_source', flat=True))

    loan_ids_stuck_before_sphp = set(filter(lambda loan_id: loan_id not in
                                            loan_ids_stuck_after_sphp,
                                            loan_ids_stuck))
    for loan_id in loan_ids_stuck_before_sphp:
        upload_sphp_loan_credit_card_to_oss.delay(loan_id)

    for loan_id in loan_ids_stuck_after_sphp:
        assign_loan_credit_card_to_lender_task.delay(loan_id)
