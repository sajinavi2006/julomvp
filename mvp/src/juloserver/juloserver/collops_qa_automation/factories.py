from factory.django import DjangoModelFactory
from faker import Faker
from factory import SubFactory
from factory import LazyAttribute
from factory import post_generation
from factory import Iterator

from juloserver.collection_vendor.tests.factories import VendorRecordingDetailFactory
from juloserver.collops_qa_automation.models import RecordingReport, AirudderRecordingUpload


class AirudderRecordingUploadFactory(DjangoModelFactory):
    class Meta(object):
        model = AirudderRecordingUpload

    vendor_recording_detail = SubFactory(VendorRecordingDetailFactory)
    task_id = 'task_123'
    status = 'ok'
    code = 200


class RecordingReportFactory(DjangoModelFactory):
    class Meta(object):
        model = RecordingReport

    airudder_recording_upload = SubFactory(
        AirudderRecordingUploadFactory)
    length = 20
    total_words = 30
    l_channel_sentence = "10'00: Selamat pagi \n30'020: Selamat siang"
    l_channel_negative_checkpoint = "negative"
    l_channel_negative_score = "1/10"
    l_channel_sop_checkpoint = "sop"
    l_channel_sop_score = "2/20"
    r_channel_sentence = "01'00: Selamat pagi \n30'020: Selamat siang"
    r_channel_negative_checkpoint = "negative"
    r_channel_negative_score = "3/10"
    r_channel_sop_checkpoint = "sop"
    r_channel_sop_score = "4/10"
