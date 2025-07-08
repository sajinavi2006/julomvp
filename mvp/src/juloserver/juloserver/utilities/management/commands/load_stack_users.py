from __future__ import print_function
from datetime import datetime

from django.core.management.base import BaseCommand

from juloserver.utilities.models import SlackUser
from juloserver.utilities.constants import CommonVariables


class Command(BaseCommand):

    help = "Load Deault slack users if they are not present in the table"

    def handle(self, *args, **options):
        default_users = CommonVariables.DEFAULT_SLACK_USERS
        for user in default_users:
            slack_user_exists = SlackUser.objects.filter(slack_id=user['slack_id']).exists()
            if not slack_user_exists:
                SlackUser.objects.create(
                    slack_id=user['slack_id'],
                    name=user['name']
                )
                print("Slack User Id: %s inserted" %(user['slack_id'],))
            else:
                print("Slack User Id: %s already exists" %(user['slack_id'],))

