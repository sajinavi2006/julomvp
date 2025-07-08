from django.conf.urls import url
from rest_framework import routers
from juloserver.julo_starter.views import view_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^user-check-eligibility/(?P<customer_id>[0-9]+)$',
        view_v1.UserCheckEligibility.as_view(),
    ),
    url(
        r'^check-process-eligibility/(?P<customer_id>[0-9]+)$',
        view_v1.CheckProcessEligibility.as_view(),
    ),
    url(r'^application/(?P<pk>[0-9]+)$', view_v1.ApplicationUpdate.as_view()),
    url(
        r'^submit-form-extra/(?P<application_id>[0-9]+)$',
        view_v1.ApplicationExtraForm.as_view(),
    ),
    url(
        r'^second-check-status/(?P<application_id>[0-9]+)$',
        view_v1.SecondCheckStatus.as_view(),
    ),
]
