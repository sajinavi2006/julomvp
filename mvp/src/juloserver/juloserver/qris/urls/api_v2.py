from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.qris.views import view_api_v2 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^transactions', views.QrisTransactionListViewV2.as_view()),
]
