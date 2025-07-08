from django.conf.urls import url
from rest_framework import routers
from juloserver.account_payment.views import views_api_v3 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^payment_methods/(?P<account_id>[0-9]+)$', views.PaymentMethodRetrieveView.as_view()),
]
