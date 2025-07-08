from django.conf.urls import include, url
from rest_framework import routers
from juloserver.fdc import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^inquiry/', views.RunFDCInquiryView.as_view(), name="inquiry"),
]
