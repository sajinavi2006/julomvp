from django.test.testcases import TestCase
from juloserver.landing_page_api.constants import FAQItemType, CareerExtraDataConst

from juloserver.landing_page_api.models import FAQItem, LandingPageCareer
from juloserver.landing_page_api.tests.factories import FAQItemFactory


class TestFAQItem(TestCase):
    def test_create_no_parent(self):
        data = {
            'title': 'this is title',
            'slug': 'this-is-slug',
            'rich_text': 'rich-text',
        }
        FAQItem.objects.create(**data)
        faq = FAQItem.objects.filter(slug=data['slug']).get()

        self.assertEquals(data['title'], faq.title)
        self.assertEquals(data['slug'], faq.slug)
        self.assertEquals(data['rich_text'], faq.rich_text)
        self.assertEquals(0, faq.order_priority)
        self.assertEquals(True, faq.visible)
        self.assertIsNone(faq.parent)

    def test_create_with_parent_relation(self):
        parent = FAQItemFactory()
        data = {
            'parent': parent,
            'title': 'this is title',
            'slug': 'this-is-slug',
            'rich_text': 'rich-text',
        }
        FAQItem.objects.create(**data)
        faq = FAQItem.objects.filter(slug=data['slug']).get()

        self.assertIsNotNone(faq.parent)
        self.assertEqual(parent.id, faq.parent_id)

    def test_str(self):
        data = {
            'title': 'this is title',
            'slug': 'this-is-slug',
            'rich_text': 'rich-text',
            'type': FAQItemType.SECTION
        }
        faq = FAQItem.objects.create(**data)

        expected = '{} - {} - {}'.format(faq.id, faq.type, faq.title)
        self.assertEquals(expected, str(faq))


class TestFAQItemManager(TestCase):
    def test_find_visible(self):
        visible_faqs = FAQItemFactory.create_batch(size=5, visible=True)
        invisible_faqs = FAQItemFactory.create_batch(size=3, visible=False)

        total = FAQItem.objects.find_visible().count()

        self.assertEqual(len(visible_faqs), total)


class TestLandingPageCareer(TestCase):
    def test_create(self):
        data = {
            'title': 'this-is-title',
            'rich_text': 'this-is-rich-text'
        }
        career = LandingPageCareer.objects.create(**data)

        expected_career = LandingPageCareer.objects.get(title='this-is-title')
        self.assertEqual(career, expected_career)

    def test_get_extra_data(self):
        data = {
            'title': 'this-is-title',
            'rich_text': 'this-is-rich-text',
            'extra_data': {
                CareerExtraDataConst.FIELD_TYPE: 'this-is-type',
                CareerExtraDataConst.FIELD_VACANCY: 'this-is-vacancy',
                CareerExtraDataConst.FIELD_SALARY:  'this-is-salary',
                CareerExtraDataConst.FIELD_EXPERIENCE: 'this-is-experience',
                CareerExtraDataConst.FIELD_LOCATION:  'this-is-location',
            }
        }
        career = LandingPageCareer.objects.create(**data)

        self.assertEqual(career.type, 'this-is-type')
        self.assertEqual(career.vacancy, 'this-is-vacancy')
        self.assertEqual(career.salary, 'this-is-salary')
        self.assertEqual(career.experience, 'this-is-experience')
        self.assertEqual(career.location, 'this-is-location')
