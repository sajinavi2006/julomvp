

def mask_value_showing_length_and_last_four_value(
    value: str,
) -> str:
    if not value or len(value) < 4:
        return value

    last_four_digits = value[-4:]
    masked_string = '*' * (len(value) - 4) + last_four_digits
    return masked_string


def mask_email_showing_length(
    email: str,
):
    username, domain = email.split('@', 1)
    if not username or len(username) < 2:
        return email

    masked_username = username[0] + '*' * (len(username) - 2) + username[len(username) - 1]
    masked_email = masked_username + '@' + domain
    return masked_email
