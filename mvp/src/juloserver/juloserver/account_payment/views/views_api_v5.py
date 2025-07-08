from datetime import datetime
from django.db.models import Q
from rest_framework.views import APIView

from juloserver.dana_linking.services import (
    is_account_whitelisted_for_dana,
    is_show_dana_linking,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.oneklik_bca.services import (
    is_account_whitelisted_for_oneklik_bca,
    is_show_oneklik_bca,
)
from juloserver.julo.models import GlobalPaymentMethod, PaymentMethod, FeatureSetting
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.services2.payment_method import aggregate_payment_methods
from juloserver.julo.statuses import ApplicationStatusCodes, PaymentStatusCodes
from juloserver.ovo.services.account_services import (
    is_show_ovo_payment_method,
    is_show_ovo_tokenization,
    is_ovo_tokenization_whitelist_feature_active,
)
from juloserver.julo.services2.payment_method import is_hide_mandiri_payment_method
from juloserver.julo.banks import BankCodes
from juloserver.payback.services.gopay import GopayServices
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)
from juloserver.account_payment.services.earning_cashback import get_cashback_drawer
from juloserver.account_payment.models import AccountPayment


class PaymentMethodRetrieveView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, account_id):
        customer = self.request.user.customer
        payment_method_switch_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PAYMENT_METHOD_SWITCH, is_active=True
        ).last()

        if not customer:
            return general_error_response('Customer tidak ditemukan')
        account = customer.account_set.get_or_none(id=account_id)
        if not account:
            return general_error_response('Account tidak ditemukan')

        payment_methods = PaymentMethod.objects.filter(customer=customer, is_shown=True).order_by(
            'sequence'
        )

        if payment_method_switch_fs:
            payment_methods = PaymentMethod.objects.filter(
                Q(customer=customer)
                & (
                    Q(is_shown=True)
                    | Q(
                        payment_method_code__in=[
                            PaymentMethodCodes.BRI,
                            PaymentMethodCodes.BRI_DOKU,
                            PaymentMethodCodes.MANDIRI,
                            PaymentMethodCodes.MANDIRI_DOKU,
                            PaymentMethodCodes.PERMATA,
                            PaymentMethodCodes.PERMATA_DOKU,
                        ]
                    )
                )
            ).order_by('sequence')
            today = datetime.now()
            payment_method_vendors = {
                param['bank']: param['vendor']
                for param in payment_method_switch_fs.parameters['payment_method']
            }
            exclusion_conditions = Q()
            scheduled_banks = {
                s['bank'] for s in payment_method_switch_fs.parameters['schedule_switch']
            }
            all_banks = set(payment_method_vendors.keys()).union(scheduled_banks)

            for bank in all_banks:
                if bank in scheduled_banks:
                    active_schedule = None
                    for schedule in payment_method_switch_fs.parameters['schedule_switch']:
                        if schedule['bank'] == bank:
                            start_date = datetime.strptime(
                                schedule['start_date'], '%Y-%m-%d %H:%M:%S'
                            )
                            end_date = datetime.strptime(schedule['end_date'], '%Y-%m-%d %H:%M:%S')
                            if start_date <= today <= end_date:
                                active_schedule = schedule
                                break

                    if active_schedule:
                        expected_vendor = active_schedule['vendor']
                    else:
                        expected_vendor = payment_method_vendors.get(bank)
                else:
                    expected_vendor = payment_method_vendors.get(bank)

                if expected_vendor:
                    exclusion_conditions |= Q(payment_method_name=bank) & ~Q(vendor=expected_vendor)

            payment_methods = payment_methods.exclude(exclusion_conditions)

        if not is_show_ovo_payment_method(account):
            payment_methods = payment_methods.exclude(payment_method_code=PaymentMethodCodes.OVO)

        if not is_ovo_tokenization_whitelist_feature_active(account):
            payment_methods = payment_methods.exclude(
                payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION
            )

        if is_hide_mandiri_payment_method():
            payment_methods = payment_methods.exclude(bank_code=BankCodes.MANDIRI)

        if not is_account_whitelisted_for_dana(account):
            payment_methods = payment_methods.exclude(payment_method_code=PaymentMethodCodes.DANA)

        if not is_account_whitelisted_for_oneklik_bca(account):
            payment_methods = payment_methods.exclude(
                payment_method_code=PaymentMethodCodes.ONEKLIK_BCA
            )

        application = account.application_set.last()
        if application.application_status_id >= ApplicationStatusCodes.LOC_APPROVED:
            global_payment_methods = GlobalPaymentMethod.objects.all()
        else:
            global_payment_methods = []

        list_method_lookups = aggregate_payment_methods(
            payment_methods,
            global_payment_methods,
            application.bank_name,
            slimline_dict=True,
            is_new_version=True,
            version=5,
        )

        active_payment = AccountPayment.objects.filter(
            account=account, status_id__lt=PaymentStatusCodes.PAID_ON_TIME
        ).exclude(due_amount=0, paid_amount=0)

        return success_response(
            {
                "payment_methods": list_method_lookups,
                "gopay_account_link": GopayServices.is_show_gopay_account_linking(account.id),
                "dana_linking": is_show_dana_linking(account.application_set.last().id),
                "oneklik_account_link": is_show_oneklik_bca(account.application_set.last().id),
                "ovo_account_link": is_show_ovo_tokenization(account.application_set.last().id),
                "forbidden_state": {
                    "account_status": account.status_id,
                    "active_payment_counter": active_payment.count(),
                },
            }
        )


class CashbackDrawerEncouragement(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = self.request.user.customer
        if not customer:
            return general_error_response('Customer tidak ditemukan')

        cashback_drawer = get_cashback_drawer(customer)

        return success_response(cashback_drawer)
