from juloserver.julolog.julolog import JuloLog
from juloserver.julo.models import ExperimentSetting, Device
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.account.models import ExperimentGroup
from juloserver.customer_module.exceptions import ExperimentSettingStoringException
from juloserver.customer_module.constants import ExperimentSettingConsts

logger = JuloLog(__name__)
sentry_client = get_julo_sentry_client()


@sentry_client.capture_exceptions
def process_experiment_data(
    data,
    customer,
):
    group_name, hash_value = None, None
    customer_id = customer.id if customer else None
    experiment_code = data['experiment_code']
    experiment = ExperimentSetting.objects.filter(code=experiment_code).last()
    if not experiment:
        logger.warning(
            'process_experiment_data|experiment_setting_not_found|'
            'experiment_code={}'.format(experiment_code)
        )
        raise ExperimentSettingStoringException('Experiment_setting not found')

    if not customer_id:
        error_message = (
            'process_experiment_data|missing_customer_id|'
            'experiment_code={}, customer_id={}'.format(experiment_code, customer_id)
        )
        logger.warning(error_message)
        raise ExperimentSettingStoringException('Invalid Request customer id is empty')

    data_result = data.get('result', None)
    hash_value_check_fail = False
    if data_result:
        group_name = data_result.get(ExperimentSettingConsts.KEY_GROUP_NAME, '').replace('"', '')

        # get has value id
        hash_value = data_result.get(ExperimentSettingConsts.HASH_VALUE, None)
        hash_attribute = data_result.get(ExperimentSettingConsts.HASH_ATTRIBUTE, None)
        if hash_value and hash_attribute:
            if hash_attribute == ExperimentSettingConsts.HashValues.CUSTOMER_ID:
                if str(hash_value) != str(customer_id):
                    hash_value_check_fail = True
            if hash_attribute == ExperimentSettingConsts.HashValues.DEVICE_ID:
                device = Device.objects.filter(customer=customer, android_id=hash_value).last()
                if not device:
                    hash_value_check_fail = True

    if not group_name or hash_value_check_fail:
        logger.warning(
            'process_experiment_data|invalid_group_name_or_customer_id|'
            'experiment_code={}, customer_id={}, group_name={}, hash_value={}'.format(
                experiment_code, customer_id, group_name, hash_value
            )
        )
        raise ExperimentSettingStoringException(
            'Invalid group name or invalid hash_value from Growthbook'
        )

    application = customer.application_set.last()
    experiment_group = ExperimentGroup.objects.filter(
        application=application,
        experiment_setting=experiment,
    ).exists()
    if not experiment_group:
        logger.info(
            'process_experiment_data|inserting_experiment_data|'
            'experiment_code={}, customer_id={}, group_name={}'.format(
                experiment_code, customer_id, group_name
            )
        )
        ExperimentGroup.objects.create(
            experiment_setting=experiment,
            application=application,
            customer=customer,
            source=data['source'],
            group=group_name,
        )

    return True
