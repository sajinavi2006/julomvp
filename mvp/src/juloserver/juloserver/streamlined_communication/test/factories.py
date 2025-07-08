from builtins import object
from datetime import datetime

from factory.django import DjangoModelFactory

from juloserver.account.tests.factories import AccountFactory
from juloserver.fdc.tests import fake
from juloserver.streamlined_communication.models import (
    Holiday,
    StreamlinedCommunication,
    StreamlinedMessage,
    InfoCardButtonProperty,
    InfoCardProperty,
    NeoBannerCard,
    StreamlinedCommunicationSegment,
    StreamlinedCampaignDepartment,
    StreamlinedCommunicationCampaign,
    StreamlinedCampaignSquad,
    CommsUserSegmentChunk,
)
from factory import SubFactory, LazyAttribute

from juloserver.streamlined_communication.models import (
    TelcoServiceProvider,
    SmsTspVendorConfig,
    CommsCampaignSmsHistory,
)

from juloserver.streamlined_communication.constant import (
    SmsTspVendorConstants,
    StreamlinedCommCampaignConstants,
    CommsUserSegmentConstants,
)

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
)


class StreamlinedMessageFactory(DjangoModelFactory):
    class Meta(object):
        model = StreamlinedMessage
    message_content = '[{"action": "talk","voiceName": "Damayanti","text": '\
                      '"Selamat {{greet}}{{ name_with_title }}, angsuran JULO Anda'\
                      '{{ due_amount }} rupiah akan jatuh tempo dalam '\
                      '{{ days_before_due_date }} hari."},{"action": "talk",'\
                      '"voiceName": "Damayanti","text": "Bayar sekarang dan dapatkan '\
                      'kesbek sebesar {{ cashback_multiplier }} kali.{{ promo_message }}"}'\
                      ',{"action": "talk","voiceName": "Damayanti","text":"Tekan '\
                      '1 untuk konfirmasi. Terima kasih"},{"action": "input","maxDigits":'\
                      ' 1,"eventUrl": ["{{input_webhook_url}}"]}]'


class StreamlinedCommunicationFactory(DjangoModelFactory):
    class Meta(object):
        model = StreamlinedCommunication

    message = SubFactory(StreamlinedMessageFactory)
    dpd = -3


class InfoCardPropertyFactory(DjangoModelFactory):
    class Meta(object):
        model = InfoCardProperty

    card_type = '1'
    card_action = 'app_deeplink'
    title = 'Title'
    card_order_number = 1


class ButtonInfoCardFactory(DjangoModelFactory):
    class Meta(object):
        model = InfoCardButtonProperty

    id = 1
    info_card_property = SubFactory(InfoCardPropertyFactory)
    button_name = 'L.BUTTON'
    text = "Button"


class HolidayFactory(DjangoModelFactory):
    class Meta(object):
        model = Holiday

    holiday_date = datetime(2022, 9, 3)
    is_annual = False


class TelcoServiceProviderFactory(DjangoModelFactory):
    class Meta(object):
        model = TelcoServiceProvider

    provider_name = SmsTspVendorConstants.OTHERS
    telco_code = None


class SmsTspVendorConfigFactory(DjangoModelFactory):
    class Meta(object):
        model = SmsTspVendorConfig

    tsp = SmsTspVendorConstants.OTHERS
    primary = None
    backup = None
    is_otp = False


class NeoBannerCardFactory(DjangoModelFactory):
    class Meta(object):
        model = NeoBannerCard

    product = "J1"
    statuses = "[100]"
    is_active = True


class StreamlinedCommunicationSegmentFactory(DjangoModelFactory):
    class Meta(object):
        model = StreamlinedCommunicationSegment

    uploaded_by = SubFactory(AuthUserFactory)
    csv_file_url = 'test_file.csv'
    csv_file_name = 'test_file.csv'
    csv_file_type = "account_id"
    segment_count = "0"
    segment_name = "test_segment_account"


class StreamlinedCampaignDepartmentFactory(DjangoModelFactory):
    class Meta(object):
        model = StreamlinedCampaignDepartment

    name = 'Marketing'
    department_code = 'MKT'


class StreamlinedCommunicationCampaignFactory(DjangoModelFactory):
    class Meta(object):
        model = StreamlinedCommunicationCampaign

    created_by = SubFactory(AuthUserFactory)
    name = 'Test Campaign'
    department = SubFactory(StreamlinedCampaignDepartmentFactory)
    campaign_type = StreamlinedCommCampaignConstants.CampaignType.SMS
    user_segment = SubFactory(StreamlinedCommunicationSegmentFactory)
    status = StreamlinedCommCampaignConstants.CampaignStatus.WAITING_FOR_APPROVAL
    content = SubFactory(StreamlinedMessageFactory)


class StreamlinedCampaignSquadFactory(DjangoModelFactory):
    class Meta(object):
        model = StreamlinedCampaignSquad

    name = 'Fraud'


class CommsCampaignSmsHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = CommsCampaignSmsHistory

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    account = SubFactory(AccountFactory)
    status = 'Delivered'
    to_mobile_phone = '+6286638032509'
    template_code = 'dummy_template_code'


class CommsUserSegmentChunkFactory(DjangoModelFactory):
    class Meta(object):
        model = CommsUserSegmentChunk

    chunk_csv_file_url = "test_file_chunk.csv"
    chunk_csv_file_name = "test_file_chunk.csv"
    chunk_number = LazyAttribute(lambda o: fake.random_int(1, 10))
    streamlined_communication_segment = SubFactory(StreamlinedCommunicationSegmentFactory)
    process_status = CommsUserSegmentConstants.ChunkStatus.START
