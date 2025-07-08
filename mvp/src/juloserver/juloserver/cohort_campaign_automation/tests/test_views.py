import mock
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from django.contrib.auth.models import Group
from django.core.urlresolvers import reverse
from factory import Iterator
from django.http import HttpResponseRedirect
from django.conf import settings
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.cohort_campaign_automation.tests.factories import (
    CollectionCohortCampaignAutomationFactory,
    CollectionCohortCampaignEmailTemplateFactory,
)
from juloserver.cohort_campaign_automation.models import CollectionCohortCampaignAutomation


class TestCreateCohortCampaignAutomation(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=JuloUserRoles.COHORT_CAMPAIGN_EDITOR)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.now = timezone.localtime(timezone.now())
        self.until = self.now + timedelta(days=10)
        self.start_str = self.now.strftime('%Y-%m-%d %H:%M:%S')
        self.end_str = self.until.strftime('%Y-%m-%d %H:%M:%S')
        self.campaigin_automation = CollectionCohortCampaignAutomationFactory(
            campaign_name='campaign_automation_test'
        )
        self.payload = {
            'campaign_name': 'campaign_automation_test1',
            'start_date': self.start_str,
            'end_date': self.end_str,
            'program_type': 'R4',
            'principal_waiver_percentage': '10',
            'interest_waiver_percentage': '100',
            'late_fee_waiver_percentage': '100',
            'metabase_link': 'http://localhost:8000/cohort-campaign-automation/create/',
            'waiting_approval': False,
            'template_code_email': 'testing_email',
            'subject_email': 'subject',
            'body_email': '<p>body email</p>',
            'show_expiry': 'true',
            'whatsapp_numbers': '082121111',
            'template_code_pn': 'testing_pn',
            'title_pn': 'title',
            'body_pn': 'body pn',
        }

    def test_to_form_creation_page(self):
        response = self.client.get('/cohort-campaign-automation/create/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cohort_campaigin_automation_list_page(self):
        response = self.client.get('/cohort-campaign-automation/list/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_submit_with_get_method(self):
        response = self.client.get('/cohort-campaign-automation/submit/')
        self.assertNotEqual(response.status_code, status.HTTP_200_OK)

    def test_submit_with_exist_campaign_name(self):
        self.payload['campaign_name'] = self.campaigin_automation.campaign_name
        response = self.client.post('/cohort-campaign-automation/submit/', self.payload)
        response_json = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_json['message'], 'Pastikan nama campaign tidak sama dengan campaign yang lain'
        )

    @mock.patch(
        'juloserver.cohort_campaign_automation.views.upload_file_cohort_campaign_automation'
    )
    def test_submit_success(self, upload_banner_mock):
        file_request = (
            open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
        )

        self.payload['banner_email'] = file_request
        self.payload['banner_pn'] = file_request
        response = self.client.post('/cohort-campaign-automation/submit/', self.payload)
        check_data = CollectionCohortCampaignAutomation.objects.get_or_none(
            campaign_name='campaign_automation_test1'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(check_data)
        upload_banner_mock.delay.assert_called()

    def test_submit_success_for_edit(self):
        self.payload['is_edit'] = True
        self.payload['campaign_name'] = 'campaign_automation_test_for_edit'
        self.payload['campaign_id'] = self.campaigin_automation.id
        response = self.client.post('/cohort-campaign-automation/submit/', self.payload)
        check_previously_data = CollectionCohortCampaignAutomation.objects.get_or_none(
            campaign_name='campaign_automation_test1'
        )
        check_data_edited = CollectionCohortCampaignAutomation.objects.get_or_none(
            campaign_name=self.payload['campaign_name']
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(check_previously_data)
        self.assertIsNotNone(check_data_edited)


class TestAjaxCohortCampaignAutomationListView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=JuloUserRoles.COHORT_CAMPAIGN_EDITOR)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.cohort_campaign = CollectionCohortCampaignAutomationFactory.create_batch(
            6, campaign_name=Iterator(['name_1', 'name_2', 'name_3', 'name_4', 'name_5', 'name_6'])
        )

    def test_ajax_cohort_campaign_automation_list_view(self):
        url = reverse('cohort_campaign_automation:cohort_campaign_automation_list')

        params = {
            'max_per_page': 50,
            'page': 1,
        }

        response = self.client.get(url, data=params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestCancelStatusCohortCampaignAutomtion(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=JuloUserRoles.COHORT_CAMPAIGN_EDITOR)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.campaigin_automation = CollectionCohortCampaignAutomationFactory(
            campaign_name='campaign_automation_test_2', status='Failed'
        )
        self.payload = {'campaign_name': self.campaigin_automation.campaign_name}

    def test_cancel_status_cohort_campaign_automtion(self):
        response = self.client.post('/cohort-campaign-automation/cancel/', self.payload)
        self.campaigin_automation.refresh_from_db()
        check_data = CollectionCohortCampaignAutomation.objects.get_or_none(
            campaign_name='campaign_automation_test_2'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(check_data.status, 'Canceled')


class TestEditCohortCampaignAutomationPage(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=JuloUserRoles.COHORT_CAMPAIGN_EDITOR)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.campaign_automation = CollectionCohortCampaignAutomationFactory(
            campaign_name='campaign_automation_test_2'
        )
        self.email_campaign = CollectionCohortCampaignEmailTemplateFactory(
            campaign_automation=self.campaign_automation,
            email_blast_date=timezone.localtime(timezone.now()),
        )
        self.payload = {
            'campaign_name': self.campaign_automation.campaign_name,
        }

    def test_campaign_not_found(self):
        response = self.client.get('/cohort-campaign-automation/edit/campaign_automation_test_3/')
        self.assertIsInstance(response, HttpResponseRedirect)

    def test_success(self):
        response = self.client.get('/cohort-campaign-automation/edit/campaign_automation_test_2/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
