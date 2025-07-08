def format_otpless_phone_number(phone_number):
    """
    This is specific for formatting phone number to start with 62
    This is required for OTPLess integration by the time this utils is created
    """
    phone_number = phone_number.lstrip('+').lstrip('0')
    if not phone_number.startswith('62'):
        phone_number = '62' + phone_number

    return phone_number
