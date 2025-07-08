import coverage

from celery.signals import task_prerun, task_postrun

from .prod import *

MIDDLEWARE_CLASSES.append('juloserver.julo.middleware.CatchCoverageMiddleware')

cov = coverage.coverage(auto_data=True, config_file='.coveragerc_python')

@task_prerun.connect
def receiver_task_pre_run(task_id, task, *args, **kwargs):
    cov.start()

@task_postrun.connect
def receiver_task_post_run(task_id, task, *args, **kwargs):
    cov.stop()
    cov.save()
