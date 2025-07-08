from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from juloserver.account.tests.factories import PartnerFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
)

from .factories import CollectionHiSeasonCampaignFactory


class TestCampaignForm(APITestCase):
    def setUp(self):
        self.client = APIClient()
        group = Group(name="admin_full")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def test_campaign_form_get(self):
        url = '/collection_hi_season/collection_hi_season_campaign_form'
        response = self.client.get(
            url,
        )
        self.assertTemplateUsed(response, "collection_hi_season/campaign_form.html")

    def test_campaign_form_post(self):
        url = '/collection_hi_season/collection_hi_season_campaign_form'
        data = {
            "save_type": "add",
            "csrfmiddlewaretoken": "9CA2YO9YyjkRU6VgWZuOq53P31qbzBaC",
            "campaign_name": "test",
            "payment_terms_criteria": "before",
            "campaign_start_period": "2022-05-30",
            "campaign_end_period": "2022-06-01",
            "due_date_start": "2022-05-31",
            "due_date_end": "2022-06-01",
            "announcement_date": "2022-06-01",
            "dpd": "",
            "start_dpd": "-2",
            "end_dpd": "",
            "eligible_partner_ids": "1, ",
            "exclude_pending_refinancing": "False",
            "prize": "100",
            "in_app_banners": [
                {
                    "id": 0,
                    "due_date": "2022-05-31",
                    "start_showing_on": "2022-05-30",
                    "removed_on": "2022-05-30",
                    "banner_content": "image/html",
                    "banner_url": "collection-hi-season/20225/banner_1.jpg",
                },
                {
                    "id": 0,
                    "due_date": "2022-06-01",
                    "start_showing_on": "2022-05-30",
                    "removed_on": "2022-05-31",
                    "banner_content": "image/html",
                    "banner_url": "collection-hi-season/20225/banner_2.jpg",
                },
            ],
            "on_click_banner": {
                "banner_type": "content_image",
                "banner_content": "",
                "blog_url": "https://www.julo.co.id/",
                "banner_url": "collection-hi-season/20225/banner_3.jpg",
            },
            "campaign_comms": [
                {
                    "comm_settings_id": 0,
                    "type": "email",
                    "pn_title": "",
                    "pn_body": "",
                    "template_code": "collection_high_season",
                    "sent_at_dpd": "-1",
                    "sent_time": "07:00",
                    "email_subject": "helooo julooo",
                    "email_content": '<html> <head> <title>test</title> </head> <body> <h1>hi there its a test </h1> <img src="{{banner_url}}" alt="banner-hi-season-april2021" style="width: 100%"/> <p>Bayar angsuran JULO Anda paling lambat{{payment_terms_date|date:"d-m-Y"}}</p></body></html>',
                    "banners": [
                        {
                            "id": 0,
                            "due_date": "2022-05-31",
                            "sent_on": "2022-05-30",
                            "banner_content": "image/html",
                            "banner_url": "collection-hi-season/20225/banner_5.jpg",
                        },
                        {
                            "id": 0,
                            "due_date": "2022-06-01",
                            "sent_on": "2022-05-31",
                            "banner_content": "image/html",
                            "banner_url": "collection-hi-season/20225/banner_6.jpg",
                        },
                    ],
                },
                {
                    "comm_settings_id": 0,
                    "type": "pn",
                    "email_subject": "",
                    "email_content": "",
                    "pn_title": "Helloooo",
                    "template_code": "collection_high_season",
                    "sent_at_dpd": "-1",
                    "sent_time": "07:00",
                    "pn_body": "test",
                    "banners": [
                        {
                            "id": 0,
                            "due_date": "2022-05-31",
                            "sent_on": "2022-05-30",
                            "banner_content": "image/html",
                            "banner_url": "collection-hi-season/20225/banner_8.jpg",
                        },
                        {
                            "id": 0,
                            "due_date": "2022-06-01",
                            "sent_on": "2022-05-31",
                            "banner_content": "image/html",
                            "banner_url": "collection-hi-season/20225/banner_9.jpg",
                        },
                    ],
                },
            ],
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestAjaxGenerateBannerScheduleHiSeason(APITestCase):
    def setUp(self):
        self.client = APIClient()
        group = Group(name="admin_full")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def test_ajax_generate_banner_schedule_hi_season(self):
        url = '/collection_hi_season/ajax_generate_banner_schedule_hi_season'
        data = {
            "campaign_start_period": "2022-05-30",
            "due_date_start": "2022-05-31",
            "due_date_end": "2022-06-01",
            "start_dpd": "-1",
            "end_dpd": "",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestAjaxGenerateCommsSettingsPartnerFactoryScheduleHiSeason(APITestCase):
    def setUp(self):
        self.client = APIClient()
        group = Group(name="admin_full")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def test_ajax_generate_comms_setting_schedule_hi_season(self):
        url = '/collection_hi_season/ajax_generate_comms_setting_schedule_hi_season'
        data = {
            "due_date_start": "2022-05-31",
            "due_date_end": "2022-06-01",
            "sent_at_dpd": "-1",
            "payment_terms_criteria": "before",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestAjaxUploadBannerHiSeason(APITestCase):
    def setUp(self):
        self.client = APIClient()
        group = Group(name="admin_full")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def test_ajax_upload_banner_hi_season(self):
        data = {
            'banner_image': open(
                settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'
            ),
        }
        url = '/collection_hi_season/ajax_upload_banner_hi_season'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestGetCollectionHiSeasonCampaignList(APITestCase):
    def setUp(self):
        self.client = APIClient()
        group = Group(name="admin_full")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.campaign = CollectionHiSeasonCampaignFactory()
        self.campaign.campaign_status = "active"
        self.campaign.exclude_pending_refinancing = True
        self.campaign.payment_terms = 'before dpd -3'
        self.campaign.eligible_partner_ids = "{1, 2}"
        self.campaign.campaign_start_period = date.today()
        self.campaign.campaign_end_period = self.campaign.campaign_start_period + timedelta(days=17)
        self.campaign.due_date_start = self.campaign.campaign_start_period + timedelta(days=11)
        self.campaign.due_date_end = self.campaign.campaign_start_period + timedelta(days=20)
        self.campaign.save()

    def test_collection_hi_season_campaign_list(self):
        url = '/collection_hi_season/collection_hi_season_campaign_list/'
        response = self.client.get(
            url,
        )
        self.assertTemplateUsed(response, "collection_hi_season/campaign_list.html")


class TestAjaxGetPartnerListHiSeason(APITestCase):
    def setup(self):
        self.client = APIClient()
        self.partner = PartnerFactory()

    def test_ajax_get_partner_list_hi_season(self):
        url = '/collection_hi_season/ajax_get_partner_list_hi_season'
        data = {'partner_name': 'grab'}
        response = self.client.post(url, data=data)
        self.assertIsNotNone(response, "collection_hi_season/campaign_list.html")
