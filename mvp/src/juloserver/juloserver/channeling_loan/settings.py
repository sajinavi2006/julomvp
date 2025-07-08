from celery.schedules import crontab

CHANNELING_SCHEDULE = {
    'juloserver.channeling_loan.tasks.retroload_all_application_address_task': {
        'task': 'juloserver.channeling_loan.tasks.retroload_all_application_address_task',
        'schedule': crontab(minute=0, hour=[4, 7, 9]),
    },
    'juloserver.channeling_loan.tasks.send_loan_for_channeling_to_bni_task': {
        'task': 'juloserver.channeling_loan.tasks.send_loan_for_channeling_to_bni_task',
        'schedule': crontab(minute=0, hour="*/1"),  # every 1 hour
    },
    'juloserver.channeling_loan.tasks.send_recap_loan_for_channeling_to_bni_task': {
        'task': 'juloserver.channeling_loan.tasks.send_recap_loan_for_channeling_to_bni_task',
        'schedule': crontab(minute=0, hour="6"),  # daily at 6AM
    },
    'juloserver.channeling_loan.tasks.fama_auto_approval_loans': {
        'task': 'juloserver.channeling_loan.tasks.fama_auto_approval_loans',
        'schedule': crontab(minute=0, hour="17"),
    },
    'juloserver.channeling_loan.tasks.store_fama_repayment_approval_data_task': {
        'task': 'juloserver.channeling_loan.tasks.store_fama_repayment_approval_data_task',
        'schedule': crontab(minute=0, hour="19"),
    },
    'juloserver.channeling_loan.tasks.check_smf_process_disbursement_task': {
        'task': 'juloserver.channeling_loan.tasks.check_smf_process_disbursement_task',
        'schedule': crontab(minute=0, hour="10"),  # daily at 10AM
    },
}
