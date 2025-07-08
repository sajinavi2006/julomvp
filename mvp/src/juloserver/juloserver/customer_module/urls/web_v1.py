from django.conf.urls import url
from rest_framework import routers

from juloserver.customer_module.views import views_web_v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^credit-info', views.CreditInfoView.as_view()),
]
