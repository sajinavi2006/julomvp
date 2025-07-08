import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.julo.clients import get_julo_email_client
from django.template.loader import render_to_string
from juloserver.julo.models import Payment
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from datetime import date
from django.utils import timezone
from juloserver.julo.models import EmailHistory
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):

    def handle(self, **options):
        today = timezone.localtime(timezone.now()).date()
        if today == date(2019, 5, 17) or today == date(2019, 5, 23):
            payments = Payment.objects.select_related('loan') \
                .filter(loan__loan_status_id=LoanStatusCodes.CURRENT) \
                .filter(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME) \
                .filter(due_date__range=["2019-05-25", "2019-05-28"]) \
                .filter(loan__application__product_line__product_line_code__in=ProductLineCodes.mtl()) \
                .distinct('loan') \
                .order_by('loan', 'due_date')
            self.send_lebaran_email(payments, 1)
        if today == date(2019, 5, 17) or today == date(2019, 5, 23):
            payments = Payment.objects.select_related('loan') \
                .filter(loan__loan_status_id=LoanStatusCodes.CURRENT) \
                .filter(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME) \
                .filter(due_date__range=["2019-05-29", "2019-06-10"]) \
                .filter(loan__application__product_line__product_line_code__in=ProductLineCodes.mtl()) \
                .distinct('loan') \
                .order_by('loan', 'due_date')
            self.send_lebaran_email(payments, 2)
        if today == date(2019, 5, 24) or today == date(2019, 5, 31):
            payments = Payment.objects.select_related('loan') \
                .filter(loan__loan_status_id=LoanStatusCodes.CURRENT) \
                .filter(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME) \
                .filter(due_date__range=["2019-06-15", "2019-06-24"]) \
                .filter(loan__application__product_line__product_line_code__in=ProductLineCodes.mtl()) \
                .distinct('loan') \
                .order_by('loan', 'due_date')
            self.send_lebaran_email(payments, 3)

    def send_lebaran_email(self, payments, category):
        for payment in payments:
            if payment.loan.customer is None:
                logger.error("Customer not Found " + payment.loan.application_id)
                continue
            else:
                email_client = get_julo_email_client()
                application = payment.loan.application
                if category == 1:
                    template_name = '201905_promo_lebaran/20190517_May Email Lebaran Promo_1'
                    subject = 'JULO Give Back! Dapatkan maks 6x Cashback dengan Membayar Minimal 2x Cicilan!'
                elif category == 2:
                    template_name = '201905_promo_lebaran/20190517_May Email Lebaran Promo_2'
                    subject = 'JULO Give Back! Dapatkan maks 6x Cashback dengan Membayar Lebih Awal!'
                else:
                    template_name = '201905_promo_lebaran/20190517_May Email Lebaran Promo_3'
                    subject = 'JULO Give Back! Dapatkan maks 6x Cashback dengan Membayar Lebih Awal!'
                due_date = date.strftime(payment.due_date, '%d %B %Y')
                context = {
                    'due_date': due_date,
                    'fullname': application.fullname_with_title,
                }
                message = render_to_string(template_name + '.html', context)
                customer = payment.loan.customer
                try:
                    status, body, headers = email_client.send_email(
                        subject=subject,
                        content=message,
                        email_to=application.email
                    )
                    message_id = headers['X-Message-Id']
                    email = EmailHistory.objects.create(
                        application=application,
                        customer=application.customer,
                        payment=payment,
                        sg_message_id=message_id,
                        to_email=application.email,
                        subject=subject,
                        message_content=message,
                        template_code=template_name,
                    )
                except Exception as e:
                    logger.error({
                        'action': 'promo_lebaran',
                        'loan id': payment.loan.id,
                        'errors': 'failed send email to {}'.format(customer, e)
                    })
                    continue