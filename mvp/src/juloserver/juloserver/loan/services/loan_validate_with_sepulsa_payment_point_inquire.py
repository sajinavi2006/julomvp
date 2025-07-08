from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, SepulsaProduct
from juloserver.payment_point.constants import (
    TransactionMethodCode,
    SepulsaProductCategory,
    SepulsaProductType,
)
from juloserver.payment_point.models import SepulsaPaymentPointInquireTracking, TrainTransaction


def is_valid_price_with_sepulsa_payment_point(
    account, transaction_method_id, price, inquire_tracking_id, payment_point_product_id
):
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        is_active=True,
    ).exists():
        return True

    # NEED TO CHECK some postpaid methods because we need amount from inquiry
    # by get last tracking of this account and compare with transaction method & price
    if transaction_method_id == TransactionMethodCode.TRAIN_TICKET.code:
        train_transaction = TrainTransaction.objects.filter(
            customer_id=account.customer_id).values('price').last()
        if train_transaction:
            return train_transaction['price'] == price
        return False

    if transaction_method_id in TransactionMethodCode.inquire_sepulsa_need_validate():
        if inquire_tracking_id:
            # In the future, Android will send sepulsa_payment_point_inquire_tracking_id
            # so, we can use this tracking id to check instead of get last tracking record.
            # We will have a separate card to use data in the tracking record
            # instead of using data user inputs in loan creation.
            if SepulsaPaymentPointInquireTracking.objects.filter(
                id=inquire_tracking_id,
                account=account,
                transaction_method_id=transaction_method_id,
                price=price,
            ).exists():
                return True

        else:
            last_tracking = SepulsaPaymentPointInquireTracking.objects.filter(
                account=account,
                transaction_method_id=transaction_method_id,
            ).last()
            if last_tracking and last_tracking.price == price:
                return True

    # DON'T NEED TO CHECK some prepaid methods because we handled it when create loan
    else:
        return True

    # For electricity prepaid, because it uses same transaction_method_id with postpaid
    # so, we need to check if price exist in SepulsaProduct
    # but currently, FE use loan_amount_request is calculated value in loan duration, not raw value
    # so, we need to check payment_point_product_id in SepulsaProduct is electricity prepaid or not
    if (
        transaction_method_id == TransactionMethodCode.LISTRIK_PLN.code
        and SepulsaProduct.objects.filter(
            id=payment_point_product_id,
            type=SepulsaProductType.ELECTRICITY,
            category=SepulsaProductCategory.ELECTRICITY_PREPAID,
            is_active=True,
        ).exists()
    ):
        return True

    return False
