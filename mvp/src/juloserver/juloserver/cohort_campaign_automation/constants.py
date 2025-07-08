from builtins import object


class CohortCampaignAutomationStatus(object):
    SCHEDULED = 'Scheduled'
    FAILED = 'Failed'
    CANCELED = 'Canceled'
    RUNNING = 'Running'
    DONE = 'Done'


class ValidContentTypeForCSV(object):
    VALID_CONTENT_TYPES_UPLOAD = [
        'text/csv',
        'application/vnd.ms-excel',
        'text/x-csv',
        'application/csv',
        'application/x-csv',
        'text/comma-separated-values',
        'text/x-comma-separated-values',
        'text/tab-separated-values',
    ]
