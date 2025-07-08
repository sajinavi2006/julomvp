from __future__ import unicode_literals

from django.conf.urls import url
from rest_framework import routers
from juloserver.partnership import views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^applications/(?P<application_id>[0-9]+)$',
        views.PartnershipDigitalSignatureGetApplicationView.as_view(),
        name="partnership_digital_signature_get_application",
    ),
    url(
        r'^applications/(?P<application_id>[0-9]+)/dukcapil',
        views.PartnershipDigitalDigitalSignatureDukcapil.as_view(),
        name="partnership_digital_signature_dukcapil",
    ),
    url(
        r'^sign/callback',
        views.PartnershipDigitalSignatureSignCallbackView.as_view(),
        name="partnership_digital_signature_sign_callback",
    ),
]
