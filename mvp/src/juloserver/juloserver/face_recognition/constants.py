from enum import Enum


class ImageType:
    SELFIE = 'selfie'
    CROP_SELFIE = 'crop_selfie'
    KTP_SELF = 'ktp_self'
    ACTIVE_LIVENESS_TOP_LEFT = 'active_liveness_TOP_LEFT'
    SELFIE_CHECK_LIVENESS = 'selfie_check_liveness'


class FaceMatchingCheckConst:
    class FeatureSetting:
        parameter_liveness_x_ktp = 'liveness_x_ktp'
        parameter_liveness_x_selfie = 'liveness_x_selfie'
        parameter_selfie_x_ktp = 'selfie_x_ktp'
        parameter_selfie_x_liveness = 'selfie_x_liveness'

    class Process(Enum):
        liveness_x_ktp = 1
        liveness_x_selfie = 2
        selfie_x_ktp = 3
        selfie_x_liveness = 4

        @property
        def string_val(self):
            if self == self.liveness_x_ktp:
                return 'liveness_to_ktp'
            elif self == self.liveness_x_selfie:
                return 'liveness_to_selfie'
            elif self == self.selfie_x_ktp:
                return 'selfie_to_ktp'
            elif self == self.selfie_x_liveness:
                return 'selfie_to_liveness'
            else:
                return None

    class Status(Enum):
        in_progress = 0
        not_passed = 1
        passed = 2
        skipped = 3
        not_triggered = 4

        def _missing_(self, val):
            return self.in_progress


class StoreFraudFaceConst:
    class FeatureSetting:
        parameter_x440_change_reasons = 'x440_change_reasons'


class FaceSearchProcessConst:
    NOT_FOUND = 'not_found'


class FraudFaceSearchProcessConst:
    NOT_FOUND = 'not_found'
