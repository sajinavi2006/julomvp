from django.conf.urls import url
from rest_framework import routers
from .. import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^android_info_card', views.InfoCardAndroidAPI.as_view(),
        name='android_info_card'),
    url(r'^android_neo_banner_card', views.NeoBannerAndroidAPI.as_view(),
        name='android_neo_banner_card'),
    url(r'^disturb_logging_push_notification_permission',
        views.PushNotificationPermissionDisturbLogging.as_view(),
        name='disturb_logging_push_notification_permission'),
    url(r'^validate/notification', views.AndroidCheckNotificationValidity.as_view(),
        name='android_check_notification'),
    url(r'^android_ipa_banner$', views.IpaBannerAndroidAPI.as_view(),
        name='android_ipa_banner'),
    url(r'^account_selloff_content$', views.AccountSellOffContent.as_view(), name='account_selloff_content'),
    url(r'^slik_notif$', views.SlikNofication.as_view(), name='slik_notification'),
    url(r'^android_ptp_card$', views.PTPCardView.as_view(), name='ptp_card'),
]
