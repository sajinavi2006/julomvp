from juloserver.julo.models import Customer


def transform_error_msg(msgs, exclude_key=False, strict_mode=False):
    result = []
    for key, value in list(msgs.items()):
        prefix = key + ' '
        if exclude_key:
            prefix = ''

        if strict_mode:
            if value[0] is not None:
                result.append(prefix + value[0])
        else:
            result.append(prefix + value[0])

    return result


def format_error_messages_for_required(message):
    messages = {
        "blank": message,
        "null": message,
        "required": message,
    }
    return messages


def check_lat_and_long_is_valid(lat, lon):
    try:
        float(lat)  # for int, long and float
        float(lon)  # for int, long and float
    except ValueError:
        return False

    return True


def get_first_name(customer: Customer) -> str:
    """
    Fetch first name of a customer based on Customer.fullname or Application.fullname
    else return 'pelanggan setia JULO'.

    Args:
        customer (Customer): Customer model object.

    Returns:
        default_str (str): First name of the Customer or 'pelanggan setia JULO' as default.

    """
    default_str = 'Pelanggan setia JULO'

    if not customer:
        return default_str

    try:
        if customer.fullname:
            return customer.fullname.split()[0]

        application = customer.application_set.last()

        if not application:
            return default_str

        if application.fullname:
            return application.fullname.split()[0]
    except IndexError:
        pass

    return default_str
