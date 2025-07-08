from __future__ import print_function

import json
from builtins import str
import logging

import time
from bs4 import BeautifulSoup
from datetime import date
from babel.numbers import format_currency
from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.db import connection
from django.template import (
    Context,
    Template,
)
from django.utils.baseconv import base64

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content
from sendgrid.helpers.mail import Email
from sendgrid.helpers.mail import Mail
from sendgrid.helpers.mail import Personalization
from sendgrid.helpers.mail import Attachment

from babel.dates import format_date

from ..utils import (
    display_rupiah,
    convert_to_base64_csv,
    splitAt,
)
from ..statuses import ApplicationStatusCodes
from ..product_lines import ProductLineCodes
from ..exceptions import EmailNotSent
from ..partners import PartnerConstant
from . import get_julo_sentry_client
from juloserver.julo.services import (
    get_google_calendar_attachment,
    get_google_calendar_for_email_reminder,
)
from juloserver.julo.models import PaymentMethodLookup
from juloserver.julo.models import PartnerPurchaseItem
from juloserver.julo.models import (
    PaymentMethod,
    EmailHistory,
)
from juloserver.julo.constants import (
    ReminderTypeConst,
    VendorConst,
)
from juloserver.julo.services2.reminders import Reminder
from juloserver.julo.banks import BankCodes
from juloserver.julo.services import (
    get_pdf_content_from_html,
    get_application_sphp,
)
from ..services2.email import get_excel_for_cashback_promo_email
from juloserver.payback.constants import CashbackPromoConst
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    Product,
)
from juloserver.streamlined_communication.services import process_streamlined_comm
from juloserver.promo_campaign.clients import PromoEmailClient
from juloserver.loan_refinancing.clients.email import LoanRefinancingEmailClient
from juloserver.loan.clients.email import LoanEmailClient
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.julo.constants import EmailDeliveryAddress
from juloserver.merchant_financing.clients import MerchantFinancingEmailClient
from juloserver.streamlined_communication.models import StreamlinedCommunication
from typing import (
    Dict,
    Any,
    Tuple,
)
from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.pii_vault.constants import PiiSource

from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.cohort_campaign_automation.clients.email import CohortCampaignAutomationClient
import requests

INFO_TITLE = "JULO INFO"
REMINDER_TITLE = "JULO REMINDER"
JULO_TITLE = "JULO"
DEFAULT_NAME_FROM = "JULO"

EMAIL_131 = 'cs131@julofinance.com'
EMAIL_138 = 'cs138@julofinance.com'
EMAIL_DEV = 'dev@julofinance.com'

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()
COMMUNICATION_PLATFORM = CommunicationPlatform.EMAIL



class JuloEmailClient(
    PromoEmailClient,
    LoanRefinancingEmailClient,
    MerchantFinancingEmailClient,
    LoanEmailClient,
    CohortCampaignAutomationClient,
    object,
):
    """
    Email client class for sending email with SendGrid.
    """
    def __init__(self, sendgrid_api_key, email_from):
        self.sendgrid_api_key = sendgrid_api_key
        self.email_from = email_from
        self.today = timezone.localtime(timezone.now()).date()

    def send_email_with_sendgrid(self, sg, mail):
        return sg.client.mail.send.post(request_body=mail.get())

    def delete_email_from_bounce(self, email: str) -> bool:
        """
        Removing email from SendGrid's bounce list if exists.
        API used:
        - https://docs.sendgrid.com/api-reference/bounces-api/retrieve-a-bounce
        - https://docs.sendgrid.com/api-reference/bounces-api/delete-a-bounce

        Args:
            email (str): The email that is to be removed from bounce list.

        Returns:
            (bool): True if the email is removed.
                False if not removed because email don't exist in list or error occur.
        """
        try:
            sendgrid_client = SendGridAPIClient(apikey=self.sendgrid_api_key)

            fetch_bounce_response = sendgrid_client.client.suppression.bounces._(email).get()
            if fetch_bounce_response.body == b'[]':
                logger.info({
                    'action': 'delete_email_from_bounce',
                    'message': 'Email does not exist in SendGrid\'s bounce list.',
                    'email': email,
                })
                return False
            else:
                fetch_data = json.loads(fetch_bounce_response.body.decode('utf-8'))
                logger.info({
                    'action': 'delete_email_from_bounce',
                    'message': 'Email found in bounce list.',
                    'email': email,
                    'bounce_created': fetch_data[0]['created'],
                    'bounce_reason': fetch_data[0]['reason'],
                    'bounce_status': fetch_data[0]['status']
                })

                sendgrid_client.client.suppression.bounces._(email).delete()
                logger.info({
                    'action': 'delete_email_from_bounce',
                    'message': 'Successfully remove email from bounce list.',
                    'email': email,
                })
                return True
        except Exception as e:
            exception_message = str(e.message) if hasattr(e, 'message') else str(e)
            sentry_client.captureException()

            logger.info({
                'action': 'delete_email_from_bounce',
                'message': 'Fail to fetch or remove email from bounce list.',
                'email': email,
                'error': exception_message,
            })
            return False

    def send_email(self, subject, content, email_to, email_from=None, pre_header=None,
                   email_cc=None, name_from=DEFAULT_NAME_FROM, reply_to=None,
                   attachment_dict=None, content_type=None, retry_max=7, attachments: list = None):
        """
        email_to and email_cc can be a single email address or a comma separated
        list of email addresses to support sending to multiple emails at once.
        """
        if attachments is None:
            attachments = []

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
            attachments.append(attachment_dict)

        if attachments:
            for attachment in attachments:
                atch = Attachment()

                for item in attachment:
                    setattr(atch, item, attachment[item])

                mail.add_attachment(atch)

        logger.info({
            'email_to': email_to,
            'email_from': email_from_obj.email,
            'email_cc': email_cc,
            'subject': subject
        })

        retry_times = 0
        while retry_times <= retry_max:
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
                if 'timed out' in error:
                    retry_seconds = pow(2, retry_times)
                    print("mail send timeout, retry for: " + str(retry_seconds) + " seconds")
                    time.sleep(retry_seconds)
                    if retry_times == retry_max:
                        raise EmailNotSent(error)
                else:
                    sentry_client.captureException()
                    raise EmailNotSent(error)
                retry_times += 1

    def email_custom_payment_reminder(self, email_to, subject, text_content,
                                      pre_header=None, is_bucket_5=False):

        if is_bucket_5:
            email_from = EmailDeliveryAddress.COLLECTIONS_JTF
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        else:
            email_from = EmailDeliveryAddress.COLLECTIONS_JTF
            name_from = None
            reply_to = None

        subject = subject + '-' + email_to
        status, body, headers = self.send_email(
            subject, text_content, email_to, email_from,
            pre_header=pre_header, name_from=name_from, reply_to=reply_to)
        return status, body, headers

    def email_payment_reminder(self, payment, day):
        """DEPRECATED"""
        """
        send email reminder for payment in T-4 and T-2
        """
        product_line_code = payment.loan.application.product_line.product_line_code
        loan = payment.loan
        application = payment.loan.application
        fullname = application.fullname_with_title
        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = date.strftime(payment.notification_due_date, '%d-%b-%Y')
        bank_name = payment.loan.julo_bank_name
        account_number = " ".join(
            splitAt(payment.loan.julo_bank_account_number, 4))
        payment_cashback_amount = (0.01 / loan.loan_duration) * loan.loan_amount
        bank_code = PaymentMethodLookup.objects.filter(name=payment.loan.julo_bank_name).first()
        if bank_code and bank_code.code != BankCodes.BCA:
            code = bank_code.code
            bank_code_text = "(Kode Bank: " + code + ")"
        else:
            code = ""
            bank_code_text = ""

        # define template and email subject
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
        )
        if payment.ptp_date:
            template = 'email_reminder_ptp_-1-3-5'
            title = "Segera Lunasi Janji Bayar Anda Sebelum %s Untuk Menghindari Proses Hukum Lebih Lanjut"\
                    % (due_date)
            filter_['ptp'] = payment.ptp_late_days
        else:
            filter_['dpd'] = payment.due_late_days
            if product_line_code in ProductLineCodes.mtl():
                template = 'email_reminder_in' + str(day)
                total_cashback_amount = int(payment.cashback_multiplier * payment_cashback_amount)
                today_str = date.strftime(timezone.localtime(timezone.now()).date(), '%d %b')
                if day == 4:
                    title = "Bayar Hari Ini, {} dan Dapatkan Cashback {}".format(
                        today_str, display_rupiah(total_cashback_amount))
                elif day == 2:
                    title = "Bayar Sekarang, {} dan Dapatkan Cashback {}".format(
                        today_str, display_rupiah(total_cashback_amount))

            elif product_line_code in ProductLineCodes.bri():
                template = 'email_reminder'
            elif product_line_code in ProductLineCodes.stl():
                template = 'stl_email_reminder_in' + str(day)
                title = "Reminder Pinjaman Anda"
            elif product_line_code in ProductLineCodes.pedemtl():
                template = 'pedemtl_email_reminder_in' + str(day)
                title = "Reminder Pinjaman PEDE Pinter Anda"
            elif product_line_code in ProductLineCodes.pedestl():
                template = 'pedestl_email_reminder_in' + str(day)
                title = "Reminder Pinjaman PEDE Pinter Anda"
            elif product_line_code in ProductLineCodes.laku6():
                template = 'laku6mtl_email_reminder_in' + str(day)
                title = "Reminder Pinjaman Prio Rental Anda"
            else:
                return None, None, None, None
        is_dpd_plus = False
        if day == '+4':
            is_dpd_plus = True
            title = "Pembayaran pinjaman Anda terlambat! Hindari biaya keterlambatan."
        today = timezone.localtime(timezone.now()).date()
        today_formated = today.strftime('%d-%b-%Y')
        context = {
            'fullname': fullname,
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'due_date_minus_' + str(day): today_formated,
            'cashback_multiplier': payment.cashback_multiplier,
            'payment_cashback_amount': display_rupiah(int(payment_cashback_amount)),
            'bank_code': code,
            'bank_code_text': bank_code_text,
            'year': today.strftime('%Y'),
            'base_url': settings.BASE_URL,
            'today': today_formated,
            'first_name_with_title': application.first_name_with_title,
            'display_calendar_reminder': 'none'
        }
        attachment_dict, content_type, google_url = None, None, None

        if product_line_code in ProductLineCodes.mtl():
            attachment_dict, content_type, google_url = get_google_calendar_for_email_reminder(application, is_dpd_plus)
            context['google_calendar_url'] = google_url

        if attachment_dict and product_line_code in ProductLineCodes.mtl():
            context['display_calendar_reminder'] = 'block'

        filter_['template_code'] = template
        try:
            msg = process_streamlined_comm(filter_, replaced_data=context)
        except Exception as e:
            msg = render_to_string(template + '.html', context)
        else:
            if not msg:
                msg = render_to_string(template + '.html', context)

        email_to = application.email
        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        subject = JULO_TITLE + ' - ' + title
        status, body, headers = self.send_email(subject, msg, email_to, email_from, name_from=None,
                                                attachment_dict=attachment_dict, content_type=content_type)
        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, VendorConst.SENDGRID,
                                         ReminderTypeConst.EMAIL_TYPE_REMINDER)

        return status, headers, subject, msg

    def email_notification_100v(self, customer):
        """ send email notification for customer verified
        """
        template = 'email_notif_100v'
        context = {
            'fullname': customer.email,
            'year': timezone.localtime(timezone.now()).date().strftime('%Y')
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = customer.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_100v',
            'customer_id': customer.id
        })

        return status, headers, subject, msg

    def email_notification_110(self, application, change_reason=None):
        """ send email notification for status change to 110
        """
        template = 'email_notif_110'
        expired_date = self.today + relativedelta(days=14)
        context = {
            'fullname': application.fullname_with_title,
            'expired_date': date.strftime(expired_date, '%d-%b-%Y'),
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y')
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.FORM_SUBMITTED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_110',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_111(self, application, change_reason):
        """ send email notification for status change to 111
        """
        template = 'email_notif_111'
        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y')
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_111',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_131(self, application, change_reason):
        """ send email notification for status change to 131
        """
        app_history = application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED).first()
        c_date = app_history.cdate
        expired_date = c_date + relativedelta(days=14)
        template = 'email_notif_131'
        reason_list = change_reason.split(",")
        docs_needed_list = []
        reasons = ""
        for i in reason_list:
            reasons = i.split("-")
            docs_needed_list.append(reasons[1])
            reasons += '<b><li>'+reasons[1]+'</li></b>'

        context = {
            'fullname': application.fullname_with_title,
            'status_change_reason': docs_needed_list,
            'expired_date': date.strftime(expired_date, '%d-%b-%Y'),
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
            'status_change_reasons_parsed': reasons
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        email_from = EMAIL_131
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to, email_from)

        logger.info({
            'action': 'send_email_notification_131',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_133(self, application, change_reason):
        """ send email notification for status change to 133
        """
        expired_date = self.today + relativedelta(days=14)
        template = 'email_notif_133'
        context = {
            'fullname': application.fullname_with_title,
            'expired_date': date.strftime(expired_date, '%d-%b-%Y'),
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_133',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_135(self, application, change_reason):
        """ send email notification for status change to 135
        """
        expired_date = self.today + relativedelta(days=14)
        template = 'email_notif_135'
        reasons_list = change_reason.split(",")
        text_reasons = []
        for c_reason in reasons_list:
            if "-" in c_reason:
                reason = c_reason.split("-")
                text_reasons.append(reason[1])

        context = {
            'fullname': application.fullname_with_title,
            'status_change_reason': text_reasons,
            'expired_date': date.strftime(expired_date, '%d-%b-%Y'),
            'change_reason_len': len(text_reasons)
        }

        msg = render_to_string(template + '.html', context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_135',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_136(self, application, change_reason):
        """ send email notification for status change to 136
        """
        template = 'email_notif_136'
        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_136',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_137(self, application, change_reason):
        """ send email notification for status change to 137
        """
        template = 'email_notif_137'
        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_137',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_138(self, application, change_reason):
        """ send email notification for status change to 138
        """
        expired_date = self.today + relativedelta(days=14)
        template = 'email_notif_138'
        reasons_list = change_reason.split(",")
        text_reasons = []
        for c_reason in reasons_list:
            if "-" in c_reason:
                reason = c_reason.split("-")
                text_reasons.append(reason[1])

        context = {
            'fullname': application.fullname_with_title,
            'status_change_reason': text_reasons,
            'change_reason_len': len(text_reasons),
            'expired_date': date.strftime(expired_date, '%d-%b-%Y'),
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        email_from = EMAIL_138
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to, email_from)

        logger.info({
            'action': 'send_email_notification_138',
            'status_change_reason': change_reason,
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_139(self, application, change_reason):
        """ send email notification for status change to 139
        """
        template = 'email_notif_139'
        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_139',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_142(self, application, change_reason):
        """ send email notification for status change to 142
        """
        template = 'email_notif_142'

        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_142',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_143(self, application, change_reason):
        """ send email notification for status change to 143
        """
        template = 'email_notif_143'
        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.OFFER_EXPIRED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_143',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_161(self, application, change_reason):
        """ send email notification for status change to 161
        """
        template = 'email_notif_161'
        context = {
            'fullname': application.fullname_with_title,
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.ACTIVATION_CALL_FAILED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_161',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_171(self, application, change_reason):
        """ send email notification for status change to 171
        """
        template = 'email_notif_171'
        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/appl_forms',
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_171',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_notification_180(self, application, change_reason, to_partner=False, email_setting=None):
        """ send email notification for status change to 180
        """
        loan = application.loan
        loan_active_date = loan.fund_transfer_ts.date()
        loan_amount = loan.loan_amount

        if application.product_line.product_line_code in ProductLineCodes.stl():
            template = 'email_notif_180_stl'
        elif application.partner_name == PartnerConstant.PEDE_PARTNER:
            template = 'email_notif_180_pede'
        else:
            template = 'email_notif_180'

        l_amount_text = 'dan akan masuk ke rekening bank Anda dalam 1 hari kerja'
        if application.partner_name == PartnerConstant.DOKU_PARTNER:
            l_amount_text = 'dan akan masuk ke rekening DOKU Anda sekarang'

        device_name = ""
        contract_number = ""
        attachment_dict = None
        content_type = None
        status, headers, subject, msg = None, None, None, None

        partnerpurchaseitem = PartnerPurchaseItem.objects.filter(application_xid=application.application_xid).first()
        if partnerpurchaseitem:
            device_name = partnerpurchaseitem.device_name
            if partnerpurchaseitem.contract_number:
                contract_number = partnerpurchaseitem.contract_number

        context = {
            'fullname': application.fullname_with_title,
            'loan_amount': display_rupiah(loan_amount),
            'l_amount_text': l_amount_text,
            'loan_active_date': date.strftime(loan_active_date, '%d-%b-%Y'),
            'link': 'http://www.julofinance.com/android/goto/appl_main',
            'application_xid':application.application_xid,
            'device_name': device_name,
            'contract_number':contract_number
        }

        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to

        def get_customer_context():
            email_to = application.email
            subject = "%s - %s - XLFrently" % (INFO_TITLE, email_to, )
            template = Template(email_setting['email_setting'].customer_email_content)
            msg = template.render(Context(context))
            return subject, msg, email_to

        def get_partner_context():
            email_to = application.partner.email
            if email_setting['partner_setting'].partner_email_list:
                email_to = email_setting['partner_setting'].partner_email_list
            if contract_number:
                subject = "%s - %s - XLFrently" % (application.application_xid, contract_number, )
            else:
                subject = "%s - XLFrently" % (application.application_xid, )
            template = Template(email_setting['email_setting'].partner_email_content)
            msg = template.render(Context(context))
            return subject, msg, email_to

        def get_sphp_attachment():
            attachment_name = "%s-%s.pdf" % (application.fullname, application.application_xid)
            attachment_string = get_application_sphp(application)
            pdf_content = get_pdf_content_from_html(attachment_string, attachment_name)
            attachment_dict = {
                "content": pdf_content,
                "filename": attachment_name,
                "type": "application/pdf"
            }
            return attachment_dict, "text/html"

        if email_setting:
            send_mail = False
            if to_partner:
                if email_setting['send_to_partner']:
                    #send to partner
                    subject, msg, email_to = get_partner_context()
                    if email_setting['attach_sphp_partner']:
                        attachment_dict, content_type = get_sphp_attachment()
                    send_mail = True
            else:
                if application.partner:
                    if email_setting['send_to_partner_customer']:
                        # send to partner customer
                        subject, msg, email_to = get_customer_context()
                        if email_setting['attach_sphp_partner_customer']:
                            attachment_dict, content_type = get_sphp_attachment()
                        send_mail = True
                elif email_setting['send_to_julo_customer']:
                    # send to julo customer
                    subject, msg, email_to = get_customer_context()
                    if email_setting['attach_sphp_julo_customer']:
                        attachment_dict, content_type = get_sphp_attachment()
                    send_mail = True

            if send_mail:
                status, body, headers = self.send_email(
                    subject, msg, email_to, attachment_dict=attachment_dict, content_type=content_type)

        elif not to_partner:
            attachment_dict, content_type = get_google_calendar_attachment(application)

            if not attachment_dict:
                return None, None, None, None

            msg = render_to_string(template + '.html', context)
            status, body, headers = self.send_email(
                subject, msg, email_to, attachment_dict=attachment_dict, content_type=content_type)

        logger.info({
            'action': 'send_email_notification_180',
            'application_id': application.id
        })
        return status, headers, subject, msg

    def email_julo_review_challenge_blast(self, email):
        # send julo review challenge email
        template = 'email_julo_review_challenge'

        msg = render_to_string(template + '.html')
        email_to = email
        subject = "2 HARI LAGI, HP SAMSUNG MENANTI ANDA"
        email_from = "finance@julofinance.com"
        name_from = "JULO"
        reply_to = "marketing@julofinance.com"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'send_email_julo_review_challenge',
            'email': email
        })

        return status, headers, subject, msg

    def email_julo_review_challenge_2_blast(self, email, name, saving):
        # send julo review challenge email
        template = 'email_julo_review_challenge_2'

        context = {
            'name': name,
            'saving': saving
        }

        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = "Sudah Hemat, Menang HP Samsung. Mau?"
        email_from = "finance@julofinance.com"
        name_from = "JULO"
        reply_to = "marketing@julofinance.com"
        status, body, headers = self.send_email(subject,
                                                msg, email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'send_email_julo_review_challenge_2',
            'email': email
        })

        return status, headers, subject, msg

    def email_reminder_105(self, application):
        """ send email reminder for status change to 105
        """
        template = 'email_reminder_105'
        context = {
            'fullname': application.fullname_with_title,
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        if not email_to:
            email_to = application.customer.email

        subject = 'Tinggal sedikit lagi!'
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_notification_180',
            'application_id': application.id
        })

        return status, headers, subject, msg

    def email_partner_daily_report(self, filename, sql_query, subject, content, recipients):
        """ send email for partner Dialy Report
        """

        with connection.cursor() as cursor:
            cursor.execute(sql_query)
            colnames = [desc[0] for desc in cursor.description]
            data_result = cursor.fetchall()
        csv_file = convert_to_base64_csv(colnames, data_result)
        attachment_dict = {'content': csv_file, 'filename': filename, 'type': 'text/csv'}

        msg = content
        email_to = recipients
        subject = subject
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                None,
                                                None,
                                                None,
                                                None,
                                                attachment_dict)

        logger.info({
            'action': 'send_email_partner_daily_report',
            'filename': filename
        })

        return status, headers

    def email_notif_balance_sepulsa_low(self, balance, subject):
        """ send email infrom finance to topup balance sepulsa
        """
        template = 'email_notif_balance_sepulsa_low'
        context = {
            'balance': display_rupiah(balance),
        }

        msg = render_to_string(template + '.html', context)
        email_to = settings.EMAIL_JULO_INFO_SEPULSA
        email_from = EMAIL_DEV
        status, body, headers = self.send_email(subject, msg, email_to, email_from)

        logger.info({
            'action': 'email_notif_balance_sepulsa_low',
            'balance': balance,
            'time': timezone.localtime(timezone.now()).date()
        })

        return status, subject, msg

    def email_notif_grab(self, email):
        # send julo review challenge email
        template = 'email_notif_grab'

        msg = render_to_string(template + '.html')
        email_to = email
        subject = 'Selamat Pinjaman Anda di Setujui'
        email_from = EmailDeliveryAddress.CS_JULO
        name_from = "JULO"
        status, body, headers = self.send_email(subject,
                                                msg, email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from)

        logger.info({
            'action': 'email_notif_grab',
            'email': email
        })

        return status, body, headers

    def email_fraud_alert(self, loan):
        """ send email reminder for alert aplicant about 'julo pinance' fraud on Facebook page
        """
        template = 'email_fraud_alert'

        msg = render_to_string(template + '.html')
        email_to = loan.application.email
        subject = 'Waspadai Modus Penipuan Mengatasnamakan JULO'
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_fraud_alert',
            'loan_id': loan.id
        })

        return status, headers, subject, msg

    def email_lebaran_promo(self, email):
        """
        send email for lebaran promo
        """
        template = 'email_lebaran_promo'

        msg = render_to_string(template + '.html')
        email_to = email
        subject = 'Diskon Ramadhan'
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_lebaran_promo',
            'email': email
        })

        return status, headers, subject, msg

    def email_loc_notification(self, email_to, message):
        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        subject = REMINDER_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, message, email_to, email_from, name_from=None)
        return status, headers, subject, message

    def email_followup_105_110(self, application):
        """
        send email to followup customer 105 110
        """

        template = 'email_followup_{}'.format(application.application_status.status_code)
        context = {
            'year': timezone.localtime(timezone.now()).date().strftime('%Y'),
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=application.application_status.status_code
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = 'Ayo lanjutkan pengajuan pinjaman Anda!'

        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_followup',
            'application': application
        })

        return status, headers, subject, msg

    def email_courtesy(self, application):
        """ send email reminder for status change to 105
        """
        template = 'email_courtesy_call'
        context = {
            'name': application.fullname_with_title,
            'reason': application.loan_purpose
        }

        msg = render_to_string(template + '.html', context)
        email_to = application.email
        if not email_to:
            email_to = application.customer.email

        email_from = EmailDeliveryAddress.CS_JULO
        subject = 'Apa Kabar dari JULO' + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to, email_from)

        logger.info({
            'action': 'send_email_notification_180',
            'application_id': application.id
        })

        return status, headers, msg, subject

    def email_reminder_grab(self, payment, template):
        """
        send email reminder for grab product
        """
        application = payment.loan.application
        fullname = application.fullname_with_title
        payment_number = payment.payment_number
        due_amount = payment.due_amount

        context = {
            'fullname': fullname,
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
        }
        msg = render_to_string(template + '.html', context)

        email_to = application.email
        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        subject = REMINDER_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to, email_from, name_from=None)
        return status, headers, subject, msg

    def email_paid_of_grab(self, email_to, template):
        """
        send email for lebaran promo
        """
        msg = render_to_string(template + '.html')
        email_to = email_to
        subject = 'Selamat Pinjaman Anda Lunas!'
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_email_paid_of_grab',
            'email': email_to
        })

        return status, headers, subject, msg

    def email_market_survey_blast(self, email):
        # send market survey email
        template = 'email_market_survey'

        msg = render_to_string(template + '.html')
        email_to = email
        subject = "Mau Hadiah Uang Tunai 3 Juta?"
        email_from = EmailDeliveryAddress.CS_JULO
        name_from = "Tim Riset JULO"
        reply_to = "marketing@julofinance.com"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'send_email_market_survey',
            'email': email
        })

        return status, headers, subject, msg

    def email_julo_promo_blast(self, email, name, gender):
        # send market survey email
        title = "Bapak/Ibu"
        if gender == "Pria":
            title = "Bapak"
        elif gender == "Wanita":
            title = "Ibu"

        template = 'email_julo_promo_blast'
        context = {
            'name': name,
            'title': title
        }

        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = "Apply Lagi & Dapatkan Kejutan Bunga 0%"
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "marketing@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_julo_promo_blast',
            'email': email
        })

        return status, headers, subject, msg

    def email_promo_asian_games_blast(self, email):
        template = 'email_promo_asian_games'
        context = {}
        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = "Promo Cashback Asian Games"
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "marketing@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)
        logger.info({
            'action': 'email_promo_asian_games_blast',
            'email': email
        })

        return status, headers, subject, msg

    def email_early_payment_blast(self, email, due, fullname):
        if due == 't-2':
            template = 'email_early_payment_t-2_blast'
        elif due == 't0':
            template = 'email_early_payment_t0_blast'
        context = {'fullname': fullname}
        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = "Menangkan Undian UANG TUNAI Rp 2.5 juta"
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "marketing@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)
        logger.info({
            'action': 'email_early_payment_t-2_blast',
            'email': email
        })

        return status, headers, subject, msg

    def email_va_notification(self, application):
        template = 'email_va_notification'
        context = {
            'fullname': application.fullname_with_title,
            'link': 'http://www.julofinance.com/android/goto/payment_methods',
        }
        msg = render_to_string(template + '.html', context)
        email_to = application.email
        subject = INFO_TITLE + ' - ' + email_to
        status, body, headers = self.send_email(subject, msg, email_to)

        return status, headers, subject, msg

    def email_coll_campaign_sept_21_blast(self, email, variant, fullname):

        subjects = {"Test: HP Samsung": "Mau Hadiah HP Samsung?",
                    "Test: 2 juta": "Mau Hadiah Uang Tunai Rp 2.000.000?",
                    "Test: 5 juta": "Mau Hadiah Uang Tunai Rp 5.000.000?"}
        templates = {"Test: HP Samsung": "email_coll_campaign_sept_21_blast_hp",
                     "Test: 2 juta": "email_coll_campaign_sept_21_blast_2jt",
                     "Test: 5 juta": "email_coll_campaign_sept_21_blast_5jt"}

        context = {'fullname': fullname}
        msg = render_to_string(templates[variant] + '.html', context)
        email_to = email
        subject = subjects[variant]
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "marketing@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)
        logger.info({
            'action': 'email_coll_campaign_sept_21_blast',
            'email': email
        })

        return status, headers, subject, msg

    def remarketing_106_blast(self, email, gender, fullname):

        subject = "Hi, %s! Anda mendapatkan kesempatan pinjaman hingga 8 juta!" % fullname
        template = "email_blast_retargeting_106"
        title = "Bapak " if gender == "Pria" else "Ibu "

        context = {'full_name_with_title': title + fullname}
        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = subject
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "marketing@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)
        logger.info({
            'action': 'email_remarketing_106_blast',
            'email': email
        })

        return status, headers, subject, msg

    def agreement_email(self, email, message, subject):
        email_from = "legal.dept@julo.co.id"
        name_from = "JULO"
        reply_to = "legal.dept@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                message,
                                                email,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to

                                                )
        logger.info({
            'action': 'email_remarketing_106_blast',
            'email': email
        })

        return status, headers, subject, message

    def notification_permata_prefix_email(self, email, message):
        subject = "[UPDATE] Perubahan Nomor Virtual Account Bank Permata JULO"
        email_from = "info@julo.co.id"
        name_from = "JULO"
        reply_to = "info@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                message,
                                                email,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to

                                                )
        logger.info({
            'action': 'notification_permata_prefix_email',
            'email': email
        })

        return status, headers, subject, message

    def custom_for_blast(self, email, gender, fullname, subject, template):
        title = "Bapak " if gender == "Pria" else "Ibu "
        context = {'full_name_with_title': '{}{}'.format(title, fullname)}
        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = subject
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "marketing@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)
        logger.info({
            'action': template,
            'email': email
        })
        return status, headers, subject, msg

    def email_reconfirmation_175(self, email, fullname, disbursment_date, bank_name, account_number, holder_name, template):
        """ send email reconfirmation for bank account data
        """
        template = template
        context = {
            'fullname': fullname,
            'date': date.strftime(disbursment_date, '%d-%b-%Y'),
            'bank_name': bank_name,
            'account_number': account_number,
            'holder_name': holder_name
        }
        subject = 'Konfirmasi Pencairan Dana'
        msg = render_to_string(template + '.html', context)
        email_to = email
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from)

        logger.info({
            'action': 'email_reconfirmation_175',
            'template': template,
            'time': timezone.localtime(timezone.now())
        })

        return status, headers, subject, msg

    def email_lottery_winner_blast(self, email, fullname_with_title):
        template = 'email_lottery_winner_dec'
        context = {
            'fullname_with_title': fullname_with_title,
            'lottery': settings.EMAIL_STATIC_FILE_PATH + 'lottery.jpg'
        }
        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = "Pengumuman Pemenang Undian Uang Tunai 20 Juta"
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "marketing@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)
        logger.info({
            'action': 'email_lottery_winner_blast',
            'email': email
        })

        return status, headers, subject, msg

    def partner_reminder_email(self, email, fullname, shorturl, subject):
        """
        send partner_reminder_email
        """
        template = 'email_partner_referal_reminder'
        context = {"fullname":fullname, "shorturl":shorturl}
        msg = render_to_string(template + '.html', context)
        email_to = email
        subject = subject
        email_from = "cs@julo.co.id"
        name_from = "JULO"
        reply_to = "cs@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)
        logger.info({
            'action': 'partner_reminder_email',
            'email': email
        })

        return status, headers, msg

    def cashback_management_email(self, email, email_type, data):
        """
        send email related to manual cashback promo
        """
        email_template = {
            CashbackPromoConst.EMAIL_TYPE_REQUESTER_NOTIF: 'email_notif_for_requester',
            CashbackPromoConst.EMAIL_TYPE_APPROVER_NOTIF: 'email_notif_for_approvers',
            CashbackPromoConst.EMAIL_TYPE_APPROVAL: 'email_approval',
            CashbackPromoConst.EMAIL_TYPE_REJECTION:'email_rejection'}
        name = email.split('@')[0]

        template = email_template[email_type]
        context = {"promo_name":data['promo_name'], "name":name}
        attachment_dict = None

        if email_type == CashbackPromoConst.EMAIL_TYPE_APPROVER_NOTIF:
            context['approval_link'] = data['approval_link']
            context['rejection_link'] = data['rejection_link']
            context['department'] = data['department']
            excel_file, file_type = get_excel_for_cashback_promo_email(
                data['document_url'], data['filename'])
            attachment_dict = {'content': excel_file,
                               'filename': data['filename'], 'type': file_type }

        msg = render_to_string('cashback_promo/' + template + '.html', context)
        name_from = "Cashback Management" + data['promo_name']
        email_to = email
        subject = 'Permohonan Pengajuan Cashback'
        email_from = "cashbackmanagement@julo.co.id"
        reply_to = "cashbackmanagement@julo.co.id"

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to,
                                                attachment_dict=attachment_dict,
                                                content_type="text/html")
        logger.info({
            'action': 'cashback_management_%s' % type,
            'email': email
        })

        return status, headers, msg

    def email_waive_pede_campaign(self, loan, principal_amount, late_fee_amount,
                                  interest_amount, due_amount):
        customer = loan.customer
        title = 'Bapak/Ibu'
        gender = customer.gender

        if gender == 'Pria':
            title = 'Bapak'
        elif gender == 'Wanita':
            title = 'Ibu'

        indomaret_va = PaymentMethod.objects.get_or_none(loan=loan,
                                                         payment_method_name='INDOMARET')

        context = {
            'fullname_with_title': title + ' ' + customer.fullname,
            'principal_amount': principal_amount,
            'late_fee_amount': late_fee_amount,
            'interest_amount': interest_amount,
            'due_amount': due_amount,
            'julo_bank_name': loan.julo_bank_name,
            'julo_bank_account_number': loan.julo_bank_account_number,
            'indomaret_va': indomaret_va.virtual_account
        }

        party_popper_emoji = u'\U0001F389'
        subject = "Bebaskan dirimu dari beban hutang!" + party_popper_emoji
        template = 'email_pede_oct.html'
        msg = render_to_string(template, context)
        email_to = customer.email
        email_from = 'promotions@julo.co.id'
        name_from = 'Julo Promotions'
        reply_to = 'promotions@julo.co.id'
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_waive_pede_campaign_promo',
            'context': context,
            'email': email_to
        })

        return status, headers, subject, msg

    def notification_permata_new_va_email(self, email, message):
        subject = "Perubahan Nomor Virtual Account Pembayaran"
        email_from = "info@julo.co.id"
        name_from = "JULO"
        reply_to = "info@julo.co.id"
        status, body, headers = self.send_email(subject,
                                                message,
                                                email,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to
                                                )
        logger.info({
            'action': 'notification_permata_new_va_email',
            'email': email
        })

        return status, headers, subject, message

    def email_waive_sell_off_campaign(self, loan, principal_amount, late_fee_amount,
                                      interest_amount, due_amount, eighty_percent_principal,
                                      subject):
        customer = loan.customer
        title = 'Bapak/Ibu'
        gender = customer.gender

        if gender == 'Pria':
            title = 'Bapak'
        elif gender == 'Wanita':
            title = 'Ibu'

        context = {
            'fullname_with_title': title + ' ' + customer.fullname,
            'principal_amount': principal_amount,
            'late_fee_amount': late_fee_amount,
            'interest_amount': interest_amount,
            'due_amount': due_amount,
            'julo_bank_name': loan.julo_bank_name,
            'julo_bank_account_number': loan.julo_bank_account_number,
            'principal_amount_80_percent': eighty_percent_principal
        }

        template = 'email_sell_off_campaign.html'
        msg = render_to_string(template, context)
        email_to = customer.email
        email_from = 'promotions@julo.co.id'
        name_from = 'Julo Promotions'
        reply_to = 'promotions@julo.co.id'
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_sell_off_campaign_promo',
            'context': context,
            'email': email_to
        })

        return status, headers, msg

    def email_notify_backup_va(self, customer, first_name, bank_code, va_method, va_number):
        context = {
            'first_name': first_name,
            'bank_code': bank_code,
            'va_method': va_method,
            'va_number': va_number
        }

        subject = 'Perubahan Nomor Virtual Account Pembayaran'
        template = 'email-notify-backup-va.html'
        msg = render_to_string(template, context)
        email_to = customer.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = 'marketing@julo.co.id'

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'emailf_notify_backup_va',
            'email': email_to
        })

        return status, headers, subject, msg

    def email_loan_refinancing_eligibility(self, customer, encoded_customer_data):
        title = 'Bapak/Ibu'
        gender = customer.gender

        if gender == 'Pria':
            title = 'Bapak'
        elif gender == 'Wanita':
            title = 'Ibu'

        context = {
            'fullname_with_title': title + ' ' + customer.fullname,
            'encoded_link': settings.JULO_WEB_URL + '/refinancingreason/' + encoded_customer_data
        }

        subject = 'Kesempatan Untuk Membayar Hutang Anda Lebih Mudah'
        template = 'loan_refinancing_eligibility_email.html'
        msg = render_to_string(template, context)
        email_to = customer.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_notify_eligible_loan_refinancing',
            'email': email_to
        })

        soap = BeautifulSoup(msg, features="lxml").find('body')
        body_msg = " ".join(soap.get_text().split())

        return status, headers, subject, body_msg

    def email_loan_refinancing_request(self, customer_info, payment_info):
        customer = customer_info['customer']
        title = 'Bapak/Ibu'
        gender = customer.gender

        if gender == 'Pria':
            title = 'Bapak'
        elif gender == 'Wanita':
            title = 'Ibu'

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['fullname', 'email'],
        )

        context = {
            'fullname_with_title': title + ' ' + customer_detokenized.fullname,
            'bank_code': customer_info['bank_code'],
            'va_number': customer_info['va_number'],
            'bank_name': customer_info['bank_name'],
            'payments': payment_info['new_payment_structures'],
            'total_due_amount': format_currency(payment_info['total_due_amount'], 'IDR'),
            'due_amount': format_currency(payment_info['due_amount'], 'IDR'),
            'late_fee_discount': format_currency(payment_info['late_fee_discount'], 'IDR'),
            'chosen_tenure': payment_info['chosen_tenure']
        }

        subject = 'Permintaan Perpanjangan Tenor Pinjaman Anda Telah Disetujui'
        template = 'loan_refinancing_request.html'
        msg = render_to_string(template, context)
        email_to = customer_detokenized.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_request',
            'email': email_to
        })

        soap = BeautifulSoup(msg, features="lxml").find('body')
        body_msg = " ".join(soap.get_text().split())

        return status, headers, subject, body_msg

    def email_loan_refinancing_success(self, customer):
        title = 'Bapak/Ibu'
        gender = customer.gender

        if gender == 'Pria':
            title = 'Bapak'
        elif gender == 'Wanita':
            title = 'Ibu'

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['fullname', 'email'],
        )

        context = {'fullname_with_title': title + ' ' + customer_detokenized.fullname}
        subject = 'Perpanjangan Tenor Pinjaman Anda Telah Aktif'
        template = 'loan_refinancing_active.html'
        msg = render_to_string(template, context)
        email_to = customer_detokenized.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_success',
            'email': email_to
        })

        soap = BeautifulSoup(msg, features="lxml").find('body')
        body_msg = " ".join(soap.get_text().split())

        return status, headers, subject, body_msg

    def email_notify_loan_selloff(self, loan, selloff_data):
        payments = loan.payment_set.all().order_by('payment_number')

        context = {
            'payments': payments,
            'total_outstanding': selloff_data['total_outstanding'],
            'dpd': loan.get_oldest_unpaid_payment().due_late_days,
            'ajb_number': selloff_data['ajb_number'],
            'ajb_date': selloff_data['ajb_date'],
            'buyer_vendor_name': selloff_data['buyer_vendor_name'],
            'collector_vendor_name': selloff_data['collector_vendor_name'],
            'collector_vendor_phone': selloff_data['collector_vendor_phone']
        }

        subject = 'PEMBERITAHUAN PENGALIHAN HAK ATAS TAGIHAN'
        template = 'email_selloff_notif.html'
        msg = render_to_string(template, context)
        email_to = loan.customer.email
        email_from = 'departemenhukum@julo.co.id'
        reply_to = 'departemenhukum@julo.co.id'

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email-selloff_notif',
            'email': email_to
        })

        return status, headers, subject, msg, template

    def email_notify_loan_selloff_j1(self, context, email_to):
        template_code = "asset_sellof_batch.html"
        subject = 'PEMBERITAHUAN PENGALIHAN HAK ATAS TAGIHAN'
        msg = render_to_string(template_code, context)
        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        name_from = 'JULO'

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_osp_recovery',
            'email': email_to
        })

        return status, headers, subject, msg, template_code


    def email_osp_recovery(self, context, email_to):
        template_code = "email_OSP_recovery_apr2020.html"
        subject = '#LebihHemat - Promo refund biaya bunga 40% untuk Anda! (berlaku hingga 15 April)'
        msg = render_to_string(template_code, context)
        email_from = 'promotions@julo.co.id'
        name_from = 'JULO'
        reply_to = 'marketing@julo.co.id'
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_osp_recovery',
            'email': email_to
        })

        return status, headers, subject, msg

    def email_covid_refinancing_approved_for_all_product(self, customer_info, payment_info, subject,\
                                                         template, calendar_link):

        customer = customer_info['customer']
        application = customer.application_set.regular_not_deletes().last()

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['email'],
        )

        context = {
            'fullname_with_title': application.fullname_with_title,
            'bank_code': customer_info['bank_code'],
            'va_number': customer_info['va_number'],
            'bank_name': customer_info['bank_name'],
            'payments': payment_info['new_payment_structures'],
            'late_fee_discount': display_rupiah(payment_info['late_fee_discount']),
            'covid_installment': display_rupiah(payment_info['prerequisite_amount']),
            'first_due_date': format_date(payment_info['due_date'], 'd MMMM yyyy', locale='id_ID'),
            'tenure_extension': payment_info['tenure_extension'],
            'calendar_link': calendar_link
        }


        msg = render_to_string(template, context)
        email_to = customer_detokenized.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_request',
            'email': email_to
        })
        template = 'approved_first_email_R1R2R3'
        return status, headers, subject, msg, template

    def email_covid_refinancing_activated_for_all_product(
            self, customer, subject, template, payments, calendar_link, is_for_j1=False):
        application = customer.application_set.regular_not_deletes().last()
        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['email'],
        )
        context = {
            'fullname_with_title': application.fullname_with_title,
            "payments": payments,
            "is_for_j1": is_for_j1,
            "calendar_link": calendar_link
        }
        msg = render_to_string(template, context)
        email_to = customer_detokenized.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_covid_refinancing_activated_for_all_product',
            'email': email_to,
            'template': template
        })
        template = 'activated_offer_refinancing_email'

        return status, headers, subject, msg, template

    # send email for lebaran campaign 2020 - Based on the date
    def email_lebaran_campaign_2020(self, application, date, tnc_url, payment_url, is_partner=False):
        moneywing_emoji = u'\U0001F4B8'
        astonishedface_emoji = u'\U0001F632'
        if application.gender == 'Pria':
            name_title = "Bapak"
        elif application.gender == 'Wanita':
            name_title = "Ibu"
        else:
            name_title = ""
        context = {
            "name_title": name_title,
            "first_name": application.first_name_only,
            "url_shortened": tnc_url,
            "payment_url": payment_url
        }
        banner_base_url = "https://julocampaign.julo.co.id/lebaran_2020/"
        if is_partner:
            if date.day == 24 and date.month == 4:
                template = 'lebaran20_email_reminder_1_laku6_pede.html'
                subject = 'KESEMPATAN SPESIAL' + astonishedface_emoji + \
                          ' Uang Tunai Jutaan Rupiah Menunggu Anda, nih!' + \
                          moneywing_emoji
                context["banner_url"] = banner_base_url + "Reminder-Undian-Ramadhan-Highseason-(Coll-Request)%201.gif"
            elif date.day == 9 and date.month == 5:
                template = 'lebaran20_email_reminder_2_laku6_pede.html'
                subject = 'KESEMPATAN TERAKHIR' + astonishedface_emoji + \
                          ' Uang Tunai Jutaan Rupiah Menunggu Anda, nih!' + moneywing_emoji
                context["banner_url"] = banner_base_url + "Copy-Reminder-Undian-Ramadhan-Highseason-%28Coll-Request%29.gif"
        else:
            if date.day == 24 and date.month == 4:
                template = 'lebaran20_email_reminder_1_mtl.html'
                subject = 'Bayar Cicilan JULO, Dapat Uang Tunai Jutaan Rupiah?' + moneywing_emoji + \
                          ' Yakin nggak mau?' + astonishedface_emoji
                context["banner_url"] = banner_base_url + "Undian-Ramadhan-Highseason-(Coll-Request).gif"
            elif date.day == 9 and date.month == 5:
                template = 'lebaran20_email_reminder_2_mtl.html'
                subject = 'KESEMPATAN TERAKHIR' + astonishedface_emoji + \
                          ' Uang Tunai Jutaan Rupiah Menunggu Anda, nih!' + moneywing_emoji
                context["banner_url"] = banner_base_url + "Reminder-Undian-Ramadhan-Highseason-(Coll-Request).gif"
        msg = render_to_string(template, context)
        email_from = "promotion@julo.co.id"
        email_to = application.email
        logger.info({
            'action': 'send_email_lebaran_campaign_2020',
            'email': email_to
        })
        status, body, headers = self.send_email(subject, msg, email_to,
                                                email_from=email_from)
        return status, headers, subject, msg, template

    def email_early_payoff_campaign(self, context, email_to):
        template_code = "email_early_payoff_campaign.html"
        subject = 'Diskon 30% biaya bunga, eksklusif untuk {}'.format(context['fullname_with_title'])
        email_from = 'promotions@julo.co.id'
        name_from = 'JULO'
        reply_to = 'cs@julo.co.id'

        msg = render_to_string(template_code, context)

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_early_payoff',
            'email': email_to
        })

        return status, headers, subject, msg

    def email_covid_refinancing_opt(self, customer_info, subject, template, template_code):

        customer = customer_info['customer']
        application = customer.application_set.regular_not_deletes().last()

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['email'],
        )

        context = {
            'fullname_with_title': application.fullname_with_title,
            'base_url': settings.BASE_URL,
            'approval_url': '{}covid_approval/{}/'.format(
                CovidRefinancingConst.URL, customer_info['encrypted_uuid']),
            'banner_setujuwebpage': settings.EMAIL_STATIC_FILE_PATH + 'banner_setujuwebpage.png',
            'banner_p1_opt': settings.EMAIL_STATIC_FILE_PATH + 'banner_p1_opt.png',
            'count_down_image_url': f"{settings.BASE_URL}/api/loan_refinancing/"
                                    f"v1/countdown_time/"
                                    f"{customer_info['encrypted_uuid']}/"
        }

        msg = render_to_string(template, context)
        email_to = customer_detokenized.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_covid_refinancing_opt',
            'email': email_to
        })
        return status, headers, subject, msg, template_code

    def email_covid_refinancing_approved_for_r4(self, customer_info, payment_info, subject,
                                                template, calendar_link, is_bucket_5=False):
        customer = customer_info['customer']
        application = customer.application_set.regular_not_deletes().last()
        email = collection_detokenize_sync_object_model(
            'customer', customer, customer.customer_xid, ['email']
        ).email

        context = {
            'fullname_with_title': application.fullname_with_title,
            'firstname_with_title': application.first_name_with_title,
            'bank_code': customer_info['bank_code'],
            'va_number': customer_info['va_number'],
            'bank_name': customer_info['bank_name'],
            'prerequisite_amount': display_rupiah(payment_info['prerequisite_amount']),
            'first_due_date': format_date(payment_info['due_date'], 'd MMMM yyyy', locale='id_ID'),
            'calendar_link': calendar_link,
        }
        if payment_info.get('total_discount_percent'):
            context['total_discount_percent'] = payment_info['total_discount_percent']

        if 'total_payments' in payment_info:
            context['total_payments'] = display_rupiah(payment_info['total_payments'])

        context['is_bucket_5'] = is_bucket_5

        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        msg = render_to_string(template, context)
        email_to = email

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_approved_r4',
            'email': email_to
        })

        return status, headers, subject, msg

    def email_covid_pending_refinancing_approved_for_all_product(self, customer_info, payment_info, subject, \
                                                                 template):

        customer = customer_info['customer']
        application = customer.application_set.regular_not_deletes().last()

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['email'],
        )

        context = {
            'fullname_with_title': application.fullname_with_title,
            'bank_code': customer_info['bank_code'],
            'va_number': customer_info['va_number'],
            'bank_name': customer_info['bank_name'],
            'payments': payment_info['new_payment_structures'],
            'first_payment_number': payment_info['new_payment_structures'][0]['payment_number'],
            'late_fee_discount': display_rupiah(payment_info['late_fee_discount']),
            'covid_installment': display_rupiah(payment_info['prerequisite_amount']),
            'first_due_date': format_date(payment_info['due_date'], 'd MMMM yyyy', locale='id_ID'),
            'tenure_extension': payment_info['tenure_extension']
        }


        msg = render_to_string(template, context)
        email_to = customer_detokenized.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_request',
            'email': email_to
        })

        return status, headers, subject, msg, template

    def email_intelix_error_report(self, failed_stores, uploader_email):
        """
        send email to uploader intelix
        """

        context = {
            'failed_stores': failed_stores
        }
        message = render_to_string('intelix_reporting_results.html', context)
        email_to = uploader_email
        subject = 'Error Report Intelix call results'

        status, body, headers = self.send_email(subject, message, email_to)

        logger.info({
            'action': 'email_intelix_error_report',
            'uploader_email': uploader_email
        })

        return status, body, headers, message

    def email_lock_pin(self, name, max_wait, max_retry, unlock_time, email_to):
        """
        send email to inform lock pin
        """

        context = {
            'name': name,
            'max_wait': max_wait,
            'max_retry': max_retry,
            'unlock_time': unlock_time
        }
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        message = render_to_string('email/temporary_account_block_pin_start.html', context)
        email_to = email_to
        subject = '%s, akun JULO Anda sedang Terblokir Sementara' % name

        status, _body, headers = self.send_email(
            subject, message, email_to,
            email_from=email_from,
            name_from=name_from)

        logger.info({
            'action': 'email_lock_pin',
            'email_to': email_to
        })

        return status, subject, headers

    def email_unlock_pin(self, name, email_to):
        """
        send email to inform unlock pin
        """

        context = {
            'name': name,
        }

        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        message = render_to_string('email/temporary_account_block_pin_end.html', context)
        email_to = email_to
        subject = '%s, Masa Pemblokiran Sementara Akun Anda Telah Berakhir!' % name

        status, _body, headers = self.send_email(
            subject, message, email_to,
            email_from=email_from,
            name_from=name_from)

        logger.info({
            'action': 'email_lock_pin',
            'email_to': email_to
        })

        return status, subject, headers

    def email_multiple_payment_ptp(
            self, customer_info, payment_info, subject, template):
        customer = customer_info['customer']
        application = customer.application_set.regular_not_deletes().last()

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['email'],
        )

        context = {
            'firstname_with_title': application.first_name_with_title,
            'bank_code': customer_info['bank_code'],
            'va_number': customer_info['va_number'],
            'bank_name': customer_info['bank_name'],
            'is_bucket_5': payment_info['is_bucket_5'],
            'multiple_payment_ptp': payment_info['multiple_payment_ptp'],
        }

        check_keys = ['sequence_txt', 'total_remaining_amount', 'is_on_promised_date']
        for check_key in check_keys:
            context[check_key] = None
            if check_key in payment_info:
                context[check_key] = payment_info[check_key]

        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        msg = render_to_string(template, context)
        email_to = customer_detokenized.email

        status, body, headers = self.send_email(
            subject, msg, email_to, email_from=email_from, email_cc=None,
            name_from=name_from, reply_to=reply_to
        )
        logger.info({'action': 'email_immediate_multiple_payment_ptp', 'email': email_to})

        return status, headers, subject, msg

    def email_multiple_ptp_and_expired_plus_1(
            self, customer_info, payments_or_account_payments_info,
            is_bucket_5, subject, template):
        context = {
            'firstname_with_title': customer_info['firstname_with_title'],
            'bank_code': customer_info['bank_code'],
            'va_number': customer_info['va_number'],
            'bank_name': customer_info['bank_name'],
            'is_bucket_5': is_bucket_5,
            'payments_or_account_payments': payments_or_account_payments_info,
        }

        if is_bucket_5:
            email_from = EmailDeliveryAddress.COLLECTIONS_JTF
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        else:
            email_from = 'cs@julo.co.id'
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        msg = render_to_string(template, context)
        email_to = customer_info['email']

        status, body, headers = self.send_email(
            subject, msg, email_to, email_from=email_from, email_cc=None,
            name_from=name_from, reply_to=reply_to
        )
        logger.info({'action': 'email_immediate_email_multiple_ptp_and_expired_plus_1', 'email': email_to})

        return status, headers, subject, msg

    def email_june_2022_promo(self, customer, banner_url, due_date, url_shortener):
        context = {
            'banner_url': banner_url,
            'due_date': due_date,
            'url_shortener': url_shortener
        }
        moneywing = u'\U0001F4B8'
        subject = 'Kilau Juni Melesat, Menangkan Hadiah Emasnya!💸 %s' % moneywing
        template = 'email_june2022_hi_season.html'
        msg = render_to_string(template, context)
        email_to = customer.email
        email_from = 'cs@julo.co.id'
        name_from = 'JULO'
        reply_to = 'cs@julo.co.id'
        status, body, headers = self.send_email(
            subject,
            msg,
            email_to,
            email_from=email_from,
            email_cc=None,
            name_from=name_from,
            reply_to=reply_to
        )

        logger.info({
            'action': 'email_june_2022_promo',
            'email': email_to
        })

        return status, headers, subject, msg

    def fraud_report_email(self, fraud_report, attachment_dict):
        # send fraud report email to julo cs

        template = 'fraud_report_email'

        msg = render_to_string(template + '.html', context={'report':fraud_report})
        email_to = "cs@julo.co.id"
        subject = "FRB_Report"
        email_from = "fraud.report@julo.co.id"
        reply_to = email_from
        application = fraud_report.application
        if application:
            detokenized_application = detokenize_pii_antifraud_data(
                PiiSource.APPLICATION, [application], ['email']
            )[0]
            if detokenized_application.email:
                reply_to = detokenized_application.email
            else:
                detokenized_customer = detokenize_pii_antifraud_data(
                    PiiSource.CUSTOMER, [application.customer], ['email']
                )[0]
                reply_to = detokenized_customer.email
        name_from = "JULO Fraud Report"
        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to,
                                                attachment_dict=attachment_dict,
                                                content_type='text/html')
        # TODO: remove reply_to from logger later
        logger.info({
            'action': 'fraud_report_email',
            'fraud_report_id': str(fraud_report.id),
            'reply_to': reply_to,
            'status': str(status)
        })
        return status, headers, subject, msg

    def email_bni_va_generation_limit_alert(self, bni_va_count, subject, email_to, email_cc):
        # send email to notify the generation limit for BNI VA

        template = 'email_bni_va_generation_limit_alert.html'
        message = render_to_string(template, context={'bni_va_count':bni_va_count})
        status, body, headers = self.send_email(subject=subject,
                                                content=message,
                                                email_to=email_to,
                                                email_cc=email_cc)
        logger.info({
            'action': 'email_to_notify_bni_va_generation_limit_reached',
            'email_to': email_to,
            'email_cc': email_cc,
            'status': str(status)
        })
        return status, headers, message

    def send_grab_email_based_on_template_code(self, template_code, application, hour=72):
        if application.fullname_with_short_title:
            fullname = application.fullname_with_short_title
        else:
            fullname = application.customer.fullname_with_short_title
        if fullname is None:
            fullname = ''

        context = {'fullname': fullname, 'hour': hour}
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            product=Product.EMAIL.GRAB,
            dpd__isnull=True,
            ptp__isnull=True,
            extra_conditions__isnull=True,
            status_code_id=application.application_status_id,
            is_active=True
        )
        streamlined_comm = StreamlinedCommunication.objects.filter(**filter_).last()
        if not streamlined_comm:
            return

        msg = process_streamlined_comm(filter_, replaced_data=context)
        email_to = application.email
        subject = streamlined_comm.subject
        status, body, headers = self.send_email(subject, msg, email_to)

        logger.info({
            'action': 'send_grab_email_based_on_template_code',
            'template_code': template_code,
            'application_id': application.id
        })
        message_id = headers['X-Message-Id']
        EmailHistory.objects.create(
            application=application,
            customer=application.customer,
            sg_message_id=message_id,
            to_email=email_to,
            subject=subject,
            message_content=msg,
            template_code=template_code
        )

        return

    def email_notify_loan_suspension_j1(
        self, context: Dict[str, Any], email_to: str
    ) -> Tuple[int, Any, str, str, str]:
        template_code = "julo_risk_suspension_email_information.html"
        subject = 'Maaf, Limit Kredit JULOmu Dinonaktifkan'
        msg = render_to_string(template_code, context)
        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
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

        logger.info({'action': 'email_notify_loan_suspension_j1', 'email': email_to})

        return status, headers, subject, msg, template_code

    def email_notify_loan_reactivation_j1(
        self, context: Dict[str, Any], email_to: str
    ) -> Tuple[int, Any, str, str, str]:
        template_code = "email_notify_back_to_420.html"
        subject = 'Kamu Udah Bisa Transaksi di JULO Lagi, Lho!'
        msg = render_to_string(template_code, context)
        email_from = EmailDeliveryAddress.CS_JULO
        reply_to = EmailDeliveryAddress.CS_JULO
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

        logger.info({'action': 'email_notify_loan_reactivation_j1', 'email': email_to})

        return status, headers, subject, msg, template_code

    def email_payment_success_notification(
        self,
        context: Dict[str, Any],
        email_to: str,
        subject: str = None,
        template_code: str = None,
    ) -> Tuple[int, Any, str, str, str]:
        msg = render_to_string(template_code, context)
        email_from = EmailDeliveryAddress.REPAYMENT_NOREPLY
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
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

        logger.info({'action': 'email_payment_success_notification', 'email': email_to})

        return status, headers, subject, msg, template_code

    def email_bni_va_limit(self, msg=""):
        email_from = EmailDeliveryAddress.REPAYMENT_NOREPLY
        reply_to = EmailDeliveryAddress.REPAYMENT_NOREPLY
        name_from = 'JULO - Repayment Service'
        subject = 'WARNING - BNI Virtual Account Suffix Limit'
        email_to = (
            EmailDeliveryAddress.REPAYMENT_NOREPLY
            + ',chris.paulus@julofinance.com,tiarani.nurfadilla@julofinance.com,rikki@julofinance.com'
        )

        status, body, headers = self.send_email(
            subject,
            msg,
            email_to,
            email_from=email_from,
            email_cc=None,
            name_from=name_from,
            reply_to=reply_to,
        )

        logger.info({'action': 'email_bni_va_limit', 'email': email_to})

        return msg, headers
