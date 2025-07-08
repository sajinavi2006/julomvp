import json
import logging
import uuid
from functools import wraps
from hashlib import sha1

from requests.exceptions import (
    ConnectTimeout,
    ConnectionError,
    HTTPError,
    ReadTimeout,
    RequestException,
)

from juloserver.fraud_score.clients.seon_client import get_seon_client
from juloserver.fraud_score.constants import (
    RequestErrorType,
    SeonConstant,
)
from juloserver.fraud_score.models import (
    SeonFraudRawResult,
    SeonFraudRequest,
    SeonFraudResult,
)
from juloserver.fraud_score.serializers import SeonFingerprintSerializer
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.exceptions import InvalidPhoneNumberError
from juloserver.julo.models import (
    Application,
    Customer,
)
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.utils import format_valid_e164_indo_phone_number


logger = logging.getLogger(__name__)


def get_seon_feature_setting():
    return FeatureSettingHelper(FeatureNameConst.SEON_FRAUD_SCORE)


def get_seon_repository():
    return SeonRepository(
        seon_client=get_seon_client(),
    )


def store_seon_fingerprint(data):
    # We don't want to store the fingerprint if there is no SDK fingerprint.
    # Remove this condition if we want to applies for non SDK fingerprint.
    if not data.get('sdk_fingerprint_hash'):
        return

    serializer = SeonFingerprintSerializer(data=data)
    serializer.is_valid(raise_exception=True)

    return serializer.create(serializer.validated_data)


class SeonRepository:
    """
    Class that will call SEON API and store the result in our database.
    If there is a new account_type, we will need to add it here.
    - Add a new mapping in ACTION_TYPE_MAPPING
    - Modifying _construct_request_data() method
    """

    # Mapping our seon_fingerprint.trigger to SEON's action_type
    ACTION_TYPE_MAPPING = {
        SeonConstant.Trigger.APPLICATION_SUBMIT: 'account_register',
    }

    def __init__(self, seon_client):
        self.seon_client = seon_client
        self.seon_config = {
            "ip": {
                "include": "flags,history,id",
                "version": "v1.1",
            },
            "email": {
                "include": "flags,history,id",
                "version": "v2.2",
                "timeout": 3000,
            },
            "phone": {
                "include": "flags,history,id",
                "version": "v1.4",
                "timeout": 3000,
            },
            "ip_api": True,
            "email_api": True,
            "phone_api": True,
            "device_fingerprinting": True
        }

    def fetch_fraud_api_result(self, seon_fingerprint):
        """
        Fetch the fraud API result from SEON. And store the result in our database.
        We will store these data:
        - ops.seon_fraud_request
        - ops.seon_fraud_result
        - ops.seon_fraud_raw_result
        """
        request_data = self._construct_request_data(seon_fingerprint)

        seon_request = SeonFraudRequest(
            seon_fingerprint=seon_fingerprint,
            action_type=request_data['action_type'],
            transaction_id=request_data['transaction_id'],
            email_address=request_data.get('email'),
            phone_number=request_data.get('phone_number'),
        )
        response = None
        try:
            request_data = {
                'config': self.seon_config,
                **request_data,
            }
            logger.info({
                'action': 'SeonRepository:fetch_fraud_api_result',
                'message': 'Sending request to SEON Fraud API',
                'request_data': request_data,
                'seon_fingerprint_id': seon_fingerprint.id,
            })
            response = self.seon_client.fetch_fraud_api(request_data)
            self._fill_seon_request_with_response(seon_request, response)
            response.raise_for_status()

            seon_request.save()
            return self._store_seon_fraud_api_result(seon_request, response.json())
        except Exception as e:
            if isinstance(e, HTTPError):
                seon_request.error_type = RequestErrorType.HTTP_ERROR
            elif isinstance(e, ConnectTimeout):
                seon_request.error_type = RequestErrorType.CONNECT_TIMEOUT_ERROR
            elif isinstance(e, ReadTimeout):
                seon_request.error_type = RequestErrorType.READ_TIMEOUT_ERROR
            elif isinstance(e, ConnectionError):
                seon_request.error_type = RequestErrorType.CONNECTION_ERROR
            elif isinstance(e, RequestException):
                seon_request.error_type = RequestErrorType.OTHER_ERROR
            else:
                seon_request.error_type = RequestErrorType.UNKNOWN_ERROR

            seon_request.save()
            logger.error({
                'action': 'SeonRepository:fetch_fraud_api_result',
                'error': str(e),
                'seon_fraud_request_id': seon_request.id,
                'response_status': response.status_code if response is not None else None,
                'response_data': response.text if response is not None else None,
                'request_data': request_data,
            })
            raise

    def _construct_request_data(self, seon_fingerprint):
        """
        Construct the fingerprint data to be sent to SEON.
        For each type of target_type, we should create a new method to construct the data.
        """
        target_type = seon_fingerprint.target_type

        target_data = {}
        if target_type == SeonConstant.Target.APPLICATION:
            target_data = self._construct_application_data(seon_fingerprint.target_id)

        customer_data = (
            self._construct_customer_data(seon_fingerprint.customer_id)
            if seon_fingerprint.customer_id else {}
        )
        return {
            **customer_data,
            **target_data,
            'transaction_id': uuid.uuid4().hex,
            'ip': seon_fingerprint.ip_address,
            'session': seon_fingerprint.sdk_fingerprint_hash,
            'action_type': self.ACTION_TYPE_MAPPING.get(seon_fingerprint.trigger),
        }

    def _construct_customer_data(self, customer_id):
        customer = Customer.objects.get(id=customer_id)
        user = customer.user
        return {
            'user_id': customer.generated_customer_xid,
            'user_created': int(customer.cdate.timestamp()),
            'password_hash': sha1(user.password.encode()).hexdigest(),
        }

    def _construct_application_data(self, application_id):
        """
        Construct the application data to be sent to SEON.
        """
        application = Application.objects.get(id=application_id)

        try:
            phone_number = format_valid_e164_indo_phone_number(application.mobile_phone_1)
        except InvalidPhoneNumberError:
            phone_number = None

        return {
            'email': application.email,
            'user_fullname': application.fullname,
            'phone_number': phone_number,
            'user_dob': application.dob.strftime('%Y-%m-%d') if application.dob else None,
            'user_pob': application.birth_place,
            'user_region': application.address_provinsi,
            'user_city': application.address_kabupaten,
            'user_zip': application.address_kodepos,
            'user_street': application.address_street_num,
            'user_bank_name': application.name_in_bank,
            'device_id': application.device.android_id if application.device else None,
            'order_memo': application.loan_purpose,
            'affiliate_id': application.referral_code if application.referral_code else None,
        }

    def _fill_seon_request_with_response(self, seon_request, response):
        seon_request.response_time = int(response.elapsed.total_seconds() * 1000)
        seon_request.response_code = response.status_code

        if response.status_code < 500:
            seon_request.seon_error_code = response.json().get('error', {}).get('code')

        return seon_request

    def _store_seon_fraud_api_result(self, seon_request, response_data):
        """
        Store the SEON fraud API result.
        """
        result_data = response_data['data']
        fraud_result = SeonFraudResult.objects.create(
            seon_fraud_request=seon_request,
            fraud_score=result_data['fraud_score'],
            state=result_data['state'],
            seon_id=result_data['seon_id'],
            calculation_time=result_data['calculation_time'],
            version=result_data['version'],
        )
        SeonFraudRawResult.objects.create(
            seon_fraud_result=fraud_result,
            raw=json.dumps(result_data),
        )
        return fraud_result


def seon_enabled_wrapper(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        feature_setting = get_seon_feature_setting()
        if feature_setting.is_active:
            return func(*args, **kwargs)
        return None

    return wrapper
