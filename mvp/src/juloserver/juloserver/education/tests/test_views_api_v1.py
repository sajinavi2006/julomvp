from django.test import TestCase
from rest_framework.test import APIClient

from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    AuthUserFactory,
)

from juloserver.education.constants import FeatureNameConst


class TestEducationViewsAPIV1(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)

    def test_faq_api(self):
        faq_feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.EDUCATION_FAQ, is_active=True, parameters=[]
        )
        res = self.client.get('/api/education/v1/faq', {}, True)
        self.assertEqual(res.status_code, 200)

        faq_feature.is_active = False
        faq_feature.save()
        res = self.client.get('/api/education/v1/faq', {}, True)
        self.assertEqual(res.status_code, 200)

    def test_faq_api_with_no_301_status_code(self):
        faq_feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.EDUCATION_FAQ, is_active=True, parameters=[]
        )
        res = self.client.get('/api/education/v1/faq/', {}, True)
        self.assertEqual(res.status_code, 200)

        faq_feature.is_active = False
        faq_feature.save()
        res = self.client.get('/api/education/v1/faq/', {}, True)
        self.assertEqual(res.status_code, 200)
