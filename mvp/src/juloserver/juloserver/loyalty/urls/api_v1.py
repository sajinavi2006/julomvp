from __future__ import unicode_literals
from __future__ import absolute_import

from rest_framework import routers
from django.conf.urls import url

from juloserver.loyalty.views.views_api_v1 import (
    DailyCheckinAPIClaimView,
    DailyCheckinAPIView,
    LoyaltyInfoAPIView,
    LoyaltyMissionDetailAPIView,
    LoyaltyMissionClaimRewardsAPIView,
    LoyaltyPointHistoryAPIView,
    LoyaltyMissionGetSearchCategories,
    load_criteria_by_category,
    load_sepulsa_categories_by_transaction_method,
    load_reward_by_category,
    generate_field_transaction_method,
    AccountPaymentListAPIView,
    PointInformation,
    PointRepayment,
    PointTransferBottomSheet,
    GopayTransfer,
    CheckGopayTransfer,
    DanaTransfer,
    CheckDanaTransfer,
    FloatingActionButtonAPI,
    LoyaltyEntryPointAPIView,
    load_target_by_category,
)


router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^info$',
        LoyaltyInfoAPIView.as_view(),
        name='info_v1'
    ),
    url(
        r'^daily-checkin/claim',
        DailyCheckinAPIClaimView.as_view(),
        name='daily-checkin-claim_v1'
    ),
    url(
        r'^daily-checkin',
        DailyCheckinAPIView.as_view(),
        name='daily-checkin_v1'
    ),
    url(
        r'^mission/details/(?P<mission_config_id>[0-9]+)$',
        LoyaltyMissionDetailAPIView.as_view(),
        name='mission_details_v1'
    ),
    url(
        r'^mission/claim',
        LoyaltyMissionClaimRewardsAPIView.as_view(),
        name='mission_claim_v1'
    ),
    url(
        r'^point-history',
        LoyaltyPointHistoryAPIView.as_view(),
        name='point_history_v1'
    ),
    url(r'^load_reward_by_category/(?P<category>[A-Za-z0-9]+)/$',
        load_reward_by_category,
        name='load_reward_by_category'),
    url(r'^load_criteria_by_category/(?P<category>[A-Za-z0-9]+)/$',
        load_criteria_by_category,
        name='load_criteria_by_category'),
    url(r'^load_target_by_category/(?P<category>[A-Za-z0-9]+)/$',
        load_target_by_category,
        name='load_target_by_category'),
    url(r'^load_sepulsa_categories_by_transaction_method/(?P<transaction_method>[A-Za-z0-9]+)/$',
        load_sepulsa_categories_by_transaction_method,
        name='load_sepulsa_categories_by_transaction_method'
    ),
    url(r'^generate_field_transaction_method/(?P<target_trx>[0-9]+)/$',
        generate_field_transaction_method, name='generate_field_transaction_method'),
    url(
        r'^account-payment$',
        AccountPaymentListAPIView.as_view(),
        name='account-payment_v1'
    ),
    url(
        r'^get_search_categories$',
        LoyaltyMissionGetSearchCategories.as_view(),
        name='get_search_categories_v1',
    ),
    url(r'^point-information',
        PointInformation.as_view(),
        name='point_information_v1'),
    url(r'^payment$', PointRepayment.as_view(), name='point_payment_v1'),
    url(
        r'^point-transfer-bottom-sheet$',
        PointTransferBottomSheet.as_view(),
        name='point_transfer_bottom_sheet_v1'
    ),
    url(r'^gopay_transfer$', GopayTransfer.as_view(), name='gopay-transfer'),
    url(r'^check_gopay_transfer$', CheckGopayTransfer.as_view(), name='check-gopay-transfer'),
    url(r'^dana_transfer$', DanaTransfer.as_view(), name='dana-transfer'),
    url(r'^check_dana_transfer$', CheckDanaTransfer.as_view(), name='check-dana-transfer'),
    url(r'^android_floating_action_button$', FloatingActionButtonAPI.as_view(),
        name='android_floating_action_button'),
    url(
        r'^loyalty_entry_point$', LoyaltyEntryPointAPIView.as_view(),
        name='loyalty-entry-point'
    ),
]
