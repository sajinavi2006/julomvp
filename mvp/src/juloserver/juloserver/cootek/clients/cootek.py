from builtins import str
from builtins import object
import logging
import requests
import json
from juloserver.julo.services2 import get_redis_client
from juloserver.cootek.constants import CootekAIRobocall
from juloserver.julo.exceptions import JuloException
from datetime import timedelta
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst


class CootekClient(object):

    def __init__(self, api_key, api_secret_key, base_url):
        self.api_key = api_key
        self.api_secret_key = api_secret_key
        self.base_url = base_url
        self.token = self.__get_token_from_redis()
        self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT, self.AIRUDDER_RECOMMENDED_READ_TIMEOUT = \
            self.__get_recommended_timeout()
        self.logger = logging.getLogger(__name__)

    def __get_recommended_timeout(self):
        # get recommended timeout from feature_setting
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AIRUDDER_RECOMMENDED_TIMEOUT,
            is_active=True
        ).last()
        connect_timeout = 120
        read_timeout = 120
        if feature_setting:
            connect_timeout = feature_setting.parameters.get('recommended_connect_timeout', 120)
            read_timeout = feature_setting.parameters.get('recommended_read_timeout', 120)

        return connect_timeout, read_timeout

    def __get_token_from_redis(self):
        redisClient = get_redis_client()
        token = redisClient.get(CootekAIRobocall.REDIS_COOTEK_TOKEN_REDIS_KEY)
        return token

    def refresh_token(self):
        redisClient = get_redis_client()
        auth_api = self.base_url + '/auth'

        app_info = {
            'APPKey': self.api_key,
            'APPSecret': self.api_secret_key
        }

        response = requests.post(auth_api, data=app_info)
        if response.status_code == requests.codes.unauthorized:
            raise JuloException('Failed to Get Token from Cootek - Unauthorized')

        token = json.loads(response.text)['data']['token']
        redisClient.set(CootekAIRobocall.REDIS_COOTEK_TOKEN_REDIS_KEY, token, timedelta(hours=23))

        self.token = token
        return token


    def _make_request(self, method, url, retry_count=0, **kwargs):
        try:

            if self.token is None:
                self.refresh_token()

            response = requests.request(method, url, headers={'Authorization': 'Token ' + self.token}, **kwargs)


            if response.status_code == requests.codes.unauthorized:
                if retry_count >= CootekAIRobocall.MAX_RETRY_COUNT:
                    raise JuloException('Failed to Make Request to Cootek - Max Retry Reached')

                self.refresh_token()
                return self._make_request(method, url, retry_count=retry_count + 1, **kwargs)

            return response
        except Exception as e:
            raise JuloException(e)


    def cancel_phone_call_for_payment_paid_off(self, task_id, call_to):
        cancel_phone_call_url = self.base_url + '/cancelphonecall'
        cancel_phone_call_data = {
            'CalleeNumber': str(call_to),
            'TaskID': str(task_id)
        }

        logger_dict = {
            'action': 'cancel_phone_call_for_payment_paid_off',
            'message': 'Cancel phone call successfully!'
        }

        response = self._make_request(
            'POST', cancel_phone_call_url, json=cancel_phone_call_data, timeout=(
                self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT, self.AIRUDDER_RECOMMENDED_READ_TIMEOUT))
        if response.ok:
            self.logger.info(logger_dict)
        else:
            logger_dict['message'] = response.text
            self.logger.info(logger_dict)
            raise JuloException('Cannot cancel phone call with response %(response)s' % {'response': response} )

    def create_task(self, task_name, start_time, end_time, robot,
                    attempts, task_details):
        """
        Note for the reader:
        This function is used in the process_call_customer_via_cootek task.
        If there is changes on the usage of `robot`, please consider the process_call_customer_via_cootek.
        """
        create_task_url = self.base_url + '/v2/task'
        robot_id = robot.robot_identifier
        task_data = {
            'TaskName': task_name,
            'ScheduleStartTime': start_time.strftime("%Y-%m-%d %X"),
            'ScheduleEndTime': end_time.strftime("%Y-%m-%d %X"),
            'RobotID': robot_id,
            'SIPLine': CootekAIRobocall.SIP_LINE,
            'RepeatInterval': 10,
            'RepeatNumber': attempts,
            'Details': task_details,
            'Perform': 1,
        }
        if robot.is_group_method:
            task_data.update(RobotMethod='group')

        response = self._make_request('POST', create_task_url, json=task_data, timeout=(10, 150))

        if response.ok:
            parsed_response = json.loads(response.text)
            response_data = parsed_response.get('data')
            error_details = response_data.get('detail_error_list', [])
            if not response_data:
                raise JuloException(parsed_response)
            task_id = response_data.get('TaskID')
            if not task_id:
                raise JuloException(parsed_response)
            logging.info(
                {
                    'action': 'payload cootek_create_task',
                    'data': {
                        'ScheduleStartTime': start_time.strftime("%Y-%m-%d %X"),
                        'ScheduleEndTime': end_time.strftime("%Y-%m-%d %X"),
                    },
                    'error': error_details,
                }
            )
            return task_id
        else:
            self.logger.info({
                'action': 'create_task_to_cootek',
                'error': 'can not create task'
            })
            raise JuloException('Failed to Create Task to Cootek with response: %(response)s' % {'response': response} )


    def get_task_details(self, task_id, retries_times=0, mock_url=None):
        get_details_url = self.base_url + '/detail'
        if mock_url:
            get_details_url = mock_url

        task_detail = {
            'TaskID': task_id
        }
        connect_timeout = self.AIRUDDER_RECOMMENDED_CONNECT_TIMEOUT
        read_timeout = self.AIRUDDER_RECOMMENDED_READ_TIMEOUT
        if retries_times:
            # we add 5 sec each retries
            connect_timeout = connect_timeout + (5 * retries_times)
            read_timeout = read_timeout + (5 * retries_times)
        response = self._make_request(
            'GET', get_details_url, params=task_detail, timeout=(
                connect_timeout, read_timeout))

        if response.ok:
            parsed_response = json.loads(response.text)
            details = parsed_response['data']
            if not details:
                raise JuloException(parsed_response)
            return details
        else:
            self.logger.info({
                'action': 'get_task_details_from_cootek',
                'error': 'can not get task_detail from cootek'
            })
            raise JuloException('Cannot get Task detail from Cootek with response %(response)s' % {'response': response} )
