from django.conf.urls import url

from .views import CheckVerificationCodeView, RenteeLoanView


urlpatterns = [
    url(r'^check-verification-code/(?P<loan_xid>[0-9]+)/', CheckVerificationCodeView.as_view()),
    url(r'^fetch-loan', RenteeLoanView.as_view()),
]
