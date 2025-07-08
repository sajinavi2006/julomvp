class FeatureNameConst:
    SALES_OPS_PDS = 'sales_ops_pds'
    SALES_OPS_AI_RUDDER_TASKS_STRATEGY_CONFIG = 'sales_ops_ai_rudder_tasks_strategy_config'
    SALES_OPS_PDS_ALERT = 'sales_ops_pds_alert'
    SALES_OPS_CALL_RESULT_FORMAT = 'sales_ops_call_result_format'


class SalesOpsPDSConst:
    class SalesOpsPDSSetting:
        # Task configurations
        START_TIME = 'start_time'
        AUTO_END_TIME = 'auto_end_time'
        REST_TIMES = 'rest_times'
        AUTO_SLOT_FACTOR = 'auto_slot_factor'
        MAX_LOST_RATE = 'max_lost_rate'
        RING_LIMIT = 'ring_limit'

        # Task strategy
        DIALING_MODE = 'dialing_mode'
        DIALING_ORDER = 'dialing_order'
        ACW_TIME = 'acw_time'

        # Redialing strategy
        REPEAT_TIMES = 'repeat_times'
        BULK_CALL_INTERVAL = 'bulk_call_interval'

        # Voicemail strategy
        VOICEMAIL_CHECK = 'voicemail_check'
        VOICEMAIL_CHECK_DURATION = 'voicemail_check_duration'
        VOICEMAIL_HANDLE = 'voicemail_handle'


    class SalesOpsPDSSettingDefault:
        # Task configurations
        START_TIME = '8:00'
        AUTO_END_TIME = '18:00'
        REST_TIMES = [['12:00', '13:00']]
        AUTO_SLOT_FACTOR = '0'
        MAX_LOST_RATE = '0.0'
        RING_LIMIT = '0'

        # Task strategy
        DIALING_MODE = '0'
        DIALING_ORDER = []
        ACW_TIME = '10'

        # Redialing strategy
        REPEAT_TIMES = '3'
        BULK_CALL_INTERVAL = '60'

        # Voicemail strategy
        VOICEMAIL_CHECK = '1'
        VOICEMAIL_CHECK_DURATION = '2500'
        VOICEMAIL_HANDLE = '1'

    SUB_APP = "sales_ops_pds"

    RECORDING_FILE_SUB_FOLDER = 'recording_file'


class SalesOpsPDSUploadConst:
    UPLOAD_BATCH_SIZE = 5000
    SUB_APP = "sales_ops_pds"
    DUMMY_CALLBACK_URL = "dummy"


class AIRudderHangupReasonConst:
    HANGUP_REASON_PDS_MAPPING = {
        0: 'Unknown',
        1: 'NoAgent after contact answering',
        2: 'Normal',
        3: 'Busy',
        4: 'Not In Use',
        5: 'Hold',
        6: 'Switched Off',
        7: 'Out of Area',
        8: 'Invalid',
        9: 'Wrong Number',
        12: 'Talked',
        13: 'AgentReject',
        14: 'UseHangUp',
        15: 'Fusing',
        16: 'AMD',
        17: 'Agent Network Failed',
        18: 'Call Attempt Limits',
        19: 'Contact Short Abandoned',
        20: 'Do-Not-Call',
    }


class AIRudderCallResultTypeConst:
    DNC = "Dnc"
    OVERRUN = "Overrun"
    NO_RINGING = "NoRinging"
    FUSING = "Fusing"
    VOICEMAIL = "Voicemail"
    NO_ANSWERED = "NoAnswered"
    AGENT_BUSY = "AgentBusy"
    USER_HANGUP_BEFORE_ASSIGN = "UserHangupBeforeAssign"
    AGENT_REJECT = "AgentReject"
    AGENT_NETWORK_ERROR = "AgentNetworkError"
    USER_HANGUP = "UserHangup"
    SUCC_USER_HANGUP = "SuccUserHangup"
    SUCC_AGENT_HANGUP = "SuccAgentHangup"

    CALL_RESULT_TYPE_MAPPING = {
        DNC: "Do not call",
        OVERRUN: "Overrun",
        NO_RINGING: "Contact Unanswered - No RingBack Tone",
        FUSING: "Contact Unanswered - Hang up by System",
        VOICEMAIL: "Voicemail Detected",
        NO_ANSWERED: "Contact Unanswered - No Answer / Contact Answered - Contact Short Abandone",
        AGENT_BUSY: "Contact Answered - All Agents Busy",
        USER_HANGUP_BEFORE_ASSIGN: "Contact Answered - Customer Abandoned before Assigning Agent",
        AGENT_REJECT: "Contact Answered - Refused by Agents",
        AGENT_NETWORK_ERROR: "Contact Answered - Connection Problems of Agent",
        USER_HANGUP: "Contact Answered - Customer Abandoned after Assigning Agent",
        SUCC_USER_HANGUP: "Talked - Hang up by Contact",
        SUCC_AGENT_HANGUP: "Talked - Hang up by Agent"
    }


class AIRudderCallResultPerLevelConst:
    class Level_1:
        CONNECTED = "Connected"
        NOT_CONNECTED = "Not_Connected"

    class Level_2:
        RPC_1 = "rpc_1"
        RPC_2 = "rpc_2"
        BUSY = "busy"
        BUSYLINE = "busyline"
        MAIL_BOX = "mail_box"
        REJECTED= "rejected"
        WPC = "wpc"

    class Level_3:
        RPC_INTERESTED = "rpc_interested"
        RPC_NOT_INTERESTED = "rpc_not_interested"
        RPC_CONSIDER = "rpc_consider"

        RPC_CALLBACK_LATER = "rpc_call_back_later"
        RPC_HANGUP = "rpc_hangup"
        RPC_MOVE_TO_CS = "rpc_moveto_cs"
        RPC_REQ_TAKEOUT = "rpc_req_takeout"
        RPC_HAVE_RPC = "rpc_have_rpc"
        RPC_REGULAR_OTHER = "rpc_regular/other"

    LV1_TO_LV2_MAPPING = {
        Level_1.CONNECTED: {
            Level_2.RPC_1,
            Level_2.RPC_2,
            Level_2.REJECTED,
            Level_2.WPC,
            Level_2.BUSY
        },
        Level_1.NOT_CONNECTED: {
            Level_2.MAIL_BOX,
            Level_2.BUSYLINE
        }
    }

    LV2_TO_LV3_MAPPING = {
        Level_2.RPC_1: {
            Level_3.RPC_INTERESTED,
            Level_3.RPC_NOT_INTERESTED,
            Level_3.RPC_CONSIDER
        },
        Level_2.RPC_2: {
            Level_3.RPC_CALLBACK_LATER,
            Level_3.RPC_HANGUP,
            Level_3.RPC_MOVE_TO_CS,
            Level_3.RPC_HAVE_RPC,
            Level_3.RPC_REQ_TAKEOUT,
            Level_3.RPC_REGULAR_OTHER
        }
    }


class SalesOpsPDSDownloadConst:
    DEFAULT_DOWNLOAD_LIMIT = 50
    IS_RPC_CALL_RESULT_TYPES = [
        AIRudderCallResultTypeConst.SUCC_USER_HANGUP,
        AIRudderCallResultTypeConst.SUCC_AGENT_HANGUP
    ]
    IS_RPC_LEVEL_1 = AIRudderCallResultPerLevelConst.Level_1.CONNECTED
    IS_RPC_LEVEL_2 = AIRudderCallResultPerLevelConst.Level_2.RPC_1


class SalesOpsPDSDataStoreType:
    UPLOAD_TO_AIRUDDER = "upload"
    UPLOAD_FAILED_TO_AIRUDDER = "upload_failed"
    DOWNLOAD_FROM_AIRUDDER = "download"


class SalesOpsPDSTaskName:
    CREATE_TASK = "create_task"
    DOWNLOAD_CALL_RESULT = "download_call_result"
    DOWNLOAD_RECORDING_FILE = "download_recording_file"
    DOWNLOAD_LIMIT = "download_limit"


class SalesOpsPDSAlert:
    CHANNEL = '#sales_ops_alerts'
    MESSAGE = '<!here> Creating PDS tasks on AIRudder report on *{date}*'


class RedisKey:
    SALES_OPS_AIRUDDER_PDS_BEARER_TOKEN_KEY = 'sales_ops_pds:airudder_bearer_token_key'
