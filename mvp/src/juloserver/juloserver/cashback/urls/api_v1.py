from ..views import api_views as views

from django.conf.urls import url
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^xendit$', views.CashbackTransfer.as_view()),
    url(r'^sepulsa$', views.CashbackSepulsa.as_view()),
    url(r'^gopay$', views.CashBackToGopay.as_view()),
    url(r'^payment$', views.CashbackPayment.as_view()),
    url(r'^information', views.CashbackInformation.as_view()),
    url(r'^options_info$', views.CashbackOptionsInfoV1.as_view()),
    url(r'^submit_overpaid$', views.SubmitOverpaid.as_view()),
    url(r'^overpaid_verification$', views.OverpaidVerification.as_view()),
]
