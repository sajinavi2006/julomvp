class RedisKeyPrefix:
    SCAN_FRAUD_HOTSPOT_VELOCITY_MODEL = 'fraud_security::scan_fraud_hotspot_velocity_model'


class FraudFlagType:
    ATO_DEVICE_CHANGE = 'ato_device_change'
    CHANGE_PHONE_ACTIVITY = 'change_phone_activity'


class FraudFlagSource:
    ANDROID = 'android_id'
    LOAN = 'loan_id'
    CUSTOMER = 'customer_id'


class FraudFlagTrigger:
    LOGIN_SUCCESS = 'login_success'
    LOAN_CREATION = 'loan_creation'
    CHANGE_PHONE_ACTIVITY = 'change_phone_activity'


class FraudBucket:
    VELOCITY_MODEL_GEOHASH = 'Velocity Model Geohash'


class FraudChangeReason:
    VELOCITY_MODEL_GEOHASH_FRAUD = 'Flag as fraud hotspot velocity model'
    VELOCITY_MODEL_GEOHASH_NOT_FRAUD = 'Success velocity model geohash verification'
    SELFIE_IN_GEOHASH_SUSPICIOUS = "Selfie in Geohash Suspicious"
    BANK_NAME_VELOCITY = "bank_name_velocity"
    BANK_NAME_VELOCITY_NO_FRAUD = "Bank Name Velocity No Fraud"
    RISKY_PHONE_AND_EMAIL_NO_FRAUD = "Risky Phone and Email No Fraud"
    PASS_SELFIE_GEOHASH = "Pass Selfie Geohash"
    ANTI_FRAUD_API_UNAVAILABLE = "anti_fraud_api_unavailable"
    RISKY_LOCATION_NO_FRAUD = "Risky Location No Fraud"
    RISKY_LOCATION_FRAUD = "Risky Location Fraud"
    PROMPTED_BY_THE_ANTI_FRAUD_API = "Prompted by the Anti Fraud API"


class FraudApplicationBucketType:
    VELOCITY_MODEL_GEOHASH = 'velocity_model_geohash'
    SELFIE_IN_GEOHASH = 'selfie_in_geohash'
    BANK_NAME_VELOCITY = 'bank_name_velocity'
    RISKY_PHONE_AND_EMAIL = 'risky_phone_and_email'
    RISKY_LOCATION = 'risky_location'

    @classmethod
    def label(cls, bucket_type):
        label_map = {
            cls.VELOCITY_MODEL_GEOHASH: "115: Velocity - Geohash",
            cls.SELFIE_IN_GEOHASH: "115: Selfie in Geohash",
            cls.BANK_NAME_VELOCITY: "115: Bank Name Velocity",
            cls.RISKY_PHONE_AND_EMAIL: "115: Risky Phone and Email",
            cls.RISKY_LOCATION: "115: Risky Location",
        }
        return label_map.get(bucket_type, bucket_type)

    @classmethod
    def all_types(cls):
        return {
            value
            for field_name, value in vars(cls).items()
            if (not field_name.startswith('_') and not callable(value) and isinstance(value, str))
        }


class SwiftLimitDrainerConditionValues:
    ACCOUNT_SET_LIMIT = 5000000
    FIRST_LOAN_AMOUNT = 4000000


class DeviceConst:
    JULO_DEVICE_ID = "julo_device_id"


class FraudBlockAccountConst:
    APPLICATION = 'application'
    FRAUD_BLOCK_ACCOUNT = 'fraud_block_account'
