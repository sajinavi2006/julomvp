import logging
import json

from celery import task

from .services import send_partner_notify
from juloserver.julo.models import (Application)

logger = logging.getLogger(__name__)


@task(name='send_retry_callback')
def send_retry_callback(app_id):
    application = Application.objects.get(pk=app_id)
    score = getattr(application, 'creditscore', None)

    if score and score.score == 'C':
        send_partner_notify(application, score)
