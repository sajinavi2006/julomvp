from django.core.management.base import BaseCommand
from django.db.models import Count, Case, When, IntegerField, Min, Max
from juloserver.julo.models import (
    FeatureSetting,
    SkiptraceHistory,
    SkiptraceStats,
)
from collections import defaultdict
from datetime import datetime, timedelta
import logging
import sys

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def handle(self, **options):
        try:
            self.stdout.write('starting retroload_init_skiptrace_stats')
            feature_setting, _ = FeatureSetting.objects.get_or_create(
                feature_name='skiptrace_stats_scheduler',
                defaults={"parameters": {"date_range": 30}},
            )
            self.stdout.write(self.style.SUCCESS('feature setting is created'))
            # + 1 because we query data from yesterday and start counting the range from yesterday.
            start_time = datetime.now().date() - timedelta(
                days=feature_setting.parameters.get('date_range', 30) + 1
            )
            end_time = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(microseconds=1)

            contact_call_results = [
                'RPC - Broken Promise',
                'RPC - Call Back',
                'RPC - HTP',
                'RPC - PTP',
                'RPC - Regular',
                'RPC - Already PTP',
                'RPC - Already Paid',
            ]

            skiptrace_histories = (
                SkiptraceHistory.objects.filter(cdate__range=(start_time, end_time))
                .values("skiptrace_id")
                .annotate(
                    attempt_count=Count("id"),
                    rpc_count=Count(
                        Case(
                            When(call_result__name__in=contact_call_results, then=1),
                            output_field=IntegerField(),
                        )
                    ),
                    min_date=Min("cdate"),
                    max_date=Max("cdate"),
                )
            )
            start_time_rpc = datetime.now().date() - timedelta(days=160 + 1)
            last_rpc_skiptrace_histories = (
                SkiptraceHistory.objects.distinct('skiptrace_id')
                .filter(
                    cdate__range=(start_time_rpc, end_time),
                    call_result__name__in=contact_call_results,
                )
                .order_by('skiptrace_id', '-start_ts')
                .values('id', 'skiptrace_id', 'start_ts')
            )

            def skiptrace_stats_init():
                return SkiptraceStats()

            skiptrace_stats_dict = defaultdict(skiptrace_stats_init)
            self.stdout.write(self.style.SUCCESS('fetching skiptrace_histories'))
            for skiptrace_history in skiptrace_histories:
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].skiptrace_id = skiptrace_history['skiptrace_id']
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].attempt_count = skiptrace_history['attempt_count']
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].rpc_count = skiptrace_history['rpc_count']
                skiptrace_stats_dict[skiptrace_history['skiptrace_id']].rpc_rate = (
                    round(skiptrace_history['rpc_count'] / skiptrace_history['attempt_count'], 5)
                    if skiptrace_history['attempt_count'] > 0
                    else 0
                )
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].calculation_start_date = skiptrace_history['min_date'].date()
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].calculation_end_date = skiptrace_history['max_date'].date()

            self.stdout.write(self.style.SUCCESS('fetching last_rpc_skiptrace_histories'))
            for skiptrace_history in last_rpc_skiptrace_histories:
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].skiptrace_id = skiptrace_history['skiptrace_id']
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].skiptrace_history_id = skiptrace_history['id']
                skiptrace_stats_dict[
                    skiptrace_history['skiptrace_id']
                ].last_rpc_ts = skiptrace_history['start_ts']

            self.stdout.write(self.style.SUCCESS('mapping skiptrace_stats successs'))
            tobe_inserted_skiptrace_stats = list(skiptrace_stats_dict.values())
            batch_size = 1000
            total = len(tobe_inserted_skiptrace_stats)
            for i in range(0, total, batch_size):
                batch = tobe_inserted_skiptrace_stats[i : min(i + batch_size, total)]
                SkiptraceStats.objects.bulk_create(batch)
                self.stdout.write(
                    self.style.SUCCESS(
                        '%d skiptrace_stats is inserted' % min(i + batch_size, total)
                    )
                )

            self.stdout.write(self.style.SUCCESS('retroload_init_skiptrace_stats finished'))
            logger.error(
                {
                    'action': 'retroload_init_skiptrace_stats',
                    'message': 'finished',
                }
            )
        except Exception as err:
            error_msg = 'Something went wrong - {}'.format(str(err))
            self.stdout.write(self.style.ERROR(error_msg))
            logger.error({'action': 'retroload_init_skiptrace_stats', 'reason': error_msg})
            raise err
