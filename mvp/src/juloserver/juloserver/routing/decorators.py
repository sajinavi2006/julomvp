from functools import wraps

from juloserver.routing.router import JuloDbReplicaDbRouter


def use_db_replica(function):
    """
    All read DB will use replica db connection.
    The traffic is automated route using JuloDbReplicaDbRouter.
    Please refer to `DATABASE_ROUTERS` in the settings for the routing order.
    """
    @wraps(function)
    def wrapper(*args, **kwargs):
        JuloDbReplicaDbRouter.enable()
        try:
            return function(*args, **kwargs)
        finally:
            JuloDbReplicaDbRouter.disable()

    return wrapper
