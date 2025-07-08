from celery import task
from juloserver.julolog.julolog import JuloLog
from juloserver.pii_vault.constants import PiiSource


logger = JuloLog(__name__)


@task(acks_late=True)
def tokenize_data_task(data):
    # logger.info('start_tokenize_data_task|data={}'.format(data))
    from juloserver.pii_vault.services import _tokenize_data

    return _tokenize_data(data)


@task(queue='back_fill_pii_vault')
def back_fill_onboarding_pii_vault():
    from juloserver.pii_vault.services import back_fill_pii_data

    back_fill_pii_data()


@task(queue='back_fill_pii_vault')
def recover_pii_vault_event():
    from juloserver.pii_vault.services import recover_pii_vault_event

    recover_pii_vault_event()


@task(queue='onboarding_pii_vault', acks_late=True)
def detokenize_data_task(
    resource_type,
    detokenize_resource_type,
    resources,
    fields,
    get_all,
    pii_data_type,
    feature_setting_params=None,
    force_get_local_data=False,
):
    logger.info('start_detokenize_data_task|data={}'.format(resources))
    from juloserver.pii_vault.services import _detokenize_data

    return _detokenize_data(
        resource_type,
        detokenize_resource_type,
        resources,
        fields,
        get_all,
        pii_data_type=pii_data_type,
        feature_setting_params=feature_setting_params,
        force_get_local_data=force_get_local_data,
    )


@task(queue='back_fill_pii_vault')
def backfill_node_by_pk(table_name: str, pk: int):
    from juloserver.pii_vault.services import backfill_tokenize, get_resource
    model_class = PiiSource.get_type_from_source(table_name)
    resource = get_resource(table_name, pk)
    field_list = model_class.PII_FIELDS
    pii_type = model_class.PII_TYPE if hasattr(model_class, 'PII_TYPE') else 'cust'
    payload = {'resource_id': pk, 'fields': field_list, 'pii_type': pii_type}
    backfill_tokenize(table_name, resource, payload)


@task(queue='back_fill_pii_vault')
def produce_backfill_task_for_page(table_name, page_size, start_id, end_id):
    logger.info('preparing backfill task for {} batch start with {}'.format(table_name, start_id))
    model_class = PiiSource.get_type_from_source(table_name)
    if end_id:
        list_of_pk = model_class.objects.filter(id__gte=start_id, id__lt=end_id
                                                ).order_by('pk').values_list('pk', flat=True)[0:page_size]
    else:
        list_of_pk = model_class.objects.filter(id__gte=start_id
                                                ).order_by('pk').values_list('pk', flat=True)[0:page_size]
    list_of_pk = list(list_of_pk)
    if len(list_of_pk) == 0:
        logger.info('backfill task for {} batch tasks are completed'.format(table_name))
        return
    for primary_key in list_of_pk:
        backfill_node_by_pk.delay(table_name=table_name, pk=primary_key)
    next_page_start_id = list_of_pk[-1] + 1
    logger.info('backfill task for {} batch start with {} is queued'.format(table_name, next_page_start_id))
    produce_backfill_task_for_page.delay(table_name=table_name,
                                         page_size=page_size,
                                         start_id=next_page_start_id,
                                         end_id=end_id
                                         )


def backfill_table(table_name: str, page_size: int, start_id: int = 0, end_id: int = 0):
    logger.info('starting backfill task for {} page size of {}'.format(table_name, page_size))
    model_class = PiiSource.get_type_from_source(table_name)
    if model_class is None:
        logger.error('backfill failed as table not added in class PiiSource get_type_from_source')
        return 0
    if not isinstance(start_id, int) or not isinstance(end_id, int) or (end_id and start_id >= end_id):
        logger.error('start_id and end_id not valid')
        return 0
    if not isinstance(page_size, int) or page_size < 1:
        logger.error('page_size not valid')
        return 0
    produce_backfill_task_for_page.delay(table_name=table_name, page_size=page_size, start_id=start_id, end_id=end_id)
    logger.info('task will run in backgound already produced')
