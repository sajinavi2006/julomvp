from django.test import TestCase
from mock import patch

from juloserver.antifraud.constant.call_back import CallBackType
from juloserver.antifraud.tasks.call_back_related import hit_anti_fraud_call_back_async
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
)
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    StatusLookupFactory,
    ProductLineFactory,
)


class TestInsertFraudApplicationBucketByAntifraudCallBack(TestCase):
    def setUp(self):
        self.product_line_j1 = ProductLineFactory()
        self.product_line_j1.product_line_code = ProductLineCodes.J1

        self.product_line_grab = ProductLineFactory()
        self.product_line_grab.product_line_code = ProductLineCodes.GRAB1

        self.application_j1 = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=115),
        )
        self.application_j1.product_line = self.product_line_j1
        self.application_j1.save()

        self.application_grab = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=115),
        )
        self.application_grab.product_line = self.product_line_grab
        self.application_grab.application_status = StatusLookupFactory(status_code=106)
        self.application_grab.save()

    @patch('juloserver.antifraud.services.call_back.hit_anti_fraud_call_back')
    def test_hit_web_hook_with_j1_application(self, mock_hit_anti_fraud_call_back):
        status_115 = str(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS)
        hit_anti_fraud_call_back_async(
            CallBackType.MOVE_APPLICATION_STATUS, self.application_j1.id, status_115
        )

        mock_hit_anti_fraud_call_back.assert_called_once_with(
            CallBackType.MOVE_APPLICATION_STATUS, self.application_j1.id, status_115
        )

    @patch('juloserver.antifraud.services.call_back.hit_anti_fraud_call_back')
    def test_hit_web_hook_with_non_j1_application(self, mock_hit_anti_fraud_call_back):
        status_115 = str(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS)
        hit_anti_fraud_call_back_async(
            CallBackType.MOVE_APPLICATION_STATUS, self.application_grab.id, status_115
        )

        mock_hit_anti_fraud_call_back.assert_not_called()
