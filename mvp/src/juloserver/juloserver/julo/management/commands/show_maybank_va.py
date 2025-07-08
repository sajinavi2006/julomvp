from builtins import str
import logging, sys
from datetime import date
from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone
from juloserver.api_token.models import ExpiryToken as Token
from dateutil.relativedelta import relativedelta
from juloserver.julo.banks import BankCodes
from juloserver.julo.models import Payment, PaymentMethod
from juloserver.julo.payment_methods import PaymentMethodManager, PaymentMethodCodes
from juloserver.julo.product_lines import ProductLineCodes
from ...clients import get_julo_email_client

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'show va maybank due to permata maintenance'
    def handle(self, *args, **options):
        product_line_all = ProductLineCodes.stl() + ProductLineCodes.mtl()
        tplus1 = date(2019, 2, 8)
        tplus5 = date(2019, 2, 13)
        payments = Payment.objects.not_paid_active().filter(
                loan__loan_status__status_code__range=(220, 237),
                due_date__range=(tplus1, tplus5),
                loan__application__product_line__product_line_code__in=product_line_all)\
            .exclude(loan__application__bank_name__icontains='bca').order_by('loan')\
            .distinct('loan')

        self.stdout.write(self.style.SUCCESS('Begin %s loans' % (payments.count())))
        for payment in payments:
            payment_method_maybank = payment.loan.paymentmethod_set.filter(
                payment_method_code=PaymentMethodCodes.MAYBANK).last()
            if not payment_method_maybank:
                payment_method = PaymentMethodManager.get_or_none(BankCodes.MAYBANK)
                va_suffix = payment.loan.virtualaccountsuffix_set.all().last()
                virtual_account = "".join([
                    payment_method.faspay_payment_code,
                    va_suffix.virtual_account_suffix
                ])
                PaymentMethod.objects.create(
                    payment_method_code=payment_method.faspay_payment_code,
                    payment_method_name=payment_method.name,
                    bank_code=BankCodes.MAYBANK,
                    loan=payment.loan,
                    is_shown=True,
                    virtual_account=virtual_account
                )
            else:
                payment_method_maybank.is_shown = True
                payment_method_maybank.save()

            # self.send_email(payment)

        self.stdout.write(self.style.SUCCESS('Successfully show va maybank'))

    def send_email(self, payment):
        email = get_julo_email_client()
        context = {
            'maybank_indo_alfa': settings.EMAIL_STATIC_FILE_PATH + 'maybank_indo_alfa.png'
        }
        text_message = render_to_string("email_permata_announcement.html", context)

        try:
            email_to = payment.loan.application.email
            subject = 'JULO - Bank Permata Maintenance 08-09 Februari 2019 '
            email_from = "collections@julo.co.id"
            name_from = "JULO"
            reply_to = "cs@julo.co.id"
            status, body, headers = email.send_email(
                subject,
                text_message,
                email_to,
                email_from=email_from,
                email_cc=None,
                name_from=name_from,
                reply_to=reply_to)
            self.stdout.write(self.style.SUCCESS('Email Sent Success %s' % (payment.id)))
        except Exception as e :
            self.stdout.write(self.style.ERROR('Sent Email Error %s - %s' % (str(e), payment.id)))
