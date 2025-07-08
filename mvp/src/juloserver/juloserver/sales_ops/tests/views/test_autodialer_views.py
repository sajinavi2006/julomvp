import json
from unittest.mock import (
    patch,
)

from django.core.urlresolvers import reverse
from django.http import JsonResponse
from django.test import TestCase, RequestFactory

from juloserver.julo.models import AutodialerSession
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    StatusLookupFactory,
)
from juloserver.portal.object.dashboard.views import (
    ajax_get_application_autodialer, ajax_autodialer_session_status,
    ajax_autodialer_history_record,
)


@patch('juloserver.portal.object.dashboard.views.sales_ops_crm_views')
@patch('juloserver.portal.object.dashboard.views.sales_ops_autodialer_services')
class TestDashboardAjaxGetApplicationAutodialer(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.user = AuthUserFactory()

    def test_handler_is_called(self, mock_sales_ops_autodialer_services, mock_sales_ops_crm_views):
        mock_sales_ops_autodialer_services.is_sales_ops_autodialer_option.return_value = True
        mock_sales_ops_crm_views.ajax_get_application_autodialer.return_value = \
            JsonResponse({'status': 'success'})

        url = reverse('dashboard:ajax_get_application_autodialer')
        data = {'options': 'sales_ops:bucket'}
        request = self.request_factory.get(url, data)
        request.user = self.user
        response = ajax_get_application_autodialer(request)

        self.assertEqual({'status': 'success'}, json.loads(response.content))
        mock_sales_ops_autodialer_services.is_sales_ops_autodialer_option.assert_called_once_with(
                'sales_ops:bucket')
        mock_sales_ops_crm_views.ajax_get_application_autodialer.assert_called_once_with(request)

    def test_handler_is_not_called(self, mock_sales_ops_autodialer_services, mock_sales_ops_crm_views):
        mock_sales_ops_autodialer_services.is_sales_ops_autodialer_option.return_value = False

        url = reverse('dashboard:ajax_get_application_autodialer')
        data = {'options': '141.j1'}
        request = self.request_factory.get(url, data)
        request.user = self.user
        ajax_get_application_autodialer(request)

        mock_sales_ops_autodialer_services.is_sales_ops_autodialer_option.assert_called_once_with(
                '141')
        mock_sales_ops_crm_views.handler_ajax_get_application_autodialer.assert_not_called()


@patch('juloserver.portal.object.dashboard.views.sales_ops_crm_views')
class TestDashboardAjaxAutodialerSessionStatus(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.user = AuthUserFactory()

    def test_if_handler_is_called(self, mock_sales_ops_crm_views):
        mock_sales_ops_crm_views.ajax_autodialer_session_status.return_value = \
            JsonResponse({'status': 'success'})

        url = reverse('dashboard:ajax_autodialer_session_status')
        data = {'object_type': 'sales_ops', 'object_id': '1'}
        request = self.request_factory.post(url, data)
        request.user = self.user
        response = ajax_autodialer_session_status(request)

        self.assertEqual({'status': 'success'}, json.loads(response.content))
        mock_sales_ops_crm_views.ajax_autodialer_session_status.assert_called_once_with(request)

    def test_if_handler_is_not_called(self, mock_sales_ops_crm_views):
        application = ApplicationFactory()
        url = reverse('dashboard:ajax_autodialer_session_status')
        data = {
            'object_type': 'application',
            'object_id': f'{application.id}',
            'session_start': '1',
        }
        request = self.request_factory.post(url, data)
        request.user = self.user
        response = ajax_autodialer_session_status(request)

        self.assertEqual({
            "status": "success",
            "message": "berhasil rekam autodialer session"
        }, json.loads(response.content))
        mock_sales_ops_crm_views.ajax_autodialer_session_status.assert_not_called()


@patch('juloserver.portal.object.dashboard.views.sales_ops_crm_views')
class TestDashboardAjaxAutodialerHistoryRecord(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.user = AuthUserFactory()

    def test_if_handler_is_called(self, mock_sales_ops_crm_views):
        mock_sales_ops_crm_views.ajax_autodialer_history_record.return_value = \
            JsonResponse({'status': 'success'})

        url = reverse('dashboard:ajax_autodialer_history_record')
        data = {
            'object_type': 'sales_ops',
            'action': 'action',
            'object_id': '1',
        }
        request = self.request_factory.post(url, data)
        request.user = self.user
        response = ajax_autodialer_history_record(request)

        self.assertEqual({'status': 'success'}, json.loads(response.content))
        mock_sales_ops_crm_views.ajax_autodialer_history_record.assert_called_once_with(request)

    def test_if_handler_is_not_called(self, mock_sales_ops_crm_views):
        application = ApplicationFactory()
        AutodialerSession.objects.create(application=application,
                                         status=application.application_status_id)
        url = reverse('dashboard:ajax_autodialer_history_record')
        data = {
            'object_type': 'application',
            'action': 'action',
            'object_id': f'{application.id}',
        }
        request = self.request_factory.post(url, data)
        request.user = self.user
        response = ajax_autodialer_history_record(request)

        self.assertEqual({
                "status": "success",
                "message": "berhasil rekam autodialer activity history"
            }, json.loads(response.content))
        mock_sales_ops_crm_views.ajax_autodialer_history_record \
            .assert_not_called()
