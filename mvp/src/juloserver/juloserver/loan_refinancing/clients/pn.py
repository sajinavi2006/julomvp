from builtins import object
import logging

from juloserver.streamlined_communication.constant import PageType

logger = logging.getLogger(__name__)


class LoanRefinancingPnClient(object):
    def loan_refinancing_notification(self, loan_refinancing, data, template_code):
        if loan_refinancing.account:
            application = loan_refinancing.account.application_set.last()
        else:
            application = loan_refinancing.loan.application

        customer = application.customer
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        data["click_action"] = "com.julofinance.juloapp_HOME"
        data["destination_page"] = PageType.HOME

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            data=data,
            template_code=template_code)
        logger.info(response)
        return response
