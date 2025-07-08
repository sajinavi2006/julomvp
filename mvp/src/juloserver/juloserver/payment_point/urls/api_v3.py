from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.payment_point.views import views_api_v3

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^inquire/train/station', views_api_v3.InquireTrainStationView.as_view()),
    url(r'^inquire/train/ticket', views_api_v3.InquireTrainTicketView.as_view()),
    url(r'^inquire/pdam/bill', views_api_v3.InquirePdamView.as_view()),
    url(r'^inquire/pdam/operator', views_api_v3.InquirePdamOperatorView.as_view()),
    url(r'^train/ticket', views_api_v3.TrainTicketView.as_view()),
    url(r'^train/passenger/seat', views_api_v3.TrainTicketPessengerSeat.as_view()),
    url(r'^train/change/seat', views_api_v3.TrainTicketChangeSeat.as_view()),
    url(r'^train/transaction/history', views_api_v3.TrainTicketTransactionHistory.as_view()),
    url(
        r'^train/booking/info/(?P<booking_code>.+)/$',
        views_api_v3.TrainTicketTransactionBookingInfo.as_view(),
    ),
    url(r'^train/info/(?P<loan_xid>[0-9]+)', views_api_v3.TrainTicketTransactionInfo.as_view()),
]
