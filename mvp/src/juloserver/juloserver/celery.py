from __future__ import absolute_import

import logging
from os.path import abspath, dirname, join
import os, sys

from django.conf import settings

from celery import Celery, signals

from ddtrace import patch

logger = logging.getLogger(__name__)


patch(celery=True)

PROJECT_ROOT = abspath(dirname(__file__))
PORTAL_ROOT = join(PROJECT_ROOT, "portal")

BUILTIN_FIXUPS = frozenset([
    'juloserver.julo.fixups_custom:fixup',
])

CELERY_DOGSLOW_TASK_WHITELIST = [
    'juloserver.channeling_loan.tasks.daily_checker_loan_tagging_task'
]

sys.path.insert(0, PORTAL_ROOT)
sys.path.insert(1, join(PORTAL_ROOT, "authentication"))
sys.path.insert(2, join(PORTAL_ROOT, "core"))
sys.path.insert(3, join(PORTAL_ROOT, "configuration"))
sys.path.insert(4, join(PORTAL_ROOT, "object"))
sys.path.insert(5, join(PORTAL_ROOT, "process"))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'juloserver.settings.local')
celery_app = Celery('juloserver', broker=os.getenv('BROKER_URL'),
                    fixups=BUILTIN_FIXUPS)
celery_app.config_from_object('django.conf:settings')
celery_app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

@signals.task_prerun.connect
def task_prerun_handler(sender, task_id=None, args=None, kwargs=None, **extras):
    if 'juloloan' not in settings.SERVICE_DOMAIN:
        return

    try:
        log_data = {
            "task_name": sender.name,
            "task_id": task_id,
            "params": {
                "args": args,
                "kwargs": kwargs,
            }
        }
        logger.info(log_data)
    except Exception as e:
        logger.error("Error logging task {} params: {}".format(sender.name, str(e)))


def is_prefork_mode():
    return celery_app.conf.worker_pool == 'prefork'


if 'juloloan' in settings.SERVICE_DOMAIN and is_prefork_mode():
    from juloserver.celery_monitoring import CeleryTaskMonitor
    task_monitor = CeleryTaskMonitor(settings.CELERY_DOGSLOW_TASK_THRESHOLD_DEFAULT)
    signals.task_prerun.connect(task_monitor.task_prerun)
    signals.task_postrun.connect(task_monitor.task_postrun)
