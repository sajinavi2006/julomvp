from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_bca_api_v1 as views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^registration$', views.AccountRegistrationView.as_view()),
    url(r'^revocation$', views.AccountRevocationView.as_view()),
    url(r'^status$', views.AccountStatusView.as_view()),
    url(r'^reset$', views.AccountResetView.as_view()),
    url(r'^tutorial$', views.AccountTutorialView.as_view()),
    url(r'^reactivate$', views.ReactivateView.as_view()),
]
