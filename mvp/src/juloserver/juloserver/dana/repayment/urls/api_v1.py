from django.conf.urls import url
from rest_framework import routers
from juloserver.dana.repayment import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'debit/repayment-host-to-host', views.DanaRepaymentView.as_view(), name="repayment"),
]
