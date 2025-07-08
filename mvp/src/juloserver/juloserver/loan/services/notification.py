from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.models import EmailHistory
import logging

logger = logging.getLogger(__name__)


class LoanEmail(object):
    def __init__(self, loan):
        self._loan = loan
        self._account = self._loan.account
        self._email_client = get_julo_email_client()
        self._application = self._account.application_set.last()
        self._customer = self._application.customer

    def _create_email_history(self, status, headers, subject, msg, template):
        if status == 202:
            email_history_param = dict(
                customer=self._customer,
                sg_message_id=headers["X-Message-Id"],
                to_email=self._customer.email,
                subject=subject,
                application=self._application,
                message_content=msg,
                template_code=template,
            )

            EmailHistory.objects.create(**email_history_param)

            logger.info({
                "action": "email_notify_loan_sphp",
                "customer_id": self._customer.id,
                "template_code": template
            })
        else:
            logger.warn({
                'action': "email_notify_loan_sphp",
                'status': status,
                'message_id': headers['X-Message-Id']
            })

    def send_sphp_email(self):
        from juloserver.loan.services.agreement_related import get_loan_agreement_type

        template = 'sphp_email.html'
        is_cashback_new_scheme = self._account.is_cashback_new_scheme
        if is_cashback_new_scheme:
            template = 'sphp_email_with_cashback.html'
        agreement_type = get_loan_agreement_type(self._loan.loan_xid)
        mail_type = agreement_type['text']
        parameters = self._email_client.email_sphp(
            self._loan, mail_type, template
        )
        self._create_email_history(*parameters)
