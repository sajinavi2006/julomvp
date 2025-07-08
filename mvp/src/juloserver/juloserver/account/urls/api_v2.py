from django.conf.urls import url
from rest_framework import routers
from juloserver.account import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^active-payment', views.AccountPaymentListV2.as_view()),
    url(r'^account-payment/$', views.AccountPaymentListEnhV2.as_view()),
    url(r'^account-payment-summary/$', views.AccountPaymentSummary.as_view()),
    url(r'^payback-transaction/$', views.PaybackTransactionList.as_view()),
    url(
        r'^payback-transaction/detail/(?P<payback_id>[0-9]+)$',
        views.PaybackTransactionDetail.as_view(),
    ),
]
