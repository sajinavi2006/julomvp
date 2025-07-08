import copy
from dataclasses import (
    dataclass,
    field,
    fields,
    is_dataclass,
)
from datetime import (
    date,
    datetime,
)
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from typing import (
    List,
    get_type_hints,
)
from juloserver.julocore.data.models import TimeStampedModel
from django.db import models
from numpy import int64
from juloserver.omnichannel.services.settings import (
    OmnichannelIntegrationSetting,
)
import math


class _UndefinedValueType:
    def __repr__(self):
        return ""

    def __deepcopy__(self, memodict):
        return self


UndefinedValue = _UndefinedValueType()


def _asdict(obj, is_json_compatible=False) -> dict:
    """
    This is duplicated function from dataclasses.asdict() to skip value with _UndefinedValue.
    Args:
        obj (object): The dataclass object that requires conversion to a dictionary.
    Returns:
        dict: A dictionary representation of the input dataclass object.
    """
    if not is_dataclass(obj):
        raise TypeError("asdict() should be called on dataclass instances")
    return _asdict_inner(obj, is_json_compatible)


def _asdict_inner(obj, is_json_compatible):
    """
    This is duplicated function from dataclasses._asdict_inner() with the following modifications:
    - skip value with _UndefinedValue.
    - convert date and datetime to string.

    Args:
        obj (object): The dataclass object that requires conversion to a dictionary.

    Raises:
        TypeError: If the input is not a valid dataclass instance.
    """
    dict_factory = dict
    if is_dataclass(obj):
        result = []
        for f in fields(obj):
            value = _asdict_inner(getattr(obj, f.name), is_json_compatible)
            if value != UndefinedValue:
                result.append((f.name, value))
        return dict_factory(result)
    elif isinstance(obj, tuple) and hasattr(obj, '_fields'):
        return type(obj)(*[_asdict_inner(v, is_json_compatible) for v in obj])
    elif isinstance(obj, (list, tuple)):
        return type(obj)(_asdict_inner(v, is_json_compatible) for v in obj)
    elif isinstance(obj, dict):
        return type(obj)(
            (_asdict_inner(k, is_json_compatible), _asdict_inner(v, is_json_compatible))
            for k, v in obj.items()
        )
    elif obj == UndefinedValue:
        return obj
    elif is_json_compatible:
        if isinstance(obj, date) or isinstance(obj, datetime):
            return str(obj)
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, int64):
            return int(obj)
        elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
    return copy.deepcopy(obj)


OMNICHANNEL_TYPE_MAP = {
    str: "string",
    int: "integer",
    int64: "long",
    float: "double",
    bool: "boolean",
    date: "date",
    datetime: "datetime",
}

# for non-built-in types,
# if the type cannot be JSONSerializable, Please update `_asdict_inner`
# on `is_json_compatible` section
SIMILAR_TYPE_HINT_MAP = {
    int: [int, int64],
    int64: [int, int64],
    str: [
        int,
        int64,
        str,
        float,
        Decimal,
    ],
    float: [
        float,
        Decimal,
    ],
}


class _BaseTypeMixin:
    """
    Base class for all dataclasses in this module.
    Beware that the attribute assignment is type-checked.
    Therefore, the performance might be affected.
    """

    def __setattr__(self, key, value):
        """
        Make sure the value is of the expected type.
        """
        expected_type = get_type_hints(self.__class__).get(key)
        if expected_type is not None:
            if isinstance(value, list):
                return super().__setattr__(key, value)

            if (
                expected_type in SIMILAR_TYPE_HINT_MAP
                and type(value) in SIMILAR_TYPE_HINT_MAP[expected_type]
            ):
                return super().__setattr__(key, value)

            if (
                value != UndefinedValue
                and value is not None
                and not isinstance(value, expected_type)
            ):
                raise TypeError(
                    f'Attribute {key} should be of type "{expected_type.__name__}", '
                    f'not "{type(value).__name__}"'
                )

        return super().__setattr__(key, value)

    def to_json_dict(self):
        result = _asdict(self, is_json_compatible=True)
        return result

    def to_dict(self):
        result = _asdict(self)
        return result

    @classmethod
    def omnichannel_data_types(cls):
        types = get_type_hints(cls)
        data_types = []
        for key, value in types.items():
            data_types.append(cls._convert_to_omnichannel_data_type(key, value))
        return data_types

    @staticmethod
    def _convert_to_omnichannel_data_type(field_name, field_type):
        if field_type in OMNICHANNEL_TYPE_MAP:
            return {
                "name": field_name,
                "type": OMNICHANNEL_TYPE_MAP[field_type],
            }
        elif is_dataclass(field_type):
            return {
                "name": field_name,
                "type": "object",
                "fields": field_type.omnichannel_data_types(),
            }
        elif hasattr(field_type, "__args__") and len(field_type.__args__) == 1:
            item_data_type = field_type.__args__[0]
            return {
                "name": field_name,
                "type": "object",
                "fields": item_data_type.omnichannel_data_types(),
            }

        raise ValueError(f"Unsupported type: {field_type}")


@dataclass
class AccountPaymentAttribute(_BaseTypeMixin):
    account_payment_id: int64
    account_payment_xid: str
    account_id: int64
    due_date: date
    due_amount: int
    late_fee_amount: int
    interest_amount: int
    principal_amount: int
    paid_amount: int
    paid_late_fee_amount: int
    paid_interest_amount: int
    paid_principal_amount: int
    paid_date: date
    ptp_date: date
    status_code: int
    ptp_amount: int
    ptp_robocall_phone_number: str
    is_restructured: bool
    autodebet_retry_count: int
    is_collection_called: bool
    is_ptp_robocall_active: bool
    is_reminder_called: bool
    is_success_robocall: bool
    is_robocall_active: bool
    paid_during_refinancing: bool
    late_fee_applied: int
    is_paid_within_dpd_1to10: bool
    potential_cashback: int
    month_due_date: str
    year_due_date: str
    due_date_long: str
    due_date_short: str
    sms_payment_details_url: str
    formatted_due_amount: str
    sort_order: float
    short_ptp_date: str = field(default=UndefinedValue)
    sms_month: int = field(default=UndefinedValue)
    is_risky: bool = field(default=UndefinedValue)


@dataclass
class CustomerAttribute(_BaseTypeMixin):
    customer_id: int64 = field(default=UndefinedValue)
    customer_xid: str = field(default=UndefinedValue)
    mobile_phone: str = field(default=UndefinedValue)
    email: str = field(default=UndefinedValue)
    timezone_offset: int = field(default=UndefinedValue)
    fcm_reg_id: str = field(default=UndefinedValue)
    source: str = field(default=UndefinedValue)

    # Customer Attribute
    application_id: int64 = field(default=UndefinedValue)
    account_id: int64 = field(default=UndefinedValue)
    application_status_code: int = field(default=UndefinedValue)
    mobile_phone_2: str = field(default=UndefinedValue)
    gender: str = field(default=UndefinedValue)
    full_name: str = field(default=UndefinedValue)
    first_name: str = field(default=UndefinedValue)
    last_name: str = field(default=UndefinedValue)
    title: str = field(default=UndefinedValue)
    title_long: str = field(default=UndefinedValue)
    name_with_title: str = field(default=UndefinedValue)
    company_name: str = field(default=UndefinedValue)
    company_phone_number: str = field(default=UndefinedValue)
    position_employees: str = field(default=UndefinedValue)
    spouse_name: str = field(default=UndefinedValue)
    kin_name: str = field(default=UndefinedValue)
    kin_relationship: str = field(default=UndefinedValue)
    spouse_mobile_phone: str = field(default=UndefinedValue)
    kin_mobile_phone: str = field(default=UndefinedValue)
    address_full: str = field(default=UndefinedValue)
    city: str = field(default=UndefinedValue)
    zip_code: str = field(default=UndefinedValue)
    dob: date = field(default=UndefinedValue)
    age: int = field(default=UndefinedValue)
    payday: int = field(default=UndefinedValue)
    loan_purpose: str = field(default=UndefinedValue)
    product_line_code: str = field(default=UndefinedValue)
    product_line_name: str = field(default=UndefinedValue)
    is_j1_customer: bool = field(default=UndefinedValue)
    collection_segment: str = field(default=UndefinedValue)
    customer_bucket_type: str = field(default=UndefinedValue)
    cashback_new_scheme_experiment_group: bool = field(default=UndefinedValue)
    application_similarity_score: float = field(default=UndefinedValue)
    credit_score: str = field(default=UndefinedValue)
    shopee_score_status: str = field(default=UndefinedValue)
    shopee_score_list_type: str = field(default=UndefinedValue)
    active_liveness_score: float = field(default=UndefinedValue)
    passive_liveness_score: float = field(default=UndefinedValue)
    heimdall_score: float = field(default=UndefinedValue)
    orion_score: float = field(default=UndefinedValue)
    total_cashback_earned: int = field(default=UndefinedValue)
    cashback_amount: int = field(default=UndefinedValue)
    cashback_counter: int = field(default=UndefinedValue)
    cashback_due_date: date = field(default=UndefinedValue)
    cashback_due_date_slash: str = field(default=UndefinedValue)
    uninstall_indicator: str = field(default=UndefinedValue)
    fdc_risky: bool = field(default=UndefinedValue)
    google_calendar_url: str = field(default=UndefinedValue)
    is_autodebet: bool = field(default=UndefinedValue)
    autodebet_vendor: str = field(default=UndefinedValue)
    sms_primary_va_name: str = field(default=UndefinedValue)
    sms_primary_va_number: str = field(default=UndefinedValue)
    sms_firstname: str = field(default=UndefinedValue)
    fpgw: float = field(default=UndefinedValue)
    mycroft_score: float = field(default=UndefinedValue)
    va_number: str = field(default=UndefinedValue)
    va_method_name: str = field(default=UndefinedValue)
    va_bca: str = field(default=UndefinedValue)
    va_maybank: str = field(default=UndefinedValue)
    va_permata: str = field(default=UndefinedValue)
    va_alfamart: str = field(default=UndefinedValue)
    va_mandiri: str = field(default=UndefinedValue)
    va_indomaret: str = field(default=UndefinedValue)
    bank_code: str = field(default=UndefinedValue)
    bank_code_text: str = field(default=UndefinedValue)
    bank_name: str = field(default=UndefinedValue)
    total_loan_amount: int = field(default=UndefinedValue)

    # Partner info
    partner_id: int = field(default=UndefinedValue)
    partner_name: str = field(default=UndefinedValue)

    # Refinancing
    refinancing_prerequisite_amount: int = field(default=UndefinedValue)
    refinancing_status: str = field(default=UndefinedValue)
    refinancing_expire_date: date = field(default=UndefinedValue)

    # Account Payment
    last_call_agent: str = field(default=UndefinedValue)
    last_call_status: str = field(default=UndefinedValue)
    is_risky: bool = field(default=UndefinedValue)
    is_email_blocked: bool = field(default=UndefinedValue)
    is_sms_blocked: bool = field(default=UndefinedValue)
    is_one_way_robocall_blocked: bool = field(default=UndefinedValue)
    is_two_way_robocall_blocked: bool = field(default=UndefinedValue)
    is_pn_blocked: bool = field(default=UndefinedValue)
    account_payment: List[AccountPaymentAttribute] = field(default=UndefinedValue)

    # Exclusion
    is_customer_julo_gold: bool = field(default=UndefinedValue)

    # Filter
    rollout_channels: List[str] = field(default=UndefinedValue)

    # collection experiment
    coll_experiment_sms_reminder_omnichannel_experiment_group: str = field(default=UndefinedValue)

    # PDS Exclusion
    dialer_blacklisted_permanent: bool = field(default=UndefinedValue)
    dialer_blacklisted_expiry_date: date = field(default=UndefinedValue)

    installment_number: int = field(default=UndefinedValue)
    last_pay_date: date = field(default=UndefinedValue)
    last_pay_amount: int = field(default=UndefinedValue)
    program_expiry_date: date = field(default=UndefinedValue)
    customer_bucket_type: str = field(default=UndefinedValue)
    promo_for_customer: str = field(default=UndefinedValue)
    installment_due_amount: int = field(default=UndefinedValue)
    other_refinancing_status: str = field(default=UndefinedValue)
    activation_amount: int = field(default=UndefinedValue)
    is_collection_field_blacklisted: bool = field(default=UndefinedValue)

    # Repayment
    odin_score: float = field(default=UndefinedValue)


@dataclass
class OmnichannelCustomer(_BaseTypeMixin):
    customer_id: str
    updated_at: datetime = field(default_factory=datetime.now)
    customer_attribute: CustomerAttribute = field(default_factory=CustomerAttribute)

    def to_json_dict(self):
        result = super(OmnichannelCustomer, self).to_json_dict()
        result['updated_at'] = int(self.updated_at.timestamp())
        return result


class OmnichannelCustomerSync(TimeStampedModel):
    id = models.AutoField(db_column='omnichannel_customer_sync_id', primary_key=True)
    customer_id = models.BigIntegerField(unique=True)
    account_id = models.BigIntegerField(blank=True, null=True)
    is_rollout_pds = models.BooleanField(default=False, db_index=True)
    is_rollout_pn = models.BooleanField(default=False, db_index=True)
    is_rollout_sms = models.BooleanField(default=False, db_index=True)
    is_rollout_email = models.BooleanField(default=False, db_index=True)
    is_rollout_one_way_robocall = models.BooleanField(default=False, db_index=True)
    is_rollout_two_way_robocall = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = 'omnichannel_customer_sync'


class OmnichannelExclusionCommsBlock(object):
    is_excluded: bool
    is_full_rollout: bool
    comm_type: OmnichannelIntegrationSetting.CommsType

    def __init__(
        self,
        is_excluded: bool = False,
        is_full_rollout: bool = False,
        comm_type: OmnichannelIntegrationSetting.CommsType = None,
    ):
        self.is_excluded = is_excluded
        self.is_full_rollout = is_full_rollout
        self.comm_type = comm_type


@dataclass
class OmnichannelCustomerSyncBulkProcessHistory:
    task_id: str = ''
    status: str = ''
    action_by: str = ''
    started_at: str = ''
    completed_at: str = ''
    processed_num: int = 0
    total: int = 0
    success_num: int = 0
    fail_num: int = 0
    percentage: str = '0%'
    parameters: str = ''
    report_thread: str = ''

    def to_dict_partial(self, exclude_cols):
        result = _asdict(self)
        for num in exclude_cols:
            result.pop(num)
        return result

    def to_dict(self):
        result = _asdict(self)
        return result

    @staticmethod
    def label_to_key():
        res = {}
        for k in OmnichannelCustomerSyncBulkProcessHistory.__annotations__.keys():
            res.update({k.replace('_', ' ').title(): k})
        return res


@dataclass
class EventAttribute(_BaseTypeMixin):
    pass


@dataclass
class OmnichannelEventTrigger(_BaseTypeMixin):
    event_type: str
    customer_id: str
    source: str = field(default_factory=lambda: settings.SERVICE_DOMAIN)
    event_at: datetime = field(default_factory=lambda: timezone.now())
    event_attribute: EventAttribute = field(default_factory=EventAttribute)
    customer_attribute: CustomerAttribute = field(default_factory=CustomerAttribute)

    def to_json_dict(self):
        # Convert event_at to ISO_8601 string.
        result = _asdict(self, is_json_compatible=True)
        result['event_at'] = timezone.localtime(self.event_at).isoformat(timespec='seconds')

        return result


@dataclass
class OmnichannelPDSActionLogTask(_BaseTypeMixin):
    skiptrace_history_id: int
    contact_source: str = field(default=UndefinedValue)
    task_name: str = field(default=UndefinedValue)


@dataclass
class OmnichannelPDSActionLog(_BaseTypeMixin):
    customer_id: str
    action: str
    metadata: dict
