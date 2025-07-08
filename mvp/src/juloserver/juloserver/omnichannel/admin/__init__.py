from django.contrib import admin

from juloserver.omnichannel.admin.omnichannel_cust_sync import OmnichannelCustomerSyncAdmin
from juloserver.omnichannel.models import OmnichannelCustomerSync

admin.site.register(OmnichannelCustomerSync, OmnichannelCustomerSyncAdmin)
