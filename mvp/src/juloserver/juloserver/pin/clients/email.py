import logging
from builtins import str

from babel.dates import format_date
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


class JuloPinEmailClient(JuloEmailClient):
    def email_new_device_login_alert(self, customer, device_model_name):

        now = timezone.localtime(timezone.now())
        application = customer.application_set.last()
        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application]
        )[0]

        title = None
        fullname = None
        if detokenized_application:
            fullname = application.fullname
            title = application.gender_title

        if not fullname:
            fullname = customer.fullname if customer.fullname else 'Pelanggan Setia JULO'

        if not title:
            title = 'Bapak/Ibu'
            # TODO: need to move this logic to customer.gender_title
            if customer.gender and customer.gender in ('Pria', 'Wanita'):
                title = 'Bapak' if customer.gender == 'Pria' else 'Ibu'
        context = {
            'banner': settings.EMAIL_STATIC_FILE_PATH + 'banner_new_device_detected.png',
            'fullname': fullname,
            'title': title,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'first_new_device_login_name': device_model_name,
            'first_new_device_login_date': str(format_date(now, 'd-MMMM-yyyy', locale='id')),
            'first_new_device_login_time': now.strftime("%H:%-M"),
        }
        msg = render_to_string('email/new_device_alert_email.html', context)
        subject = "Perangkat Baru Terdeteksi"
        email_to = (
            detokenized_application.email
            if detokenized_application and detokenized_application.email
            else customer.email
        )
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = 'JULO'
        status, body, headers = self.send_email(
            subject,
            msg,
            email_to,
            email_from=email_from,
            email_cc=None,
            name_from=name_from,
            reply_to=reply_to,
        )
        logger.info({'action': 'email_new_device_login_alert', 'email': email_to})
        return status, headers, subject, msg
