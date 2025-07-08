from builtins import object
from django.conf import settings
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst

LENDER_ACCOUNT_PARTNER = "Mintos"
LOAN_SENDIN_STATUS = "Current"
LOAN_SENDIN_TYPES = ["initial_tag", "replenishment_tag"]
LOAN_SENDIN_LOG_TYPE = "post-loans"
LOAN_REBUY_LOG_TYPE = "post-rebuy"
MINTOS_REQUEST_LIMIT = settings.MINTOS_REQUEST_LIMIT

class MintosExchangeScrape(object):
    URL = 'https://www.bi.go.id/en/moneter/informasi-kurs/transaksi-bi/Default.aspx'
    CURRENCY = 'EUR'