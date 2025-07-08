from __future__ import print_function
from builtins import str
import logging
import sys
import csv
import re
from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone
from babel.numbers import format_number
from datetime import datetime
from datetime import date
from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from juloserver.julo.clients import get_url_shorten_service
from juloserver.julo.models import Customer, Loan, Payment, PaymentMethod, WarningUrl, PaymentMethodLookup
from ...clients import get_julo_sms_client, get_julo_email_client
from juloserver.julo.services2 import encrypt
from ...models import EmailHistory
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def __init__(self):
        self.shorten = get_url_shorten_service()
        self.sms = get_julo_sms_client()
        self.email = get_julo_email_client()
        self.encrypt = encrypt()
        self.warning_types = ["1", "2", "3"]
        self.templates = {
            "1": {"email": "email.html", "sms": "sms_agreement.txt",
                  'url': settings.AGREEMENT_WEBSITE ,"subject": "Surat Peringatan Pertama"},
            "2": {"email": "email_warning_2.html", "sms": "sms_agreement_2.txt",
                  "url": settings.AGREEMENT_WEBSITE_2,"subject": "Surat Peringatan Kedua"},
            "3": {"email": "email_warning_3.html", "sms": "sms_agreement_3.txt",
                  "url": settings.AGREEMENT_WEBSITE_3, "subject": "Surat Peringatan Ketiga"},
        }

    def handle(self, *args, **options):
        csv_file_name = options['file']
        self.type = options['type']
        self.warning_type = options['warning']

        if self.type not in ['email', 'sms']:
            logger.error("invalid type. type should be 'email' or 'sms' ")
            return

        if self.warning_type not in self.warning_types:
            logger.error("invalid  warning type. type should be  1 , 2 or 3")
            return
        self.template = self.templates[self.warning_type]
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                # self.send_agreement(row['loan_id'],row['Blast_date'])
                self.send_agreement(row['loan_id'], '')
        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return

    def log_url(self, customer, url, url_type):
        if self.url:
            return False
        return WarningUrl.objects.create(
            customer=customer,
            url=url,
            is_enabled=True,
            url_type=url_type,
            warning_method=self.warning_type
        )

    def send_sms(self, customer, url):
        if self.url:
            url = self.url.url
        else:
            url = url + "#sms"
        context = {
            "url": url,
        }
        text_message = render_to_string(self.template['sms'], context=context)
        if self.phone_validation(customer.phone):
            self.sms.sms_agreement(customer.phone, text_message)
            self.log_url(customer, url, "sms")
        else:
            logger.debug('Invalid Phone Number :' + customer.phone)
            raise ValueError('Not a Valid Phone Number')

    def send_email(self, customer, loan, url, last_date):

        url = url + "#email"
        application = loan.application
        payment_method = PaymentMethod.objects.filter(loan=loan, payment_method_code=319322).first()
        due_payment = Payment.objects.by_loan(loan).filter(
            payment_status__lte=327, payment_status__gte=320, due_amount__gte=1).order_by('due_date')
        bank_code = PaymentMethodLookup.objects.filter(name=loan.julo_bank_name).first().code

        if due_payment:
            not_payed_start = due_payment.first().due_date
            not_payed_end = due_payment.last().due_date
            principal_sum = due_payment.aggregate(Sum('installment_principal'))[
                'installment_principal__sum']
            late_fee_applied_sum = due_payment.aggregate(Sum('late_fee_amount'))[
                'late_fee_amount__sum']
            installment_interest = due_payment.aggregate(Sum('installment_interest'))[
                'installment_interest__sum']
            paid_sum = due_payment.aggregate(Sum('paid_amount'))['paid_amount__sum']
            change_due_date_interest = due_payment.aggregate(Sum('change_due_date_interest'))['change_due_date_interest__sum']
            # due_sum = principal_sum + late_fee_applied_sum + installment_interest
            while paid_sum > 0:
                if principal_sum > 0:
                    if paid_sum > principal_sum:
                        paid_sum -= principal_sum
                        principal_sum = 0
                    else:
                        principal_sum -= paid_sum
                        paid_sum = 0
                elif installment_interest > 0:
                    if paid_sum > installment_interest:
                        paid_sum -= installment_interest
                        installment_interest = 0
                    else:
                        installment_interest -= paid_sum
                        paid_sum = 0
                elif late_fee_applied_sum > 0:
                    if paid_sum > late_fee_applied_sum:
                        paid_sum -= late_fee_applied_sum
                        late_fee_applied_sum = 0
                    else:
                        late_fee_applied_sum -= paid_sum
                        paid_sum = 0
                elif change_due_date_interest > 0:
                    if paid_sum > change_due_date_interest:
                        paid_sum -= change_due_date_interest
                        change_due_date_interest = 0
                    else:
                        change_due_date_interest -= paid_sum
                        paid_sum = 0
            total_sum = principal_sum + late_fee_applied_sum + installment_interest + change_due_date_interest
        else:
            not_payed_start = ""
            not_payed_end = ""
            principal_sum = ""
            late_fee_applied_sum = ""
            installment_interest = ""
            total_sum = ""
        # last_date = datetime.strptime(last_date, "%d/%m/%Y")
        # last_date_plus_7 = last_date + relativedelta(days=7)
        last_date = ''
        last_date_plus_7 = ''
        context = {
            "url": url,
            "name": application.fullname_with_title,
            "loan_amount": loan.loan_amount,
            "loan_duration": loan.loan_duration,
            "application_xid": application.application_xid,
            "late_fee_amount": loan.late_fee_amount,
            "accepted_date": loan.sphp_accepted_ts.date(),
            "fullname": application.fullname_with_title,
            "name_only": application.fullname,
            "phone": customer.phone,
            "now": timezone.now().date(),
            "sphp_accepted_ts": loan.sphp_accepted_ts.date(),
            "not_payed_start": date.strftime(not_payed_start, '%d %B %Y'),
            "not_payed_end": date.strftime(not_payed_end, '%d %B %Y'),
            "due_amount_sum": principal_sum,
            "installment_interest": installment_interest,
            "late_fee_applied_sum": late_fee_applied_sum,
            "total_sum": format_number(total_sum, locale='id_ID'),
            "julo_bank_account_number": loan.julo_bank_account_number,
            "julo_bank_name": loan.julo_bank_name,
            "header_image": settings.EMAIL_STATIC_FILE_PATH + "header.png",
            "footer_image": settings.EMAIL_STATIC_FILE_PATH + "footer.png",
            "sign_image": settings.EMAIL_STATIC_FILE_PATH + "sign.png",
            # 'last_date': date.strftime(last_date, '%d %B %Y'),
            # 'last_date_plus_7': date.strftime(last_date_plus_7, '%d %B %Y'),
            'last_date': '',
            'last_date_plus_7': '',
            'bank_code': bank_code


        }

        if(payment_method):
            context['payment_method_name'] = payment_method.payment_method_name
            context['virtual_account'] = payment_method.virtual_account
        else:
            context['payment_method_name'] = ""
            context['virtual_account'] = ""
        text_message = render_to_string(self.template['email'], context=context)
        subject = self.template['subject'] +" - " + customer.email
        email_client = get_julo_email_client()
        email_from = "legal.dept@julo.co.id"
        name_from = "JULO"
        reply_to = "legal.dept@julo.co.id"
        status, body, headers = email_client.send_email(
            subject=subject,
            content=text_message,
            email_to=customer.email,
            email_from=email_from,
            email_cc=None,
            name_from=name_from,
            reply_to=reply_to
        )
        email = EmailHistory.objects.create(
            application=application,
            customer=application.customer,
            sg_message_id=headers['X-Message-Id'],
            to_email=customer.email,
            subject=subject,
            message_content=text_message,
            template_code=self.template['email'],
        )
        self.log_url(customer, url, "email")

    def send_agreement(self, loan_id, last_date):
        loan = Loan.objects.get_or_none(pk=loan_id)
        if not loan:
            print('Loan not found {}'.format(loan_id))
            return
        customer = Customer.objects.get_or_none(pk=loan.customer_id)
        if not customer:
            print('customer not found for loan {}'.format(loan_id))
            return
        customer_id = str(loan.customer_id)
        self.url = WarningUrl.objects.filter(
            url_type=self.type, customer=customer, warning_method=self.warning_type).first()
        encoded_customer_id = self.encrypt.encode_string(customer_id)
        url = self.template['url'].format(customer_id=encoded_customer_id)
        # last_date_new = datetime.strptime(last_date, "%d/%m/%Y")
        # last_date_new = date.strftime(last_date_new, '%Y-%m-%d')
        last_date_new = ''
        url = url + "?date=" + str(timezone.now().date()) + "&ldate=" + last_date_new + "&type=" + self.warning_type
        if self.type == "sms":
            shorten_url = self.shorten.short(url)
            shorten_url_string = shorten_url['url']
        else:
            shorten_url_string = url
        if self.type == "email":
            logger.info('sending email ' + customer_id)
            try:
                self.send_email(customer, loan, shorten_url_string, last_date)
                logger.info('email sent '+ customer_id)
            except:
                logger.error("could not send email for "  + customer_id)
        elif self.type == "sms":
            logger.info("sending sms " + customer_id)
            try:
                self.send_sms(customer, shorten_url_string)
                logger.info('sms sent ' + customer_id)
            except:
                logger.error("could not send sms "  + customer_id)
        return True

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')
        parser.add_argument('-t', '--type', type=str, help='Define email or sms')
        parser.add_argument('-w', '--warning', type=str, help='define warning type')

    def phone_validation(self,value):
        phone_regex = re.compile('^08[0-9]{07,10}$')
        return re.match(phone_regex, value)