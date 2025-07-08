def mask_phone_number_preserve_last_four_digits(value: str):
    if not value or len(value) < 4:
        return value

    last_four_digits = value[-4:]
    masked_string = '*' * (len(value) - 4) + last_four_digits
    return masked_string
