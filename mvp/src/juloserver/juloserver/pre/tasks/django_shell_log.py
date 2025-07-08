from celery import task

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from juloserver.pre.models import DjangoShellLog

import logging

logger = logging.getLogger(__name__)


@task(queue='retrofix_normal')
def create_django_log(description, old_data, new_data, executed_by=None):
    logger.info(
        {
            "action": "create_django_log",
            "message": "creating log",
        }
    )
    if not executed_by:
        user = User.objects.filter(username='default_logger').last()
        if not user:
            logger.error(
                {
                    "action": "create_django_log",
                    "message": "error on creating log, user not found",
                    "old_data": old_data,
                    "new_data": new_data,
                }
            )
            return
        executed_by = user.id

    DjangoShellLog.objects.create(
        description=description,
        old_data=old_data,
        new_data=new_data,
        execute_by=executed_by,
    )
