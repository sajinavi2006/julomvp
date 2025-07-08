from django.conf.urls import url

from rest_framework import routers

from juloserver.autodebet.views import views_api_v3 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^status/',
        views.AccountStatusView.as_view()
    )
]
