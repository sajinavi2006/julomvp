from factory import LazyAttribute
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.entry_limit.models import EntryLevelLimitConfiguration

fake = Faker()


class EntryLevelLimitConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = EntryLevelLimitConfiguration

    version = 1
    customer_category = "julo1"
    is_premium_area = LazyAttribute(lambda o: fake.boolean())
    is_salaried = LazyAttribute(lambda o: fake.boolean())
    min_threshold = LazyAttribute(
        lambda o: fake.pyfloat(positive=True, left_digits=1, right_digits=2)
    )
    max_threshold = LazyAttribute(
        lambda o: fake.pyfloat(positive=True, left_digits=1, right_digits=2)
    )
    application_tags = 'is_mandatory_docs:0'
    entry_level_limit = LazyAttribute(lambda o: fake.pyint())
    action = '106->120'
    product_line_code = 1
    enabled_trx_method = '{3, 4, 6, 7, 8, 1}'
    bypass_ac = LazyAttribute(lambda o: fake.boolean())
    bypass_pva = LazyAttribute(lambda o: fake.boolean())
