import logging
from datetime import date
from typing import Optional

from juloserver.ana_api.models import PdCustomerSegmentModelResult
from juloserver.julo.models import (
    CreditMatrixRepeat,
    FeatureSetting,
)
from juloserver.julo.constants import FeatureNameConst


logger = logging.getLogger(__name__)


def get_customer_segment(customer_id: int, day_filter_range: date = None) -> Optional[str]:
    """
    Get customer segment from PdCustomerSegmentModelResult (ana).
    Data in this table is recalculate every day.
    :param customer_id: id of customer
    :param day_filter_range: to filter records >= partition_date
    :return: customer_segment as string if found, else None
    """
    pd_customer_segment_query = PdCustomerSegmentModelResult.objects.filter(
        customer_id=customer_id,
    ).order_by('-id')

    if day_filter_range:
        pd_customer_segment_query = pd_customer_segment_query.filter(
            partition_date__lte=day_filter_range,
        )

    pd_customer_segment_model_result = pd_customer_segment_query.first()

    if not pd_customer_segment_model_result:
        return None

    return pd_customer_segment_model_result.customer_segment


def get_credit_matrix_repeat(
    customer_id: int,
    product_line_id: int,
    transaction_method_id: int,
    day_to_filter_customer_segment: date = None,
) -> Optional[CreditMatrixRepeat]:
    """
    Get credit matrix repeat object for specific customer from CreditMatrixRepeat
    :param customer_id: id of customer
    :param product_line_id: id of product line
    :param transaction_method_id: id of transaction method
    :param day_to_filter_customer_segment: date to get customer segment
    :return: CreditMatrixRepeat object if found, else None
    """
    credit_matrix_repeat_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDIT_MATRIX_REPEAT_SETTING, is_active=True
    ).last()
    if not credit_matrix_repeat_setting:
        return None

    customer_segment = get_customer_segment(
        customer_id=customer_id, day_filter_range=day_to_filter_customer_segment
    )
    if not customer_segment:
        return None

    cmr = (
        CreditMatrixRepeat.objects.filter(
            is_active=True,
            customer_segment=customer_segment,
            product_line_id=product_line_id,
            transaction_method_id=transaction_method_id,
        )
        .order_by('-version')
        .first()
    )

    if customer_segment and not cmr:
        logger.error(
            {
                'error': 'customer_segment is not null but can not find CMR. Please check it',
                'customer_segment': customer_segment,
                'product_line_id': product_line_id,
                'transaction_method_id': transaction_method_id,
                'day_to_filter_customer_segment': day_to_filter_customer_segment,
            }
        )

    return cmr
