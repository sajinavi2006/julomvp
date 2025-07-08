from celery.schedules import crontab


SALES_OPS_SCHEDULE = {
    'juloserver.sales_ops.tasks.init_sales_ops_lineup_new_flow': {
        'task': 'juloserver.sales_ops.tasks.init_sales_ops_lineup_new_flow',
        'schedule': crontab(minute=30, hour=4),
    },
    'juloserver.sales_ops.tasks.send_slack_notification': {
        'task': 'juloserver.sales_ops.tasks.send_slack_notification',
        'schedule': crontab(minute=0, hour=6),
    },
}
