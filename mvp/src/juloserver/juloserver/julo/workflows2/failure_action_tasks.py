from __future__ import absolute_import

from celery import task
from .tasks import TaskWithRetry
from ..models import WorkflowFailureAction
from ..workflows import WorkflowAction

@task(name='failure_post_action_recall_task', base=TaskWithRetry, bind=True, max_retries=0)
def failure_post_action_recall_task(self, application_id, failure_action_dict):
    failure_action = WorkflowFailureAction.objects.get_or_none(pk=failure_action_dict['id'], action_type='post')
    if failure_action:
        application = failure_action.application
        args = failure_action.arguments
        action = WorkflowAction(application, int(args[1]), args[2], args[3])
        eval('action.%s()' % failure_action.action_name)