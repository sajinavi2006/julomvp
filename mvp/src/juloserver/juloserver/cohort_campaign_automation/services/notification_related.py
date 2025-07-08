import logging
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.utils import display_rupiah
from juloserver.julo.models import EmailHistory, PaymentMethod
from juloserver.loan_refinancing.models import WaiverRequest
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from django.utils.safestring import mark_safe
from babel.dates import format_date

logger = logging.getLogger(__name__)


class CohortCampaignAutomationEmail(object):
    def __init__(
        self,
        loan_refinancing=None,
        campaign_email=None,
        template_raw_email='',
        expiry_at=None,
        api_key='',
    ):
        self._email_client = get_julo_email_client()
        self._loan_refinancing = loan_refinancing
        self._account = self._loan_refinancing.account
        self._application = self._account.application_set.last()
        self._customer = self._application.customer
        self._payment_method = PaymentMethod.objects.filter(
            customer=self._customer, is_primary=True
        ).last()
        self._campaign_email = campaign_email
        self._subject = self._campaign_email.subject
        self._email_domain = self._campaign_email.email_domain
        self._banner_email = self._campaign_email.banner_url
        self._body_top_email = self._campaign_email.content_top
        self._body_mid_email = self._campaign_email.content_middle
        self._body_footer_email = self._campaign_email.content_footer
        self._template_raw_email = template_raw_email
        self._expiry_at = expiry_at
        self._api_key = api_key

    def _create_email_history(self, status, headers, subject, msg, template, account_payment):
        customer = self._customer
        application = self._application
        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            self._customer,
            self._customer.customer_xid,
            ['email'],
        )
        to_email = customer_detokenized.email
        if status == 202:
            email_history_param = dict(
                customer=customer,
                sg_message_id=headers["X-Message-Id"],
                to_email=to_email,
                subject=subject,
                application=application,
                message_content=msg,
                template_code=template,
                account_payment=account_payment,
            )
            EmailHistory.objects.create(**email_history_param)

            logger.info(
                {
                    "action": "email_cohort_campaign_automation",
                    "email_to": to_email,
                    "template_code": template,
                }
            )
        else:
            logger.warn(
                {
                    'action': "email_cohort_campaign_automation",
                    'status': status,
                    'message_id': headers['X-Message-Id'],
                }
            )

    def send_email(self):
        logger.info({"action": "send_email", "info": "sending"})
        waiver_request = WaiverRequest.objects.filter(account=self._account).last()
        account_payment = self._account.get_oldest_unpaid_account_payment()
        total_payments = waiver_request.outstanding_amount
        payment_method_detokenized = collection_detokenize_sync_object_model(
            PiiSource.PAYMENT_METHOD,
            self._payment_method,
            None,
            ['virtual_account'],
            PiiVaultDataType.KEY_VALUE,
        )
        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            self._customer,
            self._customer.customer_xid,
            ['email'],
        )
        context = {
            'fullname_with_title': self._application.fullname_with_title,
            'total_payments': display_rupiah(total_payments),
            'prerequisite_amount': display_rupiah(self._loan_refinancing.last_prerequisite_amount),
            'va_number': payment_method_detokenized.virtual_account,
            'bank_name': self._payment_method.payment_method_name,
            'banner_src': self._banner_email,
            'body_top_email': mark_safe(self._body_top_email) if self._body_top_email else '',
            'body_mid_email': mark_safe(self._body_mid_email) if self._body_mid_email else '',
            'body_footer_email': mark_safe(self._body_footer_email)
            if self._body_footer_email else '',
            'expiry_at': format_date(self._expiry_at, 'd MMMM yyyy', locale='id_ID'),
        }

        parameters = self._email_client.send_email_cohort_campaign_automation(
            subject=self._subject,
            email_to=customer_detokenized.email,
            template_raw=self._template_raw_email,
            context=context,
            email_domain=self._email_domain,
            api_key=self._api_key,
        )
        logger.info({"action": "send_email", "info": "sent"})
        template_code = self._campaign_email.campaign_automation.campaign_name.lower()
        parameters = parameters[:-1] + (template_code, account_payment)
        self._create_email_history(*parameters)
