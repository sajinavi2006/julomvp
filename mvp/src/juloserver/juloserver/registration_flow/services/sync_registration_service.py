from juloserver.julo.models import AuthUser as User
from django.db import transaction

import juloserver.pin.services as pin_services
import juloserver.apiv2.services as apiv2_services
from juloserver.julo.models import (
    Customer,
    ExperimentSetting,
)
from juloserver.otp.services import get_customer_phone_for_otp
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.registration_flow.exceptions import SyncRegistrationException
from juloserver.registration_flow.exceptions import UserNotFound
from juloserver.registration_flow.services.v3 import create_record_of_device
from juloserver.apiv1.serializers import CustomerSerializer
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import ExperimentConst
from juloserver.account.models import ExperimentGroup
from juloserver.registration_flow.constants import SyncRegistrationConst


logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def check_existing_customer(phone) -> (bool, str):

    if not phone:
        logger.error(
            {
                'message': '[SyncRegistration] Invalid Phone number',
                'phone_number': phone,
            }
        )
        return False, 'Invalid phone number'

    customers = Customer.objects.filter(phone=phone)
    customer = []
    first_cust_xid, existing_customer = None, False

    if customers:
        existing_customer = True

        if len(customers) == 1:
            first_cust = customers.first()
            is_phone_number = True if get_customer_phone_for_otp(first_cust) else False
            if not first_cust.customer_xid:
                first_cust_xid = first_cust.generated_customer_xid
            else:
                first_cust_xid = first_cust.customer_xid

            has_pin = pin_services.does_user_have_pin(first_cust.user)
            is_locked = False
            is_permanently_blocked = False
            if has_pin:
                customer_pin = first_cust.user.pin
                pin_process = pin_services.VerifyPinProcess()
                (
                    max_retry_count,
                    max_block_number,
                ) = pin_services.get_global_pin_setting()[1:3]

                if pin_process.is_user_locked(customer_pin, max_retry_count):
                    is_locked = True
                if pin_process.is_user_permanent_locked(customer_pin, max_block_number):
                    is_permanently_blocked = True

            data = {
                "customer_xid": first_cust_xid,
                "is_phone_number": is_phone_number,
                "customer_has_pin": has_pin,
                "is_locked": is_locked,
                "is_permanently_blocked": is_permanently_blocked,
            }
            customer.append(data)

    data = {
        "found": len(customers) > 0,
        "existing_customer": existing_customer,
        "total_found": len(customers),
        "customer": str(customer),
    }

    logger.info(
        {'message': '[SyncRegistration] checking existing customer phone {}'.format(phone), **data}
    )

    if existing_customer:
        logger.warning(
            {
                'message': '[SyncRegistration] already registered as user',
                'phone_number': phone,
                'customer_xid': first_cust_xid,
            }
        )
        return False, 'Already registered as user'

    return True, None


@sentry.capture_exceptions
def init_auth_data(phone) -> (bool, dict):

    data = {}
    if not phone:
        return False, data

    # double check to existing or not
    existing_user = User.objects.filter(username=phone).last()
    if existing_user:
        logger.info(
            {'message': '[SyncRegistration] phone number already registered', 'phone': phone}
        )
        data = {'auth_user_id': existing_user.id, 'auth_token': existing_user.auth_expiry_token.key}
        return True, data

    try:
        with transaction.atomic():
            user = User.objects.create(username=phone)
            data = {'auth_user_id': user.id, 'auth_token': user.auth_expiry_token.key}
            logger.info(
                {
                    'message': '[SyncRegistration] success to create user and customer data',
                    'phone': phone,
                    'auth_user_id': user.id,
                }
            )
    except Exception as error:
        error_message = 'failed to create data: {}'.format(str(error))
        logger.error(
            {'message': '[SyncRegistration] {}'.format(error_message), 'phone_number': phone}
        )
        raise SyncRegistrationException(error_message)

    return True, data


def process_sync_registration_phone_number(customer_data):
    appsflyer_device_id = None
    advertising_id = None
    phone = customer_data.get('phone')
    app_version = customer_data.get('app_version')
    latitude = customer_data.get('latitude', None)
    longitude = customer_data.get('longitude', None)

    # to get value if exists
    appsflyer_device_id, advertising_id = pin_services.determine_ads_info(
        customer_data, appsflyer_device_id, advertising_id
    )
    with transaction.atomic():
        user = User.objects.filter(username=phone).last()
        if not user:
            err_msg = 'User not found, username={}'.format(phone)
            logger.error(err_msg)
            raise UserNotFound(err_msg)

        user.set_password(customer_data['pin'])
        user.save(update_fields=["password"])

        customer = Customer.objects.create(
            user=user,
            phone=phone,
            appsflyer_device_id=appsflyer_device_id,
            advertising_id=advertising_id,
        )
        customer_pin_service = pin_services.CustomerPinService()
        customer_pin_service.init_customer_pin(user)

        # store as experiment in customer level
        store_customer_as_experiment(customer.id)

    device_id = create_record_of_device(customer, customer_data)

    # store location to device_geolocation table
    if app_version:
        apiv2_services.store_device_geolocation(customer, latitude=latitude, longitude=longitude)

    # auth user id add as response
    auth_user_id = user.id if user else None
    response_data = {
        "token": str(user.auth_expiry_token),
        "customer": CustomerSerializer(customer).data,
        "status": ApplicationStatusCodes.NOT_YET_CREATED,
        "device_id": device_id,
        "set_as_jturbo": False,
        'auth_user_id': auth_user_id,
    }
    logger.info(
        {
            'message': '[SyncRegistration] embed auth user id',
            'auth_user_id': auth_user_id,
            'customer_id': customer.id if customer else None,
        }
    )

    return response_data


def store_customer_as_experiment(
    customer_id,
    code=ExperimentConst.SYNC_REGISTRATION_J360_SERVICES,
    segment=SyncRegistrationConst.SYNC_J360_TO_REGULAR_FLOW,
):
    """
    sync_j360_regular_flow -> Sync from J360 Service to MVP (juloDB)
    """

    experiment_setting = ExperimentSetting.objects.filter(
        code=code,
    ).last()

    if not experiment_setting:
        return False

    if not ExperimentGroup.objects.filter(
        customer_id=customer_id,
        experiment_setting=experiment_setting,
        segment=segment,
    ).exists():
        ExperimentGroup.objects.create(
            customer_id=customer_id,
            group='experiment',
            segment=segment,
            experiment_setting=experiment_setting,
        )
        logger.info(
            {
                'message': '[SyncRegistration] store to experiment table',
                'code': code,
                'segment': segment,
                'customer_id': customer_id,
            }
        )

    return True
