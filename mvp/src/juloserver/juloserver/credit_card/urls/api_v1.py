from __future__ import unicode_literals
from django.conf.urls import url
from rest_framework import routers
from juloserver.credit_card.views import views_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^stock',
        views_api_v1.CardStockView.as_view(),
    ),

    # Card Android API requests group #

    url(
        r'^card/request',
        views_api_v1.CardRequestView.as_view(),
    ),
    url(
        r'^card/resubmission',
        views_api_v1.CardDataResubmissionView.as_view(),
    ),
    url(
        r'^card/information$',
        views_api_v1.CardInformation.as_view()
    ),
    url(
        r'^card/status$',
        views_api_v1.CardStatus.as_view()
    ),
    url(
        r'^card/confirmation$',
        views_api_v1.CardConfirmation.as_view()
    ),
    url(
        r'^card/validation$',
        views_api_v1.CardValidation.as_view()
    ),
    url(
        r'^card/otp/send$',
        views_api_v1.SendOTP.as_view()
    ),
    url(
        r'^card/activation$',
        views_api_v1.CardActivation.as_view()
    ),
    url(
        r'^card/pin/change',
        views_api_v1.CreditCardChangePinViews.as_view()
    ),
    url(
        r'^card/block$',
        views_api_v1.BlockCard.as_view()
    ),
    url(
        r'^card/block/reason$',
        views_api_v1.BlockReason.as_view()
    ),
    url(
        r'^card/unblock$',
        views_api_v1.UnblockCardView.as_view()
    ),
    url(
        r'^card/pin/reset',
        views_api_v1.ResetPinCreditCardViews.as_view()
    ),
    url(
        r'^card/check-otp',
        views_api_v1.CheckOTP.as_view()
    ),
    url(
        r'^faq$',
        views_api_v1.CreditCardFaq.as_view()
    ),
    url(
        r'^banner',
        views_api_v1.BannerView.as_view(),
    ),
    url(
        r'^card/transaction-history$',
        views_api_v1.TransactionHistoryView.as_view()
    ),

    # Card CCS API requests group #

    url(
        r'^card/upload/no',
        views_api_v1.CardAgentUploadDocsView.as_view()
    ),
    url(
        r'^card-control-system/credit-card-application/change-status',
        views_api_v1.CardChangeStatusView.as_view(),
    ),

    url(
        r'^card-control-system/bucket',
        views_api_v1.CardBucketView.as_view(),
    ),

    url(
        r'^card-control-system/credit-card-application-detail'
        r'/(?P<credit_card_application_id>[0-9]+)/',
        views_api_v1.CardApplicationDetailView.as_view(),
    ),

    url(
        r'^card-control-system/credit-card-application-list$',
        views_api_v1.CardApplicationListView.as_view(),
    ),
    url(
        r'^card-control-system/check-card',
        views_api_v1.CheckCardView.as_view(),
    ),
    url(
        r'^card-control-system/assign-card',
        views_api_v1.AssignCardView.as_view(),
    ),

    url(
        r'^card-control-system/block$',
        views_api_v1.CCSBlockCard.as_view()
    ),

    # TNC #

    url(
        r'^card/tnc/create/pdf',
        views_api_v1.CustomerTNCAgreementView.as_view(),
    ),

    url(
        r'^card/tnc/get/pdf',
        views_api_v1.CustomerTNCAgreementGetCustomerTNCAgreementView.as_view(),
    ),

    url(
        r'^card/tnc',
        views_api_v1.CardTNCView.as_view(),
    ),

    url(
        r'card-control-system/login$',
        views_api_v1.LoginCardControlViews.as_view(),
    ),

    url(
        r'^cdcTransaction$',
        views_api_v1.CreditCardTransactionView.as_view()
    ),
    url(
        r'^reversalCdcTransaction$',
        views_api_v1.ReversalJuloCardTransactionView.as_view()
    ),
    url(
        r'^notifyCardStatus$',
        views_api_v1.NotifyJuloCardStatusChangeView.as_view()
    ),
]
