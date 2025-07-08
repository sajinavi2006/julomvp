"""
celery_loader_custom.py
"""
from __future__ import absolute_import

from celery.loaders.base import BaseLoader

from django_replicated.utils import routers
from django.conf import settings

__all__ = ['AppLoader']


class AppLoader(BaseLoader):

    def on_task_init(self, task_id, task):
        """This method is called before a task is executed."""
        super(AppLoader, self).on_task_init(task_id, task)
        can_task_use_replica = task.name in settings.REPLICATED_CELERY_TASKS
        if can_task_use_replica:
            routers.init('slave')
        else:
            routers.init('master')
