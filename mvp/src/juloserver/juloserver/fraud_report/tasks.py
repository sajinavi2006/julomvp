import logging

from juloserver.julo.models import EmailHistory
from juloserver.julo.clients import get_julo_email_client
from celery import task
from juloserver.fraud_report.models import FraudReport

logger = logging.getLogger(__name__)


@task(queue='application_normal')
def trigger_fraud_report_email(fraud_report_id, attachment_dict):
    fraud_report = FraudReport.objects.get(id=fraud_report_id)
    julo_email_client = get_julo_email_client()
    status, headers, subject, msg = julo_email_client.fraud_report_email(
        fraud_report, attachment_dict)
    if status == 202:
        message_id = headers["X-Message-Id"]
        EmailHistory.objects.create(
            application=fraud_report.application,
            sg_message_id=message_id,
            to_email='cs@julo.co.id',
            subject=subject,
            message_content=msg,
            template_code="fraud_report_email")
        fraud_report.email_status = 'sent_to_sendgrid'
    else:
        fraud_report.email_status = 'unsent'
    fraud_report.save(update_fields=['email_status', 'udate'])
