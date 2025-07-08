from django.conf.urls import url

from rest_framework import routers

from juloserver.payback import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^transactions/$', views.TransactionView.as_view()),
    url(r'^gopay/init/$', views.GopayView.as_view({"post": "init"})),
    url(r'^gopay/request-status/(?P<transaction_id>.+)/$',
        views.GopayView.as_view({"get": "current_status"})),
    url(r'^gopay/callback/$', views.GopayCallbackView.as_view()),
    url(r'^gopay/onboarding', views.GopayOnboardingPageView.as_view()),
    url(r'^gopay/pay-account/$', views.GopayCreatePayAccountView.as_view()),
    url(r'^gopay/pay-account-details/$', views.GopayGetPayAccountDetailsView.as_view()),
    url(
        r'^gopay/pay-account-link-notification', views.GopayPayAccountLinkNotificationView.as_view()
    ),
    url(r'^gopay/pay-account/unbind', views.GopayPayAccountUnbind.as_view()),
    url(r'^gopay/pay-account/init', views.GopayAccountRepaymentView.as_view()),
]
