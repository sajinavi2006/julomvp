from django.conf.urls import include, url
from rest_framework import routers


from . import views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^activation/$', views.ActivationView.as_view()),
    url(r'^validate/$', views.ValidateView.as_view()),
    url(r'^transactions/$', views.TransactionsView.as_view()),
    url(r'^refund/$', views.RefundView.as_view()),
    url(r'^transaction_detail/$', views.TransactionDetailView.as_view()),
    url(r'^credit_limit/$', views.CreditLimitView.as_view()),
    url(r'^repayment/$', views.RepaymentView.as_view()),
    url(r'^statements/$', views.StatementsView.as_view()),
    url(r'^scrap/$', views.ScrapView.as_view()),
    url(r'^invoice_detail/$', views.TransactionDetailView.as_view()),
    url(r'^refund/$', views.RefundView.as_view()),
    url(r'^dummy-callback/$', views.DummyView.as_view()),
    url(r'^approval/(?P<customer_xid>[0-9]+)/$', views.ApprovalView.as_view(), name='approval'),
]
