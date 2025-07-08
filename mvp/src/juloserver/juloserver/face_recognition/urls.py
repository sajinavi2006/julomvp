from django.conf.urls import include, url
from rest_framework import routers

from . import views
from juloserver.face_recognition.views import (
    CheckImageQualityView,
    CheckImageQualityViewV1,
    CheckImageQualityViewV2,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^selfie/check-upload$', CheckImageQualityView.as_view()),
    url(
        r'^face_search_process',
        views.ajax_check_face_search_process_status,
        name='face_search_process',
    ),
    url(r'^get_similar_faces/(?P<pk>\d+)$', views.get_similar_faces, name='get_similar_faces'),
    url(r'^submit_matched_images', views.submit_matched_images, name='submit_matched_images'),
    url(r'^v1/selfie/check-upload$', CheckImageQualityViewV1.as_view()),
    url(
        r'^get_similar_fraud_faces/(?P<pk>\d+)$',
        views.get_similar_fraud_faces,
        name='get_similar_fraud_faces',
    ),
    url(r'^v2/selfie/check-upload$', CheckImageQualityViewV2.as_view()),
    url(r'^face-matching$', views.FaceMatchingView.as_view(), name='face-matching'),
]
