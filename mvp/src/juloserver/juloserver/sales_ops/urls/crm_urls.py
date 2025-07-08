from django.conf.urls import url
import juloserver.sales_ops.views.crm_views as crm_views

urlpatterns = [
    url(r'^list$', crm_views.SalesOpsBucketList.as_view(), name='list'),
    url(r'^detail/(?P<pk>\d+)$', crm_views.SalesOpsBucketDetail.as_view(), name='detail'),
    url(r'^create_callback_history',
        crm_views.create_callback_history, name='create_callback_history'),
    url(r'^add_skiptrace', crm_views.add_skiptrace, name='add_skiptrace'),
    url(r'^update_skiptrace', crm_views.update_skiptrace, name='update_skiptrace'),
    url(r'^skiptrace_history', crm_views.skiptrace_history, name='skiptrace_history'),
    url(r'^ajax-block/(?P<lineup_id>\d+)$', crm_views.ajax_block, name='ajax-block'),
    url(r'vendor-rpc$', crm_views.VendorRPCCreateView.as_view(), name='vendor_rpc'),
    url(r'vendor-rpc-histories', crm_views.VendorRPCListView.as_view(), name='vendor_rpc_histories'),
]
