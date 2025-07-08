import traceback

from django.utils import timezone
from django.db import transaction
from django.conf import settings
from django.db.utils import IntegrityError
from dateutil.relativedelta import relativedelta
from datetime import timedelta

from juloserver.application_form.constants import ExpireDayForm
from juloserver.julo.models import (
    Application,
    ApplicationWorkflowSwitchHistory,
    Customer,
    Mantri,
    Bank,
    Image,
    ApplicationUpgrade,
    FeatureSetting,
    Workflow,
    SmsHistory,
    ApplicationFieldChange,
    CustomerFieldChange,
    ExperimentSetting,
    AddressGeolocation,
    FDCInquiry,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
    ActiveLivenessVendorResult,
    PassiveLivenessVendorResult,
)

from juloserver.julo.constants import FeatureNameConst
from juloserver.fraud_security.constants import DeviceConst
from juloserver.julo.utils import get_oss_public_url

from juloserver.application_form.services.product_picker_service import define_workflow_application
from juloserver.apiv2.views import process_application_status_change
from juloserver.application_flow.services import store_application_to_experiment_table
from juloserver.application_form.constants import ApplicationUpgradeConst, EmergencyContactConst
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julolog.julolog import JuloLog
from juloserver.apiv1.serializers import ApplicationSerializer as ApplicationSerializerV1
from juloserver.application_form.exceptions import (
    JuloApplicationUpgrade,
    JuloEmergencyContactException,
)
from juloserver.application_flow.tasks import suspicious_ip_app_fraud_check
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.application_form.services.product_picker_service import generate_address_location
from juloserver.pin.services import (
    set_is_rooted_device,
    get_device_model_name,
    validate_device,
)

from juloserver.julo.clients.idfy import (
    IDfyApiClient,
    IDfyTimeout,
    IDfyServerError,
    IDfyProfileCreationError,
    IDfyApplicationNotAllowed,
    IDFyGeneralMessageError,
)

from juloserver.application_form.models.idfy_models import IdfyVideoCall
from juloserver.application_form.constants import (
    LabelFieldsIDFyConst,
    ApplicationDirectionConst,
    SwitchProductWorkflowConst,
)
from juloserver.julo.constants import (
    WorkflowConst,
    ExperimentConst,
)
from juloserver.application_form.models.revive_mtl_request import ReviveMtlRequest
from juloserver.application_form.services.idfy_service import (
    is_office_hours_agent_for_idfy,
    is_completed_vc,
)
from juloserver.application_form.models.agent_assisted_submission import AgentAssistedWebToken
from juloserver.julo.constants import OnboardingIdConst
from juloserver.application_form.tasks.application_task import (
    trigger_sms_for_emergency_contact_consent,
)
from juloserver.application_form.utils import (
    get_application_for_consent_form,
    update_emergency_contact_consent,
)
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_consent_received,
)

from juloserver.application_form.models.ktp_ocr import OcrKtpResult
from juloserver.application_flow.services import still_in_experiment
from juloserver.application_form.constants import OfflineBoothConst
from juloserver.application_flow.tasks import application_tag_tracking_task
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.registration_flow.services.v3 import run_fdc_inquiry_for_registration
from juloserver.application_form.utils import regenerate_web_token_data
from juloserver.application_form.models.general_models import ApplicationPhoneRecord
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.julo.exceptions import JuloException

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def upgrade_app_to_j1(customer, validated_data):
    if have_application_is_active(customer):
        error_message = 'Cannot create other application'
        logger.warning({'message': error_message, 'customer': customer.id})
        raise JuloApplicationUpgrade(error_message)

    # get application
    application_approved = Application.objects.filter(
        customer=customer, application_status=ApplicationStatusCodes.LOC_APPROVED
    ).last()

    if not application_approved:
        error_message = 'Application not found'
        logger.warning({'message': error_message, 'customer': customer.id})
        raise JuloApplicationUpgrade(error_message)

    if not application_approved.is_julo_starter():
        error_message = 'Application not allowed'
        logger.warning(
            {
                'message': error_message,
                'customer': customer.id,
                'application': application_approved.id,
            }
        )
        raise JuloApplicationUpgrade(error_message)
    try:
        customer = Customer.objects.filter(pk=customer.pk).last()
        # build data
        data_to_save, device = construct_copy_data(application_approved, customer, validated_data)
        with transaction.atomic():
            # create data with new application
            application = Application.objects.create(**data_to_save)

            # to do duplicate data image
            duplicate_image_by_application(application_approved, application)

            # active & passive liveness
            duplicate_active_liveness_detection(application_approved, application, customer)
            duplicate_passive_liveness_detection(application_approved, application, customer)

            # link_to_partner_if_exists(application)
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_CREATED,
                change_reason='customer_triggered',
            )

            # move julo starter application status to 191
            process_application_status_change(
                application_approved.id,
                ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
                change_reason='turbo_upgrade',
            )

            # record the application as upgraded to J1
            process_app_extension_record(prev_app=application_approved, new_app=application)

        create_application_checklist_async.delay(application.id)

        # refresh application to get last status
        application.refresh_from_db()
        detokenize_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': application.customer.customer_xid,
                    'object': application,
                }
            ],
            force_get_local_data=True,
        )
        application = detokenize_applications[0]
        store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

        # some function to support detect fraud
        apply_additional_fraud_check(application, customer, validated_data)

        # generate address location related with binary checking
        latitude, longitude = validated_data.get('latitude'), validated_data.get('longitude')
        if latitude is not None and longitude is not None:
            generate_address_location(application, latitude, longitude)

        # follow behavior response when x100
        response = {
            'applications': [ApplicationSerializerV1(application).data],
            'device_id': device.id,
        }

        return response
    except Exception as error:
        error_message = str(error)
        raise JuloApplicationUpgrade(error_message)


def apply_additional_fraud_check(application, customer, validated_data):
    # check suspicious IP
    suspicious_ip_app_fraud_check.delay(
        application.id, validated_data.get('ip_address'), validated_data.get('is_suspicious_ip')
    )

    device = get_data_device(customer, validated_data)
    is_rooted_device = validated_data.get('is_rooted_device', None)
    if is_rooted_device is not None:
        set_is_rooted_device(application, is_rooted_device, device)


def get_data_device(customer, validated_data):
    device_model_name = get_device_model_name(
        validated_data.get('manufacturer'), validated_data.get('model')
    )
    device, _ = validate_device(
        gcm_reg_id=validated_data['gcm_reg_id'],
        customer=customer,
        imei=validated_data.get('imei'),
        android_id=validated_data['android_id'],
        device_model_name=device_model_name,
        julo_device_id=validated_data.get(DeviceConst.JULO_DEVICE_ID),
    )
    return device


def construct_copy_data(prev_app, customer, data):
    device = None
    device_id = None
    onboarding_id = data.get('onboarding_id')

    if not data.get('web_version'):
        device = get_data_device(customer, data)
        device_id = device.id if device else None
        logger.info(
            {
                'message': 'Getting data device id',
                'device_id': device_id,
                'prev_application': prev_app.id,
            }
        )

    # determine app number (marker purpose)
    application_number = calculate_application_number(prev_app)
    workflow, product_line = define_workflow_application(onboarding_id)

    # handle condition to get device data
    if not device_id:
        device_id = prev_app.device_id
        logger.info(
            {
                'message': 'Getting data device id from previous application',
                'device_id': device_id,
                'prev_application': prev_app.id,
            }
        )

    overwrite = {
        'application_number': application_number,
        'app_version': data.get('app_version'),
        'web_version': data.get('web_version'),
        'device_id': device_id,
        'application_xid': None,
        'customer_id': prev_app.customer_id,
        'onboarding_id': onboarding_id,
        'workflow_id': workflow.id,
        'product_line_id': product_line.product_line_code,
        'customer_mother_maiden_name': customer.mother_maiden_name,
    }

    # get values data
    build_data = prepare_build_data(prev_app.id)

    for field in build_data:
        build_data[field] = getattr(prev_app, field)

    # update selected data
    build_data.update(**overwrite)

    bank_name = build_data['bank_name']
    if not Bank.objects.regular_bank().filter(bank_name=bank_name).last():
        build_data['bank_name'] = None
        build_data['bank_account_number'] = None

    # Like reapply case to sync data mantri by App
    constructed_data = sync_data_mantri_by_app(prev_app, build_data)

    return constructed_data, device


def prepare_build_data(application_id):
    remove_fields = ('id', 'cdate', 'udate', 'application_status_id')
    clean_data = Application.objects.filter(pk=application_id).values().last()
    application = Application.objects.filter(pk=application_id).last()
    detokenize_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [
            {
                'customer_xid': application.customer.customer_xid,
                'object': application,
            }
        ],
        force_get_local_data=True,
    )
    application = detokenize_applications[0]
    for field in Application.PII_FIELDS:
        clean_data[field] = getattr(application, field)

    for field in remove_fields:
        clean_data.pop(field)

    return clean_data


def sync_data_mantri_by_app(prev_app, constructed_data):
    if prev_app.mantri_id:
        referral_code = prev_app.referral_code
        constructed_data['referral_code'] = referral_code

        # check duration
        today = timezone.localtime(timezone.now()).date()
        date_apply = prev_app.cdate.date()
        day_range = (today - date_apply).days
        if day_range <= 30:
            # Set mantri id if referral code is a mantri id
            if referral_code:
                referral_code = referral_code.replace(' ', '')
                mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
                constructed_data['mantri_id'] = mantri_obj.id if mantri_obj else None

    return constructed_data


def calculate_application_number(last_application):
    last_application_number = last_application.application_number
    if not last_application_number:
        last_application_number = 1
    application_number = last_application_number + 1

    return application_number


def duplicate_image_by_application(prev_app: Application, new_app: Application):
    """
    To duplicate data image:
    - KTP self
    - Selfie
    - Crop selfie
    - And Active / Passive liveness
    with case pre-fill application when upgrade JTurbo to J1
    """

    images = Image.objects.filter(image_source=prev_app.id).order_by('cdate')
    for image in images:
        Image.objects.create(
            image_source=new_app.id,
            image_type=image.image_type,
            url=image.url,
            image_status=image.image_status,
            thumbnail_url=image.thumbnail_url,
            service=image.service,
        )
        logger.info(
            {
                'message': 'duplicating image',
                'to_application': new_app.id,
                'from_application': prev_app.id,
                'image_type': image.image_type,
            }
        )


def duplicate_active_liveness_detection(prev_app: Application, new_app: Application, customer):
    data = get_active_liveness_detection(prev_app, customer)
    if not data:
        logger.warning(
            {
                'message': 'active liveness is not found',
                'application': prev_app.id,
                'customer': customer.id,
            }
        )
        return

    with transaction.atomic():
        for row in data:
            row['application_id'] = new_app.id
            row['customer_id'] = customer.id

            vendor = None
            if row['liveness_vendor_result_id']:
                vendor_result = (
                    ActiveLivenessVendorResult.objects.filter(pk=row['liveness_vendor_result_id'])
                    .order_by('cdate')
                    .values()
                )
                clean_vendor_result = remove_some_fields(vendor_result)

                for row_vendor in clean_vendor_result:
                    vendor = ActiveLivenessVendorResult.objects.create(**row_vendor)

            row['liveness_vendor_result_id'] = vendor.id if vendor else None
            ActiveLivenessDetection.objects.create(**row)


def get_active_liveness_detection(prev_app: Application, customer):
    active_datas = (
        ActiveLivenessDetection.objects.filter(application=prev_app, customer=customer)
        .order_by('cdate')
        .values()
    )

    clean_data = remove_some_fields(active_datas)

    return clean_data


def duplicate_passive_liveness_detection(prev_app: Application, new_app: Application, customer):
    data = get_passive_liveness_detection(prev_app, customer)
    if not data:
        logger.warning(
            {
                'message': 'passive liveness is not found',
                'application': prev_app.id,
                'customer': customer.id,
            }
        )
        return

    with transaction.atomic():
        for row in data:
            row['application_id'] = new_app.id
            row['customer_id'] = customer.id

            if row['image_id']:
                row['image_id'] = get_data_image(new_app.id, 'selfie')

            vendor = None
            if row['liveness_vendor_result_id']:
                vendor_result = (
                    PassiveLivenessVendorResult.objects.filter(pk=row['liveness_vendor_result_id'])
                    .order_by('cdate')
                    .values()
                )
                clean_vendor_result = remove_some_fields(vendor_result)

                for row_vendor in clean_vendor_result:
                    vendor = PassiveLivenessVendorResult.objects.create(**row_vendor)

            row['liveness_vendor_result_id'] = vendor.id if vendor else None
            PassiveLivenessDetection.objects.create(**row)


def get_data_image(application_id, image_type):
    image = Image.objects.filter(image_source=application_id, image_type=image_type).last()

    return image.id if image else None


def get_passive_liveness_detection(prev_app: Application, customer):
    passive_datas = (
        PassiveLivenessDetection.objects.filter(application=prev_app, customer=customer)
        .order_by('cdate')
        .values()
    )
    clean_data = remove_some_fields(passive_datas)

    return clean_data


def remove_some_fields(fields):
    for field in fields:
        field.pop('cdate')
        field.pop('udate')
        field.pop('id')

    return fields


def have_application_is_active(customer):
    return Application.objects.filter(
        customer=customer, application_status=ApplicationStatusCodes.FORM_CREATED
    ).exists()


def process_app_extension_record(prev_app: Application, new_app: Application):
    """
    To marker application have upgraded from JTurbo to J1
    """

    app_existing = ApplicationUpgrade.objects.filter(
        application_id=new_app.id,
        application_id_first_approval=prev_app.id,
    ).last()
    if not app_existing:
        logger.info(
            {
                'message': 'upgrading application from JTurbo to J1',
                'application': new_app.id,
                'application_original': prev_app.id,
            }
        )
        ApplicationUpgrade.objects.create(
            application_id=new_app.id,
            application_id_first_approval=prev_app.id,
            is_upgrade=ApplicationUpgradeConst.MARK_UPGRADED,
        )
    else:
        app_existing.update_safely(is_upgrade=ApplicationUpgradeConst.MARK_UPGRADED)

    return True


def stored_application_to_upgrade_table(application, previous_upgrade=None):
    """
    To record when create application in table
    ops.application_upgrade
    """

    if not application:
        logger.error(
            {'message': 'application not found', 'process': 'save_data_init_to_upgrade_table'}
        )
        return

    application_id = application.id
    logger.info(
        {
            'message': 'creating init application extension',
            'application': application_id,
            'is_upgrade': ApplicationUpgradeConst.NOT_YET_UPGRADED,
        }
    )

    application_id_first_approval = application_id
    is_upgrade = ApplicationUpgradeConst.NOT_YET_UPGRADED
    if previous_upgrade:
        application_id_first_approval = previous_upgrade.application_id_first_approval
        is_upgrade = ApplicationUpgradeConst.MARK_UPGRADED

    logger.info(
        {
            'message': 'Stored application to upgrade table',
            'application': application_id,
            'application_id_first_approval': application_id_first_approval,
            'is_upgrade': is_upgrade,
        }
    )

    application_upgrade = ApplicationUpgrade.objects.get_or_create(
        application_id=application_id,
        application_id_first_approval=application_id_first_approval,
        is_upgrade=is_upgrade,
    )

    return application_upgrade


def check_phone_number_is_used(application_id, phone_number):
    if not phone_number:
        return True

    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return False

    detokenized_application = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'customer_xid': application.customer.customer_xid, 'object': application}],
        force_get_local_data=True,
    )
    application = detokenized_application[0]

    if phone_number in [
        application.mobile_phone_1,
        application.spouse_mobile_phone,
        application.kin_mobile_phone,
        application.close_kin_mobile_phone,
    ]:
        return False

    return True


def create_idfy_profile(customer):
    workflow = Workflow.objects.get_or_none(name=WorkflowConst.JULO_ONE)
    application = (
        customer.application_set.regular_not_deletes()
        .filter(workflow=workflow, application_status_id__lte=100)
        .last()
    )
    if not application:
        logger.warn(
            {
                'action': 'create_idfy_profile',
                'message': 'Application not allowed for video call',
                'customer': customer.id if customer else None,
            }
        )
        raise IDfyApplicationNotAllowed('Application not available for video call')

    features_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IDFY_CONFIG_ID, is_active=True
    ).last()
    if not features_setting:
        logger.warn(
            {
                'action': 'create_idfy_profile',
                'message': 'Config ID not available',
                'customer': customer.id if customer else None,
            }
        )
        raise IDfyProfileCreationError('IDfy Feature setting not active')

    idfy_client = IDfyApiClient(
        settings.IDFY_API_KEY, features_setting.parameters['config_id'], settings.IDFY_BASE_URL
    )

    # check if video call have completed status
    is_completed = is_completed_vc(application=application)
    if is_completed:
        logger.info(
            {
                'message': 'Video call completed but hit endpoint Create Profile',
                'application': application.id,
            }
        )
        return None, None

    # check for office hour
    is_office_hours, message = is_office_hours_agent_for_idfy(is_completed)
    idfy_url = IdfyVideoCall.objects.filter(
        reference_id=application.application_xid,
        application_id=application.id,
        status__in=(
            LabelFieldsIDFyConst.KEY_IN_PROGRESS,
            LabelFieldsIDFyConst.KEY_CANCELED,
        ),
        profile_url__isnull=False,
    ).last()

    if idfy_url:
        # return profile url if exists and check is office hour or not
        if is_office_hours:
            if idfy_url.status == LabelFieldsIDFyConst.KEY_CANCELED:
                # update status from canceled to in_progress and return it 200
                logger.info(
                    {
                        'message': 'update status from canceled to in_progress',
                        'is_office_hours': is_office_hours,
                        'application': application.id,
                    }
                )
                idfy_url.update_safely(status=LabelFieldsIDFyConst.KEY_IN_PROGRESS)

            logger.info(
                {
                    'message': 'return profile url in office hours',
                    'application': application.id,
                    'status_idfy': idfy_url.status,
                    'is_office_hours': is_office_hours,
                }
            )

            return idfy_url.profile_url, idfy_url.profile_id

        logger.info(
            {
                'message': 'Outside office hour in return same profile',
                'application': application.id,
                'is_office_hours': is_office_hours,
            }
        )
        raise IDFyGeneralMessageError(message)

    try:
        response = idfy_client.create_profile(application.application_xid)
    except (IDfyServerError, IDfyTimeout) as e:
        logger.warn(
            {
                'action': 'create_idfy_profile',
                'message': 'IDfyServerError/IDfyTimeout - {}'.format(str(e)),
                'customer': customer.id if customer else None,
                'application_id': application.id,
                'idfy reference_id': application.application_xid,
            }
        )
        raise IDfyTimeout(
            'Error creating profile for application_xid {}: {}'.format(
                application.application_xid, e
            )
        )
    except IDfyProfileCreationError as e:
        logger.warn(
            {
                'action': 'create_idfy_profile',
                'message': 'IDfyProfileCreationError - {}'.format(str(e)),
                'customer': customer.id if customer else None,
                'application_id': application.id,
                'idfy reference_id': application.application_xid,
            }
        )
        raise IDfyProfileCreationError(
            'Error creating profile for application_xid {}: {}'.format(
                application.application_xid, e
            )
        )

    video_call_url = response.get('capture_link')
    profile_id = response.get('profile_id')

    if not IdfyVideoCall.objects.filter(reference_id=application.application_xid).exists():
        IdfyVideoCall.objects.create(
            reference_id=application.application_xid,
            application_id=application.id,
            status=LabelFieldsIDFyConst.KEY_IN_PROGRESS,
            profile_url=video_call_url,
            profile_id=profile_id,
        )

    # check is office hour or not
    if not is_office_hours:
        logger.info(
            {
                'message': 'Outside office hour in creating profile',
                'application': application.id,
                'is_office_hours': is_office_hours,
            }
        )
        raise IDFyGeneralMessageError(message)

    return video_call_url, profile_id


def determine_active_application(customer: Customer, temp_application):
    """
    This function to determine main / active application below x105
    """

    applications = customer.application_set.regular_not_deletes().filter(
        application_status_id=ApplicationStatusCodes.FORM_CREATED,
        workflow__name__in=(WorkflowConst.JULO_ONE, WorkflowConst.JULO_STARTER),
    )

    # handle customers only have one application in x100
    if applications.count() < 2:
        logger.info(
            {
                'message': 'condition one application',
                'customer': customer.id if customer else None,
                'application': temp_application if temp_application else None,
            }
        )
        return temp_application

    # handle if customers still have double x100
    application = applications.order_by('-udate').first()
    logger.info(
        {
            'message': 'condition more than one application',
            'customer': customer.id if customer else None,
            'application': application.id if application else None,
        }
    )

    return application


def get_main_application_after_submit_form(customer):
    """
    This function to get application after customer submit the form
    without generate new application ID (App ID Generation Flow)
    """

    # check application have x100
    applications = customer.application_set.regular_not_deletes()
    application = applications.filter(
        application_status_id=ApplicationStatusCodes.FORM_CREATED,
    ).order_by('-id')[:1]
    if application:
        return application

    application = (
        customer.application_set.regular_not_deletes()
        .filter(
            application_status_id__gte=ApplicationStatusCodes.FORM_PARTIAL,
            workflow__name__in=(
                WorkflowConst.JULO_ONE,
                WorkflowConst.JULO_STARTER,
                WorkflowConst.JULO_ONE_IOS,
            ),
        )
        .order_by('-cdate')[:1]
    )
    return application


def get_destination_page(customer):
    if not customer:
        logger.error(
            {
                'message': 'Invalid request not found the customer data',
            }
        )
        return

    # handle if user not have application
    applications = customer.application_set.regular_not_deletes()
    if not applications.exists():
        return ApplicationDirectionConst.PRODUCT_PICKER

    # handle some condition by application status code
    count_applications = applications.filter(
        application_status_id__in=(
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.OFFER_REGULAR,
        ),
        workflow__name__in=(WorkflowConst.JULO_ONE, WorkflowConst.JULO_STARTER),
    ).count()

    if count_applications == 1:
        return ApplicationDirectionConst.PRODUCT_PICKER

    return ApplicationDirectionConst.HOME_SCREEN


def get_bottomsheet(feature_setting):
    response = feature_setting.parameters
    for product_bottomsheet in response:
        if not product_bottomsheet:
            continue

        for message in product_bottomsheet.get('message'):
            message['message_icon_url'] = get_oss_public_url(
                settings.OSS_PUBLIC_ASSETS_BUCKET, message['message_icon_url']
            )

    return response


def is_already_submit_form(application_id):
    if not application_id:
        logger.info(
            {
                'message': 'Invalid case empty application_id',
                'application': application_id,
            }
        )
        return False

    application = Application.objects.filter(
        pk=application_id,
        application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
    ).last()

    if application:
        logger.info(
            {
                'message': 'Application already submit the form',
                'application': application_id,
            }
        )
        return True

    logger.info(
        {
            'message': 'Application still can submit the form',
            'application': application_id,
        }
    )
    return False


def proceed_stored_data_mtl_application(data, julo_mtl_form=None):
    process_name = 'mtl_application_form'
    logger.info(
        {
            'message': 'execute function',
            'process': process_name,
        }
    )

    application_xid = julo_mtl_form
    email = data.get('email', None)

    # check privacy policy is agreed
    is_privacy_agreed = data.get('is_privacy_agreed') if data.get('is_privacy_agreed') else False
    if not is_privacy_agreed:
        return False, 'Anda harus menyetujui kebijakan privasi untuk mengajukan formulir'

    # check already existed or not
    is_exists = ReviveMtlRequest.objects.filter(email__iexact=email).exists()
    if is_exists:
        return False, 'Anda sudah pernah mengirim tanggapan Anda'

    data.update({'is_privacy_agreed': is_privacy_agreed})

    if (
        not data.get('bank_code')
        or not data.get('bank_account_number')
        or not data.get('name_in_bank')
    ):
        return False, 'Anda harus mengisi data rekening Anda'

    # Check with email as default for fetching data in table `application`
    application = Application.objects.filter(email__iexact=email).last()

    # If have application_xid parameter from FE will fetch with application_xid
    if application_xid:
        application = Application.objects.filter(application_xid=application_xid).last()
        logger.info(
            {
                'message': 'fetch application by application_xid',
                'application': application.id,
                'email': email,
                'application_xid': application_xid,
            }
        )

    bank = Bank.objects.filter(bank_code=data.get('bank_code')).last()
    if not bank:
        return False, 'Bank dengan kode tersebut tidak ditemukan'

    data.update(
        {
            'application_id': application.id if application else None,
            'bank_name': bank.bank_name,
        }
    )

    # pop bank_code, it is only used for querying bank
    if data['bank_code']:
        data.pop('bank_code')

    ReviveMtlRequest.objects.create(**data)
    logger.info(
        {
            'message': 'success stored data mtl application',
            'process_name': process_name,
            'data': str(data),
        }
    )

    return True, None


def switch_workflow_product_by_onboarding(application, new_onboarding_id):
    """
    To switch product between J1 or JTurbo
    """

    if not application or not new_onboarding_id:
        logger.info(
            {
                'message': 'invalid case application or new_onboarding_id empty',
                'application': application.id if application else None,
                'new_onboarding_id': new_onboarding_id,
            }
        )
        return False

    if application.onboarding_id == new_onboarding_id:
        logger.info(
            {
                'message': 'invalid case update with same onboarding_id',
                'application': application.id,
                'new_onboarding_id': new_onboarding_id,
            }
        )
        return False

    if (
        application.application_number
        and application.application_number > 1
        and new_onboarding_id != OnboardingIdConst.JULO_STARTER_ID
        and new_onboarding_id == OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
    ):
        denied_application = (
            Application.objects.filter(
                customer_id=application.customer_id,
                application_status_id=ApplicationStatusCodes.APPLICATION_DENIED,
            )
            .exclude(id=application.id)
            .last()
        )

        if denied_application and denied_application.onboarding_id != new_onboarding_id:
            new_onboarding_id = denied_application.onboarding_id

    old_workflow = application.workflow
    new_workflow, new_product_line = define_workflow_application(new_onboarding_id)

    with transaction.atomic():
        # do update application data
        application.update_safely(
            workflow=new_workflow, product_line=new_product_line, onboarding_id=new_onboarding_id
        )

        # record for the change
        ApplicationWorkflowSwitchHistory.objects.create(
            application_id=application.id,
            workflow_old=old_workflow.name,
            workflow_new=new_workflow.name,
            change_reason=SwitchProductWorkflowConst.CHANGE_REASON,
        )

    logger.info(
        {
            'message': 'change product by onboarding',
            'old_onboarding_id': application.onboarding_id,
            'new_onboarding_id': new_onboarding_id,
        }
    )

    return True


def determine_page_for_continue_or_video(customer):
    destination_page = ApplicationDirectionConst.HOME_SCREEN
    applications = customer.application_set.regular_not_deletes()
    if not applications.exists():
        return destination_page

    if applications.last().status == ApplicationStatusCodes.FORM_CREATED:
        destination_page = ApplicationDirectionConst.PRODUCT_PICKER

        # handle some condition by application status code
        is_has_offer_regular_status = applications.filter(
            application_status_id=ApplicationStatusCodes.OFFER_REGULAR,
        ).exists()
        if is_has_offer_regular_status:
            destination_page = ApplicationDirectionConst.FORM_SCREEN

    return destination_page


def do_check_and_copy_data_approved(target_application_id, is_upgrade):
    """
    Target application for use this function when submit form upgrade and have expired flow (x106)
    Copy some data if customer still in_progress upgrade JTurbo to J1
    """
    application = Application.objects.filter(pk=target_application_id).last()
    if not application:
        return False

    if str(is_upgrade).lower() != 'true':
        logger.info(
            {
                'message': 'Skip process application is not upgrade flow',
                'application': target_application_id,
            }
        )
        return False

    # check image is exists or not
    has_image = Image.objects.filter(image_source=application.id).exists()
    if has_image:
        logger.info(
            {'message': 'Skip process application have image', 'application': application.id}
        )
        return False

    if application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
        logger.info(
            {
                'message': 'Application status is not allowed',
                'application_status_code': application.application_status_id,
                'application': application.id,
            }
        )
        return False

    # Get data application approved in x191
    customer = application.customer
    application_approved = Application.objects.filter(
        customer=customer,
        application_status=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
    ).last()

    if not application_approved or not application.is_julo_one():
        logger.info(
            {
                'message': 'Not have status x192 or application is not J1',
                'application': application.id,
                'application_approved': application_approved.id,
            }
        )
        return False

    logger.info(
        {
            'message': 'Duplicate image by application when submit form',
            'application': application.id,
            'application_approved': application_approved.id,
        }
    )
    # To do duplicate data image
    duplicate_image_by_application(application_approved, application)

    # Active & passive liveness
    if not ActiveLivenessDetection.objects.filter(application_id=application.id).exists():
        logger.info(
            {
                'message': 'Duplicate Active liveness by application when submit form',
                'application': application.id,
                'application_approved': application_approved.id,
            }
        )
        duplicate_active_liveness_detection(application_approved, application, customer)

    if not PassiveLivenessDetection.objects.filter(application_id=application.id).exists():
        logger.info(
            {
                'message': 'Duplicate Passive liveness by application when submit form',
                'application': application.id,
                'application_approved': application_approved.id,
            }
        )
        duplicate_passive_liveness_detection(application_approved, application, customer)

    return True


def is_have_approved_application(customer):
    if not customer:
        return False

    is_exist = Application.objects.filter(
        customer=customer, application_status=ApplicationStatusCodes.LOC_APPROVED
    ).exists()

    logger.info(
        {
            'message': 'Already have application approved',
            'customer': customer.id,
        }
    )

    return is_exist


def check_is_emergency_contact_filled(application: Application) -> bool:
    if not application.kin_mobile_phone:
        return False

    return True


def proceed_save_emergency_contacts(customer, validated_data):
    application = (
        customer.application_set.regular_not_deletes()
        .filter(
            customer_id=customer.id,
            onboarding_id=9,
            application_status_id__lte=190,
        )
        .last()
    )

    if not application:
        logger.info(
            {
                'message': 'Onboarding id mismatch for split emergency contact update',
                'customer_id': customer.id,
            }
        )
        return False, EmergencyContactConst.MESSAGE_APPLICATION_NOT_FOUND, validated_data

    detokenize_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [
            {
                'customer_xid': application.customer.customer_xid,
                'object': application,
            }
        ],
        force_get_local_data=True,
    )
    application = detokenize_applications[0]

    # check if grace period already passed
    if application.is_kin_approved == EmergencyContactConst.CONSENT_IGNORED:
        return False, EmergencyContactConst.MESSAGE_GRACE_PERIOD_PASSED, validated_data

    # check if emergency contact already given consent
    if application.is_kin_approved == EmergencyContactConst.CONSENT_ACCEPTED:
        return False, EmergencyContactConst.MESSAGE_KIN_ALREADY_APPROVED, validated_data

    # check if kin_mobile_phone already used
    if application.kin_mobile_phone == validated_data.get('kin_mobile_phone'):
        return False, EmergencyContactConst.MESSAGE_KIN_MOBILE_PHONE_USED, validated_data

    if SmsHistory.objects.filter(
        application_id=application.id,
        to_mobile_phone=format_e164_indo_phone_number(validated_data['kin_mobile_phone']),
        template_code=EmergencyContactConst.SMS_TEMPLATE_NAME,
    ).exists():
        return False, EmergencyContactConst.MESSAGE_KIN_MOBILE_PHONE_USED, validated_data

    phone_number_messages = {
        'close_kin_mobile_phone': 'Nomor orang tua tidak boleh menggunakan nomor HP anda sendiri',
        'spouse_mobile_phone': 'Nomor pasangan tidak boleh menggunakan nomor HP anda sendiri',
        'kin_mobile_phone': 'Nomor kontak darurat tidak boleh menggunakan nomor HP anda sendiri',
    }

    for key in phone_number_messages:
        if validated_data.get(key) and validated_data.get(key) in [
            application.mobile_phone_1,
            application.mobile_phone_2,
        ]:
            return False, phone_number_messages[key], validated_data

    # save old values to application_field_change
    application_field_changes = []
    for key, value in list(validated_data.items()):
        old_value = getattr(application, key, None)

        if old_value and value != old_value:
            application_field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name=key,
                    old_value=getattr(application, key),
                    new_value=value,
                )
            )

    validated_data['is_kin_approved'] = EmergencyContactConst.SMS_SENT
    with transaction.atomic():
        # save application field changes
        ApplicationFieldChange.objects.bulk_create(application_field_changes)

        # update application
        application.update_safely(**validated_data, refresh=True)

    logger.info(
        {
            'message': 'Emergency contact updated',
            'application': application.id,
            'kin_relationship': application.kin_relationship,
        }
    )

    if check_is_emergency_contact_filled(application):
        if application.application_status_id == ApplicationStatusCodes.MISSING_EMERGENCY_CONTACT:
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.LOC_APPROVED,
                change_reason='customer_triggered',
            )

        trigger_sms_for_emergency_contact_consent.delay(application.id)

    return True, None, validated_data


def retrieve_application_consent_info(code: str):
    application = get_application_for_consent_form(consent_code=code)
    if not application:
        return False, EmergencyContactConst.MESSAGE_APPLICATION_NOT_FOUND

    detokenize_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [
            {
                'customer_xid': application.customer.customer_xid,
                'object': application,
            }
        ],
        force_get_local_data=True,
    )
    application = detokenize_applications[0]

    sms_history = SmsHistory.objects.filter(
        application_id=application.id, template_code=EmergencyContactConst.SMS_TEMPLATE_NAME
    ).last()

    if not sms_history:
        return False, EmergencyContactConst.MESSAGE_KIN_CONSENT_CODE_NOT_FOUND

    try:
        is_sms_expired = timezone.now() > sms_history.cdate + timedelta(days=1)
    except Exception as error:
        logger.info(
            {
                'message': 'Failure to compare the sms dates',
                'action': 'retrieve_application_consent_info',
                'error': str(error),
            }
        )
        raise JuloEmergencyContactException(str(error))

    if (
        is_sms_expired
        or application.is_kin_approved in EmergencyContactConst.CONSENT_RESPONDED_VALUE
    ):
        return False, EmergencyContactConst.MESSAGE_KIN_CONSENT_CODE_EXPIRED

    response = {
        'application_xid': application.application_xid,
        'fullname': application.fullname,
        'phone_number': application.mobile_phone_1,
        'kin_relationship': application.kin_relationship,
        'kin_name': application.kin_name,
    }
    return True, response


def record_emergency_contact_consent(application_xid: str, consent_response):
    application = get_application_for_consent_form(application_xid=application_xid)
    if not application:
        return False, EmergencyContactConst.MESSAGE_KIN_CONSENT_CODE_NOT_FOUND

    sms_history = SmsHistory.objects.filter(
        application_id=application.id, template_code=EmergencyContactConst.SMS_TEMPLATE_NAME
    ).last()

    if not sms_history:
        return False, EmergencyContactConst.MESSAGE_KIN_CONSENT_CODE_EXPIRED

    try:
        is_sms_expired = timezone.now() > sms_history.cdate + timedelta(days=1)
    except Exception as error:
        logger.info(
            {
                'message': 'Failure to compare the sms dates',
                'action': 'retrieve_application_consent_info',
                'error': str(error),
            }
        )
        raise JuloEmergencyContactException(str(error))

    if (
        is_sms_expired
        or application.is_kin_approved in EmergencyContactConst.CONSENT_RESPONDED_VALUE
    ):
        return False, EmergencyContactConst.MESSAGE_KIN_CONSENT_CODE_EXPIRED

    update_emergency_contact_consent(application, consent_response)

    # start moengage trigger
    send_user_attributes_to_moengage_for_consent_received.delay(
        application.id,
        consent_value=consent_response,
    )
    return True, None


def retrieve_ktp_ocr_result(customer: Customer, application_id):
    ocr_result = None
    is_success = False
    message = None

    application = Application.objects.filter(
        id=application_id, customer=customer, application_status=ApplicationStatusCodes.FORM_CREATED
    )

    if not application.exists():
        message = 'Aplikasi tidak ditemukan'
        return is_success, ocr_result, message

    ocr_result = OcrKtpResult.objects.filter(application_id=application_id).last()
    if ocr_result:
        is_success = True
        detokenize_ocr_results = detokenize_for_model_object(
            PiiSource.OCR_KTP_RESULT,
            [
                {
                    'object': ocr_result,
                }
            ],
            force_get_local_data=True,
            pii_data_type=PiiVaultDataType.KEY_VALUE,
        )
        ocr_result = detokenize_ocr_results[0]
    else:
        message = 'Hasil OCR tidak ditemukan'
    return is_success, ocr_result, message


def has_partner_not_allowed_reapply(customer):
    application = customer.application_set.last()
    if not application:
        return False

    setting = get_config_partner_account_force_logout(application.id)
    if not setting:
        return False

    partner = application.partner
    if not partner:
        logger.info(
            {
                'message': 'Partner ID is empty',
                'application_id': application.id,
                'customer_id': customer.id,
            }
        )
        return False

    partner_name = partner.name
    list_partner_dont_reapply = []
    for partner in setting.parameters:
        list_partner_dont_reapply.append(str(partner).lower())

    partner_name = str(partner_name).lower()
    if partner_name in list_partner_dont_reapply:
        logger.info(
            {
                'message': 'Customer dont to reapply by list partner',
                'customer_id': customer.id,
                'application_id': application.id,
                'partner_name': partner_name,
            }
        )
        return True

    logger.info(
        {
            'message': 'passed check by list partner and can to reapply',
            'customer_id': customer.id,
            'application_id': application.id,
            'partner_name': partner_name,
        }
    )
    return False


def get_config_partner_account_force_logout(application_id=None):
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PARTNER_ACCOUNTS_FORCE_LOGOUT,
    ).last()

    if not setting:
        logger.warning(
            {
                'message': 'Configuration partner account force logout not found',
                'application_id': application_id,
            }
        )
        return None

    if not setting.is_active:
        logger.warning(
            {
                'message': 'Configuration partner account force logout is not active',
                'application_id': application_id,
            }
        )
        return None

    return setting


def confirm_customer_nik(customer, validated_data, application_id):
    application = Application.objects.filter(id=application_id).last()
    if not application or not customer or customer.id != application.customer.id:
        return False, 'Application tidak bisa ditemukan'

    with transaction.atomic():
        if customer.nik and customer.nik != validated_data['nik']:
            CustomerFieldChange.objects.create(
                customer=customer,
                field_name="nik",
                old_value=customer.nik,
                new_value=validated_data['nik'],
            )
        try:
            customer.update_safely(nik=validated_data.get('nik'))
        except IntegrityError:
            return False, 'NIK kamu sudah terdaftar'

        application.update_safely(ktp=validated_data.get('nik'))

    # trigger FDC
    with transaction.atomic(using='bureau_db'):
        fdc_inquiry = FDCInquiry.objects.create(
            nik=customer.nik, customer_id=customer.id, application_id=application.id
        )
        fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': customer.nik}
        execute_after_transaction_safely(
            lambda: run_fdc_inquiry_for_registration.delay(fdc_inquiry_data, 1)
        )
    return True, None


def get_experiment_setting(code) -> (ExperimentSetting, bool):
    """
    This function will return 2 values
    1. configuration object
    2. And range in time set for range start and end date active the experiment
    """

    configuration = ExperimentSetting.objects.filter(
        code=code,
    ).last()
    if not configuration:
        logger.info(
            {
                'message': 'Configuration is empty',
                'experiment_code': code,
            }
        )
        return None, False

    if not configuration.is_active:
        logger.info(
            {
                'message': 'Configuration is not active',
                'experiment_code': code,
            }
        )
        return None, False

    in_active_range = still_in_experiment(code, configuration)
    logger.info(
        {
            'message': 'Configuration result is in range active',
            'experiment_code': code,
            'in_range_active': in_active_range,
        }
    )

    return configuration, in_active_range


def is_user_offline_activation_booth(referral_code, application_id=None, set_path_tag=True):
    """
    To check by referral code is same with defined referral code on experiment setting
    """

    if not referral_code:
        logger.warning(
            {
                'message': 'Referral code is empty',
                'referral_code': referral_code,
                'application_id': application_id,
            }
        )
        return False

    # get configuration
    configuration, is_active = get_experiment_setting(
        code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
    )

    if not configuration or not is_active:
        logger.info(
            {
                'message': 'Experiment setting {} is not active'.format(
                    ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
                ),
                'referral_code': referral_code,
                'application_id': application_id,
            }
        )
        return False

    referral_code_set = None
    if configuration.criteria:
        referral_code_set = configuration.criteria.get('referral_code', None)

    if not referral_code_set:
        logger.warning(
            {
                'message': 'Experiment setting {} is active but referral code is empty'.format(
                    ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE
                ),
                'application_id': application_id,
                'referral_code': referral_code,
                'referral_code_set': referral_code_set,
            }
        )
        return False

    for code in referral_code_set:
        if code.lower() == str(referral_code).lower():
            if set_path_tag:
                logger.info(
                    {
                        'message': 'Try to set path tag {}'.format(OfflineBoothConst.TAG_NAME),
                        'application_id': application_id,
                        'set_path_tag': set_path_tag,
                    }
                )
                # set path tag
                application_tag_tracking_task(
                    application_id,
                    None,
                    None,
                    None,
                    OfflineBoothConst.TAG_NAME,
                    OfflineBoothConst.SUCCESS_VALUE,
                    traceback.format_stack(),
                )

            return True

    return False


def validate_web_token(application_xid, token, is_generate_token=True):
    try:
        web_token = AgentAssistedWebToken.get_token_instance(token)
        if not web_token:
            web_token = AgentAssistedWebToken.get_token_from_application(application_xid)
            return False, web_token.session_token if web_token else None

        if not web_token.is_token_valid_for_application(application_xid):
            logger.warn(
                {
                    'message': 'Web Token is invalid',
                    'action': 'SalesOpsTermsAndConditionView',
                    'application_xid': application_xid,
                    'token_last_4_chars': token[-4:] if token else 'N/A',
                }
            )
            return False, None

        if timezone.now() > web_token.expire_time or not web_token.is_active:
            if not is_generate_token:
                return False, None

            regenerate_token_reason = (
                'expired_token' if timezone.now() > web_token.expire_time else 'token_not_active'
            )
            new_token = regenerate_web_token_data(web_token, application_xid)
            logger.warn(
                {
                    'message': 'Web Token is expired or inactive',
                    'action': 'SalesOpsTermsAndConditionView',
                    'application_xid': application_xid,
                    'time_now': timezone.now(),
                    'token_udate': web_token.udate,
                    'regenerate_token_reason': regenerate_token_reason,
                }
            )
            return False, new_token

        return True, None

    except Exception as e:
        logger.warn(
            {
                'message': 'Failed to validate web token',
                'action': 'SalesOpsTermsAndConditionView',
                'error': str(e),
                'application_xid': application_xid,
                'time_now': timezone.now(),
            }
        )
        return False, None


def update_application_tnc(validated_data):
    application_xid = validated_data.get('application_xid')
    is_terms_agreed = validated_data.get('is_tnc_approved')
    is_data_validation_agreed = validated_data.get('is_data_validated')

    application = Application.objects.filter(
        application_xid=application_xid,
        application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
    ).first()
    if not application or not application.is_agent_assisted_submission():
        return False, 'Aplikasi tidak ditemukan'

    if application.is_verification_agreed and application.is_term_accepted:
        return False, 'Customer sudah pernah menyetujui Terms and Conditions'

    web_token = AgentAssistedWebToken.objects.filter(application_id=application.id).first()
    if not web_token.is_active:
        return False, 'Token is not active, please regenerate token by refreshing this page'

    if is_terms_agreed and is_data_validation_agreed:

        if not AddressGeolocation.objects.filter(application=application).exists():
            if validated_data.get('latitude') is None or validated_data.get('longitude') is None:
                return (
                    False,
                    'Lokasi gagal diakses, Harap Izinkan akses lokasi di browser peringkatmu, ya',
                )
            generate_address_location(
                application, validated_data.get('latitude'), validated_data.get('longitude')
            )

        application.is_term_accepted = is_terms_agreed
        application.is_verification_agreed = is_data_validation_agreed
        application.save()

        logger.warn(
            {
                'message': 'Moving to x105 for underwriting',
                'action': 'SalesOpsTermsAndConditionView.update_application_tnc',
                'application_id': application.id,
                'is_terms_agreed': is_terms_agreed,
                'is_data_validation_agreed': is_data_validation_agreed,
            }
        )

        process_application_status_change(
            application.id,
            ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='Consented for Data Processing',
        )

        web_token.update_safely(is_active=False)

        return True, None
    return False, 'Terms and Conditions belum disetujui'


def store_phone_number_application(data, customer_token):

    application_id = data.get('application_id')
    mobile_phone_number = data.get('phone_number')
    error_msg_default = 'Terjadi kesalahan ketika mengirimkan data'

    application = Application.objects.filter(pk=application_id).last()
    if not application:
        logger.error(
            {
                'message': 'Application is not found',
                'application_id': application_id,
            }
        )
        return False, error_msg_default

    customer_id = application.customer_id
    if customer_token.id != customer_id:
        logger.error(
            {
                'message': 'Customer token not match with application customer ID',
                'application_id': application_id,
                'customer_token_id': customer_token.id,
                'customer_id': customer_id,
            }
        )

        return False, error_msg_default

    is_exist = is_already_have_phone_record(customer_id)
    if is_exist:
        logger.error(
            {
                'message': 'Customer already have phone number in record',
                'customer_id': customer_id,
            }
        )
        return False, 'Kamu sudah pernah mengirimkan No. HP'

    ApplicationPhoneRecord.objects.create(
        application_id=application_id,
        customer_id=customer_id,
        mobile_phone_number=mobile_phone_number,
    )

    logger.error(
        {
            'message': 'Success to store phone number data',
            'application_id': application_id,
        }
    )
    return True, 'Nomor HP kamu sudah berhasil terkirim'


def is_already_have_phone_record(customer_id):

    return ApplicationPhoneRecord.objects.filter(
        customer_id=customer_id,
    ).exists()


def construct_and_check_value(
    application_id, list_of_source, value, threshold_value, field_name, record_data_update
):
    from juloserver.ocr.services import similarity_value

    if not list_of_source or not threshold_value:
        return value, record_data_update

    new_value = similarity_value(list_of_source, value, threshold_value, return_upper_text=False)
    if str(value).lower() == str(new_value).lower():
        return value, record_data_update

    logger.info(
        {
            'message': 'update data from repopulate_zipcode',
            'field_name': field_name,
            'application_id': application_id,
            'value': value,
            'new_value': new_value,
            'threshold': threshold_value,
        }
    )

    record_data_update.append(
        {
            'application_id': application_id,
            'field_name': field_name,
            'old_value': value,
            'new_value': new_value,
        }
    )

    return new_value, record_data_update


def record_application_change_field(application_id, record_data_update):

    if not record_data_update:
        return

    for item in record_data_update:
        if application_id != item['application_id']:
            return

        ApplicationFieldChange.objects.create(
            application_id=item['application_id'],
            field_name=item['field_name'],
            old_value=item['old_value'],
            new_value=item['new_value'],
        )


def get_julo_core_expiry_marks(is_need_exception=False):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS, is_active=True
    ).last()

    if is_need_exception and not feature_setting:
        error_message = 'JULO_CORE_EXPIRY_MARKS not active/missing'
        logger.warning({'message': error_message})
        raise JuloException(error_message)

    return feature_setting


def get_max_date_range_expiry(is_selected_status=False):

    feature_setting = get_julo_core_expiry_marks(is_need_exception=True)
    if not feature_setting:
        return None

    # add the list from value setting
    if is_selected_status:
        list_of_values = []
        for key in ExpireDayForm.LIST_KEYS_EXPIRY_DAY_ABOVE_x105:
            value_setting = int(feature_setting.parameters[key])
            list_of_values.append(value_setting)

        if list_of_values:
            early_day = min(list_of_values)
            range_date = timezone.now() - relativedelta(days=early_day)
            logger.info(
                {
                    'message': '[ExpireForm] range value for expiry',
                    'range_date': range_date,
                    'early_value': early_day,
                }
            )
            return range_date

        return None

    list_of_values = []
    # add the list from constants
    for day_expire in ExpireDayForm.LIST_EXPIRE_DAY_J1_CONST:
        list_of_values.append(day_expire)

    # add the list from feature setting
    for key in ExpireDayForm.LIST_KEYS_EXPIRY_DAY_BELOW_x105:
        value_setting = int(feature_setting.parameters[key])
        list_of_values.append(value_setting)

    early_day = min(list_of_values)
    if not early_day:
        return None

    range_date = timezone.now() - relativedelta(days=early_day)
    logger.info(
        {
            'message': '[ExpireForm] range value for expiry',
            'range_date': range_date,
            'early_day': early_day,
        }
    )
    return range_date
