from factory import DjangoModelFactory, LazyAttribute
from faker import Faker
from django.utils.text import slugify

from juloserver.landing_page_api.models import FAQItem, LandingPageSection, LandingPageCareer

fake = Faker()


class FAQItemFactory(DjangoModelFactory):
    class Meta(object):
        model = FAQItem

    title = LazyAttribute(lambda o: fake.sentence(nb_words=5))
    slug = LazyAttribute(lambda o: slugify(fake.sentence(nb_words=3))[0:50])
    rich_text = LazyAttribute(lambda o: fake.paragraph())


class LandingPageSectionFactory(DjangoModelFactory):
    class Meta(object):
        model = LandingPageSection

    name = LazyAttribute(lambda o: fake.bothify(text='name-??????'))
    rich_text = 'rich_text_test'


class LandingPageCareerFactory(DjangoModelFactory):
    class Meta(object):
        model = LandingPageCareer

    title = LazyAttribute(lambda o: fake.sentence())
    category = LazyAttribute(lambda o: fake.sentence(3))
    is_active = True
