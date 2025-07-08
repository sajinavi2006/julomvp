from django.test import TestCase
from django.core.urlresolvers import reverse

from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.landing_page_api.constants import FAQItemType
from juloserver.landing_page_api.models import (
    LandingPageSection,
    LandingPageCareer,
    FAQItem,
)
from juloserver.landing_page_api.tests.factories import (
    LandingPageSectionFactory,
    LandingPageCareerFactory,
    FAQItemFactory,
)


class TestFAQItemAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_list(self):
        FAQItemFactory.create_batch(10)
        url = reverse('admin:landing_page_api_faqitem_changelist')
        res = self.client.get(url)

        self.assertContains(res, '10 faq item')

    def test_get_add(self):
        url = reverse('admin:landing_page_api_faqitem_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')

    def test_post_add(self):
        url = reverse('admin:landing_page_api_faqitem_add')
        post_data = {
            'type': FAQItemType.SECTION,
            'slug': 'test-title',
            'title': 'test-title',
            'rich_text': 'test-rich-text',
            'order_priority': 1,
            'visible': 0
        }
        res = self.client.post(url, post_data)

        expected_faq = FAQItem.objects.get(title='test-title')
        self.assertIsNotNone(expected_faq)
        self.assertEqual(expected_faq.title, 'test-title')

    def test_get_change(self):
        faq_item = FAQItemFactory(title='test-title', rich_text='test-rich-text')
        url = reverse('admin:landing_page_api_faqitem_change', args=[faq_item.id])
        res = self.client.get(url)

        self.assertContains(res, 'test-title')
        self.assertContains(res, 'test-rich-text')
        self.assertContains(res, 'Save')

    def test_post_change(self):
        section = FAQItemFactory(title='test-title', rich_text='test-rich-text')
        url = reverse('admin:landing_page_api_faqitem_change', args=[section.id])

        post_data = {
            'type': FAQItemType.SECTION,
            'slug': 'new-test-title',
            'title': 'new-test-title',
            'rich_text': 'new-test-rich-text',
            'order_priority': 1,
            'visible': 0
        }
        res = self.client.post(url, post_data)

        expected_faq = FAQItem.objects.get(title='new-test-title')
        self.assertIsNotNone(expected_faq)
        self.assertEqual(expected_faq.title, 'new-test-title')

    def test_get_delete(self):
        faq_item = FAQItemFactory()
        url = reverse('admin:landing_page_api_faqitem_delete', args=[faq_item.id])
        res = self.client.get(url)

        self.assertContains(res, f'faq item "{faq_item}"')
        self.assertContains(res, 'Yes')

    def test_post_delete(self):
        faq_item = LandingPageSectionFactory()
        url = reverse('admin:landing_page_api_faqitem_delete', args=[faq_item.id])
        res = self.client.post(url, {'post': 'yes'})

        with self.assertRaises(FAQItem.DoesNotExist):
            FAQItem.objects.get(id=faq_item.id)

    def test_section_select_box(self):
        FAQItemFactory(title='this-is-section', type=FAQItemType.SECTION)
        FAQItemFactory(title='this-is-question', type=FAQItemType.QUESTION)
        url = reverse('admin:landing_page_api_faqitem_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')
        self.assertContains(res, 'this-is-section')
        self.assertNotContains(res, 'this-is-question')


class TestLandingPageSectionAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_list(self):
        LandingPageSectionFactory.create_batch(10)
        url = reverse('admin:landing_page_api_landingpagesection_changelist')
        res = self.client.get(url)

        self.assertContains(res, '10 landing page sections')

    def test_get_add(self):
        url = reverse('admin:landing_page_api_landingpagesection_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')

    def test_post_add(self):
        url = reverse('admin:landing_page_api_landingpagesection_add')
        post_data = {
            'name': 'test-name',
            'rich_text': 'test-rich-text'
        }
        res = self.client.post(url, post_data)

        expected_section = LandingPageSection.objects.get(name='test-name')
        self.assertIsNotNone(expected_section)
        self.assertEqual(expected_section.name, 'test-name')

    def test_get_change(self):
        section = LandingPageSectionFactory(name='test-name', rich_text='test-rich-text')
        url = reverse('admin:landing_page_api_landingpagesection_change', args=[section.id])
        res = self.client.get(url)

        self.assertContains(res, 'test-name')
        self.assertContains(res, 'test-rich-text')
        self.assertContains(res, 'Save')

    def test_post_change(self):
        section = LandingPageSectionFactory(name='test-name', rich_text='test-rich-text')
        url = reverse('admin:landing_page_api_landingpagesection_change', args=[section.id])

        post_data = {
            'name': 'new-test-name',
            'rich_text': 'new-test-rich-text'
        }
        res = self.client.post(url, post_data)

        expected_section = LandingPageSection.objects.get(id=section.id)
        self.assertEqual(expected_section.name, 'new-test-name')
        self.assertEqual(expected_section.rich_text, 'new-test-rich-text')

    def test_get_delete(self):
        section = LandingPageSectionFactory()
        url = reverse('admin:landing_page_api_landingpagesection_delete', args=[section.id])
        res = self.client.get(url)

        self.assertContains(res, f'landing page section "{section.id}"')
        self.assertContains(res, 'Yes')

    def test_post_delete(self):
        section = LandingPageSectionFactory()
        url = reverse('admin:landing_page_api_landingpagesection_delete', args=[section.id])
        res = self.client.post(url, {'post': 'yes'})

        with self.assertRaises(LandingPageSection.DoesNotExist):
            LandingPageSection.objects.get(id=section.id)


class TestLandingPageCareerAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_list(self):
        LandingPageCareerFactory.create_batch(10)
        url = reverse('admin:landing_page_api_landingpagecareer_changelist')
        res = self.client.get(url)

        self.assertContains(res, '10 landing page careers')

    def test_get_add(self):
        url = reverse('admin:landing_page_api_landingpagecareer_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')
        self.assertContains(res, 'Vacancy')
        self.assertContains(res, 'Type')
        self.assertContains(res, 'Salary')
        self.assertContains(res, 'Experience')
        self.assertContains(res, 'Location')

    def test_post_add(self):
        url = reverse('admin:landing_page_api_landingpagecareer_add')
        post_data = {
            'title': 'test-title',
            'category': 'test-category',
            'skills': 'test-skill1,test-skill2',
            'is_active': False,
            'published_date': '2021-10-10 10:11:12',
            'rich_text': 'test-rich-text',
            'type': 'test-type',
            'vacancy': 'test-vacancy',
            'experience': 'test-experience',
            'salary': 'test-salary',
            'location': 'test-location',
        }
        res = self.client.post(url, post_data)

        expected_obj = LandingPageCareer.objects.get(title='test-title')
        self.assertIsNotNone(expected_obj)
        self.assertEqual(expected_obj.title, 'test-title')
        self.assertEqual(expected_obj.skills, ['test-skill1', 'test-skill2'])
        self.assertEqual(expected_obj.type, 'test-type')
        self.assertEqual(expected_obj.vacancy, 'test-vacancy')
        self.assertEqual(expected_obj.experience, 'test-experience')
        self.assertEqual(expected_obj.salary, 'test-salary')
        self.assertEqual(expected_obj.location, 'test-location')

    def test_get_change(self):
        initial_data = {
            'title': 'test-title',
            'category': 'test-category',
            'skills': ['test-skill1', 'test-skill2'],
            'is_active': False,
            'published_date': '2021-10-10 10:11:12',
            'rich_text': 'test-rich-text',
            'extra_data': {
                'type': 'test-type',
                'vacancy': 'test-vacancy',
                'experience': 'test-experience',
                'salary': 'test-salary',
                'location': 'test-location',
            }
        }
        obj = LandingPageCareerFactory(**initial_data)
        url = reverse('admin:landing_page_api_landingpagecareer_change', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, 'test-title')
        self.assertContains(res, 'test-rich-text')
        self.assertContains(res, 'test-experience')
        self.assertContains(res, 'test-vacancy')
        self.assertContains(res, 'test-salary')
        self.assertContains(res, 'test-location')
        self.assertContains(res, 'test-type')
        self.assertContains(res, 'test-skill1,test-skill2')
        self.assertContains(res, 'Save')

    def test_post_change(self):
        initial_data = {
            'title': 'test-title',
            'category': 'test-category',
            'skills': ['test-skill1', 'test-skill2'],
            'is_active': False,
            'published_date': '2021-10-10 10:11:12',
            'rich_text': 'test-rich-text',
            'extra_data': {
                'type': 'test-type',
                'vacancy': 'test-vacancy',
                'experience': 'test-experience',
                'salary': 'test-salary',
                'location': 'test-location',
            }
        }
        obj = LandingPageCareerFactory(**initial_data)
        url = reverse('admin:landing_page_api_landingpagecareer_change', args=[obj.id])

        post_data = {
            'title': 'new-test-title',
            'rich_text': 'new-test-rich-text',
            'type': 'new-test-type',
            'vacancy': 'new-test-vacancy',
            'experience': 'new-test-experience',
            'salary': 'new-test-salary',
            'location': 'new-test-location',
        }
        res = self.client.post(url, post_data)

        expected_obj = LandingPageCareer.objects.get(id=obj.id)
        self.assertEqual(expected_obj.title, 'new-test-title')
        self.assertEqual(expected_obj.rich_text, 'new-test-rich-text')
        self.assertEqual(expected_obj.type, 'new-test-type')
        self.assertEqual(expected_obj.vacancy, 'new-test-vacancy')
        self.assertEqual(expected_obj.experience, 'new-test-experience')
        self.assertEqual(expected_obj.salary, 'new-test-salary')
        self.assertEqual(expected_obj.location, 'new-test-location')

    def test_get_delete(self):
        obj = LandingPageCareerFactory()
        url = reverse('admin:landing_page_api_landingpagecareer_delete', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, f'landing page career "{obj.id}"')
        self.assertContains(res, 'Yes')

    def test_post_delete(self):
        obj = LandingPageCareerFactory()
        url = reverse('admin:landing_page_api_landingpagecareer_delete', args=[obj.id])
        res = self.client.post(url, {'post': 'yes'})

        with self.assertRaises(LandingPageCareer.DoesNotExist):
            LandingPageCareer.objects.get(id=obj.id)
