from django.conf.urls import url

from rest_framework import routers

from juloserver.ovo.views import ovo_tokenization_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^onboarding$', ovo_tokenization_views.OvoTokenizationOnboardingView.as_view()),
    url(r'^binding$', ovo_tokenization_views.OvoTokenizationBinding.as_view()),
    url(r'^status$', ovo_tokenization_views.OvoGetLinkingStatus.as_view()),
    url(r'^binding-status$', ovo_tokenization_views.OvoTokenizationBindingStatus.as_view()),
    url(r'^payment$', ovo_tokenization_views.OvoTokenizationPayment.as_view()),
    url(r'^unbinding$', ovo_tokenization_views.OvoTokenizationUnbinding.as_view()),
]
