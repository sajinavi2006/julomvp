import base64
import io
import shutil
import uuid
import zipfile
import json
import os
import hashlib

from collections import Counter
from datetime import datetime, timedelta
from json import JSONDecodeError

import jwt
import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.utils.dateparse import parse_datetime
from jwt import DecodeError
from rest_framework.authentication import TokenAuthentication

from juloserver.apiv2.services import rescore_application
from juloserver.application_flow.constants import CacheKey

from django.utils import timezone

from juloserver.application_flow.models import ApplicationRiskyCheck, BankStatementProviderLog
from juloserver.julo.constants import FeatureNameConst, ExperimentConst
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    BankStatementSubmit,
    FeatureSetting,
    ExperimentSetting,
    Skiptrace,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.julolog.julolog import JuloLog
from juloserver.utilities.services import HoldoutManager
from juloserver.julo.utils import format_e164_indo_phone_number, upload_file_to_oss

logger = JuloLog(__name__)


class BankStatementError(Exception):
    pass


class BankStatementClient:

    POWERCRED = 'powercred'
    PERFIOS = 'perfios'

    APPLICATION_TAG = "is_submitted_bank_statement"
    CM_PARAMETER = "feature:leverage_bank_statement"
    TAG_STATUS_PENDING = -1
    TAG_STATUS_FAILED = 0
    TAG_STATUS_SUCCESS = 1

    JULO_CALLBACK_BASE_URL = os.getenv('CALLBACK_BASE_URL')
    JULO_WEB_HOSTNAME = os.getenv('JULO_WEB_HOSTNAME')

    JWT_KID = "jwt-kid"

    def __init__(self, application: Application):
        self.application = application
        self.request = None
        self.analyzed_account = None
        self.additional_monthly_data = None

    def store_raw_response(self, provider):
        if self.request is None:
            return

        BankStatementProviderLog.objects.create(
            application_id=self.application.id,
            provider=provider,
            log=self.request,
            kind="callback",
        )

    @staticmethod
    def cast_to_date(date: str):
        date_split = date.split("-")
        month = date_split[0]
        year = date_split[1]
        if len(year) == 2:
            year = "20{}".format(year)
        date = "{}-{}".format(month, year)

        return datetime.strptime(date, '%b-%Y').replace(day=1)

    def _update_tag(self, to):
        from juloserver.application_flow.services import ApplicationTagTracking

        tag_tracking = ApplicationTagTracking(application=self.application)
        tag_tracking.tracking(tag=self.APPLICATION_TAG, status=to, certain=True)

    def update_tag_to_pending(self):
        logger.info(
            {
                "message": "Bank statement updating status to pending",
                "application_id": self.application.id,
            }
        )
        self._update_tag(to=self.TAG_STATUS_PENDING)

    set_tag_to_pending = update_tag_to_pending

    def update_tag_to_success(self):
        """
        Assign tag to the application
        """
        logger.info(
            {
                "message": "Bank statement updating status from pending to success",
                "application_id": self.application.id,
            }
        )
        self._update_tag(to=self.TAG_STATUS_SUCCESS)

    def update_tag_to_failed(self):
        """
        Assign failed tag to the application
        """
        logger.info(
            {
                "message": "Bank statement updating status from pending to fail",
                "application_id": self.application.id,
            }
        )
        self._update_tag(to=self.TAG_STATUS_FAILED)

    def is_eligible_to_move_to_128(self) -> bool:
        return (
            self.application.status
            in [
                ApplicationStatusCodes.FORM_PARTIAL,
                ApplicationStatusCodes.APPLICATION_DENIED,
            ]
            and not self.blocked_lbs_by_change_reason()
        )

    def move_to_128(self):
        skiptrace = Skiptrace.objects.filter(
            phone_number=format_e164_indo_phone_number(self.application.mobile_phone_1),
            customer_id=self.application.customer.id,
        ).exists()

        if not skiptrace:
            Skiptrace.objects.create(
                contact_name=self.application.full_name_only,
                customer=self.application.customer,
                application=self.application,
                phone_number=format_e164_indo_phone_number(self.application.mobile_phone_1),
                contact_source='mobile_phone_1',
            )

        process_application_status_change(
            self.application,
            ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
            'bank statement process available',
        )
        return self

    def move_to_121(self, reason="Submitted bank statements"):
        logger.info(
            {
                "message": "Bank statement move to 121",
                "application_id": self.application.id,
            }
        )

        process_application_status_change(
            self.application,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            change_reason=reason,
        )

    move_to_scraped_data_verified = move_to_121

    def move_to_135(self, reason="Rejected bank statement"):
        logger.info(
            {
                "message": "Bank statement move to 135",
                "application_id": self.application.id,
            }
        )

        process_application_status_change(
            self.application,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason=reason,
        )

    def get_lbs_experiment_setting(self):
        return ExperimentSetting.objects.filter(
            is_active=True, code=ExperimentConst.LEVERAGE_BANK_STATEMENT_EXPERIMENT
        ).last()

    def registered_client(self):
        """Determine the client/vendor that this user already registered."""

        customer = self.application.customer

        application_ids = list(customer.application_set.values_list('id', flat=True))
        bank_statement_providers = BankStatementProviderLog.objects.filter(
            application_id__in=application_ids
        ).values_list('provider', flat=True)

        bank_statement_counter = Counter(bank_statement_providers)
        most_common = bank_statement_counter.most_common(1)
        if len(most_common) > 0:
            value, _ = most_common[0]
            return value

        return None

    def generate_jwt_token(self, start_at, days_expire=30):
        import jwt

        token = jwt.encode(
            payload={
                "application_id": self.application.id,
                "expired_at": str(timezone.localtime(start_at) + timedelta(days=days_expire)),
            },
            key=self.JWT_KID,
            headers={"alg": "HS256", "typ": "JWT", 'kid': self.JWT_KID},
        )
        return token.decode('utf-8')

    def get_provider_from_name(self, name):
        if name is None:
            return None

        if name == self.POWERCRED:
            return PowerCred(self.application)

        if name == self.PERFIOS:
            return Perfios(self.application)

    def build_url_submission(self):
        leverage_bank_statement_setting = self.get_lbs_experiment_setting()
        percentage = 50
        per_request = 2
        redis_clients = {"right": "perfios"}

        if leverage_bank_statement_setting:
            ab_testing = leverage_bank_statement_setting.criteria['a/b_test']
            percentage = ab_testing.get('percentage')
            per_request = ab_testing.get('per_request')
            redis_clients = leverage_bank_statement_setting.criteria['clients']

        provider = None
        client = self.registered_client()
        if redis_clients and client:
            for position in redis_clients:
                if redis_clients[position] == client:
                    provider = self.get_provider_from_name(redis_clients[position])
                    break

        if not client:
            with HoldoutManager(
                percentage=percentage,
                total_request=per_request,
                key=CacheKey.BANK_STATEMENT_CLIENT_HOLDOUT_COUNTER,
            ) as holdout:
                for position in redis_clients:
                    if holdout.counter in holdout.variables[f"list_{position}"]:
                        provider = self.get_provider_from_name(redis_clients[position])
                        break

        if not provider:
            if redis_clients['right']:
                provider = self.get_provider_from_name(redis_clients['right'])
            else:
                # in case admin set only the left clients on django
                provider = self.get_provider_from_name(redis_clients['left'])

        provider_url, provider_log = provider.get_token()
        url = "{}/api/application_flow/v1/bank-statements?lid={}&token={}".format(
            self.JULO_CALLBACK_BASE_URL,
            provider_log.id,
            self.generate_jwt_token(start_at=provider_log.cdate),
        )
        if url.startswith("http://"):
            return url[7:]
        elif url.startswith("https://"):
            return url[8:]
        else:
            return url

    def generate_landing_url(self):
        bank_param = "others"
        bank_name = self.application.bank_name
        if bank_name == "BANK CENTRAL ASIA, Tbk (BCA)":
            bank_param = "bca"
        elif bank_name == "BANK MANDIRI (PERSERO), Tbk":
            bank_param = "mandiri"
        elif bank_name == "BANK RAKYAT INDONESIA (PERSERO), Tbk (BRI)":
            bank_param = "bri"
        elif bank_name == "BANK NEGARA INDONESIA (PERSERO), Tbk (BNI)":
            bank_param = "bni"

        token = self.generate_jwt_token(start_at=timezone.now(), days_expire=30)

        url = "{}/landing/leverage-bank-statement?bank={}&application-id={}&token={}".format(
            self.JULO_WEB_HOSTNAME,
            bank_param,
            self.application.id,
            token,
        )
        return url

    def disable_moengage(self):
        from juloserver.moengage.services.use_cases import (
            send_user_attributes_to_moengage_for_submit_bank_statement,
        )

        send_user_attributes_to_moengage_for_submit_bank_statement.delay(
            self.application.id, None, False
        )

    def reject(self, reason):
        self.move_to_135(reason)
        self.disable_moengage()
        self.update_tag_to_failed()

    def blocked_lbs_by_change_reason(self):
        blocked_change_reason = ['foto tidak senonoh', 'job type blacklisted', 'ineligible lbs']
        return ApplicationHistory.objects.filter(
            application_id=self.application.id, change_reason__in=blocked_change_reason
        ).exists()


class PowerCred(BankStatementClient):
    POWERCRED_ENDPOINT = os.getenv('POWERCRED_ENDPOINT')
    POWERCRED_API_KEY = os.getenv('POWERCRED_API_KEY')
    POWERCRED_API_SECRET = os.getenv('POWERCRED_API_SECRET')
    POWERCRED_CLIENT_NAME = os.getenv('POWERCRED_CLIENT_NAME')

    FAIL_MESSAGE_REJECTED = 'Rejected bank statements by PowerCred'
    FAIL_MESSAGE_NO_MATCHED_ACCOUNT = 'Different bank account by PowerCred'

    def post(self, path, headers, data):
        url = '{}{}'.format(self.POWERCRED_ENDPOINT, path)

        response = requests.post(url, json=data, headers=headers)

        return response

    def _get_active_url(self):
        """PowerCred url will valid for 7 days."""
        has_balance = False
        submission = BankStatementSubmit.objects.filter(
            application_id=self.application.id, vendor=self.POWERCRED
        ).last()
        if submission:
            has_balance = submission.bankstatementsubmitbalance_set.exists()
        if has_balance:
            logger.warning(
                {
                    "application_id": self.application.id,
                    "message": "Callback exists but still has request to get the url",
                }
            )
            return None, None

        token_log = BankStatementProviderLog.objects.filter(
            kind="token", application_id=self.application.id, provider=self.POWERCRED
        ).last()
        if not token_log:
            return None, None

        now = timezone.localtime(timezone.now())
        seven_days_ago = now - timedelta(days=7)
        if token_log.cdate > seven_days_ago:
            return json.loads(token_log.log.replace("'", "\""))["url"], token_log

        return None, None

    def get_token(self):

        if self._get_active_url()[0]:
            return self._get_active_url()

        headers = {"Content-Type": "application/json"}

        callback_url = self.JULO_CALLBACK_BASE_URL + "/api/application_flow/v1/powercred/callback"
        path = (
            "/auth/token?secret="
            + self.POWERCRED_API_SECRET
            + "&redirect_url="
            + callback_url
            + "&apikey="
            + self.POWERCRED_API_KEY
        )

        data = {
            'user_id': str(self.application.customer.user_id),
            'client': self.application.email,
            'application_xid': str(self.application.application_xid),
            'device_id': str(self.application.device_id),
        }
        logger.info(
            {
                "action": "trying to hit powercred get token endpoint",
                "url": callback_url,
                "application_id": self.application.id,
                "data": data,
            }
        )
        response = self.post(path, headers, data)

        if response.status_code != 200:
            raise BankStatementError("Failed to get token from Powercred")

        result = response.json()
        provider_log = BankStatementProviderLog.objects.create(
            application_id=self.application.id,
            provider=self.POWERCRED,
            log=result,
            kind="token",
        )

        if 'url' not in result:
            raise BankStatementError("URL not found in response")

        return result['url'], provider_log

    @classmethod
    def callback(cls, request):
        """
        Save the callback request
        """
        logger.info(
            {
                "message": "PowerCred callback",
                "request": request,
            }
        )

        data = cls.parse_data(request)

        application_xid = int(data["credentials"]["application_xid"])
        user_id = int(data["credentials"]["user_id"])
        device_id = int(data["credentials"]["device_id"])

        application = Application.objects.filter(application_xid=application_xid).last()
        if application is None:
            raise BankStatementError("Application not found")

        if application.customer.user_id != user_id:
            raise BankStatementError("User ID not match")

        has_device = application.customer.device_set.filter(id=device_id).exists()
        if not has_device:
            raise BankStatementError("Device ID not match")

        instance = cls(application)
        instance.process_callback(request)

    def process_callback(self, request):

        self.request = request

        self.store_raw_response(provider=self.POWERCRED)

        data = self.parse_data(request)
        self.get_analyzed_account(data['Analysis'])

        if self.analyzed_account:
            if self.allow_to_continue():
                with db_transactions_atomic(DbConnectionAlias.onboarding()):
                    self.store_request()
                    self.move_to_scraped_data_verified()
                    self.update_tag_to_success()
                    self.rescore_application()
            else:
                with db_transactions_atomic(DbConnectionAlias.onboarding()):
                    self.reject(self.FAIL_MESSAGE_REJECTED)
        else:
            with db_transactions_atomic(DbConnectionAlias.onboarding()):
                self.reject(self.FAIL_MESSAGE_NO_MATCHED_ACCOUNT)

    def allow_to_continue(self):
        self._update_tag_fraud()

        if self.is_fraud():
            logger.info(
                {
                    "message": "PowerCred detected as fraud",
                    "application_id": self.application.id,
                }
            )
            return False

        if not self._allowed_months_rule():
            logger.info(
                {
                    "message": "PowerCred not in allowed months",
                    "application_id": self.application.id,
                }
            )
            return False

        return True

    def _allowed_months_rule(self):
        data = self.analyzed_account
        dates = []
        for item in data:
            dates.append(self.cast_to_date(item["month"]))

        # Sort in ascending order
        dates.sort()

        # Check if months is consecutive
        if not self._is_month_consecutive(dates):
            return False

        # Check if the latest month not more that 1 month from the current month
        if not self._in_accepted_gap(dates):
            return False

        return True

    @staticmethod
    def _is_month_consecutive(months):
        months.sort()

        if len(months) < 3:
            return False

        for i in range(len(months) - 1):
            year, month = months[i].year, months[i].month
            next_year, next_month = months[i + 1].year, months[i + 1].month

            month += 1
            if month > 12:
                month = 1
                year += 1

            if (year, month) != (next_year, next_month):
                return False

        return True

    @staticmethod
    def _current_time():
        return datetime.now()

    def _in_accepted_gap(self, dates):
        accepted_gap = 2
        dates.sort()
        last_date = dates[-1]
        months_difference = abs(
            (last_date.year - self._current_time().year) * 12
            + last_date.month
            - self._current_time().month
        )

        return months_difference <= accepted_gap

    def get_analyzed_account(self, analysis):
        """
        Get the analyzed account with matching the account number with name bank validation.
        This logic maybe changed to match with the name holder in the future, or not match to
        any condition at all.
        """

        account_number = None
        name_bank_validation = self.application.name_bank_validation
        for account in analysis:
            if account == name_bank_validation.account_number:
                account_number = account
                break

        if account_number is None:
            logger.info(
                {
                    "message": (
                        "Bank statement PowerCred account number name bank validation not found"
                    ),
                    "application_id": self.application.id,
                }
            )
            return
        else:
            self.analyzed_account = analysis[account_number]

    def store_request(self):
        """
        Store the analyzed request to the database
        """
        logger.info(
            {
                "message": "PowerCred store request",
                "application_id": self.application.id,
            }
        )

        bank_statement = BankStatementSubmit.objects.create(
            application_id=self.application.id,
            vendor=self.POWERCRED,
            status='success',
        )
        name_in_banks = []
        for resume in self.analyzed_account:
            bank_statement.bankstatementsubmitbalance_set.create(
                balance_date=self.cast_to_date(resume["month"]),
                minimum_eod_balance=resume["min_EOD_balance"],
                average_eod_balance=resume["average_EOD_balance"],
            )

        for account in self.parse_data(self.request)["Account"]:
            name_in_banks.append(account["Account Holder name"])

        logger.info(
            {
                "message": "PowerCred collect name in banks",
                "application_id": self.application.id,
                "data": name_in_banks,
            }
        )

        if len(name_in_banks) == 1:
            name_in_bank = name_in_banks[0]
        elif len(name_in_banks) > 1:
            name_in_bank = json.dumps(name_in_banks)
        else:
            raise BankStatementError("Not found any name in bank in the request")

        bank_statement.update_safely(name_in_bank=name_in_bank)

    def rescore_application(self):
        """
        Rescore C Score Application based on CM
        """
        is_rescore = rescore_application(self.application, self.CM_PARAMETER)

        if is_rescore:
            logger.info(
                {
                    "message": "PowerCred success rescore application",
                    "application_id": self.application.id,
                }
            )
        else:
            logger.info(
                {
                    "message": "PowerCred failed rescore application",
                    "application_id": self.application.id,
                }
            )

    def _update_tag_fraud(self):
        """Check whether the request categorized as early warning and window dressing"""

        data = self.parse_data(self.request)
        fraud_indicators = data['fraud_indicators']
        fraud_list = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.POWERCRED_FRAUD_CRITERIA, is_active=True
        ).last()
        risky_check, created = ApplicationRiskyCheck.objects.get_or_create(
            application=self.application
        )
        early_warning_list = []
        window_dressing_list = []
        if fraud_list:
            early_warning_list = fraud_list.parameters['early_warning']
            window_dressing_list = fraud_list.parameters['window_dressing']

        if isinstance(fraud_indicators, bool):
            return

        for fraud_indicator in fraud_indicators:
            name = fraud_indicator["Fraud indicator"]
            tag = fraud_indicator["Fraud Tag"]
            is_identified = fraud_indicator["Identified"]

            if tag == "Early warning" and is_identified == "Yes" and name in early_warning_list:
                risky_check.update_safely(is_early_warning_leverage_bank=True)

            if tag == "Window dressing" and is_identified == "Yes" and name in window_dressing_list:
                risky_check.update_safely(is_window_dressing_leverage_bank=True)

    def is_fraud(self) -> bool:
        """Check whether the request categorized as fraud"""

        data = self.parse_data(self.request)
        fraud_indicators = data['fraud_indicators']
        if isinstance(fraud_indicators, bool):
            return fraud_indicators

        for fraud_indicator in fraud_indicators:
            # triggers_count = fraud_indicator["Count of Triggers"]
            # name = fraud_indicator["Fraud indicator"]
            tag = fraud_indicator["Fraud Tag"]
            is_identified = fraud_indicator["Identified"]
            # remarks = fraud_indicator["Remarks"]

            if tag == "Fraud" and is_identified == "Yes":
                return True

        return False

    @staticmethod
    def parse_data(request):
        if "data" in request:
            return request["data"]

        return request


class Perfios(BankStatementClient):
    JULO_PERFIOS_PRIVATE_KEY = os.getenv('JULO_PERFIOS_PRIVATE_KEY')
    SIGNATURE_ALGORITHM = 'PERFIOS-RSA-SHA256'
    SIGNED_HEADERS = 'host;x-perfios-content-sha256;x-perfios-date'
    GRANT_TYPE = 'client_credentials'

    HOST = os.getenv('PERFIOS_HOST')
    ENDPOINT = "https://" + HOST
    CLIENT_ID = os.getenv('PERFIOS_CLIENT_ID')
    CLIENT_SECRET = os.getenv('PERFIOS_CLIENT_SECRET')
    PERFIOS_AUTHORIZATION = (
        'Base ' + base64.b64encode((CLIENT_ID + ':' + CLIENT_SECRET).encode('utf-8')).decode()
    )

    SUCCESS_STATUS = "REPORT_GENERATION_SUCCESS"
    FAIL_STATUS = "REPORT_GENERATION_FAILURE"

    FAIL_MESSAGE_REJECTED = 'Rejected bank statements by Perfios'
    FAIL_MESSAGE_NO_MATCHED_ACCOUNT = "Different bank account by Perfios"
    FAIL_MESSAGE_NO_ACCOUNT = "No account found by Perfios"

    def __init__(self, application: Application):
        super().__init__(application)
        self.perfios_signature = None
        self.perfios_date = None
        self.perfios_content_sha256 = None
        self.canonical_headers = None
        self.canonical_request = None
        self.perfios_report_path = None
        self._is_fraud = False

    def create_signature(self, method, uri, query_string=None, payload=""):
        payload = payload.encode('utf-8')
        hash_obj = hashlib.sha256(payload)
        hex_digest = hash_obj.hexdigest()

        current_time = datetime.utcnow()
        formatted_time = current_time.strftime("%Y%m%dT%H%M%SZ")

        self.canonical_headers = (
            'host:'
            + self.HOST
            + '\n'
            + 'x-perfios-content-sha256:'
            + hex_digest
            + '\n'
            + 'x-perfios-date:'
            + formatted_time
        )

        if isinstance(query_string, dict):
            from urllib.parse import urlencode

            query_string = urlencode(query_string)

        canonical_request = (
            method
            + '\n'
            + uri
            + '\n'
            + ("" if query_string is None else query_string)
            + '\n'
            + self.canonical_headers
            + '\n'
            + self.SIGNED_HEADERS
            + '\n'
            + hex_digest
        )

        self.canonical_request = canonical_request.encode('utf-8')
        hash_obj = hashlib.sha256(self.canonical_request)
        hex_encoded_hashed_canonical_string = hash_obj.hexdigest()

        metadata_string = (
            self.SIGNATURE_ALGORITHM
            + '\n'
            + formatted_time
            + '\n'
            + hex_encoded_hashed_canonical_string
        )

        metadata_string = metadata_string.encode('utf-8')
        hash_obj = hashlib.sha256(metadata_string)
        string_to_be_signed = hash_obj.hexdigest()

        private_key_pem = self.JULO_PERFIOS_PRIVATE_KEY

        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None, backend=default_backend()
        )

        signature_text = private_key.sign(
            string_to_be_signed.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
            hashes.SHA256(),
        ).hex()

        self.perfios_content_sha256 = hex_digest
        self.perfios_date = formatted_time
        self.perfios_signature = signature_text

        return hex_digest, formatted_time, signature_text

    def post(self, path, headers, data):
        url = '{}{}'.format(self.ENDPOINT, path)
        response = requests.post(url, json=data, headers=headers)
        return response

    def _get_active_url(self):
        """Perfios url will valid for 7 days, and after clicked it will be valid for 20 minutes"""
        has_balance = False
        submission = BankStatementSubmit.objects.filter(
            application_id=self.application.id, vendor=self.PERFIOS
        ).last()
        if submission:
            has_balance = submission.bankstatementsubmitbalance_set.exists()

        if has_balance:
            logger.warning(
                {
                    "application_id": self.application.id,
                    "message": "Balance exists but still has request to get the url",
                }
            )
            return None, None

        token_log = BankStatementProviderLog.objects.filter(
            kind="token",
            application_id=self.application.id,
            provider=self.PERFIOS,
        ).last()
        if not token_log:
            return None, None

        now = timezone.localtime(timezone.now())

        has_valid_clicked_link = True
        has_valid_expiry_link = True

        # Check the first clicked at
        if token_log.clicked_at:
            expiry_clicked_time = token_log.clicked_at + timedelta(minutes=19)
            if now > expiry_clicked_time:
                has_valid_clicked_link = False

        # Check the validity of link
        expiry_link_time = token_log.cdate + timedelta(days=6)
        if now > expiry_link_time:
            has_valid_expiry_link = False

        if has_valid_clicked_link and has_valid_expiry_link:
            try:
                return json.loads(token_log.log.replace("'", "\""))["redirectUrl"], token_log
            except JSONDecodeError:
                return None, None

        return None, None

    def get_token(self):

        if self._get_active_url()[0]:
            return self._get_active_url()

        transaction_id = str(self.application.application_xid) + "-" + str(uuid.uuid4())

        uri = (
            '/lspsdk/api/julo/v1/dcp/clientTransactionId/'
            + transaction_id
            + '/initDocumentCollection'
        )
        callback_url = self.JULO_CALLBACK_BASE_URL + "/api/application_flow/v1/perfios/callback"
        app_redirect_url = "https://r.julo.co.id/1mYI/home"
        current_date = timezone.localtime(timezone.now())
        payload = {
            "metaData": {
                "productType": "BANK_STATEMENT_UPLOAD_V3",
                "perfiosRequestId": str(uuid.uuid4()),
            },
            "additionalInformation": {
                "startMonth": (current_date - relativedelta(months=5)).strftime('%Y-%m'),
                "endMonth": (current_date - relativedelta(months=1)).strftime('%Y-%m'),
                "acceptancePolicy": "atLeastOneTransactionInRange",
                "returnUrl": app_redirect_url,
                "callbackUrl": callback_url,
                "source": "Mobile",
                "loanAmount": "1",
                "loanDuration": "1",
            },
        }

        self.create_signature('POST', uri, None, json.dumps(payload))
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.PERFIOS_AUTHORIZATION,
            "grant_type": self.GRANT_TYPE,
            "host": self.HOST,
            "x-perfios-content-sha256": self.perfios_content_sha256,
            "x-perfios-date": self.perfios_date,
            "x-perfios-algorithm": self.SIGNATURE_ALGORITHM,
            "x-perfios-signed-headers": self.SIGNED_HEADERS,
            "x-perfios-signature": self.perfios_signature,
        }

        logger.info(
            {
                "action": "trying to hit perfios get token endpoint",
                "url": callback_url,
                "application_id": self.application.id,
                "transaction_id": transaction_id,
                "header": headers,
                "data": payload,
                "canonical": {"request": self.canonical_request, "header": self.canonical_headers},
            }
        )

        response = self.post(uri, headers, payload)

        try:
            result = response.json()
        except JSONDecodeError:
            result = response.content

        provider_log = BankStatementProviderLog.objects.create(
            application_id=self.application.id,
            provider=self.PERFIOS,
            log=result,
            kind="token",
        )

        logger.info(
            {
                "action": "perfios get token endpoint response",
                "application_id": self.application.id,
                "result": result,
            }
        )

        if response.status_code != 200:
            raise BankStatementError("Failed to get token from Perfios")

        if 'redirectUrl' not in result or result['redirectUrl'] is None:
            raise BankStatementError("URL not found in response")

        return result['redirectUrl'], provider_log

    @classmethod
    def callback(cls, request):
        """
        Sample success:
        {"clientTransactionId": "a5fe79ba-896a-4aa3",
        "applicationStatus": "REPORT_GENERATION_SUCCESS",
        "rejectionMessage": ""} # noqa

        Sample failed:
        {"clientTransactionId": "a5fe79ba-896a-4aa3",
        "applicationStatus": "REPORT_GENERATION_FAILURE",
        "rejectionMessage": "Missing months"} # noqa
        """

        logger.info(
            {
                "message": "Perfios callback",
                "request": request,
            }
        )
        transaction_id = request["clientTransactionId"]
        application_xid = int(transaction_id.split("-")[0])

        application = Application.objects.filter(application_xid=application_xid).last()
        instance = cls(application)
        instance.process_callback(request)

    def process_callback(self, request):
        from juloserver.application_flow.tasks import extract_perfios_report

        self.request = request
        self.store_raw_response(provider=self.PERFIOS)

        if self.request["applicationStatus"] == self.SUCCESS_STATUS:

            # Here we call the async task to extract the information of the report and decide where
            # the application should go.
            self.store_request()
            extract_perfios_report.delay(self.application.id, request["clientTransactionId"])

        elif self.request["applicationStatus"] == self.FAIL_STATUS:
            logger.info(
                {
                    "message": "Perfios x135 due to status failed",
                    "application_id": self.application.id,
                }
            )

            self.reject(self.FAIL_MESSAGE_REJECTED)

    def store_request(self, update=False):
        logger.info(
            {
                "message": "Perfios store request",
                "application_id": self.application.id,
            }
        )

        if not update:
            BankStatementSubmit.objects.create(
                application_id=self.application.id,
                vendor=self.PERFIOS,
                status='success',
                report_path=self.perfios_report_path,
                is_fraud=self._is_fraud,
            )
            return

        submission = BankStatementSubmit.objects.filter(
            application_id=self.application.id,
            vendor=self.PERFIOS,
            status="success",
        ).last()

        update_submission_data = {
            "report_path": self.perfios_report_path,
            "is_fraud": self._is_fraud,
        }
        if self.analyzed_account:
            submission.update_safely(
                **update_submission_data,
                **{"name_in_bank": self.analyzed_account["personalInfo"]["name"]},
            )
        else:
            submission.update_safely(**update_submission_data)
            return

        if not self.additional_monthly_data:
            return

        for monthly_data in self.additional_monthly_data:
            if all(
                [
                    monthly_data["avgEODBalance"] == 0,
                    monthly_data["eomBalance"] == 0,
                    monthly_data["nonProCredits"] == 0,
                    monthly_data["nonProDebits"] == 0,
                ]
            ):
                continue
            month_name = monthly_data["monthName"]
            average_eod_balance = monthly_data["avgEODBalance"]
            eom_balance = monthly_data["eomBalance"]
            for monthly_detail in self.analyzed_account["monthlyDetails"]:
                if monthly_detail["monthName"] == month_name:
                    minimum_eod_balance = monthly_detail["balMin"]
            submission.bankstatementsubmitbalance_set.create(
                balance_date=self.cast_to_date(month_name),
                minimum_eod_balance=minimum_eod_balance,
                average_eod_balance=average_eod_balance,
                eom_balance=eom_balance,
            )

    def _find_json_file(self, path):
        files = os.listdir(path)
        json_files = list(filter(lambda file: file.endswith(".json"), files))
        chosen_json = None

        if len(json_files) > 1:
            new_lists = []
            for json_file in json_files:
                new_lists.append(os.path.join(path, json_file))

            sorted_lists = sorted(new_lists, key=os.path.getctime)
            chosen_json_path = sorted_lists[-1:][0]
            _, chosen_json = os.path.split(chosen_json_path)

        # If json file not found, try to look for zip file and extract it
        if len(json_files) == 0:
            zip_files = list(filter(lambda file: file.endswith(".zip"), files))
            app_zip_file = "{}.zip".format(self.application.id)
            if app_zip_file in zip_files:
                zip_files.remove(app_zip_file)

            if len(zip_files) == 0:
                raise BankStatementError("Not found any zip file.")

            z2 = zipfile.ZipFile(path + zip_files[0])
            z2.extractall(path)
            return self._find_json_file(path)

        if chosen_json is None:
            chosen_json = json_files[0]

        with open(path + chosen_json) as f:
            return json.load(f)

    find_json_file = _find_json_file

    def get_analyzed_account(self, transaction_id: str):
        """
        This function used to get the zip report from Perfios, store the zip file inside cloud
        bucket. Extract the zip file to get the content of json report. Assign the json report
        inside analyzed_account variable. Finally, delete completely the extracted content to
        prevent storage full.
        """

        # First download the zip compressed report into the local machine
        response = self._download_report(transaction_id)

        tmp_dir = self._store_zip(response)

        # Look for the json file.
        data = self._find_json_file(tmp_dir)

        # Delete temporary directory
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)

        chosen_account = None
        if "accountAnalysis" in data:
            chosen_account = data["accountAnalysis"][0]
        if chosen_account is None:
            logger.info(
                {
                    "message": (
                        "Bank statement Perfios account number name bank validation not found"
                    ),
                    "application_id": self.application.id,
                }
            )
        else:
            self.analyzed_account = chosen_account
        self.additional_monthly_data = data["AdditionalMonthlyDetails"]["MonthlyData1"]

    def _download_report(self, transaction_id, include_all: bool = False):
        url = "{}/lspsdk/api/{}/v1/dcp/clientTransactionId/{}/report".format(
            self.ENDPOINT, self.CLIENT_ID, transaction_id
        )

        qs = {"includes": "all"} if include_all else None

        self.create_signature('GET', url, query_string=qs)
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.PERFIOS_AUTHORIZATION,
            "grant_type": self.GRANT_TYPE,
            "host": self.HOST,
            "x-perfios-content-sha256": self.perfios_content_sha256,
            "x-perfios-date": self.perfios_date,
            "x-perfios-algorithm": self.SIGNATURE_ALGORITHM,
            "x-perfios-signed-headers": self.SIGNED_HEADERS,
            "x-perfios-signature": self.perfios_signature,
        }
        logger.info(
            {
                "action": "Trying to hit Perfios get report",
                "url": url,
                "application_id": self.application.id,
                "transaction_id": transaction_id,
                "headers": headers,
                "include_all": include_all,
            }
        )
        response = requests.get(url, params=qs, headers=headers)
        if response.status_code != 200:
            if include_all:
                raise BankStatementError("Failed to download the zip file")

            response = self._download_report(transaction_id, include_all=True)

        self.perfios_report_path = 'perfios/{}/{}.zip'.format(
            self.application.id, self.application.id
        )
        return response

    def _store_zip(self, response) -> str:
        bzip = zipfile.ZipFile(io.BytesIO(response.content))

        # Check the directory existence
        if not os.path.isdir('/media/perfios'):
            os.mkdir('/media/perfios')

        tmp_dir = '/media/perfios/{}/'.format(self.application.id)
        tmp_zip = '{}{}.zip'.format(tmp_dir, self.application.id)

        if not os.path.isdir(tmp_dir):
            os.mkdir(tmp_dir)

        bzip.extractall(tmp_dir)

        with open(tmp_zip, "wb") as zp:
            zp.write(response.content)

        # Then here we move the file to OSS
        upload_file_to_oss(
            settings.OSS_MEDIA_BUCKET,
            local_filepath=tmp_zip,
            remote_filepath=self.perfios_report_path,
        )

        # Directory deletion should be done manually
        return tmp_dir

    def extract_zip_and_decide(self, transaction_id: str):

        self.get_analyzed_account(transaction_id)
        if self.analyzed_account:
            if self.allow_to_continue():
                with db_transactions_atomic(DbConnectionAlias.onboarding()):
                    self.move_to_scraped_data_verified()
                    self.store_request(update=True)
                    self.update_tag_to_success()
                return

            self.reject(self.FAIL_MESSAGE_REJECTED)

        else:
            self.reject(self.FAIL_MESSAGE_NO_ACCOUNT)

        self.store_request(update=True)

    def allow_to_continue(self):
        if self.is_fraud():
            logger.info(
                {
                    "message": "Perfios detected as fraud",
                    "application_id": self.application.id,
                }
            )
            return False

        if not self.has_sufficient_statements():
            logger.info(
                {
                    "message": "Perfios not enough bank statements",
                    "application_id": self.application.id,
                }
            )
            return False

        return True

    def has_sufficient_statements(self):
        count = sum(
            1
            for monthly_data in self.additional_monthly_data
            if any(
                [
                    monthly_data["avgEODBalance"],
                    monthly_data["eomBalance"],
                    monthly_data["nonProCredits"],
                    monthly_data["nonProDebits"],
                ]
            )
        )
        return count >= 3

    def is_fraud(self):
        fcu_analysis = self.analyzed_account["fCUAnalysis"]
        possible_fraud_indicators = fcu_analysis["possibleFraudIndicators"]
        suspicious_bank_e_statements = possible_fraud_indicators["suspiciousBankEStatements"]
        status = suspicious_bank_e_statements["status"]

        fraud_check = status == "true"
        self._is_fraud = fraud_check
        return fraud_check


def get_lbs_submission(application: Application) -> dict:
    submission = BankStatementSubmit.objects.filter(application_id=application.id).last()
    return submission


class LBSJWTAuthentication(TokenAuthentication):
    def __init__(self):
        self._request = None

    def authenticate(self, request):
        self._request = request
        return super().authenticate(request)

    def authenticate_credentials(self, key):
        try:
            payload = jwt.decode(key, BankStatementClient.JWT_KID, algorithms="HS256")
        except DecodeError:
            # todo: this used to handle existing user that still using expiry token.
            #  Remove after no message below shown up again in OpenSearch
            logger.error({"message": "LBSJWTAuthentication error decode token."})
            application_id = self._request.parser_context['kwargs']['application_id']
            user = self._get_user_from_application(application_id)
            return user, None

        application_id = payload["application_id"]
        user = self._get_user_from_application(application_id)

        expired_at = parse_datetime(payload["expired_at"])
        now = timezone.localtime(timezone.now())
        if now > expired_at:
            logger.error(
                {
                    "message": "The token already expired.",
                    "application_id": application_id,
                    "expired_at": expired_at,
                    "current_time": now,
                }
            )
            return None, "expired"

        return user, None

    @staticmethod
    def _get_user_from_application(application_id):
        application = Application.objects.select_related("customer__user").get(pk=application_id)
        user = application.customer.user
        return user
