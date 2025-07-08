from django.conf.urls import url

from juloserver.employee_financing.views import UpdateEmployeeFinancingApplicationStatus

from . import views

urlpatterns = [
    url(
        r'^change-application-status/$',
        views.ChangeApplicationStatus.as_view(),
        name='change-application-status',
    ),
    url(
        r'^update-device-scraped-data/(?P<pk>[0-9]+)/$',
        views.UpdateDeviceScrapeData.as_view(),
        name='update-device-scraped-data',
    ),
    url(
        r'^create-device-scraped-data/$',
        views.CreateDeviceScrapeData.as_view(),
        name='create-device-scraped-data',
    ),
    url(r'^create-skip-trace/$', views.CreateSkipTrace.as_view(), name='create-skip-trace'),
    url(
        r'^push-notification/etl/$',
        views.EtlPushNotification.as_view(),
        name='etl-push-notification',
    ),
    url(r'^obp-notification/$', views.ObpNotification.as_view(), name='obp-notification'),
    url(
        r'^push-notification-partner/etl/$',
        views.EtlPushNotificationPartner.as_view(),
        name='etl-push-notification-partner',
    ),
    url(
        r'^paylater/score-callback$',
        views.PaylaterScoreCallback.as_view(),
        name='paylater-score-callback',
    ),
    url(
        r'^web-notification/$',
        views.EtlPushNotificationWeb.as_view(),
        name='etl-push-notification-web',
    ),
    url(r'^iti-notification/$', views.ItiPushNotification.as_view(), name='iti-push-notification'),
    url(
        r'^etl-notification/update_status/$',
        views.EtlPushNotificationUpdateStatus.as_view(),
        name='etl-push-notification-update-status',
    ),
    url(
        r'^predict-bank-scrape/callback$',
        views.PredictBankScrapeCallback.as_view(),
        name='predict-bank-scrape-callback',
    ),
    url(
        r'^update-application-risky-check/$',
        views.UpdateApplicationRiskyCheck.as_view(),
        name='update-application-risky-check',
    ),
    url(
        r'^update-merchant-binary-check-score/$',
        views.UpdateMerchantBinaryCheckScore.as_view(),
        name='update-merchant-binary-check-score',
    ),
    url(
        r'^update-csv-partner-application-status/$',  # the application come from CSV
        views.UpdateCSVPartnerApplicationStatus.as_view(),
        name='update-csv-partner-application-status',
    ),
    url(
        r'^update-ef-application-status/$',  # the application come from CSV
        UpdateEmployeeFinancingApplicationStatus.as_view(),
        name='update-ef-application-status',
    ),
    url(
        r'^julo-starter/notification',
        views.JuloStarterNotification.as_view(),
        name='julo-starter-notification',
    ),
    url(
        r'^julo-starter/part2-notification',
        views.JuloStarterBinary.as_view(),
        name='julo-starter-binary',
    ),
    url(
        r'^fdc/calculation-ready',
        views.FDCCalculationReady.as_view(),
        name='fdc-calculation-ready',
    ),
    url(
        r'^push-notification/dsd/$',
        views.DSDCallbackReady.as_view(),
        name='dsd-callback',
    ),
]
