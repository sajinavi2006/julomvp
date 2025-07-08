from django.conf.urls import url
from rest_framework import routers
from juloserver.account_payment.views import views_api_v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^payment_methods/$', views.PaymentMethodRetrieveView.as_view()),
    url(r'^payment_methods/(?P<payment_method_id>[0-9]+)/$',
        views.PaymentMethodUpdateView.as_view()),
    url(r'^last_unpaid_account_payment_detail/', views.GetLastAccountPaymentDetail.as_view()),
    url(r'^payment-method-instruction$', views.PaymentMethodInstructionView.as_view()),
    url(r'^repayment/check$', views.RepaymentCheckView.as_view()),
    url(r'^repayment/faq$', views.RepaymentFAQView.as_view()),
    url(r'^repayment/setting/check$', views.RepaymentSettingView.as_view()),
    url(r'^payment-method-experiment$', views.PaymentMethodExperimentView.as_view()),
]
