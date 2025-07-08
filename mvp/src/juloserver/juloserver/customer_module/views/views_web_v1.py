from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView

from juloserver.account.constants import AccountConstant
from juloserver.account.services.account_related import (
    bad_payment_message,
    get_dpd_and_lock_colour_by_account,
)
from juloserver.account.services.credit_limit import update_credit_limit_with_clcs
from juloserver.apiv2.services import get_eta_time_for_c_score_delay
from juloserver.customer_module.services.view_related import get_limit_card_action
from juloserver.julo.models import CreditScore
from juloserver.julo.services import get_julo_one_is_proven
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.loan.services.views_related import validate_loan_concurrency
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionCategory, TransactionMethod
from juloserver.payment_point.services.views_related import (
    construct_transaction_method_for_android,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)


class CreditInfoView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not application:
            return general_error_response("Application Not Found")

        account = application.account
        is_proven = get_julo_one_is_proven(account)

        limit_message = None

        application_status_code = application.application_status_id
        account_status_code = None if not account else account.status_id
        now = timezone.localtime(timezone.now())
        eta_time = get_eta_time_for_c_score_delay(application, now=now)
        is_delay = now < eta_time
        delay_for_c_score_condition = (
            application.is_julo_one()
            and application_status_code == ApplicationStatusCodes.FORM_PARTIAL
            and is_delay
        )

        if (
            not application.customer.can_reapply
            and application_status_code in ApplicationStatusCodes.in_progress_j1()
        ) or delay_for_c_score_condition:
            limit_message = 'Pengajuan kredit JULO sedang dalam proses'
        dpd_colour, lock_colour = get_dpd_and_lock_colour_by_account(account)
        data = {
            "creditInfo": {
                "fullname": customer.fullname or application.fullname,
                "credit_score": None,
                "set_limit": None,
                "available_limit": None,
                "used_limit": None,
                "is_proven": is_proven,
                "limit_message": limit_message,
                "account_state": account_status_code,
                "dpd_colour": dpd_colour,
            },
            "concurrency": None,
            "concurrency_messages": None,
            "loan_agreement_xid": None,
            "account_id": account.id if account else None,
            "product": [],
        }

        credit_score = CreditScore.objects.filter(application_id=application.id).last()
        if credit_score:
            data["creditInfo"]["credit_score"] = credit_score.score

        if (
            account
            and application.status == ApplicationStatusCodes.LOC_APPROVED
            and account.accountlimit_set.last()
        ):
            account_limit = account.accountlimit_set.last()
            update_credit_limit_with_clcs(application)
            data["creditInfo"].update(
                dict(
                    credit_score=account_limit.latest_credit_score.score or "--",
                    set_limit=account_limit.set_limit,
                    available_limit=account_limit.available_limit,
                    used_limit=account_limit.used_limit,
                )
            )

        if account:
            loan = account.loan_set.last()
            if loan and loan.status in LoanStatusCodes.inactive_status():
                data["loan_agreement_xid"] = loan.loan_xid

        is_concurrency, concurrency_messages = validate_loan_concurrency(account)
        data["concurrency"] = is_concurrency
        data["concurrency_messages"] = concurrency_messages
        bad_payment_block_message = bad_payment_message(account_status_code)
        if (
            bad_payment_block_message
            and account.status_id in AccountConstant.LOCKED_TRANSACTION_STATUS
        ):
            data["block_message"] = bad_payment_block_message

        data["product"] = []

        transaction_methods = TransactionMethod.objects.all().order_by('order_number')[:7]
        for transaction_method in transaction_methods:
            data["product"].append(
                construct_transaction_method_for_android(
                    account, transaction_method, is_proven, lock_colour
                )
            )
        data['product'].append(
            {
                "is_locked": False,
                "is_partner": False,
                "code": TransactionMethodCode.ALL_PRODUCT,
                "name": 'Semua Produk',
                "foreground_icon": '{}foreground_all_products.png'.format(
                    settings.PRODUCTS_STATIC_FILE_PATH
                ),
                "background_icon": None,
                "lock_colour": None,
                "is_new": True,
            }
        )

        data["all_products"] = []
        transaction_categories = TransactionCategory.objects.all().order_by('order_number')
        for transaction_category in transaction_categories:
            product_by_category = dict(category=transaction_category.fe_display_name, product=[])
            transaction_methods = TransactionMethod.objects.filter(
                transaction_category=transaction_category
            ).order_by('order_number')
            for transaction_method in transaction_methods:
                product_by_category['product'].append(
                    construct_transaction_method_for_android(
                        account, transaction_method, is_proven, lock_colour
                    )
                )

            data["all_products"].append(product_by_category)

        data = get_limit_card_action(data)

        return success_response(data)
