class Parameter:
    SEGMENTATION_REGEX = "segmentation_regex"
    N_PER_BATCH = "n_per_batch"
    OSS_TTL_SECONDS = "oss_ttl_seconds"
    EXCLUDE_COMMS = "exclude_comms"
    INCLUDE_BATCH = 'include_batch'


class CommsType:
    EMAIL = "email"
    SMS = "sms"
    ONE_WAY_ROBOCALL = "one-way-robocall"
    PDS = "pds"
    TWO_WAY_ROBOCALL = 'two-way-robocall'
    PN = "pn"
