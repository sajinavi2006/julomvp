from django.conf.urls import include, url
from rest_framework import routers

from .views import BoostDataUpdate, BoostStatusAtHomepageView, BoostStatusView

router = routers.DefaultRouter()


urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^status/(?P<application_id>[0-9]+)/$', BoostStatusView.as_view(), name='boost-status'),
    url(r'^update/(?P<application_id>[0-9]+)/$', BoostDataUpdate.as_view(), name="boost-update"),
    url(
        r'^document-status/(?P<application_id>[0-9]+)/$',
        BoostStatusAtHomepageView.as_view(),
        name="document-status",
    ),
]
