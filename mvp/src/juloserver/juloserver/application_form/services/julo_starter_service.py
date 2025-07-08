import copy
from django.db import transaction
from django.utils import timezone
from juloserver.apiv1.exceptions import ResourceNotFound
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Application, Mantri, OtpRequest, Device, Customer, Bank
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import OnboardingIdConst
from juloserver.julo.services import process_application_status_change, link_to_partner_if_exists
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julo.tasks2.application_tasks import send_deprecated_apps_push_notif
from juloserver.employee_financing.utils import verify_nik
from juloserver.julolog.julolog import JuloLog
from juloserver.application_form.constants import (
    JuloStarterFormResponseCode,
    JuloStarterFormResponseMessage,
    JuloStarterAppCancelResponseMessage,
    JuloStarterAppCancelResponseCode,
    JuloStarterReapplyResponseCode,
    JuloStarterReapplyResponseMessage,
    ApplicationReapplyFields,
)
from juloserver.application_flow.services import (
    store_application_to_experiment_table,
)
from juloserver.application_flow.tasks import suspicious_hotspot_app_fraud_check_task
from juloserver.otp.constants import SessionTokenAction
from juloserver.apiv2.tasks import populate_zipcode
from juloserver.apiv3.views import ApplicationUpdateV3
from juloserver.pin.services import does_user_have_pin
from juloserver.application_form.services.application_service import (
    stored_application_to_upgrade_table,
)
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pii_vault.constants import PiiSource

logger = JuloLog(__name__)
julo_sentry_client = get_julo_sentry_client()


def submit_form(user, application_id, validated_data):
    from juloserver.application_form.views.view_v1 import ApplicationUpdate as ApplicationUpdateV1

    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return (
            JuloStarterFormResponseCode.APPLICATION_NOT_FOUND,
            JuloStarterFormResponseMessage.APPLICATION_NOT_FOUND,
        )

    if application.customer.user.id != user.id:
        return (
            JuloStarterFormResponseCode.USER_NOT_ALLOW,
            JuloStarterFormResponseMessage.USER_NOT_ALLOW,
        )

    if not application.application_status_id != ApplicationStatusCodes.FORM_PARTIAL:
        return (
            JuloStarterFormResponseCode.APPLICATION_NOT_ALLOW,
            JuloStarterFormResponseMessage.APPLICATION_NOT_ALLOW,
        )
    selfie_service = ApplicationUpdateV3()
    if not selfie_service.check_liveness(
        application=application
    ) or not selfie_service.check_selfie_submission(application=application):
        return (
            JuloStarterFormResponseCode.NOT_FINISH_LIVENESS_DETECTION,
            JuloStarterFormResponseMessage.NOT_FINISH_LIVENESS_DETECTION,
        )

    phone_number = validated_data.get('mobile_phone_1')
    if phone_number and not is_verify_phone_number(phone_number, application.customer_id):
        return (
            JuloStarterFormResponseCode.INVALID_PHONE_NUMBER,
            JuloStarterFormResponseMessage.INVALID_PHONE_NUMBER,
        )

    email = validated_data.get('email')
    if email and is_email_existed(email, application.customer.user):
        return (
            JuloStarterFormResponseCode.EMAIL_ALREADY_EXIST,
            JuloStarterFormResponseMessage.EMAIL_ALREADY_EXIST,
        )

    ApplicationUpdateV1.claim_customer(application, validated_data)
    application_update_data = copy.deepcopy(validated_data)
    validated_data.pop('app_version')
    application_update_data['onboarding_id'] = OnboardingIdConst.JULO_STARTER_FORM_ID
    if validated_data.get('referral_code'):
        referral_code = validated_data['referral_code'].replace(' ', '')
        mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
        if mantri_obj:
            application_update_data['mantri_id'] = mantri_obj.id
    customer = application.customer
    mother_maiden_name = application_update_data.pop('mother_maiden_name', None)
    application_update_data['name_in_bank'] = application_update_data.get('fullname')
    application_update_data['device_id'] = validated_data.get('device')
    application_update_data.pop('device')

    with transaction.atomic():
        if mother_maiden_name:
            customer.update_safely(mother_maiden_name=mother_maiden_name, refresh=False)
        application.update_safely(**application_update_data)

    # modify populate_zipcode to sync since it became intermitent delay
    # between ana server and application table when generate score
    populate_zipcode(application)
    process_application_status_change(
        application.id,
        ApplicationStatusCodes.FORM_PARTIAL,
        change_reason='customer_triggered',
    )
    application.refresh_from_db()
    suspicious_hotspot_app_fraud_check_task.delay(application.id)
    send_deprecated_apps_push_notif.delay(application.id, application.app_version)

    validated_data['mobile_phone_1'] = application.mobile_phone_1

    return JuloStarterFormResponseCode.SUCCESS, validated_data


def is_verify_phone_number(phone_number, customer_id):
    otp_request = OtpRequest.objects.filter(
        phone_number=phone_number,
        is_used=True,
        action_type__in=(SessionTokenAction.VERIFY_PHONE_NUMBER, SessionTokenAction.PHONE_REGISTER),
    ).last()

    if not otp_request:
        return False

    if (
        otp_request.action_type == SessionTokenAction.VERIFY_PHONE_NUMBER
        and otp_request.customer_id != customer_id
    ):
        return False

    return True


def is_email_existed(email, user):
    if verify_nik(user.username):
        return True

    return False


def cancel_application(customer, validated_data=None):
    last_application = customer.application_set.regular_not_deletes().last()

    if (
        not last_application
        or last_application.application_status_id != ApplicationStatusCodes.FORM_CREATED
    ):
        return (
            JuloStarterAppCancelResponseCode.APPLICATION_NOT_FOUND,
            JuloStarterAppCancelResponseMessage.APPLICATION_NOT_FOUND,
        )

    if not last_application.is_julo_one() and not last_application.is_julo_starter():
        return (
            JuloStarterFormResponseCode.APPLICATION_NOT_ALLOW,
            JuloStarterFormResponseMessage.APPLICATION_NOT_ALLOW,
        )

    if (
        last_application.application_status_id == ApplicationStatusCodes.FORM_CREATED
        and validated_data
    ):
        try:
            if (
                'mother_maiden_name' in validated_data
                and validated_data['mother_maiden_name'] is not None
            ):
                customer.update_safely(mother_maiden_name=validated_data['mother_maiden_name'])
            for key, value in validated_data.items():
                if value:
                    setattr(last_application, key, value)
            with transaction.atomic():
                last_application.save()
        except Exception:
            julo_sentry_client.captureException()
            return (
                JuloStarterReapplyResponseCode.SERVER_ERROR,
                JuloStarterReapplyResponseMessage.SERVER_ERROR,
            )

    return JuloStarterAppCancelResponseCode.SUCCESS, JuloStarterAppCancelResponseMessage.SUCCESS


def reapply(user, application_data):
    customer = user.customer
    customer_update_data = {'is_review_submitted': False}
    if application_data.get('mother_maiden_name', None):
        customer_update_data['mother_maiden_name'] = application_data['mother_maiden_name']
    customer.update_safely(**customer_update_data)
    if not does_user_have_pin(user):
        return (
            JuloStarterReapplyResponseCode.USER_HAS_NO_PIN,
            JuloStarterReapplyResponseMessage.USER_HAS_NO_PIN,
        )

    # get last application
    last_application = customer.application_set.regular_not_deletes().last()
    if last_application and last_application.is_julo_one():
        if last_application.status != ApplicationStatusCodes.APPLICATION_DENIED:
            return (
                JuloStarterReapplyResponseCode.APPLICATION_NOT_FOUND,
                JuloStarterReapplyResponseMessage.APPLICATION_NOT_FOUND,
            )
        customer.update_safely(can_reapply=True, refresh=True)

        last_application = customer.application_set.filter(
            onboarding_id__in=[
                OnboardingIdConst.JULO_STARTER_ID,
                OnboardingIdConst.JULO_STARTER_FORM_ID,
            ]
        ).last()

    if not last_application:
        return (
            JuloStarterReapplyResponseCode.APPLICATION_NOT_FOUND,
            JuloStarterReapplyResponseMessage.APPLICATION_NOT_FOUND,
        )

    # handle null app version
    app_version = application_data.get('app_version')
    if not app_version:
        from juloserver.apiv2.services import get_latest_app_version

        application_data['app_version'] = get_latest_app_version()

    try:
        data_to_save = construct_reapply_data(last_application, customer, application_data)
    except ResourceNotFound as e:
        logger.error(str(e))
        return (
            JuloStarterReapplyResponseCode.DEVICE_NOT_FOUND,
            JuloStarterReapplyResponseMessage.DEVICE_NOT_FOUND,
        )
    try:
        with transaction.atomic():
            # prevent race condition when there are multiple request at the same time
            customer = Customer.objects.select_for_update().get(pk=customer.pk)
            if not customer.can_reapply:
                logger.warning(
                    {
                        'msg': 'creating application when can_reapply is false',
                        'customer_id': customer.id,
                    }
                )
                return (
                    JuloStarterReapplyResponseCode.CUSTOMER_CAN_NOT_REAPPLY,
                    JuloStarterReapplyResponseMessage.CUSTOMER_CAN_NOT_REAPPLY,
                )

            application = Application.objects.create(**data_to_save)
            logger.info(
                {
                    'action': 'application reapply',
                    'status': 'form_created',
                    'application': application,
                    'customer': customer,
                    'device': application.device,
                }
            )

            link_to_partner_if_exists(application)

            # to trigger name bank validation in x105
            store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_CREATED,
                change_reason='customer_triggered',
            )

            # update reapply value after creating new application
            customer.update_safely(can_reapply=False)

        create_application_checklist_async.delay(application.id)
        application.refresh_from_db()

        # init application upgrade
        stored_application_to_upgrade_table(application)

        return (
            JuloStarterReapplyResponseCode.SUCCESS,
            convert_to_reapply_response_data(customer, application),
        )
    except Exception:
        julo_sentry_client.captureException()
        return (
            JuloStarterReapplyResponseCode.SERVER_ERROR,
            JuloStarterReapplyResponseMessage.SERVER_ERROR,
        )


def construct_reapply_data(last_application, customer, reapply_data):
    # get device and app_version
    device = None
    if not reapply_data.get('web_version'):
        device_id = reapply_data['device_id']
        device = Device.objects.get_or_none(id=device_id, customer=customer)
        if device is None:
            raise ResourceNotFound(
                'julo starter reapply device_id={} not found, '
                'customer_id={}'.format(device_id, customer.id)
            )

    last_application_number = last_application.application_number
    if not last_application_number:
        last_application_number = 1
    application_number = last_application_number + 1

    onboarding_id_param = reapply_data.get('onboarding_id', None)
    onboarding_id = onboarding_id_param if onboarding_id_param else last_application.onboarding_id

    constructed_data = {
        'application_number': application_number,
        'app_version': reapply_data.get('app_version'),
        'web_version': reapply_data.get('web_version'),
        'device': device,
        'customer_id': last_application.customer_id,
        'onboarding_id': onboarding_id,
    }

    # detokenize_data
    detokenized_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [
            {
                'customer_xid': last_application.customer.customer_xid,
                'object': last_application,
            }
        ],
        force_get_local_data=True,
    )
    last_application = detokenized_applications[0]

    for field in ApplicationReapplyFields.JULO_STARTER:
        constructed_data[field] = getattr(last_application, field)

    bank_name = constructed_data['bank_name']
    if not Bank.objects.regular_bank().filter(bank_name=bank_name).last():
        constructed_data['bank_name'] = None
        constructed_data['bank_account_number'] = None

    # reapply referral code for mantri
    if last_application.mantri_id:
        referral_code = last_application.referral_code
        constructed_data['referral_code'] = referral_code

        # check duration
        today = timezone.localtime(timezone.now()).date()
        date_apply = last_application.cdate.date()
        day_range = (today - date_apply).days
        if day_range <= 30:
            # Set mantri id if referral code is a mantri id
            if referral_code:
                referral_code = referral_code.replace(' ', '')
                mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
                constructed_data['mantri'] = mantri_obj

    return constructed_data


def convert_to_reapply_response_data(customer: Customer, application: Application) -> dict:
    data = {
        'id': application.id,
        'status': application.status,
        'mother_maiden_name': customer.mother_maiden_name,
    }
    for field in ApplicationReapplyFields.JULO_STARTER:
        data[field] = getattr(application, field)
    del data['workflow']
    del data['product_line']

    return data
