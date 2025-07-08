import math
from builtins import str
from datetime import timezone, datetime, tzinfo
from random import randrange

from juloserver.utilities.constants import CommonVariables


def get_valid_int(value):
    try:
        return int(value)
    except Exception as e:
        return None


def validate_rule_code(criterion):
    result = False
    group_test = criterion.split(":")
    group_test_len = len(group_test)
    if group_test_len in [2, 3]:
        if (
            group_test_len == 2
            and group_test[0] in CommonVariables.NON_POSITIONAL_CONDITION
        ):
            result = True
        elif (
            group_test_len == 3
            and group_test[0] in CommonVariables.POSITIONAL_CONDITION
            and get_valid_int(group_test[1]) is not None
        ):
            result = True
    return result


def condition_str(condition):
    con_str = {
        "#lte": "<=",
        "#gte": ">=",
        "#lt": "<",
        "#gt": ">",
        "#eq": "==",
        "#nthlte": "<=",
        "#nthgte": ">=",
        "#nthlt": "<",
        "#nthgt": ">",
        "#ntheq": "==",
    }
    return con_str[condition]


def eval_or_none(eval_str):
    try:
        return eval(eval_str)
    except Exception:
        return None


def get_result_from_condition_string(condition_str):
    try:
        return eval(condition_str)
    except Exception:
        return None


def get_position_or_none(val_str, position):
    try:
        return str(val_str)[position]
    except Exception:
        return None


def validate_condition_str(condition_str, count):
    try:
        condition_str = condition_str.replace("count", count)
        return get_result_from_condition_string(condition_str)
    except Exception:
        return None


def get_rule_db_key_value(rule_key, data_obj):
    if rule_key == "application_id":
        return data_obj.id
    elif rule_key == "application_xid":
        return data_obj.application_xid
    elif rule_key == "customer_id":
        return data_obj.customer.id
    return None


def rule_satisfied(criterion, rule_key, data_obj):
    """
    Checks whether the given data matches with the rule

    Parameters:
    criterion (string): Criteria or condition in string eg: #eq, #lte erc..
    rule_key (string): column names from the Django Model
    data_obj (Model): Django Model

    Returns:
    boolean: True of False

    Sample Conditions:
        1: #nthgte:-1:6
        2: #nth:-2:0,1,2,3,4,5,6
        3: #eq:500
    """

    group_test = criterion.split(":")
    rule_key_value = get_rule_db_key_value(rule_key, data_obj)
    result = False
    if rule_key_value is not None:
        if group_test[0] in CommonVariables.POSITIONAL_CONDITION:
            position = get_valid_int(group_test[1])
            rule_key_value_slice = get_position_or_none(rule_key_value, position)
            if position is not None and rule_key_value_slice is not None:
                input_blocks = group_test[2].split(",")
                if group_test[0] == "#nth":
                    result = rule_key_value_slice in input_blocks
                elif group_test[0] in CommonVariables.POSITIONAL_CONDITION:
                    condition = condition_str(group_test[0])
                    eval_res = eval_or_none(
                        "%s %s %s" % (rule_key_value_slice, condition, group_test[2])
                    )
                    result = eval_res if eval_res is not None else False
        elif group_test[0] in CommonVariables.NON_POSITIONAL_CONDITION:
            condition = condition_str(group_test[0])
            eval_res = eval_or_none(
                "%s %s %s" % (rule_key_value, condition, group_test[1])
            )
            result = eval_res if eval_res is not None else False

    return result


def get_bucket_emotion(bucket, count, slack_ewa_items):
    result = None
    if bucket and bucket.slack_ewa_emoji:
        for emotion in bucket.slack_ewa_emoji.all():
            if emotion.condition:
                condition_res = validate_condition_str(emotion.condition, str(count))
                if condition_res == True:
                    result = emotion.emoji
                    break
    return result


def get_bucket_slack_user(bucket, count, slack_ewa_items):
    user_ids = []
    if bucket and bucket.slack_ewa_tag:
        for tag in bucket.slack_ewa_tag.all():
            if tag.condition:
                condition_res = validate_condition_str(tag.condition, str(count))
                if condition_res == True:
                    user_ids = [
                        (user.slack_id if user.slack_id else None)
                        for user in tag.slack_user.all()
                    ]
                    return user_ids
    return user_ids


def gen_probability(param_dict):
    """generate probability follow by input prob
    Ex: param_dict = {'bca':50, 'new_xer':40, 'new_bca':10}
    """
    if not param_dict:
        return None
    total = sum(param_dict.values())
    start_point = 1

    roll_value = randrange(start_point, total+1)
    for key, value in list(param_dict.items()):
        if start_point <= roll_value < start_point+value:
            return key
        start_point = start_point+value
    return None
    

def get_holdout_variables(percentage, total_request):
    list_requests = list(range(1, total_request + 1))
    percentage_multiplier = percentage / 100
    total_right = math.floor(percentage_multiplier * total_request)
    total_left = total_request - total_right
    list_left = list_requests[:total_left]
    if total_right == 0:
        list_right = list_requests[:0]
    else:
        list_right = list_requests[-total_right:]
    return {
        'list_left': list_left,
        'list_right': list_right,
        'list_requests': list_requests,
        'percentage_multiplier': percentage_multiplier,
        'total_left': total_left,
        'total_right': total_right,
        'total_request': total_request,
    }

class HoldoutManager:

    def __init__(self, percentage, total_request, key):
        self.percentage = percentage
        self.total_request = total_request
        self.key = key
        self.cache = self._get_cache_driver()
        self.variables = self._construct_variables()
        self.counter = self.cache.get(self.key)

    def __enter__(self):
        if self.counter is None:
            self.counter = 1

            self.cache.set(self.key, self.counter, timeout=None)

        return self

    def __exit__(self, *args):
        if self.counter >= self.total_request:
            self.cache.set(self.key, 1, timeout=None)
        else:
            self.cache.incr(self.key)

    def _get_cache_driver(self):
        from juloserver.julocore.cache_client import get_redis_cache
        return get_redis_cache()

    def _construct_variables(self):
        list_requests = list(range(1, self.total_request + 1))
        percentage_multiplier = self.percentage / 100
        total_right = math.floor(percentage_multiplier * self.total_request)
        total_left = self.total_request - total_right
        list_left = list_requests[:total_left]
        if total_right == 0:
            list_right = list_requests[:0]
        else:
            list_right = list_requests[-total_right:]

        return {
            'list_left': list_left,
            'list_right': list_right,
            'list_requests': list_requests,
            'percentage_multiplier': percentage_multiplier,
            'total_left': total_left,
            'total_right': total_right,
            'total_request': self.total_request,
        }

    @property
    def list_left(self):
        return self.variables["list_left"]


    @property
    def list_right(self):
        return self.variables["list_right"]


def datetime_exists(dt):
    """Check if a datetime exists. Taken from: https://pytz-deprecation-shim.readthedocs.io/en/latest/migration.html"""
    # There are no non-existent times in UTC, and comparisons between
    # aware time zones always compare absolute times; if a datetime is
    # not equal to the same datetime represented in UTC, it is imaginary.
    return dt.astimezone(timezone.utc) == dt


def datetime_ambiguous(dt: datetime):
    """Check whether a datetime is ambiguous. Taken from: https://pytz-deprecation-shim.readthedocs.io/en/latest/migration.html"""
    # If a datetime exists and its UTC offset changes in response to
    # changing `fold`, it is ambiguous in the zone specified.
    return datetime_exists(dt) and (dt.replace(fold=not dt.fold).utcoffset() != dt.utcoffset())


def valid_datetime(dt):
    """Returns True if the datetime is not ambiguous or imaginary, False otherwise."""
    if isinstance(dt.tzinfo, tzinfo) and not datetime_ambiguous(dt):
        return True
    return False
