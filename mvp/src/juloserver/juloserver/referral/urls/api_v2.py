from django.conf.urls import url
from rest_framework import routers

from juloserver.referral import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^referral-home/$', views.ReferralHomeV2.as_view(), name='referral_home_v2',),
    url(r'^top-referral-cashbacks/$',
        views.TopReferralCashbacksView.as_view(),
        name='top-referral-cashbacks'),
]
