from __future__ import unicode_literals

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.merchant_financing import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),

    # Axiata API

    url(r'^auth', views.PartnerAuthenticationView.as_view()),  # TODO: deprecate
    url(r'^application/status', views.PartnerApplicationView.as_view()),  # TODO: deprecate
    url(r'^application', views.PartnerApplicationView.as_view()),  # TODO: deprecate
    url(r'^disbursement', views.PartnerDisbursementView.as_view()),  # TODO: deprecate
    url(r'^api/auth', views.PartnerAuthenticationView.as_view()),
    url(r'^api/application/status', views.PartnerApplicationView.as_view()),
    url(r'^api/application', views.PartnerApplicationView.as_view()),
    url(r'^api/disbursement', views.PartnerDisbursementView.as_view()),
    url(r'^api/report$', views.AxiataDailyReport.as_view()),
]
