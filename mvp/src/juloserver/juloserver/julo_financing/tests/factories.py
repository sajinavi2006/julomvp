from factory import SubFactory
from factory.django import DjangoModelFactory
from juloserver.julo_financing.models import *
from juloserver.julo.tests.factories import CustomerFactory


class JFinancingCategoryFactory(DjangoModelFactory):
    class Meta(object):
        model = JFinancingCategory

    name = 'smartphone'


class JFinancingProductFactory(DjangoModelFactory):
    class Meta(object):
        model = JFinancingProduct

    name = "product X"
    is_active = True
    price = 100_000
    display_installment_price = 100_000
    j_financing_category = SubFactory(JFinancingCategoryFactory)


class JFinancingCheckoutFactory(DjangoModelFactory):
    class Meta(object):
        model = JFinancingCheckout

    price = 100_000
    loan_duration = 3
    j_financing_product = SubFactory(JFinancingProductFactory)
    customer = SubFactory(CustomerFactory)


class JFinancingVerificationFactory(DjangoModelFactory):
    class Meta(object):
        model = JFinancingVerification


class JFinancingProductSaleTagFactory(DjangoModelFactory):
    class Meta(object):
        model = JFinancingProductSaleTag

    @classmethod
    def best_seller(cls):
        return cls(
            tag_image_url="best_seller.png",
            description="best seller",
            tag_name="best_seller",
            is_active=True,
        )

    @classmethod
    def free_insurance(cls):
        return cls(
            tag_image_url="free_insurance.png",
            description="free_insurance",
            tag_name="free_insurance",
            is_active=True,
        )

    @classmethod
    def free_data_package(cls):
        return cls(
            tag_image_url="free_data.png",
            description="free data",
            tag_name="free_data",
            is_active=True,
        )


class JFinancingProductSaleTagDetailFactory(DjangoModelFactory):
    class Meta(object):
        model = JFinancingProductSaleTagDetail
