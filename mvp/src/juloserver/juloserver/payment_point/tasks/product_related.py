import logging

from celery import task
from django.conf import settings
from juloserver.julo.models import SepulsaProduct
from juloserver.payment_point.constants import SepulsaProductType
from juloserver.payment_point.services.sepulsa import SepulsaLoanService
from django.utils import timezone
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.monitors.notifications import notify_sepulsa_product_not_exist
from django_bulk_update.helper import bulk_update
from juloserver.julo.services2.sepulsa import SepulsaService

logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


@task(queue="loan_high")
def auto_update_sepulsa_product():
    sepulsa_loan_service = SepulsaLoanService()
    data_products = sepulsa_loan_service.get_sepulsa_product()

    sepulsa_service = SepulsaService()
    cashback_products = sepulsa_service.get_sepulsa_product(
        manual_types=[SepulsaProductType.E_WALLET_OPEN_PAYMENT]
    )
    data_products.extend(cashback_products)
    data_products = {
        p['product_id']: {'price': p['price'], 'enabled': p['enabled']} for p in data_products}

    update_product_sepulsa_subtask.delay(data_products)
    update_pdam_product_sepulsa_subtask.delay()

    # set product that removed from sepulsa (no longer exist) to inactive
    product_ids = list(data_products.keys())
    SepulsaProduct.objects.filter(is_active=True).exclude(product_id__in=product_ids) \
        .exclude(type=SepulsaProductType.PDAM).update(is_active=False, is_not_blocked=False)


@task(queue="loan_high")
def update_product_sepulsa_subtask(data_products):
    list_update_products = []
    udate = timezone.localtime(timezone.now())
    product_ids = list(data_products.keys())

    sepulsa_products = list(SepulsaProduct.objects.filter(product_id__in=product_ids))
    for sepulsa_product in sepulsa_products:
        product = data_products.get(sepulsa_product.product_id)
        price = int(product['price'])
        sepulsa_product.partner_price = price
        sepulsa_product.customer_price = price + (price * 0.1)
        sepulsa_product.customer_price_regular = price
        sepulsa_product.is_active = product['enabled'] == '1'
        sepulsa_product.udate = udate
        list_update_products.append(sepulsa_product)

    update_fields = [
        'partner_price', 'customer_price', 'customer_price_regular', 'is_active', 'udate']

    bulk_update(list_update_products, update_fields=update_fields, batch_size=100)


@task(queue="loan_high")
def update_pdam_product_sepulsa_subtask():
    list_update_products = []
    errors = []
    udate = timezone.localtime(timezone.now())

    data = {
        'product_id': settings.PDAM_PRODUCTID
    }

    api_response, error = SepulsaLoanService().inquire_pdam_operator(data)

    if error:
        logger.info({
            "task": "update_pdam_product_sepulsa_subtask",
            "path": "juloserver/payment_point/tasks/product_related",
            "respon_data": error,
        })

        return False

    for operator in api_response['OperatorLists']:
        sepulsa_product = SepulsaProduct.objects.filter(product_desc=operator['code']).last()
        if sepulsa_product:
            product_status = True if operator['enabled'] == "1" else False
            sepulsa_product.is_active = product_status
            sepulsa_product.is_not_blocked = product_status
            sepulsa_product.udate = udate
            sepulsa_product.product_name = operator['description']
            list_update_products.append(sepulsa_product)
        else:
            # data not exist
            errors.append(operator)

    if errors:
        # log and push to sentry
        notify_sepulsa_product_not_exist(errors)
        logger.info(
            {
                'action': 'update_pdam_product_sepulsa_subtask',
                'data': errors,
                'message': 'Sepulsa Product with [product_desc] is not found',
            }
        )

    update_fields = ['is_active', 'is_not_blocked', 'udate', 'product_name']
    bulk_update(list_update_products, update_fields=update_fields, batch_size=100)
