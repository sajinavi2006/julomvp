import logging

from django.db import transaction

from juloserver.bpjs.models import BpjsTask, BpjsTaskEvent
from juloserver.bpjs.services.bpjs import Bpjs

logger = logging.getLogger(__name__)


def generate_bpjs_login_url_via_tongdun(customer_id, application_id, app_type):
    from juloserver.julo.models import Application

    application = Application.objects.get(pk=application_id)
    return Bpjs(application, provider=Bpjs.PROVIDER_TONGDUN, type_=app_type).authenticate()


def create_or_update_bpjs_task_from_tongdun_callback(
    data, customer_id, application_id, data_source
):
    bpjs_task = BpjsTask.objects.get_or_none(
        task_id=data["task_id"], customer=customer_id, application=application_id
    )
    task_data = dict(
        data_source=data_source,
        customer_id=customer_id,
        application_id=application_id,
        status_code=data["code"],
        task_id=data["task_id"],
    )
    with transaction.atomic():
        if not bpjs_task:
            bpjs_task = BpjsTask.objects.create(**task_data)
        else:
            bpjs_task.update_safely(data_source=data_source, status_code=data["code"])

        bpjs_task_id = bpjs_task.id
        task_event_data = dict(
            status_code=data["code"], message=data["message"], bpjs_task_id=bpjs_task_id
        )

        BpjsTaskEvent.objects.create(**task_event_data)

    return data["code"]


def retrieve_and_store_bpjs_data(task_id, customer_id, application_id):
    from juloserver.julo.models import Application

    application = Application.objects.get(pk=application_id)
    return (
        Bpjs(application)
        .using_provider(Bpjs.PROVIDER_TONGDUN)
        .store_user_information(task_id=task_id)
    )


def generate_bpjs_pdf(application_id):
    """
    This method used in CRM. We not pass the provider here because it just called
    in CRM without knowing its version. So let be the Bpjs class that decide what
    provider to be chosen.
    """

    from juloserver.julo.models import Application

    application = Application.objects.get(pk=application_id)
    return Bpjs(application).generate_pdf()


def check_submitted_bpjs(application):
    return Bpjs(application).using_provider(Bpjs.PROVIDER_TONGDUN).is_submitted
