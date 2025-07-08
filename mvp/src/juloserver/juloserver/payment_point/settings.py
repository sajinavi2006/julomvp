from celery.schedules import crontab

TASK_BASE_PATH = "juloserver.payment_point.tasks"

PAYMENT_POINT_SCHEDULE = {
    "check_transaction_sepulsa_loan": {
        "task": TASK_BASE_PATH + ".transaction_related.check_transaction_sepulsa_loan",
        "schedule": crontab(minute="*/15"),
    },
    "reset_transaction_sepulsa_loan_break": {
        "task": TASK_BASE_PATH
        + ".transaction_related.reset_transaction_sepulsa_loan_break",
        "schedule": crontab(minute=0, hour=0),
    },
    "auto_update_sepulsa_product": {
        "task": TASK_BASE_PATH + ".product_related.auto_update_sepulsa_product",
        "schedule": crontab(minute=0, hour=[5, 17]),
    },
    "check_transaction_sepulsa": {
        "task": TASK_BASE_PATH + ".transaction_related.check_transaction_sepulsa",
        "schedule": crontab(minute="*/15"),
    },
    "reset_transaction_sepulsa_break": {
        "task": TASK_BASE_PATH
        + ".transaction_related.reset_transaction_sepulsa_break",
        "schedule": crontab(minute=0, hour=0),
    },
    "send_slack_notification_sepulsa_remaining_balance": {
        "task": TASK_BASE_PATH
        + ".notification_related.send_slack_notification_sepulsa_remaining_balance",
        "schedule": crontab(minute=0, hour="*/2"),
    },
    "send_slack_notification_sepulsa_balance_reach_minimum_threshold": {
        "task": TASK_BASE_PATH
        + ".notification_related.send_slack_notification_sepulsa_balance_reach_minimum_threshold",
        "schedule": crontab(minute="*/15"),
    },
}


DEFAULT_CACHEOPS_TIMEOUT_SECONDS = 60 * 60
PAYMENT_POINT_CACHEOPS = {
    'julo.SepulsaProduct': {'ops': 'all', 'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS},
    'payment_point.TransactionCategory': {
        'ops': 'all',
        'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS,
    },
    'payment_point.TransactionMethod': {'ops': 'all', 'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS},
    'payment_point.XfersProduct': {'ops': 'all', 'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS},
    'payment_point.AYCProduct': {'ops': 'all', 'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS},
    'payment_point.TrainStation': {'ops': 'all', 'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS},
    'payment_point.PdamOperator': {'ops': 'all', 'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS},
}
