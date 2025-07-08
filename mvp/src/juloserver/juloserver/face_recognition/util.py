import re
from typing import Any


def is_2xx_status(
    value: Any,
) -> bool:
    pattern = r'^2\d{2,3}$'
    return bool(re.match(pattern, str(value)))
