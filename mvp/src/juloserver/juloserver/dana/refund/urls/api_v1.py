from django.conf.urls import url
from rest_framework import routers
from juloserver.dana.refund import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'debit/refund', views.DanaRefundView.as_view(), name="refund"),
]
