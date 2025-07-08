from juloserver.payment_point.constants import SepulsaProductType, SepulsaProductCategory
from juloserver.payment_point.models import TransactionMethod


def determine_transaction_method_by_sepulsa_product(product):
    if product.type == SepulsaProductType.EWALLET:
        return TransactionMethod.objects.get(pk=5)
    if product.type == SepulsaProductType.ELECTRICITY:
        return TransactionMethod.objects.get(pk=6)
    if product.type == SepulsaProductType.BPJS:
        if product.category in SepulsaProductCategory.BPJS_KESEHATAN:
            return TransactionMethod.objects.get(pk=7)
    if product.type == SepulsaProductType.MOBILE:
        if product.category in SepulsaProductCategory.PRE_PAID_AND_DATA:
            return TransactionMethod.objects.get(pk=3)
        if product.category in SepulsaProductCategory.POSTPAID:
            return TransactionMethod.objects.get(pk=4)
    return None
