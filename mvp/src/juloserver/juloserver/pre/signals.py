from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.pre.tasks.django_shell_log import create_django_log

import json
import logging

logger = logging.getLogger(__name__)


def my_log(sender, instance, **kwargs):
    try:
        old_data = sender.objects.filter(pk=instance.pk).last()
        if old_data:
            old_data = json.loads(json.dumps(model_to_dict(old_data), cls=DjangoJSONEncoder))
        new_data = json.loads(json.dumps(model_to_dict(instance), cls=DjangoJSONEncoder))
    except Exception as e:
        logger.error(
            {
                "action": "my_log",
                "message": str(e),
            }
        )
        return
    execute_after_transaction_safely(
        lambda: create_django_log.delay(sender._meta.db_table, old_data, new_data)
    )
