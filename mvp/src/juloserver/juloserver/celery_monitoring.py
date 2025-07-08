import inspect
import threading
import time
import traceback
import sys
import logging
from django.conf import settings
from dogslow import stack
from juloserver.celery import CELERY_DOGSLOW_TASK_WHITELIST

logger = logging.getLogger('dogslow.celery')


class CeleryTaskMonitor:
    def __init__(self, default_threshold):
        self._running_tasks = {}
        self._lock = threading.Lock()
        self.threshold = default_threshold
        self.whitelist = CELERY_DOGSLOW_TASK_WHITELIST

    class TaskInfo:
        def __init__(self, start_time, task_name, thread_id, threshold):
            self.start_time = start_time
            self.task_name = task_name
            self.thread_id = thread_id
            self.threshold = threshold
            self.timer = None

    def _start_timer(self, task_id, threshold):
        timer = threading.Timer(threshold, self._watchdog, args=(task_id,))
        timer.daemon = True
        timer.start()
        return timer

    def task_prerun(self, sender, task_id, args=None, kwargs=None, **extras):
        try:
            if sender.name in self.whitelist:
                return

            thresholds = getattr(settings, 'CELERY_DOGSLOW_TASK_THRESHOLDS', {})
            task_threshold = thresholds.get(sender.name, self.threshold)

            task_info = self.TaskInfo(
                start_time=time.time(),
                task_name=sender.name,
                thread_id=threading.get_ident(),
                threshold=task_threshold
            )

            with self._lock:
                self._running_tasks[task_id] = task_info

            task_info.timer = self._start_timer(task_id, task_threshold)
        except Exception as err:
            logger.error("Error in task_prerun: %s", err, exc_info=True)

    def task_postrun(self, sender, task_id, args=None, kwargs=None, **extras):
        with self._lock:
            task_info = self._running_tasks.pop(task_id, None)

        if task_info and task_info.timer:
            task_info.timer.cancel()

    @staticmethod
    def _compose_output(frame, task_name, task_id, execution_time):
        output = (
            'Slow task detected: {}\n'
            'Task ID:    {}\n'
            'Execution Time: {:.2f}s\n'
        ).format(task_name, task_id, execution_time)
        output += stack(frame, with_locals=False)
        output += '\n\n'
        return output

    def _log_slow_task(self, task_id, task_name, execution_time, frame):
        extra = {
            "task_id": task_id,
            "task_name": task_name,
            "execution_time": execution_time,
            "threshold": self._running_tasks.get(
                task_id, {}
            ).threshold if task_id in self._running_tasks else self.threshold,
        }

        if frame:
            module = inspect.getmodule(frame.f_code)
            culprit = "{} in {}".format(getattr(module, '__name__', '(unknown module)'),
                                        frame.f_code.co_name)
            extra["culprit"] = culprit

            stack_frames = traceback.extract_stack(frame)
            stack_frames.reverse()
            stack_trace = ''.join(traceback.format_list(stack_frames))
            extra["stack"] = stack_trace

            output = self._compose_output(frame, task_name, task_id, execution_time)

            log_level = logging.WARNING
            log_extra = {
                'task_name': task_name,
                'task_id': task_id,
                'culprit': culprit,
                'stack': [(frame, lineno) for frame, filename, lineno, function, code_context, index
                          in inspect.getouterframes(frame)],
                'full_output': output,
                'tags': {'task_name': task_name},
                'fingerprint': ['slow_celery_task__{}'.format(task_name)],
            }
            log_extra['stack'].reverse()

            message = "Slow task detected {}".format(task_name)
            logger.log(log_level, message, extra=log_extra)

    def _watchdog(self, task_id):
        with self._lock:
            task_info = self._running_tasks.get(task_id)
            if not task_info:
                return

        execution_time = time.time() - task_info.start_time
        frame = None
        if task_info.thread_id in sys._current_frames():
            frame = sys._current_frames()[task_info.thread_id]

        task_info = self._running_tasks.pop(task_id, None)

        self._log_slow_task(task_id, task_info.task_name, execution_time, frame)
