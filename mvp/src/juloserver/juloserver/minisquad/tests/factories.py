from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker
from factory import SubFactory
from factory import LazyAttribute
from factory import post_generation
from factory import Iterator

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.minisquad.models import (
    CollectionHistory,
    intelixBlacklist,
    DialerTaskEvent,
    CollectionDialerTemporaryData,
    NotSentToDialer,
    CollectionBucketInhouseVendor,
    AccountDueAmountAbove2Mio,
    CollectionDialerTaskSummaryAPI,
    AIRudderPayloadTemp,
)

from juloserver.julo.tests.factories import (
    PaymentFactory,
    LoanFactory,
    CustomerFactory
)
from juloserver.minisquad.models import SentToDialer, DialerTask, TemporaryStorageDialer
from juloserver.account.tests.factories import AccountFactory

fake = Faker()


class CollectionHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionHistory

    customer = SubFactory(CustomerFactory)
    last_current_status = True


class intelixBlacklistFactory(DjangoModelFactory):
    class Meta(object):
        model = intelixBlacklist


class DialerTaskFactory(DjangoModelFactory):
    class Meta(object):
        model = DialerTask

    vendor = 'Intelix'
    type = 'upload_julo_b1_data'
    status = 'initiated'
    retry_count = 0


class SentToDialerFactory(DjangoModelFactory):
    class Meta(object):
        model = SentToDialer

    bucket = 'test_bucket'
    sorted_by_collection_model = False
    dialer_task = SubFactory(DialerTaskFactory)


class DialerTaskSentFactory(DjangoModelFactory):
    class Meta(object):
        model = DialerTask
    vendor = 'Intelix'
    type = 'upload_julo_b3_nc_data'
    status = 'sent'
    retry_count = 0


class DialerTaskEventFactory(DjangoModelFactory):
    class Meta(object):
        model = DialerTaskEvent

    dialer_task = SubFactory(DialerTaskFactory)
    status = 'initiated'
    data_count = 0


class CollectionDialerTemporaryDataFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionDialerTemporaryData

    customer = SubFactory(CustomerFactory)
    account_payment = SubFactory(AccountPaymentFactory)
    application_id = '123123124123123'
    nama_customer = 'unit test'
    nama_perusahaan = 'company'
    posisi_karyawan = 'posisition test'
    nama_pasangan = 'spouse test'
    nama_kerabat = 'kin test'
    hubungan_kerabat = 'relate test'
    jenis_kelamin = 'L'
    tgl_lahir = '2022-01-01'
    tgl_gajian = '2022-01-01'
    tujuan_pinjaman = 'loan purpose test'
    tanggal_jatuh_tempo = '2022-01-01'
    alamat = 'address test'
    kota = 'city test'
    tipe_produk = 'j1'
    partner_name = 'partner test'
    sort_order = '1'
    dpd = 22
    team = 'Bucket 1'


class TemporaryStorageDialerFactory(DjangoModelFactory):
    class Meta(object):
        model = TemporaryStorageDialer


class NotSentToDialerFactory(DjangoModelFactory):
    class Meta(object):
        model = NotSentToDialer

    bucket = 'test_bucket'
    dialer_task = SubFactory(DialerTaskFactory)
    unsent_reason = ''


class CollectionBucketInhouseVendorFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionBucketInhouseVendor

    account_payment = SubFactory(AccountPaymentFactory)

class AccountDueAmountAbove2MioFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountDueAmountAbove2Mio


class CollectionDialerTaskSummaryAPI(DjangoModelFactory):
    class Meta(object):
        model = CollectionDialerTaskSummaryAPI


class AIRudderPayloadTempFactory(DjangoModelFactory):
    class Meta(object):
        model = AIRudderPayloadTemp

    account_payment = SubFactory(AccountPaymentFactory)
    account = SubFactory(AccountFactory)
    customer = SubFactory(CustomerFactory)
