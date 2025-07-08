from django.conf.urls import url
from . import views

urlpatterns = [
    # Get LOC info from LineOfCreditService.get_info
    url(r'^activity/$', views.LineOfCreditActivityView.as_view()),
    url(r'^add-purchase/$', views.LineOfCreditPurchaseView.as_view()),
    url(r'^product/(?P<product_id>[0-9]+)$', views.LineOfCreditProductListByIdView.as_view()),
    url(r'^product/type/$', views.LineOfCreditProductListByTypeView.as_view()),
    url(r'^product/inquiry/electricity-account/$', views.LineOfCreditProductInquryElectricityAccountView.as_view()),
    url(r'^transaction/$', views.LineOfCreditTransactionView.as_view()),
    url(r'^statement/(?P<statement_id>[0-9]+)$', views.LineOfCreditStatementDetailView.as_view()),
    url(r'^payment_methods/$', views.LineOfCreditPaymentMethodView.as_view()),
    url(r'^pin/update/$', views.LineOfCreditSetUpdatePinView.as_view()),
    url(r'^pin/reset/$', views.LineOfCreditResetPin.as_view()),
    url(r'^pin/reset/confirm/(?P<reset_pin_key>.+)/$', views.LineOfCreditResetPinConfirm.as_view()),
    url(r'^pin/reset/status$', views.LineOfCreditPinStatus.as_view()),
]
