from django.contrib import admin

from juloserver.antifraud.admin.fraud_blacklist_data import FraudBlacklistDataAdmin
from juloserver.antifraud.models.fraud_blacklist_data import FraudBlacklistData

admin.site.register(FraudBlacklistData, FraudBlacklistDataAdmin)
