import re

from django.db.models import Q

from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.julo.constants import ScoreTag
from juloserver.julo.models import Application, CreditScore
from juloserver.bpjs.models import SdBpjsProfileScrape
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julolog.julolog import JuloLog

logger = JuloLog(__name__)


class BrickRevivalError(Exception):
    pass


class X105Revival:
    REASON_PASSED_COMPLETE = "BPJS Scrape Revival"
    REASON_PASSED_DIFF_COMPANY = "BPJS Scrape with different company name"

    SUCCESS_STATUS = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED

    def __init__(self, application_id):
        logger.info(
            {
                "message": "x105 Brick revival: class X105Revival initiated",
                "application_id": application_id,
            }
        )
        self.application = Application.objects.get(
            pk=application_id
        )
        self.brick = Brick(self.application)
        self.fraud = Fraud(self.application)
        self.change_reason = None

    def run(self):
        logger.info(
            {
                "message": "x105 Brick revival: class X105Revival->run",
                "application_id": self.application.id,
            }
        )

        if not self.allow_to_continue():
            return

        if self.pass_fraud():
            self.approve()

    def allow_to_continue(self):
        if not self.brick.is_balance_above_threshold:
            logger.info(
                {
                    "message": "x105 Brick revival: Stay because balance below threshold",
                    "application_id": self.application.id,
                }
            )
            return False

        if not self.brick.is_salary_above_threshold:
            logger.info(
                {
                    "message": "x105 Brick revival: Stay because salary below threshold",
                    "application_id": self.application.id,
                }
            )
            return False

        if self.is_c_low_credit_score():
            logger.info(
                {
                    "message": "x105 Brick revival: Stay because of C low credit score",
                    "application_id": self.application.id,
                }
            )
            return False

        return True

    def pass_fraud(self) -> bool:
        if not self.fraud.pass_liveness:
            status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR
            if (
                self.fraud.liveness_reason
                and 'failed video injection' in self.fraud.liveness_reason
            ):
                status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
            self.flag_for_fraud(
                status=status,
                reason=self.fraud.liveness_reason,
            )
            return False

        if not self.fraud.pass_mycroft:
            self.flag_for_fraud(
                status=ApplicationStatusCodes.APPLICATION_DENIED,
                reason=JuloOneChangeReason.MYCROFT_FAIL,
            )
            return False

        if not self.fraud.pass_blacklisted_asn:
            self.flag_for_fraud(reason=JuloOneChangeReason.BLACKLISTED_ASN_DETECTED)
            return False

        if not self.fraud.pass_general_check:
            self.flag_for_fraud(
                status=self.fraud.binary_check_handler.fail_status_code,
                reason=self.fraud.binary_check_handler.fail_change_reason,
            )
            return False

        if not self.fraud.pass_high_risk_asn:
            # No status change at all.
            # If return true, then it categorized as pass and move to x121.
            # If return false, then it categorized as not pass and stay at x105
            return True

        return True

    def flag_for_fraud(
        self, status=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD, reason=None
    ):
        logger.info(
            {
                "message": "x105 Brick revival: Flagging for fraud",
                "application_id": self.application.id,
                "status": status,
                "reason": reason,
            }
        )
        process_application_status_change(self.application, status, reason)

    def approve(self):
        logger.info(
            {
                "message": "x105 Brick revival: Approving application",
                "application_id": self.application.id,
            }
        )
        self.rescore()
        self.to_121()

    def set_approval_reason_movement(self):
        if (
            self.brick.has_same_company_name
            and self.brick.is_balance_above_threshold
            and self.brick.is_salary_above_threshold
        ):
            self.change_reason = self.REASON_PASSED_COMPLETE
        elif self.brick.is_salary_above_threshold and self.brick.is_balance_above_threshold:
            self.change_reason = self.REASON_PASSED_DIFF_COMPANY
        else:
            raise BrickRevivalError("No condition match to pass to x121.")

    def to_121(self):
        logger.info(
            {
                "message": "x105 Brick revival: Moving to 121",
                "application_id": self.application.id,
            }
        )
        self.set_approval_reason_movement()

        process_application_status_change(self.application, self.SUCCESS_STATUS, self.change_reason)

    def rescore(self):
        from juloserver.apiv2.services import rescore_application

        logger.info(
            {
                "message": "x105 Brick revival: Rescore",
                "application_id": self.application.id,
            }
        )
        rescore_application(self.application)
        return self

    def is_c_low_credit_score(self):
        credit_score = CreditScore.objects.filter(application=self.application).last()
        return credit_score.score_tag == ScoreTag.C_LOW_CREDIT_SCORE


class Brick:
    BALANCE_THRESHOLD = 4_000_000
    SALARY_THRESHOLD = 3_500_000

    def __init__(self, application: Application):
        logger.info(
            {
                "message": "x105 Brick revival: Brick initiated",
                "application_id": application.id,
                "thresholds": {"balance": self.BALANCE_THRESHOLD, "salary": self.SALARY_THRESHOLD},
            }
        )
        self.application = application

    @property
    def profile(self):
        """
        Get the Bpjs profile, if return multiple row pick the latest one
        which has real name inside it.
        """

        profile = SdBpjsProfileScrape.objects.filter(
            real_name__isnull=False,
            application_id=self.application.id
        ).last()
        logger.info(
            {
                "message": "x105 Brick revival: Getting the profile",
                "application_id": self.application.id,
                "profile": profile.id,
            }
        )
        return profile

    @property
    def company(self):
        """
        Get the BPJS company from the profile, if return multiple rows pick the latest payment date.
        """

        company = (
            self.profile.companies.filter(employment_status="Aktif")
            .filter(~Q(company__contains="Bukan Penerima Upah"))
            .order_by("last_payment_date")
            .last()
        )

        logger.info(
            {
                "message": "x105 Brick revival: Getting the company",
                "application_id": self.application.id,
                "company": company.id,
            }
        )
        return company

    @staticmethod
    def _sanitize_company(name: str):
        name = name.lower()
        return re.sub(r"^(pt|cv)|[^a-zA-Z0-9]|(tbk(.?))$", "", name)

    @property
    def has_same_company_name(self):
        sanitized_bpjs_company = self._sanitize_company(self.company.company)
        sanitized_app_company = self._sanitize_company(self.application.company_name)
        result = sanitized_bpjs_company == sanitized_app_company
        logger.info(
            {
                "message": "x105 Brick revival: Compare company name",
                "application_id": self.application.id,
                "bpjs_company": sanitized_bpjs_company,
                "app_company": sanitized_app_company,
                "is_same": result,
            }
        )
        return result

    @property
    def is_balance_above_threshold(self):
        balance = self.profile.total_balance
        has_above_threshold = int(balance) >= self.BALANCE_THRESHOLD
        logger.info(
            {
                "message": "x105 Brick revival: Check balance threshold",
                "application_id": self.application.id,
                "balance": balance,
                "result": has_above_threshold,
            }
        )
        return has_above_threshold

    @property
    def is_salary_above_threshold(self):
        salary = self.company.current_salary
        has_above_threshold = int(salary) >= self.SALARY_THRESHOLD
        logger.info(
            {
                "message": "x105 Brick revival: Check salary threshold",
                "application_id": self.application.id,
                "balance": salary,
                "result": has_above_threshold,
            }
        )
        return has_above_threshold


class Fraud:
    def __init__(self, application: Application):
        logger.info(
            {
                "message": "x105 Brick revival: Fraud class initiated",
                "application_id": application.id,
            }
        )
        self.application = application

        self.binary_check_handler = None
        self.liveness_reason = ""

    @property
    def pass_mycroft(self):
        from juloserver.application_flow.tasks import execute_mycroft

        is_pass_mycroft, is_mycroft_holdout, _ = execute_mycroft(self.application, True)
        not_passed = not is_pass_mycroft and not is_mycroft_holdout
        _is_passed = not not_passed
        logger.info(
            {
                "message": "x105 Brick revival: Check mycroft",
                "application_id": self.application.id,
                "pass": _is_passed,
            }
        )

        return _is_passed

    @property
    def pass_blacklisted_asn(self):
        from juloserver.fraud_security.services import blacklisted_asn_check

        blacklisted = blacklisted_asn_check(self.application)
        _is_passed = not blacklisted
        logger.info(
            {
                "message": "x105 Brick revival: Check blacklisted asn",
                "application_id": self.application.id,
                "pass": _is_passed,
            }
        )
        return _is_passed

    @property
    def pass_high_risk_asn(self):
        from juloserver.fraud_security.tasks import check_high_risk_asn

        risked = check_high_risk_asn(self.application.id)
        if risked is None:
            return False
        _is_passed = not risked

        logger.info(
            {
                "message": "x105 Brick revival: Check highrisk ASN",
                "application_id": self.application.id,
                "pass": _is_passed,
            }
        )
        return _is_passed

    @property
    def pass_general_check(self):
        """
        Inside this check, including check for blacklisted company,
        blacklisted postal code, and blacklist geohash5
        """
        from juloserver.fraud_security.binary_check import process_fraud_binary_check

        is_passed, handler = process_fraud_binary_check(
            self.application, source='bpjs|services|x105_revival|Fraud|pass_general_check'
        )
        self.binary_check_handler = handler

        logger.info(
            {
                "message": "x105 Brick revival: Check binary fraud",
                "application_id": self.application.id,
                "pass": is_passed,
            }
        )
        return is_passed

    @property
    def pass_liveness(self):
        from juloserver.liveness_detection.services import (
            check_application_liveness_detection_result,
        )
        from juloserver.liveness_detection.services import trigger_passive_liveness
        from juloserver.application_flow.services import check_liveness_detour_workflow_status_path

        is_detour = check_liveness_detour_workflow_status_path(
            self.application, status_new=self.application.status
        )
        if is_detour:
            # Skip the liveness check if detour
            logger.info(
                {
                    "message": "x105 Brick revival: Detour liveness",
                    "application_id": self.application.id,
                    "pass": True,
                }
            )
            return True

        trigger_passive_liveness(self.application)
        passed, reason = check_application_liveness_detection_result(self.application)
        self.liveness_reason = reason

        logger.info(
            {
                "message": "x105 Brick revival: Check pass liveness",
                "application_id": self.application.id,
                "pass": passed,
            }
        )
        return passed
