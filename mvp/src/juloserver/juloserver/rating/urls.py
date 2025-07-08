from django.conf.urls import url
from rest_framework import routers
from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/show-popup$', views.RatingDeciderAPI.as_view()),
    url(r'^v1/submit$', views.SubmitRatingAPI.as_view()),
    url(r'^v1/loan/show-success-popup$', views.SuccessLoanRatingAPI.as_view()),
]
