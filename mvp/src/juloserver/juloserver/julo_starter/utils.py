def custom_message_error_serializer(message, non_prefix=False):

    if non_prefix:
        return {
            "blank": str(message),
            "null": str(message),
            "required": str(message),
            "invalid": str(message),
        }

    messages = {
        "blank": str(message + " harus diisi"),
        "null": str(message + " harus diisi"),
        "required": str(message + " harus diisi"),
        "invalid": str(message + " tidak valid"),
    }
    return messages
