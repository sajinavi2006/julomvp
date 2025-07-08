from builtins import object
from factory.django import DjangoModelFactory
from factory import SubFactory

from juloserver.ecommerce.models import (
    EcommerceBankConfiguration,
    EcommerceConfiguration,
    IpriceTransaction,
    JuloShopTransaction,
)

from juloserver.julo.tests.factories import (
    CustomerFactory,
    LoanFactory,
    ApplicationFactory,
)


class EcommerceConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = EcommerceConfiguration

    ecommerce_name = 'Toko online'
    selection_logo = 'http://localhost:8000/static_test/group_14646.png'
    background_logo = 'http://localhost:8000/static_test/group_14645.png'
    color_scheme = '#00FF00'
    url = 'https://toko_online.com'
    text_logo = 'http://localhost:8000/static_test/group_14644.png'


class EcommerceBankConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = EcommerceBankConfiguration


class IpriceTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = IpriceTransaction

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    iprice_order_id = 129847
    admin_fee = 2000
    iprice_total_amount = 200000


class JuloShopTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = JuloShopTransaction

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    loan = SubFactory(LoanFactory)
    seller_name = 'jd.id'
    product_total_amount = 100000
    transaction_total_amount = 100000
    admin_fee = 0
