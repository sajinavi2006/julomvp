import ast
from abc import ABCMeta, abstractmethod
from decimal import Decimal
from collections import namedtuple
from celery.result import EagerResult
from celery.backends.base import DisabledBackend

from juloserver.julo.services2 import get_redis_client

PROGRESS_STATE = 'PROGRESS'


class AbstractProgressRecorder(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def set_progress(self, current, total, description=""):
        pass


class ProgressRecorder(AbstractProgressRecorder):

    def __init__(self, task_id):
        self.redisClient = get_redis_client()
        self.task_id = task_id

    def update_status(self, status, description):
        meta = {'state': status,
                'pending': False,
                'description': description
                }
        self.redisClient.set(self.task_id, meta)

    def set_progress(self, current, total, description=""):
        percent = 0
        if total > 0:
            percent = (Decimal(current) / Decimal(total)) * Decimal(100)
            percent = float(round(percent, 2))
        status = PROGRESS_STATE
        if current == total:
            status = 'SUCCESS'

        meta = {
            'state': status,
            'pending': False,
            'current': current,
            'total': total,
            'percent': percent,
            'description': description
        }
        self.redisClient.set(self.task_id, meta)


class Progress(object):

    def __init__(self, task_id):
        """
        result:
            an AsyncResult or an object that mimics it to a degree
        """
        self.task_id = task_id
        self.redisClient = get_redis_client()
        self.result = ast.literal_eval(self.redisClient.get(task_id))
        self.info = self.result
        self.result = namedtuple("Result", self.result.keys())(*self.result.values())

    def get_info(self):
        response = {'state': self.result.state}
        if self.result.state in ['SUCCESS']:
            response.update({
                'complete': True,
                'success': True,
                'progress': _get_completed_progress(),
                'description': self.result.description,
                'result': str(self.result),
            })
        elif self.result.state in ['FAILURE']:
            response.update({
                'complete': True,
                'success': False,
                'description': self.result.description,
                'result': self.result.description,
            })
        elif self.result.state == 'IGNORED':
            response.update({
                'complete': True,
                'success': None,
                'progress': _get_completed_progress(),
                'result': str(self.info)
            })
        elif self.result.state == PROGRESS_STATE:
            response.update({
                'complete': False,
                'success': None,
                'progress': self.info,
            })
        elif self.result.state in ['PENDING', 'STARTED']:
            response.update({
                'complete': False,
                'success': None,
                'progress': _get_unknown_progress(self.result.state),
            })
        else:
            response.update({
                'complete': True,
                'success': False,
                'progress': _get_unknown_progress(self.result.state),
                'result': 'Unknown state {}'.format(str(self.result)),
            })
        return response


class KnownResult(EagerResult):
    """Like EagerResult but supports non-ready states."""
    def __init__(self, id, ret_value, state, traceback=None):
        """
        ret_value:
            result, exception, or progress metadata
        """
        # set backend to get state groups (like READY_STATES in ready())
        self.backend = DisabledBackend
        super().__init__(id, ret_value, state, traceback)

    def ready(self):
        return super(EagerResult, self).ready()

    def __del__(self):
        # throws an exception if not overridden
        pass


def _get_completed_progress():
    return {
        'pending': False,
        'current': 100,
        'total': 100,
        'percent': 100,
    }


def _get_unknown_progress(state):
    return {
        'pending': state == 'PENDING',
        'current': 0,
        'total': 100,
        'percent': 0,
    }
