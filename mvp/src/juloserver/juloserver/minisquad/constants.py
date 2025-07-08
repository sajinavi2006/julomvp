from builtins import object

ICARE_DEFAULT_ZIP_CODE = 10110
DEFAULT_DB = 'default'
REPAYMENT_ASYNC_REPLICA_DB = 'julorepayment_async_replica'
COLLECTION_DB = 'collection_db'


class Threshold(object):
    FAILED_CALLED = 10
    B1_NC_FAILED_CALLED = 5


class SquadNames(object):
    COLLECTION_BUCKET_2_SQUAD_1 = 'B2.S1'
    COLLECTION_BUCKET_2_SQUAD_2 = 'B2.S2'
    COLLECTION_BUCKET_3_SQUAD_1 = 'B3.S1'
    COLLECTION_BUCKET_3_SQUAD_2 = 'B3.S2'
    COLLECTION_BUCKET_3_SQUAD_3 = 'B3.S3'
    COLLECTION_BUCKET_4_SQUAD_1 = 'B4.S1'


class RedisKey(object):
    ASSIGNED_LOAN_IDS = 'minisquad:assigned_loan_ids'
    OLDEST_PAYMENT_IDS = 'minisquad:oldest_payment_ids'
    EXCLUDED_BUCKET_LEVEL_PAYMENT_IDS = 'minisquad:excluded_payment_ids'
    OLDEST_ACCOUNT_PAYMENT_IDS = 'collection_vendor:oldest_account_payment_ids'
    ELIGIBLE_BTTC_IDS = 'minisquad:bttc_ids'
    EXCLUDED_PARTNER_FROM_DIALER = 'minisquad:excluded_partner_from_dialer'
    DIALER_ACCOUNT_PAYMENT_IDS = 'minisquad:eligible_dialer_account_payment_ids'
    DIALER_JTURBO_ACCOUNT_PAYMENT_IDS = 'minisquad:eligible_dialer_jturbo_account_payment_ids'
    KOLEKO_CPCRD_NEW_FILE_PATH = 'minisquad:koleko_cpcrd_new_file_path'
    KOLEKO_CPCRD_EXT_FILE_PATH = 'minisquad:koleko_cpcrd_ext_file_path'
    KOLEKO_CPCRD_PAYMENT_FILE_PATH = 'minisquad:koleko_cpcrd_payment_file_path'
    GRAB_OLDEST_PAYMENT_IDS = 'minisquad:grab_oldest_payment_ids'
    TAILOR_EXPERIMENT_FOR_LOG = 'minisquad:tailor_experiment_log'
    TAILOR_EXPERIMENT_DATA = 'minisquad:tailor_experiment_data'
    EXCLUDED_KEY_LIST_OF_ACCOUNT_IDS_PER_BUCKET = 'list_excluded_account_ids_key_{}|part_{}'
    CACHED_NON_CONTACTED_ACCOUNT_PAYMENT_IDS = 'cached_non_contacted_account_payment_ids_{}'
    POPULATE_ELIGIBLE_CALL_ACCOUNT_PAYMENT_IDS = (
        'populate_eligible_call_account_payment_ids_{}_part_{}'
    )
    POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS = (
        'populate_eligible_call_grab_payment_ids_{}_rank_{}_part_{}'
    )

    CLEAN_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED = (
        'clean_account_payment_ids_for_dialer_related_{}|part_{}'
    )
    CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED = (
        'clean_grab_payment_ids_for_dialer_related_{}|rank_{}|part_{}'
    )
    SPECIFIC_ACCOUNT_PAYMENT_IDS_BUCKET_FOR_EXCLUDE = (
        'specific_account_payment_ids_bucket_for_exclude_{}|part_{}'
    )

    EXCLUDED_BY_ACCOUNT_STATUS = 'excluded_by_account_status_{}|part_{}'
    EXCLUDED_BUCKET_LEVEL_ACCOUNT_IDS = 'excluded_bucket_level_account_ids|{}|part_{}'
    EXCLUDE_PAYMENT_REFINANCING = 'exclude_payment_refinancing|{}|part_{}'
    CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX = 'constructed_data_for_send_to_intelix|{}'
    IS_SUCCESS_FORMAT_DATA_TO_INTELIX = 'is_success_format_data_to_intelix|{}'
    DATA_FOR_STORE_TO_COLLECTION_VENDOR_ASSIGNMENT = (
        'data_for_store_to_collection_vendor_assignment|{}'
    )
    COLLECTION_TAILOR_MODEL_IDS = 'minisquad:collection_tailor_model_ids_dpd|{}'
    RETRY_SEND_TO_INTELIX_BUCKET_IMPROVEMENT = 'retry_send_to_intelix_bucket_improvement_{}'
    EXCLUDED_GRAB_BUCKET_LEVEL_ACCOUNT_IDS = 'excluded_grab_bucket_level_account_ids|{}|part_{}'
    HIGH_RISK_COLLECTION_TAILOR_MODEL_IDS = 'minisquad:high_risk_collection_tailor_model_ids_dpd|{}'
    ROBOCALL_TAILOR_EXPERIMENT_FOR_LOG = 'minisquad:robocall_tailor_experiment_log'
    CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_INTELIX = 'constructed_data_for_send_to_intelix|{}|batch_{}'
    GRAB_TEMP_DATA_COLL_IDS_BATCH = 'grab_temp_data_coll_ids|{}|batch_{}'
    # AI Rudder
    AIRUDDER_EXPERIMENT_GROUP_INSERTED = 'airudder_experiment_group_inserted|{}'
    AIRUDDER_PDS_BEARER_TOKEN_KEY = 'minisquad:airudder_bearer_token_key'
    NOT_SENT_DIALER_JULO_T0 = 'not_sent_dialer_julo_t0'
    NOT_SENT_DIALER_JTURBO_T0 = 'not_sent_dialer_jturbo_t0'
    PATH_CALL_RECORDING_NEED_TO_BE_DELETE = 'path_call_recording_need_to_be_delete'
    # dialer system related
    CHECKING_DATA_GENERATION_STATUS = 'CHECKING_DATA_GENERATION_STATUS_{}'
    J1_DAILY_TASK_ID_FROM_DIALER = 'j1_daily_task_id_from_dialer'
    AI_RUDDER_POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS = (
        'ai_rudder_populate_eligible_call_grab_payment_ids_{}_rank_{}_part_{}'
    )
    AI_RUDDER_CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED = (
        'ai_rudder_clean_grab_payment_ids_for_dialer_related_{}|rank_{}|part_{}'
    )
    AI_RUDDER_GRAB_TEMP_DATA_COLL_IDS_BATCH = 'ai_rudder_grab_temp_data_coll_ids|{}|batch_{}'
    CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_AI_RUDDER = (
        'constructed_data_for_send_to_ai_rudder|{' '}|batch_{}'
    )
    AI_RUDDER_GRAB_DAILY_TASK_ID_FROM_DIALER = 'ai_rudder_grab_daily_task_id_from_dialer'
    GRAB_ACCOUNT_IDS = 'grab_account_ids'
    DAILY_TASK_ID_FROM_DIALER = 'daily_task_id_from_dialer'
    DAILY_TASK_ID_FROM_DIALER_FOR_RETROLOAD = 'daily_task_id_from_dialer_for_retroload'
    DAILY_REDIS_KEY_FOR_DIALER = 'daily_redis_key_for_dialer'
    CONSUME_CALL_RESULT_SYSTEM_LEVEL = 'consume_call_result_system_level'
    ACCOUNT_ID_BUCKET_HISTORY = 'ACCOUNT_ID_BUCKET_HISTORY_{}'
    PROCESSED_EXCLUTION_PROCESS_KEY = 'PROCESSED_EXCLUTION_PROCESS_KEY_{}'
    B6_1_TOTAL_DATA_ELIGIBLE_TO_VENDOR = 'b6_1_total_data_eligible_to_vendor'
    CLEAN_ACCOUNT_PAYMENT_IDS_AFTER_EXCLUDE = 'CLEAN_ACCOUNT_PAYMENT_IDS_AFTER_EXCLUDE_{}'
    DAILY_REDIS_KEY_FOR_DIALER_RECOVERY = 'DAILY_REDIS_KEY_FOR_DIALER_RECOVERY'
    LOCK_CHAINED_TASK_RECOVERY = 'LOCK_CHAINED_TASK_RECOVERY_{}'
    DAILY_TASK_IDS_FOR_CANCEL_CALL = 'DAILY_TASK_IDS_FOR_CANCEL_CALL'
    DYNAMIC_AIRUDDER_CONFIG = 'minisquad::airudder::DYNAMIC_AIRUDDER_CONFIG'
    LIST_BTTC_PROCESS_REDIS_KEYS = 'LIST_BTTC_PROCESS_REDIS_KEYS'
    LOCK_CHAINED_BTTC = 'LOCK_CHAINED_BTTC_{}'
    AVAILABLE_BTTC_BUCKET_LIST = 'AVAILABLE_BTTC_BUCKET_LIST'
    BTTC_FINISHED_TASK_IDS = 'BTTC_FINISHED_TASK_IDS_{}'
    NEW_PDS_EXPERIMENT_TEAM_B = 'NEW_PDS_EXPERIMENT_TEAM_B'
    BCURRENT_POPULATION_TRACKER = 'BCURRENT_POPULATION_TRACKER_{}'
    BCURRENT_CONSTRUCT_TRACKER = 'BCURRENT_CONSTRUCT_TRACKER_{}'
    BCURRENT_CONSTRUCTED_BUCKETS = 'BCURRENT_CONSTRUCTED_BUCKETS_{}'
    MANUAL_DC_ASSIGNMENT_EXPIRY = 'MANUAL_DC_ASSIGNMENT_EXPIRY_{}'
    PROCESSED_RECOVERY_POPULATED_KEY = 'PROCESSED_RECOVERY_POPULATED_KEY_{}'
    TOTAL_CLEAN_RECOVERY_COUNT = 'TOTAL_CLEAN_RECOVERY_COUNT_{}'
    YESTERDAY_IS_HOLIDAY = 'YESTERDAY_IS_HOLIDAY_{}'  # date string
    AVAILABLE_BTTC_BUCKET_LIST_EXPERIMENT_CALL_ORDER = (
        'AVAILABLE_BTTC_BUCKET_LIST_EXPERIMENT_CALL_ORDER'
    )


class CenterixCallResult(object):
    RPC = ('RPC - Regular', 'RPC - PTP', 'RPC - HTP', 'RPC - Broken Promise', 'Whatsapp - Text')

    WPC = ('WPC - Regular', 'WPC - Left Message')

    NC = ('Answering Machine', 'Busy Tone', 'Ringing', 'Dead Call')

    SYSTEM_GENERATED_SUB_STATUS = (
        '',
        'abandoned by system',
        'abandoned by customer',
        'abandoned by agent',
        'busy',
        'salah nomor',
        'tidak diangkat',
        'mesin fax',
        'positive voice',
        'trying to reach',
        'no contact / end of campaign',
        'unreachable',
        'no interaction status',
        'reallocated',
        'reassigned',
        'disconnect by system',
        'disconnect by network',
        'call failed',
        'not active',
        'answering machine',
    )

    SYSTEM_GENERATED_NC_STATUS = (
        'busy',
        'salah nomor',
        'tidak diangkat',
        'mesin fax',
        'answering machine - system',
        'call failed',
        'not active',
    )

    NC_STATUS_GROUP = 'System Generated - Non Contacted'

    SYSTEM_GENERATED_NULL_STATUS = (
        '',
        'positive voice',
        'trying to reach',
        'no contact / end of campaign',
        'unreachable',
        'reallocated',
        'reassigned',
        'disconnect by system',
        'disconnect by network',
        'abandoned by system',
        'abandoned by customer',
        'abandoned by agent',
    )

    NULL_STATUS_GROUP = 'System Generated - Null'

    SYSTEM_GENERATED_DEFAULT_STATUS = 'no interaction status'

    DEFAULT_STATUS_GROUP = 'System Generated - System Default'

    SUB_STATUS_AM_OLD_NAME = 'answering machine'

    SUB_STATUS_AM_NEW_NAME = 'Answering Machine - System'


class CollectedBy(object):
    SQUAD = 'squad'
    AGENT = 'agent'


class DialerVendor(object):
    CENTERIX = 'centerix'
    INTELIX = 'intelix'
    GENESYS = 'genesys'


class IntelixResultChoiceMapping(object):
    # key = Intelix status, value is our skiptrace choice value
    MAPPING_STATUS = {
        'call rejected': 'Busy',
        'circuit/channel congestion': 'Disconnect By Network',
        'congestion (circuits busy)': 'Disconnect By Network',
        'destination out of order': 'Not Active',
        'network out of order': 'Disconnect By Network',
        'no route to destination': 'Unreachable',
        'no user responding': 'Tidak Diangkat',
        'normal, unspecified': 'NULL',
        'other end has hungup': 'Positive Voice',
        'remote end is busy': 'Busy',
        'remote end is ringing': 'Tidak Diangkat',
        'subscriber absent': 'Salah Nomor',
        'temporary failure': 'Disconnect by Network',
        'unallocated (unassigned) number': 'Unreachable',
        'user alerting, no answer': 'Tidak Diangkat',
        'user busy': 'Busy',
        'abandoned on queue': 'Abandoned by System',
        'abandoned while transfer to agent': 'Abandoned by Agent',
        'abandoned while ringing on agent': 'Abandoned by Customer',
        'normal clearing': 'NULL',
    }
    CONNECTED_STATUS = [
        "RPC - Already PTP",
        "RPC - Already Paid",
        "RPC - Whatsapp",
        "RPC - Telegram",
        "RPC - Regular",
        "RPC - PTP",
        "RPC - HTP",
        "WPC - Regular",
        "WPC - Left Message",
        "WPC",
        "Whatsapp - Text",
        "ACW - Interrupt",
        "RPC",
        "RPC - Left Message",
        "RPC - Call Back",
        "RPC - Broken Promise",
    ]


class DialerTaskStatus(object):
    INITIATED = 'initiated'
    # UPLOAD
    QUERIED = 'queried'
    SORTED = 'sorted'
    SENT = 'sent'
    SENT_BATCH = 'batch_{}_sent'
    # DOWNLOAD
    DOWNLOADED = 'downloaded'
    STORED = 'stored'
    PARTIAL_STORED = 'partial_stored'
    FAILURE = 'failure'
    SUCCESS = 'success'
    DISPATCHED = 'dispatched'
    # BULK DOWNLOAD
    PROCESSED = 'processed'
    UPLOADING = 'uploading'
    PARTIAL_PROCESSED = 'partial_processed'
    QUERYING = 'querying'
    BATCHING_PROCESS = 'batching_process'
    BATCHING_PROCESSED = 'batching_processed'
    PROCESSING_BATCHING_EXCLUDE_SECTION = 'processing_batching_exclude_section_part_{}'
    PROCESSED_BATCHING_EXCLUDE_SECTION = 'processed_batching_exclude_section_part_{}'
    PROCESS_POPULATED_ACCOUNT_PAYMENTS = 'process_populated_account_payments_{}_part_{}'
    PROCESSED_POPULATED_ACCOUNT_PAYMENTS = 'processed_populated_account_payments_{}_part_{}'
    PROCESSED_POPULATED_GRAB_PAYMENTS = 'processed_populated_grab_payments_{}_rank_{}_part_{}'
    FAILURE_BATCH = 'failure_part_{}'
    CONSTRUCTED = 'constructed'
    SENT_PROCESS = 'sent_process'
    HIT_INTELIX_SEND_API = 'hit_intelix_send_api'
    FAILURE_ASSIGN = 'failure_assign_for_{}'
    STORE_PROCESS = 'store_process'
    PROCESSING_GRAB_BATCHING_EXCLUDE_SECTION = 'processing_grab_batching_exclude_section_part_{}'
    PROCESSED_GRAB_BATCHING_EXCLUDE_SECTION = 'processed_grab_batching_exclude_section_part_{}'
    PROCESS_POPULATED_GRAB_PAYMENTS = 'process_populated_grab_payments_{}_rank_{}_part_{}'
    QUERIED_BATCH = 'queried_{}'
    CONSTRUCTED_BATCH = 'constructed_{}'
    STORED_BATCH = 'stored_{}'
    QUERYING_RANK = 'querying_rank_{}_chunk_{}'
    QUERIED_RANK = 'queried_rank_{}'
    BATCHING_PROCESSED_RANK = 'batching_processed_rank_{}'
    FAILURE_RANK_BATCH = 'failure_rank_{}_part_{}'
    SENT_PROCESS_BATCH = 'sent_process_batch_{}'
    HIT_INTELIX_SEND_API_BATCH = 'hit_intelix_send_api_batch_{}'
    BEFORE_PROCESS_CONSTRUCT_BATCH = 'before_process_construct_batch_{}'
    TRIGGER_SENT_BATCH = 'trigger_sent_batch'
    TRIGGER_SENT_BATCHING = 'trigger_sent_batch_{}'
    UPLOADING_PER_BATCH = 'uploading_pages_{}_retries_{}'
    UPLOADED_PER_BATCH = 'uploaded_pages_{}'
    PROCESS_FAILED_ON_PROCESS_RETRYING = 'process_failed_on_process_retrying'
    BATCHING_PROCESS_FAILURE = 'batching_process_failure'
    FAILED_UPDATE_TASKS_ID = 'failed_update_tasks_id'
    CONSTRUCTING = 'constructing'
    GRAB_AI_RUDDER_QUERYING_RANK = 'ai_rudder_querying_rank_{}_chunk_{}'
    GRAB_AI_RUDDER_QUERIED_RANK = 'ai_rudder_queried_rank_{}'
    GRAB_AI_RUDDER_BATCHING_PROCESSED_RANK = 'ai_rudder_batching_processed_rank_{}'
    GRAB_AI_RUDDER_FAILURE_RANK_BATCH = 'ai_rudder_failure_rank_{}_part_{}'
    GRAB_AI_RUDDER_PROCESSED_POPULATED_GRAB_PAYMENTS = (
        'ai_rudder_processed_populated_grab_payments_{}_rank_{}_part_{}'
    )
    GRAB_AI_RUDDER_PROCESS_POPULATED_GRAB_PAYMENTS = (
        'ai_rudder_process_populated_grab_payments_{' '}_rank_{}_part_{}'
    )
    GRAB_AI_RUDDER_BEFORE_PROCESS_CONSTRUCT_BATCH = 'ai_rudder_before_process_construct_batch_{}'
    GRAB_AI_RUDDER_QUERIED_BATCH = 'ai_rudder_queried_{}'
    GRAB_AI_RUDDER_CONSTRUCTED_BATCH = 'ai_rudder_constructed_{}'
    GRAB_AI_RUDDER_STORED_BATCH = 'ai_rudder_stored_{}'
    GRAB_AI_RUDDER_SENT_PROCESS_BATCH = 'ai_rudder_sent_process_batch_{}'
    GRAB_AI_RUDDER_HIT_SEND_API_BATCH = 'hit_ai_rudder_send_api_batch_{}'
    GRAB_AI_RUDDER_TRIGGER_SENT_BATCH = 'ai_rudder_trigger_sent_batch'
    GRAB_AI_RUDDER_TRIGGER_SENT_BATCHING = 'ai_rudder_trigger_sent_batch_{}'
    DIALER_TASK_INTERNAL_SOURCE = 'mvp'
    DIALER_TASK_SERVERLESS_SOURCE = 'serverless'
    VENDOR_DISTRIBUTION_PROCESS = 'vendor_distribution_process'
    VENDOR_DISTRIBUTION_PROCESSED = 'vendor_distribution_processed'
    BTTC_DELINQUENT_TRIGGER_CONSTRUCT = 'BTTC_DELINQUENT_TRIGGER_CONSTRUCT_{}'
    VENDOR_DISTRIBUTION_PROCESS_BATCH = 'vendor_distribution_process_part_{}'
    VENDOR_DISTRIBUTION_PROCESSED_BATCH = 'vendor_distribution_processed_part_{}'


class DialerTaskType(object):
    SKIPTRACE_HISTORY_AGENT_LEVEL = 'skiptrace_history_agent_level_calls_realtime'
    SKIPTRACE_HISTORY_SYSTEM_LEVEL = 'skiptrace_history_system_level_calls'
    AGENT_PRODUCTIVITY_EVERY_HOURS = 'agent_productivity_every_hours'
    CONSTRUCT_JULO_B1 = 'construct_julo_b1_data'
    UPLOAD_JULO_B1 = 'upload_julo_b1_data'
    CONSTRUCT_JULO_B1_NC = 'construct_julo_b1_nc_data'
    UPLOAD_JULO_B1_NC = 'upload_julo_b1_nc_data'
    CONSTRUCT_JULO_B2 = 'construct_julo_b2_data'
    UPLOAD_JULO_B2 = 'upload_julo_b2_data'
    CONSTRUCT_JULO_B2_NC = 'construct_julo_b2_nc_data'
    UPLOAD_JULO_B2_NC = 'upload_julo_b2_nc_data'
    CONSTRUCT_JULO_B3 = 'construct_julo_b3_data'
    UPLOAD_JULO_B3 = 'upload_julo_b3_data'
    CONSTRUCT_JULO_B3_NC = 'construct_julo_b3_nc_data'
    UPLOAD_JULO_B3_NC = 'upload_julo_b3_nc_data'
    UPLOAD_JULO_B4 = 'upload_julo_b4_data'
    UPLOAD_JULO_B4_NC = 'upload_julo_b4_nc_data'
    UPLOAD_JULO_B5 = 'upload_julo_b5_data'
    UPLOAD_JULO_B6_1 = 'upload_julo_b6_1_data'
    UPLOAD_JULO_B6_2 = 'upload_julo_b6_2_data'
    UPLOAD_JULO_B5_4 = 'upload_julo_b5_4_data'
    UPLOAD_JULO_B5_5 = 'upload_julo_b5_5_data'
    UPLOAD_JULO_T_5 = 'upload_julo_t_5'
    UPLOAD_JULO_T_3 = 'upload_julo_t_3'
    UPLOAD_JULO_T_1 = 'upload_julo_t_1'
    UPLOAD_JULO_T0 = 'upload_julo_t0_data'
    # JTURBO
    CONSTRUCT_JTURBO_B1 = 'construct_jturbo_b1_data'
    UPLOAD_JTURBO_B1 = 'upload_jturbo_b1_data'
    CONSTRUCT_JTURBO_B1_NC = 'construct_jturbo_b1_nc_data'
    UPLOAD_JTURBO_B1_NC = 'upload_jturbo_b1_nc_data'
    CONSTRUCT_JTURBO_B2 = 'construct_jturbo_b2_data'
    UPLOAD_JTURBO_B2 = 'upload_jturbo_b2_data'
    CONSTRUCT_JTURBO_B2_NC = 'construct_jturbo_b2_nc_data'
    UPLOAD_JTURBO_B2_NC = 'upload_jturbo_b2_nc_data'
    CONSTRUCT_JTURBO_B3 = 'construct_jturbo_b3_data'
    UPLOAD_JTURBO_B3 = 'upload_jturbo_b3_data'
    CONSTRUCT_JTURBO_B3_NC = 'construct_jturbo_b3_nc_data'
    UPLOAD_JTURBO_B3_NC = 'upload_jturbo_b3_nc_data'
    CONSTRUCT_JTURBO_B4 = 'construct_jturbo_b4_data'
    UPLOAD_JTURBO_B4 = 'upload_jturbo_b4_data'
    CONSTRUCT_JTURBO_B4_NC = 'construct_jturbo_b4_nc_data'
    UPLOAD_JTURBO_B4_NC = 'upload_jturbo_b4_nc_data'
    UPLOAD_JTURBO_T_5 = 'upload_jturbo_t_5'
    UPLOAD_JTURBO_T_3 = 'upload_jturbo_t_3'
    UPLOAD_JTURBO_T_1 = 'upload_jturbo_t_1'
    UPLOAD_JTURBO_T0 = 'upload_jturbo_t0_data'

    SHARED_BUCKET_T = 'Shared Bucket| T'
    UPLOAD_GRAB = 'upload_grab_data'
    UPLOAD_ALL_CONSTRUCTED_BUCKET_TO_INTELIX = 'upload_all_constructed_bucket_to_intelix'
    STORING_RECORDING_INTELIX = 'storing_recording_intelix'
    DOWNLOADING_RECORDING_AIRUDDER = 'downloading_recording_airudder'
    STORING_RECORDING_AIRUDDER = 'storing_recording_airudder'
    EXPERIMENT_COOTEK_LATE_DPD = 'experiment_cootek_late_dpd_{}'
    BULK_DOWNLOAD_RECORDING_PROCESS_INTELIX = 'bulk_download_recording_process_intelix'
    MANUAL_UPLOAD_GENESYS_CALL_RESULTS = 'manual_upload_genesys_call_results'
    BULK_DOWNLOAD_PROCESS_METABASE = 'bulk_download_process_metabase'
    UPLOAD_GRAB_KOLEKO = 'upload_grab_data_to_koleko'
    POPULATING_COLLECTION_DIALER_TEMP_DATA = 'populating_collection_dialer_temp_data_{}'
    SORTING_COLLECTION_DIALER_TEMP_DATA = 'sorting_collection_dialer_temp_data_{}'
    DIALER_TASK_TYPE_IMPROVED = {
        UPLOAD_JULO_B1: 'JULO_B1',
        UPLOAD_JULO_B1_NC: 'JULO_B1_NON_CONTACTED',
        UPLOAD_JULO_B2: 'JULO_B2',
        UPLOAD_JULO_B2_NC: 'JULO_B2_NON_CONTACTED',
        UPLOAD_JULO_B3: 'JULO_B3',
        UPLOAD_JULO_B3_NC: 'JULO_B3_NON_CONTACTED',
        UPLOAD_JTURBO_B1: 'JTURBO_B1',
        UPLOAD_JTURBO_B1_NC: 'JTURBO_B1_NON_CONTACTED',
        UPLOAD_JTURBO_B2: 'JTURBO_B2',
        UPLOAD_JTURBO_B2_NC: 'JTURBO_B2_NON_CONTACTED',
        UPLOAD_JTURBO_B3: 'JTURBO_B3',
        UPLOAD_JTURBO_B3_NC: 'JTURBO_B3_NON_CONTACTED',
        UPLOAD_JTURBO_B4: 'JTURBO_B4',
        UPLOAD_JTURBO_B4_NC: 'JTURBO_B4_NON_CONTACTED',
    }
    PROCESS_POPULATE_VENDOR_B3_SORT1_METHOD = 'process_populate_vendor_b3_sort1_method'
    CONSTRUCT_DANA_B_ALL = 'construct_dana_b_all_data'
    UPLOAD_DANA_B1 = 'upload_dana_b1_data'
    UPLOAD_DANA_B2 = 'upload_dana_b2_data'
    UPLOAD_DANA_B3 = 'upload_dana_b3_data'
    UPLOAD_DANA_B4 = 'upload_dana_b4_data'
    UPLOAD_DANA_B5 = 'upload_dana_b5_data'
    PROCESS_POPULATE_VENDOR_B3_EXPERIMENT1_METHOD = 'process_populate_vendor_b3_experiment1_method'
    UPLOAD_DANA_T0 = 'upload_dana_t0_data'
    UPLOAD_JULO_B1_FINAL_REEXPERIMENT = 'upload_julo_b1_final_reexperiment'
    PROCESS_POPULATE_B5 = 'process_populate_b5'
    PROCESS_POPULATE_B6_1 = 'process_populate_b6_1'
    PROCESS_POPULATE_FC_B1 = 'process_populate_fc_b1'

    CONSTRUCT_COHORT_CAMPAIGN_JULO_B1 = 'CONSTRUCT_COHORT_CAMPAIGN_JULO_B1'
    CONSTRUCT_COHORT_CAMPAIGN_JULO_B1_NC = 'CONSTRUCT_COHORT_CAMPAIGN_JULO_B1_NC'
    CONSTRUCT_SPECIAL_COHORT_JULO_B1 = 'CONSTRUCT_SPECIAL_COHORT_JULO_B1'
    CONSTRUCT_SPECIAL_COHORT_JULO_B1_NC = 'CONSTRUCT_SPECIAL_COHORT_JULO_B1_NC'
    CONSTRUCT_COHORT_CAMPAIGN_JTURBO_B1 = 'CONSTRUCT_COHORT_CAMPAIGN_JTURBO_B1'
    CONSTRUCT_COHORT_CAMPAIGN_JTURBO_B1_NC = 'CONSTRUCT_COHORT_CAMPAIGN_JTURBO_B1_NC'
    CONSTRUCT_SPECIAL_COHORT_JTURBO_B1 = 'CONSTRUCT_SPECIAL_COHORT_JTURBO_B1'
    CONSTRUCT_SPECIAL_COHORT_JTURBO_B1_NC = 'CONSTRUCT_SPECIAL_COHORT_JTURBO_B1_NC'
    CONSTRUCT_JULO_B1_NON_CONTACTED = 'CONSTRUCT_JULO_B1_NC_DATA'
    CONSTRUCT_JULO_B2_NON_CONTACTED = 'CONSTRUCT_JULO_B2_NC_DATA'
    CONSTRUCT_JULO_B3_NON_CONTACTED = 'CONSTRUCT_JULO_B3_NC_DATA'
    CONSTRUCT_JULO_B4_NON_CONTACTED = 'CONSTRUCT_JULO_B4_NC_DATA'
    CONSTRUCT_COHORT_CAMPAIGN_JULO_B1_NON_CONTACTED = (
        'CONSTRUCT_COHORT_CAMPAIGN_JULO_B1_NON_CONTACTED'
    )
    CONSTRUCT_SPECIAL_COHORT_JULO_B1_NON_CONTACTED = (
        'CONSTRUCT_SPECIAL_COHORT_JULO_B1_NON_CONTACTED'
    )
    CONSTRUCT_COHORT_CAMPAIGN_JTURBO_B1_NON_CONTACTED = (
        'CONSTRUCT_COHORT_CAMPAIGN_JTURBO_B1_NON_CONTACTED'
    )
    CONSTRUCT_SPECIAL_COHORT_JTURBO_B1_NON_CONTACTED = (
        'CONSTRUCT_SPECIAL_COHORT_JTURBO_B1_NON_CONTACTED'
    )
    CONSTRUCT_JTURBO_B1_NON_CONTACTED = 'CONSTRUCT_JTURBO_B1_NC'
    CONSTRUCT_JTURBO_B2_NON_CONTACTED = 'CONSTRUCT_JTURBO_B2_NC'
    CONSTRUCT_JTURBO_B3_NON_CONTACTED = 'CONSTRUCT_JTURBO_B3_NC'
    CONSTRUCT_JTURBO_B4_NON_CONTACTED = 'CONSTRUCT_JTURBO_B4_NC'
    CONSTRUCT_DANA_BUCKET_CICIL = 'CONSTRUCT_DANA_BUCKET_CICIL'
    CONSTRUCT_DANA_BUCKET_CASHLOAN = 'CONSTRUCT_DANA_BUCKET_CASHLOAN'
    CONSTRUCT_DANA_BUCKET_91_PLUS = 'CONSTRUCT_DANA_BUCKET_91_PLUS'

    DIALER_UPLOAD_DATA_WITH_BATCH = 'DIALER_UPLOAD_DATA_WITH_BATCH_{}'
    GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA = \
        'ai_rudder_populating_collection_dialer_temp_data_{}'
    GRAB_AI_RUDDER_UPLOAD_GRAB = 'ai_rudder_upload_grab_data'
    GRAB_DOWNLOADING_RECORDING_AIRUDDER = 'grab_downloading_recording_airudder'
    GRAB_STORING_RECORDING_AIRUDDER = 'grab_storing_recording_airudder'
    BTTC_EXPERIMENT_PROCESS = 'BTTC_EXPERIMENT_PROCESS'
    CONSTRUCT_BTTC_DELINQUENT = 'CONSTRUCT_{}'

    @classmethod
    def get_construct_dialer_type(cls, bucket_name):
        return 'CONSTRUCT_' + bucket_name


class IntelixTeam(object):
    JULO_B1 = 'JULO_B1'
    JULO_B1_NC = 'JULO_B1_NON_CONTACTED'
    JULO_B2 = 'JULO_B2'
    JULO_B2_NC = 'JULO_B2_NON_CONTACTED'
    JULO_B3 = 'JULO_B3'
    JULO_B3_NC = 'JULO_B3_NON_CONTACTED'
    JULO_B4 = 'JULO_B4'
    JULO_B4_NC = 'JULO_B4_NON_CONTACTED'
    JULO_B5 = 'JULO_B5'
    JULO_B6_1 = 'JULO_B6_1'
    JULO_B6_2 = 'JULO_B6_2'
    JULO_B6_3 = 'JULO_B6_3'
    JULO_B6_4 = 'JULO_B6_4'
    JULO_T_5 = 'JULO_T-5'
    JULO_T_3 = 'JULO_T-3'
    JULO_T_1 = 'JULO_T-1'
    GRAB = 'GRAB'
    SPECIAL_COHORT = 'special_cohort_{}'
    # COOTEK
    JULO_T0 = 'JULO_T0'
    SHARED_BUCKET = 'Experiment Shared Bucket'
    ALL_BUCKET_5_TEAM = (JULO_B5, JULO_B6_1, JULO_B6_2)
    CURRENT_BUCKET = (JULO_B5, JULO_B6_1, JULO_B6_2, JULO_T_5, JULO_T_3, JULO_T_1)
    SORTED_BUCKET = (SPECIAL_COHORT.format('B1'), SPECIAL_COHORT.format('B2'),
                     SPECIAL_COHORT.format('B3'), SPECIAL_COHORT.format('B4'))
    NON_CONTACTED_BUCKET = (JULO_B1_NC, JULO_B2_NC, JULO_B3_NC, JULO_B4_NC)
    # Final call experiment
    BUCKET_1_EXPERIMENT = 'JULO_B1_EXPERIMENT'
    ALL_B3_BUCKET_LIST = (
        JULO_B3,
        JULO_B3_NC,
        'cohort_campaign_JULO_B3_NON_CONTACTED',
        'cohort_campaign_JULO_B3',
        'special_cohort_B3_NC',
        'special_cohort_B3'
    )
    #  Dana Collection Integration
    DANA_B1 = 'DANA_B1'
    DANA_B2 = 'DANA_B2'
    DANA_B3 = 'DANA_B3'
    DANA_B4 = 'DANA_B4'
    DANA_B5 = 'DANA_B5'
    DANA_T0 = 'DANA_T0'
    DANA_BUCKET = (DANA_B1, DANA_B2, DANA_B3, DANA_B4, DANA_B5)
    DANA_CURRENT_BUCKET = (DANA_T0)
    # JTurbo collection
    JTURBO_B1 = 'JTURBO_B1'
    JTURBO_B1_NC = 'JTURBO_B1_NON_CONTACTED'
    JTURBO_B2 = 'JTURBO_B2'
    JTURBO_B2_NC = 'JTURBO_B2_NON_CONTACTED'
    JTURBO_B3 = 'JTURBO_B3'
    JTURBO_B3_NC = 'JTURBO_B3_NON_CONTACTED'
    JTURBO_B4 = 'JTURBO_B4'
    JTURBO_B4_NC = 'JTURBO_B4_NON_CONTACTED'
    # mapping JTurbo for special cohort
    JTURBO_SPECIAL_COHORT = {
        JTURBO_B1: 'jturbo_special_cohort_B1',
        JTURBO_B1_NC: 'jturbo_special_cohort_B1_NC',
        JTURBO_B2: 'jturbo_special_cohort_B2',
        JTURBO_B2_NC: 'jturbo_special_cohort_B2_NC',
        JTURBO_B3: 'jturbo_special_cohort_B3',
        JTURBO_B3_NC: 'jturbo_special_cohort_B3_NC',
        JTURBO_B4: 'jturbo_special_cohort_B4',
        JTURBO_B4_NC: 'jturbo_special_cohort_B4_NC',
    }
    JTURBO_T_5 = 'JTURBO_T-5'
    JTURBO_T_3 = 'JTURBO_T-3'
    JTURBO_T_1 = 'JTURBO_T-1'
    JTURBO_T_MINUS = 'JTURBO_T_MINUS'
    JTURBO_T0 = 'JTURBO_T0'
    CURRENT_BUCKET_V2 = (JULO_T_5, JULO_T_3, JULO_T_1, JTURBO_T_5, JTURBO_T_3, JTURBO_T_1)
    # all bucket below use collection_dialer_temporary_data
    ALL_BUCKET_IMPROVED = (
        JULO_B1, JULO_B1_NC, JULO_B2, JULO_B2_NC, JULO_B3, JULO_B3_NC, JTURBO_B1, JTURBO_B1_NC,
        JTURBO_B2, JTURBO_B2_NC, JTURBO_B3, JTURBO_B3_NC, JTURBO_B4, JTURBO_B4_NC
    )


class IntelixIcareIncludedCompanies(object):
    ICARE_COMPANIES = ['Blue Bird', 'Bluebird', 'Bluebird Halim PK']


class ReasonNotSentToDialer(object):
    # why using "''" for used in extra condition ORM
    UNSENT_REASON = {
        'PENDING_REFINANCING': "'Pending Refinancing'",
        'ACCOUNT_STATUS_410': "'Account Status is 410'",
        'ACCOUNT_STATUS_431': "'Account Status is 431'",
        'ACCOUNT_STATUS_432': "'Account Status is 432'",
        'ACCOUNT_STATUS_433': "'Account Status is 433'",
        'LOAN_STATUS_210': "'Loan Status is 210'",
        'LOAN_STATUS_250': "'Loan Status is 250'",
        'LOAN_STATUS_260': "'Loan Status is 260'",
        'PARTNER_ACCOUNT': "'Partner account'",
        'LOAN_TO_THIRD_PARTY': "'Loan is assigned to 3rd party'",
        'ACCOUNT_TO_THIRD_PARTY': "'Account is assigned to 3rd party'",
        'PTP_GREATER_TOMMOROW': "'PTP date > tomorrow'",
        'COLLECTION_CALLED_AND_WHATSAPP': "'is_collection_called = TRUE and is_whatsapp = TRUE'",
        'COLLECTION_CALLED': "'is_collection_called = TRUE'",
        'IGNORE_CALLS': "'is_ignore_calls = TRUE'",
        'NON_RISKY_CUSTOMERS': "'Non-Risky Customers'",
        'T0_CRITERIA_COOTEK_CALLING': "'T0 Cootek calling status doesnt fulfill criteria of "
                                      "getting sent to dialer'",
        'EXCLUDED_FROM_BUCKET': "'excluded_from_bucket = TRUE'",
        'NON_CONTACTED_PAYMENT_NOT_OLDEST': "'Non Contacted Payment is not oldest on loan'",
        'UNKNOWN': "'UNKNOWN'",
        'USER_REQUESTED_INTELIX_REMOVAL': "'user_requested_intelix_removal'",
        'SENDING_B3_TO_VENDOR': "'sending b3 to vendor'",
        'EXCLUDED_DUE_TO_AUTODEBET': "'excluded due to autodebet'",
        'BLOCKED_BY_INTELIX_TRAFFIC_FEATURE': "'blocked by intelix traffic feature'",
        'POC_AIRUDDER': "'poc airudder'",
        'USER_REQUESTED_DIALER_SERVICE_REMOVAL': "'user_requested_dialer_service_removal'",
        'BLOCKED_BY_DIALER_SERVICE_TRAFFIC_FEATURE': "'blocked by dialer service traffic feature'",
        'ACCOUNT_SOLD_OFF': "'account sell off'",
        'MATCHMAKING_EXPERIMENT': "'matchmaking experiment'",
        'CREDGENICS_INTEGRATION': "'credgenics integration'",
        'ASSIGNED_COLLECTION_FIELD': "'assigned to field collection agent'",
        'NEW_PDS_EXPERIMENT': "'Experiment'",
        'EXCLUDE_JULO_GOLD': "'julo gold customer'",
        'EXECUTE_JULO_GOLD': "'not julo gold customer'",
        'OMNICHANNEL_EXCLUSION': "'omnichannel exclusion'",
        'INEFFECTIVE_PHONE_NUMBER': "'ineffective_phone_number'",
    }


class GenesysResultChoiceMapping(object):
    MAPPING_STATUS = {
        'ININ-OUTBOUND-BUSY': 'Busy',
        'ININ-OUTBOUND-PREVIEW-ERROR-PHONE-NUMBER': 'Salah Nomor',
        'ININ-OUTBOUND-INVALID-PHONE-NUMBER': 'Salah Nomor',
        'ININ-OUTBOUND-NUMBER_COULD_NOT_BE_DIALED': 'Salah Nomor',
        'OUTBOUND-INVALID-PHONE-NUMBER': 'Salah Nomor',
        'ININ-OUTBOUND-NO-ANSWER': 'Tidak Diangkat',
        'ININ-OUTBOUND-FAX': 'Mesin Fax',
        'ININ-OUTBOUND-MACHINE': 'Answering Machine - System',
        'ININ-OUTBOUND-LINE-CONNECTED': 'Answering Machine - System',
        'ININ-OUTBOUND-CAMPAIGN-RECYCLE-CANCELLED-RECALL': 'No Contact / End of Campaign',
        'ININ-OUTBOUND-CAMPAIGN-FORCED-OFF': 'No Contact / End of Campaign',
        'ININ-OUTBOUND-SIT-CALLABLE': 'Unreachable',
        'ININ-OUTBOUND-AMBIGUOUS': 'No Interaction Status',
        'ININ-OUTBOUND-INTERNAL-ERROR-SKIPPED': 'Disconnect by System',
        'ININ-OUTBOUND-TRANSFERRED-TO-QUEUE': 'Abandoned by System',
        'ININ-OUTBOUND-FAILED-TO-REACH-AGENT': 'Abandoned by Customer',
        'ININ-OUTBOUND-DISCONNECT': 'Abandoned by Customer',
        'ININ-OUTBOUND-SIT-UNCALLABLE': 'Call Failed',
        'ININ-OUTBOUND-PREVIEW-SKIPPED': 'Agent Skip',
        'ININ-OUTBOUND-CALLBACK-DISCONNECT': 'Callback Disconnect',
        'ININ-OUTBOUND-CONTACT-ATTEMPT-LIMIT-SKIPPED': 'Exceed Max Limit',
        'ININ-OUTBOUND-NUMBER-ATTEMPT-LIMIT-SKIPPED': 'Exceed Max Limit',
        'ININ-OUTBOUND-ON-DO-NOT-CALL-LIST': 'Do Not Call (DNC)',
        'ININ-OUTBOUND-DNC-AUTHENTICATION-FAILED': 'Do Not Call (DNC)',
        'ININ-OUTBOUND-DNC-SKIPPED': 'Do Not Call (DNC)',
        'ININ-OUTBOUND-RULE-SKIPPED': 'Rule',
        'ININ-OUTBOUND-RULE-ERROR-SKIPPED': 'Rule',
        'ININ-OUTBOUND-CONTACT-UNCALLABLE-SKIPPED': 'Rule',
        'ININ-OUTBOUND-NO-CALLABLE-NUMBERS-SKIPPED': 'Rule',
        'ININ-OUTBOUND-NUMBER-UNCALLABLE-SKIPPED': 'Rule',
        'ININ-OUTBOUND-NOT-CALLABLE-TIME': 'Rule',
        'ININ-OUTBOUND-AUTOMATIC-TIMEZONE-BLOCKED': 'Rule',
        'ININ-OUTBOUND-AUTOMATIC-TIME-ZONE-BLOCKED-SKIPPED': 'Rule',
        'ININ-OUTBOUND-EXTERNALLY-THROTTLED': 'Edge',
        'ININ-OUTBOUND-STUCK-INTERACTION': 'Edge',
        'ININ-OUTBOUND-NO-ACTIVE-EDGES': 'Edge',
        'ININ-OUTBOUND-TRANSFERRED-TO-FLOW': 'Flow',
        'ININ-OUTBOUND-NOT-TRANSFERRED-TO-FLOW': 'Flow',
        'ININ-OUTBOUND-FAILED-TO-REACH-FLOW': 'Flow',
        'ININ-OUTBOUND-LIVE-VOICE': 'Flow',
        'ININ-OUTBOUND-RECALL-CANCELLED': 'Flow',
        'ININ-OUTBOUND-CONTACT-NOT-FOUND': 'Flow',
        'OUTBOUND-MESSAGE-SENT': 'Message',
        'OUTBOUND-MESSAGE-FAILED': 'Message',
        'OUTBOUND-MAX-MESSAGE-LENGTH-EXCEEDED': 'Message',
        'OUTBOUND-MESSAGE-BLANK': 'Message',
        'OUTBOUND-STUCK-CONTACT': 'Message',
    }


class IntelixAPICallbackConst(object):
    SUCCESS = 'SUCCESS'


CALL_RESULT_DOWNLOAD_CHUNK = 1000


class FilterQueryBucket(object):
    FILTER_QUERY_BUCKET = [
        "Intelix Bucket 1 Low OSP",
        "Intelix Bucket 1 High OSP",
        "Intelix Bucket 2 Low OSP",
        "Intelix Bucket 2 High OSP",
        "Intelix Risky Bucket - Heimdall v6"
    ]


class ErrorMessageProcessDownloadManualUploadIntelix(object):
    FAILED_RUN_QUERY = 'failed_run_query'


class FeatureNameConst(object):
    TAKING_OUT_GRAB_FROM_INTELIX = 'taking_out_grab_from_intelix'
    INTELIX_BATCHING_POPULATE_DATA_CONFIG = 'intelix_batching_populate_data_config'
    HIDE_KTP_SELFIE_IMAGE_J1_ALL_300 = 'hide_ktp_selfie_image_j1_all_300'
    HANDLING_DIALER_ALERT = 'handling_dialer_alert'
    LIMITATION_FOR_GET_DATA_AIRUDDER_API = 'limitation_for_get_data_airudder_api'
    AIRUDDER_RECOMMENDED_TIMEOUT = 'airudder_recommended_timeout'
    AI_RUDDER_FULL_ROLLOUT = 'ai_rudder_full_rollout'
    AI_RUDDER_GROUP_NAME_CONFIG = 'ai_rudder_group_name_config'
    AI_RUDDER_TASKS_STRATEGY_CONFIG = 'ai_rudder_tasks_strategy_config'
    AI_RUDDER_SEND_SLACK_ALERT = 'ai_rudder_send_slack_alert'
    AI_RUDDER_SEND_BATCHING_THRESHOLD = 'ai_rudder_send_batching_threshold'
    BLOCK_TRAFFIC_INTELIX = 'block_traffic_intelix'
    DANA_AI_RUDDER_SEPARATED_BUCKET = 'dana_ai_rudder_separated_bucket'
    AI_RUDDER_BATCHING_POPULATE_DATA_CONFIG = 'ai_rudder_batching_populate_data_config'
    GRAB_AI_RUDDER_TASKS_STRATEGY_CONFIG = 'grab_ai_rudder_tasks_strategy_config'
    CASHBACK_NEW_SCHEME = 'cashback_new_scheme'
    HANGUP_REASON_RETROLOAD = 'hangup_reason_retroload'
    DIALER_DISCREPANCIES = 'DIALER_DISCREPANCIES'
    DA2M_ACCOUNTS_EXPERIMENT = 'da2m_accounts_experiment'
    SENT_TO_DIALER_RETROLOAD = 'sent_to_dialer_retroload'
    PERMANENT_RISK_BLOCK_CUSTOMER_DISBURSEMENT = 'permanent_risk_block_customer_disbursement'
    WARNING_LETTER_CONFIG = 'warning_letter_config'
    ADDITIONAL_PTP_FILTER_FOR_B5 = 'additional_ptp_filter_for_b5'
    SPLIT_MINUTES_CALL_RESULT = 'split_minutes_call_result'
    BUCKET_FIELD_COLLECTION_EXCLUDED = 'bucket_field_collection_excluded'
    BUCKET_6_FEATURE_FLAG = 'b6_feature_flag'
    COLLECTION_DETOKENIZE = "collection_detokenize"
    DIALER_IN_BULK_DETOKENIZED_METHOD = "dialer_in_bulk_detokenized_method"
    WAIVER_R4_PROMO_BLAST = "waiver_r4_promo_blast"
    BUCKET_RECOVERY_DISTRIBUTION = "bucket_recovery_distribution"
    PHYSICAL_WARNING_LETTER = 'physical_warning_letter'
    PASS_OTHER_NUMBER_TO_PDS = "pass_other_number_to_pds"
    SERVERLESS_COPY_TASK_CONFIG = "serverless_copy_task_config"
    INEFFECTIVE_PHONE_NUMBER_TO_PDS = "ineffective_phone_number_to_pds"
    RECOVERY_BUCKET_EXCLUSION_PARTNER = "recovery_bucket_exclusion_partner"
    PHYSICAL_WARNING_LETTER_ONE_TIME = 'physical_warning_letter_one_time'
    MANUAL_DC_AGENT_ASSIGNMENT = 'manual_dc_agent_assignment'
    KANGTAU_CUSTOMER_BUCKET_QUOTA = 'kangtau_customer_bucket_quota'
    PHYSICAL_WARNING_LETTER_BUCKET_B5_PLUS = 'physical_warning_letter_bucket_b5_plus'


class ExperimentConst(object):
    COLLECTION_TAILOR_EXPERIMENT = 'collection_tailor_experiment'
    COLLECTION_TAILORED_EXPERIMENT_ROBOCALL = 'collection_tailored_experiment_robocall'
    FINAL_CALL_REEXPERIMENT = 'final_call_reexperiment'
    PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_CODE = 'colldialerexp3'
    PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_NAME = 'predictive_dialer_experiment_airudder'
    LATE_FEE_EARLIER_EXPERIMENT = 'late_fee_earlier_experiment'
    CASHBACK_NEW_SCHEME = 'cashback_new_scheme'
    SMS_AFTER_ROBOCALL = 'sms_after_robocall'
    EMERGENCY_CONTACT_EXPERIMENT = 'emergency_contact_experiment'
    MERGE_NON_CONTACTED_BUCKET = 'merge_non_contacted_bucket'
    B1_SPLIT_GROUP_EXPERIMENT = 'b1_split_group_experiment'
    BTTC_EXPERIMENT = 'BTTC_Experiment'
    DELINQUENT_BTTC_EXPERIMENT = 'Delinquent_BTTC_Experiment'
    NEW_PDS = 'new_pds'
    SMS_REMINDER_OMNICHANNEL_EXPERIMENT = 'sms_reminder_omnichannel_experiment'
    COLLECTION_SORT_CALL_PRIORITY_EXPERIMENT = 'collection_sort_call_priority_experiment'
    COLLECTION_SORT_RISKIER_CUSTOMER = 'collection_sort_riskier_customer'
    CASHBACK_CLAIM_EXPERIMENT = 'cashback_claim_experiment'
    COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT = 'collection_sort_call_priority_v2_experiment'


class GoogleCalendar(object):
    SEND_GOOGLE_CALENDAR_SINGLE_METHOD = 'send_google_calendar_single_method'
    STATUS_CODE_ERROR = [400, 401, 403, 404, 409, 410, 412, 429, 500]
    MAX_PARTICIPANTS = 500


class AiRudder(object):
    AI_RUDDER_SOURCE = 'AiRudder'

    TASK_STATUS_CALLBACK_TYPE = 'TaskStatus'
    AGENT_STATUS_CALLBACK_TYPE = 'AgentStatus'
    CONTACT_STATUS_CALLBACK_TYPE = 'ContactStatus'

    TRIGGER_B5_CALLBACK_TYPE = 'Trigger Callback B5'

    TALK_RESULT_LABEL_PTP = 'PTP'

    DATE_TIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

    STATE_CALLING = 'CALLING'
    STATE_RINGING = 'RINGING'
    STATE_ANSWERED = 'ANSWERED'
    STATE_HANGUP = 'HANGUP'
    STATE_TALKRESULT = 'TALKRESULT'
    STATE_FINISHED = 'Finished'

    START_TS_STATE = [STATE_CALLING]
    END_TS_STATE = [STATE_RINGING, STATE_ANSWERED, STATE_HANGUP]

    HANGUP_REASON_STATUS_GROUP_MAP = {
        0: 'NULL',
        1: 'Abandoned by System',
        2: 'Tidak Diangkat',
        3: 'Busy',
        4: 'Unreachable',
        5: 'Busy',
        6: 'Unreachable',
        7: 'Unreachable',
        8: 'Unreachable',
        9: 'Unreachable',
        12: 'NULL',
        13: 'NULL',
        14: 'Abandoned by Customer',
        15: 'Abandoned by System',
        16: 'NULL',
        17: 'Disconnect By Network',
        18: 'NULL',
        19: 'Abandoned by System',
        20: 'NULL',
    }

    SKIPTRACE_RESULT_CHOICE_MAP = {
        'NotConnected': 'Not Connected',
        'ShortCall': 'Short Call',
        'RPC-Regular': 'RPC - Regular',
        'RPC-PTP': 'RPC - PTP',
        'RPC-HTP': 'RPC - HTP',
        'RPC-BrokenPromise': 'RPC - Broken Promise',
        'RPC-CallBack': 'RPC - Call Back',
        'WPC-Regular': 'WPC - Regular',
        'WPC-LeftMessage': 'WPC - Left Message',
        'AnsweringMachine': 'Answering Machine',
        'BusyTone': 'Busy Tone',
        'DeadCall': 'Dead Call',
        'WAText': 'Whatsapp - Text',
        'RPC-LeftMessage': 'RPC - Left Message',
        'RPC-AlreadyPTP': 'RPC - Already PTP',
        'RPC-AlreadyPaid': 'RPC - Already Paid',
        'RPC-Already_Paid': 'RPC - Already Paid',  # add status to handle potential mismatch
        'Whatsapp-Checklist1': 'Whatsapp - Checklist 1',
        'Whatsapp-Checklist2': 'Whatsapp - Checklist 2',
        'Whatsapp-NotAvailable': 'Whatsapp - Not Available',
        'RPC-Whatsapp': 'RPC - Whatsapp',
        'WPC-Whatsapp': 'WPC - Whatsapp',
        'PTP-Whatsapp': 'PTP - Whatsapp',
        'Telegram-Text': 'Telegram - Text',
        'Telegram-Checklist1': 'Telegram - Checklist 1',
        'Telegram-Checklist2': 'Telegram - Checklist 2',
        'Telegram-NotAvailable': 'Telegram - Not Available',
        'RPC-Telegram': 'RPC - Telegram',
        'WPC-Telegram': 'WPC - Telegram',
        'PTP-Telegram': 'PTP - Telegram',
        'ACW-Interrupt': 'ACW - Interrupt',
    }

    PTP_DATE_PATTERN = r"\d{4}-\d{2}-\d{2}"

    HANGUP_REASON_PDS = {
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
    DANA = 'dana'
    DANA_TEMPLATE_NAME = "julo_dana"
    GRAB = 'GRAB'
    GRAB_TEMPLATE_NAME = "julo_grab"
    SALES_OPS = "sales_ops"
    SALES_OPS_TEMPLATE_NAME = "pds_default"
    SOURCE_WEB = 'web'
    J1_ELIGIBLE_PRODUCT = ['J1', 'J-STARTER']
    ASYNCHRONOUS_METHOD = 'asynchronous'
    SYNCHRONOUS_METHOD = 'synchronous'
    TASK_NAME_CONTAINS_MANUAL_UPLOAD = [
        'manual',
        'airudder',
        'sample',
        'courtessy',
        'julo_b5',
        'julo_b6',
        'inhouse',
        'risk',
        'upload',
    ]
    PERSONAL_CONTACT_SOURCE = ["mobile_phone_1", 'mobile_phone_2']
    COMPANY_CONTACT_SOURCE = ["company_phone_number", 'telp_perusahaan']
    KIN_CONTACT_SOURCE = [
        "kin_mobile_phone",
        'close_kin_mobile_phone',
        'spouse_mobile_phone',
        'no_telp_pasangan',
    ]
    MJOLNIR_CONTACT_SOURCE = PERSONAL_CONTACT_SOURCE + COMPANY_CONTACT_SOURCE + KIN_CONTACT_SOURCE
    MJOLNIR_USER_TYPE = {
        "mobile_phone_1": "User Call",
        "mobile_phone_2": "User Call",
        "company_phone_number": "Company",
        "telp_perusahaan": "Company",
        "kin_mobile_phone": "Kin Call",
        "close_kin_mobile_phone": "Kin Call",
        "spouse_mobile_phone": "Kin Call",
        "no_telp_pasangan": "Kin Call",
    }
    EVER_RPC_STATUSES = [
        'RPC - Broken Promise',
        'RPC - Call Back',
        'RPC - HTP',
        'RPC - PTP',
        'RPC - Regular',
        'RPC - Already PTP',
        'RPC - Already Paid',
        'RPC - Whatsapp',
        'RPC - Telegram',
    ]
    ALLOWED_DIALING_ORDER = [
        'mobile_phone_2',
        'telp_perusahaan',
        'mobile_phone_1_2',
        'mobile_phone_2_2',
        'no_telp_pasangan',
        'mobile_phone_1_3',
        'mobile_phone_2_3',
        'no_telp_kerabat',
        'mobile_phone_1_4',
        'mobile_phone_2_4',
    ]
    UNREACHABLE_HANGUP_IDS = [4, 6, 7, 8, 9]
    NOT_CONNECTED_CALL_STATUS_LIST = [
        "Unreachable",
        "Tidak Diangkat",
        "Short Call",
        "Ringing",
        "NULL",
        "Disconnect By Network",
        "Dead Call",
        "Busy Tone",
        "Busy",
        "Answering Machine",
        "Abandoned by System",
        "Abandoned by Customer",
    ]


class AIRudderPDSConstant(object):
    REQUEST_MAX_RETRY_COUNT = 5
    SUCCESS_MESSAGE_RESPONSE = 'successfully'


class DialerSystemConst(object):
    AI_RUDDER_PDS = 'AIRudderPDS'
    INTELIX_DIALER_SYSTEM = 'IntelixDialerSystem'
    DIALER_BUCKET_0 = 'JULO_T0'
    DIALER_JTURBO_T0 = 'JTURBO_T0'
    DIALER_BUCKET_1 = 'JULO_B1'
    DIALER_BUCKET_1_NC = 'JULO_B1_NON_CONTACTED'
    DIALER_BUCKET_3 = 'JULO_B3'
    DIALER_BUCKET_3_NC = 'JULO_B3_NON_CONTACTED'
    DIALER_BUCKET_2 = 'JULO_B2'
    DIALER_BUCKET_2_NC = 'JULO_B2_NON_CONTACTED'
    DIALER_BUCKET_4 = 'JULO_B4'
    DIALER_BUCKET_6_1 = 'JULO_B6_1'
    DIALER_BUCKET_4_NC = 'JULO_B4_NON_CONTACTED'
    DIALER_BUCKET_5 = 'JULO_B5'
    DIALER_BUCKET_5_NC = 'JULO_B5_NON_CONTACTED'
    DIALER_JTURBO_B1 = 'JTURBO_B1'
    DIALER_JTURBO_B1_NON_CONTACTED = 'JTURBO_B1_NON_CONTACTED'
    DIALER_JTURBO_B2 = 'JTURBO_B2'
    DIALER_JTURBO_B2_NON_CONTACTED = 'JTURBO_B2_NON_CONTACTED'
    DIALER_JTURBO_B3 = 'JTURBO_B3'
    DIALER_JTURBO_B3_NON_CONTACTED = 'JTURBO_B3_NON_CONTACTED'
    DIALER_JTURBO_B4 = 'JTURBO_B4'
    DIALER_JTURBO_B4_NON_CONTACTED = 'JTURBO_B4_NON_CONTACTED'
    DIALER_SPECIAL_COHORT = 'special_cohort_{}'
    DIALER_JTURBO_SPECIAL_COHORT = {
        DIALER_JTURBO_B1: 'jturbo_special_cohort_B1',
        DIALER_JTURBO_B1_NON_CONTACTED: 'jturbo_special_cohort_B1_NC',
        DIALER_JTURBO_B2: 'jturbo_special_cohort_B2',
        DIALER_JTURBO_B2_NON_CONTACTED: 'jturbo_special_cohort_B2_NC',
        DIALER_JTURBO_B3: 'jturbo_special_cohort_B3',
        DIALER_JTURBO_B3_NON_CONTACTED: 'jturbo_special_cohort_B3_NC',
        DIALER_JTURBO_B4: 'jturbo_special_cohort_B4',
        DIALER_JTURBO_B4_NON_CONTACTED: 'jturbo_special_cohort_B4_NC',
    }
    DIALER_DATA_GENERATION_BUCKET = {
        'JULO_B1': DIALER_BUCKET_1,
        'JULO_B2': DIALER_BUCKET_2,
        'JULO_B3': DIALER_BUCKET_3,
        'JULO_B4': DIALER_BUCKET_4,
        'JULO_B6_1': DIALER_BUCKET_6_1,
        'JTURBO_B1': DIALER_JTURBO_B1,
        'JTURBO_B2': DIALER_JTURBO_B2,
        'JTURBO_B3': DIALER_JTURBO_B3,
        'JTURBO_B4': DIALER_JTURBO_B4,
    }
    DIALER_T_MINUS = 'JULO_T{}'
    DIALER_T_MINUS_BUCKET_NAME = 'JULO_T_MINUS'
    DIALER_JTURBO_T_MINUS = 'JTURBO_T{}'
    DIALER_T_MINUS_BUCKET_LIST = [
        DIALER_T_MINUS.format(-1),
        DIALER_T_MINUS.format(-3),
        DIALER_T_MINUS.format(-5),
        DIALER_JTURBO_T_MINUS.format(-1),
        DIALER_JTURBO_T_MINUS.format(-3),
        DIALER_JTURBO_T_MINUS.format(-5),
    ]
    DIALER_BUCKET_ALREADY_SORTED = DIALER_T_MINUS_BUCKET_LIST + [
        DIALER_BUCKET_6_1,
        DIALER_BUCKET_1,
        DIALER_BUCKET_2,
        DIALER_BUCKET_3,
    ]
    DIALER_T_0_BUCKET_LIST = [DIALER_BUCKET_0, DIALER_JTURBO_T0]
    DANA_B_ALL = 'DANA_B_ALL'
    DANA_BUCKET_CICIL = 'DANA_BUCKET_CICIL'
    DANA_BUCKET_CASHLOAN = 'DANA_BUCKET_CASHLOAN'
    DANA_BUCKET_SIM = 'DANA_BUCKET_SIM'
    DANA_BUCKET_PEPPER = 'DANA_BUCKET_PEPPER'
    DANA_BUCKET_91_PLUS = 'DANA_BUCKET_91_PLUS'

    # Dana AiRudder Group Name
    GROUP_DANA_B_ALL = 'Group_Dana_Bucket_All'
    GRAB = 'GRAB'
    GRAB_90_PLUS = 'GRAB_90+'

    EXCLUSION_ACCOUNT_STATUS = 'EXCLUSION_ACCOUNT_STATUS'
    EXCLUSION_PENDING_REFINANCING = 'EXCLUSION_PENDING_REFINANCING'
    EXCLUSION_ACTIVE_PTP = 'EXCLUSION_ACTIVE_PTP'
    EXCLUSION_INTELIX_BLACKLIST = 'EXCLUSION_INTELIX_BLACKLIST'
    EXCLUSION_AUTODEBET_ACTIVE = 'EXCLUSION_AUTODEBET_ACTIVE'
    EXCLUSION_EVER_ENTERED_B6_1 = 'EXCLUSION_EVER_ENTERED_B6_1'
    EXCLUSION_GOJEK_TSEL_PRODUCT = 'EXCLUSION_GOJEK_TSEL_PRODUCT'
    RECOVERY_BUCKET_5_EXCLUDE_LIST = (
        EXCLUSION_ACCOUNT_STATUS,
        EXCLUSION_PENDING_REFINANCING,
        EXCLUSION_ACTIVE_PTP,
        EXCLUSION_INTELIX_BLACKLIST,
        EXCLUSION_AUTODEBET_ACTIVE,
        EXCLUSION_EVER_ENTERED_B6_1,
        EXCLUSION_GOJEK_TSEL_PRODUCT,
    )
    RECOVERY_BUCKET_UNSENT_REASON_MAPPING = {
        EXCLUSION_ACCOUNT_STATUS: 'Account Status is {}',
        EXCLUSION_PENDING_REFINANCING: 'Pending Refinancing',
        EXCLUSION_ACTIVE_PTP: 'PTP date > tomorrow',
        EXCLUSION_INTELIX_BLACKLIST: 'blocked by intelix traffic feature',
        EXCLUSION_AUTODEBET_ACTIVE: 'excluded due to autodebet',
        EXCLUSION_EVER_ENTERED_B6_1: 'Account is ever entered bucket 6.1',
        EXCLUSION_GOJEK_TSEL_PRODUCT: 'Account is gojek tsel product',
    }
    RECOVERY_BUCKET_6_EXCLUDE_LIST = (
        EXCLUSION_ACCOUNT_STATUS,
        EXCLUSION_PENDING_REFINANCING,
        EXCLUSION_ACTIVE_PTP,
        EXCLUSION_INTELIX_BLACKLIST,
        EXCLUSION_AUTODEBET_ACTIVE,
        EXCLUSION_GOJEK_TSEL_PRODUCT,
    )
    B2_EXPERIMENT_POC_C_ICARE = 'B2_experiment'
    DIALER_BUCKET_FC_B1 = "JULO_FC_B1"
    BASE_DIALER_J1 = 'JULO_B{}'
    BASE_DIALER_JTURBO = 'JTURBO_B{}'


class TMinusConst(object):
    T_MINUS_CONST = [
        {
            'dpd': -5,
            'dialer_type': DialerTaskType.UPLOAD_JULO_T_5,
            'intelix_team': IntelixTeam.JULO_T_5
        },
        {
            'dpd': -3,
            'dialer_type': DialerTaskType.UPLOAD_JULO_T_3,
            'intelix_team': IntelixTeam.JULO_T_3
        },
        {
            'dpd': -1,
            'dialer_type': DialerTaskType.UPLOAD_JULO_T_1,
            'intelix_team': IntelixTeam.JULO_T_1
        },
        {
            'dpd': -5,
            'dialer_type': DialerTaskType.UPLOAD_JTURBO_T_5,
            'intelix_team': IntelixTeam.JTURBO_T_5
        },
        {
            'dpd': -3,
            'dialer_type': DialerTaskType.UPLOAD_JTURBO_T_3,
            'intelix_team': IntelixTeam.JTURBO_T_3
        },
        {
            'dpd': -1,
            'dialer_type': DialerTaskType.UPLOAD_JTURBO_T_1,
            'intelix_team': IntelixTeam.JTURBO_T_1
        }
    ]


class DialerServiceTeam(object):
    JULO_B1 = 'JULO_B1'
    JULO_B1_NC = 'JULO_B1_NON_CONTACTED'
    JULO_B2 = 'JULO_B2'
    JULO_B2_NC = 'JULO_B2_NON_CONTACTED'
    JULO_B3 = 'JULO_B3'
    JULO_B3_NC = 'JULO_B3_NON_CONTACTED'
    JULO_B4 = 'JULO_B4'
    JULO_B4_NC = 'JULO_B4_NON_CONTACTED'
    JULO_B5 = 'JULO_B5'
    JULO_B6_1 = 'JULO_B6_1'
    JULO_B6_2 = 'JULO_B6_2'
    JULO_B6_3 = 'JULO_B6_3'
    JULO_B6_4 = 'JULO_B6_4'
    JULO_T_5 = 'JULO_T-5'
    JULO_T_3 = 'JULO_T-3'
    JULO_T_1 = 'JULO_T-1'
    JULO_T_MINUS = 'JULO_T_MINUS'
    GRAB = 'GRAB'
    SPECIAL_COHORT = 'special_cohort_{}'
    # COOTEK
    JULO_T0 = 'JULO_T0'
    SHARED_BUCKET = 'Experiment Shared Bucket'
    ALL_BUCKET_5_TEAM = (JULO_B5, JULO_B6_1, JULO_B6_2)
    CURRENT_BUCKET = (JULO_B5, JULO_B6_1, JULO_B6_2, JULO_T_5, JULO_T_3, JULO_T_1)
    SORTED_BUCKET = (SPECIAL_COHORT.format('B1'), SPECIAL_COHORT.format('B2'),
                     SPECIAL_COHORT.format('B3'), SPECIAL_COHORT.format('B4'))
    NON_CONTACTED_BUCKET = (JULO_B1_NC, JULO_B2_NC, JULO_B3_NC, JULO_B4_NC)
    # Final call experiment
    BUCKET_1_EXPERIMENT = 'JULO_B1_EXPERIMENT'
    ALL_B3_BUCKET_LIST = (
        JULO_B3,
        JULO_B3_NC,
        'cohort_campaign_JULO_B3_NON_CONTACTED',
        'cohort_campaign_JULO_B3',
        'special_cohort_B3_NC',
        'special_cohort_B3'
    )
    #  Dana Collection Integration
    DANA_B1 = 'DANA_B1'
    DANA_B2 = 'DANA_B2'
    DANA_B3 = 'DANA_B3'
    DANA_B4 = 'DANA_B4'
    DANA_B5 = 'DANA_B5'
    DANA_T0 = 'DANA_T0'
    DANA_BUCKET = (DANA_B1, DANA_B2, DANA_B3, DANA_B4, DANA_B5)
    DANA_CURRENT_BUCKET = (DANA_T0)
    # JTurbo collection
    JTURBO_B1 = 'JTURBO_B1'
    JTURBO_B1_NC = 'JTURBO_B1_NON_CONTACTED'
    JTURBO_B2 = 'JTURBO_B2'
    JTURBO_B2_NC = 'JTURBO_B2_NON_CONTACTED'
    JTURBO_B3 = 'JTURBO_B3'
    JTURBO_B3_NC = 'JTURBO_B3_NON_CONTACTED'
    JTURBO_B4 = 'JTURBO_B4'
    JTURBO_B4_NC = 'JTURBO_B4_NON_CONTACTED'
    # mapping JTurbo for special cohort
    JTURBO_SPECIAL_COHORT = {
        JTURBO_B1: 'jturbo_special_cohort_B1',
        JTURBO_B1_NC: 'jturbo_special_cohort_B1_NC',
        JTURBO_B2: 'jturbo_special_cohort_B2',
        JTURBO_B2_NC: 'jturbo_special_cohort_B2_NC',
        JTURBO_B3: 'jturbo_special_cohort_B3',
        JTURBO_B3_NC: 'jturbo_special_cohort_B3_NC',
        JTURBO_B4: 'jturbo_special_cohort_B4',
        JTURBO_B4_NC: 'jturbo_special_cohort_B4_NC',
    }
    JTURBO_T_5 = 'JTURBO_T-5'
    JTURBO_T_3 = 'JTURBO_T-3'
    JTURBO_T_1 = 'JTURBO_T-1'
    JTURBO_T_MINUS = 'JTURBO_T_MINUS'
    JTURBO_T0 = 'JTURBO_T0'
    CURRENT_BUCKET_V2 = (JULO_T_5, JULO_T_3, JULO_T_1, JTURBO_T_5, JTURBO_T_3, JTURBO_T_1)
    # all bucket below use collection_dialer_temporary_data
    ALL_BUCKET_IMPROVED = (
        JULO_B1, JULO_B1_NC, JULO_B2, JULO_B2_NC, JULO_B3, JULO_B3_NC, JTURBO_B1, JTURBO_B1_NC,
        JTURBO_B2, JTURBO_B2_NC, JTURBO_B3, JTURBO_B3_NC, JTURBO_B4, JTURBO_B4_NC
    )
    EXCLUSION_FROM_OTHER_BUCKET_LIST = (JULO_B6_1,)
    JULO_B6_1_SORTING_PREPARATION = 'JULO_B6_1_SORTING_PREPARATION'


class ExperimentGroupSource(object):
    GROWTHBOOK = 'Growthbook'


class PIIMappingCustomerXid(object):
    TABLE = {
        'application': 'object.customer.customer_xid',
        'customer': 'object.customer_xid',
    }


class CollectionQueue:
    TOKENIZED_QUEUE = 'collection_pii_vault'


class BTTCExperiment:
    TEST_GROUP_BCURRENT_1 = 'experiment_all_range'
    TEST_GROUP_BCURRENT_2 = 'experiment_max_2'
    TEST_GROUP_BCURRENT_3 = 'experiment_max_3'
    TEST_GROUP_BCURRENTS = [TEST_GROUP_BCURRENT_1, TEST_GROUP_BCURRENT_2, TEST_GROUP_BCURRENT_3]
    BUCKET_NAMES_CURRENT_MAPPING = {
        TEST_GROUP_BCURRENT_1: 'bttc-BC-test1-{}',
        TEST_GROUP_BCURRENT_2: 'bttc-BC-test2-{}',
        TEST_GROUP_BCURRENT_3: 'bttc-BC-test3-{}',
    }
    SENDING_TIME = {
        'a': '08:00',
        'b': '10:00',
        'c': '13:00',
        'd': '16:00',
    }
    BASED_CURRENT_BUCKET_NAME = 'bttc-BC-test{}-{}'
    BASED_T0_NAME = 'bttc-BC-T0-{}'


class NewPDSExperiment(object):
    B2_EXPERIMENT = 'B2_experiment'
    EXPERIMENT_GROUP_A = 2
    EXPERIMENT_GROUP_B = 3


class JuloGold(object):
    JULO_GOLD_SEGMENT = 'julogold'
    JULO_GOLD_EXCLUDE_STATUS = 'exclude'
    JULO_GOLD_EXECUTE_STATUS = 'execute'


class SkiptraceContactSource:
    MOBILE_PHONE_1 = 'mobile_phone_1'
    MOBILE_PHONE_2 = 'mobile_phone_2'
    LANDLORD_MOBILE_PHONE = 'landlord_mobile_phone'
    KIN_MOBILE_PHONE = 'kin_mobile_phone'
    CLOSE_KIN_MOBILE_PHONE = 'close_kin_mobile_phone'
    SPOUSE_MOBILE_PHONE = 'spouse_mobile_phone'
    COMPANY_PHONE_NUMBER = 'company_phone_number'
    FC_CUSTOMER_MOBILE_PHONE = 'fc_cust_mobile_phone'
    APPLICATION_SOURCES = [
        MOBILE_PHONE_1,
        MOBILE_PHONE_2,
        LANDLORD_MOBILE_PHONE,
        KIN_MOBILE_PHONE,
        CLOSE_KIN_MOBILE_PHONE,
        SPOUSE_MOBILE_PHONE,
        COMPANY_PHONE_NUMBER,
    ]


class SkiptraceHistoryEventName(object):
    UNREACHABLE = 'unreachable'
    REACHABLE = 'reachable'
    REMOVE = 'remove'
    REMOVE_START = 'remove_start'


class KangtauCampaignStatus:
    ONGOING = 'ONGOING'
    FINISHED = 'FINISHED'


class KangtauBucketWhitelist:
    BTTC_B1_EXPERIMENT_1_A = 'bttc-B1-experiment1-A'
    BTTC_B1_EXPERIMENT_1_B = 'bttc-B1-experiment1-B'
    BTTC_B1_EXPERIMENT_1_C = 'bttc-B1-experiment1-C'
    BTTC_B1_EXPERIMENT_1_D = 'bttc-B1-experiment1-D'
    BTTC_B1_EXPERIMENT_1_TEST_A = 'bttc-B1-experiment1-test-A'
    BTTC_B1_EXPERIMENT_1_TEST_B = 'bttc-B1-experiment1-test-B'
    BTTC_B1_EXPERIMENT_1_TEST_C = 'bttc-B1-experiment1-test-C'
    BTTC_B1_EXPERIMENT_1_TEST_D = 'bttc-B1-experiment1-test-D'
    BTTC_B1_EXPERIMENT_2_A = 'bttc-B1-experiment2-A'
    BTTC_B1_EXPERIMENT_2_B = 'bttc-B1-experiment2-B'
    BTTC_B1_EXPERIMENT_2_C = 'bttc-B1-experiment2-C'
    BTTC_B1_EXPERIMENT_2_D = 'bttc-B1-experiment2-D'
    BTTC_B1_EXPERIMENT_3_A = 'bttc-B1-experiment3-A'
    BTTC_B1_EXPERIMENT_3_B = 'bttc-B1-experiment3-B'
    BTTC_B1_EXPERIMENT_3_C = 'bttc-B1-experiment3-C'
    BTTC_B1_EXPERIMENT_3_D = 'bttc-B1-experiment3-D'
    BTTC_B1_EXPERIMENT_4_A = 'bttc-B1-experiment4-A'
    BTTC_B1_EXPERIMENT_4_B = 'bttc-B1-experiment4-B'
    BTTC_B1_EXPERIMENT_4_C = 'bttc-B1-experiment4-C'
    BTTC_B1_EXPERIMENT_4_D = 'bttc-B1-experiment4-D'
    JULO_B1_GROUP_A = 'JULO_B1_groupA'
    JULO_B1 = 'JULO_B1'
    JULO_B2 = 'JULO_B2'
    JULO_B3 = 'JULO_B3'
    JULO_B4 = 'JULO_B4'
    JULO_B5 = 'JULO_B5'
    JULO_T0 = 'JULO_T0'
    BTTC_BC_T0_A = 'bttc-BC-T0-A'
    BTTC_BC_T0_B = 'bttc-BC-T0-B'
    BTTC_BC_T0_C = 'bttc-BC-T0-C'
    BTTC_BC_T0_D = 'bttc-BC-T0-D'
    BTTC_BC_TEST3_A = 'bttc-BC-test3-A'
    BTTC_BC_TEST3_B = 'bttc-BC-test3-B'
    BTTC_BC_TEST3_C = 'bttc-BC-test3-C'
    BTTC_BC_TEST3_D = 'bttc-BC-test3-D'
    B0_LIST = [
        JULO_T0,
        BTTC_BC_T0_A,
        BTTC_BC_T0_B,
        BTTC_BC_T0_C,
        BTTC_BC_T0_D,
        BTTC_BC_TEST3_A,
        BTTC_BC_TEST3_B,
        BTTC_BC_TEST3_C,
        BTTC_BC_TEST3_D,
    ]
    B1_LIST = [
        JULO_B1,
        JULO_B1_GROUP_A,
        BTTC_B1_EXPERIMENT_1_A,
        BTTC_B1_EXPERIMENT_1_B,
        BTTC_B1_EXPERIMENT_1_C,
        BTTC_B1_EXPERIMENT_1_D,
        BTTC_B1_EXPERIMENT_1_TEST_A,
        BTTC_B1_EXPERIMENT_1_TEST_B,
        BTTC_B1_EXPERIMENT_1_TEST_C,
        BTTC_B1_EXPERIMENT_1_TEST_D,
        BTTC_B1_EXPERIMENT_2_A,
        BTTC_B1_EXPERIMENT_2_B,
        BTTC_B1_EXPERIMENT_2_C,
        BTTC_B1_EXPERIMENT_2_D,
        BTTC_B1_EXPERIMENT_3_A,
        BTTC_B1_EXPERIMENT_3_B,
        BTTC_B1_EXPERIMENT_3_C,
        BTTC_B1_EXPERIMENT_3_D,
        BTTC_B1_EXPERIMENT_4_A,
        BTTC_B1_EXPERIMENT_4_B,
        BTTC_B1_EXPERIMENT_4_C,
        BTTC_B1_EXPERIMENT_4_D,
    ]
    B2_LIST = [
        JULO_B2,
    ]
    B3_LIST = [
        JULO_B3,
    ]
    B4_LIST = [
        JULO_B4,
    ]
    B5_LIST = [
        JULO_B5,
    ]
