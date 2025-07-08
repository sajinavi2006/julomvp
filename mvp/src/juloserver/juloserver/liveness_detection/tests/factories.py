from builtins import object

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    ImageFactory,
)
from juloserver.liveness_detection.constants import (
    ActiveLivenessPosition,
    LivenessCheckStatus,
    LivenessCheckType,
    LivenessVendor,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    ActiveLivenessVendorResult,
    PassiveLivenessDetection,
    PassiveLivenessVendorResult,
)


class ActiveLivenessVendorResultFactory(DjangoModelFactory):
    class Meta(object):
        model = ActiveLivenessVendorResult

    vendor_name = LivenessVendor.INNOVATRICS
    raw_response = {}
    raw_response_type = LivenessCheckType.ACTIVE


class ActiveLivenessDetectionFactory(DjangoModelFactory):
    class Meta(object):
        model = ActiveLivenessDetection

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    status = LivenessCheckStatus.INITIAL
    image_ids = []
    score = 1.0
    sequence = ActiveLivenessPosition.ALL
    liveness_vendor_result = SubFactory(ActiveLivenessVendorResultFactory)
    latency = 1
    configs = {}
    error_code = None


class PassiveLivenessVendorResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PassiveLivenessVendorResult

    vendor_name = LivenessVendor.INNOVATRICS
    raw_response = {}
    raw_response_type = LivenessCheckType.ACTIVE


class PassiveLivenessDetectionFactory(DjangoModelFactory):
    class Meta(object):
        model = PassiveLivenessDetection

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    status = LivenessCheckStatus.INITIAL
    image = SubFactory(ImageFactory)
    score = 1.0
    liveness_vendor_result = SubFactory(PassiveLivenessVendorResultFactory)
    latency = 1
    configs = {}
    error_code = None
    attempt = 0
