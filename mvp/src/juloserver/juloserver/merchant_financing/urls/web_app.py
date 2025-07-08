from django.conf.urls import url, include
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r"^",
        include("juloserver.merchant_financing.web_app.urls.api_v1", namespace="web_app"),
    ),
    url(
        r"^",
        include(
            "juloserver.merchant_financing.web_app.urls.merchant_financing_v1",
            namespace="merchant_financing_web_app",
        ),
    ),
]
