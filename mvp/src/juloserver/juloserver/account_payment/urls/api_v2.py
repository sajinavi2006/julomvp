from django.conf.urls import url
from rest_framework import routers
from juloserver.account_payment.views import views_api_v2 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^payment_methods/(?P<account_id>[0-9]+)$', views.PaymentMethodRetrieveView.as_view()),
    url(
        r'^payment_checkout',
        views.PaymentCheckout.as_view()
    ),
    url(
        r'^payment_status',
        views.UpdateCheckoutRequestStatus.as_view()
    ),
    url(
        r'^checkout_receipt',
        views.UploadCheckoutReceipt.as_view()
    ),
    url(
        r'^crm_customer_detail_list/(?P<account_payment_id>[0-9]+)/$',
        views.CRMCustomerDetailList.as_view(), name='ajax_crm_customer_detail_list'),
    url(
        r'^crm_unpaid_loan_account_details_list/(?P<account_payment_id>[0-9]+)/$',
        views.CRMUnpaidLoanAccountDetailsList.as_view(),
        name='ajax_crm_unpaid_loan_account_details_list'),
]
