import logging
from django.template import Context, Template

logger = logging.getLogger(__name__)


class CohortCampaignAutomationClient(object):
    def send_email_cohort_campaign_automation(
        self, subject, email_to, template_raw, context, email_domain, api_key
    ):
        from juloserver.julo.clients import get_external_email_client

        msg = Template(template_raw).render(Context(context))
        msg_new = Template(msg).render(Context(context))
        if 'kaldlaw' in email_domain.lower():
            name_from = 'KALD LAW office'
            email = get_external_email_client(api_key, email_domain)
            status, body, headers = email.send_email(
                subject,
                msg_new,
                email_to,
                email_from=email_domain,
                email_cc=None,
                name_from=name_from,
                reply_to=email_domain,
            )
        else:
            name_from = 'JULO'
            status, body, headers = self.send_email(
                subject,
                msg_new,
                email_to,
                email_from=email_domain,
                email_cc=None,
                name_from=name_from,
                reply_to=email_domain,
            )

        logger.info(
            {
                'action': 'send_email_cohort_campaign_automation',
                'email': email_to,
            }
        )
        template = 'activated_offer_template'

        return status, headers, subject, msg_new, template
