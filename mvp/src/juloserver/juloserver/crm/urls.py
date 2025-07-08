from django.conf.urls import include, url
from rest_framework import routers
from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),

    # Endpoint for getting all history in application page
    url(r'^application-history/(?P<application_id>[0-9]+)/$',
        views.ApplicationDetailHistoryView.as_view()),
    url(r'^application-notes/$',
        views.ApplicationNotesView.as_view()),
    url(r'^check-app-locked/(?P<application_id>[0-9]+)/$',
        views.AppLockedView.as_view()),
    url(r'^set-app-locked/$',
        views.AppLockedView.as_view()),
    url(r'^get-lock-status/(?P<application_id>[0-9]+)/$',
        views.GetLockStatusView.as_view()),
    url(r'^set-unlock-app/$',
        views.SetUnlockApp.as_view()),
    url(r'^application/(?P<application_id>[0-9]+)/$',
        views.ApplicationDetailView.as_view()),
    url(r'^change-status/$',
        views.ChangeStatusUpdateView.as_view()),
    url(r'^canned-response/(?P<canned_response_id>[0-9]+)/$',
        views.CannedResponseView.as_view()),
    url(r'^canned-response/$',
        views.CannedResponseListCreateView.as_view()),
    url(r'^send-email/$',
        views.SendEmailView.as_view()),
]
