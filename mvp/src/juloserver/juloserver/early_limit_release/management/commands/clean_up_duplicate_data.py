from django.db.models import Sum, Count

from django.core.management.base import BaseCommand
from juloserver.early_limit_release.models import ReleaseTracking
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.loan.services.lender_related import logger


class Command(BaseCommand):
    help = """
        Clean up duplicate payment_id in ReleaseTracking
        command: python manage.py clean_up_duplicate_data
    """

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=========START========='))
        early_release_duplicate = (
            ReleaseTracking.objects.values('payment_id')
            .annotate(
                payment_count=Count('payment_id'), total_release_amount=Sum('limit_release_amount')
            )
            .filter(payment_count__gt=1)
            .values('payment_id', 'total_release_amount')
        )
        list_failed = []
        clean_tracking_success = []

        for early_release in early_release_duplicate:
            payment_id = early_release['payment_id']
            total_release_amount = early_release['total_release_amount']
            self.stdout.write(
                self.style.SUCCESS('Processing with payment_id: {}'.format(payment_id))
            )
            tracking = ReleaseTracking.objects.filter(payment_id=payment_id).last()
            try:
                clean_early_tracking = dict(payment_id=payment_id)
                with db_transactions_atomic(DbConnectionAlias.utilization()):
                    tracking.update_safely(limit_release_amount=total_release_amount)
                    early_tracking_deleted = list(
                        ReleaseTracking.objects.filter(payment_id=payment_id)
                        .exclude(pk=tracking.pk)
                        .values()
                    )
                    clean_early_tracking['early_tracking_deleted'] = early_tracking_deleted
                    ReleaseTracking.objects.filter(payment_id=payment_id).exclude(
                        pk=tracking.pk
                    ).delete()
                    clean_tracking_success.append(clean_early_tracking)
                    logger.info(
                        {
                            'action': 'clean_up_duplicate_early_release_tracking_success',
                            'payment_id': payment_id,
                            'info': clean_early_tracking,
                        }
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR('Error with payment_id: {} {}'.format(payment_id, str(e)))
                )
                logger.info(
                    {
                        'action': 'clean_up_duplicate_early_release_tracking_failed',
                        'payment_id': payment_id,
                        'errors': str(e),
                    }
                )
                list_failed.append(payment_id)

        self.stdout.write(
            self.style.SUCCESS('====TOTAL====: {}'.format(len(early_release_duplicate)))
        )
        self.stdout.write(
            self.style.SUCCESS('====SUCCESS====: {}'.format(len(clean_tracking_success)))
        )
        self.stdout.write(self.style.SUCCESS('====FAILED====: {}'.format(len(list_failed))))

        logger.info(
            {
                'action': 'clean_up_duplicate_early_release_tracking',
                'failed': list_failed,
                'clean_tracking_success': clean_tracking_success,
            }
        )
        self.stdout.write(self.style.SUCCESS('=========Finish========'))
