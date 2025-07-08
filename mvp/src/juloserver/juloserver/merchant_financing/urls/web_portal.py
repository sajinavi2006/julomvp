from django.conf.urls import url, include
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include('juloserver.merchant_financing.web_portal.urls.api_v1', namespace='web_portal')),
]
