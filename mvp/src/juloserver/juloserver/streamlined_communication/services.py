import logging
import os
import re
from typing import Tuple, Optional

from dateutil.relativedelta import relativedelta
from django.db.models import (
    Q,
    QuerySet,
    Count,
    Sum,
)
from django.template import Template, Context
from django.forms.models import model_to_dict
from babel.numbers import format_decimal


from PIL import Image as PILImage
from PIL import ImageFont, ImageDraw
from io import BytesIO
from juloserver.customer_module.services.customer_related import get_ongoing_account_deletion_request

import semver

from juloserver.account.constants import AccountConstant
from juloserver.autodebet.constants import FeatureNameConst, AutodebetStatuses, AutodebetVendorConst
from juloserver.cfs.constants import CfsProgressStatus
from juloserver.customer_module.services.device_related import (
    DeviceRepository,
    get_device_repository,
)
from juloserver.customer_module.services.view_related import (
    get_transaction_method_whitelist_feature,
    is_transaction_method_whitelist_user,
)
from juloserver.julo.constants import (
    ExperimentConst,
    FeatureNameConst as JuloFeatureNameConst,
    WorkflowConst,
    OnboardingIdConst,
)
from juloserver.julo.models import Customer
from juloserver.julo.services2 import (
    encrypt,
    get_redis_client,
)
from juloserver.julo.statuses import (
    JuloOneCodes,
    Statuses,
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
    CreditCardCodes,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.apiv2.models import PdCreditModelResult
from juloserver.julo.clients import (
    get_julo_pn_client,
    get_julo_sentry_client,
)
from juloserver.julo.models import (
    Image,
    MobileFeatureSetting,
    FeatureSetting,
    CreditMatrix,
    Application,
    ApplicationHistory,
    LoanHistory,
    PaymentMethod,
    PTP,
    Payment,
    ReferralSystem,
    Loan,
    RefereeMapping,
    ExperimentSetting,
    CreditMatrixProductLine,
    CreditScore,
    FDCInquiry,
    FDCInquiryLoan,
    ExperimentSetting,
    BankStatementSubmit,
)
from juloserver.julo_financing.services.core_services import is_julo_financing_product_id_valid
from juloserver.loan_selloff.models import LoanSelloff
from juloserver.minisquad.services import is_eligible_for_in_app_ptp
from juloserver.loan.services.loan_prize_chance import add_prize_chances_context
from juloserver.otp.constants import OTPType
from juloserver.julo.utils import (
    upload_file_to_oss,
    get_oss_public_url,
    display_rupiah,
)
from juloserver.payback.constants import GopayAccountStatusConst
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.streamlined_communication.cache import RedisCache
from juloserver.referral.services import show_referral_code
from juloserver.streamlined_communication.constant import (
    CardProperty,
    INAPP_RATING_POPUP_DAYS,
    CommunicationPlatform,
    PageType,
    RedisKey,
    J1_PRODUCT_DEEP_LINK_MAPPING_TRANSACTION_METHOD,
    Product,
    StatusReapplyForIOS,
    ListSpecificRuleStatus,
)
from juloserver.streamlined_communication.exceptions import StreamlinedCommunicationException, \
    ApplicationNotFoundException, MissionEnableStateInvalid
from juloserver.streamlined_communication.models import (
    Holiday,
    StreamlinedCommunication,
    PnAction,
    PushNotificationPermission,
    StreamlinedCommunicationParameterList,
    NeoBannerCard,
    AppDeepLink,
    NeoInfoCard,
)
from juloserver.portal.core import functions
from django.conf import settings
from django.utils import timezone
from datetime import timedelta, datetime
from babel.dates import format_date  # noqa
from babel.numbers import format_number  # noqa
from juloserver.account.models import (
    Account,
    ExperimentGroup,
)
from juloserver.autodebet.models import AutodebetAccount
from django.db.models import F, Max
from juloserver.streamlined_communication.utils import is_julo_financing_product_action
from juloserver.urlshortener.services import shorten_url
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.application_flow.services import (
    JuloOneService,
    pass_binary_check_scoring,
    is_hsfbp_hold_with_status,
)
from juloserver.application_form.models import IdfyVideoCall
from juloserver.application_form.constants import LabelFieldsIDFyConst
from juloserver.julo.constants import ExperimentConst
from juloserver.minisquad.utils import validate_activate_experiment, batch_list
from juloserver.autodebet.services.account_services import (
    construct_autodebet_feature_status,
    is_idfy_autodebet_valid,
    is_autodebet_feature_disable,
)
from juloserver.streamlined_communication.constant import (
    NeoBannerConst,
    NeoBannerStatusesConst,
)
from juloserver.tokopedia.constants import TokoScoreConst
from juloserver.application_flow.constants import ApplicationStatusExpired
from juloserver.ana_api.models import EligibleCheck, PdCustomerSegmentModelResult
from juloserver.application_form.constants import GoodFDCX100Const
from juloserver.fdc.constants import FDCLoanQualityConst
from juloserver.loyalty.services.services import check_loyalty_whitelist_fs
from juloserver.application_flow.services import (
    is_agent_assisted_submission_flow,
)
from juloserver.application_flow.constants import AgentAssistedSubmissionConst, HSFBPIncomeConst
from juloserver.application_form.utils import get_url_form_for_tnc
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.application_flow.models import ApplicationPathTagStatus, ApplicationPathTag
from juloserver.application_flow.services import rule_hsfbp_for_infocards

logger = logging.getLogger(__name__)


def process_streamlined_comm(filter_, replaced_data=None):
    streamlined_comm = StreamlinedCommunication.objects.get_or_none(**filter_)
    if not streamlined_comm:
        logger.error({
            'action': 'get message for streamlined communication',
            'request': replaced_data,
            'filter': filter_,
            'response': 'Streamlined Communication not found'
        })
        # because on the previous code if not maching with condition will return ""
        return ""

    message = streamlined_comm.message.message_content
    parameter = streamlined_comm.message.parameter
    if parameter and replaced_data:
        template = Template(message)
        message = template.render(Context(replaced_data))
    return message


def process_streamlined_comm_without_filter(streamlined_comm, available_context):
    message = streamlined_comm.message.message_content
    template = Template(message)
    message = template.render(Context(available_context))
    return message


def process_streamlined_comm_context_base_on_model(streamlined_comm, models):
    context = model_to_dict(models)
    message = streamlined_comm.message.message_content
    template = Template(message)
    message = template.render(Context(context))
    return message


def process_streamlined_comm_context_base_on_model_and_parameter(
        streamlined_comm, models, is_with_header=False):
    context = {}
    message = streamlined_comm.message.message_content
    parameters = streamlined_comm.message.parameter
    for parameter in parameters:
        if hasattr(models, parameter):
            key = "models.{}".format(parameter)
            context[parameter] = eval(key)
            if parameter == 'current_balance' and context[parameter]:
                context[parameter] = format_decimal(context[parameter], locale='id_ID')
        if parameter == 'fullname':
            context[parameter] = models.loan.application.full_name_only

    template = Template(message)
    message = template.render(Context(context))
    if is_with_header:
        template_header = Template(streamlined_comm.heading_title)
        heading_title = template_header.render(Context(context))
        return message, heading_title

    return message


def process_streamlined_comm_email_subject(subject_title, context):
    template = Template(subject_title)
    rendered_subject = template.render(Context(context))
    return rendered_subject


def get_pn_action_buttons(streamlined_communication_id):
    pn_actions = PnAction.objects.filter(
        streamlined_communication_id=streamlined_communication_id)

    pn_action_buttons = []
    for pn_action in pn_actions:
        pn_action_buttons.append({
            "id": pn_action.id,
            "order": pn_action.order,
            "title": pn_action.title,
            "action": pn_action.action,
            "target": pn_action.target
        })

    return pn_action_buttons


def process_convert_params_to_data(message, available_context):
    template = Template(message)
    message = template.render(Context(available_context))
    return message


def format_info_card_data(qs):
    data = []
    for streamline_comm in qs:
        content = streamline_comm.message
        info_card_property = content.info_card_property
        customer_data = '-'
        expiration_option_data = ""
        if streamline_comm.dpd or streamline_comm.dpd == 0:
            customer_data = 'dpd:{}'.format(streamline_comm.dpd)
        elif streamline_comm.dpd_lower or streamline_comm.dpd_lower == 0:
            if streamline_comm.dpd_upper or streamline_comm.dpd_upper == 0:
                customer_data = 'dpd:{}-{}'.format(streamline_comm.dpd_lower,
                                                   streamline_comm.dpd_upper)
            elif streamline_comm.until_paid:
                customer_data = 'dpd:{}-paid'.format(streamline_comm.dpd_lower)
        if streamline_comm.expiration_option:
            expiration_option_data = streamline_comm.expiration_option
            if streamline_comm.expiry_period:
                expiration_option_data += '\n\nExpiry Period={} {}'.format(
                    streamline_comm.expiry_period,
                    streamline_comm.expiry_period_unit)

        item = dict(
            id=streamline_comm.id,
            card_type_id=info_card_property.card_type,
            card_type=CardProperty.CARD_TYPE.get(info_card_property.card_type),
            title=info_card_property.title,
            content=content.message_content,
            parameter=content.parameter,
            template_code=streamline_comm.template_code,
            is_active=streamline_comm.is_active,
            card_order_number=info_card_property.card_order_number,
            customer_data=customer_data,
            expiration_option_data=expiration_option_data

        )
        buttons_display = ''
        for button in info_card_property.button_list:
            buttons_display += "{} - {}\n".format(
                button.button_name, button.destination)

        item['buttons'] = buttons_display
        data.append(item)
    return data


def create_and_upload_image_assets_for_streamlined(
        image_source_id, image_type, image_file, image_prefix=None, is_update=False):
    _, file_extension = os.path.splitext(image_file.name)

    image_name = image_type if not image_prefix else image_prefix
    if not is_update:
        remote_path = 'info-card/{}_{}{}'.format(image_name, image_source_id, file_extension)
        image = Image()
        image.image_source = image_source_id
        image.image_type = image_type
        image.url = remote_path
        image.save()
    else:
        today = timezone.localtime(timezone.now())
        remote_path = 'info-card/{}_{}_{}{}'.format(
            image_name, image_source_id, today.strftime("%d%m%Y%H%M%S"), file_extension)
        image = Image.objects.filter(
            image_source=image_source_id, image_type=image_type).last()
        # for prevent update but dont have image because image is not mandatory
        if image:
            image.update_safely(url=remote_path)
        else:
            image = Image()
            image.image_source = image_source_id
            image.image_type = image_type
            image.url = remote_path
            image.save()

    file = functions.upload_handle_media(image_file, "info-card")
    if file:
        upload_file_to_oss(
            settings.OSS_PUBLIC_ASSETS_BUCKET,
            file['file_name'],
            remote_path
        )
        return True

    return False


def format_info_card_for_android(streamlined_communication, available_context, account_id=None):
    streamlined_message = streamlined_communication.message
    info_card_property = streamlined_message.info_card_property
    card_type = info_card_property.card_type[0]
    button_list = info_card_property.button_list
    formated_buttons = []
    for button in button_list:
        formated_buttons.append(
            {
                "colour": '',
                "text": button.text,
                "textcolour": button.text_color,
                "action_type": button.action_type,
                "destination": button.destination,
                "border": None,
                "background_img": button.background_image_url
            }
        )

    extra_conditions = streamlined_communication.extra_conditions
    card_destination = info_card_property.card_destination
    if extra_conditions == JuloFeatureNameConst.MARKETING_LOAN_PRIZE_CHANCE:
        card_destination = add_prize_chances_context(card_destination, available_context)

    if extra_conditions == CardProperty.CASHBACK_CLAIM and account_id:
        encrypttext = encrypt()
        account_id_encrypted = encrypttext.encode_string(str(account_id))
        card_destination += account_id_encrypted

    text_content = process_convert_params_to_data(
        streamlined_message.message_content,
        available_context
    )

    if "loan_sphp_exp_date_day" in available_context:
        text_content = process_convert_params_to_data(
            streamlined_message.message_content.format(
                expired_day=available_context["loan_sphp_exp_date_day"]
            ),
            available_context
        )

    formated_data = dict(
        type=card_type,
        streamlined_communication_id=streamlined_communication.id,
        title={
            "colour": info_card_property.title_color,
            "text": process_convert_params_to_data(
                info_card_property.title, available_context)
        },
        content={
            "colour": info_card_property.text_color,
            "text": text_content
        },
        button=formated_buttons,
        border=None,
        background_img=info_card_property.card_background_image_url,
        image_icn=info_card_property.card_optional_image_url,
        card_action_type=info_card_property.card_action,
        card_action_destination=card_destination,
        youtube_video_id=info_card_property.youtube_video_id
    )
    return formated_data


def is_already_have_transaction(customer):
    account = customer.account
    transaction_account = AccountPayment.objects.filter(
        account=account
    ).count()
    if transaction_account > 0:
        return True
    else:
        return False


def checking_rating_shown(application):
    """
    Rule definition: https://juloprojects.atlassian.net/browse/CLS3-105
    In-app pop up rating and review will be appear to the customers
    who has oldest account payment status 330, 331, & 332.
    """
    today = timezone.localtime(timezone.now()).date()
    redis_cache = RedisCache(
        f'streamlined_communication::checking_rating_shown::{application.customer_id}', days=30)

    # make sure that the application is has an account
    # to prevent null query.
    if (
            application.account_id is None
            or application.account.status_id not in AccountConstant.UNLOCK_STATUS
            or application.customer.is_review_submitted
    ):
        return False

    oldest_account_payment = AccountPayment.objects.filter(
        account_id=application.account_id).order_by('cdate').first()
    is_shown = (
            oldest_account_payment
            and oldest_account_payment.status_id in PaymentStatusCodes.paid_status_codes_without_sell_off()
    )
    if not is_shown:
        return False

    # Return true if the function is called at the same day
    # return false if the cache is exists and the function is called at different day
    cache_value = redis_cache.get()
    if cache_value:
        return str(today) == cache_value

    redis_cache.set(str(today))
    return is_shown


def is_info_card_expired(streamlined_communication, application, loan=None):
    datetime_now = timezone.localtime(timezone.now())
    start_date = ""
    if streamlined_communication.expiration_option == "Triggered by - Customer Entered Status & Condition":
        info_card_status = streamlined_communication.status_code_id
        if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED and loan:
            if info_card_status == loan.status:
                loan_history = LoanHistory.objects.filter(
                    loan=loan,
                    status_new__in=[loan.status]
                ).order_by("cdate").last()
                start_date = loan_history.cdate
        else:
            application_history = ApplicationHistory.objects.filter(
                application=application, status_new=application.application_status_id
            ).order_by("cdate").last()
            start_date = application_history.cdate

    elif streamlined_communication.expiration_option == "Triggered by - Campaign Creation Date":
        start_date = streamlined_communication.cdate
    else:
        return False

    if start_date:
        if streamlined_communication.expiry_period_unit == "days":
            end_time = timedelta(days=streamlined_communication.expiry_period)
        else:
            end_time = timedelta(hours=streamlined_communication.expiry_period)
        expiry_datetime = start_date + end_time

        if datetime_now < expiry_datetime:
            return False
    else:
        return False

    return True


def process_pn_logging(customer, request_data):
    account = customer.account
    latest_pn_log = PushNotificationPermission.objects.filter(
        customer=customer, account=account
    ).order_by('cdate').last()

    # Extracting the data from the request
    fe_is_pn_permission = request_data['is_pn_permission']
    fe_is_do_not_disturb = request_data['is_do_not_disturb']
    feature_name = request_data.get('feature_name', '')

    # Check if there are no changes in the push notification permissions
    if (
        latest_pn_log
        and latest_pn_log.is_pn_permission == fe_is_pn_permission
        and latest_pn_log.is_do_not_disturb == fe_is_do_not_disturb
        and latest_pn_log.feature_name == feature_name
    ):
        return {"message": "No Change Detected"}

    PushNotificationPermission.objects.create(
        customer=customer,
        account=account,
        is_pn_permission=fe_is_pn_permission,
        is_do_not_disturb=fe_is_do_not_disturb,
        feature_name=feature_name,
    )

    return {"message": "Success Insert new row on Push Notification Logging"}


def process_streamlined_comm_context_for_ptp(payment_or_account_payment,
                                             application,
                                             is_account_payment):
    primary_va_name = ""
    primary_va_number = ""
    payment_method_filter = {'is_primary': True}
    if is_account_payment:
        application = payment_or_account_payment.account.application_set.last()
        payment_method_filter['customer'] = application.customer

    else:
        application = payment_or_account_payment.loan.application
        payment_method_filter['loan'] = payment_or_account_payment.loan

    due_amount = payment_or_account_payment.due_amount
    fullname = application.full_name_only
    first_name = application.first_name_only
    short_title = application.bpk_ibu
    title = application.gender_title
    ptp_amount = payment_or_account_payment.ptp_amount

    payment_method = PaymentMethod.objects.filter(**payment_method_filter).last()
    if payment_method:
        primary_va_name = payment_method.payment_method_name
        primary_va_number = payment_method.virtual_account
    due_date = format_date(payment_or_account_payment.due_date, 'd-MMM-yyyy', locale='id_ID')
    ptp_date = format_date(payment_or_account_payment.ptp_date, 'd-MMM-yyyy', locale='id_ID')
    short_ptp_date = format_date(payment_or_account_payment.ptp_date, 'd/M', locale='id_ID')
    available_context = {
        'due_amount': display_rupiah(due_amount),
        'due_date': due_date,
        'ptp_amount': display_rupiah(ptp_amount),
        'ptp_date': ptp_date,
        'primary_va_name': primary_va_name,
        'primary_va_number': primary_va_number,
        'firstname': first_name,
        'fullname': fullname,
        'short_title': short_title,
        'title': title,
        'short_ptp_date': short_ptp_date
    }

    return available_context


def is_ptp_payment_already_paid(payment_id, ptp_date, is_account_payment=False):
    paid_ptp_status = ['Paid', 'Paid after ptp date']
    if is_account_payment:
        payment_or_account_payment = AccountPayment.objects.get_or_none(id=payment_id)
        ptp = PTP.objects.filter(account_payment=payment_or_account_payment, ptp_date=ptp_date)
    else:
        payment_or_account_payment = Payment.objects.get_or_none(id=payment_id)
        ptp = PTP.objects.filter(payment=payment_or_account_payment, ptp_date=ptp_date)

    ptp_count = ptp.filter(
        ptp_status__in=paid_ptp_status).count()

    if ptp_count > 0:
        return True
    else:
        return False


def process_sms_message_j1(message, model, is_have_account_payment=False):
    encrypttext = encrypt()
    encoded_payment_id = encrypttext.encode_string(str(model.id))
    url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
    shortened_url = ''
    if is_have_account_payment:
        shortened_url = shorten_url(url)
        shortened_url = shortened_url.replace('https://', '')

    available_context = {
        'sms_payment_details_url': shortened_url
    }
    sms_parameters = StreamlinedCommunicationParameterList.objects.filter(
        platform=CommunicationPlatform.SMS,
    )
    order_payment_methods_feature = FeatureSetting.objects.filter(
        feature_name=JuloFeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
    ).last()

    for sms_parameter in sms_parameters:
        if not sms_parameter.parameter_model_value:
            continue

        value_from = sms_parameter.parameter_model_value.get(
            type(model).__name__.lower())
        if not value_from:
            continue

        try:
            final_value = eval(value_from)
            if sms_parameter.parameter_name == '{{sms_primary_va_name}}':
                payment_groups = {
                    'e_wallet_group': 'e-wallet',
                    'retail_group': 'gerai',
                    'bank_va_group': 'VA',
                    'direct_debit_group': 'direct debit',
                }

                for group, prefix in payment_groups.items():
                    if final_value.lower() in order_payment_methods_feature.parameters.get(
                        group, []
                    ):
                        final_value = prefix + ' ' + final_value
                        final_value = (
                            final_value.replace('Bank ', '')
                            .replace(' Biller', '')
                            .replace(' Tokenization', '')
                        )

            format_value = sms_parameter.parameter_model_value.get('format_value')
            if format_value:
                final_value = eval(format_value.format(value_from))

            available_context[sms_parameter.replace_symbols] = final_value
        except Exception:
            continue
    template = Template(message)
    message = template.render(Context(available_context))
    return message


def is_first_time_user_paid_for_first_installment(application):
    customer = application.customer
    if not customer:
        return False

    is_referral_used = RefereeMapping.objects.filter(
        referrer_id=customer.id
    )

    if is_referral_used:
        return False

    referral_system = ReferralSystem.objects.filter(
        name='PromoReferral', is_active=True).first()

    if not referral_system:
        return False

    account = application.account

    if not account:
        return False

    application_count = account.application_set.filter(
        application_status_id__gte=ApplicationStatusCodes.LOC_APPROVED
    ).count()

    # check first apply
    if application_count != 1:
        return False

    loan_count = Loan.objects.filter(
        account=account,
        loan_status__gte=LoanStatusCodes.PAID_OFF).count()

    # check paid first installment
    if loan_count < 1:
        return False

    return True


def validate_action(customer, action_type):
    from juloserver.julo_starter.services.services import user_have_upgrade_application
    from juloserver.cfs.services.core_services import get_mission_enable_state
    from juloserver.promo.services import is_eligible_promo_entry_page
    from juloserver.julo_starter.services.services import determine_application_for_credit_info

    is_valid = False
    response = {"isValid": is_valid}
    application = determine_application_for_credit_info(customer)
    if not application:
        raise ApplicationNotFoundException

    if action_type.lower() == PageType.CFS:
        mission_enable_state = get_mission_enable_state(application)
        if not mission_enable_state:
            raise MissionEnableStateInvalid

        is_valid = True
        response['isValid'] = is_valid
    elif action_type.lower() == PageType.REFERRAL:
        is_valid = show_referral_code(customer)
        response['isValid'] = is_valid
    elif action_type.lower() == PageType.AUTODEBET_BCA_WELCOME:
        is_valid, response = autodebet_deeplink(customer, FeatureNameConst.WHITELIST_AUTODEBET_BCA)
    elif action_type.lower() == PageType.AUTODEBET_BRI_WELCOME:
        is_valid, response = autodebet_deeplink(customer, FeatureNameConst.WHITELIST_AUTODEBET_BRI)
    elif action_type.lower() == PageType.JULO_SHOP:
        from juloserver.loan.services.loan_related import is_product_locked
        account = customer.account
        if (not is_product_locked(account, TransactionMethodCode.E_COMMERCE)
                and application.has_master_agreement()):
            is_valid = True
        response = {
            'isValid': is_valid
        }
        return True, response
    elif action_type.lower() == PageType.OVO_TAGIHAN_PAGE:
        is_valid, response = ovo_deeplink(customer)
    elif action_type.lower() == PageType.TURBO_DEEPLINK_UPGRADE_FORM:
        app, has_upgrade = user_have_upgrade_application(customer)
        is_valid = not has_upgrade
        response = {
            'isValid': is_valid
        }
    elif action_type.lower() == PageType.TURBO_ADDITIONAL_FORM:
        is_valid = not application.has_submit_extra_form()
        response = {
            'isValid': is_valid
        }
    elif (action_type.lower() == PageType.TARIK_DANA.lower() or
          action_type.lower() == PageType.PRODUCT_TRANSFER_SELF or
          action_type.lower() == PageType.NAV_INAPP_PRODUCT_TRANSFER_OTHER):
        # validate PN transaction must signed agreement
        response = {
            'isValid': application.has_master_agreement()
        }
        return True, response
    elif action_type.lower() == PageType.JULO_CARD_HOME_PAGE:
        is_valid = True
        response = {
            'isValid': julo_card_home_page_deeplink(application)
        }
    elif action_type.lower() == PageType.CASHBACK:
        is_valid, response = cashback_deeplink(customer)
    elif is_julo_card_transaction_completed_action(action_type.lower()):
        loan_xid = action_type.lower().split('/')[1]
        is_valid = True
        response = {
            'isValid': Loan.objects.filter(
                loan_xid=loan_xid, transaction_method_id=TransactionMethodCode.CREDIT_CARD
            ).exists()
        }
    elif action_type.lower() == PageType.JULO_CARD_CHOOSE_TENOR:
        is_valid = True
        datetime_5_minutes_ago = timezone.localtime(timezone.now()) - timedelta(minutes=5)
        response = {
            'isValid': Loan.objects.filter(
                customer_id=application.customer_id,
                transaction_method_id=TransactionMethodCode.CREDIT_CARD,
                cdate__gte=datetime_5_minutes_ago,
                loan_status_id=LoanStatusCodes.INACTIVE
            ).exists()
        }
    elif action_type.lower() == PageType.GOPAY_LINKING:
        is_valid, response = gopay_account_link_deeplink(application)
    elif action_type.lower() == PageType.GOPAY_PAYMENT:
        is_valid, response = gopay_repayment_deeplink(application)
    elif action_type.lower() == PageType.DANA_LINK:
        is_valid, response = dana_account_link_deeplink(application)
    elif action_type.lower() in J1_PRODUCT_DEEP_LINK_MAPPING_TRANSACTION_METHOD:
        is_valid = is_eligible_for_deep_link(
            application, J1_PRODUCT_DEEP_LINK_MAPPING_TRANSACTION_METHOD[action_type.lower()]
        )
        response = {
            'isValid': is_valid,
        }
    elif action_type.lower() == PageType.PROMO_ENTRY_PAGE:
        is_valid = is_eligible_promo_entry_page(application)
        response['isValid'] = is_valid
    elif action_type.lower() in [PageType.UPLOAD_SALARY_SLIP, PageType.UPLOAD_BANK_STATEMENT]:
        mission_enable_state = get_mission_enable_state(application)
        if not mission_enable_state:
            raise MissionEnableStateInvalid

        is_valid = is_eligible_for_payslip_and_bank_statement_deeplink(
            application, action_type.lower()
        )
        response['isValid'] = is_valid
    elif action_type.lower() == PageType.IN_APP_PTP:
        is_valid, _, _, _ = is_eligible_for_in_app_ptp(customer.account)
        response['isValid'] = is_valid
    elif action_type.lower() == PageType.CHANGE_DATA_PRIVACY:
        last_app = customer.last_application
        if last_app.status != ApplicationStatusCodes.LOC_APPROVED:
            return False, {'isValid': False}
        return True, {'isValid': True}
    elif action_type.lower() == PageType.CHANGE_PHONE_NUMBER:
        is_valid = is_eligible_for_change_phone_number_deeplink(customer)
        if not is_valid:
            return False, {'isValid': False}
        return True, {'isValid': True}
    elif action_type.lower() == PageType.LOYALTY_HOMEPAGE:
        is_valid = is_eligible_for_loyalty_deeplink(customer)
        response['isValid'] = is_valid
    elif action_type.lower() == PageType.AUTODEBET_IDFY:
        is_valid = is_idfy_autodebet_valid(customer.account)
        return True, {'isValid': is_valid}
    elif action_type.lower() == PageType.CHECKOUT:
        is_valid = customer.loan_set.filter(
            loan_status__gte=LoanStatusCodes.CURRENT,
            loan_status__lt=LoanStatusCodes.PAID_OFF,
        ).exists()
        return is_valid, {'isValid': is_valid}
    elif is_julo_financing_product_action(action_type.lower()):
        product_id = action_type.lower().split('/')[1]
        is_valid = is_julo_financing_product_id_valid(int(product_id))
        response['isValid'] = is_valid
    elif action_type.lower() in [
        PageType.DANA_AUTODEBET,
        PageType.BCA_AUTODEBET,
        PageType.BNI_AUTODEBET,
        PageType.BRI_AUTODEBET,
        PageType.MANDIRI_AUTODEBET,
        PageType.OVO_AUTODEBET,
        PageType.GOPAY_AUTODEBET,
    ]:
        is_valid, response = onboarding_autodebet_deeplink(customer)
        return is_valid, response
    else:
        # For other action that don't have logic, It always success.
        return True, {'isValid': True}

    return is_valid, response


def filter_streamlined_based_on_partner_selection(streamlined, queryset):
    if not queryset:
        return queryset
    action = streamlined.partner_selection_action
    partners_selection_list = streamlined.partner_selection_list
    if action and partners_selection_list:
        if queryset.model is Application:
            if action == 'include':
                queryset = queryset.filter(partner_id__in=partners_selection_list)
            elif action == 'exclude':
                queryset = queryset.exclude(partner_id__in=partners_selection_list)
        elif queryset.model is AccountPayment:
            # Add specific condition, is communication platform == sms
            if streamlined.communication_platform.lower() == OTPType.SMS:
                if action == 'include':
                    queryset = queryset.extra(where=['"application"."partner_id" IN %s'],
                                              params=[tuple(partners_selection_list)])
                elif action == 'exclude':
                    queryset = queryset.extra(
                        where=['("application"."partner_id" NOT IN %s OR "application"."partner_id" IS NULL)'],
                        params=[tuple(partners_selection_list)])
            else:
                qs_ids = queryset.annotate(
                    last_application_id=Max('account__application')).filter(
                    account__application=F('last_application_id'),
                    account__application__partner_id__in=partners_selection_list). \
                    values_list('id', flat=True)
                if action == 'include':
                    queryset = queryset.filter(id__in=qs_ids)
                elif action == 'exclude':
                    queryset = queryset.exclude(id__in=qs_ids)
        elif queryset.model is Payment:
            if action == 'include':
                queryset = queryset.filter(loan__application__partner_id__in=partners_selection_list)
            elif action == 'exclude':
                queryset = queryset.exclude(loan__application__partner_id__in=partners_selection_list)
    return queryset


def render_kaliedoscope_image_as_bytes(data):
    if data.get('on_time_image') is True:
        url = settings.STATICFILES_DIRS[0] + '/images/email/kaliedoscope_2021_1.png'
    else:
        url = settings.STATICFILES_DIRS[0] + '/images/email/kaliedoscope_2021_2.png'
    img = PILImage.open(url)
    draw = ImageDraw.Draw(img)
    nunito_bold = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Nunito-Bold.ttf", 50)
    nunito_black = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Nunito-Black.ttf", 50)
    montserrat_small = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Montserrat-Black.ttf", 82)
    montserrat = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Montserrat-ExtraBold.ttf", 95)
    draw.text((130, 350), data['name_with_title'], (255, 255, 255), font=montserrat_small)
    draw.text((867, 645), data['most_used_transaction_method'], (255, 255, 255), font=nunito_black)
    draw.text((1350, 1370), data['total_amount_paid'], (19, 99, 123), font=nunito_bold)
    draw.text((1500, 3025), data['customer_referred_count'] + ' orang', (19, 99, 123), font=nunito_bold)
    draw.text((635, 3310), data['referral_code'], (255, 255, 255), font=montserrat)
    # img.save('test_content.png', "png")
    memf = BytesIO()
    img.save(memf, "png")
    return memf.getvalue()


def process_partner_sms_message(message, model):
    available_context = {}
    sms_parameters = StreamlinedCommunicationParameterList.objects.filter(
        platform=CommunicationPlatform.SMS, is_ptp=False
    )

    for sms_parameter in sms_parameters:
        if not sms_parameter.parameter_model_value:
            continue

        value_from = sms_parameter.parameter_model_value.get(
            type(model).__name__.lower())
        if not value_from:
            continue
        try:
            final_value = eval(value_from)
            if final_value is None:
                final_value = ''

            format_value = sms_parameter.parameter_model_value.get('format_value')
            if format_value:
                final_value = eval(format_value.format(value_from))

            available_context[sms_parameter.replace_symbols] = final_value
        except Exception:
            continue

    template = Template(message)
    message = template.render(Context(available_context))
    return message


def exclude_experiment_excellent_customer_from_robocall(account_payments, record_type=None):
    if not account_payments:
        return account_payments
    today_date = timezone.localtime(timezone.now()).date()
    excellent_customer_experiment = ExperimentSetting.objects.filter(
        is_active=True, code=ExperimentConst.EXCELLENT_CUSTOMER_EXPERIMENT
    ).filter(
        (Q(start_date__date__lte=today_date) & Q(end_date__date__gte=today_date))
        | Q(is_permanent=True)
    ).last()
    if not excellent_customer_experiment:
        return account_payments

    last_month_date = today_date - relativedelta(months=1)
    last_3_month_date = today_date - relativedelta(months=3)
    # checking excellent customer
    """
    checking number 1
        Customer paid payments with extra condition of:
            If in last three months early (prior to due date <= t-1)
            Customer paid all due payments in full (only for paid off account payments)
    """
    excellent_customer_account_payments = account_payments.extra(
        where=["(select count(1) from ops.account_payment as ap where "
               "ap.account_id = account_payment.account_id and ap.due_date >= "
               "%s and ap.status_code = %s and ap.due_date < account_payment.due_date and "
               "(ap.paid_date - ap.due_date) <= -1"
               ") > 0"
               ],
        params=[last_3_month_date, PaymentStatusCodes.PAID_ON_TIME]
    )
    if not excellent_customer_account_payments:
        return account_payments
    """
    next checking
        Customer has pgood > 90% (Pgood). We can refer to ana.pd_credit_model_result.pgood
        Customer was NOT graduated last month. Using account_id go to ops.account_limit and then
        go check the affordability_history_id and then check if reason = manual graduation.
    """
    excellent_customer_account_payments = excellent_customer_account_payments.filter(
        account__accountproperty__pgood__gt=float(0.9),
    )
    if not excellent_customer_account_payments:
        return account_payments

    last_month_manual_graduation_account_payment_ids = excellent_customer_account_payments.filter(
        account__application__affordabilityhistory__reason='manual graduation',
        account__application__affordabilityhistory__cdate__date__gte=last_month_date
    ).values_list('id', flat=True)

    excellent_customer_account_payments = excellent_customer_account_payments.exclude(
        id__in=list(last_month_manual_graduation_account_payment_ids)
    )
    if not excellent_customer_account_payments:
        return account_payments
    # separate control and test group
    test_group_criteria = excellent_customer_experiment.criteria['account_id'].split(':')
    test_group_last_digit = test_group_criteria[1]
    test_group_eligible_digit = tuple(test_group_criteria[2].split(','))
    test_group_account_ids = excellent_customer_account_payments.extra(
        where=["left(right(account_payment.account_id::text, %s), 1) in %s"],
        params=[test_group_last_digit, test_group_eligible_digit]
    ).values_list('account_id', flat=True)
    control_group_account_ids = excellent_customer_account_payments.exclude(
        account_id__in=list(test_group_account_ids)
    ).values_list('account_id', flat=True)
    # set to redis and save the data to experiment account tabel
    if record_type:
        redis_client = get_redis_client()
        if test_group_account_ids:
            redis_client.set_list(
                RedisKey.EXCELLENT_CUSTOMER_ACCOUNT_IDS_TEST_GROUP.format(record_type),
                test_group_account_ids
            )
        if control_group_account_ids:
            redis_client.set_list(
                RedisKey.EXCELLENT_CUSTOMER_ACCOUNT_IDS_CONTROL_GROUP.format(record_type),
                control_group_account_ids
            )
    return account_payments.exclude(
        account_id__in=test_group_account_ids
    )


def get_loan_info_card(loan):
    account = loan.account
    loan_cards_qs = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.INFO_CARD,
        status_code_id=loan.status,
        is_active=True
    )

    account_limit = account.get_account_limit
    account_property = account.accountproperty_set.last()
    if account_limit and account_property.concurrency and \
            loan.status == LoanStatusCodes.CURRENT and \
            account_limit.available_limit >= CardProperty.EXTRA_220_LIMIT_THRESHOLD:

        loan_cards_qs = loan_cards_qs.filter(
            extra_conditions=CardProperty.LIMIT_GTE_500
        )
    else:
        loan_cards_qs = loan_cards_qs.filter(extra_conditions__isnull=True)

    return list(loan_cards_qs.order_by('message__info_card_property__card_order_number'))


def autodebet_deeplink(customer, feature):
    response = {
        'isValid': False
    }
    whitelist_autodebet_feature = FeatureSetting.objects.filter(
        feature_name=feature,
        is_active=True
    ).last()
    application = Application.objects.filter(
        customer=customer,
        application_status_id=190
    ).last()
    account = Account.objects.filter(
        customer=customer,
        status=420
    ).last()
    autodebet_account = AutodebetAccount.objects.filter(
        account=account
    ).last()

    if not autodebet_account:
        response['isValid'] = True
    elif not autodebet_account.is_use_autodebet:
        if autodebet_account.status in [AutodebetStatuses.REVOKED,
                                        AutodebetStatuses.FAILED_REGISTRATION]:
            if application and account:
                if whitelist_autodebet_feature:
                    if application.id in whitelist_autodebet_feature.parameters["applications"]:
                        response['isValid'] = True
                else:
                    response['isValid'] = True

    return True, response


def ovo_deeplink(customer):
    response = {
        'isValid': False
    }
    valid_account_status = [420, 421, 430]

    application = Application.objects.filter(
        customer=customer,
        application_status_id=190
    ).last()
    account = Account.objects.filter(
        customer=customer,
        status__in=valid_account_status
    ).last()

    if application and account:
        response['isValid'] = True

    return True, response


def cashback_deeplink(customer):
    response = {
        'isValid': False
    }
    valid_account_status = [
        AccountConstant.STATUS_CODE.active,
        AccountConstant.STATUS_CODE.active_in_grace,
        AccountConstant.STATUS_CODE.suspended]

    application = Application.objects.filter(
        customer=customer,
        application_status_id=ApplicationStatusCodes.LOC_APPROVED
    ).last()
    account = Account.objects.filter(
        customer=customer,
        status__in=valid_account_status
    ).last()

    if application and account:
        response['isValid'] = True

    return True, response


def is_holiday(date: Optional[datetime] = None) -> bool:
    """
    Check if a given date is in the holiday.

    Args:
        date (Optional[datetime]): Date to be checked.

    Returns:
        bool: Returns True if it is holiday.
    """
    if date is None:
        date = datetime.now().date()

    return Holiday.objects.filter(
        Q(holiday_date=date) |
        Q(holiday_date__month=date.month, holiday_date__day=date.day, is_annual=True)
    ).exists()


def julo_card_home_page_deeplink(application: Application) -> bool:
    from juloserver.credit_card.services.registration_related import (
        application_eligible_credit_card,
    )
    from juloserver.credit_card.services.card_related import is_julo_card_whitelist_user
    from juloserver.cfs.services.core_services import check_lock_by_customer_tier
    from juloserver.loan.services.loan_related import _is_julo_one_product_locked_by_setting
    from juloserver.loan.constants import LoanJuloOneConstant

    account = application.account
    if _is_julo_one_product_locked_by_setting(account, LoanJuloOneConstant.CREDIT_CARD):
        return False
    elif not application_eligible_credit_card(application, account):
        return False
    elif check_lock_by_customer_tier(account, TransactionMethodCode.CREDIT_CARD.code):
        return False
    elif not is_julo_card_whitelist_user(application.id):
        return False
    return True


def render_kaliedoscope22_image_as_bytes(data):
    url = settings.STATICFILES_DIRS[0] + '/images/email/kaliedoscope_2022.png'
    img = PILImage.open(url)
    draw = ImageDraw.Draw(img)
    nunito_bold = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Nunito-Bold.ttf", 35)
    nunito_bold_ref = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Nunito-Bold.ttf", 35)
    nunito_black = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Nunito-Black.ttf", 22)
    montserrat_small = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Montserrat-Black.ttf", 30)
    montserrat = ImageFont.truetype(settings.BASE_DIR + "/misc_files/fonts/Montserrat-ExtraBold.ttf", 40)
    draw.text((72, 750), data['name_with_title'], (19, 99, 123), font=montserrat_small)
    draw.text((485, 950), data['most_used_transaction_method'], (255, 255, 255), font=nunito_black)
    draw.text((635, 1390), data['total_amount_paid'], (19, 99, 123), font=nunito_bold)
    draw.text((781, 1790), data['customer_referred_count'] + ' orang', (19, 99, 123), font=nunito_bold_ref)
    draw.text((375, 1970), data['referral_code'], (255, 255, 255), font=montserrat)
    img.save('test_content.png', "png")
    memf = BytesIO()
    img.save(memf, "png")
    return memf.getvalue()


class PushNotificationService:
    """
    A service class with the responsibility is to send a PN.
    This is middle-layer service that relies on internal data type or model.
    """

    def __init__(self, pn_client, device_repo: DeviceRepository):
        """
        Args:
            pn_client (juloserver.julo.clients.pn.JuloPNClient):
            device_repo (juloserver.customer_module.services.device_related.DeviceRepository):
        """
        self.pn_client = pn_client
        self.device_repo = device_repo

    def send_pn(
            self,
            streamlined_communication: StreamlinedCommunication,
            customer_id: int,
            extra_data: dict = None,
    ):
        fcm_id = self.device_repo.get_active_fcm_id(customer_id)
        if fcm_id is None:
            raise StreamlinedCommunicationException(
                'No FCM ID for the registered customer [{}].'.format(customer_id),
            )

        notification_data = {'customer_id': customer_id}
        if extra_data:
            notification_data.update(extra_data)

        return self.pn_client.send_downstream_message(
            registration_ids=[fcm_id],
            data=self._construct_pn_data(streamlined_communication),
            template_code=streamlined_communication.template_code,
            notification=notification_data,
        )

    def _construct_pn_data(self, streamlined_communication: StreamlinedCommunication):
        return {
            "title": streamlined_communication.subject,
            "body": streamlined_communication.message.message_content,
        }


def get_push_notification_service():
    return PushNotificationService(
        pn_client=get_julo_pn_client(),
        device_repo=get_device_repository(),
    )


def upload_image_assets_for_streamlined_pn(path_string, image_source_id, image_type, upload_to,
                                           image_file):
    today = timezone.localtime(timezone.now())
    file_name, file_extension = os.path.splitext(image_file.name)
    remote_path = '{}/{}_{}_{}{}'.format(
        path_string, file_name, image_source_id, today.strftime("%d%m%Y%H%M%S"), file_extension)
    if Image.objects.filter(image_source=image_source_id, image_type=image_type).first():
        Image.objects.filter(
            image_source=image_source_id, image_type=image_type
        ).update(url=remote_path, image_status=Image.CURRENT)
    else:
        image = Image()
        image.image_source = image_source_id
        image.image_type = image_type
        image.url = remote_path
        image.image_status = Image.CURRENT
        image.save()
    file = functions.upload_handle_media(image_file, upload_to)

    if file:
        upload_file_to_oss(
            settings.OSS_PUBLIC_ASSETS_BUCKET,
            file['file_name'],
            remote_path
        )
        return True
    return False


def is_julo_card_transaction_completed_action(action: str) -> bool:
    if re.match(r'^{}/(?P<loan_xid>[0-9]+)$'.format(PageType.JULO_CARD_TRANSACTION_COMPLETED),
                action):
        return True
    return False


def is_transaction_status_action(action: str) -> bool:
    """
    Check if notfication string is correct for frontend side
    """
    if re.match(r'^{}/(?P<loan_xid>[0-9]+)$'.format(PageType.TRANSACTION_STATUS), action):
        return True
    return False



def customer_have_upgrade_case(customer, current_app: Application, target_success=False):
    """
    This function to check customer have application upgrade
    from JTurbo to J1
    """
    if not current_app:
        return False

    if current_app.is_julo_one():
        if not target_success:
            application_status = ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        else:
            application_status = ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED

        return Application.objects.filter(
            customer=customer,
            workflow__name=WorkflowConst.JULO_STARTER,
            product_line=ProductLineCodes.JULO_STARTER,
            application_status=application_status
        ).exists()

    # check if customer have app JStarter in rejected
    if current_app.is_julo_starter():
        return Application.objects.filter(
            Q(customer=customer)
            & Q(workflow__name=WorkflowConst.JULO_ONE)
            & Q(product_line=ProductLineCodes.J1)
            & (Q(application_status=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED)
               | Q(application_status=ApplicationStatusCodes.APPLICATION_DENIED))
        ).exists()

    return False


def take_out_account_payment_for_experiment_dpd_minus_7(
        qs_account_payments: QuerySet, experiment_setting: ExperimentSetting
) -> Tuple[QuerySet, list]:
    criteria = experiment_setting.criteria
    account_id_tail = criteria.get('account_id_tail')
    control_group_account_tail = account_id_tail.get('control_group')
    experiment_group_account_tail = account_id_tail.get('experiment_group')
    filter_control_account_tail_objects = Q()
    for account_tail_id in control_group_account_tail:
        filter_control_account_tail_objects |= Q(account__id__endswith=account_tail_id)

    filter_experiment_account_tail_objects = Q()
    for account_tail_id in experiment_group_account_tail:
        filter_experiment_account_tail_objects |= Q(account__id__endswith=account_tail_id)

    return qs_account_payments.filter(
        filter_control_account_tail_objects), \
           list(qs_account_payments.filter(
               filter_experiment_account_tail_objects).values_list('id', flat=True))


def gopay_account_link_deeplink(application):
    from juloserver.payback.services.gopay import GopayServices
    gopay_account_link_feature = GopayServices.is_show_gopay_account_linking(application.account_id)

    if not gopay_account_link_feature:
        return True, {'isValid': False}

    # app status validation
    if application.application_status.status_code < \
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        return True, {'isValid': False}
    # account status validation
    if application.account.status.status_code in JuloOneCodes.deleted() or \
        application.account.status.status_code != JuloOneCodes.ACTIVE:
        return True, {'isValid': False}

    gopay_account = application.account.gopayaccountlinkstatus_set.exists()

    if not gopay_account and application.application_status_id == \
            ApplicationStatusCodes.LOC_APPROVED:
        return True, {'isValid': True}

    gopay_account = application.account.gopayaccountlinkstatus_set.filter(
        status__in=[GopayAccountStatusConst.DISABLED, GopayAccountStatusConst.EXPIRED]).last()

    if gopay_account:
        return True, {'isValid': True}

    return True, {'isValid': False}


def gopay_repayment_deeplink(application):
    # feature setting validation, highest priority
    gopay_linking_fs = FeatureSetting.objects.get(
        feature_name=JuloFeatureNameConst.GOPAY_ACTIVATION_LINKING
    )
    if not gopay_linking_fs.is_active:
        return True, {'isValid': False}
    gopay_linking_whitelist_fs = FeatureSetting.objects.get(
        feature_name=JuloFeatureNameConst.WHITELIST_GOPAY
    )
    # this part assumes that whitelist parameter is filled with application_id key
    if gopay_linking_whitelist_fs.is_active:
        if 'application_id' in gopay_linking_whitelist_fs.parameters:
            if application.id not in gopay_linking_whitelist_fs.parameters['application_id']:
                return True, {'isValid': False}
    # app status validation
    if application.application_status.status_code < \
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        return True, {'isValid': False}
    # account status validation
    if application.account.status.status_code in JuloOneCodes.deleted() or \
        application.account.status.status_code != JuloOneCodes.ACTIVE:
        return True, {'isValid': False}
    # active loan validation
    if not application.account.get_all_active_loan().exists():
        return True, {'isValid': False}

    gopay_account = application.account.gopayaccountlinkstatus_set.filter(
        status=GopayAccountStatusConst.ENABLED).exists()

    if gopay_account and application.account.get_all_active_loan().exists():
        return True, {'isValid': True}

    return True, {'isValid': False}


def gopay_autodebet_deeplink(application):
    # feature setting validation, highest priority
    gopay_autodebet_fs = FeatureSetting.objects.get(
        feature_name=JuloFeatureNameConst.AUTODEBET_GOPAY
    )
    if not gopay_autodebet_fs.is_active:
        return True, {'isValid': False}
    gopay_autodebet_whitelist_fs = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.WHITELIST_AUTODEBET_GOPAY
    )
    # this part assumes that whitelist parameter is filled with application_id key
    if gopay_autodebet_whitelist_fs.is_active:
        if 'application_id' in gopay_autodebet_whitelist_fs.parameters:
            if application.id not in gopay_autodebet_whitelist_fs.parameters['application_id']:
                return True, {'isValid': False}
    # app status validation
    if application.application_status.status_code < \
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        return True, {'isValid': False}
    # account status validation
    if application.account.status.status_code in JuloOneCodes.deleted() or \
        application.account.status.status_code != JuloOneCodes.ACTIVE:
        return True, {'isValid': False}
    # active loan validation
    if not application.account.get_all_active_loan().exists():
        return True, {'isValid': False}

    gopay_account = application.account.gopayaccountlinkstatus_set.filter(
        status=GopayAccountStatusConst.ENABLED).exists()

    if gopay_account and application.account.get_all_active_loan().exists():
        return True, {'isValid': True}

    return True, {'isValid': False}


def dana_account_link_deeplink(application):
    # feature setting validation, highest priority
    dana_linking_fs = FeatureSetting.objects.get(
        feature_name=JuloFeatureNameConst.DANA_LINKING
    )
    if not dana_linking_fs.is_active:
        return True, {'isValid': False}
    dana_linking_whitelist_fs = FeatureSetting.objects.get(
        feature_name=JuloFeatureNameConst.DANA_LINKING_WHITELIST
    )
    # this part assumes that whitelist parameter is filled with application_id key
    if dana_linking_whitelist_fs.is_active:
        if 'application_id' in dana_linking_whitelist_fs.parameters:
            if application.id not in dana_linking_whitelist_fs.parameters['application_id']:
                return True, {'isValid': False}
    # app status validation
    if application.application_status.status_code < \
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        return True, {'isValid': False}
    # account status validation
    if application.account.status.status_code in JuloOneCodes.deleted() or \
        application.account.status.status_code != JuloOneCodes.ACTIVE:
        return True, {'isValid': False}

    return True, {'isValid': True}


def determine_main_application_infocard(customer):
    """
    Check main application for Infocard logic
    """
    from juloserver.julo_starter.services.services import user_have_upgrade_application
    from juloserver.application_form.services.application_service import determine_active_application

    list_applications, application_upgrade = user_have_upgrade_application(
        customer=customer,
        return_instance=True
    )

    # case if not have applications
    if not list_applications:
        return None

    # this case customer not have upgrade case
    if not application_upgrade:
        # check for x100 case
        return determine_active_application(
            customer,
            list_applications.first(),
        )

    # case customer have upgrade
    # for case rejected need to check last application
    # have x106 or x135 (x105 and score c)
    application_target = list_applications.first()

    # List application will be reapply with endpoint reapply
    # x106, x135, x136, x137, x139
    if (
            application_target.application_status_id in ApplicationStatusExpired.STATUS_CODES
            or check_application_have_score_c(application_target)
    ):
        # return application JTurbo as main application
        return Application.objects.filter(
            pk=application_upgrade.application_id_first_approval
        ).last()

    # return application J1 as main application
    return Application.objects.filter(
        pk=application_upgrade.application_id
    ).last()


def check_application_are_rejected_status(customer):
    checker = False
    application_j1 = Application.objects.filter(
        customer=customer,
        workflow__name=WorkflowConst.JULO_ONE,
        product_line=ProductLineCodes.J1,
    ).last()

    if not application_j1:
        logger.error({
            'message': 'Not have application upgrade to J1',
            'process': 'check_application_are_rejected_status',
            'customer': customer.id
        })
        return checker

    if (
            application_j1.application_status_id in ApplicationStatusExpired.STATUS_CODES
            or check_application_have_score_c(application_j1)
    ):
        checker = True

    logger.info({
        'message': 'Application upgrade J1 have rejected or expired',
        'process': 'check_application_are_rejected_status',
        'customer': customer.id,
        'result': checker
    })

    return checker


def check_application_have_score_c(application):
    # check if application is J1 and x105 get c score
    if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
        is_c_score = JuloOneService.is_c_score(application)
        if is_c_score:
            return True

    return False


def is_eligible_for_deep_link(application: Application, transaction_method) -> bool:
    whitelist_feature_setting = get_transaction_method_whitelist_feature(transaction_method.name)
    if whitelist_feature_setting:
        return is_transaction_method_whitelist_user(
            transaction_method.name, application.id, whitelist_feature_setting
        )

    from juloserver.loan.services.loan_related import is_product_locked
    return (
        # Application status must be x190
            application.application_status_id == ApplicationStatusCodes.LOC_APPROVED
            # Account status must be x420
            and application.account.status_id == AccountConstant.STATUS_CODE.active
            # transaction method must not be locked
            and not is_product_locked(application.account, transaction_method.code)
    )


def get_neo_status(application, app_version=None, is_ios_device=False):
    from juloserver.apiv2.services import get_eta_time_for_c_score_delay

    if application.customer and get_ongoing_account_deletion_request(application.customer):
        return JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW

    status = application.application_status_id
    if status == ApplicationStatusCodes.FORM_CREATED:
        if determine_idfy_neo_banner(application) and not application.is_julo_one_ios():
            status = '100_VIDEO_CALL'
            status = determine_neo_banner_by_app_version(app_version, status)
            logger.info({
                'message': 'determine_idfy_neo_banner',
                'application': application.id,
                'status_result': status,
                'app_version': app_version,
                'target_version': NeoBannerConst.TARGET_VERSION_FORM_OR_VIDEO,
            })
        else:
            status = '100_FORM'
    elif status == ApplicationStatusCodes.FORM_PARTIAL:
        is_agent_assisted_flow = is_agent_assisted_submission_flow(application)
        if is_agent_assisted_flow:
            logger.info(
                {
                    'message': 'Neo Banner for Agent Assisted Submission',
                    'application': application.id,
                    'app_version': app_version,
                    'status_result': status,
                }
            )
            return AgentAssistedSubmissionConst.STATUS_IN_NEO_BANNER

        credit_score = CreditScore.objects.filter(application_id=application.id).last()
        if not credit_score:
            status = '105_NO_SCORE'
        elif credit_score.score in ['C', '--']:
            submission = BankStatementSubmit.objects.filter(application_id=application.id).last()
            is_fraud = (submission.is_fraud or False) if submission else False

            eta_time = get_eta_time_for_c_score_delay(application)
            now = timezone.localtime(timezone.now())
            if pass_binary_check_scoring(application) and not is_fraud:
                status = '105_C_SCORE_BANK_STATEMENT_AVAILABLE'
            else:
                status = '105_C_SCORE_BANK_STATEMENT_UNAVAILABLE'
                if now < eta_time:
                    status = '105_NOT_C_SCORE'
        else:
            status = '105_NOT_C_SCORE'
    elif status == ApplicationStatusCodes.APPLICATION_DENIED:
        if application.customer.can_reapply:
            status = '135_REAPPLY'
        else:
            from juloserver.application_flow.workflows import JuloOneWorkflowAction
            action = JuloOneWorkflowAction(application, None, None, None, None)
            is_available_bank_statement = action.need_check_bank_statement()
            if is_available_bank_statement:
                status = '135_CANNOT_REAPPLY_BANK_STATEMENT_AVAILABLE'
            else:
                status = '135_CANNOT_REAPPLY_BANK_STATEMENT_UNAVAILABLE'
    elif status == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
        history = ApplicationHistory.objects.filter(
            status_new=status,
            application_id=application.id
        ).last()
        status_old = history.status_old
        if application.customer.can_reapply:
            status = '106_REAPPLY'
        else:
            credit_score = CreditScore.objects.filter(application_id=application.id).last()
            if (
                status_old == ApplicationStatusCodes.DOCUMENTS_SUBMITTED
                and credit_score
                and credit_score.score not in ['C', '--']
            ):
                status = '106_RESUBMIT'
            else:
                status = '106_CANNOT_REAPPLY'
    elif status == ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED:
        if application.customer.can_reapply:
            status = '136_REAPPLY'
        else:
            status = '136_RESUBMIT'
    elif status == ApplicationStatusCodes.ACTIVATION_AUTODEBET:
        account = application.account
        autodebet_feature_status = construct_autodebet_feature_status(account, version='v2')
        bca_dict = next((item for item in autodebet_feature_status['status'] if item['bank_name'] == 'BCA'), None)
        if bca_dict and bca_dict.get('on_process_type') not in [None, '', 'revocation'] and not bca_dict.get(
                'is_manual_activation'):
            status = '153_PENDING'
        else:
            status = '153_READY'
    elif (
        status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        and not is_ios_device
        and application.is_julo_one()
        and app_version
    ):
        is_hsfbp = is_hsfbp_hold_with_status(application, is_ios_device)

        experiment_setting = ExperimentSetting.objects.filter(
            code=ExperimentConst.HSFBP_INCOME_VERIFICATION,
        ).last()
        if not experiment_setting:
            return status

        app_version_criteria = experiment_setting.criteria.get(
            HSFBPIncomeConst.KEY_ANDROID_APP_VERSION
        )
        is_hsfbp_x120_available = semver.match(app_version, app_version_criteria)

        is_result = is_hsfbp and is_hsfbp_x120_available
        status = ListSpecificRuleStatus.STATUS_120_HSFBP if is_result else status

        # check session status is still available ?
        from juloserver.application_flow.services import is_available_session_check_hsfbp

        is_available = is_available_session_check_hsfbp(application.id)
        if is_available:
            logger.info(
                {
                    'message': '[x120_HSFBP] session hold neo banner in x105 until process HSFBP done',
                    'application_id': application.id,
                }
            )
            status = '105_NOT_C_SCORE'
    elif (
        status == ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL
        and application.is_julo_one()
    ):
        status = '127_TYPO'

        is_target_version = semver.match(app_version, ">=9.2.0")
        if not is_ios_device and is_target_version:
            application_history = ApplicationHistory.objects.filter(
                application_id=application.id,
                status_new=ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
            ).order_by("cdate").last()
            if application_history:
                if application_history.change_reason == 'Improper mother name':
                    status = '127_MOTHER_MAIDEN_NAME'
                elif application_history.change_reason == 'Improper mother name and typo':
                    status = '127_TYPO_AND_MOTHER_MAIDEN_NAME'

    return status


def get_public_url(path):
    if path == '' or path is None:
        return None
    return get_oss_public_url(settings.OSS_PUBLIC_ASSETS_BUCKET, path)


def get_neo_banner(application, app_version=None, is_ios_device=False):
    from juloserver.application_flow.services2.shopee_scoring import ShopeeWhitelist
    from juloserver.tokopedia.services.credit_matrix_service import build_credit_matrix_parameters
    from juloserver.tokopedia.services.common_service import is_success_revive_by_tokoscore

    cards = []
    list_cards = None
    if application.is_julo_one() or application.is_julo_one_ios():
        status = get_neo_status(application, app_version, is_ios_device)
        list_cards = get_neo_banner_cards_by_status(status)
    if list_cards:
        cards = model_to_dict(list_cards)

        if cards['extended_title'] and status != '105_NO_SCORE':
            from juloserver.account.services.credit_limit import (
                get_transaction_type,
                get_credit_matrix_parameters,
                get_credit_matrix,
            )

            credit_matrix = None

            custom_matrix_parameters = get_credit_matrix_parameters(application)
            transaction_type = get_transaction_type()
            shopee_whitelist = ShopeeWhitelist(application)
            if shopee_whitelist.has_success_tags:

                if shopee_whitelist.has_anomaly():
                    shopee_whitelist.reject_application()
                else:
                    additional_parameters = (
                        shopee_whitelist.build_additional_credit_matrix_parameters()
                    )
                    credit_matrix = get_credit_matrix(
                        {**custom_matrix_parameters, **additional_parameters},
                        transaction_type,
                        parameter=Q(parameter=ShopeeWhitelist.CREDIT_MATRIX_PARAMETER)
                    )
            elif is_success_revive_by_tokoscore(application):
                # check is success revive by tokoscore to x120 and will use CM Tokoscore
                additional_parameters = build_credit_matrix_parameters(application.id)
                logger.info({
                    'message': 'Tokoscore: Use CM Tokoscore have path tag tokoscore passed',
                    'application': application.id,
                    'additional_parameters': str(additional_parameters),
                })
                credit_matrix = get_credit_matrix(
                    {**custom_matrix_parameters, **additional_parameters},
                    transaction_type,
                    parameter=Q(parameter=TokoScoreConst.CREDIT_MATRIX_PARAMETER),
                )
            else:
                credit_matrix = get_credit_matrix(custom_matrix_parameters, transaction_type)
            potential_limit = 500000
            if credit_matrix:
                credit_matrix_product_line = CreditMatrixProductLine.objects.filter(
                    credit_matrix=credit_matrix
                ).last()
                potential_limit = credit_matrix_product_line.max_loan_amount
            cards['extended_message'] = "Rp{:,.0f}".format(potential_limit).replace(',', '.')

        if status in (
            '135_CANNOT_REAPPLY_BANK_STATEMENT_AVAILABLE',
            '105_C_SCORE_BANK_STATEMENT_AVAILABLE',
            ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
        ):
            from juloserver.application_flow.services2.bank_statement import BankStatementClient
            cards['button_action'] = 'https://' + BankStatementClient(application).generate_landing_url()

        cards['top_image'] = get_public_url(cards['top_image'])
        cards['extended_image'] = get_public_url(cards['extended_image'])
        cards['badge_icon'] = get_public_url(cards['badge_icon'])

        if '100_VIDEO_CALL' in cards['statuses']:
            fs = FeatureSetting.objects.filter(
                feature_name=JuloFeatureNameConst.IDFY_VIDEO_CALL_HOURS,
                is_active=True,
            ).last()

            if fs:
                cards['top_info_message'] = get_video_call_hours(fs.parameters)

        if AgentAssistedSubmissionConst.STATUS_IN_NEO_BANNER in cards['statuses']:
            # source from table the link
            cards['button_action'] = get_url_form_for_tnc(
                application_id=application.id,
                is_need_protocol_prefix=True,
            )

        if is_ios_device and (application.is_julo_one_ios() or application.is_julo_one()):
            for status_reapply in StatusReapplyForIOS.STATUSES:
                if status_reapply in cards['statuses']:
                    cards['button_action'] = 'reapply_form'

    return cards


def get_neo_info_cards(application, app_version=None, is_ios_device=False):
    cards = []
    list_cards = None
    if application.is_julo_one() or application.is_julo_one_ios():
        status = get_neo_status(application, app_version, is_ios_device)
        list_cards = NeoInfoCard.objects.filter(
            is_active=True,
            statuses__contains=status,
            product="J1"
        ).order_by('priority', 'id')

    fields_to_include = ['id', 'product', 'statuses', 'image_url', 'action_type', 'action_destination']

    if list_cards:
        for card in list_cards:
            card_dict = model_to_dict(card, fields=fields_to_include)
            if 'image_url' in card_dict:
                card_dict['image_url'] = get_public_url(card_dict['image_url'])
            cards.append(card_dict)

    return cards


def get_list_dpd_late_fee_experiment(extra_condition: str, platform: str) -> list:
    redis_client = get_redis_client()
    cached_list_dpd = redis_client.get_list(
        RedisKey.STREAMLINE_LATE_FEE_EXPERIMENT.format(extra_condition, platform)
    )
    if cached_list_dpd:
        return list(map(int, cached_list_dpd))

    list_dpd = StreamlinedCommunication.objects.filter(
        extra_conditions=extra_condition, communication_platform=platform
    ).values_list('dpd', flat=True).distinct()

    if list_dpd:
        redis_client.set_list(
            RedisKey.STREAMLINE_LATE_FEE_EXPERIMENT.format(extra_condition, platform),
            list_dpd, timedelta(hours=8))
        return list(list_dpd)

    return []


def get_list_account_ids_late_fee_experiment(group: str, experiment: ExperimentSetting) -> list:
    data = ExperimentGroup.objects.filter(
        group=group, experiment_setting=experiment).values_list('account_id', flat=True)
    return list(data)


def is_account_id_late_fee_experiment(account_id: int, experiment: ExperimentSetting) -> list:
    return ExperimentGroup.objects.filter(
        group='experiment', experiment_setting=experiment, account_id=account_id).exists()


def get_reminder_streamlined_comms_by_dpd(
        android_infocards_queryset: QuerySet, dpd: int, account: Account, product_line=None,
) -> list:
    from juloserver.julo.services2.experiment import get_experiment_setting_by_code
    from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
    filter_dict = dict(
        communication_platform=CommunicationPlatform.INFO_CARD,
        product__isnull=True,
        extra_conditions__isnull=True,
        is_active=True
    )
    late_fee_experiment = get_experiment_setting_by_code(
        MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT)
    if late_fee_experiment:
        experiment_dpd_list = get_list_dpd_late_fee_experiment(
            'LATE_FEE_EARLIER_EXPERIMENT', CommunicationPlatform.INFO_CARD)
        if dpd in experiment_dpd_list and is_account_id_late_fee_experiment(
                account.id, late_fee_experiment):
            filter_dict.pop('extra_conditions__isnull')
            filter_dict['extra_conditions'] = 'LATE_FEE_EARLIER_EXPERIMENT'

    if product_line == Product.STREAMLINED_PRODUCT.jstarter:
        filter_dict.pop('product__isnull')
        filter_dict['product'] = Product.STREAMLINED_PRODUCT.jstarter

    account_payment_cards = list(android_infocards_queryset.filter(
        Q(dpd=dpd)
        | (Q(dpd_lower__lte=dpd) & Q(dpd_upper__gte=dpd))
        | (Q(dpd_lower__lte=dpd) & Q(until_paid=True))).filter(**filter_dict
                                                               ).order_by(
        'message__info_card_property__card_order_number'))
    return account_payment_cards


def get_app_deep_link_list():
    """Function to return the app deeplinks list"""
    app_deeplink_list = [(obj.deeplink, obj.label) for obj in AppDeepLink.objects.all().order_by('id')]
    return app_deeplink_list


def determine_idfy_neo_banner(application):
    """
    Gate from neo banner to start video call from Customer
    """

    from juloserver.application_form.services.idfy_service import (
        is_completed_vc,
        is_office_hours_agent_for_idfy,
    )

    is_completed = is_completed_vc(application)
    is_office_hours, message = is_office_hours_agent_for_idfy(is_completed=is_completed)
    if is_office_hours:
        logger.info({
            'message': 'IDFy Neo Banner',
            'result': True,
            'application': application.id,
            'is_completed_vc': is_completed,
        })
        return True

    logger.info({
        'message': 'Non-IDFy Neo Banner',
        'result': False,
        'application': application.id,
        'is_completed_vc': is_completed,
    })

    return False


def is_eligible_for_payslip_and_bank_statement_deeplink(application, action_type):
    from juloserver.cfs.services.core_services import get_cfs_missions

    if not (
        application.application_status_id == ApplicationStatusCodes.LOC_APPROVED
        and application.account.status_id == AccountConstant.STATUS_CODE.active
        and application.product_line_id == ProductLineCodes.J1
    ):
        return False

    _, on_going_missions, _ = get_cfs_missions(application)
    cfs_action = [mission['action_code'] for mission in on_going_missions
                  if mission['progress_status'] == CfsProgressStatus.START]

    return action_type in cfs_action


def is_eligible_for_loyalty_deeplink(customer):
    application = Application.objects.get_active_julo_product_applications().filter(
        customer_id=customer.pk,
    ).last()

    is_whitelist_customer = check_loyalty_whitelist_fs(customer_id=customer.id)

    if application and is_whitelist_customer:
        return True

    return False


def is_eligible_for_change_phone_number_deeplink(customer: Customer) -> bool:
    """
    Checks if a customer is eligible for generating a deep link to change their phone number.

    Args:
    - customer (dict): Customer information including attributes

    Returns:
    - bool: True if the customer is eligible, False otherwise.
    """

    application = customer.last_application
    if (
        application.application_status_id == ApplicationStatusCodes.CUSTOMER_ON_DELETION
        or application.application_status_id == ApplicationStatusCodes.FORM_CREATED
    ):
        return False

    account = customer.account
    if account and account.status_id == JuloOneCodes.SOLD_OFF:
        return False

    return True


def show_ipa_banner(customer, app_version):
    fdc_binary, message = False, None
    last_j1_application = Application.objects.filter(
        customer=customer,
        application_status=ApplicationStatusCodes.FORM_CREATED,
        workflow__name=WorkflowConst.JULO_ONE,
    ).last()

    if not last_j1_application or not last_j1_application.onboarding or last_j1_application.onboarding.id != 3:
        return fdc_binary, message
    is_experiment = determine_ipa_banner_experiment(customer, app_version)
    fdc_binary, message = determine_ipa_banner_by_fdc_loan_data(customer, is_experiment)
    message = message if is_experiment else None
    return fdc_binary, message


def show_ipa_banner_v2(customer, app_version):
    """
    Card: https://juloprojects.atlassian.net/browse/RUS1-3112
    IPA banner will show 4 variations:
    - High for Control Group
    - High for Experiment Group
    - Medium for Control Group
    - Medium for Experiment Group

    Segmentation logic:
    High if good FDC, else Medium
    """
    fs = FeatureSetting.objects.filter(
        feature_name=JuloFeatureNameConst.IPA_BANNER_V2, is_active=True
    ).last()

    if not fs:
        return False, False, None

    application = (
        Application.objects.filter(
            customer=customer, onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID
        )
        .select_related('customer')
        .last()
    )

    if not application:
        return False, False, None

    parameters = fs.parameters or {}

    # Determine experiment settings version
    is_experiment, group_name, segment_postfix = determine_ipa_banner_experiment_version(
        customer, app_version, application=application
    )

    # Check if customer has a good FDC
    is_good_fdc = determine_ipa_banner_by_good_fdc(application.id)

    # Determine the message and segment based on FDC
    group_message = parameters.get(group_name, parameters.get('control', {}))
    fdc_key = 'high_fdc' if is_good_fdc else 'medium_fdc'
    message = group_message.get(fdc_key)
    segment = fdc_key

    # Check and set sticky bar value
    show_sticky_bar, show_banner = False, False
    if segment_postfix:
        show_sticky_bar = segment_postfix not in {'no_stickybar'}
        show_banner = segment_postfix not in {'no_banner'}
        segment = f"{segment}_{segment_postfix}"
    else:
        show_banner = True

    # Update the experiment group segment
    experiment_setting = experiment_setting = determine_experiment_setting_for_ipa_banner(
        app_version
    )
    if experiment_setting:
        experiment_group = ExperimentGroup.objects.filter(
            experiment_setting=experiment_setting,
            application=application,
        ).last()
        if experiment_group:
            experiment_group.update_safely(segment=segment)

    logger.info(
        {
            'message': 'IPABannerV2: execute banner IPA',
            'is_good_fdc': is_good_fdc,
            'application_id': application.id,
            'group': group_name,
            'segment': segment,
        }
    )

    # Process the images if exist
    if message:
        # Add link images if they exist
        if message.get('link_image'):
            message['link_image'] = get_oss_public_url(
                settings.OSS_PUBLIC_ASSETS_BUCKET, message['link_image']
            )

        # Add sticky bar link if available
        if message.get('link_sticky_bar'):
            message['link_sticky_bar'] = get_oss_public_url(
                settings.OSS_PUBLIC_ASSETS_BUCKET, message['link_sticky_bar']
            )

        return show_banner, show_sticky_bar, message
    return False, False, None


def determine_ipa_banner_by_good_fdc(application_id):

    return EligibleCheck.objects.filter(
        application_id=application_id,
        check_name=GoodFDCX100Const.KEY_CHECK_NAME,
        is_okay=True,
    ).exists()


def determine_ipa_banner_experiment(customer, app_version, application=None):
    experiment_setting = ExperimentSetting.objects.filter(
        code=ExperimentConst.FDC_IPA_BANNER_EXPERIMENT, is_active=True
    ).last()

    if not experiment_setting:
        return False

    criteria = experiment_setting.criteria
    if not criteria:
        return False
    if not experiment_setting.is_permanent:
        if experiment_setting.start_date and experiment_setting.end_date:
            today = timezone.localtime(timezone.now())
            if not experiment_setting.start_date <= today <= experiment_setting.end_date:
                return False
        else:
            return False
    if not criteria.get('target_version'):
        return False

    if not semver.match(app_version, criteria.get('target_version')):
        return False

    tail_customer_id = str(customer.id)[-1]
    group_name = 'control'
    is_experiment = False
    if int(tail_customer_id) in criteria.get('customer_id'):
        group_name = 'experiment'
        is_experiment = True

    experiment_group = ExperimentGroup.objects.filter(
        experiment_setting=experiment_setting,
        customer_id=customer.id,
    )

    if not experiment_group.exists():
        experiment_group = ExperimentGroup.objects.create(
            experiment_setting=experiment_setting,
            customer_id=customer.id,
        )
    else:
        experiment_group = experiment_group.last()

    if application and experiment_group:
        experiment_group.update_safely(application=application, group=group_name, refresh=True)

    return is_experiment


def determine_ipa_banner_experiment_version(customer, app_version, application=None):

    experiment_setting = determine_experiment_setting_for_ipa_banner(app_version)
    if experiment_setting:
        # Create experiment group record
        experiment_group, created = ExperimentGroup.objects.get_or_create(
            experiment_setting=experiment_setting,
            customer_id=customer.id,
            application_id=application.id if application else None,
        )

        # Dispatch function based on version
        if experiment_setting.code == ExperimentConst.FDC_IPA_BANNER_EXPERIMENT_V3:
            if experiment_setting.is_active:
                return determine_ipa_banner_experiment_v3(
                    customer, experiment_setting, experiment_group
                )
        elif experiment_setting.code == ExperimentConst.FDC_IPA_BANNER_EXPERIMENT_V2:
            if experiment_setting.is_active:
                return determine_ipa_banner_experiment_v2(
                    customer, experiment_setting, experiment_group
                )
    return False, None, None


def determine_ipa_banner_experiment_v2(customer, experiment_setting, experiment_group):
    today = timezone.localtime(timezone.now())
    if not experiment_setting.is_permanent and not (
        experiment_setting.start_date <= today <= experiment_setting.end_date
    ):
        return False, None, None

    tail_customer_id = int(str(customer.id)[-1])
    group_name = (
        'experiment'
        if tail_customer_id in experiment_setting.criteria.get('customer_id', [])
        else 'control'
    )

    experiment_group.update_safely(group=group_name)

    return True, group_name, None


def determine_ipa_banner_experiment_v3(customer, experiment_setting, experiment_group):
    today = timezone.localtime(timezone.now())
    if not experiment_setting.is_permanent and not (
        experiment_setting.start_date <= today <= experiment_setting.end_date
    ):
        return False, None, None

    tail_customer_id = int(str(customer.id)[-1])
    customer_id_criteria = experiment_setting.criteria.get('customer_id')

    lookup_table = {
        tail_id: segment
        for segment, tail_ids in customer_id_criteria.items()
        for tail_id in tail_ids
    }
    segment_postfix = lookup_table.get(tail_customer_id)
    group_name = 'experiment' if segment_postfix else 'control'

    experiment_group.update_safely(group=group_name)
    return True, group_name, segment_postfix


def determine_neo_banner_by_app_version(app_version, available_value):

    if not app_version:
        logger.info({
            'message': 'App version is empty',
            'result': available_value,
            'process': 'determine_neo_banner_by_app_version',
        })
        return available_value

    is_target_version = semver.match(app_version, ">=%s" % NeoBannerConst.TARGET_VERSION_FORM_OR_VIDEO)
    if is_target_version:
        return NeoBannerStatusesConst.FORM_OR_VIDEO_CALL_STATUSES

    return available_value


def get_list_dpd_experiment(extra_condition: str, platform: str, redis_key: str) -> list:
    redis_client = get_redis_client()
    cached_list_dpd = redis_client.get_list(redis_key.format(extra_condition, platform))

    if cached_list_dpd:
        return [int(dpd) for dpd in cached_list_dpd]

    list_dpd = StreamlinedCommunication.objects.filter(
        extra_conditions=extra_condition, communication_platform=platform
    ).values_list('dpd', flat=True).distinct()

    if list_dpd:
        redis_client.set_list(redis_key.format(extra_condition, platform), list_dpd, timedelta(hours=8))
        return list(list_dpd)


    return []


def get_video_call_hours(parameters: dict):
    weekdays = parameters.get('weekdays')
    holidays = parameters.get('holidays')

    def format_hours_and_minutes(hour, minute):
        return f"{str(hour).zfill(2)}:{str(minute).zfill(2)}"

    weekdays_hours = "{}-{}".format(
        format_hours_and_minutes(weekdays["open"]["hour"], weekdays["open"]["minute"]),
        format_hours_and_minutes(weekdays["close"]["hour"], weekdays["close"]["minute"])
    )
    holidays_hours = "{}-{}".format(
        format_hours_and_minutes(holidays["open"]["hour"], holidays["open"]["minute"]),
        format_hours_and_minutes(holidays["close"]["hour"], holidays["close"]["minute"])
    )

    if weekdays_hours == holidays_hours:
        result = "Senin-Minggu/Libur Nasional: {}".format(weekdays_hours)
    else:
        result = "Senin-Jumat: {} <br>Sabtu-Minggu/Libur Nasional: {}".format(weekdays_hours, holidays_hours)

    return result


def replace_vendor_name(data, new_vendor_name):
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                replace_vendor_name(value, new_vendor_name)
            elif isinstance(value, str):
                data[key] = value.replace('{{vendor_name}}', new_vendor_name)


def get_selloff_content(account):
    from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
    loan_selloff = LoanSelloff.objects.filter(account=account).order_by('cdate').last()
    if not loan_selloff:
        return {}

    vendor_name = loan_selloff.loan_selloff_batch.vendor
    data = {
        'home': {
            'bg_image': '',
            'title': 'Informasi Pinjaman',
            'content': 'Utang kamu telah kami alihkan kepada {}.'
                       '<br><br>Dengan pengalihan utang ini, '
                       'hak tagih akan dipegang oleh {}. Selanjutnya, penagihan akan dilakukan oleh '
                       '{} dan JULO tidak memiliki hak tagih lagi atas utang kamu.'
                       '<br><br>Silakan cek email kamu untuk informasi lebih lanjut.'.format(
                vendor_name, vendor_name, vendor_name),
        },
        'loan': {
            'content': 'Utang kamu telah kami alihkan kepada {}. Dengan pengalihan utang ini, '
                       'penagihan selanjutnya akan dilakukan oleh {}.'.format(vendor_name,
                                                                              vendor_name)
        },
        'partner_company': vendor_name
    }
    feature_setting = FeatureSetting.objects.filter(
        feature_name=JuloFeatureNameConst.LOAN_SELL_OFF_CONTENT_API, is_active=True).last()
    if feature_setting:
        params = feature_setting.parameters
        replace_vendor_name(params, vendor_name)
        data = params

    return data


def determine_ipa_banner_by_fdc_loan_data(customer, is_experiment=False):
    """
    This function to handle show ipa banner for v1 and v2
    """

    fdc_binary, message = None, None

    fdc_inquiry = FDCInquiry.objects.filter(
        customer_id=customer.id,
        inquiry_status='success',
        inquiry_date__isnull=False,
        inquiry_reason='1 - Applying loan via Platform',
    ).last()

    if fdc_inquiry:
        try:
            dpd_passed, sisa_pinjaman_passed = False, False

            bad_loans = FDCInquiryLoan.objects.filter(
                fdc_inquiry=fdc_inquiry,
                tgl_pelaporan_data__gte=fdc_inquiry.inquiry_date - relativedelta(years=1),
                kualitas_pinjaman__in=(
                    *FDCLoanQualityConst.TIDAK_LANCAR,
                    *FDCLoanQualityConst.MACET,
                    *FDCLoanQualityConst.LANCAR,
                ),
            )
            if bad_loans:
                total_non_smooth_credit = 0
                total_bad_credit = 0
                total_current_credit = 0
                bad_loans = bad_loans.values('kualitas_pinjaman').annotate(total=Count('kualitas_pinjaman'))

                for bad_loan in bad_loans:
                    if bad_loan['kualitas_pinjaman'] in FDCLoanQualityConst.TIDAK_LANCAR:
                        total_non_smooth_credit = bad_loan['total']

                    elif bad_loan['kualitas_pinjaman'] in FDCLoanQualityConst.MACET:
                        total_bad_credit = bad_loan['total']

                    elif bad_loan['kualitas_pinjaman'] in FDCLoanQualityConst.LANCAR:
                        total_current_credit = bad_loan['total']
                total_credit = total_current_credit + total_bad_credit + total_non_smooth_credit

                criteria_value = 0
                if total_credit:
                    criteria_value = float(total_bad_credit) / total_credit

                fdc_binary = total_bad_credit == 0

                if not fdc_binary:
                    today = timezone.localtime(timezone.now()).date()
                    get_loans = FDCInquiryLoan.objects.filter(
                        fdc_inquiry=fdc_inquiry,
                        tgl_pelaporan_data__gte=fdc_inquiry.inquiry_date - relativedelta(days=1),
                        tgl_jatuh_tempo_pinjaman__lt=today,
                    )

                    if get_loans:
                        get_loans = get_loans.aggregate(
                            outstanding_amount=Sum('sisa_pinjaman_berjalan'),
                            total_amount=Sum('nilai_pendanaan'),
                        )

                        paid_pct, outstanding_amount, total_amount = 0, 0, 0
                        if get_loans['outstanding_amount']:
                            outstanding_amount = get_loans['outstanding_amount']

                        if get_loans['total_amount']:
                            total_amount = get_loans['total_amount']

                        if total_amount > 0:
                            paid_pct = float(outstanding_amount) / float(total_amount)

                        fdc_binary = outstanding_amount == 0
        except:
            raise StreamlinedCommunicationException

        message = {
            "title": "Asik, Kamu Lolos Pengecekan Awal",
            "message": "Yuk, isi formnya sedikit lagi agar kamu makin cepat mendapatkan limit!"
        } if fdc_binary and is_experiment else None

    return fdc_binary, message


def format_bottom_sheet_for_grab(streamlined_communication, available_context):
    streamlined_message = streamlined_communication.message
    info_card_property = streamlined_message.info_card_property
    card_type = info_card_property.card_type[0]
    button_list = info_card_property.button_list
    formated_buttons = []
    for button in button_list:
        formated_buttons.append(
            {
                "colour": button.button_color,
                "text": button.text,
                "textcolour": button.text_color,
                "action_type": button.action_type,
                "destination": button.destination,
                "border": None,
                "background_img": button.background_image_url
            }
        )

    card_destination = info_card_property.card_destination

    formated_data = dict(
        type=card_type,
        streamlined_communication_id=streamlined_communication.id,
        title={
            "colour": info_card_property.title_color,
            "text": process_convert_params_to_data(
                info_card_property.title, available_context)
        },
        content={
            "colour": info_card_property.text_color,
            "text": process_convert_params_to_data(
                streamlined_message.message_content, available_context)
        },
        button=formated_buttons,
        border=None,
        background_img=info_card_property.card_background_image_url,
        image_url=info_card_property.card_optional_image_url,
        bottom_sheet_destination=streamlined_communication.bottom_sheet_destination,
        card_action_type=info_card_property.card_action,
        card_action_destination=card_destination,
        youtube_video_id=info_card_property.youtube_video_id
    )
    return formated_data


def determine_experiment_setting_for_ipa_banner(app_version):

    experiment_setting = None
    experiment_settings = ExperimentSetting.objects.filter(
        Q(code=ExperimentConst.FDC_IPA_BANNER_EXPERIMENT_V3)
        | Q(code=ExperimentConst.FDC_IPA_BANNER_EXPERIMENT_V2),
    ).order_by('-code')

    # Find experiment settings with matching version
    for es in experiment_settings:
        target_version = es.criteria.get('target_version')
        if semver.match(app_version, target_version):
            experiment_setting = es
            break

    return experiment_setting


def determine_julo_gold_for_streamlined_communication(julo_gold_status, qs):
    from juloserver.minisquad.constants import JuloGold

    if not julo_gold_status:
        return qs

    qs = qs.select_related('account', 'account__customer')

    today = timezone.localtime(timezone.now()).date()
    customer_ids = list(qs.values_list('account__customer_id', flat=True))

    julo_gold_query = "customer_segment ILIKE %s"
    julo_gold_customer_ids = []
    for batch_customer_ids in batch_list(customer_ids, 1000):
        batch_julo_gold_customer_ids = list(
            PdCustomerSegmentModelResult.objects.filter(
                customer_id__in=batch_customer_ids,
                partition_date=today,
            )
            .extra(
                where=[julo_gold_query],
                params=[f"%{JuloGold.JULO_GOLD_SEGMENT}%"],
            )
            .values_list('customer_id', flat=True)
        )
        if not batch_julo_gold_customer_ids:
            # if data for today doesn't exists will try to get data yesterday
            batch_julo_gold_customer_ids = list(
                PdCustomerSegmentModelResult.objects.filter(
                    customer_id__in=batch_customer_ids,
                    partition_date=today - timedelta(days=1),
                )
                .extra(
                    where=[julo_gold_query],
                    params=[f"%{JuloGold.JULO_GOLD_SEGMENT}%"],
                )
                .values_list('customer_id', flat=True)
            )
        julo_gold_customer_ids.extend(batch_julo_gold_customer_ids)


    if not julo_gold_customer_ids:
        # if still not exists, all customers data will treat as BAU
        return qs

    if julo_gold_status == JuloGold.JULO_GOLD_EXCLUDE_STATUS:
        return qs.exclude(account__customer_id__in=julo_gold_customer_ids)
    elif julo_gold_status == JuloGold.JULO_GOLD_EXECUTE_STATUS:
        return qs.filter(account__customer_id__in=julo_gold_customer_ids)


def get_slik_data(account: Account):
    if not account:
        return {"is_active": False, "message": "Account not exist"}
    oldest_account_payment = account.get_oldest_unpaid_account_payment()
    if oldest_account_payment:
        dpd = oldest_account_payment.dpd
    else:
        return {"is_active": False, "message": "No payment due payment"}
    card = StreamlinedCommunication.objects.filter(
        Q(
            communication_platform=CommunicationPlatform.SLIK_NOTIFICATION,
            dpd_upper__gte=dpd,
            dpd_lower__lte=dpd,
            is_active=True,
        )
        | Q(
            communication_platform=CommunicationPlatform.SLIK_NOTIFICATION,
            dpd_upper=None,
            dpd_lower__lte=dpd,
            is_active=True,
        )
        | Q(
            communication_platform=CommunicationPlatform.SLIK_NOTIFICATION,
            dpd_upper__gte=dpd,
            dpd_lower=None,
            is_active=True,
        )
    ).last()
    slik_notification_data = {
        "is_active": False,
        "message": "No slik notification matched",
        }
    if card:
        if card.slik_notification_properties:
            card_props = card.slik_notification_properties
            slik_notification_data = dict(
                is_active=True,
                streamline=dict(
                    background=card_props['card_colour'],
                    content=dict(
                        text=card_props['info_text'],
                        colour=card_props['info_text_colour'],
                    ),
                    icon=card_props['info_imcard_image'],
                    action=dict(
                        destination=card_props['redirect_url'],
                        action_type="webpage",
                    ) if card_props.get('redirect_url') else dict(),
                ),
            )

    return slik_notification_data


def onboarding_autodebet_deeplink(customer):
    response = {'isValid': False}

    application = Application.objects.filter(
        customer=customer,
        application_status_id__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
    ).last()

    account = Account.objects.filter(
        customer=customer,
        status=AccountConstant.STATUS_CODE.active,
    ).last()

    if not application or not account:
        return True, response

    autodebet_account = AutodebetAccount.objects.filter(
        account=account, is_use_autodebet=True
    ).exists()

    if autodebet_account:
        return True, response

    response['isValid'] = True
    return True, response


def is_show_new_ptp_card(app_version):
    setting = FeatureSetting.objects.filter(
        feature_name=JuloFeatureNameConst.IN_APP_PTP_SETTING, is_active=True
    ).last()
    if not setting or not app_version:
        return False

    min_version = setting.parameters.get('new_card_minimum_version') if setting else None
    if not min_version:
        return False

    return semver.match(app_version, min_version)


def get_neo_banner_cards_by_status(status):
    query = NeoBannerCard.objects.filter(
        is_active=True,
        product="J1",
    )

    if status == ListSpecificRuleStatus.STATUS_120_HSFBP:
        return query.filter(
            statuses=status,
        ).last()

    return (
        query.exclude(
            statuses=ListSpecificRuleStatus.STATUS_120_HSFBP,
        )
        .filter(
            statuses__contains=status,
        )
        .last()
    )


def extra_rules_for_info_cards(application, info_cards):

    if not application or not application.is_julo_one():
        return info_cards

    new_info_cards = rule_hsfbp_for_infocards(application, info_cards)
    return new_info_cards
