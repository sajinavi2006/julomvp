import logging

from django.conf import settings
from django.template import Context, Template

from juloserver.account_payment.models import AccountPayment
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.julo.models import EmailHistory

logger = logging.getLogger(__name__)


class CollectionHiSeasonEmailClient(JuloEmailClient):
    def email_collection_hi_season(
        self,
        account_payment_id,
        collection_hi_season_campaign,
        email_comm_setting,
        email_campaign_banner,
        payment_terms_date,
    ):
        account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
        customer = account_payment.account.customer
        application = account_payment.account.application_set.last()
        url = settings.OSS_CAMPAIGN_BASE_URL + email_campaign_banner.banner_url

        context = {
            'banner_url': url,
            'payment_terms_date': payment_terms_date,
            'due_date': account_payment.due_date,
            'block_url': email_comm_setting.block_url,
        }
        subject = email_comm_setting.email_subject
        template = Template(email_comm_setting.email_content)
        msg = template.render(Context(context))
        email_to = customer.email
        status, body, headers = self.send_email(
            subject,
            msg,
            email_to,
            email_from='info@mkt.julo.co.id',
            email_cc=None,
            name_from='JULO',
            reply_to='cs@julo.co.id',
        )

        logger.info(
            {
                'action': 'email_collection_hi_season',
                'email': email_to,
                'customer_id': customer.id,
                "promo_type": email_comm_setting.template_code,
            }
        )

        email_history = EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=email_to,
            subject=subject,
            application=application,
            message_content=msg,
            template_code=email_comm_setting.template_code,
            collection_hi_season_campaign_comms_setting=email_comm_setting,
        )

        if email_history:
            return True

        return False
