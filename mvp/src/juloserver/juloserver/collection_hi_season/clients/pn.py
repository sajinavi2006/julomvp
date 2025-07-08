import logging

from django.conf import settings
from django.template import Context, Template

from juloserver.julo.clients.pn import JuloPNClient

from juloserver.streamlined_communication.constant import PageType

logger = logging.getLogger(__name__)


class CollectionHiSeasonPNClient(JuloPNClient):
    def pn_collection_hi_season(
        self, gcm_reg_id, pn_campaign_banner, pn_comm_setting, payment_terms_date
    ):
        parameter = {'payment_terms_date': payment_terms_date}
        template = Template(pn_comm_setting.pn_body)
        message = template.render(Context(parameter))
        title = pn_comm_setting.pn_title
        template_code = pn_comm_setting.template_code
        url = settings.OSS_CAMPAIGN_BASE_URL + pn_campaign_banner.banner_url

        notification = {"title": title, "body": message}

        data = {"destination_page": PageType.HOME, "image_url": url}

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code,
        )

        logger.info(response)
        return response
