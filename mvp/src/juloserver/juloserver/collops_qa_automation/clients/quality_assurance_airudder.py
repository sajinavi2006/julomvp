from builtins import object
import logging
import requests
import json

from juloserver.collops_qa_automation.constant import QAAirudderResponse, QAAirudderTaskAction
from juloserver.collops_qa_automation.exceptions import QAAirudderException


class QAAirudderEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return str(obj, encoding='utf-8')

        return json.JSONEncoder.default(self, obj)


class QualityAssuranceAirudder(object):

    def __init__(self, api_key, api_secret_key, base_url):
        self.api_key = api_key
        self.api_secret_key = api_secret_key
        self.base_url = base_url
        self.token = self.__get_token()
        self.logger = logging.getLogger(__name__)

    def __get_token(self):
        auth_api = self.base_url + 'customer_token'

        app_info = {
            'APPKey': self.api_key,
            'APPSecret': self.api_secret_key
        }

        response = requests.post(auth_api, json=app_info)
        if response.status_code == requests.codes.unauthorized:
            raise QAAirudderException('Failed to Get Token from QualityAssuranceAirudder - Unauthorized')

        token = json.loads(response.text)['data']['token']
        self.token = token
        return token

    def _make_request(self, method, url, retry_count=0, is_multipart=False, **kwargs):
        try:

            if self.token is None:
                self.__get_token()

            headers = {'Authorization': 'Bearer ' + self.token}
            if is_multipart:
                headers["Content-Type"] = "application/json"

            response = requests.request(method, url, headers=headers, **kwargs)

            if response.status_code == requests.codes.unauthorized:
                if retry_count >= 3:
                    raise QAAirudderException('Failed to Make Request to QA Airudder - Max Retry Reached')

                return self._make_request(method, url, retry_count=retry_count + 1, **kwargs)

            return response
        except Exception as e:
            raise QAAirudderException(e)

    def create_task(self, task_name):
        create_task_url = self.base_url + 'task'
        task_data = {
            "TaskName": task_name,
            "Language": "id_BA",
            "SOPModel": "2"
        }
        response = self._make_request('POST', create_task_url, json=task_data)

        if response.ok:
            parsed_response = json.loads(response.text)
            task_id = parsed_response['data']['TaskID']
            if not task_id:
                task_id = None

            return task_id, parsed_response['status'], parsed_response['code']
        else:
            self.logger.info({
                'action': 'create_task_to_QA_airudder',
                'error': 'can not create task',
                'response': response
            })
            raise QAAirudderException('Failed to Create Task to QA Airudder'
                                ' with response: %(response)s' % {'response': response})

    def upload_recording_file_to_airudder(self, task_id, recording_details):
        upload_url = self.base_url + 'task/recording'
        upload_recording_file_data = {
            'TaskID': task_id,
            'RecordingDetails': recording_details  # array of dict
        }
        self.logger.info({
            'action': 'upload_recording_file_to_airudder',
            'message': 'try to hit API'
        })
        response = self._make_request(
            'POST', upload_url, is_multipart=True, data=json.dumps(
                upload_recording_file_data, cls=QAAirudderEncoder)
        )
        self.logger.info({
            'action': 'upload_recording_file_to_airudder',
            'message': 'finish hit API'
        })
        if response.ok:
            parsed_response = json.loads(response.text)
            status = parsed_response['status']
            return status, parsed_response['code']
        else:
            self.logger.info({
                'action': 'upload_recording_file_to_airudder',
                'error': 'can not upload file to task %s' % task_id
            })
            raise QAAirudderException(
                'Failed to upload file Task to QA Airudder '
                'with response: %(response)s' % {'response': response})

    def action_task(self, task_id, action):
        action_task_url = self.base_url + 'task'
        action_data = {
            'TaskID': task_id,
            'Action': action
        }
        response = self._make_request('PUT', action_task_url, json=action_data)
        if response.ok:
            parsed_response = json.loads(response.text)
            return parsed_response
        else:
            self.logger.info({
                'action': 'action_task',
                'error': 'failed execute task with task_id {} and action {}'.format(
                    task_id, action
                )
            })
            raise QAAirudderException('Failed to execute Task to QA Airudder'
                                ' with response: %(response)s' % {'response': response})

    def start_task(self, task_id):
        response = self.action_task(task_id, QAAirudderTaskAction.START)
        return response

    def cancel_task(self, task_id):
        response = self.action_task(task_id, QAAirudderTaskAction.CANCEL)
        return response
