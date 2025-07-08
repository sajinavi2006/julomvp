import logging
from abc import (
    ABC,
    abstractmethod,
)
from typing import Union

from django.db.models import Q


from juloserver.fraud_security.tasks import (
    fetch_and_store_phone_insights_task,
)
from juloserver.ana_api.models import PdApplicationFraudModelResult
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.fraud_security.models import (
    FraudBlacklistedCompany,
    FraudBlacklistedPostalCode,
    FraudBlacklistedGeohash5,
    FraudBlacklistedEmergencyContact,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Application, Customer
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.geohash.models import AddressGeolocationGeohash

logger = logging.getLogger(__name__)


class AbstractBinaryCheckHandler(ABC):
    label = None
    fail_change_reason_format = 'Fail to pass fraud binary check. [{}]'
    fail_status_code = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD

    def __init__(self, application: Application):
        self.application = application

    @property
    def fail_change_reason(self):
        label = self.label
        if not label:
            label = self.__class__.__name__.replace('Handler', '')
        return self.fail_change_reason_format.format(label)

    @abstractmethod
    def is_pass(self) -> bool:
        """
        Return True if the application is passed the fraud check.
        Returns:
            bool
        """
        pass


class BlacklistedCompanyHandler(AbstractBinaryCheckHandler):
    def __init__(self, application: Application):
        super().__init__(application)
        self.setting = FeatureSettingHelper(FeatureNameConst.FRAUD_BLACKLISTED_COMPANY)

    def is_pass(self):
        if not self.setting.is_active:
            return True

        return not FraudBlacklistedCompany.objects.is_blacklisted(
            company_name=self.application.company_name
        )


class BlacklistedPostalCodeHandler(AbstractBinaryCheckHandler):
    def __init__(self, application: Application):
        super().__init__(application)
        self.setting = FeatureSettingHelper(FeatureNameConst.FRAUD_BLACKLISTED_POSTAL_CODE)

    def is_pass(self):
        if not self.setting.is_active:
            return True

        return not FraudBlacklistedPostalCode.objects.filter(
            postal_code=self.application.address_kodepos).exists()


class BlacklistedGeohash5Handler(AbstractBinaryCheckHandler):
    def __init__(self, application: Application):
        super().__init__(application)
        self.setting = FeatureSettingHelper(FeatureNameConst.FRAUD_BLACKLISTED_GEOHASH5)

    def is_pass(self):
        if not self.setting.is_active:
            return True

        if not getattr(self.application, 'addressgeolocation', None):
            return True

        address_geolocation_geohash = AddressGeolocationGeohash.objects.get(
            address_geolocation=self.application.addressgeolocation
        )

        return not FraudBlacklistedGeohash5.objects.filter(
            geohash5=address_geolocation_geohash.geohash6[:5]).exists()


class EmergencyContactBlacklistHandler(AbstractBinaryCheckHandler):
    """
    Handler class for checking if an emergency contact should lead to
    rejection of a J1 application.
    """

    def __init__(self, application: Application):
        super().__init__(application)
        self.setting = FeatureSettingHelper(FeatureNameConst.EMERGENCY_CONTACT_BLACKLIST)

    def is_pass(self):
        if not self.setting.is_active:
            logger.info(
                f"Emergency contact blacklist feature is inactive "
                f"for application_id={self.application.id}"
            )
            return True

        if not self.application.is_julo_one_product():
            return True

        # Initialize referral_code_valid
        referral_code_valid = False
        if self.application.referral_code:
            matching_customers = Customer.objects.filter(
                referral_code__iexact=self.application.referral_code
            )
            referral_code_valid = matching_customers.exists()

        emergency_contact_numbers = [
            number
            for number in [
                self.application.spouse_mobile_phone,
                self.application.close_kin_mobile_phone,
            ]
            if number
        ]
        last_mycroft_score = PdApplicationFraudModelResult.objects.filter(
            customer_id=self.application.customer_id, application_id=self.application.id
        ).last()
        mycroft_score_passed = last_mycroft_score.pgood < 0.9 if last_mycroft_score else False

        for number in emergency_contact_numbers:
            if (
                FraudBlacklistedEmergencyContact.objects.filter(phone_number=number).exists()
                and not referral_code_valid
                and mycroft_score_passed
            ):
                logger.info(
                    f"Application {self.application.id} rejected "
                    f"due to blacklisted emergency contact number, failed referral "
                    f"check and mycroft score < 0.9"
                )
                return False

        # Retrieve relevant J1 applications
        j1_applications = Application.objects.filter(
            (
                Q(spouse_mobile_phone__in=emergency_contact_numbers)
                | Q(close_kin_mobile_phone__in=emergency_contact_numbers)
            ),
            product_line_id=ProductLineCodes.J1,
        ).exclude(customer_id=self.application.customer_id)

        emergency_contact_used_count = j1_applications.count()
        unique_customers_with_emergency_contact = (
            j1_applications.values('customer_id').distinct().count()
        )

        # Blacklist condition check
        if emergency_contact_used_count >= 2 and unique_customers_with_emergency_contact > 1:
            suspicious_number = (
                self.application.spouse_mobile_phone or self.application.close_kin_mobile_phone
            )
            FraudBlacklistedEmergencyContact.objects.get_or_create(phone_number=suspicious_number)
            logger.info(
                f"Blacklisted emergency contact number {suspicious_number} "
                f"for application_id={self.application.id}"
            )

        # Final rejection decision based on all criteria
        if (
            emergency_contact_used_count >= 2
            and unique_customers_with_emergency_contact > 1
            and mycroft_score_passed
            and not referral_code_valid
        ):
            logger.info(
                f"Application rejected due to emergency contact "
                f"blacklist criteria for application_id={self.application.id}"
            )
            return False

        return True


class MonnaiInsightHandler(AbstractBinaryCheckHandler):
    def __init__(self, application: Application, source=''):
        super().__init__(application)
        self.setting = FeatureSettingHelper(FeatureNameConst.MONNAI_INSIGHT_INTEGRATION)
        self.source = source

    def is_pass(self):
        if not self.setting.is_active:
            return True

        if not self.application.is_julo_one_product():
            return True

        logger.info(
            {
                'message': 'MonnaiInsightHandler',
                'source': self.source,
                'application_id': self.application.id,
            }
        )

        fetch_and_store_phone_insights_task.delay(self.application.id, source=self.source)

        return True, None


def process_fraud_binary_check(
    application: Application, source='', use_monnai_handler: bool = False
) -> (bool, Union[None, AbstractBinaryCheckHandler]):
    """
    This function is used to check whether the application is passed fraud check or not.
    Args:
        application(Application): Application object
        source: To check source call
        use_monnai_handler: Bool to call monnai_insights
    Returns:
        bool, Union[None, AbstractBinaryCheckHandler]
    """
    # Add a new class in this variable for future handlers
    handlers = [
        BlacklistedCompanyHandler,
        BlacklistedPostalCodeHandler,
        BlacklistedGeohash5Handler,
        EmergencyContactBlacklistHandler,
        MonnaiInsightHandler,
    ]
    if not use_monnai_handler:
        handlers.remove(MonnaiInsightHandler)

    # Case to exclude the binary check Handlers for JTurbo applications based on
    # the trigger at x105 and x109.
    if application.is_julo_starter():
        if application.status == ApplicationStatusCodes.FORM_PARTIAL:
            handlers.remove(BlacklistedCompanyHandler)
        elif application.status == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED:
            handlers.remove(BlacklistedPostalCodeHandler)
            handlers.remove(BlacklistedGeohash5Handler)

    if source == 'handle_iti_ready':
        handlers = [
            MonnaiInsightHandler,
        ]

    logger_data = {
        'action': 'fraud_binary_check',
        'application_id': application.id,
    }
    for handler in handlers:
        if handler == MonnaiInsightHandler:
            handler_instance = handler(application, source)
        else:
            handler_instance = handler(application)
        if not handler_instance.is_pass():
            logger.info({
                'message': 'Fraud check failed',
                'handler': handler.__name__,
                **logger_data,
            })
            return False, handler_instance

        logger.info({
            'message': 'Fraud check passed',
            'handler': handler.__name__,
            **logger_data,
        })

    return True, None
