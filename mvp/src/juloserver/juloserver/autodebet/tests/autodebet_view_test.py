from mock import ANY, patch
from rest_framework.test import APIClient, APITestCase
from juloserver.autodebet.tests.factories import (
    AutodebetDeactivationSurveyQuestionFactory,
    AutodebetDeactivationSurveyAnswerFactory,
    AutodebetAccountFactory,
    AutodebetPaymentOfferFactory,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.autodebet.constants import FeatureNameConst


class TestAutodebetDeactivationSurvey(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account,
            is_deleted_autodebet=True,
            is_use_autodebet=False,
            vendor="DANA",
        )

        self.question = AutodebetDeactivationSurveyQuestionFactory()
        self.answer1 = AutodebetDeactivationSurveyAnswerFactory(
            question=self.question,
            answer='Tidak menggunakan autodebit lagi',
            order=1,
        )
        self.answer2 = AutodebetDeactivationSurveyAnswerFactory(
            question=self.question,
            answer='Ingin ganti autodebit lain',
            order=2,
        )

    def test_get_deactivation_autodebet_survey(self):
        url = '/api/autodebet/v1/deactivation/survey'
        response = self.client.get(url, follow=True)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json_response["data"]["answers"]), 2)

    def test_post_deactivation_autodebet_survey(self):
        url = '/api/autodebet/v1/deactivation/survey/answer'
        data = {
            "bank_name": "DANA",
            "question": "Kenapa ingin deaktivasi autodebit?",
            "answer": "Ingin ganti ke autodebit lain",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)


class TestAutodebetPaymentOffer(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_PAYMENT_OFFER_CONTENT,
            parameters={
                "title": "Aktifkan Autodebit, yuk!",
                "content": "Nggak perlu khawatir lagi lupa bayar tagihan dan kena denda keterlambatan.\n\nTanya agent JULO perihal aktivasinya atau aktifkan autodebit kamu sekarang!",
            },
        )
        self.paymet_offer = AutodebetPaymentOfferFactory(
            account_id=self.account.id,
        )

    def test_get_deactivation_payment_offer(self):
        url = '/api/autodebet/v1/payment/offer'
        response = self.client.get(url, follow=True)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json_response["data"]["should_show"], True)

    def test_post_deactivation_payment_offer(self):
        url = '/api/autodebet/v1/payment/offer'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
