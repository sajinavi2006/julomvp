from celery.schedules import crontab

OMNICHANNEL_SCHEDULE = {
    'send_credgenics_customer_attribute_to_omnichannel_daily': {
        'task': 'juloserver.omnichannel.tasks.send_omnichannel_customer_attribute_daily',
        'schedule': crontab(hour=2, minute=30),
    },
    'send_field_collection_blacklisted_customers_to_omnichannel_daily': {
        'task': 'juloserver.omnichannel.tasks.send_field_collection_blacklisted_customers_daily',
        'schedule': crontab(hour=1, minute=0),
    },
    'send_julo_gold_to_omnichannel_daily': {
        'task': 'juloserver.omnichannel.tasks.send_julo_gold_to_omnichannel_daily',
        'schedule': crontab(hour=6, minute=30),
    },
    'send_automated_comm_sms_j1_autodebet_only_scheduler': {
        'task': 'juloserver.omnichannel.tasks.retrofix.send_automated_comm_sms_j1_autodebet_only_scheduler',  # noqa
        'schedule': crontab(hour=14, minute=0),
    },
}
