from juloserver.email_delivery.constants import EmailStatusMapping


def email_status_prioritization(old_status: str, new_status: str) -> str:
    """
    Control the prioritization of overriding email statuses received from MoEngageStream.
    Higher priority email status should not be overriden by lower priority email status.
    """
    if (
        not old_status
        or EmailStatusMapping['MoEngageStreamPriority'][new_status]
        > EmailStatusMapping['MoEngageStreamPriority'][old_status]
    ):
        return new_status
    else:
        return old_status
