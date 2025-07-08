from builtins import str
from builtins import object
import logging
from typing import (
    List, Dict
)
from enum import Enum

import pytz
import requests
import json
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.exceptions import JuloException
from datetime import timedelta, datetime

from juloserver.minisquad.constants import (
    RedisKey,
    AIRudderPDSConstant,
    AiRudder
)

logger = logging.getLogger(__name__)


class AIRudderErrorCodes(Enum):
    NOT_RETURN_ERROR_CODE = (
        1, "AI Rudder not returning error_code param",
        "response json can be not provided error_code or maybe return is not json format")
    REQUEST_MARSH_ERROR = (-1, "Internal error", "CreateTaskAPI request marsh error")
    INTERNAL_ERROR = (10201, "Internal error", "There is an internal service error.")
    INVALID_APP_KEY = (10301, "Invalid app key", "Invalid appkey, please contact AI Rudder team.")
    ACCOUNT_VERIFICATION_FAILED = (
        10302, "Account verification failed", "User information verification failed.")
    TASK_CREATION_FAILED = (
        10501, "Task creation failed", "Task creation failed.")
    TASK_ID_NULL = (10502, "TaskID is null", "TaskID is empty.")
    CALLBACK_URL_NULL = (10503, "Callback url is null", "Callback url is empty.")
    INVALID_CALLBACK_URL = (10504, "Invalid callback url", "Invalid callback url.")
    CONTACT_LIST_NULL = (10505, "ContactList is null", "Contact list is empty.")
    TASK_NOT_FOUND = (10506, "Task is not found", "Task is not found.")
    TASK_NOT_EXECUTED = (10507, "Task has not been executed", "Task has not been executed.")
    DUPLICATE_TASK_NAME = (10508, "Task Name is duplicated", "Duplicate task names.")
    SCHEDULED_TIME_EARLIER_THAN_CURRENT = (
        10509, "The scheduled start time can not be earlier than the current time",
        "The scheduled task start time is earlier than the current time.")
    INVALID_PHONE_NUMBER = (
        10510, "Incorrect phone number",
        "Incorrect phone number format. The correct format should start with + "
        "and not exceed 14 digits.")
    GROUP_NOT_FOUND = (10511, "The group is not found.", "The skill group is not found.")
    NULL_GROUP_NAME = (10512, "The groupName is null.", "The groupName is empty.")
    TASK_FINISHED = (10513, "Task has finished.", "Task has finished.")
    TASK_NOT_STARTED_YET = (10514, "Task has not started yet.", "Task has not started yet.")
    TASK_NOT_FINISHED = (10515, "Task has not finished.", "Task has not finished.")
    NO_RECORDINGS_FOR_TASK = (
        10516, "No recordings for the task.", "Task does not have any recording.")
    INVALID_PRIVATE_DATA = (
        10517, "Invalid privateData [Data]",
        "Invalid user private data, e.g. it has incorrect length.")
    INVALID_TASK_NAME = (
        10518, "Invalid TaskName",
        "Invalid task name (non-alphanumeric and underscore characters present)")
    EMPTY_COPIED_TASK = (
        10519, "Copied task is empty.", "The copied task name is empty.")
    INCORRECT_TASK_PAUSE_TIME = (
        10520, "Incorrect Task Pause Time", "Task pause time is not in correct format.")
    INVALID_REPEAT_TIMES = (
        10521, "invalid RepeatTimes", "repeatTimes is invalid.")
    INVALID_BULK_CALL_INTERVAL = (
        10522, "invalid BulkCallInterval", "bulkCallInterval is invalid.")
    INVALID_VOICEMAIL_CONFIG = (
        10523, "invalid Voicemail Config", "Voicemail configuration is invalid.")
    INVALID_QA_CONFIG = (10524, "invalid QA Config", "QA configuration is invalid.")
    INVALID_MAX_LOST_RATE = (
        10525, "invalid Max Lost Rate", "The maximum lost rate is invalid.")
    INVALID_CONTACT_NUMBER_INTERVAL = (
        10526, "invalid Contact Number Interval",
        "Dialing interval for multiple numbers is invalid.")
    TASK_ADDITION_LIMIT_REACHED = (
        10527, "This task cannot be added to the list",
        "No more contacts can be added after the task is created.")
    INVALID_AGENT_NAME = (10550, "Invalid agentName", "The name of the agent is invalid.")
    AGENT_NOT_IN_GROUP = (
        10551, "agentName is not in the group", "The agent does not belong to the group.")
    TASK_NOT_STARTED = (
        10605, "The task is not in the status of NOT Started",
        "The task is not in the status of NOT Started.")
    CHECK_TASK_FAILED = (10606, "Check Task failed", "Check task failed.")
    CHECK_TASK_DETAIL_FAILED = (10607, "Check TaskDetail failed", "Failed to check task details.")
    NULL_CALL_ID = (10608, "CallID is null", "Call ID is empty.")
    INVALID_CALL_ID = (10609, "CallID is invalid", "Call ID is invalid.")
    UNVERIFIABLE_CALL_ID = (10610, "CallID can’t be verified", "Call ID cannot be verified.")
    CALL_NOT_FINISHED = (10611, "The call of the CallID is not finished", "Call has not finished.")
    CALL_NOT_TALKED = (
        10612, "The call of the CallID is not talked",
        "The call of the Callid is not answered by the agent.")
    TASK_NOT_RUNNING = (
        10613, "The task is not in the status of Running",
        "The task is not in the status of Running.")
    TASK_NOT_PAUSED = (
        10614, "The task is not in the status of Paused", "The task is not in the status of Paused."
    )
    MISSING_CUSTOMER_INFO = (
        10617, "No customer info configured", "Customer information is not configured.")
    MISSING_PHONE_NUMBER_FIELD = (
        10618, "The PhoneNumber field of customer info is not configured",
        "The PhoneNumber field of customer info is not configured.")
    INVALID_TASK_TIME_INTERVAL = (
        10620, "At least 5 minutes between task start time and task end time",
        "Task end time should be at least 5 minutes later than task start time.")
    INVALID_TASK_TIME_DAY = (
        10621, "Task start time and task end time must be on the same day",
        "Task start time and task end time must be on the same day.")
    INVALID_TASK_ID = (
        10702, "TaskID is invalid", "Invalid Task ID, no corresponding task found.")
    UNVERIFIABLE_TASK_ID = (10703, "TaskID can’t be verified", "TaskID cannot be verified.")
    INVALID_WORKFLOW_TASK_OPERATION = (
        10704, "The workflow task cannot perform this operation",
        "Workflow tasks cannot be copied, started, paused, resumed, etc.")
    QUERY_LIMIT_EXCEEDED = (
        10705, "The number of queries exceeds the number limit",
        "The number of queries exceeds the number limit.")
    INVALID_USER_CREDENTIALS = (
        10801, "Invalid username or password", "Invalid username or password")
    USER_NOT_AGENT = (
        10802, "The role of user is not an agent", "User’s role is not an Agent.")
    INVALID_USER_ORGANIZATION = (
        10803, "The organization of the user is invalid", "User’s organization is invalid.")
    EMPTY_USER_TOKEN = (10810, "User token is empty", "User Token is empty.")
    USER_TOKEN_PARSING_ERROR = (10811, "User token parsing error", "User Token parsing error.")
    INVALID_USER_TOKEN = (10812, "Invalid user token", "Invalid user token")
    EXPIRED_USER_TOKEN = (10813, "Expired user token", "Expired user token")
    USER_NOT_FOUND = (10814, "User is not found", "User is not found.")
    MISSING_FILE = (10820, "File doesn’t exist", "File does not exist.")
    VOICEMAIL_NOT_ENABLED = (
        10901, "Voicemail configuration is not enabled",
        "The voicemail configuration of the company is not enabled.")

    def __init__(self, code, message, description):
        self._code = code
        self._message = message
        self._description = description

    @property
    def code(self):
        return self._code

    @property
    def message(self):
        return self._message

    @property
    def description(self):
        return self._description


ERROR_MAPPING_CODE = {
    0: None,  # This is a placeholder for successful response
    1: AIRudderErrorCodes.NOT_RETURN_ERROR_CODE,
    -1: AIRudderErrorCodes.REQUEST_MARSH_ERROR,
    10201: AIRudderErrorCodes.INTERNAL_ERROR,
    10301: AIRudderErrorCodes.INVALID_APP_KEY,
    10302: AIRudderErrorCodes.ACCOUNT_VERIFICATION_FAILED,
    10501: AIRudderErrorCodes.TASK_CREATION_FAILED,
    10502: AIRudderErrorCodes.TASK_ID_NULL,
    10503: AIRudderErrorCodes.CALLBACK_URL_NULL,
    10504: AIRudderErrorCodes.INVALID_CALLBACK_URL,
    10505: AIRudderErrorCodes.CONTACT_LIST_NULL,
    10506: AIRudderErrorCodes.TASK_NOT_FOUND,
    10507: AIRudderErrorCodes.TASK_NOT_EXECUTED,
    10508: AIRudderErrorCodes.DUPLICATE_TASK_NAME,
    10509: AIRudderErrorCodes.SCHEDULED_TIME_EARLIER_THAN_CURRENT,
    10510: AIRudderErrorCodes.INVALID_PHONE_NUMBER,
    10511: AIRudderErrorCodes.GROUP_NOT_FOUND,
    10512: AIRudderErrorCodes.NULL_GROUP_NAME,
    10513: AIRudderErrorCodes.TASK_FINISHED,
    10514: AIRudderErrorCodes.TASK_NOT_STARTED_YET,
    10515: AIRudderErrorCodes.TASK_NOT_FINISHED,
    10516: AIRudderErrorCodes.NO_RECORDINGS_FOR_TASK,
    10517: AIRudderErrorCodes.INVALID_PRIVATE_DATA,
    10518: AIRudderErrorCodes.INVALID_TASK_NAME,
    10519: AIRudderErrorCodes.EMPTY_COPIED_TASK,
    10520: AIRudderErrorCodes.INCORRECT_TASK_PAUSE_TIME,
    10521: AIRudderErrorCodes.INVALID_REPEAT_TIMES,
    10522: AIRudderErrorCodes.INVALID_BULK_CALL_INTERVAL,
    10523: AIRudderErrorCodes.INVALID_VOICEMAIL_CONFIG,
    10524: AIRudderErrorCodes.INVALID_QA_CONFIG,
    10525: AIRudderErrorCodes.INVALID_MAX_LOST_RATE,
    10526: AIRudderErrorCodes.INVALID_CONTACT_NUMBER_INTERVAL,
    10527: AIRudderErrorCodes.TASK_ADDITION_LIMIT_REACHED,
    10550: AIRudderErrorCodes.INVALID_AGENT_NAME,
    10551: AIRudderErrorCodes.AGENT_NOT_IN_GROUP,
    10605: AIRudderErrorCodes.TASK_NOT_STARTED,
    10606: AIRudderErrorCodes.CHECK_TASK_FAILED,
    10607: AIRudderErrorCodes.CHECK_TASK_DETAIL_FAILED,
    10608: AIRudderErrorCodes.NULL_CALL_ID,
    10609: AIRudderErrorCodes.INVALID_CALL_ID,
    10610: AIRudderErrorCodes.UNVERIFIABLE_CALL_ID,
    10702: AIRudderErrorCodes.INVALID_TASK_ID,
    10703: AIRudderErrorCodes.UNVERIFIABLE_TASK_ID,
    10704: AIRudderErrorCodes.INVALID_WORKFLOW_TASK_OPERATION,
    10705: AIRudderErrorCodes.QUERY_LIMIT_EXCEEDED,
    10801: AIRudderErrorCodes.INVALID_USER_CREDENTIALS,
    10802: AIRudderErrorCodes.USER_NOT_AGENT,
    10803: AIRudderErrorCodes.INVALID_USER_ORGANIZATION,
    10810: AIRudderErrorCodes.EMPTY_USER_TOKEN,
    10811: AIRudderErrorCodes.USER_TOKEN_PARSING_ERROR,
    10812: AIRudderErrorCodes.INVALID_USER_TOKEN,
    10813: AIRudderErrorCodes.EXPIRED_USER_TOKEN,
    10814: AIRudderErrorCodes.USER_NOT_FOUND,
    10820: AIRudderErrorCodes.MISSING_FILE,
    10901: AIRudderErrorCodes.VOICEMAIL_NOT_ENABLED,
}


class AIRudderPDSClient(object):
    '''
        AI Rudder PDS ( Predictive Dialer System ) is third party for calling our due customer
    '''
    AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT = 120
    AIRUDDER_RECOMMENDED_READ_TIMEOUT = 120
    PDS_URL_PATH = '/service/callcenter/call/predict'

    def __init__(self, api_key, api_secret_key, base_url):
        self.api_key = api_key
        self.api_secret_key = api_secret_key
        self.base_url = base_url
        self.token = self.__get_token_from_redis()
        self.logger = logging.getLogger(__name__)

    def __get_token_from_redis(self):
        redisClient = get_redis_client()
        token = redisClient.get(RedisKey.AIRUDDER_PDS_BEARER_TOKEN_KEY)
        return token

    def refresh_token(self):
        redisClient = get_redis_client()
        auth_api = self.base_url + self.PDS_URL_PATH + '/auth'

        app_info = {
            'APPKey': self.api_key,
            'APPSecret': self.api_secret_key
        }

        response = requests.post(auth_api, data=app_info)
        parsed_response = json.loads(response.text)
        self.logger.info({
            'action': 'refresh_token',
            'message': 'raw response from airudder',
            'data': parsed_response
        })
        if response.status_code == requests.codes.unauthorized:
            raise JuloException('Failed to Get Token from AI Rudder PDS - Unauthorized')
        converted_response = json.loads(response.text)
        if converted_response.get('code', 1) != 0:
            raise JuloException('Failed to Get Token from AI Rudder PDS - {}'.format(response.text))
        body_response = converted_response .get('body')
        token = body_response.get('token')
        redisClient.set(RedisKey.AIRUDDER_PDS_BEARER_TOKEN_KEY, token, timedelta(hours=23))
        self.token = token
        return token

    def _make_request(self, method: str, url: str, retry_count=0, **kwargs):
        response = None
        try:

            if self.token is None:
                self.refresh_token()
            headers = {
                'Authorization': 'Token ' + self.token,
                'Content-Type': 'application/json'
            }
            response = requests.request(
                method, url, headers=headers, **kwargs)

            if response.status_code == requests.codes.unauthorized:
                if retry_count >= AIRudderPDSConstant.REQUEST_MAX_RETRY_COUNT:
                    raise JuloException('Failed to Make Request to Cootek - Max Retry Reached')

                self.refresh_token()
                return self._make_request(method, url, retry_count=retry_count + 1, **kwargs)

            parsed_response = json.loads(response.text)
            if parsed_response.get('code', 1) != 0:
                self.logger.info({
                    'action': '_make_request',
                    'message': 'raw response from airudder',
                    'data': parsed_response
                })

            return response
        except Exception as e:
            raise JuloException(e)

    def cancel_phone_call_by_phone_numbers(self, task_id: str, phone_numbers: List):
        cancel_phone_call_url = self.base_url + self.PDS_URL_PATH + '/canceltaskcontacts'
        cancel_phone_call_data = {
            'contactList': phone_numbers,
            'TaskID': task_id
        }

        logger_dict = {
            'action': 'cancel_phone_call_by_phone_numbers',
            'message': 'start cancel phones numbers',
            'data': cancel_phone_call_data
        }
        response = self._make_request(
            'POST', cancel_phone_call_url, data=json.dumps(cancel_phone_call_data), timeout=(self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT, self.AIRUDDER_RECOMMENDED_READ_TIMEOUT))
        parsed_response = json.loads(response.text)
        if parsed_response.get('code', 1) == 0:
            self.logger.info(logger_dict)
            return parsed_response
        else:
            logger_dict['message'] = response.text
            self.logger.info(logger_dict)
            raise JuloException(
                'Cannot cancel phone call with code {} and message {}'.format(
                    parsed_response.get('code', 1), parsed_response.get('status', '')))

    def query_task_list(
            self, check_start_time: datetime, check_end_time: datetime, limit=500,
            is_custom_filter=False, task_name: str = None, state: str = None,
            check_field_time=None, order_by=None, retries_time: int = 0):
        '''
            1. limit param is required by AI rudder so default limit is 50
            2. state param is not required but the value list you can choose
                ‘Creating’, 'Not Started', 'Running', 'Paused', 'Cancelled', and 'Finished'
            3. check_field_time param is can be filled but default value will always cdate
            4. order_by param have default value CreatedAt, but have values
                actualStartTime, startTime, endTime
            5. is_custom_filter param please set True if you want to use the other params
        '''
        connect_timeout = (retries_time * 60) + self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT
        read_timeout = (retries_time * 60) + self.AIRUDDER_RECOMMENDED_READ_TIMEOUT
        get_details_url = self.base_url + self.PDS_URL_PATH + '/querytasklist'
        logger.info({
            'action': 'query_task_list',
            'message': 'prepare to hit',
            'timeout': '{}, {}'.format(connect_timeout, read_timeout)
        })

        payload = {
            'minstarttime': check_start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'maxstarttime': check_end_time.strftime('%Y-%m-%d %H:%M:%S'),
            'limit': limit,
        }
        if is_custom_filter:
            if task_name:
                payload.update({'taskName': task_name})
            if state:
                payload.update({'state': state})
            if check_field_time:
                payload.update({'filterTime': check_field_time})
            if order_by:
                payload.update({'orderBy': order_by})

        response = self._make_request(
            'POST', get_details_url, data=json.dumps(payload),
            timeout=(connect_timeout, read_timeout))
        parsed_response = json.loads(response.text)
        if parsed_response.get('code', 1) != 0:
            self.logger.info({
                'action': 'check_task_list',
                'error': response.text
            })
            raise JuloException('Cannot get Task detail from Cootek with code {} and message {}'.format(
                    parsed_response.get('code', 1), parsed_response.get('status', '')))

        if not parsed_response.get('message'):
            raise JuloException(
                "AI Rudder PDS: query_task_list dont have message response. {}".format(
                    parsed_response))

        status = parsed_response['message']
        if not status == AIRudderPDSConstant.SUCCESS_MESSAGE_RESPONSE:
            raise JuloException("AI Rudder PDS: {}".format(status))
        details = parsed_response.get('body')
        if not details:
            raise JuloException(parsed_response)

        return details

    def query_task_detail(
        self,
        task_id: str,
        call_id: str = '',
        limit: int = 1,
        offset: int = 0,
        start_time: datetime = None,
        end_time: datetime = None,
        retries_time: int = 0,
        need_customer_info: bool = False,
    ):
        connect_timeout = (retries_time * 60) + self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT
        read_timeout = (retries_time * 60) + self.AIRUDDER_RECOMMENDED_READ_TIMEOUT
        query_task_detail_url = self.base_url + self.PDS_URL_PATH + '/querytaskdetail'
        logger.info({
            'action': 'query_task_list',
            'message': 'prepare to hit',
            'timeout': '{}, {}'.format(connect_timeout, read_timeout)
        })
        query_task_detail_data = {
            "taskId": task_id,
            "limit": limit,
            "orderBy": "calltime",
            "offset": offset,
            "needCustomerInfo": need_customer_info,
        }
        if limit == 0:
            query_task_detail_data.pop("limit")

        if call_id != '':
            query_task_detail_data.update({"like": [{"field": "callid", "pattern": call_id}]})

        if start_time:
            query_task_detail_data.update(
                {"minstarttime": start_time.strftime('%Y-%m-%d %H:%M:%S')})

        if end_time:
            query_task_detail_data.update(
                {"maxstarttime": end_time.strftime('%Y-%m-%d %H:%M:%S')})

        logger_dict = {
            'action': 'query_task_detail',
            'message': 'start query task detail',
            'data': query_task_detail_data
        }
        response = self._make_request(
            'POST', query_task_detail_url, data=json.dumps(query_task_detail_data),
            timeout=(connect_timeout, read_timeout))
        parsed_response = json.loads(response.text)
        if parsed_response.get('code', 1) == 0:
            self.logger.info(logger_dict)
            return parsed_response
        else:
            logger_dict['message'] = response.text
            self.logger.info(logger_dict)
            raise JuloException(
                'Cannot query task detail with code {} and message {}'.format(
                    parsed_response.get('code', 1), parsed_response.get('status', '')))

    def get_recording_url_by_call_id(self, call_id: str):
        '''
            this API will get download address of recording files from AIRudder with WAV extention
        '''
        recording_by_call_id_url = self.base_url + self.PDS_URL_PATH + '/case/recording'
        recording_by_call_id_data = {
            'callid': call_id
        }
        logger_dict = {
            'action': 'get_recording_url_by_call_id',
            'data': recording_by_call_id_data
        }
        response = self._make_request(
            'POST', recording_by_call_id_url, data=json.dumps(recording_by_call_id_data),
            timeout=(self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT, self.AIRUDDER_RECOMMENDED_READ_TIMEOUT))
        parsed_response = json.loads(response.text)
        if parsed_response.get('code', 1) == 0:
            self.logger.info(logger_dict)
            return parsed_response
        else:
            logger_dict['message'] = response.text
            self.logger.error(logger_dict)
            return dict()

    def create_task(
            self, task_name: str, start_time: datetime, end_time: datetime, group_name: str,
            list_contact_to_call: List[Dict], call_back_url: str = '', strategy_config: Dict = None,
            partner_name: str = ''
    ):
        fn_name = 'AIRudderPDSCLient.create_task'
        self.logger.info({
            'action': fn_name,
            'identifier': task_name,
            'state': 'start'
        })
        strategy_configuration = {}
        if strategy_config:
            strategy_configuration = strategy_config

        end_point_url = self.base_url + self.PDS_URL_PATH + '/createtask'
        bulk_call_interval = int(strategy_configuration.get('bulkCallInterval', 120))
        if bulk_call_interval < 60:
            bulk_call_interval = 60

        payload = {
            "taskName": task_name,
            "startTime": start_time.strftime('%Y-%m-%d %H:%M:%S') if start_time else start_time,
            "autoEndTime": end_time.strftime('%Y-%m-%d %H:%M:%S'),
            "groupName": group_name,
            "agentName": [],
            "remark": task_name,
            "restTimes": strategy_configuration.get('restTimes', []),
            "callback": call_back_url,
            "contactList": [],
            "dialingOrder": strategy_configuration.get('dialingOrder', []),
            "autoSlotFactor": int(strategy_configuration.get('autoSlotFactor', 0)),
            "callInterval": int(strategy_configuration.get('callInterval', 0)),
            "acwTime": int(strategy_configuration.get('acwTime', 15)),
            "maxLostRate": float(strategy_configuration.get('maxLostRate', 0.0)),
            "contactNumberInterval": int(strategy_configuration.get('contactNumberInterval', 0)),
            "ringLimit": int(strategy_configuration.get('ringLimit', 0)),
            "dialingMode": int(strategy_configuration.get('dialingMode', 0)),
            "repeatTimes": int(strategy_configuration.get('repeatTimes', 1)),
            "bulkCallInterval": bulk_call_interval,
            "autoQa": strategy_configuration.get('autoQA', "Y"),
            "qaConfigId": int(strategy_configuration.get('qaConfigId', 142)),
            "qaLimitLength": int(strategy_configuration.get('qaLimitLength', 0)),
            "qaLimitRate": int(strategy_configuration.get('qaLimitRate', 100)),
            "voicemailRedial": int(strategy_configuration.get('voicemailRedial', 0)),
            "voicemailCheck": int(strategy_configuration.get('voicemailCheck', 0)),
        }
        if payload['voicemailCheck'] == 1:
            payload['voicemailCheckDuration'] = int(
                strategy_configuration.get('voicemailCheckDuration', 0)
            )
            payload['voicemailHandle'] = int(strategy_configuration.get('voicemailHandle', 1))

        if partner_name == AiRudder.GRAB:
            payload['templateName'] = AiRudder.GRAB_TEMPLATE_NAME
        if partner_name == AiRudder.DANA:
            payload['templateName'] = AiRudder.DANA_TEMPLATE_NAME
        if partner_name == AiRudder.SALES_OPS:
            payload['templateName'] = AiRudder.SALES_OPS_TEMPLATE_NAME

        if strategy_configuration.get('slotFactor', 0):
            payload['slotFactor'] = float(strategy_configuration.get('slotFactor', 2.5))

        if strategy_configuration.get('autoQA', "Y") == "Y":
            payload['autoQA'] = strategy_configuration.get('autoQA', "Y")
            payload['qaConfigId'] = int(strategy_configuration.get('qaConfigId', 142))

        if strategy_configuration.get('resultStrategies', "off") == "on":
            payload['resultStrategies'] = strategy_configuration.get('resultStrategiesConfig', [])

        self.logger.info({
            'action': fn_name,
            'identifier': task_name,
            'state': 'preparation_before_create_task',
            'config': payload
        })
        # set customer that will call, we separate it because we want to record our config on logger
        # also prevent log size bigger
        payload["customizeContacts"] = list_contact_to_call
        response = self._make_request(
            'POST', end_point_url, data=json.dumps(payload),
            timeout=(
                self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT, self.AIRUDDER_RECOMMENDED_READ_TIMEOUT))
        parsed_response = json.loads(response.text)
        self.logger.info({
            'action': fn_name,
            'identifier': task_name,
            'state': 'API_success'
        })
        response_code_param = ERROR_MAPPING_CODE.get(parsed_response.get('code', 1))
        if response_code_param is None:
            self.logger.info({
                'action': fn_name,
                'identifier': task_name,
                'response': response.text
            })
            return parsed_response
        else:
            self.logger.error({
                'action': fn_name,
                'identifier': task_name,
                'response': response.text,
                'payload': payload
            })
            raise JuloException(
                'Cannot create new tasks with error code {} {} {}'.format(
                    response_code_param.code, response_code_param.message,
                    response_code_param.description)
            )

    def copy_task(
        self,
        task_name: str,
        from_task_name: str,
        group_name: str,
        strategy_config: Dict = None,
    ):
        fn_name = 'AIRudderPDSClient.copy_task'
        self.logger.info({'action': fn_name, 'identifier': task_name, 'state': 'start'})

        loc = pytz.timezone("Asia/Jakarta")
        now = datetime.now(loc)

        # End Time
        try:
            end_hour, end_minute = map(int, strategy_config.get("end_time", "20:00").split(":"))
        except ValueError:
            end_hour, end_minute = 20, 0
        end_time = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        auto_end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

        # Rest Times
        rest_times = [{"start": "12:00:00", "end": "13:00:00"}]
        if strategy_config.get("rest_times"):
            rest_times = [
                {"start": rt[0] + ":00", "end": rt[1] + ":00"}
                for rt in strategy_config["rest_times"]
            ]

        # Parsing numbers
        def safe_int(val, default=0):
            return int(val) if str(val).isdigit() else default

        def safe_float(val, default=0.0):
            try:
                return float(val)
            except:
                return default

        repeat_times = safe_int(strategy_config.get("repeatTimes", 3))
        max_lost_rate = safe_float(strategy_config.get("maxLostRate", "1.5"))
        contact_number_interval = safe_int(strategy_config.get("contactNumberInterval", 3))
        dialing_mode = safe_int(strategy_config.get("dialingMode", 0))
        qa_limit_length = safe_int(strategy_config.get("qaLimitLength", 0))
        qa_limit_rate = safe_int(strategy_config.get("qaLimitRate", 100))
        qa_config_id = safe_int(strategy_config.get("qaConfigId", 142))
        auto_qa = strategy_config.get("autoQA", "Y") or "Y"
        result_strategies = strategy_config.get("result_strategies")

        strategy_configuration = {}
        if strategy_config:
            strategy_configuration = strategy_config

        end_point_url = self.base_url + self.PDS_URL_PATH + '/copytask'
        bulk_call_interval = int(strategy_configuration.get('bulkCallInterval', 120))
        if bulk_call_interval < 60:
            bulk_call_interval = 60

        payload = {
            "taskName": task_name,
            "startTime": "",
            "autoEndTime": auto_end_time_str,
            "groupName": group_name,
            "agentName": [],
            "remark": task_name,
            "restTimes": rest_times,
            "repeatTimes": repeat_times,
            "bulkCallInterval": bulk_call_interval,
            "maxLostRate": max_lost_rate,
            "contactNumberInterval": contact_number_interval,
            "dialingMode": dialing_mode,
            "autoQa": auto_qa,
            "qaConfigId": qa_config_id,
            "qaLimitLength": qa_limit_length,
            "qaLimitRate": qa_limit_rate,
            "fromTask": from_task_name,
            "noanswerOnly": "Y",
            "resultStrategies": result_strategies,
            "ignoreCancelled": "Y",
        }

        if strategy_configuration.get('autoQA', "Y") == "Y":
            payload['autoQA'] = strategy_configuration.get('autoQA', "Y")
            payload['qaConfigId'] = int(strategy_configuration.get('qaConfigId', 142))

        self.logger.info(
            {
                'action': fn_name,
                'identifier': task_name,
                'state': 'preparation_before_copy_task',
                'config': payload,
            }
        )

        response = self._make_request(
            'POST',
            end_point_url,
            data=json.dumps(payload),
            timeout=(
                self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT,
                self.AIRUDDER_RECOMMENDED_READ_TIMEOUT,
            ),
        )
        parsed_response = json.loads(response.text)
        self.logger.info({'action': fn_name, 'identifier': task_name, 'state': 'API_success'})
        response_code_param = ERROR_MAPPING_CODE.get(parsed_response.get('code', 1))
        if response_code_param is None:
            self.logger.info(
                {'action': fn_name, 'identifier': task_name, 'response': response.text}
            )
            return parsed_response
        else:
            self.logger.error(
                {
                    'action': fn_name,
                    'identifier': task_name,
                    'response': response.text,
                    'payload': payload,
                }
            )
            raise JuloException(
                'Cannot copy task with error code {} {} {}'.format(
                    response_code_param.code,
                    response_code_param.message,
                    response_code_param.description,
                )
            )
