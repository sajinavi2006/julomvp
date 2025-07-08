from django.db import transaction
from juloserver.application_flow.handlers import JuloOne130Handler
from juloserver.julo.models import Application


def trigger_130(app_ids):
    for app_id in app_ids:
        app = Application.objects.get_or_none(pk=app_id)
        if app is None:
            continue
        last_app = Application.objects.filter(customer_id=app.customer_id).last()
        if last_app is None:
            continue
        if last_app.id != app.id:
            continue
        with transaction.atomic():
            try:
                handler = JuloOne130Handler(app, None, None, None, None)
                handler.post()
            except Exception as e:
                return str(e)


def check_trigger_130(app_ids):
    result = {}
    for app_id in app_ids:
        result[app_id] = []

    for app_id in app_ids:
        app = Application.objects.get(pk=app_id)
        if app.status == 130:
            result[app_id].append("need to fix! status still on 130")
        else:
            result[app_id].append("correct! status is not on 130 but " + str(app.status))

    return result
