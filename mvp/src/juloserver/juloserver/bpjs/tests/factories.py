from builtins import object

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.bpjs.constants import TongdunCodes
from juloserver.bpjs.models import (
    BpjsTask,
    BpjsAPILog,
    BpjsUserAccess,
    SdBpjsCompany,
    SdBpjsCompanyScrape,
    SdBpjsPaymentScrape,
    SdBpjsProfile,
    SdBpjsProfileScrape,
)
from juloserver.julo.tests.factories import ApplicationFactory, CustomerFactory


class BpjsTaskFactory(DjangoModelFactory):
    class Meta(object):
        model = BpjsTask

    status_code = TongdunCodes.TONGDUN_TASK_SUCCESS_CODE
    application = SubFactory(ApplicationFactory)
    customer = SubFactory(CustomerFactory)


class BpjsApiLogFactory(DjangoModelFactory):
    class Meta(object):
        model = BpjsAPILog

    service_provider = 'bpjs_direct'
    application = SubFactory(ApplicationFactory)
    customer = SubFactory(CustomerFactory)
    http_status_code = 200
    response = "{'ret': '0', 'msg': 'Sukses', 'score': {'namaLengkap': 'SESUAI', 'nomorIdentitas': 'SESUAI', 'tglLahir': 'SESUAI', 'jenisKelamin': 'SESUAI', 'handphone': 'SESUAI', 'email': 'SESUAI', 'namaPerusahaan': 'SESUAI', 'paket': 'SESUAI', 'upahRange': 'SESUAI', 'blthUpah': 'SESUAI'}, 'CHECK_ID': '22111000575686'}"


class SdBpjsProfileFactory(DjangoModelFactory):
    class Meta(object):
        model = SdBpjsProfile

    email = "test@gmail.com"
    customer_id = 0
    application_id = 0


class SdBpjsCompanyFactory(DjangoModelFactory):
    class Meta(object):
        model = SdBpjsCompany

    sd_bpjs_profile = SubFactory(SdBpjsProfileFactory)


class SdBpjsProfileScrapeFactory(DjangoModelFactory):
    class Meta(object):
        model = SdBpjsProfileScrape

    identity_number = "12313131132"
    real_name = "testing"
    npwp_number = None
    birthday = "19-04-1986"
    phone = "+62891283131"
    address = "Jalan. xxxxxx"
    gender = "Laki-laki"
    bpjs_cards = '{"number": "019238","balance": "4556700"}'
    total_balance = "4556700"
    type = "bpjs-tk"


class SdBpjsCompanyScrapeFactory(DjangoModelFactory):
    class Meta(object):
        model = SdBpjsCompanyScrape

    profile = SubFactory(SdBpjsProfileScrapeFactory)
    company = "PT. XYZ"
    current_salary = "7000000"
    last_payment_date = "19-04-2022"
    employment_status = "Aktif"
    employment_month_duration = "2"
    bpjs_card_number = "019238"


class SdBpjsPaymentScrapeFactory(DjangoModelFactory):
    class Meta(object):
        model = SdBpjsPaymentScrape

    company = SubFactory(SdBpjsCompanyScrapeFactory)


class BpjsUserAccessFactory(DjangoModelFactory):
    class Meta(object):
        model = BpjsUserAccess

    data_source = "data_source"
    service_provider = "brick"
