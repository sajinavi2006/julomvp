from factory import DjangoModelFactory

from juloserver.comms.constants import (
    ChannelConst,
    VendorConst,
)
from juloserver.comms.models import CommsRequest


class CommsRequestFactory(DjangoModelFactory):
    class Meta:
        model = CommsRequest

    request_id = "test_request_id"
    channel = ChannelConst.EMAIL
    vendor = VendorConst.EMAIL_SERVICE_HTTP
