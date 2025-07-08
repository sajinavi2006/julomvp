from django.conf.urls import url
from rest_framework import routers

from juloserver.bpjs.views import view_v2 as view

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r"^public-access-token$",
        view.GeneratePublicAccessToken.as_view(),
        name="bpjs-public-access-token",
    ),
    url(
        r"applications/(?P<application_xid>.*)/brick-callback",
        view.BrickCallback.as_view(),
        name="brick-bpjs-callback",
    ),
    url(r"logs", view.BrickAPILogs.as_view(), name="brick-api-logs"),
    url(
        r"^generate-web-view-bpjs$",
        view.GenerateWebViewBPJS.as_view(),
        name="bpjs-generate-web-view",
    ),
]
