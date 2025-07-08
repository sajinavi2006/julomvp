from builtins import object
import pytest
import random
import string

from datetime import datetime
from factory.django import DjangoModelFactory
from django.conf import settings
from django.utils import timezone
from factory import LazyAttribute
from factory import SubFactory
from faker import Faker
from mock import patch

from juloserver.portal.object.product_profile.services import generate_product_lookup
from juloserver.portal.object.product_profile.services import generate_rate
from juloserver.julo.models import ProductProfile
from juloserver.julo.models import ProductLine

fake = Faker()


class ProductProfileFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductProfile

    # code = '10'
    name = 'TPP1',
    min_amount = 1000000
    max_amount = 5000000
    min_duration = 3
    max_duration = 12
    min_interest_rate = 0.02
    max_interest_rate = 0.2
    interest_rate_increment = 0.04
    min_origination_fee = 0.05
    max_origination_fee = 0.1
    origination_fee_increment = 0.03
    payment_frequency = 'Monthly'
    late_fee = 0.00
    cashback_initial = 0.00
    cashback_payment = 0.00
    is_active = True
    debt_income_ratio = 0.1
    # is_lender_exclusive = False
    # is_customer_exclusive = False
    # is_deleted = False
    # partner = None


class ProductLineFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductLine

    product_line_code = '10'
    product_line_type = 'TPP1'
    min_amount = 1000000
    max_amount = 5000000
    min_duration = 3
    max_duration = 12
    min_interest_rate = 0.02
    max_interest_rate = 0.2
    payment_frequency = 'Monthly'
    product_profile = SubFactory(ProductProfileFactory)


class TestFunction(object):

    def test_generate_rate(self):
        test_cases = ((0.01, 0.05, 0.02, [0.01, 0.03, 0.05]),
                     (0.02, 0.24, 0.03, [0.02, 0.05, 0.08, 0.11, 0.14, 0.17, 0.2, 0.23, 0.24]),
                     (0.02, 0.02, 0.00, [0.02])
                    )

        for min_val, max_val, increment_val, expected_list in test_cases:
            rate_list = generate_rate(min_val, max_val, increment_val)
            assert rate_list == expected_list

    def test_should_raise_exception(self):
        with pytest.raises(Exception) as excinfo:
            generate_rate(0.01, 0.02, 0.00)
            assert 'increment value could not greater than max value' == excinfo.value

            generate_rate(0.05, 0.02, 0.01)
            assert 'min value could not greater than max value' == excinfo.value

    # def test_generate_product_lookup(self):
    #     product_profile1 = ProductProfileFactory()
    #     product_line1 = ProductLineFactory()
    #     interest_rate_count = len(generate_rate(0.02, 0.2, 0.04))
    #     origination_fee_count = len(generate_rate(0.05, 0.1, 0.03))
    #     expected_product_lookup_count = interest_rate_count * origination_fee_count

    #     product_lookup_list = generate_product_lookup(product_profile1, product_line1)

    #     assert expected_product_lookup_count == len(product_lookup_list)
