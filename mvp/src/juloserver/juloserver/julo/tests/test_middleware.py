from unittest.mock import (
    patch,
    call,
)

from django.http import JsonResponse
from django.test import TestCase, RequestFactory

from juloserver.julo.middleware import DeviceIpMiddleware
from juloserver.julo.tests.factories import AuthUserFactory

PACKAGE_NAME = 'juloserver.julo.middleware'


@patch(f'{PACKAGE_NAME}.logger')
@patch(f'{PACKAGE_NAME}.capture_device_ip')
class TestDeviceIpMiddleware(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.middleware = DeviceIpMiddleware()
        self.mock_response = JsonResponse({'data': 'response'})
        self.request_factory = RequestFactory()

    @classmethod
    def setUpTestData(cls):
        cls.ip_headers = [
            'HTTP_X_FORWARDED_FOR',
            'REMOTE_ADDR',
            'HTTP_X_REAL_IP',
        ]

    def test_not_valid_path(self, mock_capture_device_ip, mock_logger):
        invalid_paths = [
            '/api/invalid',
            '/api/rest-auth/registration',
            '/api/rest-auth/password',
            '/api/rest-auth/login',
            '/api/auth/v2/login',
            '/api/devices/',
            '/api/first-product-lines',
            '/api/login/',
            '/api/login2/',
            '/api/otp/',
            '/api/registration/',
            '/api/register2/',
        ]
        for path in invalid_paths:
            request = self.request_factory.get(path)
            res = self.middleware.process_response(request, self.mock_response)

            self.assertEqual(self.mock_response, res)
            mock_logger.info.assert_not_called()
            mock_capture_device_ip.delay.assert_not_called()

    def test_valid_path(self, mock_capture_device_ip, mock_logger):
        valid_paths = [
            '/api/v1/some-api',
            '/api/v2/some-api',
            '/api/sdk/some-api'
        ]
        for path in valid_paths:
            request = self.request_factory.get(path)
            request.user = self.user
            res = self.middleware.process_response(request, self.mock_response)

            self.assertEqual(self.mock_response, res)

        self.assertEqual(3, mock_logger.info.call_count)
        self.assertEqual(3, mock_capture_device_ip.delay.call_count)

    def test_check_log_info(self, mock_capture_device_ip, mock_logger):
        path = '/api/v1/some-api'
        request = self.request_factory.get(path)
        request.user = self.user
        res = self.middleware.process_response(request, self.mock_response)

        self.assertEqual(self.mock_response, res)
        calls = [
            call({
                'action': 'call_capture_device_ip',
                'path': path,
                'ip_address': '127.0.0.1',
                'user': self.user,
            }),
        ]
        mock_logger.info.assert_has_calls(calls)
        mock_capture_device_ip.delay.assert_called_once_with(self.user, '127.0.0.1', path)

    def test_no_user(self, mock_capture_device_ip, mock_logger):
        path = '/api/v1/some-api'
        request = self.request_factory.get(path)
        res = self.middleware.process_response(request, self.mock_response)

        self.assertEqual(self.mock_response, res)
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_capture_device_ip.delay.assert_not_called()

    def test_not_valid_response_status(self, mock_capture_device_ip, mock_logger):
        path = '/api/v1/some-api'
        request = self.request_factory.get(path)
        request.user = self.user
        self.mock_response.status_code = 400
        res = self.middleware.process_response(request, self.mock_response)

        self.assertEqual(self.mock_response, res)
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_called_once_with({
            'path': path,
            'response_status': 400,
            'status': 'not_successful_response'
        })
        mock_capture_device_ip.delay.assert_not_called()

    def test_no_address_found(self, mock_capture_device_ip, mock_logger):
        path = '/api/v1/some-api'
        request = self.request_factory.get(path)
        request.user = self.user

        for header in self.ip_headers:
            request.META.pop(header, None)
        res = self.middleware.process_response(request, self.mock_response)

        self.assertEqual(self.mock_response, res)
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_called_once_with({
            'status': 'ip_address is None',
            'path': path,
            'ip_address': None,
            'user': self.user
        })
        mock_capture_device_ip.delay.assert_not_called()

    def test_ip_ordering(self, mock_capture_device_ip, mock_logger):
        path = '/api/v1/some-api'
        request = self.request_factory.get(path)
        request.user = self.user

        request.META['HTTP_X_FORWARDED_FOR'] = '127.0.1.1'
        request.META['REMOTE_ADDR'] = '127.0.1.2'
        request.META['HTTP_X_REAL_IP'] = '127.0.1.3'
        res = self.middleware.process_response(request, self.mock_response)

        calls = [
            call({
                'action': 'call_capture_device_ip',
                'path': path,
                'ip_address': '127.0.1.3',
                'user': self.user,
            }),
        ]
        mock_logger.info.assert_has_calls(calls)

    def test_ip_ordering_with_invalid_ip(self, mock_capture_device_ip, mock_logger):
        path = '/api/v1/some-api'
        request = self.request_factory.get(path)
        request.user = self.user

        request.META['HTTP_X_FORWARDED_FOR'] = '127.0.0.2.invalid'
        request.META['REMOTE_ADDR'] = '127.0.0.1'
        request.META['HTTP_X_REAL_IP'] = '127.0.1.3.invalid'
        res = self.middleware.process_response(request, self.mock_response)

        calls = [
            call(
                {
                    'action': 'call_capture_device_ip',
                    'path': path,
                    'ip_address': '127.0.0.1',
                    'user': self.user,
                }
            ),
        ]
        mock_logger.info.assert_has_calls(calls)

    def test_short_form_application(self, mock_capture_device_ip, mock_logger):
        # list urls called between 100 and 105 in short form
        short_form_routes = [
            '/api/v2/etl/dsd/',
            '/api/liveness-detection/v1/pre-check',
            '/api/v2/mobile/feature-settings?feature_name=mother_maiden_name',
            '/api/application-form/v1/precheck-reapply',
            '/api/v3/product-line/10/dropdown_bank_data?is_show_logo=true',
            '/api/v3/address/provinces',
            '/api/application-form/v1/regions/check?province=provinsi&city=kota&district=kecamatan&sub-district=kelurahan',
            '/api/v1/applications/2000154241/images/?include_deleted=false',
            '/api/face_recognition/v1/selfie/check-upload',
            '/api/liveness-detection/v1/license',
            '/api/liveness-detection/v1/pre-active-check',
            '/api/liveness-detection/v2/active-check',
            '/api/application_flow/v1/get_application_image_url/?image_id=2000154241',
            '/api/v3/termsprivacy',
            '/api/application-form/v1/application/2000154241',
        ]

        for path in short_form_routes:
            request = self.request_factory.get(path)
            request.user = self.user
            res = self.middleware.process_response(request, self.mock_response)
            self.assertEqual(self.mock_response, res)

        self.assertEqual(15, mock_logger.info.call_count)
        self.assertEqual(15, mock_capture_device_ip.delay.call_count)

    def test_long_form_application(self, mock_capture_device_ip, mock_logger):

        # list urls called between 100 and 105 in long form
        long_form_routes = [
            '/api/customer-module/v1/user-config?app_version=7.0.0',
            '/api/application_flow/v1/longform/settings',
            '/api/v1/applications',
            '/api/customer-module/v2/update-analytics-data',
            '/api/v2/mobile/feature-settings?feature_name=form_selfie',
            '/api/v2/mobile/check-payslip-mandatory/2000154241',
            '/api/v3/appsflyer',
            '/api/v1/applications/2000154241/images/?include_deleted=false',
            '/api/liveness-detection/v1/pre-check',
            '/api/liveness-detection/v1/pre-active-check',
            '/api/v2/etl/dsd/',
            '/api/ocr/v2/setting/ocr_timeout',
            '/api/ocr/v3/ktp/',
            '/api/ocr/v2/ktp/submit/',
            '/api/v2/mobile/feature-settings?feature_name=mother_maiden_name',
            '/api/v2/mobile/feature-settings?feature_name=set_birth_place_required',
            '/api/face_recognition/selfie/check-upload',
            '/api/liveness-detection/v1/license',
            '/api/application_flow/v1/get_application_image_url/?image_id=2000154241',
            '/api/v3/address/provinces',
            '/api/v3/address/districts',
            '/api/v3/address/subdistricts',
            '/api/otp/v1/request',  # this souldn't be counted
            '/api/v3/product-line/10/dropdown_bank_data?is_show_logo=true',
            '/api/v2/mobile/feature-settings?feature_name=boost',
            '/api/v3/booster/status/2000154241/',
            '/api/v3/termsprivacy',
            '/api/v3/application/2000154241'
            '/api/v2/mobile/feature-settings?feature_name=saving_information_page',
        ]

        for path in long_form_routes:
            request = self.request_factory.get(path)
            request.user = self.user
            res = self.middleware.process_response(request, self.mock_response)
            self.assertEqual(self.mock_response, res)

        self.assertEqual(27, mock_logger.info.call_count)
        self.assertEqual(27, mock_capture_device_ip.delay.call_count)
