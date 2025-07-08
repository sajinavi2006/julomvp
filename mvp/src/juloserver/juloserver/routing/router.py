"""
router.py
purpose: Override some flows of package
"""
import logging
import threading

from django.db import (
    connections,
    transaction,
)
from django_replicated.router import ReplicationRouter
from django.conf import settings

from juloserver.julocore.cache_client import get_loc_mem_cache


logger = logging.getLogger(__name__)


class CustomReplicationRouter(ReplicationRouter):

    def db_for_read(self, model, *args, **kwargs):
        chosen = super(CustomReplicationRouter, self).db_for_read(model, *args, **kwargs)
        if model.__name__ in settings.IGNORE_MODELS:
            return self.DEFAULT_DB_ALIAS
        return chosen


class JuloDbReplicaDbRouter:
    master_db = 'default'
    replica_db = 'replica'

    dead_cache_duration = 60
    dead_mark = 'dead'
    enable_by_thread_id = []

    @classmethod
    def enable(cls):
        """
        Enabling the read connection to use replica connection.
        Only usable in "partial" mode. And this is thread-safe.
        """
        if not cls._is_partial():
            return

        cls.enable_by_thread_id.append(threading.get_ident())

    @classmethod
    def disable(cls):
        """
        Disable the read connection to use replica connection. This only works after enable().
        Only usable in "partial" mode. And this is thread-safe.
        """
        if not cls._is_partial():
            return

        cls.enable_by_thread_id.remove(threading.get_ident())

    @staticmethod
    def _is_partial():
        return settings.DATABASE_JULO_DB_REPLICA_ROUTING_MODE == 'partial'

    @staticmethod
    def _is_forced():
        return settings.DATABASE_JULO_DB_REPLICA_ROUTING_MODE == 'force'

    def is_enabled(self):
        """
        Check if the router is enabled and can use replica connection or not.
        Returns:
            bool
        """
        is_setting_enabled = (
            self._is_forced()
            or (
                self._is_partial()
                and threading.get_ident() in self.enable_by_thread_id
            )
        )
        return is_setting_enabled and not self.is_in_db_transaction()

    @classmethod
    def is_alive(cls):
        """
        Check if the replica connection is healthy.
        The health check is inspired by https://github.com/yandex/django_replicated

        Returns:
            bool
        """
        connection = connections[cls.replica_db]
        mem_cache = get_loc_mem_cache()
        cache_key = ':'.join((cls.__name__, 'is_alive', cls.replica_db))

        is_dead = mem_cache.get(cache_key) == cls.dead_mark
        if is_dead:
            logger.debug(
                'Check DB replica alive was failed less than {}s ago, no check needed'.format(
                    cls.dead_cache_duration,
                )
            )
            return False

        try:
            with connection.cursor():
                return True
        except Exception:   # noqa
            logger.exception('DB Connection to "{}" failed'.format(cls.replica_db))
            mem_cache.set(cache_key, cls.dead_mark, cls.dead_cache_duration)
            return False

    def is_in_db_transaction(self):
        master_connection = transaction.get_connection(using=self.master_db)
        return master_connection.in_atomic_block

    def db_for_read(self, model, instance=None, **hints):
        if not self.is_enabled():
            return None

        # Don't reroute related object that is not from master_db.
        if instance and instance._state.db != self.master_db:
            return None

        # Use master DB if the replica is not alive.
        if not self.is_alive():
            return self.master_db

        return self.replica_db

    def db_for_write(self, model, instance=None, **hints):
        if not self.is_enabled():
            return None

        # Only try to reroute if the original database is from replica_db
        if instance and instance._state.db == self.replica_db:
            logger.warning('Attempt saving to julodb from replica db. ({}: {}'.format(
                model.__name__,
                instance.pk,
            ))
            return self.master_db

        return None

    def allow_relation(self, obj1, obj2, **hints):
        """
        We allow the relation between master DB and replica DB.
        Return True if a relation between obj1 and obj2 should be allowed,
        False if the relation should be prevented,
        None if the router has no opinion

        Refer to: https://docs.djangoproject.com/en/4.2/topics/db/multi-db/#allow_relation
        """
        if not self.is_enabled():
            return None

        db_list = (self.replica_db, self.master_db)
        if obj1._state.db in db_list and obj2._state.db in db_list:
            return True

        return None


class LoggingDbRouter:
    route_db_tables = {
        'crm_navlog',
        'julo_app_report',
        'moengage_upload',
        'mobile_user_action_log',
        'shortened_url',
        'pusdafil_upload',
        'bank_statement_provider_log',
        'revive_mtl_request',
        'bpjs_alert_log',
        'customer_product_locked',
        'pii_vault_event',
        'web_user_action_log',
        'loan_error_log',
    }
    db = 'logging_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class AnaDbRouter:
    route_db_tables = {
        # Add table here
        '"ana"."pd_churn_model_result"',
        '"ana"."customer_suspend"',
        '"ana"."customer_suspend_history"',
        '"ana"."zero_interest_exclude"',
        '"ana"."daily_osp_product_lender"',
        '"ana"."fdc_platform_check_bypass"',
        '"ana"."customer_segmentation_comms"',
        '"ana"."fdc_loan_data_upload"',
        '"ana"."fdc_inquiry_prioritization_reason_2"',
        '"ana"."loan_lender_tagging_loan_dpd"',
        '"ana"."account_due_amount_above_2mio"',
        '"ana"."loan_refinancing_score_j1"',
        '"ana"."everdpd90_whitelist"',
        '"ana"."customer_high_limit_utilization"',
        '"ana"."pd_customer_lifetime_model_result"',
        '"ana"."credgenics_poc"',
        '"ana"."product_picker_logged_out_never_resolved"',
        '"ana"."blacklist_dbr"',
        '"ana"."sales_ops_prepare_data"',
        '"ana"."collection_b5"',
        '"ana"."pd_clik_model_result"',
        '"ana"."permata_channeling_disbursement_agun"',
        '"ana"."permata_channeling_disbursement_cif"',
        '"ana"."permata_channeling_disbursement_fin"',
        '"ana"."permata_channeling_disbursement_sipd"',
        '"ana"."permata_channeling_disbursement_slik"',
        '"ana"."permata_channeling_payment"',
        '"ana"."permata_channeling_reconciliation"',
        '"ana"."b2_exclude_field_collection"',
        '"ana"."easy_income_eligible"',
        '"ana"."ml_mjolnir_result"',
        '"ana"."collection_b6"',
        '"ana"."icare_account_list_experiment_poc"',
        '"ana"."b2_additional_agent_experiment"',
        '"ana"."pd_bscore_model_result"',
        '"ana"."b3_exclude_field_collection"',
        '"ana"."partnership_null_partner"',
        '"ana"."early_hi_season_ticket_count"',
        '"ana"."sales_ops_lineup_airudder_data"',
        '"ana"."collection_call_priority"',
        '"ana"."odin_consolidated"',
        '"ana"."qris_funnel_last_log"',
        '"ana"."channeling_bscore"',
    }
    db = 'julo_analytics_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db


class BureauDbRouter:
    route_db_tables = {
        'dana_fdc_result',
        'fdc_validation_error',
        'fdc_inquiry_check',
        'fdc_outdated_loan',
        'fdc_inquiry_run',
        'fdc_risky_history',
        'fdc_delivery_temp',
        'fdc_delivery',
        'fdc_delivery_statistic',
        'fdc_delivery_report',
        'fdc_inquiry',
        'fdc_inquiry_loan',
        'initial_fdc_inquiry_loan_data',
    }
    db = 'bureau_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class OnboardingDbRouter:
    route_db_tables = {
        'ocr_ktp_result',
        "dukcapil_api_log",
        "dukcapil_callback_info_api_log",
        "dukcapil_face_recognition_check",
        'bpjs_user_access',
        'sd_bpjs_company',
        'sd_bpjs_profile',
        'sd_bpjs_payment',
        'entry_level_limit_configuration',
        'entry_level_limit_history',
        'perfios_institution_lookup',
        'application_data_check',
        'application_install_history',
        'application_name_bank_validation_change',
        'application_note',
        'application_tag',
        'application_path_tag_history',
        'application_path_tag_status',
        'application_path_tag',
        'application_scrape_action',
        'application_upgrade',
        'application_workflow_switch_history',
        'bank_statement_submit',
        'bank_statement_submit_balance',
        'workflow_failure_action',
        'telco_scoring_result',
        'ocr_ktp_meta_data',
        'ocr_ktp_meta_data_attribute',
        'ocr_ktp_meta_data_value',
        'idfy_video_call',
        'idfy_callback_log',
        "agent_assisted_web_token",
        'toko_score_result',
        'application_phone_record',
        'underwriting_runner',
        'income_check_log',
        'income_check_api_log',
        'neo_info_card',
        'neo_banner_card',
        'hsfbp_income_verification',
        'company_lookup',
    }

    db = 'onboarding_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class LoanDbRouter:
    route_db_tables = {
        'gateway_client',
        'gateway_doku_transaction',
        'gateway_name_bank_validation',
        'gateway_transaction',
        'gateway_transaction_history',
        'gateway_transaction_method_config',
        'gateway_transaction_method_config_history',
        'gateway_transaction_method_response_code',
        'gateway_bank',
        'loan_transaction_detail',
    }
    db = 'loan_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class UtilizationDbRouter:
    route_db_tables = {
        # cfs
        'cfs_action_points_assignment',
        'total_action_points_history',

        # sales ops
        'sales_ops_account_segment_history',
        'sales_ops_autodialer_activity',
        'sales_ops_autodialer_queue_snapshot',
        'sales_ops_lineup_history',
        'sales_ops_rm_scoring',
        'sales_ops_bucket',
        'sales_ops_vendor_bucket_mapping',
        'sales_ops_vendor',
        'sales_ops_daily_summary',
        'sales_ops_prioritization_configuration',
        'sales_ops_lineup_callback_history',
        'sales_ops_vendor_agent_mapping',
        'sales_ops_agent_assignment',
        'sales_ops_autodialer_session',
        'sales_ops_rm_scoring_config',

        # loyalty
        'daily_checkin',
        'daily_checkin_progress',
        'loyalty_point',
        'mission_config',
        'mission_config_criteria',
        'mission_criteria',
        'mission_progress',
        'mission_progress_history',
        'mission_reward',
        'mission_target',
        'mission_target_progress',
        'mission_config_target',
        'point_earning',
        'point_history',
        'point_usage_history',
        'loyalty_gopay_transfer_transaction',

        # early limit release
        'early_release_checking',
        'early_release_checking_history',
        'early_release_experiment',
        'early_release_loan_mapping',
        'release_tracking',
        'release_tracking_history',
        'early_release_checking_v2',
        'early_release_checking_history_v2',
        # graduation/downgrade
        'customer_graduation_failure',
        'downgrade_customer_history',
        'graduation_customer_history_v2',
        # promo code
        'promo_code',
        'promo_code_benefit',
        'promo_code_criteria',
        'promo_code_usage',
        'promo_code_control_list',
        'promo_code_agent_mapping',
        'promo_page',
        # sales ops PDS
        'airudder_agent_group_mapping',
        'airudder_dialer_task_group',
        'airudder_dialer_task_upload',
        'airudder_dialer_task_download',
        'airudder_vendor_recording_detail',

        # easy income upload
        'easy_income_config',
        'easy_income_customer',
        'easy_income_agent_verification',
    }
    db = 'utilization_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class PlatformDbRouter:
    route_db_tables = {
        # CX
        "cx_documents",
        "cx_external_parties",
        'account_deletion_request_web',
        "inapp_survey_question",
        "inapp_survey_answer",
        "inapp_survey_answer_criteria",
        "inapp_survey_user_answer",
        "inapp_survey_triggered_answer",
        "complaint_topic",
        "complaint_subtopic",
        "complaint_submission_log",
        "suggested_answers",
        "suggested_answer_feedback",
        "suggested_answers_user_log",
        "consent_withdrawal_request",
        "consent_withdrawal_request_web",
        # comms
        'sms_vendor_request',
        'comms_request',
        'comms_request_event',
        # anti fraud
        'vpn_detection',
        'geohash_reverse',
        'fraud_blacklisted_asn',
        'fraud_blacklisted_company',
        'fraud_blacklisted_geohash5',
        'fraud_blacklisted_postal_code',
        'fraud_high_risk_asn',
        'fraud_hotspot',
        'suspicious_domain',
        'suspicious_fraud_apps',
        'face_recognition',
        'fraud_blacklist_data',
        'fraud_block',
    }
    db = 'juloplatform_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class CollectionDbRouter:
    route_db_tables = {
        'bulk_vendor_recording_file_cache',
        'collection_ineffective_phone_number',
        'skiptrace_history_pds_detail',
        'manual_dc_agent_assignment',
        'physical_warning_letter_delivery_data',
        'cashback_claim',
        'cashback_claim_payment',
        'collection_skiptrace_event_history',
        'kangtau_uploaded_customer_list',
    }

    db = 'collection_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class PartnershipDbRouter:
    route_db_tables = {
        # Axiata
        'axiata_repayment_data',
        # Etc.
        'partnership_image',
        'partner_disbursement_request',
        'partnership_document',
        'partnership_feature_setting',
        'partnership_product_lookup',
        'dana_payment_bill',
        'dana_hangup_reason_pds',
        'dana_repayment_reference_status',
        'partnership_loan_expectation',
        'partnership_loan_additional_fee',
        'dana_lender_settlement_file',
    }
    db = 'partnership_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class RepaymentDbRouter:
    route_db_tables = {
        'repayment_api_log',
        'repayment_recall_log',
        'bni_virtual_account_suffix',
        'autodebet_api_log',
        'autodebet_benefit',
        'autodebet_benefit_detail',
        'autodebet_deactivation_survey_question',
        'autodebet_deactivation_survey_answer',
        'autodebet_deactivation_survey_user_answer',
        'autodebet_payment_offer',
        'oneklik_bca_account',
        'doku_virtual_account_suffix',
        'oneklik_bca_repayment_transaction',
        'ovo_wallet_account',
        'ovo_wallet_balance_history',
        'ovo_wallet_transaction',
        'autodebet_ovo_transaction',
        'payback_api_log',
        'gopay_autodebet_subscription_retry',
    }
    db = 'repayment_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class PartnershipOnboardingDbRouter:
    route_db_tables = {
        'partnership_application_flag',
        # 'partnership_order_data',
        # 'partnership_fraud_blacklisted_geohash5',
        'dana_account_info',
        'sent_credit_information',
        'merchant_risk_assessment_result',
        'dana_application_reference',
        'partnership_session_information',
        # Liveness
        'liveness_configuration',
        'liveness_result',
        'liveness_result_metadata',
        'liveness_image',
        'partnership_application_flag_history',
        'partnership_clik_model_result',
        'liveness_results_mapping',
    }
    db = 'partnership_onboarding_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None


class PartnershipGrabDbRouter:
    route_db_tables = {
        'grab_api_log',
        'grab_payment_data',
        'grab_transactions',
        'grab_call_log_poc_airudder_pds',
        'grab_collection_dialer_temporary_data',
        'grab_constructed_collection_dialer',
        'grab_async_audit_cron',
        'grab_task_status',
        'grab_temp_loan_no_cscore',
        'grab_master_lock',
        'grab_restructure_history_log',
        'fdc_check_manual_approval',
    }
    db = 'partnership_grab_db'

    def db_for_read(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db

    def db_for_write(self, model, **hints):
        if model._meta.db_table in self.route_db_tables:
            return self.db
        return None

    def allow_migrate(self, db, db_table, model_name=None, **hints):
        if db_table in self.route_db_tables:
            return self.db
        return None
