import logging

from celery import task
from datetime import timedelta

from django.utils import timezone

from juloserver.julo.models import Loan
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.loan.models import LoanJuloCare
from juloserver.loan.services.julo_care_related import julo_care_create_policy
from juloserver.loan.constants import JuloCareStatusConst

logger = logging.getLogger(__name__)


@task(queue="loan_high")
def generate_julo_care_policy_task(loan_id):
    logger_dict = {
        'action': 'generate_julo_care_policy_task',
        'loan_id': loan_id,
        'message': 'start function',
    }
    logger.info(logger_dict)

    loan = Loan.objects.get(pk=loan_id)
    if not loan:
        message = "Loan not found"
        logger.info(logger_dict.update({"message": message}))
        return False, message

    loan_julo_care = LoanJuloCare.objects.filter(loan=loan).last()
    if not loan_julo_care:
        message = "Loan Julo Care not found"
        logger.info(logger_dict.update({"message": message}))
        return False, message

    if julo_care_create_policy(loan, loan_julo_care):
        logger.info(logger_dict.update({"message": "success"}))
        return True, "success"

    logger.info(logger_dict.update({"message": "end function"}))
    return False, "failed"


@task(queue="loan_low")
def scheduled_pending_policy_sweeper():
    current_ts = timezone.localtime(timezone.now())
    logger_dict = {
        'action': 'scheduled_pending_policy_sweeper',
        'current_ts': current_ts,
        'message': 'start function',
    }
    logger.info(logger_dict)

    pending_policies = LoanJuloCare.objects.filter(
        status=JuloCareStatusConst.PENDING,
        cdate__date__lte=current_ts.date() - timedelta(days=1),
        loan__loan_status__in=LoanStatusCodes.fail_status()
    )
    if pending_policies:
        pending_policies.update(status=JuloCareStatusConst.FAILED)
        logger.info(logger_dict.update({"message": "success"}))

    logger.info(logger_dict.update({"message": "end function"}))
