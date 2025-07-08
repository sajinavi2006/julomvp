from builtins import str

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def cs_v20b_check_application_id_criteria(criteria, application_id):
    rule = criteria.split(":")
    result = False
    if rule[0] == "#nth":
        digit_index = int(rule[1])
        digit_criteria = rule[2].split(",")
        if digit_index < 0:
            digit = str(application_id)[digit_index]
        else:
            digit = str(application_id)[digit_index - 1]

        if digit in digit_criteria:
            result = True
    return result


def cs_v20b_check_product_criteria(criteria, product_line_type):
    product_line_criteria = criteria.lower().split(",")
    result = False
    if product_line_type.lower() in product_line_criteria:
        result = True
    return result


def check_app_cs_v20b(application):
    """
    criteria are same like application experimentations

    """
    result = False
    feature_score_v20b = (
        FeatureSetting.objects.filter(feature_name=FeatureNameConst.V20B_SCORE, is_active=True)
        .cache(timeout=60 * 60 * 24)
        .last()
    )
    if feature_score_v20b:
        if feature_score_v20b.category in ["application_id", "application_xid", "product"]:
            if feature_score_v20b.category == "application_id":
                result = cs_v20b_check_application_id_criteria(
                    feature_score_v20b.parameters["criteria"], application.id
                )
            elif feature_score_v20b.category == "application_xid":
                result = cs_v20b_check_application_id_criteria(
                    feature_score_v20b.parameters["criteria"], application.application_xid
                )
            elif feature_score_v20b.category == "product":
                result = cs_v20b_check_product_criteria(
                    feature_score_v20b.parameters["criteria"],
                    application.product_line.product_line_type,
                )
    return result
