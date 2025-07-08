import json
import re
from datetime import datetime, date

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from juloserver.dana.constants import (
    AccountInfoResponseCode,
    BindingResponseCode,
    BindingRejectCode,
    CUSTOMER_UPDATE_KEY,
    UPDATE_KEY_LIMIT,
    AccountUpdateResponseCode,
    DanaProductType,
    DanaQueryTypeAccountInfo,
)
from juloserver.dana.exceptions import APIInvalidFieldFormatError, APIError, APIMandatoryFieldError
from juloserver.dana.models import DanaCustomerData, DanaApplicationReference
from juloserver.dana.onboarding.services import is_whitelisted_user
from juloserver.dana.utils import get_redis_key
from juloserver.julo.models import Partner
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import trim_name, format_mobile_phone
from juloserver.partnership.utils import verify_nik, validate_image_url

from rest_framework import serializers
from rest_framework import status

from typing import Any, Dict, Union


class DanaRegisterSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using a that Format

    creditSore, lenderProductId, appId might not used in JULO side
    but we still validate it to required because in DANA side the data is required
    """

    def __init__(self, partner: Partner, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.partner = partner

    customerId = serializers.CharField(
        required=True,
    )
    partnerReferenceNo = serializers.CharField(
        required=True,
    )
    phoneNo = serializers.CharField(
        required=True,
    )
    registrationTime = serializers.CharField(
        required=True,
    )
    cardId = serializers.CharField(
        required=True,
    )
    cardName = serializers.CharField(
        required=True,
    )
    selfieImage = serializers.CharField(
        required=True,
    )
    identityCardImage = serializers.CharField(
        required=True,
    )
    address = serializers.CharField(
        required=True,
    )
    dob = serializers.CharField(
        required=True,
    )
    proposedCreditLimit = serializers.CharField(
        required=True,
    )
    creditScore = serializers.CharField(
        required=True,
    )
    lenderProductId = serializers.CharField(
        required=True,
    )
    appId = serializers.CharField(
        required=True,
    )
    incomeRange = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    pob = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    gender = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    cityHomeAddress = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    provinceHomeAddress = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    postalCodeHomeAddress = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    occupation = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    sourceOfIncome = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    domicileAddress = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    marriageStatus = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    houseOwnership = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    educationalLevel = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate_customerId(self, value: str) -> int:
        try:
            value = int(value)
        except Exception:
            raise APIInvalidFieldFormatError(
                detail={'customerId': 'Invalid customerId, customerId not a number'},
            )

        return value

    def validate_registrationTime(self, value: str) -> datetime:
        value = parse_datetime(value)
        if not value:
            raise APIInvalidFieldFormatError(
                detail={'registrationTime': 'Invalid datetime format'},
            )

        try:
            value = timezone.localtime(value)
        except Exception:
            raise APIInvalidFieldFormatError(
                detail={'registrationTime': 'Invalid datetime format'},
            )

        return value

    def validate_phoneNo(self, value: str) -> str:
        """
        Standarize +62, 62, become 08
        startswith 08, range 8 -13
        eg: 082290907878
        """

        msg = {'phoneNo': 'Invalid phoneNo format'}

        if len(value) > 16:
            raise APIInvalidFieldFormatError(
                detail=msg,
            )
        elif not value.isnumeric():
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        try:
            phone_number = format_mobile_phone(value)
        except Exception:
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return phone_number

    def validate_cardName(self, value: str) -> str:

        msg = {'cardName': 'Invalid name format, name too long'}
        if len(value) > 100:
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_cardId(self, value: str) -> str:
        if not verify_nik(value):
            raise APIInvalidFieldFormatError(detail={'cardId': 'Invalid cardId format'})

        return value

    def validate_selfieImage(self, value: str) -> str:
        if not validate_image_url(value):
            raise APIInvalidFieldFormatError(
                detail={'selfieImage': 'Invalid selfieImage format'},
            )

        return value

    def validate_identityCardImage(self, value: str) -> str:
        if not validate_image_url(value):
            raise APIInvalidFieldFormatError(
                detail={'identityCardImage': 'Invalid identityCardImage format'},
            )

        return value

    def validate_dob(self, value: str) -> date:
        date_parser = datetime.strptime
        try:
            value = date_parser(value, '%d-%m-%Y')
        except Exception:
            raise APIInvalidFieldFormatError(
                detail={'dob': 'Invalid dob format'},
            )

        return value

    def validate_proposedCreditLimit(self, value: str) -> float:
        try:
            value = float(value)
        except Exception:
            raise APIInvalidFieldFormatError(
                detail={'proposedCreditLimit': 'proposedCreditLimit not a number'},
            )

        return value

    def validate_creditScore(self, value: str) -> Union[None, int]:
        if value:
            try:
                value = int(value)
            except Exception:
                raise APIInvalidFieldFormatError(
                    detail={'creditScore': 'Invalid creditScore, creditScore not a number'},
                )
        return value

    def validate_lenderProductId(self, value: str) -> str:
        msg = {'lenderProductId': 'Invalid lenderProductId format or lenderProductId too long'}
        if len(value) > 255:
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        if value not in {DanaProductType.CASH_LOAN, DanaProductType.CICIL}:
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_appId(self, value: str) -> str:
        msg = {'appId': 'Invalid appId format, appId too long'}
        if len(value) > 255:
            raise APIInvalidFieldFormatError(
                detail=msg,
            )
        return value

    def validate_incomeRange(self, value: str) -> str:
        if value and len(value) > 64:
            msg = {'incomeRange': 'Invalid incomeRange format or incomeRange too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_pob(self, value: str) -> str:
        if value and len(value) > 64:
            msg = {'pob': 'Invalid pob format or pob too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_gender(self, value: str) -> str:
        if value and len(value) > 16:
            msg = {'gender': 'Invalid gender format or gender too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_cityHomeAddress(self, value: str) -> str:
        if value and len(value) > 64:
            msg = {'cityHomeAddress': 'Invalid cityHomeAddress format or cityHomeAddress too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_provinceHomeAddress(self, value: str) -> str:
        if value and len(value) > 64:
            err_msg = 'Invalid provinceHomeAddress format or provinceHomeAddress too long'
            msg = {'provinceHomeAddress': err_msg}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_postalCodeHomeAddress(self, value: str) -> str:
        if value and len(value) > 64:
            err_msg = 'Invalid postalCodeHomeAddress format or postalCodeHomeAddress too long'
            msg = {'postalCodeHomeAddress': err_msg}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_occupation(self, value: str) -> str:
        if value and len(value) > 64:
            msg = {'occupation': 'Invalid occupation format or occupation too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_sourceOfIncome(self, value: str) -> str:
        if value and len(value) > 64:
            msg = {'sourceOfIncome': 'Invalid sourceOfIncome format or sourceOfIncome too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_domicileAddress(self, value: str) -> str:
        if value and len(value) > 1024:
            msg = {'domicileAddress': 'Invalid domicileAddress format or domicileAddress too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_marriageStatus(self, value: str) -> str:
        if value and len(value) > 16:
            msg = {'marriageStatus': 'Invalid marriageStatus format or marriageStatus too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_houseOwnership(self, value: str) -> str:
        if value and len(value) > 64:
            msg = {'houseOwnership': 'Invalid houseOwnership format or houseOwnership too long'}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate_educationalLevel(self, value: str) -> str:
        if value and len(value) > 64:
            err_msg = 'Invalid educationalLevel format or educationalLevel too long'
            msg = {'educationalLevel': err_msg}
            raise APIInvalidFieldFormatError(
                detail=msg,
            )

        return value

    def validate(self, data: Dict) -> Dict:
        # Handle if existing phone number or nik but different customer Id
        nik = data.get('cardId')
        phone_no = data.get('phoneNo')
        dana_customer_id = data.get('customerId')
        partner_reference_no = data.get('partnerReferenceNo')
        card_name = data.get('cardName')
        card_id = data.get('cardId')
        lender_product_id = data.get('lenderProductId')

        user_whitelisted = is_whitelisted_user(str(dana_customer_id))

        # Handling idempotency and fraud request
        dana_customer = DanaCustomerData.objects.filter(
            dana_customer_identifier=dana_customer_id, lender_product_id=lender_product_id
        ).last()

        if dana_customer:
            application = dana_customer.application

            application_id = application.id
            dana_application_reference = DanaApplicationReference.objects.get(
                application_id=application_id
            )

            existing_partner_reference_no = dana_application_reference.partner_reference_no
            reference_no = dana_application_reference.reference_no

            # If Fraud (133) and valid (190) early return, cannot re-apply
            if application.status == ApplicationStatusCodes.LOC_APPROVED:
                """
                Special Case if user is registered and valid will be returning SUCCESS
                This case covered if dana hit our API getting Timeout and hit again
                based on customerId Dana expected to return Success or 200 with rejectCode
                """
                data = {
                    'responseCode': BindingResponseCode.SUCCESS.code,
                    'responseMessage': BindingResponseCode.SUCCESS.message,
                    'accountId': str(dana_customer.customer.customer_xid),
                    'partnerReferenceNo': existing_partner_reference_no,
                    'referenceNo': str(reference_no),
                    'additionalInfo': {
                        'rejectCode': BindingRejectCode.USER_HAS_REGISTERED.code,
                        'rejectReason': BindingRejectCode.USER_HAS_REGISTERED.reason,
                        'approvedCreditLimit': {
                            'value': '{:.2f}'.format(dana_customer.proposed_credit_limit),
                            'currency': 'IDR',
                        },
                    },
                }

                raise APIError(status_code=status.HTTP_200_OK, detail=data)
            else:
                is_fraud_application = (
                    application.status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
                )

                # Currently whitelist fraud only for dana cicil user
                if not user_whitelisted and is_fraud_application:
                    data = {
                        'responseCode': BindingResponseCode.BAD_REQUEST.code,
                        'responseMessage': BindingResponseCode.BAD_REQUEST.message,
                        'accountId': str(dana_customer.customer.customer_xid),
                        'partnerReferenceNo': existing_partner_reference_no,
                        'referenceNo': str(reference_no),
                        'additionalInfo': {
                            'rejectCode': BindingRejectCode.FRAUD_CUSTOMER.code,
                            'rejectReason': BindingRejectCode.FRAUD_CUSTOMER.reason,
                        },
                    }

                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=data)

        # Handling inconsistent request
        is_exists_partner_reference_no = DanaApplicationReference.objects.filter(
            partner_reference_no=partner_reference_no
        ).exists()

        if is_exists_partner_reference_no:
            data = {
                'responseCode': BindingResponseCode.INCONSISTENT_REQUEST.code,
                'responseMessage': BindingResponseCode.INCONSISTENT_REQUEST.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': {
                    'rejectCode': BindingRejectCode.HAS_INCONSISTENT_REQUEST.code,
                    'rejectReason': BindingRejectCode.HAS_INCONSISTENT_REQUEST.reason,
                    'errors': {'partnerReferenceNo': 'partnerReferenceNo already exists'},
                },
            }

            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=data)

        if (
            DanaCustomerData.objects.filter(
                nik=nik,
                lender_product_id=lender_product_id,
            )
            .exclude(dana_customer_identifier=dana_customer_id)
            .exists()
        ):
            error_data = {
                'responseCode': BindingResponseCode.BAD_REQUEST.code,
                'responseMessage': BindingResponseCode.BAD_REQUEST.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': {
                    'rejectCode': BindingRejectCode.EXISTING_USER_DIFFERENT_CUSTOMER_ID.code,
                    'rejectReason': BindingRejectCode.EXISTING_USER_DIFFERENT_CUSTOMER_ID.reason,
                },
            }

            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

        # Currently whitelist fraud only for dana cicil user
        if lender_product_id == DanaProductType.CICIL:

            # Phone number matching only for Dana cicil user
            if (
                DanaCustomerData.objects.filter(
                    mobile_number=phone_no,
                    lender_product_id=lender_product_id,
                )
                .exclude(dana_customer_identifier=dana_customer_id)
                .exists()
            ):
                reject_code = BindingRejectCode.EXISTING_USER_DIFFERENT_CUSTOMER_ID.code
                reject_reason = BindingRejectCode.EXISTING_USER_DIFFERENT_CUSTOMER_ID.reason
                error_data = {
                    'responseCode': BindingResponseCode.BAD_REQUEST.code,
                    'responseMessage': BindingResponseCode.BAD_REQUEST.message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {
                        'rejectCode': reject_code,
                        'rejectReason': reject_reason,
                    },
                }

                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

        # Handle if existing user dana cicil / dana cashloan, different NIK
        existing_user_with_different_product = (
            DanaCustomerData.objects.filter(dana_customer_identifier=dana_customer_id)
            .exclude(lender_product_id=lender_product_id)
            .last()
        )

        if existing_user_with_different_product and (
            existing_user_with_different_product.nik != nik
        ):
            error_data = {
                'responseCode': BindingResponseCode.BAD_REQUEST.code,
                'responseMessage': BindingResponseCode.BAD_REQUEST.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': {
                    'rejectCode': BindingRejectCode.EXISTING_USER_DIFFERENT_NIK.code,
                    'rejectReason': BindingRejectCode.EXISTING_USER_DIFFERENT_NIK.reason,
                },
            }

            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

        if not user_whitelisted:

            # Cache fraud phone key
            fraud_phone_key = '%s_%s' % ("fraud_phone_key:", phone_no)
            is_phone_fraud = get_redis_key(fraud_phone_key)
            if is_phone_fraud:
                error_data = {
                    'responseCode': BindingResponseCode.BAD_REQUEST.code,
                    'responseMessage': BindingResponseCode.BAD_REQUEST.message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {
                        'rejectCode': BindingRejectCode.FRAUD_CUSTOMER.code,
                        'rejectReason': BindingRejectCode.FRAUD_CUSTOMER.reason,
                    },
                }

                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            # Cache Blacklisted name
            stripped_name = trim_name(card_name)
            blacklist_key = '%s_%s' % ("blacklist_user_key:", stripped_name)
            is_blacklisted = get_redis_key(blacklist_key)
            if is_blacklisted:
                error_data = {
                    'responseCode': BindingResponseCode.BAD_REQUEST.code,
                    'responseMessage': BindingResponseCode.BAD_REQUEST.message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {
                        'rejectCode': BindingRejectCode.BLACKLISTED_CUSTOMER.code,
                        'rejectReason': BindingRejectCode.BLACKLISTED_CUSTOMER.reason,
                    },
                }

                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            # Cache Fraud NIK
            fraud_nik_key = '%s_%s' % ("fraud_nik_key:", card_id)
            is_nik_fraud = get_redis_key(fraud_nik_key)
            if is_nik_fraud:
                error_data = {
                    'responseCode': BindingResponseCode.BAD_REQUEST.code,
                    'responseMessage': BindingResponseCode.BAD_REQUEST.message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {
                        'rejectCode': BindingRejectCode.FRAUD_CUSTOMER.code,
                        'rejectReason': BindingRejectCode.FRAUD_CUSTOMER.reason,
                    },
                }

                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

        return data

    def save(self) -> DanaCustomerData:
        data = {
            'partner': self.partner,
            'mobile_number': self.validated_data['phoneNo'],
            'registration_time': self.validated_data['registrationTime'],
            'nik': self.validated_data['cardId'],
            'full_name': self.validated_data['cardName'],
            'selfie_image_url': self.validated_data['selfieImage'],
            'ktp_image_url': self.validated_data['identityCardImage'],
            'proposed_credit_limit': self.validated_data['proposedCreditLimit'],
            'credit_score': self.validated_data['creditScore'],
            'app_id': self.validated_data['appId'],
            'dob': self.validated_data['dob'],
            'address': self.validated_data['address'],
            'income': self.validated_data.get('incomeRange'),
            'pob': self.validated_data.get('pob'),
            'gender': self.validated_data.get('gender'),
            'city_home_address': self.validated_data.get('cityHomeAddress'),
            'province_home_address': self.validated_data.get('provinceHomeAddress'),
            'postal_code_home_address': self.validated_data.get('postalCodeHomeAddress'),
            'occupation': self.validated_data.get('occupation'),
            'source_of_income': self.validated_data.get('sourceOfIncome'),
            'domicile_address': self.validated_data.get('domicileAddress'),
            'marriage_status': self.validated_data.get('marriageStatus'),
            'house_ownership': self.validated_data.get('houseOwnership'),
            'educational_level': self.validated_data.get('educationalLevel'),
        }

        dana_customer_data, _ = DanaCustomerData.objects.update_or_create(
            dana_customer_identifier=self.validated_data['customerId'],
            lender_product_id=self.validated_data['lenderProductId'],
            defaults=data,
        )
        return dana_customer_data


class DanaAccountUpdateLimitValueSerializer(serializers.Serializer):
    currency = serializers.CharField(required=True)
    value = serializers.CharField(required=True)


class DanaAccountUpdateInfoSerializer(serializers.Serializer):
    updateKey = serializers.CharField(required=True)
    updateValue = serializers.CharField(required=True)
    updateAdditionalInfo = serializers.DictField(
        child=serializers.CharField(), required=True, allow_null=True
    )

    def validate(self, data):
        if data['updateKey'] == UPDATE_KEY_LIMIT:
            update_value = json.loads(data['updateValue'])
            if not DanaAccountUpdateLimitValueSerializer(data=update_value).is_valid():
                raise APIMandatoryFieldError(
                    detail={'updateValue': "Invalid updateValue format for updateKey 'limit'"}
                )

        if data['updateAdditionalInfo'] is not None and len(data['updateAdditionalInfo']) == 0:
            raise APIInvalidFieldFormatError(
                detail={'updateAdditionalInfo': "Invalid updateAdditionalInfo, cannot empty JSON"}
            )

        return data


class DanaAccountUpdateSerializer(serializers.Serializer):
    customerId = serializers.CharField(required=True)
    lenderProductId = serializers.CharField(required=True)
    updateInfoList = serializers.ListField(
        child=DanaAccountUpdateInfoSerializer(), allow_empty=False
    )
    additionalInfo = serializers.DictField(required=True)

    def validate_customerId(self, value):
        # Invalid format length
        if len(value) > 64:
            raise APIMandatoryFieldError(
                detail={'customerId': 'Invalid customerId, customerId too long'},
            )

        # Customer id not found
        is_exists_dana_customer = DanaCustomerData.objects.filter(
            dana_customer_identifier=value
        ).exists()
        if not is_exists_dana_customer:
            response_data = {
                'responseCode': AccountUpdateResponseCode.BAD_REQUEST.code,
                'responseMessage': AccountUpdateResponseCode.BAD_REQUEST.message,
                'additionalInfo': {
                    'errors': {'customerId': 'Invalid customerId, customerId not a found'}
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )

        try:
            value = int(value)
        except Exception:
            raise APIInvalidFieldFormatError(
                detail={'customerId': 'Invalid customerId, customerId not a number'},
            )

        return value

    def validate_lenderProductId(self, value: str) -> str:
        if len(value) > 32:
            raise APIMandatoryFieldError(
                detail={'lenderProductId': 'Invalid lenderProductId, lenderProductId too long'},
            )

        return value

    def validate_updateInfoList(self, value):

        # Check duplicate updateKey
        value_key_list = [item['updateKey'] for item in value]
        has_duplicate_key = any(value_key_list.count(x) > 1 for x in value_key_list)
        if has_duplicate_key:
            raise APIMandatoryFieldError(detail={'updateInfoList': 'Has duplicate updateKey'})

        # Check invalid updateKey
        if any(key not in CUSTOMER_UPDATE_KEY for key in value_key_list):
            response_data = {
                'responseCode': AccountUpdateResponseCode.INVALID_UPDATE_KEY.code,
                'responseMessage': AccountUpdateResponseCode.INVALID_UPDATE_KEY.message,
                'additionalInfo': {'errors': {'updateKey': 'Invalid updateKey format'}},
            }
            raise APIError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=response_data,
            )

        return value

    def validate(self, data: Dict) -> Dict:
        is_exists_dana_customer = DanaCustomerData.objects.filter(
            dana_customer_identifier=data['customerId'], lender_product_id=data['lenderProductId']
        ).exists()

        if not is_exists_dana_customer:
            error_message = (
                "Invalid lenderProductId, lenderProductId {} not found for customerId {}".format(
                    data['lenderProductId'], data['customerId']
                )
            )
            response_data = {
                'responseCode': AccountUpdateResponseCode.BAD_REQUEST.code,
                'responseMessage': AccountUpdateResponseCode.BAD_REQUEST.message,
                'additionalInfo': {'errors': {'lenderProductId': error_message}},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )

        return data


class DanaAccountInquirySerializer(serializers.Serializer):
    partnerReferenceNo = serializers.CharField(required=True)
    additionalInfo = serializers.DictField(required=False)

    def validate_partnerReferenceNo(self, value: str) -> str:
        if len(value) > 64:
            raise APIMandatoryFieldError(
                detail={
                    'partnerReferenceNo': 'Invalid partnerReferenceNo, partnerReferenceNo too long'
                },
            )

        return value


class DanaAccountInfoQuerySerializer(serializers.Serializer):
    queryType = serializers.CharField(required=True)
    queryTypeParam = serializers.DictField(required=False)

    ALLOWED_QUERY_TYPE = {
        DanaQueryTypeAccountInfo.CREDITOR_CHECK,
        DanaQueryTypeAccountInfo.DBR_ALLOWED,
        DanaQueryTypeAccountInfo.DBR_INSTALLMENT_CHECK,
    }

    def _validate_repayment_plan_list(self, repayment_plan):
        keys = {"principalAmount", "interestFeeAmount", "totalAmount"}
        for key in keys:
            if not isinstance(repayment_plan[key], dict) or not (
                "value" in repayment_plan[key].keys() and "currency" in repayment_plan[key].keys()
            ):
                error_message = "{}; {} objects doesn't have value or currency".format(
                    str(repayment_plan), key
                )
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {"errors": error_message},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            if not repayment_plan[key].get("value") or not repayment_plan[key].get("currency"):
                error_message = "{}; {} field may not be blank".format(str(repayment_plan), key)
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {"errors": error_message},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            try:
                float(repayment_plan[key].get("value"))
            except ValueError:
                error_message = "{}; {} value is not a number".format(str(repayment_plan), key)
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                    "additionalInfo": {"errors": error_message},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

        if not repayment_plan.get("dueDate"):
            error_message = "{}; dueDate is a mandatory field and may not be blank".format(
                str(repayment_plan)
            )
            response_data = {
                "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                "additionalInfo": {"errors": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        try:
            datetime.strptime(repayment_plan["dueDate"], "%Y%m%d")
        except ValueError:
            error_message = "{}; dueDate Format is not valid".format(str(repayment_plan))
            response_data = {
                "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                "additionalInfo": {"errors": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )

        if not repayment_plan.get("periodNo"):
            error_message = "{}; periodNo is a mandatory field and may not be blank".format(
                str(repayment_plan)
            )
            response_data = {
                "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                "additionalInfo": {"errors": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        try:
            float(repayment_plan.get("periodNo"))
        except ValueError:
            error_message = "{}; periodNo is not a number".format(str(repayment_plan))
            response_data = {
                "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                "additionalInfo": {"errors": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )

        return repayment_plan

    def validate(self, data: Dict) -> Dict:
        if data["queryType"] not in self.ALLOWED_QUERY_TYPE:
            response_data = {
                "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                "additionalInfo": {"errors": "queryType {} not allowed".format(data["queryType"])},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )

        if data["queryType"] == DanaQueryTypeAccountInfo.DBR_ALLOWED:
            query_type_param = data.get("queryTypeParam")
            if not query_type_param:
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {
                        "errors": "queryType {} need queryTypeParam".format(data["queryType"])
                    },
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            if not isinstance(query_type_param, dict):
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {"errors": "invalid queryTypeParam"},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            if 'repaymentPlanList' not in query_type_param:
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {"errors": "missing repaymentPlanList"},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            repayment_plans = query_type_param.get("repaymentPlanList")
            if not isinstance(repayment_plans, list) or not repayment_plans:
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                    "additionalInfo": {"errors": "repaymentPlanList is not a list"},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            for repayment_plan in repayment_plans:
                keys = {
                    "dueDate",
                    "principalAmount",
                    "interestFeeAmount",
                    "totalAmount",
                    "periodNo",
                }
                if not keys <= repayment_plan.keys():
                    response_data = {
                        "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                        "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                        "additionalInfo": {"errors": "repaymentPlanList have missings key"},
                    }
                    raise APIError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=response_data,
                    )

                self._validate_repayment_plan_list(repayment_plan)

        if data["queryType"] == DanaQueryTypeAccountInfo.DBR_INSTALLMENT_CHECK:
            query_type_param = data.get("queryTypeParam")
            if not query_type_param:
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {
                        "errors": "queryType {} need queryTypeParam".format(data["queryType"])
                    },
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            if not isinstance(query_type_param, dict):
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {"errors": "invalid queryTypeParam"},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            if 'installmentPlanList' not in query_type_param:
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                    "additionalInfo": {"errors": "missing installmentPlanList"},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            installment_plans = query_type_param.get("installmentPlanList")
            if not isinstance(installment_plans, list) or not installment_plans:
                response_data = {
                    "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                    "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                    "additionalInfo": {"errors": "installmentPlanList is not a list"},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )

            for installment_plan in installment_plans:
                if (
                    'repaymentPlanList' not in installment_plan
                    or 'installmentPlanId' not in installment_plan
                ):
                    response_data = {
                        "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                        "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                        "additionalInfo": {"errors": "missing keys in installmentPlanList"},
                    }
                    raise APIError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=response_data,
                    )

                if not installment_plan.get('installmentPlanId'):
                    response_data = {
                        "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                        "responseMessage": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message,
                        "additionalInfo": {
                            "errors": "installmentPlanId is required and cannot be empty"
                        },
                    }
                    raise APIError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=response_data,
                    )

                repayment_plans = installment_plan.get("repaymentPlanList")
                if not isinstance(repayment_plans, list) or not repayment_plans:
                    response_data = {
                        "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                        "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                        "additionalInfo": {
                            "errors": "repaymentPlanList in installmentPlan is not a list"
                        },
                    }
                    raise APIError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=response_data,
                    )

                for repayment_plan in repayment_plans:
                    keys = {
                        "dueDate",
                        "principalAmount",
                        "interestFeeAmount",
                        "totalAmount",
                        "periodNo",
                    }
                    if not keys <= repayment_plan.keys():
                        message = AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message
                        response_data = {
                            "responseCode": AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code,
                            "responseMessage": message,
                            "additionalInfo": {"errors": "repaymentPlanList have missing keys"},
                        }
                        raise APIError(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=response_data,
                        )

                    self._validate_repayment_plan_list(repayment_plan)
        return data


class DanaAccountInfoSerializer(serializers.Serializer):
    customerId = serializers.CharField(required=True)
    lenderProductId = serializers.CharField(required=True)
    queryInfoParamList = serializers.ListField(
        child=DanaAccountInfoQuerySerializer(), allow_empty=True
    )
    additionalInfo = serializers.DictField(required=False)

    def validate_queryInfoParamList(self, value: list) -> list:
        if not isinstance(value, list) or not value:
            response_data = {
                "responseCode": AccountInfoResponseCode.INVALID_FIELD_FORMAT.code,
                "responseMessage": AccountInfoResponseCode.INVALID_FIELD_FORMAT.message,
                "additionalInfo": {"errors": "queryInfoParamList is not a list"},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value
