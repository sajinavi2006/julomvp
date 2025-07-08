from dataclasses import dataclass


@dataclass
class MonnaiRequestLogData:
    reference_id: str = ''
    packages: str = ''
    application_id: int = 0
    has_device_info: bool = False
    has_device_location: bool = False
    raw_response: str = ''
