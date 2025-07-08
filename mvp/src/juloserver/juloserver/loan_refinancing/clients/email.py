from builtins import object
import logging

from django.db.models import Sum
from django.template.loader import render_to_string
from babel.dates import format_date
from ..constants import CovidRefinancingConst
from django.utils import timezone
from datetime import timedelta
from juloserver.julo.utils import display_rupiah
from juloserver.julo.models import Payment
from juloserver.loan_refinancing.models import WaiverRequest
from juloserver.julocore.python2.utils import py2round
from ...account_payment.models import AccountPayment
from ...account_payment.services.account_payment_related import get_unpaid_account_payment
from juloserver.julo.constants import EmailDeliveryAddress
from juloserver.loan_refinancing.services.notification_related import \
    check_loan_refinancing_with_requested_status_cohort_campaign
from juloserver.loan_refinancing.services.refinancing_product_related import (
    generate_content_email_sos_refinancing,
    get_first_payment_due_date,
    get_prerequisite_amount_has_paid,
)
from django.conf import settings
from juloserver.portal.core.templatetags.unit import format_rupiahs
from ...julosoap.views import application
from juloserver.pii_vault.constants import PiiSource
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from django.template import Context, Template
from juloserver.julo.clients import get_julo_email_client, get_external_email_client
from juloserver.minisquad.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting

logger = logging.getLogger(__name__)


class LoanRefinancingEmailClient(object):
    def email_base(self, loan_refinancing, subject, template,
                   payments=None, calendar_link=None, customer_info=None,
                   is_bucket_5=False, is_for_j1=False):
        loan = loan_refinancing.loan
        if is_for_j1:
            application = loan_refinancing.account.application_set.first()
            customer = loan_refinancing.account.customer
            unpaid_payments = get_unpaid_account_payment(
                loan_refinancing.account.id)
        else:
            application = loan.application
            customer = loan.customer
            unpaid_payments = Payment.objects.by_loan(loan_refinancing.loan)
        total_payments = 0
        for payment in unpaid_payments:
            total_payments = total_payments + payment.due_amount

        if loan_refinancing.product_type in CovidRefinancingConst.waiver_products():
            if not loan_refinancing.product_type == CovidRefinancingConst.PRODUCTS.r4:
                if is_for_j1:
                    waiver_request = WaiverRequest.objects.filter(
                        account=loan_refinancing.account).last()
                else:
                    waiver_request = WaiverRequest.objects.filter(loan_id=loan.id).last()
                if waiver_request:
                    total_payments = waiver_request.outstanding_amount

        # check if it's from offer campaign with status loan refinancing 'requested'
        # and for R123 cohort campaign
        if check_loan_refinancing_with_requested_status_cohort_campaign(loan_refinancing.id):
            total_payments = loan_refinancing.account.get_total_overdue_amount()

        prerequisite_amount = loan_refinancing.last_prerequisite_amount
        # handle if customer pay partialy
        if loan_refinancing.product_type == CovidRefinancingConst.PRODUCTS.r4:
            waiver_request = WaiverRequest.objects.filter(account=loan_refinancing.account).last()
            # This is to handle situations where the due amount from a customer increases 
            # or where a customer makes a partial payment during the R4 process.
            amount_deducted = get_prerequisite_amount_has_paid(
                loan_refinancing,
                get_first_payment_due_date(loan_refinancing),
                loan_refinancing.account
            )
            prerequisite_amount -= amount_deducted

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['fullname', 'email'],
        )

        context = {
            'fullname_with_title': application.fullname_with_title,
            'first_due_date': format_date(
                loan_refinancing.first_due_date, 'd MMMM yyyy', locale='id_ID'
            ),
            'prerequisite_amount': display_rupiah(prerequisite_amount),
            'rating_link': "https://play.google.com/store/apps/details?id=com.julofinance.juloapp",
            'payments': payments,
            'calendar_link': calendar_link,
            'total_payments': display_rupiah(total_payments),
            'firstname_with_title': application.first_name_with_title,
            'is_for_j1': is_for_j1
        }
        if total_payments > 0:
            context["total_discount_percent"] = int(
                (1 - loan_refinancing.last_prerequisite_amount / float(total_payments)) * 100)

        if customer_info:
            context['bank_code'] = customer_info['bank_code']
            context['va_number'] = customer_info['va_number']
            context['bank_name'] = customer_info['bank_name']

        context['is_bucket_5'] = is_bucket_5
        if is_bucket_5:
            email_from = EmailDeliveryAddress.COLLECTIONS_JTF
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        else:
            email_from = EmailDeliveryAddress.CS_JULO
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        msg = render_to_string(template, context)
        email_to = customer_detokenized.email

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_request',
            'email': email_to,
            'template': template
        })
        template = 'activated_offer_template'

        return status, headers, subject, msg, template

    def email_reminder_refinancing(self, loan_refinancing, subject, template, due_date):
        if loan_refinancing.account:
            application = loan_refinancing.account.application_set.first()
        else:
            application = loan_refinancing.loan.application

        customer = application.customer

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['fullname', 'email'],
        )

        context = {
            'fullname_with_title': application.fullname_with_title,
            'due_date': format_date(due_date, 'd MMMM yyyy', locale='id_ID'),
            'url': loan_refinancing.url,
        }

        msg = render_to_string(template, context)
        email_to = customer_detokenized.email
        email_from = EmailDeliveryAddress.CS_JULO
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

        if loan_refinancing.product_type in CovidRefinancingConst.reactive_products():
            template = 'reminder_click_setujuwebpage_email_1'
        elif loan_refinancing.product_type in CovidRefinancingConst.waiver_products():
            template = 'reminder_click_setujuwebpage_email_2'

        return status, headers, subject, msg, template

    def email_proactive_refinancing_reminder(self, loan_refinancing,
                                             subject, template_code, is_bucket_5=False):
        if loan_refinancing.account:
            application = loan_refinancing.account.application_set.first()
            installment_amount = loan_refinancing.account.\
                sum_of_all_active_installment_amount()
        else:
            application = loan_refinancing.loan.application
            installment_amount = loan_refinancing.loan.installment_amount

        customer = application.customer

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['email'],
        )

        context = {
            'current_installment_amount': display_rupiah(installment_amount),
            'fullname_with_title': application.fullname_with_title,
            'url': loan_refinancing.url,
        }

        if loan_refinancing.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
            due_date = loan_refinancing.first_due_date
            context["due_date"] = format_date(due_date, 'd MMMM yyyy', locale='id_ID')

        context['is_bucket_5'] = is_bucket_5
        if is_bucket_5:
            email_from = EmailDeliveryAddress.COLLECTIONS_JTF
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
            template_name = template_code.rstrip('_b5')
        else:
            email_from = EmailDeliveryAddress.CS_JULO
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
            template_name = template_code

        email_to = customer_detokenized.email
        template = "proactive_refinancing/%s.html" % template_name
        msg = render_to_string(template, context)

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_proactive_request',
            'email': email_to
        })

        return status, headers, subject, msg, template_code

    def email_refinancing_offer_selected(self, loan_refinancing, subject,
                                         template_code, is_bucket_5=False, is_for_j1=False):
        loan = loan_refinancing.loan
        if is_for_j1:
            application = loan_refinancing.account.application_set.last()
            payments = AccountPayment.objects.filter(
                account=loan_refinancing.account).not_paid_active().order_by('due_date')
        else:
            application = loan.application
            payments = Payment.objects.filter(
                loan=loan_refinancing.loan).not_paid_active().order_by('payment_number')

        customer = application.customer

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['fullname', 'email'],
        )

        all_outstanding_amount = 0
        for payment in payments:
            all_outstanding_amount = all_outstanding_amount + int(payment.due_amount)

        first_unpaid_payment = payments.first().due_amount if payments.first() else 0

        total_discount = all_outstanding_amount - loan_refinancing.prerequisite_amount
        total_discount = (float(total_discount) / float(all_outstanding_amount)) * float(100)
        if is_for_j1:
            all_ongoing_loan_installment_amount = loan_refinancing.account.\
                sum_of_all_active_installment_amount()
        else:
            all_ongoing_loan_installment_amount = loan.installment_amount

        dif_discount = all_ongoing_loan_installment_amount - loan_refinancing.prerequisite_amount
        total_discount_refinancing = float(dif_discount) / float(all_ongoing_loan_installment_amount)
        total_discount_refinancing = total_discount_refinancing * float(100)

        if loan_refinancing.product_type in CovidRefinancingConst.reactive_products():
            product_name = "Restrukturisasi"
        else:
            product_name = "Pelunasan Dengan Diskon"

        context = {
            'refinancing_installment_amount': display_rupiah(loan_refinancing.prerequisite_amount),
            'fullname_with_title': application.first_name_with_title_short,
            'total_discount': int(py2round(total_discount)),
            'total_discount_refinancing': int(py2round(total_discount_refinancing)),
            'total_prerequisite_amount': display_rupiah(loan_refinancing.prerequisite_amount),
            'sum_current_due_amount': display_rupiah(all_outstanding_amount),
            'url': loan_refinancing.url,
            'product_name': product_name,
            'due_date': format_date(loan_refinancing.first_due_date, 'd MMMM yyyy', locale='id_ID'),
            'current_installment_amount': display_rupiah(all_ongoing_loan_installment_amount),
            'first_unpaid_payment': display_rupiah(first_unpaid_payment),
        }

        context['is_bucket_5'] = is_bucket_5
        if is_bucket_5:
            email_from = EmailDeliveryAddress.COLLECTIONS_JTF
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
            template_name = template_code.rstrip('_b5')
        else:
            email_from = EmailDeliveryAddress.CS_JULO
            name_from = 'JULO'
            reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
            template_name = template_code

        template = "proactive_refinancing/%s.html" % template_name
        msg = render_to_string(template, context)
        email_to = customer_detokenized.email

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_offer_selected',
            'email': email_to
        })

        return status, headers, subject, msg, template_code

    def email_sos_refinancing(self, loan_refinancing, subject, template):
        application = loan_refinancing.account.application_set.first()
        customer = loan_refinancing.account.customer

        context = generate_content_email_sos_refinancing(
            application.fullname_with_title, loan_refinancing)

        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF

        msg = render_to_string(template, context)
        email_to = customer.email

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_loan_refinancing_request',
            'email': email_to,
            'template': template
        })
        template = 'sos_email_refinancing_r1_30/08/23'

        return status, headers, subject, msg, template

    def email_promo_r4_b5(self, loan_refinancing, subject, template, api_key):
        from juloserver.julo.clients.email import JuloEmailClient

        logger.info(
            {'action': 'email_promo_r4_b5', 'status': 'construct email', 'template': template}
        )

        application = loan_refinancing.account.application_set.last()
        customer = application.customer
        all_outstanding_amount = loan_refinancing.account.account.get_total_outstanding_amount()

        discount_amount = loan_refinancing.last_prerequisite_amount
        name_with_title = application.fullname_with_title

        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        name_from = 'JULO'
        context = dict(
            name_with_title=name_with_title,
            discounted_due_amount=format_rupiahs(int(discount_amount), 'default-0'),
            due_amount=format_rupiahs(int(all_outstanding_amount), 'default-0'),
        )

        msg = render_to_string(template, context)
        email = JuloEmailClient(api_key, settings.EMAIL_FROM)

        logger.info(
            {'action': 'email_promo_r4_b5', 'status': 'start blast email', 'template': template}
        )

        status, body, headers = email.send_email(
            subject,
            msg,
            customer.email,
            email_from=email_from,
            email_cc=None,
            name_from=name_from,
            reply_to=email_from,
        )
        logger.info(
            {'action': 'email_promo_r4_b5', 'status': 'finish blast email', 'template': template}
        )
        logger.info({'action': 'email_promo_r4_b5', 'email': customer.email, 'template': template})
        return status, headers, subject, msg, template

    def email_promo_r4_blast(self, loan_refinancing, subject, template, template_raw=None):
        from juloserver.julo.clients.email import JuloEmailClient

        logger.info(
            {'action': 'email_promo_r4_blast', 'status': 'construct email', 'template': template}
        )

        application = loan_refinancing.account.application_set.last()
        customer = application.customer
        all_outstanding_amount = loan_refinancing.account.get_total_outstanding_amount()

        discount_amount = loan_refinancing.last_prerequisite_amount
        name_with_title = application.fullname_with_title

        context = dict(
            name_with_title=name_with_title,
            discounted_due_amount=format_rupiahs(int(discount_amount), 'default-0'),
            due_amount=format_rupiahs(int(all_outstanding_amount), 'default-0'),
        )

        if template_raw:
            msg = Template(template_raw).render(Context(context))
        else:
            msg = render_to_string(template, context)

        promo_blast_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
        ).last()

        if promo_blast_fs:
            parameters = promo_blast_fs.parameters
            email_settings = parameters.get('email_settings')

            api_key = email_settings.get('api_key')
            email_from = email_settings.get('email_from')
            name_from = email_settings.get('name_from')
            email = get_external_email_client(api_key, email_from)
        else:
            email = get_julo_email_client()
            email_from = settings.EMAIL_FROM
            name_from = 'JULO'


        logger.info(
            {'action': 'email_promo_r4_blast', 'status': 'start blast email', 'template': template}
        )

        status, body, headers = email.send_email(
            subject,
            msg,
            customer.email,
            email_from=email_from,
            email_cc=None,
            name_from=name_from,
            reply_to=email_from,
        )
        logger.info(
            {'action': 'email_promo_r4_blast', 'status': 'finish blast email', 'template': template}
        )
        logger.info(
            {'action': 'email_promo_r4_blast', 'email': customer.email, 'template': template}
        )
        return status, headers, subject, msg, template
