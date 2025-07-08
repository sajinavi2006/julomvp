from juloserver.application_form.services.product_picker_service import generate_address_location
from juloserver.julo.models import (
    Application,
    AddressGeolocation,
    Customer,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.constants import OnboardingIdConst
from juloserver.pii_vault.services import detokenize_for_model_object, detokenize_value_lookup
from juloserver.pii_vault.constants import PiiSource, PIIType

logger = JuloLog(__name__)


def check_and_storing_location(
    application_id, latitude, longitude, address_latitude=None, address_longitude=None
):

    application = Application.objects.filter(pk=application_id).last()
    address_geolocation = AddressGeolocation.objects.filter(application=application).last()

    if not address_geolocation:
        logger.info(
            {
                'message': 'Generate address location at x105',
                'application_id': application_id,
                'latitude': latitude,
                'longitude': longitude,
            }
        )
        generate_address_location(
            application=application,
            latitude=latitude,
            longitude=longitude,
            address_latitude=address_latitude,
            address_longitude=address_longitude,
        )
        return True

    if address_latitude and address_longitude:
        logger.info(
            {
                'message': 'update address latitude and longitude in address_geolocation',
                'application_id': application.id,
                'address_latitude': address_latitude,
                'address_longitude': address_longitude,
            }
        )
        address_geolocation.update_safely(
            address_latitude=address_latitude,
            address_longitude=address_longitude,
        )

    return True


def is_passed_checking_email(application, onboarding_id, email):

    if not onboarding_id:
        onboarding_id = application.onboarding_id

    if onboarding_id not in (OnboardingIdConst.JULO_360_J1_ID, OnboardingIdConst.JULO_360_TURBO_ID):
        return True

    customer = Customer.objects.filter(pk=application.customer_id).last()

    detokenized_customer = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [{'customer_xid': customer.customer_xid, 'object': customer}],
        force_get_local_data=True,
    )
    customer = detokenized_customer[0]

    nik = customer.nik if customer.nik else application.ktp

    detokenize_value_lookup(email, PIIType.CUSTOMER)
    detokenize_value_lookup(nik, PIIType.CUSTOMER)
    existing = (
        Customer.objects.filter(
            email__iexact=email,
        )
        .exclude(nik=nik)
        .exists()
    )
    if existing:
        return False

    return True
