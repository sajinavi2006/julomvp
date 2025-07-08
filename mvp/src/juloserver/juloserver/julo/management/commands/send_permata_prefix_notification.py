from __future__ import print_function
import logging, sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone
from juloserver.api_token.models import ExpiryToken as Token
from juloserver.julo.statuses import PaymentStatusCodes
from dateutil.relativedelta import relativedelta
from juloserver.julo.models import Customer, Loan, Payment, PaymentMethod,Application
from ...clients import get_julo_sms_client,get_julo_email_client, get_julo_pn_client
from juloserver.julo.utils import have_pn_device

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))



class Command(BaseCommand):
    help = 'retroactively payment method suffix'
    payment_method_code = '877332'
    def handle(self, *args, **options):
        payment_method = PaymentMethod.objects.filter(loan__loan_status__status_code__range=(220, 237))
        for payment in payment_method:
            payment.payment_method_code = settings.FASPAY_PREFIX_PERMATA
            va = payment.virtual_account[6:]
            self.va = va
            payment.virtual_account =  settings.FASPAY_PREFIX_PERMATA + va
            payment.save(update_fields=['payment_method_code',
                                        'virtual_account',
                                        'udate'])
            self.send_notification(payment)
            Token.objects.filter(user=payment.loan.customer.user).delete()



        self.stdout.write(self.style.SUCCESS('Successfully payment method suffix'))

    def send_notification_task(self, due_in_days):
        codes = PaymentStatusCodes.paid_status_codes()
        today = timezone.localtime(timezone.now()).date()
        for day in due_in_days:
            days = today + relativedelta(days=day)

            for payment in Payment.objects.filter(due_date=days).exclude(payment_status__in=codes):
                payment_method = PaymentMethod.objects \
                     .filter(loan=payment.loan,payment_method_code=settings.FASPAY_PREFIX_PERMATA).first()
                if payment_method:
                    self.send_notification(payment_method)
                    logger.info({
                        'action': 'setting ptp_date to None',
                        'payment_id': payment.id,
                        'ptp_date': payment.ptp_date,
                    })

    def send_email(self, payment):
        va_suffix = payment.virtual_account[6:]
        email = get_julo_email_client()
        context = {
            "old_va": '{}-{}'.format(self.payment_method_code, va_suffix),
            "new_va": '{}-{}'.format(settings.FASPAY_PREFIX_PERMATA, va_suffix),
            "now": timezone.now(),
            'udate': payment.udate,
            "header_image": settings.EMAIL_STATIC_FILE_PATH + "header-notification.jpg",
            "footer_image": settings.EMAIL_STATIC_FILE_PATH + "footer.png",
            "alfamart": settings.EMAIL_STATIC_FILE_PATH + "alfamart.png",
            "bca": settings.EMAIL_STATIC_FILE_PATH + "bca.png",
            "indomart": settings.EMAIL_STATIC_FILE_PATH + "indomart.png",
            "header_notification": settings.EMAIL_STATIC_FILE_PATH + "header-notification.jpg",
        }

        text_message = render_to_string("email-notification.html", context=context)

        try:
            email.notification_permata_prefix_email(payment.loan.customer.email, text_message)
            print(("Email has been sent", payment.loan.id))
        except Exception as e :
            print((e, payment.loan.id))

    def send_notification(self,payment):
        sms = get_julo_sms_client()
        context = {}
        text_message = render_to_string("permata_prefix_change.txt", context=context)

        try:
            sms.prefix_change_notification(payment.loan.customer.phone, text_message)
            print(("SMS has been sent", payment.loan.id))
        except Exception as e :
            print((e, payment.loan.id))

        application = Application.objects.filter(customer=payment.loan.customer).first()
        text = "Perubahan nomor Virtual Account PERMATA, Cek info selengkap nya di EMAIL"
        if have_pn_device(application.device):
            try:
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.early_payment_promo(application.device.gcm_reg_id, text)
                print(("PN has been sent", payment.loan.id))
            except Exception as e :
                print((e, payment.loan.id))

        self.send_email(payment)
