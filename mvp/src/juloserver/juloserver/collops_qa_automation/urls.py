from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^store_recording_report/', views.QAAirudderRecordingReportCallback.as_view()),
]
