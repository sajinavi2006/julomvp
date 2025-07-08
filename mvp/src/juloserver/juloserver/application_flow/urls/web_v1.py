from __future__ import unicode_literals

from django.conf.urls import url

from juloserver.application_flow import web_views

urlpatterns = [
    url(r'^dropdown_list', web_views.DropDownApi.as_view()),
    url(r'^resubmit_bank_account', web_views.ResubmitBankAccount.as_view()),
]
