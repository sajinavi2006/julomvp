from __future__ import unicode_literals
from __future__ import absolute_import

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.education.views import views_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(
        r'^student/(?P<student_register_id>\d+)$',
        views_api_v1.StudentRegisterListAndCreateView.as_view(),
    ),
    url(r'^student', views_api_v1.StudentRegisterListAndCreateView.as_view()),
    url(r'^school', views_api_v1.SchoolListView.as_view()),
    url(r'^faq/?$', views_api_v1.EducationFAQView.as_view()),
]
