from django.test import TestCase
from factory import Iterator

from juloserver.julo.services2.device_ip_history import get_application_submission_ip_history
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    DeviceIpHistoryFactory,
)


class TestGetApplicationSubmissionIpHistory(TestCase):
    def test_return_none(self):
        DeviceIpHistoryFactory(path='/api/v2/application/123123')
        application = ApplicationJ1Factory()

        ret_val = get_application_submission_ip_history(application)
        self.assertIsNone(ret_val)

    def test_success(self):
        application = ApplicationJ1Factory()
        DeviceIpHistoryFactory.create_batch(
            3,
            ip_address=Iterator(['192.168.0.1', '192.168.0.1']),
            customer=application.customer,
            path=Iterator(['/api/v3/application/{}/'.format(application.id), '/api/v2/homescreen/combined'])
        )

        ret_val = get_application_submission_ip_history(application)
        self.assertEqual('192.168.0.1', ret_val.ip_address)
