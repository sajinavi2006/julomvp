
from juloserver.sdk.tests.factories import AxiataCustomerDataFactory
from factory import DjangoModelFactory
from factory.declarations import SubFactory

from juloserver.julo.tests.factories import CustomerFactory
from juloserver.merchant_financing.models import ApplicationSubmission, Merchant
from juloserver.partnership.models import (
    MasterPartnerConfigProductLookup, HistoricalPartnerConfigProductLookup,
)

class MerchantFactory(DjangoModelFactory):
    class Meta(object):
        model = Merchant

    customer = SubFactory(CustomerFactory)

class ApplicationSubmissionFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationSubmission

    axiata_customer_data = SubFactory(AxiataCustomerDataFactory)


class MasterPartnerConfigProductLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = MasterPartnerConfigProductLookup


class HistoricalPartnerConfigProductLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = HistoricalPartnerConfigProductLookup
