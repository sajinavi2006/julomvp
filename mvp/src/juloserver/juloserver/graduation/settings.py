from celery.schedules import crontab

PACKAGE_NAME = 'juloserver.graduation.tasks'

GRADUATION_SCHEDULE = {
    #  "At 05:00 on the 9th day after every 1 month"
    f'{PACKAGE_NAME}.refresh_materialized_view_graduation_regular_customer_accounts': {
        'task': f'{PACKAGE_NAME}.refresh_materialized_view_graduation_regular_customer_accounts',
        'schedule': crontab(minute=0, hour=5, day_of_month=9),
    },
    #  "At 05:00 from the 10th to the 19th day after every 1 month"
    f'{PACKAGE_NAME}.upgrade_entry_level_for_regular_customer': {
        'task': f'{PACKAGE_NAME}.upgrade_entry_level_for_regular_customer',
        'schedule': crontab(minute=0, hour=5, day_of_month='10-19'),
    },

    #  "At 00:00 every hour"
    f'{PACKAGE_NAME}.graduation_customer': {
        'task': f'{PACKAGE_NAME}.graduation_customer',
        'schedule': crontab(minute=0),
    },

    # At 5:00 PM everyday
    f'{PACKAGE_NAME}.run_downgrade_customers': {
        'task': f'{PACKAGE_NAME}.run_downgrade_customers',
        'schedule': crontab(hour=17, minute=0),
    },
    # Every monday at 1:00 AM
    f'{PACKAGE_NAME}.retry_downgrade_customers': {
        'task': f'{PACKAGE_NAME}.retry_downgrade_customers',
        'schedule': crontab(day_of_week=1, hour=1, minute=0),
    },

    # At 7:00 AM everyday
    f'{PACKAGE_NAME}.scan_customer_suspend_unsuspend_for_sending_to_me': {
        'task': f'{PACKAGE_NAME}.scan_customer_suspend_unsuspend_for_sending_to_me',
        'schedule': crontab(hour=7, minute=0),
    },
}
