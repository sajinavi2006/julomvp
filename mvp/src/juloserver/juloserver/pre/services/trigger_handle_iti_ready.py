from django.db import transaction
from juloserver.julo.models import Application, CreditScore
from juloserver.application_flow.tasks import (
    handle_iti_ready,
)


def _create_key(arr):
    result = ""
    for index in range(0, len(arr)):
        temp_key = str(arr[index])
        result += temp_key
        if index != len(arr) - 1:
            result += " - "
    return result


def _get_summary_from_result(result):
    summary = {}
    for keys, logs in result.items():
        for log in logs:
            if not (log in summary):
                summary[log] = 1
            else:
                summary[log] += 1
    return summary


def trigger_handle_iti_ready(data):

    result = {}
    duplicate_data = 0

    for trigger_app in data:
        app_id = trigger_app["app_id"]
        key = _create_key([app_id])
        if key not in result:
            result[key] = []
        if len(result[key]) > 0:
            duplicate_data += 1
            continue

        result[key].append("processed")
        app = Application.objects.get_or_none(pk=app_id)
        if app is None:
            continue
        last_app = Application.objects.filter(customer_id=app.customer_id).last()
        if last_app is None:
            continue
        if last_app.id != app.id:
            continue
        if app.status != 105:
            result[key].append("current status is not in 105 but " + str(app.status))
            continue
        cs = CreditScore.objects.get(application=app)
        if cs.score in ['C', '--']:
            result[key].append("current score is C or -- (current score " + cs.score + ")")
            continue
        is_j1 = app.product_line_code == 1 and app.partner_id is None
        if not is_j1:
            result[key].append('this application is not j1')
            continue
        with transaction.atomic():
            try:
                # -- fix --
                handle_iti_ready(app.id)
                result[key].append("success")
                # ---------
            except Exception as e:
                result[key].append("failed : " + str(e))

    resp = {
        "summary": _get_summary_from_result(result),
        "duplicate_data": duplicate_data,
        "result": result,
    }
    return resp


def check_trigger_handle_iti_ready(data):

    result = {}
    duplicate_data = 0

    for trigger_app in data:
        app_id = trigger_app["app_id"]
        key = _create_key([app_id])
        if key not in result:
            result[key] = []
        if len(result[key]) > 0:
            duplicate_data += 1
            continue
        result[key].append("checked")
        try:
            # -- check --
            app = Application.objects.get(pk=app_id)
            cs = CreditScore.objects.filter(application_id=app.id).last()
            if cs is None:
                result[key].append(
                    "credit score not generated yet (current status is " + str(app.status) + ")"
                )
                continue

            if cs.score not in ['C', '--'] and app.status == 105:
                result[key].append(
                    "credit score not in C or -- but status is 105 (current score is "
                    + cs.score
                    + ")"
                )
                continue

            result[key].append("this app is fine now")
            # ---------

        except Exception as e:
            result[key].append("failed : " + str(e))

    resp = {
        "summary": _get_summary_from_result(result),
        "duplicate_data": duplicate_data,
        "result": result,
    }
    return resp
