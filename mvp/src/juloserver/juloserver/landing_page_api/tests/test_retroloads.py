from importlib import import_module

from django.test import TestCase

from juloserver.landing_page_api.constants import FAQItemType
from juloserver.landing_page_api.models import FAQItem, LandingPageSection, LandingPageCareer


class TestInitialFaqRetroload(TestCase):
    retroload = import_module(
        '.163349440190__landing_page_api__initial_faq', package='juloserver.retroloads'
    )

    def test_initial_data(self):
        self.retroload.retroload_initial_data(None, None)

        total_section = FAQItem.objects.filter(type=FAQItemType.SECTION).count()
        total_question = FAQItem.objects.filter(type=FAQItemType.QUESTION).count()

        product_section = FAQItem.objects.filter(title='Produk').get()
        total_product_question = FAQItem.objects.filter(parent=product_section).count()

        self.assertEqual(total_section, 6)
        self.assertEqual(total_question, 41)
        self.assertEqual(total_product_question, 21)


class TestInitialCareerRetroload(TestCase):
    retroload = import_module(
        '.163515813827__landing_page_api__initial_data_for_career', package='juloserver.retroloads'
    )

    def test_init_career_page_data(self):
        self.retroload.init_career_page_data(None, None)
        total_engineering = LandingPageCareer.objects.filter(category='Engineering').count()
        total_data = LandingPageCareer.objects.filter(category='Data').count()
        total_product = LandingPageCareer.objects.filter(category='Product').count()

        self.assertEqual(12, total_engineering)
        self.assertEqual(4, total_data)
        self.assertEqual(5, total_product)

    def test_init_career_section_data(self):
        self.retroload.init_career_section_data(None, None)
        benefit_section = LandingPageSection.objects.get(name='career_benefit')
        culture_section = LandingPageSection.objects.get(name='career_culture')

        self.assertIsNotNone(benefit_section)
        self.assertIsNotNone(culture_section)
