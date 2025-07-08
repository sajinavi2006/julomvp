from django.test.testcases import TestCase
from juloserver.julo.tests.factories import (ApplicationFactory, CreditScoreFactory,
                                             ProductLineFactory,
                                             AuthUserFactory, CustomerFactory, ITIConfigurationFactory)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.apiv2.services import get_high_score_iti_bypass


class TestGetSonicFullBypass(TestCase):

    def setUp(self):
        self.product_line = ProductLineFactory(product_line_code=1, product_line_type="J1")
        self.user = AuthUserFactory(password='123457')
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, product_line=self.product_line)
        self.application.save()
        self.sonic_score_full_bypass = ITIConfigurationFactory(customer_category='julo', is_salaried=False)
        self.sonic_score_full_bypass.max_threshold = 0.9
        self.sonic_score_full_bypass.min_threshold = 0.8
        self.sonic_score_full_bypass.max_income = 4000000
        self.sonic_score_full_bypass.save()
        self.pd_credit_model_result = PdCreditModelResultFactory(pgood=0.8, application_id=self.application.id)
        self.credit_score = CreditScoreFactory(model_version='34', application_id=self.application.id)
        self.application.save()
        self.pd_credit_model_result.save()

    # happy path
    def test_case_1(self):
        self.sonic_score_full_bypass.is_active = True
        self.sonic_score_full_bypass.is_salaried = True
        self.sonic_score_full_bypass.is_premium_area = True
        self.sonic_score_full_bypass.parameters = {
            "job_type": [
                "Pegawai swasta"
            ],
            "province": [
                "Gorontalo"
            ],
            "job_industry": [
                "Admin / Finance / HR"
            ],
            "job_description": [
                "Admin / Finance / HR:All"
            ],
        }
        self.application.address_provinsi = 'Gorontalo'
        self.application.job_industry = 'Admin / Finance / HR'
        self.application.job_description = 'Admin'
        self.sonic_score_full_bypass.max_threshold = 0.9
        self.sonic_score_full_bypass.min_threshold = 0.7
        self.sonic_score_full_bypass.max_income = 5000000
        self.sonic_score_full_bypass.customer_category = 'julo1'
        self.sonic_score_full_bypass.save()
        result = get_high_score_iti_bypass(self.application, 1, True, 'julo1', True, 0.8)
        self.assertTrue(result)

    # for not get a high score
    def test_case_2(self):
        self.sonic_score_full_bypass.is_premium_area = False
        self.sonic_score_full_bypass.parameters = {
            "job_type": [
                "Pegawai swasta"
            ],
            "province": [
                "Gorontalo"
            ],
            "job_industry": [
                "Admin / Finance / HR"
            ],
            "job_description": [
                "Admin / Finance / HR:All"
            ],
        }
        self.application.address_provinsi = 'Gorontalo'
        self.application.job_industry = 'Admin / Finance / HR'
        self.application.job_description = 'Musisi'
        self.sonic_score_full_bypass.save()
        result = get_high_score_iti_bypass(self.application, 1, True, 'julo', True, 0.5)
        self.assertFalse(result)

    # blank province and job
    def test_case_3(self):
        self.sonic_score_full_bypass.is_premium_area = True
        self.sonic_score_full_bypass.parameters = {
            "job_type": [],
            "province": [],
            "job_industry": [],
            "job_description": [],
        }
        self.application.address_provinsi = 'Gorontalo'
        self.application.job_industry = 'Admin / Finance / HR'
        self.application.job_description = 'Admin'
        self.sonic_score_full_bypass.save()
        result = get_high_score_iti_bypass(self.application, 1, False, 'julo', False, 0.9)
        self.assertFalse(result)

    # no parameters
    def test_case_4(self):
        self.sonic_score_full_bypass.is_premium_area = True
        self.sonic_score_full_bypass.save()
        result = get_high_score_iti_bypass(self.application, 1, False, 'julo', False, 0.9)
        self.assertFalse(result)
