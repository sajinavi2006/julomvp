import phonenumbers
from requests import ReadTimeout

from juloserver.application_flow.services2.telco_scoring import (
    TelcoScore,
    TelcoException,
    TelcoClient,
    Telkomsel,
    Indosat,
    XL,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Application
from juloserver.julolog.julolog import JuloLog
from juloserver.partnership.constants import PartnershipTelcoScoringStatus, PartnershipProductFlow
from juloserver.partnership.models import PartnershipFlowFlag

sentry = get_julo_sentry_client()
logger = JuloLog(__name__)


class PartnershipTelcoScore(TelcoScore):

    def __init__(self, application: Application):
        super().__init__(application=application)

        if self.application:
            self.setting = PartnershipFlowFlag.objects.filter(
                partner=self.application.partner,
                name=PartnershipProductFlow.AGENT_ASSISTED,
            ).last()

    def determine_operator(self):
        fn_name = "PartnershipTelcoScore.determine_operator()"
        chosen_operator = None
        providers = self.setting.configs["provider"]

        # Because the configuration use national number start with `0` (zero)
        # we must change the input to this format. For this reason, return value has format
        # 0811-1234-1234, has dashes between section.
        phone = phonenumbers.parse(self.phone, "ID")
        phone = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.NATIONAL)

        for operator in providers:
            for prefix in providers[operator]["prefixes"]:
                if phone.startswith(prefix):
                    chosen_operator = operator
                    break

        possible_operators = [Telkomsel, Indosat, XL]
        for possible_operator in possible_operators:
            if chosen_operator == possible_operator.MNO.lower():
                return possible_operator

        logger.info(
            {
                'action': fn_name,
                'message': (
                    "Telco, The phone prefix not match any Telco TS configuration. "
                    "Or it being disabled."
                ),
                'application': self.application.id,
            }
        )
        raise TelcoException(
            "The phone prefix not match any Telco TS configuration. Or it being disabled."
        )

    def run_in_eligibility_check(self) -> str:
        """Telco scoring for leadgen agent assisted
        Run in step 2 - eligibility check agent assisted
        QOALA PARTNERSHIP - Leadgen Agent Assisted 21-11-2024
        """
        fn_name = "PartnershipTelcoScore.run_in_binary_check()"
        if not self.application:
            return PartnershipTelcoScoringStatus.APPLICATION_NOT_FOUND

        if not self.operator:
            try:
                providers = self.setting.configs["provider"]
                self.operator = self.determine_operator()

                operator_config = providers.get(self.operator.MNO.lower())
                if operator_config and not operator_config.get("is_active"):
                    return PartnershipTelcoScoringStatus.OPERATOR_NOT_ACTIVE

            except TelcoException as e:
                logger.error(
                    {
                        "action": fn_name,
                        "message": str(e),
                        "note": "Error determine operator",
                        "application_id": self.application.id,
                    }
                )
                return PartnershipTelcoScoringStatus.OPERATOR_NOT_FOUND

            except ReadTimeout:
                sentry.captureException()
                return PartnershipTelcoScoringStatus.OPERATOR_NOT_FOUND

        if not self.has_record():
            try:
                self.result = self.run(self.TYPE_SWAP_IN)

            except TelcoException as e:
                logger.error(
                    {
                        "action": fn_name,
                        "message": str(e),
                        "application_id": self.application.id,
                    }
                )
                return PartnershipTelcoScoringStatus.FAILED_TELCO_SCORING

            except ReadTimeout:
                sentry.captureException()
                return PartnershipTelcoScoringStatus.FAILED_TELCO_SCORING

        if not self.result:
            logger.info(
                {
                    'action': fn_name,
                    'message': "Telco, Not found any Telco score response.",
                    'application_id': self.application.id,
                }
            )
            return PartnershipTelcoScoringStatus.EMPTY_RESULT

        is_okay_swap_in = self._is_okay_swap_in()
        if is_okay_swap_in:
            self.assign_tag(self.TAG_STATUS_PASS_SWAP_IN)
            return PartnershipTelcoScoringStatus.PASSED_SWAP_IN
        else:
            self.assign_tag(self.TAG_STATUS_FAIL_SWAP_IN)
            return PartnershipTelcoScoringStatus.FAILED_SWAP_IN

    def _is_okay_swap_in(self) -> bool:
        fn_name = "PartnershipTelcoScore._is_okay_swap_in()"

        # Get threshold setting for partner application
        operator = self.operator.MNO.lower()
        provider_configs = self.setting.configs.get('provider', {}).get(operator, {})
        swap_in_threshold = provider_configs.get('swap_in_threshold', 750)

        bad_score = False
        score = self.result.score

        if self.result.scoring_type == TelcoClient.SCORE_RANGE_TYPE:
            scores = self.result.score.split("-")
            score = scores[0]

        if int(score) < swap_in_threshold:
            bad_score = True

        logger.info(
            {
                "action": fn_name,
                "application_id": self.application.id,
                "message": "Telco score: eligible_in_binary_check",
                "result": {
                    "score": score,
                    "bad_score": bad_score,
                },
            }
        )
        return not bad_score
