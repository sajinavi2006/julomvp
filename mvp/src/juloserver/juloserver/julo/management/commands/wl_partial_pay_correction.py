from __future__ import print_function
from builtins import str
import logging
import sys
import csv

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.db.models import Q
from datetime import date
from django.utils import timezone
from ...models import PaymentMethod
from ...models import Payment
from ...models import Sum
from ...models import WlLevelConfig
from ...models import EmailHistory, Application
from ...models import WarningLetterHistory
from ...clients import get_julo_email_client
from ...product_lines import ProductLineCodes
from ...statuses import PaymentStatusCodes, LoanStatusCodes
from ...payment_methods import PaymentMethodCodes
from dateutil.relativedelta import relativedelta
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        try:
            with open(path, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                try:
                    application = Application.objects.get_or_none(pk=row['application_id'])
                    if not application:
                        print('Application not found {}'.format(row['application_id']))
                        continue
                    self.run_send_warning_letters(application)
                except Exception as e:
                    pass
        except IOError:
            logger.error("could not open given file " + path)
            return



    def run_send_warning_letters(self, application):
        today = timezone.localtime(timezone.now()).date()
        payments_to_exclude = (ProductLineCodes.PEDEMTL1, ProductLineCodes.PEDEMTL2,
                               ProductLineCodes.PEDESTL1, ProductLineCodes.PEDESTL2,
                               ProductLineCodes.LAKU1, ProductLineCodes.LAKU2,
                               ProductLineCodes.ICARE1, ProductLineCodes.ICARE2)
        payments = Payment.objects.normal().select_related('loan') \
            .exclude(loan__application__product_line__product_line_code__in=payments_to_exclude) \
            .filter(loan__loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
                    loan__loan_status_id__gte=LoanStatusCodes.LOAN_1DPD) \
            .filter(loan__application__id=application.id) \
            .distinct('loan') \
            .order_by('loan')
        wl_config = WlLevelConfig.objects.all()
        configMap = {}
        index = 1
        for wl_configs in wl_config:
            configMap[index] = wl_configs.wl_level
            index = index + 1

        for payment in payments:
            loan_id = payment.loan.id
            due_date = payment.due_date
            if payment.loan.customer is None:
                logger.error("Customer not Found " + payment.loan.application_id)
                continue
            customer = payment.loan.customer
            due_payments = Payment.objects.filter(payment_status_id__lte=PaymentStatusCodes.PAYMENT_180DPD,
                                                  payment_status_id__gte=PaymentStatusCodes.PAYMENT_1DPD) \
                .filter(Q(ptp_date=None) | Q(ptp_date__lt=today)) \
                .filter(loan_id=loan_id) \
                .order_by('payment_number')
            late_payment_count = len(due_payments)
            if late_payment_count > 0:
                wl_level = configMap[late_payment_count]
                try:
                    self.email_warning_letters(payment, due_payments, wl_level)
                except Exception as e:
                    logger.error({
                        'action': 'run_send_warning_letters',
                        'loan id': loan_id,
                        'errors': 'failed send email to {} - {}'.format(customer, e)
                    })
                    continue

    def email_warning_letters(self, loan, due_payment, warning_type):
        loan = loan.loan
        payment_method = PaymentMethod.objects.filter(loan_id=loan.id,
                                                       payment_method_code=PaymentMethodCodes.INDOMARET)
        if payment_method:
            virtual_account = payment_method.first().virtual_account
        else:
            virtual_account = None
        application = loan.application
        customer = loan.customer
        late_fee_total = due_payment.aggregate(Sum('late_fee_amount'))[
            'late_fee_amount__sum']
        due_amount_total = due_payment.aggregate(Sum('due_amount'))[
                               'due_amount__sum']
        net_amount_to_pay = late_fee_total + due_amount_total
        sph_date = loan.sphp_accepted_ts
        if sph_date is None:
            sph_date = ""
        else:
            sph_date = loan.sphp_accepted_ts.date()
        if due_payment:
            not_payed_start = due_payment.first().due_date
            not_payed_end = due_payment.last().due_date
        else:
            not_payed_start = ""
            not_payed_end = ""

        context = {
            "name": application.fullname_with_title,
            "loan_amount": loan.loan_amount,
            "loan_duration": loan.loan_duration,
            "application_xid": application.application_xid,
            "late_fee_total": late_fee_total,
            "due_amount_total":due_amount_total,
            "net_amount_to_pay":net_amount_to_pay,
            "accepted_date": sph_date,
            "fullname": application.fullname_with_title,
            "name_only": application.fullname,
            "now": timezone.now().date(),
            "sphp_accepted_ts": sph_date,
            "julo_bank_account_number": loan.julo_bank_account_number,
            "julo_bank_name": loan.julo_bank_name,
            "header_image": settings.EMAIL_STATIC_FILE_PATH + "wl_header.png",
            "footer_image": settings.EMAIL_STATIC_FILE_PATH + "footer.png",
            "sign_image": settings.EMAIL_STATIC_FILE_PATH + "sign.png",
            "wa_image": settings.EMAIL_STATIC_FILE_PATH + "wl_whatsapp.png",
            "email_image": settings.EMAIL_STATIC_FILE_PATH + "wl_email.png",
            "lihat_image": settings.EMAIL_STATIC_FILE_PATH + "wl_lihat.png",
            'due_payment':due_payment,
            "not_payed_start": date.strftime(not_payed_start, '%d %B %Y'),
            "not_payed_end": date.strftime(not_payed_end, '%d %B %Y'),
            "virtual_account": virtual_account,
            "play_store": settings.EMAIL_STATIC_FILE_PATH + "google-play-badge.png"

        }
        if warning_type == 1:
            subject = 'Surat Peringatan Pertama'
            wl_type = 'pertama'
        elif warning_type == 2:
            subject = 'Surat Peringatan Kedua'
            wl_type = 'kedua'
        else:
            subject = 'Surat Peringatan Ketiga'
            wl_type = 'ketiga'

        context_correction = {
            "name": application.fullname_with_title,
            "wl_type": wl_type
        }

        template_correction_name = 'wl_partial_pay_correction.html'
        text_message_correction = render_to_string(template_correction_name, context=context_correction)
        template_name = 'warning_letter'+str(warning_type)+'.html'
        text_message = render_to_string(template_name, context=context)
        subject = subject +" - " + customer.email
        email_client = get_julo_email_client()
        email_from = "departemen.hukum@julo.co.id"
        name_from = "JULO"
        reply_to = "departemen.hukum@julo.co.id"
        status, body, headers = email_client.send_email(
            subject=subject,
            content=text_message_correction + text_message,
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
            message_content=text_message_correction + text_message,
            template_code=template_name
        )
        warning_letter_history = WarningLetterHistory.objects.create(
            warning_number=warning_type,
            customer=customer,
            loan=due_payment.last().loan,
            due_date=due_payment.last().due_date,
            payment=due_payment.last(),
            loan_status_code=due_payment.last().loan.status,
            payment_status_code=due_payment.last().status,
            total_due_amount=due_amount_total,
            event_type='WL' + str(warning_type)
        )
