from __future__ import unicode_literals
from __future__ import absolute_import

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.followthemoney.views import application_v2_views
from juloserver.followthemoney.withdraw_view import views as withdraw_view

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^lender/sphp/(?P<application_xid>[0-9]+)/$', application_v2_views.LenderSphp.as_view()),
    url(r'^customer/sphp/(?P<application_xid>[0-9]+)/$', application_v2_views.CustomerSphp.as_view()),
    url(r'^lender/preview-agreement/',
        application_v2_views.LenderPreviewAgreement.as_view()),
]
