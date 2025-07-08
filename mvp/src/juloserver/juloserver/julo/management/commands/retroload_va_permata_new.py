from __future__ import print_function
from django.core.management.base import BaseCommand

from juloserver.julo.banks import BankCodes
from juloserver.julo.models import Loan, VirtualAccountSuffix, PaymentMethod, EmailHistory, SmsHistory
from juloserver.julo.payment_methods import PaymentMethodCodes, PaymentMethodManager
from juloserver.julo.statuses import LoanStatusCodes
from ...clients import get_julo_sms_client,get_julo_email_client
from django.template.loader import render_to_string
from ...utils import format_e164_indo_phone_number

class Command(BaseCommand):
    help = 'retroactively va permata for exist loan'

    def handle(self, *args, **options):
        loans = Loan.objects.filter(loan_status__status_code__lt=LoanStatusCodes.PAID_OFF,
                                    loan_status__status_code__gt=LoanStatusCodes.INACTIVE)
        for loan in loans:
            payment_methods = loan.paymentmethod_set.filter(
                payment_method_code__in=[PaymentMethodCodes.PERMATA, PaymentMethodCodes.BRI],
                  is_shown=True).order_by('-is_primary').first()
            if payment_methods:
                va_suffix = VirtualAccountSuffix.objects.filter(loan__id=loan.id).first()
                if va_suffix:
                    permata = PaymentMethodManager.get_or_none(BankCodes.PERMATA)
                    virtual_account = permata.faspay_payment_code + va_suffix.virtual_account_suffix
                    is_primary = payment_methods.is_primary
                    payment_method_data = {
                        'payment_method_code': permata.faspay_payment_code,
                        'payment_method_name': permata.name,
                        'bank_code': BankCodes.PERMATA,
                        'loan': loan,
                        'is_shown': True,
                        'is_primary': is_primary,
                        'virtual_account': virtual_account,
                        'customer_id': payment_methods.customer.id if payment_methods.customer else None
                    }
                    payment_method_permata = PaymentMethod(**payment_method_data)
                    payment_method_permata.save()
                    PaymentMethod.objects.filter(loan=loan,
                                                 payment_method_code__in=[PaymentMethodCodes.PERMATA, PaymentMethodCodes.BRI])\
                                                .update(is_primary=False,is_shown=False)
                    if "BCA" not in loan.application.bank_name:
                        loan.julo_bank_name = permata.name
                        loan.julo_bank_account_number = virtual_account
                        loan.save()
                    self.send_notification(payment_methods, virtual_account)
                    self.send_email(payment_methods, virtual_account)
                    self.stdout.write(self.style.SUCCESS(
                        'success load VA PERMATA as payment method {} to Loan {}'.format(
                        payment_method_permata.id, loan.id)))

        self.stdout.write(self.style.SUCCESS('Assign VA Done'))

    def send_notification(self, payment, virtual_account):
        if not payment.loan.application.mobile_phone_1:
            print(("Invalid phone number", payment.loan.id))
            return
        client = get_julo_sms_client()
        context = {'number': virtual_account,
                   'first_name': payment.loan.application.fullname.split()[0]}
        phone_number = format_e164_indo_phone_number(payment.loan.application.mobile_phone_1)
        message = render_to_string("permata_new_va.txt", context=context)
        try:
            text_message, response = client.send_sms(phone_number, message)
            response = response['messages'][0]
            if response['status'] == '0':
                sms = SmsHistory.objects.create(
                    customer=payment.loan.application.customer if payment.loan.application.customer else None,
                    message_id=response['message-id'],
                    message_content=message,
                    application=payment.loan.application,
                    template_code='permata_new_va',
                    to_mobile_phone=phone_number,
                    phone_number_type='mobile_phone_1'
                )
                print(("SMS has been sent", payment.loan.id))
        except Exception as e:
            print((e, payment.loan.id))
            pass

    def send_email(self, payment, virtual_account):
        if not payment.loan.customer.email:
            print(("Invalid email", payment.loan.id))
            return
        julo_email_client = get_julo_email_client()
        context = {
            "number": virtual_account,
            "first_name": payment.loan.application.fullname.split()[0]
        }
        text_message = render_to_string("email_permata_new_va_notification.html", context=context)
        try :
            status, headers, subject, msg =julo_email_client.notification_permata_new_va_email(payment.loan.customer.email, text_message)
            template_code = "notification_permata_new_va_email"
            EmailHistory.objects.create(
                customer=payment.loan.customer,
                sg_message_id=headers["X-Message-Id"],
                to_email=payment.loan.customer.email,
                subject=subject,
                application=payment.loan.application,
                message_content=msg,
                template_code=template_code,
            )
            print(("Email has been sent", payment.loan.id))
        except Exception as e :
            print((e, payment.loan.id))
