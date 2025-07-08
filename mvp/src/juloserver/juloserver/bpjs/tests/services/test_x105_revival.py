from django.test import TestCase
from unittest.mock import patch

from juloserver.bpjs.services.x105_revival import X105Revival, Brick, Fraud
from juloserver.bpjs.tests.factories import SdBpjsCompanyScrapeFactory, SdBpjsProfileScrapeFactory
from juloserver.julo.models import CreditScore
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    CreditScoreFactory,
)


class TestX105Revival(TestCase):
    def setUp(self) -> None:
        x105 = StatusLookupFactory(status_code=105)
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer, company_name='Pt. Julo', application_status=x105
        )

        self.bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        self.bpjs_company = SdBpjsCompanyScrapeFactory(
            profile=self.bpjs_profile, company='PT. Julo'
        )
        self.credit_score = CreditScoreFactory(score="C", application_id=self.application.id)

    @patch.object(X105Revival, 'approve')
    def test_reject_when_balance_below_threshold(self, mock_approve):
        self.bpjs_profile.update_safely(total_balance=str(3_500_000))
        X105Revival(self.application.id).run()

        mock_approve.assert_not_called()
        credit_score = CreditScore.objects.filter(application=self.application).last()
        self.assertEqual(credit_score.score, "C")

    @patch.object(X105Revival, 'approve')
    def test_reject_when_salary_below_threshold(self, mock_approve):
        self.bpjs_company.update_safely(current_salary=str(3_000_000))
        X105Revival(self.application.id).run()
        mock_approve.assert_not_called()
        credit_score = CreditScore.objects.filter(application=self.application).last()
        self.assertEqual(credit_score.score, "C")

    @patch.object(X105Revival, 'pass_fraud')
    @patch.object(X105Revival, 'approve')
    def test_reject_c_low_credit_score(self, mock_approve, mock_check_fraud):
        self.credit_score.update_safely(score_tag="c_low_credit_score")
        X105Revival(self.application.id).run()
        mock_approve.assert_not_called()
        mock_check_fraud.assert_not_called()
        credit_score = CreditScore.objects.filter(application=self.application).last()
        self.assertEqual(credit_score.score, "C")

    @patch.object(X105Revival, 'approve')
    @patch.object(X105Revival, 'pass_fraud', return_value=False)
    def test_reject_when_not_pass_fraud_check(self, mock_fraud, mock_approve):
        X105Revival(self.application.id).run()
        mock_approve.assert_not_called()
        credit_score = CreditScore.objects.filter(application=self.application).last()
        self.assertEqual(credit_score.score, "C")

    @patch.object(X105Revival, 'rescore')
    @patch.object(X105Revival, 'pass_fraud', return_value=True)
    @patch("juloserver.bpjs.services.x105_revival.process_application_status_change")
    def test_pass_complete_scenario(self, mock_status_change, mock_fraud_check, mock_rescore):
        self.bpjs_profile.update_safely(total_balance=str(4_900_000))
        self.bpjs_company.update_safely(current_salary=str(3_900_000))
        X105Revival(self.application.id).run()
        mock_status_change.assert_called_once_with(self.application, 121, "BPJS Scrape Revival")
        mock_rescore.assert_called_once_with()

    @patch.object(X105Revival, 'rescore')
    @patch.object(X105Revival, 'pass_fraud', return_value=True)
    @patch("juloserver.bpjs.services.x105_revival.process_application_status_change")
    def test_pass_partial_scenario(self, mock_status_change, mock_fraud, mock_rescore):
        self.application.update_safely(company_name="Google")
        self.bpjs_profile.update_safely(total_balance=str(4_900_000))
        self.bpjs_company.update_safely(current_salary=str(3_900_000))
        X105Revival(self.application.id).run()
        mock_status_change.assert_called_once_with(
            self.application, 121, "BPJS Scrape with different company name"
        )
        mock_rescore.assert_called_once_with()


class TestBrick(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    def test_has_same_company_name_1(self):
        self.application.update_safely(company_name='PT. Julo')
        bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        SdBpjsCompanyScrapeFactory(profile=bpjs_profile, company='PT. Julo')
        brick = Brick(self.application)
        self.assertTrue(brick.has_same_company_name)

    def test_has_same_company_name_2(self):
        self.application.update_safely(company_name='PT. Julo')
        bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        SdBpjsCompanyScrapeFactory(profile=bpjs_profile, company='Julo')
        brick = Brick(self.application)
        self.assertTrue(brick.has_same_company_name)

    def test_has_same_company_name_3(self):
        self.application.update_safely(company_name='CV Julo')
        bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        SdBpjsCompanyScrapeFactory(profile=bpjs_profile, company='Julo')
        brick = Brick(self.application)
        self.assertTrue(brick.has_same_company_name)

    def test_has_same_company_name_4(self):
        self.application.update_safely(company_name='Julo Tbk')
        bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        SdBpjsCompanyScrapeFactory(profile=bpjs_profile, company='Julo')
        brick = Brick(self.application)
        self.assertTrue(brick.has_same_company_name)

    def test_has_same_company_name_5(self):
        self.application.update_safely(company_name='PT. Julo Tbk')
        bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        SdBpjsCompanyScrapeFactory(profile=bpjs_profile, company='Julo')
        brick = Brick(self.application)
        self.assertTrue(brick.has_same_company_name)

    def test_has_same_company_name_6(self):
        self.application.update_safely(company_name='PT. Julo, Tbk.')
        bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        SdBpjsCompanyScrapeFactory(profile=bpjs_profile, company='Julo')
        brick = Brick(self.application)
        self.assertTrue(brick.has_same_company_name)


class TestFraud(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    @patch("juloserver.application_flow.tasks.execute_mycroft")
    def test_pass_mycroft_1(self, mock_mycroft):
        mock_mycroft.return_value = True, False, False
        fraud = Fraud(self.application)

        self.assertTrue(fraud.pass_mycroft)

    @patch("juloserver.application_flow.tasks.execute_mycroft")
    def test_pass_mycroft_2(self, mock_mycroft):
        mock_mycroft.return_value = True, True, False
        fraud = Fraud(self.application)

        self.assertTrue(fraud.pass_mycroft)

    @patch("juloserver.application_flow.tasks.execute_mycroft")
    def test_fail_mycroft(self, mock_mycroft):
        mock_mycroft.return_value = False, False, False
        fraud = Fraud(self.application)

        self.assertFalse(fraud.pass_mycroft)

    @patch("juloserver.fraud_security.services.blacklisted_asn_check", return_value=True)
    def test_pass_blacklisted_asn(self, mock_asn):
        fraud = Fraud(self.application)

        self.assertFalse(fraud.pass_blacklisted_asn)

    @patch("juloserver.fraud_security.services.blacklisted_asn_check", return_value=False)
    def test_fail_blacklisted_asn(self, mock_asn):
        fraud = Fraud(self.application)

        self.assertTrue(fraud.pass_blacklisted_asn)

    @patch("juloserver.fraud_security.tasks.check_high_risk_asn", return_value=False)
    def test_pass_high_risk_asn(self, mock_asn):
        fraud = Fraud(self.application)

        self.assertTrue(fraud.pass_high_risk_asn)

    @patch("juloserver.fraud_security.tasks.check_high_risk_asn", return_value=True)
    def test_fail_high_risk_asn_1(self, mock_asn):
        fraud = Fraud(self.application)

        self.assertFalse(fraud.pass_high_risk_asn)

    @patch("juloserver.fraud_security.tasks.check_high_risk_asn", return_value=None)
    def test_fail_high_risk_asn_2(self, mock_asn):
        fraud = Fraud(self.application)

        self.assertFalse(fraud.pass_high_risk_asn)

    @patch("juloserver.fraud_security.binary_check.process_fraud_binary_check")
    def test_pass_binary_check_fraud(self, mock_binary):
        mock_binary.return_value = True, "handler"
        fraud = Fraud(self.application)

        passed = fraud.pass_general_check

        self.assertTrue(passed)
        self.assertEqual(fraud.binary_check_handler, "handler")

    @patch("juloserver.fraud_security.binary_check.process_fraud_binary_check")
    def test_fail_binary_check_fraud(self, mock_binary):
        mock_binary.return_value = False, "handler"
        fraud = Fraud(self.application)

        passed = fraud.pass_general_check

        self.assertFalse(passed)
        self.assertEqual(fraud.binary_check_handler, "handler")

    @patch("juloserver.liveness_detection.services.check_application_liveness_detection_result")
    def test_pass_liveness(self, mock_liveness):
        mock_liveness.return_value = True, "reason"
        fraud = Fraud(self.application)

        self.assertTrue(fraud.pass_liveness)
        self.assertEqual(fraud.liveness_reason, "reason")

    @patch("juloserver.liveness_detection.services.check_application_liveness_detection_result")
    def test_fail_liveness(self, mock_liveness):
        mock_liveness.return_value = False, "reason"
        fraud = Fraud(self.application)

        self.assertFalse(fraud.pass_liveness)
        self.assertEqual(fraud.liveness_reason, "reason")
