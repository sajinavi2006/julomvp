import base64
import csv
import logging
import os
import sys

from django.core.management.base import BaseCommand

from django.conf import settings

from juloserver.julo.banks import BankCodes
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.clients import get_julo_sms_client
from juloserver.julo.exceptions import EmailNotSent, SmsNotSent
from juloserver.julo.models import Loan
from juloserver.julo.models import PaymentMethod
from juloserver.julo.models import VirtualAccountSuffix
from juloserver.julo.models import SmsHistory
from juloserver.julo.payment_methods import PaymentMethodCodes, PaymentMethodManager
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import format_e164_indo_phone_number
from django.utils import timezone

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


def send_email_notification(application):
    email_client = get_julo_email_client()
    try:
        status, headers, subject, msg = email_client.email_va_notification(application)
    except EmailNotSent:
        return False

    if status == 202:
        to_email = application.email
        message_id = headers['X-Message-Id']

        logger.info({
            'status': status,
            'message_id': message_id,
            'to_email': to_email
        })
        return True
    else:
        return False


def send_pn_notification(application):
    customer = application.customer
    pn_client = get_julo_pn_client()
    try:
        send_pn = pn_client.inform_va_notification(customer)
    except Exception:
        return False

    return True

def send_sms_notification(application):
    sms_client = get_julo_sms_client()
    try:
        txt_msg, response  = sms_client.sms_va_notification(application)
    except SmsNotSent:
        return False

    if response['status'] != '0':
        return False
    else:
        sms = SmsHistory.objects.create(
            customer=application.customer,
            message_id=response['message-id'],
            message_content=txt_msg,
            to_mobile_phone=format_e164_indo_phone_number(response['to']),
            phone_number_type='mobile_phone_1'
        )

        logger.info({
            'status': 'sms_created',
            'sms_history_id': sms.id,
            'message_id': sms.message_id
        })
        return True


class Command(BaseCommand):
    help = 'retroload VA BCA Online for existing loan with status < 250'

    def handle(self, *args, **options):
        
        loans = Loan.objects.filter(loan_status__status_code__lt=LoanStatusCodes.PAID_OFF,
                                    application__bank_name__contains='BCA').exclude(
                                    paymentmethod__payment_method_code=PaymentMethodCodes.BCA)

        success_loans = []
        success_loan_count = 0

        self.stdout.write(self.style.SUCCESS(
            '=== retroload va bca online begin {} - {} ==='.format(
                len(loans), loans.values('id'))))

        fields = ["loan_id", "application_id", "bca_offline", "bca_online", "email", "sms", "pn"]
        reports = []

        for loan in loans:
            data = {}
            data["loan_id"] = loan.id
            data["application_id"] = loan.application.id

            payment_method_bca_offline = loan.paymentmethod_set.filter(
                payment_method_code=BankCodes.BCA).last()
            has_payment_method_bca_faspay = loan.paymentmethod_set.filter(
                payment_method_code=PaymentMethodCodes.BCA).exists()

            if payment_method_bca_offline:
                data["bca_offline"] = payment_method_bca_offline.virtual_account
                self.stdout.write(self.style.SUCCESS(
                    '=== set is_shown False VA BCA Offline for loan: {}==='.format(loan.id)))
                payment_method_bca_offline.is_shown = False
                payment_method_bca_offline.save()
            else:
                data["bca_offline"] = "No VA BCA Offline"


            if not has_payment_method_bca_faspay:
                self.stdout.write(self.style.SUCCESS(
                    '=== create VA BCA Online for loan: {}==='.format(loan.id)))
                va_suffix = VirtualAccountSuffix.objects.filter(loan__id=loan.id).first()
                if va_suffix:
                    bca_online = PaymentMethodManager.get_or_none(BankCodes.BCA)
                    virtual_account = "".join([
                        bca_online.faspay_payment_code,
                        va_suffix.virtual_account_suffix
                    ])
                    payment_method_data = {
                        'payment_method_code': bca_online.faspay_payment_code,
                        'payment_method_name': bca_online.name,
                        'bank_code': bca_online.code,
                        'loan': loan,
                        'is_shown': True,
                        'virtual_account': virtual_account
                    }
                    payment_method_bca_online = PaymentMethod(**payment_method_data)
                    payment_method_bca_online.save()

                    loan.julo_bank_name = payment_method_bca_online.payment_method_name
                    loan.julo_bank_account_number = virtual_account
                    loan.save()

                    success_loans.append(loan.id)
                    success_loan_count += 1

                    data["bca_online"] = virtual_account
                    application_status = loan.application.application_status.status_code
                    
                    if application_status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                        send_email_notif = send_email_notification(loan.application)
                        if send_email_notif:
                            data["email"] = "Sent"
                            self.stdout.write(self.style.SUCCESS(
                                'success send email notification email {}'.format(
                                    loan.application.email)))
                        else:
                            data["email"] = "Not Sent"
                            self.stdout.write(self.style.ERROR(
                                'Failed send email notification to email {} loan {}'.format(
                                    loan.application.email, loan.id)))

                        send_sms_notif = send_sms_notification(loan.application)
                        if send_sms_notif:
                            data["sms"] = "Sent"
                            self.stdout.write(self.style.SUCCESS(
                                'success send sms notification {}'.format(
                                    loan.application.mobile_phone_1)))
                        else:
                            data["sms"] = "Not Sent"
                            self.stdout.write(self.style.ERROR(
                                'Failed send sms notification to number {} loan {}'.format(
                                    loan.application.mobile_phone_1, loan.id)))

                        send_pn_notif = send_pn_notification(loan.application)
                        if send_pn_notif:
                            data["pn"] = "Sent"
                            self.stdout.write(self.style.SUCCESS(
                                'success send pn notification to customer {}'.format(
                                    loan.application.customer.id)))
                        else:
                            data["pn"] = "Not Sent"
                            self.stdout.write(self.style.ERROR(
                                'Failed send pn notification to customer {} loan {}'.format(
                                    loan.customer.id, loan.id)))
                    else:
                        data["email"] = "Skipped: application status {}".format(application_status)
                        data["sms"] = "Skipped: application status {}".format(application_status)
                        data["pn"] = "Skipped: application status {}".format(application_status)
                        self.stdout.write(self.style.WARNING(
                            'Skip Notif Blast loan {} - application status {}'.format(
                                loan.id, application_status)))

                    self.stdout.write(self.style.SUCCESS(
                    'success load VA BCA Online as payment method {} to Loan {}'.format(
                        payment_method_bca_online.id, loan.id)))

            elif has_payment_method_bca_faspay:
                data["bca_online"] = "Already has VA BCA Online"
                data["email"] = "Skipped"
                data["sms"] = "Skipped"
                data["pn"] = "Skipped"
                self.stdout.write(self.style.WARNING(
                    'loan {} already has VA BCA Online'.format(loan.id)))

            reports.append(data)

        self.stdout.write(self.style.SUCCESS(
            'Successfully retroload va bca online for {} - {}'.format(
                success_loan_count, success_loans)))

        filename = 'report_retroload_va_bca_online.csv'
        with open(filename, 'wb') as csvfile:
            w = csv.DictWriter(csvfile, fields)
            w.writeheader()
            w.writerows(reports)

        with open(filename, 'rb') as rf:
            result_string = rf.read()

        b64content = base64.b64encode(result_string)
        attachment = {
            'content': b64content.encode('utf-8'),
            'filename': filename,
            'type': 'csv'
        }
        now = timezone.now()
        list_email_to = ['yogi@julo.co.id', 'febby@julofinance.com', 'rayhan@julofinance.com',
                         'coki@julo.co.id']
        email_client = get_julo_email_client()
        email_to = (',').join(list_email_to)
        subject = 'Retroload VA BCA Online Report %s' % (settings.ENVIRONMENT)
        message = 'Retroload VA BCA Online Report on %s - %s' % (settings.ENVIRONMENT, now)

        status = None
        try:
            status, body, headers = email_client.send_email(subject,
                                                            message,
                                                            email_to,
                                                            attachment_dict=attachment)
        except EmailNotSent as e:
            self.stdout.write(self.style.WARNING(e))

        if status == 202:
            os.remove(filename)
            self.stdout.write(self.style.SUCCESS(
                'Successfully send report to %s' % (email_to)))
        else:
            self.stdout.write(self.style.WARNING(
                'Send email report response status %s') % (status))