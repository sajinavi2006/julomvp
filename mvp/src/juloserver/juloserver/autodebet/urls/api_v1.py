from django.conf.urls import url

from rest_framework import routers

from juloserver.autodebet.views import views_api_v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^tutorial/$', views.AccountTutorialView.as_view()),
    url(r'^status/', views.AccountStatusView.as_view()),
    url(r'^video/entry-page/$', views.IdfyInstructionPage.as_view()),
    url(r'^video/create-profile', views.CreateProfileRequest.as_view()),
    url(r'^video/start-timer-notification', views.IdfyScheduleNotification.as_view()),
    url(r'^deactivation/survey/$', views.DeactivationSurveyView.as_view()),
    url(r'^deactivation/survey/answer', views.DeactivationSurveyAnswerView.as_view()),
    url(r'^payment/offer', views.AutodebetPaymentOfferView.as_view()),
]
