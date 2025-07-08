from celery import task

from .analytic_event import *  # noqa
from .campaign import *  # noqa
from .lender_related import *  # noqa
from .sphp import *  # noqa
from .loan_prize_chance import *  # noqa
from .loan_related import *  # noqa
from juloserver.loan.services.alert_for_stuck_loan import send_alert_for_stuck_loan_through_slack


@task(queue="loan_normal")
def send_alert_for_stuck_loan_through_slack_task():
    send_alert_for_stuck_loan_through_slack()
