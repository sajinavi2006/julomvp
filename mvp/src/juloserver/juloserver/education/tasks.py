import logging
import redis
from celery import task

from juloserver.education.constants import (
    REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME,
    FeatureNameConst,
)
from juloserver.education.models import LoanStudentRegister
from juloserver.education.services.tasks_related import (
    generate_education_invoice,
    send_email_education_invoice,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import FeatureSetting
from juloserver.julocore.redis_completion_py3 import RedisEnginePy3

logger = logging.getLogger(__name__)
BASE_PATH = "juloserver/payment_point/tasks/notificatin_related"


@task(queue="loan_normal")
def send_education_email_invoice_task(loan_id):
    education_transaction = (
        LoanStudentRegister.objects.select_related(
            'loan', 'student_register', 'loan__account', 'loan__transaction_method'
        )
        .filter(loan__id=loan_id)
        .last()
    )
    if not education_transaction:
        logger.info(
            {
                "task": "send_education_email_invoice_task",
                "path": BASE_PATH,
                "respon_data": "Education transaction not found with related ID",
            }
        )
        return

    generate_education_invoice(education_transaction)
    send_email_education_invoice(education_transaction)


@task(queue='loan_normal')
def health_check_redis_for_school_searching():
    sentry_client = get_julo_sentry_client()

    # Check if Redis is alive by sending a PING command
    redis_completion_engine = None
    try:
        redis_completion_engine = RedisEnginePy3(prefix=REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME)
        redis_completion_engine.client.ping()
        is_redis_alive = True
    except redis.exceptions.RedisError:
        sentry_client.captureException()
        is_redis_alive = False

    is_exists_school_hash_table_in_redis = False
    if is_redis_alive:
        is_exists_school_hash_table_in_redis = redis_completion_engine.client.exists(
            redis_completion_engine.data_key
        )
        if not is_exists_school_hash_table_in_redis:
            sentry_client.captureMessage({'error': 'not exist hash table for school data in Redis'})

    feature_setting = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.SEARCH_SCHOOL_IN_REDIS
    )
    if not is_redis_alive or not is_exists_school_hash_table_in_redis:
        if feature_setting.is_active:
            feature_setting.is_active = False
            feature_setting.save()
            logger.info(
                {
                    'task': 'health_check_redis_for_school_searching',
                    'status': 'Disabled SEARCH_SCHOOL_IN_REDIS feature setting',
                }
            )
