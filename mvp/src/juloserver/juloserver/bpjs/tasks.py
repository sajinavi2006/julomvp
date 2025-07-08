import logging

from celery import task

from juloserver.bpjs.services import retrieve_and_store_bpjs_data
from juloserver.bpjs.services.bpjs_direct import retrieve_and_store_bpjs_direct
from juloserver.bpjs.services.providers.brick import store_bpjs_from_brick
from juloserver.julo.models import Application

logger = logging.getLogger(__name__)


@task(name="async_get_bpjs_data")
def async_get_bpjs_data(task_id, customer_id, application_id):
    retrieve_and_store_bpjs_data(task_id, customer_id, application_id)


@task(name="async_get_bpjs_direct_data", queue="application_high")
def async_get_bpjs_direct_data(application_id):
    retrieve_and_store_bpjs_direct(application_id)


@task(name="async_get_bpjs_data_from_brick", queue="application_high")
def async_get_bpjs_data_from_brick(application_xid, user_access_credential, referrer):
    """
    For method call async task run on the celery for Get Information User
    """
    from juloserver.bpjs.services.x105_revival import X105Revival

    store_bpjs_from_brick(application_xid, user_access_credential, referrer)

    application = Application.objects.get_or_none(application_xid=application_xid)
    if application.status == 105:
        X105Revival(application.id).run()
