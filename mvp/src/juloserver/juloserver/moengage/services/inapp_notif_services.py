from juloserver.streamlined_communication.models import InAppNotificationHistory
from juloserver.moengage.constants import InAppStatusType, InAppStreamsStatus
import logging
logger = logging.getLogger(__name__)


def update_inapp_notif_details(data, is_stream=False):
    if not data:
        return

    if not is_stream:
        if data['event_code'] not in list(InAppStatusType.keys()):
            return
        status = InAppStatusType[data['event_code']]
    else:
        if data['event_code'] not in list(InAppStreamsStatus.keys()):
            return
        status = InAppStreamsStatus[data['event_code']]
    InAppNotificationHistory.objects.create(
        source=data['event_source'],
        customer_id=data['customer_id'],
        template_code=data['template_code'],
        status=status,
    )
