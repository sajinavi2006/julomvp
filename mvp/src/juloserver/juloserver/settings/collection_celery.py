from celery.schedules import crontab
from juloserver.julo.constants import AddressPostalCodeConst
from juloserver.cootek.constants import LoanIdExperiment

COLLECTION_CELERYBEAT_SCHEDULE = {
    'update-payment-status-every-night': {
        'task': 'update_payment_status',
        'schedule': crontab(minute=1, hour=0),  # Right after midnight
    },
    'update-payment-status-missing-loan-status-paid-off': {
        'task': 'juloserver.grab.tasks.task_update_payment_status_to_paid_off',
        'schedule': crontab(minute=0, hour=10),  # At 10am everyday
    },
    'reactivation-account': {
        'task': 'juloserver.account.tasks.account_task.scheduled_reactivation_account',
        'schedule': crontab(minute=0, hour=[2,19]),  # new J1 account payment
    },
    'update-checkout-request-status-to-expired-every-night': {
        'task': 'juloserver.account_payment.tasks.scheduled_tasks.update_checkout_request_status_to_expired',
        'schedule': crontab(minute=1, hour=0),  # checkout request
    },
    'process_execute_account_selloff': {
        'task': 'juloserver.account.tasks.account_task.process_execute_account_selloff',
        'schedule': crontab(minute=1, hour=0),
    },
    # commented since already handled by automated
    # 'send_all_pn_payment_reminders': {
    #     'task': 'send_all_pn_payment_reminders',
    #     'schedule': crontab(minute=15, hour=9),
    # },

    # 'send_all_pn_payment_mtl_stl_reminders': {
    #     'task': 'send_all_pn_payment_mtl_stl_reminders',
    #     'schedule': crontab(minute=30, hour=9),
    # },

    # 'trigger_all_email_payment_reminders': {
    #     'task': 'trigger_all_email_payment_reminders',
    #     'schedule': crontab(minute=30, hour=12),
    # },

    # 'send_all_whatsapp_reminders_on_wa_bucket_daily_17_and_20pm': {
    #     'task': 'send_all_whatsapp_on_wa_bucket',
    #     'schedule': crontab(minute=0, hour=[17, 20])
    # },

    'clear_overdue_promise_to_pay': {
        'task': 'juloserver.julo.tasks.clear_overdue_promise_to_pay',
        'schedule': crontab(minute=5, hour=2),
    },

    # 'fill_uncalled_today_bucket': {
    #     'task': 'juloserver.julo.tasks.fill_uncalled_today_bucket',
    #     'schedule': crontab(minute=0, hour=20)
    # },

    'reset_collection_called_status_for_unpaid_payment': {
        'task': 'juloserver.julo.tasks.reset_collection_called_status_for_unpaid_payment',
        'schedule': crontab(minute=20, hour=00)
    },

    'reset_collection_called_status_for_unpaid_statement': {
        'task': 'juloserver.paylater.tasks.reset_collection_called_status_for_unpaid_statement',
        'schedule': crontab(minute=20, hour=00)
    },

    # 'assign_collection_agent': {
    #     'task': 'assign_collection_agent',
    #     'schedule': crontab(minute=1, hour=4),
    # },

    'activate_lebaran_promo': {
        'task': 'activate_lebaran_promo',
        'schedule': crontab(minute=0, hour=1)
    },

    # disable loc task
    # 'execute_loc_notification': {
    #     'task': 'execute_loc_notification',
    #     'schedule': crontab(minute=0, hour='*/1')
    # },

    # 'create_loc_statement': {
    #     'task': 'create_loc_statement',
    #     'schedule': crontab(minute=0, hour='*/3')
    # },

    'checking_cashback_delayed': {
        'task': 'juloserver.julo.tasks.checking_cashback_delayed',
        'schedule': crontab(minute=0, hour=9),
    },

    'send_voice_ptp_payment_reminder': {
        'task': 'juloserver.julo.services2.voice.send_voice_ptp_payment_reminder',
        'schedule': crontab(minute=0, hour=10)
    },

    'send_asian_games_campaign': {
        'task': 'send_asian_games_campaign',
        'schedule': crontab(minute=0, hour=12)
    },

    'checking_cashback_abnormal': {
        'task': 'juloserver.julo.tasks.checking_cashback_abnormal',
        'schedule': crontab(minute=0, hour=[9, 12, 18])
    },

    'reverse_waive_late_fee_daily': {
        'task': 'juloserver.julo.tasks.reverse_waive_late_fee_daily',
        'schedule': crontab(minute=50, hour=23)
    },

    'expiration_waiver_daily': {
        'task': 'juloserver.payback.tasks.waiver_tasks.expiration_waiver_daily',
        'schedule': crontab(minute=15, hour=00)
    },

    'experiment_payment_daily_9am': {
        'task': 'run_payment_experiment_at_9am',
        'schedule': crontab(minute=0, hour=9)
    },

    'run_agent_active_flag_update': {
        'task': 'run_agent_active_flag_update',
        'schedule': crontab(minute=0, hour=15),
    },

    'run_ptp_update': {
        'task': 'juloserver.julo.tasks.run_ptp_update',
        'schedule': crontab(minute=10, hour=1),
    },

    'run_rudolf_friska_experiment': {
        'task': 'run_rudolf_friska_experiment',
        'schedule': crontab(minute=0, hour=12),
    },

    'run_cashback_reminder_experiment': {
        'task': 'run_cashback_reminder_experiment',
        'schedule': crontab(minute=0, hour=10),
    },

    'run_march_lottery_experiment': {
        'task': 'run_march_lottery_experiment',
        'schedule': crontab(minute=0, hour=10),
    },

    'run_april_lottery_experiment': {
        'task': 'run_april_lottery_experiment',
        'schedule': crontab(minute=0, hour=10),
    },

    'run_april_rudolf_friska_experiment': {
        'task': 'run_april_rudolf_friska_experiment',
        'schedule': crontab(minute=0, hour=12),
    },

    # 'run_send_warning_letter1': {
    #     'task': 'run_send_warning_letter1',
    #     'schedule': crontab(minute=0, hour=10),
    # },
    # remove code because MTL is not using anymore
    # 'run_send_warning_letters': {
    #     'task': 'juloserver.julo.tasks.run_send_warning_letters',
    #     'schedule': crontab(minute=0, hour=10),
    # },
    'run_send_warning_letters_julo_one': {
        'task': 'juloserver.warning_letter.tasks.run_send_warning_letters_julo_one',
        'schedule': crontab(minute=0, hour=10),
    },
    'send_pn_loan_approved': {
        'task': 'juloserver.julo.tasks.send_pn_loan_approved',
        'schedule': crontab(minute=0, hour=[8, 11, 19]),
    },
    # 'upload_julo_t0_data_to_centerix': {
    #     'task': 'upload_julo_t0_data_to_centerix',
    #     'schedule': crontab(minute=0, hour=5)
    # },
    # 'upload_julo_tminus1_data_to_centerix': {
    #     'task': 'upload_julo_tminus1_data_to_centerix',
    #     'schedule': crontab(minute=5, hour=5),
    # },
    # 'upload_julo_tplus1_to_4_data_centerix': {
    #     'task': 'upload_julo_tplus1_to_4_data_centerix',
    #     'schedule': crontab(minute=10, hour=5)
    # },
    # 'upload_julo_tplus5_to_10_data_centerix': {
    #     'task': 'upload_julo_tplus5_to_10_data_centerix',
    #     'schedule': crontab(minute=15, hour=5),
    # },
    # 'upload_julo_b2_data_centerix': {
    #     'task': 'upload_julo_b2_data_centerix',
    #     'schedule': crontab(minute=15, hour=6),
    # },
    # 'upload_julo_b2_s1_data_centerix': {
    #     'task': 'upload_julo_b2_s1_data_centerix',
    #     'schedule': crontab(minute=15, hour=6),
    # },
    # 'upload_julo_b2_s2_data_centerix': {
    #     'task': 'upload_julo_b2_s2_data_centerix',
    #     'schedule': crontab(minute=15, hour=6),
    # },
    # 'upload_julo_b3_data_centerix': {
    #     'task': 'upload_julo_b3_data_centerix',
    #     'schedule': crontab(minute=15, hour=6),
    # },
    # 'upload_julo_b3_s1_data_centerix': {
    #     'task': 'upload_julo_b3_s1_data_centerix',
    #     'schedule': crontab(minute=15, hour=6),
    # },
    # 'upload_julo_b3_s2_data_centerix': {
    #     'task': 'upload_julo_b3_s2_data_centerix',
    #     'schedule': crontab(minute=30, hour=6),
    # },
    # 'upload_julo_b3_s3_data_centerix': {
    #     'task': 'upload_julo_b3_s3_data_centerix',
    #     'schedule': crontab(minute=30, hour=6),
    # },
    # 'upload_julo_b4_data_centerix': {
    #     'task': 'upload_julo_b4_data_centerix',
    #     'schedule': crontab(minute=30, hour=6),
    # },
    # 'upload_julo_b4_s1_data_centerix': {
    #     'task': 'upload_julo_b4_s1_data_centerix',
    #     'schedule': crontab(minute=30, hour=6),
    # },
    # 'upload_ptp_agent_level_data_centerix': {
    #     'task': 'upload_ptp_agent_level_data_centerix',
    #     'schedule': crontab(minute=5, hour=6),
    # },
    'send_pn_180_playstore_rating_wit_postalcode': {
        'task': 'juloserver.julo.tasks.send_pn_180_playstore_rating',
        'schedule': crontab(minute=0, hour=17),
        'args': AddressPostalCodeConst.WIT_POSTALCODE,
    },
    'send_pn_180_playstore_rating_wita_postalcode': {
        'task': 'juloserver.julo.tasks.send_pn_180_playstore_rating',
        'schedule': crontab(minute=0, hour=18),
        'args': AddressPostalCodeConst.WITA_POSTALCODE,
    },
    'send_pn_180_playstore_rating_wib_postalcode': {
        'task': 'juloserver.julo.tasks.send_pn_180_playstore_rating',
        'schedule': crontab(minute=0, hour=19),
        'args': AddressPostalCodeConst.WIB_POSTALCODE,
    },
    # 'unassign_ptp_payments_from_agent': {
    #     'task': 'unassign_ptp_payments_from_agent',
    #     'schedule': crontab(minute=30, hour=0),
    # },
    # disabled due to bloating 5xx in Pii vault and this task is obsolete
    # 'run_waive_pede_campaign': {
    #     'task': 'run_waive_pede_campaign',
    #     'schedule': crontab(minute=45, hour=23)
    # },
    'run_send_email_pede_campaign_oct_7am': {
        'task': 'run_send_email_pede_campaign',
        'schedule': crontab(minute=0, hour=7, day_of_month='17,30',
                            month_of_year='10')
    },
    'run_send_email_pede_campaign_oct_8am': {
        'task': 'run_send_email_pede_campaign',
        'schedule': crontab(minute=0, hour=8, day_of_month='22',
                            month_of_year='10')
    },
    'run_send_email_pede_campaign_oct_3pm': {
        'task': 'run_send_email_pede_campaign',
        'schedule': crontab(minute=0, hour=15, day_of_month='26',
                            month_of_year='10')
    },
    'run_send_email_pede_campaign_nov_8am': {
        'task': 'run_send_email_pede_campaign',
        'schedule': crontab(minute=0, hour=8, day_of_month='3',
                            month_of_year='11')
    },
    'run_waive_sell_off_oct_campaign': {
        'task': 'run_waive_sell_off_oct_campaign',
        'schedule': crontab(minute=0, hour=1)
    },
    'run_send_email_sell_off_oct_campaign_oct_25': {
        'task': 'run_send_email_sell_off_oct_campaign',
        'schedule': crontab(minute=0, hour=7, day_of_month='25',
                            month_of_year='10')
    },
    'run_send_email_sell_off_oct_campaign_oct_29': {
        'task': 'run_send_email_sell_off_oct_campaign',
        'schedule': crontab(minute=0, hour=21, day_of_month='29',
                            month_of_year='10')
    },
    'run_send_email_sell_off_oct_campaign_nov_2': {
        'task': 'run_send_email_sell_off_oct_campaign',
        'schedule': crontab(minute=0, hour=10, day_of_month='2',
                            month_of_year='11')
    },
    'run_send_email_sell_off_oct_campaign_nov_6': {
        'task': 'run_send_email_sell_off_oct_campaign',
        'schedule': crontab(minute=0, hour=12, day_of_month='6',
                            month_of_year='11')
    },
    'run_send_email_sell_off_oct_campaign_nov_9': {
        'task': 'run_send_email_sell_off_oct_campaign',
        'schedule': crontab(minute=0, hour=19, day_of_month='9',
                            month_of_year='11')
    },
    'load_sell_off_oct_campaign_data_at_midnight': {
        'task': 'load_sell_off_oct_campaign_data',
        'schedule': crontab(minute=0, hour=11, day_of_month='24',
                            month_of_year='10')
    },
    'run_wa_experiment_group_1_4_5': {
        'task': 'run_wa_experiment',
        'schedule': crontab(minute=0, hour=[12, 13, 14, 17, 18, 19, 20, 21], month_of_year=[10, 11])
    },
    'run_wa_experiment_group_2': {
        'task': 'run_wa_experiment',
        'schedule': crontab(minute=5, hour=[10, 11, 12], month_of_year=[10, 11])
    },
    'run_wa_experiment_group_3': {
        'task': 'run_wa_experiment',
        'schedule': crontab(minute=30, hour=[14, 15, 16], month_of_year=[10, 11])
    },
    'call_pede_api_with_payment_greater_5DPD': {
        'task': 'call_pede_api_with_payment_greater_5DPD',
        'schedule': crontab(minute=0, hour=1)
    },
    # get token authenctication from cootek every 12 hours
    'get_token_authentication_from_cootek': {
        'task': 'juloserver.cootek.tasks.get_token_authentication_from_cootek',
        'schedule': crontab(minute=0, hour=[6, 18]),
    },
    'get_tasks_from_db_and_schedule_cootek': {
        'task': 'juloserver.cootek.tasks.get_tasks_from_db_and_schedule_cootek',
        'schedule': crontab(minute=0, hour=1),
    },
    # 'unassign_bucket_level_excluded_payment': {
    #     'task': 'unassign_bucket_level_excluded_payment',
    #     'schedule': crontab(minute=30, hour=1)
    # },

    # 'run_get_call_status_details_from_centerix': {
    #     'task': 'run_get_call_status_details_from_centerix',
    #     'schedule': crontab(minute=0, hour=19),
    # },
    # 'run_get_all_system_call_result_from_centerix': {
    #     'task': 'run_get_all_system_call_result_from_centerix',
    #     'schedule': crontab(minute=10, hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
    # },
    'exclude_abandoned_payments_calls_from_daily_upload': {
        'task': 'juloserver.minisquad.tasks.exclude_abandoned_payments_calls_from_daily_upload',
        'schedule': crontab(minute=00, hour=23)
    },
    # 'run_get_agent_productiviy_details_from_centerix': {
    #     'task': 'run_get_agent_productiviy_details_from_centerix',
    #     'schedule': crontab(minute=30, hour=22),
    # },
    'send_automated_comms': {
        'task': 'juloserver.julo.tasks.send_automated_comms',
        'schedule': crontab(minute=1, hour=00),
    },
    'load_campaign_covid_data': {
        'task': 'load_campaign_covid_data',
        'schedule': crontab(minute=0, hour=23, day_of_month='23', month_of_year='3'),
    },
    'summary_covid_campaign': {
        'task': 'summary_covid_campaign',
        'schedule': crontab(minute=0, hour=7, day_of_month='16', month_of_year='4'),
    },
    'run_send_email_osp_recovery_7am': {
        'task': 'send_email_osp_recovery',
        'schedule': crontab(minute=0, hour=7, day_of_month='24,28,10',
                            month_of_year=[3, 4])
    },
    'run_send_email_osp_recovery_11am': {
        'task': 'send_email_osp_recovery',
        'schedule': crontab(minute=0, hour=11, day_of_month='2,14',
                            month_of_year='4')
    },
    'run_send_sms_osp_recovery_7am': {
        'task': 'send_sms_osp_recovery',
        'schedule': crontab(minute=30, hour=7, day_of_month='25',
                            month_of_year='3')
    },
    'run_send_sms_osp_recovery_11am': {
        'task': 'send_sms_osp_recovery',
        'schedule': crontab(minute=0, hour=11, day_of_month='11',
                            month_of_year='4')
    },
    # 'sending_robocall_covid_campaign': {
    #     'task': 'juloserver.julo.tasks2.campaign_tasks.sending_robocall_covid_campaign',
    #     'schedule': crontab(minute=0, hour=8, day_of_month='10', month_of_year='4'),
    # },
    # 'retry_sending_robocall_covid_campaign': {
    #     'task': 'juloserver.julo.tasks2.campaign_tasks.retry_sending_robocall_covid_campaign',
    #     'schedule': crontab(minute=0, hour=8, day_of_month='11', month_of_year='4'),
    # },
    # 'upload_julo_t0_cootek_data_to_centerix': {
    #     'task': 'upload_julo_t0_cootek_data_to_centerix',
    #     'schedule': crontab(minute=30, hour=11)
    # },
    'run_lebaran_campaign_2020_email_1': {
        'task': 'send_lebaran_campaign_2020_email',
        'schedule': crontab(hour=8, day_of_month='24',
                            month_of_year='4')
    },
    'run_lebaran_campaign_2020_email_2': {
        'task': 'send_lebaran_campaign_2020_email',
        'schedule': crontab(hour=8, day_of_month='9',
                            month_of_year='5')
    },
    'run_lebaran_campaign_2020_pn_1': {
        'task': 'send_lebaran_campaign_2020_pn',
        'schedule': crontab(minute=30, hour=12, day_of_month='27',
                            month_of_year='4')
    },
    'run_lebaran_campaign_2020_pn_2': {
        'task': 'send_lebaran_campaign_2020_pn',
        'schedule': crontab(minute=0, hour=17, day_of_month='29',
                            month_of_year='4')
    },
    'run_lebaran_campaign_2020_pn_3': {
        'task': 'send_lebaran_campaign_2020_pn',
        'schedule': crontab(minute=30, hour=12, day_of_month='1',
                            month_of_year='5')
    },
    'run_lebaran_campaign_2020_pn_4': {
        'task': 'send_lebaran_campaign_2020_pn',
        'schedule': crontab(minute=0, hour=17, day_of_month='3',
                            month_of_year='5')
    },
    'run_lebaran_campaign_2020_pn_5': {
        'task': 'send_lebaran_campaign_2020_pn',
        'schedule': crontab(minute=30, hour=12, day_of_month='7',
                            month_of_year='5')
    },
    'run_lebaran_campaign_2020_sms_1': {
        'task': 'send_lebaran_campaign_2020_sms',
        'schedule': crontab(hour=19, day_of_month='26',
                            month_of_year='4')
    },
    'run_lebaran_campaign_2020_sms_2': {
        'task': 'send_lebaran_campaign_2020_sms',
        'schedule': crontab(hour=8, day_of_month='6',
                            month_of_year='5')
    },
    'sms_campaign_for_non_contacted_customer_7am_apr20': {
        'task': 'juloserver.julo.tasks2.campaign_tasks.sms_campaign_for_non_contacted_customer_7am',
        'schedule': crontab(minute=0, hour=7, day_of_month='20', month_of_year='4'),
    },
    'sms_campaign_for_non_contacted_customer_7am_may11': {
        'task': 'juloserver.julo.tasks2.campaign_tasks.sms_campaign_for_non_contacted_customer_7am',
        'schedule': crontab(minute=0, hour=7, day_of_month='11', month_of_year='5'),
    },
    'sms_campaign_for_non_contacted_customer_12h30pm_apr27': {
        'task': 'juloserver.julo.tasks2.campaign_tasks.sms_campaign_for_non_contacted_customer_12h30pm',
        'schedule': crontab(minute=30, hour=12, day_of_month='27', month_of_year='4'),
    },
    'sms_campaign_for_non_contacted_customer_12h30pm_may18': {
        'task': 'juloserver.julo.tasks2.campaign_tasks.sms_campaign_for_non_contacted_customer_12h30pm',
        'schedule': crontab(minute=30, hour=12, day_of_month='18', month_of_year='5'),
    },
    'sms_campaign_for_non_contacted_customer_5pm_may4': {
        'task': 'juloserver.julo.tasks2.sms_campaign_for_non_contacted_customer_5pm',
        'schedule': crontab(minute=0, hour=17, day_of_month='4', month_of_year='5'),
    },
    'sms_campaign_for_non_contacted_customer_5pm_may25': {
        'task': 'juloserver.julo.tasks2.sms_campaign_for_non_contacted_customer_5pm',
        'schedule': crontab(minute=0, hour=17, day_of_month='25', month_of_year='5'),
    },
    # running only on 17,24 april and 1,8 may
    'run_send_sms_repayment_awareness_campaign': {
        'task': 'send_sms_repayment_awareness_campaign',
        'schedule': crontab(minute=0, hour=8, day_of_month='17,24,1,8',
                            month_of_year=[4, 5])
    },
    # 'remove_centerix_log_more_than_30days': {
    #     'task': 'remove_centerix_log_more_than_30days',
    #     'schedule': crontab(minute=0, hour=1)
    # },
    # 'send_ramadhan_email_campaign': {
    #     'task': 'send_ramadhan_email_campaign',
    #     'schedule': crontab(minute=0, hour=8)
    # },

    # 'send_ramadhan_pn_campaign': {
    #     'task': 'send_ramadhan_pn_campaign',
    #     'schedule': crontab(minute=30, hour=13)
    # },
    # 'send_ramadhan_sms_campaign': {
    #     'task': 'send_ramadhan_sms_campaign',
    #     'schedule': crontab(minute=00, hour=19)
    # },
    # 'run_get_agent_hourly_data_from_centerix': {
    #     'task': 'run_get_agent_hourly_data_from_centerix',
    #     'schedule': crontab(
    #     minute=00,
    #     hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21])
    # },
    # 'upload_julo_b2_non_contacted_data_centerix': {
    #     'task': 'upload_julo_b2_non_contacted_data_centerix',
    #     'schedule': crontab(minute=45, hour=5)
    # },
    # 'upload_julo_b3_non_contacted_data_centerix': {
    #     'task': 'upload_julo_b3_non_contacted_data_centerix',
    #     'schedule': crontab(minute=45, hour=5)
    # },
    # 'upload_julo_b4_non_contacted_data_centerix': {
    #     'task': 'upload_julo_b4_non_contacted_data_centerix',
    #     'schedule': crontab(minute=45, hour=5)
    # },
    'exclude_non_contacted_payment_for_intelix': {
        'task': 'juloserver.minisquad.tasks.exclude_non_contacted_payment_for_intelix',
        'schedule': crontab(minute=0, hour=2)
    },
    # 'schedule_for_dpd_minus_to_centerix': {
    #     'task': 'schedule_for_dpd_minus_to_centerix',
    #     'schedule': crontab(minute=0, hour=7)
    # },
    'send_all_refinancing_request_reminder_to_pay_minus_1': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_refinancing_request_reminder_to_pay_minus_1',
        'schedule': crontab(minute=0, hour=12)
    },
    'send_all_refinancing_request_reminder_to_pay_minus_2': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_refinancing_request_reminder_to_pay_minus_2',
        'schedule': crontab(minute=0, hour=12)
    },
    # send offer reminder for R1 R2 R3 minus 1
    'send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_1': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_1',
        'schedule': crontab(minute=0, hour=12)
    },
    # send offer reminder for R1 R2 R3 minus 2
    'send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_2': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_2',
        'schedule': crontab(minute=0, hour=12)
    },
    'send_all_refinancing_request_reminder_offer_selected_2': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_refinancing_request_reminder_offer_selected_2',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_all_refinancing_request_reminder_offer_selected_1': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_refinancing_request_reminder_offer_selected_1',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_all_proactive_refinancing_email_reminder_8am': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_proactive_refinancing_email_reminder_8am',
        'schedule': crontab(minute=0, hour=8)
    },
    'send_all_proactive_refinancing_email_reminder_10am': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_proactive_refinancing_email_reminder_10am',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_all_proactive_refinancing_pn_reminder_8am': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_proactive_refinancing_pn_reminder_8am',
        'schedule': crontab(minute=0, hour=8)
    },
    'send_all_proactive_refinancing_pn_reminder_10am': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_proactive_refinancing_pn_reminder_10am',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_all_proactive_refinancing_pn_reminder_12pm': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_proactive_refinancing_pn_reminder_12pm',
        'schedule': crontab(minute=0, hour=12)
    },
    # 'send_all_proactive_refinancing_robocall_reminder_8am': {
    #     'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_proactive_refinancing_robocall_reminder_8am',
    #     'schedule': crontab(minute=0, hour=[8, 10, 12])
    # },
    'send_all_proactive_refinancing_sms_reminder_10am': {
        'task': 'send_all_proactive_refinancing_sms_reminder_10am',
        'schedule': crontab(minute=0, hour=10)
    },
    # 'send_robocall_refinancing_request_reminder_offer_selected_3': {
    #     'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_robocall_refinancing_request_reminder_offer_selected_3',
    #     'schedule': crontab(minute=0, hour=[8, 10, 12])
    # },
    # 'send_robocall_refinancing_request_approved_selected_3': {
    #     'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_robocall_refinancing_request_approved_selected_3',
    #     'schedule': crontab(minute=0, hour=[8, 10, 12])
    # },
    # 'trigger_system_call_results_every_hour': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.trigger_system_call_results_every_hour',
    #     'schedule': crontab(minute=20, hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]),
    # },
    # 'trigger_system_call_results_every_hour_last_attempt': {
    #     'task': 'trigger_system_call_results_every_hour_last_attempt',
    #     'schedule': crontab(minute=20, hour=[21]),
    # },
    # 'store_agent_productivity_from_intelix_every_hours': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.store_agent_productivity_from_intelix_every_hours',
    #     'schedule': crontab(minute=10, hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
    # },
    # 'store_agent_productivity_from_intelix_every_hours_last_attempt': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.store_agent_productivity_from_intelix_every_hours_last_attempt',
    #     'schedule': crontab(minute=10, hour=[21]),
    # },
    # 'construct_julo_b1_data_to_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.construct_julo_b1_data_to_intelix',
    #     'schedule': crontab(minute=30, hour=4),
    # },
    # 'construct_julo_b2_data_to_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.construct_julo_b2_data_to_intelix',
    #     'schedule': crontab(minute=30, hour=4),
    # },
    # 'construct_julo_b3_non_contacted_data_to_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.construct_julo_b3_non_contacted_data_to_intelix',
    #     'schedule': crontab(minute=30, hour=4),
    # },
    # # JTURBO collection
    # 'construct_jturbo_b1_data_to_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b1_data_to_intelix',
    #     'schedule': crontab(minute=30, hour=4),
    # },
    # 'construct_jturbo_b2_data_to_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b2_data_to_intelix',
    #     'schedule': crontab(minute=30, hour=4),
    # },
    # 'construct_jturbo_b3_data_to_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b3_data_to_intelix',
    #     'schedule': crontab(minute=30, hour=4),
    # },
    # 'construct_jturbo_b4_data_to_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b4_data_to_intelix',
    #     'schedule': crontab(minute=30, hour=4),
    # },
    # AI rudder
    # 'trigger_data_generation_bucket_current': {
    #     'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_data_generation_bucket_current',
    #     'schedule': crontab(minute=15, hour=4),
    # },
    # 'trigger_construct_call_data_bucket_current': {
    #     'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_construct_call_data_bucket_current',
    #     'schedule': crontab(minute=50, hour=4),
    # },
    'trigger_construct_call_data_bucket_3': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_construct_call_data_bucket_3',
        'schedule': crontab(minute=30, hour=4),
    },
    'trigger_construct_call_data_bucket_2': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_construct_call_data_bucket_2',
        'schedule': crontab(minute=10, hour=4),
    },
    'trigger_construct_call_data_bucket_1': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_construct_call_data_bucket_1',
        'schedule': crontab(minute=15, hour=4),
    },
    'trigger_construct_call_data_bucket_4': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_construct_call_data_bucket_4',
        'schedule': crontab(minute=20, hour=4),
    },
    'trigger_construct_call_data_bucket_6_1': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_construct_call_data_bucket_6_1',
        'schedule': crontab(minute=10, hour=4),
    },
    'trigger_b6_data_population': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_b6_data_population',
        'schedule': crontab(minute=50, hour=1),
    },
    'flush_payload_dialer_data': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.flush_payload_dialer_data',
        'schedule': crontab(minute=0, hour=20),
    },
    'trigger_upload_data_to_dialer': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_upload_data_to_dialer',
        'schedule': crontab(minute=30, hour=6),
    },
    'trigger_slack_notification_for_empty_bucket': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_slack_notification_for_empty_bucket',
        'schedule': crontab(minute=50, hour=6),
    },
    'trigger_construct_call_data_bucket_0': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_construct_call_data_bucket_0',
        'schedule': crontab(minute=15, hour=4),
    },
    'trigger_upload_call_data_bucket_0': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_upload_call_data_bucket_0',
        'schedule': crontab(minute=30, hour=11),
    },
    'check_upload_dialer_task_is_finish_t0': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.check_upload_dialer_task_is_finish_t0',
        'schedule': crontab(minute=30, hour=12),
    },
    'retroload_sync_hangup_reason': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.retroload_sync_hangup_reason',
        'schedule': crontab(minute=30, hour=21),
    },
    'sent_alert_data_discrepancies': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.sent_alert_data_discrepancies',
        'schedule': crontab(minute=5, hour=23),
    },
    'fix_start_ts_skiptrace_history_daily': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.fix_start_ts_skiptrace_history_daily',
        'schedule': crontab(minute=30, hour=21),
    },
    'process_retroload_sent_to_dialer': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.process_retroload_sent_to_dialer',
        'schedule': crontab(minute=30, hour=21),
    },
    'sync_call_result_agent_level': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.sync_call_result_agent_level',
        'schedule': crontab(minute=0, hour=22),
    },
    'trigger_upload_data_bucket_current_bttc_to_dialer': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_upload_data_bucket_current_bttc_to_dialer',
        'schedule': crontab(minute=30, hour=7),
    },
    'trigger_upload_data_bucket_delinquent_bttc_to_dialer': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.trigger_upload_data_bucket_delinquent_bttc_to_dialer',
        'schedule': crontab(minute=30, hour=7),
    },
    'expiry_manual_agent_assignment': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.expiry_manual_agent_assignment',
        'schedule': crontab(minute=0, hour=9),
    },
    # end of AI rudder
    'upload_julo_formatted_data_to_intelix': {
        'task': 'juloserver.minisquad.tasks2.intelix_task.upload_julo_formatted_data_to_intelix',
        'schedule': crontab(minute=15, hour=6),
    },
    'upload_j1_jturbo_t_minus_to_intelix': {
        'task': 'juloserver.minisquad.tasks2.intelix_task.upload_j1_jturbo_t_minus_to_intelix',
        'schedule': crontab(minute=0, hour=5),
    },
    'upload_partial_cootek_data_to_intelix_august_period': {
        'task': 'juloserver.cootek.tasks.upload_partial_cootek_data_to_intelix_t0_00_33',
        'schedule': crontab(minute=30, hour=11, month_of_year=8, day_of_month='25-31'),
    },
    'upload_partial_cootek_data_to_intelix_september_period': {
        'task': 'juloserver.cootek.tasks.upload_partial_cootek_data_to_intelix_t0_00_33',
        'schedule': crontab(minute=30, hour=11, month_of_year=9, day_of_month='01-10'),
    },
    'enable_trigger_experiment_cootek_config': {
        'task': 'juloserver.cootek.tasks.trigger_experiment_cootek_config',
        'schedule': crontab(minute=00, hour=23, month_of_year=8, day_of_month=24),
        'args': (False,),
    },
    'disable_trigger_experiment_cootek_config': {
        'task': 'juloserver.cootek.tasks.trigger_experiment_cootek_config',
        'schedule': crontab(minute=0, hour=1, month_of_year=9, day_of_month=11),
        'args': (True,),
    },
    'set_time_retry_mechanism_and_send_alert_for_unsent_intelix_issue': {
        'task': 'juloserver.minisquad.tasks2.intelix_task.set_time_retry_mechanism_and_send_alert_for_unsent_intelix_issue',
        'schedule': crontab(minute=1, hour=0)
    },
    # ---Sep 2020 hi season---
    'create_accounting_cut_off_date_monthly_entry': {
        'task': 'create_accounting_cut_off_date_monthly_entry',
        'schedule': crontab(minute=0, hour=0, day_of_month='1')
    },
    'upload_julo_t0_cootek_data_to_intelix': {
        'task': 'juloserver.cootek.tasks.upload_julo_t0_cootek_data_to_intelix',
        'schedule': crontab(minute=30, hour=11)
    },
    # bucket 5 related
    'update-change-ever-entered-B5': {
        'task': 'juloserver.collection_vendor.tasks.bucket_5_task.change_ever_entered_b5',
        'schedule': crontab(minute=30, hour=0),  # Right after midnight
    },
    'schedule_unassign_payment_and_account_payment_already_paid': {
        'task': 'juloserver.collection_vendor.task.schedule_unassign_payment_and_account_payment_already_paid',
        'schedule': crontab(minute=30, hour=1),
    },
    'allocate_payments_to_collection_vendor_for_bucket_six_sub_3': {
        'task': 'juloserver.collection_vendor.task.allocate_payments_to_collection_vendor_for_bucket_6_3',
        'schedule': crontab(minute=30, hour=2),
    },
    'set_settled_status_for_bucket_six_sub_three_and_four': {
        'task': 'juloserver.collection_vendor.task.set_settled_status_for_bucket_6_sub_3_and_4',
        'schedule': crontab(minute=0, hour=3),
    },
    'set_is_warehouse_status_for_bucket_six_sub_four': {
        'task': 'juloserver.collection_vendor.task.set_is_warehouse_status_for_bucket_6_sub_4',
        'schedule': crontab(minute=0, hour=3),
    },
    # end of bucket 5
    'run_ptp_update_for_j1': {
        'task': 'run_ptp_update_for_j1',
        'schedule': crontab(minute=10, hour=1),
    },
    'run_broken_ptp_flag_update_j1': {
        'task': 'run_broken_ptp_flag_update_j1',
        'schedule': crontab(minute=15, hour=1),
    },
    'run_broken_ptp_flag_update': {
        'task': 'run_broken_ptp_flag_update',
        'schedule': crontab(minute=15, hour=1),
    },
    # 'unassign_ptp_account_payments_from_agent': {
    #     'task': 'unassign_ptp_payments_from_agent',
    #     'schedule': crontab(minute=30, hour=0),
    # },
    'reset_collection_called_status_for_unpaid_account_payment': {
        'task': 'juloserver.julo.tasks.reset_collection_called_status_for_unpaid_account_payment',
        'schedule': crontab(minute=20, hour=00)
    },
    'send_all_multiple_payment_ptp_minus_reminder': {
        'task': 'send_all_multiple_payment_ptp_minus_reminder',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_all_multiple_payment_ptp_reminder': {
        'task': 'send_all_multiple_payment_ptp_reminder',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_all_multiple_payment_ptp_minus_expiry': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_multiple_payment_ptp_minus_expiry',
        'schedule': crontab(minute=0, hour=12)
    },
    'send_all_multiple_payment_ptp_expiry': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_all_multiple_payment_ptp_expiry',
        'schedule': crontab(minute=0, hour=12)
    },
    'kick_off_bulk_disbursement_midnight': {
        'task': 'kick_off_bulk_disbursement_midnight',
        'schedule': crontab(minute=5, hour=0)
    },
    'send_email_for_multiple_ptp_waiver_expired_plus_1_wib': {
        'task': 'send_email_for_multiple_ptp_waiver_expired_plus_1_wib',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_email_for_multiple_ptp_waiver_expired_plus_1_wita': {
        'task': 'send_email_for_multiple_ptp_waiver_expired_plus_1_wita',
        'schedule': crontab(minute=0, hour=9)
    },
    'send_email_for_multiple_ptp_waiver_expired_plus_1_wit': {
        'task': 'send_email_for_multiple_ptp_waiver_expired_plus_1_wit',
        'schedule': crontab(minute=0, hour=8)
    },
    'get_and_store_oldest_unpaid_account_payment': {
        'task': 'juloserver.moengage.tasks.get_and_store_oldest_unpaid_account_payment',
        'schedule': crontab(minute=30, hour=[7, 9, 11, 13, 14]),
    },
    'send_manual_pn_for_unsent_moengage': {
        'task': 'juloserver.julo.tasks.send_manual_pn_for_unsent_moengage',
        'schedule': crontab(minute=0, hour=15)
    },
    'send_email_sms_for_unsent_moengage': {
        'task': 'juloserver.julo.tasks.send_email_sms_for_unsent_moengage',
        'schedule': crontab(minute=0, hour=15)
    },
    # task for insert checkout experiment to experiment group
    'process_create_data_for_checkout_experience_experiment': {
        'task': 'juloserver.account_payment.tasks.scheduled_tasks.process_create_data_for_checkout_experience_experiment',
        'schedule': crontab(minute=0, hour=1)
    },



    'send_slack_notification_intelix_blacklist': {
        'task': 'juloserver.minisquad.tasks2.notifications.send_slack_notification_intelix_blacklist',
        'schedule': crontab(minute=0, hour=1, day_of_week='5')
    },

    'trigger_in_app_ptp_broken': {
        'task': 'juloserver.minisquad.tasks.trigger_in_app_ptp_broken',
        'schedule': crontab(minute=0, hour=8)
    },

    'trigger_in_app_callback_notification_before_call': {
        'task': 'juloserver.minisquad.tasks.trigger_in_app_callback_notification_before_call',
        'schedule': crontab(minute=5, hour=00),
    },
    # run before b5 vendor assignment
    'trigger_expiry_vendor_b4_j1': {
        'task': 'juloserver.collection_vendor.task.trigger_expiry_vendor_b4_j1',
        'schedule': crontab(minute=0, hour=2),
    },
    # Koleko
    'juloserver.minisquad.tasks2.koleko_task.trigger_upload_grab_data_collection': {
        'task': 'juloserver.minisquad.tasks2.koleko_task.trigger_upload_grab_data_collection',
        'schedule': crontab(minute=0, hour=2),
    },

    # ---Start June 2022 hi season---
    'run_send_email_june2022_hi_season': {
        'task': 'run_send_email_june2022_hi_season',
        'schedule': crontab(minute=0, hour=7, month_of_year=6, day_of_month='19-28')
    },
    'run_send_pn1_june22_hi_season_8h': {
        'task': 'run_send_pn1_june22_hi_season_8h',
        'schedule': crontab(minute=0, hour=8, month_of_year=6, day_of_month='20-29')
    },
    'run_send_pn2_june22_hi_season_8h': {
        'task': 'run_send_pn2_june22_hi_season_8h',
        'schedule': crontab(minute=0, hour=8, month_of_year=6, day_of_month='22-30')
    },
    'run_send_pn2_june22_hi_season_8h_june': {
        'task': 'run_send_pn2_june22_hi_season_8h',
        'schedule': crontab(minute=0, hour=8, month_of_year=7, day_of_month='1')
    },
    # ---End June 2022 hi season---
    'juloserver.minisquad.tasks2.notifications.send_pn_for_collection_tailor_experiment': {
        'task': 'juloserver.minisquad.tasks2.notifications.send_pn_for_collection_tailor_experiment',
        'schedule': crontab(minute=0, hour=2),
    },
    'juloserver.minisquad.tasks2.notifications.trigger_manual_send_pn_for_unsent_collection_tailor_experiment_backup': {
        'task': 'juloserver.minisquad.tasks2.notifications.trigger_manual_send_pn_for_unsent_collection_tailor_experiment_backup',
        'schedule': crontab(minute=0, hour=16),
    },
    'populate_temp_data_for_dialer': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.populate_temp_data_for_dialer',
        'schedule': crontab(minute=0, hour=1),
    },
    'flush_temp_data_for_dialer': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.flush_temp_data_for_dialer',
        'schedule': crontab(minute=0, hour=20),
    },
    # 'cron_trigger_grab_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_grab_intelix',
    #     'schedule': crontab(minute=1, hour=0),  # Right after midnight
    # },
    'clear_grab_collection_dialer_temp_data': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.clear_grab_collection_dialer_temp_data',
        'schedule': crontab(minute=0, hour=22),
    },
    'clear_temporary_data_dialer': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.clear_temporary_data_dialer',
        'schedule': crontab(minute=0, hour=22),
    },
    'send_robocall_for_collection_tailor_experiment': {
        'task': 'juloserver.minisquad.tasks2.notifications.send_robocall_for_collection_tailor_experiment',
        'schedule': crontab(minute=0, hour=5),
    },
    'process_populate_bucket_3_vendor_distribution_sort1_method': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.process_populate_bucket_3_vendor_distribution_sort1_method',
        'schedule': crontab(minute=30, hour=2),
    },
    # 'cron_trigger_sent_grab_intelix': {
    #     'task': 'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_sent_to_intelix',
    #     'schedule': crontab(minute='*/30', hour='5-7'),  # every 30 min, in range 5 - 7 AM
    # },
    'process_populate_bucket_3_vendor_distribution_experiment1_method': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.process_populate_bucket_3_vendor_distribution_experiment1_method',
        'schedule': crontab(minute=30, hour=2),
    },
    'update_dana_account_payment_status': {
        'task': 'juloserver.dana.tasks.update_dana_account_payment_status',
        'schedule': crontab(minute=1, hour=0),  # dana account payment
    },
    'clear_temporary_constructed_data_dialer': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.clear_temporary_constructed_data_dialer',
        'schedule': crontab(minute=0, hour=22),
    },
    # retrive call recording airudder
    # already handle by webhook
    # 'process_retrieve_call_recording_data': {
    #     'task': 'juloserver.minisquad.tasks2.dialer_system_task.process_retrieve_call_recording_data',
    #     'schedule': crontab(minute=0, hour=22),
    # },
    'update_payment_amount_every_night': {
        'task': 'juloserver.julo.tasks.update_payment_amount',
        'schedule': crontab(minute=5, hour=3),
    },
    'alert_dialer_data_pre_processing': {
        'task': 'juloserver.minisquad.tasks2.intelix_task2.alert_dialer_data_pre_processing',
        'schedule': crontab(minute=0, hour=[2, 3]),
    },
    'consume_call_result_system_level': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.consume_call_result_system_level',
        'schedule': crontab(minute=15, hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]),
    },
    'update_is_automated_for_late_fee_experiment': {
        'task': 'juloserver.minisquad.tasks.update_is_automated_for_late_fee_experiment',
        'schedule': crontab(minute=30, hour=22),
    },
    'cron_trigger_grab_ai_rudder': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_grab_ai_rudder',
        'schedule': crontab(minute=1, hour=0),  # Right after midnight
    },
    'cron_trigger_sent_to_ai_rudder': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_sent_to_ai_rudder',
        'schedule': crontab(minute='*/30', hour='5-7'),  # every 30 min, in range 5 - 7 AM
    },
    'grab_consume_call_result_system_level': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task_grab.grab_consume_call_result_system_level',
        'schedule': crontab(minute=15, hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]),
    },
    # cashback new scheme
    'cashback_new_scheme_break': {
        'task': 'juloserver.account.tasks.scheduled_tasks.cashback_new_scheme_break',
        'schedule': crontab(minute=0, hour=1),
    },
    'grab_retroload_air_call_result_for_manual_upload': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task_grab.grab_retroload_air_call_result_for_manual_upload',
        'schedule': crontab(minute=15, hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]),
    },
    'populate_account_id_for_sms_after_robocall_experiment': {
        'task': 'juloserver.minisquad.tasks.populate_account_id_for_sms_after_robocall_experiment',
        'schedule': crontab(minute=0, hour=2),
    },
    'get_grab_account_id_to_be_deleted_from_airudder': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task_grab.get_grab_account_id_to_be_deleted_from_airudder',
        'schedule': crontab(minute=5, hour=[7, 9, 11, 13, 15, 17]),
    },
    # collection risk bucket list
    'populate_collection_risk_bucket_list': {
        'task': 'juloserver.julo.tasks.populate_collection_risk_bucket_list',
        'schedule': crontab(minute=0, hour=4),
    },
    'update_collection_risk_bucket_list_passed_minus_11': {
        'task': 'juloserver.julo.tasks.update_collection_risk_bucket_list_passed_minus_11',
        'schedule': crontab(minute=1, hour=0),
    },
    # bucket reach history
    'account_bucket_history_querying': {
        'task': 'juloserver.account.tasks.scheduled_tasks.account_bucket_history_querying',
        'schedule': crontab(minute=1, hour=0),
    },
    'b5_autodialer_recovery_distribution': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.b5_autodialer_recovery_distribution',
        'schedule': crontab(minute=0, hour=2),
    },
    # cohort campaign automation
    'trigger_blast_cohort_campaign_automation': {
        'task': 'juloserver.cohort_campaign_automation.tasks.trigger_blast_cohort_campaign_automation',
        'schedule': crontab(minute=0, hour=5),
    },
    'trigger_update_cohort_campaign_to_be_done': {
        'task': 'juloserver.cohort_campaign_automation.tasks.trigger_update_cohort_campaign_to_be_done',
        'schedule': crontab(minute=1, hour=0),
    },
    'dpd3_to_90_autodialer_recovery_distribution': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.dpd3_to_90_autodialer_recovery_distribution',
        'schedule': crontab(minute=1, hour=0, day_of_month=[1]),
    },
    # remove experiment sms
    'send_sms_reminder_user_attribute_to_omnichannel': {
        'task': 'juloserver.streamlined_communication.tasks.send_sms_reminder_user_attribute_to_omnichannel',
        'schedule': crontab(minute=30, hour=0),
    },
    # physical warning letter
    'physical_warning_letter_generation': {
        'task': 'juloserver.warning_letter.tasks2.physical_warning_letter_generation',
        'schedule': crontab(minute=30, hour=7),
    },
    # Kangtau
    'upload_customer_list': {
        'task': 'juloserver.minisquad.tasks2.upload_customer_list_task.upload_customer_list',
        'schedule': crontab(minute=0, hour=7),  # Schedule daily at 07.00 AM
    },
    'send_customer_odin_score_to_omnichannel': {
        'task': 'juloserver.apiv2.tasks.send_customer_odin_score_to_omnichannel',
        'schedule': crontab(minute=15, hour=0),
    },
    # physical warning letter bucket_b5_plus
    'physical_warning_letter_generation_bucket_b5_plus': {
        'task': 'juloserver.warning_letter.tasks2.physical_warning_letter_generation_bucket_b5_plus',
        'schedule': crontab(minute=00, hour=7),
    },
}
