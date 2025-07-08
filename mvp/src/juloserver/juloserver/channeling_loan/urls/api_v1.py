from django.conf.urls import url

from juloserver.channeling_loan.views.view_api_v1 import DBSUpdateLoanStatusView


urlpatterns = [
    # DBS callback (follow DBS api document)
    url(
        r'^unsecuredLoans/statusUpdate$',
        DBSUpdateLoanStatusView.as_view(),
        name='dbs_update_loan_status',
    ),
]
