from celery.schedules import crontab

LOAN_SCHEDULE = {
    'scheduled_pending_policy_sweeper': {
        'task': 'juloserver.loan.tasks.julo_care_task_related.scheduled_pending_policy_sweeper',
        'schedule': crontab(minute=0, hour="6,18"),
    },
    'update_is_maybe_gtl_inside_to_false': {
        'task': 'juloserver.loan.tasks.loan_related.update_is_maybe_gtl_inside_to_false',
        'schedule': crontab(minute=0, hour="*/1"),  # every 1 hour
    },
    'expire_gtl_outside': {
        'task': 'juloserver.loan.tasks.loan_related.expire_gtl_outside',
        'schedule': crontab(minute=0, hour="5"),  # daily at 5AM
    },
    'send_customer_lifetime_value_analytic_event': {
        'task': 'juloserver.loan.tasks.analytic_event.send_customer_lifetime_value_analytic_event',
        'schedule': crontab(minute=0, hour="5"),  # daily at 5AM
    },
}
