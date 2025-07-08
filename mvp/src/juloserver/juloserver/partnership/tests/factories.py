from builtins import object
from factory import LazyAttribute
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.partnership.models import (
    Distributor,
    MerchantDistributorCategory,
    PartnershipType,
    MerchantHistoricalTransaction,
    PartnershipConfig,
    PartnershipApplicationData,
    PartnershipTransaction,
    PartnershipLogRetryCheckTransactionStatus,
    PartnershipUserOTPAction,
    PartnerLoanSimulations,
    PaylaterTransaction,
    CustomerPinVerify,
    PaylaterTransactionDetails,
    PaylaterTransactionStatus,
    PartnerOrigin,
    PartnershipApiLog,
    PaylaterTransactionLoan,
    PartnerLoanRequest,
    PartnershipApplicationFlag,
    PartnershipFlowFlag,
    PartnershipImage,
    PartnershipDocument,
    LivenessResultsMapping,
)

fake = Faker()


class DistributorFactory(DjangoModelFactory):
    class Meta(object):
        model = Distributor


class MerchantDistributorCategoryFactory(DjangoModelFactory):
    class Meta(object):
        model = MerchantDistributorCategory

    category_name = LazyAttribute(lambda o: fake.name())


class PartnershipTypeFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipType

    partner_type_name = LazyAttribute(lambda o: fake.name())


class MerchantHistoricalTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = MerchantHistoricalTransaction


class PartnershipConfigFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipConfig


class PartnershipApplicationDataFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipApplicationData


class PartnershipTransactionFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipTransaction


class PartnershipLogRetryCheckTransactionStatusFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipLogRetryCheckTransactionStatus


class PartnershipUserOTPActionFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipUserOTPAction


class PartnerLoanSimulationsFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerLoanSimulations


class PaylaterTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = PaylaterTransaction


class CustomerPinVerifyFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerPinVerify


class PaylaterTransactionDetailsFactory(DjangoModelFactory):
    class Meta(object):
        model = PaylaterTransactionDetails


class PaylaterTransactionStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = PaylaterTransactionStatus


class PartnerOriginFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerOrigin


class PartnershipApiLogFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipApiLog


class PaylaterTransactionLoanFactory(DjangoModelFactory):
    class Meta(object):
        model = PaylaterTransactionLoan


class PartnerLoanRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerLoanRequest


class PartnershipApplicationFlagFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipApplicationFlag


class PartnershipFlowFlagFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipFlowFlag


class PartnershipImageFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipImage

    application_image_source = 0
    image_type = 'ktp_self'
    image = 'example.com/test.jpg'
    thumbnail_url = 'example.com/thumbnail.jpg'
    service = 'oss'


class PartnershipDocumentFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnershipDocument

    document_source = 0
    document_type = 'cashflow_report'
    file = 'example.com/test.csv'
    service = 'oss'


class LivenessResultsMappingFactory(DjangoModelFactory):
    class Meta(object):
        model = LivenessResultsMapping
