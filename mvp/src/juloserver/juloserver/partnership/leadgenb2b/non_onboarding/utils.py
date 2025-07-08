from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.partnership.leadgenb2b.non_onboarding.constants import PaymentStatusLSP

j1_partnership_message_mapping_dict = {
    "User not allowed": "Akses user tidak diijinkan",
    "Bank account does not belong to you": "Akun bank bukan milik Anda",
}


def mapping_message(message, message_mapping):
    def find_mapping(text, mapping):
        # Convert text to lowercase for case-insensitive matching
        lower_text = text.lower()
        for original_message, mapped_message in mapping.items():
            # Convert original_message to lowercase for case-insensitive matching
            if original_message.lower() in lower_text:
                return mapped_message
        return text

    if isinstance(message, list):
        # If message is a list, process each element
        mapped_items = [mapping_message(item, message_mapping) for item in message]
        # Join all mapped items into a single string
        return ' '.join(item if isinstance(item, str) else ' '.join(item) for item in mapped_items)
    elif isinstance(message, str):
        # If message is a string, translate it
        return find_mapping(message, message_mapping)
    return message


def rename_request_keys(request_data, mapping):
    for new_key, old_key in mapping.items():
        if old_key in request_data:
            request_data[new_key] = request_data.pop(old_key)
        else:
            continue


def mapping_status_payment(payment_status_code):
    payment_status = ""

    if payment_status_code <= PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS:
        payment_status = PaymentStatusLSP.NOT_DUE
    elif (
        PaymentStatusCodes.PAID_ON_TIME
        > payment_status_code
        > PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS
    ):
        payment_status = PaymentStatusLSP.LATE
    elif payment_status_code == PaymentStatusCodes.PAID_ON_TIME:
        payment_status = PaymentStatusLSP.PAID_ON_TIME
    elif payment_status_code >= PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD:
        payment_status = PaymentStatusLSP.PAID_LATE

    return payment_status
