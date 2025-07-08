from django.utils import timezone
from django.db import transaction
from datetime import timedelta

from juloserver.julo.models import (
    Customer,
    Device,
    ApplicationStatusCodes,
    Application,
    ProductLine,
    Workflow,
    AddressGeolocation,
    ApplicationHistory,
    OnboardingEligibilityChecking,
    Onboarding,
    FDCInquiry,
)

from juloserver.julo.product_lines import ProductLineCodes
from juloserver.apiv1.serializers import (
    ApplicationSerializer,
    CustomerSerializer,
    PartnerReferralSerializer,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.constants import OnboardingIdConst
from juloserver.application_form.constants import (
    AllowedOnboarding,
    JStarterOnboarding,
    GeneralMessageResponseShortForm,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.application_flow.services import store_application_to_experiment_table
from juloserver.application_flow.tasks import suspicious_ip_app_fraud_check
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.apiv2.tasks import generate_address_from_geolocation_async
from juloserver.pin.services import set_is_rooted_device
from juloserver.streamlined_communication.tasks import (
    send_sms_for_webapp_dropoff_customers_x100,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.application_form.exceptions import JuloProductPickerException
from juloserver.julo.services import update_customer_data
from juloserver.application_form.tasks.application_task import trigger_generate_good_fdc_x100
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.application_form.services.mother_name_experiment_service import MotherNameValidation

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def router_onboarding(onboarding_id):
    if onboarding_id not in AllowedOnboarding.JULO_PRODUCT_PICKER:
        logger.error(
            {
                "message": OnboardingIdConst.MSG_NOT_ALLOWED,
                "onboarding": onboarding_id,
            }
        )
        return False, OnboardingIdConst.MSG_NOT_ALLOWED

    return True, None


def get_device_customer(customer):
    device = Device.objects.values('id').filter(customer=customer).last()
    if not device:
        return None

    return device['id']


@sentry.capture_exceptions
def proceed_select_product(data):
    from juloserver.julo.services import (
        link_to_partner_if_exists,
        process_application_status_change,
    )
    from juloserver.application_form.services.application_service import (
        stored_application_to_upgrade_table,
        switch_workflow_product_by_onboarding,
    )
    from juloserver.julo_starter.services.services import user_have_upgrade_application

    partner_referral = None
    new_application = True
    onboarding_id = data['onboarding_id']
    app_version = data['app_version']
    previous_upgrade = None
    latitude = data.get('latitude', None)
    longitude = data.get('longitude', None)
    override_onboarding_id = None
    const = GeneralMessageResponseShortForm

    is_routed, error_msg = router_onboarding(onboarding_id)
    if not is_routed:
        raise JuloProductPickerException(error_msg)

    # get application_id
    customer = Customer.objects.get_or_none(id=data['customer_id'])
    if not customer:
        error_msg = "Customer not found"
        logger.error(
            {
                "message": error_msg,
                "customer": data['customer_id'],
                "process": "julo_starter_product_picker",
            }
        )
        raise JuloProductPickerException(error_msg)

    detokenize_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenize_customers[0]

    if Application.objects.filter(
        customer=customer,
        application_status_id=ApplicationStatusCodes.LOC_APPROVED,
    ).exists():
        error_msg = "Already have application approved"
        logger.error(
            {
                "message": error_msg,
                "process": "have_application_x190_go_product_picker",
                "customer": customer.id,
            }
        )
        raise JuloProductPickerException(error_msg)

    existing_app = check_existing_application(customer, return_last_instance=True)
    if existing_app:
        detokenize_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': existing_app.customer.customer_xid,
                    'object': existing_app,
                }
            ],
            force_get_local_data=True,
        )
        existing_app = detokenize_applications[0]
    device_id = get_device_customer(customer)
    allowed_create_app = False

    if existing_app and existing_app.status == ApplicationStatusCodes.FORM_PARTIAL:
        _, previous_upgrade = user_have_upgrade_application(customer, return_instance=True)
        if not previous_upgrade:
            error_msg = "Has application in progress approval"
            logger.error(
                {
                    "message": error_msg,
                    "app_version": app_version,
                    "onboarding_id": onboarding_id,
                    "application_id": existing_app.id,
                    "status_code": existing_app.application_status_id,
                }
            )
            raise JuloProductPickerException(
                'Kamu sudah memiliki pengajuan form, mohon kembali ke halaman utama'
            )

    # ONBOARDING_ID OVERRIDE SECTION
    # switch onboarding if sent parameter incorrect
    if onboarding_id == OnboardingIdConst.JULO_STARTER_ID and not is_allowed_pick_turbo(customer):
        logger.info(
            {
                'message': '[SwitchOnboardingID]: Switch to J1 onboarding_id',
                'reason': 'last application is x107',
                'onboarding_id': onboarding_id,
                'application_status_id': existing_app.application_status_id,
                'last_application': existing_app.id,
                'workflow_id': existing_app.workflow_id,
            }
        )

        onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID

    if onboarding_id == OnboardingIdConst.SHORTFORM_ID and existing_app:
        if not existing_app.email or not existing_app.ktp:
            logger.error(
                {
                    'message': 'Failed create application with onboarding ID Shortform',
                    'application_id': existing_app.id,
                }
            )
            return False, {
                const.key_name_flag: const.flag_not_allowed_reapply_for_shortform,
                const.key_name_message: const.message_not_allowed_reapply_for_shortform,
            }

        # change onboarding ID to 3 LFS
        old_onboarding_id = onboarding_id
        onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
        override_onboarding_id = onboarding_id

        logger.info(
            {
                'message': 'Re-route onboarding ID to onboarding ID Longform Shortened',
                'application_id': existing_app.id,
                'old_onboarding_id': old_onboarding_id,
                'new_onboarding_id': onboarding_id,
            }
        )
    # ONBOARDING_ID OVERRIDE SECTION OVER

    # handle condition if customer have application and x100
    if existing_app and existing_app.status == ApplicationStatusCodes.FORM_CREATED:
        new_application = False
        if (
            existing_app.onboarding_id == OnboardingIdConst.LONGFORM_SHORTENED_ID
            and onboarding_id == OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
        ):
            onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
        if existing_app.onboarding_id == onboarding_id:
            logger.info(
                {
                    "message": 'customer hit product picker even have application',
                    "process": 'return_with_same_application',
                    "app_version": app_version,
                    "selected_onboarding": onboarding_id,
                    "existing_onboarding": existing_app.onboarding_id,
                    "application_id": existing_app.id,
                }
            )

            existing_app.device = (
                Device.objects.get_or_none(id=device_id)
                if not existing_app.device
                else existing_app.device
            )

            existing_app_data = ApplicationSerializer(existing_app).data

            if customer.mother_maiden_name:
                customer_mother_maiden_name = {
                    "customer_mother_maiden_name": customer.mother_maiden_name
                }
                existing_app_data.update(customer_mother_maiden_name)

            return new_application, {
                "customer": CustomerSerializer(customer).data,
                "applications": [existing_app_data],
                "partner": PartnerReferralSerializer(partner_referral).data,
                "device_id": device_id,
            }
        else:
            # update the product data things (workflow, product, onboarding_id)
            existing_app = check_existing_application(customer, True)
            switch_workflow_product_by_onboarding(existing_app, onboarding_id)
            if onboarding_id == OnboardingIdConst.LONGFORM_SHORTENED_ID:
                # experiment stored as UW if onboarding_id is J1 / LFS
                store_application_to_experiment_table(existing_app, 'ExperimentUwOverhaul')

            return new_application, {
                "customer": CustomerSerializer(customer).data,
                "applications": [ApplicationSerializer(existing_app).data],
                "partner": PartnerReferralSerializer(partner_referral).data,
                "device_id": device_id,
            }

    if (
        existing_app
        and customer.can_reapply is False
        and existing_app.status
        and not allowed_create_app
        not in (
            ApplicationStatusCodes.OFFER_REGULAR,
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        )
    ):
        error_msg = "Cannot create other application"
        logger.error(
            {
                "function": 'Function call -> proceed_select_product',
                "message": error_msg,
                "customer": customer.id,
                "app_version": app_version,
                "onboarding_id": onboarding_id,
                "application_id": existing_app.id,
                "status_code": existing_app.application_status_id,
                "workflow_id": existing_app.workflow_id,
                "product_line_code": existing_app.product_line_code,
                "cdate": existing_app.cdate,
                "udate": existing_app.udate,
            }
        )
        raise JuloProductPickerException(error_msg)

    if not existing_app and customer.can_reapply is False:
        oec = OnboardingEligibilityChecking.objects.filter(customer=customer).last()
        if oec and (oec.fdc_check == 2 or oec.bpjs_check == 2):
            error_msg = "Cannot create other application"
            logger.error(
                {
                    "message": error_msg,
                    "customer": customer.id,
                    "app_version": app_version,
                    "onboarding_id": onboarding_id,
                }
            )
            raise JuloProductPickerException(error_msg)

    prev_app = customer.application_set.last()
    if customer.can_reapply and prev_app:
        if prev_app.status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD:
            error_msg = "Existing application not allowed to reapply"
            logger.error(
                {
                    "message": error_msg,
                    "customer": data['customer_id'],
                    "application": prev_app.id,
                    "process": "julo_starter_product_picker",
                }
            )
            raise JuloProductPickerException(error_msg)

        if prev_app.status == ApplicationStatusCodes.APPLICATION_DENIED:
            history = ApplicationHistory.objects.filter(
                status_old=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                status_new=ApplicationStatusCodes.APPLICATION_DENIED,
                application=prev_app,
            ).last()
            if history and onboarding_id == 7:
                error_msg = "Existing application not allowed to reapply"
                logger.error(
                    {
                        "message": error_msg,
                        "customer": data['customer_id'],
                        "application": prev_app.id,
                        "process": "julo_starter_product_picker",
                    }
                )
                raise JuloProductPickerException(error_msg)

        onboarding_id = (
            prev_app.onboarding_id
            if onboarding_id == OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
            and prev_app.onboarding_id != onboarding_id
            else onboarding_id
        )
        workflow, product_line = define_workflow_application(onboarding_id)
        onboarding = Onboarding.objects.get(pk=onboarding_id)
        application = duplicate_application(
            prev_app,
            request=data,
            overrides={
                "workflow": workflow,
                "product_line": product_line,
                "onboarding": onboarding,
            },
            override_onboarding_id=override_onboarding_id,
        )
    else:
        application = store_application_data(customer, app_version, onboarding_id)
        # reset mother maiden name in customer
        # customer.update_safely(mother_maiden_name=None)

    customer = update_customer_data(application, customer=customer)
    if customer.can_reapply:
        customer.can_reapply = False
        customer.can_reapply_date = None
        customer.save()

    # check suspicious IP
    suspicious_ip_app_fraud_check.delay(
        application.id, data.get('ip_address'), data.get('is_suspicious_ip')
    )

    # link to partner attribution rules
    if application.is_julo_one():
        partner_referral = link_to_partner_if_exists(application)
        # store the application to application experiment
        store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

    # check if select LFS with have upgrade flow from JTurbo
    if onboarding_id == OnboardingIdConst.LONGFORM_SHORTENED_ID:
        _, previous_upgrade = user_have_upgrade_application(customer, return_instance=True)

    # record application to upgrade table
    stored_application_to_upgrade_table(application, previous_upgrade)

    if application.ktp:
        fdc_inquiry = FDCInquiry.objects.filter(
            customer_id=application.customer.id, nik=application.ktp
        ).last()
        if fdc_inquiry and not fdc_inquiry.application_id:
            fdc_inquiry.update_safely(application_id=application.id, refresh=False)

    # change status application x0 to x100
    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
    )

    if application.is_julo_starter():
        oec = OnboardingEligibilityChecking.objects.filter(customer=customer).last()
        if oec and oec.bpjs_check == 1:
            oec.update_safely(application=application)

    if application.is_julo_one():
        trigger_generate_good_fdc_x100.delay(application_id=application.id)

        mother_name_validation = MotherNameValidation(
            application_id=application.id, app_version=app_version, mother_maiden_name=None
        )
        mother_name_validation.run()

    is_rooted_device = data.get('is_rooted_device', None)
    if is_rooted_device is not None:
        device = get_device_data(customer)
        set_is_rooted_device(application, is_rooted_device, device)

    # generate address location related with binary checking
    generate_address_location(
        application,
        latitude,
        longitude,
    )

    if (
        application.web_version
        and application.partner
        and application.product_line_code == ProductLineCodes.J1
    ):
        day_later = timezone.localtime(timezone.now()) + timedelta(hours=24)
        send_sms_for_webapp_dropoff_customers_x100.apply_async(
            (application.id, True), eta=day_later
        )

    # make sure getting last data
    application.refresh_from_db()

    application.device = (
        Device.objects.get_or_none(id=device_id) if not application.device else application.device
    )
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

    response_data = {
        "customer": CustomerSerializer(customer).data,
        "applications": [ApplicationSerializer(application).data],
        "partner": PartnerReferralSerializer(partner_referral).data,
        "device_id": device_id,
    }

    create_application_checklist_async.delay(application.id)

    return new_application, response_data


@sentry.capture_exceptions
def define_workflow_application(onboarding):
    if not onboarding:
        raise JuloProductPickerException(
            'Invalid condition create application with onboarding ID is empty'
        )

    if onboarding in JStarterOnboarding.JSTARTER_ONBOARDING:
        workflow = Workflow.objects.get_or_none(name=WorkflowConst.JULO_STARTER)
        product_line = ProductLine.objects.get_or_none(pk=ProductLineCodes.JULO_STARTER)
        return workflow, product_line

    workflow = Workflow.objects.get_or_none(name=WorkflowConst.JULO_ONE)
    product_line = ProductLine.objects.get_or_none(pk=ProductLineCodes.J1)
    return workflow, product_line


def store_application_data(customer, app_version, onboarding_id):
    workflow, product_line = define_workflow_application(onboarding_id)

    application_data = {
        'customer': customer,
        'ktp': customer.nik,
        'app_version': app_version,
        'web_version': None,
        'email': customer.email,
        'partner': None,
        'workflow': workflow,
        'product_line': product_line,
        'onboarding_id': onboarding_id,
    }

    if onboarding_id in OnboardingIdConst.JULO_360_IDS:
        application_data['mobile_phone_1'] = customer.phone

    with transaction.atomic():
        application = Application.objects.create(**application_data)

        return application


def duplicate_application(application: Application, *args, **kwargs):
    from juloserver.application_form.services.julo_starter_service import construct_reapply_data
    from juloserver.application_form.services.application_service import (
        is_user_offline_activation_booth,
    )

    override_onboarding_id = kwargs.get('override_onboarding_id', None)

    data = construct_reapply_data(
        application,
        application.customer,
        {
            "app_version": kwargs["request"]["app_version"],
            "device_id": kwargs["request"]["device_id"],
            "onboarding_id": override_onboarding_id,
        },
    )

    for kwarg in kwargs["overrides"]:
        data[kwarg] = kwargs["overrides"][kwarg]

    if "onboarding_id" in data:
        del data["onboarding_id"]

    application = Application.objects.create(**data)
    referral_code = application.referral_code
    if referral_code:
        # condition for offline activation booth
        is_user_offline_activation_booth(referral_code, application.id)

    return application


def get_device_data(customer):
    device = None
    if customer:
        device = Device.objects.filter(customer=customer).last()

    return device


def generate_address_location_for_application(
    application, latitude, longitude, update=False, address_latitude=None, address_longitude=None
):
    address_geolocation = AddressGeolocation.objects.filter(application=application).first()
    if address_geolocation:
        if update:
            new_latitude = latitude if latitude is not None else address_geolocation.latitude
            new_longitude = longitude if longitude is not None else address_geolocation.longitude
            address_geolocation.update_safely(latitude=new_latitude, longitude=new_longitude)
            generate_address_from_geolocation_async.delay(address_geolocation.id)

        if address_latitude and address_longitude:
            address_geolocation.update_safely(
                address_latitude=address_latitude,
                address_longitude=address_longitude,
            )
    else:
        if latitude is not None and longitude is not None:
            generate_address_location(
                application=application,
                latitude=latitude,
                longitude=longitude,
                address_latitude=address_latitude,
                address_longitude=address_longitude,
            )


def generate_address_location(
    application, latitude, longitude, address_latitude=None, address_longitude=None
):
    if not check_latitude_longitude(application, latitude, longitude):
        return

    existing_address = AddressGeolocation.objects.filter(application=application).last()
    if existing_address:
        logger.info(
            {
                'message': 'already have data address geolocation',
                'application': application.id if application else None,
            }
        )

        if not address_latitude and not address_longitude:
            return

        if not existing_address.address_latitude or not existing_address.address_longitude:
            logger.info(
                {
                    'message': 'update address latitude and longitude in address_geolocation',
                    'application_id': application.id,
                    'address_latitude': address_latitude,
                    'address_longitude': address_longitude,
                }
            )
            existing_address.update_safely(
                address_latitude=address_latitude,
                address_longitude=address_longitude,
            )
            return

    # create AddressGeolocation related with binary check
    address_geolocation = AddressGeolocation.objects.create(
        application=application,
        latitude=latitude,
        longitude=longitude,
        address_latitude=address_latitude,
        address_longitude=address_longitude,
    )

    logger.info(
        {
            'message': 'creating address geolocation by application',
            'application': application.id,
            'latitude': str(latitude),
            'longitude': str(longitude),
        }
    )

    # Address location generate
    generate_address_from_geolocation_async.delay(address_geolocation.id)


def check_latitude_longitude(application, latitude, longitude):
    if not latitude or not longitude:
        logger.error(
            {
                'message': 'latitude or longitude is empty',
                'application': application.id,
                'latitude': str(latitude),
                'longitude': str(longitude),
            }
        )
        return False

    return True


def check_existing_application(customer, return_last_instance=False, onboarding_id=None):
    application = customer.application_set

    if return_last_instance:
        if onboarding_id:
            return application.filter(onboarding_id=onboarding_id).last()
        return application.last()

    if onboarding_id:
        return application.filter(onboarding_id=onboarding_id).exists()

    return application.exists()


def is_allowed_pick_turbo(customer):
    turbo_app = (
        customer.application_set.filter(onboarding_id=OnboardingIdConst.JULO_STARTER_ID)
        .order_by('-id')
        .first()
    )

    if not turbo_app or turbo_app.application_status_id != ApplicationStatusCodes.OFFER_REGULAR:
        return True

    # If the turbo_app status is 107, check the J1 app status
    j1_app = (
        customer.application_set.filter(onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        .order_by('-id')
        .first()
    )

    if (
        j1_app
        and j1_app.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED
        and customer.can_reapply
    ):
        return True
    return False
