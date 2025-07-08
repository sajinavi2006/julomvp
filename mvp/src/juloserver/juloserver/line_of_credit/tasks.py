import logging

from celery import task
from datetime import datetime

from .models import LineOfCredit
from .services import LineOfCreditNotificationService
from .services import LineOfCreditStatementService


logger = logging.getLogger(__name__)


@task(name='execute_loc_notification')
def execute_loc_notification():
    notification_service = LineOfCreditNotificationService()
    notification_service.execute()


@task(name='create_loc_statement')
def create_loc_statement():
    today = datetime.now()
    due_line_of_credits = LineOfCredit.objects.filter(next_statement_date__lte=today)
    for loc in due_line_of_credits:
        logger.info({
            'action': 'create_statement',
            'loc_id': loc.id,
            'statement_date': loc.next_statement_date,
            'date today': today
        })
        LineOfCreditStatementService.create(loc.id, loc.next_statement_date)
