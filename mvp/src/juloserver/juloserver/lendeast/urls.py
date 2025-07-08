from django.conf.urls import url
from rest_framework import routers

from juloserver.lendeast import views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/loaninformation$', views.LoanInformation.as_view()),
]
