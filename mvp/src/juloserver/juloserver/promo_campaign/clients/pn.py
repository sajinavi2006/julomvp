from builtins import object
import logging

from juloserver.streamlined_communication.constant import PageType

REMINDER_TITLE = "JULO Reminder"


logger = logging.getLogger(__name__)


class PromoPnClient(object):
    def send_ramadan_pn(self, gcm_reg_id, pn_info):
        notification = {
            "title": pn_info['title'],
            "body": pn_info['message']
        }

        data = {
            "destination_page": PageType.HOME,
            "image_url": pn_info['image_url']
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=pn_info['template'])

        logger.info(response)

        return response
