from celery import task

from juloserver.julo.clients import get_julo_sentry_client

from .services import EntryLevelLimitProcess


@task(name='entry_level_limit_force_status')
def entry_level_limit_force_status(application_id, new_status):
    entry_limit_process = EntryLevelLimitProcess(application_id)
    try:
        return entry_limit_process.start(new_status)
    except Exception:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
    return False
