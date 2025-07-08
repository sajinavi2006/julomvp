import os

from builtins import object
import json
import logging
import time
from datetime import (
    timedelta,
    date,
)
from http import HTTPStatus

import pysftp
import requests
from argparse import Namespace

from dateutil.parser import parse
from django.utils import timezone

from juloserver.julo.models import AgentProductivity
from juloserver.minisquad.constants import (
    DialerTaskType,
    DialerTaskStatus,
)
from juloserver.minisquad.exceptions import IntelixException
from juloserver.minisquad.models import DialerTask
from juloserver.minisquad.services2.intelix import (
    create_history_dialer_task_event
)

logger = logging.getLogger(__name__)


class JuloIntelixClient(object):
    INTELIX_CONNECT_TIMEOUT = 120
    INTELIX_READ_TIMEOUT = 120

    def __init__(self, api_token, base_url):
        self.api_token = api_token
        self.base_url = base_url
        self.headers = {
            "Token": self.api_token,
            'Content-type': 'application/json'
        }
        self.requests = Namespace(post=self._post, get=self._get)

    def _post(self, *args, **kwargs):
        kwargs['timeout'] = (self.INTELIX_CONNECT_TIMEOUT, self.INTELIX_READ_TIMEOUT)
        return requests.post(*args, **kwargs)

    def _get(self, *args, **kwargs):
        kwargs['timeout'] = (self.INTELIX_CONNECT_TIMEOUT, self.INTELIX_READ_TIMEOUT)
        return requests.get(*args, **kwargs)

    def delete_paid_payment_from_queue(self, loan_ids):
        url = self.base_url + 'ecx_ws.php?function=del_queue'
        data_to_send = []
        for loan_id in loan_ids:
            data_to_send.append(dict(uid=loan_id))

        logger.info({
            'action': 'before hit delete queue intelix API',
            'data_to_send': json.dumps(data_to_send),
        })
        response = self.requests.post(
            url, headers=self.headers, data=json.dumps(data_to_send))
        status_code = response.status_code
        converted_response = response.json()
        logger.info({
            'action': 'intelix_delete_queue_paid_payment',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': converted_response
        })
        if status_code != 200:
            raise IntelixException(
                "Failed delete queue intelix, API status code %s" % status_code
            )
        if converted_response['result'] == 'Failed':
            failed_reason = ''
            # because if reason more than one its possible have more than 1 failed reason
            # so split each message by ;
            for failed_message in converted_response['failed']:
                failed_reason += failed_message['reason'] + "; "

            raise IntelixException(
                "Failed delete queue intelix, because %s" % failed_reason
            )
        return converted_response

    def download_system_call_results(self, start_date, end_date):
        data_to_send = {
            'start_date': start_date.strftime('%Y-%m-%d %H:%M:%S'),
            'end_date': end_date.strftime('%Y-%m-%d %H:%M:%S')
        }
        url = self.base_url + 'ecx_ws.php?function=call_result'

        logger.info({
            "action": 'download_system_call_results',
            "data_to_send": data_to_send,
            "url": url
        })

        start_time = time.time()
        response = self.requests.get(url=url, headers=self.headers, data=json.dumps(data_to_send))

        status_code = response.status_code
        logger.info({
            "action": 'download_system_call_results',
            "duration": round(time.time() - start_time, 3),
            "status_code": status_code
        })

        if status_code != 200:
            raise IntelixException(
                "Failed downloading call results, API status code %s" % status_code
            )

        return response.json()

    def upload_to_queue(self, data_to_send):
        url = self.base_url + 'ecx_ws.php?function=add_queue'

        logger.info({
            'action': 'upload_to_queue_intelix',
            'message': 'before hit upload queue intelix API',
            'data_to_send': json.dumps(data_to_send),
        })
        response = self.requests.post(
            url, headers=self.headers, data=json.dumps(data_to_send))
        status_code = response.status_code
        try:
            converted_response = response.json()
            if not converted_response:
                raise Exception("response is null or not on json format")
            logger.info({
                'action': 'intelix_upload_queue',
                'response_status': response.status_code,
            })
        except Exception as e:
            logger.exception({
                'action': 'intelix_upload_queue_failed_conversion',
                'response_status': response.status_code,
                'request': response.request.__dict__,
                'response': response.content
            })
            raise
        if status_code != 200:
            raise IntelixException(
                "Failed upload queue intelix, API status code %s" % status_code
            )

        if converted_response['result'].lower() == 'failed':
            raise IntelixException(
                "Failed upload queue intelix, because %s" % converted_response['reason']
            )

        return converted_response

    def get_agent_productivity_data(self, dialer_task):
        today = timezone.localtime(timezone.now())
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
        url = self.base_url + 'ecx_ws.php?function=agent_productivity'
        last_stored_dialer_task_date = DialerTask.objects.filter(
            type=DialerTaskType.AGENT_PRODUCTIVITY_EVERY_HOURS,
            status=DialerTaskStatus.STORED
        ).order_by('-cdate').values_list('cdate', flat=True).first()
        if not last_stored_dialer_task_date:
            last_stored_dialer_task_date = (today - timedelta(days=1)).replace(
                hour=21, minute=0, second=0
            )
        last_stored_dialer_task_date = date.strftime(
            timezone.localtime(last_stored_dialer_task_date), '%Y-%m-%d %H:%M:%S'
        )
        data_to_send = {
            'start_date': last_stored_dialer_task_date,
            'end_date': today.strftime('%Y-%m-%d %H:%M:%S')
        }
        response = self.requests.get(
            url, headers=self.headers, data=json.dumps(data_to_send)
        )
        status_code = response.status_code
        if status_code != 200:
            error_message = "Failed download agent productivity intelix, " \
                            "API status code %s" % status_code
            create_history_dialer_task_event(
                param=dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE),
                error_message=error_message
            )
            raise IntelixException(error_message)

        data = response.json()
        create_history_dialer_task_event(
            param=dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.DOWNLOADED,
                data_count=len(data)
            )
        )
        for result in data:
            agent_productivity = AgentProductivity.objects.filter(
                agent_name=result.get('AGENT_NAME'), hourly_interval=result.get('INTERVAL'),
                calling_date=parse(result.get('SUMMARY_DATE')))

            if not agent_productivity:
                AgentProductivity.objects.create(
                    agent_name=result.get('AGENT_NAME'),
                    hourly_interval=result.get('INTERVAL'),
                    calling_date=parse(result.get('SUMMARY_DATE')),
                    inbound_calls_offered=result.get('INBOUND_CALLS_OFFERED'),
                    inbound_calls_answered=result.get('INBOUND_CALLS_ANSWERED'),
                    inbound_calls_not_answered=result.get('INBOUND_CALLS_NOT_ANSWERED'),
                    outbound_calls_initiated=result.get('OUTBOUND_CALLS_INITIATED'),
                    outbound_calls_connected=result.get('OUTBOUND_CALLS_CONNECTED'),
                    outbound_calls_not_connected=result.get('OUTBOUND_CALLS_NOT_CONNECTED'),
                    outbound_calls_offered=result.get('OUTBOUND_CALLS_OFFERED'),
                    outbound_calls_answered=result.get('OUTBOUND_CALLS_ANSWERED'),
                    outbound_calls_not_answered=result.get('OUTBOUND_CALLS_NOT_ANSWERED'),
                    manual_in_calls_offered=result.get('MANUAL_IN_CALLS_OFFERED'),
                    manual_in_calls_answered=result.get('MANUAL_IN_CALLS_ANSWERED'),
                    manual_in_calls_not_answered=result.get('MANUAL_IN_CALLS_NOT_ANSWERED'),
                    manual_out_calls_initiated=result.get('MANUAL_OUT_CALLS_INITIATED'),
                    manual_out_calls_connected=result.get('MANUAL_OUT_CALLS_CONNECTED'),
                    manual_out_calls_not_connected=result.get('MANUAL_OUT_CALLS_NOT_CONNECTED'),
                    internal_in_calls_offered=result.get('INTERNAL_IN_CALLS_OFFERED'),
                    internal_in_calls_answered=result.get('INTERNAL_IN_CALLS_ANSWERED'),
                    internal_in_calls_not_answered=result.get('INTERNAL_IN_CALLS_NOT_ANSWERED'),
                    internal_out_calls_initiated=result.get('INTERNAL_OUT_CALLS_INITIATED'),
                    internal_out_calls_connected=result.get('INTERNAL_OUT_CALLS_CONNECTED'),
                    internal_out_calls_not_connected=result.get('INTERNAL_OUT_CALLS_NOT_CONNECTED'),
                    inbound_talk_time=result.get('INBOUND_TALK_TIME'),
                    inbound_hold_time=result.get('INBOUND_HOLD_TIME'),
                    inbound_acw_time=result.get('INBOUND_ACW_TIME'),
                    inbound_handling_time=result.get('INBOUND_HANDLING_TIME'),
                    outbound_talk_time=result.get('OUTBOUND_TALK_TIME'),
                    outbound_hold_time=result.get('OUTBOUND_HOLD_TIME'),
                    outbound_acw_time=result.get('OUTBOUND_ACW_TIME'),
                    outbound_handling_time=result.get('OUTBOUND_HANDLING_TIME'),
                    manual_out_call_time=result.get('MANUAL_OUT_CALL_TIME'),
                    manual_in_call_time=result.get('MANUAL_IN_CALL_TIME'),
                    internal_out_call_time=result.get('INTERNAL_OUT_CALL_TIME'),
                    internal_in_call_time=result.get('INTERNAL_IN_CALL_TIME'),
                    logged_in_time=result.get('LOGGED_IN_TIME'),
                    available_time=result.get('AVAILABLE_TIME'),
                    aux_time=result.get('AUX_TIME'),
                    busy_time=result.get('BUSY_TIME'),
                    login_ts=None if not result.get('LOGIN_TIME') else result.get('LOGIN_TIME'),
                    logout_ts=None if not result.get('LOGOUT_TIME') else result.get('LOGOUT_TIME'),
                )

        create_history_dialer_task_event(
            param=dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.STORED,
                data_count=len(data)
            )
        )

    def upload_account_payment_detail(self, data_to_send):
        url = self.base_url + 'ecx_ws.php?function=payment_detail'

        logger.info({
            'action': 'before hit payment detail intelix API',
            'data_to_send': json.dumps(data_to_send),
        })
        response = self.requests.get(
            url, headers=self.headers, data=json.dumps(data_to_send))
        status_code = response.status_code
        converted_response = response.json()
        logger.info({
            'action': 'upload_payment_detail',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': converted_response
        })
        if status_code != 200:
            raise IntelixException(
                "Failed upload payment detail intelix, API status code %s" % status_code
            )
        if converted_response['result'].lower() == 'failed':
            raise IntelixException(
                "Failed upload payment detail intelix, because %s" % converted_response['reason']
            )
        return converted_response

    def upload_grab_data(self, data_to_send):
        total_uploaded_data = 0
        url = self.base_url + 'ecx_ws.php?function=add_queue'

        logger.info({
            'action': 'upload_grab_data',
            'message': 'before hit upload queue intelix API for grab data',
            'total_data_to_send': len(data_to_send),
        })
        response = self.requests.post(
            url, headers=self.headers, data=json.dumps(data_to_send))
        status_code = response.status_code

        if not status_code == HTTPStatus.OK:
            logger.exception({
                'action': 'upload_grab_data',
                'message': 'failed to upload grab data to intellix',
                'response_status': response.status_code,
                'response': response.content
            })
            return status_code, total_uploaded_data

        # check is response can be converted to json fromat
        # to get the total data that uploaded successfully
        try:
            converted_response = response.json()
            if not converted_response:
                logger.exception({
                    'action': 'upload_grab_data',
                    'message': 'response is null or not on json format',
                    'response_status': response.status_code,
                    'response': response.content
                })
                return status_code, total_uploaded_data

            if converted_response['result'].lower() == 'failed':
                logger.exception({
                    'action': 'upload_grab_data',
                    'message': 'failed to upload grab data to intellix, because %s' %
                               converted_response['reason'],
                    'response_status': response.status_code,
                    'response': response.content
                })
                return status_code, total_uploaded_data

            total_uploaded_data = converted_response.get('rec_num')
            logger.info({
                'action': 'intelix_upload_queue',
                'message': 'success sent and convert data',
                'response_status': response.status_code,
                'total_uploaded_data': total_uploaded_data
            })
        except Exception as e:
            logger.exception({
                'action': 'upload_grab_data',
                'message': 'failed to convert intelix upload grab data to json format',
                'response_status': response.status_code,
                'response': response.content
            })
            return status_code, total_uploaded_data

        return status_code, total_uploaded_data


class JuloIntelixSFTPClient(object):
    def __init__(self, host, username, password, port):
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    def create_intelix_sftp_connection(self):
        cnopts = pysftp.CnOpts()
        cnopts.hostkeys = None

        return pysftp.Connection(
            host=self.host, username=self.username,
            password=self.password, port=self.port, cnopts=cnopts)

    def download_call_recording_file(self, tempdir, voice_path_file, temp_file_name):
        temp_file_name_store = "{}.wav".format(temp_file_name)
        with self.create_intelix_sftp_connection() as connection:
            local_path = os.path.join(tempdir, temp_file_name_store)
            logger.info({
                "action": "download_call_recording_file",
                "remote_path": voice_path_file,
                "local_path": local_path,
                "host": self.host
            })
            connection.get(voice_path_file, local_path)
            return local_path
