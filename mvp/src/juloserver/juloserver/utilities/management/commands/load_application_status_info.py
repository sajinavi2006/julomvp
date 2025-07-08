from __future__ import print_function
from datetime import datetime

from django.core.management.base import BaseCommand
from django.core.management import call_command

from juloserver.utilities.models import (
        SlackUser, SlackEWAStatusEmotion, 
        SlackEWATag, SlackEWABucket)
from juloserver.julo.models import StatusLookup
from juloserver.utilities.constants import CommonVariables


class Command(BaseCommand):

    help = "Load Initial Application status to SlackEWABucket"

    def handle(self, *args, **options):
        for item in CommonVariables.DEFAULT_SLACK_EWA:
            status = StatusLookup.objects.get_or_none(status_code=item['status_code'])
            if status:
                print("Processing status %s" %(item['status_code'],))
                bucket = SlackEWABucket.objects.get_or_none(status_code=status)
                if not bucket:
                    bucket = SlackEWABucket.objects.create(
                        status_code=status, 
                        order_priority=item['order_priority'],
                        display_text=item['display_text'])
                
                for emoji in item['emoji_con']:
                    se = SlackEWAStatusEmotion.objects.get_or_none(
                                emoji=emoji["emotion"],
                                bucket=bucket)
                    if not se:
                        SlackEWAStatusEmotion.objects.create(
                                condition=emoji["condition"],
                                emoji=emoji["emotion"],
                                bucket=bucket)
                
                for user_tag in item['tag_con']:
                    slack_users = []
                    for user in user_tag['slack_users']:
                        slack_user = SlackUser.objects.get_or_none(slack_id=user['slack_id'])
                        if not slack_user:
                            print("Creatin slack user: %s" %(user['slack_id'],))
                            slack_user = SlackUser.objects.create(
                                slack_id=user['slack_id'],
                                name = user['name'])
                        slack_users.append(slack_user)
                        
                    st = SlackEWATag.objects.get_or_none(
                                condition=user_tag["condition"],
                                bucket=bucket)
                    if not st:
                        st = SlackEWATag.objects.create(
                                condition=user_tag["condition"],
                                bucket=bucket)
                    for s_user in slack_users:
                        if s_user not in st.slack_user.all():
                            print("Adding slack user %s to bucket %s" %(user['slack_id'],item['status_code'],))
                            st.slack_user.add(s_user)
            else:
                print("Skippig Status %s: status not found in StatusLookup" %(item['status_code'],))
    

