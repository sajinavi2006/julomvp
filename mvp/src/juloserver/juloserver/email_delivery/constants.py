EmailStatusMapping = {
    'SendGrid': {  # https://docs.sendgrid.com/for-developers/tracking-events/event#delivery-events
        'processed': 'processed',
        'dropped': 'dropped',
        'delivered': 'delivered',
        'deferred': 'deferred',
        'bounce': 'bounce',  # Bounce mapping handled in callback logic due to complication
        'open': 'open',
        'click': 'clicked',
        'spamreport': 'spam',
        'unsubscribe': 'unsubscribed',
        'group_unsubscribe': 'group_unsubscribed',
        'group_resubscribe': 'group_resubscribed',
    },
    'MoEngageStream': {  # https://developers.moengage.com/hc/en-us/articles/4952761690644-Streams-
        'MOE_EMAIL_SENT': 'processed',
        'MOE_EMAIL_DEFERRED': 'deferred',
        'MOE_EMAIL_DELIVERED': 'delivered',
        'MOE_EMAIL_HARD_BOUNCE': 'hard_bounce',
        'MOE_EMAIL_SOFT_BOUNCE': 'soft_bounce',
        'MOE_EMAIL_OPEN': 'open',
        'MOE_EMAIL_CLICK': 'clicked',
        'MOE_EMAIL_UNSUBSCRIBE': 'unsubscribed',
        'MOE_EMAIL_SPAM': 'spam',
        'MOE_EMAIL_DROP': 'dropped'
    },
    'MoEngageStreamPriority': {
        'sent': 0,
        'processed': 0,
        'dropped': 1,
        'deferred': 2,
        'unsubscribed': 3,
        'spam': 4,
        'hard_bounce': 5,
        'soft_bounce': 6,
        'delivered': 7,
        'open': 8,
        'clicked': 9,
    },
}


class EmailBounceType:
    HARD_BOUNCE = 'hard_bounce'
    SOFT_BOUNCE = 'soft_bounce'
