from django.db import transaction
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.pre.services.common import track_agent_retrofix

logger = JuloLog(__name__)


def change_force(app_id, data, with_history, with_handler=[], actor_id=None):
    with transaction.atomic():
        try:
            track_agent_retrofix('change_force', app_id, data, actor_id)
            _do_change_force(app_id, data, with_history, with_handler)
        except Exception as e:
            logger.info({"function": "change_force", "app_id": app_id, "error": str(e)})
    return


def _do_change_force(app_id, data, with_history, with_handler=[]):

    app = Application.objects.get(pk=app_id)

    if "status" in data:
        if "value" in data["status"] and "reason" in data["status"]:
            old_status = app.status
            app.change_status(data["status"]["value"])
            app.save()
            if with_history:
                ApplicationHistory.objects.create(
                    application=app,
                    status_old=old_status,
                    status_new=data["status"]["value"],
                    change_reason=data["status"]["reason"],
                )
            if len(with_handler) > 0:
                if data['status']['value'] == 120:
                    from juloserver.julo.workflows2.handlers import Status120Handler

                    handler = Status120Handler(
                        application=app,
                        old_status_code=old_status,
                        new_status_code=data['status']['value'],
                        change_reason=data['status']['reason'],
                        note=None,
                    )
                    if "pre" in with_handler:
                        handler.pre()
                    if "post" in with_handler:
                        handler.post()
                    if "async_task" in with_handler:
                        handler.async_task()


def check_change_force(app_id, data):
    try:
        app = Application.objects.get(pk=app_id)
        wrong_fields = {}

        if "status" in data:
            if app.status != data["status"]["value"]:
                wrong_fields["status_code"] = app.status

        if wrong_fields:
            print("not all field is correct ", wrong_fields)
        else:
            print("all field is correct")
    except Exception as e:
        print('error happen')
        print(e)
