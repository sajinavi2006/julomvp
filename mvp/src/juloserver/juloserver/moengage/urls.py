from django.conf.urls import include, url
from rest_framework import routers
from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^callback/pn_details', views.MoengagePnDetails.as_view()),
    url(r'^callback/sms_details', views.MoengageSMSDetails.as_view()),
    url(r'^callback/email_details', views.MoengageEmailDetails.as_view()),
    url(r'^callback/inappnotif_details', views.MoengageInAppDetails.as_view()),
    # url(r'^callback/streams/updated', views.MoengageStreamView2.as_view()),
    url(r'^callback/streams', views.MoengageStreamView2.as_view()),
]
