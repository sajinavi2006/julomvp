from __future__ import unicode_literals

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.merchant_financing import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    # Axiata WEB API
    url(r'^(?P<partner_name>[a-z0-9A-Z_-]+)/list-data', views.AxiataListData.as_view()),
]
