from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from juloserver.account.tasks import account_bucket_history_creation
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import WorkflowConst, BucketConst
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.minisquad.constants import DialerServiceTeam, RedisKey
from juloserver.minisquad.utils import batch_pk_query_with_cursor


class Command(BaseCommand):
    help = "Retroload account bucket history"

    def add_arguments(self, parser):
        parser.add_argument('-f', '--queue', type=str, help='define queue')

    def handle(self, *args, **options):
        today = timezone.localtime(timezone.now()).date()
        retro_queue = options.get('queue', 'collection_dialer_high')
        self.stdout.write(self.style.WARNING('Start retroloading and querying'))
        account_id_list = (
            AccountPayment.objects.not_paid_active()
            .filter(
                account__account_lookup__workflow__name__in=(
                    WorkflowConst.JULO_ONE,
                    WorkflowConst.JULO_STARTER,
                    WorkflowConst.JULO_ONE_IOS,
                )
            )
            .filter(accountpaymentstatushistory__status_new=PaymentStatusCodes.PAYMENT_180DPD)
            .filter(due_date__lte=today - timedelta(days=BucketConst.BUCKET_6_1_DPD['from']))
            .order_by('account_id', 'due_date')
            .distinct('account_id')
            .values_list('account_id')
        )
        redis_client = get_redis_client()
        bucket_name = DialerServiceTeam.JULO_B6_1
        index = 1
        total_data = 0
        for batch_account_ids in batch_pk_query_with_cursor(account_id_list, 10000):
            self.stdout.write(self.style.WARNING('start part {} retroloading'.format(index)))
            bucket_name_for_redis = "{}_{}".format(bucket_name, index)
            redis_key = RedisKey.ACCOUNT_ID_BUCKET_HISTORY.format(bucket_name_for_redis)
            redis_client.set_list(redis_key, batch_account_ids, timedelta(hours=4))
            account_bucket_history_creation.apply_async(
                (
                    redis_key,
                    bucket_name,
                ),
                queue=retro_queue,
            )
            self.stdout.write(self.style.WARNING('send to task {} retroloading'.format(index)))
            total_data += len(batch_account_ids)
            index += 1

        self.stdout.write(
            self.style.WARNING(
                'Finish retroloading with total data {} and split into {}'.format(total_data, index)
            )
        )
