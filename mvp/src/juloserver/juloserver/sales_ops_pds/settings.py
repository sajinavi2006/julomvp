from celery.schedules import crontab


SALES_OPS_PDS_SCHEDULE = {
    'juloserver.sales_ops_pds.tasks.init_create_sales_ops_pds_task': {
        'task': 'juloserver.sales_ops_pds.tasks.init_create_sales_ops_pds_task',
        'schedule': crontab(minute=0, hour=7),
    },
    'juloserver.sales_ops_pds.tasks.init_download_sales_ops_pds_call_result_task': {
        'task': 'juloserver.sales_ops_pds.tasks.init_download_sales_ops_pds_call_result_task',
        'schedule': crontab(minute=15, hour='8-20'),
    },
    'juloserver.sales_ops_pds.tasks.send_slack_notification': {
        'task': 'juloserver.sales_ops_pds.tasks.send_slack_notification',
        'schedule': crontab(minute=0, hour=8),
    },
}
