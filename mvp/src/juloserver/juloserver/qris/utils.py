import time
import uuid


def get_timestamp():
    return int(time.time())


def is_uuid_valid(value: str, version=4) -> bool:
    try:
        uuid.UUID(value, version=version)
    except ValueError:
        return False

    return True
