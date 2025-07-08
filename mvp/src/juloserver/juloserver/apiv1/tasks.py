import logging

from celery import task
from django.conf import settings
from django.template.loader import get_template
from django.utils import timezone

from juloserver.julo.models import EmailHistory

from ..julo.clients import get_julo_email_client

logger = logging.getLogger(__name__)


@task(name='send_email_verification')
def send_email_verification_email(email, verification_key):
    template = get_template('email_verifikasi.html')
    username = email.split("@")
    variable = {"link": settings.EMAIL_ACTIVATION_LINK_HOST + verification_key, "name": username[0]}
    html_content = template.render(variable)
    time_now = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    subject_email = ' (%s) - %s' % (email, time_now)
    logger.info(
        {
            'action': 'sending_email_verification',
            'from': settings.EMAIL_FROM,
            'to': email,
            'verification_key': verification_key,
        }
    )
    get_julo_email_client().send_email(
        settings.EMAIL_SUBJECT + subject_email, html_content, email, settings.EMAIL_FROM
    )


@task(name='send_customer_feedback_email')
def send_customer_feedback_email(email, full_name, email_subject, application_id, feedback):
    template = get_template('customer_feedback.html')
    project_url = getattr(settings, 'PROJECT_URL')
    href = project_url + "/app_status/list?search_q=" + application_id
    variable = {
        "email": email,
        "feedback": feedback,
        "full_name": full_name,
        "application_id": application_id,
        "href": href,
    }
    html_content = template.render(variable)
    time_now = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    email_subject += ' (%s) - %s' % (email, time_now)

    logger.info(
        {
            'action': 'send_email_error_and_feedback',
            'from': settings.EMAIL_FROM,
            'to': settings.EMAIL_HOST_USER,
            'email': email,
            'full_name': full_name,
            'feedback': feedback,
            'application_id': application_id,
        }
    )
    julo_email_client = get_julo_email_client()
    julo_email_client.send_email(
        email_subject,
        html_content,
        settings.EMAIL_HOST_USER,
        settings.EMAIL_FROM,
        content_type="text/html",
    )


@task(name='send_apk_error_email')
def send_apk_error_email(email, stack_trace):
    julo_email_client = get_julo_email_client()
    julo_email_client.send_email(
        settings.EMAIL_SUBJECT_APP_ERROR,
        email + ' - ' + stack_trace,
        settings.EMAIL_DEV,
        settings.EMAIL_FROM,
    )


@task(name='send_reset_password_email')
def send_reset_password_email(email, reset_password_key):
    reset_password_page_link = settings.RESET_PASSWORD_LINK_HOST + reset_password_key + '/'

    logger.info(
        {
            'status': 'reset_password_page_link_created',
            'action': 'sending_email',
            'email': email,
            'reset_password_page_link': reset_password_page_link,
        }
    )
    time_now = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    subject = "JULO: Reset Password (%s) - %s" % (email, time_now)
    template = get_template('email_reset_password.html')
    username = email.split("@")
    variable = {"link": reset_password_page_link, "name": username[0]}
    html_content = template.render(variable)
    status, _, headers = get_julo_email_client().send_email(
        subject, html_content, email, settings.EMAIL_FROM
    )

    message_id = headers['X-Message-Id']
    EmailHistory.objects.create(
        to_email=email,
        subject=subject,
        sg_message_id=message_id,
        template_code='email_reset_password',
        status=str(status),
    )
