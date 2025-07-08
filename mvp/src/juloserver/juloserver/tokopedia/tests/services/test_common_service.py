import json

from django.test import TestCase, override_settings
from unittest.mock import Mock, patch


from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    WorkflowFactory,
    ProductLineFactory,
    TokoScoreResultFactory,
)
from juloserver.julo.constants import (
    WorkflowConst,
    ProductLineCodes,
)
from juloserver.tokopedia.models import TokoScoreResult
from juloserver.tokopedia.constants import TokoScoreConst
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.tokopedia.services.common_service import (
    run_shadow_score_with_toko_score,
    get_score,
)


class TestShadowScore(TestCase):
    def setUp(self):

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            id=1,
            customer=self.customer,
            workflow=self.workflow,
            email='testing@julofinance.com',
            mobile_phone_1='083822825220',
        )
        self.application.update_safely(application_status_id=ApplicationStatusCodes.LOC_APPROVED)
        self.toko_score_result = TokoScoreResultFactory(
            application_id=self.application.id,
            request_score_id=TokoScoreConst.SCORE_ID,
            score_type=TokoScoreConst.SHADOW_SCORE_TYPE,
            score='800.000000',
            request_message_id='20231211.17022861059571357',
            is_match=True,
            is_active=True,
            request_status='success',
        )

    @patch('juloserver.tokopedia.services.common_service.get_score')
    @patch('juloserver.tokopedia.services.common_service.is_have_tokopedia_apps', return_value=True)
    @patch(
        'juloserver.tokopedia.services.common_service.is_success_revive_by_tokoscore',
        return_value=False,
    )
    @patch('requests.post')
    def test_scenario_for_shadow_score(
        self, mock_request, mock_is_success_revive, mock_is_have_tokopedia, mock_request_get_score
    ):

        mock_request_get_score.return_value = self.toko_score_result

        self.assertTrue(run_shadow_score_with_toko_score(self.application.id))

    @patch('juloserver.tokopedia.services.common_service.get_score')
    @patch('juloserver.tokopedia.services.common_service.is_have_tokopedia_apps', return_value=True)
    @patch(
        'juloserver.tokopedia.services.common_service.is_success_revive_by_tokoscore',
        return_value=False,
    )
    @patch('requests.post')
    def test_scenario_for_shadow_score_failed(
        self, mock_request, mock_is_success_revive, mock_is_have_tokopedia, mock_request_get_score
    ):

        mock_request_get_score.return_value = self.toko_score_result
        self.application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL)
        self.assertFalse(run_shadow_score_with_toko_score(self.application.id))


class TestReviveScore(TestCase):
    def setUp(self):

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            id=1,
            customer=self.customer,
            workflow=self.workflow,
            email='testing@julofinance.com',
            mobile_phone_1='083822825220',
        )
        self.application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL)
        self.score_default = '800.000000'
        self.structure_response = {
            "code": "200000",
            "latency": "242.42 ms",
            "data": {
                "message_id": "20231127.TEST_SCORE_06",
                "score_id": 160,
                "score": "AvIcbZLCiSc+S2X6eb0/AJbxNwS9hwN+CV1KJ4ZoSKmhypopX6L0AaIxgkH8Tg8WZ"
                "9IxWa6jz6rfuX8LhR3XG17qrXZYtDgCMnBSs7LQsC5+BYoy78K5oOd9zjQTTUEHDV4/S4i4k/M6E81NBYIds"
                "Tp+5P0USgYoWNImO5WxJtTn6bSPMBERN+ptUCo5ecm3rq/Bp1IBf7OpJZnYPl69DIxLwCSdxZBCnQEsQqhgrFbeG"
                "bPnNmSutEqEcvXq86FlWcoEz/bSrUmvvfeMogkIUJVXcboyWZ1k8N2uniipT2exIxK6MLW+tBWTXOkrc4RrbkVOcmQ"
                "MX3F8+wq9SyjTvwQRRSHhvozA/XcOTee4JovKgQcVNZKVOW43ecmQqD1WCkBJoN8MgfV9vvnhBzdzrix+2GNwhzKs"
                "VTJcV5r06Ve9mynaylBp4hlorK2vakuP/YFELwfgZy3lVETZwMGutJH8MmvUhfJSz6kyliKr55wKKozsa6uJS+plR"
                "d0SmcV2cHDVlDMrfaLH93dTr7tUaPF+emxOLvuH9EJc8AU6Tc3wFAiHXc9Tzbp/RTTOzPmRWHByWJRN+g3Ii02Oy4"
                "kKfFzuSHVP1VgdTrebjMDhorU3xRcYWtDuCfYNZ36+GF579Xzbp/QS98J4Cj+TrUQvw1JsgML3fI9wIOsbAO68BJc=",
                "no_pg_dg": True,
                "response_timestamp": "2023-11-27T13:46:14.498544457+07:00",
            },
        }

    @patch(
        'juloserver.tokopedia.services.clients.TokoScoreClient.do_decrypt',
        return_value='800.000000',
    )
    @patch('juloserver.tokopedia.services.clients.TokoScoreClient.get_request_score')
    def test_success_toko_score_request(self, mock_response_tokoscore, mock_decrypt_score):

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = self.structure_response
        mock_response_tokoscore.return_value = mock_response

        tokoscore_data = get_score(self.application.id)
        total_of_data = TokoScoreResult.objects.filter(application_id=self.application.id).count()
        self.assertEqual(tokoscore_data.score, self.score_default)
        self.assertEqual(tokoscore_data.is_active, False)
        self.assertEqual(total_of_data, 1)

    @patch(
        'juloserver.tokopedia.services.clients.TokoScoreClient.do_decrypt',
        return_value='800.000000',
    )
    @patch('juloserver.tokopedia.services.clients.TokoScoreClient.get_request_score')
    def test_success_toko_score_with_return_last_request(
        self, mock_response_tokoscore, mock_decrypt_score
    ):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = self.structure_response
        mock_response_tokoscore.return_value = mock_response

        last_request = TokoScoreResultFactory(
            application_id=self.application.id,
            request_score_id=TokoScoreConst.SCORE_ID,
            score_type=TokoScoreConst.REVIVE_SCORE_TYPE,
            score=self.score_default,
            request_message_id='20231211.17022861059571357',
            is_match=True,
            is_active=True,
            request_status='success',
        )

        # try to re-hit to tokoscore
        tokoscore_data = get_score(self.application.id)
        total_of_data = TokoScoreResult.objects.filter(application_id=self.application.id).count()
        self.assertEqual(tokoscore_data.score, self.score_default)
        self.assertEqual(total_of_data, 1)
