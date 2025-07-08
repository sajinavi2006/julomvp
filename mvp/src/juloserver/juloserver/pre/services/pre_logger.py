# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from juloserver.pre.models import DjangoShellLog


def create_log(user, description, old_data, new_data):

    result_id_user = 0

    # user can be email or user id
    # if user is email then we need to get user id, else throw error
    if user is None:
        raise Exception(
            "user should not empty, please fill it using email (as string) or user id (as integer)"
        )

    if isinstance(user, str):  # if user is string, it should a email
        email = user
        auth_user = User.objects.filter(email=email).last()
        if auth_user is None:
            raise Exception(
                "auth user with email " + str(email) + " is not found, so you cannot do logging."
            )
        result_id_user = auth_user.id
    elif isinstance(user, int):  # if user is int, it should an user id
        auth_user = User.objects.filter(id=user).last()
        if auth_user is None:
            raise Exception(
                "auth user with id " + str(user) + " is not found, so you cannot do logging."
            )
        result_id_user = user
    else:
        raise Exception("user parameter should be email (as string) or user id (as integer)")

    log = DjangoShellLog.objects.create(
        description=description, old_data=old_data, new_data=new_data, execute_by=result_id_user
    )
    return log


def update_log(log_id, description=None, old_data=None, new_data=None):
    log = DjangoShellLog.objects.get_or_none(pk=log_id)
    if log is None:
        raise Exception("log is not found")
    if description is not None:
        log.description = description
    if old_data is not None:
        log.old_data = old_data
    if new_data is not None:
        log.new_data = new_data
    log.save()
