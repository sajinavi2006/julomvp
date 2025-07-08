import os
import sys

from juloserver.celery import celery_app

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Make sure task name in celery schedule is existing in code'


    def handle(self, *args, **options):
        celerybeat_tasks_name = [x['task'] for x in settings.CELERYBEAT_SCHEDULE.values()]
        celerybeat_tasks_name = set(celerybeat_tasks_name)
        celery_app.autodiscover_tasks(lambda: settings.INSTALLED_APPS, force=True)
        celery_task_name = set(celery_app.tasks.keys())
        diff_tasks = celerybeat_tasks_name - celery_task_name
        if diff_tasks:
            self.stdout.write(self.style.ERROR(f"CAN NOT FOUND DEFINITION OF THESE TASKS: {diff_tasks}"))
            sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS("OK"))
            sys.exit(0)
