from django.utils import timezone
from celery.task import task
from juloserver.limit_validity_timer.models import LimitValidityTimer
from juloserver.limit_validity_timer.utils import read_csv_file_by_csv_reader


@task(queue='loan_normal')
def trigger_upload_limit_validity_timer_campaign(campaign_id):
    from juloserver.limit_validity_timer.services import populate_limit_validity_campaign_on_redis
    campaign = LimitValidityTimer.objects.get(id=campaign_id)
    csv_reader = read_csv_file_by_csv_reader(campaign.upload_url)
    customer_ids = set([int(row[0]) for row in csv_reader])
    if customer_ids:
        expire_at = timezone.localtime(campaign.end_date)
        populate_limit_validity_campaign_on_redis(customer_ids, campaign.id, expire_at)
