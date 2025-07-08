# flake8:
import csv
import os
from io import StringIO
from builtins import str
from builtins import range
import logging

from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
)
from juloserver.customer_module.services.customer_related import get_ongoing_account_deletion_request
import semver
from babel.dates import format_date
import requests
from datetime import datetime
from django.conf import settings
from django.db.models import F, ExpressionWrapper, FloatField, Value
from django.db.models.functions import Coalesce

from django.http import (HttpResponse, HttpResponseRedirect, StreamingHttpResponse,
                         HttpResponseNotAllowed, JsonResponse, HttpResponseBadRequest)
from django.db.models import Q
from django.template import RequestContext, loader
from django.utils import timezone
from django.shortcuts import get_object_or_404
from juloserver.minisquad.services import is_eligible_for_in_app_ptp
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
)
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView
from rest_framework.generics import (
    ListCreateAPIView,
    ListAPIView,
    CreateAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.authentication import SessionAuthentication

from juloserver.streamlined_communication.utils import (
    add_thousand_separator,
    format_date_indo,
    format_campaign_name,
    get_total_sms_price,
)
from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.julo.statuses import (
    JuloOneCodes,
    PaymentStatusCodes,
    Statuses,
    ApplicationStatusCodes,
    LoanStatusCodes,
    CreditCardCodes,
)
from juloserver.portal.object import julo_login_required, julo_login_required_group
from juloserver.sdk.services import is_customer_has_good_payment_histories
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
    StrictStandardizedExceptionHandlerMixin,
)
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    response_template,
    unauthorized_error_response,
)
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    Product,
    CardProperty,
    TemplateCode,
    ImageType,
    StreamlinedCommCampaignConstants,
    CommsUserSegmentConstants,
    IMAGE_FOR_SLIK_NOTIFICATION,
)
from juloserver.streamlined_communication.models import (
    StreamlinedCommunication,
    StreamlinedMessage,
    StreamlinedCommunicationParameterList,
    StreamlinedCommunicationFunctionList,
    StreamlinedVoiceMessage,
    InfoCardProperty,
    InfoCardButtonProperty,
    SmsVendorRequest,
    StreamlinedCommunicationCampaign,
    StreamlinedCampaignDepartment,
    StreamlinedCommunicationSegment,
    StreamlinedCampaignSquad,
    CommsCampaignSmsHistory,
)
from juloserver.reminder.models import CallRecordUrl
from juloserver.julo.clients import get_julo_sentry_client, get_voice_client, get_julo_sms_client
from juloserver.julo.models import (
    Partner,
    Payment,
    Image,
    CommsBlocked,
    Loan,
    ProductLine,
    Customer,
    JobType,
    FeatureSetting,
    OtpLessHistory,
    Application,
)
from juloserver.julo.clients import get_voice_client_v2
from juloserver.julo.services2.reminders import Reminder
from juloserver.julo.constants import (
    FeatureNameConst,
    VendorConst,
    ReminderTypeConst,
    CommsConst,
    WorkflowConst,
    ProductLineCodes,
    IdentifierKeyHeaderAPI,
)
from juloserver.account.constants import AccountConstant
from juloserver.julo.exceptions import VoiceNotSent
from juloserver.streamlined_communication.serializers import (
    InfoCardSerializer,
    PushNotificatonPermissionSerializer,
    NotificationActionType,
    NotificationSellOffWhiteList,
    StreamlinedCommunicationCampaignListSerializer,
    StreamlinedCommunicationCampaignCreateSerializer,
    CommsCampaignPhoneNumberSerializer,
    StreamlinedCommunicationCampaignDetailSerializer,
)
from juloserver.streamlined_communication.services import (
    format_info_card_data,
    create_and_upload_image_assets_for_streamlined,
    format_info_card_for_android,
    is_already_have_transaction,
    is_info_card_expired,
    process_pn_logging,
    process_sms_message_j1,
    is_first_time_user_paid_for_first_installment,
    validate_action,
    get_loan_info_card,
    get_neo_banner,
    get_reminder_streamlined_comms_by_dpd,
    show_ipa_banner,
    show_ipa_banner_v2,
    get_neo_info_cards,
    get_selloff_content,
    get_slik_data,
    is_show_new_ptp_card,
)
from juloserver.streamlined_communication.services import (
    checking_rating_shown,
    upload_image_assets_for_streamlined_pn,
    determine_main_application_infocard,
    check_application_are_rejected_status,
    get_app_deep_link_list,
    extra_rules_for_info_cards,
)
from django.db import transaction
from juloserver.apiv2.services import (
    get_eta_time_for_c_score_delay,
    check_iti_repeat)
from juloserver.apiv2.models import EtlJob
from juloserver.julo_privyid.services.privy_services import get_info_cards_privy
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment, CashbackClaim
from juloserver.loan_refinancing.services.loan_related import get_unpaid_payments
from juloserver.moengage.services.use_cases import send_user_attributes_to_moengage_for_block_comms

from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.loan.services.loan_related import (
    is_product_locked,
    get_loan_credit_card_inactive,
    get_loan_duration,
    get_credit_matrix_and_credit_matrix_product_line,
)
from juloserver.julo.clients.infobip import (
    JuloInfobipClient,
    JuloInfobipVoiceClient,
)
from juloserver.loan.services.loan_prize_chance import (
    get_prize_chances_by_application,
)
from juloserver.streamlined_communication.tasks import (
    send_sms_campaign_async,
    handle_failed_campaign_and_notify_slack,
    set_campaign_status_partial_or_done,
)
from juloserver.integapiv1.tasks2.callback_tasks import update_voice_call_record
from ..integapiv1.serializers import VoiceCallbackResultSerializer
from ..julo.clients.alicloud import JuloAlicloudClient
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
    format_valid_e164_indo_phone_number,
)
from juloserver.julo.exceptions import InvalidPhoneNumberError
from ..minisquad.services import is_eligible_for_in_app_callback
from juloserver.streamlined_communication.exceptions import (
    ApplicationNotFoundException,
    MissionEnableStateInvalid,
    StreamlinedCommunicationException
)

from juloserver.referral.services import show_referral_code

from juloserver.julo.workflows2.tasks import do_advance_ai_id_check_task

from juloserver.autodebet.services.account_services import (
    is_autodebet_whitelist_feature_active,
    get_existing_autodebet_account,
    is_disabled_autodebet_activation,
    is_idfy_autodebet_valid,
)
from juloserver.autodebet.services.idfy_service import is_idfy_profile_exists
from juloserver.autodebet.services.benefit_services import get_autodebet_benefit_data
from juloserver.autodebet.constants import AutodebetVendorConst
from juloserver.income_check.services import check_salary_izi_data, is_income_in_range

from juloserver.application_flow.services import (
    is_experiment_application,
    JuloOneService,
    get_expiry_hsfbp,
    is_hsfbp_hold_with_status,
)

from juloserver.bpjs.services import check_submitted_bpjs
from juloserver.boost.services import check_scrapped_bank
from juloserver.ana_api.models import SdBankAccount, SdBankStatementDetail
from juloserver.collection_hi_season.services import create_collection_hi_season_promo_card
from ..moengage.constants import UNSENT_MOENGAGE
from juloserver.application_form.services.application_infocard_service import (
    is_active_session_limit_infocard,
    message_info_card_for_reapply_duration,
)
from juloserver.julo_starter.services.services import user_have_upgrade_application
from juloserver.account.services.credit_limit import is_using_turbo_limit

from juloserver.julo.tasks import send_otpless_sms_request
from juloserver.partnership.leadgenb2b.onboarding.services import is_income_in_range_leadgen_partner
from juloserver.julo_starter.constants import JuloStarter190RejectReason
from juloserver.new_crm.services import streamlined_services
from juloserver.partnership.services.services import is_income_in_range_agent_assisted_partner
from juloserver.pin.decorators import parse_device_ios_user
from juloserver.julo.utils import get_oss_public_url
from juloserver.account_payment.constants import CashbackClaimConst


logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_group('product_manager')
def streamlined_communication(request):
    ptp_option_list = list(range(-10, 211))
    ptp_option_list.insert(0, "real-time")
    listParametersAll = StreamlinedCommunicationParameterList.objects.all()
    listParametersUnique = listParametersAll.filter(is_ptp=False).distinct('parameter_name').\
        order_by('parameter_name')

    listParamsInfoCard = listParametersAll.filter(platform=CommunicationPlatform.INFO_CARD)

    app_deeplink_list = get_app_deep_link_list()
    template_name = 'streamlined_communication/list.html'
    data = {
        'listEmail': [],
        'listSMS': [],
        'listIAN': [],
        'listPN': [],
        'listWhatsapp': [],
        'listRobocall': [],
        'listInfoCard': [],
        'listPaymentWidget': [],
        'listSlikNotification' : [],
        'listParameter': listParametersUnique,
        'listParameterAll': listParametersAll,
        'listParameterInfoCard': listParamsInfoCard,
        'listParamsPN': listParametersUnique,
        'listParamsSMS': listParametersUnique.filter(
            platform=CommunicationPlatform.SMS),
        'listParamsEmail': listParametersUnique,
        'listVoiceMessages': StreamlinedVoiceMessage.objects.all(),
        'listFunction': StreamlinedCommunicationFunctionList.objects.all(),
        'statusCodes': Statuses,
        'dpdOption': list(range(-70, 211)),
        'ptpOption': ptp_option_list,
        'dpdOptionLower': list(range(-70, 211)),
        'dpdOptionUpper': list(range(-70, 211)),
        'hrOption': list(range(0, 24)),
        'minOption': list(range(0, 60)),
        'communicationPlatforms': CommunicationPlatform.CHOICES,
        'listRobocallFunction': StreamlinedCommunicationFunctionList.objects.filter(
            communication_platform=CommunicationPlatform.ROBOCALL
        ),
        'email_products': Product.EMAIL_PRODUCTS,
        'sms_products': Product.SMS_PRODUCTS,
        'robocall_products': Product.ROBOCALL_PRODUCTS,
        'pn_products': Product.PN_PRODUCTS,
        'info_card_type_choices': CardProperty.CARD_TYPE_CHOICES_FOR_FORM,
        'info_card_product': CardProperty.CARD_PRODUCT_CHOICES_FOR_FORM,
        'app_deeplink_list': app_deeplink_list,
        'base_url': settings.BASE_URL,
        'extra_condition_option': CardProperty.EXTRA_CONDITION,
        'infocard_expiry_feature': False,
        'partners': Partner.objects.all(),
    }
    template = loader.get_template(template_name)
    application_status = request.GET.get('application_status')
    dpd = request.GET.get('status_dpd')
    ptp = request.GET.get('status_ptp')
    dpd_lower = request.GET.get('status_dpd_lower')
    dpd_upper = request.GET.get('status_dpd_upper')
    until_paid = request.GET.get('until_paid')
    extra_condition = request.GET.get('extra_condition')
    selected_category = request.GET.get('selected_category')

    default_active_tab = (
        request.GET.get('default_active_tab_filter')
        if request.GET.get('default_active_tab_filter')
        else 'info_card'
    )

    if request.POST:
        active_tab = request.POST.get('active_tab')
        default_active_tab = request.POST.get('default_active_tab') if request.POST.get('default_active_tab') \
            else active_tab

        # this id is for StreamlinedCommunication
        updated_streamlined_comm_ids = request.POST.get('updated_message_id_{}'.format(active_tab))
        new_streamlined_comm_ids = request.POST.get('new_message_id_{}'.format(active_tab))
        deleted_streamlined_comm_ids = request.POST.get('deleted_message_id_{}'.format(active_tab))
        delete_msg_id = request.POST.get('delete_msg_id_{}'.format(active_tab))
        update_msg_id_automated = request.POST.get('update_msg_id_automated_{}'.format(active_tab))

        if active_tab in ('sms', 'robocall', 'pn', 'email'):
            if delete_msg_id:
                streamlined_communication = StreamlinedCommunication.objects.get_or_none(
                    pk=delete_msg_id)
                if streamlined_communication:
                    streamlined_communication.delete()
            if update_msg_id_automated:
                for streamlined_comm_id in update_msg_id_automated.split(','):
                    if streamlined_comm_id:
                        msg_automated = request.POST.get(
                            'msg_active_and_automated-{}'.format(streamlined_comm_id))
                        is_automated = True if msg_automated else False
                        StreamlinedCommunication.objects.filter(
                            id=streamlined_comm_id).update(is_automated=is_automated)
                default_active_tab = active_tab
        elif active_tab == 'parameterlist':
            if delete_msg_id:
                streamlined_communication = StreamlinedCommunicationParameterList.objects \
                    .get_or_none(pk=delete_msg_id)
                if streamlined_communication:
                    streamlined_communication.delete()
        elif active_tab == 'functionlist':
            if updated_streamlined_comm_ids:
                for streamlined_comm_id in updated_streamlined_comm_ids.split(','):
                    function_name = request.POST.get('function-{}'.format(streamlined_comm_id))
                    description = request.POST.get(
                        'description-function-{}'.format(streamlined_comm_id))
                    platform = request.POST.get('platform-function-{}'.format(streamlined_comm_id))
                    function = StreamlinedCommunicationFunctionList.objects.get_or_none(
                        pk=streamlined_comm_id)
                    if function:
                        function.update_safely(function_name=function_name, description=description,
                                               communication_platform=platform)
            if new_streamlined_comm_ids:
                for streamlined_comm_id in new_streamlined_comm_ids.split(','):
                    function_name = request.POST.get('function-{}'.format(streamlined_comm_id))
                    description = request.POST.get(
                        'description-function-{}'.format(streamlined_comm_id))
                    platform = request.POST.get('platform-function-{}'.format(streamlined_comm_id))
                    function = StreamlinedCommunicationFunctionList.objects.create(
                        function_name=function_name,
                        description=description,
                        communication_platform=platform
                    )
            if deleted_streamlined_comm_ids:
                for streamlined_comm_id in deleted_streamlined_comm_ids.split(','):
                    functionlist = StreamlinedCommunicationFunctionList.objects.get_or_none(
                        pk=streamlined_comm_id)
                    if functionlist:
                        functionlist.delete()
        elif active_tab in ['widgetduedate', 'sliknotification']:
            if delete_msg_id:
                streamlined_communication = StreamlinedCommunication.objects.get_or_none(
                    pk=delete_msg_id
                )
                if streamlined_communication:
                    streamlined_communication.delete()
            if update_msg_id_automated:
                for streamlined_comm_id in update_msg_id_automated.split(','):
                    if streamlined_comm_id:
                        msg_automated = request.POST.get(
                            'msg_active_and_automated-{}'.format(streamlined_comm_id)
                        )
                        is_active = True if msg_automated else False
                        StreamlinedCommunication.objects.filter(id=streamlined_comm_id).update(
                            is_active=is_active
                        )
                default_active_tab = active_tab
        else:
            # update streamlined_communication data when changes
            if updated_streamlined_comm_ids:
                for streamlined_comm_id in updated_streamlined_comm_ids.split(','):
                    message = request.POST.get('message-{}'.format(streamlined_comm_id))
                    description = request.POST.get('description-{}'.format(streamlined_comm_id))
                    status = request.POST.get('status-{}'.format(streamlined_comm_id))
                    streamlined_communication = StreamlinedCommunication.objects.get_or_none(
                        pk=streamlined_comm_id)
                    if streamlined_communication:
                        message_communication = streamlined_communication.message
                        message_communication.update_safely(message_content=message)
                        streamlined_communication.update_safely(
                            description=description, status=status)
            if new_streamlined_comm_ids:
                for streamlined_comm_id in new_streamlined_comm_ids.split(','):
                    message = request.POST.get('message-{}'.format(streamlined_comm_id))
                    description = request.POST.get('description-{}'.format(streamlined_comm_id))
                    status = request.POST.get('status-{}'.format(streamlined_comm_id))
                    new_streamlined_message = StreamlinedMessage.objects.create(
                        message_content=message)
                    data_for_create = dict(message=new_streamlined_message,
                                           description=description,
                                           communication_platform=active_tab.upper(),
                                           status=status, )
                    if application_status:
                        data_for_create['status_code_id'] = application_status
                    if dpd:
                        data_for_create['dpd'] = int(dpd)
                    if ptp:
                        data_for_create['ptp'] = ptp
                    if (dpd_lower and dpd_upper and (int(dpd_lower) < int(dpd_upper))) \
                            or (dpd_lower and until_paid):
                        if dpd_lower and dpd_upper:
                            data_for_create['dpd_upper'] = dpd_upper
                            data_for_create['dpd_lower'] = dpd_lower
                        else:
                            data_for_create['dpd_lower'] = dpd_lower
                            data_for_create['until_paid'] = True

                    new_streamlined_communication = StreamlinedCommunication.objects.create(
                        **data_for_create)
            if deleted_streamlined_comm_ids:
                for streamlined_comm_id in deleted_streamlined_comm_ids.split(','):
                    streamlined_communication = StreamlinedCommunication.objects.get_or_none(
                        pk=streamlined_comm_id)
                    if streamlined_communication:
                        streamlined_communication.delete()
        return HttpResponseRedirect('/streamlined_communication/list/?application_status={}&status_dpd={}&status_ptp={}'
                                    '&default_active_tab={}&status_dpd_lower={}&status_dpd_upper={}'
                                    .format(application_status, dpd, ptp, default_active_tab, dpd_lower, dpd_upper))
    if request.GET and (application_status or dpd or ptp or dpd_upper or dpd_lower or until_paid or extra_condition):
        Q_filter_email_ = Q()
        Q_filter_sms_ = Q()
        Q_filter_ian_ = Q()
        Q_filter_wa_ = Q()
        Q_filter_pn_ = Q()
        Q_filter_robocall_ = Q()
        Q_filter_info_card_ = Q()
        Q_filter_payment_widget_ = Q()
        Q_filter_slik_notification_ = Q()
        filter_email_ = dict(
            communication_platform=CommunicationPlatform.EMAIL,
        )
        filter_sms_ = dict(
            communication_platform=CommunicationPlatform.SMS,
        )
        filter_ian_ = dict(
            communication_platform=CommunicationPlatform.IAN,
        )
        filter_wa_ = dict(
            communication_platform=CommunicationPlatform.WA,
        )
        filter_pn_ = dict(
            communication_platform=CommunicationPlatform.PN,
        )
        filter_robocall_ = dict(
            communication_platform=CommunicationPlatform.ROBOCALL,
        )
        filter_info_card_ = dict(
            communication_platform=CommunicationPlatform.INFO_CARD,
        )
        filter_payment_widget_ = dict(
            communication_platform=CommunicationPlatform.PAYMENT_WIDGET,
        )
        filter_slik_notification_ = dict(
            communication_platform=CommunicationPlatform.SLIK_NOTIFICATION,
        )

        if application_status:
            converted_application_status = int(application_status)
            data['selected_status_code'] = converted_application_status
            filter_email_['status_code'] = converted_application_status
            filter_sms_['status_code'] = converted_application_status
            filter_ian_['status_code'] = converted_application_status
            filter_wa_['status_code'] = converted_application_status
            filter_robocall_['status_code'] = converted_application_status
            filter_pn_['status_code'] = converted_application_status
            filter_info_card_['status_code'] = converted_application_status
            filter_payment_widget_['status_code'] = converted_application_status
            filter_slik_notification_['status_code'] = converted_application_status

        if until_paid:
            data['until_paid'] = True
            data['selected_dpd_upper'] = None
            dpd_upper = None

        if dpd:
            converted_dpd = int(dpd)
            data['selected_dpd'] = converted_dpd
            Q_filter_email_ |= Q(dpd=converted_dpd) & (Q(dpd_lower__isnull=True))
            Q_filter_sms_ |= Q(dpd=converted_dpd) & Q(dpd_lower__isnull=True)
            Q_filter_ian_ |= Q(dpd=converted_dpd) & Q(dpd_lower__isnull=True)
            Q_filter_wa_ |= Q(dpd=converted_dpd) & Q(dpd_lower__isnull=True)
            Q_filter_robocall_ |= Q(dpd=converted_dpd) & Q(dpd_lower__isnull=True)
            Q_filter_pn_ |= Q(dpd=converted_dpd) & Q(dpd_lower__isnull=True)
            Q_filter_info_card_ |= Q(dpd=converted_dpd) & Q(dpd_lower__isnull=True)
            Q_filter_payment_widget_ |= Q(dpd=converted_dpd) & Q(dpd__isnull=False)
            Q_filter_slik_notification_ |= Q(dpd=converted_dpd) & Q(dpd__isnull=False)
            Q_filter_email_ |= (Q(dpd_upper__lte=converted_dpd) & Q(dpd_upper__isnull=False)) & (
                Q(dpd_lower__gte=converted_dpd) & Q(dpd_lower__isnull=False)
            )
            Q_filter_sms_ |= (Q(dpd_upper__lte=converted_dpd) & Q(dpd_upper__isnull=False)) & (
                Q(dpd_lower__gte=converted_dpd) & Q(dpd_lower__isnull=False)
            )
            Q_filter_ian_ |= (Q(dpd_upper__lte=converted_dpd) & Q(dpd_upper__isnull=False)) & (
                Q(dpd_lower__gte=converted_dpd) & Q(dpd_lower__isnull=False)
            )
            Q_filter_wa_ |= (Q(dpd_upper__lte=converted_dpd) & Q(dpd_upper__isnull=False)) & (
                Q(dpd_lower__gte=converted_dpd) & Q(dpd_lower__isnull=False)
            )
            Q_filter_robocall_ |= (Q(dpd_upper__lte=converted_dpd) & Q(dpd_upper__isnull=False)) & (
                Q(dpd_lower__gte=converted_dpd) & Q(dpd_lower__isnull=False)
            )
            Q_filter_pn_ |= (Q(dpd_upper__lte=converted_dpd) & Q(dpd_upper__isnull=False)) & (
                Q(dpd_lower__gte=converted_dpd) & Q(dpd_lower__isnull=False)
            )
            Q_filter_info_card_ |= (
                Q(dpd_upper__gte=converted_dpd) & Q(dpd_upper__isnull=False)
            ) & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False))

            Q_filter_email_ |= (Q(until_paid=True)
                                & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False)))
            Q_filter_sms_ |= (Q(until_paid=True)
                              & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False)))
            Q_filter_ian_ |= (Q(until_paid=True)
                              & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False)))
            Q_filter_wa_ |= (Q(until_paid=True)
                             & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False)))
            Q_filter_robocall_ |= (Q(until_paid=True)
                                   & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False)))
            Q_filter_pn_ |= (Q(until_paid=True)
                             & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False)))
            Q_filter_info_card_ |= (Q(until_paid=True)
                                    & (Q(dpd_lower__lte=converted_dpd) & Q(dpd_lower__isnull=False)))

        if (dpd_upper and dpd_lower and (int(dpd_lower) <= int(dpd_upper))) or (dpd_lower and until_paid):
            converted_dpd_lower = int(dpd_lower)
            data['selected_dpd_lower'] = converted_dpd_lower
            if dpd_upper and dpd_lower:
                converted_dpd_upper = int(dpd_upper)
                data['selected_dpd_upper'] = converted_dpd_upper
                Q_filter_email_ |= ((Q(dpd__lte=converted_dpd_upper) & Q(dpd_upper__isnull=True))
                                    & (Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)))
                Q_filter_sms_ |= ((Q(dpd__lte=converted_dpd_upper) & Q(dpd_upper__isnull=True))
                                  & (Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)))
                Q_filter_ian_ |= ((Q(dpd__lte=converted_dpd_upper) & Q(dpd_upper__isnull=True))
                                  & (Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)))
                Q_filter_wa_ |= ((Q(dpd__lte=converted_dpd_upper) & Q(dpd_upper__isnull=True))
                                 & (Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)))
                Q_filter_robocall_ |= ((Q(dpd__lte=converted_dpd_upper) & Q(dpd_upper__isnull=True))
                                       & (Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)))
                Q_filter_pn_ |= ((Q(dpd__lte=converted_dpd_upper) & Q(dpd_upper__isnull=True))
                                 & (Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)))
                Q_filter_info_card_ |= ((Q(dpd__lte=converted_dpd_upper) & Q(dpd_upper__isnull=True))
                                        & (Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)))

                Q_filter_email_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_sms_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_ian_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_wa_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_robocall_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_pn_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_info_card_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_payment_widget_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_slik_notification_ |= (
                    Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                ) & (Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False))
                Q_filter_email_ |= (Q(until_paid=True)) & (
                    Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False)
                )
                Q_filter_sms_ |= (Q(until_paid=True)) & (
                    Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False)
                )
                Q_filter_ian_ |= (Q(until_paid=True)) & (
                    Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False)
                )
                Q_filter_wa_ |= (Q(until_paid=True)) & (
                    Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False)
                )
                Q_filter_robocall_ |= (Q(until_paid=True)) & (
                    Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False)
                )
                Q_filter_pn_ |= (Q(until_paid=True)) & (
                    Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False)
                )
                Q_filter_info_card_ |= (Q(until_paid=True)) & (
                    Q(dpd_lower__lte=converted_dpd_upper) & Q(dpd_lower__isnull=False)
                )

            else:
                Q_filter_email_ |= Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)
                Q_filter_sms_ |= Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)
                Q_filter_ian_ |= Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)
                Q_filter_wa_ |= Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)
                Q_filter_robocall_ |= Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)
                Q_filter_pn_ |= Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)
                Q_filter_info_card_ |= Q(dpd__gte=converted_dpd_lower) & Q(dpd_lower__isnull=True)
                Q_filter_payment_widget_ |= Q(dpd__gte=converted_dpd_lower) & Q(
                    dpd_lower__isnull=True
                )
                Q_filter_slik_notification_ |= Q(dpd__gte=converted_dpd_lower) & Q(
                    dpd_lower__isnull=True
                )

                Q_filter_email_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(
                    dpd_upper__isnull=False
                )
                Q_filter_sms_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                Q_filter_ian_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                Q_filter_wa_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                Q_filter_robocall_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(
                    dpd_upper__isnull=False
                )
                Q_filter_pn_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(dpd_upper__isnull=False)
                Q_filter_info_card_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(
                    dpd_upper__isnull=False
                )
                Q_filter_payment_widget_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(
                    dpd_upper__isnull=False
                )
                Q_filter_slik_notification_ |= Q(dpd_upper__gte=converted_dpd_lower) & Q(
                    dpd_upper__isnull=False
                )

                Q_filter_email_ |= Q(until_paid=True)
                Q_filter_sms_ |= Q(until_paid=True)
                Q_filter_ian_ |= Q(until_paid=True)
                Q_filter_wa_ |= Q(until_paid=True)
                Q_filter_robocall_ |= Q(until_paid=True)
                Q_filter_pn_ |= Q(until_paid=True)
                Q_filter_info_card_ |= Q(until_paid=True)
                Q_filter_payment_widget_ |= Q(until_paid=True)
                Q_filter_slik_notification_ |= Q(until_paid=True)

        if dpd_upper:
            converted_dpd_upper = int(dpd_upper)
            data['selected_dpd_upper'] = converted_dpd_upper

        if dpd_lower:
            converted_dpd_lower = int(dpd_lower)
            data['selected_dpd_lower'] = converted_dpd_lower

        if ptp:
            converted_ptp = ptp if ptp == 'real-time' else int(ptp)
            data['selected_ptp'] = converted_ptp
            filter_email_['ptp'] = converted_ptp
            filter_sms_['ptp'] = converted_ptp
            filter_ian_['ptp'] = converted_ptp
            filter_wa_['ptp'] = converted_ptp
            filter_robocall_['ptp'] = converted_ptp
            filter_pn_['ptp'] = converted_ptp
            filter_info_card_['ptp'] = converted_ptp
            filter_payment_widget_['ptp'] = converted_ptp
            filter_slik_notification_['ptp'] = converted_ptp

            data['listParamsSMS'] = listParametersAll.filter(
                platform=CommunicationPlatform.SMS, is_ptp=True)
            data['listParamsEmail'] = listParametersAll.filter(
                platform=CommunicationPlatform.EMAIL, is_ptp=True)
            data['listParamsPN'] = listParametersAll.filter(
                platform=CommunicationPlatform.PN, is_ptp=True)

        if extra_condition:
            data['selected_extra_condition'] = extra_condition
            filter_email_['extra_conditions'] = extra_condition
            filter_sms_['extra_conditions'] = extra_condition
            filter_ian_['extra_conditions'] = extra_condition
            filter_wa_['extra_conditions'] = extra_condition
            filter_robocall_['extra_conditions'] = extra_condition
            filter_pn_['extra_conditions'] = extra_condition
            filter_info_card_['extra_conditions'] = extra_condition
            filter_payment_widget_['extra_conditions'] = extra_condition
            filter_slik_notification_['extra_conditions'] = extra_condition
        else:
            filter_info_card_['extra_conditions__isnull'] = True

        if selected_category:
            data['selected_category'] = selected_category
            if selected_category == 'backup':
                filter_email_['extra_conditions'] = UNSENT_MOENGAGE
                filter_pn_['extra_conditions'] = UNSENT_MOENGAGE
            else:
                filter_email_['extra_conditions__isnull'] = True
                filter_pn_['extra_conditions__isnull'] = True

        data['listEmail'] = (
            StreamlinedCommunication.objects.filter(Q_filter_email_)
            .filter(**filter_email_)
            .values(
                'id',
                'status',
                'dpd',
                'message__message_content',
                'description',
                'message__parameter',
                'template_code',
                'moengage_template_code',
                'subject',
                'product',
                'type',
                'time_sent',
                'is_automated',
                'pre_header',
                'partner_selection_list',
                'partner_selection_action',
                'extra_conditions',
                'julo_gold_status',
            )
            .order_by('product')
        )
        data['listSMS'] = (
            StreamlinedCommunication.objects.filter(Q_filter_sms_)
            .filter(**filter_sms_)
            .values(
                'id',
                'status',
                'dpd',
                'message__message_content',
                'description',
                'message__parameter',
                'template_code',
                'product',
                'type',
                'time_sent',
                'is_automated',
                'partner_selection_list',
                'partner_selection_action',
                'julo_gold_status',
            )
            .order_by('product')
        )
        data['listIAN'] = (
            StreamlinedCommunication.objects.filter(Q_filter_ian_)
            .filter(**filter_ian_)
            .values(
                'id',
                'status',
                'dpd',
                'message__message_content',
                'description',
                'message__parameter',
                'is_automated',
                'template_code',
            )
        )
        data['listPN'] = (
            StreamlinedCommunication.objects.filter(Q_filter_pn_)
            .filter(**filter_pn_)
            .values(
                'id',
                'status',
                'dpd',
                'message__message_content',
                'description',
                'message__parameter',
                'template_code',
                'moengage_template_code',
                'subject',
                'heading_title',
                'product',
                'type',
                'time_sent',
                'is_automated',
                'extra_conditions',
            )
            .order_by('product')
        )
        data['listWhatsapp'] = (
            StreamlinedCommunication.objects.filter(Q_filter_wa_)
            .filter(**filter_wa_)
            .values(
                'id',
                'status',
                'dpd',
                'message__message_content',
                'description',
                'message__parameter',
                'is_automated',
                'template_code',
            )
        )
        data['listRobocall'] = (
            StreamlinedCommunication.objects.filter(Q_filter_robocall_)
            .filter(**filter_robocall_)
            .values(
                'id',
                'status',
                'dpd',
                'message__message_content',
                'description',
                'message__parameter',
                'template_code',
                'function_name',
                'product',
                'type',
                'attempts',
                'call_hours',
                'is_automated',
                'time_out_duration',
                'exclude_risky_customer',
                'partner_selection_list',
                'partner_selection_action',
                'criteria',
                'julo_gold_status',
            )
            .order_by('product')
        )
        data['listPaymentWidget'] = (
            StreamlinedCommunication.objects
            .filter(Q_filter_payment_widget_)
            .filter(**filter_payment_widget_)
            .values('id', 'template_code', 'product', 'is_active', 'payment_widget_properties')
            .order_by('product')
        )
        data['listSlikNotification'] = (
            StreamlinedCommunication.objects
            .filter(Q_filter_slik_notification_)
            .filter(**filter_slik_notification_)
            .values('id', 'template_code', 'product', 'is_active', 'slik_notification_properties')
            .order_by('product')
        )
        info_card_qs = (
            StreamlinedCommunication.objects.filter(Q_filter_info_card_)
            .filter(**filter_info_card_)
            .order_by('message__info_card_property__card_order_number')
        )
        data['listInfoCard'] = format_info_card_data(info_card_qs)
        max_range = 0
        if info_card_qs:
            max_range = info_card_qs.values_list(
                'message__info_card_property__card_order_number', flat=True
            )
            maximum_qs = max(list(max_range))
            maximum_count = info_card_qs.count()
            maximum_count = maximum_count if maximum_count > maximum_qs else maximum_qs
            max_range = list(range(1, maximum_count + 1))
        data['max_order_info_card'] = max_range

    if default_active_tab not in ('sms', 'parameterlist', 'pn', 'email') and ptp == 'real-time':
        default_active_tab = 'email'
    if (dpd or ptp or dpd_upper or dpd_lower or until_paid):
        data['infocard_expiry_feature'] = False
    elif (application_status or (application_status and extra_condition)):
        data['infocard_expiry_feature'] = True

    data['show'] = True
    data['default_active_tab'] = default_active_tab
    context = RequestContext(request, data)
    return HttpResponse(template.render(context))


@julo_login_required
@julo_login_required_group('product_manager')
def download_call_record(request):
    template_name = 'streamlined_communication/call_record_downloader.html'
    template = loader.get_template(template_name)
    context = {'user': request.user}
    context['show'] = True
    uuid = request.GET.get('record_uuid')
    if not uuid:
        return HttpResponse(template.render(context))
    context['record_uuid'] = uuid
    try:
        call_record_url = CallRecordUrl.objects.filter(
            Q(recording_uuid=uuid)
            | Q(recording_url=uuid)
        ).first()
        if not call_record_url:
            context['message'] = 'Recording UUID/Call Record URL ID is not found'
            return HttpResponse(template.render(context))

        url = call_record_url.recording_url
        voice_client = get_voice_client()
        headers = voice_client.get_headers()
        with requests.get(url, headers=headers, stream=True) as response_stream:
            if response_stream.raw.status != 200:
                context['message'] = 'Failed due to Bad Credentials'
                return HttpResponse(template.render(context))
            response = StreamingHttpResponse(
                streaming_content=response_stream.raw.read(decode_content=True), content_type='audio/mpeg'
            )
            response['Content-Disposition'] = 'attachment; filename="' + \
                call_record_url.recording_uuid + '.mp3"'
            return response

    except Exception as e:
        context['message'] = e
        return HttpResponse(template.render(context))


@julo_login_required
@julo_login_required_group('product_manager')
def update_sms_details(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    sms_type = data['sms_type']
    sms_product = data['sms_product']
    sms_hour = data['sms_hour']
    sms_minute = data['sms_minute']
    sms_template_code = data['sms_template_code']
    sms_content = data['sms_content']
    sms_description = data['sms_description']
    sms_msg_id = data['sms_msg_id']
    sms_parameters = data['sms_parameters']
    communication_platform = 'SMS'
    dpd = data['dpd']
    ptp = data['ptp']
    application_status = data['application_status']
    dpd_from = data['dpd_from']
    dpd_until = data['dpd_until']
    partners_selection = data.get('partners_selection')
    partners_selection_action = data.get('partners_selection_action')
    sms_julo_gold_status = data.get('sms_julo_gold_status')
    if sms_julo_gold_status == 'null':
        sms_julo_gold_status = None
    partners_selection_list = []
    if partners_selection:
        partners_selection_list = partners_selection.split(",")

    filter = dict(template_code=sms_template_code,
                  communication_platform=communication_platform)
    if sms_msg_id:
        template_code_count = StreamlinedCommunication.objects.filter(**filter)\
            .exclude(id=sms_msg_id).count()
    else:
        template_code_count = StreamlinedCommunication.objects.filter(**filter).count()
    response_data = {}
    if sms_minute:
        time = sms_hour + ":" + sms_minute
    else:
        time = sms_hour
    if template_code_count > 0:
        response_data['msg'] = 'Template Code already exists'
        response_data['status'] = 'Failure'
        return JsonResponse({
            'data': response_data
        })
    data_for_create = dict(
        description=sms_description,
        template_code=sms_template_code,
        type=sms_type,
        product=sms_product,
        time_sent=time,
        partner_selection_list=partners_selection_list,
        partner_selection_action=partners_selection_action,
        julo_gold_status=sms_julo_gold_status,
    )
    if dpd:
        data_for_create['dpd'] = int(dpd)
    if ptp:
        data_for_create['ptp'] = ptp
    if application_status:
        data_for_create['status_code_id'] = application_status
    if dpd_from != '':
        data_for_create['dpd_lower'] = int(dpd_from)
    if dpd_until != '':
        data_for_create['dpd_upper'] = int(dpd_until)
    if dpd_until != '' and dpd_from != '':
        if dpd:
            del data_for_create['dpd_lower']
            del data_for_create['dpd_upper']

    if sms_msg_id:
        streamlined_message = StreamlinedCommunication.objects.get_or_none(
            id=sms_msg_id)
        if not streamlined_message:
            response_data['msg'] = 'Template not exists'
            response_data['status'] = 'Failure'
            return JsonResponse({
                'data': response_data
            })
        StreamlinedMessage.objects.filter(id=streamlined_message.message.id) \
            .update(message_content=sms_content, parameter='{' + sms_parameters + '}')
        old_streamlined = StreamlinedCommunication.objects.get(id=sms_msg_id)
        if old_streamlined.dpd:
            if data_for_create.get('dpd_lower'):
                del data_for_create['dpd_lower']
            if data_for_create.get('dpd_upper'):
                del data_for_create['dpd_upper']

        old_streamlined.update_safely(**data_for_create)
        response_data['msg'] = 'SMS details updated successfully'
    else:
        new_streamlined_message = StreamlinedMessage.objects.create(message_content=sms_content,
                                                                    parameter='{' + sms_parameters + '}')
        data_for_create['communication_platform'] = communication_platform
        data_for_create['message'] = new_streamlined_message
        data_for_create['is_automated'] = True
        new_streamlined_communication = StreamlinedCommunication.objects.create(**data_for_create)
        response_data['msg'] = 'SMS details added successfully'
    response_data['status'] = 'Success'
    return JsonResponse({
        'data': response_data
    })


@julo_login_required
@julo_login_required_group('product_manager')
def update_robocall_details(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    robocall_type = data['robocall_type']
    robocall_product = data['robocall_product']
    robocall_template_code = data['robocall_template_code']
    robocall_content = data['robocall_content']
    robocall_description = data['robocall_description']
    robocall_msg_id = data['robocall_msg_id']
    communication_platform = 'ROBOCALL'
    robocall_call_time = data['robocall_call_time']
    robocall_call_function = data['robocall_call_function']
    robocall_attempts = data['robocall_attempts']
    application_status = data['application_status']
    robocall_parameters = data['robocall_parameters']
    robocall_time_out_duration = data['robocall_time_out_duration']
    robocall_time_out_duration = data['robocall_time_out_duration']
    robocall_exclude_risky = data['robocall_exclude_risky']
    dpd = data['dpd']
    ptp = data['ptp']
    partners_selection = data.get('partners_selection')
    partners_selection_action = data.get('partners_selection_action')
    robocall_segment = data['robocall_segment']
    robocall_julogold_status = data['robocall_julo_gold_status']
    if robocall_julogold_status == 'null':
        robocall_julogold_status = None
    partners_selection_list = []
    if partners_selection:
        partners_selection_list = partners_selection.split(",")
    filter = dict(template_code=robocall_template_code,
                  communication_platform=communication_platform)

    robocall_exclude_risky = (robocall_exclude_risky == 'true')

    if robocall_msg_id:
        template_code_count = StreamlinedCommunication.objects.filter(**filter)\
            .exclude(id=robocall_msg_id).count()
    else:
        template_code_count = StreamlinedCommunication.objects.filter(**filter).count()
    response_data = {}
    if template_code_count > 0:
        response_data['msg'] = 'Template Code already exists'
        response_data['status'] = 'Failure'
        return JsonResponse({'data': response_data})
    data_for_create = dict(
        description=robocall_description,
        template_code=robocall_template_code,
        product=robocall_product,
        type=robocall_type,
        attempts=robocall_attempts,
        call_hours="{" + robocall_call_time + "}",
        function_name="{" + robocall_call_function + "}",
        time_out_duration=robocall_time_out_duration,
        exclude_risky_customer=robocall_exclude_risky,
        partner_selection_list=partners_selection_list,
        partner_selection_action=partners_selection_action,
        criteria={'segment': robocall_segment},
        julo_gold_status=robocall_julogold_status,
    )
    if dpd:
        data_for_create['dpd'] = int(dpd)
    if ptp:
        data_for_create['ptp'] = ptp
    if application_status:
        data_for_create['status_code_id'] = application_status
    if data.get('robocall_extra_condition'):
        data_for_create['extra_conditions'] = data.get('robocall_extra_condition')
    if robocall_msg_id:
        streamlined_message = StreamlinedCommunication.objects.get_or_none(id=robocall_msg_id)
        if not streamlined_message:
            response_data['msg'] = 'Template not exists'
            response_data['status'] = 'Failure'
            return JsonResponse({
                'data': response_data
            })
        StreamlinedMessage.objects.filter(id=streamlined_message.message.id) \
            .update(message_content=robocall_content,
                    parameter='{' + robocall_parameters + '}')
        StreamlinedCommunication.objects.filter(id=robocall_msg_id).update(**data_for_create)
        response_data['msg'] = 'ROBOCALL details updated successfully'
    else:
        new_streamlined_message = StreamlinedMessage.objects.create(message_content=robocall_content,
                                                                    parameter='{' + robocall_parameters + '}')
        data_for_create['communication_platform'] = communication_platform
        data_for_create['message'] = new_streamlined_message
        data_for_create['is_automated'] = True
        new_streamlined_communication = StreamlinedCommunication.objects.create(**data_for_create)
        response_data['msg'] = 'ROBOCALL details added successfully'
    response_data['status'] = 'Success'
    return JsonResponse({
        'data': response_data
    })


@julo_login_required
@julo_login_required_group('product_manager')
def update_pn_details(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]
    data = request.POST.dict()
    pn_category = data['pn_category']
    pn_type = data['pn_type']
    pn_product = data['pn_product']
    pn_hour = data['pn_hour']
    pn_minute = data['pn_minute']
    pn_template_code = data['pn_template_code']
    pn_subject = data['pn_subject']
    pn_content = data['pn_content']
    pn_heading = data['pn_heading']
    pn_description = data['pn_description']
    pn_msg_id = data['pn_msg_id']
    pn_parameters = data['pn_parameters']
    communication_platform = 'PN'
    dpd = data['dpd']
    ptp = data['ptp']
    if 'pn_image' in request.FILES:
        image = request.FILES['pn_image']
        _, file_extension = os.path.splitext(image.name)

        if file_extension not in ['.webp']:
            return JsonResponse(
                {
                    'data': {
                        "status": "Failed",
                        "msg": "Unsupport image type. Please upload webp"
                    }
                }
            )
        elif image._size > 204800:  # 200kb = 204800 bytes (Binary)
            return JsonResponse(
                {
                    'data': {
                        "status": "Failed",
                        "msg": "Unsupport image size. Please upload file less than 200kb"
                    }
                }
            )
    application_status = data['application_status']
    filter = dict(template_code=pn_template_code,
                  communication_platform=communication_platform)
    if pn_msg_id:
        template_code_count = StreamlinedCommunication.objects.filter(**filter)\
            .exclude(id=pn_msg_id).count()
    else:
        template_code_count = StreamlinedCommunication.objects.filter(**filter).count()
    response_data = {}
    if pn_minute:
        time = pn_hour + ":" + pn_minute
    else:
        time = pn_hour
    if template_code_count > 0:
        response_data['msg'] = 'Template Code already exists'
        response_data['status'] = 'Failure'
        return JsonResponse({
            'data': response_data
        })

    data_for_create = dict(
        description=pn_description,
        template_code=pn_template_code,
        subject=pn_subject,
        type=pn_type,
        product=pn_product if pn_product else None,
        heading_title=pn_heading,
        time_sent=time if time else None
    )

    if dpd:
        data_for_create['dpd'] = int(dpd)
    if ptp:
        data_for_create['ptp'] = ptp
    if application_status:
        data_for_create['status_code_id'] = application_status
    if pn_category == 'backup':
        if 'pn_moengage_template_code' not in data:
            response_data['msg'] = 'Backup PN must have moengage template code'
            response_data['status'] = 'Failure'

            return JsonResponse({
                'data': response_data
            })

        pn_moengage_template_code = data['pn_moengage_template_code']
        pn_moengage_template_code = pn_moengage_template_code.lstrip().rstrip()
        if len(pn_moengage_template_code) < 1:
            response_data['msg'] = 'Moengage template code cannot contain only whitespace'
            response_data['status'] = 'Failure'

            return JsonResponse({
                'data': response_data
            })

        data_for_create['moengage_template_code'] = pn_moengage_template_code
        data_for_create['extra_conditions'] = UNSENT_MOENGAGE
    else:
        data_for_create['moengage_template_code'] = None
        data_for_create['extra_conditions'] = None
    streamlined_communication_obj = None
    if pn_msg_id:
        streamlined_message = StreamlinedCommunication.objects.get_or_none(id=pn_msg_id)
        if not streamlined_message:
            response_data['msg'] = 'Template not exists'
            response_data['status'] = 'Failure'
            return JsonResponse({
                'data': response_data
            })
        StreamlinedMessage.objects.get(id=streamlined_message.message.id) \
            .update_safely(message_content=pn_content, parameter='{' + pn_parameters + '}')
        streamlined_communication_obj = StreamlinedCommunication.objects.get(id=pn_msg_id)
        streamlined_communication_obj.update_safely(**data_for_create)

        if data.get('pn_image_status') == "Delete":
            _delete_pn_image(pn_msg_id)

        response_data['msg'] = 'PN details updated successfully'
    else:
        new_streamlined_message = StreamlinedMessage.objects.create(message_content=pn_content,
                                                                    parameter='{' + pn_parameters + '}')
        data_for_create['communication_platform'] = communication_platform
        data_for_create['message'] = new_streamlined_message
        data_for_create['is_automated'] = True
        streamlined_communication_obj = StreamlinedCommunication.objects.create(**data_for_create)

        if data.get('pn_image_status') == "Delete":
            _delete_pn_image(pn_msg_id)

        response_data['msg'] = 'PN details added successfully'
    if 'pn_image' in request.FILES:
        upload_image_assets_for_streamlined_pn(
            "streamlined-PN", streamlined_communication_obj.id, ImageType.STREAMLINED_PN, "streamlined-PN/image",
            request.FILES['pn_image']
        )

    response_data['status'] = 'Success'
    return JsonResponse({
        'data': response_data
    })


@julo_login_required
@julo_login_required_group('product_manager')
def update_email_details(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    email_category = data['email_category']
    email_type = data['email_type']
    email_product = data['email_product']
    email_hour = data['email_hour']
    email_minute = data['email_minute']
    email_subject = data['email_subject']
    email_template_code = data['email_template_code']
    email_content = data['email_content']
    email_description = data['email_description']
    email_msg_id = data['email_msg_id']
    email_parameters = data['email_parameters']
    communication_platform = 'EMAIL'
    dpd = data['dpd']
    ptp = data['ptp']
    application_status = data['application_status']
    pre_header = data['pre_header']
    partners_selection = data.get('partners_selection')
    partners_selection_action = data.get('partners_selection_action')
    email_julo_gold_status = data.get('email_julo_gold_status')
    if email_julo_gold_status == 'null':
        email_julo_gold_status = None
    partners_selection_list = []
    if partners_selection:
        partners_selection_list = partners_selection.split(",")
    filter = dict(template_code=email_template_code,
                  communication_platform=communication_platform)
    if dpd:
        filter['dpd'] = dpd
    if ptp:
        filter['ptp'] = ptp

    if email_msg_id:
        template_code_count = StreamlinedCommunication.objects.filter(**filter)\
            .exclude(id=email_msg_id).count()
    else:
        template_code_count = StreamlinedCommunication.objects.filter(**filter).count()
    response_data = {}
    if email_minute:
        time = email_hour + ":" + email_minute
    else:
        time = email_hour
    if template_code_count > 0:
        response_data['msg'] = 'Template Code already exists'
        response_data['status'] = 'Failure'
        return JsonResponse({'data': response_data})
    data_for_create = dict(
        description=email_description,
        subject=email_subject,
        template_code=email_template_code,
        type=email_type,
        product=email_product,
        time_sent=time,
        pre_header=pre_header,
        partner_selection_list=partners_selection_list,
        partner_selection_action=partners_selection_action,
        julo_gold_status=email_julo_gold_status,
    )
    if dpd not in (None, ""):
        data_for_create['dpd'] = int(dpd)
    if ptp not in (None, ""):
        data_for_create['ptp'] = ptp
    if application_status:
        data_for_create['status_code_id'] = application_status
    if email_category == 'backup':
        if 'email_moengage_template_code' not in data:
            response_data['msg'] = 'Backup email must have moengage template code'
            response_data['status'] = 'Failure'

            return JsonResponse({
                'data': response_data
            })

        email_moengage_template_code = data['email_moengage_template_code']
        email_moengage_template_code = email_moengage_template_code.lstrip().rstrip()
        if len(email_moengage_template_code) < 1:
            response_data['msg'] = 'Moengage template code cannot contain only whitespace'
            response_data['status'] = 'Failure'

            return JsonResponse({
                'data': response_data
            })

        data_for_create['moengage_template_code'] = email_moengage_template_code
        data_for_create['extra_conditions'] = UNSENT_MOENGAGE
    else:
        data_for_create['moengage_template_code'] = None
        data_for_create['extra_conditions'] = None

    if email_msg_id:
        streamlined_message = StreamlinedCommunication.objects.get_or_none(id=email_msg_id)
        if not streamlined_message:
            response_data['msg'] = 'Template not exists'
            response_data['status'] = 'Failure'
            return JsonResponse({
                'data': response_data
            })
        StreamlinedMessage.objects.filter(id=streamlined_message.message.id) \
            .update(message_content=email_content, parameter='{' + email_parameters + '}')
        StreamlinedCommunication.objects.filter(id=email_msg_id).update(**data_for_create)
        response_data['msg'] = 'Email details updated successfully'
    else:
        new_streamlined_message = StreamlinedMessage.objects.create(message_content=email_content,
                                                                    parameter='{' + email_parameters + '}')
        data_for_create['communication_platform'] = communication_platform
        data_for_create['message'] = new_streamlined_message
        new_streamlined_communication = StreamlinedCommunication.objects.create(**data_for_create)
        response_data['msg'] = 'Email details added successfully'
    response_data['status'] = 'Success'
    return JsonResponse({
        'data': response_data
    })


@julo_login_required
@julo_login_required_group('product_manager')
def update_parameterlist_details(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    parameterlist_parameter = data['parameterlist_parameter']
    parameterlist_platform = data['parameterlist_platform']
    parameterlist_example = data['parameterlist_example']
    parameterlist_description = data['parameterlist_description']
    parameterlist_msg_id = data['parameterlist_msg_id']
    response_data = {}
    if parameterlist_msg_id:
        streamlined_message = StreamlinedCommunicationParameterList.objects \
            .get_or_none(id=parameterlist_msg_id)
        if not streamlined_message:
            response_data['msg'] = 'Not exists'
            response_data['status'] = 'Failure'
            return JsonResponse({
                'data': response_data
            })

        StreamlinedCommunicationParameterList.objects.filter(id=streamlined_message.id) \
            .update(description=parameterlist_description,
                    platform=parameterlist_platform,
                    example=parameterlist_example,
                    parameter_name='{' + parameterlist_parameter + '}')
        response_data['msg'] = 'Parameter List details updated successfully'
    else:
        StreamlinedCommunicationParameterList.objects \
            .create(description=parameterlist_description,
                    platform=parameterlist_platform,
                    example=parameterlist_example,
                    parameter_name='{' + parameterlist_parameter + '}')
        response_data['msg'] = 'Parameter List details added successfully'
    response_data['status'] = 'Success'
    return JsonResponse({
        'data': response_data
    })


@julo_login_required
@julo_login_required_group('product_manager')
def create_update_widget_due_date(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    response_data = {'status': 'Failed', 'msg': ''}
    widgetduedate_id = data.get('widgetduedate_id')
    template_code = data.get('template_code', '')
    product = data.get('product_type', '')
    widget_type = data.get('type', '5')
    info_text = data.get('info_text', '')
    card_colour = data.get('card_colour', '')
    info_colour = data.get('info_colour', '')
    card_text_colour = data.get('card_text_colour', '')
    info_text_colour = data.get('info_text_colour', '')

    dpd = data.get('dpd')
    ptp = data.get('ptp')
    application_status = data.get('application_status')
    dpd_lower = data.get('dpd_lower')
    dpd_upper = data.get('dpd_upper')
    until_paid = data.get('until_paid')

    if widgetduedate_id:
        # update
        streamline = StreamlinedCommunication.objects.get_or_none(id=widgetduedate_id)
        if not streamline:
            response_data['msg'] = 'Template not exists'
            response_data['status'] = 'Failure'
            return JsonResponse({'data': response_data})
        StreamlinedMessage.objects.filter(id=streamline.message.id).update(
            message_content=info_text
        )

        data_to_update = dict(
            template_code=template_code,
            product=product,
        )

        payment_widget_properties = streamline.payment_widget_properties
        payment_widget_properties['type'] = widget_type
        payment_widget_properties['info_text'] = info_text
        payment_widget_properties['card_colour'] = card_colour
        payment_widget_properties['info_colour'] = info_colour
        payment_widget_properties['card_text_colour'] = card_text_colour
        payment_widget_properties['info_text_colour'] = info_text_colour

        if 'widgetduedate_image' in request.FILES:
            create_and_upload_image_assets_for_streamlined(
                image_source_id=streamline.id,
                image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_CONTENT,
                image_file=request.FILES['widgetduedate_image'],
                is_update=True,
            )

            uploaded_image = Image.objects.filter(
                image_source=streamline.id, image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_CONTENT
            ).last()
            payment_widget_properties['info_imcard_image'] = uploaded_image.public_image_url
        if 'widgetduedate_image_desc' in request.FILES:
            create_and_upload_image_assets_for_streamlined(
                image_source_id=streamline.id,
                image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_DESC,
                image_file=request.FILES['widgetduedate_image_desc'],
                is_update=True,
            )

            uploaded_image = Image.objects.filter(
                image_source=streamline.id, image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_DESC
            ).last()
            payment_widget_properties['info_image'] = uploaded_image.public_image_url
        data_to_update['payment_widget_properties'] = payment_widget_properties

        streamline.update_safely(**data_to_update)
        response_data['msg'] = 'Widget due date updated successfully'
    else:
        # create
        streamline_message = StreamlinedMessage.objects.create(message_content=info_text)
        payment_widget_properties = {
            "type": widget_type,
            "info_text": info_text,
            "info_image": "",
            "card_colour": card_colour,
            "info_colour": info_colour,
            "card_text_colour": card_text_colour,
            "info_text_colour": info_text_colour,
            "info_imcard_image": "",
        }
        data_for_create = dict(
            communication_platform=CommunicationPlatform.PAYMENT_WIDGET,
            message=streamline_message,
            template_code=template_code,
            product=product,
            type="Information",
            show_in_android=True,
            show_in_web=True,
            payment_widget_properties=payment_widget_properties,
            is_active=True,
        )
        if dpd_lower:
            data_for_create['dpd_lower'] = int(dpd_lower)
        if dpd_upper:
            data_for_create['dpd_upper'] = int(dpd_upper)
        if dpd:
            data_for_create['dpd'] = int(dpd)
            data_for_create['dpd_lower'] = int(dpd)
            data_for_create['dpd_upper'] = int(dpd)
        if until_paid:
            data_for_create['until_paid'] = True if until_paid == 'until_paid' else False
        if ptp:
            data_for_create['ptp'] = ptp


        streamline = StreamlinedCommunication.objects.create(**data_for_create)

        if 'widgetduedate_image' in request.FILES:
            create_and_upload_image_assets_for_streamlined(
                image_source_id=streamline.id,
                image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_CONTENT,
                image_file=request.FILES['widgetduedate_image'],
            )

            uploaded_image_icon = Image.objects.filter(
                image_source=streamline.id, image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_CONTENT
            ).last()
            payment_widget_properties['info_imcard_image'] = uploaded_image_icon.public_image_url

        if 'widgetduedate_image_desc' in request.FILES:
            create_and_upload_image_assets_for_streamlined(
                image_source_id=streamline.id,
                image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_DESC,
                image_file=request.FILES['widgetduedate_image_desc'],
            )

            uploaded_image_desc = Image.objects.filter(
                image_source=streamline.id, image_type=ImageType.STREAMLINED_PAYMENT_WIDGET_DESC
            ).last()
            payment_widget_properties['info_image'] = uploaded_image_desc.public_image_url

        streamline.update_safely(payment_widget_properties=payment_widget_properties)

        response_data['msg'] = 'Parameter List details added successfully'

    response_data['status'] = 'Success'
    return JsonResponse({'data': response_data})


@julo_login_required
@julo_login_required_group('product_manager')
def create_update_slik_notification(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    response_data = {'status': 'Failed', 'msg': ''}
    sliknotification_id = data.get('sliknotification_id')
    template_code = data.get('template_code', '')
    product = data.get('product_type', '')
    widget_type = data.get('type', '5')
    info_text = data.get('info_text', '')
    card_colour = data.get('card_colour', '')
    info_text_colour = data.get('info_text_colour', '')
    info_imcard_image = data.get('info_imcard_image', IMAGE_FOR_SLIK_NOTIFICATION)
    redirect_url = data.get('redirect_url','')

    dpd = data.get('dpd')
    ptp = data.get('ptp')
    application_status = data.get('application_status')
    dpd_lower = data.get('dpd_lower')
    dpd_upper = data.get('dpd_upper')
    until_paid = data.get('until_paid')

    if sliknotification_id:
        # update
        streamline = StreamlinedCommunication.objects.get_or_none(id=sliknotification_id)
        if not streamline:
            response_data['msg'] = 'Template not exists'
            response_data['status'] = 'Failure'
            return JsonResponse({'data': response_data})
        StreamlinedMessage.objects.filter(id=streamline.message.id).update(
            message_content=info_text
        )

        data_to_update = dict(
            template_code=template_code,
            product=product,
        )

        slik_notification_properties = streamline.slik_notification_properties
        slik_notification_properties['type'] = widget_type
        slik_notification_properties['info_text'] = info_text
        slik_notification_properties['card_colour'] = card_colour
        slik_notification_properties['info_text_colour'] = info_text_colour
        slik_notification_properties['info_imcard_image'] = info_imcard_image
        slik_notification_properties['redirect_url'] = redirect_url if redirect_url and redirect_url.lower() != "none" else ""
        data_to_update['slik_notification_properties'] = slik_notification_properties

        streamline.update_safely(**data_to_update)
        response_data['msg'] = 'Widget due date updated successfully'
    else:
        # create
        streamline_message = StreamlinedMessage.objects.create(message_content=info_text)
        slik_notification_properties = {
            "type": widget_type,
            "info_text": info_text,
            "info_image": "",
            "card_colour": card_colour,
            "info_text_colour": info_text_colour,
            "info_imcard_image": info_imcard_image,
            "redirect_url": redirect_url if redirect_url and redirect_url.lower() != "none" else "",
        }
        data_for_create = dict(
            communication_platform=CommunicationPlatform.SLIK_NOTIFICATION,
            message=streamline_message,
            template_code=template_code,
            product=product,
            type="Information",
            show_in_android=True,
            show_in_web=True,
            slik_notification_properties=slik_notification_properties,
            is_active=True,
        )
        if dpd_lower:
            data_for_create['dpd_lower'] = int(dpd_lower)
        if dpd_upper:
            data_for_create['dpd_upper'] = int(dpd_upper)
        if dpd:
            data_for_create['dpd'] = int(dpd)
            data_for_create['dpd_lower'] = int(dpd)
            data_for_create['dpd_upper'] = int(dpd)
        if until_paid:
            data_for_create['until_paid'] = True if until_paid == 'until_paid' else False
        if ptp:
            data_for_create['ptp'] = ptp

        streamline = StreamlinedCommunication.objects.create(**data_for_create)

        streamline.update_safely(slik_notification_properties=slik_notification_properties)

        response_data['msg'] = 'Parameter List details added successfully'

    response_data['status'] = 'Success'
    return JsonResponse({'data': response_data})


@julo_login_required
@julo_login_required_group('product_manager')
def nexmo_robocall_test(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed("POST")

    data = request.POST.dict()
    payment_id = data['payment']
    phone = data['phone']
    test_content = data['test_content']
    is_account_payment = True if data['is_account_payment'] == 'true' else False
    if is_account_payment:
        payment = AccountPayment.objects.get_or_none(id=payment_id)
    else:
        payment = Payment.objects.get_or_none(id=payment_id)

    response_data = {}
    if not payment:
        response_data['status'] = 'Failure'
        response_data['msg'] = 'Invalid payment id {}'.format(payment_id)
        return JsonResponse({
            'data': response_data
        })

    voice_client = get_voice_client_v2()
    try:
        reminder = Reminder()
        template_code = 'nexmo_robocall_test'
        if not is_account_payment:
            reminder.create_reminder_history(payment, None, template_code, VendorConst.NEXMO,
                                             ReminderTypeConst.ROBOCALL_TYPE_REMINDER)
            voice_client.payment_reminder(phone, payment.id,
                                          streamlined_id=None,
                                          template_code=template_code,
                                          test_robocall_content=test_content)
        else:
            reminder.create_j1_reminder_history(payment, None, template_code, VendorConst.NEXMO,
                                                ReminderTypeConst.ROBOCALL_TYPE_REMINDER)
            voice_client.account_payment_reminder(
                phone, payment.id, streamlined_id=None, template_code=template_code,
                test_robocall_content=test_content)
    except VoiceNotSent as e:
        loan_id = payment.loan.id if is_account_payment else None
        logger.warn({
            'action': 'nexmo_robocall_test_failed',
            'payment_id': payment.id,
            'loan_id': loan_id,
            'phone_number': phone,
            'errors': e
        })
        response_data['status'] = 'Failure'
        response_data['msg'] = e
        return JsonResponse({
            'data': response_data
        })

    response_data['status'] = 'Success'
    return JsonResponse({
        'data': response_data
    })


@julo_login_required
@julo_login_required_group('product_manager')
def get_info_card_property(request):
    streamlined_communication_id = request.GET.get('streamlined_communication_id')
    response_data = {}
    if not streamlined_communication_id:
        response_data['status'] = 'Failure'
        return JsonResponse({
            'data': response_data
        })

    streamlined_communication = StreamlinedCommunication.objects.get_or_none(
        pk=streamlined_communication_id)
    if not streamlined_communication:
        response_data['status'] = 'Failure'
        return JsonResponse({
            'data': response_data
        })
    content = streamlined_communication.message
    info_card = content.info_card_property
    expiration_option_data = ""
    if streamlined_communication.expiration_option:
        expiration_option_data = streamlined_communication.expiration_option
        if streamlined_communication.expiry_period:
            expiration_option_data += '\n\nExpiry Period={} {}'.format(streamlined_communication.expiry_period,
                                                                       streamlined_communication.expiry_period_unit)
    info_card_property = {
        'content': content.message_content,
        'card_type': info_card.card_type,
        'product': streamlined_communication.product,
        'title': info_card.title,
        'title_color': info_card.title_color,
        'text_color': info_card.text_color,
        'card_background_image_url': info_card.card_background_image_url,
        'card_optional_image_url': info_card.card_optional_image_url,
        'template_code': streamlined_communication.template_code,
        'card_action': info_card.card_action,
        'card_destination': info_card.card_destination,
        'content_parameter': content.parameter,
        'expiration_option_data': expiration_option_data,
        'is_shown_in_android': streamlined_communication.show_in_android,
        'is_shown_in_web': streamlined_communication.show_in_web,
        'youtube_video_id': info_card.youtube_video_id,
        'bottom_sheet_destination': streamlined_communication.bottom_sheet_destination
    }
    buttons = []
    for button in info_card.button_list:
        buttons.append({
            'button_text': button.text,
            'text_color': button.text_color,
            'button_color': button.button_color,
            'button_name': button.button_name,
            'background_image_url': button.background_image_url,
            'button_action': button.action_type,
            'destination': button.destination,
        })

    info_card_property['buttons'] = buttons
    response_data['status'] = 'Success'
    response_data['info_card_property'] = info_card_property
    return JsonResponse({
        'data': response_data
    })


class CreateNewInfoCard(APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = InfoCardSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = request.POST.dict()
        bottom_sheet_destination = data.get('bottom_sheet_destination')
        template_code = data['info_card_template_code']
        card_type = data['info_card_type']
        info_card_product = data['info_card_product']
        info_card_title = data['info_card_title']
        title_text_color = data['title_text_color']
        info_card_content = data['info_card_content']
        info_card_parameters = data['content_parameters']
        body_text_color = data['body_text_color']
        dpd = data['dpd']
        ptp = data['ptp']
        dpd_lower = data['dpd_lower']
        dpd_upper = data['dpd_upper']
        until_paid = data['until_paid']
        status_code = data['status_code']
        extra_condition = data['extra_condition']
        youtube_video_id = data['youtube_video_id']

        streamlined_parameters = dict(
            template_code=template_code,
            communication_platform=CommunicationPlatform.INFO_CARD)
        until_paid = True if until_paid == 'until_paid' else False
        if 'expiration_option' in data:
            expiration_option = data['expiration_option']
            streamlined_parameters['expiration_option'] = expiration_option
            if expiration_option and expiration_option != "No Expiration Time":
                if 'expiry_period_unit' in data:
                    streamlined_parameters['expiry_period_unit'] = data['expiry_period_unit']
                    streamlined_parameters['expiry_period'] = data['expiry_period']
        if dpd:
            streamlined_parameters['dpd'] = dpd
        if ptp:
            streamlined_parameters['ptp'] = ptp
        if status_code:
            streamlined_parameters['status_code_id'] = status_code
        if extra_condition:
            streamlined_parameters['extra_conditions'] = extra_condition
        if info_card_product != 'J1':
            streamlined_parameters['product'] = info_card_product
        if (dpd_lower and dpd_upper and (int(dpd_lower) < int(dpd_upper))) \
                or (dpd_lower and until_paid):
            streamlined_parameters['dpd_lower'] = dpd_lower
            streamlined_parameters['dpd'] = None
            if dpd_upper:
                streamlined_parameters['dpd_upper'] = dpd_upper
            else:
                streamlined_parameters['until_paid'] = until_paid

        # check last order number
        last_order_filter = streamlined_parameters
        del last_order_filter['template_code']
        last_order_info_card = StreamlinedCommunication.objects.filter(
            **last_order_filter).order_by(
            'message__info_card_property__card_order_number'
        ).last()
        # create info card property
        is_have_l_button = True if data['is_have_l_button'] == 'true' else False
        is_have_r_button = True if data['is_have_r_button'] == 'true' else False
        is_have_m_button = True if data['is_have_m_button'] == 'true' else False
        clickable_card = True if data['clickable_card'] == 'true' else False
        is_shown_in_android = True if data['is_shown_in_android'] == 'true' else False
        is_shown_in_webview = True if data['is_shown_in_webview'] == 'true' else False

        with transaction.atomic():
            info_card_parameter = dict(
                title=info_card_title,
                title_color=title_text_color,
                text_color=body_text_color,
            )
            if card_type == '3':
                if is_have_l_button and is_have_r_button:
                    info_card_parameter['card_type'] = '3A'
                else:
                    info_card_parameter['card_type'] = '3B'
            else:
                info_card_parameter['card_type'] = card_type

            if clickable_card:
                info_card_parameter['card_action'] = data['card_action']
                if data['card_action'] == 'webpage':
                    info_card_parameter['card_destination'] = data['info_card_destination_webpage']
                elif data['card_action'] == 'app_deeplink':
                    info_card_parameter['card_destination'] = \
                        data['info_card_destination_app_deeplink']
                else:
                    info_card_parameter['card_destination'] = \
                        data['info_card_destination_redirect']

            info_card_order = 1
            if last_order_info_card:
                last_number = last_order_info_card.message.info_card_property.card_order_number
                info_card_order = last_number + 1
            if youtube_video_id:
                info_card_parameter['youtube_video_id'] = youtube_video_id

            info_card_parameter['card_order_number'] = info_card_order
            info_card_property = InfoCardProperty.objects.create(**info_card_parameter)
            if 'background_card_image' in request.FILES:
                create_and_upload_image_assets_for_streamlined(
                    image_source_id=info_card_property.id,
                    image_type=CardProperty.IMAGE_TYPE.card_background_image,
                    image_file=request.FILES['background_card_image']
                )
            if 'optional_image' in request.FILES:
                create_and_upload_image_assets_for_streamlined(
                    image_source_id=info_card_property.id,
                    image_type=CardProperty.IMAGE_TYPE.card_optional_image,
                    image_file=request.FILES['optional_image']
                )
            if is_have_l_button:
                l_button_parameter = dict(
                    info_card_property=info_card_property,
                    button_name='L.BUTTON',
                    text=data['l_button_text'],
                    text_color=data['l_button_text_color'],
                    action_type=data['l_button_action'],
                    button_color=data.get('l_button_color'),
                )
                if data['l_button_action'] == 'webpage':
                    l_button_parameter['destination'] = data['l_button_destination_webpage']
                elif data['l_button_action'] == 'app_deeplink':
                    l_button_parameter['destination'] = data['l_button_destination_app_deeplink']
                else:
                    l_button_parameter['destination'] = data['l_button_destination_redirect']

                button_l = InfoCardButtonProperty.objects.create(**l_button_parameter)
                if 'l_button_image' in request.FILES:
                    create_and_upload_image_assets_for_streamlined(
                        image_source_id=button_l.id,
                        image_type=CardProperty.IMAGE_TYPE.button_background_image,
                        image_prefix=CardProperty.IMAGE_TYPE.l_button_background_image,
                        image_file=request.FILES['l_button_image']
                    )
            if is_have_m_button:
                m_button_parameter = dict(
                    info_card_property=info_card_property,
                    button_name='M.BUTTON',
                    text=data['m_button_text'],
                    text_color=data['m_button_text_color'],
                    action_type=data['m_button_action'],
                    button_color=data.get('m_button_color'),
                )
                if data['m_button_action'] == 'webpage':
                    m_button_parameter['destination'] = data['m_button_destination_webpage']
                elif data['m_button_action'] == 'app_deeplink':
                    m_button_parameter['destination'] = data['m_button_destination_app_deeplink']
                elif data['m_button_action'] == 'reload':
                    m_button_parameter['destination'] = data['m_button_destination_reload']
                else:
                    m_button_parameter['destination'] = data['m_button_destination_redirect']

                button_m = InfoCardButtonProperty.objects.create(**m_button_parameter)
                if 'm_button_image' in request.FILES:
                    create_and_upload_image_assets_for_streamlined(
                        image_source_id=button_m.id,
                        image_type=CardProperty.IMAGE_TYPE.button_background_image,
                        image_prefix=CardProperty.IMAGE_TYPE.m_button_background_image,
                        image_file=request.FILES['m_button_image']
                    )
            if is_have_r_button:
                r_button_parameter = dict(
                    info_card_property=info_card_property,
                    button_name='R.BUTTON',
                    text=data['r_button_text'],
                    text_color=data['r_button_text_color'],
                    button_color=data.get('r_button_color'),
                    action_type=data['r_button_action'],
                )
                if data['r_button_action'] == 'webpage':
                    r_button_parameter['destination'] = data['r_button_destination_webpage']
                elif data['r_button_action'] == 'app_deeplink':
                    r_button_parameter['destination'] = data['r_button_destination_app_deeplink']
                else:
                    r_button_parameter['destination'] = data['r_button_destination_redirect']

                r_button = InfoCardButtonProperty.objects.create(**r_button_parameter)
                if 'r_button_image' in request.FILES:
                    create_and_upload_image_assets_for_streamlined(
                        image_source_id=r_button.id,
                        image_type=CardProperty.IMAGE_TYPE.button_background_image,
                        image_prefix=CardProperty.IMAGE_TYPE.r_button_background_image,
                        image_file=request.FILES['r_button_image']
                    )

            streamlined_content = StreamlinedMessage.objects.create(
                message_content=info_card_content,
                parameter='{' + info_card_parameters + '}',
                info_card_property=info_card_property
            )
            streamlined_parameters['message'] = streamlined_content
            streamlined_parameters['is_active'] = True
            streamlined_parameters['template_code'] = template_code
            streamlined_parameters['show_in_android'] = is_shown_in_android
            streamlined_parameters['show_in_web'] = is_shown_in_webview
            streamlined_parameters['bottom_sheet_destination'] = bottom_sheet_destination
            StreamlinedCommunication.objects.create(**streamlined_parameters)

            return success_response()


class UpdateInfoCard(APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = InfoCardSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = request.POST.dict()
        streamlined_communication_id = data['info_card_id']
        streamlined_communication = StreamlinedCommunication.objects.get_or_none(
            pk=streamlined_communication_id
        )
        streamlined_communication_content = streamlined_communication.message
        info_card_property = streamlined_communication_content.info_card_property
        template_code = data['info_card_template_code']
        card_type = data['info_card_type']
        info_card_title = data['info_card_title']
        title_text_color = data['title_text_color']
        info_card_content = data['info_card_content']
        info_card_parameters = data['content_parameters']
        body_text_color = data['body_text_color']
        info_card_product = data['info_card_product']
        youtube_video_id = data['youtube_video_id']
        bottom_sheet_destination = data.get('bottom_sheet_destination')

        # create info card property
        is_have_l_button = True if data['is_have_l_button'] == 'true' else False
        is_have_r_button = True if data['is_have_r_button'] == 'true' else False
        is_have_m_button = True if data['is_have_m_button'] == 'true' else False
        clickable_card = True if data['clickable_card'] == 'true' else False
        is_background_changes = True if data['is_background_changes'] == 'true' else False
        is_optional_image_changes = True if data['is_optional_image_changes'] == 'true' else False
        is_shown_in_android = True if data['is_shown_in_android'] == 'true' else False
        is_shown_in_webview = True if data['is_shown_in_webview'] == 'true' else False

        with transaction.atomic():
            info_card_parameter = dict(
                title=info_card_title,
                title_color=title_text_color,
                text_color=body_text_color,
            )
            if card_type == '3':
                if is_have_l_button and is_have_r_button:
                    info_card_parameter['card_type'] = '3A'
                else:
                    info_card_parameter['card_type'] = '3B'
            else:
                info_card_parameter['card_type'] = card_type

            if clickable_card:
                info_card_parameter['card_action'] = data['card_action']
                if data['card_action'] == 'app_deeplink':
                    info_card_parameter['card_destination'] = data['info_card_destination_app_deeplink']
                elif data['card_action'] == 'webpage':
                    info_card_parameter['card_destination'] = data['info_card_destination_webpage']
                elif data['card_action'] == 'redirect':
                    info_card_parameter['card_destination'] = data['info_card_destination_redirect']
            else:
                info_card_parameter['card_action'] = None
                info_card_parameter['card_destination'] = None

            if youtube_video_id:
                info_card_parameter['youtube_video_id'] = youtube_video_id

            info_card_property.update_safely(**info_card_parameter)

            if 'background_card_image' in request.FILES and is_background_changes:
                recent_image = Image.objects.filter(
                    image_source=info_card_property.id,
                    image_type=CardProperty.IMAGE_TYPE.card_background_image,
                ).last()
                create_and_upload_image_assets_for_streamlined(
                    image_source_id=info_card_property.id,
                    image_type=CardProperty.IMAGE_TYPE.card_background_image,
                    image_file=request.FILES['background_card_image'],
                    is_update=True if recent_image else False
                )
            if 'optional_image' in request.FILES and is_optional_image_changes:
                recent_image = Image.objects.filter(
                    image_source=info_card_property.id,
                    image_type=CardProperty.IMAGE_TYPE.card_optional_image,
                ).last()
                create_and_upload_image_assets_for_streamlined(
                    image_source_id=info_card_property.id,
                    image_type=CardProperty.IMAGE_TYPE.card_optional_image,
                    image_file=request.FILES['optional_image'],
                    is_update=True if recent_image else False
                )
            # delete unchecked button when already checked
            button_l = InfoCardButtonProperty.objects.filter(
                info_card_property=info_card_property,
                button_name='L.BUTTON'
            ).last()
            button_m = InfoCardButtonProperty.objects.filter(
                info_card_property=info_card_property,
                button_name='M.BUTTON',
            ).last()
            button_r = InfoCardButtonProperty.objects.filter(
                info_card_property=info_card_property,
                button_name='R.BUTTON'
            ).last()
            if button_l and not is_have_l_button:
                image = Image.objects.filter(
                    image_source=button_l.id,
                    image_type=CardProperty.IMAGE_TYPE.button_background_image).last()
                if image:
                    image.delete()

                button_l.delete()
            if button_m and not is_have_m_button:
                image = Image.objects.filter(
                    image_source=button_m.id,
                    image_type=CardProperty.IMAGE_TYPE.button_background_image).last()
                if image:
                    image.delete()

                button_m.delete()
            if button_r and not is_have_r_button:
                image = Image.objects.filter(
                    image_source=button_r.id,
                    image_type=CardProperty.IMAGE_TYPE.button_background_image).last()
                if image:
                    image.delete()

                button_r.delete()

            if is_have_l_button:
                is_button_l_background_changes = True \
                    if data['is_button_l_background_changes'] == 'true' else False
                l_button_parameter = dict(
                    info_card_property=info_card_property,
                    text=data['l_button_text'],
                    text_color=data['l_button_text_color'],
                    action_type=data['l_button_action'],
                    button_color=data.get('l_button_color'),
                )
                if data['l_button_action'] == 'webpage':
                    l_button_parameter['destination'] = data['l_button_destination_webpage']
                elif data['l_button_action'] == 'app_deeplink':
                    l_button_parameter['destination'] = data['l_button_destination_app_deeplink']
                else:
                    l_button_parameter['destination'] = data['l_button_destination_redirect']
                is_new = False
                button_l = InfoCardButtonProperty.objects.filter(
                    info_card_property=info_card_property,
                    button_name='L.BUTTON'
                ).last()
                if button_l:
                    button_l.update_safely(**l_button_parameter)
                else:
                    l_button_parameter['button_name'] = 'L.BUTTON'
                    button_l = InfoCardButtonProperty.objects.create(**l_button_parameter)
                    is_new = True

                if ('l_button_image' in request.FILES and is_button_l_background_changes) or \
                        ('l_button_image' in request.FILES and is_new):
                    # not is_update will be True if is new = False
                    create_and_upload_image_assets_for_streamlined(
                        image_source_id=button_l.id,
                        image_type=CardProperty.IMAGE_TYPE.button_background_image,
                        image_prefix=CardProperty.IMAGE_TYPE.l_button_background_image,
                        image_file=request.FILES['l_button_image'],
                        is_update=not is_new
                    )
            if is_have_m_button:
                is_button_m_background_changes = True \
                    if data['is_button_m_background_changes'] == 'true' else False
                m_button_parameter = dict(
                    info_card_property=info_card_property,
                    text=data['m_button_text'],
                    text_color=data['m_button_text_color'],
                    action_type=data['m_button_action'],
                    button_color=data.get('m_button_color'),
                )
                if data['m_button_action'] == 'webpage':
                    m_button_parameter['destination'] = data['m_button_destination_webpage']
                elif data['m_button_action'] == 'app_deeplink':
                    m_button_parameter['destination'] = data['m_button_destination_app_deeplink']
                elif data['m_button_action'] == 'reload':
                    m_button_parameter['destination'] = data['m_button_destination_reload']
                else:
                    m_button_parameter['destination'] = data['m_button_destination_redirect']
                is_new = False
                button_m = InfoCardButtonProperty.objects.filter(
                    info_card_property=info_card_property,
                    button_name='M.BUTTON',
                ).last()
                if button_m:
                    button_m.update_safely(**m_button_parameter)
                else:
                    m_button_parameter['button_name'] = 'M.BUTTON'
                    button_m = InfoCardButtonProperty.objects.create(**m_button_parameter)
                    is_new = True

                if ('m_button_image' in request.FILES and is_button_m_background_changes) or \
                        ('m_button_image' in request.FILES and is_new):
                    create_and_upload_image_assets_for_streamlined(
                        image_source_id=button_m.id,
                        image_type=CardProperty.IMAGE_TYPE.button_background_image,
                        image_prefix=CardProperty.IMAGE_TYPE.m_button_background_image,
                        image_file=request.FILES['m_button_image'],
                        is_update=not is_new
                    )
            if is_have_r_button:
                is_button_r_background_changes = True \
                    if data['is_button_r_background_changes'] == 'true' else False
                r_button_parameter = dict(
                    info_card_property=info_card_property,
                    text=data['r_button_text'],
                    text_color=data['r_button_text_color'],
                    button_color=data.get('r_button_color'),
                    action_type=data['r_button_action'],
                )
                if data['r_button_action'] == 'webpage':
                    r_button_parameter['destination'] = data['r_button_destination_webpage']
                elif data['r_button_action'] == 'app_deeplink':
                    r_button_parameter['destination'] = data['r_button_destination_app_deeplink']
                else:
                    r_button_parameter['destination'] = data['r_button_destination_redirect']

                is_new = False
                button_r = InfoCardButtonProperty.objects.filter(
                    info_card_property=info_card_property,
                    button_name='R.BUTTON'
                ).last()
                if button_r:
                    button_r.update_safely(**r_button_parameter)
                else:
                    r_button_parameter['button_name'] = 'R.BUTTON'
                    button_r = InfoCardButtonProperty.objects.create(**r_button_parameter)
                    is_new = True

                if ('r_button_image' in request.FILES and is_button_r_background_changes) or \
                        ('r_button_image' in request.FILES and is_new):
                    create_and_upload_image_assets_for_streamlined(
                        image_source_id=button_r.id,
                        image_type=CardProperty.IMAGE_TYPE.button_background_image,
                        image_prefix=CardProperty.IMAGE_TYPE.r_button_background_image,
                        image_file=request.FILES['r_button_image'],
                        is_update=not is_new
                    )

            streamlined_parameters = dict(template_code=template_code)
            streamlined_communication_content.update_safely(
                message_content=info_card_content,
                parameter='{' + info_card_parameters + '}',
            )
            streamlined_parameters['template_code'] = template_code
            streamlined_parameters['show_in_android'] = is_shown_in_android
            streamlined_parameters['show_in_web'] = is_shown_in_webview
            streamlined_parameters['bottom_sheet_destination'] = bottom_sheet_destination
            if info_card_product != 'J1':
                streamlined_parameters['product'] = info_card_product
            else:
                streamlined_parameters['product'] = None
            streamlined_communication.update_safely(**streamlined_parameters)

            return success_response()


@julo_login_required
@julo_login_required_group('product_manager')
def info_card_update_ordering_and_activate(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]
    updated_info_cards = request.POST.get('updated_info_card_ids')
    if updated_info_cards:
        for streamlined_comm_id in updated_info_cards.split(','):
            if streamlined_comm_id:
                is_active_form = request.POST.get('is_active-{}'.format(streamlined_comm_id))
                is_active = True if is_active_form else False
                order_form = request.POST.get('infoCardOrder-{}'.format(streamlined_comm_id))
                streamlined = StreamlinedCommunication.objects.filter(id=streamlined_comm_id).last()
                message = streamlined.message
                info_card_property = message.info_card_property
                info_card_property.update_safely(card_order_number=order_form)
                streamlined.update_safely(
                    is_active=is_active,
                )

    response_data = {}
    response_data['status'] = 'Success'
    response_data['message'] = 'Success Update Info card'
    return JsonResponse({
        'data': response_data
    })


@julo_login_required
@julo_login_required_group('product_manager')
def delete_info_card(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    streamlined_communication_id = data['streamlined_communication_id']
    streamlined_communication = StreamlinedCommunication.objects.get_or_none(
        pk=streamlined_communication_id)
    streamlined_message = streamlined_communication.message
    info_card_property = streamlined_message.info_card_property
    buttons = info_card_property.button_list
    streamlined_parameters = dict(
        communication_platform=CommunicationPlatform.INFO_CARD,
        message__info_card_property__card_order_number__gt=info_card_property.card_order_number
    )
    if streamlined_communication.dpd:
        streamlined_parameters['dpd'] = streamlined_communication.dpd
    if streamlined_communication.ptp:
        streamlined_parameters['ptp'] = streamlined_communication.ptp
    if streamlined_communication.status_code:
        streamlined_parameters['status_code_id'] = streamlined_communication.status_code_id
    if streamlined_communication.extra_conditions:
        streamlined_parameters['extra_conditions'] = streamlined_communication.extra_conditions

    response_data = {}
    if streamlined_communication.delete() and streamlined_message.delete():
        if buttons:
            buttons.delete()
        info_card_property.delete()
        fixing_ordered = StreamlinedCommunication.objects.filter(**streamlined_parameters)
        if fixing_ordered:
            for streamlined_comm_order in fixing_ordered:
                message = streamlined_comm_order.message
                info_card_order = message.info_card_property
                info_card_order.update_safely(
                    card_order_number=info_card_order.card_order_number - 1)

        response_data['status'] = 'Success'
        response_data['message'] = 'Success Delete Info Card'
        return JsonResponse({
            'data': response_data
        })
    else:
        response_data['status'] = 'Failed'
        response_data['message'] = 'Failed Delete Info Card'
        return JsonResponse({
            'data': response_data
        })


class InfoCardAndroidAPI(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request):
        empty_data = {'cards': []}
        customer = request.user.customer
        if customer and get_ongoing_account_deletion_request(customer):
            return success_response(empty_data)

        application = determine_main_application_infocard(customer)
        app_version = None
        promotion_card = None
        is_locked_product = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        from juloserver.julo_starter.services.onboarding_check import check_process_eligible
        eligibile_reapply = check_process_eligible(customer)
        # for jstarter reject fdc and bpjs check on x0
        if eligibile_reapply and not application:
            info_cards = []
            android_infocards_queryset = StreamlinedCommunication.objects.filter(
                show_in_android=True
            )
            if (
                eligibile_reapply['is_eligible'] == 'passed'
                and customer.can_reapply
            ):
                info_cards = list(android_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
                    status_code_id=None,
                    product="jstarter",
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
            elif eligibile_reapply['is_eligible'] == 'not_passed':
                if customer.can_reapply:
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
                        status_code_id=None,
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                else:
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=None,
                        status_code_id=ApplicationStatusCodes.APPLICATION_DENIED,
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
            elif eligibile_reapply['is_eligible'] == 'offer_regular':
                info_cards = list(android_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
                    status_code_id=ApplicationStatusCodes.APPLICATION_DENIED,
                    product="jstarter",
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))

            highest_info_card = None
            available_context = {
                'card_title': '',
                'card_full_name': customer.fullname,
                'card_first_name': customer.fullname,
                'card_due_date': '-',
                'card_due_amount': '-',
                'card_cashback_amount': '-',
                'card_cashback_multiplier': '-',
                'card_dpd': '-'
            }
            if info_cards:
                available_context['reapply_date'] = customer.reapply_msg

            data = {
                'shouldRatingShown': False,
                'is_document_submission': False,
            }

        if not application and not eligibile_reapply:
            return general_error_response("Aplikasi tidak ditemukan")

        if application:
            application_status_no_need_credit_score = [
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.APPLICATION_DENIED,
                ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED
            ]
            if (
                not hasattr(application, 'creditscore')
                and application.application_status_id not in application_status_no_need_credit_score
                and not application.is_julo_starter()
                and (
                    not application.is_julo_one()
                    and (
                        application.application_status_id ==
                        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER
                    )
                )
            ):
                return success_response(empty_data)
            should_rating_shown = checking_rating_shown(application)
            data = {
                'shouldRatingShown': should_rating_shown,
            }
            is_document_submission = False
            card_due_date = '-'
            card_due_amount = '-'
            card_cashback_amount = '-'
            card_cashback_multiplier = '-'
            card_dpd = '-'
            card_cashback_counter = '-'
            loan = None if not hasattr(application, 'loan') else application.loan
            if application.is_julo_one() or application.is_julo_starter():
                if application.account:
                    loan = application.account.loan_set.last()
                    if loan and loan.account:
                        card_cashback_counter = loan.account.cashback_counter_for_customer
                        oldest_account_payment = loan.account.accountpayment_set.not_paid_active() \
                            .order_by('due_date') \
                            .first()
                        if oldest_account_payment:
                            card_due_date = format_date_indo(oldest_account_payment.due_date)
                            card_due_amount = add_thousand_separator(
                                str(oldest_account_payment.due_amount))
                            card_cashback_amount = oldest_account_payment.payment_set.last().cashback_earned
                            card_cashback_multiplier = oldest_account_payment.cashback_multiplier
                            card_dpd = oldest_account_payment.dpd

            available_context = {
                'card_title': application.bpk_ibu,
                'card_full_name': application.full_name_only,
                'card_first_name': application.first_name_only,
                'card_due_date': card_due_date,
                'card_due_amount': card_due_amount,
                'card_cashback_amount': card_cashback_amount,
                'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
                'card_dpd': card_dpd,
                'card_cashback_counter': card_cashback_counter,
            }
            info_cards = []
            android_infocards_queryset = StreamlinedCommunication.objects.filter(
                show_in_android=True
            )
            now = timezone.localtime(timezone.now())

            mandocs_overhaul_105 = False
            mandocs_overhaul_status_code = ApplicationStatusCodes.FORM_PARTIAL
            sonic_pass = False
            salary_izi_data = False
            is_data_check_passed = False
            etl_job = None
            highest_info_card = None

            _, is_upgrade_application = user_have_upgrade_application(customer)
            if application.is_julo_one() and \
                    is_experiment_application(application.id, 'ExperimentUwOverhaul'):
                if application.application_status_id == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
                    mandocs_overhaul_status_code = ApplicationStatusCodes.DOCUMENTS_SUBMITTED
                    sonic_pass = check_iti_repeat(application.id)
                    customer_high_score = feature_high_score_full_bypass(application)

                    is_submitted_bpjs = check_submitted_bpjs(application)
                    is_scrapped_bank = check_scrapped_bank(application)

                    success_status = ['auth_success', 'done',
                                      'initiated', 'load_success', 'scrape_success']

                    etl_job = EtlJob.objects.filter(application_id=application.id).last()

                    if etl_job:
                        if etl_job.status in success_status:
                            is_data_check_passed = True

                    if is_scrapped_bank:
                        sd_bank_account = SdBankAccount.objects.filter(
                            application_id=application.id).last()
                        if sd_bank_account:
                            sd_bank_statement_detail = SdBankStatementDetail.objects.filter(
                                sd_bank_account=sd_bank_account).last()
                            if sd_bank_statement_detail:
                                is_data_check_passed = True

                    if is_submitted_bpjs and not is_data_check_passed:
                        from juloserver.bpjs.services import Bpjs
                        is_data_check_passed = Bpjs(application).is_scraped

                    if not customer_high_score:
                        if not sonic_pass:
                            if not is_data_check_passed:
                                salary_izi_data = check_salary_izi_data(application)
                elif application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
                    mandocs_overhaul_105 = True

            # Julo Starter section
            if application.is_julo_starter():
                has_submit_extra_form = application.has_submit_extra_form()
                show_master_agreement = FeatureSetting.objects.get_or_none(
                    is_active=True,
                    feature_name="master_agreement_setting",
                )
                account = application.account
                deactivate_account = False
                fraud_account = False
                if account:
                    if account.status_id == AccountConstant.STATUS_CODE.deactivated:
                        deactivate_account = True
                    if account.status_id == AccountConstant.STATUS_CODE.fraud_reported:
                        fraud_account = True

                fraud_history = application.applicationhistory_set.filter(
                    status_new=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
                ).exists()
                if fraud_history and not fraud_account:
                    fraud_account = True

                if deactivate_account and fraud_history:
                    info_cards = list(
                        android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            extra_conditions=None,
                            status_code_id=ApplicationStatusCodes.APPLICATION_DENIED,
                            product="jstarter",
                            is_active=True,
                        ).order_by('message__info_card_property__card_order_number')
                    )
                elif (
                    application.application_status_id == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
                    and has_submit_extra_form
                ):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.JULO_STARTER_WAIT_VERIFICATION,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                elif (
                    application.application_status_id == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
                    or (
                    application.application_status_id == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                    and application.account
                    and application.account.status.status_code == AccountConstant.STATUS_CODE.inactive
                    )
                ):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.JULO_STARTER_WAIT_VERIFICATION,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))

                    autodebet_account = get_existing_autodebet_account(application.account)
                    _filters = {
                        'communication_platform': CommunicationPlatform.INFO_CARD,
                        'extra_conditions': CardProperty.AUTODEBET_NOT_ACTIVE_JTURBO,
                        'is_active': True,
                    }
                    if (
                        not autodebet_account or not autodebet_account.is_use_autodebet
                    ) and not is_disabled_autodebet_activation(account):
                        info_cards += list(
                            StreamlinedCommunication.objects.filter(
                                **_filters,
                                status_code_id=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                            ).order_by('message__info_card_property__card_order_number')
                        )

                    if is_idfy_autodebet_valid(application.account) and is_idfy_profile_exists(
                        application.account
                    ):
                        info_cards += list(
                            StreamlinedCommunication.objects.filter(
                                **_filters,
                                template_code=TemplateCode.IDFY_AUTODEBET_NOT_ACTIVE,
                            ).order_by('message__info_card_property__card_order_number')
                        )

                elif (
                    application.application_status_id == ApplicationStatusCodes.DOCUMENTS_SUBMITTED
                    or application.application_status_id == ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK  # noqa
                ):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.JULO_STARTER_WAIT_VERIFICATION,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                elif (
                    not application.has_master_agreement()
                    and show_master_agreement
                    and (
                        application.application_status_id == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
                        or application.application_status_id == ApplicationStatusCodes.LOC_APPROVED
                    )
                ):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.HAS_NOT_SIGN_MASTER_AGREEMENT,
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                elif (
                    not has_submit_extra_form
                    and not show_master_agreement
                    and (
                        application.application_status_id == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
                        or application.application_status_id == ApplicationStatusCodes.LOC_APPROVED
                    )
                ):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.HAS_NOT_SUBMIT_EXTRA_FORM,
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                elif (
                    customer.can_reapply
                    and application.application_status_id != ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
                    and application.application_status_id != ApplicationStatusCodes.LOC_APPROVED
                ):
                    prev_status = application.applicationhistory_set.last().status_old
                    if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=application.application_status_id,
                            extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
                            product="jstarter",
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                    elif (
                        application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED
                        and prev_status == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                    ):
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
                            status_code_id=application.application_status_id,
                            product="jstarter",
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                    else:
                        if (
                            application.application_status_id
                            == ApplicationStatusCodes.OFFER_REGULAR
                        ):
                            # for infocard if user got x107 JTurbo should be hit endpoint Product picker J1
                            info_cards = list(
                                android_infocards_queryset.filter(
                                    communication_platform=CommunicationPlatform.INFO_CARD,
                                    extra_conditions=CardProperty.JULO_TURBO_OFFER_TO_REGULAR,
                                    status_code_id=ApplicationStatusCodes.OFFER_REGULAR,
                                    product="jstarter",
                                    is_active=True,
                                ).order_by('message__info_card_property__card_order_number')
                            )
                        else:
                            info_cards = list(
                                android_infocards_queryset.filter(
                                    communication_platform=CommunicationPlatform.INFO_CARD,
                                    status_code_id=None,
                                    extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
                                    product="jstarter",
                                    is_active=True,
                                ).order_by('message__info_card_property__card_order_number')
                            )
                elif (
                    application.application_status_id == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
                    or application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
                    or application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED
                    and not customer.can_reapply
                ):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=None,
                        status_code_id=ApplicationStatusCodes.APPLICATION_DENIED,
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                elif (
                    application.application_status_id == ApplicationStatusCodes.LOC_APPROVED
                    and not fraud_account
                ):
                    change_reason = application.applicationhistory_set.last().change_reason
                    app_history = application.applicationhistory_set.filter(
                        status_new=ApplicationStatusCodes.APPLICATION_DENIED
                    ).exists()
                    if app_history:
                        if change_reason == JuloStarter190RejectReason.REJECT_FRAUD:
                            info_cards = list(
                                android_infocards_queryset.filter(
                                    communication_platform=CommunicationPlatform.INFO_CARD,
                                    extra_conditions=CardProperty.JULO_STARTER_135_190,
                                    status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                                    product="jstarter",
                                    is_active=True,
                                ).order_by('message__info_card_property__card_order_number')
                            )
                        else:
                            info_cards = list(android_infocards_queryset.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CAN_REAPPLY,
                                product=Product.STREAMLINED_PRODUCT.jstarter,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                    else:
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            extra_conditions=None,
                            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                            product="jstarter",
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))

                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CAN_REAPPLY,
                            product=Product.STREAMLINED_PRODUCT.jstarter,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))

                        logger.info({
                            'message': 'Show infocard for upgrade to J1 to reapply',
                            'extra_conditions': CardProperty.JULO_TURBO_OFFER_J1_CAN_REAPPLY,
                            'application': application.id if application else None,
                        })

                    # Marketing Prize Chance Info Card. See `loan.services.loan_prize_chance`
                    try:
                        is_eligible_prize_chance, prize_chances = get_prize_chances_by_application(
                            application
                        )
                        if is_eligible_prize_chance:
                            prize_chance_info_cards = list(StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=FeatureNameConst.MARKETING_LOAN_PRIZE_CHANCE,
                                is_active=True,
                            ).order_by('message__info_card_property__card_order_number'))
                            available_context['prize_chances'] = prize_chances
                            info_cards = info_cards + prize_chance_info_cards
                    except Exception:
                        logger.exception('Error getting prize chance info card')
                        get_julo_sentry_client().captureException()

                    # JTurbo Collection Info Card.
                    loan = application.account.loan_set.last()
                    if loan:
                        oldest_account_payment = loan.account.accountpayment_set.not_paid_active() \
                            .order_by('due_date') \
                            .first()
                        if oldest_account_payment:
                            dpd = oldest_account_payment.dpd
                            account_payment_cards = get_reminder_streamlined_comms_by_dpd(
                                android_infocards_queryset, dpd, account,
                                product_line=Product.STREAMLINED_PRODUCT.jstarter)
                            info_cards = account_payment_cards + info_cards

                    # JTurbo Autodebet Info Card.
                    autodebet_account = get_existing_autodebet_account(application.account)
                    _filters = {
                        'communication_platform': CommunicationPlatform.INFO_CARD,
                        'extra_conditions': CardProperty.AUTODEBET_NOT_ACTIVE_JTURBO,
                        'is_active': True,
                    }
                    if (
                        not autodebet_account or not autodebet_account.is_use_autodebet
                    ) and not is_disabled_autodebet_activation(account):
                        info_cards += list(
                            StreamlinedCommunication.objects.filter(
                                **_filters,
                                status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                            )
                            .exclude(template_code=TemplateCode.IDFY_AUTODEBET_NOT_ACTIVE)
                            .order_by('message__info_card_property__card_order_number')
                        )

                    if is_idfy_autodebet_valid(application.account) and is_idfy_profile_exists(
                        application.account
                    ):
                        info_cards += list(
                            StreamlinedCommunication.objects.filter(
                                **_filters,
                                template_code=TemplateCode.IDFY_AUTODEBET_NOT_ACTIVE,
                            ).order_by('message__info_card_property__card_order_number')
                        )

                elif application.application_status_id == ApplicationStatusCodes.OFFER_REGULAR:
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.JULO_TURBO_OFFER_TO_REGULAR,
                        status_code_id=ApplicationStatusCodes.OFFER_REGULAR,
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))

                elif application.application_status_id == ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE:
                    # Default infocard for J1 in progress
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CANNOT_REAPPLY,
                        product=Product.STREAMLINED_PRODUCT.jstarter,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                    application_j1_have_rejected = check_application_are_rejected_status(customer)
                    if application_j1_have_rejected:

                        # show infocard rejected and setup manage session for infocard
                        temp_info_cards = list(StreamlinedCommunication.objects.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            extra_conditions=CardProperty.REJECTION_JTURBO_UPGRADE,
                            product="jstarter",
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                        stream_lined_id = temp_info_cards[0].id if temp_info_cards else None
                        available_context['duration_message'] = ''

                        if is_active_session_limit_infocard(application, stream_lined_id):
                            info_cards = temp_info_cards
                            message_reapply = message_info_card_for_reapply_duration(customer)
                            if message_reapply:
                                available_context['duration_message'] = message_reapply

                    loan = application.account.loan_set.last()
                    if loan:
                        oldest_account_payment = loan.account.accountpayment_set.not_paid_active() \
                            .order_by('due_date') \
                            .first()
                        if oldest_account_payment:
                            dpd = oldest_account_payment.dpd
                            account_payment_cards = get_reminder_streamlined_comms_by_dpd(
                                android_infocards_queryset, dpd, account,
                                product_line=Product.STREAMLINED_PRODUCT.jstarter)
                            info_cards = account_payment_cards + info_cards

                latest_app_history = application.applicationhistory_set.last()
                if latest_app_history and \
                        latest_app_history.status_old == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD and \
                        latest_app_history.status_new == ApplicationStatusCodes.LOC_APPROVED:
                    reject_jturbo_x190_info_cards = list(android_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    extra_conditions=CardProperty.JULO_STARTER_133_TO_190,
                    status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                    product="jstarter",
                    is_active=True).order_by('message__info_card_property__card_order_number'))
                    info_cards+=reject_jturbo_x190_info_cards

            elif customer.can_reapply and application.is_allow_for_j1_migration():
                info_cards = list(android_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    extra_conditions=CardProperty.MTL_MIGRATION_CAN_REAPPLY,
                    product=None,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
            elif not customer.can_reapply and application.is_allow_for_j1_migration():
                info_cards = list(android_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    extra_conditions=CardProperty.MTL_MIGRATION_CAN_NOT_REAPPLY,
                    product=None,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
                if info_cards:
                    available_context['reapply_date'] = customer.reapply_msg
            # if still in experiment and the app is 105
            elif mandocs_overhaul_105:
                is_c_score = JuloOneService.is_c_score(application)
                if is_c_score:
                    eta_time = get_eta_time_for_c_score_delay(application)
                    if now > eta_time:
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=application.application_status_id,
                            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                    else:
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=application.application_status_id,
                            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DElAY,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                else:
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.CUSTOMER_WAITING_SCORE,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
            elif application.application_status_id == mandocs_overhaul_status_code:
                customer_high_score = feature_high_score_full_bypass(application)
                customer_with_high_c_score = JuloOneService.is_high_c_score(application)
                is_c_score = JuloOneService.is_c_score(application)
                is_hold_status_hsfbp = is_hsfbp_hold_with_status(application, is_ios_device=False)

                if is_hold_status_hsfbp:
                    info_cards = list(
                        android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=application.application_status_id,
                            extra_conditions=CardProperty.CUSTOMER_WAITING_SCORE,
                            is_active=True,
                        ).order_by('message__info_card_property__card_order_number')
                    )
                elif is_c_score:
                    eta_time = get_eta_time_for_c_score_delay(application)
                    if now > eta_time:
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=application.application_status_id,
                            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                    else:
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=application.application_status_id,
                            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DElAY,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                elif customer_high_score:
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.CUSTOMER_HAVE_HIGH_SCORE,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                elif customer_with_high_c_score:
                    if sonic_pass:
                        julo_one_service = JuloOneService()
                        if not julo_one_service.check_affordability_julo_one(application):
                            info_cards = list(android_infocards_queryset.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                status_code_id=application.application_status_id,
                                extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                        else:
                            info_cards = list(android_infocards_queryset.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                status_code_id=application.application_status_id,
                                extra_conditions=CardProperty.CUSTOMER_HAVE_HIGH_SCORE,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                    else:

                        if etl_job:
                            if mandocs_overhaul_status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED and \
                                    etl_job.status == 'load_success':
                                do_advance_ai_id_check_task.delay(application.id)

                        card_property = CardProperty.CUSTOMER_HAVE_HIGH_SCORE

                        job_type = JobType.objects.get_or_none(
                            job_type=application.job_type)
                        is_salaried = job_type.is_salaried if job_type else None
                        passes_income_check = salary_izi_data and is_salaried
                        if (
                            not is_data_check_passed
                            or mandocs_overhaul_status_code == ApplicationStatusCodes.FORM_PARTIAL
                        ) and (
                            not passes_income_check
                            or (
                                passes_income_check
                                and (
                                    not is_income_in_range(application)
                                    or not is_income_in_range_agent_assisted_partner(application)
                                    or not is_income_in_range_leadgen_partner(application)
                                )
                            )
                        ):
                            is_document_submission = True
                            card_property = CardProperty.CUSTOMER_HAVE_HIGH_C_SCORE

                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=application.application_status_id,
                            extra_conditions=card_property,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
                elif not is_c_score:
                    # Medium because not meet customer high score and not meet
                    # high c score also not meet c
                    if etl_job:
                        if mandocs_overhaul_status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED and \
                                etl_job.status == 'load_success':
                            do_advance_ai_id_check_task.delay(application.id)

                    card_property = CardProperty.CUSTOMER_HAVE_HIGH_SCORE

                    job_type = JobType.objects.get_or_none(
                        job_type=application.job_type)
                    is_salaried = job_type.is_salaried if job_type else None
                    passes_income_check = salary_izi_data and is_salaried
                    if (
                        not sonic_pass
                        and (
                            not is_data_check_passed
                            or mandocs_overhaul_status_code == ApplicationStatusCodes.FORM_PARTIAL
                        )
                        and (
                            not passes_income_check
                            or (
                                passes_income_check
                                and (
                                    not is_income_in_range(application)
                                    or not is_income_in_range_agent_assisted_partner(application)
                                    or not is_income_in_range_leadgen_partner(application)
                                )
                            )
                        )
                    ):
                        is_document_submission = True
                        card_property = CardProperty.CUSTOMER_HAVE_MEDIUM_SCORE

                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=card_property,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
            elif (
                application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
                and not application.is_julo_starter()
            ):
                if not customer.can_reapply:
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=None,
                        status_code_id=ApplicationStatusCodes.APPLICATION_DENIED,
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                else:
                    negative_payment_history = not is_customer_has_good_payment_histories(
                        customer, is_for_julo_one=True)
                    if negative_payment_history:
                        extra_condition = CardProperty.MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY
                    else:
                        extra_condition = CardProperty.ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=extra_condition,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))

            elif application.application_status_id in (
                    ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
                    ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
            ):
                info_cards = list(android_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    extra_conditions=CardProperty.TYPO_CALLS_UNSUCCESSFUL,
                    product='j1',
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))

            elif application.application_status_id == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
                info_cards = get_info_cards_privy(application.id)

            elif application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED:
                if customer.can_reapply and not application.is_julo_starter():
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.ALREADY_ELIGIBLE_TO_REAPPLY,
                        product=None,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
            elif application.application_status_id in (
                    ApplicationStatusCodes.LOC_APPROVED,
                    ApplicationStatusCodes.MISSING_EMERGENCY_CONTACT
            ):
                show_master_agreement = False
                try:
                    if app_version and semver.match(app_version, ">=7.7.0"):
                        show_master_agreement = True
                except ValueError:
                    show_master_agreement = False

                if (not application.has_master_agreement() and application.is_julo_one()
                        and show_master_agreement):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                        extra_conditions=CardProperty.HAS_NOT_SIGN_MASTER_AGREEMENT,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                else:
                    if not is_already_have_transaction(customer):
                        info_cards = list(android_infocards_queryset.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                            extra_conditions=CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))

                    if is_first_time_user_paid_for_first_installment(application):
                        info_cards = list(StreamlinedCommunication.objects.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            status_code_id=LoanStatusCodes.PAID_OFF,
                            extra_conditions=CardProperty.PAID_FIRST_INSTALLMENT_AND_NOT_REFER,
                            is_active=True
                        ).order_by('message__info_card_property__card_order_number'))
            elif (application.application_status_id
                  == ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER):
                if application.is_julo_one():
                    # use same info card of jstarter for for j turbo
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=None,
                        extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
                        product="jstarter",
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))

            if len(info_cards) == 0:
                # Change infocard when reach in x141 status to Infocard JTurbo
                if (is_upgrade_application
                        and application.application_status_id == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER):
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.ACTIVATION_CALL_JTURBO_UPGRADE,
                        product=Product.STREAMLINED_PRODUCT.jstarter,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))

                else:
                    # Default infocards
                    info_cards = list(android_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions__isnull=True,
                        is_active=True
                    ).exclude(
                        product='jstarter'
                    ).order_by('message__info_card_property__card_order_number'))

            if application.application_status_id == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
                is_document_submission = True

            data['is_document_submission'] = is_document_submission
            is_block_infocard = False
            account = application.account
            # Account-based info card. Applies for JTurbo and J1.
            if account:
                account_status = account.status.status_code
                if account_status in AccountConstant.EMPTY_INFO_CARD_ACCOUNT_STATUS:
                    if not application.is_julo_starter():
                        is_block_infocard = True
                        # delete existing infocard because account status is 430
                        info_cards = []
                elif account_status == JuloOneCodes.ACTIVE:
                    # share customer referral code info card
                    if show_referral_code(customer):
                        share_referral_info_card = StreamlinedCommunication.objects.filter(
                            template_code=TemplateCode.CARD_REFERRAL_SERBUCUANKITA,
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            is_active=True,
                            extra_conditions=CardProperty.J1_ACTIVE_REFERRAL_CODE_EXIST
                        ).last()
                        if share_referral_info_card:
                            info_cards.append(share_referral_info_card)

            if (
                    application.application_status_id in (
                        ApplicationStatusCodes.LOC_APPROVED,
                        ApplicationStatusCodes.MISSING_EMERGENCY_CONTACT
                    )
            ):
                # J1 Extra Condition Info Card at x190.
                if application.is_julo_one():
                    # Marketing Prize Chance Info Card. See `loan.services.loan_prize_chance`
                    try:
                        is_eligible_prize_chance, prize_chances = get_prize_chances_by_application(
                            application
                        )
                        if is_eligible_prize_chance:
                            prize_chance_info_cards = list(
                                StreamlinedCommunication.objects.filter(
                                    communication_platform=CommunicationPlatform.INFO_CARD,
                                    extra_conditions=FeatureNameConst.MARKETING_LOAN_PRIZE_CHANCE,
                                    is_active=True,
                                ).order_by('message__info_card_property__card_order_number')
                            )
                            available_context['prize_chances'] = prize_chances
                            info_cards = prize_chance_info_cards + info_cards
                    except Exception:
                        logger.exception('Error getting prize chance info card')
                        get_julo_sentry_client().captureException()

                    # check limit after upgrade
                    using_turbo_limit = is_using_turbo_limit(application)

                    # handle infocard if user success upgrade
                    # from JTurbo to J1
                    if is_upgrade_application:
                        if using_turbo_limit:
                            upgrade_info_cards = list(android_infocards_queryset.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                                extra_conditions='J1_LIMIT_LESS_THAN_TURBO',
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                        else:
                            # put the condition card if get more than limit from JTurbo
                            upgrade_info_cards = list(android_infocards_queryset.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                                extra_conditions='J1_LIMIT_MORE_THAN_TURBO',
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                        info_cards = upgrade_info_cards + info_cards

                    eligible_for_app_ptp, already_have_ptp, ptp_date, in_app_ptp_order = is_eligible_for_in_app_ptp(
                        application.account
                    )

                    if eligible_for_app_ptp and not is_show_new_ptp_card(app_version):
                        if not already_have_ptp:
                            info_cards_ptp = StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.INAPP_PTP_BEFORE_SET,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number')
                        else:
                            info_cards_ptp = StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.INAPP_PTP_AFTER_SET,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number')
                            formatted_date = format_date(ptp_date, 'd MMM yyyy', locale='id_ID')
                            available_context['selected_date'] = formatted_date

                        if in_app_ptp_order and in_app_ptp_order == 'force_top_order':
                            highest_info_card = info_cards_ptp.last()
                        else:
                            info_cards = list(info_cards_ptp) + info_cards

                    info_cards_callback = []
                    eligible_for_app_callback, selected_time_slot_start = is_eligible_for_in_app_callback(
                        application.account
                    )
                    if eligible_for_app_callback:
                        if selected_time_slot_start:
                            data['isEligibleInAppCallbackAlert'] = False
                            info_cards_callback = list(StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.INAPP_CALLBACK_ALREADY_FILLED,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                            selected_time_slot_start = '{} WIB'.format(selected_time_slot_start)
                            available_context['selected_time_slot_start'] = selected_time_slot_start
                        else:
                            data['isEligibleInAppCallbackAlert'] = True
                            info_cards_callback = list(StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.ELIGIBLE_FOR_INAPP_CALLBACK,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                    info_cards = info_cards_callback + info_cards

                    credit_card_application = account.creditcardapplication_set.last()
                    if credit_card_application:
                        if credit_card_application.status_id == CreditCardCodes.RESUBMIT_SELFIE:
                            info_cards += list(StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.CREDIT_CARD_RESUBMIT_SELFIE,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))
                        elif credit_card_application.status_id == \
                                CreditCardCodes.CARD_BLOCKED_WRONG_PIN:
                            info_cards += list(StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.JULO_CARD_WRONG_PIN_EXCEED,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))

                    loan = application.account.loan_set.last()
                    if loan:
                        if not is_block_infocard:
                            loan_cards = get_loan_info_card(loan)
                            info_cards = loan_cards + info_cards

                        active_loans = account.loan_set.filter(
                            loan_status_id__gte=LoanStatusCodes.CURRENT,
                            loan_status_id__lt=LoanStatusCodes.RENEGOTIATED)
                        first_installment_paid = active_loans.filter(
                            payment__payment_status_id__gte=PaymentStatusCodes.PAID_ON_TIME)
                        if active_loans and not first_installment_paid:
                            double_disburse_card = StreamlinedCommunication.objects.filter(
                                template_code='card_double_disburse')
                            info_cards = info_cards + list(double_disburse_card)

                        oldest_account_payment = loan.account.accountpayment_set.not_paid_active() \
                            .order_by('due_date') \
                            .first()
                        if oldest_account_payment:
                            dpd = oldest_account_payment.dpd
                            account_payment_cards = get_reminder_streamlined_comms_by_dpd(
                                android_infocards_queryset, dpd, account)
                            info_cards = account_payment_cards + info_cards

                    if is_autodebet_whitelist_feature_active(application.account):
                        success, benefit_name, _ = get_autodebet_benefit_data(application.account)
                        benefit_names = benefit_name.split("_")
                        if success and benefit_names[0] in CardProperty.AUTODEBET_BENEFITS:
                            info_cards += list(StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.AUTODEBET_BENEFITS[benefit_names[0]],
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number'))

                    autodebet_account = get_existing_autodebet_account(application.account)
                    _filters = {
                        'communication_platform': CommunicationPlatform.INFO_CARD,
                        'extra_conditions': CardProperty.AUTODEBET_NOT_ACTIVE,
                        'is_active': True,
                    }
                    if (
                        not autodebet_account or not autodebet_account.is_use_autodebet
                    ) and not is_disabled_autodebet_activation(account):
                        info_cards += list(
                            StreamlinedCommunication.objects.filter(**_filters)
                            .exclude(template_code=TemplateCode.IDFY_AUTODEBET_NOT_ACTIVE)
                            .order_by('message__info_card_property__card_order_number')
                        )

                    if is_idfy_autodebet_valid(application.account) and is_idfy_profile_exists(
                        application.account
                    ):
                        info_cards += list(
                            StreamlinedCommunication.objects.filter(
                                **_filters,
                                template_code=TemplateCode.IDFY_AUTODEBET_NOT_ACTIVE,
                            ).order_by('message__info_card_property__card_order_number')
                        )

                    credit_card_loan_inactive = get_loan_credit_card_inactive(account)
                    if credit_card_loan_inactive:
                        account_limit = account.get_account_limit
                        loan_amount_request = credit_card_loan_inactive.loan_disbursement_amount
                        _, credit_matrix_product_line = \
                            get_credit_matrix_and_credit_matrix_product_line(
                                application,
                                False,
                                False,
                                TransactionMethodCode.CREDIT_CARD.name
                            )
                        available_durations = get_loan_duration(
                            loan_amount_request,
                            credit_matrix_product_line.max_duration,
                            credit_matrix_product_line.min_duration,
                            account_limit.set_limit,
                            account.customer,
                            application
                        )
                        if loan_amount_request <= 100000:
                            available_durations = [1]
                        if len(available_durations) > 1:
                            choose_tenor_info_card = StreamlinedCommunication.objects.filter(
                                communication_platform=CommunicationPlatform.INFO_CARD,
                                extra_conditions=CardProperty.CREDIT_CARD_TRANSACTION_CHOOSE_TENOR,
                                is_active=True
                            ).order_by('message__info_card_property__card_order_number')
                            info_cards = list(choose_tenor_info_card) + info_cards
            elif application.is_julover():
                loan = application.account.loan_set.last()
                if not is_block_infocard and loan:
                    loan_cards = get_loan_info_card(loan)
                    info_cards = loan_cards + info_cards

            if account:
                account_status = account.status_id
                if account_status == AccountConstant.STATUS_CODE.fraud_soft_reject:
                    # delete existing infocard because account status is 443
                    info_cards = []
                    soft_reject_info_card = StreamlinedCommunication.objects.filter(
                        template_code=TemplateCode.FRAUD_SOFT_REJECT,
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        is_active=True).last()
                    if soft_reject_info_card:
                        info_cards.append(soft_reject_info_card)

                promotion_card = create_collection_hi_season_promo_card(application.account)
                is_locked_product = is_product_locked(
                    application.account, TransactionMethodCode.SELF.code
                )

                # eligible cashback claim check
                eligible_cashback = CashbackClaim.objects.filter(
                    account_id=account.id,
                    status=CashbackClaimConst.STATUS_ELIGIBLE,
                ).exists()
                if eligible_cashback:
                    cashback_claim_info_cards = list(
                        StreamlinedCommunication.objects.filter(
                            communication_platform=CommunicationPlatform.INFO_CARD,
                            extra_conditions=CardProperty.CASHBACK_CLAIM,
                            is_active=True,
                        ).order_by('message__info_card_property__card_order_number')
                    )
                    info_cards = info_cards + cashback_claim_info_cards

        self_deeplink = "product_transfer_self"
        processed_info_cards = []
        today_date = timezone.localtime(timezone.now()).date()

        for info_card in info_cards:
            is_expired = False

            # check locked product
            card_property = info_card.message.info_card_property
            is_deeplink_card = card_property and card_property.card_destination == self_deeplink
            if is_locked_product and is_deeplink_card:
                continue

            button_list = card_property.button_list
            skip_button = False
            for button in button_list:
                if is_locked_product and button.destination == self_deeplink:
                    skip_button = True
                    break

            if skip_button:
                continue

            if app_version and semver.match(app_version, "<8.5.0") and card_property.card_type == '9':
                continue

            if info_card.expiration_option and info_card.expiration_option != "No Expiration Time":
                is_expired = is_info_card_expired(info_card, application, loan)
            if not is_expired:
                processed_info_cards.append(
                    format_info_card_for_android(
                        info_card, available_context, account.id if account else None
                    )
                )
        if promotion_card is not None and not is_block_infocard:
            if not is_locked_product or promotion_card['buttonurl'] != self_deeplink:
                promotion_card = dict(
                    streamlined_communication_id=None,
                    type=None,
                    title=None,
                    content=None,
                    button=None,
                    border=None,
                    background_img=promotion_card['topimage'],
                    image_icn=None,
                    card_action_type=CardProperty.WEBPAGE,
                    card_action_destination=promotion_card['buttonurl'],
                )
                processed_info_cards.insert(0, promotion_card)
        if highest_info_card:
            processed_info_cards.insert(
                0, format_info_card_for_android(highest_info_card, available_context)
            )
        data['cards'] = processed_info_cards
        data['cards'] = extra_rules_for_info_cards(application, data['cards'])
        return success_response(data)


@julo_login_required
def submit_pause_reminder(request):
    block_id = int(request.POST.get('block_id'))
    block_type = str(request.POST.get('block_type'))
    comms_block = request.POST.getlist('comms_block[]', [])
    block_dpd = request.POST.get('block_dpd')
    if not block_dpd:
        return HttpResponseBadRequest('block until need to be filled', status=400)
    block_payment_ids = request.POST.getlist('block_ids[]', [])
    block_payments = []
    if block_type == 'mtl':
        loan = Loan.objects.get_or_none(id=block_id)
        if not loan:
            return HttpResponseBadRequest('loan not found', status=400)
        product = loan.product.product_line
        comms_blocked = CommsBlocked.objects.filter(loan=loan).last()
        customer = loan.customer
        for payment_id in block_payment_ids:
            payment = Payment.objects.get_or_none(id=payment_id)
            if not payment:
                return HttpResponseBadRequest('payment %s not found' % payment_id, status=400)
            dpd = payment.get_dpd
            block_payments.append(payment)
    elif block_type == 'j1':
        # will handle JTURBO as well
        account = Account.objects.get_or_none(id=block_id)
        if not account:
            return HttpResponseBadRequest('account not found', status=400)

        # check product type
        if account.account_lookup.workflow.name == WorkflowConst.JULO_STARTER:
            product = ProductLine.objects.filter(product_line_code=ProductLineCodes.JULO_STARTER).last()
        else:
            product = ProductLine.objects.filter(product_line_code=ProductLineCodes.J1).last()

        comms_blocked = CommsBlocked.objects.filter(account=account).last()
        customer = account.customer
        for account_payment_id in block_payment_ids:
            account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
            if not account_payment:
                return HttpResponseBadRequest(
                    'account payment %s not found' % account_payment_id, status=400)
            dpd = account_payment.dpd
            block_payments.append(account_payment)
    else:
        return HttpResponseBadRequest('block type %s not found' % block_type, status=400)

    comms_block_data = dict(
        is_email_blocked=True if CommsConst.EMAIL in comms_block else False,
        is_sms_blocked=True if CommsConst.SMS in comms_block else False,
        is_robocall_blocked=True if CommsConst.ROBOCALL in comms_block else False,
        is_cootek_blocked=True if CommsConst.COOTEK in comms_block else False,
        is_pn_blocked=True if CommsConst.PN in comms_block else False,
        agent=request.user,
        block_until=int(block_dpd),
        product=product,
        loan=loan if block_type == 'mtl' else None,
        account=account if block_type == 'j1' else None,
        impacted_payments=[int(block_payment_id) for block_payment_id in block_payment_ids]
    )
    with transaction.atomic():
        if comms_blocked:
            comms_blocked.update_safely(**comms_block_data)
        else:
            CommsBlocked.objects.create(**comms_block_data)
        if block_type == 'j1':
            for block_payment in block_payments:
                send_user_attributes_to_moengage_for_block_comms.apply_async((
                    customer, block_payment),
                    countdown=settings.DELAY_FOR_REALTIME_EVENTS)

    return JsonResponse({'data': {'message': 'success'}})


@julo_login_required
def get_pause_reminder(request):
    block_id = request.GET.get('block_id')
    block_type = request.GET.get('block_type')
    template = loader.get_template('pause_reminder/pause_reminder.html')
    context = {
        'user': request.user,
        'show': True,
        'block_not_found': False,
        "block_type": 'loan',
    }

    if not block_id or not block_type:
        context['show'] = False
        return HttpResponse(template.render(context))

    if block_type == 'mtl':
        loan = Loan.objects.get_or_none(id=block_id)
        if not loan:
            context['show'] = False
            context['block_not_found'] = True
            return HttpResponse(template.render(context))
        comms_blocked = CommsBlocked.objects.filter(loan=loan).last()
        disabled_block = 'disabled' if comms_blocked else ''
        name = loan.customer.fullname
        last_payment = loan.get_oldest_unpaid_payment()
        if not last_payment:
            bucket = 'Current'
        else:
            bucket = str(last_payment.bucket_number) \
                if last_payment.bucket_number != 0 else 'Current'
        payments = get_unpaid_payments(loan, order_by='due_date')[:4]
        dpd = payments[0].get_dpd if payments else None
        impacted_payments = format_payments_to_block(
            payments, comms_blocked.impacted_payments if comms_blocked else None)
    elif block_type == 'j1':
        # will handle JTURBO as well
        account = Account.objects.get_or_none(id=block_id)
        if not account:
            context['show'] = False
            context['block_not_found'] = True
            return HttpResponse(template.render(context))
        comms_blocked = CommsBlocked.objects.filter(account=account).last()
        disabled_block = 'disabled' if comms_blocked else ''
        name = account.customer.fullname
        bucket = account.bucket_name
        account_payments = AccountPayment.objects.filter(
            account=account).not_paid_active().order_by('due_date')[:4]
        dpd = account_payments[0].dpd if account_payments else None
        impacted_payments = format_payments_to_block(
            account_payments, comms_blocked.impacted_payments if comms_blocked else None)
    else:
        return HttpResponseBadRequest('This view can not handle type {}'.format(block_type),
                                      status=400)

    context = RequestContext(request, {
        "block_id": block_id,
        "block_type": block_type,
        "show": True,
        "name": name,
        "bucket": bucket,
        "dpd": dpd,
        "comms_blocked": {
            'email': "checked" if comms_blocked and comms_blocked.is_email_blocked else "",
            'pn': "checked" if comms_blocked and comms_blocked.is_pn_blocked else "",
            'sms': "checked" if comms_blocked and comms_blocked.is_sms_blocked else "",
            'cootek': "checked" if comms_blocked and comms_blocked.is_cootek_blocked else "",
            'robocall': "checked" if comms_blocked and comms_blocked.is_robocall_blocked else "",
        },
        "block_until": comms_blocked.block_until if comms_blocked else None,
        "impacted_payments": impacted_payments,
        "disabled_block": disabled_block,
        "is_comms_blocked_existed": True if comms_blocked else False
    })

    return HttpResponse(template.render(context))


def format_payments_to_block(payments, block_payments=None):
    impacted_payments = []
    for payment in payments:
        payment_format = {
            'id': payment.id,
            'display_text': "{} ({})".format(
                str(payment.id), datetime.strftime(payment.due_date, '%d-%b')),
            'is_blocked': False
        }
        if block_payments and payment.id in block_payments:
            payment_format['is_blocked'] = True

        impacted_payments.append(payment_format)

    return impacted_payments


class PushNotificationPermissionDisturbLogging(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = PushNotificatonPermissionSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        customer = Customer.objects.get_or_none(
            pk=data['customer_id']
        )
        if not customer:
            return general_error_response("Account not found")

        return success_response(process_pn_logging(customer, data))


@julo_login_required
def mocking_sms_text_value(request):
    data = request.POST.dict()
    customer_id = data.get('customer_id')
    message = data.get('message')
    customer = Customer.objects.get_or_none(
        pk=int(customer_id))
    if not customer:
        return JsonResponse({
            'status': 'failed',
            'messages': 'Customer dengan id {} tidak ada'.format(customer_id)
        })
    account = customer.account
    account_payment = None
    model = customer.application_set.last()
    is_have_account_payment = False
    if account:
        account_payment = account.get_last_unpaid_account_payment()
        if account_payment:
            model = account_payment
            is_have_account_payment = True

    processed_message = process_sms_message_j1(
        message, model, is_have_account_payment=is_have_account_payment
    )
    return JsonResponse({
        'status': 'success',
        'processed_message': processed_message,
        'message_length': len(processed_message)
    })


class AndroidCheckNotificationValidity(StrictStandardizedExceptionHandlerMixin, APIView):
    serializer_class = NotificationActionType

    def post(self, request):
        selloff_white_list_serializer = NotificationSellOffWhiteList(
            data=request.data, context={'request': request})
        if not selloff_white_list_serializer.is_valid() and 'action' in request.data:
            return success_response({'isValid': False})

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = request.user.customer
        try:
            is_valid, response = validate_action(
                customer,
                request.data['action']
            )
        except (ApplicationNotFoundException, MissionEnableStateInvalid):
            is_valid = False

        if not is_valid:
            return success_response({'isValid': False})

        return success_response(response)


def _delete_pn_image(streamlined_communication_id):

    Image.objects.filter(
        image_source=streamlined_communication_id, image_type=ImageType.STREAMLINED_PN
    ).update(image_status=Image.DELETED)


def _delete_image(streamlined_communication_id, image_type):

    Image.objects.filter(image_source=streamlined_communication_id, image_type=image_type).update(
        image_status=Image.DELETED
    )


class InfobipSmsReport(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        """
        Infobip SMS callback format is based on its Receive Sent Sms Report API
        https://www.infobip.com/docs/api/channels/sms/sms-messaging/outbound-sms/send-sms-message#channels/sms/receive-sent-sms-report
        """
        data = request.data
        if not data:
            return general_error_response(data={'message': 'failure'}, message="No data sent")

        report_data = data['results']
        infobip_api_client = JuloInfobipClient()
        infobip_api_client.fetch_sms_report.delay(report_data)

        return success_response(data={"message": 'success'})


class InfobipVoiceReport(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        """
        Infobip robocall callback format is based on its Receive Voice Delivery Reports API
        https://www.infobip.com/docs/api/channels/voice/voice-reports-and-logs/receive-voice-delivery-reports
        """
        data = request.data
        if not data:
            return general_error_response(data={'message': 'failure'}, message='No data sent')
        report_data = data['results']
        infobip_api_client = JuloInfobipVoiceClient()
        infobip_api_client.fetch_voice_report.delay(report_data)

        return success_response(data={'message': 'success'})


class NeoBannerAndroidAPI(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    @parse_device_ios_user
    def get(self, request, *args, **kwargs):

        app_version = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        is_ios_device = True if device_ios_user else False

        empty_data = {'cards': None}
        customer = request.user.customer
        application = determine_main_application_infocard(customer)

        logger.info(
            {
                'message': 'get NeoBanner cards',
                'app_version': app_version,
                'application': application.id if application else None,
                'device_ios_user': device_ios_user,
            }
        )

        if not application:
            return success_response(empty_data)

        cards = get_neo_banner(application, app_version, is_ios_device)

        data = {
            'fullname': application.full_name_only,
            'cards': cards if len(cards) > 0 else None,
            'neo_infocard': get_neo_info_cards(application, app_version, is_ios_device),
            'button_active_until': get_expiry_hsfbp(application.id),
        }

        return success_response(data)


class IpaBannerAndroidAPI(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        customer = request.user.customer
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')
        else:
            return general_error_response("Pengecekan Awal gagal")

        try:
            fdc_binary, message = show_ipa_banner(customer, app_version)
        except StreamlinedCommunicationException as e:
            logger.warning({
                "action": "show_ipa_banner failed",
                "message": "exception when fdc binary check",
                "customer_id": customer.id,
                "error": str(e),
            })
            return general_error_response("Pengecekan Awal gagal")

        data = {
            "customer_id": customer.id,
            'show_ipa_banner': fdc_binary,
            'message': message
        }
        return success_response(data)


class IpaBannerAndroidAPIV2(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        customer = request.user.customer

        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')
        else:
            logger.error({
                'message': 'App version data is empty',
                'customer': customer.id if customer else None
            })
            return general_error_response("Mohon maaf terjadi kesalahan")

        try:
            show_banner, show_stickybar, message = show_ipa_banner_v2(customer, app_version)
        except StreamlinedCommunicationException as e:
            logger.warning({
                "action": "show_ipa_banner_v2 failed",
                "customer_id": customer.id,
                "error": str(e),
            })
            return general_error_response("Pengecekan Awal gagal")

        data = {
            "customer_id": customer.id,
            'show_sticky_banner': show_stickybar,
            'show_ipa_banner': show_banner,
            'message': message
        }
        return success_response(data)


class AlicloudSmsReport(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        """
        Alicloud SMS callback processing.
        """
        data_array = request.data
        if not data_array:
            return general_error_response(data={'message': 'failure'}, message='No data sent')

        alicloud_api_client = JuloAlicloudClient()
        for data in data_array:
            alicloud_api_client.process_sms_report.delay(data)

        return success_response(data={'code': 0, 'message': 'The message is received.'})


class AccountSellOffContent(StandardizedExceptionHandlerMixinV2, APIView):
    def get(self, request):
        customer = request.user.customer
        data = get_selloff_content(customer.account)
        return success_response(data)


class SlikNofication(StandardizedExceptionHandlerMixinV2, APIView):
    def get(self, request):
        customer = request.user.customer
        data = get_slik_data(customer.account)
        return success_response(data)


class OTPLessDeliveryReport(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        """
        OTPLess delivery report callback processing.
        {
            "status": "DELIVERED/SENT/READ",
            "data": {
                "referenceId": "626579608ad840b39906f14e999f66a6",
                "timestamp": 1704802716000,
                "identity": "08123456789",
                "channel": "WHATSAPP",
                "errorCode": "003",
                "errorMessage": "Other Delivery Failure"
            }
        }
        """
        data = request.data.get('data',None)
        status = request.data.get('status',None)

        if not data:
            return general_error_response(data={'message': 'failure'}, message='No data sent')

        OtpLessHistory.objects.create(
            status=status,
            otpless_reference_id=data.get('referenceId', 'empty_callback'),
            timestamp=datetime.fromtimestamp(int(data.get('timestamp', 0)) / 1000),
            phone_number=data.get('identity', 'empty_callback'),
            channel=data.get('channel', 'empty_callback'),
            error_code=data.get('errorCode', None),
            error_message=data.get('errorMessage', None),
        )

        return success_response(data={'code': 201, 'message': 'Callback Success.'})

class OTPLessVerificationReport(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        """
        OTPLess validation code used processing.
        {
            "token": "626579608ad840b39906f14e999f66a6",
            "timestamp": "2023-09-05T19:08:09Z",
            "mobile": {
                "name": "OTPless",
                "number": "08123456789"
            },
            "requestId": "580884110b1b46668baa1d46a65f46d9",
            "notificationType": "FALLBACK_TRIGGERED",
            "fallbackChannel": "WHATSAPP/SMS"
        }
        """
        reference_id = request.data.get('token', 'empty_callback')
        notificationType = request.data.get('notificationType', None)
        mobile = request.data.get('mobile', None)
        fallbackChannel = request.data.get('fallbackChannel', None)

        if notificationType:
            if notificationType == 'FALLBACK_TRIGGERED':
                OtpLessHistory.objects.create(
                    status=notificationType,
                    otpless_reference_id=reference_id,
                    timestamp=datetime.fromtimestamp(int(request.data.get('timestamp', 0)) / 1000),
                    phone_number=mobile.get('number', 'empty_callback'),
                    channel=fallbackChannel,
                    error_code=None,
                    error_message=None,
                )
                return success_response(data={'code': 201, 'message': 'Callback Success.'})

        if not reference_id:
            return general_error_response(data={'message': 'failure'}, message='No data sent')

        otpless_history = OtpLessHistory.objects.filter(
            otpless_reference_id=reference_id
        )
        if not otpless_history:
            return general_error_response(data={'message': 'failure'}, message='No data found related to given reference id')

        for entry in otpless_history:
            entry.update_safely(is_confirmed_used=True)
        return success_response(data={'code': 201, 'message': 'Callback Success.'})


class OTPLessSMSCallbackEntryPoint(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        """
        OTPLess validation code used processing.
        {
            request_id : 580884110b1b46668baa1d46a65f46d9,
            phone_number: 08123456789,
            verification_link: https://otpless.me/Cc3fiHZQ9qHZ,
            expiry_time: 60
        }
        """

        phone_number = request.data.get('phone_number', None)
        otpless_link = request.data.get('verification_link', None)
        if not phone_number:
            return general_error_response(
                data={'message': 'failure'}, message='Phone number is empty'
            )
        if not otpless_link:
            return general_error_response(
                data={'message': 'failure'}, message='Verification link is empty'
            )

        response = send_otpless_sms_request(phone_number, otpless_link)
        if not response:
            return general_error_response(data={'message': 'failure'}, message='SMS sending failed')

        return success_response(data={'code': 201, 'message': 'SMS Callback Success.'})


class SmsCampaignListPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


class CampaignCreateListView(StandardizedExceptionHandlerMixin, ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = StreamlinedCommunicationCampaignListSerializer
    pagination_class = SmsCampaignListPagination

    def get_queryset(self):
        campaign_status = self.request.GET.get('campaign_status')
        sort_by = self.request.GET.get('sort_by')
        sms_campaigns_qs = StreamlinedCommunicationCampaign.objects.all()
        if campaign_status is not None:
            backend_statuses = StreamlinedCommCampaignConstants.status_mapping.get(
                campaign_status.lower(), []
            )
            if backend_statuses:
                sms_campaigns_qs = sms_campaigns_qs.filter(status__in=backend_statuses)
        if sort_by:
            sort_mapping = {
                'department': 'department__name',
                'user_segment': 'user_segment__segment_name',
                'created_by': 'created_by__email',
            }
            descending = sort_by.startswith('-')
            sort_key = sort_by.lstrip('-')
            if sort_by.lstrip('-') in sort_mapping:
                order_by_field = sort_mapping.get(sort_key, sort_by)
                if descending:
                    order_by_field = '-' + order_by_field
            else:
                order_by_field = sort_by
            sms_campaigns_qs = sms_campaigns_qs.order_by(order_by_field)

        return sms_campaigns_qs

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = self.pagination_class()
        result_page = paginator.paginate_queryset(queryset, self.request)
        serializer = self.serializer_class(result_page, many=True)
        data = {"data": serializer.data, "total_count": queryset.count()}
        return paginator.get_paginated_response(data)

    def post(self, request, *args, **kwargs):
        user = request.user
        if not any(
            element in list(user.groups.all().values_list('name', flat=True))
            for element in ['product_manager', 'comms_campaign_manager']
        ):
            return general_error_response(
                {'message': 'You do not have permission to perform this action.'}
            )
        serializer = StreamlinedCommunicationCampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=HTTP_201_CREATED)


class CampaignDropdownListView(StandardizedExceptionHandlerMixin, ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        if not any(
            element in list(user.groups.all().values_list('name', flat=True))
            for element in ['product_manager', 'comms_campaign_manager']
        ):
            return general_error_response(
                {'message': 'You do not have permission to perform this action.'}
            )
        departments = StreamlinedCampaignDepartment.objects.all().values('id', 'name')
        user_segments = (
            StreamlinedCommunicationSegment.objects.annotate(
                total_sms_price=ExpressionWrapper(
                    get_total_sms_price(Coalesce(F('segment_count'), Value(0))),
                    output_field=FloatField(),
                ),
                segment_users_count=Coalesce(F('segment_count'), Value(0)),
            )
            .filter(
                Q(
                    status__in=[
                        CommsUserSegmentConstants.SegmentStatus.SUCCESS,
                        CommsUserSegmentConstants.SegmentStatus.PROCESSING,
                    ]
                )
            )
            .values(
                'id', 'segment_name', 'segment_users_count', 'total_sms_price', 'status', 'cdate'
            )
        )

        squads = StreamlinedCampaignSquad.objects.all().values('id', 'name')

        data = {
            'department': departments,
            'squad': squads,
            'user_segment': user_segments,
        }
        return Response(status=HTTP_201_CREATED, data=data)


class CampaignTestSmsView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        if not any(
            element in list(user.groups.all().values_list('name', flat=True))
            for element in ['product_manager', 'comms_campaign_manager']
        ):
            return general_error_response(
                {'message': 'You do not have permission to perform this action.'}
            )
        data = request.data
        phone_number = data.get('phone_number')
        serializer = CommsCampaignPhoneNumberSerializer(data={'phone_number': phone_number})
        serializer.is_valid(raise_exception=True)
        julo_sms_client = get_julo_sms_client()
        msg = data.get('content')
        phone_number = format_e164_indo_phone_number(phone_number)
        message, response = julo_sms_client.send_sms(phone_number, msg)
        response['messages'][0]['is_comms_campaign_sms'] = True
        response = response['messages'][0]

        if response["status"] != "0":
            logger.exception(
                {
                    "send_status": response["status"],
                    "message_id": response.get("message-id"),
                    "sms_client_method_name": "campaign_test_sms",
                    "error_text": response.get("error-text"),
                }
            )
            return general_error_response({"message": "Failed to send SMS"})
        template_code = StreamlinedCommCampaignConstants.TemplateCode.TEST_SMS
        sms = create_sms_history(
            response=response,
            message_content=msg,
            to_mobile_phone=format_e164_indo_phone_number(phone_number),
            phone_number_type="mobile_phone_1",
            template_code=template_code,
        )
        if sms:
            logger.info(
                {
                    "status": "sms_created",
                    "sms_history_id": sms.id,
                    "message_id": sms.message_id,
                }
            )
            return success_response(
                {
                    "message": "SMS sent successfully",
                    "sms_history_id": sms.id,
                    "message_id": sms.message_id,
                }
            )

        return general_error_response({"message": "Failed to create SMS history"})


class ApproveRejectCommsCampaignView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        if not any(
            element in list(user.groups.all().values_list('name', flat=True))
            for element in ['comms_campaign_manager']
        ):
            return general_error_response(
                {'message': 'You do not have permission to perform this action. '}
            )

        campaign_id = request.data.get('campaign_id', None)
        action_type = request.data.get('action_type', None)

        if not campaign_id:
            return general_error_response({'message': 'Campaign id is empty'})

        campaign = get_object_or_404(StreamlinedCommunicationCampaign, pk=campaign_id)
        if campaign.status != StreamlinedCommCampaignConstants.CampaignStatus.WAITING_FOR_APPROVAL:
            return general_error_response(
                {'message': 'Campaign status is not waiting for approval'}
            )
        if action_type.lower() == StreamlinedCommCampaignConstants.Action.REJECT:
            StreamlinedCommunicationCampaign.objects.filter(pk=campaign_id).update(
                status=StreamlinedCommCampaignConstants.CampaignStatus.REJECTED, confirmed_by=user
            )
            return success_response({"message": "SMS campaign Rejected"})
        elif action_type.lower() == StreamlinedCommCampaignConstants.Action.APPROVE:
            StreamlinedCommunicationCampaign.objects.filter(pk=campaign_id).update(
                status=StreamlinedCommCampaignConstants.CampaignStatus.ON_GOING,
                confirmed_by=user,
            )
            response = self.process_sms_campaign_with_user_segment(campaign_id)
            return JsonResponse({'data': response.data}, status=response.status_code)
        return general_error_response({'message': 'Invalid action_type'})

    def get_valid_mobile_number_list(self, mobile_number_list):
        """
        Filter and format a list of mobile numbers to return only the valid ones.
        Args:
            mobile_number_list (list): A list of mobile numbers to validate and format.
        Returns:
            list: A list of valid mobile numbers format.
        """
        valid_numbers = []
        for number in mobile_number_list:
            try:
                formatted_number = format_valid_e164_indo_phone_number(number)
                valid_numbers.append(formatted_number)
            except InvalidPhoneNumberError:
                logger.warning(
                    {
                        "message": "Invalid phone number.",
                        "method_name": "get_valid_mobile_number_list",
                        'mobile_number': number,
                    }
                )
        return valid_numbers

    def get_mobile_numbers_list(self, column_header, csv_data_list):
        result_tuples = []
        if column_header == 'account_id':
            accounts = Account.objects.filter(pk__in=csv_data_list)
            result_tuples = [
                (account.id, account.customer.application_set.last().mobile_phone_1)
                for account in accounts
                if account.customer.application_set.last()
            ]
        elif column_header == 'application_id':
            applications = Application.objects.filter(pk__in=csv_data_list)
            result_tuples = [(app.id, app.mobile_phone_1) for app in applications]
        elif column_header == 'customer_id':
            customers = Customer.objects.filter(pk__in=csv_data_list)
            result_tuples = [
                (customer.id, customer.application_set.last().mobile_phone_1)
                for customer in customers
                if customer.application_set.last()
            ]
        elif column_header == 'phone_number':
            result_tuples = [(None, str(phone_number)) for phone_number in csv_data_list]
        mobile_number_list = [mobile_number for _, mobile_number in result_tuples]
        valid_mobile_number_list = self.get_valid_mobile_number_list(mobile_number_list)
        filtered_result_tuples = [
            (csv_data, format_e164_indo_phone_number(mobile_number))
            for csv_data, mobile_number in result_tuples
            if format_e164_indo_phone_number(mobile_number) in valid_mobile_number_list
        ]

        return filtered_result_tuples

    def send_sms_campaign(self, mobile_numbers_tuples, campaign, column_header):
        template_code = 'J1_sms_{}'.format(campaign.name)
        msg = campaign.content.message_content
        for csv_item_id, phone_number in mobile_numbers_tuples:
            send_sms_campaign_async.delay(
                phone_number, msg, template_code, csv_item_id, column_header, campaign
            )

    def process_sms_campaign_with_user_segment(self, campaign_id):
        """
        Process an SMS campaign for a given campaign ID.
        This function retrieves user data based on the user segment associated with the campaign,
        processes the CSV file containing the user data, extracts mobile numbers,
        and initiates an SMS campaign to the extracted mobile numbers.
        Parameters:
        - campaign_id (int): The ID of the StreamlinedCommunicationCampaign to process.
        Returns:
        - dict: A dictionary containing a success message if the SMS campaign tasks are enqueued successfully,
                or an error message if any step fails.
        """

        campaign = get_object_or_404(StreamlinedCommunicationCampaign, pk=campaign_id)
        import_user_client = streamlined_services.StreamlinedImportUserClient(
            segment_obj=campaign.user_segment
        )
        responses = import_user_client.get_downloadable_response()
        for response in responses:
            column_header, csv_data_list = self.process_user_segment_csv_file(response)
            if not column_header or not csv_data_list:
                StreamlinedCommunicationCampaign.objects.filter(pk=campaign_id).update(
                    status=StreamlinedCommCampaignConstants.CampaignStatus.FAILED
                )
                return general_error_response({"message": "Failed to process CSV data"})
            mobile_numbers_tuples = self.get_mobile_numbers_list(column_header, csv_data_list)
            mobile_numbers_list = [mobile_number for _, mobile_number in mobile_numbers_tuples]

            if not mobile_numbers_list:
                StreamlinedCommunicationCampaign.objects.filter(pk=campaign_id).update(
                    status=StreamlinedCommCampaignConstants.CampaignStatus.FAILED
                )
                return general_error_response({"message": "No mobile numbers found"})
            self.send_sms_campaign(mobile_numbers_tuples, campaign, column_header)
            set_campaign_status_partial_or_done.apply_async((campaign,), countdown=300)
        feature_setting = FeatureSetting.objects.get(
            feature_name=FeatureNameConst.SMS_CAMPAIGN_FAILED_PROCESS_CHECK_TTL,
        )
        handle_failed_campaign_and_notify_slack.apply_async(
            (campaign,), countdown=int(feature_setting.parameters['TTL'])
        )

        return success_response({"message": "SMS campaign tasks enqueued for processing"})

    def process_user_segment_csv_file(self, downloadable_response):
        """
        Process the CSV content from a downloadable response to extract specific data.
        This function reads the streaming content from the downloadable response,
        converts it to a CSV file, and extracts data based on specific headers.
        Parameters:
        - downloadable_response: The downloadable response object containing CSV content.
        Returns:
        - tuple: A tuple containing the header of the CSV file and a list of extracted data.
                 Otherwise, it returns (None, None).
        """

        csv_content = b''
        for chunk in downloadable_response.streaming_content:
            csv_content += chunk

        csv_content_str = csv_content.decode('utf-8')
        csv_file = StringIO(csv_content_str)

        csv_reader = csv.reader(csv_file)
        header = None
        try:
            header = next(csv_reader)
        except StopIteration:
            return None, None

        if header[0] in ['application_id', 'account_id', 'customer_id', 'phone_number']:
            csv_data_list = []
            for row in csv_reader:
                if row[0].strip():
                    try:
                        data = int(row[0].strip())
                        csv_data_list.append(data)
                    except ValueError:
                        print(f"Skipping invalid value: {row[0]}")
            return header[0], csv_data_list
        return None, None


class DownloadCampaignReportView(StandardizedExceptionHandlerMixin, ListAPIView):
    authentication_classes = [SessionAuthentication]

    def post(self, request, *args, **kwargs):
        campaign_id = request.data.get('campaign_id', None)
        if not campaign_id:
            return general_error_response({'message': 'Campaign id cant be empty'})

        campaign_obj = StreamlinedCommunicationCampaign.objects.get(pk=campaign_id)
        if campaign_obj.status in [
            StreamlinedCommCampaignConstants.CampaignStatus.WAITING_FOR_APPROVAL,
            StreamlinedCommCampaignConstants.CampaignStatus.ON_GOING,
        ]:
            return general_error_response(
                {'message': 'Campaign is still pending approval or ongoing. Cannot proceed.'}
            )

        campaign_sms_history_qs = CommsCampaignSmsHistory.objects.filter(
            template_code='J1_sms_{}'.format(campaign_obj.name)
        )

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="campaign_sms_report.csv"'

        csv_writer = csv.writer(response)

        csv_writer.writerow(
            [
                'WAKTU DIBUAT',
                'DIBUAT OLEH',
                'DEPARTEMEN',
                'TIPE CAMPAIGN',
                'NAMA CAMPAIGN',
                'USER SEGMENT',
                'ACCOUNT ID',
                'CUSTOMER ID',
                'APPLICATION ID',
                'PHONE NUMBER',
                'DELIVERY STATUS',
                'TIPE DATA SEGMENT',
            ]
        )
        if not campaign_sms_history_qs:
            return general_error_response({'message': 'Campaign SMS history is empty.'})

        for sms_history in campaign_sms_history_qs:
            if sms_history:
                csv_writer.writerow(
                    [
                        campaign_obj.cdate,
                        campaign_obj.created_by,
                        campaign_obj.department,
                        campaign_obj.campaign_type,
                        campaign_obj.name,
                        campaign_obj.user_segment.segment_name,
                        sms_history.account_id,
                        sms_history.customer_id,
                        sms_history.application_id,
                        sms_history.to_mobile_phone,
                        sms_history.status,
                        campaign_obj.user_segment.csv_file_type,
                    ]
                )
            else:
                csv_writer.writerow(['', '', '', '', '', '', '', '', ''])

        return response


class CampaignDetailView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, campaign_id):
        user = request.user
        if not any(
            element in list(user.groups.all().values_list('name', flat=True))
            for element in ['comms_campaign_manager']
        ):
            return general_error_response(
                {'message': 'You do not have permission to perform this action.'}
            )
        try:
            campaign = StreamlinedCommunicationCampaign.objects.get(pk=campaign_id)
            serializer = StreamlinedCommunicationCampaignDetailSerializer(campaign)
            return success_response(data=serializer.data)
        except StreamlinedCommunicationCampaign.DoesNotExist:
            return general_error_response({"message": "Campaign not found"})


class UserDetailsView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        roles_list = user.groups.all().values_list('name', flat=True)
        user_details = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'roles_list': roles_list,
        }
        return success_response(data=user_details)


class CommunicationServiceOutboundCallView(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = (AllowAny,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = VoiceCallbackResultSerializer

    def post(self, request):
        """
        Vonage-based callback from communication-service

        While this appears almost identical to VoiceCallResultView, it is intended to be separated
        due to scope concerns.
        """
        data = request.data
        if not data:
            return general_error_response(data={'message': 'failure'}, message="No data sent")

        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        logger.info({"action": "CommunicationServiceOutboundCallView.post", "data": data})

        update_voice_call_record.delay(data)

        return success_response(data={"message": 'success'})


class PTPCardView(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        user = request.user
        if not user:
            return unauthorized_error_response('Authentication not provided')

        customer = getattr(user, 'customer', None)
        app_version = request.META.get('HTTP_X_APP_VERSION')

        response = {
            'is_showing': False,
        }
        if not (customer and app_version):
            return success_response(data=response)

        application = determine_main_application_infocard(customer)
        if not application:
            return success_response(data=response)

        if not (application and application.account):
            return success_response(data=response)

        if not is_show_new_ptp_card(app_version):
            return success_response(data=response)

        if get_ongoing_account_deletion_request(customer):
            return success_response(data=response)

        eligible, already_have_ptp, _, _ = is_eligible_for_in_app_ptp(application.account)
        if not (eligible and not already_have_ptp):
            return success_response(data=response)

        ptp_card = StreamlinedCommunication.objects.filter(
            communication_platform=CommunicationPlatform.INFO_CARD,
            extra_conditions=CardProperty.INAPP_PTP_BEFORE_SET_V2,
            is_active=True,
        ).last()

        if not (ptp_card and ptp_card.message and ptp_card.message.info_card_property):
            return general_error_response('PTP card content or property is missing')

        message = ptp_card.message
        card_property = message.info_card_property
        response.update(
            {
                'is_showing': True,
                'title': {
                    'colour': card_property.title_color,
                    'text': card_property.title,
                },
                'content': {
                    'colour': card_property.text_color,
                    'text': message.message_content,
                },
                'image_icn': None,
            }
        )

        icon = Image.objects.filter(image_source=card_property.id).last()
        if icon:
            response['image_icn'] = get_oss_public_url(settings.OSS_PUBLIC_ASSETS_BUCKET, icon.url)

        return success_response(data=response)
