from django.conf.urls import url
from rest_framework import routers

from juloserver.referral import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^referral-home/$', views.ReferralHome.as_view()),
    url(
        r'^referral-check-limit/(?P<referral_code>[A-Za-z0-9\s]+)/?$',
        views.ReferralCodeLimit.as_view(),
    ),
    url(r'^promo/(?P<customer_id>[0-9]+)/$', views.PromoInfoView.as_view()),
    url(r'^promos/(?P<customer_id>[0-9]+)/$', views.PromoInfoViewV1.as_view()),
]
