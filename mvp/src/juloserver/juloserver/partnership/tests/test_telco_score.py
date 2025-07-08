import json

from django.conf import settings
from django.test.testcases import TestCase
from mock import patch
from requests import Response

from juloserver.application_flow.factories import (
    ApplicationPathTagStatusFactory,
    ApplicationTagFactory,
)
from juloserver.application_flow.models import ApplicationPathTag
from juloserver.application_flow.services2.telco_scoring import XL
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    PartnerFactory,
    ProductLineFactory,
    WorkflowFactory,
)
from juloserver.partnership.constants import PartnershipProductFlow, PartnershipTelcoScoringStatus
from juloserver.partnership.models import PartnershipFlowFlag
from juloserver.partnership.telco_scoring import PartnershipTelcoScore


class PartnershipTelcoScoreTest(TestCase):
    """
    QOALA PARTNERSHIP - Leadgen Agent Assisted 21-11-2024
    """

    def setUp(self) -> None:
        self.partner = PartnerFactory(name='qoala')

        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        j1_product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(workflow=j1_workflow, product_line=j1_product_line)
        self.application.partner = self.partner
        self.application.save()

        self.partnership_flow_flag = PartnershipFlowFlag.objects.create(
            partner=self.partner,
            name=PartnershipProductFlow.AGENT_ASSISTED,
            configs={
                "provider": {
                    "xl": {
                        "is_active": True,
                        "prefixes": [
                            '0877',
                            '0878',
                            '0817',
                            '0818',
                            '0819',
                        ],
                        "swap_out_threshold": 750,
                    },
                }
            },
        )

        self.private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA2aKNdqA54p3HsAirZawfxnJ7JgWrnhxrinX6iSHXbPoxDc/J\n"
            "7fNy2+Sww6TKvjw4/nRBFFEALSQ6uqN/FDcQPjOjsLKybaBXcsbN7v9aK6EB9Dmo\n"
            "5vwKj4EFLhGAjEQ//MTjonFCoOz4WCDTM8n1EOLYk7b+b8CbfLPjSZ/cucAnOCcd\n"
            "AjBSurXPlwBn2qV7GII10on5P5VGY5QoFQc3ALbi+Rx0Nfa1k9uAmTuDxFgj6JOy\n"
            "f6M8/DKGA/EBOGbFBGTd2U6fTPQlz4o1BXtRr8v/ln97vvaqo5pP/kA9FY/UOBuI\n"
            "2f9HTX4qfTNK7mI/aFWrY7vS0S/yLDTeQvq0wwIDAQABAoIBAQCPuVnSzV1s2uXU\n"
            "yuTl8BXL6C6LnZMIh5w9hEw/46lwvolGpcKk8fEYZp6VlW6O0xaQdBXGZPfI1/Qw\n"
            "7Wgu4W5IpbGkL17GJu2ZTtEQ1HGn/lxb/PgeErSmsH3LPqO1/hyDwULTNBjcTaJ0\n"
            "ELlpqiW9URHV+zNsebY1VFb1eC08PQF/kfgXsYCKQShs3QrwEmGJ0lf3D8wzSEMg\n"
            "fv9+vCsxgkU9oHNCGuizKJoEIYbBCNvhIr0KlxiRA9rnhAC43xqmK6oMBtvNVkO6\n"
            "3ORvJY6HXVwrfFv8YQfsKOk/KvfbAaYA5xtTxw7neRwu3mz6duS9z/3ZMvA+XWcq\n"
            "ctzZfbcBAoGBAPhZY/be+KrxR+4LTi1ms879CHy+Np8UHKZMd5Pv4jawcJT1405W\n"
            "YUcaT6Iyl6tNoxzFf36L/FHOvHkbnnUdXuLvyqg//Tpga+Yv21R9IruB1VwlXgNe\n"
            "EPlnDsuREL/vdYIKmH+XHoUWFS4vVV3SlDaAghVOaaYVXgCH2/Iy6ly7AoGBAOBW\n"
            "7xxtW6oVUfJO//nUxrJIBxqY3qRxkp0Cj/HBzHRa++DMlSHiJlr9j5OPdL7NHYc4\n"
            "SU53deBvcjG/6vZ/unJ4IDe66N2owhEmKYi7A4T5LcrasrKf8eAZhf8IFeUHGXaZ\n"
            "UsrUUyl6FWWveOAvX0+rCjgNRaBgINcw7CNak8uZAoGATF1wV6EIZcf7jj77swo5\n"
            "kBROX809jnzoslohCuRgcuCePa++TYBSOULl6cIU0R/2YAp6wbbZx24CllrfxrNZ\n"
            "Uf7aGhJTE3hCtW1RzBEOdQnfSY5T8kUigw4lhoL824gOYgZQDiuxvsqjiKgVX9w4\n"
            "pumtFlAePGullBQyla8CUbECgYEAt113PZYJKWEZxONbiJmo+smyvMOcn26RNrKE\n"
            "c0dDVQuU+u5dKv/M9+xusV69PsMq0n5oNLGh8JtHDHDgnTBTdgLH2qV0dtDcJuY5\n"
            "Zp/tRX/iNP9CtovTSKe0BXtXYgbGglDaAh1ACBPYb2/Ybe1qixSzWpNGiMpprVo4\n"
            "eMEtMmkCgYAsmt4lK6FmZV8imlkXvgZz03I11Y7cVQ+tmjPNP6b/zRPnnZf6vpAw\n"
            "p2Zgici9ikQ8x+HB3S9b6YxnhULZAPpZJb1bfXgH1SDmEXsZ92+50zJrksXJwgCM\n"
            "k9NHMJHh6e2slIKbDMexCyYz0NYjusRWztYC7Tn7Ec82WKrDeviw6g==\n"
            "-----END RSA PRIVATE KEY-----\n"
        )

        settings.TS_TELCO_SCORING["TELKOMSEL"]["PRIVATE_KEY"] = self.private_key
        settings.TS_TELCO_SCORING["INDOSAT"]["PRIVATE_KEY"] = self.private_key
        settings.TS_TELCO_SCORING["XL"]["PRIVATE_KEY"] = self.private_key

        self.score_success_content = json.dumps(
            {
                "verdict": "success",
                "message": "credit insight is available",
                "2017-09-06T04:24:32Z": "",
                "data": {
                    "score": "JWxN2bDgqcN4Vw4OoSJJfz4kiPkOn2tOJkAb79fX9Y2wRAQ_NSw0FhPDJJcigDXn1wc22sIXD6fMTBrQ2z0soyhpI0vhsgDJo98juRWluaV4c2btmzjgtI7zewlXmURZMKw0ngAqktnLnX_nteIEfX_O8D61oMxYr5n5WHkCpN_AI5aPmmtr2xvzEz00XvgFB8rvQ23MlEt82dBh9cOqkTpIAoOYfZx2F0guQ6-2CypI9liNLQrnk7lYZ8owDnA4NenIsXpZ-mJmzUogVDNqpolsha1H-FpQacW3XRYRr-s5-sCyN___jXr9uUa6ZNI3tQ86KtxIXHM2bgrX5UZing==",
                    "request_id": 12,
                    "verify": "new",
                },
            }
        ).encode("utf-8")

        ApplicationTagFactory(application_tag=PartnershipTelcoScore.TAG)
        self.tag_pass = ApplicationPathTagStatusFactory(
            application_tag=PartnershipTelcoScore.TAG,
            status=PartnershipTelcoScore.TAG_STATUS_PASS_SWAP_IN,
        )
        self.tag_bad = ApplicationPathTagStatusFactory(
            application_tag=PartnershipTelcoScore.TAG,
            status=PartnershipTelcoScore.TAG_STATUS_FAIL_SWAP_IN,
        )

    def test_run_when_application_null(self):
        telco = PartnershipTelcoScore(application=None)
        self.assertIsNone(telco.run())

    def test_run_when_setting_null(self):
        self.partnership_flow_flag.feature_name = "just-random-name"
        self.partnership_flow_flag.save()

        telco = PartnershipTelcoScore(application=self.application)
        self.assertIsNone(telco.run())

    @patch.object(XL, "call_score_endpoint")
    def test_operator_setting_disabled(self, mock_call_score_endpoint):
        self.partnership_flow_flag.configs["provider"]["xl"]["is_active"] = False
        self.partnership_flow_flag.save()

        self.application.mobile_phone_1 = "+628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = PartnershipTelcoScore(application=self.application)
        telco_result = telco.run_in_eligibility_check()
        self.assertTrue(telco_result == PartnershipTelcoScoringStatus.OPERATOR_NOT_ACTIVE)

    @patch.object(XL, "call_score_endpoint")
    @patch.object(PartnershipTelcoScore, "_is_okay_swap_in", return_value=False)
    def test_run_in_binary_check(self, _is_okay_swap_in, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "+628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = PartnershipTelcoScore(application=self.application)
        telco_result = telco.run_in_eligibility_check()

        tag = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=self.tag_bad
        ).last()
        self.assertIsNotNone(tag)

        is_bad_result = telco_result in PartnershipTelcoScoringStatus.bad_result_list()
        self.assertTrue(is_bad_result)

    @patch.object(XL, "call_score_endpoint")
    def test_phone_prefix_not_found(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "+628599186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = PartnershipTelcoScore(application=self.application)
        telco_result = telco.run_in_eligibility_check()
        self.assertTrue(telco_result == PartnershipTelcoScoringStatus.OPERATOR_NOT_FOUND)
