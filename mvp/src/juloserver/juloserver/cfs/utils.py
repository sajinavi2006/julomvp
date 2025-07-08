def convert_size_unit(bytes: int, to_unit: str, b_size=1024) -> str:
    """
    Convert B to KB, MB, GB, TB
    """
    exponential = {
        "KB": 1,
        "MB": 2,
        "GB": 3,
        "TB": 4
    }
    if to_unit not in exponential:
        raise ValueError("Invalid converted unit")
    return f"{round(bytes / (b_size ** exponential[to_unit]), 1)} {to_unit}"
