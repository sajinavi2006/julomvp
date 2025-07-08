from mock import patch
from django.test.testcases import TestCase
from juloserver.julo.services2.fraud_check import check_suspicious_ip
from juloserver.julo.models import VPNDetection
from juloserver.julo.tests.factories import VPNDetectionFactory


class TestFraudCheck(TestCase):
    def setUp(self):
        pass

    @patch('juloserver.julo.services2.fraud_check.ipinfo_client')
    def test_check_suspicious_ip(self, mock_ipinfo_client):
        # is not suspicious ip
        mock_ipinfo_client.get_ip_info_detail.return_value = {'privacy': {'vpn': False}}
        result = check_suspicious_ip('123.456.11.123')
        self.assertEqual(result, False)
        vpn_detect = VPNDetection.objects.filter(ip_address='123.456.11.123').last()
        self.assertIsNotNone(vpn_detect)
        self.assertFalse(vpn_detect.is_vpn_detected)
        # vpn detection is already existed
        result = check_suspicious_ip('123.456.11.123')
        self.assertEqual(result, False)

        # is suspicious ip
        mock_ipinfo_client.get_ip_info_detail.return_value = {'privacy': {'vpn': True}}
        result = check_suspicious_ip('123.456.11.124')
        self.assertEqual(result, True)
        vpn_detect = VPNDetection.objects.filter(ip_address='123.456.11.124').last()
        self.assertTrue(vpn_detect.is_vpn_detected)
