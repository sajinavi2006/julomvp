from __future__ import division

import codecs
import collections
from builtins import str
from builtins import range

from django.contrib.admin.options import get_content_type_for_model
from django.contrib.admin.utils import unquote
from django.contrib.postgres.forms import JSONField as JSONFormField
from django.core.exceptions import PermissionDenied
from django.forms.models import ModelFormMetaclass
from django.http import Http404
from django.template.response import TemplateResponse
from django.utils.text import capfirst
from django.utils import timezone
from datetime import datetime as DateTimeModule

from faker.utils.datetime_safe import strftime
from past.utils import old_div
from builtins import object
import logging
import time
import datetime
import os
import json
import re
import ast

from copy import copy
import csv

from rest_framework import serializers
from django.contrib.postgres.fields import JSONField
from django.db import transaction
from django.forms.utils import flatatt
from django.shortcuts import render, redirect
from django.conf.urls import url
from django.utils.encoding import force_text
from django.utils.functional import cached_property
from django.utils.html import format_html, escape
from django.utils.translation import ugettext_lazy as _
from django.contrib import admin
from django.contrib.admin import AdminSite
from django.contrib.admin import ModelAdmin
from django.contrib.admin import BooleanFieldListFilter
from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib import messages
from django.contrib.postgres.forms import SimpleArrayField
from django.core.urlresolvers import reverse
from django.utils.safestring import mark_safe
from django.utils.http import urlquote
from django.conf import settings
from django.db.models import Q, Count
from rest_framework.exceptions import ValidationError
from juloserver.julo.widget import TimePickerInput

from juloserver.julo.clients import get_julo_pn_client, get_s3_url

from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from juloserver.julocore.python2.utils import py2round
from juloserver.julocore.constants import RedisWhiteList

from juloserver.julo.models import (
    AddressGeolocation,
    ProductProfile,
    RedisWhiteListUploadHistory,
    ReminderEmailSetting,
    SkiptraceResultChoice,
    SiteMapJuloWeb,
    Agent,
    Application,
    ApplicationHistory,
    ApplicationNote,
    Banner,
    BannerGroup,
    BannerSetting,
    DataCheck,
    Decision,
    Device,
    DeviceScrapedData,
    DeviceIpHistory,
    Document,
    FacebookData,
    FacebookDataHistory,
    Image,
    Loan,
    Offer,
    OriginalPassword,
    Payment,
    PaymentExperiment,
    PaymentNote,
    ProductLookup,
    RobocallTemplate,
    StatusLookup,
    ChangeReason,
    ThirdPartyData,
    Customer,
    Transaction,
    DeviceGeolocation,
    VoiceRecord,
    PartnerReportEmail,
    MobileOperator,
    SepulsaProduct,
    SphpTemplate,
    WarningUrl,
    CreditScore,
    StatusLabel,
    ReferralCampaign,
    ReferralSystem,
    CreditMatrix,
    CreditMatrixProductLine,
    CreditMatrixRepeat,
    Partner,
    PartnerLoan,
    PartnerReferral,
    PartnerTransaction,
    PartnerTransactionItem,
    PartnerAddress,
    PartnerAccountAttribution,
    PartnerAccountAttributionSetting,
    PartnerBankAccount,
    AppVersionHistory,
    PaymentMethod,
    ScrapingButton,
    AppVersion,
    CustomerAppAction,
    Workflow,
    WorkflowStatusNode,
    WorkflowStatusPath,
    WorkflowFailureAction,
    LoanPurpose,
    ProductLine,
    MobileFeatureSetting,
    Experiment,
    ExperimentAction,
    ExperimentSetting,
    ExperimentTestGroup,
    ApplicationExperiment,
    FeatureSetting,
    FaqSubTitle,
    FaqItem,
    FaqSection,
    FaqCheckout,
    JuloContactDetail,
    PaybackTransaction,
    CreditScoreExperiment,
    PaybackTransactionStatusHistory,
    FrontendView,
    EmailSetting,
    PartnerEmailSetting,
    JuloCustomerEmailSetting,
    DigisignConfiguration,
    DigisignConfigurationHistory,
    NotificationTemplate,
    PartnerOriginationData,
    FaceRecognition,
    BlacklistCustomer,
    HighScoreFullBypass,
    ITIConfiguration,
    MarginOfError,
    FDCInquiryCheck,
    GlobalPaymentMethod,
    PartnerSignatureMode,
    PartnerSignatureModeHistory,
    Onboarding,
    MasterAgreementTemplate,
    Bank,
    FraudHotspot,
    SuspiciousDomain,
    HelpCenterItem,
    HelpCenterSection,
    FormAlertMessageConfig,
    FaqFeature,
)
from juloserver.payment_point.models import TransactionMethod
from juloserver.paylater.models import BukalapakInterest, InitialCreditLimit
from juloserver.cootek.models import CootekConfiguration, CootekRobot, CootekControlGroup
from juloserver.cootek.utils import add_minutes_to_datetime
from juloserver.julo.services import (process_received_payment, change_cycle_day, disable_original_password,
                                      enable_original_password)


from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.fdc.admins import FdcTimeoutSettingForm

from juloserver.julo.utils import (have_pn_device, display_rupiah, display_IDR, upload_file_to_oss,
                                   generate_temporary_password, generate_product_name)
from juloserver.julo.views import (workflow_diagram, notification_template_add, notification_template_update,
                                   notification_template_send, email_autocomplete)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.payment_methods import SecondaryMethodName

from juloserver.julo.workflows2.failure_action_tasks import failure_post_action_recall_task
from juloserver.julo.serializers import (
    FraudHotspotSerializer,
    SuspiciousDomainSerializer,
)
from juloserver.julo.admin2.recipients_backup_password_admin import RecipientsBackupPasswordForm
from juloserver.julo.admin2 import (
    FraudHighRiskAsnTowerCheckForm,
    SelfieGeohashCrmImageLimitForm,
)
from juloserver.julo.admin2.feature_setting_monnai_fraud_score import MonnaiFraudScoreForm
from juloserver.julo.admin2.feature_setting_trust_decision_admin import TrustDecisionForm
# dont remove called by eval(action_name) from DB
from .workflows2.tasks import update_status_apps_flyer_task, send_sms_status_change_131_task
from .workflows2.tasks import send_email_status_change_task, process_documents_verified_action_task
from .workflows2.tasks import send_sms_status_change_task
from .workflows2.tasks import reminder_push_notif_application_status_105
from juloserver.payback.status import PaybackTransStatus

from juloserver.apiv2.models import PdCreditModelResult

from django.template import RequestContext, loader
from django.forms import widgets
from juloserver.portal.core import functions

from juloserver.julo.constants import ExperimentConst, FeatureNameConst, MobileFeatureNameConst, InAppPTPDPD
from juloserver.loan.constants import LoanFeatureNameConst, LoanJuloOneConstant

from juloserver.cootek.constants import (
    CriteriaChoices,
    DpdConditionChoices,
    CootekProductLineCodeName,
    JuloGoldFilter,
)

from juloserver.julo.admin2.special_event_binary_admin import (
    SpecialEventBinaryForm,
    save_form_special_event_binary,
)
from juloserver.application_flow.admins.high_score_full_bypass_admin import (
    HighScoreFullBypassForm,
    save_form_hsfb,
)
from juloserver.account.models import (
    Account,
    AccountLimit,
    CurrentCreditMatrix,
)

from juloserver.account.constants import TransactionType
from juloserver.api_token.constants import EXPIRY_SETTING_KEYWORD
from juloserver.julo.admin2.job_data_constants import JOB_INDUSTRY_LIST, JOB_DESC_LIST
from juloserver.julo.admin2.job_data_constants import JOB_MAPPING, JOB_TYPE, PROVINCE, ACTION
from juloserver.autodebet.constants import (
    TutorialAutodebetConst,
    FeatureNameConst as AutodebetFeatureNameConst,
)
from juloserver.cashback.constants import CashbackExpiredConst
from juloserver.collops_qa_automation.constant import SendingRecordingConfig
from juloserver.followthemoney.models import LenderCurrent
from juloserver.grab.models import (
    GrabFeatureSetting,
    GrabProgramFeatureSetting,
    GrabProgramInterest,
)
from juloserver.minisquad.models import SentToDialer
from juloserver.sales_ops.services.sales_ops_services import save_setting
from juloserver.sales_ops.utils import get_list_int_by_str
from juloserver.personal_data_verification.constants import DUKCAPIL_METHODS
from juloserver.personal_data_verification.constants import FeatureNameConst as DukcapilFeatureNameConst
from juloserver.julo.forms import PartnerExtendForm, SepulsaProductForm
from juloserver.julo.admin2.config_flow_to_limit_jstarter_admin import ConfigFlowToLimitJstarterForm, save_model_config_jstarter
from juloserver.julo.admin2.message_jstarter_second_check import SettingMessageJStarterForm, save_model_setup_message_jstarter
from juloserver.application_flow.models import MycroftThreshold
from juloserver.grab.constants import FeatureSettingParameters, GrabFeatureNameConst
from juloserver.minisquad.constants import FeatureNameConst as MiniSquadFeatureSettingConst
from juloserver.minisquad.constants import (
    IntelixTeam,
    DialerTaskType,
    ExperimentConst as MinisquadExperimentConst,
)
from juloserver.julo.admin2.config_sphinx_no_bpjs import (
    ConfigurationFormSphinxNoBpjs,
    save_model_sphinx_no_bpjs,
)
from juloserver.utilities.paginator import (
    FixPaginator,
)
from juloserver.julo.admin2.specific_user_for_jstarter import (
    ConfigSpecificUserForJstarter,
    save_model_config_specific_jstarter,
)
from juloserver.payback.client import get_gopay_client
from juloserver.payback.models import GopayAutodebetTransaction
from juloserver.monitors.notifications import send_slack_bot_message
from juloserver.julo.admin2.config_sphinx_no_bpjs import (
    ConfigurationFormSphinxNoBpjs,
    save_model_sphinx_no_bpjs,
)
from juloserver.autodebet.tasks import send_pn_autodebet_payment_method_disabled, \
    change_benefit_value
from juloserver.payback.tasks import update_subscription
from juloserver.payback.constants import GopayTransactionStatusConst
from juloserver.moengage.constants import MoengageEventType
from juloserver.autodebet.tasks import send_pn_autodebet_payment_method_disabled

from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
)
from juloserver.autodebet.constants import (
    VendorConst,
)
from juloserver.channeling_loan.utils import (
    convert_str_as_list_of_int,
    ChannelingLoanAdminHelper,
)
from juloserver.channeling_loan.forms import ChannelingLoanAdminForm, CreditScoreConversionAdminForm
from juloserver.julo.forms import PartnerExtendForm
from juloserver.fraud_security.models import FraudHighRiskAsn
from juloserver.fraud_security.serializers import FraudHighRiskAsnSerializer
from juloserver.loan.admin import MarketingLoanPrizeChanceSettingForm
from juloserver.loan.admin import DelayDisbursementSetting, DelayDisbursementAdminForm
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.dana_linking.tasks import send_dana_payment_disable_slack_notification
from juloserver.customer_module.admin import CustomerDataChangeRequestSettingAdminForm
from juloserver.autodebet.constants import FeatureNameConst as FeatureNameConstAutodebet
from juloserver.autodebet.services.mandiri_services import (
    get_channel_name_slack_autodebet_mandiri_deduction,
)
from juloserver.account_payment.models import LateFeeRule
from juloserver.account_payment.constants import FeatureNameConst as AccountPaymentFeatureNameConst
from juloserver.julo.admin2.feature_setting_ktp_ocr_threshold_value import KTPThresholdValueForm
from juloserver.julo.payment_methods import active_payment_method_name_list
from juloserver.julo.admin2.feature_setting_idfy_video_call_hours import IDFyVideoCallHoursForm
from juloserver.account.tasks import late_fee_rule_creation
from juloserver.julo.admin2.cross_os_login_form import CrossOSLoginForm
from juloserver.julo.clients import get_julo_sentry_client

SITE_NAME = admin.site.name
SUPERVISOR_SITE_NAME = 'supervisoradmin'
CUSTOMER_SERVICE_SITE_NAME = 'csadmin'
sentry_client = get_julo_sentry_client()

logger = logging.getLogger(__name__)


class PrettyJSONWidget(widgets.Textarea):
    def render(self, name, value, attrs=None):
        if value is None:
            value = ''

        try:
            value = json.dumps(json.loads(value), indent=2, sort_keys=True)
            # these lines will try to adjust size of TextArea to fit to content
            row_lengths = [len(r) for r in value.split('\n')]
            self.attrs['rows'] = min(max(len(row_lengths) + 2, 10), 30)
            self.attrs['cols'] = min(max(max(row_lengths) + 2, 40), 120)
        except json.JSONDecodeError:
            self.attrs['rows'] = 30
            self.attrs['cols'] = 120

        final_attrs = self.build_attrs(attrs, name=name)
        return format_html('<textarea{}>\r\n{}</textarea>',
                           flatatt(final_attrs),
                           force_text(value))


class CustomPrettyJSONWidget(PrettyJSONWidget):
    def render(self, name, value, attrs=None):
        try:
            result = super().render(name, value, attrs)
        except json.decoder.JSONDecodeError:
            return super(PrettyJSONWidget, self).render(name, value, attrs)

        return result


class LateFeeRulePrettyJSONWidget(widgets.Textarea):
    def render(self, name, value, attrs=None):
        if value is None:
            value = ''

        try:
            value = json.dumps(json.loads(value), indent=2)
            # these lines will try to adjust size of TextArea to fit to content
            row_lengths = [len(r) for r in value.split('\n')]
            self.attrs['rows'] = min(max(len(row_lengths) + 2, 10), 30)
            self.attrs['cols'] = min(max(max(row_lengths) + 2, 40), 120)
        except json.JSONDecodeError:
            self.attrs['rows'] = 30
            self.attrs['cols'] = 120

        final_attrs = self.build_attrs(attrs, name=name)
        return format_html('<textarea{}>\r\n{}</textarea>',
                           flatatt(final_attrs),
                           force_text(value))


class ImportCsvForm(forms.Form):
    csv_file = forms.FileField()


class JuloModelAdmin(ModelAdmin):
    actions_on_bottom = True

    empty_value_display = '-empty-'

    save_on_top = True

    import_csv_form = ImportCsvForm
    import_csv_data_table = {
        'property', ('column_name',),
        'data', ('Text',),
    }
    import_csv_serializer = None


    def change_form_link(self, target_model, target_model_name, label=None):
        target_link = reverse(
            self.admin_site.name + ":julo_%s_change" % target_model_name,
            args=[target_model.id])
        if label:
            target_model = label
        return mark_safe(
            '<a href="{}">{}</a>'.format(target_link, target_model))

    def change_list_link(self, obj, obj_name, target_model_name, label=None):
        target_link = reverse(
            self.admin_site.name + ":julo_%s_changelist" % target_model_name)
        if label:
            link_label = label
        else:
            link_label = " ".join([target_model_name, "entries"])
        return mark_safe(
            '<a href="{}?{}={}">{}</a>'.format(
                target_link, obj_name, obj.id, link_label)
        )

    def import_csv(self, request):
        if request.method != 'POST':
            form = self.import_csv_form()
            payload = {
                'data_table': self.import_csv_data_table,
                'form': form
            }
            return render(
                request, 'custom_admin/upload_config_form.html', payload
            )

        csv_file = request.FILES['csv_file']
        if not csv_file:
            self.message_user(request, 'Fail to read csv file', level='error')
            return redirect('..')

        csv_data = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'), delimiter=',')
        try:
            with transaction.atomic():
                serializer = self.import_csv_serializer(data=list(csv_data), many=True)
                if serializer.is_valid(raise_exception=True):
                    serializer.save()
        except Exception as e:
            self.message_user(
                request,
                'Fail to import due to error in one or more row: {}'.format(e),
                level='error'
            )
            return redirect('..')

        self.message_user(request, 'Your csv file has been imported.')
        return redirect('..')


class ReadonlyJuloModelAdmin(JuloModelAdmin):

    def has_add_permission(self, request):
        # Nobody is allowed to add
        return False

    def has_delete_permission(self, request, obj=None):
        # Nobody is allowed to delete
        return False


class AdminActionCompleted(object):
    def __init__(self, model_admin, request, model_name, success_message=None):
        self.entries = []
        self.model_admin = model_admin
        self.request = request
        self.model_name = model_name
        self.success_message = success_message

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_value:
            logger.error("something bad happened")
            return

        if len(self.entries) == 0:
            message = "No %s was processed." % self.model_name,
            self.model_admin.message_user(
                self.request, message, level=messages.INFO)
            return

        if len(self.entries) == 1:
            message_bit = '1 %s entry' % self.model_name
        else:
            message_bit = '%s %s entries' % (len(self.entries), self.model_name)

        if self.success_message:
            message = "%s for %s." % (self.success_message, message_bit)
        else:
            message = "Action completed for %s." % message_bit
        self.model_admin.message_user(
            self.request, message, level=messages.SUCCESS)


class ApplicationStatusCodeFilter(admin.SimpleListFilter):
    title = _('status code')
    parameter_name = 'status'

    code_agent_mappings = [
        (StatusLookup.FORM_SUBMITTED_CODE, "Data Verifier"),
        (StatusLookup.DOCUMENTS_SUBMITTED_CODE, "Data Verifier"),
        (ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL, "Data Verifier"),
        (ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL, "Credit Analyst"),
        (StatusLookup.APPLICATION_RESUBMISSION_REQUESTED_CODE, "Data Verifier"),
        (StatusLookup.APPLICATION_DENIED_CODE, "Data Verifier, Credit Analyst, Outbound Caller"),
        (StatusLookup.OFFER_MADE_TO_CUSTOMER_CODE, "Credit Analyst"),
        (StatusLookup.OFFER_ACCEPTED_BY_CUSTOMER_CODE, "Outbound Caller"),
        (StatusLookup.ACTIVATION_CALL_SUCCESSFUL_CODE, "Outbound Caller"),
        (StatusLookup.LEGAL_AGREEMENT_SIGNED_CODE, "Finance"),
    ]

    def lookups(self, request, model_admin):

        lookup_list = []
        for code, agent in ApplicationStatusCodeFilter.code_agent_mappings:
            status_lookup = StatusLookup.objects.get(status_code=code)
            label = "%s %s (for %s)" % (code, status_lookup.status, agent)
            logger.debug([code, agent])
            lookup_list.append((str(code), _(label)))
        return lookup_list

    def queryset(self, request, queryset):
        if self.value() is not None:
            return queryset.filter(
                application_status__status_code=int(self.value()))


class ApplicationAdmin(JuloModelAdmin):
    list_display = (
        'email',
        'application_id',
        'cdate',
        'udate',
        'status_history_link',
        'fullname',
        'dob',
        'mobile_phone_1',
        'offers_link',
        'loan_link',
        'payment_link',
        'customer_link',
        'image_link',
        'voice_link',
        'notes_link',
        'geolocation_link',
        'scraped_data_link',
        'facebook_link'
    )

    list_filter = (ApplicationStatusCodeFilter,)
    list_display_links = None
    ordering = ('id', 'cdate',)
    list_select_related = (
        'addressgeolocation',
        'application_status',
        'customer',
        'note',
    )

    readonly_fields = ('customer', 'device',)

    actions = (
        'send_for_review',
        'send_for_underwriting',
        'show_offers',
        'accept_default_offer',
        'show_legal_document'
    )

    def application_submitter(self, obj):
        return obj.customer.user.username

    application_submitter.short_description = "Submitter"

    def email(self, obj):
        return obj.email

    email.short_description = 'Email'

    def application_id(self, obj):
        return self.change_form_link(obj, 'application')

    application_id.short_description = 'Application ID'

    application_id.admin_order_field = 'id'

    def cdate(self, obj):
        return obj.application_cdate

    cdate.short_description = 'Creation Date'

    def status(self, obj):
        return obj.application_status.status

    def status_history_link(self, obj):
        label = obj.application_status.status_code
        return self.change_list_link(
            obj, 'application', 'applicationhistory', label=label)

    status_history_link.short_description = 'Status'

    def application_status_code(self, obj):
        return obj.application_status.status_code

    application_status_code.short_description = 'application status code'

    def fullname(self, obj):
        return obj.fullname

    fullname.short_description = 'Full Name'

    def dob(self, obj):
        return obj.dob

    dob.short_description = 'date of birth'

    def mobile_phone_1(self, obj):
        return obj.mobile_phone_1

    search_fields = [
        '^email',
        '^fullname',
        '^id',
        '^mobile_phone_1'
    ]

    def customer_link(self, obj):
        return self.change_form_link(obj.customer, 'customer')

    customer_link.short_description = 'Customer'

    def image_link(self, obj):

        url = reverse('admin:julo_image_changelist')
        return '<a href="{0}?image_source={1}">Images</a>'.format(url, urlquote(obj.id))

    image_link.allow_tags = True
    image_link.short_description = 'Images'

    def voice_link(self, obj):

        return self.change_list_link(obj, 'application', 'voicerecord', label="Voices")

    voice_link.short_description = 'Voices'
    voice_link.admin_order_field = 'id'

    def geolocation_link(self, obj):
        """
        Old code in case we want this link to go to the AddressGeoLocation Object,
        not to google maps URL.

            return self.change_form_link(obj.addressgeolocation, 'addressgeolocation')

        geolocation_link.short_description = 'Geolocation'
        geolocation_link.allow_tags = False
        """

        url = obj.addressgeolocation
        return '<a href={}>Google Maps</a>'.format(url)

    geolocation_link.short_description = 'Geolocation'
    geolocation_link.allow_tags = True

    def facebook_link(self, obj):

        url = reverse('admin:julo_facebookdata_change', args=[obj.facebook_data.id])
        return '<a href="{0}">Facebook Data</a>'.format(url)

    facebook_link.allow_tags = True
    facebook_link.short_description = 'Facebook'

    def notes_link(self, obj):
        return self.change_list_link(
            obj, 'application', 'applicationnote', label="Notes")

    notes_link.short_description = 'Application Note'

    def device_link(self, obj):
        return self.change_form_link(obj.device, 'device')

    device_link.short_description = 'Device'

    def offers_link(self, obj):
        return self.change_list_link(obj, 'application', 'offer', label="Offers")

    offers_link.short_description = 'Offers'
    offers_link.admin_order_field = 'id'

    def loan_link(self, obj):
        return self.change_list_link(obj, 'application', 'loan', label="Loans")

    loan_link.short_description = 'Loans'

    def scraped_data_link(self, obj):
        return self.change_list_link(
            obj, 'application', 'devicescrapeddata', label="SD")

    scraped_data_link.short_description = 'SD'

    def payment_link(self, obj):
        """
        The url construction below allows filtering list lookups to the specific application.

        NOTE: The URL below will only work if I declare PaymentAdmin.lookup_allowed
        """

        url = reverse('admin:julo_payment_changelist')
        return '<a href="{0}?loan__application__id={1}">Payments</a>'.format(url, obj.id)

    payment_link.allow_tags = True
    payment_link.short_description = 'Payments'

    def send_for_review(self, request, queryset):

        submitted_applications = list(queryset.submitted())

        application_count = 0
        for application in submitted_applications:
            application.mark_documents_submitted()
            application_count += 1

        self.message_user(request, "Mark documents submitted", level=messages.SUCCESS)

    send_for_review.short_description = (
        "Mark documents submitted and ready for review (to be automated)"
    )

    def send_for_underwriting(self, request, queryset):

        applications_ready_for_underwriting = []

        documents_submitted_applications = list(queryset.documents_submitted())
        applications_ready_for_underwriting += documents_submitted_applications

        # NOTE: To accommodate applications in which documents are being
        # resubmitted via emails and verified by agents manually. Here,
        # the applications are being marked as resubmitted automatically.
        resubmitted_applications = []
        for application in list(queryset.resubmission_requested()):
            application.change_status(
                StatusLookup.APPLICATION_RESUBMITTED_CODE)
            application.save()
            resubmitted_applications.append(application)
        applications_ready_for_underwriting += resubmitted_applications

        # with AdminActionCompleted(
        #         self, request, "application",
        #         success_message="Mark verified and sent for decision"
        # ) as completed:

        # for application in applications_ready_for_underwriting:
        #     decided = create_offers(application)
        #     if decided:
        #         completed.entries.append(application)

    send_for_underwriting.short_description = (
        "1. Mark verified and send for decision"
    )

    def show_offers(self, request, queryset):

        verified_applications = list(
            queryset.verified().select_related('customer', 'device'))

        # with AdminActionCompleted(
        #         self, request, "application", success_message="Offers shown"
        # ) as completed:

        # for application in verified_applications:
        #     shown = show_offers(application)
        #     if shown:
        #         completed.entries.append(application)

    show_offers.short_description = "2a. Show offers and notify customer"

    def accept_default_offer(self, request, queryset):

        verified_applications = list(
            queryset.verified().select_related('customer', 'device'))

        # with AdminActionCompleted(
        #         self, request, "application", success_message="Offer no. 1 accepted"
        # ) as completed:

        # for application in verified_applications:
        #     accepted = accept_default_offer(application)
        #     if accepted:
        #         completed.entries.append(application)

    accept_default_offer.short_description = "2b. Accept default offer"

    def show_legal_document(self, request, queryset):

        ready_applications = list(
            queryset.verification_call_successful().select_related('customer', 'device'))

        # with AdminActionCompleted(
        #         self, request, "application",
        #         success_message="Legal document shown"
        # ) as completed:

        # for application in ready_applications:
        #     shown = show_legal_document(application)
        #     if shown:
        #         completed.entries.append(application)

    show_legal_document.short_description = \
        "4. Show legal document and notify customer"


class ApplicationHistoryAdmin(JuloModelAdmin):
    list_display = (
        'application',
        'status_old',
        'status_new',
        'change_reason',
        'changer',
        'changed_on'
    )

    def changer(self, obj):
        # NOTE: this is a workaround as the django-cuser lib cannot capture
        # current API user.
        return obj.changed_by if obj.changed_by is not None else "API"

    def changed_on(self, obj):
        return obj.cdate


class BankForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(BankForm, self).__init__(*args, **kwargs)

    class Meta(object):
        model = Bank
        fields = ('is_active',)


class BankAdmin(JuloModelAdmin):
    form = BankForm
    list_display = (
        'bank_name',
        'bank_code',
        'cdate',
        'udate',
        'is_active',
    )

    actions_on_bottom = True
    save_on_top = False

    def save_model(self, request, obj, form, change):
        obj.save()

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class DeviceAdmin(JuloModelAdmin):
    list_display = (
        'short_gcm_reg_id', 'android_id', 'imei', 'customer_link',
        'applications_link'
    )

    search_fields = [
        'customer__fullname', 'customer__user__email', '^gcm_reg_id', '^imei'
    ]

    readonly_fields = (
        'customer',
    )

    def short_gcm_reg_id(self, obj):
        return "%s..." % obj.gcm_reg_id[:10]

    short_gcm_reg_id.short_description = "short GCM REG ID"

    def customer_link(self, obj):
        return self.change_form_link(obj.customer, 'customer')

    customer_link.short_description = 'Customer'

    def applications_link(self, obj):
        return self.change_list_link(obj, 'device', 'application')

    applications_link.short_description = 'application'


class DeviceScrapedDataAdmin(JuloModelAdmin):
    list_display = (
        'cdate',
        'id',
        'application_link',
        'url',
        'file_type',
        'download_link',
        'reports_link'
    )

    search_fields = (
        '^id',
        '^url',
        '^application__id',
        '^application__email',
    )

    list_filter = ('file_type',)

    readonly_fields = (
        'application',
    )

    def application_link(self, obj):
        return self.change_form_link(obj.application, 'application')

    application_link.short_description = 'Application'

    def download_link(self, obj):
        url = get_s3_url(obj.s3_bucket, obj.s3_object_path(obj.url))
        if url == '':
            return None
        return '<a href="%s">%s</a>' % (url, 'Download Link')

    download_link.allow_tags = True

    def reports_link(self, obj):
        url = get_s3_url(
            obj.reports_s3_bucket, obj.s3_object_path(obj.reports_url))
        if url == '':
            return None
        return '<a href="%s">%s</a>' % (url, 'Reports Link')

    reports_link.allow_tags = True


class DeviceIpHistoryAdmin(JuloModelAdmin):
    list_display = (
        'ip_address', 'cdate', 'customer', 'device'
    )


class FacebookDataAdmin(JuloModelAdmin):
    list_display = (
        'facebook_id',
        'application',
        'friend_count',
        'open_date',
    )

    search_fields = [
        '^customer__email'
    ]


class GeoLocationAdmin(JuloModelAdmin):
    list_display = (
        'email', 'applications_link', 'geolocation',
    )

    def email(self, obj):
        return obj.application.email

    email.short_description = "email"

    def applications_link(self, obj):
        return self.change_form_link(obj.application, 'application')

    applications_link.short_description = "application_id"

    def geolocation(self, obj):
        url = obj
        return '<a href={}>Google Maps</a>'.format(url)

    geolocation.short_description = "Geolocation URL"
    geolocation.allow_tags = True


class ImageAdmin(JuloModelAdmin):
    list_display = (
        'image_id',
        'image_source_id',
        'image_type',
        'image_url',
    )

    def image_id(self, obj):
        return obj.id

    def image_url(self, obj):
        url = get_s3_url(obj.s3_bucket, obj.s3_object_path)
        if url == '':
            return None
        return '<a href="%s">%s</a>' % (url, 'link to image')

    image_url.allow_tags = True

    image_url.short_description = 'image_url'

    def image_source_id(self, obj):
        return obj.image_source

    image_source_id.short_description = "image source"

    def image_type(self, obj):
        return obj.image.image_type

    image_type.short_description = 'image type'


class VoiceAdmin(JuloModelAdmin):
    list_display = (
        'voice_id',
        'voice_source_id',
        'voice_url'
    )

    def voice_id(self, obj):
        return obj.id

    voice_id.short_description = 'Voice id'

    def voice_source_id(self, obj):
        return obj.application_id

    voice_source_id.short_description = 'Voice Source'

    def voice_url(self, obj):
        url = get_s3_url(obj.s3_bucket, obj.url)
        if url == '':
            return None
        return '<a href="%s">%s</a>' % (url, 'link to voice')

    voice_url.allow_tags = True

    voice_url.short_description = 'Voice Url'


class StatusLookupAdmin(JuloModelAdmin):
    list_display = ('status_code', 'status', 'change_reason_link')

    def change_reason_link(self, obj):
        target_link = reverse(
            self.admin_site.name + ":julo_%s_changelist" % 'changereason')
        link_label = 'change reason entries'
        return mark_safe(
            '<a href="{}?{}={}">{}</a>'.format(
                target_link, 'status__status_code__exact', obj.status_code, link_label)
        )

    ordering = ('status_code',)


class ChangeReasonAdmin(JuloModelAdmin):
    list_display = ('status', 'reason')
    list_filter = ('status',)


class OfferAdmin(JuloModelAdmin):
    list_display_links = None

    list_display = (
        'email', 'application_link', 'offer_id', 'offer_name', 'offer_number',
        'is_accepted', 'loan_amount_formatted', 'loan_duration_offer',
        'installment_amount_formatted', 'offer_accepted_ts',
    )

    ordering = ('application_id', 'id', 'offer_number')

    list_filter = (('is_accepted', BooleanFieldListFilter),)

    search_fields = [
        '^application__email',
        '^application__fullname',
        '^application__id',
        '^application__mobile_phone_1'
    ]

    def email(self, obj):
        return obj.application.email

    email.short_description = 'Email'

    def application_link(self, obj):
        return self.change_form_link(obj.application, 'application')

    application_link.short_description = 'Application id'
    application_link.admin_order_field = 'id'

    def offer_id(self, obj):
        return obj.id

    offer_id.short_description = 'Offer ID'
    offer_id.admin_order_field = 'id'

    def offer_name(self, obj):
        return self.change_form_link(obj, 'offer')

    offer_name.short_description = "Offer name"

    def offer_number(self, obj):
        return obj.offer_number

    offer_number.short_description = 'Offer Number'

    def loan_amount_formatted(self, obj):
        return display_rupiah(obj.loan_amount_offer)

    loan_amount_formatted.short_description = 'Loan Amount'

    def loan_duration_offer(self, obj):
        return obj.loan_duration_offer

    loan_duration_offer.short_description = 'Loan Duration'

    def installment_amount_formatted(self, obj):
        return display_rupiah(obj.installment_amount_offer)

    installment_amount_formatted.short_description = ' Installment Amount'

    def application_submitter(self, obj):
        return obj.application.customer.user.username

    application_submitter.short_description = "submitter"

    def name(self, obj):
        return str(obj)

    application_link.admin_order_field = 'application_id'
    offer_id.admin_order_field = 'id'


class DecisionAdmin(JuloModelAdmin):
    list_display = (
        'interest_rate', 'max_monthly_pmt', 'application_submitter')

    list_filter = (
        ('is_non_fraud', BooleanFieldListFilter),
        ('is_able_to_pay', BooleanFieldListFilter),
        ('is_willing_to_pay', BooleanFieldListFilter),
        ('is_approved', BooleanFieldListFilter),
    )

    def application_submitter(self, obj):
        return obj.application.customer.user.username

    application_submitter.short_description = "submitter"


class CustomerAdmin(JuloModelAdmin):
    list_display = (
        'email', 'devices_link', 'applications_link', 'loans_link',
        'device_ip_history_link', 'auth_user_link', 'token'
    )

    readonly_fields = (
        'user', 'appsflyer_device_id', 'advertising_id'
    )

    list_filter = (
        'can_reapply', 'is_email_verified', 'is_phone_verified', 'is_review_submitted'
    )

    search_fields = [
        '^email', '^user__username', '^user__first_name', '^user__last_name'
    ]

    actions = (
        'generate_temporary_password',
        'disable_temporary_password'
    )

    def token(self, obj):
        return obj.user.auth_expiry_token

    def devices_link(self, obj):
        return self.change_list_link(
            obj, 'customer', 'device', label="Devices")

    devices_link.short_description = 'Devices'

    def applications_link(self, obj):
        return self.change_list_link(
            obj, 'customer', 'application', label="Applications")

    applications_link.short_description = 'Applications'

    def loans_link(self, obj):
        return self.change_list_link(
            obj, 'customer', 'loan', label="Loans")

    loans_link.short_description = 'Loans'

    def auth_user_link(self, obj):
        return mark_safe(
            '<a href="{}">{}</a>'.format(
                reverse(SITE_NAME + ":auth_user_change", args=[obj.user.id]),
                obj.user.username)
        )

    auth_user_link.short_description = 'auth user'

    def device_ip_history_link(self, obj):
        return self.change_list_link(
            obj, 'customer', 'deviceiphistory', label="Device IP History")

    device_ip_history_link.short_description = 'Device IP History'

    def generate_temporary_password(self, request, queryset):
        customers = list(queryset.all())
        if len(customers) == 1:
            for customer in customers:
                temporary_password = generate_temporary_password()
                disable_original_password(customer, temporary_password)
            self.message_user(request,
                              "successfully ENABLED temporary password = " + temporary_password)
        else:
            self.message_user(request, "Please choose only for 1 customer..")

    generate_temporary_password.short_description = "Enable temporary password"

    def disable_temporary_password(self, request, queryset):
        customers = list(queryset.all())
        if len(customers) == 1:
            for customer in customers:
                enable_original_password(customer)

            self.message_user(request, "successfully DISABLED temporary password.")
        else:
            self.message_user(request, "Please choose only for 1 customer..")

    disable_temporary_password.short_description = "Disable temporary password"


class LoanAdmin(JuloModelAdmin):
    list_display_links = None

    list_display = (
        'email',
        'application_link',
        'loan_id',
        'loan_status_code',
        'status',
        'loan_amount_formatted',
        'loan_duration',
        'installment_amount_formatted',
        'cashback_earned_formatted',
        'payments_link',
        'payment_methods_link'
    )

    readonly_fields = (
        'agent_2',
        'agent_3',
        'application',
        'application_xid',
        'customer',
        'offer',
        'product',
    )

    search_fields = [
        '^application__email',
        '^application__fullname',
        '^application__id',
        '^application__mobile_phone_1'
    ]

    actions = ('start_loan', 'change_cycle_day',)

    def status(self, obj):
        return obj.loan_status.status

    status.short_description = "Status"

    def email(self, obj):
        return obj.application.email

    email.short_description = 'Email'

    def loan_id(self, obj):
        return self.change_form_link(obj, 'loan')

    loan_id.short_description = 'Loan ID'

    def application_link(self, obj):
        return self.change_form_link(obj.application, 'application')

    application_link.short_description = 'application_ID'

    def loan_status_code(self, obj):
        return obj.loan_status.status_code

    loan_status_code.short_description = 'loan status code'

    def loan_amount_formatted(self, obj):
        return display_rupiah(obj.loan_amount)

    loan_amount_formatted.short_description = 'loan amount'

    def loan_duration(self, obj):
        return obj.loan_duration_offer

    loan_duration.short_description = 'loan duration offer'

    def installment_amount_formatted(self, obj):
        return display_rupiah(obj.installment_amount)

    installment_amount_formatted.short_description = 'installment amount'

    def cashback_earned_formatted(self, obj):
        if obj.cashback_earned_total is not None:
            return display_rupiah(obj.cashback_earned_total)

    cashback_earned_formatted.short_description = 'cashback earned'

    def customer_link(self, obj):
        return mark_safe(
            '<a href="{}">{}</a>'.format(
                reverse(
                    SITE_NAME + ':julo_customer_change',
                    args=[obj.customer.id]),
                obj.customer
            )
        )

    customer_link.short_description = "Customer"

    def offer_link(self, obj):
        return mark_safe(
            '<a href="{}">{}</a>'.format(
                reverse(
                    SITE_NAME + ':julo_offer_change',
                    args=[obj.offer.id]),
                obj.offer
            )
        )

    def payments_link(self, obj):
        return mark_safe(
            '<a href="{}?loan={}">Payments</a>'.format(
                reverse(SITE_NAME + ":julo_payment_changelist"), obj.id)
        )

    payments_link.short_description = "Link to Payment"

    def start_loan(self, request, queryset):

        ready_to_start_loans = list(
            queryset.inactive().application_signed().select_related(
                'application__device')
        )

        # with AdminActionCompleted(
        #         self, request, "loan", success_message="Loan started"
        # ) as completed:

        # for loan in ready_to_start_loans:
        #     started = start_loan(loan.application)
        #     if started:
        #         completed.entries.append(loan)

    def change_cycle_day(self, request, queryset):

        loans = list(queryset.all_loan())

        with AdminActionCompleted(
                self, request, "loan", success_message="Cycle day changed"
        ) as completed:

            for loan in loans:
                changed = change_cycle_day(loan)
                if changed:
                    completed.entries.append(loan)

    change_cycle_day.short_description = "Change cycle day"

    def payment_methods_link(self, obj):
        return mark_safe(
            '<a href="{}?loan={}">Payment Methods</a>'.format(
                reverse(SITE_NAME + ":julo_paymentmethod_changelist"), obj.id)
        )

    payments_link.short_description = "Payment methods"


class ApplicationNoteAdmin(JuloModelAdmin):
    list_display = ('note_text', 'added_by')


class PaymentDueDateFilter(admin.SimpleListFilter):
    title = _('due_date code')
    parameter_name = 'due_date'

    def lookups(self, request, model_admin):
        due_pass_date_code = [
            (6, 'T >= -5'),
            (5, 'T-5'),
            (4, 'T-4'),
            (3, 'T-3'),
            (2, 'T-2'),
            (1, 'T-1'),
            (0, 'T 0'),
            (-1, 'T > 0')
        ]
        lookup_list = due_pass_date_code
        return lookup_list

    def queryset(self, request, queryset):
        if self.value() is not None:
            value = int(self.value())
            if value == 6:
                return queryset.dpd_groups()
            if 0 <= value < 6:
                return queryset.due_soon(due_in_days=value)
            if value < 0:
                return queryset.overdue()


class PaymentAdmin(JuloModelAdmin):
    list_display = (
        'email', 'loan_link', 'loan_status_code', 'payment_id', 'payment_number', 'dpd',
        'status', 'payment_status_code', 'due_date', 'due_amount_formatted',
        'late_fee_amount_formatted', 'cash_back_earned_formatted', 'notes_link',
    )

    list_filter = (PaymentDueDateFilter,)

    list_display_links = None

    search_fields = [
        '^loan__application__email',
        '^loan__application__fullname',
        '^loan__application__id',
        '^loan__application__mobile_phone_1'
    ]

    def lookup_allowed(self, key, value):
        # This permits a filtered url lookup on a specific key from the
        # ApplicationAdmin page
        return True

    actions = (
        'inform_payment_received',
        'remind_payment_due_soon'
    )

    def status(self, obj):
        return obj.payment_status.status

    status.short_description = "Status"

    def email(self, obj):
        return obj.loan.customer.email

    email.short_description = 'email'

    def payment_id(self, obj):
        return self.change_form_link(obj, "payment")

    payment_id.admin_order_field = 'id'

    def payment_number(self, obj):
        return obj.payment_number

    payment_number.short_description = 'Payment Number'

    def payment_status_code(self, obj):
        return obj.payment_status.status_code

    payment_status_code.short_description = 'Payment Status Code'

    def due_amount_formatted(self, obj):
        return display_rupiah(obj.due_amount)

    due_amount_formatted.short_description = 'Due Amount'

    def late_fee_amount_formatted(self, obj):
        if obj.late_fee_amount is not None:
            return display_rupiah(obj.late_fee_amount)

    late_fee_amount_formatted.short_description = 'late fee amount'

    def cash_back_earned_formatted(self, obj):
        if obj.cashback_earned is not None:
            return display_rupiah(obj.cashback_earned)

    cash_back_earned_formatted.short_description = 'cash back earned'

    def loan_link(self, obj):
        return mark_safe(
            '<a href="{}">{}</a>'.format(
                reverse(
                    SITE_NAME + ':julo_loan_change',
                    args=[obj.loan.id]),
                obj.loan
            )
        )

    loan_link.short_description = "Loan ID"
    loan_link.admin_order_field = 'id'

    def loan_status_code(self, obj):
        return obj.loan.status

    loan_status_code.short_description = "loan status code"

    def customer_link(self, obj):
        """2nd-degree indirect relation"""
        return mark_safe(
            '<a href="{}">{}</a>'.format(
                reverse(
                    SITE_NAME + ':julo_customer_change',
                    args=[obj.loan.customer.id]),
                obj.loan.customer
            )
        )

    customer_link.short_description = "Customer"

    def inform_payment_received(self, request, queryset):

        not_paid_payments = list(
            queryset.not_paid_active() \
                # block notify to ICare client
                .filter(loan__application__customer__can_notify=True) \
                .select_related('loan__application__device') \
            )

        with AdminActionCompleted(
                self, request, "payment", success_message="Mark as paid"
        ) as completed:

            for payment in not_paid_payments:
                processed = process_received_payment(payment)
                if processed:
                    if have_pn_device(payment.loan.application.device):
                        julo_pn_client = get_julo_pn_client()
                        julo_pn_client.inform_payment_received(
                            payment.loan.application.device.gcm_reg_id,
                            payment.payment_number, payment.loan.application.id,
                            payment.loan.application.product_line_code,
                            payment.payment_status_id)
                    completed.entries.append(payment)

    inform_payment_received.short_description = (
        "Mark payment received and notify customer"
    )

    def remind_payment_due_soon(self, request, queryset):
        due_soon_payments = list(
            queryset.due_soon() \
                # block notify to ICare client
                .filter(loan__application__customer__can_notify=True) \
                .select_related('loan__application__device')
        )
        payment_count = 0
        for payment in due_soon_payments:
            if have_pn_device(payment.loan.application.device):
                julo_pn_client = get_julo_pn_client()
                julo_pn_client.inform_payment_due_soon(payment)
            payment_count += 1

        if payment_count == 0:
            self.message_user(
                request, "No payment was processed.", level=messages.INFO)
            return

        if payment_count == 1:
            message_bit = '1 payment'
        else:
            message_bit = '%s payments' % payment_count
        message = "Notify customer payment due soon for %s." % message_bit
        self.message_user(request, message, level=messages.SUCCESS)

    remind_payment_due_soon.short_description = (
        "Notify customer payment due soon (to be auto dispatched)"
    )

    def dpd(self, obj):
        if obj.due_date is None or obj.loan.status == StatusLookup.INACTIVE_CODE:
            return '-'
        return obj.due_late_days

    dpd.admin_order_field = 'due_date'

    def notes_link(self, obj):
        return self.change_list_link(obj, 'payment', 'paymentnote', label="Notes")

    notes_link.short_description = 'Notes'


class ProductLookupAdmin(JuloModelAdmin):
    list_display = (
        'product_name', 'product_line', 'interest_rate', 'montly_interest_rate',
        'origination_fee_pct', 'late_fee_pct', 'cashback_initial_pct', 'cashback_payment_pct'
    )

    list_filter = ('product_line',)

    def montly_interest_rate(self, obj):
        months_in_year = 12
        return old_div(obj.interest_rate, months_in_year)


class PartnerAdmin(JuloModelAdmin):
    form = PartnerExtendForm

    list_display = (
        'name', 'email', 'phone', 'token', 'systrace'
    )

    readonly_fields = ("preview_image",)

    def get_form(self, request, obj=None, *args, **kwargs):
        form = super(PartnerAdmin, self).get_form(request, *args, **kwargs)
        form.base_fields['name_bank_validation'].widget = forms.HiddenInput(
            attrs={'readonly': 'readonly'})
        form.base_fields['user'].widget = forms.HiddenInput(
            attrs={'readonly': 'readonly'})
        form.base_fields['user'].required = False
        form.base_fields['type'].choices = ((None, '---------'),
                                            ('referrer', 'referrer'),
                                            ('receiver', 'receiver'),)

        return form

    def save_model(self, request, obj, form, change):
        super(PartnerAdmin, self).save_model(request, obj, form, change)
        if request.FILES and request.FILES['logo']:
            logo = request.FILES['logo']
            _, file_extension = os.path.splitext(logo.name)

            remote_path = 'partner_{}/logo{}'.format(obj.pk, file_extension)

            image = Image()
            image.image_source = obj.pk
            image.image_type = 'partner_logo'
            image.url = remote_path
            image.save()

            file = functions.upload_handle_media(logo, "partner/logo")
            if file:
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    file['file_name'],
                    remote_path
                )

    def preview_image(self, obj):
        return mark_safe('<img src="{url}" width="{width}" />'.format(
            url=obj.logo,
            width=300
        )
        )


class PartnerReferralAdmin(JuloModelAdmin):
    list_display = (
        'id', 'customer', 'partner', 'cust_email', 'partner_account_id',
        'kyc_indicator', 'is_android_user', 'pre_exist'
    )

    list_filter = ('partner',)

    search_fields = [
        'id',
        '^cust_email',
        'partner_account_id',
    ]

    readonly_fields = (
        'customer',
        'partner',
    )


class AgentAdmin(JuloModelAdmin):
    list_display = (
        'auth_user_link', 'user_extension_link'
    )

    def auth_user_link(self, obj):
        return mark_safe(
            '<a href="{}">{}</a>'.format(
                reverse(SITE_NAME + ":auth_user_change", args=[obj.user.id]),
                obj.user.username)
        )

    auth_user_link.short_description = 'auth user'

    def user_extension_link(self, obj):
        return self.change_form_link(obj, 'agent')

    user_extension_link.short_description = 'user extension'


class PartnerLoanAdmin(JuloModelAdmin):
    list_display = (
        'application', 'partner', 'approval_status'
    )

    list_filter = ('application', 'partner')

    search_fields = [
        '^partner_loan__application__email',
        '^partner_loan__partner',
    ]

    readonly_fields = (
        'application',
        'partner',
    )


class PaymentMethodAdmin(JuloModelAdmin):
    list_display = (
        'payment_method_name',
        'virtual_account',
        'fullname',
        'email',
        'customer_link',
        'application_link',
        'loan_link',
        'is_shown'
    )
    search_fields = (
        'customer__id',
        'customer__fullname',
        'customer__email',
        'loan__application__fullname',
        'loan__application__id',
        'loan__id',
        'payment_method_code',
        'bank_code',
        'virtual_account',
        'payment_method_name',
    )

    list_filter = ('is_shown',)

    readonly_fields = (
        'payment_method_name',
        'virtual_account',
        'loan',
        'payment_method_code',
        'bank_code'
    )

    def customer_link(self, obj):
        try:
            return self.change_form_link(
                obj.customer, "customer", obj.customer.id)
        except Exception as e:
            return None

    def application_link(self, obj):
        try:
            return self.change_form_link(
                obj.loan.application, "application", obj.loan.application.id)
        except Exception as e:
            return None

    def loan_link(self, obj):
        try:
            return self.change_form_link(obj.loan, "loan", obj.loan.id)
        except Exception as e:
            return None

    def fullname(self, obj):
        try:
            return obj.customer.fullname or obj.loan.application.fullname
        except Exception as e:
            return None

    def email(self, obj):
        try:
            return obj.customer.email
        except Exception as e:
            return None


class ScrapingButtonAdmin(JuloModelAdmin):
    list_display = (
        'name', 'type', 'is_shown'
    )

    list_filter = ('is_shown',)


class AppVersionAdmin(JuloModelAdmin):
    list_display = (
        'app_version_id',
        'app_version',
        'status'
    )

    def app_version_id(self, obj):
        return obj.id

    def app_version(self, obj):
        return obj.app_version

    def status(self, obj):
        return obj.status

    def get_actions(self, request):
        actions = super(AppVersionAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        latest_app_version = AppVersion.objects.latest_version()
        if not latest_app_version:
            return super(AppVersionAdmin, self).save_model(request, obj, form, change)

        if obj.is_latest():
            # Make sure we switch the previous latest app_version to "supported"
            if latest_app_version.id != obj.id:
                latest_app_version.status = 'supported'
                latest_app_version.save(update_fields=['status'])

            return super(AppVersionAdmin, self).save_model(request, obj, form, change)

        # Prevent saving app_version that is latest
        if latest_app_version.id == obj.id and obj.status != latest_app_version.status:
            return

        return super(AppVersionAdmin, self).save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        latest_app_version = AppVersion.objects.latest_version()
        # Prevent to delete the latest version
        if latest_app_version and latest_app_version.id == obj.id:
            return

        return super(AppVersionAdmin, self).delete_model(request, obj)

    def mark_deprecated(self, request, queryset):
        latest_app_version = AppVersion.objects.latest_version()
        queryset.exclude(id=latest_app_version.id).update(status='deprecated')

    mark_deprecated.short_description = "Mark app version as deprecated"

    def mark_not_supported(self, request, queryset):
        latest_app_version = AppVersion.objects.latest_version()
        queryset.exclude(id=latest_app_version.id).update(status='not_supported')

    mark_not_supported.short_description = "Mark app version as not supported"

    def mark_supported(self, request, queryset):
        latest_app_version = AppVersion.objects.latest_version()
        queryset.exclude(id=latest_app_version.id).update(status='supported')

    mark_supported.short_description = "Mark app version as supported"

    def custom_delete_selected(self, request, queryset):
        latest_app_version = AppVersion.objects.latest_version()
        queryset.exclude(id=latest_app_version.id).delete()

    custom_delete_selected.short_description = "Delete selected app versions"

    actions = [custom_delete_selected, mark_deprecated, mark_not_supported, mark_supported]


class CustomerAppActionAdmin(JuloModelAdmin):
    list_display = (
        'action_id',
        'customer_link',
        'action',
        'is_completed'
    )
    search_fields = ['customer__id', 'customer__email', 'customer__nik']

    def action_id(self, obj):
        return obj.id

    def customer_link(self, obj):
        return self.change_form_link(obj.customer, 'customer')

    customer_link.short_description = 'Customer'

    def action(self, obj):
        return obj.action

    def is_completed(self, obj):
        return obj.is_completed


class PartnerReportEmailAdmin(JuloModelAdmin):
    list_display = (
        'partner_name',
        'email_subject',
        'email_content',
        'email_recipients',
        'is_active'
    )
    search_fields = ['partner__id', 'partner__name']

    def partner_name(self, obj):
        return obj.partner.name


class WorkflowStatusPathAdmin(JuloModelAdmin):
    list_display = (
        'workflow',
        'status_previous',
        'status_next',
        'type',
        'customer_accessible',
        'agent_accessible',
        'is_active',
    )

    search_fields = ('status_previous', 'status_next',)
    list_filter = ('is_active', 'customer_accessible', 'agent_accessible', 'type',)


class WorkflowStatusNodeAdmin(JuloModelAdmin):
    list_display = (
        'workflow',
        'status_node',
        'handler',
    )


class WorkflowAdmin(JuloModelAdmin):
    list_display = (
        'name',
        'desc',
        'handler',
        'is_active',
        'status_path_link',
        'status_node_link',
        'flowchart_link',
    )

    def flowchart_link(self, obj):
        return mark_safe('<a href="/xgdfat82892ddn/flowchart/?workflow_id=%s">Visual Diagram</a>' % obj.id)

    def status_path_link(self, obj):
        return self.change_list_link(obj, 'workflow', 'workflowstatuspath', label="Status Paths")

    def status_node_link(self, obj):
        return self.change_list_link(obj, 'workflow', 'workflowstatusnode', label="Status Nodes")


class WorkflowFailureActionAdmin(JuloModelAdmin):
    list_display = (
        'application_id',
        'action_name',
        'action_type',
        'arguments',
        'task_id',
        'error_message',
        'recalled_counter',
        'is_recalled_succeed',
    )

    actions = (
        'recall_on_background',
    )

    def recall_on_background(self, request, queryset):
        async_actions = queryset.filter(action_type='async')
        post_actions = queryset.filter(action_type='post')
        for async_action in async_actions:
            if async_action.is_recalled_succeed is not True:
                args = list([int(x) if x.isdigit() else x for x in async_action.arguments])
                args.append({'failure_action': True, 'id': async_action.id})
                eval(async_action.action_name).delay(*args)

        for post_action in post_actions:
            if async_action.is_recalled_succeed is not True:
                failure_post_action_recall_task.delay(
                    post_action.application.id,
                    {'failure_action': True, 'id': post_action.id})

    recall_on_background.short_description = "Re run selected failure action on the background"


class OperatorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return "{} : {}".format(obj.id, obj.name)


class SepulsaProductAdminFeeFilter(admin.SimpleListFilter):
    title = _('Admin Fee')
    parameter_name = 'admin_fee'

    def lookups(self, request, model_admin):
        due_pass_date_code = [
            (0, 'empty'),
            (1, 'not_empty'),
        ]
        lookup_list = due_pass_date_code
        return lookup_list

    def queryset(self, request, queryset):
        if self.value() is not None:
            value = int(self.value())
            if value == 0:
                return queryset.filter(admin_fee__isnull=True)
            if value == 1:
                return queryset.filter(admin_fee__isnull=False)


class SepulsaProductServiceFeeFilter(admin.SimpleListFilter):
    title = _('Service Fee')
    parameter_name = 'service_fee'

    def lookups(self, request, model_admin):
        due_pass_date_code = [
            (0, 'empty'),
            (1, 'not_empty'),
        ]
        lookup_list = due_pass_date_code
        return lookup_list

    def queryset(self, request, queryset):
        if self.value() is not None:
            value = int(self.value())
            if value == 0:
                return queryset.filter(service_fee__isnull=True)
            if value == 1:
                return queryset.filter(service_fee__isnull=False)


class SepulsaProductCollectionFeeFilter(admin.SimpleListFilter):
    title = _('Collection Fee')
    parameter_name = 'collection_fee'

    def lookups(self, request, model_admin):
        due_pass_date_code = [
            (0, 'empty'),
            (1, 'not_empty'),
        ]
        lookup_list = due_pass_date_code
        return lookup_list

    def queryset(self, request, queryset):
        if self.value() is not None:
            value = int(self.value())
            if value == 0:
                return queryset.filter(collection_fee__isnull=True)
            if value == 1:
                return queryset.filter(collection_fee__isnull=False)


class SepulsaProductPartnerPriceFilter(admin.SimpleListFilter):
    title = _('Partner Price')
    parameter_name = 'partner_price'

    def lookups(self, request, model_admin):
        due_pass_date_code = [
            (0, 'empty'),
            (1, 'not_empty'),
        ]
        lookup_list = due_pass_date_code
        return lookup_list

    def queryset(self, request, queryset):
        if self.value() is not None:
            value = int(self.value())
            if value == 0:
                return queryset.filter(partner_price__isnull=True)
            if value == 1:
                return queryset.filter(partner_price__isnull=False)


class SepulsaProductAdmin(JuloModelAdmin):
    list_display = (
        'product_id',
        'product_name',
        'operator_name',
        'category',
        'partner_price',
        'customer_price',
        'customer_price_regular',
        'admin_fee',
        'collection_fee',
        'service_fee',
        'is_active',
        'is_not_blocked',
    )
    readonly_fields = ()
    search_fields = ('product_name',)
    list_filter = ('category', 'operator__name', SepulsaProductPartnerPriceFilter,
                   SepulsaProductAdminFeeFilter, SepulsaProductCollectionFeeFilter,
                   SepulsaProductServiceFeeFilter, 'type')
    ordering = ('product_id',)
    form = SepulsaProductForm

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'operator':
            return OperatorChoiceField(queryset=MobileOperator.objects.all())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def operator_name(self, obj):
        if obj.operator:
            return obj.operator.name
        else:
            return '-'

    operator_name.short_description = 'Operator name'


class MobileOperatorAdmin(JuloModelAdmin):
    list_display = (
        'id',
        'name',
        'initial_numbers',
        'is_active',
    )
    readonly_fields = ('id',)
    search_fields = ('name',)
    list_filter = ('is_active',)
    ordering = ('id',)


class LoanPurposeInline(admin.TabularInline):
    model = ProductLine.loan_purposes.through


class ProductLineAdmin(JuloModelAdmin):
    inlines = (
        LoanPurposeInline,
    )


class LoanPurposeAdmin(JuloModelAdmin):
    list_display = ('purpose', 'version')
    readonly_fields = ('version',)


class ExperimentAdmin(JuloModelAdmin):
    list_display = (
        'id', 'code', 'name', 'is_active', 'status_old', 'status_new',
        'date_start', 'date_end'
    )


class ExperimentActionAdmin(JuloModelAdmin):
    list_display = ('id', 'type', 'value', 'experiment')


class ExperimentTestGroupAdmin(JuloModelAdmin):
    list_display = ('id', 'type', 'value', 'experiment')


class PartnerReferralChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.id


class PartnerAccountAttributionAdmin(JuloModelAdmin):
    list_display = (
        'id', 'partner_account_id', 'partner', 'v_customer_id', 'v_application_id', 'v_partner_referral_id'
    )
    readonly_fields = ('application', 'customer', 'partner')
    list_filter = ('partner',)
    search_fields = ('id', 'application__id', 'partner_referral__id', 'partner_account_id', 'customer__id')
    ordering = ('id',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'partner_referral':
            return PartnerReferralChoiceField(queryset=PartnerReferral.objects.all().order_by('-id'))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def v_customer_id(self, obj):
        if obj.customer:
            return obj.customer.id
        else:
            return '-'

    v_customer_id.short_description = 'Customer Id'

    def v_application_id(self, obj):
        if obj.application:
            return obj.application.id
        else:
            return '-'

    v_application_id.short_description = 'Application Id'

    def v_partner_referral_id(self, obj):
        if obj.partner_referral:
            return obj.partner_referral.id
        else:
            return '-'

    v_partner_referral_id.short_description = 'Partner Referral Id'


class PartnerAccountAttributionSettingAdmin(JuloModelAdmin):
    list_display = (
        'partner',
    )
    ordering = ('partner__name',)


class BannerExtendForm(forms.ModelForm):
    image = forms.ImageField(required=False)

    dpd_payment_choices = [(i, i) for i in range(-30, 32, 1)]
    dpd_payment_choices.append(('All', 'All'))

    month_choices = [(1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
                     (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'), (9, 'September'), (10, 'October'),
                     (11, 'November'), (12, 'December'), ('All', 'All')]

    choices = []
    for x in range(1, 366, 7):
        if x == 365:
            new_list = ">= {}".format(x)
        else:
            new_list = "{}-{}".format(x, x + 6)

        choices.append((x, new_list))
    choices.append(('All', 'All'))

    due_date_payemnt_choices = [(x, x) for x in range(1, 32)]
    due_date_payemnt_choices.append(('All', 'All'))

    app_version = forms.ChoiceField(required=False,
                                    widget=forms.Select(attrs={'class': 'banner-setting-control'}),
                                    label="Minimum app. version (in.)"
                                    )
    credit_score = forms.MultipleChoiceField(required=False,
                                             widget=forms.SelectMultiple(attrs={'class': 'banner-setting-control'})
                                             )
    product = forms.MultipleChoiceField(required=False,
                                        widget=forms.SelectMultiple(attrs={'class': 'banner-setting-control'})
                                        )
    partner = forms.MultipleChoiceField(required=False,
                                        widget=forms.SelectMultiple(attrs={'class': 'banner-setting-control'})
                                        )
    application_status = forms.MultipleChoiceField(required=False,
                                                   widget=forms.SelectMultiple(
                                                       attrs={'class': 'banner-setting-control'})
                                                   )
    loan_status = forms.MultipleChoiceField(required=False,
                                            widget=forms.SelectMultiple(attrs={'class': 'banner-setting-control'})
                                            )
    due_date_payment = forms.MultipleChoiceField(required=False,
                                                 widget=forms.SelectMultiple(attrs={
                                                     'class': 'banner-setting-control',
                                                     'onchange': 'enable_due_date_month()'}),
                                                 choices=due_date_payemnt_choices
                                                 )
    due_date_month = forms.MultipleChoiceField(required=False,
                                               widget=forms.SelectMultiple(attrs={'class': 'banner-setting-control'})
                                               , choices=month_choices
                                               )
    payment_status = forms.MultipleChoiceField(required=False,
                                               widget=forms.SelectMultiple(attrs={'class': 'banner-setting-control'})
                                               )
    dpd_loan = forms.MultipleChoiceField(required=False,
                                         widget=forms.SelectMultiple(attrs={
                                             'class': 'banner-setting-control'}),
                                         choices=choices
                                         )
    dpd_payment = forms.MultipleChoiceField(required=False,
                                            widget=forms.SelectMultiple(attrs={
                                                'class': 'banner-setting-control'}),
                                            choices=dpd_payment_choices
                                            )
    can_reapply = forms.MultipleChoiceField(required=False,
                                            widget=forms.SelectMultiple(attrs={
                                                'class': 'banner-setting-control can_apply',
                                                'onchange': 'show_true_false()', }),
                                            choices=[(None, ''), (True, True), (False, False)]
                                            )

    def __init__(self, *args, **kwargs):
        super(BannerExtendForm, self).__init__(*args, **kwargs)


class BannerAdmin(JuloModelAdmin):
    list_display = (
        'id',
        'name',
        'banner_type',
        'is_active',
        'start_date',
        'end_date',
        'is_permanent',
        'display_order'
    )
    readonly_fields = ('id',)
    search_fields = ('name',)
    list_filter = ('banner_type',)
    ordering = ('id',)
    add_form_template = "custom_admin/banner.html"
    change_form_template = "custom_admin/banner.html"
    readonly_fields = ("preview_image",)

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = BannerExtendForm
        form = super(BannerAdmin, self).get_form(request, *args, **kwargs)

        selected_all = (('All', 'All'),)

        app_versions = tuple(
            AppVersion.objects.filter(
                status__in=('supported', 'latest',)
            ).order_by('-id').values_list('app_version', 'app_version'))

        credit_score = tuple(CreditMatrix.objects.order_by('score').values_list('score', 'score').distinct())
        undefined_score = (('--', '--'),)

        product_line = tuple(ProductLine.objects.values_list('product_line_code', 'product_line_type'))

        application_status_combined = tuple(
            StatusLookup.objects.filter(status_code__startswith=1).values_list('status_code', 'status_code'))

        loan_status_combined = tuple(
            StatusLookup.objects.filter(status_code__startswith=2).values_list('status_code', 'status_code'))

        payment_status_combined = tuple(
            StatusLookup.objects.filter(status_code__startswith=3).values_list('status_code', 'status_code'))

        form.base_fields['app_version'].choices = selected_all + app_versions
        form.base_fields['credit_score'].choices = credit_score + undefined_score + selected_all
        form.base_fields['product'].choices = product_line + selected_all
        form.base_fields['partner'].choices = tuple(Partner.objects.values_list('id', 'name')) + selected_all
        form.base_fields['application_status'].choices = application_status_combined + selected_all
        form.base_fields['loan_status'].choices = loan_status_combined + selected_all
        form.base_fields['payment_status'].choices = payment_status_combined + selected_all

        if obj:
            types = ["app_version", "credit_score", "product", "partner", "application_status", "loan_status",
                     "due_date_payment", "payment_status", "dpd_loan", "dpd_payment",
                     "due_date_month", "can_reapply"]

            for key in types:
                existing_data = obj.get_setting(key)
                if key == "app_version" and len(existing_data) > 0:
                    existing_data = existing_data[0]
                form.base_fields[key].initial = existing_data

        return form

    def save_model(self, request, obj, form, change):
        super(BannerAdmin, self).save_model(request, obj, form, change)

        types = {
            "app_version": 'AppVersion',
            "credit_score": 'CreditMatrix',
            "product": 'ProductLine',
            "partner": 'Partner',
            "application_status": 'StatusLookup',
            "loan_status": 'StatusLookup',
            "due_date_payment": 'Payment',
            "payment_status": 'StatusLookup',
            "dpd_loan": 'Loan',
            "dpd_payment": 'Payment',
            "due_date_month": 'due_date_month',
            "can_reapply": 'can_reapply'
        }

        obj.bannersetting_set.all().delete()
        for key, model in list(types.items()):
            if request.POST.getlist(key):
                for reference_id in request.POST.getlist(key):
                    banner_setting = BannerSetting()
                    banner_setting.reference_model = model
                    banner_setting.reference_type = key
                    banner_setting.reference_id = str(reference_id)
                    banner_setting.banner_id = obj.pk
                    banner_setting.save()

        if request.FILES and request.FILES['image']:
            banner_image = request.FILES['image']
            _, file_extension = os.path.splitext(banner_image.name)

            remote_path = 'banner_{}/image{}'.format(obj.pk, file_extension)

            image = Image()
            image.image_source = obj.pk
            image.image_type = 'banner_image'
            image.url = remote_path
            image.save()

            file = functions.upload_handle_media(banner_image, "banner/image")
            if file:
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    file['file_name'],
                    remote_path
                )

    def preview_image(self, obj):
        return mark_safe('<img src="{url}" width="{width}" />'.format(
            url=obj.image_url,
            width=300
        )
        )

    def get_queryset(self, request):
        qs = super(BannerAdmin, self).get_queryset(request)
        return qs.filter(is_deleted=False)


class BannerGroupAdmin(JuloModelAdmin):
    list_display = (
        'id',
        'v_banner',
        'v_partner',
        'v_product_line',
        'status',
    )
    readonly_fields = ('id',)
    search_fields = ('partner',)
    list_filter = ('status',)
    ordering = ('id',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'banner':
            return OperatorChoiceField(queryset=Banner.objects.all())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def v_banner(self, obj):
        return obj.banner.name

    v_banner.short_description = 'Banner Name'

    def v_partner(self, obj):
        if obj.partner:
            partners = ', '.join(obj.partner)
            return partners
        else:
            return '-'

    v_partner.short_description = 'Partner'

    def v_product_line(self, obj):
        if obj.product_line:
            partners = ', '.join(str(e) for e in obj.product_line)
            return partners
        else:
            return '-'

    v_product_line.short_description = 'Product Line'


class MobileFeatureSettingExtendForm(forms.ModelForm):
    title = forms.CharField()
    content = forms.CharField(widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super(MobileFeatureSettingExtendForm, self).__init__(*args, **kwargs)


class MobileFeatureSettingWithCustomParameters(forms.ModelForm):
    custom_parameters = forms.CharField(widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super(MobileFeatureSettingWithCustomParameters, self).__init__(*args, **kwargs)


class MobileFeatureSettingAdmin(JuloModelAdmin):
    formfield_overrides = {
        JSONField: {'widget': PrettyJSONWidget}
    }

    list_display = (
        'feature_name',
        'is_active',
        'parameters',
    )
    readonly_fields = ('feature_name',)

    def get_actions(self, request):
        # Disable delete
        actions = super(MobileFeatureSettingAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def save_model(self, request, obj, form, change):
        if obj.feature_name.lower() in [payment_method.lower() for payment_method in SecondaryMethodName]:
            PaymentMethod.objects.filter(payment_method_name__iexact=obj.feature_name, is_shown=not obj.is_active) \
                .update(is_shown=obj.is_active)
            messages.success(request, 'Success update payment method')

        elif obj.feature_name == "concurrency_message":
            obj.parameters = dict(
                title=request.POST['title'],
                content=request.POST['content'],
            )
        elif obj.feature_name == MobileFeatureNameConst.PRE_LONG_FORM_GUIDANCE_POP_UP:
            custom_parameters = ast.literal_eval(request.POST['custom_parameters'])
            obj.parameters['message'] = custom_parameters['message']
            obj.parameters['title'] = custom_parameters['title']
        elif obj.feature_name == MobileFeatureNameConst.JSTARTER_REJECTION_PAGE_MESSAGE:
            messages.get_messages(request)
            parameters = obj.parameters
            if not parameters or parameters == "" or not isinstance(parameters, dict):
                error_message = "Error: The 'parameters' field must be a non-empty dictionary."
                messages.set_level(request, messages.ERROR)
                messages.error(request, error_message)
                return
            required_parameters = ["offer_j1_first_check", "reject_first_check", "offer_j1_second_check",
                                   "reject_second_check"]
            missing_parameters = [param for param in required_parameters if param not in parameters]
            if missing_parameters:
                error_message = "Error: The 'parameters' field is missing the following required parameters: {}.".format(
                    ", ".join(missing_parameters)
                )
                messages.set_level(request, messages.ERROR)
                messages.error(request, error_message)
                return
            for param_name in required_parameters:
                param = parameters.get(param_name, {})
                if not isinstance(param, dict):
                    error_message = "Error: The '{}' parameter must be a dictionary.".format(param_name)
                    messages.set_level(request, messages.ERROR)
                    messages.error(request, error_message)
                    return
                if not all(key in param for key in ["title", "body", "image", "button"]):
                    error_message = "Error: The '{}' parameter must have 'title', 'body', 'image', and 'button' fields.".format(
                        param_name)
                    messages.set_level(request, messages.ERROR)
                    messages.error(request, error_message)
                    return
                title = param["title"]
                body = param["body"]
                image = param["image"]
                button = param["button"]
                if len(title) < 10 or len(title) > 80:
                    error_message = "Error: The 'title' field in '{}' parameter must have between 10 and 80 characters.".format(
                        param_name
                    )
                    messages.set_level(request, messages.ERROR)
                    messages.error(request, error_message)
                    return
                if len(body) < 10 or len(body) > 150:
                    error_message = "Error: The 'body' field in '{}' parameter must have between 10 and 150 characters.".format(
                        param_name
                    )
                    messages.set_level(request, messages.ERROR)
                    messages.error(request, error_message)
                    return
                if len(button) < 10 or len(button) > 35:
                    error_message = "Error: The 'button' field in '{}' parameter must have between 10 and 35 characters.".format(
                        param_name
                    )
                    messages.set_level(request, messages.ERROR)
                    messages.error(request, error_message)
                    return
                if image == "":
                    error_message = "Error: The 'image' field in '{}' parameter cannot be empty.".format(
                        param_name
                    )
                    messages.set_level(request, messages.ERROR)
                    messages.error(request, error_message)
                    return
            if not obj.is_active:
                error_message = "Error: The 'is_active' field of jstarter_rejection_page_message cannot be inactivated."
                messages.set_level(request, messages.ERROR)
                messages.error(request, error_message)
                return
        elif obj.feature_name == LoanJuloOneConstant.PRODUCT_LOCK_FEATURE_SETTING:
            # Validate app_version before saving the model
            app_version_regex = re.compile(r'^\d+\.\d+\.\d+$')
            parameters = obj.parameters  # Assuming `parameters` is a dictionary

            invalid_versions = []

            # Iterate over all entries in the dictionary
            for key, value in parameters.items():
                app_version = value.get("app_version")  # Extract app_version
                if app_version and not bool(app_version_regex.match(app_version)):
                    invalid_versions.append((key, app_version))
            if invalid_versions:
                messages.get_messages(request)
                messages.set_level(request, messages.ERROR)
                # Show an error message and prevent saving
                error_messages = []
                for invalid_version in invalid_versions:
                    error_message = {
                        "error": "Invalid app_version format detected",
                        "expected_format": "X.Y.Z",
                        "received_value": invalid_version[1],
                        "feature": invalid_version[0],
                        "timestamp": strftime(
                            timezone.localtime(timezone.now()), "%Y:%m:%d %H:%M:%S"
                        ),
                    }
                    error_messages.append(error_message)
                messages.error(request, error_messages)
                sentry_client.captureMessage(error_messages)
                return  # Stop saving

        obj.save()

    def get_form(self, request, obj=None, *args, **kwargs):
        if obj and obj.feature_name == "concurrency_message":
            kwargs['form'] = MobileFeatureSettingExtendForm
            self.exclude = ('parameters',)
        elif obj and obj.feature_name == MobileFeatureNameConst.PRE_LONG_FORM_GUIDANCE_POP_UP:
            kwargs['form'] = MobileFeatureSettingWithCustomParameters
            self.exclude = ('parameters',)

        form = super(MobileFeatureSettingAdmin, self).get_form(request, *args, **kwargs)

        if obj and obj.feature_name == "concurrency_message":
            form.base_fields["title"].initial = obj.parameters["title"]
            form.base_fields["content"].initial = obj.parameters["content"]
        elif obj and obj.feature_name == MobileFeatureNameConst.PRE_LONG_FORM_GUIDANCE_POP_UP:
            # removed because minimum_salary should not editable its comes from ana
            custom_parameters = obj.parameters.copy()
            custom_parameters.pop('minimum_salary', None)
            form.base_fields["custom_parameters"].initial = custom_parameters

        return form


class TrafficManagementForm(forms.ModelForm):
    customer_type = forms.CharField(label='Customer Type', widget=forms.Select(choices=[]))
    money_flow = forms.CharField(label='Money Flow', widget=forms.Select(choices=[]))
    probability = forms.IntegerField(
        label='Traffic Flow',
        widget=forms.NumberInput(attrs={'min': '0', 'max': '100', 'class': 'slider',
                                        'step': '5', 'type': 'range'})
    )
    data = forms.CharField(widget=forms.HiddenInput(attrs={'readonly': 'readonly'}))

    customer_type_dict = {
        "bca": "BCA Customer",
        "xfers": "Non-BCA Customer",
    }

    money_flow_dict = {
        "bca": "BCA Direct",
        "xfers": "Old Xfers",
        "new_xfers": "New Xfers",
    }

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(TrafficManagementForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            data = dict(instance.parameters)
            customer_types = [(x, self.customer_type_dict[x]) for x in list(data.keys())]
            initial_type_val = customer_types[0][0]
            self.fields['customer_type'].widget.choices = customer_types
            self.fields['customer_type'].widget.initial = initial_type_val

            money_flows = [(x, self.money_flow_dict[x]) for x in list(data[initial_type_val].keys())]
            initial_flow_val = money_flows[0][0]
            self.fields['money_flow'].widget.choices = money_flows
            self.fields['money_flow'].widget.initial = initial_flow_val
            self.fields['probability'].initial = data[initial_type_val][initial_flow_val]
            data['field'] = self.money_flow_dict
            self.fields['data'].initial = json.dumps(data)

    @cached_property
    def changed_data(self):
        data = []
        for name, field in list(self.fields.items()):
            prefixed_name = self.add_prefix(name)
            data_value = field.widget.value_from_datadict(self.data, self.files, prefixed_name)
            if not field.show_hidden_initial:
                initial_value = self.initial.get(name, field.initial)
                if callable(initial_value):
                    initial_value = initial_value()
            else:
                initial_prefixed_name = self.add_initial_prefix(name)
                hidden_widget = field.hidden_widget()
                try:
                    initial_value = field.to_python(hidden_widget.value_from_datadict(
                        self.data, self.files, initial_prefixed_name))
                except ValidationError:
                    # Always assume data has changed if validation fails.
                    data.append(name)
                    continue

            if name in ['customer_type', 'money_flow', 'probability']:
                if name == 'customer_type':
                    data.append(name + ': %s' % self.customer_type_dict[data_value])
                elif name == 'money_flow':
                    data.append(name + ': %s' % self.money_flow_dict[data_value])
                else:
                    data.append(name + ': %s' % data_value)
        return data


class RepaymentForm(forms.ModelForm):
    form_data = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super(RepaymentForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            data = dict(instance.parameters)
            self.fields['form_data'].initial = json.dumps(data, sort_keys=True)

    class Meta(object):
        fields = ['form_data']


class MinimumAmountTransactionForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    minimum_amount = forms.IntegerField(required=True)
    information = forms.CharField(widget=forms.Textarea)

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(MinimumAmountTransactionForm, self).__init__(*args, **kwargs)
        self.fields['minimum_amount'].help_text = \
            "Minimum transaction has to be {}. Anything less will cause error.".format(
                display_IDR(LoanJuloOneConstant.MIN_lOAN_TRANSFER_AMOUNT)
            )
        self.fields['information'].help_text = \
            "Use '{minimum_amount}' as dynamic value for Minimum_amount field on Android."
        instance = kwargs.get('instance')
        if instance:
            self.fields['minimum_amount'].initial = instance.parameters['limit_transaction']
            self.fields['information'].initial = instance.parameters['information']


class LoanMaxAllowedDurationForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    params = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(LoanMaxAllowedDurationForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            self.fields['params'].initial = json.dumps(
                sorted(instance.parameters, key=lambda i: i['min_amount']))


class AutodebetIDFyEntryPoint(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    form_data = forms.CharField(widget=forms.HiddenInput, required=False)
    image_data = forms.CharField(required=False, widget=forms.HiddenInput)
    image = forms.ImageField(required=False)

    def __init__(self, *args, **kwargs):
        super(AutodebetIDFyEntryPoint, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)

            image = Image.objects.get_or_none(id=data['image_id'])
            if image:
                data['image_url'] = image.image_url

            self.fields['form_data'].initial = json.dumps(data)


class CashbackDrawerEncouragement(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    title = forms.CharField(widget=forms.TextInput, required=False)
    subtitle = forms.CharField(widget=forms.Textarea, required=False)
    cta = forms.CharField(widget=forms.TextInput, required=False)
    dpd = forms.CharField(widget=forms.Textarea, required=False)
    form_data = forms.CharField(widget=forms.HiddenInput, required=False)
    image_data = forms.CharField(required=False, widget=forms.HiddenInput)
    image = forms.ImageField(required=False)

    class Meta(object):
        fields = [
            'is_active',
            'title',
            'subtitle',
            'cta',
            'dpd',
            'image',
        ]

    def __init__(self, *args, **kwargs):
        super(CashbackDrawerEncouragement, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)
            self.fields['title'].initial = data['title']
            self.fields['subtitle'].initial = data['subtitle']
            self.fields['cta'].initial = data['cta']
            self.fields['dpd'].initial = json.dumps(data['dpd'])

            image = Image.objects.get_or_none(id=data['image']['image_id'])
            if image:
                data['image']['image_url'] = image.image_url

            self.fields['form_data'].initial = json.dumps(data)

    def clean(self):
        parameters = self.cleaned_data
        try:
            dpd_list = json.loads(parameters.get('dpd'))
        except Exception as e:
            raise forms.ValidationError('dpd has to be a list: wrapped inside []')

        if not isinstance(dpd_list, list):
            raise forms.ValidationError('dpd has to be a list: wrapped inside []')

        dpd_cleaned = []
        for dpd in dpd_list:
            if not isinstance(dpd, int) or dpd < -10 or dpd > 10:
                raise forms.ValidationError('each dpd has to be an integer ranging from -10 to 10')

            if dpd not in dpd_cleaned:
                dpd_cleaned.append(dpd)
        self.cleaned_data['dpd'] = json.dumps(sorted(dpd_cleaned))

        return self.cleaned_data


class AutodebetIDFyCallButton(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    form_data = forms.CharField(widget=forms.HiddenInput, required=False)
    image_data = forms.CharField(required=False, widget=forms.HiddenInput)
    image = forms.ImageField(required=False)

    def __init__(self, *args, **kwargs):
        super(AutodebetIDFyCallButton, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)

            image = Image.objects.get_or_none(id=data['image_id'])
            if image:
                data['image_url'] = image.image_url

            self.fields['form_data'].initial = json.dumps(data)


class TutorialAutodebetBriForm(forms.ModelForm):
    CONTENT_TYPE_CHOICES = (
        ("image", "Image"),
        ("video", "Video"),
    )

    CTA_TYPE_CHOICES = (
        # ("deeplink", "Deeplink"),
        ("webview", "Webview"),
    )

    BENEFIT_TYPE_CHOICES = (
        ("cashback", "Cashback"),
        ("waive_interest", "Waiver"),
    )

    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    form_data = forms.CharField(widget=forms.HiddenInput, required=False)
    image_data = forms.CharField(required=False, widget=forms.HiddenInput)
    vendor = forms.ChoiceField(
        choices=VendorConst.VENDOR_CHOICES,
        widget=forms.Select(attrs={'class': 'vendor_choices'})
    )

    # REGISTRATION
    registration_content_type = forms.ChoiceField(
        choices=CONTENT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'registration_content_type'})
    )
    registration_image = forms.ImageField(required=False)
    registration_cta_type = forms.ChoiceField(
        choices=CTA_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'registration_cta_type'})
    )
    registration_cta = forms.CharField(required=False)
    registration_video = forms.CharField(required=False)
    registration_subtitle = forms.CharField(required=False)

    # TURN OFF
    revocation_content_type = forms.ChoiceField(
        choices=CONTENT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'revocation_content_type'})
    )
    revocation_image = forms.ImageField(required=False)
    revocation_cta_type = forms.ChoiceField(
        choices=CTA_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'revocation_cta_type'})
    )
    revocation_cta = forms.CharField(required=False)
    revocation_video = forms.CharField(required=False)
    revocation_subtitle = forms.CharField(required=False)

    # BENEFIT
    benefit_type = forms.ChoiceField(
        choices=BENEFIT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'benefit_type'})
    )
    benefit_content_type = forms.ChoiceField(
        choices=CONTENT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'benefit_content_type'})
    )
    benefit_image = forms.ImageField(required=False)
    benefit_cta_type = forms.ChoiceField(
        choices=CTA_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'benefit_cta_type'})
    )
    benefit_cta = forms.CharField(required=False)
    benefit_video = forms.CharField(required=False)
    benefit_subtitle = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super(TutorialAutodebetBriForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)

            for vendor in TutorialAutodebetConst.VENDOR:
                for ad_type in TutorialAutodebetConst.AUTODEBET_TYPES:
                    if ad_type == 'benefit':
                        for benefit_type in TutorialAutodebetConst.BENEFIT_TYPE:
                            image_id = data[vendor][ad_type][benefit_type]['image_data']['id']
                            if image_id:
                                image = Image.objects.get_or_none(id=image_id)
                                if image:
                                    data[vendor][ad_type][benefit_type]['image_data']['type'] = image.image_url

                    else:
                        image_id = data[vendor][ad_type]['image_data']['id']
                        if image_id:
                            image = Image.objects.get_or_none(id=image_id)
                            if image:
                                data[vendor][ad_type]['image_data']['type'] = image.image_url
            self.fields['form_data'].initial = json.dumps(data)


class AutodebetDeductionDayForm(forms.ModelForm):
    DEDUCTION_DAY_CHOICES = (
        ("due_date", "Due date"),
        ("payday", "Payday"),
    )

    is_active = forms.BooleanField(widget=forms.CheckboxInput,
                                   required=False,
                                   help_text='if this setting is OFF, deduction = due_date.'
                                   )
    form_data = forms.CharField(widget=forms.HiddenInput, required=False)
    vendor = forms.ChoiceField(
        choices=VendorConst.VENDOR_CHOICES,
        widget=forms.Select(attrs={'class': 'vendor_choices'})
    )
    deduction_day_type = forms.ChoiceField(
        choices=DEDUCTION_DAY_CHOICES,
        widget=forms.Select(attrs={'class': 'deduction_day_choices'})
    )
    last_update = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super(AutodebetDeductionDayForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)
            self.fields['form_data'].initial = json.dumps(data)


class ZeroInterestHigherProvisionForm(forms.ModelForm):
    """
    Setting form for FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION
    """
    class Meta(object):
        model = FeatureSetting
        fields = ('is_active', 'parameters')
        widgets = {'parameters': forms.HiddenInput()}

    parameter_data = forms.CharField(widget=forms.HiddenInput, required=False)

    condition_min_loan_amount = forms.IntegerField(
        required=False, label="Min loan amount", min_value=0
    )
    condition_max_loan_amount = forms.IntegerField(
        required=False, label="Max loan amount", min_value=0
    )
    condition_min_duration = forms.IntegerField(
        required=False, label="Min loan duration", min_value=1
    )
    condition_max_duration = forms.IntegerField(
        required=False, label="Max loan duration", min_value=1
    )
    condition_list_transaction_method_code = forms.MultipleChoiceField(
        required=False,
        choices=TransactionMethodCode.choices(),
        widget=forms.CheckboxSelectMultiple,
        label="List transaction method"
    )

    whitelist_is_active = forms.BooleanField(required=False, label="Is active")
    whitelist_list_customer_id = forms.CharField(required=False, label="Customer IDs")

    is_experiment_for_last_digit_customer_id_is_even = forms.BooleanField(
        required=False, label="Is experiment for users whose last digit of customer Id is even (only works when Whitelist is inactive)"
    )
    content_title = forms.CharField(required=False, label="Title")
    content_banner_link = forms.CharField(
        required=False,
        label="Banner link",
        widget=forms.Textarea,
    )
    content_description = forms.CharField(
        required=False,
        label="Description",
        widget=forms.Textarea,
    )
    content_webview_link = forms.CharField(
        required=False,
        label="Webview link",
        widget=forms.Textarea,
    )
    campaign_content = JSONFormField(required=True, widget=CustomPrettyJSONWidget)

    customer_segments_is_ftc = forms.BooleanField(required=False, label="Allow FTC Customer")
    customer_segments_is_repeat = forms.BooleanField(required=False, label="Allow Repeat Customer")

    def __init__(self, *args, **kwargs):
        super(ZeroInterestHigherProvisionForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)
            self.fields['parameter_data'].initial = json.dumps(data)
            self.fields['content_banner_link'].initial = data["content"]["banner_link"]
            self.fields['content_description'].initial = data["content"]["description"]
            self.fields['content_webview_link'].initial = data["content"]["webview_link"]
            self.fields['campaign_content'].initial = data.get("campaign_content")

    def is_valid(self):
        if not super().is_valid():
            return False

        min_loan_amount = self.cleaned_data.get('condition_min_loan_amount')
        max_loan_amount = self.cleaned_data.get('condition_max_loan_amount')
        if max_loan_amount < min_loan_amount:
            self.add_error(
                'condition_max_loan_amount',
                'Max loan amount must be greater than or equal to min loan amount'
            )

        min_duration = self.cleaned_data.get('condition_min_duration')
        max_duration = self.cleaned_data.get('condition_max_duration')
        if max_duration < min_duration:
            self.add_error(
                'condition_max_duration',
                'Max duration must be greater than or equal to min duration'
            )

        return False if self.errors else True

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data['parameters'] = {
            "condition": {
                "min_loan_amount": cleaned_data.get('condition_min_loan_amount'),
                "max_loan_amount": cleaned_data.get('condition_max_loan_amount'),
                "min_duration": cleaned_data.get('condition_min_duration'),
                "max_duration": cleaned_data.get('condition_max_duration'),
                "list_transaction_method_code": cleaned_data.get(
                    'condition_list_transaction_method_code'
                ),
            },
            "whitelist": {
                "is_active": cleaned_data.get('whitelist_is_active'),
                "list_customer_id": convert_str_as_list_of_int(
                    cleaned_data.get('whitelist_list_customer_id')
                ),
            },
            "is_experiment_for_last_digit_customer_id_is_even": cleaned_data.get(
                'is_experiment_for_last_digit_customer_id_is_even'
            ),
            "content": {
                "title": cleaned_data.get('content_title'),
                "banner_link": cleaned_data.get('content_banner_link'),
                "description": cleaned_data.get('content_description'),
                "webview_link": cleaned_data.get('content_webview_link'),
            },
            "customer_segments": {
                "is_ftc": cleaned_data.get('customer_segments_is_ftc'),
                "is_repeat": cleaned_data.get('customer_segments_is_repeat')
            },
            "campaign_content": cleaned_data.get('campaign_content'),
        }
        return cleaned_data


class FailedBankNameValidationDuringUnderwritingForm(forms.ModelForm):
    """
    Setting form for FeatureNameConst.FAILED_BANK_NAME_VALIDATION_DURING_UNDERWRITING
    """

    class Meta(object):
        model = FeatureSetting
        fields = ('is_active', 'parameters')
        widgets = {'parameters': forms.HiddenInput()}

    parameter_data = forms.CharField(widget=forms.HiddenInput, required=False)
    allowed_transaction_methods = forms.MultipleChoiceField(
        required=False,
        choices=TransactionMethodCode.choices(),
        widget=forms.CheckboxSelectMultiple,
        label="List transaction method",
    )

    def __init__(self, *args, **kwargs):
        super(FailedBankNameValidationDuringUnderwritingForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)
            self.fields['parameter_data'].initial = json.dumps(data)

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data['parameters'] = {
            "allowed_transaction_methods": cleaned_data.get('allowed_transaction_methods')
        }
        return cleaned_data


class PreApprovalForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']


class GrabProgramFeatureSettingInline(admin.TabularInline):
    extra = 0
    model = GrabProgramFeatureSetting


class DynamicFormModelAdmin(JuloModelAdmin):
    """
    A ModelAdmin class that allows the use of dynamic forms depends on specific model field value.
    The dynamic form is utilizing `ModelAdmin.get_form()`.
    To register the form, use the `register_form` method.
    To register the function, use the `register_function` method.
    """
    dynamic_form_key_field = None
    dynamic_form_function_maps = {}
    dynamic_form_class_maps = {}

    @classmethod
    def register_form(cls, key_value: str, form_class: ModelFormMetaclass):
        """
        Register a form for a specific key value to override the default form
        Args:
            key_value (str): a unique value based on the model field
            form_class (ModelFormMetaclass): A valid Django Form class.

        Returns:
            None
        """
        cls.dynamic_form_class_maps[key_value] = form_class

    @classmethod
    def register_function(cls, key_value: str, prepare_func: callable):
        """
        Register a function to prepare a form for a specific key value
        Args:
            key_value (str): a unique value based on the model field
            prepare_func (callable): a callable function to prepare the form.
                                     The function should accept the following parameters:
                                        - self: the instance of the admin class
                                        - request: the request object
                                        - obj: the instance of the model
                                        - **kwargs: the keyword arguments

        Returns:
            None
        """
        cls.dynamic_form_function_maps[key_value] = prepare_func

    def get_form(self, request, obj=None, **kwargs):
        if not self.dynamic_form_key_field:
            return super().get_form(request, obj, **kwargs)

        value = getattr(obj, self.dynamic_form_key_field, None)
        if value and value in self.dynamic_form_class_maps:
            self.form = self.dynamic_form_class_maps[value]

        if value and value in self.dynamic_form_function_maps:
            prepare_func = self.dynamic_form_function_maps[value]
            prepare_func(self, request, obj, **kwargs)

        return super().get_form(request, obj, **kwargs)


class FeatureSettingAdminFormMixin:
    """
    A mixin for FeatureSettingAdmin's form to customize the `parameters` fields validation.
    The class that extending this class should implement the `ParameterForm` class in the class.
    """
    class Meta(object):
        model = FeatureSetting
        exclude = ("feature_name",)

    def clean(self):
        parameters = self.cleaned_data.get('parameters', {})

        if not parameters:
            return self.cleaned_data

        parameter_form = self.ParameterForm(parameters)
        if not parameter_form.is_valid():
            raise forms.ValidationError({
                'parameters': self.flatten_errors(parameter_form.errors)})

        cleaned_data = {
            field: value
            for field, value in parameter_form.cleaned_data.items()
            if value is not None
        }
        self.cleaned_data['parameters'] = cleaned_data
        return self.cleaned_data

    @staticmethod
    def flatten_errors(form_errors):
        errors = []
        for field, error_list in form_errors.items():
            errors.append('"{}": {}'.format(field, ', '.join(error_list)))
        return errors

class FeatureSettingAdmin(DynamicFormModelAdmin):
    list_display = (
        'feature_name',
        'is_active',
        'category',
    )
    readonly_fields = ('feature_name', 'preview_image')
    list_filter = ('is_active',)
    search_fields = ('feature_name',)
    ordering = ('feature_name',)
    formfield_overrides = {
        JSONField: {'widget': PrettyJSONWidget}
    }
    dynamic_form_key_field = 'feature_name'

    class Media(object):
        js = (
            'default/js/slider_script.js',  # project static folder
        )
        css = {
            'all': ('default/css/slider-style.css',)
        }

    def history_view(self, request, object_id, extra_context=None):
        "The 'history' admin view for this model."
        from django.contrib.admin.models import LogEntry
        # First check if the user can see this history.
        model = self.model
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {
                'name': force_text(model._meta.verbose_name),
                'key': escape(object_id),
            })

        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        # Then get the history for this object.
        opts = model._meta
        app_label = opts.app_label
        action_list = LogEntry.objects.filter(
            object_id=unquote(object_id),
            content_type=get_content_type_for_model(model)
        ).select_related().order_by('-action_time')

        context = dict(self.admin_site.each_context(request),
                       title=_('Change history: %s') % force_text(obj),
                       action_list=action_list,
                       module_name=capfirst(force_text(opts.verbose_name_plural)),
                       object=obj,
                       opts=opts,
                       preserved_filters=self.get_preserved_filters(request),
                       )
        context.update(extra_context or {})

        request.current_app = self.admin_site.name

        return TemplateResponse(request, self.object_history_template or [
            "admin/%s/%s/object_history.html" % (app_label, opts.model_name),
            "admin/%s/object_history.html" % app_label,
            "admin/object_history.html"
        ], context)

    def get_actions(self, request):
        # Disable delete
        actions = super(FeatureSettingAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url(
                regex=r'^(?P<object_id>[0-9]+)/upload_csv/?$',
                view=self.upload_csv,
                name='julo_featuresetting_upload_csv',
            ),
        ]

        return my_urls + urls

    def upload_csv(self, request, object_id, *args, **kwargs):
        obj = self.get_object(request, unquote(object_id))

        # POST
        if request.method == "POST":
            csv_file = request.FILES.get("csv_file", None)
            if not csv_file or not csv_file.name.lower().endswith('.csv'):
                self.message_user(request, 'Invalid file upload', level='error')
                return redirect("admin:julo_featuresetting_change", obj.id)

            if obj.feature_name == LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER:
                from juloserver.qris.services.admin_related import (
                    upload_qris_customer_whitelist_csv,
                )

                upload_qris_customer_whitelist_csv(
                    file_bytes=csv_file.read(),
                    user_id=request.user.id,
                )

            # redirect back to change page
            return redirect("admin:julo_featuresetting_change", obj.id)

        # GET
        form = CsvImportForm()
        payload = {"form": form}

        if obj.feature_name == LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER:
            history = RedisWhiteListUploadHistory.objects.filter(
                whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
                is_latest_success=True,
            ).last()
            if history:
                payload.update(
                    {
                        "last_successful_whitelist": history.udate,
                    }
                )
            payload.update(
                {
                    'data_table': {
                        'property': ['customer_id'],
                        'data': [
                            '1000576953',
                        ],
                    },
                }
            )
        return render(request, "featuresetting/upload_csv_form.html", payload)

    def get_form(self, request, obj=None, **kwargs):
        self.change_form_template = None
        if obj.feature_name == FeatureNameConst.REPAYMENT_TRAFFIC_SETTING:
            self.form = RepaymentForm
            self.change_form_template = 'featuresetting/form.html'
        elif obj.feature_name == FeatureNameConst.DISBURSEMENT_TRAFFIC_MANAGE:
            self.form = TrafficManagementForm
        elif obj.feature_name == FeatureNameConst.SPECIAL_EVENT_BINARY:
            self.form = SpecialEventBinaryForm
            self.change_form_template = 'featuresetting/special_event_binary_form.html'
            self.fieldsets = (
                (None, {
                    'fields': ('is_active', 'form_data'),
                }),
                ('ACTION', {
                    'fields': ('action',),
                }),
                ('PROVINSI', {
                    'fields': ('province',),
                }),
                ("AGE", {
                    'fields': ('min_age', 'max_age'),
                }),
                ("JOB TYPE", {
                    'fields': ('job_type',),
                }),
                ("JOB INDUSTRY & JOB DESCRIPTION", {
                    'fields': ('job_industry', 'job_description'),
                }),
                (None, {
                    'fields': ('feature_name',),
                }),
            )
        elif obj.feature_name == FeatureNameConst.LOAN_MAX_ALLOWED_DURATION:
            self.form = LoanMaxAllowedDurationForm
            self.change_form_template = "custom_admin/loan_max_allowed_duration.html"
        elif obj.feature_name == FeatureNameConst.EVER_ENTERED_B5_J1_EXPIRED_CONFIGURATION:
            self.form = EverEnteredB5ExpirationForm
            self.change_form_template = 'featuresetting/expiration_ever_entered_b5.html'
            self.fieldsets = (
                (obj.description, {
                    'fields': ('expiration_option', 'many_days'),
                }),
            )
        elif obj.feature_name == FeatureNameConst.EXPIRY_TOKEN_SETTING:
            self.form = ExpiryTokenSettingForm
        elif obj.feature_name == FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION:
            self.form = CashbackExpiredForm
        elif obj.feature_name == FeatureNameConst.MINIMUM_AMOUNT_TRANSACTION_LIMIT:
            self.form = MinimumAmountTransactionForm
        elif obj.feature_name == FeatureNameConst.SENDING_RECORDING_CONFIGURATION:
            self.change_form_template = 'featuresetting/sending_recording_configuration.html'
            self.form = SendingRecordingConfigurationForm
        elif obj.feature_name == FeatureNameConst.PARTNER_ELIGIBLE_USE_RENTEE:
            self.change_form_template = 'featuresetting/partner_eligible_use_rentee.html'
            self.form = PartnerEligibleUseRenteeForm
        elif obj.feature_name == FeatureNameConst.B4_EXPIRED_THRESHOLD:
            self.form = B4ExpirationForm
        elif obj.feature_name == FeatureNameConst.SALES_OPS:
            self.form = SalesOpsSettingForm
        elif obj.feature_name == FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM:
            self.change_form_template = 'featuresetting/blacklist_partner_from_dialer.html'
            self.form = BlacklistPartnerDialerForm
        elif obj.feature_name == FeatureNameConst.FDC_TIMEOUT:
            self.form = FdcTimeoutSettingForm
        elif obj.feature_name == DukcapilFeatureNameConst.DUKCAPIL_VERIFICATION:
            self.form = DukcapilVerificationForm
        elif obj.feature_name == FeatureNameConst.TUTORIAL_AUTODEBET:
            self.form = TutorialAutodebetBriForm
            self.change_form_template = 'custom_admin/tutorial_autodebet.html'
            self.fieldsets = (
                (None, {
                    'fields': ('is_active',),
                }),
                ('VENDOR', {
                    'fields': (
                        'vendor',
                    ),
                }),
                ('TURN ON', {
                    'fields': (
                        'registration_subtitle',
                        'registration_content_type',
                        'registration_cta_type',
                        'registration_cta',
                        'registration_image',
                        'registration_video',
                        'preview_image',
                    ),
                }),
                ('TURN OFF', {
                    'fields': (
                        'revocation_subtitle',
                        'revocation_content_type',
                        'revocation_cta_type',
                        'revocation_cta',
                        'revocation_image',
                        'revocation_video',
                        'preview_image',
                    ),
                }),
                ('BENEFIT', {
                    'fields': (
                        'benefit_subtitle',
                        'benefit_type',
                        'benefit_content_type',
                        'benefit_cta_type',
                        'benefit_cta',
                        'benefit_image',
                        'benefit_video',
                        'preview_image',
                    ),
                }),
                (None, {
                    'fields': ('form_data',),
                }),
            )
        elif obj.feature_name == FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE:
            self.form = BypassLenderByProductLineSettingForm
        elif obj.feature_name == FeatureNameConst.BSS_CHANNELING_CUTOFF:
            self.form = BSSChannelingCufOffForm
        elif obj.feature_name == FeatureNameConst.EF_PRE_APPROVAL:
            self.form = PreApprovalForm
        elif obj.feature_name == FeatureNameConst.GRAB_DEDUCTION_SCHEDULE:
            self.form = GrabDeductionFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL:
            self.form = AutodebetCustomerExcludeFromIntelixCallForm
        elif obj.feature_name == FeatureNameConst.GRAB_INTELIX_CALL:
            self.form = GrabIntelixCallFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.GRAB_WRITE_OFF:
            self.form = GrabWriteOffFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.GOPAY_ONBOARDING_PAGE:
            self.form = GopayOnboardingForm
        elif obj.feature_name == FeatureNameConst.GRAB_REFERRAL_PROGRAM:
            self.form = GrabReferralFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.GOPAY_ACTIVATION_LINKING:
            self.form = GopayActivationLinkingForm
        elif obj.feature_name == FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS:
            self.form = PaymentMethodGroupingForm
        elif obj.feature_name == FeatureNameConst.GRAB_STOP_REGISTRATION:
            self.form = GrabModalStopRegistrationFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.GRAB_FILE_TRANSFER_CALL:
            self.form = GrabFileTransferCallFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER:
            self.form = ConfigFlowToLimitJstarterForm
        elif obj.feature_name == FeatureNameConst.SECOND_CHECK_JSTARTER_MESSAGE:
            self.form = SettingMessageJStarterForm
        elif obj.feature_name == FeatureNameConst.MYCROFT_SCORE_CHECK:
            self.form = MycroftScoreCheckForm
        elif obj.feature_name == MiniSquadFeatureSettingConst.HANDLING_DIALER_ALERT:
            self.form = HandlingDialerAlertForm
        elif obj.feature_name == FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD:
            self.form = ConfigurationFormSphinxNoBpjs
        elif obj.feature_name == FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER:
            self.form = ConfigSpecificUserForJstarter
        elif obj.feature_name == FeatureNameConst.RECIPIENTS_BACKUP_PASSWORD:
            self.form = RecipientsBackupPasswordForm
        elif obj.feature_name == FeatureNameConst.PAYMENT_METHOD_FAQ_URL:
            self.form = PaymentMethodFaqForm
        elif obj.feature_name in [
            AutodebetFeatureNameConst.AUTODEBET_BCA,
            AutodebetFeatureNameConst.AUTODEBET_BRI,
            AutodebetFeatureNameConst.AUTODEBET_GOPAY,
            AutodebetFeatureNameConst.AUTODEBET_MANDIRI,
            AutodebetFeatureNameConst.AUTODEBET_BNI,
            AutodebetFeatureNameConst.AUTODEBET_DANA,
            AutodebetFeatureNameConst.AUTODEBET_OVO,
        ]:
            self.form = AutodebetForm
        elif obj.feature_name == ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG:
            channeling_admin = ChannelingLoanAdminHelper()
            channeling_admin.initialize_form(ChannelingLoanAdminForm)
            self.form = channeling_admin.form
            self.change_form_template = channeling_admin.change_form_template
            self.fieldsets = channeling_admin.fieldsets
        elif obj.feature_name == FeatureNameConst.HIGH_RISK_ASN_TOWER_CHECK:
            self.form = FraudHighRiskAsnTowerCheckForm
        elif obj.feature_name == FeatureNameConst.MARKETING_LOAN_PRIZE_CHANCE:
            self.form = MarketingLoanPrizeChanceSettingForm
        elif obj.feature_name == FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION:
            self.form = ZeroInterestHigherProvisionForm
            self.change_form_template = 'custom_admin/zero_interest_higher_provision.html'
            self.fieldsets = (
                (None, {
                    'fields': (
                        'is_active',
                        'parameters',
                        'parameter_data',
                    ),
                }),
                ('Condition', {
                    'fields': [
                        ('condition_min_loan_amount', 'condition_max_loan_amount'),
                        ('condition_min_duration', 'condition_max_duration'),
                        'condition_list_transaction_method_code',
                    ],
                }),
                ('Whitelist', {
                    'fields': [
                        'whitelist_is_active',
                        'whitelist_list_customer_id',
                    ],
                }),
                ('Experiment', {
                    'fields': [
                        'is_experiment_for_last_digit_customer_id_is_even'
                    ]
                }),
                ('Popup And Banner Content', {
                    'fields': [
                        'content_title',
                        'content_banner_link',
                        'content_description',
                        'content_webview_link',
                    ]
                }),
                ('Customer segments', {
                    'fields': [
                        'customer_segments_is_ftc', 'customer_segments_is_repeat',
                    ]
                }),
                ('Campaign Content', {'fields': ['campaign_content']}),
            )
        elif obj.feature_name == FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO:
            self.form = GrabPGRatioSettingForm
        elif obj.feature_name == FeatureNameConst.SELFIE_GEOHASH_CRM_IMAGE_LIMIT:
            self.form = SelfieGeohashCrmImageLimitForm
        elif obj.feature_name == FeatureNameConst.SIMILAR_AND_FRAUD_FACE_TIME_LIMIT:
            self.form = SimilarAndFraudFaceTimeLimitForm
        elif obj.feature_name == FeatureNameConst.GRAB_SMALLER_LOAN_OPTION:
            self.form = GrabSmallerLoanOptionsForm
        elif obj.feature_name == FeatureNameConst.AUTODEBET_DEDUCTION_DAY:
            self.form = AutodebetDeductionDayForm
            self.change_form_template = 'custom_admin/autodebet_deduction_day.html'
            self.fieldsets = (
                (None, {
                    'fields': ('is_active',),
                }),
                ('VENDOR', {
                    'fields': (
                        'vendor',
                    ),
                }),
                ('DEDUCTION DAY TYPE', {
                    'fields': (
                        'deduction_day_type',
                        'last_update'
                    ),
                }),
                (None, {
                    'fields': ('form_data',),
                }),
            )
        elif obj.feature_name == FeatureNameConst.TRUST_GUARD_SCORING:
            self.form = TrustDecisionForm
        elif obj.feature_name == FeatureNameConst.GRAB_AI_RUDDER_CALL:
            self.form = GrabAirudderCallFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.DANA_OTHER_PAGE_URL:
            self.form = DanaOtherPageForm
        elif obj.feature_name == FeatureNameConst.DISABLE_PAYMENT_METHOD:
            self.form = DisablePaymentMethodForm
        elif obj.feature_name == FeatureNameConst.CUSTOMER_DATA_CHANGE_REQUEST:
            self.form = CustomerDataChangeRequestSettingAdminForm
        elif obj.feature_name == FeatureNameConst.PAYMENT_GATEWAY_ALERT:
            self.form = PaymentGatewayAlertForm
        elif obj.feature_name == AutodebetFeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY:
            self.form = AutodebetMandiriMaxLimitDeductionForm
        elif obj.feature_name == FeatureNameConst.MONNAI_FRAUD_SCORE:
            self.form = MonnaiFraudScoreForm
        elif obj.feature_name == FeatureNameConst.LATE_FEE_RULE:
            self.form = LateFeeRuleForm
        elif obj.feature_name == AutodebetFeatureNameConst.AUTODEBET_RE_INQUIRY:
            self.form = ReinquiryAutodebetForm
        elif obj.feature_name == FeatureNameConst.KTP_OCR_THRESHOLD_VALUE:
            self.form = KTPThresholdValueForm
        elif obj.feature_name == FeatureNameConst.GRAB_DISBURSEMENT_RETRY:
            self.form = GrabDisbursementRetryForm
        elif obj.feature_name == FeatureNameConst.FAILED_BANK_NAME_VALIDATION_DURING_UNDERWRITING:
            self.form = FailedBankNameValidationDuringUnderwritingForm
            self.change_form_template = (
                'custom_admin/failed_bank_name_validation_during_underwriting.html'
            )
            self.fieldsets = (
                (
                    None,
                    {
                        'fields': (
                            'is_active',
                            'parameters',
                            'parameter_data',
                        ),
                    },
                ),
                (
                    'Allowed Transaction Methods',
                    {
                        'fields': [
                            'allowed_transaction_methods',
                        ],
                    },
                ),
            )
        elif obj.feature_name == FeatureNameConst.EXCLUDE_LATEST_PAYMENT_METHOD:
            self.form = ExcludeLatestPaymentMethodForm
        elif obj.feature_name == AutodebetFeatureNameConst.AUTODEBET_BNI_MAX_LIMIT_DEDUCTION_DAY:
            self.form = AutodebetBniMaxLimitDeductionForm
        elif obj.feature_name == FeatureNameConst.GRAB_ADMIN_FEE_TIERING:
            self.form = GrabAdminFeeFeatureSettingForm
        elif obj.feature_name == AutodebetFeatureNameConst.INSUFFICIENT_BALANCE_TURN_OFF:
            self.form = InsufficientBalanceFeatureSettingForm
        elif obj.feature_name == FeatureNameConst.IDFY_VIDEO_CALL_HOURS:
            self.form = IDFyVideoCallHoursForm
        elif obj.feature_name == FeatureNameConst.AUTODEBET_IDFY_ENTRY_POINT:
            self.form = AutodebetIDFyEntryPoint
            self.change_form_template = 'custom_admin/autodebet_idfy_entry_point.html'
            self.fieldsets = (
                (
                    None,
                    {
                        'fields': (
                            'is_active',
                            'image',
                            'preview_image',
                            'form_data',
                        ),
                    },
                ),
            )
        elif obj.feature_name == FeatureNameConst.CASHBACK_DRAWER_ENCOURAGEMENT:
            self.form = CashbackDrawerEncouragement
            self.change_form_template = 'custom_admin/cashback_drawer_encouragement.html'
        elif obj.feature_name == FeatureNameConst.DELAY_DISBURSEMENT:
            delay_disbursement_setting = DelayDisbursementSetting()
            delay_disbursement_setting.initialize_form(DelayDisbursementAdminForm)
            self.form = delay_disbursement_setting.form
            self.change_form_template = delay_disbursement_setting.change_form_template
            self.fieldsets = delay_disbursement_setting.fieldsets
        elif obj.feature_name == FeatureNameConst.USER_SEGMENT_CHUNK_SIZE:
            self.form = UserSegmentChunkSizeAdminForm
        elif obj.feature_name == FeatureNameConst.USER_SEGMENT_CHUNK_INTEGRITY_CHECK_TTL:
            self.form = UserSegmentChunkIntegrityCheckTtlAdminForm
        elif obj.feature_name == FeatureNameConst.SMS_CAMPAIGN_FAILED_PROCESS_CHECK_TTL:
            self.form = SmsCampaignFailedProcessCheckTtlAdminForm
        elif obj.feature_name == FeatureNameConst.AUTODEBET_IDFY_CALL_BUTTON:
            self.form = AutodebetIDFyCallButton
            self.change_form_template = 'custom_admin/autodebet_idfy_call_button.html'
            self.fieldsets = (
                (
                    None,
                    {
                        'fields': (
                            'is_active',
                            'image',
                            'preview_image',
                            'form_data',
                        ),
                    },
                ),
            )
        elif obj.feature_name == FeatureNameConst.THOR_TENOR_INTERVENTION:
            self.form = ThorTenorInterventionVerificationForm
        elif obj.feature_name == LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER:
            self.change_form_template = 'featuresetting/change_form_with_upload_csv_btn.html'
        elif obj.feature_name == LoanFeatureNameConst.QRIS_MULTIPLE_LENDER:
            self.form = QrisMultiLenderSettingForm
        elif obj.feature_name == FeatureNameConst.CROSS_OS_LOGIN:
            self.form = CrossOSLoginForm
        elif obj.feature_name == AccountPaymentFeatureNameConst.REPAYMENT_FAQ_SETTING:
            self.form = RepaymentFaqSettingForm
        elif obj.feature_name == FeatureNameConst.QRIS_LANDING_PAGE_CONFIG:
            self.form = QrisLandingPageConfigForm
        elif obj.feature_name == FeatureNameConst.PAYMENT_METHOD_SWITCH:
            self.form = PaymentMethodSwitchForm
            self.change_form_template = 'featuresetting/payment_method_switch.html'
        elif obj.feature_name == ChannelingFeatureNameConst.CREDIT_SCORE_CONVERSION:
            self.form = CreditScoreConversionAdminForm
        else:
            self.form = forms.ModelForm
            self.fieldsets = None
        return super(FeatureSettingAdmin, self).get_form(request, obj, **kwargs)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj.feature_name == FeatureNameConst.GRAB_DEDUCTION_SCHEDULE:
            self.change_form_template = 'custom_admin/change_form_help_text.html'
            extra = {
                'help_text': "This is a help message"
            }

            context.update(extra)
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request, obj, form, change):
        """
        Given a model instance save it to the database.
        """
        if obj.feature_name == FeatureNameConst.DISBURSEMENT_TRAFFIC_MANAGE:
            customer_type = form.cleaned_data['customer_type']
            money_flow = form.cleaned_data['money_flow']
            probability = form.cleaned_data['probability']
            obj.parameters[customer_type][money_flow] = probability
            for flow in list(obj.parameters[customer_type].keys()):
                if flow != money_flow:
                    obj.parameters[customer_type][flow] = 100 - probability
                    break
        elif obj.feature_name == FeatureNameConst.REPAYMENT_TRAFFIC_SETTING:
            new_data = json.loads(form.cleaned_data['form_data'])
            for customer_type, channel_list in list(obj.parameters.items()):
                for channel, channel_settings in list(channel_list['settings'].items()):
                    prob = new_data[customer_type]['settings'][channel]["prob"]
                    backup_channel = new_data[customer_type]['settings'][channel]["selected"]
                    channel_settings["prob"] = prob
                    channel_settings["selected"] = backup_channel
        elif obj.feature_name == FeatureNameConst.SPECIAL_EVENT_BINARY:
            save_form_special_event_binary(obj, form)
        elif obj.feature_name == FeatureNameConst.ACCOUNT_REACTIVATION_SETTING:
            from juloserver.account.tasks.account_task import scheduled_reactivation_account
            scheduled_reactivation_account.delay()
        elif obj.feature_name == FeatureNameConst.LOAN_MAX_ALLOWED_DURATION:
            parameters = []
            for index in list(range(0, int(request.POST["last_index"]) + 1)):
                if "max_duration_%s" % index not in request.POST:
                    continue
                parameters.append(
                    dict(
                        duration=int(request.POST["max_duration_%s" % index] or 0),
                        max_amount=int(request.POST["max_amount_%s" % index] or 0),
                        min_amount=int(request.POST["min_amount_%s" % index] or 0),
                    )
                )
            obj.parameters = parameters
            obj.is_active = form.cleaned_data['is_active']
        elif obj.feature_name == FeatureNameConst.EVER_ENTERED_B5_J1_EXPIRED_CONFIGURATION:
            expiration_option = form.cleaned_data['expiration_option']
            obj.parameters['entered_b5_valid_for'] = expiration_option
            if expiration_option != "forever":
                many_days = form.cleaned_data['many_days']
                obj.parameters['entered_b5_valid_for'] = str(many_days)
            pass
        elif obj.feature_name == FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION:
            obj.is_active = form.cleaned_data['is_active']
            obj.parameters['reminder_days'] = form.cleaned_data['reminder_days']
        elif obj.feature_name == FeatureNameConst.MINIMUM_AMOUNT_TRANSACTION_LIMIT:
            obj.is_active = form.cleaned_data['is_active']
            obj.parameters['limit_transaction'] = form.cleaned_data['minimum_amount']
            obj.parameters['information'] = form.cleaned_data['information']
        elif obj.feature_name == FeatureNameConst.SENDING_RECORDING_CONFIGURATION:
            obj.parameters['recording_resources'] = form.cleaned_data['recording_resources']
            recording_duration_type = form.cleaned_data['recording_duration']
            duration = []
            if recording_duration_type == 'between':
                duration.append(form.cleaned_data['duration_from'])
                duration.append(form.cleaned_data['duration_until'])
            elif recording_duration_type:
                duration.append(form.cleaned_data['duration_from'])

            obj.parameters['recording_duration_type'] = recording_duration_type
            obj.parameters['recording_duration'] = duration
            obj.parameters['buckets'] = form.cleaned_data['buckets']
            obj.parameters['call_result_ids'] = form.cleaned_data['call_result_ids']
        elif obj.feature_name == FeatureNameConst.PARTNER_ELIGIBLE_USE_RENTEE:
            obj.parameters['partner_ids'] = list(map(int, form.cleaned_data['partner_ids']))
        elif obj.feature_name == FeatureNameConst.SALES_OPS:
            save_setting(form.cleaned_data['parameters'])
        elif obj.feature_name == FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM:
            partner_ids = form.cleaned_data['partner_ids']
            parameters = {}
            for partner_id in partner_ids:
                config = request.POST.get('dpd_configuration_for_{}'.format(partner_id))
                parameters.update({partner_id: config})
            obj.parameters = parameters
        elif obj.feature_name == FeatureNameConst.TUTORIAL_AUTODEBET:
            parameters = obj.parameters
            request_data = request.POST
            vendor = request_data['vendor']
            benefit_type = request_data['benefit_type']

            if request_data:
                for autodebet_type in TutorialAutodebetConst.AUTODEBET_TYPES:
                    for autodebet_content in TutorialAutodebetConst.AUTODEBET_CONTENTS:
                        if autodebet_content == 'video':
                            if request.POST['{}_{}'.format(autodebet_type, autodebet_content)]:
                                video = request.POST['{}_{}'.format(autodebet_type, autodebet_content)] \
                                    .split('watch?v=')
                                if autodebet_type == 'benefit':
                                    parameters[vendor][autodebet_type][benefit_type][autodebet_content] = \
                                        video[1] if len(video) > 1 else video[0]
                                else:
                                    parameters[vendor][autodebet_type][autodebet_content] = \
                                        video[1] if len(video) > 1 else video[0]
                        else:
                            ad_value = request.POST['{}_{}'.format(
                                autodebet_type, autodebet_content
                            )]

                            if autodebet_type == 'benefit':
                                parameters[vendor][autodebet_type][benefit_type][autodebet_content] = \
                                    ad_value
                            else:
                                parameters[vendor][autodebet_type][autodebet_content] = ad_value

                    if request.FILES and request.FILES.get('{}_{}'.format(autodebet_type, 'image')):
                        banner_image = request.FILES['{}_{}'.format(autodebet_type, 'image')]
                        _, file_extension = os.path.splitext(banner_image.name)

                        if autodebet_type == 'benefit':
                            remote_path = 'tutorial_autodebet_{}_{}_{}/image{}'.format(
                                vendor,
                                autodebet_type,
                                benefit_type,
                                file_extension
                            )
                        else:
                            remote_path = 'tutorial_autodebet_{}_{}/image{}'.format(
                                vendor,
                                autodebet_type,
                                file_extension
                            )

                        image = Image()
                        image.image_source = obj.pk
                        image.image_type = remote_path.split('/image')[0]
                        image.url = remote_path
                        image.save()

                        if autodebet_type == 'benefit':
                            parameters[vendor][autodebet_type][benefit_type]['image_data']['type'] = image.image_type
                            parameters[vendor][autodebet_type][benefit_type]['image_data']['id'] = image.id
                        else:
                            parameters[vendor][autodebet_type]['image_data']['type'] = image.image_type
                            parameters[vendor][autodebet_type]['image_data']['id'] = image.id

                        file = functions.upload_handle_media(banner_image, "tutorial/image")
                        if file:
                            upload_file_to_oss(
                                settings.OSS_MEDIA_BUCKET,
                                file['file_name'],
                                remote_path
                            )
        elif obj.feature_name == FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER:
            save_model_config_jstarter(obj, form)
        elif obj.feature_name == FeatureNameConst.SECOND_CHECK_JSTARTER_MESSAGE:
            save_model_setup_message_jstarter(obj, form)
        elif obj.feature_name == FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD:
            save_model_sphinx_no_bpjs(obj, form)

        elif obj.feature_name == FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER:
            save_model_config_specific_jstarter(obj, form)
        elif obj.feature_name == FeatureNameConst.AUTODEBET_GOPAY:
            is_active = obj.is_active
            old_start_date_time = obj.parameters.get('disable').get('disable_start_date_time')
            old_end_date_time = obj.parameters.get('disable').get('disable_end_date_time')
            obj.parameters['disable'] = json.loads(form.cleaned_data['disable'])
            obj.parameters['retry_schedule'] = json.loads(form.cleaned_data['retry_schedule'])
            obj.parameters['deduction_dpd'] = json.loads(form.cleaned_data['deduction_dpd'])
            now = timezone.localtime(timezone.now())
            gopay_client = get_gopay_client()

            # send message to slack
            slack_message = " Autodebet Gopay Feature is Turned ON" \
                if is_active else " Autodebet Gopay Feature is Turned OFF"

            if settings.ENVIRONMENT != 'prod':
                slack_message = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_message
            send_slack_bot_message("#gopay-autodebit-alert", slack_message)

            # check if gopay autodebet is disabled and deactivate the subscription
            autodebet_gopay_disable = False
            start_date_time = obj.parameters.get('disable').get('disable_start_date_time')
            end_date_time = obj.parameters.get('disable').get('disable_end_date_time')
            if start_date_time and end_date_time:
                start_date_time_obj = DateTimeModule.strptime(start_date_time, '%d-%m-%Y %H:%M')
                end_date_time_obj = DateTimeModule.strptime(end_date_time, '%d-%m-%Y %H:%M')
                today = DateTimeModule.strptime(DateTimeModule.strftime(now, '%d/%m/%y %H:%M'), '%d/%m/%y %H:%M')
                if (start_date_time_obj <= today <= end_date_time_obj) or (today.date() == start_date_time_obj.date()):
                    autodebet_gopay_disable = True
                if not old_start_date_time or start_date_time != old_start_date_time:
                    if start_date_time_obj > today:
                        send_pn_autodebet_payment_method_disabled.apply_async(
                            (obj.feature_name, MoengageEventType.AUTODEBET_DISABLE_TURNED_ON, start_date_time, end_date_time,),
                            eta=timezone.localtime(start_date_time_obj)
                        )
                if not old_end_date_time or end_date_time != old_end_date_time:
                    if end_date_time_obj > today:
                        send_pn_autodebet_payment_method_disabled.apply_async(
                            (obj.feature_name, MoengageEventType.AUTODEBET_DISABLE_TURNED_OFF, start_date_time, end_date_time,),
                            eta=timezone.localtime(end_date_time_obj)
                        )
                if start_date_time_obj.time().hour <= 10 and end_date_time_obj.time().hour > 10:
                    gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
                        is_active=True,
                        cdate__date=start_date_time_obj.date() - datetime.timedelta(days=1),
                        status=None
                    )
                    if gopay_autodebet_transactions:
                        autodebet_gopay_disable = True
                        for gopay_autodebet_transaction in gopay_autodebet_transactions.iterator():
                            try:
                                gopay_client.disable_subscription_gopay_autodebet(
                                    gopay_autodebet_transaction
                                )
                                gopay_autodebet_transaction.update_safely(
                                    is_active=False,
                                )
                            except Exception as e:
                                logger.error(
                                    {
                                        'action': 'julo.admin.AutodebetGopayForm',
                                        'message': 'Failed To Disable Subscription',
                                        'gopay_autodebet_transaction_id': gopay_autodebet_transaction.id
                                    }
                                )
                                continue
            if not autodebet_gopay_disable:
                if is_active:
                    gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
                        is_active=False,
                        cdate__date__range=[now.date() - datetime.timedelta(days=1), now.date()],
                        forced_inactive_by_julo=True
                    ).exclude(status__in=[
                        GopayTransactionStatusConst.SETTLEMENT,
                        GopayTransactionStatusConst.EXPIRED
                    ]).values_list('id', flat=True)
                    if gopay_autodebet_transactions:
                        update_subscription.delay(gopay_autodebet_transactions)
                else:
                    gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
                        is_active=True,
                        cdate__date__range=[now.date() - datetime.timedelta(days=1), now.date()]
                    ).exclude(status=GopayTransactionStatusConst.SETTLEMENT)

                    if gopay_autodebet_transactions:
                        for gopay_autodebet_transaction in gopay_autodebet_transactions.iterator():
                            try:
                                gopay_client.disable_subscription_gopay_autodebet(
                                    gopay_autodebet_transaction
                                )
                                gopay_autodebet_transaction.update_safely(
                                    is_active=False,
                                    forced_inactive_by_julo=True
                                )
                            except Exception as e:
                                logger.error(
                                    {
                                        'action': 'julo.admin.AutodebetGopayForm',
                                        'message': 'Failed to disable subscription',
                                        'gopay_autodebet_transaction_id': gopay_autodebet_transaction.id
                                    }
                                )
                                continue
        elif obj.feature_name in [
            AutodebetFeatureNameConst.AUTODEBET_BCA,
            AutodebetFeatureNameConst.AUTODEBET_BRI,
            AutodebetFeatureNameConst.AUTODEBET_MANDIRI,
            AutodebetFeatureNameConst.AUTODEBET_BNI,
            AutodebetFeatureNameConst.AUTODEBET_DANA,
            AutodebetFeatureNameConst.AUTODEBET_OVO,
        ]:
            obj.is_active = form.cleaned_data['is_active']
            if obj.feature_name == FeatureNameConstAutodebet.AUTODEBET_MANDIRI:
                channel_name = get_channel_name_slack_autodebet_mandiri_deduction()
                slack_message = " Autodebet Mandiri Feature is Turned OFF"
                if obj.is_active:
                    slack_message = " Autodebet Mandiri Feature is Turned ON"

                send_slack_bot_message(channel_name, slack_message)
            if (
                obj.feature_name != AutodebetFeatureNameConst.AUTODEBET_MANDIRI
                and obj.feature_name != AutodebetFeatureNameConst.AUTODEBET_BNI
                and obj.feature_name != AutodebetFeatureNameConst.AUTODEBET_OVO
            ):
                obj.parameters['minimum_amount'] = form.cleaned_data['minimum_amount']
            if obj.feature_name == AutodebetFeatureNameConst.AUTODEBET_DANA:
                obj.parameters['deduction_dpd'] = json.loads(form.cleaned_data['deduction_dpd'])
                # send message to slack
                slack_message = (
                    " Autodebet Dana Feature is Turned ON"
                    if obj.is_active
                    else " Autodebet Dana Feature is Turned OFF"
                )

                if settings.ENVIRONMENT != 'prod':
                    slack_message = (
                        "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper())
                        + slack_message
                    )
                send_slack_bot_message("#dana-autodebit-alert", slack_message)
            if obj.feature_name == AutodebetFeatureNameConst.AUTODEBET_OVO:
                obj.parameters['deduction_dpd'] = json.loads(form.cleaned_data['deduction_dpd'])
                # send message to slack
                slack_message = (
                    " Autodebet OVO Feature is Turned ON"
                    if obj.is_active
                    else " Autodebet OVO Feature is Turned OFF"
                )

                if settings.ENVIRONMENT != 'prod':
                    slack_message = (
                        "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper())
                        + slack_message
                    )
                send_slack_bot_message("#ovo-autodebit-alert", slack_message)
            old_start_date_time = obj.parameters.get('disable').get('disable_start_date_time')
            old_end_date_time = obj.parameters.get('disable').get('disable_end_date_time')
            obj.parameters['disable'] = json.loads(form.cleaned_data['disable'])
            start_date_time = obj.parameters.get('disable').get('disable_start_date_time')
            end_date_time = obj.parameters.get('disable').get('disable_end_date_time')
            if start_date_time and end_date_time:
                start_date_time_obj = DateTimeModule.strptime(start_date_time, '%d-%m-%Y %H:%M')
                end_date_time_obj = DateTimeModule.strptime(end_date_time, '%d-%m-%Y %H:%M')
                today = DateTimeModule.strptime(
                    DateTimeModule.strftime(timezone.localtime(timezone.now()), '%d/%m/%y %H:%M'), '%d/%m/%y %H:%M')
                if not old_start_date_time or start_date_time != old_start_date_time:
                    if start_date_time_obj > today:
                        send_pn_autodebet_payment_method_disabled.apply_async(
                            (obj.feature_name, MoengageEventType.AUTODEBET_DISABLE_TURNED_ON, start_date_time, end_date_time,),
                            eta=timezone.localtime(start_date_time_obj)
                        )
                if not old_end_date_time or end_date_time != old_end_date_time:
                    if end_date_time_obj > today:
                        send_pn_autodebet_payment_method_disabled.apply_async(
                            (obj.feature_name, MoengageEventType.AUTODEBET_DISABLE_TURNED_OFF, start_date_time, end_date_time,),
                            eta=timezone.localtime(end_date_time_obj)
                        )
        elif obj.feature_name == ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG:
            channeling_admin = ChannelingLoanAdminHelper()
            channeling_admin.reconstruct_request(request.POST)
            obj.parameters[channeling_admin.channeling_type] = channeling_admin.cleaned_request
        elif obj.feature_name == FeatureNameConst.IN_APP_PTP_SETTING:
            dpd_start_appear = obj.parameters.get('dpd_start_appear')
            if dpd_start_appear == None:
                dpd_start_appear = InAppPTPDPD.DPD_START_APPEAR

            dpd_stop_appear = obj.parameters.get('dpd_stop_appear')
            if dpd_stop_appear == None:
                dpd_stop_appear = InAppPTPDPD.DPD_STOP_APPEAR

            if dpd_start_appear>=0 or dpd_stop_appear >=0:
                return messages.error(request, "dpd tidak boleh lebih besar sama dengan 0(%d,%d)"%(dpd_start_appear,dpd_stop_appear))
            if dpd_start_appear>dpd_stop_appear:
                return messages.error(request, "dpd_start_appear tidak boleh lebih besar dpd_stop_appear")
        elif obj.feature_name == FeatureNameConst.AUTODEBET_BENEFIT_CONTROL:
            parameters = obj.parameters
            change_benefit_value.delay(parameters.get('cashback'))
        elif obj.feature_name == FeatureNameConst.DISABLE_PAYMENT_METHOD:
            is_active = obj.is_active
            payment_method_name_list = obj.parameters.get('payment_method_name')
            if is_active and 'DANA' in payment_method_name_list:
                disable_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.DISABLE_PAYMENT_METHOD
                ).last()
                old_start_date_time = disable_feature.parameters.get('disable_start_date_time')
                old_end_date_time = disable_feature.parameters.get('disable_end_date_time')
                start_date_time = obj.parameters.get('disable_start_date_time')
                end_date_time = obj.parameters.get('disable_end_date_time')
                if start_date_time and end_date_time:
                    start_date_time_obj = DateTimeModule.strptime(start_date_time, '%d-%m-%Y %H:%M')
                    end_date_time_obj = DateTimeModule.strptime(end_date_time, '%d-%m-%Y %H:%M')
                    today = DateTimeModule.strptime(
                        DateTimeModule.strftime(timezone.localtime(timezone.now()), '%d/%m/%y %H:%M'), '%d/%m/%y %H:%M')
                    if not old_start_date_time or start_date_time != old_start_date_time:
                        if start_date_time_obj > today:
                            slack_message = "Dana Payment Method Disabling is Turned ON"
                            send_dana_payment_disable_slack_notification.apply_async(
                                (slack_message,),
                                eta=timezone.localtime(start_date_time_obj)
                            )
                    if not old_end_date_time or end_date_time != old_end_date_time:
                        if end_date_time_obj > today:
                            slack_message = "Dana Payment Method Disabling is Turned OFF"
                            send_dana_payment_disable_slack_notification.apply_async(
                                (slack_message,),
                                eta=timezone.localtime(end_date_time_obj)
                            )
        elif obj.feature_name == FeatureNameConst.DANA_LINKING:
            is_active = obj.is_active
            # send message to slack
            slack_message = " Dana Linking Feature is Turned ON" \
                if is_active else " Dana Linking Feature is Turned OFF"

            if settings.ENVIRONMENT != 'prod':
                slack_message = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_message
            send_slack_bot_message("#dana_ewallet_alert", slack_message)

        elif obj.feature_name == FeatureNameConst.AUTODEBET_DEDUCTION_DAY:
            parameters = obj.parameters
            request_data = request.POST
            deduction_type = request_data['deduction_day_type']
            vendor = request_data['vendor']
            parameters[vendor]['deduction_day_type'] = deduction_type
            prev_deduction_type = FeatureSetting.objects.get(
                pk=obj.id
            ).parameters[vendor]['deduction_day_type']
            if prev_deduction_type != deduction_type:
                parameters[vendor]['last_update'] = timezone.localtime(timezone.now()).strftime(
                    '%Y-%m-%d')
        elif obj.feature_name == FeatureNameConst.LATE_FEE_RULE:
            parameters = json.dumps(obj.parameters)
            late_fee_rule_creation.delay(parameters)
            messages.success(
                request,
                'When new product lookup created. Please upload new credit matrix '
                'according to MAX late fee value.',
            )
        elif obj.feature_name == FeatureNameConstAutodebet.AUTODEBET_BNI:
            is_active = obj.is_active
            # send message to slack
            slack_message = " Autodebet BNI Feature is Turned ON" \
                if is_active else " Autodebet BNI Feature is Turned OFF"

            if settings.ENVIRONMENT != 'prod':
                slack_message = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_message
            send_slack_bot_message("#bni-autodebet-alert", slack_message)
        elif obj.feature_name == FeatureNameConst.OVO_TOKENIZATION:
            is_active = obj.is_active
            # send message to slack
            slack_message = (
                " OVO TOKENIZATION Feature is Turned ON"
                if is_active
                else " OVO TOKENIZATION Feature is Turned OFF"
            )

            if settings.ENVIRONMENT != 'prod':
                slack_message = (
                    "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper())
                    + slack_message
                )
            send_slack_bot_message("#ovolinking_alert", slack_message)
        elif obj.feature_name == FeatureNameConst.AUTODEBET_IDFY_ENTRY_POINT:
            request_data = request.POST

            if request_data:
                if request.FILES and request.FILES.get('image'):
                    banner_image = request.FILES['image']
                    _, file_extension = os.path.splitext(banner_image.name)

                    remote_path = 'autodebet_idfy_entry_point/image{}'.format(file_extension)
                    image = Image()
                    image.image_source = obj.pk
                    image.image_type = remote_path.split('/image')[0]
                    image.url = remote_path
                    image.save()

                    obj.parameters['image_id'] = image.id
                    obj.parameters['image_type'] = image.image_type
                    obj.parameters['image_url'] = image.image_url

                    file = functions.upload_handle_media(banner_image, "tutorial/image")
                    if file:
                        upload_file_to_oss(
                            settings.OSS_MEDIA_BUCKET, file['file_name'], remote_path
                        )
        elif obj.feature_name == FeatureNameConst.CASHBACK_DRAWER_ENCOURAGEMENT:
            request_data = request.POST

            is_active = obj.is_active
            obj.parameters['title'] = form.cleaned_data['title']
            obj.parameters['subtitle'] = form.cleaned_data['subtitle']
            obj.parameters['cta'] = form.cleaned_data['cta']
            obj.parameters['dpd'] = json.loads(form.cleaned_data['dpd'])

            if request_data:
                if request.FILES and request.FILES.get('image'):
                    banner_image = request.FILES['image']
                    _, file_extension = os.path.splitext(banner_image.name)

                    remote_path = 'cashback_drawer_encouragement/image{}'.format(file_extension)
                    image = Image()
                    image.image_source = obj.pk
                    image.image_type = remote_path.split('/image')[0]
                    image.url = remote_path
                    image.save()

                    obj.parameters['image']['image_id'] = image.id
                    obj.parameters['image']['image_type'] = image.image_type
                    obj.parameters['image']['image_url'] = image.image_url

                    file = functions.upload_handle_media(banner_image, "cashback/image")
                    if file:
                        upload_file_to_oss(
                            settings.OSS_MEDIA_BUCKET, file['file_name'], remote_path
                        )
        elif obj.feature_name == FeatureNameConst.DELAY_DISBURSEMENT:
            delay_disbursement_admin = DelayDisbursementSetting()
            delay_disbursement_admin.cleaned_data = obj.parameters
            delay_disbursement_admin.reconstruct_request(request.POST)
            obj.parameters = delay_disbursement_admin.cleaned_request
        elif obj.feature_name == FeatureNameConst.AUTODEBET_IDFY_CALL_BUTTON:
            request_data = request.POST

            if request_data:
                if request.FILES and request.FILES.get('image'):
                    banner_image = request.FILES['image']
                    _, file_extension = os.path.splitext(banner_image.name)

                    remote_path = 'autodebet_idfy_call_button/image{}'.format(file_extension)
                    image = Image()
                    image.image_source = obj.pk
                    image.image_type = remote_path.split('/image')[0]
                    image.url = remote_path
                    image.save()

                    obj.parameters['image_id'] = image.id
                    obj.parameters['image_type'] = image.image_type
                    obj.parameters['image_url'] = image.image_url

                    file = functions.upload_handle_media(banner_image, "tutorial/image")
                    if file:
                        upload_file_to_oss(
                            settings.OSS_MEDIA_BUCKET, file['file_name'], remote_path
                        )
        elif obj.feature_name == FeatureNameConst.ONEKLIK_BCA:
            obj.is_active = form.cleaned_data['is_active']
            slack_message = " OneKlik BCA Feature is Turned OFF"
            if obj.is_active:
                slack_message = " OneKlik BCA Feature is Turned ON"

            send_slack_bot_message("#oneklik_alert", slack_message)
        elif obj.feature_name == FeatureNameConst.PAYMENT_METHOD_SWITCH:
            form_data = json.loads(form.cleaned_data.get('form_data', '{}'))
            obj.parameters['payment_method'] = [
                {'bank': bank, 'vendor': vendor}
                for bank, vendor in form_data.get('switches', {}).items()
            ]
            obj.is_active = form.cleaned_data['is_active']
            obj.parameters['schedule_switch'] = json.loads(form.cleaned_data['schedule_switch'])
        elif obj.feature_name == ChannelingFeatureNameConst.CREDIT_SCORE_CONVERSION:
            if change:
                obj._old_instance = self.model.objects.get(pk=obj.pk)

        obj.save()

    def preview_image(self, obj):
        return mark_safe('<img src="{url}" width="{width}" />'.format(
            url=obj.image_url,
            width=300
        )
        )

    def get_inline_instances(self, request, obj=None):
        _inlines = super().get_inline_instances(request, obj=None)
        custom_inline = GrabProgramFeatureSettingInline(self.model, self.admin_site)
        if obj.feature_name == FeatureNameConst.GRAB_DEDUCTION_SCHEDULE:
            _inlines.append(custom_inline)
        return _inlines

    def get_readonly_fields(self, request, obj=None):
        if obj.feature_name in {
            FeatureNameConst.GRAB_DEDUCTION_SCHEDULE,
            FeatureNameConst.GRAB_INTELIX_CALL,
            FeatureNameConst.GRAB_FILE_TRANSFER_CALL,
            FeatureNameConst.GRAB_STOP_REGISTRATION,
            FeatureNameConst.GRAB_REFERRAL_PROGRAM,
            FeatureNameConst.GRAB_AI_RUDDER_CALL,
            FeatureNameConst.GRAB_DISBURSEMENT_RETRY,
        }:
            self.readonly_fields = ('feature_name',)
            return self.readonly_fields
        return super().get_readonly_fields(request, obj)

    def log_change(self, request, obj, message):
        if obj.feature_name == ChannelingFeatureNameConst.CREDIT_SCORE_CONVERSION:
            old_obj = obj._old_instance
            changes = []

            for field in obj._meta.fields:
                if field.name == "parameters":
                    params_changes = []
                    old_params = getattr(old_obj, field.name)
                    new_params = getattr(obj, field.name)
                    for channeling_type in set(old_params.keys()) | set(new_params.keys()):
                        old_value = old_params.get(channeling_type)
                        new_value = new_params.get(channeling_type)
                        if old_value != new_value:
                            params_changes.append(f"{channeling_type}: '{old_value}' → '{new_value}'")

                    if params_changes:
                        changes.append(f"{field.name}: * " + " *".join(params_changes))
                else:
                    old_value = getattr(old_obj, field.name)
                    new_value = getattr(obj, field.name)
                    if old_value != new_value and field.name not in ['cdate', 'udate']:
                        changes.append(f"{field.name}: '{old_value}' → '{new_value}'")

            message = "Changed: - " + " -".join(changes)

        super().log_change(request, obj, message)


class ExpiryTokenSettingForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = ("__all__")

    def clean_parameters(self):
        data = self.cleaned_data['parameters']
        value = data.get(EXPIRY_SETTING_KEYWORD, None) if data else None
        if not (isinstance(value, int) and value >= 0):
            raise forms.ValidationError("Invalid parameters")

        return data


class SalesOpsSettingSerializer(serializers.Serializer):
    monetary_percentages = serializers.CharField(required=True)
    recency_percentages = serializers.CharField(required=True)
    autodial_rpc_assignment_delay_hour = serializers.IntegerField(required=True)
    lineup_min_available_limit = serializers.IntegerField(required=True)
    lineup_min_available_days = serializers.IntegerField(required=True)
    lineup_max_used_limit_percentage = serializers.FloatField(required=True)
    lineup_delay_paid_collection_call_day = serializers.IntegerField(required=True)
    lineup_loan_restriction_call_day = serializers.IntegerField(required=True)
    lineup_and_autodial_non_rpc_attempt_count = serializers.IntegerField(required=True)
    lineup_and_autodial_non_rpc_delay_hour = serializers.IntegerField(required=True)
    lineup_and_autodial_non_rpc_final_delay_hour = serializers.IntegerField(required=True)
    lineup_and_autodial_rpc_delay_hour = serializers.IntegerField(required=True)

    @staticmethod
    def validate_percentages(value):
        try:
            percentages = get_list_int_by_str(value)
        except Exception as e:
            raise serializers.ValidationError(f"Exception setting config: {e}")
        if sum(percentages) != 100:
            raise serializers.ValidationError(
                "Sum of percentages config should be 100 percent"
            )

    def validate_monetary_percentages(self, value):
        self.validate_percentages(value)
        return value

    def validate_recency_percentages(self, value):
        self.validate_percentages(value)
        return value


class SalesOpsSettingForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = "__all__"

    serializer_class = SalesOpsSettingSerializer

    def clean_parameters(self):
        parameters = self.cleaned_data['parameters']
        try:
            self.serializer_class(data=parameters).is_valid(raise_exception=True)
        except ValidationError as e:
            raise forms.ValidationError(e)
        return parameters


class BypassLenderByProductLineSettingForm(forms.ModelForm):
    """
    Setting form for
    FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE
    """

    class Meta:
        model = FeatureSetting
        fields = "__all__"

    def clean(self):
        super(BypassLenderByProductLineSettingForm, self).clean()
        parameters = self.cleaned_data.get('parameters')
        if parameters is None and 'parameters' in self.cleaned_data:
            self.cleaned_data['parameters'] = {}
            return self.cleaned_data

        if not isinstance(parameters, dict):
            raise forms.ValidationError({
                'parameters': 'Invalid json format. {"<product_line_code>": <lender_current_id>}'
            })

        self.validate_product_lines()
        self.validate_lender_ids()
        return self.cleaned_data

    def validate_product_lines(self):
        product_line_codes = self.cleaned_data['parameters'].keys()
        valid_codes = ProductLine.objects.filter(product_line_code__in=product_line_codes) \
            .values_list('product_line_code', flat=True)
        different_codes = [int(code) for code in product_line_codes if int(code) not in valid_codes]
        if len(different_codes) > 0:
            raise forms.ValidationError({
                'parameters': 'Invalid product lines: {}'.format(different_codes)
            })

    def validate_lender_ids(self):
        lender_ids = self.cleaned_data['parameters'].values()
        valid_ids = LenderCurrent.objects.filter(id__in=lender_ids) \
            .values_list('id', flat=True)
        different_ids = [id for id in lender_ids if id not in valid_ids]
        if len(different_ids) > 0:
            raise forms.ValidationError({
                'parameters': 'Invalid lender ids: {}'.format(different_ids)
            })


class RobocallTemplateAdmin(JuloModelAdmin):
    list_display = (
        'template_name',
        'text',
        'is_active',
        'used_count',
        'template_category',
        'start_date',
        'end_date',
    )
    readonly_fields = ('added_by',)

    def used_count(self, obj):
        return obj.payment_set.count()

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False


class WarningUrlAdmin(JuloModelAdmin):
    list_display = (
        ("short_url", 'phone', 'email', 'loan', 'status', 'cdate', 'name', 'warning_method', 'url_type', 'is_enabled')
    )
    readonly_fields = ("customer", 'cdate', 'url', 'warning_method', 'url_type')

    def name(self, obj):
        return obj.customer.fullname

    def email(self, obj):
        return obj.customer.email

    def phone(self, obj):
        return obj.customer.phone

    def loan(self, obj):
        return Loan.objects.filter(customer=obj.customer).order_by('id').last()

    def status(self, obj):
        return Loan.objects.filter(customer=obj.customer).order_by('id').last().loan_status


class ExperimentSettingAdmin(JuloModelAdmin):
    list_display = ("code", "name", "type", "action", "start_date", "end_date", "is_active",)
    readonly_fields = ('code',)
    list_filter = ('is_active',)
    search_fields = ('code', 'type', 'action')
    ordering = ('cdate',)

    def get_form(self, request, obj=None, **kwargs):
        if obj and obj.code == ExperimentConst.CHECKOUT_EXPERIENCE_EXPERIMENT:
            self.form = CheckoutExperimentForm

        if obj and obj.code in (ExperimentConst.PRIMARY_SMS_VENDORS_EXPERIMENT,
                                ExperimentConst.PRIMARY_OTP_SMS_VENDORS_EXPERIMENT):
            self.form = SmsAbExperimentForm
        elif obj and obj.code == ExperimentConst.ROBOCALL_1WAY_VENDORS_EXPERIMENT:
            self.form = Robocall1WayVendorExperimentForm
        elif obj and obj.code in (
            ExperimentConst.SHOPEE_WHITELIST_EXPERIMENT,
            ExperimentConst.AUTODEBET_ACTIVATION_EXPERIMENT,
            ExperimentConst.TOKO_SCORE_EXPERIMENT,
            ExperimentConst.LANNISTER_EXPERIMENT,
        ):
            self.exclude = ('action',)

        return super(ExperimentSettingAdmin, self).get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        is_trigger_send_data_to_moengage = False
        if obj.code == MinisquadExperimentConst.LATE_FEE_EARLIER_EXPERIMENT:
            if change and 'is_active' in form.changed_data:
                is_trigger_send_data_to_moengage = True
        obj.save()
        if is_trigger_send_data_to_moengage:
            from juloserver.moengage.tasks import (
                send_user_attribute_late_fee_experiment_changed_is_active)

            send_user_attribute_late_fee_experiment_changed_is_active.delay()


class PaymentExperimentAdmin(JuloModelAdmin):
    list_display = (
        ("cdate", "udate", "payment_id", "experiment_setting_code", "note_text")
    )
    list_filter = ('cdate', 'payment_id')
    search_fields = ('payment', 'experiment_setting',)
    ordering = ('cdate',)

    def experiment_setting_code(self, obj):
        return obj.experiment_setting.code


class JuloContactDetailForm(forms.ModelForm):
    sunday = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label='Sunday from:', required=False)
    sunday_to = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label=' to:', required=False)
    monday = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label='Monday from:', required=False)
    monday_to = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label=' to:', required=False)
    tuesday = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label='Tuesday from:', required=False)
    tuesday_to = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label=' to:', required=False)
    wednesday = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label='Wednesday from:', required=False)
    wednesday_to = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label=' to:', required=False)
    thursday = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label='Thursday from:', required=False)
    thursday_to = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label=' to:', required=False)
    friday = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label='Friday from:', required=False)
    friday_to = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label=' to:', required=False)
    saturday = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label='Saturday from:', required=False)
    saturday_to = forms.TimeField(
        widget=forms.widgets.TimeInput(attrs={'type': 'time'}), label=' to:', required=False)

    email_ids = SimpleArrayField(forms.EmailField(), required=False,
                                 widget=forms.widgets.EmailInput(attrs={'size': 75}),
                                 help_text=_('mail@gmail.com,mail@yahoo.com,mail@live.com')
                                 )
    phone_numbers = SimpleArrayField(forms.CharField(), required=False,
                                     widget=forms.widgets.TextInput(attrs={'size': 75}),
                                     help_text=_('+62 97159xxxxx,(62) 97159xxxxx,97159xxxxx'))

    def get_time_or_none(self, time_str):
        if time_str is None:
            return None
        else:
            try:
                time_obj = time.strptime(time_str, '%H:%M:%S')
                return datetime.time(hour=time_obj.tm_hour,
                                     minute=time_obj.tm_min)
            except Exception as e:
                return None

    def get_chat_availablitity(self, instance):
        days_range = {
            'monday': ['monday', 'monday_to'],
            'tuesday': ['tuesday', 'tuesday_to'],
            'wednesday': ['wednesday', 'wednesday_to'],
            'thursday': ['thursday', 'thursday_to'],
            'friday': ['friday', 'friday_to'],
            'saturday': ['saturday', 'saturday_to'],
            'sunday': ['sunday', 'sunday_to'],
        }
        build_update_data = {}
        try:
            chat_availability = instance.chat_availability
            for (key, value) in list(chat_availability.items()):
                for (daykey, dayval) in enumerate(days_range[str(key)]):
                    build_update_data[dayval] = self.get_time_or_none(value[int(daykey)])
        except Exception as e:
            logger.error(str(e))
        return build_update_data

    def __init__(self, *args, **kwargs):
        instance = kwargs.get('instance', None)
        build_update_data = self.get_chat_availablitity(instance)
        kwargs.update(initial=build_update_data)
        super(JuloContactDetailForm, self).__init__(*args, **kwargs)

    class Meta(object):
        model = JuloContactDetail
        fields = [
            'title',
            'link_url',
            'image_url',
            'description',
            'address',
            'rich_text',
            'email_ids',
            'phone_numbers',
            'contact_us_text',
            'monday',
            'monday_to',
            'tuesday',
            'tuesday_to',
            'wednesday',
            'wednesday_to',
            'thursday',
            'thursday_to',
            'friday',
            'friday_to',
            'saturday',
            'saturday_to',
            'sunday',
            'sunday_to',
        ]
        exclude = ['chat_availability']
        widgets = {
            'address': forms.Textarea(attrs={'cols': 50, 'rows': 5}),
        }

    def time_or_none(self, time):
        if time is not None:
            return str(time)
        return None

    def build_chat_availability(self, cleaned_data):
        return {
            'monday': [self.time_or_none(cleaned_data['monday']),
                       self.time_or_none(cleaned_data['monday_to'])],
            'tuesday': [self.time_or_none(cleaned_data['tuesday']),
                        self.time_or_none(cleaned_data['tuesday_to'])],
            'wednesday': [self.time_or_none(cleaned_data['wednesday']),
                          self.time_or_none(cleaned_data['wednesday_to'])],
            'thursday': [self.time_or_none(cleaned_data['thursday']),
                         self.time_or_none(cleaned_data['thursday_to'])],
            'friday': [self.time_or_none(cleaned_data['friday']),
                       self.time_or_none(cleaned_data['friday_to'])],
            'saturday': [self.time_or_none(cleaned_data['saturday']),
                         self.time_or_none(cleaned_data['saturday_to'])],
            'sunday': [self.time_or_none(cleaned_data['sunday']),
                       self.time_or_none(cleaned_data['sunday_to'])],
        }

    def save(self, commit=True):
        m = super(JuloContactDetailForm, self).save(commit=False)
        m.chat_availability = self.build_chat_availability(self.cleaned_data)
        if commit:
            m.save()
        return m


class JuloContactDetailAdmin(JuloModelAdmin):
    exclude = ('chat_availability',)
    form = JuloContactDetailForm

    fieldsets = [(None, {'fields': [
        'section',
        'title',
        'link_url',
        'image_url',
        'show_image',
        'description',
        'address',
        'rich_text',
        'email_ids',
        'phone_numbers',
        'contact_us_text',
        'order_priority',
        'visible',
    ]}), ('Chat Timing', {'fields': (
        ('monday', 'monday_to'),
        ('tuesday', 'tuesday_to'),
        ('wednesday', 'wednesday_to'),
        ('thursday', 'thursday_to'),
        ('friday', 'friday_to'),
        ('saturday', 'saturday_to'),
        ('sunday', 'sunday_to'),
    )})]

    def has_add_permission(self, request):
        return not JuloContactDetail.objects.exists()


class FaqItemInline(admin.TabularInline):
    model = FaqItem
    extra = 0
    fields = ('question', 'order_priority')
    readonly_fields = ('question', 'order_priority')
    show_change_link = True

    def has_add_permission(self, request):
        return False


class FaqSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'order_priority', 'visible', 'is_security_faq')
    list_filter = ('visible',)
    inlines = [FaqItemInline]


class FaqSubTitleInline(admin.TabularInline):
    model = FaqSubTitle
    extra = 0
    fields = ('title', 'order_priority')
    readonly_fields = ('title', 'order_priority')
    show_change_link = True

    def has_add_permission(self, request):
        return False


class FaqItemAdmin(admin.ModelAdmin):
    list_display = ('question', 'order_priority', 'visible', 'is_security_faq')
    list_filter = ('section', 'visible')
    inlines = [FaqSubTitleInline]

    def is_security_faq(self, obj):
        return obj.section.is_security_faq

    is_security_faq.boolean = True


class FaqSubTitleAdmin(admin.ModelAdmin):
    list_display = ('title', 'order_priority', 'visible')
    list_filter = ('faq', 'visible')


class PartnerBankAccountItem(JuloModelAdmin):
    list_display = (
        'id', 'partner', 'bank_name', 'bank_branch',
        'bank_account_number', 'name_in_bank', 'phone_number'
    )

    list_filter = ('partner',)

    search_fields = [
        'id',
        'partner',
        'bank_account_number',
    ]

    readonly_fields = (
        'partner',
    )


class DocumentAdmin(JuloModelAdmin):
    list_display = (
        'document_id',
        'document_source_id',
        'document_type',
        'url',
    )

    def document_id(self, obj):
        return obj.id

    def document_source_id(self, obj):
        return obj.document_source


class PaybackTransactionStatusHistoryInline(admin.TabularInline):
    model = PaybackTransactionStatusHistory
    extra = 0
    fields = ('old_status', 'new_status', 'cdate',)
    readonly_fields = ('old_status', 'new_status', 'cdate',)
    show_change_link = False

    def has_add_permission(self, request):
        return False

    def old_status(self, obj):
        des = PaybackTransStatus.get_mapped_description(obj.old_status_code)
        return "%s - %s" % (obj.old_status_code, des)

    def new_status(self, obj):
        des = PaybackTransStatus.get_mapped_description(obj.new_status_code)
        return "%s - %s" % (obj.new_status_code, des)


class PaybackTransactionAdmin(JuloModelAdmin):
    list_display = (
        'transaction_id',
        'customer_link',
        'payment_link',
        'loan_link',
        'status',
        'payback_service',
        'is_processed',
    )
    list_filter = (
        'payback_service',
        'status_code',
        'is_processed',
    )
    search_fields = (
        'transaction_id',
        'customer__fullname',
    )
    readonly_fields = (
        'payment_method',
    )
    ordering = ('-id',)
    inlines = [PaybackTransactionStatusHistoryInline]

    def status(self, obj):
        des = PaybackTransStatus.get_mapped_description(obj.status_code)
        return "%s - %s" % (obj.status_code, des)

    status.short_description = "Status"

    def customer_link(self, obj):
        try:
            return self.change_form_link(obj.customer, 'customer')
        except:
            return None

    customer_link.short_description = "Customer"

    def payment_link(self, obj):
        try:
            return self.change_form_link(obj.payment, "payment")
        except:
            return None

    payment_link.short_description = "Payment"

    def loan_link(self, obj):
        try:
            return self.change_form_link(obj.loan, 'loan')
        except:
            return None

    loan_link.short_description = "Loan"


class CreditScoreExperimentAdmin(admin.ModelAdmin):
    list_display = ('id', 'link_application', 'link_experiment', 'link_credit_score')

    def link_application(self, obj):
        try:
            link = reverse(
                "admin:julo_application_change",
                args=[obj.credit_score.application.id]
            )
            return mark_safe(
                '<a href="%s">%s</a>' % (link, obj.credit_score.application.id))
        except:
            return None

    def link_credit_score(self, obj):
        link = reverse(
            "admin:julo_creditscore_change", args=[obj.credit_score.id])
        return mark_safe('<a href="%s">%s</a>' % (link, obj.credit_score.id))

    def link_experiment(self, obj):
        link = reverse(
            "admin:julo_experiment_change", args=[obj.experiment.id])
        return mark_safe('<a href="%s">%s</a>' % (link, obj.experiment.code))


class CreditScoreForm(forms.ModelForm):
    application_id = forms.CharField(max_length=100)

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.get('instance', None)
        form = super(CreditScoreForm, self).__init__(*args, **kwargs)
        try:
            self.initial['application_id'] = self.instance.application.id
        except:
            pass

    class Meta(object):
        model = CreditScore
        fields = [
            'application_id',
            'score',
            'message',
            'products_str',
            'income_prediction_score',
            'thin_file_score',
            'inside_premium_area',
            'score_tag',
            'credit_limit',
            'failed_checks',
        ]
        exclude = ['id', 'application']

    def clean(self):
        instance = self.instance
        application = instance.application
        application_id = None
        try:
            application_id = int(self.cleaned_data.get('application_id'))
        except:
            raise forms.ValidationError("Provide a valid application Id")
        if application_id:
            application_obj = Application.objects.filter(id=application_id).first()
            if not application_obj:
                raise forms.ValidationError("Provide a valid application Id")
            if application and application_obj.id == application.id:
                return self.cleaned_data

            credit_score_obj = CreditScore.objects.filter(application=application_obj)
            if credit_score_obj:
                raise forms.ValidationError("Application cont have multiple Credit Score")
            else:
                instance.application = application_obj
        else:
            raise forms.ValidationError("Provide a valid application Id")


class CreditScoreAdmin(JuloModelAdmin):
    form = CreditScoreForm
    list_display = (
        'id',
        'application_link',
        'score',
        'score_tag',
        'credit_limit',
        'failed_checks',
        'credit_matrix_id'
    )
    readonly_fields = ('application',)

    def application_link(self, obj):
        return self.change_form_link(obj.application, 'application')

    ordering = ('-cdate',)


class SphpTemplateAdmin(JuloModelAdmin):
    list_display = (
        'id',
        'product_name',
    )


class FrontendViewAdmin(JuloModelAdmin):
    list_display = (
        'id',
        'label_name',
        'label_value',
    )

    exclude = (
        'label_name',
        'label_code',
    )


class StatusLabelAdmin(JuloModelAdmin):
    ordering = ('status',)


class DigisignConfigurationForm(forms.ModelForm):
    class Meta(object):
        model = DigisignConfiguration
        fields = ("product_selection", "is_active")
        readonly_fields = ("product_selection",)

    def save(self, commit=True):
        instance = super(DigisignConfigurationForm, self).save(commit=False)
        instance.save()

        # Create digisign config history
        DigisignConfigurationHistory.objects.create(
            product_selection=instance.product_selection,
            is_active=instance.is_active
        )

        #     filter_ = dict(
        #         application_status__lt=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
        #     )

        #     if instance.product_selection == "STL":
        #         filter_['product_line__in'] = list(ProductLineCodes.stl())
        #     elif instance.product_selection == "MTL":
        #         filter_['product_line__in'] = list(ProductLineCodes.mtl())
        #     elif instance.product_selection == "BRI":
        #         filter_['product_line__in'] = list(ProductLineCodes.bri())
        #     elif instance.product_selection == "GRAB":
        #         filter_['product_line__in'] = list(ProductLineCodes.grab())
        #     elif instance.product_selection == "GRABF":
        #         filter_['product_line__in'] = list(ProductLineCodes.grabfood())
        #     elif instance.product_selection == "LOC":
        #         filter_['product_line__in'] = list(ProductLineCodes.loc())
        #     elif instance.product_selection == "LAKU":
        #         filter_['product_line__in'] = list(ProductLineCodes.laku6())
        #     elif instance.product_selection == "ICARE":
        #         filter_['product_line__in'] = list(ProductLineCodes.icare())
        #     elif instance.product_selection == "AXIATA":
        #         filter_['product_line__in'] = list(ProductLineCodes.axiata())
        #     elif instance.product_selection == "PEDE":
        #         filter_['product_line__in'] = list(ProductLineCodes.pede())
        #     elif instance.product_selection == "PEDEMTL":
        #         filter_['product_line__in'] = list(ProductLineCodes.pedemtl())
        #     elif instance.product_selection == "PEDESTL":
        #         filter_['product_line__in'] = list(ProductLineCodes.pedestl())
        #     else:
        #         filter_['product_line__product_line_type'] = instance.product_selection

        #     customers = Application.objects.filter(**filter_).values_list('customer_id', flat=True).distinct()
        #     for customer in customers:
        #         customer = Customer.objects.get(pk=customer)
        #         customer.is_digisign_affected = instance.is_active
        #         customer.save()

        return instance


class DigisignConfigurationAdmin(ReadonlyJuloModelAdmin):
    form = DigisignConfigurationForm
    list_display = (
        "id",
        "product_selection",
        "is_active"
    )
    readonly_fields = ('product_selection',)
    ordering = ("-is_active",)


class DigisignConfigurationHistoryAdmin(ReadonlyJuloModelAdmin):
    list_display = (
        "id",
        "product_selection",
        "is_active"
    )
    ordering = ("-is_active",)


class ProductLineInline(admin.TabularInline):
    model = CreditMatrixProductLine
    extra = 1


class CreditMatrixForm(forms.ModelForm):
    min_threshold = forms.FloatField(help_text="Min Threshold => probabilty")
    max_threshold = forms.FloatField(help_text="probabilty <= Max Threshold")

    class Meta(object):
        model = CreditMatrix
        fields = ('score', 'min_threshold', 'max_threshold', 'score_tag',
                  'parameter', 'priority', 'message', 'is_premium_area',
                  'credit_matrix_type', 'product', 'is_fdc')


class CreditMatrixAdmin(JuloModelAdmin):
    form = CreditMatrixForm
    inlines = (ProductLineInline,)
    list_display = (
        "id",
        "score",
        "min_threshold",
        "max_threshold",
        "score_tag",
        "message",
        "is_premium_area",
        "is_fdc",
        "credit_matrix_type",
        "product",
        "parameter",
        "priority",
    )

    change_list_template = "custom_admin/upload_btn_change_list.html"

    def get_urls(self):
        urls = super(CreditMatrixAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES["csv_file"]
            try:
                reader = csv.DictReader(csv_file.read().decode().splitlines())
                product_line_map = {}
                credit_matrix_data = []
                current_credit_matrix_data = []
                credit_matrix_product_line_data = []

                product_filter_keys = [
                    'product_code',
                    'origination_fee_pct',
                    'product_line',
                    'interest',
                    'late_fee_pct'
                ]
                transaction_type_keys = [TransactionType.SELF,
                                         TransactionType.OTHER,
                                         TransactionType.PPOB]

                version = CreditMatrix.objects.next_version()
                for line in reader:
                    transaction_type = line['transaction_type']
                    interest = line['interest']

                    product_line_type = line['product_line']
                    product_line_code = product_line_map.get(product_line_type)

                    # try to create a map between product_line_code and product_line_type
                    if not product_line_code:
                        product_line = ProductLine.objects.get(product_line_type=product_line_type)
                        product_line_map[product_line_type] = product_line.product_line_code
                        product_line_code = product_line.product_line_code

                    product_lines = [
                        ProductLineCodes.J1,
                        ProductLineCodes.JULOVER,
                    ]
                    # Skip column interest_other for other products
                    if product_line_code not in product_lines and \
                            transaction_type == TransactionType.OTHER:
                        continue
                    # new credit matrix object with data from file
                    credit_matrix_record = CreditMatrix(
                        score=line['score'],
                        min_threshold=line['min_threshold'],
                        max_threshold=line['max_threshold'],
                        is_premium_area=int(line['is_premium_area']),
                        credit_matrix_type=line['credit_matrix_type'],
                        is_salaried=int(line['is_salaried']),
                        is_fdc=int(line['is_fdc']),
                        score_tag=line['score_tag'],
                        message=line['message'],
                        parameter=line['parameter'],
                        priority=line['Priority'],
                        transaction_type=line['transaction_type'],
                        version=version
                    )

                    current_credit_matrix_record = CurrentCreditMatrix(
                        transaction_type=transaction_type
                    )

                    # append to list to prepare for bulk create
                    credit_matrix_data.append(credit_matrix_record)
                    current_credit_matrix_data.append(current_credit_matrix_record)

                    # separate error log between none product_code and not none product_code
                    if product_filter_keys and product_line_code not in ProductLineCodes.ctl():
                        product_filter = {key: line[key] for key in product_filter_keys}
                        if 'product_code' in product_filter and not product_filter['product_code']:
                            # remove key if product is empty
                            product_filter.pop('product_code')
                        if 'product_line' in product_filter:
                            # replace product_line_code instead of product_line_type
                            product_filter.pop('product_line')
                            product_filter['product_line_id'] = product_line_code
                        if 'interest' in product_filter:
                            # convert interest yearly
                            product_filter['interest_rate'] = py2round(float(product_filter['interest']) * 12, 2)
                            product_filter.pop('interest')
                        mismatch_value = ""

                        # try to filter with pk first
                        if 'product_code' in product_filter:
                            product = ProductLookup.objects.get_or_none(pk=product_filter['product_code'])
                            if not product:
                                self.message_user(request,
                                                  "Product code doesn't exist: %s" % product_filter['product_code'],
                                                  level="ERROR")
                                return redirect("..")
                            # if any mismatch value, return a None product
                            else:
                                for key, val in list(product_filter.items()):
                                    db_value = getattr(product, key)
                                    if str(val) != str(db_value):
                                        product = None
                                        mismatch_value = {key: (val, db_value)}
                                        break
                        # find with data
                        else:
                            product = ProductLookup.objects.filter(**product_filter).last()

                        if not product:
                            self.message_user(request,
                                              "Product code mismatch: %s, %s" % (str(product_filter), mismatch_value),
                                              level="ERROR")
                            return redirect("..")

                        credit_matrix_record.product = product

                    # CurrentCreditMatrix
                    credit_matrix_product_line_data.append(
                        CreditMatrixProductLine(
                            product_id=product_line_code,
                            interest=interest,
                            min_duration=line['min_duration'],
                            max_duration=line['max_duration'],
                            min_loan_amount=line['min_loan_amount'],
                            max_loan_amount=line['max_loan_amount'],
                        )
                    )

                with transaction.atomic():
                    # Remove all entries in current credit matrix before uploading new matrix
                    CurrentCreditMatrix.objects.all().delete()

                    for idx, credit_matrix in enumerate(credit_matrix_data):
                        credit_matrix.save()
                        current_credit_matrix_data[idx].credit_matrix_id = credit_matrix.pk
                        current_credit_matrix_data[idx].save()
                        if credit_matrix_product_line_data[idx].product_id:
                            credit_matrix_product_line_data[idx].credit_matrix_id = credit_matrix.pk
                            credit_matrix_product_line_data[idx].save()
            except Exception as error:
                self.message_user(request, "Something went wrong with file: %s" % str(error),
                                  level="ERROR")
            else:
                self.message_user(request, "Your csv file has been imported")
            return redirect("..")
        form = CsvImportForm()
        payload = {"form": form}
        return render(
            request, "custom_admin/upload_config_form.html", payload
        )


class CreditMatrixRepeatForm(forms.ModelForm):
    class Meta(object):
        model = CreditMatrixRepeat
        fields = (
            'customer_segment',
            'product_line',
            'transaction_method',
            'provision',
            'min_tenure',
            'max_tenure',
            'interest',
            'repeat_level',
            'total_utilization_rate',
            'aging',
            'fdc_status',
            'is_active',
            'version',
        )


class CreditMatrixRepeatAdmin(JuloModelAdmin):
    form = CreditMatrixRepeatForm
    list_display = (
        'id',
        'customer_segment',
        'product_line',
        'transaction_method',
        'provision',
        'min_tenure',
        'max_tenure',
        'interest',
        'repeat_level',
        'total_utilization_rate',
        'aging',
        'show_tenure',
        'fdc_status',
        'is_active',
        'version',
    )
    readonly_fields = (
        'customer_segment',
        'product_line',
        'transaction_method',
        'provision',
        'min_tenure',
        'max_tenure',
        'interest',
        'repeat_level',
        'total_utilization_rate',
        'aging',
        'show_tenure',
        'fdc_status',
        'version',
    )
    change_list_template = "custom_admin/upload_btn_change_list.html"

    def get_urls(self):
        urls = super(CreditMatrixRepeatAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            try:
                csv_file = request.FILES["csv_file"]
                reader = csv.DictReader(csv_file.read().decode().splitlines())

                product_lines = set()
                transaction_methods = set()
                csv_lines = []
                validations = []
                validate_non_duplicate_data = set()
                not_null_fields = {'product_line', 'transaction_method', 'customer_segment', 'provision', 'max_tenure', 'min_tenure', 'interest'}
                for line in reader:
                    csv_lines.append(line)
                    for field in not_null_fields:
                        if not line[field]:
                            validations.append("Field [" + field + "] Cannot be null")

                    if line['product_line']:
                        product_lines.add(line['product_line'])
                    if line['transaction_method']:
                        transaction_methods.add(line['transaction_method'])

                    key = "{}-{}-{}".format(line['customer_segment'], line['product_line'], line['transaction_method'])
                    # no duplicate row with same customer_segment, product_line, transaction_method allowed in 1 file
                    if key in validate_non_duplicate_data and line['customer_segment'] and line['product_line'] and line['transaction_method']:
                        validations.append(
                            "row for customer segment [{}], product_line [{}] and transaction_method [{}] already exist"
                            .format(
                                line['customer_segment'], line['product_line'], line['transaction_method']
                            )
                        )
                    validate_non_duplicate_data.add(key)

                if not csv_lines:
                    validations.append("CSV data Cannot be null")

                product_lines_result = ProductLine.objects.filter(product_line_code__in=product_lines)
                transaction_methods_result = TransactionMethod.objects.filter(
                    id__in=transaction_methods
                )

                # validate Foreign key input exist on db
                product_lines_validate = {int(obj.product_line_code):obj for obj in product_lines_result}
                transaction_methods_validate = {int(obj.id):obj for obj in transaction_methods_result}

                for transaction_method in transaction_methods:
                    if int(transaction_method) not in transaction_methods_validate:
                        validations.append("Transaction Method [" + transaction_method + "] Not found")

                for product_line in product_lines:
                    if int(product_line) not in product_lines_validate:
                        validations.append("Product Line [" + product_line + "] Not found")

                if validations:
                    self.message_user(
                        request,
                        "Something went wrong with file: %s" % str(validations),
                        level="ERROR"
                    )
                    return redirect("..")

                credit_matrix_repeat_lists = []
                for line in csv_lines:
                    old_credit_matrix_record = CreditMatrixRepeat.objects.filter(
                        customer_segment = line['customer_segment'],
                        product_line = product_lines_validate[int(line['product_line'])],
                        transaction_method = transaction_methods_validate[int(line['transaction_method'])],
                    ).order_by('-version').first()

                    credit_matrix_repeat_record = CreditMatrixRepeat(
                        customer_segment = line['customer_segment'],
                        product_line = product_lines_validate[int(line['product_line'])],
                        transaction_method = transaction_methods_validate[int(line['transaction_method'])],
                        provision = line['provision'],
                        max_tenure = line['max_tenure'],
                        min_tenure = line['min_tenure'],
                        interest = line['interest'],
                        version = old_credit_matrix_record.version + 1 if old_credit_matrix_record else 1,
                        repeat_level = line.get('repeat_level') or None,
                        total_utilization_rate = line.get('total_utilization_rate') or None,
                        aging = line.get('aging') or None,
                        fdc_status = line.get('fdc_status') or None,
                        show_tenure = line.get('show_tenure') or [],
                        is_active = True,
                    )

                    credit_matrix_repeat_lists.append(credit_matrix_repeat_record)

                with transaction.atomic():
                    if credit_matrix_repeat_lists:
                        """
                        1. Inserting to CreditMatrixRepeat,
                        2. Inserting the uploaded CSV URL & filename to Document table,
                        3. Upload to OSS
                        file will be saved with credit_matrix_repeat_upload-{date}.csv format
                        """
                        CreditMatrixRepeat.objects.bulk_create(credit_matrix_repeat_lists)
                        _, file_extension = os.path.splitext(csv_file.name)
                        date_formatted = int(datetime.date.today().strftime("%Y%m%d"))
                        report_type = "credit_matrix_repeat_upload"
                        file_name = '{}-{}.csv'.format(
                            report_type,
                            timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S"),
                        )
                        document_remote_filepath = 'creditmatrixrepeat/upload{}'.format(file_name)
                        file = functions.upload_handle_media(csv_file, "creditmatrixrepeat/upload")
                        Document.objects.create(
                            document_source=date_formatted,
                            document_type=report_type,
                            filename=file_name,
                            url=document_remote_filepath,
                        )
                        if file:
                            upload_file_to_oss(
                                settings.OSS_MEDIA_BUCKET,
                                file['file_name'],
                                document_remote_filepath
                            )

            except Exception as error:
                self.message_user(request, "Something went wrong with file: %s" % str(error),
                                  level="ERROR")
            else:
                self.message_user(request, "Your csv file has been imported")
            return redirect("..")
        form = CsvImportForm()
        payload = {"form": form}
        return render(
            request, "custom_admin/upload_config_form.html", payload
        )

    def get_actions(self, request):
        # Disable delete
        actions = super(CreditMatrixRepeatAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False


class HighScoreFullBypassAdmin(JuloModelAdmin):
    form = HighScoreFullBypassForm
    list_display = (
        "cm_version",
        "threshold",
        "is_premium_area",
        "is_salaried",
        "bypass_dv_x121",
        "customer_category",
    )
    add_form_template = 'core/high_score_full_bypass_form.html'
    change_form_template = 'core/high_score_full_bypass_form.html'

    def get_form(self, request, obj=None, **kwargs):
        self.form = HighScoreFullBypassForm
        self.fieldsets = (
            (
                None,
                {
                    'fields': (
                        'form_data',
                        'cm_version',
                        'threshold',
                        'is_premium_area',
                        'province',
                        'is_salaried',
                        'job_type',
                        'job_industry',
                        'job_description',
                        'bypass_dv_x121',
                        'customer_category',
                        'agent_assisted_partner_ids',
                        'partner_ids',
                    ),
                },
            ),
        )
        return super(HighScoreFullBypassAdmin, self).get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        save_form_hsfb(obj, form)
        obj.save()


class PartnerOriginationDataForm(forms.ModelForm):
    interest_rate = forms.FloatField()
    admin_fee = forms.FloatField()

    class Meta(object):
        model = PartnerOriginationData
        fields = ['id', 'origination_fee', 'interest_rate', 'admin_fee', 'partner']

    field_order = ['id', 'origination_fee', 'interest_rate', 'admin_fee', 'partner']

    def clean_partner(self):
        try:
            eval("ProductLineCodes.{}()".format(self.cleaned_data['partner']))
        except Exception:
            raise forms.ValidationError("partner doesn't have product line")

        return self.cleaned_data['partner']


class PartnerOriginationDataAdmin(JuloModelAdmin):
    form = PartnerOriginationDataForm

    list_display = (
        'id',
        'get_interest_rate',
        'get_admin_fee',
        'origination_fee',
        'partner',
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super(PartnerOriginationDataAdmin, self).get_form(request, obj, **kwargs)
        id = PartnerOriginationData.objects.all().last().id + 1
        form.base_fields['id'].initial = id
        form.base_fields['id'].disabled = True
        if obj:
            form.base_fields['interest_rate'].initial = self.get_interest_rate(obj)
            form.base_fields['admin_fee'].initial = self.get_admin_fee(obj)
        return form

    def get_interest_rate(self, obj):
        partner_product_lines = getattr(ProductLineCodes, obj.partner.name)()
        if partner_product_lines:
            for partner_product_line in partner_product_lines:
                product_line = ProductLine.objects.get_or_none(pk=partner_product_line)
                product_lookup = ProductLookup.objects.filter(
                    Q(origination_fee_pct=obj.origination_fee) &
                    Q(product_line=product_line.product_line_code))
                if product_lookup:
                    return product_lookup.last().interest_rate

    def get_admin_fee(self, obj):
        partner_product_lines = getattr(ProductLineCodes, obj.partner.name)()
        if partner_product_lines:
            for partner_product_line in partner_product_lines:
                product_line = ProductLine.objects.get_or_none(pk=partner_product_line)
                product_lookup = ProductLookup.objects.filter(
                    Q(origination_fee_pct=obj.origination_fee) &
                    Q(product_line=product_line))
                if product_lookup:
                    return product_lookup.last().admin_fee

    def save_model(self, request, obj, form, change):
        super(PartnerOriginationDataAdmin, self).save_model(request, obj, form, change)
        partner_origination_data = obj
        partner_origination_data.update_safely(
            partner=form.cleaned_data['partner'],
            origination_fee=form.cleaned_data['origination_fee'])
        partner_product_lines = getattr(ProductLineCodes, obj.partner.name)()
        if partner_product_lines:
            for partner_product_line in partner_product_lines:
                product_line = ProductLine.objects.get_or_none(pk=partner_product_line)
                product_lookup = ProductLookup.objects.filter(
                    Q(origination_fee_pct=obj.origination_fee) & Q(product_line=product_line))

                if not product_lookup:
                    product_profile = ProductProfile.objects.get_or_none(pk=product_line.product_profile.id)
                    params_product_name = {
                        "interest_value": 0.00,
                        "origination_value": obj.origination_fee,
                        "late_fee_value": 0.00,
                        "cashback_initial_value": 0.00,
                        "cashback_payment_value": 0.00
                    }
                    product_name = generate_product_name(params_product_name)
                    product_lookup_data = {
                        'product_name': product_name,
                        'interest_rate': form.cleaned_data['interest_rate'],
                        'origination_fee_pct': obj.origination_fee,
                        'late_fee_pct': 0,
                        'cashback_initial_pct': 0,
                        'cashback_payment_pct': 0,
                        'product_line': product_line,
                        'product_profile': product_profile,
                        'admin_fee': form.cleaned_data['admin_fee']
                    }
                    ProductLookup.objects.create(**product_lookup_data)
                else:
                    interest_rate = form.cleaned_data['interest_rate']
                    admin_fee = form.cleaned_data['admin_fee']
                    for product in product_lookup:
                        product.update_safely(interest_rate=interest_rate,
                                              admin_fee=admin_fee)


class FaceRecognitionForm(forms.ModelForm):
    class Meta(object):
        model = FaceRecognition
        fields = '__all__'

    def clean_brightness(self):
        if self.cleaned_data['brightness'] > 100 or self.cleaned_data['brightness'] < 0:
            raise forms.ValidationError("brightness can't more than 100, or less than 0")

        return self.cleaned_data['brightness']

    def clean_sharpness(self):
        if self.cleaned_data['sharpness'] > 100 or self.cleaned_data['sharpness'] < 0:
            raise forms.ValidationError("sharpness can't more than 100, or less than 0")

        return self.cleaned_data['sharpness']


class FaceRecognitionAdmin(JuloModelAdmin):
    form = FaceRecognitionForm
    list_display = (
        'id',
        'feature_name',
        'is_active',
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super(FaceRecognitionAdmin, self).get_form(request, obj, **kwargs)
        if obj.feature_name == 'face_recognition':
            if 'brightness' in form.base_fields:
                for val in ['sharpness', 'brightness', 'quality_filter']:
                    del form.base_fields[val]
        elif obj.feature_name == 'IndexFace Filter':
            form.base_fields['quality_filter'].required = True
            if 'brightness' in form.base_fields:
                for val in ['sharpness', 'brightness']:
                    del form.base_fields[val]
        elif obj.feature_name == 'IndexStorage Threshold':
            form.base_fields['sharpness'].required = True
            form.base_fields['brightness'].required = True
            if 'quality_filter' in form.base_fields:
                for val in ['quality_filter']:
                    del form.base_fields[val]
        return form

    def get_actions(self, request):
        # Disable delete
        actions = super(FaceRecognitionAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def has_add_permission(self, request, obj=None):
        return False


class ITIConfigurationForm(forms.ModelForm):
    form_data = forms.CharField(
        widget=forms.HiddenInput(attrs={'readonly': 'readonly'}),
        required=False)
    min_threshold = forms.FloatField(label="Min Threshold (in.)")
    max_threshold = forms.FloatField(label="Max Threshold (ex.)")
    min_income = forms.IntegerField(label="Min Income (in.)")
    max_income = forms.IntegerField(label="Max Income (ex.)")
    province = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'special-event-binary-setting-control_area'}))
    is_premium_area = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'is_premium_area', 'onclick': 'OnChangeIsPremiumArea(this)'}))
    is_salaried = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'is_salaried'}))
    job_description = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'job-description-control'}))
    job_industry = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'job-industry-control'}))
    job_type = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'special-event-binary-setting-control_job', 'id': 'job'}))
    partner_ids = forms.MultipleChoiceField(
        required=False, widget=forms.SelectMultiple(attrs={'class': 'partner-ids-control'})
    )
    agent_assisted_partner_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'agent-assisted-partner-ids-control'}),
    )

    class Meta(object):
        model = ITIConfiguration
        fields = (
            'iti_version',
            'min_threshold',
            'max_threshold',
            'min_income',
            'max_income',
            'is_active',
            "is_premium_area",
            "province",
            "is_salaried",
            "job_industry",
            "job_description",
            "customer_category",
            "partner_ids",
            "agent_assisted_partner_ids",
        )

    def __init__(self, *args, **kwargs):
        super(ITIConfigurationForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        selected_job_industry = []
        if args:
            selected_job_industry = copy(args[0].getlist('job_industry'))

        self.fields['form_data'].initial = json.dumps(JOB_MAPPING)
        self.fields['job_industry'].choices = JOB_INDUSTRY_LIST
        self.fields['job_description'].choices = JOB_DESC_LIST
        self.fields['job_type'].choices = JOB_TYPE
        self.fields['province'].choices = PROVINCE

        # add partner ids choice for iti configuration
        partners_active = (
            Partner.objects.filter(is_active=True, is_csv_upload_applicable=False)
            .exclude(type='lender')
            .all()
            .values('id', 'name')
        )
        partner_choices = []
        for partner_active in partners_active:
            partner_choices.append((partner_active['id'], partner_active['name']))
        self.fields['partner_ids'].choices = partner_choices
        self.fields['agent_assisted_partner_ids'].choices = partner_choices
        try:
            if instance.parameters:
                self.fields['job_industry'].initial = instance.parameters.get('job_industry')
                self.fields['job_type'].initial = instance.parameters.get('job_type')
                self.fields['province'].initial = instance.parameters.get('province')
                self.fields['job_description'].initial = instance.parameters.get('job_description')
                selected_partner = []
                for key in instance.parameters.get('partner_ids'):
                    selected_partner.append(key)
                self.fields['partner_ids'].initial = selected_partner
                # QOALA PARTNERSHIP - Leadgen Agent Assisted 20-11-2024
                selected_agent_assisted_partner = []
                for key in instance.parameters.get('agent_assisted_partner_ids'):
                    selected_agent_assisted_partner.append(key)
                self.fields['agent_assisted_partner_ids'].initial = selected_agent_assisted_partner

        except Exception:
            self.fields['form_data'].initial = json.dumps(JOB_MAPPING)
            self.fields['job_industry'].choices = JOB_INDUSTRY_LIST
            self.fields['job_description'].choices = JOB_DESC_LIST
            self.fields['job_type'].choices = JOB_TYPE
            self.fields['province'].choices = PROVINCE
            self.fields['partner_ids'].choices = partner_choices
            self.fields['agent_assisted_partner_ids'].choices = partner_choices

        if self.fields['job_industry'].initial:
            for job_industry in self.fields['job_industry'].initial:
                if job_industry not in selected_job_industry:
                    selected_job_industry.append(job_industry)

        for job_industry in selected_job_industry:
            for job_desc_ele in JOB_MAPPING.get(job_industry, []):
                new_choice = "%s:%s" % (job_industry, job_desc_ele)
                self.fields['job_description'].choices.append((new_choice, new_choice))

    def clean(self):
        cleaned_data = super(ITIConfigurationForm, self).clean()
        return cleaned_data


class CsvImportForm(forms.Form):
    csv_file = forms.FileField()


class ITIConfigurationAdmin(JuloModelAdmin):
    form = ITIConfigurationForm
    list_display = (
        "iti_version",
        "is_active",
        "min_threshold_",
        "max_threshold_",
        "min_income_",
        "max_income_",
        "is_premium_area",
        "is_salaried",
        "customer_category",
    )
    add_form_template = 'core/iti_form.html'
    change_form_template = 'core/iti_form.html'
    change_list_template = "custom_admin/upload_btn_change_list.html"

    def get_urls(self):
        urls = super(ITIConfigurationAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES["csv_file"]
            try:
                reader = csv.DictReader(csv_file.read().decode().splitlines())
                iti_data = []
                for line in reader:
                    data = line
                    data['is_premium_area'] = True if data['is_premium_area'] == '1' else False
                    data['is_salaried'] = True if data['is_salaried'] == '1' else False
                    data['is_active'] = True if data['is_active'] == '1' else False
                    iti_data.append(ITIConfiguration(**data))

                with transaction.atomic():
                    ITIConfiguration.objects.bulk_create(iti_data)
            except Exception as error:
                self.message_user(request, "Something went wrong with file: %s" % str(error),
                                  level="ERROR")
            else:
                self.message_user(request, "Your csv file has been imported")
            return redirect("..")
        form = CsvImportForm()
        payload = {"form": form}
        return render(
            request, "custom_admin/upload_config_form.html", payload
        )

    def min_threshold_(self, obj):
        return obj.min_threshold

    min_threshold_.short_description = "Min Threshold (in.)"

    def max_threshold_(self, obj):
        return obj.max_threshold

    max_threshold_.short_description = "Max Threshold (ex.)"

    def min_income_(self, obj):
        return obj.min_income

    min_income_.short_description = "Min Income (in.)"

    def max_income_(self, obj):
        return obj.max_income

    max_income_.short_description = "Max Income (ex.)"

    def save_model(self, request, obj, form, change):
        save_form_iti(obj, form)
        obj.save()


def save_form_iti(obj, form):
    # check if is premium area is blank or not

    cleaned_data = form.cleaned_data

    job_type = JOB_TYPE
    fix_job_type = []
    salaried_job = ['Pegawai swasta', 'Pegawai negeri']
    provinces = []

    if cleaned_data['is_premium_area'] == True:
        cleaned_data['province'] = None
    else:
        if len(cleaned_data['province']) == 0:
            for provinsi in PROVINCE:
                provinces.append(provinsi[0])
            cleaned_data['province'] = provinces

    if cleaned_data['is_salaried'] == False:
        for job in job_type:
            if job[0] not in salaried_job:
                fix_job_type.append(job[0])
    else:
        fix_job_type = salaried_job

    cleaned_data.pop('form_data')
    cleaned_data['job_type'] = fix_job_type
    obj.parameters = cleaned_data


class SiteMapContentForm(forms.ModelForm):
    label_name = forms.CharField()
    label_url = forms.CharField()

    class Meta(object):
        model = SiteMapJuloWeb
        fields = ('id', 'label_name', 'label_url')


class SiteMapContentAdmin(JuloModelAdmin):
    form = SiteMapContentForm
    list_display = (
        'id', 'label_name', 'label_url'
    )

    change_list_template = "custom_admin/upload_btn_change_list.html"

    def get_urls(self):
        urls = super(SiteMapContentAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            if 'csv_file' in request.FILES:
                csv_file = request.FILES["csv_file"]
            else:
                self.message_user(request, "Please choose a csv file",
                                  level="ERROR")
                return redirect("..")

            try:
                reader = csv.DictReader(csv_file.read().decode().splitlines())
                site_data = []
                for line in reader:
                    data = dict()
                    data['label_name'] = line['Label Name']
                    data['label_url'] = line['URL']
                    site_data.append(SiteMapJuloWeb(**data))
                with transaction.atomic():
                    SiteMapJuloWeb.objects.all().delete()
                    SiteMapJuloWeb.objects.bulk_create(site_data)
            except Exception as error:
                self.message_user(request, "Something went wrong with file: %s" % str(error),
                                  level="ERROR")
            else:
                self.message_user(request, "Your csv file has been imported")
            return redirect("..")
        form = CsvImportForm()
        payload = {"form": form}
        return render(
            request, "custom_admin/upload_config_form.html", payload
        )

    def label_name_(self, obj):
        return obj.label_name

    label_name_.short_description = "Label Name"

    def label_url_(self, obj):
        return obj.label_url

    label_url_.short_description = "Label Url"


class MarginOfErrorForm(forms.ModelForm):
    min_threshold = forms.FloatField(label="Min Threshold (in.)")
    max_threshold = forms.FloatField(label="Max Threshold (ex.)")

    class Meta(object):
        model = MarginOfError
        fields = ('min_threshold', 'max_threshold', 'mae')


class MarginOfErrorAdmin(JuloModelAdmin):
    form = MarginOfErrorForm
    list_display = (
        "mae",
        "min_threshold_",
        "max_threshold_",
    )

    def min_threshold_(self, obj):
        return obj.min_threshold

    min_threshold_.short_description = "Min Threshold (in.)"

    def max_threshold_(self, obj):
        return obj.max_threshold

    max_threshold_.short_description = "Max Threshold (ex.)"


class FDCInquiryCheckForm(forms.ModelForm):
    old_id = forms.CharField(widget=forms.HiddenInput())
    min_threshold = forms.FloatField(label="Min Threshold (in.)")
    max_threshold = forms.FloatField(label="Max Threshold (ex.)")
    min_macet_pct = forms.FloatField(label="Min Macet Percentage (in.)")
    max_paid_pct = forms.FloatField(label="Max Paid Percentage (ex.)")

    class Meta(object):
        model = FDCInquiryCheck
        fields = ('is_active', 'min_threshold', 'max_threshold', 'min_macet_pct', 'max_paid_pct')

    def clean(self):
        old_id = int(self.cleaned_data.get("old_id"))
        min_threshold = self.cleaned_data.get("min_threshold")
        max_threshold = self.cleaned_data.get("max_threshold")

        if min_threshold >= max_threshold:
            raise forms.ValidationError("Min Threshold value should lower than Max Threshold")

        do_validation = True
        if old_id > 0:
            fdc_inquiry_check = FDCInquiryCheck.objects.get(pk=old_id)
            if fdc_inquiry_check.min_threshold == min_threshold and fdc_inquiry_check.max_threshold == max_threshold:
                do_validation = False

        if do_validation:
            fdc_inquiry_checks = FDCInquiryCheck.objects.exclude(pk=old_id).order_by('min_threshold')
            for fdc_inquiry_check in fdc_inquiry_checks:
                min_threshold_validation = fdc_inquiry_check.min_threshold <= min_threshold < fdc_inquiry_check.max_threshold
                max_threshold_validation = fdc_inquiry_check.min_threshold < max_threshold <= fdc_inquiry_check.max_threshold
                if min_threshold_validation or max_threshold_validation:
                    raise forms.ValidationError(
                        "Duplicate value of {} until {}".format(
                            fdc_inquiry_check.min_threshold,
                            fdc_inquiry_check.max_threshold,
                        )
                    )


class FDCInquiryCheckAdmin(JuloModelAdmin):
    form = FDCInquiryCheckForm
    list_display = (
        "is_active",
        "min_threshold_",
        "max_threshold_",
        "min_macet_pct_",
        "max_paid_pct_",
    )

    def min_threshold_(self, obj):
        return obj.min_threshold

    min_threshold_.short_description = "Min Threshold (in.)"

    def max_threshold_(self, obj):
        return obj.max_threshold

    max_threshold_.short_description = "Max Threshold (ex.)"

    def min_macet_pct_(self, obj):
        return obj.min_macet_pct

    min_macet_pct_.short_description = "Min Macet Percentage (in.)"

    def max_paid_pct_(self, obj):
        return obj.max_paid_pct

    max_paid_pct_.short_description = "Max Paid Percentage (ex.)"

    def get_form(self, request, obj=None, *args, **kwargs):
        form = super(FDCInquiryCheckAdmin, self).get_form(request, *args, **kwargs)

        form.base_fields['old_id'].initial = 0
        if obj:
            form.base_fields['old_id'].initial = obj.id

        return form


class AccountForm(forms.ModelForm):
    class Meta(object):
        model = Account
        fields = (
            'id',
            'status',
            'cycle_day'
        )


class AccountAdmin(JuloModelAdmin):
    form = AccountForm
    list_display = (
        'id',
        'get_customer_email',
        'get_customer_fullname',
        'get_customer_id',
        'status',
        'get_account_limit_id',
        'get_account_max_limit',
        'get_account_set_limit',
        'get_account_available_limit',
        'get_account_used_limit',
    )
    search_fields = ('id', 'customer__fullname', 'customer__email')

    def has_add_permission(self, request):
        # Nobody is allowed to add
        return False

    def get_customer_email(self, obj):
        return obj.customer.email

    def get_customer_fullname(self, obj):
        return obj.customer.fullname

    def get_customer_id(self, obj):
        return '<a href="/xgdfat82892ddn/julo/customer/{}/change/">{}</a>'.format(
            obj.customer.id, obj.customer.id
        )

    def get_account_id(self, obj):
        return '<a href="/xgdfat82892ddn/account/account/{}/change/">{}</a>'.format(
            obj.id, obj.id
        )

    def get_account_limit_id(self, obj):
        if obj.get_account_limit:
            return '<a href="/xgdfat82892ddn/account/accountlimit/{}/change/">{}</a>'.format(
                obj.get_account_limit.id, obj.get_account_limit.id
            )
        else:
            return '-'

    def get_account_max_limit(self, obj):
        if obj.get_account_limit:
            return obj.get_account_limit.max_limit
        else:
            return '-'

    def get_account_set_limit(self, obj):
        if obj.get_account_limit:
            return obj.get_account_limit.set_limit
        else:
            return '-'

    def get_account_used_limit(self, obj):
        if obj.get_account_limit:
            return obj.get_account_limit.used_limit
        else:
            return '-'

    def get_account_available_limit(self, obj):
        if obj.get_account_limit:
            return obj.get_account_limit.available_limit
        else:
            return '-'

    get_customer_id.short_description = 'customer_id'
    get_customer_id.allow_tags = True
    get_customer_fullname.short_description = 'fullname'
    get_customer_fullname.allow_tags = False
    get_customer_email.short_description = 'email'
    get_account_id.short_description = 'account_id'
    get_account_id.allow_tags = True
    get_account_limit_id.short_description = 'account_limit_id'
    get_account_limit_id.allow_tags = True
    get_account_max_limit.short_description = 'max_limit'
    get_account_set_limit.short_description = 'set_limit'
    get_account_used_limit.short_description = 'used_limit'
    get_account_available_limit.short_description = 'available_limit'

    def get_actions(self, request):
        # Disable delete
        actions = super(AccountAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False


class AccountLimitForm(forms.ModelForm):
    max_limit = forms.IntegerField(label="Max limit")
    set_limit = forms.IntegerField(label="Set limit")
    available_limit = forms.IntegerField(label="Set limit")
    used_limit = forms.IntegerField(label="Used limit")

    class Meta(object):
        model = AccountLimit
        fields = (
            'id',
            'account',
            'max_limit',
            'set_limit',
            'available_limit',
            'used_limit',
        )


class AccountLimitAdmin(JuloModelAdmin):
    form = AccountLimitForm
    list_display = (
        'id',
        'account',
        'max_limit',
        'set_limit',
        'available_limit',
        'used_limit',
    )

    def has_add_permission(self, request):
        # Nobody is allowed to add
        return False

    def get_actions(self, request):
        # Disable delete
        actions = super(AccountLimitAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False


class FaqCheckoutAdmin(admin.ModelAdmin):
    list_display = ('title', 'order_priority', 'visible')
    list_filter = ('visible',)


class FaqFeatureAdmin(admin.ModelAdmin):
    list_display = ('title', 'section_name', 'order_priority', 'visible')
    list_filter = ('visible', 'section_name')
    ordering = ('section_name', 'order_priority')


admin.site.register(LoanPurpose, LoanPurposeAdmin)
admin.site.register(ProductLine, ProductLineAdmin)
admin.site.register(AddressGeolocation, GeoLocationAdmin)
admin.site.register(Agent, AgentAdmin)
admin.site.register(Application, ApplicationAdmin)
admin.site.register(ApplicationHistory, ApplicationHistoryAdmin)
admin.site.register(Bank, BankAdmin)
admin.site.register(DataCheck)
admin.site.register(Decision, DecisionAdmin)
admin.site.register(Device, DeviceAdmin)
admin.site.register(DeviceScrapedData, DeviceScrapedDataAdmin)
admin.site.register(DeviceIpHistory, DeviceIpHistoryAdmin)
admin.site.register(FacebookData, FacebookDataAdmin)
admin.site.register(FacebookDataHistory, FacebookDataAdmin)
admin.site.register(Image, ImageAdmin)
admin.site.register(Loan, LoanAdmin)
admin.site.register(ApplicationNote, ApplicationNoteAdmin)
admin.site.register(Offer, OfferAdmin)
admin.site.register(OriginalPassword)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(PaymentNote)
admin.site.register(ProductLookup, ProductLookupAdmin)
admin.site.register(StatusLookup, StatusLookupAdmin)
admin.site.register(ThirdPartyData)
admin.site.register(Customer, CustomerAdmin)
admin.site.register(Transaction)
admin.site.register(DeviceGeolocation)
admin.site.register(AppVersionHistory)
admin.site.register(VoiceRecord, VoiceAdmin)
admin.site.register(Document, DocumentAdmin)

admin.site.register(Partner, PartnerAdmin)
admin.site.register(PartnerLoan, PartnerLoanAdmin)
admin.site.register(PartnerReferral, PartnerReferralAdmin)
admin.site.register(PartnerTransaction)
admin.site.register(PartnerTransactionItem)
admin.site.register(PartnerAddress)
admin.site.register(PartnerBankAccount, PartnerBankAccountItem)
admin.site.register(PaymentMethod, PaymentMethodAdmin)
admin.site.register(ScrapingButton, ScrapingButtonAdmin)
admin.site.register(AppVersion, AppVersionAdmin)
admin.site.register(CustomerAppAction, CustomerAppActionAdmin)
admin.site.register(PartnerReportEmail, PartnerReportEmailAdmin)
admin.site.register(ChangeReason, ChangeReasonAdmin)
admin.site.register(Workflow, WorkflowAdmin)
admin.site.register(WorkflowStatusNode, WorkflowStatusNodeAdmin)
admin.site.register(WorkflowStatusPath, WorkflowStatusPathAdmin)
admin.site.register(WorkflowFailureAction, WorkflowFailureActionAdmin)
admin.site.register(MobileOperator, MobileOperatorAdmin)
admin.site.register(SepulsaProduct, SepulsaProductAdmin)
admin.site.register(ApplicationExperiment)
admin.site.register(Experiment, ExperimentAdmin)
admin.site.register(ExperimentAction, ExperimentActionAdmin)
admin.site.register(ExperimentTestGroup, ExperimentTestGroupAdmin)
admin.site.register(PartnerAccountAttribution, PartnerAccountAttributionAdmin)
admin.site.register(PartnerAccountAttributionSetting, PartnerAccountAttributionSettingAdmin)
admin.site.register(Banner, BannerAdmin)
admin.site.register(BannerGroup, BannerGroupAdmin)
admin.site.register(MobileFeatureSetting, MobileFeatureSettingAdmin)
admin.site.register(RobocallTemplate, RobocallTemplateAdmin)
admin.site.register(FeatureSetting, FeatureSettingAdmin)
admin.site.register(SphpTemplate, SphpTemplateAdmin)
admin.site.register(WarningUrl, WarningUrlAdmin)
admin.site.register(ExperimentSetting, ExperimentSettingAdmin)
admin.site.register(PaymentExperiment, PaymentExperimentAdmin)
admin.site.register(FaqItem, FaqItemAdmin)
admin.site.register(FaqSubTitle, FaqSubTitleAdmin)
admin.site.register(FaqSection, FaqSectionAdmin)
admin.site.register(FaqCheckout, FaqCheckoutAdmin)
admin.site.register(JuloContactDetail, JuloContactDetailAdmin)
admin.site.register(PaybackTransaction, PaybackTransactionAdmin)
admin.site.register(CreditScore, CreditScoreAdmin)
admin.site.register(CreditScoreExperiment, CreditScoreExperimentAdmin)
admin.site.register(FrontendView, FrontendViewAdmin)
admin.site.register(StatusLabel, StatusLabelAdmin)
admin.site.register(DigisignConfiguration, DigisignConfigurationAdmin)
admin.site.register(DigisignConfigurationHistory, DigisignConfigurationHistoryAdmin)
admin.site.register(CreditMatrix, CreditMatrixAdmin)
admin.site.register(CreditMatrixRepeat, CreditMatrixRepeatAdmin)
admin.site.register(PartnerOriginationData, PartnerOriginationDataAdmin)
admin.site.register(HighScoreFullBypass, HighScoreFullBypassAdmin)
admin.site.register(FaceRecognition, FaceRecognitionAdmin)
admin.site.register(ITIConfiguration, ITIConfigurationAdmin)
admin.site.register(MarginOfError, MarginOfErrorAdmin)
admin.site.register(FDCInquiryCheck, FDCInquiryCheckAdmin)
admin.site.register(Account, AccountAdmin)
admin.site.register(AccountLimit, AccountLimitAdmin)
admin.site.register(SiteMapJuloWeb, SiteMapContentAdmin)
admin.site.register(FaqFeature, FaqFeatureAdmin)


class SupervisorAdminSite(AdminSite):

    def has_permission(self, request):
        default_permission = super(SupervisorAdminSite, self).has_permission(
            request)
        return default_permission or request.user.group.name == 'Supervisor'


supervisor_admin_site = SupervisorAdminSite(
    name=SUPERVISOR_SITE_NAME)


class WorkflowCustomAdmin(JuloModelAdmin):
    pass


class WorkflowAdminSite(AdminSite):
    def get_urls(self):
        from django.conf.urls import url
        urls = super(WorkflowAdminSite, self).get_urls()
        # Note that custom urls get pushed to the list (not appended)
        # This doesn't work with urls += ...
        urls = [
                   url(r'^flowchart/$', self.admin_view(workflow_diagram), name='flowchart-workflow')
               ] + urls

        return urls


workflow_admin_site = WorkflowAdminSite()
workflow_admin_site.register(Workflow, WorkflowCustomAdmin)


class CustomerServiceAdminAuthenticationForm(AdminAuthenticationForm):
    """
    A custom authentication form used in the admin app.
    """

    def confirm_login_allowed(self, user):
        if user.is_active and user.is_staff:
            return
        if user.is_active and user.groups.filter(name='Supervisor').exists():
            return
        if user.is_active and user.groups.filter(name='CS').exists():
            return
        raise forms.ValidationError(
            self.error_messages['invalid_login'],
            code='invalid_login',
            params={'username': self.username_field.verbose_name}
        )


class CustomerServiceAdminSite(AdminSite):
    login_form = CustomerServiceAdminAuthenticationForm

    def has_permission(self, request):
        if super(CustomerServiceAdminSite, self).has_permission(request):
            return True
        if request.user.groups.filter(name='Supervisor').exists() and request.user.is_active:
            return True
        if request.user.groups.filter(name='CS').exists() and request.user.is_active:
            return True


customer_service_admin_site = CustomerServiceAdminSite(
    name=CUSTOMER_SERVICE_SITE_NAME)
customer_service_admin_site.register(Device, ReadonlyJuloModelAdmin)

# Text to put at the end of each page's <title>.
admin.site.site_title = _('JuloFinance site')

# Text to put in each page's <h1> (and above login form).
admin.site.site_header = _('Julo Finance Admin')


# Text to put at the top of the admin index page.
# admin.site.index_title = _('Hehehehe')


class ProfileInline(admin.StackedInline):
    model = Agent
    fk_name = "user"
    fields = ["inactive_date"]


class CustomUserAdmin(UserAdmin):
    inlines = (ProfileInline,)
    paginator = FixPaginator
    ordering = ()

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super(CustomUserAdmin, self).get_inline_instances(request, obj)


class JuloCustomerEmailSettingInline(admin.StackedInline):
    model = JuloCustomerEmailSetting
    extra = 0
    fields = (
        'send_email',
        'attach_sphp',
        'enabled')
    readonly_fields = ('attach_sphp',)

    def has_add_permission(self, request, obj=None):
        return JuloCustomerEmailSetting.objects.count() < 1


class PartnerEmailSettingInline(admin.TabularInline):
    model = PartnerEmailSetting
    extra = 0
    fields = (
        'partner',
        'send_to_partner_customer',
        'send_to_partner',
        'partner_email_list',
        'attach_sphp_partner_customer',
        'attach_sphp_partner',
        'enabled')


class EmailSettingAdmin(JuloModelAdmin):
    list_display = (
        'status_code',
        'payment_settings_str',
        'julo_customer_settings_str',
        'enabled',
    )
    inlines = (
        PartnerEmailSettingInline,
        JuloCustomerEmailSettingInline,
    )

    def payment_settings_str(self, obj):
        try:
            result = ''
            for partner in obj.partneremailsetting_set.all():
                result += '{}<br/>'.format(partner)
            return mark_safe(result)
        except Exception:
            return None

    def julo_customer_settings_str(self, obj):
        try:
            return obj.julocustomeremailsetting
        except:
            return None


class NotificationTemplateAdmin(admin.ModelAdmin):
    def __init__(self, *args, **kwargs):
        super(NotificationTemplateAdmin, self).__init__(*args, **kwargs)
        self.list_display_links = None

    def action(self, obj):
        url = reverse('notification_templates_admin:notification-template-update', kwargs={'notif_id': obj.id})
        url_send = reverse('notification_templates_admin:notification-template-send', kwargs={'notif_id': obj.id})
        action_button = '<a class="default" href="' + url + '"> Edit </a> | ' \
                                                            '<a class="default" href="' + url_send + '"> Send </a>'
        return mark_safe(action_button)

    def has_add_permission(self, request, obj=None):
        return False

    search_fields = ['title']
    list_display = ('title', 'action')
    change_list_template = loader.get_template('custom_admin/notification_template.html')


class NotificationTemplateCustomAdmin(JuloModelAdmin):
    pass


class NotificationTemplateAdminSite(AdminSite):
    def __init__(self, *args, **kwargs):
        super(NotificationTemplateAdminSite, self).__init__(*args, **kwargs)
        self.name = 'notification_templates_admin'

    def get_urls(self):
        from django.conf.urls import url
        urls = super(NotificationTemplateAdminSite, self).get_urls()
        # Note that custom urls get pushed to the list (not appended)
        # This doesn't work with urls += ...
        urls = [
                   url(r'^notification_template_add/$', self.admin_view(notification_template_add),
                       name='notification-template-add'),
                   url(r'^notification_template_update/(?P<notif_id>[0-9]+)$',
                       self.admin_view(notification_template_update), name='notification-template-update'),
                   url(r'^notification_template_send/(?P<notif_id>[0-9]+)$',
                       self.admin_view(notification_template_send), name='notification-template-send'),
                   url(r'^email_autocomplete/$', self.admin_view(email_autocomplete), name='email_autocomplete'),
               ] + urls

        return urls


class ReferralPromoForm(forms.ModelForm):
    promoImage = forms.ImageField()

    def __init__(self, *args, **kwargs):
        super(ReferralPromoForm, self).__init__(*args, **kwargs)
        self.fields['promoImage'].required = False


class ReferralSystemAdmin(JuloModelAdmin):
    form = ReferralPromoForm

    list_display = (
        'id',
        'name'
    )
    readonly_fields = ('name', 'promo_image',)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super(ReferralSystemAdmin, self).save_model(request, obj, form, change)
        if request.FILES and request.FILES['promoImage']:
            promoImage = request.FILES['promoImage']
            _, file_extension = os.path.splitext(promoImage.name)

            image = Image()
            image.image_source = obj.pk
            image.image_type = 'referral_promo'
            image.save()

            remote_path = 'referral_system/promoimage{}'.format(image.pk)
            image.update_safely(url=remote_path)
            file = functions.upload_handle_media(promoImage, "referral_system/promoimage")
            if file:
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    file['file_name'],
                    remote_path
                )

    def promo_image(self, obj):
        return mark_safe('<img src="{url}" width="{width}" />'.format(
            url=obj.banner_static_url,
            width=300
        )
        )


notification_template_admin_site = NotificationTemplateAdminSite()
notification_template_admin_site.register(NotificationTemplate, NotificationTemplateCustomAdmin)
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(EmailSetting, EmailSettingAdmin)
admin.site.register(NotificationTemplate, NotificationTemplateAdmin)

admin.site.register(ReferralCampaign)
admin.site.register(ReferralSystem, ReferralSystemAdmin)


class BukalapakInterestAdmin(JuloModelAdmin):
    def has_add_permission(self, request):
        # Nobody is allowed to add
        return False

    def has_delete_permission(self, request, obj=None):
        # Nobody is allowed to delete
        return False


admin.site.register(BukalapakInterest, BukalapakInterestAdmin)


class InitialCreditLimitForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.instance = kwargs.get('instance', None)
        form = super(InitialCreditLimitForm, self).__init__(*args, **kwargs)

    class Meta(object):
        model = InitialCreditLimit
        fields = [
            'cluster_type',
            'score_first',
            'score_last',
            'initial_credit_limit'
        ]
        exclude = ['id']

    def clean(self):
        data = self.cleaned_data
        try:
            if data['score_last'] < data['score_first']:
                raise forms.ValidationError("score_last can't less than score_first")
        except Exception as e:
            raise forms.ValidationError(e)

        return self.cleaned_data


class InitialCreditLimitAdmin(JuloModelAdmin):
    form = InitialCreditLimitForm

    list_display = (
        'cluster_type',
        'score_first_',
        'score_last_',
        'initial_credit_limit',
    )

    def has_delete_permission(self, request, obj=None):
        # Nobody is allowed to delete
        return False

    def score_first_(self, obj):
        return obj.score_first

    score_first_.short_description = 'score_first(included)'

    def score_last_(self, obj):
        return obj.score_last

    score_last_.short_description = 'score_last(excluded)'


admin.site.register(InitialCreditLimit, InitialCreditLimitAdmin)


class BlacklistCustomerAdmin(JuloModelAdmin):
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    list_display = (
        'source',
        'name',
        'citizenship',
        'dob'
    )

    def get_urls(self):
        urls = super(BlacklistCustomerAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            with transaction.atomic():
                try:
                    csv_file = request.FILES["csv_file"]
                    reader = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
                    for line in reader:
                        if not line.get('name'):
                            raise ValidationError(
                                "'name' cannot be empty in any of the rows in the CSV")
                        BlacklistCustomer.objects.get_or_create(name=line.get('name'), defaults=line)
                except Exception as error:
                    self.message_user(
                        request, "Something went wrong with file: %s" % str(error), level="ERROR"
                    )
                else:
                    self.message_user(request, "Your csv file has been imported")
            return redirect("..")
        form = CsvImportForm()
        payload = {
            'data_table': {
                'property': ['citizenship','dob','fullname_trim','name','source'],
                'data': ['El Gouazine, Dahmani, Governorate dari Le Kef, Tunisia',
                         '5 Oktober 1991', 'ashrafalgizani', 'ashraf al-gizani', 'dttot']
            },
            'form': form
        }
        return render(request, "custom_admin/upload_config_form.html", payload)


admin.site.register(BlacklistCustomer, BlacklistCustomerAdmin)


class PartnerSignatureModeHistoryAdmin(JuloModelAdmin):
    list_display = ('partner_signature_mode', 'is_active')


class PartnerSignatureModeAdmin(JuloModelAdmin):
    list_display = ('partner', 'is_active')


admin.site.register(PartnerSignatureModeHistory, PartnerSignatureModeHistoryAdmin)
admin.site.register(PartnerSignatureMode, PartnerSignatureModeAdmin)


class CootekRobotAdmin(admin.ModelAdmin):
    fieldsets = [
        (None, {'fields': ['robot_identifier']}),
        (None, {'fields': ['robot_name']}),
        (None, {'fields': ['is_group_method']}),
    ]


admin.site.register(CootekRobot, CootekRobotAdmin)


class CootekConfigurationForm(forms.ModelForm):
    julo_gold = forms.ChoiceField(
        widget=forms.RadioSelect(attrs={'class': 'action-control'}),
        choices=JuloGoldFilter.as_options(with_none=True),
        required=False,
    )
    tag_status = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'cootek-configuration-setting-control'})
    )
    product = forms.ChoiceField(required=False, widget=forms.Select())

    def init(self, *args, **kwargs):
        super(CootekConfigurationForm, self).init(*args, **kwargs)

    class Meta(object):
        fields = (
            'is_active',
            'strategy_name',
            'task_type',
            'partner',
            'product',
            'criteria',
            'dpd_condition',
            'cootek_control_group',
            'time_to_start',
            'time_to_end',
            'number_of_attempts',
            'cootek_robot',
            'called_at',
            'called_to',
            'exclude_risky_customer',
            'loan_ids',
            'is_exclude_b3_vendor',
            'exclude_autodebet',
            'julo_gold',
        )

    def clean_loan_ids(self):
        data = self.cleaned_data['loan_ids']
        for loan_ids in data:

            id_number_checking = re.match(r'^\d+$', loan_ids)
            if id_number_checking:
                continue

            id_pair_checking = re.match(r'^(\d+)-(\d+)$', loan_ids)
            if not id_pair_checking:
                raise forms.ValidationError("Loan_ids is incorrect format: %s" % loan_ids)

            first_param = id_pair_checking.group(1)
            second_param = id_pair_checking.group(2)
            if len(first_param) != len(second_param) or int(first_param) > int(second_param):
                raise forms.ValidationError("Loan_ids is incorrect format: %s" % loan_ids)

        return data

    def clean(self):
        self.cleaned_data.update({'called_to': self.data.get('called_to')})
        self.cleaned_data.update({'called_at': self.data.get('called_at')})
        called_to = self.data.get('called_to')
        called_at = self.data.get('called_at')
        super(CootekConfigurationForm, self).clean()

        if self.cleaned_data['criteria'] == CriteriaChoices.REFINANCING_PENDING \
                and self.cleaned_data['partner']:
            raise forms.ValidationError("Can not active on both Refinacing and Partner")

        if self.cleaned_data['exclude_autodebet']:
            if self.cleaned_data['product'] not in (
                    CootekProductLineCodeName.J1, CootekProductLineCodeName.JTURBO):
                raise forms.ValidationError('Can not activate exclude autodebet for non J1 product')

        if not self.cleaned_data['criteria']:
            try:
                if called_to:
                    called_to = int(called_to)
                if called_at:
                    called_at = int(called_at)
            except ValueError:
                raise forms.ValidationError("Incorrect called at values")
            if not (called_at != '' and self.cleaned_data['dpd_condition']):
                raise forms.ValidationError("Called at can not be empty")
            elif self.cleaned_data['dpd_condition'] == DpdConditionChoices.RANGE:
                if called_to == '':
                    raise forms.ValidationError("Called at can not be empty")
                elif called_at >= called_to:
                    raise forms.ValidationError("From must be less than To")

        if not self.cleaned_data.get('time_to_end'):
            raise forms.ValidationError("Time to End can not be empty")
        if self.cleaned_data.get('time_to_start') and self.cleaned_data.get('time_to_end'):
            if self.cleaned_data.get('time_to_start') > self.cleaned_data.get('time_to_end'):
                raise forms.ValidationError("Time to End can not be less than Time to Start")

        self.cleaned_data.update({'called_to': called_to})
        self.cleaned_data.update({'called_at': called_at})

        # Handle Julo Gold thing
        if self.cleaned_data['julo_gold'] == 'None':
            self.cleaned_data.update({'julo_gold': None})
        if self.cleaned_data['product'] != "J1":
            self.cleaned_data.update({'julo_gold': None})


class CootekConfigurationAdmin(JuloModelAdmin):
    list_display = (
        'strategy_name',
        'task_type',
        'time_to_start',
        'time_to_end',
        'cootek_robot',
        'get_partner',
        'product',
        'tag_status',
        'number_of_attempts',
        'time_to_prepare',
        'time_to_query_result',
        'is_active'
    )

    exclude = (
        'from_previous_cootek_result',
        'time_to_query_result',
        'time_to_prepare',
    )

    add_form_template = "custom_admin/cootek_configurations.html"
    change_form_template = "custom_admin/cootek_configurations.html"

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = CootekConfigurationForm
        form = super(CootekConfigurationAdmin, self).get_form(request, *args, **kwargs)
        form.base_fields['task_type'].initial = '--'
        selected_all = (('All', 'All'),)

        tag_status_choices = (
            ('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D'), ('E', 'E'), ('F', 'F'), ('G', 'G'),
            ('H', 'H'), ('I', 'I'), ('--', '--')
        )

        form.base_fields['tag_status'].choices = tag_status_choices + selected_all
        form.base_fields['called_at'].widget = forms.HiddenInput(
            attrs={
                'readonly': 'readonly',
                'id': 'fake_called_at',
                'name': 'fake_called_at'})
        form.base_fields['called_to'].widget = forms.HiddenInput(
            attrs={
                'readonly': 'readonly',
                'id': 'fake_called_to',
                'name': 'fake_called_at'})
        form.base_fields['product'].choices = CootekProductLineCodeName.COOTEK_CONFIGURATION_PRODUCT_LINE
        form.base_fields['partner'].choices = ((None, 'JULO'),) + tuple(
            Partner.objects.values_list('id', 'name'))
        return form

    def save_model(self, request, obj, form, change):
        if obj.time_to_end:
            obj.time_to_query_result = add_minutes_to_datetime(obj.time_to_end, 10)
        else:
            obj.time_to_query_result = add_minutes_to_datetime(obj.time_to_start, 70)
        obj.time_to_prepare = add_minutes_to_datetime(obj.time_to_start, -10)

        if not obj.cootek_robot:
            return messages.error(request, 'Please fill cootek robot field')
        obj.called_at = form.cleaned_data['called_at']
        obj.called_to = form.cleaned_data['called_to'] \
            if form.cleaned_data['called_to'] else None
        if obj.criteria and obj.criteria == CriteriaChoices.UNCONNECTED_LATE_DPD:
            obj.task_type = form.cleaned_data['task_type']
            obj.time_to_query_result = None
        elif obj.dpd_condition == DpdConditionChoices.EXACTLY and not obj.is_unconnected_late_dpd:
            obj.task_type = 'JULO_T%s' % obj.called_at + \
                            ('_%s' % obj.product.upper() if obj.product is not None else '')
        elif obj.criteria and obj.criteria != CriteriaChoices.UNCONNECTED_LATE_DPD:
            obj.task_type = 'JULO_%s' % obj.criteria.upper()
        elif obj.dpd_condition == DpdConditionChoices.LESS and not obj.is_unconnected_late_dpd:
            obj.task_type = 'JULO_T<%s' % obj.called_at
            obj.task_type = 'JULO_T%s' % obj.called_at + \
                            ('_T%s' % obj.called_to if obj.called_to is not None else '')

        partner = obj.partner
        if partner is not None:
            if partner.name in CootekProductLineCodeName.partner_eligible_for_cootek():
                if partner.name == 'bukalapak_paylater':
                    obj.task_type = 'BL_PAYLATER-' + str(obj.called_at)
                elif partner.name == CootekProductLineCodeName.DANA:
                    obj.task_type = 'DANA_T' + str(obj.called_at)

            else:
                return messages.error(request, 'This partner not registered to cootek')

        if obj.tag_status and "All" in obj.tag_status:
            obj.tag_status = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', '--']

        super(CootekConfigurationAdmin, self).save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super(CootekConfigurationAdmin, self).get_queryset(request)
        return qs.filter()

    def get_partner(self, obj):
        return obj.partner.name if obj.partner else "JULO"

    get_partner.short_description = "Partner"


admin.site.register(CootekConfiguration, CootekConfigurationAdmin)


class GlobalPaymentMethodForm(forms.ModelForm):
    impacted_type = forms.ChoiceField(initial='Impacted type', widget=forms.Select())

    def init(self, *args, **kwargs):
        super(GlobalPaymentMethodForm, self).init(*args, **kwargs)


class GlobalPaymentMethodAdmin(JuloModelAdmin):
    list_display = (
        'feature_name',
        'is_shown',
        'parameters'
    )

    readonly_fields = ('feature_name', 'payment_method_code', 'payment_method_name')

    def is_shown(self, obj):
        return obj.is_active

    is_shown.boolean = True
    is_shown.short_description = 'is_shown'

    change_form_template = "custom_admin/payment_method_view_template.html"

    def has_add_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        # Disable delete
        actions = super(GlobalPaymentMethodAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = GlobalPaymentMethodForm
        form = super(GlobalPaymentMethodAdmin, self).get_form(request, *args, **kwargs)

        impacted_types = (('Primary', 'Primary'), ('Backup', 'Backup'),
                          ('Primary and Backup', 'Primary and Backup'),)
        form.base_fields['impacted_type'].choices = impacted_types

        return form


class EverEnteredB5ExpirationForm(forms.ModelForm):
    radio_choices = [('forever', 'Forever'),
                     ('expired_days', 'Config expired days')]
    form_data = forms.CharField(
        widget=forms.HiddenInput(attrs={'readonly': 'readonly'}),
        required=False)
    expiration_option = forms.ChoiceField(
        required=True,
        choices=radio_choices, widget=forms.RadioSelect(attrs={'class': 'expiration_option'}))
    many_days = forms.IntegerField(required=True)

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(EverEnteredB5ExpirationForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            if instance.parameters:
                entered_b5_valid_for = instance.parameters.get('entered_b5_valid_for')
                self.fields[
                    'expiration_option'].initial = "expired_days" if entered_b5_valid_for != "forever" else entered_b5_valid_for
                if entered_b5_valid_for != "forever":
                    self.fields['many_days'].initial = int(entered_b5_valid_for)

    def clean(self):
        cleaned_data = super(EverEnteredB5ExpirationForm, self).clean()
        expiration_option = cleaned_data.get('expiration_option')
        many_days = cleaned_data.get('many_days')
        if expiration_option != "forever" and int(many_days) == 0:
            raise forms.ValidationError(
                "many_days should not 0 "
            )
        return cleaned_data


class CashbackExpiredForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=True)
    reminder_days = forms.IntegerField(required=True, min_value=1)

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(CashbackExpiredForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            if instance.parameters:
                self.fields['reminder_days'].initial = instance.parameters.get(
                    'reminder_days', CashbackExpiredConst.DEFAULT_REMINDER_DAYS)


class SendingRecordingConfigurationForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    recording_resources = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'recording-resource-control'}))
    recording_duration = forms.CharField(label='Recording Duration', widget=forms.Select(
        choices=SendingRecordingConfig.RECORDING_DURATION_TYPE), required=False)
    duration_from = forms.IntegerField(label='Duration', required=False)
    duration_until = forms.IntegerField(label='Duration Until', required=False)
    buckets = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'buckets-control'}))
    call_result_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'call-result-ids-control'}))

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(SendingRecordingConfigurationForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            self.fields['recording_resources'].choices = SendingRecordingConfig.RECORDING_RESOURCES
            existing_buckets = SentToDialer.objects.values('bucket').order_by('bucket'). \
                annotate(total=Count('bucket'))
            bucket_choices = []
            for data in existing_buckets:
                bucket_choices.append((data['bucket'], data['bucket']))
            self.fields['buckets'].choices = bucket_choices
            queryset = SkiptraceResultChoice.objects.all().values_list(
                'id', flat=True).order_by('id')
            self.fields['call_result_ids'].choices = [(i, i) for i in queryset]
            if instance.parameters:
                if instance.parameters:
                    self.fields['recording_resources'].initial = instance.parameters.get('recording_resources')
                    recording_duration_type = instance.parameters.get('recording_duration_type')
                    self.fields['recording_duration'].initial = instance.parameters.get('recording_duration_type')
                    if recording_duration_type == 'between':
                        self.fields['duration_from'].initial = instance.parameters.get('recording_duration')[0]
                        self.fields['duration_until'].initial = instance.parameters.get('recording_duration')[1]
                    elif recording_duration_type:
                        self.fields['duration_from'].initial = instance.parameters.get('recording_duration')[0]

                    self.fields['buckets'].initial = instance.parameters.get('buckets')
                    self.fields['call_result_ids'].initial = instance.parameters.get('call_result_ids')

    def clean(self):
        cleaned_data = super(SendingRecordingConfigurationForm, self).clean()
        duration_type = cleaned_data.get('recording_duration')
        if duration_type:
            duration_from = cleaned_data.get('duration_from')
            if not duration_from:
                raise forms.ValidationError(
                    "Duration from is required"
                )
            if duration_type == 'between':
                duration_until = cleaned_data.get('duration_until')
                if not duration_until:
                    raise forms.ValidationError(
                        "Duration until is required"
                    )
        return cleaned_data


class PartnerEligibleUseRenteeForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    partner_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'partner-ids-control'}))

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(PartnerEligibleUseRenteeForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            partners_active = Partner.objects.filter(is_active=True).values('id', 'name')
            partner_choices = []
            for partner_active in partners_active:
                partner_choices.append((partner_active['id'], partner_active['name']))
            self.fields['partner_ids'].choices = partner_choices

            if instance.parameters:
                if instance.parameters:
                    self.fields['partner_ids'].initial = instance.parameters.get('partner_ids')


admin.site.register(GlobalPaymentMethod, GlobalPaymentMethodAdmin)


class CootekControlGroupAdmin(admin.ModelAdmin):
    fieldsets = [
        (None, {'fields': ['percentage']}),
        (None, {'fields': ['account_tail_ids']})
    ]


admin.site.register(CootekControlGroup, CootekControlGroupAdmin)


class B4ExpirationForm(forms.ModelForm):
    class Meta(object):
        fields = ("__all__")

    def clean(self):
        cleaned_data = super(B4ExpirationForm, self).clean()
        expired_days = cleaned_data.get('parameters').get('expired_in_days')
        if expired_days > 19:
            raise forms.ValidationError(
                "expired in days threshold cant more than 19 days"
            )
        return cleaned_data


class BlacklistPartnerDialerForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    partner_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'partner-ids-control'}))
    configs = forms.CharField(
        widget=forms.HiddenInput(attrs={'readonly': 'readonly'}),
        required=False)

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super(BlacklistPartnerDialerForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            partners_active = Partner.objects.all().values('id', 'name')
            partner_choices = []
            for partner_active in partners_active:
                partner_choices.append((partner_active['id'], partner_active['name']))
            self.fields['partner_ids'].choices = partner_choices

            if instance.parameters:
                if instance.parameters:
                    selected_partner = []
                    for key in instance.parameters:
                        selected_partner.append(key)
                    self.fields['partner_ids'].initial = selected_partner
                    self.fields['configs'].initial = str(instance.parameters).replace(
                        "'", '"')


class DukcapilVerificationForm(forms.ModelForm):
    class Meta(object):
        fields = ("__all__")

    def clean(self):
        cleaned_data = super(DukcapilVerificationForm, self).clean()
        parameters = cleaned_data.get('parameters')
        if not parameters or 'method' not in parameters:
            raise forms.ValidationError(
                'for dukcapil_verification parameters method can not be empty, please define method')
        if parameters.get('method') not in DUKCAPIL_METHODS:
            raise forms.ValidationError("parameter 'method' should be either 'asliri' or 'direct'")
        pass_criteria = parameters.get('minimum_checks_to_pass')
        if pass_criteria is not None:
            if not isinstance(pass_criteria, int) or pass_criteria > 3 or pass_criteria <= 0:
                raise forms.ValidationError("parameter 'minimum_checks_to_pass' should be a \
                                             positive integer and less than or equal to 3")
        return cleaned_data


class ReminderEmailSettingAdminForm(forms.ModelForm):
    class Meta:
        model = ReminderEmailSetting
        exclude = ['id', 'day_before']

        widgets = {
            'time_scheduled': TimePickerInput()
        }

    def clean(self):
        cleaned_data = super().clean()
        days_before = cleaned_data.get('days_before')
        days_after = cleaned_data.get('days_after')
        recipients = cleaned_data.get('recipients')

        for day in days_before:
            if day < 3 or day > 31:
                self.add_error('days_before', forms.ValidationError('Angka harus minimal 3 atau maksimal 31'))

        for day in days_after:
            if day < 3 or day > 31:
                self.add_error('days_after', forms.ValidationError('Angka harus minimal 3 atau maksimal 31'))

        if recipients:
            cleaned_data['recipients'] = recipients.strip()
        return cleaned_data


class ReminderEmailSettingAdmin(JuloModelAdmin):
    form = ReminderEmailSettingAdminForm


admin.site.register(ReminderEmailSetting, ReminderEmailSettingAdmin)


class BSSChannelingCufOffForm(forms.ModelForm):
    class Meta:
        fields = ("__all__")

    def clean(self):
        cleaned_data = super(BSSChannelingCufOffForm, self).clean()
        params = cleaned_data.get('parameters')
        if params:
            dates = set(params.get('inactive_dates'))
            weekdays = set(params.get('inactive_weekdays'))

            # filtering
            try:
                for x in dates:
                    datetime.datetime.strptime(x, '%Y/%m/%d')
            except ValueError:
                raise forms.ValidationError("(Dates) Date must be valid & format must match YYYY/mm/dd")

            weekdays_choices = ["mon", 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
            for x in weekdays:
                if x.strip().lower() not in weekdays_choices:
                    raise forms.ValidationError("(Weekdays) Choices are: {}".format(weekdays_choices))

            params['inactive_dates'] = list(dates)
            params['inactive_weekdays'] = [x.strip().lower() for x in weekdays]

        return cleaned_data


class GrabDeductionFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. complete_rollover : if true then we process all grab loan data, otherwise it will be based on the selected program ids <br>'
                '2. schedule          : times the deduction will happen in a day'
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '2. "complete_rollover" and "schedule" is required inside of parameters<br>'
                '3. If "complete_rollover" is "false" then the program feature setting can not be null<br>'
                '4. "schedule" should always follow this format "21:00" and cannot more than 24 hours'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  "complete_rollover": true, <br>'
                '  "schedule": [ <br>'
                '     "10:00", <br>'
                '     "13:00", <br>'
                '     "15:00" <br>'
                '   ] <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            complete_rollover = parameters.get('complete_rollover')
            schedules = parameters.get('schedule')
            # check if there is no 'complete rollover' and 'schedule' in parameters
            if complete_rollover is None or schedules is None:
                raise forms.ValidationError('Parameters should have "complete_rollover" and "schedule" key')

            if not isinstance(schedules, list):
                raise forms.ValidationError('Invalid parameters, please see example input')

            # if complete_rollover have value false then feature setting should have the program_feature_setting value
            total_form = int(self.data.get('program_feature_settings-TOTAL_FORMS'))
            if complete_rollover is False:
                if total_form == 0:
                    raise forms.ValidationError('Parameters should have program_feature_setting selected')

            """
            - validate schedule string format
            - validate schedule is not more than 24 hours
            - validate unique schedule
            """
            temp_schedule = set()
            for schedule in schedules:
                import re
                # checking using regex
                rgx = re.compile('.{2}:.{2}')
                if rgx.match(schedule) is None:
                    raise forms.ValidationError('Invalid "schedule" format, e.g: "24:00" ')
                else:
                    if schedule in temp_schedule:
                        raise forms.ValidationError('"schedule" have duplicated data')

                    # check is valid 24 hours format
                    try:
                        datetime.datetime.strptime(schedule, '%H:%M').time()
                    except ValueError:
                        raise forms.ValidationError('"schedule" should use 24 hours format')

                    temp_schedule.add(schedule)

            if total_form > 0:
                temp_program_ids = set()
                for idx in range(0, total_form):
                    program_id = self.data.get(f'program_feature_settings-{idx}-program_id')
                    if program_id in temp_program_ids:
                        raise forms.ValidationError('program id already exist in this feature setting')
                    if self.data.get(f'program_feature_settings-{idx}-is_active') == 'on' and self.data.get(
                            f'program_feature_settings-{idx}-DELETE') == 'on':
                        raise forms.ValidationError('cannot delete the active grab program feature setting')
                    if program_id == '':
                        raise forms.ValidationError('cannot add empty program id')
                    temp_program_ids.add(program_id)

        return self.cleaned_data


class CheckoutExperimentForm(forms.ModelForm):
    class Meta(object):
        fields = ("__all__")

    def clean(self):
        list_account_id_tail = list(range(10))
        cleaned_data = super(CheckoutExperimentForm, self).clean()
        criteria = cleaned_data.get('criteria')
        # validation
        # check account_id_tail key
        if not criteria or 'account_id_tail' not in criteria:
            raise forms.ValidationError(
                'for checkout experience experiment, account_id_tail can not be empty, please define account_id_tail')
        account_id_tail = criteria.get('account_id_tail')
        # check all name of group name must be define
        if 'control_group' not in account_id_tail:
            raise forms.ValidationError(
                'please define control_group')
        if 'experiment_group_1' not in account_id_tail:
            raise forms.ValidationError(
                'please define experiment_group_1')
        if 'experiment_group_2' not in account_id_tail:
            raise forms.ValidationError(
                'please define experiment_group_2')
        # check data type for all group name is list/array
        if not isinstance(account_id_tail.get('control_group'), list) or \
                not isinstance(account_id_tail.get('experiment_group_1'), list) or \
                not isinstance(account_id_tail.get('experiment_group_2'), list):
            raise forms.ValidationError(
                'type every group name must be list or array, example "experiment_group_1": [4, 5, 6] or "experiment_group_1": [ ]')
        all_list_account_id_tail = []
        # check data type of list must integer
        # check eligible account_id_tail only in range 0-9
        # check duplicate account_id_tail
        for group_name in account_id_tail:
            for id_tail in account_id_tail[group_name]:
                if not isinstance(id_tail, int):
                    raise forms.ValidationError('list account_id_tail of %s must be integer' % group_name)
                if id_tail not in list_account_id_tail:
                    raise forms.ValidationError('eligible account_id_tail only in range 0 - 9')
                if id_tail in all_list_account_id_tail:
                    raise forms.ValidationError('there are duplicate for account_id_tail %s ' % id_tail)
                all_list_account_id_tail.append(id_tail)

        return cleaned_data


class SmsAbExperimentForm(forms.ModelForm):
    class Meta(object):
        fields = ('__all__')

    def clean(self):
        cleaned_data = super(SmsAbExperimentForm, self).clean()
        criteria = cleaned_data.get('criteria')

        digits = []
        for key, value in criteria.items():
            digits += value

        if sorted(digits) != list(range(0, 10)):
            raise forms.ValidationError('Criteria must use all 0 - 9 digit exactly once.')

        return cleaned_data

class GrabProgramInterestAdmin(JuloModelAdmin):
    pass


class Robocall1WayVendorExperimentForm(forms.ModelForm):
    class Meta(object):
        fields = ('__all__')

    def clean(self):
        cleaned_data = super(Robocall1WayVendorExperimentForm, self).clean()
        criteria = cleaned_data.get('criteria')

        digits = criteria['nexmo'] + criteria['infobip']['account_id_tail']
        if sorted(digits) != list(range(0, 10)):
            raise forms.ValidationError(
                'Criteria for account_id_tail must use all 0 - 9 digit exactly once.')

        if 'calling_number' not in criteria['infobip']:
            raise forms.ValidationError('calling_number missing from criteria for infobip.')


class EmailCollectionTailorForm(forms.ModelForm):
    class Meta(object):
        fields = ("__all__")

admin.site.register(GrabProgramInterest, GrabProgramInterestAdmin)


class OnboardingAdmin(JuloModelAdmin):
    list_display = ('id', 'description', 'status')
    readonly_fields = ('id',)

    def get_actions(self, request):
        # Disable delete
        actions = super(OnboardingAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False


admin.site.register(Onboarding, OnboardingAdmin)


class AutodebetCustomerExcludeFromIntelixCallForm(forms.ModelForm):
    class Meta(object):
        fields = ("__all__")

    def clean(self):
        cleaned_data = super(AutodebetCustomerExcludeFromIntelixCallForm, self).clean()
        parameters = cleaned_data.get('parameters')
        if not parameters:
            raise forms.ValidationError(
                'for autodebit_customer_exclude_verification parameters can not empty')
        if 'dpd_minus' not in parameters:
            raise forms.ValidationError(
                'for autodebit_customer_exclude_verification dpd_minus can not empty, please define method')
        if 'dpd_zero' not in parameters:
            raise forms.ValidationError(
                'for autodebit_customer_exclude_verification dpd_zero can not empty, please define method')
        if 'dpd_plus' not in parameters:
            raise forms.ValidationError(
                'for autodebit_customer_exclude_verification dpd_plus can not empty, please define method')
        if not isinstance(parameters.get('dpd_minus'), bool) or not \
            isinstance(parameters.get('dpd_zero'), bool) or not \
                isinstance(parameters.get('dpd_plus'), bool):
            raise forms.ValidationError(
                'all parameters dpd value must be true or false only')

        return cleaned_data


class MasterAgreementTemplateAdmin(JuloModelAdmin):
    list_display = ('id', 'is_active', 'product_name')

    def get_actions(self, request):
        # Disable delete
        actions = super(MasterAgreementTemplateAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(MasterAgreementTemplate, MasterAgreementTemplateAdmin)


class GrabIntelixCallFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. populate_schedule          : times the populating data will happen in a day <br>'
                '2. send_schedule              : times the sending data will happen in a day <br>'
                '3. grab_construct_batch_size  : this batch size will limit the data that need to be constructed<br>'
                '4. grab_send_batch_size       : this Batch size will limit the data we fetch while '
                'sending data to intelix<br>'
                '5. c_score_db_populate_schedule : times the c_score_db_populate will happen in a day <br> '
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. Please consult to engineering team before updating the parameters'
                '2. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '3. "populate_schedule" , "send_schedule" and "c_score_db_populate_schedule" '
                'is required inside of parameters<br>'
                '4. "populate_schedule" should always follow this format "01:00" and have maximum for "06:00"<br>'
                '5. "send_schedule" should always follow this format "01:00" and have maximum for "07:00" <br>'
                '6. "send_schedule" should be bigger than "populate_schedule" with range 1 hour<br>'
                '7. "grab_construct_batch_size" should always be on type integer and follow this format "100"<br>'
                '8. "grab_construct_batch_size" default value will be 500.<br>'
                '9. "grab_construct_batch_size" value will always be greater than 0.<br>'
                '10. "grab_send_batch_size" should always be on type integer and follow this format "100"<br>'
                '11. "grab_send_batch_size" default value will be 500.<br>'
                '12. "grab_send_batch_size" value will always be greater than 0.<br>'
                '13. "c_score_db_populate_schedule" should always follow this format "01:00" '
                'and have maximum for "23:59"<br>'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &emsp;"populate_schedule": "01:00", <br>'
                '  &emsp;"send_schedule": "03:00", <br>'
                '  &emsp;"grab_construct_batch_size": "1000" <br>'
                '  &emsp;"grab_send_batch_size": "25000" <br>'
                '  &emsp;"c_score_db_populate_schedule": "23:00" <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            populate_schedule = parameters.get('populate_schedule')
            send_schedule = parameters.get('send_schedule')
            grab_construct_batch_size = parameters.get('grab_construct_batch_size')
            grab_send_batch_size = parameters.get('grab_send_batch_size')
            c_score_db_populate_schedule = parameters.get('c_score_db_populate_schedule')

            for key in {'populate_schedule', 'send_schedule', 'grab_construct_batch_size',
                        'grab_send_batch_size', 'c_score_db_populate_schedule'}:
                if not parameters.get(key):
                    raise forms.ValidationError('Parameters should have {} key'.format(key))

            # check input type
            if not isinstance(populate_schedule, str) or not isinstance(send_schedule, str) \
                    or not isinstance(c_score_db_populate_schedule, str):
                raise forms.ValidationError('Invalid parameters, please see example input')

            if not isinstance(grab_construct_batch_size, (str, int)) or not isinstance(
                    grab_send_batch_size, (str, int)):
                raise forms.ValidationError(
                    'Invalid grab_send_batch_size, please see example input')

            """
            - validate populate_schedule and send_schedule is string format
            - validate populate_schedule is not more than 6 AM
            - validate send_schedule is not more than 7 AM
            - validate grab_construct_batch_size is greater than 0
            - validate grab_send_batch_size is greater than 0
            - validate c_score_db_populate_schedule is not more than 23:59 PM
            """
            try:
                splitted_populate_schedule = populate_schedule.split(":")
                if len(splitted_populate_schedule) != 2:
                    raise ValueError('Invalid "populate_schedule" format, e.g: "01:00"')
                if len(splitted_populate_schedule[0]) != 2 or len(
                        splitted_populate_schedule[1]) != 2:
                    raise ValueError('Invalid "populate_schedule" format, e.g: "01:00"')
                ps_hour_part = int(splitted_populate_schedule[0])
                ps_min_part = int(splitted_populate_schedule[1])
                if ps_hour_part < 1 or ps_hour_part > 6 or (ps_hour_part == 6 and ps_min_part > 0):
                    raise ValueError('"populate_schedule" should in range of 1 until 6 AM')

                splitted_send_schedule = send_schedule.split(":")
                if len(splitted_send_schedule) != 2:
                    raise ValueError('Invalid "populate_schedule" format, e.g: "01:00"')
                if len(splitted_send_schedule[0]) != 2 or len(splitted_send_schedule[1]) != 2:
                    raise ValueError('Invalid "send_schedule" format, e.g: "01:00"')
                ss_hour_part = int(splitted_send_schedule[0])
                ss_min_part = int(splitted_send_schedule[1])
                if ss_hour_part < 1 or ss_hour_part > 7 or (ss_hour_part == 7 and ss_min_part > 0):
                    raise ValueError('"send_schedule" should in range of 1 until 7 AM')
                range_of_populate_and_send = ss_hour_part - ps_hour_part
                if range_of_populate_and_send < 1:
                    raise ValueError(
                        '"send_schedule" should be greater one hour from "populate_schedule"')

                if not str(grab_construct_batch_size).isnumeric():
                    raise ValueError('"grab_construct_batch_size" should be a Numeric Value')
                if isinstance(grab_construct_batch_size, str):
                    grab_construct_batch_size = int(grab_construct_batch_size)
                if int(grab_construct_batch_size) <= 0:
                    raise ValueError(
                        '"grab_construct_batch_size" should be greater than 0'
                    )

                if not str(grab_send_batch_size).isnumeric():
                    raise ValueError('"grab_send_batch_size" should be a Numeric Value')
                if isinstance(grab_send_batch_size, str):
                    grab_send_batch_size = int(grab_send_batch_size)
                if int(grab_send_batch_size) <= 0:
                    raise ValueError(
                        '"grab_send_batch_size" should be greater than 0'
                    )
                splitted_c_score_db_populate_schedule = c_score_db_populate_schedule.split(":")
                if len(splitted_c_score_db_populate_schedule) != 2:
                    raise ValueError('Invalid "c_score_db_populate_schedule" format, e.g: "23:00"')
                if len(splitted_c_score_db_populate_schedule[0]) != 2 or len(
                        splitted_c_score_db_populate_schedule[1]) != 2:
                    raise ValueError('Invalid "c_score_db_populate_schedule" format, e.g: "23:00"')
                cs_hour_part = int(splitted_c_score_db_populate_schedule[0])
                cs_min_part = int(splitted_c_score_db_populate_schedule[1])
                if cs_hour_part < 23 or cs_hour_part >= 24 or (cs_hour_part == 23 and cs_min_part >= 60):
                    raise ValueError('"c_score_db_populate_schedule" should in range of 23:00 - 23:59')
            except ValueError as e:
                raise forms.ValidationError(e)
        return self.cleaned_data


class GrabWriteOffFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. early_write_off        : Boolean field to turn on/off the early write off feature <br>'
                '2. 180_dpd_write_off      : Boolean field to turn on/off the 180 DPD write off feature <br>'
                '3. manual_write_off       : Boolean field to turn on/off the manual write off feature <br>'
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. If Feature is not active all are turned off.<br>'
                '2. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '3. "populate_schedule" and "send_schedule" is required inside of parameters<br>'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &emsp;"early_write_off": false, <br>'
                '  &emsp;"180_dpd_write_off": false, <br>'
                '  &emsp;"manual_write_off": false <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            early_write_off = parameters['early_write_off'] if 'early_write_off' in parameters else False
            dpd_180_write_off = parameters['180_dpd_write_off'] if '180_dpd_write_off' in parameters else False
            manual_write_off = parameters['manual_write_off'] if 'manual_write_off' in parameters else False

            if 'early_write_off' not in parameters:
                raise forms.ValidationError('Parameters should have "early_write_off" key')

            if '180_dpd_write_off' not in parameters:
                raise forms.ValidationError('Parameters should have "180_dpd_write_off" key')

            if 'manual_write_off' not in parameters:
                raise forms.ValidationError('Parameters should have "manual_write_off" key')
            # check input type
            if not isinstance(early_write_off, bool) or \
                    not isinstance(manual_write_off, bool) or not isinstance(dpd_180_write_off, bool):
                raise forms.ValidationError('Invalid parameters, please see example input')
        return self.cleaned_data


class DanaLateFeeForm(forms.ModelForm):
    late_fee = forms.FloatField(required=True, help_text='value in decimal format like 0.0015')

    class Meta(object):
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            if instance.parameters:
                self.fields['late_fee'].initial = instance.parameters.get('late_fee')

    def clean(self):
        cleaned_data = super(DanaLateFeeForm, self).clean()
        late_fee = cleaned_data.get('late_fee')
        if not isinstance(late_fee, float) or late_fee <= 0:
            raise forms.ValidationError(
                "invalid late fee amount"
            )
        return cleaned_data


class GopayOnboardingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'is_active']
        help_texts = {
            'parameters':
                'Maximum 3 rows for benefit description <br>'
                'Delete row if not needed <br>'
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')

        if not parameters:
            raise forms.ValidationError('Parameters is required')
        else:
            if len(parameters) > 3:
                raise forms.ValidationError('Maximum 3 benefit description only.')
        return self.cleaned_data


class FraudHotspotForm(forms.ModelForm):
    class Meta(object):
        model = FraudHotspot
        fields = ('geohash', 'latitude', 'longitude', 'radius', 'count_of_application')


class FraudHotspotImportForm(forms.Form):
    csv_file = forms.FileField()


class FraudHotspotAdmin(JuloModelAdmin):
    list_display = ('id', 'geohash', 'latitude', 'longitude', 'radius', 'count_of_application',
                    'addition_date')
    search_fields = ('id', 'geohash', 'latitude', 'longitude', 'radius', 'addition_date')
    list_display_links = ('id', 'latitude', 'longitude', 'radius')

    form = FraudHotspotForm

    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES['csv_file']
            if not csv_file:
                self.message_user(request, 'Fail to read csv file', level='error')
                return redirect('..')

            csv_data = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'), delimiter=',')
            try:
                with transaction.atomic():
                    for row in csv_data:
                        if 'count_of_application' not in row or \
                            ('count_of_application' in row and row['count_of_application'] == ''):
                            row['count_of_application'] = None
                        row['addition_date'] = datetime.date.today()
                        serializer = FraudHotspotSerializer(data=row)
                        if serializer.is_valid(raise_exception=True):
                            serializer.save()
            except Exception as e:
                self.message_user(
                    request,
                    'Fail to import due to error in one or more row: {}'.format(e),
                    level='error'
                )
                return redirect('..')

            self.message_user(request, 'Your csv file has been imported.')
            return redirect('..')

        form = FraudHotspotImportForm()
        payload = {
            'data_table': {
                'property': ['geohash', 'latitude', 'longitude', 'radius', 'count_of_application'],
                'data': ['text (optional)', 'decimal', 'decimal', 'decimal',
                         'whole number (optional)']
            },
            'form': form
        }
        return render(
            request, 'custom_admin/upload_config_form.html', payload
        )

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls
admin.site.register(FraudHotspot, FraudHotspotAdmin)


class GrabReferralFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. max incentivised referral/whitelist: '
                '       Integer field to cap number of referals per whitelist <br>'
                '2. referrer_incentive : number of incentive per referral for referrer <br>'
                '3. referred_incentive : number of incentive per referral for referred <br>'
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. "max incentivised referral/whitelist" is required inside of parameters<br>'
                '2. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '3. "referrer_incentive" and "referred_incentive" is required inside of parameters<br>'
                '4. "referrer_incentive" and "referred_incentive" have maximum value from 0 to 200000 <br>'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &emsp;"max incentivised referral/whitelist": "10", <br>'
                '  &emsp;"referrer_incentive": 50000, <br>'
                '  &emsp;"referred_incentive": 20000, <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            max_referral_per_whitelist = parameters['max incentivised referral/whitelist'] if \
                'max incentivised referral/whitelist' in parameters else False
            referrer_incentive = parameters.get('referrer_incentive')
            referred_incentive = parameters.get('referred_incentive')

            for key in {'referrer_incentive', 'referred_incentive',
                        'max incentivised referral/whitelist'}:
                if key not in parameters:
                    raise forms.ValidationError('Parameters should have "{}" key'.format(key))

            # check input type
            if not isinstance(max_referral_per_whitelist, str) and not isinstance(max_referral_per_whitelist, int):
                raise forms.ValidationError('Invalid parameters, please see example input')

            if not isinstance(referrer_incentive, int) or not isinstance(referred_incentive, int):
                raise forms.ValidationError('Invalid parameters, please see example input')

            if not str(max_referral_per_whitelist).isnumeric():
                raise forms.ValidationError('"max incentivised referral/whitelist" should be an Integer Value')

            if isinstance(max_referral_per_whitelist, str):
                max_referral_per_whitelist = int(max_referral_per_whitelist)

            if int(max_referral_per_whitelist) < 0:
                raise forms.ValidationError(
                    '"max incentivised referral/whitelist" should be greater than or equal to 0'
                )

            try:
                if int(referrer_incentive) < 0 or int(referrer_incentive) > 200000:
                    raise ValueError('"referrer_incentive" should in range of 0 and 200000' )
                if int(referred_incentive) < 0 or int(referred_incentive) > 200000:
                    raise ValueError('"referred_incentive" should in range of 0 and 200000')
                if int(max_referral_per_whitelist) < 0:
                    raise ValueError('"max incentivised referral/whitelist" should be greater than or equal to 0'
                )
            except ValueError as e:
                raise forms.ValidationError(e)

        return self.cleaned_data


class GopayActivationLinkingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'parameters']


class PaymentMethodGroupingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'is_active']
        help_texts = {
            'parameters':
                "These payment method groups won't have an impact on ordering. <br>"
                'The ordering is handled in the back end.'
        }


class GrabModalStopRegistrationFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Notes:</b><br>'
                'Inactivate this feature will also affect to: <br>'
                '1. Disable "ajukan pinjaman button" for GRAB <br>'
                '2. Disable GRAB loan creation<br>'
                '3. Disable GRAB loan offer'
                '<br><br>',
        }


class GrabFileTransferCallFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. populate_daily_txn_schedule : times the populating daily transaction data will happen in a day <br>'
                '2. populate_loan_schedule      : times the populating loan data will happen in a day <br>'
                '3. loan_per_file               : limit loan data generated per file <br>'
                '4. transaction_per_file        : limit daily_transaction data generated per file <br>'
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. Please consult to engineering team before updating the parameters'
                '2. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '3. "populate_daily_txn_schedule" , "populate_loan_schedule" , "loan_per_file" and "transaction_per_file" is required inside of parameters<br>'
                '4. "populate_daily_txn_schedule" should always follow this format "01:00" and have range from "20:00" until "23:59"<br>'
                '5. "populate_loan_schedule" should always follow this format "01:00" and have range from "20:00" until "23:59" <br>'
                '6. "loan_per_file" should always in range from 1 to 25000 <br>'
                '7. "transaction_per_file" should always in range from 1 to 25000 <br>'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &emsp;"populate_daily_txn_schedule": "21:30", <br>'
                '  &emsp;"populate_loan_schedule": "21:30", <br>'
                '  &emsp;"loan_per_file": 1000, <br>'
                '  &emsp;"transaction_per_file": 1000, <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            populate_daily_txn_schedule = parameters.get(
                FeatureSettingParameters.POPULATE_DAILY_TXN_SCHEDULE)
            populate_loan_schedule = parameters.get(FeatureSettingParameters.POPULATE_LOAN_SCHEDULE)
            loan_per_file = parameters.get(FeatureSettingParameters.LOAN_PER_FILE)
            transaction_per_file = parameters.get(FeatureSettingParameters.TRANSACTION_PER_FILE)

            for key in FeatureSettingParameters.GRAB_FILE_TRANSFER_PARAMETERS:
                if not parameters.get(key):
                    raise forms.ValidationError('Parameters should have {} key'.format(key))

            # check input type
            if not isinstance(populate_daily_txn_schedule, str) or \
                    not isinstance(populate_loan_schedule, str) or \
                    not isinstance(loan_per_file, (str, int)) or \
                    not isinstance(transaction_per_file, (str, int)):
                raise forms.ValidationError('Invalid parameters, please see example input')

            try:
                splitted_populate_daily_txn_schedule = populate_daily_txn_schedule.split(":")
                if len(splitted_populate_daily_txn_schedule) != 2:
                    raise ValueError('Invalid "{}" format, e.g: "01:00"'.format(
                        FeatureSettingParameters.POPULATE_DAILY_TXN_SCHEDULE
                    ))
                if len(splitted_populate_daily_txn_schedule[0]) != 2 or len(
                        splitted_populate_daily_txn_schedule[1]) != 2:
                    raise ValueError('Invalid "{}" format, e.g: "01:00"'.format(
                        FeatureSettingParameters.POPULATE_DAILY_TXN_SCHEDULE
                    ))
                pdts_hour_part = int(splitted_populate_daily_txn_schedule[0])
                pdts_min_part = int(splitted_populate_daily_txn_schedule[1])
                if pdts_hour_part < 20 or pdts_hour_part > 23 or (
                        pdts_hour_part == 23 and pdts_min_part > 59):
                    raise ValueError('"{}" should in range of 20:00 until 23:59'.format(
                        FeatureSettingParameters.POPULATE_DAILY_TXN_SCHEDULE
                    ))

                splitted_populate_loan_schedule = populate_loan_schedule.split(":")
                if len(splitted_populate_loan_schedule) != 2:
                    raise ValueError('Invalid "{}" format, e.g: "01:00"'.format(
                        FeatureSettingParameters.POPULATE_LOAN_SCHEDULE
                    ))
                if len(splitted_populate_loan_schedule[0]) != 2 or len(
                        splitted_populate_loan_schedule[1]) != 2:
                    raise ValueError('Invalid "{}" format, e.g: "01:00"'.format(
                        FeatureSettingParameters.POPULATE_LOAN_SCHEDULE
                    ))
                pls_hour_part = int(splitted_populate_loan_schedule[0])
                pls_min_part = int(splitted_populate_loan_schedule[1])
                if pls_hour_part < 20 or pls_hour_part > 23 or (
                        pls_hour_part == 23 and pls_min_part > 59):
                    raise ValueError(
                        '"{}" should in range of 20:00 until 23:59'.format(
                            FeatureSettingParameters.POPULATE_LOAN_SCHEDULE
                        ))

                if not str(loan_per_file).isnumeric():
                    raise ValueError('"{}" should be a Numeric Value'.format(
                        FeatureSettingParameters.LOAN_PER_FILE
                    ))
                if isinstance(loan_per_file, str):
                    loan_per_file = int(loan_per_file)
                if loan_per_file < 1 or loan_per_file > 25000:
                    raise ValueError(
                        '"{}" should be in range 1 to 25000'.format(
                            FeatureSettingParameters.LOAN_PER_FILE
                        ))

                if not str(transaction_per_file).isnumeric():
                    raise ValueError('"{}" should be a Numeric Value'.format(
                        FeatureSettingParameters.TRANSACTION_PER_FILE
                    ))
                if isinstance(transaction_per_file, str):
                    transaction_per_file = int(transaction_per_file)
                if transaction_per_file < 1 or transaction_per_file > 25000:
                    raise ValueError(
                        '"{}" should be in range 1 to 25000'.format(
                            FeatureSettingParameters.TRANSACTION_PER_FILE
                        ))

            except ValueError as e:
                raise forms.ValidationError(e)

        return self.cleaned_data


class MycroftScoreCheckForm(forms.ModelForm):
    def clean(self):
        cleaned_data = super().clean()
        is_active = cleaned_data['is_active']

        if is_active:
            if not MycroftThreshold.objects.filter(is_active=True).exists():
                self.add_error(
                    'is_active',
                    'Cannot activate feature. At least one active MycroftThreshold is required.'
                )

        return cleaned_data


class SuspiciousDomainForm(forms.ModelForm):
    class Meta(object):
        model = SuspiciousDomain
        fields = '__all__'

    def clean_email_domain(self):
        email_domain = self.cleaned_data.get('email_domain')
        if SuspiciousDomain.objects.filter(email_domain=email_domain).exists():
            raise forms.ValidationError('This email domain already exists.')
        return email_domain


class SuspiciousDomainImportForm(forms.Form):
    csv_file = forms.FileField()


class SuspiciousDomainAdmin(JuloModelAdmin):
    list_display = ('id', 'email_domain', 'reason')
    search_fields = ('id', 'email_domain')
    list_display_links = ('id', 'email_domain')

    form = SuspiciousDomainForm

    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                self.message_user(request, 'Fail to read csv file', level='error')
                return redirect('..')

            csv_data = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'), delimiter=',')
            try:
                with transaction.atomic():
                    for row in csv_data:
                        serializer = SuspiciousDomainSerializer(data=row)
                        if serializer.is_valid(raise_exception=True):
                            if not SuspiciousDomain.objects.filter(email_domain=serializer.validated_data.get("email_domain")).exists():
                                serializer.save()

            except Exception as e:
                self.message_user(
                    request,
                    'Fail to import due to error in one or more row: {}'.format(e),
                    level='error'
                )
                return redirect('..')

            self.message_user(request, 'Your csv file has been imported.')
            return redirect('..')

        form = SuspiciousDomainImportForm()
        payload = {
            'data_table': {
                'property': ['email_domain', 'reason'],
                'data': ['text', 'text']
            },
            'form': form
        }
        return render(
            request, 'custom_admin/upload_config_form.html', payload
        )

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

admin.site.register(SuspiciousDomain, SuspiciousDomainAdmin)


class HandlingDialerAlertForm(forms.ModelForm):
    def clean(self):
        cleaned_data = super().clean()
        parameters = cleaned_data['parameters']
        if parameters:
            current_bucket = parameters.get('current_bucket', [])
            if current_bucket:
                valid_current_bucket = list(IntelixTeam.CURRENT_BUCKET_V2)
                invalid_current_bucket = [
                    value for value in current_bucket if value not in valid_current_bucket]
                if invalid_current_bucket:
                    raise forms.ValidationError(
                        '''bucket name {} not allowed for current_bucket key
                        , please put value based on this {}'''.format(
                            json.dumps(invalid_current_bucket), json.dumps(valid_current_bucket))
                    )
            bucket_improved = parameters.get('bucket_improved', [])
            if bucket_improved:
                valid_bucket_improved = list(DialerTaskType.DIALER_TASK_TYPE_IMPROVED.values())
                invalid_bucket_improved = [
                    value for value in bucket_improved
                    if value not in valid_bucket_improved]
                if invalid_bucket_improved:
                    raise forms.ValidationError(
                        '''bucket name {} not allowed for bucket_improved key
                        , please put value based on this {}'''.format(
                            json.dumps(invalid_bucket_improved), json.dumps(valid_bucket_improved))
                    )

        return cleaned_data


class PaymentMethodFaqForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'is_active']


class AutodebetForm(forms.ModelForm):
    disable = forms.CharField(widget=forms.Textarea)
    minimum_amount = forms.IntegerField(required=False)
    retry_schedule = forms.CharField(required=False, widget=forms.Textarea)
    deduction_dpd = forms.CharField(required=False, widget=forms.Textarea)

    class Meta(object):
        fields = [
            'is_active',
            'minimum_amount',
            'disable',
            'category',
            'description',
            'retry_schedule',
            'deduction_dpd',
        ]

    def __init__(self, *args, **kwargs):
        super(AutodebetForm, self).__init__(*args, **kwargs)
        self.fields['disable'].help_text = \
            "Disable start time and end time has to be in this format DD-MM-YYYY HH:MM <br>" \
                "Anything else will cause error"
        if self.instance.feature_name == AutodebetFeatureNameConst.AUTODEBET_GOPAY:
            self.fields[
                'deduction_dpd'
            ].help_text = "start_dpd and end_dpd refer to the start and end days for creating a subscription. However, the actual payment dates are one day after these values. For example, if start_dpd = -1, the payment will occur on the 0 dpd."

        instance = kwargs.get('instance')
        if instance:
            if instance.parameters.get('minimum_amount'):
                self.fields['minimum_amount'].required = True
                self.fields['minimum_amount'].initial = instance.parameters['minimum_amount']
            else:
                self.fields['minimum_amount'].widget = forms.HiddenInput()
            if instance.parameters.get('retry_schedule'):
                self.fields['retry_schedule'].required = True
                self.fields['retry_schedule'].initial = json.dumps(
                    instance.parameters['retry_schedule']
                )
            else:
                self.fields['retry_schedule'].widget = forms.HiddenInput()
            if instance.parameters.get('deduction_dpd'):
                self.fields['deduction_dpd'].required = True
                self.fields['deduction_dpd'].initial = json.dumps(
                    instance.parameters['deduction_dpd']
                )
            else:
                self.fields['deduction_dpd'].widget = forms.HiddenInput()
            self.fields['disable'].initial = json.dumps(instance.parameters['disable'])

    def clean(self):
        if self.instance.feature_name == AutodebetFeatureNameConst.AUTODEBET_GOPAY:
            parameters = self.cleaned_data
            retry_schedule = json.loads(parameters.get('retry_schedule'))
            if not retry_schedule:
                raise forms.ValidationError('retry_schedule is required')

            required_fields = {'interval': int, 'interval_unit': str, 'max_interval': int}

            for field, expected_type in required_fields.items():
                if not isinstance(retry_schedule.get(field), expected_type):
                    raise forms.ValidationError(
                        '{} must be of type {}'.format(field, expected_type.__name__)
                    )

            if retry_schedule['interval_unit'] not in ['minute', 'hour', 'day']:
                raise forms.ValidationError('interval_unit must be one of: minute, hour, day')

            deduction_dpd = json.loads(parameters.get('deduction_dpd'))
            if not deduction_dpd:
                raise forms.ValidationError('deduction_dpd is required')

            dpd_start = deduction_dpd.get("dpd_start")
            dpd_end = deduction_dpd.get("dpd_end")
            if dpd_start == None or dpd_end == None:
                raise forms.ValidationError(
                    'deduction_dpd.dpd_start and deduction_dpd.dpd_end is required'
                )
            if not isinstance(dpd_start, int) or not isinstance(dpd_end, int):
                raise forms.ValidationError(
                    'deduction_dpd.dpd_start and deduction_dpd.dpd_end must be an integer'
                )
            if dpd_start > 0:
                raise forms.ValidationError('deduction_dpd.dpd_start must be less than or equal 0')
            if dpd_end < -1:
                raise forms.ValidationError(
                    'deduction_dpd.dpd_end must be greater than or equal -1'
                )
        elif self.instance.feature_name in [
            AutodebetFeatureNameConst.AUTODEBET_DANA,
            AutodebetFeatureNameConst.AUTODEBET_OVO,
        ]:
            parameters = self.cleaned_data
            deduction_dpd = json.loads(parameters.get('deduction_dpd'))
            if not deduction_dpd:
                raise forms.ValidationError('deduction_dpd is required')

            dpd_start = deduction_dpd.get("dpd_start")
            dpd_end = deduction_dpd.get("dpd_end")
            if dpd_start == None or dpd_end == None:
                raise forms.ValidationError(
                    'deduction_dpd.dpd_start and deduction_dpd.dpd_end is required'
                )
            if not isinstance(dpd_start, int) or not isinstance(dpd_end, int):
                raise forms.ValidationError(
                    'deduction_dpd.dpd_start and deduction_dpd.dpd_end must be an integer'
                )
            if dpd_start > 0:
                raise forms.ValidationError('deduction_dpd.dpd_start must be less than or equal 0')
            if dpd_end < 0:
                raise forms.ValidationError('deduction_dpd.dpd_end must be greater than or equal 0')
        return self.cleaned_data


class FraudHighRiskAsnForm(forms.ModelForm):
    class Meta(object):
        model = FraudHighRiskAsn
        fields = ('name',)


class FraudHighRiskAsnImportForm(forms.Form):
    csv_file = forms.FileField()


class FraudHighRiskAsnAdmin(JuloModelAdmin):
    list_display = ('id', 'name',)
    search_fields = ('name',)
    list_display_links = ('id', 'name',)

    form = FraudHighRiskAsnForm

    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES['csv_file']
            if not csv_file:
                self.message_user(request, 'Fail to read csv file', level='error')
                return redirect('..')

            csv_data = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'), delimiter=',')
            try:
                with transaction.atomic():
                    for row in csv_data:
                        serializer = FraudHighRiskAsnSerializer(data=row)
                        if serializer.is_valid(raise_exception=True):
                            serializer.save()
            except Exception as e:
                self.message_user(
                    request,
                    'Fail to import due to error in one or more row: {}'.format(e),
                    level='error'
                )
                return redirect('..')

            self.message_user(request, 'Your csv file has been imported.')
            return redirect('..')

        form = FraudHighRiskAsnImportForm()
        payload = {
            'data_table': {
                'property': ['name'],
                'data': ['text']
            },
            'form': form
        }
        return render(
            request, 'custom_admin/upload_config_form.html', payload
        )

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls


admin.site.register(FraudHighRiskAsn, FraudHighRiskAsnAdmin)


class HelpCenterItemAdmin(JuloModelAdmin):
    list_display = ('id', 'question', 'section', 'visible')
    list_filter = ('section', 'visible')
    list_display_links = ('id', 'question')

admin.site.register(HelpCenterItem, HelpCenterItemAdmin)


class HelpCenterSectionAdmin(JuloModelAdmin):
    list_display = ('id', 'title', 'visible')
    list_filter = ('title', 'visible')
    list_display_links = ('id', 'title')

admin.site.register(HelpCenterSection, HelpCenterSectionAdmin)


class GrabPGRatioSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters': '<b>Description:</b><br>'
            '1. doku_ratio: doku ratio in number followed by % <br>'
            '2. ac_ratio : ayoconnect ratio in number followed by %  <br>'
            '<br><br>'
            '<b>Rules to follow:</b><br>'
            '1. Always use "{" in the start and use "}" in the end of parameters.<br>'
            '2. "doku_ratio" and "ac_ratio" is required inside of parameters<br>'
            '3. "doku_ratio" and "ac_ratio" total should be 100% <br>'
            '<br><br>'
            '<b>Example Input:</b><br>'
            '{ <br>'
            '  &emsp;"doku_ratio": "50%", <br>'
            '  &emsp;"ac_ratio": "50%" <br>'
            '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            doku_ratio = parameters.get('doku_ratio')
            ac_ratio = parameters.get('ac_ratio')
            for key in {'doku_ratio', 'ac_ratio'}:
                if key not in parameters:
                    raise forms.ValidationError('Parameters should have "{}" key'.format(key))

            total_percentage = 0
            if doku_ratio:
                doku_ratio_data = doku_ratio.split('%')
                if (
                    doku_ratio_data
                    and doku_ratio_data[0].isdigit()
                    and len(doku_ratio_data) == 2
                    and doku_ratio_data[1] == ''
                ):
                    total_percentage = total_percentage + int(doku_ratio_data[0])
                else:
                    raise forms.ValidationError("invalid doku_ratio")

            if ac_ratio:
                ac_ratio_data = ac_ratio.split('%')
                if (ac_ratio_data and ac_ratio_data[0].isdigit() and
                        len(ac_ratio_data) == 2 and ac_ratio_data[1] == ''):
                    total_percentage = total_percentage + int(ac_ratio_data[0])
                else:
                    raise forms.ValidationError("invalid ac_ratio")

            if total_percentage > 100:
                raise forms.ValidationError(
                    "total rasio tidak boleh lebih dari 100%"
                )
            elif total_percentage < 100:
                raise forms.ValidationError(
                    "total rasio tidak boleh kurang dari 100%"
                )
            return self.cleaned_data


class FormAlertMessageConfigAdmin(JuloModelAdmin):
    list_display = ('id', 'screen', 'title')


admin.site.register(FormAlertMessageConfig, FormAlertMessageConfigAdmin)


class SimilarAndFraudFaceTimeLimitForm(forms.ModelForm):
    class Meta(object):
        fields = '__all__'
        model = FeatureSetting

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if not parameters:
            if 'parameters' in self._errors:
                return cleaned_data

        if 'pending_status_wait_time_limit_in_minutes' not in parameters:
            raise forms.ValidationError(
                'Parameters field must have \'pending_status_wait_time_limit_in_minutes\' key.'
                'E.g: {"pending_status_wait_time_limit_in_minutes": 30}'
            )

        pending_status_wait_time_limit_in_minutes = parameters[
            'pending_status_wait_time_limit_in_minutes'
        ]
        if (not isinstance(pending_status_wait_time_limit_in_minutes, int)):
            raise forms.ValidationError(
                'Parameters field dictionary \'pending_status_wait_time_limit_in_minutes\' must '
                'be a number value.'
                'E.g: {"pending_status_wait_time_limit_in_minutes": 30}'
            )

        if pending_status_wait_time_limit_in_minutes < 0:
            raise forms.ValidationError(
                'pending_status_wait_time_limit_in_minutes value must be equal or larger than 0.'
            )

        return cleaned_data


class GrabSmallerLoanOptionsForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. min_loan_amount: loan amount criteria for elligible user% <br>'
                '2. range_to_max_gen_loan_amount : loan amount max generated  criteria for elligible user%  <br>'
                '2. loan_option_range : array of loan option percentage %  <br>'
                '2. loan_tenure : loan option duration %  <br>'
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '2. "min_loan_amount", "range_to_max_gen_loan_amount", "loan_option_range" and "loan_tenure" is required inside of parameters<br>'
                '3. "loan_option_range" value cannot more than 99% <br>'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &emsp;"min_loan_amount": 3500000, <br>'
                '  &emsp;"range_to_max_gen_loan_amount": 2000000 <br>'
                '  &emsp;"loan_option_range": ["30%", "60%"] <br>'
                '  &emsp;"loan_tenure": 180 <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            loan_option_range = parameters.get('loan_option_range')
            for key in {'min_loan_amount', 'range_to_max_gen_loan_amount', 'loan_option_range',
                        'loan_tenure'}:
                if key not in parameters:
                    raise forms.ValidationError('Parameters should have "{}" key'.format(key))

            percentage_threshold = 99
            for loan_option in loan_option_range:
                try:
                    loan_option_range_digit = re.match(r'(\d+)%', loan_option).group(1)
                    if int(loan_option_range_digit) > percentage_threshold:
                        raise forms.ValidationError("loan_option_range value cannot more than 100%")
                except forms.ValidationError as err:
                    raise forms.ValidationError(err.message)
                except (IndexError, AttributeError, TypeError) as err:
                    raise forms.ValidationError("invalid loan_option_range")

            return self.cleaned_data


class DanaOtherPageItemSerializer(serializers.Serializer):
    title_content = serializers.CharField(required=True)
    web_link = serializers.CharField(required=False, allow_blank=True)
    type = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['type'] == 'link' and not attrs.get('web_link'):
            raise serializers.ValidationError(
                {'web_link': 'This field is required when type is "link"'}
            )

        if 'web_link' not in attrs:
            attrs['web_link'] = ''

        return attrs


class DanaOtherPageSerializer(serializers.ListSerializer):
    child = DanaOtherPageItemSerializer()

    @staticmethod
    def format_errors(error_list):
        formatted_errors = []
        for idx, item_errors in enumerate(error_list):
            if isinstance(item_errors, dict) and item_errors:
                error_message = f"Item {idx + 1}: "
                field_errors = []
                for field, errors in item_errors.items():
                    if isinstance(errors, list):
                        field_errors.append(f"{field}: {'; '.join(errors)}")
                    else:
                        field_errors.append(f"{field}: {errors}")
                error_message += ", ".join(field_errors)
                formatted_errors.append(error_message)
            elif isinstance(item_errors, str):
                formatted_errors.append(item_errors)
        return formatted_errors


class DanaOtherPageForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'is_active']

    serializer_class = DanaOtherPageSerializer

    def clean_parameters(self):
        parameters = self.cleaned_data['parameters']
        serializer = self.serializer_class(data=parameters)
        if not serializer.is_valid():
            raise forms.ValidationError(self.serializer_class.format_errors(serializer.errors))
        return parameters


class GrabAirudderCallFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. populate_schedule          : times the populating data will happen in a day <br>'
                '2. send_schedule              : times the sending data will happen in a day <br>'
                '3. grab_construct_batch_size  : this batch size will limit the data that need to be constructed<br>'
                '4. grab_send_batch_size       : this Batch size will limit the data we fetch while '
                'sending data to ai rudder<br>'
                '5. c_score_db_populate_schedule : times the c_score_db_populate will happen in a day <br> '
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. Please consult to engineering team before updating the parameters'
                '2. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '3. "populate_schedule" , "send_schedule" and "c_score_db_populate_schedule" '
                'is required inside of parameters<br>'
                '4. "populate_schedule" should always follow this format "01:00" and have maximum for "06:00"<br>'
                '5. "send_schedule" should always follow this format "01:00" and have maximum for "07:00" <br>'
                '6. "send_schedule" should be bigger than "populate_schedule" with range 1 hour<br>'
                '7. "grab_construct_batch_size" should always be on type integer and follow this format "100"<br>'
                '8. "grab_construct_batch_size" default value will be 500.<br>'
                '9. "grab_construct_batch_size" value will always be greater than 0.<br>'
                '10. "grab_send_batch_size" should always be on type integer and follow this format "100"<br>'
                '11. "grab_send_batch_size" default value will be 500.<br>'
                '12. "grab_send_batch_size" value will always be greater than 0.<br>'
                '13. "c_score_db_populate_schedule" should always follow this format "01:00" '
                'and have maximum for "23:59"<br>'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &emsp;"populate_schedule": "01:00", <br>'
                '  &emsp;"send_schedule": "03:00", <br>'
                '  &emsp;"grab_construct_batch_size": "1000" <br>'
                '  &emsp;"grab_send_batch_size": "25000" <br>'
                '  &emsp;"c_score_db_populate_schedule": "23:00" <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            populate_schedule = parameters.get('populate_schedule')
            send_schedule = parameters.get('send_schedule')
            grab_construct_batch_size = parameters.get('grab_construct_batch_size')
            grab_send_batch_size = parameters.get('grab_send_batch_size')
            c_score_db_populate_schedule = parameters.get('c_score_db_populate_schedule')

            for key in {'populate_schedule', 'send_schedule', 'grab_construct_batch_size',
                        'grab_send_batch_size', 'c_score_db_populate_schedule'}:
                if not parameters.get(key):
                    raise forms.ValidationError('Parameters should have {} key'.format(key))

            # check input type
            if not isinstance(populate_schedule, str) or not isinstance(send_schedule, str) \
                    or not isinstance(c_score_db_populate_schedule, str):
                raise forms.ValidationError('Invalid parameters, please see example input')

            if not isinstance(grab_construct_batch_size, (str, int)) or not isinstance(
                    grab_send_batch_size, (str, int)):
                raise forms.ValidationError(
                    'Invalid grab_send_batch_size, please see example input')

            """
            - validate populate_schedule and send_schedule is string format
            - validate populate_schedule is not more than 6 AM
            - validate send_schedule is not more than 7 AM
            - validate grab_construct_batch_size is greater than 0
            - validate grab_send_batch_size is greater than 0
            - validate c_score_db_populate_schedule is not more than 23:59 PM
            """
            try:
                splitted_populate_schedule = populate_schedule.split(":")
                if len(splitted_populate_schedule) != 2:
                    raise ValueError('Invalid "populate_schedule" format, e.g: "01:00"')
                if len(splitted_populate_schedule[0]) != 2 or len(
                        splitted_populate_schedule[1]) != 2:
                    raise ValueError('Invalid "populate_schedule" format, e.g: "01:00"')
                ps_hour_part = int(splitted_populate_schedule[0])
                ps_min_part = int(splitted_populate_schedule[1])
                if ps_hour_part < 1 or ps_hour_part > 6 or (ps_hour_part == 6 and ps_min_part > 0):
                    raise ValueError('"populate_schedule" should in range of 1 until 6 AM')

                splitted_send_schedule = send_schedule.split(":")
                if len(splitted_send_schedule) != 2:
                    raise ValueError('Invalid "populate_schedule" format, e.g: "01:00"')
                if len(splitted_send_schedule[0]) != 2 or len(splitted_send_schedule[1]) != 2:
                    raise ValueError('Invalid "send_schedule" format, e.g: "01:00"')
                ss_hour_part = int(splitted_send_schedule[0])
                ss_min_part = int(splitted_send_schedule[1])
                if ss_hour_part < 1 or ss_hour_part > 7 or (ss_hour_part == 7 and ss_min_part > 0):
                    raise ValueError('"send_schedule" should in range of 1 until 7 AM')
                range_of_populate_and_send = ss_hour_part - ps_hour_part
                if range_of_populate_and_send < 1:
                    raise ValueError(
                        '"send_schedule" should be greater one hour from "populate_schedule"')

                if not str(grab_construct_batch_size).isnumeric():
                    raise ValueError('"grab_construct_batch_size" should be a Numeric Value')
                if isinstance(grab_construct_batch_size, str):
                    grab_construct_batch_size = int(grab_construct_batch_size)
                if int(grab_construct_batch_size) <= 0:
                    raise ValueError(
                        '"grab_construct_batch_size" should be greater than 0'
                    )

                if not str(grab_send_batch_size).isnumeric():
                    raise ValueError('"grab_send_batch_size" should be a Numeric Value')
                if isinstance(grab_send_batch_size, str):
                    grab_send_batch_size = int(grab_send_batch_size)
                if int(grab_send_batch_size) <= 0:
                    raise ValueError(
                        '"grab_send_batch_size" should be greater than 0'
                    )
                splitted_c_score_db_populate_schedule = c_score_db_populate_schedule.split(":")
                if len(splitted_c_score_db_populate_schedule) != 2:
                    raise ValueError('Invalid "c_score_db_populate_schedule" format, e.g: "23:00"')
                if len(splitted_c_score_db_populate_schedule[0]) != 2 or len(
                        splitted_c_score_db_populate_schedule[1]) != 2:
                    raise ValueError('Invalid "c_score_db_populate_schedule" format, e.g: "23:00"')
                cs_hour_part = int(splitted_c_score_db_populate_schedule[0])
                cs_min_part = int(splitted_c_score_db_populate_schedule[1])
                if cs_hour_part < 23 or cs_hour_part >= 24 or (cs_hour_part == 23 and cs_min_part >= 60):
                    raise ValueError('"c_score_db_populate_schedule" should in range of 23:00 - 23:59')
            except ValueError as e:
                raise forms.ValidationError(e)
        return self.cleaned_data


class DisablePaymentMethodForm(forms.ModelForm):

    class Meta:
        model = FeatureSetting
        fields = '__all__'
        help_texts = {
            'parameters':
                "Disable start time and end time has to be in this format DD-MM-YYYY HH:MM <br>"
                "Anything else will cause error"
        }


class PaymentGatewayAlertForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Description:</b><br>'
                '1. slack_alert_staging: toggle alert on staging <br>'
                '2. slack_alert_uat : toggle alert on uat <br>'
                '2. slack_alert_prod : toggle alert on prod <br>'
                '2. min_balance_ayoconnect : minimum balance for trigger ayoconnect insufficient balance alert <br>'
                '<br><br>'
                '<b>Rules to follow:</b><br>'
                '1. Always use "{" in the start and use "}" in the end of parameters.<br>'
                '2. "slack_alert_staging", "slack_alert_uat", "slack_alert_prod" and "min_balance_ayoconnect" is required inside of parameters<br>'
                '3. "slack_alert_staging", "slack_alert_uat", "slack_alert_prod should only using true/false <br>'
                '<br><br>'
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &emsp;"slack_alert_staging": true, <br>'
                '  &emsp;"slack_alert_staging": true <br>'
                '  &emsp;"slack_alert_staging": true <br>'
                '  &emsp;"min_balance_ayoconnect": 1000000000 <br>'
                '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            for key in {'slack_alert_staging', 'slack_alert_uat', 'slack_alert_prod',
                        'min_balance_ayoconnect'}:
                if key not in parameters:
                    raise forms.ValidationError('Parameters should have "{}" key'.format(key))
                if key in {'slack_alert_staging', 'slack_alert_uat',
                           'slack_alert_prod'} and parameters.get(key) not in {True, False}:
                    raise forms.ValidationError(
                        'Parameters {} should only true / false '.format(key))

            return self.cleaned_data


class AutodebetMandiriMaxLimitDeductionForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'is_active']


class LateFeeRuleForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']

    parameters = JSONFormField(required=True, widget=LateFeeRulePrettyJSONWidget)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ordered_value = dict(
            sorted(self.initial.get('parameters', {}).items(), key=lambda item: int(item[0]))
        )
        self.initial['parameters'] = ordered_value

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        for key, value in parameters.items():
            # Check if key is a string representation of an integer
            if not key.isdigit():
                raise forms.ValidationError('key for dpd must be numeric')
            # Convert value to float and check if it's within the range [0, 1.0]
            try:
                float_value = float(value)
                if float_value < 0 or float_value > 1.0:
                    raise forms.ValidationError('value must be in range 0 - 1.0')
            except ValueError:
                # If value cannot be converted to float, it's not within the range [0, 1.0]
                raise forms.ValidationError('invalid value')

        return self.cleaned_data


class ReinquiryAutodebetForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                'The changes will be implemented on the following day.'
        }

class GrabDisbursementRetryForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters': '<b>Description:</b><br>'
            '1. max_retry_times: maximum number disbursement can be retried <br>'
            '2. delay_in_min : delay for each disbursement <br>'
            '<br><br>'
            '<b>Rules to follow:</b><br>'
            '1. Always use "{" in the start and use "}" in the end of parameters.<br>'
            '2. "max_retry_times", "delay_in_min" is required inside of parameters<br>'
            '3. "max_retry_times" and "delay_in_min" value cannot less than 0 <br>'
            '<br><br>'
            '<b>Example Input:</b><br>'
            '{ <br>'
            '  &emsp;"max_retry_times": 0, <br>'
            '  &emsp;"delay_in_min": 5 <br>'
            '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            max_retry_times = parameters.get('max_retry_times')
            delay_in_min = parameters.get('delay_in_min')
            for key in {'max_retry_times', 'delay_in_min'}:
                if key not in parameters:
                    raise forms.ValidationError('Parameters should have "{}" key'.format(key))

            min_max_retry_times = 0
            min_delay = 0
            try:
                if int(delay_in_min) < min_delay:
                    raise forms.ValidationError(
                        "delay_in_min value cannot less than {}".format(min_delay)
                    )
                if int(max_retry_times) < min_max_retry_times:
                    raise forms.ValidationError(
                        "max_retry_times value cannot less than {}".format(min_max_retry_times)
                    )
            except forms.ValidationError as err:
                raise forms.ValidationError(err.message)
            except (IndexError, AttributeError, TypeError) as err:
                raise forms.ValidationError(str(err))

            return self.cleaned_data


class ExcludeLatestPaymentMethodForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                "The payment method name should be exactly same as the name presented <br>"
                "in the payment method DB, Anything else will cause error."
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if parameters:
            payment_method_name_list = parameters.get('payment_method_name')
            if payment_method_name_list:
                for payment_method_name in payment_method_name_list:
                    if payment_method_name not in active_payment_method_name_list:
                        raise forms.ValidationError(
                            "The payment method name {} is not matching with the name presented in DB".format(payment_method_name)
                        )

        return self.cleaned_data


class AutodebetBniMaxLimitDeductionForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'is_active']


class GrabAdminFeeFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters':
                '<b>Example Input:</b><br>'
                '{ <br>'
                '  &nbsp;"no_of_tiers": "3", <br>'
                '  &nbsp;"tiers": [<br>'
                '  &nbsp;&nbsp;&nbsp;{ <br> '
                '  &nbsp;&nbsp;&nbsp;&nbsp;"range" : [0, 1000000],<br>'
                '  &nbsp;&nbsp;&nbsp;&nbsp;"admin_fee" : 35000<br>'
                '  &nbsp;&nbsp;&nbsp;}, <br> '
                '  &nbsp;&nbsp;&nbsp;{ <br> '
                '  &nbsp;&nbsp;&nbsp;&nbsp;"range" : [1000001, 1500000],<br>'
                '  &nbsp;&nbsp;&nbsp;&nbsp;"admin_fee" : 55000<br>'
                '  &nbsp;&nbsp;&nbsp;}, <br> '
                '  &nbsp;&nbsp;&nbsp;{ <br> '
                '  &nbsp;&nbsp;&nbsp;&nbsp;"range" : [1500001, 100000000],<br>'
                '  &nbsp;&nbsp;&nbsp;&nbsp;"admin_fee" : 75000<br>'
                '  &nbsp;&nbsp;&nbsp;} <br> '
                '  &nbsp;] <br>'
                '}',
        }

    def equality_check_tier_range(self, arr1, arr2):
        if len(arr1) != len(arr2):
            return False

        arr1.sort()
        arr2.sort()
        if arr1 == arr2:
            return True

        return False

    def add_or_update_product_lookup(self, tiers):
        interest_rates = ProductLookup.objects.filter(
            product_line_id=ProductLineCodes.GRAB,
            is_active=True).values_list('interest_rate', flat=True)
        interest_rates = set(interest_rates)
        for tier in tiers:
            with transaction.atomic():
                for interest_rate in interest_rates:
                    data = {
                        'product_line_id': ProductLineCodes.GRAB,
                        'interest_rate': interest_rate,
                        'admin_fee': tier.get('admin_fee')
                    }
                    product_lookup = ProductLookup.objects.filter(**data).last()
                    if product_lookup:
                        product_lookup.is_active = True
                        product_lookup.save()
                    else:
                        interest = 120 * interest_rate * 100
                        product_name = "I.{}-O.000-L.000-C1.000-C2.000-D".format(round(interest))
                        data['is_active'] = True
                        data['product_name'] = product_name
                        data['origination_fee_pct'] = 0
                        data['late_fee_pct'] = 0
                        data['cashback_initial_pct'] = 0
                        data['cashback_payment_pct'] = 0
                        ProductLookup.objects.get_or_create(**data)

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        is_active = self.cleaned_data.get('is_active')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters, please see example input')

            no_of_tiers = str(parameters.get('no_of_tiers'))
            tiers = parameters.get('tiers')

            for key in {'no_of_tiers', 'tiers'}:
                if key == 'no_of_tiers' and parameters.get(key) == 0:
                    continue

                if not parameters.get(key):
                    raise forms.ValidationError('Parameters should have {} key'.format(key))

            if not no_of_tiers.isdigit():
                raise forms.ValidationError('no_of_tiers should be an integer')

            if len(tiers) != int(no_of_tiers):
                raise forms.ValidationError('no_of_tiers and length of tiers should be same')

            range_arrays = []
            for index, tier in enumerate(tiers):
                position = index + 1
                admin_fee_key = 'admin_fee'
                range_key = 'range'
                if admin_fee_key not in tier:
                    raise forms.ValidationError('tier {} should have {}'.format(position, admin_fee_key))

                if not str(tier.get(admin_fee_key)).isdigit():
                    raise forms.ValidationError('admin_fee of tier {} should be integer'.format(position))

                if range_key not in tier:
                    raise forms.ValidationError('tier {} should have {}'.format(position, range_key))

                if len(tier.get(range_key)) != 2:
                    raise forms.ValidationError('tier {} range should have 2 values'.format(position))
                elif not str(tier.get(range_key)[0]).isdigit() or not str(tier.get(range_key)[1]).isdigit():
                    raise forms.ValidationError('range values of tier {} should be integer'.format(position))
                elif tier.get(range_key)[0] >= tier.get(range_key)[1]:
                    raise forms.ValidationError('lower limit of tier {} range should be '
                                                'less than upper limit'.format(position))
                range = tier.get('range')
                range_arrays.append(range)

            for position, tier in enumerate(tiers):
                range = tier.get('range')
                if len(range_arrays) > 1:
                    for index, range_array in enumerate(range_arrays):
                        if index != position:
                            is_equal_array = self.equality_check_tier_range(
                                range, range_array
                            )
                            if is_equal_array:
                                raise forms.ValidationError('tier {} range and tier {} '
                                                            'range should not be same'.
                                                            format(position+1, index+1))
            if is_active:
                self.add_or_update_product_lookup(tiers)

        return self.cleaned_data


class InsufficientBalanceFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id', 'is_active']


class GrabFeatureSettingAdmin(DynamicFormModelAdmin):
    list_display = (
        'feature_name',
        'is_active',
        'category',
    )
    readonly_fields = ('feature_name', 'preview_image')
    list_filter = ('is_active',)
    search_fields = ('feature_name',)
    ordering = ('feature_name',)
    formfield_overrides = {JSONField: {'widget': PrettyJSONWidget}}
    dynamic_form_key_field = 'feature_name'

    class Media(object):
        js = ('default/js/slider_script.js',)  # project static folder
        css = {'all': ('default/css/slider-style.css',)}

    def history_view(self, request, object_id, extra_context=None):
        "The 'history' admin view for this model."
        from django.contrib.admin.models import LogEntry

        # First check if the user can see this history.
        model = self.model
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404(
                _('%(name)s object with primary key %(key)r does not exist.')
                % {
                    'name': force_text(model._meta.verbose_name),
                    'key': escape(object_id),
                }
            )

        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        # Then get the history for this object.
        opts = model._meta
        app_label = opts.app_label
        action_list = (
            LogEntry.objects.filter(
                object_id=unquote(object_id), content_type=get_content_type_for_model(model)
            )
            .select_related()
            .order_by('-action_time')
        )

        context = dict(
            self.admin_site.each_context(request),
            title=_('Change history: %s') % force_text(obj),
            action_list=action_list,
            module_name=capfirst(force_text(opts.verbose_name_plural)),
            object=obj,
            opts=opts,
            preserved_filters=self.get_preserved_filters(request),
        )
        context.update(extra_context or {})

        request.current_app = self.admin_site.name

        return TemplateResponse(
            request,
            self.object_history_template
            or [
                "admin/%s/%s/object_history.html" % (app_label, opts.model_name),
                "admin/%s/object_history.html" % app_label,
                "admin/object_history.html",
            ],
            context,
        )

    def get_actions(self, request):
        # Disable delete
        actions = super(GrabFeatureSettingAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def has_add_permission(self, request):
        return False

    def get_form(self, request, obj=None, **kwargs):
        self.change_form_template = None
        if obj.feature_name == GrabFeatureNameConst.GRAB_POPULATING_CONFIG:
            self.form = GrabPopulatingConfigFeatureSettingForm
        elif obj.feature_name == GrabFeatureNameConst.GRAB_CRS_FLOW_BLOCKER:
            self.form = GrabFlowBlockerAdminForm
        elif obj.feature_name == GrabFeatureNameConst.GRAB_FDC_AUTO_APPROVAL:
            self.form = GrabFDCAutoApprovalSettingForm
        else:
            self.form = forms.ModelForm
            self.fieldsets = None
        return super(GrabFeatureSettingAdmin, self).get_form(request, obj, **kwargs)

    def preview_image(self, obj):
        return mark_safe('<img src="{url}" width="{width}" />'.format(url=obj.image_url, width=300))

    def get_readonly_fields(self, request, obj=None):
        if obj.feature_name in {
            GrabFeatureNameConst.GRAB_POPULATING_CONFIG,
            GrabFeatureNameConst.GRAB_CRS_FLOW_BLOCKER,
            GrabFeatureNameConst.GRAB_FDC_AUTO_APPROVAL,
        }:
            self.readonly_fields = ('feature_name',)
            return self.readonly_fields
        return super().get_readonly_fields(request, obj)


class GrabPopulatingConfigFeatureSettingForm(forms.ModelForm):
    class Meta:
        model = GrabFeatureSetting
        exclude = ['id']

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, list):
                raise forms.ValidationError('Invalid parameters, please see example input')

            for param in parameters:
                for key in {'category', 'dpd', 'rank', 'score'}:
                    if key not in param:
                        raise forms.ValidationError('Parameters should have "{}" key'.format(key))

                rank = param.get('rank')
                list_of_category = param.get('category', [])
                list_of_dpd = param.get('dpd', [])
                list_of_score = param.get('score', [])

                if not list_of_dpd:
                    raise forms.ValidationError('dpd cannot be null on rank {}'.format(rank))

                if list_of_category:
                    for category in list_of_category:
                        if category not in {'2W', '4W'}:
                            raise forms.ValidationError(
                                'wrong vehicle type value on rank {}'.format(rank)
                            )

                for dpd in list_of_dpd:
                    if dpd.get('min') > dpd.get('max'):
                        raise forms.ValidationError('incorrect range on rank {}'.format(rank))

                if list_of_score:
                    for score in list_of_score:
                        if score.get('min') > score.get('max'):
                            raise forms.ValidationError('incorrect range on rank {}'.format(rank))

        return self.cleaned_data


class GrabFlowBlockerAdminForm(forms.ModelForm):
    class Meta:
        model = GrabFeatureSetting
        exclude = ['id']

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters')

            failed_crs = str(parameters.get('failed_crs'))

            for key in {'failed_crs'}:
                if key == 'failed_crs' and parameters.get(key) == 0:
                    continue

                if not parameters.get(key):
                    raise forms.ValidationError('Parameters should have {} key'.format(key))

            if not failed_crs.isdigit():
                raise forms.ValidationError('failed_crs should be an integer')

        return self.cleaned_data


class GrabFDCAutoApprovalSettingForm(forms.ModelForm):
    class Meta:
        model = GrabFeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters': '<b>Description:</b><br>'
            '1. retry_count          : max retry count <br>'
            '2. wait_time_for_retry  : delay between each retry in minutes<br>'
            '2. scheduler_run_time   : time for scheduler to be triggered<br>'
            '<br>'
            '<b>Rules to follow:</b><br>'
            '1. Please consult to engineering team before updating the parameters.<br>'
            '2. Always use "{" in the start and use "}" in the end of parameters.<br>'
            '3. "retry_count", "wait_time_for_retry" and "scheduler_run_time" is required inside of parameters<br>'
            '4. "scheduler_run_time" is 24 hour format, e.g if you input 9 then iw will scheduled at 9 AM<br>'
            '<br>'
            '<b>Example Input:</b><br>'
            '{ <br>'
            '  &emsp;"retry_count": 3, <br>'
            '  &emsp;"wait_time_for_retry": 60, <br>'
            '  &emsp;"scheduler_run_time": 9, <br>'
            '}',
        }

    def clean(self):
        parameters = self.cleaned_data.get('parameters')
        if not parameters:
            self.data['parameters'] = '{}'
            self.cleaned_data['parameters'] = {}
            raise forms.ValidationError('Parameters is required')
        else:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Invalid parameters')
            retry_count = str(parameters.get('retry_count'))
            wait_time_for_retry = str(parameters.get('wait_time_for_retry'))
            scheduler_run_time = str(parameters.get('scheduler_run_time'))
            for key in {'retry_count', 'wait_time_for_retry', 'scheduler_run_time'}:
                if parameters.get(key) == 0:
                    continue
                if not parameters.get(key):
                    raise forms.ValidationError('Parameters should have {} key'.format(key))
            if not retry_count.isdigit():
                raise forms.ValidationError('retry_count should be an integer')
            if not wait_time_for_retry.isdigit():
                raise forms.ValidationError('wait_time_for_retry should be an integer')
            if not scheduler_run_time.isdigit():
                raise forms.ValidationError('scheduler_run_time should be an integer')
            if int(scheduler_run_time) < 1 or int(scheduler_run_time) > 24:
                raise forms.ValidationError('scheduler_run_time should be in 24 hours format')
        return self.cleaned_data


admin.site.register(GrabFeatureSetting, GrabFeatureSettingAdmin)


class UserSegmentChunkSizeAdminForm(forms.ModelForm):
    class Meta(object):
        fields = '__all__'
        model = FeatureSetting

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if not parameters:
            if 'chunk_size' in self._errors:
                return cleaned_data
            else:
                raise forms.ValidationError('Parameters must be an integer value. E.g: 25000")}')

        if 'chunk_size' not in parameters:
            raise forms.ValidationError(
                'Parameters field must have \'chunk_size\' key.' 'E.g: {"chunk_size": 25000}'
            )

        chunk_size = parameters['chunk_size']
        if not isinstance(chunk_size, int):
            raise forms.ValidationError(
                'Parameters field dictionary \'chunk_size\' must '
                'be a number value.'
                'E.g: {"chunk_size": 25000}'
            )

        if chunk_size <= 0:
            raise forms.ValidationError('chunk_size must be greater than 0.')

        return cleaned_data


class UserSegmentChunkIntegrityCheckTtlAdminForm(forms.ModelForm):
    class Meta(object):
        fields = '__all__'
        model = FeatureSetting

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if not parameters:
            if 'parameters' in self._errors:
                return cleaned_data
            else:
                raise forms.ValidationError('Parameters must be an integer value. E.g: 1800")}')

        if 'TTL' not in parameters:
            raise forms.ValidationError(
                'Parameters field must have \'TTL\' key.' 'E.g: {"TTL": 1800}'
            )

        ttl = parameters['TTL']
        if not isinstance(ttl, int):
            raise forms.ValidationError(
                'Parameters field dictionary \'TTL\' must '
                'be a number value.'
                'E.g: {"TTL": 1800}'
            )

        if ttl <= 0:
            raise forms.ValidationError('TTL must be greater than 0.')

        return cleaned_data


class SmsCampaignFailedProcessCheckTtlAdminForm(forms.ModelForm):
    class Meta(object):
        fields = '__all__'
        model = FeatureSetting

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if not parameters:
            if 'parameters' in self._errors:
                return cleaned_data

        if 'TTL' not in parameters:
            raise forms.ValidationError(
                'Parameters field must have \'TTL\' key.' 'E.g: {"TTL": 1800}'
            )

        ttl = parameters['TTL']
        if not isinstance(ttl, int):
            raise forms.ValidationError(
                'Parameters field dictionary \'TTL\' must '
                'be a number value.'
                'E.g: {"TTL": 1800}'
            )

        if ttl <= 0:
            raise forms.ValidationError('TTL must be greater than 0.')
        return cleaned_data


class ThorTenorInterventionVerificationForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = ("__all__")

    def clean(self):
        cleaned_data = super(ThorTenorInterventionVerificationForm, self).clean()
        parameters = cleaned_data.get('parameters')
        if not parameters or \
                not ('delay_intervention' in parameters or 'tenor_option' in parameters):
            raise forms.ValidationError(
                'for thor_verification parameters can not be empty')
        delay_intervention = parameters.get('delay_intervention')
        if not isinstance(delay_intervention, int) or delay_intervention <= 0:
            raise forms.ValidationError("parameter 'delay_intervention' should be a \
                                         positive integer")
        tenor_options = parameters.get('tenor_option')
        for tenor_option in tenor_options:
            if not isinstance(tenor_option, int) or tenor_option <= 0:
                raise forms.ValidationError("parameter 'tenor_options' should be a \
                                             list of positive integers")
        return cleaned_data


class ThorTenorInterventionVerificationForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = ("__all__")

    def clean(self):
        cleaned_data = super(ThorTenorInterventionVerificationForm, self).clean()
        parameters = cleaned_data.get('parameters')
        if not parameters or \
                not ('delay_intervention' in parameters or 'tenor_option' in parameters):
            raise forms.ValidationError(
                'for thor_verification parameters can not be empty')
        delay_intervention = parameters.get('delay_intervention')
        if not isinstance(delay_intervention, int) or delay_intervention <= 0:
            raise forms.ValidationError("parameter 'delay_intervention' should be a \
                                         positive integer")
        tenor_options = parameters.get('tenor_option')
        for tenor_option in tenor_options:
            if not isinstance(tenor_option, int) or tenor_option <= 0:
                raise forms.ValidationError("parameter 'tenor_options' should be a \
                                             list of positive integers")
        # sort tenor_option
        parameters["tenor_option"] = sorted(tenor_options)

        return cleaned_data


class QrisMultiLenderSettingForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        parameters = cleaned_data.get('parameters')
        if not parameters or not (
            'lender_names_ordered_by_priority' in parameters
            or 'out_of_balance_threshold' in parameters
        ):
            raise forms.ValidationError('Parameters can not be empty')
        threshold = parameters.get('out_of_balance_threshold')
        if not isinstance(threshold, int) or threshold < 0:
            raise forms.ValidationError("out of balance threshold is not a valid value")

        lender_names = parameters.get('lender_names_ordered_by_priority', [])

        if not isinstance(lender_names, list):
            raise forms.ValidationError("Lenders' names should be list")

        if not lender_names:
            raise forms.ValidationError("Please set-up at least one lender")

        lender_count = (
            LenderCurrent.objects.filter(
                lender_name__in=lender_names,
            )
            .values('lender_name')
            .count()
        )

        if len(lender_names) != lender_count:
            raise forms.ValidationError(
                "Check if lenders are valid and unique. Please refer to lender table."
            )

        return cleaned_data


class FaqItemSerializer(serializers.Serializer):
    content = serializers.CharField(required=True)
    title = serializers.CharField(required=True)
    type = serializers.CharField(required=True)
    order = serializers.IntegerField(required=True)

    def validate_order(self, value):
        if value <= 0:
            raise serializers.ValidationError("Order must be a positive integer")
        return value


class RepaymentFaqSettingSerializer(serializers.ListSerializer):
    child = FaqItemSerializer()

    def validate(self, attrs):
        used_orders = set()
        for item in attrs:
            if item['order'] in used_orders:
                raise serializers.ValidationError(f"Duplicate order value found: {item['order']}")
            used_orders.add(item['order'])
        return attrs

    @staticmethod
    def format_errors(error_list):
        formatted_errors = []
        for idx, item_errors in enumerate(error_list):
            if isinstance(item_errors, dict) and item_errors:
                error_message = f"Item {idx + 1}: "
                field_errors = []
                for field, errors in item_errors.items():
                    if isinstance(errors, list):
                        field_errors.append(f"{field}: {', '.join(errors)}")
                    else:
                        field_errors.append(f"{field}: {errors}")
                error_message += "; ".join(field_errors)
                formatted_errors.append(error_message)
            elif isinstance(item_errors, str):
                formatted_errors.append(item_errors)
        return formatted_errors


class RepaymentFaqSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        fields = "__all__"

    serializer_class = RepaymentFaqSettingSerializer

    def clean_parameters(self):
        parameters = self.cleaned_data['parameters']
        serializer = self.serializer_class(data=parameters)
        if not serializer.is_valid():
            raise forms.ValidationError(self.serializer_class.format_errors(serializer.errors))
        return parameters


class QrisLandingPageConfigForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = "__all__"

    def clean(self):
        cleaned_data = super(QrisLandingPageConfigForm, self).clean()
        parameters = cleaned_data.get('parameters')
        if not parameters or not ('banner_image_link' in parameters or 'faq_link' in parameters):
            raise forms.ValidationError(
                'for banner_image_link/faq_link parameters can not be empty'
            )
        banner_image_link = parameters['banner_image_link']

        if not banner_image_link or not isinstance(banner_image_link, str):
            raise forms.ValidationError("banner url invalid format")

        url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        if not re.match(url_pattern, banner_image_link, re.IGNORECASE):
            raise forms.ValidationError("banner url invalid format")

        url_lower = banner_image_link.lower().split('?')[0]
        allowed_extensions = ('.png', '.jpg', '.jpeg')

        if not url_lower.endswith(allowed_extensions):
            raise forms.ValidationError("banner url invalid file extension")

        return cleaned_data


class PaymentMethodSwitchForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    form_data = forms.CharField(widget=forms.HiddenInput())
    schedule_switch = forms.CharField(widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super(PaymentMethodSwitchForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            params = instance.parameters
            data = {
                'switches': {
                    switch['bank']: switch['vendor'] for switch in params['payment_method']
                },
                'banks': ['PERMATA Bank', 'Bank BRI', 'Bank MANDIRI'],
                'vendors': ['DOKU', 'FASPAY'],
            }
            self.fields['form_data'].initial = json.dumps(data)
            self.fields['schedule_switch'].initial = json.dumps(params['schedule_switch'], indent=2)

    class Meta:
        model = FeatureSetting
        fields = ['is_active', 'form_data', 'schedule_switch']

    def clean(self):
        cleaned_data = super().clean()
        try:
            form_data = json.loads(cleaned_data.get('form_data', '{}'))
        except json.JSONDecodeError:
            raise forms.ValidationError("Invalid form data format")

        schedule_data = cleaned_data.get('schedule_switch')

        try:
            schedules = json.loads(schedule_data)
        except json.JSONDecodeError:
            raise forms.ValidationError("Invalid JSON format for schedule switch")

        if not isinstance(schedules, list):
            raise forms.ValidationError("Schedule data must be a list of schedules")

        required_fields = {'bank', 'vendor', 'start_date', 'end_date'}
        for schedule in schedules:
            if not all(field in schedule for field in required_fields):
                raise forms.ValidationError(
                    f"Each schedule must contain: {', '.join(required_fields)}"
                )

            if any(schedule.get(field) is None for field in required_fields):
                raise forms.ValidationError("All schedule fields must have non-null values")

            try:
                from datetime import datetime

                datetime.strptime(schedule['start_date'], '%Y-%m-%d %H:%M:%S')
                datetime.strptime(schedule['end_date'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise forms.ValidationError("Dates must be in format: YYYY-MM-DD HH:MM:SS")
        return cleaned_data
