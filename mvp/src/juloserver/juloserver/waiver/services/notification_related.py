from builtins import str
from builtins import range
from builtins import object

import logging

from django.utils import timezone
from django.db.models import Sum

from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.models import PaymentMethod, EmailHistory

from juloserver.loan_refinancing.services.notification_related import check_template_bucket_5
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from datetime import timedelta

from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.pii_vault.constants import PiiVaultDataType

logger = logging.getLogger(__name__)


class MultiplePaymentPTPEmail(object):
    def __init__(self, multiple_payment_ptp):
        self._multiple_payment_ptp = multiple_payment_ptp
        self._sequence = self._multiple_payment_ptp.sequence
        self._waiver_request = multiple_payment_ptp.waiver_request
        self._account = self._waiver_request.account
        self._is_for_j1 = True if self._account else False
        self._email_client = get_julo_email_client()
        self._loan = self._waiver_request.loan
        self._account_payment = None
        self._payment = None
        if self._is_for_j1:
            self._application = self._account.last_application
            self._account_payment = self._account.get_oldest_unpaid_account_payment()
        else:
            self._application = self._loan.application
            self._payment = self._loan.get_oldest_unpaid_payment()
        self._customer = self._application.customer
        self._payment_method = PaymentMethod.objects.filter(
            customer=self._customer, is_primary=True).last()
        self._is_fully_paid = self._multiple_payment_ptp.is_fully_paid
        self._is_on_promised_date = None

    def send_multiple_payment_ptp_email_minus_reminder(self):
        self._is_on_promised_date = False
        if not self._validate_email_send():
            return

        template = 'multiple_payment_ptp/payment_date_multiple_ptp_reminder.html'
        template_code = 'payment_date_{}_multiple_ptp_1_day'.format(self._sequence)
        customer_info, payment_info, first_unpaid_payment, template_code = \
            self._construct_email_params(template_code)

        subject = 'Pembayaran {} untuk program keringanan'.format(payment_info['sequence_txt'])
        parameters = self._email_client.email_multiple_payment_ptp(
            customer_info, payment_info, subject, template)
        self._create_email_history(*(parameters + (template_code, first_unpaid_payment)))

    def send_multiple_payment_ptp_email_reminder(self):
        self._is_on_promised_date = True
        if not self._validate_email_send():
            return

        template = 'multiple_payment_ptp/payment_date_multiple_ptp_reminder.html'
        template_code = 'payment_date_{}_multiple_ptp_on_day'.format(self._sequence)
        customer_info, payment_info, first_unpaid_payment, template_code = \
            self._construct_email_params(template_code)

        subject = 'Pembayaran {} untuk program keringanan'.format(payment_info['sequence_txt'])
        parameters = self._email_client.email_multiple_payment_ptp(
            customer_info, payment_info, subject, template)
        self._create_email_history(*(parameters + (template_code, first_unpaid_payment)))

    def _construct_email_params(self, template_code):
        customer_info = {
            'customer': self._customer,
            'va_number': self._payment_method.virtual_account,
            'bank_code': self._payment_method.bank_code,
            'bank_name': self._payment_method.payment_method_name,
        }

        first_unpaid_payment = self._account_payment or self._payment
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', self._is_for_j1)

        payment_info = {
            'is_bucket_5': is_bucket_5,
            'is_on_promised_date': self._is_on_promised_date,
        }
        multiple_payment_ptp = self._waiver_request.ordered_multiple_payment_ptp().filter(
            sequence__lte=self._sequence)

        sequence_txt = "pertama"
        payment_info['total_remaining_amount'] = multiple_payment_ptp.aggregate(
            total=Sum('remaining_amount'))["total"] or 0
        if self._sequence == 2:
            sequence_txt = "kedua"
        elif self._sequence == 3:
            sequence_txt = "ketiga"

        payment_info.update(
            dict(
                multiple_payment_ptp=multiple_payment_ptp,
                sequence_txt=sequence_txt,
            )
        )

        return customer_info, payment_info, first_unpaid_payment, template_code

    def _create_email_history(self, status, headers, subject, msg, template, payment):
        email = collection_detokenize_sync_object_model(
            'customer', self._customer, self._customer.customer_xid, ['email']
        ).email
        if status == 202:
            email_history_param = dict(
                customer=self._customer,
                sg_message_id=headers["X-Message-Id"],
                to_email=email,
                subject=subject,
                application=self._application,
                message_content=msg,
                template_code=template,
            )
            if self._is_for_j1:
                email_history_param['account_payment'] = payment
            else:
                email_history_param['payment'] = payment

            EmailHistory.objects.create(**email_history_param)

            logger.info({
                "action": "email_notify_multiple_payment_ptp",
                "customer_id": self._customer.id,
                "template_code": template
            })
        else:
            logger.warn({
                'action': "email_notify_multiple_payment_ptp",
                'status': status,
                'message_id': headers['X-Message-Id']
            })

    def _validate_email_send(self):
        if not self._waiver_request.is_multiple_ptp_payment or self._is_fully_paid:
            return False

        if self._waiver_request.loan_refinancing_request:
            loan_refinancing_request = self._waiver_request.loan_refinancing_request
            if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.approved:
                return False

        templates = ['immediate_multiple_ptp_payment', 'immediate_multiple_ptp_payment_b5']
        for i in range(self._sequence - 1):
            templates.append('payment_date_%s_multiple_ptp_1_day' % str(i + 1))
            templates.append('payment_date_%s_multiple_ptp_1_day_b5' % str(i + 1))
            templates.append('payment_date_%s_multiple_ptp_on_day' % str(i + 1))
            templates.append('payment_date_%s_multiple_ptp_on_day_b5' % str(i + 1))

        if self._is_on_promised_date:
            templates.append('payment_date_%s_multiple_ptp_1_day' % str(self._sequence))
            templates.append('payment_date_%s_multiple_ptp_1_day_b5' % str(self._sequence))

        today = timezone.localtime(timezone.now())
        start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        return not EmailHistory.objects.filter(
            customer=self._customer,
            application=self._application,
            template_code__in=templates,
            account_payment=self._account_payment,
            payment=self._payment,
            cdate__gte=start_of_day,
            cdate__lt=end_of_day,
        ).exists()


class WaiverRequestExpiredEmail(object):
    def __init__(self, waiver_request):
        self._waiver_request = waiver_request
        self._is_for_j1 = waiver_request.is_j1
        self._email_client = get_julo_email_client()
        self._loan = self._waiver_request.loan
        self._account = self._waiver_request.account
        self._account_payments = None
        self._payments = None
        if self._is_for_j1:
            self._application = self._account.last_application
            self._account_payments = self._account.accountpayment_set.normal().order_by('due_date')
            self._first_unpaid_payment_or_account_payment = self._account_payments.first()
        else:
            self._application = self._loan.application
            self._payments = self._loan.payment_set.normal().order_by('payment_number')
            self._first_unpaid_payment_or_account_payment = self._payments.first()
        self._customer = self._application.customer
        self._payment_method = PaymentMethod.objects.filter(
            customer=self._customer, is_primary=True).last()

    def _construct_email_params(self):
        email = collection_detokenize_sync_object_model(
            'customer', self._customer, self._customer.customer_xid, ['email']
        ).email
        va = collection_detokenize_sync_object_model(
            'payment_method',
            self._payment_method,
            0,
            ['virtual_account'],
            PiiVaultDataType.KEY_VALUE,
        ).virtual_account
        customer_info = {
            'firstname_with_title': self._application.first_name_with_title,
            'va_number': va,
            'bank_code': self._payment_method.bank_code,
            'bank_name': self._payment_method.payment_method_name,
            'email': email,
        }
        data = self._account_payments
        if not self._is_for_j1:
            data = self._payments

        payments_or_account_payments_info = []
        for payment_or_account_payment in data:
            is_paid_label = 'Ya' if payment_or_account_payment.is_paid else 'Tidak'
            if self._is_for_j1:
                dpd = payment_or_account_payment.dpd
                installment_amount_without_late_fee = payment_or_account_payment.principal_amount +\
                    payment_or_account_payment.interest_amount
            else:
                dpd = payment_or_account_payment.due_late_days
                installment_amount_without_late_fee = \
                    payment_or_account_payment.installment_principal + \
                    payment_or_account_payment.installment_interest

            payments_or_account_payments_info.append(
                dict(
                    due_date=payment_or_account_payment.due_date,
                    dpd=dpd,
                    installment_amount_without_late_fee=installment_amount_without_late_fee,
                    late_fee_amount=payment_or_account_payment.late_fee_amount,
                    paid_amount=payment_or_account_payment.paid_amount,
                    due_amount=payment_or_account_payment.due_amount,
                    is_paid_label=is_paid_label,
                )
            )

        return customer_info, payments_or_account_payments_info

    def _create_email_history(
            self, status, headers, subject, msg, template,
            payment_or_account_payment):
        if status == 202:
            email = collection_detokenize_sync_object_model(
                'customer', self._customer, self._customer.customer_xid, ['email']
            ).email
            email_history_param = dict(
                customer=self._customer,
                sg_message_id=headers["X-Message-Id"],
                to_email=email,
                subject=subject,
                application=self._application,
                message_content=msg,
                template_code=template,
            )
            if self._is_for_j1:
                email_history_param['account_payment'] = payment_or_account_payment
            else:
                email_history_param['payment'] = payment_or_account_payment

            EmailHistory.objects.create(**email_history_param)

            logger.info({
                "action": "email_for_multiple_ptp_and_expired_plus_1",
                "customer_id": self._customer.id,
                "template_code": template
            })
        else:
            logger.warn({
                'action': "email_for_multiple_ptp_and_expired_plus_1",
                'status': status,
                'message_id': headers['X-Message-Id']
            })

    def _validate_email_send(self):
        if not self._waiver_request.is_multiple_ptp_payment:
            return False

        templates = ['multiple_ptp_after_expiry_date', 'multiple_ptp_after_expiry_date_b5']
        today = timezone.localtime(timezone.now())
        start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        email_history_filter = dict(
            customer=self._customer,
            application=self._application,
            template_code__in=templates,
            cdate__gte=start_of_day,
            cdate__lt=end_of_day,
        )
        if self._is_for_j1:
            email_history_filter['account_payment'] = self._first_unpaid_payment_or_account_payment
        else:
            email_history_filter['payment'] = self._first_unpaid_payment_or_account_payment

        return not EmailHistory.objects.filter(**email_history_filter).exists()

    def send_email_for_multiple_ptp_and_expired_plus_1(self):
        if not self._validate_email_send():
            return

        template_code = 'multiple_ptp_after_expiry_date'
        template = 'multiple_payment_ptp/multiple_ptp_reminder_plus_1.html'
        customer_info, payments_or_account_payments_info = self._construct_email_params()
        is_bucket_5, template_code = check_template_bucket_5(
            self._first_unpaid_payment_or_account_payment, template_code, 'email', self._is_for_j1)
        subject = 'Masa berlaku program keringanan telah kadaluarsa.'
        parameters = self._email_client.email_multiple_ptp_and_expired_plus_1(
            customer_info, payments_or_account_payments_info, is_bucket_5, subject, template)
        self._create_email_history(*(parameters + (
            template_code, self._first_unpaid_payment_or_account_payment)))
