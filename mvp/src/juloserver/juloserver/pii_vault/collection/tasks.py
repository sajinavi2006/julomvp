import re
from celery import task
import ast
from django.utils import timezone
import logging
from juloserver.pii_vault.collection.services import mask_phone_number

logger = logging.getLogger(__name__)


@task(queue='collection_high')
def mask_phone_numbers(sentence, column_name, model, pk, is_json=False):
    fn_name = 'PII_collection_mask_phone_numbers'

    now = timezone.localtime(timezone.now())
    phone_number_regex = r'\+?\d{1,3}[- ]?\d{3,4}[- ]?\d{3,4}[- ]?\d{3,4}|\d{10,15}'

    logger.info(
        {
            'action': fn_name,
            'state': 'start',
            'table': model,
            'id': pk,
        }
    )
    update_dict = dict()
    if is_json:
        masked_sentence = re.sub(phone_number_regex, mask_phone_number, str(sentence))
        update_dict = {column_name: ast.literal_eval(masked_sentence)}
    else:
        masked_sentence = re.sub(phone_number_regex, mask_phone_number, sentence)
        update_dict = {column_name: masked_sentence}
    update_dict.update(udate=now)
    model.objects.filter(pk=pk).update(**update_dict)
    logger.info(
        {
            'action': fn_name,
            'state': 'finish',
            'table': model,
            'id': pk,
        }
    )
