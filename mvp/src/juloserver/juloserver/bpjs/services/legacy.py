import logging
import urllib.parse

import pdfkit
from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string

from juloserver.bpjs import get_anaserver_client, get_julo_tongdun_client
from juloserver.bpjs.constants import JuloRedirectUrls, TongdunCodes
from juloserver.bpjs.exceptions import JuloBpjsException
from juloserver.bpjs.models import BpjsTask, BpjsTaskEvent, SdBpjsProfile

logger = logging.getLogger(__name__)


def generate_bpjs_login_url_via_tongdun(customer_id, application_id, app_type):
    julo_redirect_url = JuloRedirectUrls.ANDROID_REDIRECT_URL
    return_page = "julo"
    if app_type == "app":
        box_token = settings.TONGDUN_BOX_TOKEN_ANDROID
    else:
        box_token = settings.TONGDUN_BOX_TOKEN_WEB
        if len(app_type.split("_")) == 3:
            app_type, partner, return_page = app_type.split("_")
            julo_redirect_url = JuloRedirectUrls.BPJS_WEB_REDIRECT_URL + partner
        else:
            app_type = "web"

    data = {
        "box_token": box_token,
        "passback_params": customer_id + "_" + application_id + "_" + app_type + "_" + return_page,
        "cb": julo_redirect_url,
        "fix": 1,
    }
    encoded_data = urllib.parse.urlencode(data)
    login_url = "{}?{}".format(settings.TONGDUN_BPJS_LOGIN_URL, encoded_data)
    logger.info({"action": "generate_bpjs_login_url_via_tongdun", "login_url": login_url})

    return login_url


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
    tongdun_client = get_julo_tongdun_client()
    response = tongdun_client.get_bpjs_data(task_id, customer_id, application_id)

    anaserver_client = get_anaserver_client()
    ana_result = anaserver_client.send_bpjs_data(response, customer_id, application_id)

    return ana_result


def generate_bpjs_pdf(application_id):
    bpjs_task = BpjsTask.objects.filter(
        application_id=application_id,
        status_code=TongdunCodes.TONGDUN_TASK_SUCCESS_CODE,
    )
    if not bpjs_task:
        raise JuloBpjsException("No tongdun task for application_id {}".format(application_id))

    anaserver_client = get_anaserver_client()
    ana_bpjs_data = anaserver_client.get_bpjs_data(application_id)
    if not ana_bpjs_data["does_data_exist"]:
        raise JuloBpjsException(
            "No BPJS profile data for " "application_id {}".format(ana_bpjs_data["application_id"])
        )

    context = {
        "julo_image": settings.SPHP_STATIC_FILE_PATH + "scraoe-copy-3@3x.png",
        "application_id": application_id,
        "sd_bpjs_profile": ana_bpjs_data["sd_bpjs_profile"],
        "sd_bpjs_companies": ana_bpjs_data["sd_bpjs_companies"],
    }
    if not ana_bpjs_data["sd_bpjs_profile"] or not ana_bpjs_data["sd_bpjs_companies"]:
        raise JuloBpjsException("Either sd_bpjs_profile or sd_bpjs_companies is empty")

    template = render_to_string("legacy_report.html", context=context)
    pdf = pdfkit.from_string(template, False)
    return pdf


def check_bpjs_task_for_application(application_id):
    success_tongdun_task = BpjsTask.objects.filter(application_id=application_id).last()
    return success_tongdun_task


def check_submitted_bpjs(application):
    check_bpjs_ready = SdBpjsProfile.objects.filter(application_id=application.id).last()
    return True if check_bpjs_ready else False
