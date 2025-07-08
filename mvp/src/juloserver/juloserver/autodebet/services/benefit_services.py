import ast
import math
from builtins import str
from datetime import datetime

from django.utils import timezone

from juloserver.autodebet.constants import (
    FeatureNameConst,
    TutorialAutodebetConst,
    AutodebetStatuses,
    AutodebetVendorConst,
    AutodebetBenefitConst,
)
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetBenefit,
    AutodebetBenefitDetail,
    AutodebetBenefitCounter,
)

from juloserver.julo.models import FeatureSetting, Image
from juloserver.julo.utils import display_rupiah
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst


def construct_benefit_autodebet_list():
    benefit_autodebet_bca_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BENEFIT_AUTODEBET_BCA, is_active=True
    ).last()
    if benefit_autodebet_bca_feature_setting:
        benefits = []
        for parameter in benefit_autodebet_bca_feature_setting.parameters:
            if parameter["status"] == "active":
                value = str(parameter["amount"])
                message = parameter["message"].format(display_rupiah(parameter["amount"]))
                if parameter["percentage"] and not parameter["amount"]:
                    value = "{}%".format(parameter["percentage"])
                    message = parameter["message"]
                benefit = {
                    "type": parameter["type"],
                    "value": value,
                    "message": message,
                }
                benefits.append(benefit)
        return benefits

    return []


def get_autodebet_benefit_message(account):
    existing_autodebet_account = AutodebetAccount.objects.filter(account=account).last()

    if existing_autodebet_account and existing_autodebet_account.status != \
            AutodebetStatuses.FAILED_REGISTRATION:
        return ""

    _, _, benefit = get_random_autodebet_benefit(account)
    if benefit:
        if not AutodebetBenefit.objects.filter(account_id=account.id).exists():
            AutodebetBenefit.objects.create(
                account_id=account.id,
                pre_assigned_benefit=benefit["type"],
            )
        return benefit['message']
    return ""


def get_autodebet_benefit_control_message(account):
    today = timezone.localtime(timezone.now()).date()
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)

    if not existing_benefit:
        return None, None

    benefit_type = existing_benefit.benefit_type or existing_benefit.pre_assigned_benefit

    if not benefit_type:
        return None, None

    autodebet_benefit_control_feature = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_BENEFIT_CONTROL,
        is_active=True
    )

    if not autodebet_benefit_control_feature:
        return None, None

    benefit_message = autodebet_benefit_control_feature.parameters['message']

    campaign_duration_start_date = datetime.strptime(
        autodebet_benefit_control_feature.parameters['campaign_duration']['start_date'],
        '%Y-%m-%d').date()
    campaign_duration_end_date = datetime.strptime(
        autodebet_benefit_control_feature.parameters['campaign_duration']['end_date'],
        '%Y-%m-%d').date()

    if campaign_duration_start_date <= today <= campaign_duration_end_date:
        return benefit_message[benefit_type], benefit_message['success_message']

    return None, None


def set_default_autodebet_benefit(account, account_payment):
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
    if existing_benefit and existing_benefit.benefit_type in ('cashback', 'waive_interest'):
        return

    benefits, benefit_name, benefit = get_random_autodebet_benefit(account)
    if not benefits or not benefit:
        return

    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
    if not existing_benefit:
        existing_benefit = AutodebetBenefit.objects.create(
            account_id=account.id,
            pre_assigned_benefit=benefit['type'],
        )
    existing_benefit.update_safely(
        benefit_type=benefit['type'],
        benefit_value=benefit['value'],
        is_benefit_used=False
    )

    if benefit_name == "cashback":
        cashback_earned = float(benefit['value'].replace('%', ''))
        customer = account.customer
        customer.change_wallet_balance(
            change_accruing=0,
            change_available=cashback_earned,
            reason='autodebet_payment',
            account_payment=account_payment
        )


def set_default_autodebet_benefit_control(account, vendor=None):
    autodebet_benefit_control_feature = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_BENEFIT_CONTROL,
        is_active=True
    )

    if not autodebet_benefit_control_feature:
        return

    benefit_value = autodebet_benefit_control_feature.parameters['cashback']
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)

    if existing_benefit:
        if existing_benefit.benefit_type == 'waive_interest':
            existing_benefit.update_safely(
                benefit_type='cashback',
                benefit_value=benefit_value
            )
            return

        existing_benefit.update_safely(
            benefit_value=benefit_value
        )
        return

    AutodebetBenefit.objects.create(
        account_id=account.id, benefit_type='cashback', benefit_value=benefit_value, vendor=vendor
    )


def get_random_benefit_autodebet_control():
    benefits = AutodebetBenefitConst.AUTODEBET_BENEFIT
    existing_benefits = AutodebetBenefitCounter.objects.filter(
        name__in=benefits
    ).order_by('rounded_count')
    benefit_name = ''
    if len(benefits) == len(existing_benefits):
        benefit_name = existing_benefits.first().name

    return benefit_name


def store_autodebet_benefit_control(account, account_payment, payment_id, benefit, value):
    phase = 'first'
    existing_autodebet_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
    AutodebetBenefitDetail.objects.create(
        autodebet_benefit=existing_autodebet_benefit,
        account_payment_id=account_payment.id,
        payment=payment_id,
        benefit_value=value,
        phase=existing_autodebet_benefit.phase
    )

    autodebet_benefit_control_feature = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_BENEFIT_CONTROL,
        is_active=True
    )

    update_benefit = dict()

    if existing_autodebet_benefit.phase == 'first':
        phase = 'second'
    elif existing_autodebet_benefit.phase == 'second':
        phase = 'third'
    elif existing_autodebet_benefit.phase == 'third':
        phase = 'third'
        update_benefit['is_benefit_used'] = True

    benefit_value = autodebet_benefit_control_feature.parameters[benefit['type']][phase]
    update_benefit['benefit_value'] = benefit_value
    update_benefit['phase'] = phase
    existing_autodebet_benefit.update_safely(**update_benefit)


def get_random_autodebet_benefit(account):
    benefits = construct_benefit_autodebet_list()
    if not benefits:
        return benefits, None, None

    benefit_name = "cashback"
    if not len(account.get_all_active_loan()):
        benefit_name_list = [benefit["type"] for benefit in benefits]
        existing_benefits = AutodebetBenefitCounter.objects.filter(
            name__in=benefit_name_list
        ).order_by('counter')
        benefit_name = "waive_interest"
        if len(benefit_name_list) == len(existing_benefits):
            benefit_name = existing_benefits.first().name
    else:
        autodebet_account = AutodebetAccount.objects.filter(
            account=account,
            is_use_autodebet=True,
            status=AutodebetStatuses.REGISTERED,
            vendor=AutodebetVendorConst.BRI
        ).last()
        if autodebet_account:
            benefit_name = 'waive_interest'

    benefit = next((benefit for benefit in benefits if benefit["type"] == benefit_name), None)
    return benefits, benefit_name, benefit


def construct_tutorial_benefit_data(account):
    return_response = {
        "registration": {"type": "video", "url": "Qtlo75XpL7Y"},
        "revocation": {"type": "video", "url": "JZFtQ_xDA0g"},
        "benefit": {"type": "image", "url": ""},
        "message": "",
    }
    tutorial_autodebet_bca_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.TUTORIAL_AUTODEBET_BCA, is_active=True
    ).last()
    if tutorial_autodebet_bca_feature_setting:
        parameters = tutorial_autodebet_bca_feature_setting.parameters
        return_response["registration"] = parameters["registration"]
        return_response["revocation"] = parameters["revocation"]

    success, benefit_name, benefit = get_autodebet_benefit_data(account)
    if not success:
        return return_response

    base_url = "https://julocampaign.julo.co.id/autodebet-bca/"
    if benefit:
        benefit_names = benefit_name.split("_") if benefit_name else [""]
        return_response["benefit"]["url"] = "{}AutoPayBCA-InAppCard-{}.png".format(
            base_url, benefit_names[0].capitalize()
        )
        return_response["message"] = benefit["message"]
    return return_response


def get_autodebet_benefit_data(account):
    benefit_autodebet_bca_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BENEFIT_AUTODEBET_BCA
    ).last()
    if not benefit_autodebet_bca_feature_setting:
        return False, None, None

    benefits = []
    for parameter in benefit_autodebet_bca_feature_setting.parameters:
        value = str(parameter["amount"])
        message = parameter["message"].format(display_rupiah(parameter["amount"]))
        if parameter["percentage"] and not parameter["amount"]:
            value = "{}%".format(parameter["percentage"])
            message = parameter["message"]
        benefit = {
            "type": parameter["type"],
            "value": value,
            "message": message,
        }
        benefits.append(benefit)

    existing_benefit = AutodebetBenefit.objects.filter(account_id=account.id).last()
    benefit = None
    if existing_benefit:
        benefit_name = existing_benefit.benefit_type
        benefit = next((benefit for benefit in benefits if benefit["type"] == benefit_name), None)

    if not benefit:
        _, benefit_name, benefit = get_random_autodebet_benefit(account)

    return True, benefit_name, benefit


def construct_tutorial_benefit_autodebet(vendor, account):
    active_feature_setting = FeatureSetting.objects.filter(
        feature_name=TutorialAutodebetConst.FEATURE_SETTING_NAME, is_active=True
    ).last()

    if not active_feature_setting:
        return

    return_response = active_feature_setting.parameters[vendor]
    success, benefit_name, benefit = get_autodebet_benefit_data(account)
    return_response["message"] = benefit["message"] if benefit else ""
    for ad_type in TutorialAutodebetConst.AUTODEBET_TYPES:
        if ad_type == 'benefit':
            for benefit_type in TutorialAutodebetConst.BENEFIT_TYPE:
                image_id = return_response[ad_type][benefit_type]['image_data']['id']
                if image_id:
                    image = Image.objects.get_or_none(id=image_id)
                    if image:
                        return_response[ad_type][benefit_type]['image_data']['type'] = \
                            image.image_url
                        return_response[ad_type][benefit_type]['image'] = image.image_url

        else:
            image_id = return_response[ad_type]['image_data']['id']
            if image_id:
                image = Image.objects.get_or_none(id=image_id)
                if image:
                    return_response[ad_type]['image_data']['type'] = image.image_url
                    return_response[ad_type]['image'] = image.image_url

        if success and ad_type == "benefit":
            return_response['benefit'] = return_response['benefit'][benefit_name]

    return return_response


def get_benefit_waiver_amount(account_payment):
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account_payment.account.id)
    if existing_benefit:
        if existing_benefit.benefit_type:
            benefit_types = existing_benefit.benefit_type.split("_")
            if benefit_types[0] == 'waive' and not existing_benefit.is_benefit_used:
                try:
                    benefit_value = ast.literal_eval(existing_benefit.benefit_value)
                    if type(benefit_value) != dict:
                        return 0
                except SyntaxError:
                    return 0

                waiver_percentage = float(benefit_value['percentage']) / float(100)
                remaining_amount = getattr(account_payment, "remaining_%s" % benefit_types[1])
                waiver_amount = math.ceil(float(waiver_percentage) * float(remaining_amount))
                waiver_max_amount = benefit_value['max']
                if waiver_amount >= waiver_max_amount:
                    waiver_amount = waiver_max_amount
                return waiver_amount
    return 0


def update_autodebet_benefit_vendor(account, vendor):
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id, vendor=None)
    if existing_benefit:
        existing_benefit.update_safely(vendor=vendor)


def update_not_eligible_benefit(account):
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
    if existing_benefit:
        existing_benefit.update_safely(is_benefit_used=True)


def is_eligible_to_get_benefit(account, is_split_payment=False):
    if is_split_payment:
        return False

    autodebet_benefit_control_feature = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_BENEFIT_CONTROL,
        is_active=True
    )

    if not autodebet_benefit_control_feature:
        return False

    date_now = datetime.now().date()

    if not autodebet_benefit_control_feature.parameters['campaign_duration']['start_date']\
            or not autodebet_benefit_control_feature.parameters['campaign_duration']['end_date']:
        return False

    campaign_duration_start_date = datetime.strptime(autodebet_benefit_control_feature.parameters[
        'campaign_duration']['start_date'], '%Y-%m-%d').date()
    campaign_duration_end_date = datetime.strptime(autodebet_benefit_control_feature.parameters[
        'campaign_duration']['end_date'], '%Y-%m-%d').date()

    late_account_payment = account.accountpayment_set.not_paid_active().filter(
        due_date__lt=date_now
    ).exists()

    if late_account_payment:
        return False

    if campaign_duration_start_date <= date_now <= campaign_duration_end_date:
        if AutodebetBenefit.objects.filter(account_id=account.id).exists():
            return True
    return False


def give_benefit(benefit, account, account_payment, payment_id=None):
    autodebet_benefit_control_feature = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_BENEFIT_CONTROL,
        is_active=True
    )

    if not autodebet_benefit_control_feature or not benefit:
        return

    if benefit.benefit_type == 'cashback':
        cashback_amount = autodebet_benefit_control_feature.parameters['cashback']
        account.customer.change_wallet_balance(change_accruing=0,
                                               change_available=int(cashback_amount),
                                               reason='autodebet_payment',
                                               account_payment=account_payment)
        AutodebetBenefitDetail.objects.create(
            autodebet_benefit=benefit,
            account_payment_id=account_payment.id,
            payment=payment_id,
            benefit_value=cashback_amount
        )
