import re
from builtins import str
import logging
from django.db import transaction

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from django.core.exceptions import ObjectDoesNotExist

import juloserver.apiv2.services as apiv2_services
from juloserver.apiv2.tasks import generate_address_from_geolocation_async
from juloserver.apiv1.serializers import CustomerSerializer, ApplicationSerializer
from juloserver.apiv1.serializers import PartnerReferralSerializer
from juloserver.julo.services import process_application_status_change, link_to_partner_if_exists
from juloserver.fraud_security.constants import DeviceConst
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import Partner, AddressGeolocation, Customer
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julo.constants import OnboardingIdConst
from juloserver.pin.services import (
    CustomerPinService,
    get_device_model_name,
    validate_device,
    set_is_rooted_device,
)
from juloserver.application_flow.services import (
    store_application_to_experiment_table,
    create_julo1_application,
)
from juloserver.application_flow.tasks import suspicious_ip_app_fraud_check
from juloserver.otp.services import get_customer_phone_for_otp
from juloserver.registration_flow.exceptions import UserNotFound
from juloserver.application_form.services.application_service import (
    stored_application_to_upgrade_table,
)

logger = logging.getLogger(__name__)


def process_register_phone_number(customer_data):
    user, customer, application = create_initial_account(customer_data)

    # check suspicious IP
    suspicious_ip_app_fraud_check.delay(
        application.id, customer_data.get('ip_address'), customer_data.get('is_suspicious_ip')
    )

    # link to partner attribution rules
    partner_referral = link_to_partner_if_exists(application)

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
    )

    # record in application upgrade table
    stored_application_to_upgrade_table(application)

    # create Device
    device_id = None
    device = None
    if customer_data.get('app_version'):
        device_model_name = get_device_model_name(
            customer_data.get('manufacturer'), customer_data.get('model')
        )
        device, _ = validate_device(
            gcm_reg_id=customer_data['gcm_reg_id'],
            customer=customer,
            imei=customer_data.get('imei'),
            android_id=customer_data['android_id'],
            device_model_name=device_model_name,
            julo_device_id=customer_data.get(DeviceConst.JULO_DEVICE_ID),
        )
        device_id = device.id

        # store location to device_geolocation table
        apiv2_services.store_device_geolocation(
            customer, latitude=customer_data['latitude'], longitude=customer_data['longitude']
        )

    is_rooted_device = customer_data.get('is_rooted_device', None)
    if is_rooted_device is not None:
        set_is_rooted_device(application, is_rooted_device, device)

    # create AddressGeolocation
    address_geolocation = AddressGeolocation.objects.create(
        application=application,
        latitude=customer_data['latitude'],
        longitude=customer_data['longitude'],
    )
    generate_address_from_geolocation_async.delay(address_geolocation.id)

    response_data = {
        "token": str(user.auth_expiry_token),
        "customer": CustomerSerializer(customer).data,
        "applications": [ApplicationSerializer(application).data],
        "partner": PartnerReferralSerializer(partner_referral).data,
        "device_id": device_id,
        "set_as_jturbo": False,
    }

    create_application_checklist_async.delay(application.id)

    return response_data


def create_initial_account(customer_data):
    appsflyer_device_id, advertising_id = None, None

    if 'appsflyer_device_id' in customer_data:
        appsflyer_device_id_exist = Customer.objects.filter(
            appsflyer_device_id=customer_data['appsflyer_device_id']
        ).last()
        if not appsflyer_device_id_exist:
            appsflyer_device_id = customer_data['appsflyer_device_id']
            if 'advertising_id' in customer_data:
                advertising_id = customer_data['advertising_id']

    with transaction.atomic():
        phone = customer_data['phone']
        user = User.objects.filter(username=phone).last()
        if not user:
            err_msg = 'User not found, username={}'.format(phone)
            logger.error(err_msg)
            raise UserNotFound(err_msg)

        user.set_password(customer_data['pin'])
        user.save()

        customer = Customer.objects.create(
            user=user,
            phone=phone,
            appsflyer_device_id=appsflyer_device_id,
            advertising_id=advertising_id,
        )
        app_version = customer_data.get('app_version')

        partner_name = customer_data.get('partner_name')
        partner = Partner.objects.get_or_none(name=partner_name) if partner_name else None
        onboarding_id = customer_data.get('onboarding_id') or OnboardingIdConst.SHORTFORM_ID
        application = create_julo1_application(
            customer,
            None,
            app_version,
            web_version=None,
            email=None,
            partner=partner,
            phone=phone,
            onboarding_id=onboarding_id,
        )
        # store the application to application experiment
        application.refresh_from_db()
        store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(user)

    return user, customer, application


def get_customer_from_nik_email(username):

    customer = None
    try:
        if re.match(r'\d{16}', username):
            customer = Customer.objects.get(nik=username)
        else:
            customer = Customer.objects.get(email__iexact=username)
        if not customer.customer_xid:
            customer.generated_customer_xid
        customer_data = {"customer_xid": customer.customer_xid}
        if not customer.is_active:
            customer_data.update({"is_deleted_account": True})
        is_phone_number = True if get_customer_phone_for_otp(customer) else False
        customer_data["is_phone_number"] = is_phone_number
    except ObjectDoesNotExist:
        customer_data = None

    return customer_data, customer
