from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_gopay_api_v1 as views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^registration$', views.GopayRegistrationView.as_view()),
    url(r'^revocation$', views.GopayRevocationView.as_view()),
    url(r'^reactivate$', views.ReactivateView.as_view()),
]
