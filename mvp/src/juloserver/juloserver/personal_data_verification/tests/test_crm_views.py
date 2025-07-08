from django.contrib.auth.models import Group
from django.test import TestCase

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    AuthUserFactory,
    FeatureSettingFactory,
)
from juloserver.personal_data_verification.constants import FeatureNameConst
from juloserver.personal_data_verification.tests.factories import DukcapilResponseFactory
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestChangeAppStatusDukcapil(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
            parameters={'method': 'direct'},
        )

    def test_check_dukcapil_tab_direct(self):
        DukcapilResponseFactory(application=self.application, status='200', source='Dukcapil')
        shown_statuses = [121]
        not_shown_statuses = [105, 133, 140, 150]

        for status in shown_statuses:
            msg_prefix = "(status: {}) ".format(status)
            self.application.update_safely(application_status_id=status)
            response = self.client.get('/app_status/change_status/{}'.format(self.application.id))
            self.assertContains(response, 'data-test="dukcapil-tab"', msg_prefix=msg_prefix)

        for status in not_shown_statuses:
            msg_prefix = "(status: {}) ".format(status)
            self.application.update_safely(application_status_id=status)
            response = self.client.get('/app_status/change_status/{}'.format(self.application.id))
            self.assertNotContains(response, 'data-test="dukcapil-tab"', msg_prefix=msg_prefix)

    def test_method_asliri_dukcapil_tab(self):
        self.feature_setting.update_safely(parameters={'method': 'asliri'})
        DukcapilResponseFactory(application=self.application, status='200', source='AsliRI')
        shown_statuses = [133, 140]
        not_shown_statuses = [105, 121, 150]

        for status in shown_statuses:
            msg_prefix = "(status: {}) ".format(status)
            self.application.update_safely(application_status_id=status)
            response = self.client.get('/app_status/change_status/{}'.format(self.application.id))
            self.assertContains(response, 'data-test="dukcapil-tab"', msg_prefix=msg_prefix)

        for status in not_shown_statuses:
            msg_prefix = "(status: {}) ".format(status)
            self.application.update_safely(application_status_id=status)
            response = self.client.get('/app_status/change_status/{}'.format(self.application.id))
            self.assertNotContains(response, 'data-test="dukcapil-tab"', msg_prefix=msg_prefix)

    def test_method_direct_v2_dukcapil_tab(self):
        self.feature_setting.update_safely(parameters={'method': 'direct_v2'})
        DukcapilResponseFactory(application=self.application, status='200', source='Dukcapil')
        shown_statuses = [133, 140]
        not_shown_statuses = [105, 121, 150]

        for status in shown_statuses:
            msg_prefix = "(status: {}) ".format(status)
            self.application.update_safely(application_status_id=status)
            response = self.client.get('/app_status/change_status/{}'.format(self.application.id))
            self.assertContains(response, 'data-test="dukcapil-tab"', msg_prefix=msg_prefix)

        for status in not_shown_statuses:
            msg_prefix = "(status: {}) ".format(status)
            self.application.update_safely(application_status_id=status)
            response = self.client.get('/app_status/change_status/{}'.format(self.application.id))
            self.assertNotContains(response, 'data-test="dukcapil-tab"', msg_prefix=msg_prefix)
