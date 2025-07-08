from django.conf.urls import url
from rest_framework import routers
from juloserver.dana_linking import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^onboarding/', views.DanaOnboardingPageView.as_view()),
    url(r'^link-account$', views.DanaLinkingView.as_view()),
    url(r'^finalize-link$', views.DanaFinalizeLinkingView.as_view()),
    url(r'^status$', views.DanaAccountStatusView.as_view()),
    url(r'^unbinding', views.DanaAccountUnbindingView.as_view()),
    url(r'^debit/payment$', views.DanaPaymentView.as_view()),
    url(r'^other-page-details$', views.DanaAccountOtherPageDetailsView.as_view()),
]
