from django.conf.urls import url

from rest_framework import routers

from juloserver.payback import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^product$', views.DanaBillerProductView.as_view()),
    url(r'^destination/inquiry$', views.DanaBillerInquiryView.as_view()),
    url(r'^order/create', views.DanaBillerCreateOrderView.as_view()),
    url(r'^order/detail$', views.DanaGetOrderDetailView.as_view()),
]
