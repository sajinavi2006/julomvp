from juloserver.julo.models import (
    ApplicationNote,
)

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User


def track_agent_retrofix(function_name, app_id, parameter, actor_id):
    # prepare note json
    note = {"function_name": function_name, "app_id": app_id, "parameter": parameter}

    # prepare actor identifier
    if actor_id is not None:
        user = User.objects.filter(id=actor_id).last()
        actor_identifier = "anonymous"
        if user.email:
            actor_identifier = str(user.email)
        elif user.username:
            actor_identifier = str(user.username)
    else:
        actor_identifier = "anonymous"

    # create note as string
    note_str = f"[agent_retrofix][actor : {actor_identifier}]{note}"

    # create application note
    ApplicationNote.objects.create(
        note_text=note_str, application_id=app_id, application_history_id=None
    )
