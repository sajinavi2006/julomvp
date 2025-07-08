from typing import Optional

import phonenumbers
import requests
import base64

from abc import ABC, abstractmethod
from django.conf import settings
from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Hash import SHA256
from Crypto.Signature.pss import MGF1
from requests.exceptions import ReadTimeout

from juloserver.application_flow.models import (
    TelcoScoringResult,
    ApplicationPathTagStatus,
    ApplicationPathTag,
)
from juloserver.cfs.services.core_services import get_pgood
from juloserver.julo.models import Application, FeatureSetting
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.application_flow.services import eligible_vendor_check_telco

sentry = get_julo_sentry_client()
logger = JuloLog(__name__)


class TelcoException(Exception):
    pass


class TelcoClient(ABC):
    MNO = None
    AUTH_ENDPOINT = None
    SCORE_ENDPOINT = None

    SCORE_EXACT_TYPE = 1
    SCORE_RANGE_TYPE = 2

    def __init__(self, application: Application):
        self.application = application
        self.phone = self.application.mobile_phone_1 if application else None
        self.encrypt_phone = True
        self.response = None

        if not self.MNO:
            logger.info(
                {
                    "message": "Telco, not found any mobile network operator.",
                    "operator": self.MNO,
                    "application": self.application.id,
                }
            )
            raise TelcoException("Not found any mobile network operator.")

        self.base_url = settings.TS_TELCO_SCORING[self.MNO]["BASE_URL"]
        self.mno_public_key = settings.TS_TELCO_SCORING[self.MNO]["PUBLIC_KEY"]
        self.mno_private_key = settings.TS_TELCO_SCORING[self.MNO]["PRIVATE_KEY"]
        self.client_code = settings.TS_TELCO_SCORING[self.MNO]["CLIENT_CODE"]
        self.username = settings.TS_TELCO_SCORING[self.MNO]["USERNAME"]
        self.password = settings.TS_TELCO_SCORING[self.MNO]["PASSWORD"]

    def login(self):
        logger.info(
            {
                "message": "Telco, getting access token.",
                "operator": self.MNO,
                "application": self.application.id,
            }
        )
        url = "{}{}".format(self.base_url, self.AUTH_ENDPOINT)
        response = requests.post(
            url,
            json={"user_name": self.username, "password": self.password},
            headers={'Content-Type': 'application/json'},
        )

        logger.info(
            {
                "message": "Telco, login",
                "operator": self.MNO,
                "application": self.application.id,
                "response": response.content,
            }
        )

        return response

    @property
    def bearer_token(self):
        logger.info(
            {
                "message": "Telco, trying to get access token.",
                "operator": self.MNO,
                "application": self.application.id,
            }
        )
        response = self.login()
        if response.status_code != 200:
            logger.info(
                {
                    "message": "Telco, failed to get access token.",
                    "operator": self.MNO,
                    "application": self.application.id,
                }
            )
            raise TelcoException("Failed to get access token.")

        token = response.json()["data"]["access_token"]
        return token

    @property
    def encrypted_phone(self):

        if not self.encrypt_phone:
            return self.phone

        cipher = PKCS1_OAEP.new(
            RSA.importKey(self.mno_public_key), SHA256, lambda x, y: MGF1(x, y, SHA256)
        )
        cipher_text = cipher.encrypt(self.phone.encode("utf-8"))

        b64 = base64.urlsafe_b64encode(cipher_text)
        return b64.decode('utf8')

    def get_credit_insight(self):
        logger.info(
            {
                "message": "Telco, trying get_credit_insight",
                "operator": self.MNO,
                "application": self.application.id,
            }
        )
        response = self.call_score_endpoint()
        logger.info(
            {
                "message": "Telco, get_credit_insight",
                "operator": self.MNO,
                "application": self.application.id,
                "response": response.content,
            }
        )
        self.response = response
        return response

    def get_score(self):
        logger.info(
            {
                "message": "Telco, trying to get score.",
                "application": self.application.id,
            }
        )
        response = self.get_credit_insight()
        if response.status_code != 200:
            logger.info(
                {
                    "message": "Telco, failed to get score",
                    "application": self.application.id,
                }
            )
            raise TelcoException("Failed to get score")

        json = response.json()
        if "score" in json["data"]:
            return self.SCORE_EXACT_TYPE, self.decrypt_score(json["data"]["score"])
        elif "score_range" in json["data"]:
            return self.SCORE_RANGE_TYPE, self.decrypt_score(json["data"]["score_range"])

    def decrypt_score(self, cipher_text):
        score_bytes = base64.urlsafe_b64decode(cipher_text)
        cipher = PKCS1_OAEP.new(
            RSA.importKey(self.mno_private_key), SHA256, lambda x, y: MGF1(x, y, SHA256)
        )
        score = cipher.decrypt(score_bytes)
        return score.decode('utf8')

    @abstractmethod
    def call_score_endpoint(self):
        pass


class FirstOperatorClientStructure:
    AUTH_ENDPOINT = "/authentication/users/login"
    SCORE_ENDPOINT = "/score_api/credit_score_requests/create/with_external_consent"

    def call_score_endpoint(self):
        url = "{}{}".format(self.base_url, self.SCORE_ENDPOINT)
        return requests.post(
            url,
            json={
                "client_code": self.client_code,
                "requested_msisdn": self.encrypted_phone,
                "external_source_id": str(self.application.application_xid),
            },
            headers={
                "Authorization": "Bearer {}".format(self.bearer_token),
                'Content-Type': 'application/json',
                "X-REQUEST-ID": str(self.application.application_xid),
            },
        )


class Telkomsel(FirstOperatorClientStructure, TelcoClient):
    MNO = "TELKOMSEL"


class Indosat(FirstOperatorClientStructure, TelcoClient):
    MNO = "INDOSAT"


class XL(TelcoClient):
    MNO = "XL"
    AUTH_ENDPOINT = "/auth/users/login"
    SCORE_ENDPOINT = "/score/v2/credit_score_requests/create"

    def call_score_endpoint(self):
        url = "{}{}".format(self.base_url, self.SCORE_ENDPOINT)
        payload = {
            "client_code": self.client_code,
            "requested_msisdns": {"xlaxiata": self.encrypted_phone},
            "external_source_id": str(self.application.application_xid),
        }
        headers = {
            "Authorization": "Bearer {}".format(self.bearer_token),
            'Content-Type': 'application/json',
            "X-REQUEST-ID": str(self.application.application_xid),
        }
        logger.info(
            {
                "message": "Telco, call score endpoint.",
                "operator": self.MNO,
                "application": self.application.id,
                "url": url,
                "payload": payload,
                "headers": headers,
            }
        )

        return requests.post(
            url,
            json=payload,
            headers=headers,
        )


class TelcoScore:
    TAG = "is_telco_pass"
    TAG_STATUS_PASS_SWAP_IN = 1
    TAG_STATUS_FAIL_SWAP_IN = 0
    TAG_STATUS_BAD_SWAP_OUT = -1

    TYPE_SWAP_IN = "swap_in"
    TYPE_SWAP_OUT = "swap_out"
    TYPE_HOLDOUT = "holdout"

    def __init__(self, application: Application):
        from juloserver.julo.constants import FeatureNameConst

        self.application = application
        self.phone = application.mobile_phone_1 if application else None
        self.setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.TELCO_SCORE, is_active=True
        ).last()
        self.score_type = None
        self.score = None
        self.operator = None
        self.result = None  # TelcoScoringResult
        self._heimdall = None

    def run(self, _type=""):
        if not self.application:
            return

        logger.info(
            {
                "message": "Telco, initiate telco score class",
                "application": self.application.id,
            }
        )

        if not self.setting:
            logger.info(
                {
                    "message": "Telco, feature setting not found or disabled.",
                    "application": self.application.id,
                }
            )
            return

        try:
            operator = self.determine_operator()
            self.operator = operator(self.application)
            score_type, score = self.operator.get_score()
            self.score_type = score_type
            self.score = score

            return self.store_response(self.operator.response, _type)
        except TelcoException as e:
            logger.error(
                {
                    "message": str(e),
                    "note": "TelcoScoring.run()",
                    "application_id": self.application.id,
                }
            )

    def determine_operator(self):
        chosen_operator = None
        providers = self.setting.parameters["provider"]

        # Because the configuration use national number start with `0` (zero)
        # we must change the input to this format. For this reason, return value has format
        # 0811-1234-1234, has dashes between section.
        phone = phonenumbers.parse(self.phone, "ID")
        phone = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.NATIONAL)

        for operator in providers:
            if not providers[operator]["is_active"]:
                continue

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
                "message": (
                    "Telco, The phone prefix not match any Telco TS configuration. "
                    "Or it being disabled."
                ),
                "application": self.application.id,
            }
        )
        raise TelcoException(
            "The phone prefix not match any Telco TS configuration. Or it being disabled."
        )

    def store_response(self, response, _type: Optional[str] = ""):
        from juloserver.application_flow.models import TelcoScoringResult

        if not response:
            logger.info(
                {
                    "message": "Telco, Not found any Telco score response.",
                    "application": self.application.id,
                }
            )
            raise TelcoException("Not found any Telco score response.")

        return TelcoScoringResult.objects.create(
            application_id=self.application.id,
            score=self.score,
            scoring_type=self.score_type,
            type=_type,
            raw_response=response.json(),
        )

    def run_in_105(self):
        if self.skip_execution_in_105():
            return False

        if not self.has_record():
            try:
                self.result = self.run(self.TYPE_SWAP_IN)

            except TelcoException as e:
                logger.error(
                    {
                        "message": str(e),
                        "note": "TelcoScoring.run_in_105()",
                        "application_id": self.application.id,
                    }
                )
                return False

            except ReadTimeout:
                sentry.captureException()
                return False

        if not self.operator:
            try:
                self.operator = self.determine_operator()
            except TelcoException as e:
                logger.error(
                    {
                        "message": str(e),
                        "note": "TelcoScoring.run_in_105()",
                        "application_id": self.application.id,
                    }
                )
                return False

            except ReadTimeout:
                sentry.captureException()
                return False

        operator = self.operator.MNO.lower()
        swap_in_threshold = self.setting.parameters["provider"][operator]["swap_in_threshold"]

        if not self.result:
            logger.info(
                {
                    "message": "Telco, Not found any Telco score response.",
                    "application_id": self.application.id,
                }
            )
            return False

        is_okay_in_105 = self._is_okay_in_105(swap_in_threshold)
        if is_okay_in_105:
            self.assign_tag(self.TAG_STATUS_PASS_SWAP_IN)
        else:
            self.assign_tag(self.TAG_STATUS_FAIL_SWAP_IN)

        return is_okay_in_105

    def skip_execution_in_105(self) -> bool:
        if not self.application.is_julo_one():
            return True

        if self.application.status != 105:
            return True

        pgood = get_pgood(self.application.id)
        is_pgood_okay = 0.75 <= pgood < 0.85
        eligible_binary = eligible_vendor_check_telco(self.application.id)
        if self._is_fdc_found() or not eligible_binary or not is_pgood_okay:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: not eligible to swap in",
                    "result": {
                        "is_pgood_okay": is_pgood_okay,
                        "is_fdc_found": self._is_fdc_found(),
                        "eligible_binary": eligible_binary,
                    },
                }
            )
            return True

        # Check setting
        if self.setting is None:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: setting not found",
                }
            )
            return True

        last_digit_id = int(str(self.application.id)[-1:])
        if last_digit_id not in self.setting.parameters['application_id']:
            logger.info(
                {
                    "message": "Telco, Last digit is not listed.",
                    "application_id": self.application.id,
                }
            )
            return True

    def _is_okay_in_105(self, swap_in_threshold) -> bool:
        bad_score = False
        score = self.result.score

        if self.result.scoring_type == TelcoClient.SCORE_RANGE_TYPE:
            scores = self.result.score.split("-")
            score = scores[0]

        if int(score) < swap_in_threshold:
            bad_score = True

        logger.info(
            {
                "application_id": self.application.id,
                "message": "Telco score: eligible_in_105",
                "result": {
                    "score": score,
                    "bad_score": bad_score,
                },
            }
        )
        return not bad_score

    def run_in_130_swapout(self):
        logger.info(
            {
                "application_id": self.application.id,
                "message": "Telco score: initiate run_in_130_swapout",
            }
        )

        if self.skip_execution_in_130():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: skipped execution in 130",
                }
            )
            return

        if self._is_bad_in_130():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: bad result in 130",
                }
            )
            self.assign_tag(self.TAG_STATUS_BAD_SWAP_OUT)

    def _is_bad_in_130(self) -> bool:

        # Check Non FDC
        if self._is_fdc_found():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: _is_bad_in_130",
                    "result": {
                        "non_fdc": False,
                    },
                }
            )
            return False

        # Check NON-FDC: pgood
        if self.heimdall.pgood < 0.85:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: _is_bad_in_130",
                    "result": {
                        "in_pgood_threshold": False,
                    },
                }
            )
            return False

        # Check for the Telco Score
        bad_score = False
        if not self.has_record():
            self.result = self.run(self.TYPE_SWAP_OUT)

        if not self.operator:
            try:
                self.operator = self.determine_operator()
            except TelcoException as e:
                logger.error(
                    {
                        "message": str(e),
                        "note": "TelcoScoring._is_bad_in_130()",
                        "application_id": self.application.id,
                    }
                )
                return False

        operator = self.operator.MNO.lower()
        swap_out_threshold = self.setting.parameters["provider"][operator]["swap_out_threshold"]

        if self.result.scoring_type == TelcoClient.SCORE_RANGE_TYPE:
            scores = self.result.score.split("-")
            bottom_score = scores[0]
            if int(bottom_score) < swap_out_threshold:
                bad_score = True

        elif self.result.scoring_type == TelcoClient.SCORE_EXACT_TYPE:
            score = int(self.result.score)
            if score < swap_out_threshold:
                bad_score = True

        logger.info(
            {
                "application_id": self.application.id,
                "message": "Telco score: _is_bad_in_130",
                "result": {
                    "bad_score": bad_score,
                },
            }
        )

        return bad_score

    def skip_execution_in_130(self, _async=True) -> bool:

        if (
            not self.application.is_julo_one()
            or not self.application.is_julo_one_ios()
        ):
            return True

        if not _async and self.application.status != 130:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: not in 130 when not async",
                }
            )
            return True

        # Check setting
        if self.setting is None:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: setting not found",
                }
            )
            return True

        if (
            not eligible_vendor_check_telco(self.application.id)
            and not self.application.is_julo_one_ios()
        ):
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: has no eligible check match",
                }
            )
            return True

        # Check existing application path tag
        if self.has_pass_telco_check_tag():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Telco score: already pass telco check",
                }
            )
            return True

        # Check bad score
        return False

    def tag(self, status: int):
        statuses = ApplicationPathTagStatus.objects.filter(application_tag=self.TAG, status=status)
        return ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status__in=statuses
        )

    def has_pass_telco_check_tag(self):
        return self.tag(self.TAG_STATUS_PASS_SWAP_IN).exists()

    def assign_tag(self, status):
        from juloserver.application_flow.tasks import application_tag_tracking_task

        application_tag_tracking_task.delay(self.application.id, None, None, None, self.TAG, status)
        logger.info(
            {
                "application_id": self.application.id,
                "message": "Telco score: Queued application tag",
                "tag": self.TAG,
                "status": status,
            }
        )

    def has_record(self):
        if self.result is None:
            self.result = TelcoScoringResult.objects.filter(
                application_id=self.application.id
            ).last()

        if self.result:
            return True

        return False

    @property
    def heimdall(self):
        from juloserver.account.services.credit_limit import get_credit_model_result

        if self._heimdall is None:
            self._heimdall = get_credit_model_result(self.application)
        return self._heimdall

    def _is_fdc_found(self):
        return self.heimdall.has_fdc
