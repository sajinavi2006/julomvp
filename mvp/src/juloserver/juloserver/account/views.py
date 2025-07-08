import json
import jwt
import logging
from builtins import str
from datetime import datetime, timedelta

from django.conf import settings
from babel.dates import format_date
from django.db import transaction
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.http.response import HttpResponseNotAllowed
from django.utils import timezone
from rest_framework.pagination import CursorPagination, _positive_int
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter
from urllib.parse import urlparse, parse_qs

from juloserver.account.constants import (
    ImageSource,
    DpdWarningColorTreshold,
    CheckoutPaymentType,
    UserType,
)
from juloserver.account.serializers import (
    AdditionalCustomerInfoSerializer,
    ImageAccountPaymentSerializer,
    TagihanRevampExperimentSerializer,
)
from juloserver.account.services.account_related import (
    get_detail_cashback_counter_history,
)
from juloserver.account.services.repayment import (
    get_payment_data_payment_method,
    get_payback_services_for_listing,
)
from juloserver.account.services.account_transaction import (
    get_loans,
    get_loans_amount,
    get_payment_list_by_loan,
)
from juloserver.account_payment.models import AccountPayment, CheckoutRequest, CashbackClaim
from juloserver.account_payment.services.account_payment_related import (
    construct_last_checkout_request,
    construct_loan_in_account_payment_list,
    construct_loan_in_account_payment_listv2,
    get_checkout_experience_setting,
    get_checkout_xid_by_paid_off_accout_payment,
    get_image_by_account_payment_id,
    get_late_fee_amount_by_account_payment,
    get_late_fee_amount_by_account_payment_v2,
    get_potential_cashback_by_account_payment,
    get_cashback_new_scheme_banner,
    store_experiment,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    ApplicationNote,
    Customer,
    FaqCheckout,
    Image,
    Loan,
    Payment,
    PaymentMethod,
    FeatureSetting,
    PaymentMethodLookup,
    PaybackTransaction,
    MobileFeatureSetting,
)
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.tasks import upload_image_julo_one
from juloserver.portal.object.loan_app.constants import ImageUploadType
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    not_found_response,
    success_response,
)

from .models import Account, AdditionalCustomerInfo
from juloserver.julo.constants import FeatureNameConst, NewCashbackConst, ExperimentConst
from juloserver.account_payment.services.earning_cashback import (
    get_potential_cashback_by_loan,
    get_cashback_experiment,
    get_paramters_cashback_new_scheme,
)
from juloserver.julo.utils import display_rupiah_no_space
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.julo.services2.payment_method import (
    get_main_payment_method,
    get_payment_method_type,
    get_disable_payment_methods,
)
from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    is_autodebet_feature_disable,
    construct_deactivate_warning,
    is_disabled_autodebet_activation,
)
from juloserver.autodebet.constants import AutodebetStatuses

from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.account_payment.constants import CashbackClaimConst
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.account_payment.services.earning_cashback import make_cashback_available
from juloserver.julo.services2 import encrypt
from rest_framework.permissions import AllowAny

logger = logging.getLogger(__name__)


class CustomCursorPagination(CursorPagination):
    page_size = 20
    max_page_size = 100
    ordering = 'due_date'
    page_size_query_param = 'page_size'
    cursor_query_param = 'next_cursor'

    def get_page_size(self, request):
        if self.page_size_query_param:
            try:
                return _positive_int(
                    request.query_params[self.page_size_query_param],
                    strict=True,
                    cutoff=self.max_page_size,
                )
            except (KeyError, ValueError):
                pass

        return self.page_size

    def get_next_cursor(self):
        next_link = self.get_next_link()
        if next_link:
            parsed_url = urlparse(next_link)
            cursor = parse_qs(parsed_url.query).get(self.cursor_query_param, [None])[0]
            return cursor
        return None

    def get_paginated_response(self, data):
        return Response(
            {
                'success': True,
                'page_size': len(data),
                'next_cursor': self.get_next_cursor(),
                'data': data,
                'errors': [],
            }
        )


class AccountPaymentSummary(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user
        customer = user.customer
        account = Account.objects.filter(customer=customer).last()

        if not account:
            return not_found_response(
                "Account untuk customer id {} tidak ditemukan".format(customer.id)
            )

        user_type = None
        last_application = customer.last_application
        if last_application.is_julo_one_product():
            user_type = UserType.J1
        elif last_application.is_julo_starter():
            user_type = UserType.JTURBO
        elif last_application.is_julover():
            user_type = UserType.JULOVERS

        payment_type = None
        refinancing_param = None
        checkout_content = None
        _, show_payment_method = get_checkout_experience_setting(account.id)
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            account=account, status=CovidRefinancingConst.STATUSES.approved
        ).last()

        if account.is_cashback_new_scheme:
            payment_type = CheckoutPaymentType.CASHBACK
        elif show_payment_method:
            payment_type = CheckoutPaymentType.DEFAULT

        if loan_refinancing_request:
            payment_type = CheckoutPaymentType.REFINANCING
            expired_date = loan_refinancing_request.request_date + timedelta(
                loan_refinancing_request.expire_in_days
            )
            expired_date = format_date(expired_date, 'd MMM yyyy', locale='id_ID')
            checkout_content = {
                'title': 'Bayar {} Dulu, Bisa Dapet Keringanan Cicilan!'.format(
                    display_rupiah_no_space(loan_refinancing_request.prerequisite_amount)
                ),
                'content': 'Aktifkan Programnya sebelum {}'.format(expired_date),
            }
            refinancing_param = {
                'request_id': loan_refinancing_request.id,
                'total_amount': loan_refinancing_request.prerequisite_amount,
                'expired_date': expired_date,
            }

        last_checkout_data = None
        checkout_request = CheckoutRequest.objects.filter(account_id=account).last()
        if checkout_request and checkout_request.checkout_payment_method_id:
            payment_method = PaymentMethod.objects.get_or_none(
                pk=checkout_request.checkout_payment_method_id.id
            )
            is_new_cashback = account.is_eligible_for_cashback_new_scheme
            last_checkout_request = construct_last_checkout_request(
                checkout_request, payment_method, is_new_cashback=is_new_cashback
            )
            last_checkout_data = {
                'checkout_id': last_checkout_request['checkout_id'],
                'status': last_checkout_request['status'].upper(),
            }

        payment_method_data = None
        payment_method = get_main_payment_method(account.customer)
        if payment_method and payment_method.is_shown:
            payment_method_lookup = PaymentMethodLookup.objects.filter(
                name=payment_method.payment_method_name
            ).first()
            order_payment_methods_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
            ).last()

            is_enable_payment_method = True
            payment_method_type = get_payment_method_type(
                payment_method, order_payment_methods_feature
            )
            disable_payment_method_list = get_disable_payment_methods()
            if disable_payment_method_list:
                if payment_method.payment_method_name in disable_payment_method_list:
                    is_enable_payment_method = False

            image_logo_url = ''
            if payment_method_lookup:
                image_logo_url = payment_method_lookup.image_logo_url
            elif payment_method_lookup and payment_method_lookup.image_logo_url_v2:
                image_logo_url = payment_method_lookup.image_logo_url_v2

            payment_method_data = {
                'id': payment_method.id,
                'bank_name': payment_method.payment_method_name,
                'virtual_account': payment_method.virtual_account,
                'type': payment_method_type,
                'image_logo_url': image_logo_url,
                'is_latest_payment_method': payment_method.is_latest_payment_method,
                'is_enable': is_enable_payment_method,
            }

        autodebet_data = None
        deactivate_warning = None
        autodebet_account = get_existing_autodebet_account(account)

        if autodebet_account:
            is_disable_autodebet = is_autodebet_feature_disable(autodebet_account.vendor)

            on_process_type = None
            if autodebet_account.status == AutodebetStatuses.PENDING_REGISTRATION:
                on_process_type = 'ACTIVATION'
            elif autodebet_account.status == AutodebetStatuses.PENDING_REVOCATION:
                on_process_type = 'REVOCATION'

            autodebet_status = None
            if autodebet_account.status == AutodebetStatuses.REGISTERED:
                autodebet_status = 'ACTIVE'
            elif autodebet_account.status in (
                AutodebetStatuses.PENDING_REGISTRATION,
                AutodebetStatuses.PENDING_REVOCATION,
            ):
                autodebet_status = 'PENDING'
            if autodebet_account.is_suspended is True:
                autodebet_status = 'SUSPEND'

            payment_method_lookup = PaymentMethodLookup.objects.filter(
                name__icontains=autodebet_account.vendor
            ).first()

            image_logo_url = ''
            if payment_method_lookup:
                image_logo_url = payment_method_lookup.image_logo_url
            elif payment_method_lookup and payment_method_lookup.image_logo_url_v2:
                image_logo_url = payment_method_lookup.image_logo_url_v2

            deactivate_warning = construct_deactivate_warning(
                autodebet_account, autodebet_account.vendor
            )

            autodebet_data = {
                'bank_name': autodebet_account.vendor,
                'image_logo_url': image_logo_url,
                'status': autodebet_status,
                'on_process_type': on_process_type,
                'is_disable': is_disable_autodebet,
                'is_manual_activation': autodebet_account.is_manual_activation,
            }

        account_payment = account.get_last_unpaid_account_payment()
        is_ptp_active = False
        ptp_date = None
        potential_cashback_amount = 0
        if account_payment:
            if account_payment.dpd < 0:
                is_ptp_active = True
            ptp_date = account_payment.ptp_date
            due_date, percentage_mapping = get_paramters_cashback_new_scheme()
            cashback_parameters = dict(
                is_eligible_new_cashback=account.is_cashback_new_scheme,
                due_date=due_date,
                percentage_mapping=percentage_mapping,
                account_status=account.status_id,
            )
            potential_cashback_amount = get_potential_cashback_by_account_payment(
                account_payment=account_payment,
                cashback_counter=account.cashback_counter,
                cashback_parameters=cashback_parameters,
            )
        ptp_data = {
            'ptp_date': ptp_date,
            'potential_cashback_amount': potential_cashback_amount,
        }

        cashback_banner = None
        if account.is_cashback_new_scheme:
            cashback_banner = get_cashback_new_scheme_banner(account, 2)

        response_data = {
            'info': {
                'payment_type': payment_type,
                'user_type': user_type,
                'account_state': account.status.status_code,
                'bucket_number': account.bucket_number,
                'checkout_content': checkout_content,
                'refinancing_param': refinancing_param,
                'last_checkout_data': last_checkout_data,
                'deactivate_warning': deactivate_warning,
                'is_ptp_active': is_ptp_active,
                'cashback_banner': cashback_banner,
            },
            'payment_method': payment_method_data,
            'autodebit_data': autodebet_data,
            'is_activation_enabled': not is_disabled_autodebet_activation(account),
            'ptp_data': ptp_data,
        }

        return success_response(response_data)


class AccountPaymentListEnhV2(StandardizedExceptionHandlerMixin, APIView):
    filter_backends = [OrderingFilter]
    ordering_fields = ['due_date', 'paid_date']
    ordering = ['due_date']
    pagination_class = CustomCursorPagination

    def get(self, request):
        user = self.request.user
        customer = user.customer

        is_paid_off_account_payment = request.GET.get('is_paid_off', 'false') == 'true'
        account = Account.objects.filter(customer=customer).last()

        if not account:
            return not_found_response(
                "Account untuk customer id {} tidak ditemukan".format(customer.id)
            )

        query_filter = dict(status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
        all_account_payment = AccountPayment.objects.filter(account=account).exclude(
            due_amount=0, paid_amount=0
        )

        if is_paid_off_account_payment:
            account_payment_ids = (
                Payment.objects.filter(account_payment__in=all_account_payment)
                .paid()
                .values_list('account_payment', flat=True)
                .distinct('account_payment_id')
            )
            query_filter = dict(pk__in=account_payment_ids)

        account_payments = all_account_payment.filter(**query_filter)
        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(account_payments, request, view=self)

        results = []
        cashback_counter = account.cashback_counter
        for account_payment in paginated_queryset:
            loans = construct_loan_in_account_payment_listv2(
                account_payment.id, is_paid_off_account_payment
            )

            due_amount = account_payment.due_amount
            cashback = None
            if is_paid_off_account_payment:
                due_amount = account_payment.paid_amount
                cashback_history = get_detail_cashback_counter_history(account_payment.id)
                if cashback_history and cashback_history.get('amount', 0) != 0:
                    cashback = dict(
                        amount=cashback_history.get('amount', 0),
                        streak=cashback_history.get('streak_level', None),
                        percent=cashback_history.get('streak_bonus', None),
                        due_date=None,
                    )
            elif not is_paid_off_account_payment and account.is_cashback_new_scheme:
                due_date, percentage_mapping = get_paramters_cashback_new_scheme()
                cashback_parameters = dict(
                    is_eligible_new_cashback=account.is_cashback_new_scheme,
                    due_date=due_date,
                    percentage_mapping=percentage_mapping,
                    account_status=account.status_id,
                )
                potential_cashback = get_potential_cashback_by_account_payment(
                    account_payment=account_payment,
                    cashback_counter=cashback_counter,
                    cashback_parameters=cashback_parameters,
                )
                if potential_cashback:
                    if cashback_counter < NewCashbackConst.MAX_CASHBACK_COUNTER:
                        cashback_counter += 1
                    percent = percentage_mapping.get(str(cashback_counter))
                    cashback = dict(
                        amount=potential_cashback,
                        streak=cashback_counter,
                        percent=percent,
                        due_date=account_payment.due_date - timedelta(days=abs(due_date)),
                    )
                else:
                    cashback_counter = 0

            late_fee = None
            current, potential, late_due = get_late_fee_amount_by_account_payment_v2(
                account_payment=account_payment,
                is_paid_off_account_payment=False,
            )
            if current or potential:
                late_fee = dict(potential=potential, current=current, late_due_date=late_due)

            results.append(
                dict(
                    account_payment_id=account_payment.id,
                    due_status=account_payment.due_statusv2(),
                    due_amount=due_amount,
                    due_date=account_payment.due_date,
                    dpd=account_payment.dpd,
                    paid_date=account_payment.paid_date,
                    loans=loans,
                    cashback=cashback,
                    late_fee=late_fee,
                )
            )

        return paginator.get_paginated_response(results)


class AccountPaymentList(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user
        customer = user.customer

        last_application = customer.last_application
        account_payments_data = {
            'server_date': timezone.localtime(timezone.now()).date(),
            'has_history': False,
            'is_julover': last_application.is_julover() if last_application else False,
        }

        is_paid_off_account_payment = request.GET.get('is_paid_off_account_payment', False)
        is_paid_off_account_payment = is_paid_off_account_payment == 'true'
        account = Account.objects.filter(customer=customer).last()
        if not account:
            return success_response(account_payments_data)
        query_filter = dict(status_id__lt=PaymentStatusCodes.PAID_ON_TIME)

        all_account_payment = AccountPayment.objects.filter(account=account).exclude(
            due_amount=0, paid_amount=0
        )

        if is_paid_off_account_payment:
            account_payment_ids = (
                Payment.objects.filter(account_payment__in=all_account_payment)
                .paid()
                .values_list('account_payment', flat=True)
                .distinct('account_payment_id')
            )
            query_filter = dict(pk__in=account_payment_ids)

        account_payments = all_account_payment.filter(**query_filter).order_by('due_date')

        account_payments_data['has_history'] = bool(all_account_payment)
        account_payments_list = []
        cashback_counter = account.cashback_counter or 0
        due_date, percentage_mapping = get_paramters_cashback_new_scheme()
        cashback_parameters = dict(
            is_eligible_new_cashback=account.is_cashback_new_scheme,
            due_date=due_date,
            percentage_mapping=percentage_mapping,
            account_status=account.status_id,
        )
        for account_payment in account_payments:
            loan_ids = account_payment.payment_set.distinct('loan_id').values_list(
                'loan_id', flat=True
            )
            image = get_image_by_account_payment_id(account_payment.id)
            image_url = image.image_url if image and image.image_url else None
            loans = construct_loan_in_account_payment_list(
                account_payment.id, is_paid_off_account_payment
            )
            total_installment = 0
            if loan_ids:
                total_installment = (
                    Loan.objects.filter(pk__in=loan_ids)
                    .aggregate(total_installment=Sum('installment_amount'))
                    .get('total_installment')
                )
            due_amount = account_payment.due_amount
            # for transction history
            cashback = None
            if is_paid_off_account_payment:
                due_amount = account_payment.paid_amount
                cashback = get_detail_cashback_counter_history(account_payment.id)

            # calculate potential cashback for checkout experience
            potential_cashback = get_potential_cashback_by_account_payment(
                account_payment=account_payment,
                cashback_counter=cashback_counter,
                cashback_parameters=cashback_parameters,
            )
            if potential_cashback:
                if cashback_counter < NewCashbackConst.MAX_CASHBACK_COUNTER:
                    cashback_counter += 1
            else:
                cashback_counter = 0
            # calculate late fee amount for checkout experience
            late_fee_amount, grace_period = get_late_fee_amount_by_account_payment(
                account_payment=account_payment,
                is_paid_off_account_payment=is_paid_off_account_payment,
            )
            checkout_xid = get_checkout_xid_by_paid_off_accout_payment(
                is_paid_off_account_payment=is_paid_off_account_payment,
                account_payment=account_payment,
            )

            account_payments_list.append(
                dict(
                    due_status=account_payment.due_status(False),
                    due_amount=due_amount,
                    due_date=account_payment.due_date,
                    paid_date=account_payment.paid_date,
                    loans=list(loans),
                    image_url=image_url,
                    account_payment_id=account_payment.id,
                    total_loan_installment=total_installment,
                    cashback_amount=potential_cashback,
                    late_fee=late_fee_amount,
                    remaining_installment_amount=account_payment.remaining_installment_amount(),
                    checkout_xid=checkout_xid,
                    grace_period=grace_period,
                    cashback=cashback,
                )
            )

        total_potential_cashback = 0
        active_loans = Loan.objects.filter(
            account=account,
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lte=LoanStatusCodes.LOAN_4DPD,
            is_restructured=False,
        )
        if active_loans:
            for loan in active_loans.iterator():
                potential_cashback = get_potential_cashback_by_loan(loan)
                total_potential_cashback += potential_cashback
        account_payments_data['potential_cashback'] = dict(total_amount=total_potential_cashback)

        if not is_paid_off_account_payment and account_payments:
            today = timezone.localtime(timezone.now()).date()

            account_payments_due = account_payments.filter(due_date__lte=today).order_by('due_date')

            oldest_account_payment = account_payments.first()
            dpd = oldest_account_payment.due_late_days
            due_amount = oldest_account_payment.due_amount
            if account_payments_due:
                due_amount = account_payments_due.aggregate(due_amount=Sum('due_amount')).get(
                    'due_amount'
                )
                oldest_account_payment = account_payments_due.first()
                dpd = oldest_account_payment.due_late_days
            due_date = oldest_account_payment.due_date
            due_status = oldest_account_payment.due_status()

            account_payments_data['account_payments_information'] = dict(
                dpd=abs(dpd), due_status=due_status, due_amount=due_amount, due_date=due_date
            )

        if account_payments_list:
            account_payments_data['account_payments_list'] = account_payments_list

        return success_response(account_payments_data)


class AccountPaymentDpd(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        payment_widget = dict()
        user = self.request.user
        account = user.customer.account

        account_payments_data = {
            'total_loan_amount': 0,
            'due_date': None,
            'dpd': None,
            'dpd_warning_threshold': DpdWarningColorTreshold.DEFAULT,
            'cashback_counter': None,
            'card': {},
        }

        if not account:
            return not_found_response(account_payments_data)

        today = timezone.localtime(timezone.now()).date()
        account_payments = (
            AccountPayment.objects.not_paid_active().filter(account=account).order_by('due_date')
        )

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DPD_WARNING_COLOR_TRESHOLD,
            is_active=True,
        ).last()

        if feature_setting:
            dpd_warning_threshold = feature_setting.parameters.get('dpd_warning_color_treshold')

        if account_payments:
            account_payments_due = account_payments.filter(due_date__lte=today).order_by('due_date')

            oldest_account_payment = account_payments.first()
            dpd = oldest_account_payment.due_late_days
            due_amount = oldest_account_payment.due_amount
            if account_payments_due:
                due_amount = account_payments_due.aggregate(due_amount=Sum('due_amount')).get(
                    'due_amount'
                )
                oldest_account_payment = account_payments_due.first()
                dpd = oldest_account_payment.due_late_days
            due_date = oldest_account_payment.due_date
            cashback_counter = None
            if get_cashback_experiment(account.id):
                cashback_counter = account.cashback_counter

            card = StreamlinedCommunication.objects.filter(
                Q(
                    communication_platform=CommunicationPlatform.PAYMENT_WIDGET,
                    dpd_upper__lte=dpd,
                    dpd_lower__gte=dpd,
                    is_active=True,
                )
                | Q(
                    communication_platform=CommunicationPlatform.PAYMENT_WIDGET,
                    dpd_upper=None,
                    dpd_lower__gte=dpd,
                    is_active=True,
                )
                | Q(
                    communication_platform=CommunicationPlatform.PAYMENT_WIDGET,
                    dpd_upper__lte=dpd,
                    until_paid=True,
                    is_active=True,
                )
            ).last()

            if card:
                if card.payment_widget_properties:
                    card_props = card.payment_widget_properties
                    payment_widget = dict(
                        type=card_props['type'],
                        streamlined_communication_id=card.id,
                        title=None,
                        image_icn=None,
                        dpd_props=dict(
                            content_card_colour=card_props['card_colour'],
                            content_text_colour=card_props['card_text_colour'],
                            content_icon=card_props['info_imcard_image'],
                            info_card_colour=card_props['info_colour'],
                            info_text_colour=card_props['info_text_colour'],
                            info_text=card_props['info_text']
                            if account.is_julo_one_account()
                            else None,
                            info_icon=card_props['info_image'],
                            is_active=card.is_active,
                        ),
                        content=None,
                        button=None,
                        border=None,
                        background_img=None,
                        card_action_type=None,
                        card_action_destination=None,
                        youtube_video_id=None,
                    )
            account_payments_data = dict(
                dpd=dpd,
                total_loan_amount=due_amount,
                due_date=due_date,
                dpd_warning_threshold=dpd_warning_threshold,
                cashback_counter=cashback_counter,
                card=payment_widget,
            )

            if dpd >= -2:
                order_payment_methods_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
                ).last()
                parameters = order_payment_methods_feature.parameters

                payment_method = get_main_payment_method(account.customer)

                if payment_method and payment_method.is_shown:
                    if not payment_method.payment_method_name.lower() in parameters.get(
                        'e_wallet_group'
                    ):
                        payment_method_data = PaymentMethodLookup.objects.filter(
                            name=payment_method.payment_method_name
                        ).first()
                        account_payments_data['payment_method'] = {
                            'bank_name': payment_method.payment_method_name,
                            'virtual_account': payment_method.virtual_account,
                            'image_logo_url': payment_method_data.image_logo_url,
                            'type': 'Virtual Account' if payment_method.bank_code else 'Retail',
                        }

        return success_response(account_payments_data)


class ImageAccountPayment(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ImageAccountPaymentSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        image = Image()
        image_source = data['account_payment_id']
        upload = data['upload']

        image.image_type = ImageUploadType.LATEST_PAYMENT_PROOF

        image.image_source = int(image_source)

        account_payment = AccountPayment.objects.get_or_none(pk=image.image_source)
        if not account_payment:
            return general_error_response(
                "Account payment dengna id={} tidak ditemukan".format(image.image_source)
            )

        if user.id != account_payment.account.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        image.save()
        image.image.save(image.full_image_name(upload.name), upload)

        upload_image_julo_one.apply_async(
            (image.id, True, ImageSource.ACCOUNT_PAYMENT), countdown=3
        )

        return success_response({'id': str(image.id)})


class AccountLoansView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        try:
            results = get_loans(request)

            return success_response(results)
        except Exception as e:
            return general_error_response(str(e))


class AccountLoansAmountView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        try:
            result = get_loans_amount(request)

            return success_response({"total_amount": result})
        except Exception as e:
            return general_error_response(str(e))


def get_additional_address(request, customer_id):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    customer = Customer.objects.get_or_none(pk=customer_id)
    user = request.user

    if not customer:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['customer tidak ditemukan']}
        )

    if user.id != customer.user_id:
        return JsonResponse(
            {'success': False, 'data': {'user_id': user.id}, 'errors': ['User not allowed']}
        )

    additional_customer_info = AdditionalCustomerInfo.objects.filter(customer=customer).values(
        'id',
        'additional_customer_info_type',
        'customer',
        'street_number',
        'provinsi',
        'kabupaten',
        'kecamatan',
        'kelurahan',
        'kode_pos',
        'home_status',
        'latest_updated_by__username',
        'additional_address_number',
        'occupied_since',
    )

    return JsonResponse({'success': True, 'data': list(additional_customer_info), 'errors': []})


def store_additional_address(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = json.loads(request.body)
    customer = Customer.objects.get_or_none(pk=int(data['customer_id']))

    if not customer:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['Customer tidak ditemukan']}
        )
    additional_address_info = AdditionalCustomerInfo.objects.filter(customer=customer)

    if len(additional_address_info) >= 3:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['Maksimal menyimpan 3 data']}
        )
    application = Application.objects.get_or_none(pk=int(data['application_id']))

    if not application:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['application tidak ditemukan']}
        )

    user = request.user

    if user.id != customer.user_id:
        return JsonResponse(
            {'success': False, 'data': {'user_id': user.id}, 'errors': ['User not allowed']}
        )

    data['occupied_since'] = datetime.strptime(data['occupied_since'], '%d-%m-%Y').date()
    data['customer'] = customer.id
    data['latest_updated_by'] = user.id
    data['latest_action'] = 'Add'
    data['additional_customer_info_type'] = 'address'
    serializer = AdditionalCustomerInfoSerializer(data=data)
    serializer.is_valid(raise_exception=True)

    try:
        with transaction.atomic(using='onboarding_db'):
            serializer.save()
            ApplicationNote.objects.create(
                application_id=application.id,
                added_by_id=user.id,
                note_text='menambahkan alamat baru ke #{}'.format(
                    serializer.data['additional_address_number']
                ),
            )
    except JuloException as je:
        return JsonResponse({'success': False, 'data': None, 'errors': [str(je)]})
    return JsonResponse({'success': True, 'data': serializer.data, 'errors': []})


def update_additional_address(request, pk):
    if request.method != 'PATCH':
        return HttpResponseNotAllowed(["PATCH"])

    data = json.loads(request.body)
    data['occupied_since'] = datetime.strptime(data['occupied_since'], '%d-%m-%Y').date()
    data['latest_action'] = 'Edit'
    additional_customer_info = AdditionalCustomerInfo.objects.filter(pk=pk).last()
    if not additional_customer_info:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['Data customer tidak ditemukan']}
        )
    user = request.user
    application = Application.objects.get_or_none(pk=int(data['application_id']))
    if not application:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['application tidak ditemukan']}
        )

    if user.id != application.customer.user_id:
        return JsonResponse(
            {'success': False, 'data': {'user_id': user.id}, 'errors': ['User not allowed']}
        )

    serializer = AdditionalCustomerInfoSerializer(additional_customer_info, data=data, partial=True)
    serializer.is_valid(raise_exception=True)
    try:
        with transaction.atomic(using='onboarding_db'):
            serializer.save()
            ApplicationNote.objects.create(
                application_id=application.id,
                added_by_id=user.id,
                note_text='mengubah alamat baru ke #{}'.format(
                    serializer.data['additional_address_number']
                ),
            )
    except JuloException as je:
        return JsonResponse({'success': False, 'data': None, 'errors': [str(je)]})
    return JsonResponse({'success': True, 'data': serializer.data, 'errors': []})


def delete_additional_address(request, pk):
    user = request.user

    if request.method != 'DELETE':
        return HttpResponseNotAllowed(["DELETE"])

    data = json.loads(request.body)
    additional_customer_info = AdditionalCustomerInfo.objects.filter(pk=pk).last()
    if not additional_customer_info:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['Data customer tidak ditemukan']}
        )
    application = Application.objects.get_or_none(pk=int(data['application_id']))

    if not application:
        return JsonResponse(
            {'success': False, 'data': None, 'errors': ['application tidak ditemukan']}
        )

    if user.id != application.customer.user_id:
        return JsonResponse(
            {'success': False, 'data': {'user_id': user.id}, 'errors': ['User not allowed']}
        )

    additional_address_number = additional_customer_info.additional_address_number

    with transaction.atomic(using='onboarding_db'):
        additional_customer_info.delete()
        ApplicationNote.objects.create(
            application_id=application.id,
            added_by_id=user.id,
            note_text='menghapus alamat baru ke #{}'.format(additional_address_number),
        )
    return JsonResponse({'success': True, 'data': None, 'errors': []})


class ActivePaymentCheckout(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user
        customer = user.customer
        account = Account.objects.filter(customer=customer).last()
        if not account:
            return not_found_response('Account tidak ditemukan')
        timenow = timezone.localtime(timezone.now())
        show_button, show_payment_method = get_checkout_experience_setting(account.id)
        is_new_cashback = account.is_eligible_for_cashback_new_scheme
        response_data = {
            'is_feature_button_active': show_button,
            'is_feature_payment_active': show_payment_method,
            'server_date': timenow,
            'last_checkout_data': None,
            'is_new_cashback_active': account.is_cashback_new_scheme,
            'current_streak_level': account.cashback_counter,
            'cashback_banner': None,
        }
        checkout_request = CheckoutRequest.objects.filter(account_id=account).last()
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            account=account, status=CovidRefinancingConst.STATUSES.approved
        ).last()

        if response_data['is_new_cashback_active']:
            response_data['payment_type'] = CheckoutPaymentType.CASHBACK
        elif response_data['is_feature_payment_active']:
            response_data['payment_type'] = CheckoutPaymentType.DEFAULT
        else:
            response_data['payment_type'] = None

        if loan_refinancing_request:
            response_data['payment_type'] = CheckoutPaymentType.REFINANCING
            expired_date = loan_refinancing_request.request_date + timedelta(
                loan_refinancing_request.expire_in_days
            )
            expired_date = format_date(expired_date, 'd MMM yyyy', locale='id_ID')
            response_data['checkout_content'] = {
                'title': 'Bayar {} Dulu, Bisa Dapet Keringanan Cicilan!'.format(
                    display_rupiah_no_space(loan_refinancing_request.prerequisite_amount)
                ),
                'content': 'Aktifkan Programnya sebelum {}'.format(expired_date),
            }
            response_data['refinancing_param'] = {
                'request_id': loan_refinancing_request.id,
                'total_amount': loan_refinancing_request.prerequisite_amount,
                'expired_date': expired_date,
            }
        # handle cashback new scheme banner
        if account.is_cashback_new_scheme:
            response_data['cashback_banner'] = get_cashback_new_scheme_banner(account)

        if not checkout_request:
            return success_response(response_data)
        payment_method = None
        if checkout_request.checkout_payment_method_id:
            payment_method = PaymentMethod.objects.get_or_none(
                pk=checkout_request.checkout_payment_method_id.id
            )
            if not payment_method:
                return not_found_response('Payment method tidak ditemukan')
        last_checkout_request = construct_last_checkout_request(
            checkout_request, payment_method, is_new_cashback=is_new_cashback
        )
        response_data['last_checkout_data'] = last_checkout_request

        return success_response(response_data)


class FAQCheckoutList(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        faq_checkout = FaqCheckout.objects.all().filter(visible=True)
        if not faq_checkout:
            return not_found_response('Checkout FAQ not found')

        response_data = []
        for item in faq_checkout:
            data = {'title': item.title, 'content': item.description}
            response_data.append(data)

        return success_response(response_data)


class ZendeskJwtTokenGenerator(APIView):
    def get(self, request, *args, **kwargs):
        payload = {
            "name": request.user.customer.fullname,
            "email": request.user.customer.email,
            "external_id": str(request.user.customer.pk),
            "exp": int((datetime.now() + timedelta(hours=1, minutes=30)).timestamp()),
            "scope": "user",
        }
        token = jwt.encode(
            payload,
            settings.ZENDESK_SECRET_KEY,
            algorithm="HS256",
            headers={"alg": "HS256", "typ": "JWT", 'kid': settings.ZENDESK_KEY_ID},
        )
        data = {"token": token.decode("utf-8")}
        return success_response(data)


class AccountPaymentListV2(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user
        customer = user.customer

        account = Account.objects.filter(customer=customer).last()
        if not account:
            return not_found_response(
                "Account untuk customer id {} tidak ditemukan".format(customer.id)
            )

        if not account.is_cashback_new_scheme:
            return general_error_response(
                "Account id {} tidak terdaftar sebagai cashback new scheme".format(account.id)
            )

        all_account_payment = (
            AccountPayment.objects.filter(
                status_id__lt=PaymentStatusCodes.PAID_ON_TIME, account=account
            )
            .exclude(due_amount=0)
            .order_by('due_date')
        )

        if not all_account_payment.exists():
            return general_error_response(
                "Account id {} tidak mempunyai tagihan".format(account.id)
            )
        due_date, percentage_mapping = get_paramters_cashback_new_scheme()
        cashback_parameters = dict(
            is_eligible_new_cashback=account.is_cashback_new_scheme,
            due_date=due_date,
            percentage_mapping=percentage_mapping,
            account_status=account.status_id,
        )
        account_payments_data = []
        cashback_counter = account.cashback_counter
        for account_payment in all_account_payment:
            account_payment_dict = dict(
                id=account_payment.id,
                account_payment_deadline=account_payment.dpd,
                due_status=account_payment.due_status(False),
                due_amount=account_payment.remaining_installment_amount(),
                due_date=account_payment.due_date,
                cashback=None,
                late=None,
            )
            late_fee_amount, grace_period = get_late_fee_amount_by_account_payment(
                account_payment=account_payment,
                is_paid_off_account_payment=False,
            )
            potential_cashback = get_potential_cashback_by_account_payment(
                account_payment=account_payment,
                cashback_counter=cashback_counter,
                cashback_parameters=cashback_parameters,
            )
            if late_fee_amount:
                account_payment_dict.update(
                    late=dict(amount=late_fee_amount, grace_period=grace_period)
                )
            if potential_cashback:
                if cashback_counter < NewCashbackConst.MAX_CASHBACK_COUNTER:
                    cashback_counter += 1
                account_payment_dict.update(
                    cashback=dict(
                        streak_level=cashback_counter,
                        amount=potential_cashback,
                        deadline_date=account_payment.due_date - timedelta(days=abs(due_date)),
                    )
                )
            else:
                cashback_counter = 0
            account_payments_data.append(account_payment_dict)

        return success_response(account_payments_data)


class PotentialCashbackList(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        active_loans = Loan.objects.filter(
            account=account,
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lte=LoanStatusCodes.LOAN_4DPD,
            is_restructured=False,
        )
        potential_cashback_list = []
        if not active_loans:
            return success_response(potential_cashback_list)

        for loan in active_loans.iterator():
            if not loan.transaction_method:
                continue
            potential_cashback = get_potential_cashback_by_loan(loan)
            if potential_cashback:
                potential_cashback_list.append(
                    dict(
                        loan_date=timezone.localtime(loan.sphp_accepted_ts),
                        cashback_amount=potential_cashback,
                        product=dict(
                            name=loan.transaction_method.fe_display_name,
                            icon=loan.transaction_method.foreground_icon_url,
                        )
                    )
                )

        return success_response(potential_cashback_list)


class ChatBotTokenGenerator(APIView):
    def get(self, request, *args, **kwargs):
        user = request.user
        if not hasattr(user, "customer"):
            return general_error_response("User has no customer")
        token = str(request.user.customer.pk) + "_" + str(request.user.customer.customer_xid)
        return success_response({"token": token})


class TagihanRevampExperimentView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = TagihanRevampExperimentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = request.user.customer
        store_experiment(ExperimentConst.TAGIHAN_REVAMP_EXPERIMENT, customer.id, data['group'])

        return success_response({"message": "Data has been processed"})


class PaymentListView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, loan_xid):
        try:
            customer = request.user.customer
            if not customer:
                return general_error_response('Customer tidak ditemukan')

            results = get_payment_list_by_loan(customer, loan_xid)

            return success_response(results)
        except Exception as e:
            return general_error_response(str(e))


class PaybackTransactionList(StandardizedExceptionHandlerMixin, APIView):
    filter_backends = [OrderingFilter]
    ordering_fields = ['order_date']
    ordering = ['-order_date']
    pagination_class = CustomCursorPagination

    def get(self, request):
        user = self.request.user
        customer = user.customer

        payback_service_list = get_payback_services_for_listing()

        if not payback_service_list:
            logger.error(
                {'action': 'get_payback_services_for_listing', 'errors': "cannot find payback list"}
            )
            return general_error_response("Riwayat gagal ditampilkan")

        _filter = {
            "customer": customer,
            "is_processed": True,
            "payback_service__in": payback_service_list,
        }

        paybacks = PaybackTransaction.objects.annotate(
            order_date=Coalesce('transaction_date', 'udate')
        ).filter(**_filter)

        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(paybacks, request, view=self)

        results = []
        for payback in paginated_queryset:
            payback_result = {
                "amount": payback.amount,
                "status": "SUCCESS",
                "date": timezone.localtime(payback.order_date).strftime('%Y-%m-%dT%H:%M:%S+07:00'),
                "payback_id": payback.id,
            }

            results.append(payback_result)

        return paginator.get_paginated_response(results)


class PaybackTransactionDetail(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, payback_id):
        user = self.request.user
        customer = user.customer

        payback_service_list = get_payback_services_for_listing()

        if not payback_service_list:
            logger.error(
                {'action': 'get_payback_services_for_listing', 'errors': "cannot find payback list"}
            )
            return general_error_response("Riwayat gagal ditampilkan")

        _filter = {
            "customer": customer,
            "is_processed": True,
            "payback_service__in": payback_service_list,
            "id": payback_id,
        }

        payback = (
            PaybackTransaction.objects.annotate(order_date=Coalesce('transaction_date', 'udate'))
            .filter(**_filter)
            .last()
        )

        if not payback:
            return not_found_response("Payback tidak ditemukan")

        payback_result = {
            "amount": payback.amount,
            "status": "SUCCESS",
            "date": timezone.localtime(payback.order_date).strftime('%Y-%m-%dT%H:%M:%S+07:00'),
        }

        payback_result["payback_data"] = get_payment_data_payment_method(payback)

        return success_response(payback_result)


class CashbackClaimCheck(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        account_id_encrypted = self.request.query_params.get('token', '')
        encryptor = encrypt()
        decoded_account_id = encryptor.decode_string(account_id_encrypted)
        account = Account.objects.filter(pk=decoded_account_id).last()
        if not decoded_account_id or not account:
            return not_found_response('Account id tidak ditemukan')

        last_cashback_claim = CashbackClaim.objects.filter(
            account_id=account.id,
        ).last()
        if not last_cashback_claim:
            return not_found_response('Account in tidak mempunyai cashback untuk di klaim')

        last_cashback_claim_payment = last_cashback_claim.cashbackclaimpayment_set.last()
        payment = Payment.objects.filter(pk=last_cashback_claim_payment.payment_id).last()
        fs = MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.BOTTOMSHEET_CONTENT_CASHBACK_CLAIM, is_active=True
        ).last()
        if not fs:
            return not_found_response('bottomsheet tidak ditemukan')
        bottomsheet_dict = fs.parameters
        status = last_cashback_claim.status
        cashback_amount = last_cashback_claim.total_cashback_amount
        bottomsheet = {}

        if status == CashbackClaimConst.STATUS_ELIGIBLE:
            bottomsheet = bottomsheet_dict.get('cashback_claim_congrats', {})
            if "description_warn" in bottomsheet:
                bottomsheet["description_warn"] = bottomsheet["description_warn"].replace(
                    "{{cashback_amount}}", str(cashback_amount)
                )
        elif status == CashbackClaimConst.STATUS_CLAIMED:
            bottomsheet = bottomsheet_dict.get('cashback_claim_claimed', {})
            if "description" in bottomsheet:
                bottomsheet["description"] = bottomsheet["description"].replace(
                    "{{cashback_amount}}", str(cashback_amount)
                )
        elif status in [
            CashbackClaimConst.STATUS_EXPIRED,
            CashbackClaimConst.STATUS_VOID,
            CashbackClaimConst.STATUS_VOID_CLAIM,
        ]:
            bottomsheet = bottomsheet_dict.get('cashback_claim_expired', {})
        if not bottomsheet:
            return not_found_response('bottomsheet tidak ditemukan')

        response_data = {
            'cashback_status': status,
            'cashback_amount': last_cashback_claim.total_cashback_amount,
            'last_payment_id': payment.account_payment.id,
            'bottomsheet': bottomsheet,
        }

        return success_response(response_data)


class CashbackClaimInfoCard(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        account_id_encrypted = self.request.data['token']
        encryptor = encrypt()
        decoded_account_id = encryptor.decode_string(account_id_encrypted)
        account = Account.objects.filter(pk=decoded_account_id).last()
        if not decoded_account_id or not account:
            return not_found_response('Account id tidak ditemukan')

        cashback_claim = CashbackClaim.objects.filter(
            account_id=account.id,
            status=CashbackClaimConst.STATUS_ELIGIBLE,
        ).last()
        if not cashback_claim:
            return not_found_response('Account ini tidak mempunyai cashback untuk di klaim')

        with transaction.atomic():
            cashback_claim.update_safely(status=CashbackClaimConst.STATUS_CLAIMED)
            eligible_cashback_payments = cashback_claim.cashbackclaimpayment_set.filter(
                status=CashbackClaimConst.STATUS_ELIGIBLE
            )
            cashback_payment_ids = []
            for eligible_cashback_payment in eligible_cashback_payments:
                payment = (
                    Payment.objects.paid().filter(id=eligible_cashback_payment.payment_id).last()
                )
                if not payment:
                    logger.info(
                        {
                            'action': 'claim_elibigle_cashback',
                            'account_id': account.id,
                            'payment_id': eligible_cashback_payment.payment_id,
                            'message': 'payment not found',
                        }
                    )
                    continue

                payment.cashback_earned += eligible_cashback_payment.cashback_amount
                payment.loan.customer.change_wallet_balance(
                    change_accruing=eligible_cashback_payment.cashback_amount,
                    change_available=0,
                    reason=CashbackChangeReason.PAYMENT_ON_TIME,
                    payment=payment,
                    account_payment=payment.account_payment,
                    # is_eligible_new_cashback=is_eligible_new_cashback,
                    # counter=counter,
                    # new_cashback_percentage=new_cashback_percentage,
                )
                payment.update_safely(cashback_earned=payment.cashback_earned)
                eligible_cashback_payment.update_safely(status=CashbackClaimConst.STATUS_CLAIMED)
                cashback_payment_ids.append(eligible_cashback_payment.payment_id)

            if cashback_payment_ids:
                loans = Loan.objects.select_for_update().filter(
                    id__in=Payment.objects.paid()
                    .filter(id__in=cashback_payment_ids)
                    .values_list('loan_id', flat=True)
                    .distinct(),
                    loan_status_id=LoanStatusCodes.PAID_OFF,
                )
                for loan in loans:
                    make_cashback_available(loan)

        fs = MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.BOTTOMSHEET_CONTENT_CASHBACK_CLAIM, is_active=True
        ).last()
        if not fs:
            return not_found_response('bottomsheet tidak ditemukan')

        bottomsheet_dict = fs.parameters
        bottomsheet = bottomsheet_dict.get('cashback_claim_success', {})
        if "description" in bottomsheet:
            bottomsheet["description"] = bottomsheet["description"].replace(
                "{{cashback_amount}}", str(cashback_claim.total_cashback_amount)
            )
        response_data = {
            'bottomSheet': bottomsheet,
        }

        return success_response(response_data)
