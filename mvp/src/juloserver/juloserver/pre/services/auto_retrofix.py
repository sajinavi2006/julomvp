from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import FeatureSetting, ApplicationNote, Application
from juloserver.application_flow.models import (
    ApplicationPathTagStatus,
    ApplicationPathTag,
)
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta
from juloserver.julo.product_lines import ProductLineCodes
from time import perf_counter
from django.conf import settings
from juloserver.monitors.notifications import get_slack_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julolog.julolog import JuloLog
from juloserver.pre.services.trigger_130 import trigger_130
from juloserver.pre.services.trigger_141 import trigger_141
from juloserver.pre.services.trigger_check_face_similarity import trigger_check_face_similarity
from juloserver.pre.services.trigger_handle_iti_ready import trigger_handle_iti_ready
from juloserver.pre.services.trigger_process_validate_bank import trigger_process_validate_bank
from juloserver.pre.services.move_application_to_trash_customer import (
    move_application_to_trash_customer,
)
from time import sleep

logger = JuloLog()


def track_auto_retrofix(function_name="", app_ids=[]):
    for app_id in app_ids:
        note = {"function_name": function_name, "app_id": app_id}
        note_str = f"[auto_retrofix]{note}"
        ApplicationNote.objects.create(
            note_text=note_str, application_id=app_id, application_history_id=None
        )


def _exclude_revive_query(q):
    revive_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_revive_mtl', status=1
    ).last()

    if revive_tag is None:
        return q
    else:
        application_ids = ApplicationPathTag.objects.filter(
            application_path_tag_status_id=revive_tag.id
        ).values_list('application_id', flat=True)
        return q.exclude(id__in=list(application_ids))


def _auto_retrofix_trigger_check_face_similarity(only_get_impacted=False):

    title = "Retrofix application (x121) that face similarity stuck on pending "
    func_name = "_auto_retrofix_trigger_check_face_similarity"

    # start stopwatch
    t1_start = perf_counter()

    # gather data
    q_app_ids = Application.objects.filter(
        Q(application_status_id=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED)
        & (
            Q(product_line_id=ProductLineCodes.J1)
            | Q(product_line_id=ProductLineCodes.JULO_STARTER)
        )
        & Q(partner_id=None)
        & Q(facesearchprocess__status='pending')
    )

    q_app_ids = _exclude_revive_query(q_app_ids).values_list('pk', flat=True)

    app_ids = list(q_app_ids)
    if only_get_impacted:
        return {
            "title": title,
            "function_name": func_name,
            "impacted_list": app_ids,
        }

    # run action
    track_auto_retrofix(func_name, app_ids)
    for app_id in app_ids:
        trigger_check_face_similarity(app_id)

    # stop stopwatch
    t1_stop = perf_counter()

    # summarize
    result = {
        "title": title,
        "function_name": func_name,
        "duration": f"{round(t1_stop - t1_start, 2)} seconds",
        "total_retrofixed": len(app_ids),
    }

    return result


def _auto_retrofix_trigger_process_validate_bank(only_get_impacted=False):

    title = "Retrofix application that stuck on x175 without name_bank_validation_id"
    func_name = "_auto_retrofix_trigger_process_validate_bank"

    # start stopwatch
    t1_start = perf_counter()

    # gather data
    q_app_ids = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        product_line_id=ProductLineCodes.J1,
        partner_id=None,
        name_bank_validation_id=None,
    )

    q_app_ids = _exclude_revive_query(q_app_ids).values_list('pk', flat=True)

    app_ids = list(q_app_ids)
    if only_get_impacted:
        return {
            "title": title,
            "function_name": func_name,
            "impacted_list": app_ids,
        }

    # run action
    track_auto_retrofix(func_name, app_ids)
    trigger_process_validate_bank(app_ids)

    # stop stopwatch
    t1_stop = perf_counter()

    # summarize
    result = {
        "title": title,
        "function_name": func_name,
        "duration": str(round(t1_stop - t1_start, 2)) + " seconds",
        "total_retrofixed": len(app_ids),
    }

    return result


def _auto_retrofix_trigger_handle_iti_ready(only_get_impacted=False):

    title = "Retrofix application that stuck on x105 with passed score (non C / --)"
    func_name = "_auto_retrofix_trigger_handle_iti_ready"

    # start stopwatch
    t1_start = perf_counter()

    # gather data
    time_max = timezone.localtime(timezone.now() - timedelta(hours=1))
    q_app_ids = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
        product_line_id=ProductLineCodes.J1,
        partner_id=None,
        creditscore__cdate__lt=time_max,
    ).exclude(creditscore__score__in=['C', '--'])

    q_app_ids = _exclude_revive_query(q_app_ids).values_list('pk', flat=True)

    app_ids = list(q_app_ids)
    if only_get_impacted:
        return {
            "title": title,
            "function_name": func_name,
            "impacted_list": app_ids,
        }

    # run action
    track_auto_retrofix(func_name, app_ids)
    params = []
    for app_id in app_ids:
        params.append({"app_id": app_id})
    trigger_handle_iti_ready(params)

    # stop stopwatch
    t1_stop = perf_counter()

    # summarize
    result = {
        "title": title,
        "function_name": func_name,
        "duration": str(round(t1_stop - t1_start, 2)) + " seconds",
        "total_retrofixed": len(app_ids),
    }

    return result


def _auto_retrofix_last_app_is_not_active_app(only_get_impacted=False):

    title = "Retrofix application that stuck on x105 passed score because not latest app"
    func_name = "_auto_retrofix_last_app_is_not_active_app"

    # start stopwatch
    t1_start = perf_counter()

    # gather data
    time_max = timezone.localtime(timezone.now() - timedelta(hours=1))
    q_app_ids = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
        product_line_id=ProductLineCodes.J1,
        partner_id=None,
        creditscore__cdate__lt=time_max,
    ).exclude(creditscore__score__in=['C', '--'])

    q_app_ids = _exclude_revive_query(q_app_ids)
    app_ids = []
    for app in q_app_ids:
        last_app = Application.objects.filter(customer_id=app.customer_id).last()
        if last_app.id != app.id:
            app_ids.append(app.id)

    if only_get_impacted:
        return {
            "title": title,
            "function_name": func_name,
            "impacted_list": app_ids,
        }

    # run action
    track_auto_retrofix(func_name, app_ids)

    # move to trash first
    list_app_id_that_need_remove = []
    for app_id in app_ids:
        temp_app = Application.objects.get(pk=app_id)
        temp_apps_need_remove = Application.objects.filter(
            customer_id=temp_app.customer_id, pk__gt=temp_app.id
        )
        allow_remove = True
        for temp_app_need_remove in temp_apps_need_remove:
            if temp_app_need_remove.status not in (100, 137):
                logger.info(
                    {
                        "function": "_auto_retrofix_last_app_is_not_active_app",
                        "state": "have another app that have status not in (100, 137)",
                        "app_id": app_id,
                    }
                )
                allow_remove = False
        if allow_remove:
            list_app_id_that_need_remove += temp_apps_need_remove.values_list('pk', flat=True)

    for app_id in list_app_id_that_need_remove:
        move_application_to_trash_customer(app_id)

    params = []
    for app_id in app_ids:
        params.append({"app_id": app_id})

    trigger_handle_iti_ready(params)

    # stop stopwatch
    t1_stop = perf_counter()

    # summarize
    result = {
        "title": title,
        "function_name": func_name,
        "duration": str(round(t1_stop - t1_start, 2)) + " seconds",
        "total_retrofixed": len(app_ids),
    }

    return result


def _auto_retrofix_trigger_130(only_get_impacted=False):

    title = "Retrofix application that stuck on x130"
    func_name = "_auto_retrofix_trigger_130"

    # start stopwatch
    t1_start = perf_counter()

    # gather data
    q_app_ids = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        product_line_id=ProductLineCodes.J1,
        partner_id=None,
    )

    q_app_ids = _exclude_revive_query(q_app_ids).values_list('pk', flat=True)

    app_ids = list(q_app_ids)

    if only_get_impacted:
        return {
            "title": title,
            "function_name": func_name,
            "impacted_list": app_ids,
        }

    # run action
    track_auto_retrofix(func_name, app_ids)
    trigger_130(app_ids)

    # stop stopwatch
    t1_stop = perf_counter()

    # summarize
    result = {
        "title": title,
        "function_name": func_name,
        "duration": str(round(t1_stop - t1_start, 2)) + " seconds",
        "total_retrofixed": len(app_ids),
    }

    return result


def _auto_retrofix_trigger_141(only_get_impacted=False):

    title = "Retrofix application that stuck on x141"
    func_name = "_auto_retrofix_trigger_141"

    # start stopwatch
    t1_start = perf_counter()

    # gather data
    q_app_ids = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        product_line_id=ProductLineCodes.J1,
        partner_id=None,
    )

    q_app_ids = _exclude_revive_query(q_app_ids).values_list('pk', flat=True)

    app_ids = list(q_app_ids)
    if only_get_impacted:
        return {
            "title": title,
            "function_name": func_name,
            "impacted_list": app_ids,
        }

    # run action
    track_auto_retrofix(func_name, app_ids)
    trigger_141(app_ids)

    # stop stopwatch
    t1_stop = perf_counter()

    # summarize
    result = {
        "title": title,
        "function_name": func_name,
        "duration": str(round(t1_stop - t1_start, 2)) + " seconds",
        "total_retrofixed": len(app_ids),
    }

    return result


def is_need_run(title, fs_params):
    if title not in fs_params:
        return False
    if fs_params[title] is False:
        return False
    return True


def run_auto_retrofix():
    logger.info({"message": "run_auto_retrofix_task()", "status": "entering function"})

    # get feature setting configuration
    fs = FeatureSetting.objects.filter(feature_name=FeatureNameConst.AUTO_RETROFIX).last()
    parameters = None
    if fs is None:
        return
    if fs.is_active is False:
        return
    parameters = fs.parameters
    if parameters is None:
        return

    logger.info({"action": "run_auto_retrofix()", "status": "start run", "parameters": parameters})
    result = []
    failed_list = []

    # run all auto retrofix
    try:
        if is_need_run("auto_retrofix_trigger_141", parameters):
            result_trigger_141 = _auto_retrofix_trigger_141()
            result.append(result_trigger_141)
            failed_trigger_141 = _auto_retrofix_trigger_141(only_get_impacted=True)
            failed_list.append(failed_trigger_141)

        if is_need_run("auto_retrofix_trigger_130", parameters):
            result_trigger_130 = _auto_retrofix_trigger_130()
            result.append(result_trigger_130)
            failed_trigger_130 = _auto_retrofix_trigger_130(only_get_impacted=True)
            failed_list.append(failed_trigger_130)

        if is_need_run("auto_retrofix_trigger_handle_iti_ready", parameters):
            result_trigger_handle_iti_ready = _auto_retrofix_trigger_handle_iti_ready()
            result.append(result_trigger_handle_iti_ready)
            failed_trigger_handle_iti_ready = _auto_retrofix_trigger_handle_iti_ready(
                only_get_impacted=True
            )
            failed_list.append(failed_trigger_handle_iti_ready)

        if is_need_run("auto_retrofix_last_app_is_not_active_app", parameters):
            result_last_app_is_not_active_app = _auto_retrofix_last_app_is_not_active_app()
            result.append(result_last_app_is_not_active_app)
            failed_last_app_is_not_active_app = _auto_retrofix_last_app_is_not_active_app(
                only_get_impacted=True
            )
            failed_list.append(failed_last_app_is_not_active_app)

        if is_need_run("auto_retrofix_trigger_process_validate_bank", parameters):
            result_trigger_process_validate_bank = _auto_retrofix_trigger_process_validate_bank()
            result.append(result_trigger_process_validate_bank)
            failed_trigger_process_validate_bank = _auto_retrofix_trigger_process_validate_bank(
                only_get_impacted=True
            )
            failed_list.append(failed_trigger_process_validate_bank)

        if is_need_run("auto_retrofix_trigger_check_face_similarity", parameters):
            result_trigger_check_face_similarity = _auto_retrofix_trigger_check_face_similarity()
            result.append(result_trigger_check_face_similarity)
            sleep(5)  # since change face similarity is async, so to get the result need wait a bit
            failed_trigger_check_face_similarity = _auto_retrofix_trigger_check_face_similarity(
                only_get_impacted=True
            )
            failed_list.append(failed_trigger_check_face_similarity)
    except Exception as e:
        logger.info(
            {
                "action": "run_auto_retrofix()",
                "status": "error happen !",
                "error": str(e),
            }
        )
        send_auto_retrofix_error(str(e))

    logger.info(
        {
            "action": "run_auto_retrofix()",
            "status": "finish",
            "result": result,
            "failed_list": failed_list,
        }
    )
    if len(result) > 0:
        send_auto_retrofix_result_to_slack(result, failed_list)

    logger.info({"message": "run_auto_retrofix_task()", "status": "end function"})


def send_auto_retrofix_error(err_str):
    # define channel
    text = ""
    slack_channel = "#retrofix-automation-onboarding"
    if settings.ENVIRONMENT != 'prod':
        text += " <--{settings.ENVIRONMENT}"
        slack_channel = "#retrofix-automation-onboarding-test"

    # prepare client
    slack_client = get_slack_client()

    # prepare text
    text = (
        '*=== ERROR !! Auto Retrofix '
        + timezone.localtime(timezone.now()).strftime("%A, %Y-%m-%d | %H:%M")
        + " ===*\n"
    )
    text += err_str

    # send to slack
    slack_client.api_call("chat.postMessage", channel=slack_channel, text=text)


def send_auto_retrofix_result_to_slack(result, failed_list):
    # define channel
    text = ""
    slack_channel = "#retrofix-automation-onboarding"
    if settings.ENVIRONMENT != 'prod':
        text += " <--{settings.ENVIRONMENT}"
        slack_channel = "#retrofix-automation-onboarding-test"

    # prepare client
    slack_client = get_slack_client()

    # prepare text
    text = (
        '*=== Auto Retrofix '
        + timezone.localtime(timezone.now()).strftime("%A, %Y-%m-%d | %H:%M")
        + " ===*\n"
    )
    text += "*Result Auto Retrofix*"
    for index, item in enumerate(result):
        title = item['title']
        duration = item['duration']
        total_retrofixed = item['total_retrofixed']
        text += f"\n{(index + 1)}. {title}. Total Retrofix : {total_retrofixed} ({duration})"

    text += "\n\n\n*Failed to Retrofix (Need Check <@U049828C29K>)*"
    for index, item in enumerate(failed_list):
        title = item['title']
        impacted_list = item['impacted_list']
        if len(impacted_list) > 0:
            text += f"\n{(index + 1)}. {title}. List ID that cannot retrofixed : {impacted_list} "
            text += f"(Total : {len(impacted_list)})"

    # send to slack
    slack_client.api_call("chat.postMessage", channel=slack_channel, text=text)
