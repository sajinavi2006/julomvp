from django.conf.urls import url

from rest_framework import routers

from juloserver.payback import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^gopay/init/$', views.GopayView.as_view({"post": "init"})),
    url(r'^gopay/pay-account/init', views.GopayAccountRepaymentView.as_view()),
    url(r'^gopay/pay-account/$', views.GopayCreatePayAccountView.as_view()),
]
