import urllib.request
import csv

from django.core.management.base import BaseCommand
from juloserver.early_limit_release.models import ReleaseTracking, EarlyReleaseLoanMapping
from juloserver.early_limit_release.constants import (
    ReleaseTrackingType,
    EarlyLimitReleaseMoengageStatus,
)
from juloserver.account.models import AccountLimit
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.loan.services.lender_related import logger
from juloserver.loan.models import Loan
from juloserver.julo.statuses import LoanStatusCodes
from django.db.models import Sum
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_early_limit_release,
)


class Command(BaseCommand):
    help = """
        Execute early limit release for a list of loans that we prepare in advance
        The format csv must be: loan_id, payment_id, limit_release_amount, account_id
        Command: python manage.py execute_early_limit_one_time csv_path
        csv_path is a path to a CSV file.
    """

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to CSV file")

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        early_limit_data = self.get_early_limit_release_from_csv(csv_path)
        list_negative = []
        list_loan_failed = []
        list_loan_x250 = []
        list_existed = []
        list_loans_auto = []
        list_over_amount = []

        self.stdout.write(self.style.SUCCESS('=========START========='))
        for data in early_limit_data:
            try:
                loan_id = data['loan_id']
                limit_release_amount = int(data['limit_release_amount'])
                payment_id = data['payment_id']

                release_loan_mapping = EarlyReleaseLoanMapping.objects.get_or_none(loan_id=loan_id)
                if release_loan_mapping and release_loan_mapping.is_auto:
                    logger.info(
                        {
                            'action': 'execute_early_limit_one_time_payment_is_auto',
                            'loan_id': loan_id,
                        }
                    )
                    list_loans_auto.append(loan_id)
                    continue

                if ReleaseTracking.objects.filter(payment_id=payment_id).exists():
                    logger.info(
                        {
                            'action': 'execute_early_limit_one_time_payment_existed',
                            'loan_id': loan_id,
                        }
                    )
                    list_existed.append(loan_id)
                    continue
                with db_transactions_atomic(DbConnectionAlias.utilization()):
                    loan = Loan.objects.get_or_none(
                        pk=loan_id, loan_status__lt=LoanStatusCodes.PAID_OFF
                    )
                    if loan:
                        total_limit_release = (
                            ReleaseTracking.objects.filter(loan_id=loan.pk).aggregate(
                                total_limit_release_amount=Sum('limit_release_amount')
                            )['total_limit_release_amount']
                            or 0
                        )
                        # don't allow release limit > loan amount
                        if (total_limit_release + limit_release_amount) > loan.loan_amount:
                            logger.info(
                                {
                                    'action': 'execute_early_limit_one_time_over_amount',
                                    'loan_id': payment_id,
                                }
                            )
                            list_over_amount.append(payment_id)
                            continue

                        account_limit = (
                            AccountLimit.objects.select_for_update()
                            .filter(account_id=loan.account_id)
                            .last()
                        )
                        new_available_limit = account_limit.available_limit + limit_release_amount
                        new_used_limit = account_limit.used_limit - limit_release_amount

                        if new_used_limit < 0:
                            list_negative.append(loan_id)
                            logger.info(
                                {
                                    'action': 'execute_early_limit_one_time_negative_release',
                                    'loan_id': loan_id,
                                }
                            )
                        else:
                            ReleaseTracking.objects.create(
                                limit_release_amount=limit_release_amount,
                                payment_id=payment_id,
                                loan_id=loan_id,
                                account_id=loan.account_id,
                                type=ReleaseTrackingType.EARLY_RELEASE,
                            )
                            account_limit.update_safely(
                                available_limit=new_available_limit, used_limit=new_used_limit
                            )
                            if not release_loan_mapping:
                                EarlyReleaseLoanMapping.objects.create(
                                    loan_id=loan_id, is_auto=False
                                )
                            send_user_attributes_to_moengage_for_early_limit_release.delay(
                                customer_id=loan.customer_id,
                                limit_release_amount=limit_release_amount,
                                status=EarlyLimitReleaseMoengageStatus.SUCCESS,
                            )
                            logger.info(
                                {
                                    'action': 'execute_early_limit_one_time_success',
                                    'loan_id': loan_id,
                                }
                            )

                    else:
                        list_loan_x250.append(loan_id)
                        logger.info(
                            {
                                'action': 'execute_early_limit_one_time_already_x250',
                                'loan_id': loan_id,
                            }
                        )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR('====ERROR===: loan_id: {} Error: {}'.format(loan_id, str(e)))
                )
                list_loan_failed.append([loan_id, str(e)])

        # Print the result
        logger.info(
            {
                'action': 'execute_early_limit_one_time',
                'list_negative_limit': list_negative,
                'list_loan_failed': list_loan_failed,
                'list_loan_x250': list_loan_x250,
                'list_duplicated': list_existed,
                'list_over_loan_amount': list_over_amount,
            }
        )
        total_income_data = len(early_limit_data)
        total_negative_limit = len(list_negative)
        total_loan_failed = len(list_loan_failed)
        total_loan_x250 = len(list_loan_x250)
        total_list_existed = len(list_existed)
        total_list_over_amount = len(list_over_amount)
        total_list_loans_auto = len(list_loans_auto)
        total_success = (
            total_income_data
            - total_negative_limit
            - total_loan_failed
            - total_loan_x250
            - total_list_existed
            - total_list_over_amount
            - total_list_loans_auto
        )
        self.stdout.write(
            self.style.SUCCESS('====Total negative limit====: {}'.format(total_negative_limit))
        )
        self.stdout.write(
            self.style.SUCCESS('====Total failed loans====: {}'.format(total_loan_failed))
        )
        self.stdout.write(
            self.style.SUCCESS('====Total loans x250====: {}'.format(total_loan_x250))
        )
        self.stdout.write(
            self.style.SUCCESS('====Total over amount====: {}'.format(total_list_over_amount))
        )
        self.stdout.write(
            self.style.SUCCESS('====Total payments existed====: {}'.format(total_list_existed))
        )
        self.stdout.write(
            self.style.SUCCESS('====Total loans are auto====: {}'.format(total_list_loans_auto))
        )
        self.stdout.write(
            self.style.SUCCESS(
                '====TOTAL SUCCESS====: {}/{}'.format(total_success, total_income_data)
            )
        )
        self.stdout.write(self.style.SUCCESS('=========Finish========'))

    def get_early_limit_release_from_csv(self, csv_path):
        with urllib.request.urlopen(csv_path) as response:
            data = response.read().decode('utf-8')

        return list(csv.DictReader(data.splitlines()))
