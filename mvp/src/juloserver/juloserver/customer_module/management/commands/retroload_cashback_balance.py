import time
from builtins import str

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from juloserver.account.constants import AccountConstant
from juloserver.customer_module.constants import CashbackBalanceStatusConstant
from juloserver.customer_module.models import CashbackBalance, CashbackStatusHistory
from juloserver.julo.constants import ApplicationStatusCodes as Status
from juloserver.julo.constants import ProductLineCodes
from juloserver.julo.models import Application, CustomerWalletHistory

MAX_QUERY_LIMIT = 1000
SLEEP_INTERVAL = 2


class Command(BaseCommand):
    help = "Retroloads cashback balance table limited by 1000 per excecution"

    def handle(self, *args, **options):
        while Application.objects.filter(
            (Q(application_status_id=190) & Q(product_line_id__in=ProductLineCodes.julo_one()))
            | (
                Q(application_status_id=Status.FUND_DISBURSAL_SUCCESSFUL)
                & Q(product_line_id__in=ProductLineCodes.mtl())
            )
        ).exclude(customer_id__in=CashbackBalance.objects.all().values_list('customer', flat=True)):
            try:
                with transaction.atomic():
                    applications = (
                        Application.objects.filter(
                            (
                                Q(application_status_id=190)
                                & Q(product_line_id__in=ProductLineCodes.julo_one())
                            )
                            | (
                                Q(application_status_id=Status.FUND_DISBURSAL_SUCCESSFUL)
                                & Q(product_line_id__in=ProductLineCodes.mtl())
                            )
                        )
                        .exclude(
                            customer_id__in=CashbackBalance.objects.all().values_list(
                                'customer', flat=True
                            )
                        )
                        .order_by('-cdate')
                        .select_related('customer')[:MAX_QUERY_LIMIT]
                    )
                    cashback_status_history_data = []
                    for application in applications:
                        customer = application.customer
                        cashback_balance = CashbackBalance.objects.filter(customer=customer).last()
                        if cashback_balance:
                            continue
                        status = CashbackBalanceStatusConstant.UNFREEZE
                        account = customer.account_set.last()
                        if (
                            account
                            and account.status.status_code == AccountConstant.STATUS_CODE.suspended
                        ):
                            status = CashbackBalanceStatusConstant.FREEZE
                        else:
                            loan = customer.loan_set.get_queryset().all_active_mtl().last()
                            if loan:
                                oldest_unpaid_payment = loan.get_oldest_unpaid_payment()
                                if (
                                    oldest_unpaid_payment
                                    and oldest_unpaid_payment.due_late_days >= 5
                                ):
                                    status = CashbackBalanceStatusConstant.FREEZE

                        cashback_balance = CashbackBalance.objects.create(
                            status=status,
                            customer=customer,
                            cashback_balance=customer.wallet_balance_available,
                            cashback_accruing=customer.wallet_balance_accruing,
                        )
                        cashback_status_history_data.append(
                            CashbackStatusHistory(
                                cashback_balance=cashback_balance,
                                status_new=cashback_balance.status,
                            )
                        )
                        CustomerWalletHistory.objects.filter(customer=customer).update(
                            cashback_balance=cashback_balance
                        )
                    CashbackStatusHistory.objects.bulk_create(cashback_status_history_data)
            except Exception as e:
                self.stdout.write(self.style.ERROR(str(e)))
            time.sleep(SLEEP_INTERVAL)
        self.stdout.write(self.style.SUCCESS('=========Finish========='))
