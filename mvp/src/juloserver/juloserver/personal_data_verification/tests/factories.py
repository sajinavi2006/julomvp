import factory
from factory import DjangoModelFactory, SubFactory

from juloserver.julo.tests.factories import ApplicationFactory, ImageFactory
from juloserver.personal_data_verification.models import (
    BureauEmailSocial,
    BureauMobileIntelligence,
    BureauPhoneSocial,
    DukcapilResponse,
    DukcapilFaceRecognitionCheck,
)


class DukcapilResponseFactory(DjangoModelFactory):
    class Meta:
        model = DukcapilResponse

    application = SubFactory(ApplicationFactory)


class DukcapilFaceRecognitionCheckFactory(DjangoModelFactory):
    class Meta:
        model = DukcapilFaceRecognitionCheck

    application_id = 1
    transaction_source = ""
    client_customer_id = ""
    nik = ""
    threshold = 1
    image_id = 1
    template = ""
    type = ""
    position = ""


class BureauEmailSocialFactory(DjangoModelFactory):
    class Meta:
        model = BureauEmailSocial

    application = SubFactory(ApplicationFactory)
    raw_data = {}


class BureauMobileIntelligenceFactory(DjangoModelFactory):
    class Meta:
        model = BureauMobileIntelligence

    application = SubFactory(ApplicationFactory)
    raw_data = {}


class BureauPhoneSocialFactory(DjangoModelFactory):
    class Meta:
        model = BureauPhoneSocial

    application = SubFactory(ApplicationFactory)
    raw_data = {}
