import logging

from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.template import RequestContext, Template
from django.template.loader import get_template
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from juloserver.account.models import Account
from juloserver.apiv2.constants import PromoType
from juloserver.cfs.services.core_services import get_cfs_referral_bonus_by_application
from juloserver.collection_hi_season.constants import (
    EXCLUDE_PENDING_REFINANCING_STATUS,
    CampaignBanner,
)
from juloserver.collection_hi_season.models import (
    CollectionHiSeasonCampaignBanner,
    CollectionHiSeasonCampaignParticipant,
)
from juloserver.collection_hi_season.services import (
    get_active_collection_hi_season_campaign,
    get_dpd_from_payment_terms,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Customer, ReferralSystem
from juloserver.julo.utils import display_rupiah
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.promo.models import PromoHistory
from juloserver.promo.services import check_promo_code_application_type_exist
from juloserver.followthemoney.utils import (
    success_response,
)
from .services import (
    get_total_referral_invited_and_total_referral_benefits,
    show_referral_code,
    check_referral_code_is_limit,
    get_shareable_referral_image,
    get_referral_data,
    get_top_referral_cashbacks,
)
from .constants import ReferralCodeMessage
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response as success_response_api,
)
from juloserver.application_form.services.application_service import (
    is_user_offline_activation_booth,
)

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


class ReferralHome(APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.application_set.last()
        if not show_referral_code(customer):
            return general_error_response(ReferralCodeMessage.UNAVAILABLE_REFERRAL_CODE)

        referral_system = ReferralSystem.objects.get(name='PromoReferral')

        (
            total_referral_invited,
            total_referral_benefits,
        ) = get_total_referral_invited_and_total_referral_benefits(customer)

        cfs_referral_bonus = get_cfs_referral_bonus_by_application(application)
        referral_bonus = (
            cfs_referral_bonus if cfs_referral_bonus else referral_system.caskback_amount
        )

        content = referral_system.extra_data['content']
        cashback_currency = display_rupiah(referral_bonus)
        cashback_referee_currency = display_rupiah(referral_system.referee_cashback_amount)

        shareable_referral_image = None
        text, image = get_shareable_referral_image()
        if text and image:
            shareable_referral_image = {
                'text_x_coordinate': text['coordinates']['x'],
                'text_y_coordinate': text['coordinates']['y'],
                'text_size': text['size'],
                'image_url': image,
            }

        return success_response(
            {
                "header": content['header'],
                "image": referral_system.banner_static_url,
                "body": content['body'].format(cashback_currency, cashback_referee_currency),
                "footer": content['footer'],
                "referral_code": customer.self_referral_code,
                'message': content['message'].format(
                    cashback_referee_currency, customer.self_referral_code
                ),
                'terms': content['terms'].format(cashback_currency),
                'total_referral_invited': total_referral_invited,
                'total_referral_benefits': total_referral_benefits,
                'shareable_referral_image': shareable_referral_image,
                'referee_cashback_amount': referral_system.referee_cashback_amount,
            }
        )


class PromoInfoView(APIView):
    permission_classes = (AllowAny,)
    """
    API to record customer who click the banner
    """

    def get(self, request, customer_id):
        if Customer.objects.get_or_none(pk=customer_id) is None:
            return render(request, '404-promo.html')

        last_days_delta = 3

        promo_history = PromoHistory.objects.get_or_none(
            customer_id=customer_id, promo_type=PromoType.RUNNING_PROMO
        )

        if promo_history is not None:
            oldest_account_payment = promo_history.account.get_oldest_unpaid_account_payment()
            if not oldest_account_payment:
                return render(request, '404-promo.html')
            last_date_payment_promo = oldest_account_payment.due_date - relativedelta(
                days=last_days_delta
            )

            return render(request, promo_history.promo_type, {'due_date': last_date_payment_promo})

        account = Account.objects.filter(customer_id=customer_id).last()
        if not account:
            return render(request, '404-promo.html')
        oldest_account_payment = account.get_oldest_unpaid_account_payment()
        if not oldest_account_payment:
            return render(request, '404-promo.html')
        last_date_payment_promo = oldest_account_payment.due_date - relativedelta(
            days=last_days_delta
        )

        PromoHistory.objects.create(
            customer_id=customer_id,
            account=account,
            promo_type=PromoType.RUNNING_PROMO,
            account_payment=oldest_account_payment,
        )

        return render(request, PromoType.RUNNING_PROMO, {'due_date': last_date_payment_promo})


class PromoInfoViewV1(APIView):
    permission_classes = (AllowAny,)
    """
    API to record customer who click the banner
    """

    def get(self, request, customer_id):
        if Customer.objects.get_or_none(pk=customer_id) is None:
            return render(request, '404-promo.html')

        campaign = get_active_collection_hi_season_campaign()

        if not campaign:
            return render(request, '404-promo.html')

        payment_terms = campaign.payment_terms

        start_dpd, _ = get_dpd_from_payment_terms(payment_terms)

        on_click_banner = CollectionHiSeasonCampaignBanner.objects.filter(
            type=CampaignBanner.ON_CLICK, collection_hi_season_campaign=campaign
        ).last()

        if not on_click_banner:
            return render(request, '404-promo.html')

        account = Account.objects.filter(customer_id=customer_id).last()
        if not account:
            return render(request, '404-promo.html')

        exclude_pending_refinancing = campaign.exclude_pending_refinancing

        if exclude_pending_refinancing:
            pending_refinancing = LoanRefinancingRequest.objects.filter(
                status__in=EXCLUDE_PENDING_REFINANCING_STATUS, account=account
            )

            if pending_refinancing:
                return None

        oldest_account_payment = account.get_oldest_unpaid_account_payment()
        if not oldest_account_payment:
            return render(request, '404-promo.html')

        campaign_participant = CollectionHiSeasonCampaignParticipant.objects.filter(
            collection_hi_season_campaign=campaign,
            customer_id=customer_id,
            account_payment=oldest_account_payment,
            is_banner_clicked=True,
            due_date=oldest_account_payment.due_date,
        )

        if not campaign_participant:
            CollectionHiSeasonCampaignParticipant.objects.create(
                collection_hi_season_campaign=campaign,
                customer_id=customer_id,
                account_payment=oldest_account_payment,
                is_banner_clicked=True,
                due_date=oldest_account_payment.due_date,
            )

        payment_terms_date = oldest_account_payment.due_date - relativedelta(
            days=int(start_dpd) * -1
        )
        paid_account_payment_on_campaign = (
            account.accountpayment_set.paid_or_partially_paid()
            .filter(
                paid_date__gte=campaign.campaign_start_period,
                paid_date__lte=campaign.campaign_end_period,
            )
            .order_by('due_date')
            .first()
        )

        if on_click_banner.banner_content:
            template = Template(on_click_banner.banner_content)
            due_date = oldest_account_payment.due_date
            if paid_account_payment_on_campaign:
                due_date = paid_account_payment_on_campaign.due_date
            data = {
                'exact_due_date': due_date,
                'due_date': payment_terms_date,
                'is_paid': bool(paid_account_payment_on_campaign),
                'due_amount': oldest_account_payment.due_amount,
                'announcement_date': campaign.announcement_date,
            }
            context = RequestContext(request, data)
            return HttpResponse(template.render(context))

        elif on_click_banner.banner_url:
            data = {
                'due_date': payment_terms_date,
                'banner': settings.OSS_CAMPAIGN_BASE_URL + on_click_banner.banner_url,
                'blog': on_click_banner.blog_url,
            }
            template = get_template('collection_hi_season/on_click_image_banner.html')
            context = RequestContext(request, data)
            return HttpResponse(template.render(context))


class ReferralCodeLimit(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, referral_code):
        code = referral_code.strip()

        # to define is referral code from offline booth or not
        # handle by experiment setting for referral code active range
        is_offline_booth = is_user_offline_activation_booth(
            code, application_id=None, set_path_tag=None
        )
        if is_offline_booth:
            return success_response_api({'referral_code': code})

        referrer = Customer.objects.filter(self_referral_code=code).first()
        if not referrer:
            current_time = timezone.now()
            if check_promo_code_application_type_exist(code, current_time):
                return success_response_api({'referral_code': code})
            return general_error_response(ReferralCodeMessage.ERROR.WRONG)

        referral_system = ReferralSystem.objects.get(name='PromoReferral')
        if referral_system.referral_bonus_limit:
            if check_referral_code_is_limit(referral_system, referrer):
                return general_error_response(ReferralCodeMessage.ERROR.LIMIT)

        return success_response_api({'referral_code': code})


class ReferralHomeV2(APIView):
    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        return success_response_api(get_referral_data(customer))


class TopReferralCashbacksView(APIView):
    """API to get top referral cashbacks with masked customer names."""

    def get(self, request):
        top_cashbacks = get_top_referral_cashbacks()
        return success_response_api({"top_cashbacks": top_cashbacks})
