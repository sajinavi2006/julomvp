import logging
import getpass

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from juloserver.moengage.tasks import daily_update_customer_segment_data_on_moengage

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Bulk send customer segmentation data to moengage with amount of days before today"
        "\nUsage: manage.py <command_name> --days_before <number_of_days>"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--days_before",
            type=int,
            required=True,
        )

    def handle(self, *args, **options):
        try:
            days_before = options["days_before"]
            user = getpass.getuser()

            # run
            daily_update_customer_segment_data_on_moengage.delay(days_before)

            # logging
            now = timezone.localtime(timezone.now())
            logger.info(
                {
                    "action": "bulk_update_customer_segment_data_on_moengage",
                    "at": f"{now.isoformat()}",
                    "days_before_value": days_before,
                    "by_user": user,
                }
            )

            self.stdout.write(
                f"Success sent to async server to update customer segmentation updated in previous {days_before} days"
            )

        except Exception as e:
            self.stdout.write(f"An error occured: {e}")
            raise e
