from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.qris.views import view_api_v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    # legacy
    url(r'^user-status', views.CheckUserStatus.as_view()),
    url(r'^linking-confirm', views.LinkingConfirm.as_view()),
    url(r'^submit-otp', views.SubmitOtp.as_view()),
    url(r'^scan', views.ScanQris.as_view()),
    url(r'^status/(?P<loan_xid>[0-9]+)$', views.StatusQris.as_view()),
    #
    url(r'^transaction-limit-check', views.TransactionLimitCheckView.as_view()),
    url(r'^user/agreement/?$', views.QrisUserAgreementView.as_view()),
    url(r'^user/signature/?$', views.QrisUserSignatureView.as_view()),
    url(r'^user/state/?$', views.QrisUserState.as_view()),
    url(r'^amar/callback/initial-account-status', views.AmarRegisterLoginCallbackView.as_view()),
    url(r'^transaction-confirmation', views.TransactionConfirmationView.as_view()),
    url(r'^transactions', views.QrisTransactionListView.as_view()),
    url(r'^amar/loan/callback/?$', views.AmarLoanCallbackView.as_view()),
    url(
        r'^amar/prefilled-data/(?P<to_partner_user_xid>[a-zA-Z0-9-]+)$',
        views.PrefilledDataView.as_view(),
    ),
    url(
        r'^tenure-range/?$',
        views.QrisTenureRangeView.as_view(),
    ),
    url(r'^config/?$', views.QrisConfigView.as_view()),
]
