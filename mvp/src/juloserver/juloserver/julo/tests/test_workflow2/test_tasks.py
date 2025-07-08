from __future__ import absolute_import
import pytest
from mock import patch
from collections import namedtuple
from django.test.testcases import TestCase
from django.test.utils import override_settings
from juloserver.julo.models import (StatusLookup, ProductLine, Application, AppsFlyerLogs)
from juloserver.julo.workflows2.tasks import appsflyer_update_status_task
from juloserver.julo.tests.factories import (LoanFactory, ApplicationHistoryFactory)

appsflyer_event_response = namedtuple('Response', ['status_code'])

@pytest.mark.django_db
@override_settings(SUSPEND_SIGNALS=True)
class TestTaskUpdateLateFeeAmount(TestCase):
    def setUp(self):
        self.status_220 = StatusLookup.objects.get(status_code=220)
        self.loan = LoanFactory(loan_status=self.status_220)
        self.application = Application.objects.get(id=self.loan.application.id)
        self.application.product_line = ProductLine.objects.get(product_line_code=10)
        self.application.save()

    @patch('juloserver.julo.workflows2.tasks.get_julo_apps_flyer')
    def test_late_fee_update(self, mock_get_julo_apps_flyer):
        ApplicationHistoryFactory(
            application_id=self.application.id, status_old=105, status_new=134)
        mock_get_julo_apps_flyer().post_event.return_value = appsflyer_event_response(
            status_code=200
        )
        appsflyer_update_status_task(self.application.id, 105, status_old=100, status_new=105)
        appsflyer_log = AppsFlyerLogs.objects.filter(application=self.application).last()
        self.assertEqual((appsflyer_log.status_old, appsflyer_log.status_new), (100, 105))
        # without parameter
        appsflyer_update_status_task(self.application.id, 134)
        appsflyer_log = AppsFlyerLogs.objects.filter(application=self.application).last()
        self.assertEqual((appsflyer_log.status_old, appsflyer_log.status_new), (105, 134))
