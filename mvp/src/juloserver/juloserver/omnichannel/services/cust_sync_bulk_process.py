from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import operator
import pandas as pd
import traceback
import typing
import uuid

from django.db import connection
from django.db.backends.utils import CursorWrapper

from juloserver.julo.services2 import get_redis_client
from juloserver.monitors.notifications import get_slack_sdk_web_client
from juloserver.omnichannel.models import OmnichannelCustomerSyncBulkProcessHistory
from juloserver.omnichannel.constants import (
    BULK_PROCESS_GUIDELINE_URL,
    COLUMN_TO_CHANNEL,
    CRM_OMNI_MONITORING_CHANNEL,
    CRM_OMNI_MONITORING_USERNAME,
    PRE_CRM_FORMATTED,
    ACTION_TO_MEANING,
)


logger = logging.getLogger(__name__)


class CustomerSyncBulkProcessRepository:
    BATCH_SIZE = 1000

    def __init__(
        self,
        customer_ids: typing.List[int],
        parameters: typing.Dict[str, typing.Any],
        batch_size: typing.Optional[int] = None,
        cursor: CursorWrapper = None,
    ):
        self.customer_ids = customer_ids
        self.total_data = len(customer_ids)

        self.parameters = parameters
        self.action_by = ''
        self.action = ''
        self.sync_rollout_attr = False
        self.sync_cust_attribute = False
        self.is_rollout_pds = False
        self.is_rollout_pn = False
        self.is_rollout_sms = False
        self.is_rollout_email = False
        self.is_rollout_one_way_robocall = False
        self.is_rollout_two_way_robocall = False
        self.batch_size = batch_size or self.BATCH_SIZE
        self.notes = '-'
        self.rollout_channels = []
        self.set_attr_from_param()

        self.cursor = cursor

    def set_attr_from_param(self):
        for k, v in self.parameters.items():
            if hasattr(self, k):
                setattr(self, k, v)
            if k.startswith('is_rollout'):
                self.rollout_channels.append(COLUMN_TO_CHANNEL.get(k))

    @classmethod
    def customer_id_batch_generator(cls, customer_ids, total_data, batch_size=None):
        if batch_size is None:
            batch_size = cls.BATCH_SIZE
        for start in range(0, total_data, batch_size):
            end = min(start + batch_size, total_data)
            yield customer_ids[start:end]

    def dispatch(self, customer_ids, account_ids) -> typing.List[int]:
        if not customer_ids or not account_ids:
            return None
        if hasattr(self, self.action):
            return getattr(self, self.action)(customer_ids, account_ids)
        return None

    def __query(self, q, params=None, custom_func=None) -> typing.List[int]:
        if self.cursor is None:
            with connection.cursor() as cursor:
                cursor.execute(q, params)
                if custom_func:
                    return custom_func(cursor.fetchall())
                return list(map(lambda row: int(row[0]), cursor.fetchall()))

        self.cursor.execute(q, params)
        if custom_func:
            return custom_func(self.cursor.fetchall())
        return list(map(lambda row: int(row[0]), self.cursor.fetchall()))

    def __map_cust_to_acc_id_from_list(self, query_res: typing.List[typing.Tuple[str, str]]):
        cust_to_acc = {}
        for res in query_res:
            cust_to_acc[res[0]] = res[1]
        return cust_to_acc

    def validate_customer_ids(self, customer_ids) -> typing.Dict[str, str]:
        if not customer_ids:
            return []
        q = """
        SELECT c.customer_id, a.account_id
        FROM ops.customer c
        JOIN ops.account a ON a.customer_id=c.customer_id
        WHERE c.customer_id=ANY(ARRAY[{cust_ids}])
        GROUP BY c.customer_id, a.account_id
        """.format(
            cust_ids=','.join(['%s' for _ in range(len(customer_ids))])
        )
        return self.__query(q, list(customer_ids), self.__map_cust_to_acc_id_from_list)

    def get_insert_param(self, customer_ids, account_ids):
        params = ['cdate', 'udate', 'customer_id', 'account_id']
        values = [
            'UNNEST(ARRAY[{rollout}])'.format(
                rollout=','.join(['NOW()' for _ in range(len(customer_ids))])
            ),
            'UNNEST(ARRAY[{rollout}])'.format(
                rollout=','.join(['NOW()' for _ in range(len(customer_ids))])
            ),
            'UNNEST(ARRAY[{cust_ids}])'.format(
                cust_ids=','.join(['%s' for _ in range(len(customer_ids))])
            ),
            'UNNEST(ARRAY[{acc_ids}])'.format(
                acc_ids=','.join(['%s' for _ in range(len(account_ids))])
            ),
        ]
        rollouts = [
            'is_rollout_pds',
            'is_rollout_pn',
            'is_rollout_sms',
            'is_rollout_email',
            'is_rollout_one_way_robocall',
            'is_rollout_two_way_robocall',
        ]
        for r in rollouts:
            params.append(r)
            if hasattr(self, r) and getattr(self, r, False):
                values.append(
                    'UNNEST(ARRAY[{rollout}])'.format(
                        rollout=','.join(['true' for _ in range(len(customer_ids))])
                    )
                )
                continue
            if hasattr(self, r):
                values.append(
                    'UNNEST(ARRAY[{rollout}])'.format(
                        rollout=','.join(['false' for _ in range(len(customer_ids))])
                    )
                )
        placeholders = customer_ids + account_ids
        return params, values, placeholders

    def base_upsert(self, params, values, action_query, placeholders=None):
        q = """
        INSERT INTO ops.omnichannel_customer_sync ({params})
        SELECT {values}
        ON CONFLICT (customer_id) DO {action}
        RETURNING customer_id
        """.format(
            params=', '.join(params), values=', '.join(values), action=action_query
        )
        return self.__query(q, params=placeholders)

    def insert(self, customer_ids, account_ids):
        params, values, placeholders = self.get_insert_param(customer_ids, account_ids)
        return self.base_upsert(params, values, action_query='NOTHING', placeholders=placeholders)

    def upsert(self, customer_ids, account_ids):
        params, values, placeholders = self.get_insert_param(customer_ids, account_ids)
        q = []
        for p in params:
            if p == 'cdate':
                continue
            q.append('{p} = excluded.{p}'.format(p=p))

        action_query = 'NOTHING'
        if q:
            action_query = 'UPDATE SET ' + ', '.join(q)

        return self.base_upsert(
            params, values, action_query=action_query, placeholders=placeholders
        )


class CustomerSyncBulkProcessRedisRepository:
    REDIS_PREFIX = 'BulkProcess::OmnichannelCustomerSync'
    CACHE_TTL = 60 * 60 * 24 * 7
    SEPARATE_COLS = ['processed_num', 'success_num', 'fail_num', 'percentage', 'total']
    DATA_KEY = 'data'

    class NumCols:
        PROCESSED = 'processed_num'
        SUCCESS = 'success_num'
        FAIL = 'fail_num'
        PCT = 'percentage'
        TOTAL = 'total'

    def __init__(self, task_id=None, redis_client=None):
        self.task_id = task_id
        if self.task_id is None:
            self.task_id = self.generate_task_id()

        self.cache = redis_client
        if self.cache is None:
            self.cache = get_redis_client()

    @staticmethod
    def generate_task_id():
        return str(uuid.uuid4())

    def __key(self, *args):
        keys = [self.REDIS_PREFIX, self.task_id] + list(args)
        return '::'.join(keys)

    def set(self, data: OmnichannelCustomerSyncBulkProcessHistory):
        self.cache.set(
            self.__key(self.DATA_KEY),
            json.dumps(data.to_dict_partial(self.SEPARATE_COLS)),
            self.CACHE_TTL,
        )
        for c in self.SEPARATE_COLS:
            self.cache.set(self.__key(c), getattr(data, c), self.CACHE_TTL)

    def get(self) -> OmnichannelCustomerSyncBulkProcessHistory:
        try:
            data = json.loads(self.cache.get(self.__key(self.DATA_KEY)))
            obj = OmnichannelCustomerSyncBulkProcessHistory(**data)
            for c in self.SEPARATE_COLS:
                setattr(obj, c, self.cache.get(self.__key(c)))
            return obj
        except Exception:
            logger.error(
                {
                    "action": "CustomerSyncBulkProcessRedisRepository.get",
                    "key": self.__key(self.DATA_KEY),
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )
            return None

    @classmethod
    def list(
        cls, sort_by='started_at', reverse_sort=True
    ) -> typing.List[OmnichannelCustomerSyncBulkProcessHistory]:
        cache = get_redis_client()
        all_keys = cache.client.keys(cls.REDIS_PREFIX + '::*::data')
        if not all_keys:
            return []
        task_ids = [k.decode().split('::')[-2] for k in all_keys]
        data = []
        for t in task_ids:
            get_data = CustomerSyncBulkProcessRedisRepository(task_id=t, redis_client=cache).get()
            if get_data:
                data.append(get_data)
        return sorted(data, key=operator.attrgetter(sort_by), reverse=reverse_sort)

    def incr(self, success=True, amount=1):
        if amount == 0:
            return
        proc = self.cache.client.incr(self.__key(self.NumCols.PROCESSED), amount)
        total = self.cache.get(self.__key(self.NumCols.TOTAL))
        self.cache.set(self.__key(self.NumCols.PCT), '{:.2f}%'.format((proc / int(total)) * 100))
        if success:
            self.cache.client.incr(self.__key(self.NumCols.SUCCESS), amount)
            return
        self.cache.client.incr(self.__key(self.NumCols.FAIL), amount)

    def delete(self):
        return self.cache.client.delete(*self.cache.client.keys(self.__key('*')))

    @classmethod
    def clear(cls):
        cache = get_redis_client()
        keys = cache.client.keys('::'.join([cls.REDIS_PREFIX, '*']))
        if not keys:
            return
        return cache.client.delete(*keys)


@dataclass
class CustomerSyncBulkProcessSlackRepository:
    started_at: datetime
    environment: str
    task_id: str
    cust_svc: CustomerSyncBulkProcessRepository

    def __post_init__(self):
        self.slack_client = get_slack_sdk_web_client()

    def send_bulk_process_notif_start(self):
        try:
            resp = self.slack_client.chat_postMessage(
                channel=CRM_OMNI_MONITORING_CHANNEL,
                blocks=self.block_template_main_thread_start.get("blocks"),
                text=" ",
                username=CRM_OMNI_MONITORING_USERNAME,
                icon_emoji=":catspinq:",
            )
            if resp and not resp.get('ok', False):
                logger.error(
                    {
                        "action": "send_bulk_process_notif_start",
                        "task_id": self.task_id,
                        "message": str(resp or ""),
                        "level": "error",
                    }
                )
                return None
            return resp.get("ts")
        except Exception:
            logger.error(
                {
                    "action": "send_bulk_process_notif_start",
                    "task_id": self.task_id,
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )
            return None

    def get_permalink_from_ts(self, thread_ts: str):
        try:
            resp = self.slack_client.chat_getPermalink(
                channel=CRM_OMNI_MONITORING_CHANNEL, message_ts=thread_ts
            )
            if resp and not resp.get('ok', False):
                logger.error(
                    {
                        "action": "get_permalink_from_ts",
                        "task_id": self.task_id,
                        "message": str(resp or ""),
                        "level": "error",
                    }
                )
                return None
        except Exception:
            logger.error(
                {
                    "action": "get_permalink_from_ts",
                    "task_id": self.task_id,
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )
            return None
        return resp.get("permalink")

    def send_bulk_process_report(
        self,
        thread_ts: str,
        process_result: OmnichannelCustomerSyncBulkProcessHistory,
        failed_process: typing.Optional[
            typing.Dict[str, typing.List[typing.Union[str, int]]]
        ] = None,
    ):
        self.send_reply_to_bulk_process(
            thread_ts, self.construct_bulk_process_result(process_result)
        )

        if not failed_process:
            return

        data = self.construct_failed_bulk_process_as_csv_bytes(failed_process)
        if not data:
            return

        self.send_failed_process_file_report(data, thread_ts)

    def construct_bulk_process_result(
        self, process_result: OmnichannelCustomerSyncBulkProcessHistory
    ):
        try:
            text = "Bulk process has been completed.\n"
            text += "{}/{} ({} success)".format(
                str(process_result.success_num),
                str(process_result.total),
                '{:.2f}%'.format(
                    (int(process_result.success_num) / int(process_result.total)) * 100
                ),
            )
            return text
        except Exception:
            logger.error(
                {
                    "action": "construct_bulk_process_result",
                    "task_id": self.task_id,
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )
            return None

    def send_reply_to_bulk_process(self, thread_ts: str, text_to_send: str):
        try:
            if not text_to_send:
                return
            resp = self.slack_client.chat_postMessage(
                channel=CRM_OMNI_MONITORING_CHANNEL,
                thread_ts=thread_ts,
                text=text_to_send,
                username=CRM_OMNI_MONITORING_USERNAME,
                icon_emoji=":catspinq:",
            )
            if resp and not resp.get('ok', False):
                logger.error(
                    {
                        "action": "send_bulk_process_result",
                        "task_id": self.task_id,
                        "message": str(resp or ""),
                        "level": "error",
                    }
                )
        except Exception:
            logger.error(
                {
                    "action": "send_bulk_process_result",
                    "task_id": self.task_id,
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )

    def construct_failed_bulk_process_as_csv_bytes(
        self, failed_process: typing.Dict[str, typing.List[typing.Union[str, int]]] = None
    ):
        if not failed_process:
            return None
        try:
            df = pd.DataFrame.from_dict(failed_process)
            return df.to_csv(index=False).encode()
        except Exception:
            logger.error(
                {
                    "action": "construct_failed_bulk_process_as_csv_bytes",
                    "task_id": self.task_id,
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )
        return None

    def send_failed_process_file_report(self, data: bytes, thread_ts: str):
        try:
            res = self.slack_client.files_upload_v2(
                file=data,
                filename=self.task_id + '.csv',
                thread_ts=thread_ts,
                channel=CRM_OMNI_MONITORING_CHANNEL,
                initial_comment='Bulk Process Failed Report',
                username=CRM_OMNI_MONITORING_USERNAME,
                icon_emoji=":catspinq:",
            )
            if res and not res.get('ok', False):
                logger.error(
                    {
                        "action": "send_bulk_process_result",
                        "task_id": self.task_id,
                        "message": str(res or ""),
                        "level": "error",
                    }
                )
        except Exception:
            logger.error(
                {
                    "action": "send_bulk_process_report",
                    "task_id": self.task_id,
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )

    @property
    def block_template_main_thread_start(self):
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Bulk Process Notification"},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Started at {} by {} \nEnvironment: {} \nTask ID: {}".format(
                                self.started_at.strftime("%B %d, %Y %H:%M"),
                                self.cust_svc.action_by,
                                self.environment.title(),
                                self.task_id,
                            ),
                        }
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":meow_bongo: *Omnichannel Customer Sync Bulk Process*\n\nBulk process was triggered from django admin panel with action *{action}*. It means, this process will *{action}* customer_id that uploaded through django admin to the omnichannel_customer_sync table with additional parameters below.".format(  # noqa
                            action=ACTION_TO_MEANING.get(self.cust_svc.action.lower(), "").upper()
                        ),
                    },
                    "accessory": {
                        "type": "image",
                        "image_url": "https://i.giphy.com/media/v1.Y2lkPTc5MGI3NjExbjR2Y2w4b2p3ZnMyYmp3am83amM5NjFlbDdrbXFqc3BmMDhscmRkaiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/y4ot9l2lAalRiwdinp/giphy.gif",  # noqa
                        "alt_text": "batch process",
                    },
                },
                {"type": "divider"},
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {"type": "emoji", "name": "mag", "unicode": "1f50d"},
                                {
                                    "type": "text",
                                    "text": " Additional Parameters",
                                    "style": {"bold": True},
                                },
                                {"type": "text", "text": "\n"},
                            ],
                        },
                        {
                            "type": "rich_text_list",
                            "style": "bullet",
                            "indent": 0,
                            "border": 0,
                            "elements": [
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {
                                            "type": "text",
                                            "text": "Sync Rollout Attribute to the Omnichannel: ",
                                        },
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.sync_rollout_attr),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {
                                            "type": "text",
                                            "text": "Sync Customer Attribute to the Omnichannel: ",
                                        },
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.sync_cust_attribute),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [{"type": "text", "text": "Rollout Attribute:"}],
                                },
                            ],
                        },
                        {
                            "type": "rich_text_list",
                            "style": "bullet",
                            "indent": 1,
                            "border": 0,
                            "elements": [
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {"type": "text", "text": "PN: "},
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.is_rollout_pn),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {"type": "text", "text": "SMS: "},
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.is_rollout_sms),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {"type": "text", "text": "Email: "},
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.is_rollout_email),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {"type": "text", "text": "One Way Robocall: "},
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.is_rollout_one_way_robocall),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {"type": "text", "text": "Two Way Robocall: "},
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.is_rollout_two_way_robocall),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {"type": "text", "text": "PDS: "},
                                        {
                                            "type": "text",
                                            "text": str(self.cust_svc.is_rollout_pds),
                                            "style": {"bold": True},
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":green_book: *Notes* \n{}".format(self.cust_svc.notes or '-'),
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "<{}|Bulk Process Guideline>".format(BULK_PROCESS_GUIDELINE_URL),
                    },
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "cc: {}".format(PRE_CRM_FORMATTED)}],
                },
            ]
        }
