from __future__ import unicode_literals

from django.conf.urls import url

from juloserver.disbursement.views import crm_views

urlpatterns = [
    url(
        r'^daily_disbursement_limit$',
        crm_views.daily_disbursement_limit_whitelist_view,
        name='daily_disbursement_limit_whitelist_upload'
    )
]
