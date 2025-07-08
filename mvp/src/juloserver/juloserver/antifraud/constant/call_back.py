from enum import Enum


class CallBackType(Enum):
    MOVE_APPLICATION_STATUS = "move_application_status"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(self, val):
        return self.UNKNOWN
