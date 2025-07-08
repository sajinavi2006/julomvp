import datetime
import json
import urllib.parse
from abc import abstractmethod, ABC
from base64 import b64decode, b64encode
from json import JSONDecodeError

import phonenumbers
import requests
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from Crypto.Util.Padding import pad, unpad
from django.conf import settings
from django.db import transaction
from django.db.models import Q

from juloserver.apiv2.models import AutoDataCheck, PdCreditModelResult
from juloserver.application_flow.models import (
    ShopeeScoringFailedLog,
    ApplicationPathTagStatus,
    ApplicationPathTag,
)
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Application, FeatureSetting, CreditScore
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julolog.julolog import JuloLog
from juloserver.application_flow.constants import CacheKey
from juloserver.monitors.notifications import send_slack_bot_message

sentry = get_julo_sentry_client()

logger = JuloLog()


class ShopeeException(Exception):
    pass


class ShopeeScoring:
    MAX_RETRY = 3

    def __init__(self, nik, phone, encrypt=True, flow_no=None):
        """
        Data would be having information of ktp_no and msisdn
        """

        self.customer_id = settings.SCORING_CUSTOMER_ID
        self.app_id = settings.SCORING_APP_ID
        self.key = settings.SCORING_KEY
        self.url = settings.SCORING_URL
        self.julo_private_key = settings.SCORING_JULO_PRIVATE_KEY
        self.julo_public_key = settings.SCORING_JULO_PUBLIC_KEY
        self.scoring_public_key = settings.SCORING_PUBLIC_KEY
        self.flow_no = flow_no

        self.is_encrypted = encrypt
        phone_parse = phonenumbers.parse(phone, "ID")
        phone = phonenumbers.format_number(phone_parse, phonenumbers.PhoneNumberFormat.E164)
        self.data = {"ktp_no": nik, "msisdn": phone[1:]}
        self._encrypted_data = None

        self._encoding = "utf-8"
        self._start_at = datetime.datetime.now()
        self._sign = None
        self._iv = bytes(self.key[:16], self._encoding)

        logger.info(
            {
                "message": "ShopeeScoring class initialized.",
                "application_id": self.flow_no,
            }
        )

    def encrypt_data(self, data=None):
        if data is None:
            data = self.data

        cipher = AES.new(self.key.encode(self._encoding), AES.MODE_CBC, iv=self._iv)

        data = json.dumps(data).encode(self._encoding)
        cipher_text = cipher.encrypt(pad(data, AES.block_size))
        self._encrypted_data = b64encode(cipher_text).decode(self._encoding)

        logger.info({"message": "Shopee: Data encrypted with AES.", "application_id": self.flow_no})
        return self._encrypted_data

    @property
    def encrypted_data(self):
        """"""
        if self._encrypted_data is None:
            self.encrypt_data()

        return self._encrypted_data

    def decrypt_data(self, encrypted_data):
        cipher = AES.new(bytes(self.key, self._encoding), AES.MODE_CBC, self._iv)
        encrypted_data = b64decode(encrypted_data)
        plain = unpad(cipher.decrypt(encrypted_data), AES.block_size).decode(self._encoding)

        logger.info({"message": "Shopee: Data decrypted with AES.", "application_id": self.flow_no})

        return json.loads(plain)

    def sign(self):
        parse_with_quotes = True
        if parse_with_quotes:
            payloads = []
            for key in self._payload():
                val = self._payload()[key]
                if isinstance(val, str):
                    payloads.append(f'{key}="{val}"')
                elif isinstance(val, bool):
                    val = str(val).lower()
                    payloads.append(f"{key}={val}")
                else:
                    payloads.append(f"{key}={val}")
            payload = "&".join(payloads)
        else:
            payload = urllib.parse.urlencode(self._payload())

        signer = PKCS1_v1_5.new(RSA.importKey(b64decode(self.julo_private_key)))
        hashed = SHA256.new(payload.encode(self._encoding))
        self._sign = b64encode(signer.sign(hashed)).decode(self._encoding)

        logger.info(
            {
                "message": "Shopee: Successfully generate signature.",
                "application_id": self.flow_no,
            }
        )

        return self._sign

    def _payload(self):
        """"""
        raw = {
            "api_name": "query.blacklist",
            "app_id": self.app_id,
            "customer_id": self.customer_id,
            "encrypt": self.is_encrypted,
            "encrypt_type": "AES-CBC" if self.is_encrypted else "",
            "flow_no": str(self.flow_no),
            "sign_type": "rsa-sha256",
            "timestamp": int(round(self._start_at.timestamp() * 1000)),
            "version": "1.0",
            "biz_data": self.encrypted_data if self.is_encrypted else json.dumps(self.data),
        }

        return dict(sorted(raw.items()))

    def to_curl(self):
        command = (
            'curl -H "Content-Type: application/json"'
            ' -XPOST "https://api-tob.uat.scoring.co.id/openapi/v1/gateway" -d'
        )
        payload = json.dumps(self.payload)
        return f"{command} '{payload}'"

    @property
    def payload(self):
        _payload = self._payload().copy()
        _payload["sign"] = self.sign()
        return dict(sorted(_payload.items()))

    @sentry.capture_exceptions
    def call(self):
        from juloserver.julo.exceptions import BadStatuses

        logger.info({"message": "Try to call Shopee API...", "application_id": self.flow_no})

        loop = True
        retry_cnt = 0
        result = None
        exception = None
        while retry_cnt < self.MAX_RETRY and loop:
            payload = self.payload
            try:
                logger.info({"url": f"{self.url}/openapi/v1/gateway", "payload": payload})
                response = requests.post(
                    f"{self.url}/openapi/v1/gateway",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            except requests.exceptions.ConnectionError as e:
                sentry.captureMessage(e)
                logger.warning(
                    {
                        "application_id": self.flow_no,
                        "message": "Shopee scoring connection error.",
                    }
                )
                ShopeeScoringFailedLog.objects.create(
                    method="POST",
                    application_id=self.flow_no,
                    request=json.dumps(payload),
                    response='Connection error',
                    latency=(datetime.datetime.now() - self._start_at).total_seconds(),
                )
                retry_cnt += 1
                continue

            if response.status_code in [200, 201]:
                logger.info("Shopee scoring data fetched successfully.")
                result = response.json()
                if str(result['code']) not in ['5000', '5001'] and str(result['biz_code']) not in [
                    '999999'
                ]:
                    loop = False
                    retry_cnt += 1
                    continue

            if response.status_code == 403:
                logger.warning(
                    {
                        "application_id": self.flow_no,
                        "message": (
                            "Shopee: Your public Ip address is not whitelisted by Scoring team."
                        ),
                    }
                )
                ShopeeScoringFailedLog.objects.create(
                    method="POST",
                    application_id=self.flow_no,
                    request=json.dumps(payload),
                    response=response.content,
                    status_code=response.status_code,
                    latency=(datetime.datetime.now() - self._start_at).total_seconds(),
                )

                # raise BadStatuses("Your public Ip address is not whitelisted by Scoring team.")
                exception = BadStatuses(
                    "Your public Ip address is not whitelisted by Scoring team."
                )
                retry_cnt += 1
                continue

            logger.warning(
                {
                    "application_id": self.flow_no,
                    "message": "Shopee scoring request failed.",
                }
            )
            ShopeeScoringFailedLog.objects.create(
                application_id=self.flow_no,
                request=json.dumps(payload),
                response=response.content,
                method="POST",
                status_code=response.status_code,
                latency=(datetime.datetime.now() - self._start_at).total_seconds(),
            )
            exception = BadStatuses("Request failed")
            retry_cnt += 1
            continue

        if result is not None:
            return result

        if exception is not None:
            raise exception


class ShopeeAbstract(ABC):
    TYPE_WHITELIST = "whitelist"
    TYPE_BLACKLIST = "blacklist"
    TYPE_HOLDOUT = "holdout"

    def __init__(self, application: Application):
        self.application = application
        self.scoring = None
        self.shopee_result = {}
        self.hit_reason_code = None
        self._biz_data = {}
        self._biz_code = None

    @abstractmethod
    def skip_execution(self) -> bool:
        pass

    @abstractmethod
    def decide(self) -> None:
        pass

    @abstractmethod
    def check_shopee(self):
        pass

    @staticmethod
    def _is_valid_json(string):
        try:
            json.loads(string)
        except ValueError:
            return False

        return True

    def call_and_store_to_db(self, scoring_type):
        from juloserver.application_flow.models import ShopeeScoring as Scoring

        scoring = ShopeeScoring(
            nik=self.application.ktp,
            phone=self.application.mobile_phone_1,
            flow_no=self.application.id,
        )

        # The Result is json object from Shopee
        start = datetime.datetime.now()
        result = scoring.call()
        end = datetime.datetime.now()
        diff = end - start

        try:
            biz_data = json.loads(result['biz_data'])
            hit_reason_code = int(biz_data['hit_reason_code'])
        except (JSONDecodeError, TypeError):
            logger.warning(
                {
                    "message": "shopee" + scoring_type + "Fail to load json data.",
                    "application_id": self.application.id,
                }
            )
            hit_reason_code = None
        except Exception as e:
            logger.warning(
                {
                    "message": "shopee" + scoring_type + ": Exception occurred",
                    "exception": str(e),
                    "application_id": self.application.id,
                }
            )
            hit_reason_code = None
        finally:
            if result and 'biz_data' in result:
                result_biz_data = result['biz_data']
                if self._is_valid_json(result_biz_data):
                    biz_data = json.loads(result_biz_data)
                else:
                    biz_data = result_biz_data
            else:
                biz_data = {}

        self.shopee_result = result
        self._biz_data = biz_data
        if "biz_code" in result:
            self._biz_code = result['biz_code']
        self.hit_reason_code = hit_reason_code

        # Store the result inside the table
        self.scoring = Scoring.objects.create(
            application=self.application,
            code=result['code'],
            msg=result['msg'],
            sign_type=result['sign_type'],
            sign=result['sign'],
            encrypt=result['encrypt'],
            encrypt_type=result['encrypt_type'],
            flow_no=result['flow_no'],
            timestamp=datetime.datetime.fromtimestamp(result['timestamp'] / 1000),
            biz_code=result['biz_code'],
            biz_msg=result['biz_msg'],
            biz_data=biz_data,
            latency=diff.total_seconds(),  # Will has return value like 4.123456
            type=scoring_type,
        )

    @property
    def biz_code(self):
        if self._biz_code is None:
            from juloserver.application_flow.models import ShopeeScoring as Scoring

            # todo: efficiency query!
            self.scoring = Scoring.objects.filter(application=self.application).last()
            self._biz_code = self.scoring.biz_code

        return int(self._biz_code)

    @property
    def is_blacklisted(self) -> bool:
        if self.biz_code != 200000:
            return False

        if "list_type" in self._biz_data and self._biz_data["list_type"] == 1:
            return True

        return False

    @property
    def is_greylisted(self) -> bool:
        if self.biz_code != 200000:
            return False

        if "list_type" in self._biz_data and self._biz_data["list_type"] == 2:
            return True

        return False

    @property
    def is_whitelisted(self) -> bool:
        """Because Shopee doesn't explicitly say whitelist. So we use biz_code 200000
        and compare with blacklist and whitelist. Actually, we can check from `hit_flag` as well.
        """
        if self.biz_code != 200000:
            return False

        if not self.is_blacklisted and not self.is_greylisted:
            return True

        return False

    def reject(self, reason, to=ApplicationStatusCodes.APPLICATION_DENIED):
        from juloserver.julo.services import process_application_status_change

        return process_application_status_change(self.application, to, reason)

    def approve(self, reason, to):
        from juloserver.julo.services import process_application_status_change

        return process_application_status_change(self.application, to, reason)


class ShopeeBlacklist(ShopeeAbstract):
    def __init__(
        self, application: Application, new_status, change_reason, bypass_swapout_dukcapil=False
    ):
        super().__init__(application)

        self.new_status = new_status
        self.change_reason = change_reason

        self._configuration = None
        self._raise_error = True
        self._reuse = None
        self.bypass_swapout_dukcapil = bypass_swapout_dukcapil

    def run(self) -> bool:

        logger.info({"application_id": self.application.id, "message": "shopee blacklist: Running"})

        if self.skip_execution():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "shopee blacklist: skipping execution",
                }
            )

            return False

        self.check_shopee()

        return self.decide()

    def skip_execution(self) -> bool:
        return not self.should_continue()

    def should_continue(self) -> bool:

        if not self.application.is_julo_one() and not self.application.is_julo_one_ios():
            logger.info(
                {
                    "message": "shopee blacklist: Workflow not J1",
                    "application_id": self.application.id,
                }
            )
            return False

        if self.application.status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD:
            return False

        if self.application.status != ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL:
            logger.warning(
                {
                    "message": f"Application status is not 130 but {self.application.status}",
                    "application_id": self.application.id,
                    "status": self.application.status,
                }
            )

            # Handle race condition when entry level already change the status not in 130
            # anymore
            return False

        if not self._has_active_configuration():
            logger.warning(
                {
                    "message": "Shopee blacklist: Feature setting for Shopee scoring is not exists",
                    "application_id": self.application.id,
                    "status": self.application.status,
                }
            )
            return False

        if not self._in_heimdall_threshold():
            return False

        return True

    def check_shopee(self):
        from juloserver.application_flow.models import ShopeeScoring as Scoring

        self.scoring = Scoring.objects.filter(application=self.application).last()
        if self.scoring:
            logger.info(
                {
                    "message": "shopee blacklist: Found the Shopee record in db",
                    "application_id": self.application.id,
                }
            )
            self._reuse = True
            biz_data = self.scoring.biz_data
            if biz_data and 'hit_reason_code' in biz_data:
                self.hit_reason_code = int(biz_data['hit_reason_code'])
                return
            else:
                return

        self.call_and_store_to_db(self.TYPE_BLACKLIST)

    def decide(self) -> bool:
        from juloserver.utilities.services import HoldoutManager
        from juloserver.application_flow.services2.bank_statement import BankStatementClient
        from juloserver.julo.models import ExperimentSetting
        from juloserver.julo.constants import ExperimentConst

        tag = BankStatementClient.APPLICATION_TAG
        application_path_tag_status = ApplicationPathTagStatus.objects.filter(
            application_tag=tag, status=BankStatementClient.TAG_STATUS_SUCCESS
        ).last()
        bank_statement_success = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status=application_path_tag_status,
        ).exists()

        lbs_bypass_setting = ExperimentSetting.objects.filter(
            is_active=True, code=ExperimentConst.LBS_130_BYPASS
        ).last()
        swapout_dukcapil_bp_quota = (
            lbs_bypass_setting.criteria.get("limit_total_of_application_swap_out_dukcapil", 0)
            if lbs_bypass_setting
            else 0
        )

        redis_client = get_redis_client()
        swapout_dukcapil_bp_count = redis_client.get(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER)
        if not swapout_dukcapil_bp_count:
            redis_client.set(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER, 0)
            swapout_dukcapil_bp_count = 0
        else:
            swapout_dukcapil_bp_count = int(swapout_dukcapil_bp_count)

        if (
            not self.bypass_swapout_dukcapil
            and bank_statement_success
            and swapout_dukcapil_bp_count < swapout_dukcapil_bp_quota
        ):
            redis_client.increment(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER)
            swapout_dukcapil_bp_quota_left = (
                swapout_dukcapil_bp_quota - swapout_dukcapil_bp_count - 1
            )
            if swapout_dukcapil_bp_quota_left in (0, 25, 50, 75, 100):
                slack_channel = "#alerts-backend-onboarding"
                mentions = "<@U04EDJJTX6Y> <@U040BRBR5LM>\n"
                title = ":alert: ===LBS Bypass Quota Alert=== :alert: \n"
                message = (
                    "Swapout Dukcapil Bypass Quota : "
                    + str(swapout_dukcapil_bp_quota_left)
                    + " left\n"
                )
                text = mentions + title + message
                if settings.ENVIRONMENT != 'prod':
                    text = "*[" + settings.ENVIRONMENT + " notification]*\n" + text
                send_slack_bot_message(slack_channel, text)
            self.bypass_swapout_dukcapil = True

        if self.hit_reason_code in self.configuration.parameters['blacklist_reason_code']:
            logger.info(
                {
                    "message": "shopee blacklist: Match with blacklist reason code",
                    "application_id": self.application.id,
                }
            )
            with HoldoutManager(
                percentage=int(self.configuration.parameters['holdout']['percentage']),
                total_request=int(self.configuration.parameters['holdout']['per_requests']),
                key=CacheKey.SHOPEE_REJECT_HOLDOUT_COUNTER,
            ) as holdout:
                log = {
                    'holdout': {
                        'config': self.configuration.parameters['holdout'],
                        'counter': holdout.counter,
                        'variables': holdout.variables,
                    }
                }
                from juloserver.application_flow.services import eligible_to_offline_activation_flow

                if holdout.counter in holdout.list_left and not self.bypass_swapout_dukcapil:
                    if not eligible_to_offline_activation_flow(self.application):
                        changed = self.reject(reason=JuloOneChangeReason.SHOPEE_SCORE_NOT_PASS)
                        reason = "Blacklisted or greylisted{}.".format(
                            " (reuse)" if self._reuse else ""
                        )
                    else:
                        changed = False
                        reason = 'Offline Activation Flow'

                    self.scoring.update_safely(is_passed=False, log=log, passed_reason=reason)
                    return changed

        if (
            self.application.status != self.new_status
            and self.application.status != ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        ):
            changed = self.approve(to=self.new_status, reason=self.change_reason)
            reason = "Not blacklisted nor greylisted{}.".format(" (reuse)" if self._reuse else "")
            self.scoring.update_safely(is_passed=True, passed_reason=reason)
            return changed

    @property
    def configuration(self):
        if self._configuration is None:
            self._fetch_configuration()

        return self._configuration

    def _has_active_configuration(self) -> bool:
        if self.configuration is None:
            return False

        return True

    def _fetch_configuration(self):
        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SHOPEE_SCORING, is_active=True
        ).last()

        if setting:
            self._configuration = setting
            return setting

        logger.warning(
            {
                "message": "Shopee blacklist: Feature setting for Shopee blacklist is not exists",
                "application_id": self.application.id,
            }
        )

        return

    def _in_heimdall_threshold(self):
        from juloserver.account.services.credit_limit import get_credit_model_result

        if 'pgood_threshold' not in self.configuration.parameters:
            error_msg = (
                "Shopee blacklist: Pgood threshold or last application id is not exists in setting."
            )
            logger.warning(
                {
                    "message": error_msg,
                    "application_id": self.application.id,
                    "status": self.application.status,
                }
            )
            if self._raise_error:
                raise ShopeeException(error_msg)
            return False

        threshold = float(self.configuration.parameters['pgood_threshold'])
        credit_model = get_credit_model_result(self.application)
        if credit_model.pgood > threshold:
            logger.warning(
                {
                    "application_id": self.application.id,
                    "status": self.application.status,
                    "message": "Shopee blacklist: pgood threshold is not match.",
                }
            )
            return False

        return True


class ShopeeWhitelist(ShopeeAbstract):
    BINARY_DYNAMIC_CHECK_KEY = "dynamic_check_for_shopee_whitelist"
    CREDIT_MATRIX_PARAMETER = 'feature:shopee_whitelist'
    CREDIT_MATRIX_TYPE = "julo1"
    EXCEPTION_MESSAGE_NO_MATCHED_CRITERIA = (
        "Total matched criteria is zero in matched_criteria method."
    )

    def __init__(self, application, stay: bool = False):
        """
        :param application:
        :param stay: bool. Whether the application stays in original status,
        or move to another status
        """
        super().__init__(application)

        self._configuration = None
        self._matched_criteria = None
        self._stay = stay
        self._credit_matrix = None

        self.fdc = ""
        self.heimdall = None
        self.mycroft = None
        self.is_premium_area = False
        self.autodebit = None

    def run(self) -> bool:

        logger.info({"application_id": self.application.id, "message": "shopee whitelist: Running"})

        if self.skip_execution():
            return False

        self.check_shopee()

        if self.is_whitelisted:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "shopee whitelist: Whitelisted for this application.",
                }
            )
            return self.decide()

        # For application that not in whitelists, there is two possibility.
        # First, reject to x135. Second stay the status where they are before.
        logger.info(
            {
                "application_id": self.application.id,
                "message": "shopee whitelist: Not in whitelist.",
            }
        )
        if not self._stay:
            self.reject_application()

        return False

    def _fetch_configuration(self):
        """
        Configuration value example:
        {
            "criteria_1": {
                "fdc": "pass",
                "tag": "xxx",
                "limit": 12345,
                "mycroft": {
                    "bottom_threshold": 0.8,
                    "upper_threshold": 1.0,
                },
                "heimdall": {
                    "bottom_threshold": 0.45,
                    "upper_threshold": 0.51,
                }
            }
        }
        """
        from juloserver.julo.models import ExperimentSetting
        from juloserver.julo.constants import ExperimentConst

        parameter = None
        if self.application.status < 190:
            parameter = Q(is_active=True)

        query_set = ExperimentSetting.objects.filter(
            code=ExperimentConst.SHOPEE_WHITELIST_EXPERIMENT
        )

        if parameter is not None:
            query_set = query_set.filter(parameter)

        self._configuration = query_set.last()

        return self._configuration

    @property
    def configuration(self):
        if self._configuration is None:
            self._fetch_configuration()

        return self._configuration

    def _has_active_configuration(self) -> bool:
        if self.configuration is None:
            return False

        return True

    def should_continue(self) -> bool:
        """Determine if the conditions match the rules."""
        if not self.application.is_regular_julo_one():
            return False

        # If not 105 should be skipped.
        if self.application.status != ApplicationStatusCodes.FORM_PARTIAL:
            return False

        if not self._has_active_configuration():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "shopee whitelist: Does not have active configuration",
                }
            )
            return False

        if self.fdc == "" and self.heimdall is None and self.mycroft is None:
            self._fetch_fdc_heimdall_and_mycroft()

        # Choose the autodebit or shopee whitelist.
        # If last digit of application id is even, then it is autodebit.
        # The otherwise it is shopee whitelist.
        if self.autodebit and self.autodebit.has_pending_tag:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "shopee whitelist: Autodebet has pending tags.",
                    "criteria": self.matched_criteria,
                }
            )
            return False

        # Check the special dynamic check from ana
        if not self._pass_shopee_whitelist_dynamic_check():
            return False

        try:
            if not self._still_has_quota(self.matched_criteria):
                logger.info(
                    {
                        "application_id": self.application.id,
                        "message": "shopee whitelist: Quota exhausted.",
                    }
                )
                return False
        except ShopeeException:
            return False

        return True

    def skip_execution(self) -> bool:
        return not self.should_continue()

    @property
    def matched_criteria(self):

        if self._matched_criteria is not None:
            logger.info(
                {
                    "message": "shopee whitelist: Found matched criteria.",
                    "application_id": self.application.id,
                }
            )
            return self._matched_criteria

        logger.info(
            {
                "message": "shopee whitelist: Start looking matched criteria.",
                "application_id": self.application.id,
            }
        )

        criteria = self.configuration.criteria
        results = {}

        for key in criteria:
            results[key] = self._is_pass_criterion(criteria[key])

        if self._total_matched(results) == 0:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": (
                        "shopee whitelist: {}".format(self.EXCEPTION_MESSAGE_NO_MATCHED_CRITERIA)
                    ),
                }
            )
            raise ShopeeException(self.EXCEPTION_MESSAGE_NO_MATCHED_CRITERIA)

        if self._total_matched(results) > 1:
            # todo: send real time notification to PM that they has wrong configuration!!!
            logger.error(
                {
                    "application_id": self.application.id,
                    "message": (
                        "shopee whitelist: There is more 1 condition that match in criteria."
                    ),
                }
            )
            raise ShopeeException("There is more 1 condition that match in criteria.")

        self._matched_criteria = [key for key, value in results.items() if value is True][0]
        return self._matched_criteria

    def check_shopee(self):
        from juloserver.application_flow.models import ShopeeScoring as Scoring

        self.scoring = Scoring.objects.filter(application=self.application).last()
        if self.scoring:
            logger.info(
                {
                    "message": "shopee whitelist: Found the Shopee record in db",
                    "application_id": self.application.id,
                }
            )
            self._biz_code = self.scoring.biz_code
            self._biz_data = self.scoring.biz_data
            return

        self.call_and_store_to_db(self.TYPE_WHITELIST)

    def _fetch_fdc_heimdall_and_mycroft(self):

        # Fdc will return `pass` or `not-found``
        if self.fdc == "":
            self.fdc = self._fetch_fdc_state()

        # heimdall and mycroft will return decimal value
        if self.heimdall is None:
            self.heimdall = self._fetch_heimdall_score()

        if self.mycroft is None:
            self.mycroft = self._fetch_mycroft_score()

    def _fetch_fdc_state(self):
        """
        Get the FDC state; actually there are 3 states, pass FDC,
        not-found, and bad FDC. We are only using pass and not-found.
        """

        # Check the binary first, if not pass, then raise an error.
        # If it has bad-FDC should not go here.
        fdc_binary = AutoDataCheck.objects.filter(
            application_id=self.application.id, data_to_check="fdc_inquiry_check"
        ).last()
        if fdc_binary.is_okay is False:
            logger.warning(
                {
                    "message": 'shopee whitelist: This application has failed fdc binary!',
                    "application_id": self.application.id,
                }
            )
            return "fail"

        # If the binary check is good, check the FDC inquiry loan. If there is no record, means
        #  FDC is not found
        credit_model = PdCreditModelResult.objects.filter(application_id=self.application.id).last()

        if credit_model.has_fdc:
            return "pass"

        return "not_found"

    def _fetch_heimdall_score(self):
        from juloserver.apiv2.models import PdCreditModelResult

        credit_model = PdCreditModelResult.objects.filter(application_id=self.application.id).last()
        return credit_model.pgood

    def _fetch_mycroft_score(self):
        from juloserver.ana_api.models import PdApplicationFraudModelResult

        mycroft = PdApplicationFraudModelResult.objects.filter(
            application_id=self.application.id
        ).last()
        return mycroft.pgood

    def _fetch_credit_matrix(self):
        from juloserver.account.services.credit_limit import (
            get_salaried,
            get_credit_matrix,
            get_transaction_type,
        )

        criteria = self.configuration.criteria
        criterion = criteria[self.matched_criteria]

        logger.info(
            {
                "message": "shopee whitelist: Fetching credit matrix",
                "parameter": {
                    "heimdall": self.heimdall,
                    "criterion": criterion,
                    "matched": self.matched_criteria,
                },
            }
        )

        params = {
            "min_threshold__lte": self.heimdall,
            "max_threshold__gte": self.heimdall,
            "credit_matrix_type": self.CREDIT_MATRIX_TYPE,
            "is_salaried": get_salaried(self.application.job_type),
            "is_premium_area": self.is_premium_area,
        }

        additional_params = self.build_additional_credit_matrix_parameters()
        params = {**params, **additional_params}

        cm = get_credit_matrix(
            params,
            get_transaction_type(),
            parameter=Q(parameter=self.CREDIT_MATRIX_PARAMETER),
        )

        if cm is None:
            logger.error(
                {
                    "application_id": self.application.id,
                    "message": (
                        "shopee whitelist: "
                        "The Shopee configuration value is different from credit matrix!"
                    ),
                }
            )
            raise ShopeeException("The Shopee configuration value is different from credit matrix!")

        self._credit_matrix = cm

    @property
    def credit_matrix(self):
        if self._credit_matrix is None:
            logger.info(
                {
                    "message": "shopee whitelist: Credit matrix not found, try to fetch.",
                    "application_id": self.application.id,
                }
            )
            self._fetch_credit_matrix()

        return self._credit_matrix

    def reject_application(self):
        return self.reject(reason="rejected by Shopee whitelist")

    def approve_application(self):
        return self.approve(to=120, reason=JuloOneChangeReason.PASS_SHOPEE_WHITELIST)

    def decide(self) -> bool:

        with transaction.atomic():
            self._decrease_quota()
            self._assign_tag()
            self._pass_shopee_score()

            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "shopee whitelist: Increase quota, and assign tag.",
                    "criteria": self.matched_criteria,
                }
            )

        # Return that process executed
        return True

    def _still_has_quota(self, criterion) -> bool:
        criteria = self.configuration.criteria
        try:
            count = json.loads(self.configuration.action)[criterion]
            limit = criteria[criterion]["limit"]
            return count < limit
        except KeyError:
            return False

    def _decrease_quota(self) -> None:
        """Decrease quota with increasing the limit"""

        counts = json.loads(self.configuration.action)
        counts[self.matched_criteria] += 1
        self.configuration.action = json.dumps(counts)
        self.configuration.save()

    @staticmethod
    def _total_matched(results) -> int:
        return sum(results.values())

    def _is_pass_criterion(self, criterion) -> bool:
        """Here we check in each criterion. Fail or pass is based on configuration in the threshold.
        It is mean if the expectation is fail, it will match the threshold in the configuration.
        If the number is out of the threshold, then not pass criteria!.
        """

        logger.info(
            {
                "message": "shopee whitelist: Checking the criterion {}.".format(criterion),
                "application_id": self.application.id,
            }
        )

        fdc_criterion = criterion["fdc"]
        heimdall_criterion = criterion["heimdall"]
        mycroft_criterion = criterion["mycroft"]

        self._fetch_fdc_heimdall_and_mycroft()

        # Checking if the FDC is match or not
        fdc = self._is_pass_fdc(fdc_criterion)

        # Checking if the heimdall is match or not.
        heimdall = self._is_pass_heimdall(heimdall_criterion)

        # Checking the Mycroft is match or not
        mycroft = self._is_pass_mycroft(mycroft_criterion)

        logger.info(
            {
                "application_id": self.application.id,
                "message": "shopee whitelist: Checking criteria",
                "data": {"fdc": fdc, "heimdall": heimdall, "mycroft": mycroft},
            }
        )

        return fdc and heimdall and mycroft

    def _is_pass_heimdall(self, heimdall_criterion) -> bool:
        logger.info(
            {
                "message": "shopee whitelist: Checking Heimdall",
                "criterion": heimdall_criterion,
                "data": self.heimdall,
                "application_id": self.application.id,
            }
        )
        try:
            bottom_threshold = heimdall_criterion["bottom_threshold"]

            if "upper_threshold" in heimdall_criterion:
                upper_threshold = heimdall_criterion["upper_threshold"]
                in_threshold = upper_threshold >= self.heimdall >= bottom_threshold
            else:
                in_threshold = self.heimdall >= bottom_threshold

            return in_threshold
        except Exception as e:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "shopee whitelist: Failed check heimdall condition",
                    "exception": str(e),
                }
            )
            return False

    def _is_pass_fdc(self, fdc_criterion) -> bool:
        logger.info(
            {
                "message": "shopee whitelist: Checking FDC",
                "data": [fdc_criterion, self.fdc],
                "application_id": self.application.id,
            }
        )
        return fdc_criterion == self.fdc

    def _is_pass_mycroft(self, mycroft_criterion) -> bool:
        """
        Check whether the current C score is coming from Mycroft and in our threshold range.
        """

        logger.info(
            {
                "message": "shopee whitelist: Checking Mycroft",
                "criterion": mycroft_criterion,
                "data": self.mycroft,
                "application_id": self.application.id,
            }
        )

        try:
            bottom_threshold = mycroft_criterion["bottom_threshold"]

            if "upper_threshold" in mycroft_criterion:
                upper_threshold = mycroft_criterion["upper_threshold"]
                in_threshold = upper_threshold >= self.mycroft >= bottom_threshold
            else:
                in_threshold = self.mycroft >= bottom_threshold

            return in_threshold
        except Exception as e:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "shopee whitelist: Failed check mycroft condition",
                    "exception": str(e),
                }
            )
            return False

    def _assign_tag(self) -> None:
        import traceback

        from juloserver.application_flow.tasks import application_tag_tracking_task

        criteria = self.configuration.criteria
        if 'tag' not in criteria[self.matched_criteria]:
            return

        tag = criteria[self.matched_criteria]['tag']
        application_tag_tracking_task.delay(
            self.application.id, None, None, None, tag, 1, traceback.format_stack()
        )
        logger.info(
            {
                "application_id": self.application.id,
                "message": "shopee whitelist: Queued application tag",
                "tag": tag,
            }
        )

    def _set_credit_score(self) -> None:
        criteria = self.configuration.criteria
        score = criteria[self.matched_criteria].get('credit_score', None)
        if score:
            credit_score = CreditScore.objects.filter(application_id=self.application.id).last()
            if not credit_score:
                logger.info(
                    {
                        "application_id": self.application.id,
                        "message": "shopee whitelist: Application has no credit score.",
                    }
                )
                raise ShopeeException("Application has no credit score.")
            credit_score.score = score
            credit_score.save(update_fields=['score'])

    def _pass_shopee_score(self) -> None:
        self.scoring.is_passed = True
        self.scoring.passed_reason = "Whitelisted"
        self.scoring.save()

    def tags(self, success: bool = True):
        """If shopee already running, get the all application tags."""

        if not self.configuration:
            return []

        _tags = []
        criteria = self.configuration.criteria
        for criterion in criteria:
            if "tag" in criteria[criterion]:
                _tags.append(criteria[criterion]["tag"])

        _status = 1 if success else 0
        statuses = ApplicationPathTagStatus.objects.filter(
            application_tag__in=_tags, status=_status
        )
        return ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status__in=statuses
        )

    @property
    def has_success_tags(self) -> bool:
        """If shopee already running, check has tag or not."""

        return len(self.tags()) > 0

    def _pass_shopee_whitelist_dynamic_check(self):
        return AutoDataCheck.objects.filter(
            application_id=self.application.id,
            data_to_check=self.BINARY_DYNAMIC_CHECK_KEY,
            is_okay=True,
        ).exists()

    def build_additional_credit_matrix_parameters(self):
        configuration = self.configuration.criteria
        criterion = configuration[self.matched_criteria]

        try:
            params = {"min_threshold": criterion["heimdall"]["bottom_threshold"]}
            if "upper_threshold" in criterion["heimdall"]:
                params["max_threshold"] = criterion["heimdall"]["upper_threshold"]
        except KeyError as e:
            raise ShopeeException(e)

        return params

    def has_anomaly(self) -> bool:

        try:
            if self.has_success_tags:
                _ = self.matched_criteria
        except ShopeeException as e:
            if str(e) == self.EXCEPTION_MESSAGE_NO_MATCHED_CRITERIA:
                logger.warning(
                    {
                        "message": (
                            "shopee whitelist: anomaly detected, has tag but no criteria matched"
                        ),
                        "application_id": self.application.id,
                    }
                )
                return True

        return False
