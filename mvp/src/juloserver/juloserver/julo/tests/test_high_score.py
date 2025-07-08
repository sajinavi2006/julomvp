"""
"""
from __future__ import absolute_import

from django.test.testcases import TestCase
from juloserver.julo.services2.high_score import get_high_score_full_bypass

from juloserver.julo.tests.factories import (ApplicationFactory,CreditScoreFactory, HighScoreFullBypassFactory,
                                             FeatureSetting, ProductLineFactory,FeatureSettingFactory,
                                             AuthUserFactory,CustomerFactory)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.julo.constants import FeatureNameConst

# class TestGetHighScoreFullBypass(TestCase):
#
#     def setUp(self):
#         self.product_line = ProductLineFactory(product_line_code=1, product_line_type="J1")
#         self.user = AuthUserFactory(password='123457')
#         self.customer = CustomerFactory(user=self.user)
#         self.application = ApplicationFactory(customer=self.customer, product_line = self.product_line)
#         self.application.save()
#         self.high_score_full_bypass = HighScoreFullBypassFactory(cm_version='34', threshold=0.3,
#                                                                  customer_category='julo', is_salaried=False)
#         self.pd_credit_model_result = PdCreditModelResultFactory(pgood=0.9,application_id=self.application.id)
#         self.feature_setting = FeatureSettingFactory(feature_name=FeatureNameConst.HIGH_SCORE_FULL_BYPASS,
#                                                      is_active=True,)
#         self.credit_score = CreditScoreFactory(model_version='34', application_id=self.application.id)
#         self.application.save()
#         self.pd_credit_model_result.save()
#
#     # happy path
#     def test_case_1(self):
#         self.high_score_full_bypass.is_premium_area = True
#         self.high_score_full_bypass.parameters = {
#                                                   "job_type": [
#                                                     "Pegawai swasta"
#                                                   ],
#                                                   "province": [
#                                                       "Gorontalo"
#                                                   ],
#                                                   "job_industry": [
#                                                     "Perbankan"
#                                                   ],
#                                                   "job_description": [
#                                                     "Kolektor"
#                                                   ],
#                                                 }
#         self.application.address_provinsi = 'Gorontalo'
#         self.application.job_industry = 'Perbankan'
#         self.application.job_description = 'Kolektor'
#         self.high_score_full_bypass.save()
#         result = get_high_score_full_bypass(self.application, 34, True, 'julo', 0.9)
#
#         self.assertEqual(result.id, self.high_score_full_bypass.id)
#
#     # for not get a high score
#     def test_case_2(self):
#         self.high_score_full_bypass.is_premium_area = False
#         self.high_score_full_bypass.parameters = {
#                                                   "job_type": [
#                                                     "Pegawai swasta"
#                                                   ],
#                                                   "province": [
#                                                       "Gorontalo"
#                                                   ],
#                                                   "job_industry": [
#                                                     "Admin / Finance / HR"
#                                                   ],
#                                                   "job_description": [
#                                                     "Admin / Finance / HR:All"
#                                                   ],
#                                                 }
#         self.application.address_provinsi = 'Gorontalo'
#         self.application.job_industry = 'Admin / Finance / HR'
#         self.application.job_description = 'Kameramen'
#         self.high_score_full_bypass.save()
#         result = get_high_score_full_bypass(self.application, 34, True, 'julo', 0.9)
#         self.assertEqual(None, result)
#
#     # blank province and job
#     def test_case_3(self):
#         self.high_score_full_bypass.is_premium_area = True
#         self.high_score_full_bypass.parameters = {
#                                                   "job_type": [],
#                                                   "province": [],
#                                                   "job_industry": [],
#                                                   "job_description": [],
#                                                 }
#         self.application.address_provinsi = 'Gorontalo'
#         self.application.job_industry = 'Perhotelan'
#         self.application.job_description = 'Kebersihan'
#         self.high_score_full_bypass.save()
#         result = get_high_score_full_bypass(self.application, 34, True, 'julo', 0.9)
#         self.assertEqual(result.id, self.high_score_full_bypass.id)
#
#     # no parameters
#     def test_case_4(self):
#         self.high_score_full_bypass.is_premium_area = True
#         self.high_score_full_bypass.save()
#         result = get_high_score_full_bypass(self.application, 34, True, 'julo', 0.9)
#         self.assertEqual(result.id, self.high_score_full_bypass.id)
