from django.core.management.base import BaseCommand
from juloserver.omnichannel.serilizers.update_omnichannel_rollout_request import (
    UpdateOmnichannelRolloutRequest,
)
from juloserver.omnichannel.services.utils import (
    str_to_bool,
)
import logging
from juloserver.omnichannel.services.omnichannel import update_omnichannel_rollout

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Retroload to update customer rollout'

    def add_arguments(self, parser):
        parser.add_argument(
            '--customer_ids', type=str, help='Comma-separated list of customer IDs as integers'
        )
        parser.add_argument(
            '--rollout_channels', type=str, help='Comma-separated list of rollout channels'
        )
        parser.add_argument(
            '--is_included',
            type=str_to_bool,
            help='Boolean flag for rollout_channels is included or not',
        )

    def handle(self, *args, **options):

        request_body = get_request_body(
            options['customer_ids'], options['rollout_channels'], options['is_included']
        )

        update_omnichannel_rollout(
            customer_ids=request_body.customer_ids,
            rollout_channels=request_body.rollout_channels,
            is_included=request_body.is_included,
        )

        self.stdout.write(self.style.SUCCESS(f'Customer IDs: {request_body.customer_ids}'))
        self.stdout.write(self.style.SUCCESS(f'Rollout Channels: {request_body.rollout_channels}'))
        self.stdout.write(self.style.SUCCESS(f'Is Included: {request_body.is_included}'))


def get_request_body(customer_ids_str: str, rollout_channels_str: str, is_included: bool):
    customer_ids = [int(id) for id in customer_ids_str.split(',')] if customer_ids_str else []
    rollout_channels = rollout_channels_str.split(',') if rollout_channels_str else []

    return UpdateOmnichannelRolloutRequest(
        customer_ids=customer_ids, rollout_channels=rollout_channels, is_included=is_included
    )
