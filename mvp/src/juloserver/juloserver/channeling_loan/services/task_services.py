import logging
import pandas
from django.conf import settings

from juloserver.channeling_loan.services.general_services import send_notification_to_slack
from juloserver.julo.models import FeatureSetting

from juloserver.channeling_loan.constants import FeatureNameConst

logger = logging.getLogger(__name__)


def construct_channeling_url_reader(url):
    if '.google.' in url:
        download_url = 'https://drive.google.com/uc?id=' + url.split('/')[-2]
        if 'drive.google' in url:
            return pandas.read_csv(download_url)

        elif 'docs.google' in url:
            return pandas.read_excel(download_url)
    else:
        if '.csv' in url:
            return pandas.read_csv(url)

        if '.xls' in url:
            return pandas.read_excel(url)

    return None


def get_ar_switching_lender_list():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AR_SWITCHING_LENDER, is_active=True
    ).last()

    return feature_setting.parameters if feature_setting else ()


def send_consolidated_error_msg(batch, total_count, failed_count):
    title = "*{} finished with summary* \n".format(batch)

    failed_count_msg = "\n*Failed*: *{}* rows from *{}* rows\n\n".format(
        str(failed_count), str(total_count)
    )

    send_notification_to_slack(
        title + failed_count_msg, settings.AR_SWITCHING_FAILED_SLACK_NOTIFICATION_CHANNEL
    )
