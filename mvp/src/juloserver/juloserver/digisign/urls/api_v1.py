from __future__ import unicode_literals
from __future__ import absolute_import

from rest_framework import routers
from django.conf.urls import url

from juloserver.digisign.views.views_api_v1 import (
    DigisignDocumentConsentPage,
    DigisignRegistrationAPIView,
    SignDocumentCallback,
)


router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^get_consent_page$',
        DigisignDocumentConsentPage.as_view(),
        name='get_consent_page'
    ),
    url(
        r'^registration/check$',
        DigisignRegistrationAPIView.as_view(),
        name='digisign_registration'
    ),
    url(
        r'^sign_document/callback',
        SignDocumentCallback.as_view(),
        name='sign_document_callback'
    ),
]
