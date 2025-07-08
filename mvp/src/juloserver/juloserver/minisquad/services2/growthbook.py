import logging
from juloserver.account.models import Account
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import ExperimentSetting
from juloserver.account.models import ExperimentGroup
from juloserver.autodebet.models import AutodebetAccount
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.minisquad.constants import ExperimentConst, ExperimentGroupSource
from juloserver.julo.clients.growthbook import JuloGrowthbookClient

logger = logging.getLogger(__name__)


def store_from_growthbook(feature_name: str, account_ids):
    fn_name = 'store_from_growthbook'
    client = JuloGrowthbookClient()
    growthbook = client.load_growthbook_features(callback_store_from_growthbook)
    for account_id in account_ids:
        try:
            if not Account.objects.filter(
                pk=account_id,
                account_lookup__workflow__name=WorkflowConst.JULO_ONE).exists():
                logger.warning({
                    'action': fn_name,
                    'message': 'this account id {}, is non J1 account'.format(
                        str(account_id)),
                })
                continue

            if AutodebetAccount.objects.is_account_autodebet(account_id):
                logger.warning({
                    'action': fn_name,
                    'message': 'this account id {}, is active autodebet'.format(
                        str(account_id)),
                })
                continue

            growthbook.set_attributes({'account_id': account_id})
            # automatically call callback_store_from_growthbook function
            value = growthbook.get_feature_value(feature_name, '')
            # check if this feature not yet integrate with experiment growthbook
            if not value:
                logger.warning({
                    'action': fn_name,
                    'message': '{} feature is not exist, or experiment is unset'.format(
                        feature_name),
                })
                continue
        except Exception as err:
            logger.error({
                'action': fn_name,
                'account_id': account_id,
                'message': str(err),
            })
            get_julo_sentry_client().captureException()
            if str(err) == "experiment setting not exist":
                return
            continue

    growthbook.destroy()
    logger.info({
        'action': fn_name,
        'message': 'task finished',
    })


def callback_store_from_growthbook(experiment, result):
    cashback_experiment_id = ExperimentSetting.objects.filter(
        code=experiment.key
    ).values_list('id', flat=True).last()
    if not cashback_experiment_id:
        raise Exception("experiment setting not exist")
    data = {
        'account_id': int(result.hashValue),
        'experiment_setting_id': cashback_experiment_id,
        'source': ExperimentGroupSource.GROWTHBOOK,
    }
    if not ExperimentGroup.objects.filter(**data).exists():
        data.update(group=result.value)
        ExperimentGroup.objects.create(**data)


def callback_growthbook():
    pass


def get_experiment_group_data_on_growthbook(code, account_id):
    experiment_group = None
    client = JuloGrowthbookClient()
    growthbook = client.load_growthbook_features(callback_growthbook)
    growthbook.set_attributes({'account_id': account_id})
    value = growthbook.get_feature_value(code, '')
    if not value:
        growthbook.destroy()
        return experiment_group

    experiment_setting_id = ExperimentSetting.objects.filter(
        code=code
    ).values_list('id', flat=True).last()
    if not experiment_setting_id:
        growthbook.destroy()
        return experiment_group

    experiment_group = ExperimentGroup.objects.filter(
        experiment_setting_id=experiment_setting_id, account_id=account_id
    ).last()
    if not experiment_group:
        growthbook.destroy()
        return experiment_group

    growthbook.destroy()
    return experiment_group


def get_experiment_setting_data_on_growthbook(code):
    fn_name = 'get_experiment_setting_data_on_growthbook_{}'.format(code)
    experiment_setting = ExperimentSetting.objects.filter(
        code=code
    ).last()
    if not experiment_setting:
        logger.info({
            'action': fn_name,
            'message': 'experiment setting not found'
        })
        return None

    account_id = ExperimentGroup.objects.filter(
        experiment_setting_id=experiment_setting.id
    ).values_list('account_id', flat=True).first()
    if not account_id and not experiment_setting.is_active:
        logger.info({
            'action': fn_name,
            'message': 'no one experiment group found and experiment setting not active'
        })
        return None

    client = JuloGrowthbookClient()
    growthbook = client.load_growthbook_features(callback_growthbook)
    growthbook.set_attributes({'account_id': account_id}) # for trigger latest status
    value = growthbook.get_feature_value(code, '')
    if not value and not experiment_setting.is_active:
        growthbook.destroy()
        logger.info({
            'action': fn_name,
            'message': 'growthbook not active'
        })
        return None

    growthbook.destroy()
    return experiment_setting.id
