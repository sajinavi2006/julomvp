import datetime
from datetime import datetime
from unittest.mock import patch

from django.conf import settings
from django.core.urlresolvers import reverse
from django.db.models import signals
from django.test import TestCase
from django.utils import timezone
from factory import Iterator, django

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    AuthUserFactory,
    AutodialerSessionFactory,
    FeatureSettingFactory,
    PredictiveMissedCallFactory,
    SkiptraceFactory,
    StatusLookupFactory,
    ApplicationHistoryFactory,
    CustomerFactory,
    LoanFactory,
)
from django.contrib.auth.models import Group

PACKAGE_NAME = 'juloserver.portal.object.dashboard.views'


class TestAjaxGetApplicationAutodialer(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    @django.mute_signals(signals.pre_save)
    def test_fifo_uncalled_app(self):
        applications = ApplicationFactory.create_batch(
            size=5, application_status=StatusLookupFactory(status_code=124)
        )
        for application in applications:
            SkiptraceFactory(
                application=application, contact_source='mobile_phone_1', phone_number='123'
            )

        with patch.object(timezone, 'now') as mock_now:
            map_cdate = {
                applications[0].id: datetime(2022, 2, 12),
                applications[1].id: datetime(2022, 2, 10),
                applications[2].id: datetime(2022, 2, 13),
                applications[3].id: datetime(2022, 2, 9),
                applications[4].id: datetime(2022, 2, 14),
            }
            for application in applications:
                mock_now.return_value = map_cdate[application.id]
                ApplicationHistoryFactory(
                    application_id=application.id, status_old=105, status_new=124
                )

        data = {'options': '124'}
        url = reverse('dashboard:ajax_get_application_autodialer')
        response = self.client.get(url, data)
        resp_json = response.json()

        self.assertEqual('success', resp_json.get('status'), resp_json)
        self.assertEqual(applications[3].id, resp_json.get('object_id'), resp_json)

    @django.mute_signals(signals.pre_save)
    def test_uncalled_and_recalled_app(self):
        prev_2_hours = timezone.now() - timezone.timedelta(hours=2)
        uncalled_apps = ApplicationFactory.create_batch(
            size=2, application_status=StatusLookupFactory(status_code=124)
        )
        recalled_apps = ApplicationFactory.create_batch(
            2, application_status=StatusLookupFactory(status_code=124)
        )
        sessions = AutodialerSessionFactory.create_batch(
            2,
            application=Iterator(recalled_apps),
            next_session_ts=Iterator(
                [
                    prev_2_hours + timezone.timedelta(minutes=1),
                    prev_2_hours + timezone.timedelta(minutes=2),
                ]
            ),
        )

        with patch.object(timezone, 'now') as mock_now:
            map_cdate = {
                uncalled_apps[0].id: datetime(2022, 2, 10),
                uncalled_apps[1].id: datetime(2022, 2, 11),
            }
            for application in uncalled_apps:
                mock_now.return_value = map_cdate[application.id]
                ApplicationHistoryFactory(
                    application_id=application.id, status_old=105, status_new=124
                )

        data = {'options': '124'}
        url = reverse('dashboard:ajax_get_application_autodialer')
        response = self.client.get(url, data)
        resp_json = response.json()

        self.assertEqual('success', resp_json.get('status'), resp_json)
        self.assertEqual(recalled_apps[0].id, resp_json.get('object_id'), resp_json)

        next_2_hours = timezone.now() + timezone.timedelta(hours=2)
        sessions[0].update_safely(next_session_ts=next_2_hours)
        response = self.client.get(url, data)
        resp_json = response.json()
        self.assertEqual(recalled_apps[1].id, resp_json.get('object_id'), resp_json)

        sessions[1].update_safely(next_session_ts=next_2_hours)
        response = self.client.get(url, data)
        resp_json = response.json()
        self.assertEqual(uncalled_apps[0].id, resp_json.get('object_id'), resp_json)

        AutodialerSessionFactory(application=uncalled_apps[0], next_session_ts=next_2_hours)
        response = self.client.get(url, data)
        resp_json = response.json()
        self.assertEqual(uncalled_apps[1].id, resp_json.get('object_id'), resp_json)

    @django.mute_signals(signals.pre_save)
    def test_no_application_and_inactive_autodialer_logic(self):
        next_2_hours = timezone.now() + timezone.timedelta(hours=2)
        recalled_apps = ApplicationFactory.create_batch(
            2, application_status=StatusLookupFactory(status_code=124)
        )
        sessions = AutodialerSessionFactory.create_batch(
            2, application=Iterator(recalled_apps), next_session_ts=next_2_hours
        )
        FeatureSettingFactory(feature_name=FeatureNameConst.AUTODIALER_LOGIC, is_active=False)
        data = {'options': '124'}
        url = reverse('dashboard:ajax_get_application_autodialer')
        response = self.client.get(url, data)
        resp_json = response.json()

        self.assertEqual('failed', resp_json.get('status'), resp_json)
        self.assertEqual('tidak ada aplikasi yang tersedia', resp_json.get('message'), resp_json)

    @django.mute_signals(signals.pre_save)
    def test_no_application_and_active_autodialer_logic(self):
        next_2_hours = timezone.now() + timezone.timedelta(hours=2)
        next_3_hours = timezone.now() + timezone.timedelta(hours=3)
        recalled_apps = ApplicationFactory.create_batch(
            2, application_status=StatusLookupFactory(status_code=124)
        )
        sessions = AutodialerSessionFactory.create_batch(
            2,
            status=124,
            application=Iterator(recalled_apps),
            next_session_ts=Iterator([next_2_hours, next_3_hours]),
        )
        FeatureSettingFactory(feature_name=FeatureNameConst.AUTODIALER_LOGIC, is_active=True)

        data = {'options': '124'}
        url = reverse('dashboard:ajax_get_application_autodialer')
        response = self.client.get(url, data)
        resp_json = response.json()

        self.assertEqual('success', resp_json.get('status'), resp_json)
        self.assertEqual(recalled_apps[0].id, resp_json.get('object_id'), resp_json)

        sessions[0].update_safely(next_session_ts=next_2_hours + timezone.timedelta(hours=2))
        response = self.client.get(url, data)
        resp_json = response.json()

        self.assertEqual('success', resp_json.get('status'), resp_json)
        self.assertEqual(recalled_apps[1].id, resp_json.get('object_id'), resp_json)

    @django.mute_signals(signals.pre_save)
    def test_recalled_app_next_status(self):
        next_2_hours = timezone.now() + timezone.timedelta(hours=2)
        prev_2_hours = timezone.now() - timezone.timedelta(hours=2)
        recalled_app = ApplicationFactory(application_status=StatusLookupFactory(status_code=124))
        current_session = AutodialerSessionFactory(
            application=recalled_app, status=124, next_session_ts=next_2_hours
        )
        prev_session = AutodialerSessionFactory(
            application=recalled_app, status=122, next_session_ts=prev_2_hours
        )

        data = {'options': '124'}
        url = reverse('dashboard:ajax_get_application_autodialer')
        response = self.client.get(url, data)
        resp_json = response.json()

        self.assertEqual('failed', resp_json.get('status'), resp_json)

    @django.mute_signals(signals.pre_save)
    def test_recalled_app_122_feature_active(self):
        prev_2_hours = timezone.now() - timezone.timedelta(hours=2)
        recalled_app = ApplicationFactory(application_status=StatusLookupFactory(status_code=122))
        current_session = AutodialerSessionFactory(
            application=recalled_app, status=122, next_session_ts=prev_2_hours
        )
        FeatureSettingFactory(feature_name=FeatureNameConst.AUTO_CALL_PING_122, is_active=True)

        data = {'options': '122'}
        url = reverse('dashboard:ajax_get_application_autodialer')
        response = self.client.get(url, data)
        resp_json = response.json()

        self.assertEqual('success', resp_json.get('status'), resp_json)


class TestCSAdmin(TestCase):
    def setUp(self):
        group = Group(name="cs_admin")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.user.groups.add(group)

        self.client.force_login(self.user)

    def test_dashboard_cs_admin_get(self):
        url = '/dashboard/cs_admin_dashboard/'
        response = self.client.get(
            url,
        )
        redirected_url = settings.CRM_BASE_URL
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, redirected_url, fetch_redirect_response=False)

    def test_dashboard_cs_admin_post(self):
        self.loan = LoanFactory()
        self.loan.loan_status_id = 237
        self.loan.save()
        url = '/dashboard/cs_admin_dashboard/'
        data = {"application_id": self.application.pk}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 405)
