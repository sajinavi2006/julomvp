import logging

from . import get_julo_sentry_client
from collections import namedtuple
from django.conf import settings

from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.julo.exceptions import EmailNotSent
from juloserver.julo.models import Application, Customer, Partner
from juloserver.julo.utils import display_rupiah
from juloserver.partnership.decorators import retry

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content
from sendgrid.helpers.mail import Email
from sendgrid.helpers.mail import Mail
from sendgrid.helpers.mail import Personalization
from sendgrid.helpers.mail import Attachment
from typing import Tuple, Any, Dict
from juloserver.application_flow.constants import PartnerNameConstant


logger = logging.getLogger(__name__)
client = get_julo_sentry_client(__name__)
DEFAULT_NAME_FROM = "JULO"


class PartnershipEmailClient(object):
    """
    This function copied from juloserver/julo/clients/email.py
    send individual customize email payment reminder
    """
    def __init__(self, sendgrid_api_key: str, email_from: str) -> None:
        self.sendgrid_api_key = sendgrid_api_key
        self.email_from = email_from
        self.today = timezone.localtime(timezone.now()).date()

    def send_email_with_sendgrid(self, sg: Any, mail: Any) -> Any:
        return sg.client.mail.send.post(request_body=mail.get())

    @retry(EmailNotSent, delay=5, tries=7)
    def send_email(self, subject: str, content: str, email_to: str, email_from: str = None,
                   pre_header: str = None, email_cc: str = None,
                   name_from: str = DEFAULT_NAME_FROM, reply_to: str = None,
                   attachment_dict: Dict = None, content_type: str = None):
        """
        email_to and email_cc can be a single email address or a comma separated
        list of email addresses to support sending to multiple emails at once.
        """
        sg = SendGridAPIClient(apikey=self.sendgrid_api_key)
        sg.client.timeout = 10

        if email_from is None:
            email_from_obj = Email(self.email_from)
        else:
            if name_from is None:
                email_from_obj = Email(email_from)
            else:
                if '<' in email_from and '>' in email_from:
                    email_from_obj = Email(self.email_from)
                else:
                    email_from_obj = Email(email_from, name_from)

        if not content_type:
            content_type = "text/plain" if attachment_dict else "text/html"
        if pre_header:
            content = '<style>.preheader { display:none !important; ' \
                      'visibility:hidden; opacity:0; color:transparent; ' \
                      'height:0; width:0; }</style>' + '<span class="preheader"' \
                      ' style="display: none !important; ''visibility: hidden; opacity: 0; ' \
                      'color: transparent;'' height: 0; width: 0;">' + pre_header + '</span>' +\
                      content
        content_obj = Content(content_type, content)
        mail = Mail()
        mail.from_email = email_from_obj
        if reply_to:
            reply_to_obj = Email(reply_to)
            mail.reply_to = reply_to_obj
        mail.add_content(content_obj)
        personalization = Personalization()

        if "," in email_to:
            email_to = email_to.split(",")
            for email in email_to:
                email_to_obj = Email(email)
                personalization.add_to(email_to_obj)
        elif type(email_to) == list:
            for email in email_to:
                email_to_obj = Email(email)
                personalization.add_to(email_to_obj)
        else:
            email_to_obj = Email(email_to)
            personalization.add_to(email_to_obj)

        personalization.subject = subject

        if email_cc:
            if "," in email_cc:
                email_cc = email_cc.split(",")
                for email in email_cc:
                    email_cc_obj = Email(email)
                    personalization.add_cc(email_cc_obj)
            elif type(email_cc) == list:
                for email in email_cc:
                    email_cc_obj = Email(email)
                    personalization.add_cc(email_cc_obj)
            else:
                email_cc_obj = Email(email_cc)
                personalization.add_cc(email_cc_obj)

        mail.add_personalization(personalization)

        if attachment_dict:
            attachment = Attachment()
            attachment.content = attachment_dict['content']
            attachment.filename = attachment_dict['filename']
            attachment.type = attachment_dict['type']

            mail.add_attachment(attachment)

        logger.info({
            'email_to': email_to,
            'email_from': email_from_obj.email,
            'email_cc': email_cc,
            'subject': subject
        })

        try:
            response = self.send_email_with_sendgrid(sg, mail)
            if response.status_code != 202:
                logger.warn({
                    'status': response.status_code,
                    'error_message': response.body
                })
            return response.status_code, response.body, response.headers
        except Exception as e:
            error = str(e)
            client.captureException()
            raise EmailNotSent(error)

    def email_notify_user_to_check_submission_status(self, application: Application) -> Tuple:
        """
            Currently running in leadgen, if account is not C Score and application status 105
        """
        customer = application.customer
        partner = application.partner

        webview_url = None
        if partner and partner.partnership_config:
            webview_url = partner.partnership_config.julo_partner_webview_url

        context = {
            'webview_url': webview_url,
            'fullname': customer.fullname,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'title': application.gender_title
        }

        msg = render_to_string('email/notify_user_email_to_complete_registration.html', context)
        subject = "Pengajuan berhasil dibuat"
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject, msg, email_to, email_from=email_from, email_cc=None,
            name_from=name_from, reply_to=reply_to
        )
        logger.info({'action': 'submission_status_email_check', 'email': email_to})
        email_of_data = namedtuple(
            'EmailLinking',
            ['customer', 'email_to', 'status', 'headers', 'subject', 'message']
        )
        email_sended = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sended

    def email_success_linking_account(self, customer: Customer, partner: Partner) -> Tuple:
        """
            Currently running in paylater, if account is successfully linked
        """
        application = customer.application_set.last()
        context = {
            'banner': settings.EMAIL_STATIC_FILE_PATH + 'banner_account_linking.png',
            'fullname': customer.fullname,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'title': application.gender_title,
            'partner_name': partner.name
        }

        msg = render_to_string('email/linking_success_email.html', context)
        subject = "Cek akunmu, yuk!"
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject, msg, email_to, email_from=email_from, email_cc=None,
            name_from=name_from, reply_to=reply_to
        )
        logger.info({'action': 'email_linking_account', 'email': email_to})

        email_of_data = namedtuple(
            'EmailLinking',
            ['customer', 'email_to', 'status', 'headers', 'subject', 'message']
        )
        email_sended = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sended

    def email_create_pin_agent_assisted(
        self, application: Application, action_url: str, is_pin_created=False
    ) -> tuple:
        customer = application.customer

        context = {
            'action_url': action_url,
            'fullname': customer.fullname,
            'title': application.gender_title,
            'is_pin_created': is_pin_created,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
            'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
            'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
        }

        if is_pin_created:
            subject = "Sedikit Lagi Akun JULOmu Aktif, Lho!"
        else:
            subject = "Lanjutkan Proses Pengajuanmu, Yuk!"

        msg = render_to_string('email/create_pin_agent_assisted_email.html', context)
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject=subject,
            content=msg,
            email_to=email_to,
            email_from=email_from,
            name_from=name_from,
            reply_to=reply_to,
            content_type="text/html",
        )
        logger.info({'action': 'email_create_pin_agent_assisted', 'email': email_to})
        email_of_data = namedtuple(
            'EmailLinking', ['customer', 'email_to', 'status', 'headers', 'subject', 'message']
        )
        email_sent = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sent

    def email_forgot_pin_leadgen(self, application: Application, action_url: str) -> tuple:
        customer = application.customer

        context = {
            "action_url": action_url,
            "fullname": customer.fullname,
            "title": application.gender_title,
            "play_store": settings.EMAIL_STATIC_FILE_PATH + "google-play-badge.png",
            "ojk_icon": settings.EMAIL_STATIC_FILE_PATH + "ojk.png",
            "afpi_icon": settings.EMAIL_STATIC_FILE_PATH + "afpi.png",
            "afj_icon": settings.EMAIL_STATIC_FILE_PATH + "afj.png",
        }

        subject = "JULO: Reset PIN ({}) - {}".format(
            customer.email, timezone.localtime(timezone.now())
        )

        msg = render_to_string("email/leadgen_forgot_pin_email.html", context)
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject=subject,
            content=msg,
            email_to=email_to,
            email_from=email_from,
            name_from=name_from,
            reply_to=reply_to,
            content_type="text/html",
        )
        logger.info({"action": "email_forgot_pin", "email": email_to})
        email_of_data = namedtuple(
            "EmailLinking", ["customer", "email_to", "status", "headers", "subject", "message"]
        )
        email_sent = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sent

    def email_soft_reject_agent_assisted(self, application: Application, action_url: str,
                                         is_pin_created=False) -> tuple:
        customer = application.customer

        context = {
            'action_url': action_url,
            'fullname': customer.fullname,
            'title': application.gender_title,
            'is_pin_created': is_pin_created,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
            'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
            'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
        }

        if is_pin_created:
            subject = "Lakukan Pengajuan Lagi, Yuk!"
        else:
            subject = "Lanjutkan Lagi Proses Buat Akun JULOmu, Yuk!"

        msg = render_to_string('email/soft_reject_agent_assisted_email.html', context)
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject=subject, content=msg, email_to=email_to, email_from=email_from,
            name_from=name_from, reply_to=reply_to, content_type="text/html"
        )
        logger.info({'action': 'email_create_pin_agent_assisted', 'email': email_to})
        email_of_data = namedtuple(
            'EmailLinking',
            ['customer', 'email_to', 'status', 'headers', 'subject', 'message']
        )
        email_sent = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sent

    def email_loc_approved_agent_assisted(self, application: Application, action_url: str,
                                          is_pin_created=False, set_limit: int = 0) -> tuple:
        customer = application.customer
        credit_limit = set_limit

        money_image = settings.EMAIL_STATIC_FILE_PATH + 'credit_limit_agent_assisted_image.png'
        context = {
            'action_url': action_url,
            'fullname': customer.fullname,
            'title': application.gender_title,
            'is_pin_created': is_pin_created,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
            'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
            'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
            'credit_limit': display_rupiah(credit_limit),
            'money_vector': money_image,
        }

        if is_pin_created:
            subject = "Limit JULO mu sudah siap!"
        else:
            subject = "Yuk, aktifin akun JULOmu!"

        if application.partner and application.partner.name == PartnerNameConstant.QOALA:
            context['is_qoala_partner'] = True
            if settings.ENVIRONMENT == 'prod':
                context['promo_code'] = 'QOALAXJULO1224'
            else:
                context['promo_code'] = 'PROMOTESTXJULO1224'
        else:
            context['is_qoala_partner'] = False

        msg = render_to_string('email/loc_approved_agent_assisted_email.html', context)
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject=subject, content=msg, email_to=email_to, email_from=email_from,
            name_from=name_from, reply_to=reply_to, content_type="text/html"
        )
        logger.info({'action': 'email_create_pin_agent_assisted', 'email': email_to})
        email_of_data = namedtuple(
            'EmailLinking',
            ['customer', 'email_to', 'status', 'headers', 'subject', 'message']
        )
        email_sent = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sent

    def email_reject_smartphone_financing_agent_assisted(self, application: Application) -> tuple:
        customer = application.customer

        context = {
            'fullname': customer.fullname,
            'title': application.gender_title,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
            'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
            'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
            'cs_email': "cs@julo.co.id",
            'cs_phone': "021-5091 9034 | 021-5091 9035",
            'cs_image': settings.EMAIL_STATIC_FILE_PATH + 'customer_service_icon.png',
            'mail_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-mail.png',
            'phone_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-phone.png',
            'banner_image': settings.EMAIL_STATIC_FILE_PATH + 'banner-soft-reject-gosel-email.jpeg',
        }
        crying_face = b"\xF0\x9F\x98\xA2".decode("utf-8")
        subject = "Maaf, Pengajuanmu Ditolak {}".format(crying_face)
        template_name = 'email/soft_reject_smartphone_financing_agent_assisted_email.html'
        msg = render_to_string(template_name, context)
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject=subject, content=msg, email_to=email_to, email_from=email_from,
            name_from=name_from, reply_to=reply_to, content_type="text/html"
        )
        logger.info({'action': 'email_create_pin_agent_assisted', 'email': email_to})
        email_of_data = namedtuple(
            'EmailLinking',
            ['customer', 'email_to', 'status', 'headers', 'subject', 'message']
        )
        email_sent = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sent

    def email_approved_smartphone_financing_agent_assisted(self, application: Application) -> tuple:
        customer = application.customer

        context = {
            'fullname': customer.fullname,
            'title': application.gender_title,
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
            'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
            'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
            'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
            'cs_email': "cs@julo.co.id",
            'cs_phone': "021-5091 9034 | 021-5091 9035",
            'cs_image': settings.EMAIL_STATIC_FILE_PATH + 'customer_service_icon.png',
            'mail_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-mail.png',
            'phone_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-phone.png',
            'banner_image': settings.EMAIL_STATIC_FILE_PATH + 'banner-approved-gosel-email.jpeg',
        }

        hour_glass = b"\xE2\x8F\xB3".decode("utf-8")
        subject = "Pengajuanmu Sedang Diproses {}".format(hour_glass)
        template_name = 'email/approved_smartphone_financing_agent_assisted_email.html'
        msg = render_to_string(template_name, context)
        email_to = customer.email
        email_from = "cs@julo.co.id"
        reply_to = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(
            subject=subject, content=msg, email_to=email_to, email_from=email_from,
            name_from=name_from, reply_to=reply_to, content_type="text/html"
        )
        logger.info({'action': 'email_create_pin_agent_assisted', 'email': email_to})
        email_of_data = namedtuple(
            'EmailLinking',
            ['customer', 'email_to', 'status', 'headers', 'subject', 'message']
        )
        email_sent = email_of_data(customer, email_to, status, headers, subject, msg)
        return email_sent
