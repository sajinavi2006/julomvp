import logging
from celery import task
from django.db import transaction
from ..models import WaiverTemp
from ..constants import WaiverConst
from django.utils import timezone


logger = logging.getLogger(__name__)

@task(queue="collection_high")
@transaction.atomic
def expiration_waiver_daily():
    logger.info({
        'task' : 'expiration_waiver_daily',
    })
    today = timezone.localtime(timezone.now()).date()
    WaiverTemp.objects.select_for_update().filter(
        status=WaiverConst.ACTIVE_STATUS, valid_until__lt=today).update(status=WaiverConst.EXPIRED_STATUS)