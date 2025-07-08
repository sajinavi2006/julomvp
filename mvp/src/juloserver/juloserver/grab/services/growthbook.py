import logging

from juloserver.grab.exceptions import GrabLogicException
from juloserver.grab.models import GrabExperimentGroup, GrabCustomerData
from juloserver.julo.models import ExperimentSetting
from juloserver.grab.clients.growthbook import GrabGrowthbookClient
from juloserver.grab.constants import GrabExperimentConst, GrabExperimentGroupSource

logger = logging.getLogger(__name__)


def trigger_store_grab_customer_data_to_growthbook(grab_customer_data_id: int):
    experiment_setting_id = ExperimentSetting.objects.filter(
        code=GrabExperimentConst.NEW_LOAN_OFFER_PAGE_FEATURE,
        is_active=True
    ).values_list('id', flat=True).last()
    if not experiment_setting_id:
        return GrabExperimentConst.CONTROL_TYPE, "{} experiment setting doesnt not exist or inactivated".format(
            GrabExperimentConst.NEW_LOAN_OFFER_PAGE_FEATURE)
    feature_name = GrabExperimentConst.NEW_LOAN_OFFER_PAGE_FEATURE
    callback_func = callback_store_grab_customer_data_id_for_loan_offer_new_page
    return store_gcd_to_growthbook(feature_name, grab_customer_data_id, callback_func)


def store_gcd_to_growthbook(feature_name: str, grab_customer_data_id: int, callback_func):
    """
    Store grab customer data id to growthbook
    """
    error_message = None
    default_experiment_group_value = GrabExperimentConst.CONTROL_TYPE
    client = GrabGrowthbookClient()
    growthbook = client.load_growthbook_features(callback_func)

    if not GrabCustomerData.objects.filter(pk=grab_customer_data_id).exists():
        error_message = 'this grab customer data id {}, is not GRAB account'.format(
            str(grab_customer_data_id))
        logger.warning({
            'action': 'store_grab_customer_data_ids_for_loan_offer_new_page',
            'message': error_message
        })

        return default_experiment_group_value, error_message

    growthbook.set_attributes({'id': grab_customer_data_id})
    # automatically call callback
    experiment_group_value = growthbook.get_feature_value(feature_name, '')
    # check if this feature not yet integrates with experiment growthbook
    if not experiment_group_value:
        logger.warning({
            'action': 'store_grab_customer_data_ids_for_loan_offer_new_page',
            'message': '{} feature is not exist, or experiment is unset'.format(
                feature_name),
        })
        experiment_group_value = default_experiment_group_value
    growthbook.destroy()
    logger.info({
        'action': 'store_grab_customer_data_ids_for_loan_offer_new_page',
        'message': 'task finished',
    })

    return experiment_group_value, error_message


def callback_store_grab_customer_data_id_for_loan_offer_new_page(experiment, result):
    experiment_setting_id = ExperimentSetting.objects.filter(
        code=GrabExperimentConst.NEW_LOAN_OFFER_PAGE_FEATURE,
        is_active=True
    ).values_list('id', flat=True).last()
    if not experiment_setting_id:
        raise GrabLogicException("{} experiment setting doesnt not exist or inactivated".format(
            GrabExperimentConst.NEW_LOAN_OFFER_PAGE_FEATURE))
    data = {
        'grab_customer_data_id': int(result.hashValue),
        'experiment_setting_id': experiment_setting_id,
        'source': GrabExperimentGroupSource.GROWTHBOOK,
    }
    logger.info({
        "action": "callback_store_grab_customer_data_id_for_loan_offer_new_page",
        "data": data
    })
    if not GrabExperimentGroup.objects.filter(**data).exists():
        data.update(group=result.value)
        GrabExperimentGroup.objects.create(**data)
