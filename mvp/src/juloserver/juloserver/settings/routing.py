"""
routing.py
purpose: config for views and tasks need to be routed to replica DB
"""

# Django views
# Using
# REPLICATED_VIEWS_OVERRIDES = (
#     'api-store-event',
#     'app.views.do_smthg': 'master',
#     '/admin/*': 'master',
#     '/users/': 'slave',
# )
REPLICATED_VIEWS_OVERRIDES = (
    #'dashboard.views.get_dashboard_bucket_count',
    #'payment_status.views.ajax_payment_list_view',
    #'juloserver.apiv2.views.UnpaidPaymentPopupView',
    #'juloserver.apiv1.views.ImageListView',
    #'juloserver.apiv1.views.LoanListView',
    #'juloserver.apiv2.views.EtlJobStatusListView',
    #'app_status.views.ApplicationDataWSCListView',
    #'juloserver.apiv2.views.CashbackBar',
    'juloserver.apiv2.views.FAQDataView',
    'juloserver.apiv1.views.DropDownApi',
    'juloserver.apiv2.views.StatusLabelView',
    #'juloserver.apiv1.views.PaymentListView',
    #'juloserver.apiv2.views.VersionCheckView',
    #'dashboard.views.ajax_get_application_autodialer',
    #'dashboard.views.get_collection_bucket_v2',
    #'app_status.views.ApplicationDataListView',
    #'payment_status.views.payment_list_view_v2',
    #'bl_statement.views.statement_detail',
    'juloserver.apiv1.views.PartnerReferralRetrieveView',
)


# Celery tasks
# Use task name if it was defined Ex: 'pn_app_105_subtask'
# Use path to task if it was not defined Ex: 'juloserver.julo.tasks.pn_app_105_subtask'
REPLICATED_CELERY_TASKS = (
    'send_phone_verification_reminder_pm',
)

# Ignore model list
IGNORE_MODELS = (
    "Token",
)
