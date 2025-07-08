from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ..utils import template_reminders
import logging

logger = logging.getLogger(__name__)


def parse_template_reminders(due_date, product_type, is_streamline=False):
    delta = (timezone.localtime(timezone.now()).date() - due_date).days
    delta_string = 'T{}'.format(delta)

    template = template_reminders.get(delta_string + "_" + product_type)
    if template:
        return template
    elif is_streamline:
        return template_reminders.get(product_type).format(delta_string)

    logger.warn({
        "error": "template not found"
    })
    return None
