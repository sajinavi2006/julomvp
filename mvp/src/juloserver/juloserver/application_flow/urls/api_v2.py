from django.conf.urls import url

from juloserver.application_flow import views

urlpatterns = [
    url(r'^emulators/(?P<application_id>[0-9]+)', views.GooglePlayIntegrity.as_view()),
    url(r'^emulator-check-decode/(?P<application_id>[0-9]+)',
        views.GooglePlayIntegrityDecodeView.as_view()),
    url(r'^emulator-check-ios/(?P<application_id>[0-9]+)', views.EmulatorCheckIOSView.as_view()),
]
