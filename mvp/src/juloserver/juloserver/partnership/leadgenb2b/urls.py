from django.conf.urls import url, include
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^',
        include('juloserver.partnership.leadgenb2b.onboarding.urls.api_v1', namespace='onboarding'),
    ),
    url(
        r'^',
        include(
            'juloserver.partnership.leadgenb2b.non_onboarding.urls.api_v1',
            namespace='non_onboarding',
        ),
    ),
]
