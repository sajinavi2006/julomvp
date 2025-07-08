from builtins import object
import logging
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.promo_campaign.utils import save_sms_history

logger = logging.getLogger(__name__)


class LoanRefinancingSmsClient(object):
    @save_sms_history
    def loan_refinancing_sms(self, loan_refinancing, message, template_code):
        if loan_refinancing.account:
            application = loan_refinancing.account.application_set.last()
        else:
            application = loan_refinancing.loan.application
        mobile_phone_1 = collection_detokenize_sync_object_model(
            'application', application, application.customer.customer_xid, ['mobile_phone_1']
        ).mobile_phone_1
        phone_number = format_e164_indo_phone_number(mobile_phone_1)
        logger.info({
            'action': 'loan_refinancing_notification',
            'to_phone_number': phone_number,
            'msg': message
        })
        message, response = self.send_sms(phone_number, message)
        return dict(
            response=response['messages'][0],
            customer=application.customer,
            application=application,
            template_code=template_code,
            message_content=message,
            to_mobile_phone=phone_number,
            phone_number_type='mobile_phone_1'
        )
