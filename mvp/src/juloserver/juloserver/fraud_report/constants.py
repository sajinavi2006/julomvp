from django.conf import settings

OSS_FRAUD_REPORT_BUCKET = 'fraudreport-{}'.format(str(settings.ENVIRONMENT))
