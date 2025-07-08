from django.conf.urls import include, url
from rest_framework import routers

from juloserver.application_flow import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^reapply/', views.ApplicationReapplyJuloOne.as_view()),
    url(r'^longform/setting/', views.PreLongFormSettingAPI.as_view()),
    url(r'^get_application_image_url', views.GetApplicationImageURL.as_view()),
    url(r'^emulator-check', views.SafetyNetViewEmulatorCheck.as_view()),
    url(r'^bottom-sheet-tutorial$', views.TutorialBottomSheet.as_view()),
    url(r'^bank-statements/(?P<application_id>[0-9]+)/urls$', views.BankStatementUrl.as_view()),
    url(r'^bank-statements$', views.BankStatement.as_view()),
    url(r'^powercred/callback$', views.PowerCredCallback.as_view()),
    url(r'^perfios/callback$', views.PerfiosCallback.as_view()),
    url(
        r'^digital-signature/applications/(?P<application_id>[0-9]+)$',
        views.DigitalSignatureData.as_view(),
    ),
    url(
        r'^digital-signature/applications/(?P<application_id>[0-9]+)/dukcapil$',
        views.DigitalSignatureDukcapil.as_view(),
    ),
    url(
        r'^applications/(?P<application_id>[0-9]+)/self-correction$',
        views.SelfCorrectionTypoView.as_view(),
    ),
    url(
        r'^applications/(?P<application_id>[0-9]+)/self-mother-correction$',
        views.SelfMotherCorrectionView.as_view(),
    ),
    url(
        r'^applications/(?P<application_id>[0-9]+)/self-mother-typo-correction$',
        views.SelfMotherTypoCorrectionView.as_view(),
    ),
    url(
        r'^applications/(?P<application_id>[0-9]+)/bank-correction$',
        views.BankCorrectionView.as_view(),
    ),
    url(r'^instruction-verification-docs$', views.InstructionVerificationDocs.as_view()),
    url(
        r'^applications/(?P<application_id>[0-9]+)/decline-hsfbp$',
        views.DeclineHsfbpView.as_view(),
    ),
]
