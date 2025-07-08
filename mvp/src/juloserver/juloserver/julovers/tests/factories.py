import random
from datetime import date
from faker import Faker
from factory.django import DjangoModelFactory
from factory import (
    LazyAttribute,
    Sequence,
)
from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.models import (
    UploadAsyncState,
    ProductLine,
    WorkflowStatusPath,
    WorkflowStatusNode
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julovers.constants import JuloverPageConst
from juloserver.julovers.models import JuloverPage, Julovers

fake = Faker()
fake.add_provider(JuloFakerProvider)


class UploadAsyncStateFactory(DjangoModelFactory):
    class Meta(object):
        model = UploadAsyncState


class JuloverFactory(DjangoModelFactory):
    class Meta(object):
        model = Julovers

    email = Sequence(lambda n: "test.email.%03d@email.com" % n)
    fullname = fake.name()
    address = fake.address()
    dob = date(1996, 10, 3)
    birth_place = fake.address()
    mobile_phone_number = LazyAttribute(lambda o: fake.phone_number())
    gender = random.choice(['Pria', 'Wanita'])
    marital_status = random.choice(['Lajang', 'Menikah', 'Cerai', 'Janda / duda'])
    job_type = random.choice([
        'Freelance', 'Ibu rumah tangga', 'Pengawai negeri', 'Pengawai swasta', 'Pengusaha',
        'Staf rumah tangga', 'Tidak berkerja'
    ])
    job_start = date(2022, 3, 3)
    bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
    bank_account_number = '12342222'
    name_in_bank = 'Nha Ho'
    set_limit = 10000000
    is_sync_application = False


class JuloversProductLineFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductLine

    product_line_code = ProductLineCodes.JULOVER
    product_line_type = 'JULOVER'
    min_amount = 300000
    max_amount = 20000000
    min_duration = 1
    max_duration = 4
    min_interest_rate = 0
    max_interest_rate = 0
    payment_frequency = 'Monthly'


class WorkflowStatusPathFactory(DjangoModelFactory):
    class Meta(object):
        model = WorkflowStatusPath


class WorkflowStatusNodeFactory(DjangoModelFactory):
    class Meta(object):
        model = WorkflowStatusNode

class JuloverPageFactory(DjangoModelFactory):
    class Meta(object):
        model = JuloverPage

    @classmethod
    def email_at_190(cls):
        return cls(
            title=JuloverPageConst.EMAIL_AT_190,
            content='bumder',
            extra_data={'title': "Selamat! J1 JULOvers kamu sudah aktif"},
        )
