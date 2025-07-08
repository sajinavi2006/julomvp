from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker
from factory import SubFactory
from factory import LazyAttribute
from factory import post_generation
from django.utils import timezone

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import (
    PaymentFactory,
    ApplicationFactory,
    CustomerFactory,
)

from juloserver.collection_vendor.models import (
    CollectionVendorAssignment,
    CollectionVendorRatio,
    CollectionVendorAssignmentExtension,
    CollectionVendor,
    CollectionVendorAssignmentTransfer,
    CollectionVendorAssigmentTransferType,
    AgentAssignment,
    SubBucket,
    UploadVendorReport,
    VendorReportErrorInformation
)
from juloserver.collection_vendor.constant import CollectionVendorCodes
from juloserver.julo.models import Skiptrace, Customer, Application, SkiptraceResultChoice, SkiptraceHistory, Loan
from juloserver.julo.tests.factories import AuthUserFactory, PaymentFactory
from juloserver.minisquad.models import VendorRecordingDetail

fake = Faker()


class CollectionVendorFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionVendor

    vendor_name = 'Rajawali'
    is_active = True
    is_special = True
    is_general = True
    is_final = True


class SubBucketFactory(DjangoModelFactory):
    class Meta(object):
        model = SubBucket

    bucket = 1
    sub_bucket = 1
    start_dpd = 1


class CollectionVendorAssigmentTransferTypeFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionVendorAssigmentTransferType
        django_get_or_create = ('id',)

    id = 4
    transfer_from = 'Vendor'
    transfer_to = 'Vendor'


class CollectionVendorAssignmentTransferFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionVendorAssignmentTransfer

    payment = SubFactory(PaymentFactory)
    transfer_type = SubFactory(CollectionVendorAssigmentTransferTypeFactory)


class CollectionVendorAssignmentExtensionFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionVendorAssignmentExtension

    vendor = SubFactory(CollectionVendorFactory)
    payment = SubFactory(PaymentFactory)
    sub_bucket_current = SubFactory(SubBucketFactory)
    dpd_current = 1
    retain_reason = 'test_retain_reason'
    retain_removal_date = '2020-12-30'
    retain_inputted_by = SubFactory(AuthUserFactory)


class CollectionVendorAssignmentFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionVendorAssignment

    vendor = SubFactory(CollectionVendorFactory)
    payment = SubFactory(PaymentFactory)
    sub_bucket_assign_time = SubFactory(SubBucketFactory)
    dpd_assign_time = 1
    collection_vendor_assigment_transfer = SubFactory(CollectionVendorAssignmentTransferFactory)
    # vendor_assignment_extension = SubFactory(CollectionVendorAssignmentExtensionFactory)


class CollectionVendorRatioFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionVendorRatio

    collection_vendor = SubFactory(CollectionVendorFactory)
    vendor_types = CollectionVendorCodes.VENDOR_TYPES.get('special')
    account_distribution_ratio = 0.3


class SkipTraceFactory(DjangoModelFactory):
    class Meta(object):
        model = Skiptrace

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    contact_name = "Unit Test"
    phone_number = "+6285111112341"
    contact_source = "mobile_phone_1"
    phone_operator = "Unit Test Operator"
    effectiveness = 0.00


class SkiptraceResultChoiceFactory(DjangoModelFactory):
    class Meta(object):
        model = SkiptraceResultChoice

    name = "RPC - PTP"
    weight = 3
    customer_reliability_score = 10


class SkiptraceHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = SkiptraceHistory

    skiptrace = SubFactory(SkipTraceFactory)
    start_ts = timezone.localtime(timezone.now())
    agent = SubFactory(AuthUserFactory)
    agent_name = 'unittest'
    call_result = SubFactory(SkiptraceResultChoiceFactory)
    application = SubFactory(ApplicationFactory)
    application_status = 180
    old_application_status = 180
    loan_status = 234
    payment_status = 324
    notes = 'test Skiptrace'


class AgentAssignmentFactory(DjangoModelFactory):
    class Meta(object):
        model = AgentAssignment

    agent = SubFactory(AuthUserFactory)
    payment = SubFactory(PaymentFactory)
    dpd_assign_time = 92
    sub_bucket_assign_time = SubFactory(SubBucketFactory)


class UploadVendorReportFactory(DjangoModelFactory):
    class Meta(object):
        model = UploadVendorReport

    file_name = 'test.xls'
    vendor = SubFactory(CollectionVendorFactory)
    upload_status = 'success'


class VendorReportErrorInformationFactory(DjangoModelFactory):
    class Meta(object):
        model = VendorReportErrorInformation

    upload_vendor_report = SubFactory(UploadVendorReportFactory)
    field = 'action id'
    error_reason = 'tidak terisi'
    value = None


class VendorRecordingDetailFactory(DjangoModelFactory):
    class Meta(object):
        model = VendorRecordingDetail

    agent = SubFactory(AuthUserFactory)
    bucket = 'BUCKET_1'
    payment = SubFactory(PaymentFactory)
    account_payment = SubFactory(AccountPaymentFactory)
    call_status = SubFactory(SkiptraceResultChoiceFactory)
    call_to = '08123456789'
    call_start = timezone.localtime(timezone.now())
    call_end = timezone.localtime(timezone.now())
    duration = 10
    voice_path = 'unittest/recording_detail/voice.wav'
