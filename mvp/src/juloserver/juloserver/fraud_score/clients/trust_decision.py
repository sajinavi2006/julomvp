import copy
import logging
from typing import (
    Dict,
    Optional,
    Tuple,
    Union,
)

import requests
from django.conf import settings
from requests import (
    RequestException,
    Response,
)

from juloserver.fraud_score.constants import TrustGuardConst, FeatureNameConst
from juloserver.fraud_score.models import TrustGuardApiRequest
from juloserver.julo.services2.feature_setting import FeatureSettingHelper

logger = logging.getLogger(__name__)


class TrustDecisionPayload:
    """
    Class to handle Trust Guard API payload/Request.
    """
    def __init__(self, data: Dict, ):
        self.data = data

    def _construct_event_type(self) -> str:
        """
        Construct Trust Guard's event type.
        https://en-doc.trustdecision.com/reference/summary

        Returns:
            str: Returns event_type for the payload.
        """
        event_type = self.data['event_type']
        event_type_request = 'loan'  # default event type
        if event_type:
            event_type_request = getattr(TrustGuardConst.EventType, event_type)[1]
        return event_type_request

    def _construct_terminal_data_object(self) -> Dict:
        """
        Construct Trust Guard's Terminal data object.
        It is used as part of basic parameters in the payload.
        https://en-doc.trustdecision.com/reference/terminal-information1

        Returns:
            Dict: Constructed Terminal data object.
        """
        data = {'black_box': self.data['black_box']}

        ip = self.data.get('ip')
        if ip:
            data.update({'ip': ip})

        return data

    def _construct_address_data_object(
        self,
        province: Optional[str] = None,
        regency: Optional[str] = None,
        subdistrict: Optional[str] = None,
        zip_code: Optional[str] = None
    ) -> Union[None, Dict]:
        """
        Construct Trust Guard's Address data object.
        This data object is used to build 'birthplace' and 'address' in Profile data object.
        https://en-doc.trustdecision.com/reference/address1

        Args:
            province (str, None): Provinsi or Daerah Istimewa in Indonesia.
            regency (str, None): Kabupaten or Kota in Indonesia.
            subdistrict (str, None): Kecamatan (Subdistrik), Distrik, Kapanewon or Kemantren in
                Indonesia.
            zip_code (str, None): Postal code in Indonesia.

        Returns:
            Union[None, Dict]: Returns None if data object cannot be constructed due to missing
                required property. Otherwise, returns Dict.
        """
        if not province or not regency:
            return None

        data = {'country': 'ID', }
        if province:
            data.update({'region': province})
        if regency:
            data.update({'city': regency})
        if subdistrict:
            data.update({'district': subdistrict})
        if zip_code:
            data.update({'zip_code': zip_code})

        return data

    def _construct_phone_data_object(self, phone_number: str) -> Dict:
        """
        Construct Trust Guard's Phone data object.
        https://en-doc.trustdecision.com/v1.0/reference/phone1

        Args:
            phone_number (str): Phone number to be processed..

        Returns:
            Dict: Returns constructed data object for the payload.
        """
        return {'country_code': 62, 'phone_number': phone_number}

    def _construct_profile_data_object(self) -> Dict:
        """
        Construct Trust Guard's Profile data object.
        https://en-doc.trustdecision.com/reference/personal-profile1

        Returns:
            Dict: Constructed Profile data object. Cannot be None as it is required for scoring.
        """
        required_data = {
            'name': self.data['fullname'],
            'id': {
                'id_country': 'ID',
                'id_type': 'identity_card',
                'id_number': self.data['nik'],
            },
        }

        if self.data.get('phone_number'):
            required_data.update({
                'phone': self._construct_phone_data_object(self.data['phone_number'])
            })
        if self.data.get('email'):
            required_data.update({'email': self.data['email']})
        if self.data.get('gender'):
            required_data.update({'sex': self.data['gender']})
        if self.data.get('birthdate'):
            required_data.update({'birthdate': self.data['birthdate']})
        if self.data.get('birthplace_regency'):
            required_data.update({
                'birthplace': self._construct_address_data_object(
                    regency=self.data['birthplace_regency']
                )
            })

        address = self._construct_address_data_object(
            self.data['address_province'],
            self.data['address_regency'],
            self.data['address_subdistrict'],
            self.data['address_zip_code'],
        )
        if address:
            required_data.update({'address': address})

        return required_data

    def construct_loan_event_payload(self):
        payload = {
            'event_time': self.data['event_time'],
            'event_type': self._construct_event_type(),
            'scenario': 'default',
            'terminal': self._construct_terminal_data_object(),
            'ext': {
                'ext_response_types': 'device_info',  # Mandatory according to TG sample
            },
            'profile': self._construct_profile_data_object(),
        }
        # Strangely, not documented as data object in TG documentation. So does not own a function.
        if self.data.get('bank_name'):
            payload.update({'bank': {
                'bank_branch_name': self.data['bank_name'],
            }})

        event_type = self.data.get('event_type')
        if event_type in TrustGuardConst.EVENT_NEED_ACCOUNT_PARAM:
            payload.update({'account': {
                'account_id': str(self.data['customer_id']),
            }})

        return payload


class TrustDecisionClient:
    """
    Client class to wrap Trust Decision's "Trust Guard" API.
    https://en-doc.trustdecision.com/reference/overview

    TODO: May be worth to rename this to TrustGuard to avoid confusion as FinScore also belongs
        to Trust Decision but has its own client class.
    """
    def __init__(self, partner_code=None, partner_key=None, host_url=None):
        if not partner_code:
            raise ValueError('Missing configuration "partner_code".')
        if not partner_key:
            raise ValueError('Missing configuration "partner_key".')
        if not host_url:
            raise ValueError('Missing configuration "host_url".')

        self.partner_code = partner_code
        self.partner_key = partner_key
        self.host_url = host_url

    def fetch_trust_guard_loan_event(
        self, data: Dict, trust_guard_api_request: TrustGuardApiRequest
    ) -> Tuple[Union[None, Response], bool]:
        """
        Interact with Trust Guard API to fetch score for 'loan' event.

        Args:
            data (Dict): Parsed Dict data for Payload.

        Returns:
            Dict: Scoring result from Trust Guard Decision API.
            bool: True if fail to retrieve Trust Guard score.
        """
        headers = {
            'Content-Type': 'application/json',
        }
        params = {
            'partner_code': self.partner_code,
            'partner_key': self.partner_key,
        }

        try:
            trust_decision_payload = TrustDecisionPayload(data)
            request_payload = trust_decision_payload.construct_loan_event_payload()
            if settings.ENVIRONMENT != 'prod':
                logger.info({
                    'action': 'fetch_trust_guard_loan_event',
                    'request_payload': request_payload,
                    'application_id': data['application_id'],
                })
            if trust_guard_api_request:
                trust_guard_api_request.update_safely(raw_request=copy.deepcopy(request_payload))

            response = requests.post(
                self.get_url(), headers=headers, params=params, json=request_payload
            )
            response.raise_for_status()

            return response, False
        except RequestException as e:
            logger.exception({
                'action': 'fetch_trust_guard_loan_event',
                'message': 'HTTP requests exception detected.',
                'error': e,
                'application_id': data['application_id'],
            })

            return e.response if e.response else e, True
        except Exception as e:
            logger.exception({
                'action': 'fetch_trust_guard_loan_event',
                'message': 'Unexpected error during TrustGuard score retrieval.',
                'error': e,
                'application_id': data['application_id'],
            })

            return None, True

    def get_url(self):
        feature_setting = FeatureSettingHelper(FeatureNameConst.MOCK_TRUST_GUARD_URL)
        actual_url = '{}/credit/fraud/v1'.format(self.host_url)
        if feature_setting.is_active:
            return '{}/credit/fraud/v1'.format(feature_setting.get('baseUrl', actual_url))

        return actual_url
