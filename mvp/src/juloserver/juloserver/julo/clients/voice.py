from builtins import str
from builtins import object
import json
import logging
import os
import calendar
import random
import requests

from base64 import urlsafe_b64encode
from datetime import datetime
from jose import jwt
from rest_framework.status import HTTP_201_CREATED
from django.core.urlresolvers import reverse
from django.conf import settings

from ...julo.exceptions import JuloException
from ...julo.utils import format_nexmo_voice_phone_number
from ...julo.constants import VoiceTypeStatus
from ...julo.models import VoiceCallRecord, Autodialer122Queue
from ...julo.models import NexmoAutocallHistory, Application, PredictiveMissedCall
from . import get_julo_sentry_client


logger = logging.getLogger(__name__)
client = get_julo_sentry_client()


class VoiceApiError(JuloException):
    pass


class JuloVoiceClient(object):

    def __init__(self, voice_key, voice_secret, voice_url, voice_application_id,
                 private_key, julo_phone_number, base_url):
        self.voice_key = voice_key
        self.voice_secret = voice_secret
        self.voice_url = voice_url
        self.voice_application_id = voice_application_id
        self.private_key = private_key
        self.julo_phone_numbers = julo_phone_number.split(",")
        self.base_url = base_url

    def create_call(self, phone_number, answer_url, event_url=None):
        """
        initiate call with nexmo
        """
        answer_url_endpoint = self.base_url + answer_url
        params = {
            'api_key': self.voice_key,
            'api_secret': self.voice_secret,
            'to': [{'type': 'phone', 'number': phone_number}],
            'from': {'type': 'phone', 'number': random.choice(self.julo_phone_numbers)},
            'answer_url': [answer_url_endpoint]
        }

        if event_url:
            params['event_url'] = [event_url]

        url = self.voice_url
        headers = self.get_headers()
        # This is so that our API credentials are not entirely logged,
        # only the last 2 chars for debugging
        safe_params = params.copy()
        safe_params['api_key'] = safe_params['api_key'][-2:]
        safe_params['api_secret'] = safe_params['api_secret'][-2:]
        logger.info({
            'action': 'initiate call',
            'url': url,
            'params': safe_params,
            'headers': headers,
            'answer_url': answer_url_endpoint
        })

        response = requests.post(url, headers=headers, json=params)

        return response

    def get_headers(self):

        d = datetime.utcnow()

        token_payload = {
            "iat": calendar.timegm(d.utctimetuple()),  # issued at
            "application_id": self.voice_application_id,  # application id
            "jti": urlsafe_b64encode(os.urandom(64)).decode('utf-8')
        }

        headers = {'User-Agent': 'nexmo-python/2.0.0/2.7.12+'}

        token = jwt.encode(claims=token_payload, key=self.private_key, algorithm='RS256')

        return dict(headers, Authorization='Bearer ' + token)

    def payment_reminder(self, phone_number, payment_id, streamlined_id=None, template_code=None):
        """
        send voice for payment reminder
        """
        answer_url = ''.join([
            '/api/integration/v1/callbacks/voice-call/',
            VoiceTypeStatus.PAYMENT_REMINDER,
            '/',
            str(payment_id)
        ])
        if streamlined_id:
            answer_url += '?streamlined_id={}'.format(streamlined_id)

        response = self.create_call(
            format_nexmo_voice_phone_number(phone_number), answer_url)
        logger.info({
            'action': 'sending_voice_call_for_payment_reminder',
            'payment_id': payment_id,
            'response': response
        })

        if response.status_code == HTTP_201_CREATED:
            data = json.loads(response.content)
            VoiceCallRecord.objects.create(
                template_code=template_code,
                event_type=VoiceTypeStatus.PAYMENT_REMINDER,
                voice_identifier=payment_id, status=data['status'],
                direction=data['direction'], uuid=data['uuid'],
                conversation_uuid=data['conversation_uuid'])

        return response

    def ptp_payment_reminder(self, phone_number, payment_id):
        """
        send voice for payment reminder
        """
        answer_url = ''.join([
            '/api/integration/v1/callbacks/voice-call/',
            VoiceTypeStatus.PTP_PAYMENT_REMINDER,
            '/',
            str(payment_id)
        ])

        response = self.create_call(
            format_nexmo_voice_phone_number(phone_number), answer_url)
        logger.info({
            'action': 'sending_voice_call_for_ptp_payment_reminder',
            'payment_id': payment_id,
            'response': response
        })

        if response.status_code != requests.codes.CREATED:
            raise VoiceApiError('Error {}{}'.format(response.status, response.reason))

        response_data = json.loads(response.content)

        return response_data


    def make_a_ping_call(self, phone_number, event_url):
        answer_url = reverse('ping_auto_call')
        response = self.create_call(
            format_nexmo_voice_phone_number(phone_number), answer_url, event_url)
        return response


    def ping_auto_call(self, phone_number, app_id):
        """
        call for ping determine answered or not
        """
        event_url = settings.BASE_URL + reverse('auto_call_event_callback')
        response = self.make_a_ping_call(phone_number, event_url)
        logger.info({
            'action': 'sending_voice_call_for_auto_ping',
            'application_id': app_id,
            'response': response
        })

        if response.status_code == requests.codes.CREATED:
            data = json.loads(response.content)
            auto_122_queue = Autodialer122Queue.objects.get_or_none(application_id=app_id)
            if auto_122_queue:
                attempt = auto_122_queue.attempt + 1
                auto_122_queue.attempt=attempt
                auto_122_queue.conversation_uuid=data['conversation_uuid']
                auto_122_queue.auto_call_result_status=data['status']
                auto_122_queue.save()
            else:
                Autodialer122Queue.objects.create(application_id=app_id,
                                          attempt=1,
                                          conversation_uuid=data['conversation_uuid'],
                                          company_phone_number=phone_number,
                                          auto_call_result_status=data['status'],
                                          )
        else:
            logger.error({
                'action': 'ping_auto_call',
                'application_id': app_id,
                'response': response.content
            })


    def ping_auto_call_138(self, phone_number, app_id):
        """
        call for ping determine answered or not to expired 138
        """
        event_url = settings.BASE_URL + reverse('auto_call_event_callback_status_138')
        response = self.make_a_ping_call(phone_number, event_url)
        logger.info({
            'action': 'sending_voice_call_for_auto_ping_status_138',
            'application_id': app_id,
            'response': response
        })

        if response.status_code == requests.codes.CREATED:
            data = json.loads(response.content)
            app = Application.objects.get(pk=app_id)
            NexmoAutocallHistory.objects.create(application_history=app.applicationhistory_set.last(),
                                      conversation_uuid=data['conversation_uuid'],
                                      company_phone_number=phone_number,
                                      auto_call_result_status=data['status'],
                                      )
        else:
            logger.error({
                'action': 'ping_auto_call_status_138',
                'application_id': app_id,
                'response': response.content
            })


    def predictive_missed_called(self, phone_number, app_id):
        """
        call for missed call
        """
        app = Application.objects.get_or_none(pk=app_id)
        if app:
            event_url = settings.BASE_URL + reverse('predictive_missed_call_callback')
            response = self.make_a_ping_call(phone_number, event_url)
            logger.info({
                'action': 'sending_voice_call_for_predictive_missed_called_callback',
                'application_id': app_id,
                'application_status': app.application_status_id,
                'response': response
            })

            if response.status_code == requests.codes.CREATED:
                data = json.loads(response.content)
                predictive_missed_call = PredictiveMissedCall.objects.get_or_none(
                    application_id=app.id,
                    application_status=app.application_status)
                if predictive_missed_call:
                    attempt = predictive_missed_call.attempt + 1
                    predictive_missed_call.attempt = attempt
                    predictive_missed_call.conversation_uuid = data['conversation_uuid']
                    predictive_missed_call.auto_call_result_status = data['status']
                    predictive_missed_call.save()
                else:
                    PredictiveMissedCall.objects.create(application_id=app_id,
                                                          attempt=1,
                                                          conversation_uuid=data['conversation_uuid'],
                                                          phone_number=phone_number,
                                                          auto_call_result_status=data['status'],
                                                          application_status=app.application_status
                                                      )
            else:
                logger.error({
                    'action': 'call_for_predictive_missed_called_callback',
                    'application_id': app_id,
                    'response': response.content
                })

    def covid_19_campaign(self, phone_number, loan_id):
        """
        send voice for covid 19 campaign
        """
        event_type = VoiceTypeStatus.COVID_CAMPAIGN
        answer_url = ''.join([
            '/api/integration/v1/callbacks/voice-call/',
            event_type,
            '/',
            str(loan_id)
        ])

        response = self.create_call(
            format_nexmo_voice_phone_number(phone_number), answer_url)
        logger.info({
            'action': 'sending_voice_call_for_covid_19_campaign',
            'loan_id': loan_id,
            'response': response
        })

        if response.status_code == HTTP_201_CREATED:
            data = json.loads(response.content)
            VoiceCallRecord.objects.create(
                event_type=event_type,
                voice_identifier=loan_id, status=data['status'],
                direction=data['direction'], uuid=data['uuid'],
                conversation_uuid=data['conversation_uuid'])
            return True

        return False
