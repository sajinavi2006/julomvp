from mock import patch, MagicMock
from dateutil.relativedelta import relativedelta
from django.test.testcases import TestCase
from django.utils import timezone
from datetime import timedelta

from juloserver.magic_link.services import *
from factories import MagicLinkHistoryFactory

from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.julo.constants import FeatureNameConst


class TestMagicLinkService(TestCase):
    def setUp(self):
        self.magic_link_history = MagicLinkHistoryFactory()
        self.feature_settings = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.MAGIC_LINK_EXPIRY_TIME,
            description="magic  link expiry time in minutes",
            parameters=10
        )


    def test_generate_magic_link_and_verify(self):
        short_url, magic_link_history = generate_magic_link()
        self.assertIsNotNone(magic_link_history.id)

        token = magic_link_history.token
        is_valid_token = is_valid_magic_link_token(token)
        self.assertTrue(is_valid_token)

        # expired checking
        self.magic_link_history.expiry_time = timezone.localtime(timezone.now()) - timedelta(minutes=20)
        self.magic_link_history.save()
        is_valid_token = is_valid_magic_link_token(self.magic_link_history.token)
        self.assertFalse(is_valid_token)

