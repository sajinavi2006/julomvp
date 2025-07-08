from celery.schedules import crontab

LENDERINVESTMENT_SCHEDULE = {
    # 'get_forex_rate_idr_to_eur': {
    #     'task': 'juloserver.lenderinvestment.tasks.get_forex_rate_idr_to_eur',
    #     'schedule': crontab(minute=5, hour=11),
    # },
    'send_all_data_loan_to_mintos': {
        'task': 'juloserver.lenderinvestment.tasks.send_all_data_loan_to_mintos',
        'schedule': crontab(minute='*/5', hour=2),
    },
    # 'get_loans_tasks': {
    #     'task': 'juloserver.lenderinvestment.tasks.get_loans_tasks',
    #     'schedule': crontab(minute=0, hour=[9]),
    # },
}
