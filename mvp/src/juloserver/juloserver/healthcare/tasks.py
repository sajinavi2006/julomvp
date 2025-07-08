import logging

from celery import task

from juloserver.healthcare.models import HealthcareUser
from juloserver.healthcare.services.tasks_related import (
    generate_healthcare_invoice,
    send_email_healthcare_invoice,
)
from juloserver.julo.models import Loan

logger = logging.getLogger(__name__)


@task(queue="loan_normal")
def send_healthcare_email_invoice_task(loan_id):
    healthcare_user = (
        HealthcareUser.objects.select_related('healthcare_platform')
        .filter(loans__loan_id=loan_id)
        .first()
    )

    loan = Loan.objects.get_or_none(pk=loan_id)

    if not healthcare_user or not loan:
        logger.error(
            {
                "task": "send_healthcare_email_invoice_task",
                "message": "Not found healthcare transaction with loan id = {}".format(loan_id),
            }
        )
        return

    generate_healthcare_invoice(healthcare_user, loan)
    send_email_healthcare_invoice(healthcare_user, loan)
