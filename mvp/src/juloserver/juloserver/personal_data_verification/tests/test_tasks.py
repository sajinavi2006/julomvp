import responses
from django.test import TestCase
from django.test.utils import override_settings
from mock import patch

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.personal_data_verification.constants import (
    DukcapilFeatureMethodConst,
    DukcapilResponseSourceConst,
    FeatureNameConst,
)
from juloserver.personal_data_verification.tasks import (
    send_dukcapil_official_callback_data,
)
from juloserver.personal_data_verification.tests.factories import (
    DukcapilResponseFactory,
)


class TestSendDukcapilOfficialCallbackData(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(customer_xid="1234567890")
        self.application = ApplicationFactory(application_xid="123456789", customer=self.customer)
        self.dukcapil_response = DukcapilResponseFactory(
            application=self.application,
            source=DukcapilResponseSourceConst.DIRECT,
            name=True,
            birthplace=True,
            birthdate=True,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={'method': DukcapilFeatureMethodConst.DIRECT, 'minimum_checks_to_pass': 2},
            is_active=True,
        )

    @responses.activate
    def test_feature_not_active(self):
        self.feature_setting.is_active = False
        self.feature_setting.save(update_fields=['is_active'])
        ret_val = send_dukcapil_official_callback_data(self.application.id)
        self.assertFalse(ret_val)

    @responses.activate
    @patch(
        "juloserver.personal_data_verification.services.get_dukcapil_verification_feature",
        return_value=True,
    )
    def test_send_success_callback(self, mock_feature):
        responses.add(
            responses.POST,
            'http://172.16.160.31/databalikan/api/store',
            body='{"message": "Success"}',
            status=200,
        )
        ret_val = send_dukcapil_official_callback_data(self.application.id)
        self.assertTrue(ret_val)

    @responses.activate
    def test_not_eligible_different_source(self):
        self.dukcapil_response.source = DukcapilResponseSourceConst.ASLIRI
        self.dukcapil_response.save(update_fields=['source'])

        ret_val = send_dukcapil_official_callback_data(self.application.id)
        self.assertFalse(ret_val)

    @responses.activate
    def test_not_eligible(self):
        self.dukcapil_response.birthplace = False
        self.dukcapil_response.birthdate = False
        self.dukcapil_response.save(update_fields=['birthplace', 'birthdate'])

        ret_val = send_dukcapil_official_callback_data(self.application.id)
        self.assertFalse(ret_val)

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
    @responses.activate
    def test_called_using_apply_async(self):
        self.feature_setting.is_active = False
        self.feature_setting.save(update_fields=['is_active'])
        async_result = send_dukcapil_official_callback_data.apply_async(args=(self.application.id,))
        self.assertFalse(async_result.get())
