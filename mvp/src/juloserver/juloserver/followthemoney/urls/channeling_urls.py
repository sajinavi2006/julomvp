from __future__ import unicode_literals
from __future__ import absolute_import

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.followthemoney.views import channeling_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r"^", include(router.urls)),
    url(
        r"^list_application/(?P<channeling_type>[a-zA-Z0-9]+)/",
        channeling_views.ListApplicationViews.as_view(),
        name="list_application",
    ),
    url(
        r"^channeling_lender_approval/(?P<channeling_type>[a-zA-Z0-9]+)/",
        channeling_views.CreateLenderBucketChannelingViews.as_view(),
        name='channeling_lender_approvel'
    ),
]
