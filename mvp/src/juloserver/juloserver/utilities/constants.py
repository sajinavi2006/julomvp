

from builtins import object
class CommonVariables(object):
    RULE_DISBURSEMENT_TRAFFIC = "disbursement_traffic_rule"
    POSITIONAL_CONDITION = ["#nth", "#nthlte", "#nthgte", "#nthlt", "#nthgt", "#ntheq"]
    NON_POSITIONAL_CONDITION = ["#eq", "#lte", "#gte", "#lt", "#gt"]
    CONDITION = POSITIONAL_CONDITION + NON_POSITIONAL_CONDITION
    DISBURSEMENT_RULE_VALUES = (
        ('instamoney', 'instamoney'),
        ('xfers', 'xfers'),
        ('bca', 'bca'),
    )
    TRAFFIC_RULES = (
        (RULE_DISBURSEMENT_TRAFFIC, RULE_DISBURSEMENT_TRAFFIC),
    )
    TRAFFIC_RULES_KEYS = (
        ("application_id", "application_id"),
        ("application_xid", "application_xid"),
        ("customer_id", "customer_id"),
    )


    DEFAULT_SLACK_USERS = [
        {"name": "Wita Septiana", "slack_id": "U3Y0SKKUK"},
        {"name": "Anastasia Hasiane", "slack_id": "U3KTGV6RX"},
        {"name": "Ken", "slack_id": "UAJV2BAJZ"},
        {"name": "Lisen", "slack_id": "UC4DMB85S"},
        {"name": "Meitina", "slack_id": "UA9CQ8AR0"},
        {"name": "Rizky Sonia Pradja", "slack_id": "U7B66LMC1"},
        {"name": "Anissa Maegiya Indah", "slack_id": "UA0BMMF5L"}
    ]

    DEFAULT_SLACK_EWA = [{
        "status_code": 120,
        "display_text": "Documents submitted",
        "order_priority": 1,
        "emoji_con": [],
        "tag_con": [],
    },
        {
        "status_code": 121,
        "display_text": "Scraped data verified",
        "order_priority": 2,
        "emoji_con": [{
            "condition": "count <= 200",
            "emotion": ":crying_cat_face:"
        },
            {
            "condition": "200 < count <= 300",
            "emotion": ":ok_hand:"
        },
            {
            "condition": "300 < count <= 500",
            "emotion": ":notbad:"
        },
            {
            "condition": "count > 500",
            "emotion": ":bananadance:"
        }
        ],
        "tag_con": [{
            "condition": "count > 200",
            "slack_users": [
                DEFAULT_SLACK_USERS[0],
                DEFAULT_SLACK_USERS[1],
                DEFAULT_SLACK_USERS[2],
                DEFAULT_SLACK_USERS[3],
            ]
        }],
    },
        {
        "status_code": 122,
        "display_text": "Documents verified",
        "order_priority": 3,
        "emoji_con": [],
        "tag_con": [{
            "condition": "count > 100",
            "slack_users": [
                DEFAULT_SLACK_USERS[0],
                DEFAULT_SLACK_USERS[1],
                DEFAULT_SLACK_USERS[2],
                DEFAULT_SLACK_USERS[3],
            ]
        }],
    },
        {
        "status_code": 124,
        "display_text": "Verification calls successful",
        "order_priority": 4,
        "emoji_con": [],
        "tag_con": [{
            "condition": "count > 100",
            "slack_users": [
                DEFAULT_SLACK_USERS[0],
                DEFAULT_SLACK_USERS[1],
                DEFAULT_SLACK_USERS[2],
                DEFAULT_SLACK_USERS[3],
            ]
        }],
    },
        {
        "status_code": 130,
        "display_text": "Applicant calls successful",
        "order_priority": 5,
        "emoji_con": [],
        "tag_con": [],
    },
        {
        "status_code": 138,
        "display_text": "Verification calls ongoing",
        "order_priority": 6,
        "emoji_con": [],
        "tag_con": [{
            "condition": "count > 200",
            "slack_users": [
                DEFAULT_SLACK_USERS[0],
                DEFAULT_SLACK_USERS[1],
                DEFAULT_SLACK_USERS[2],
                DEFAULT_SLACK_USERS[3],
            ]
        }],
    },
        {
        "status_code": 141,
        "display_text": "Offer accepted by customer",
        "order_priority": 7,
        "emoji_con": [],
        "tag_con": [],
    },
        {
        "status_code": 172,
        "display_text": "Legal agreement signed and dp pending",
        "order_priority": 8,
        "emoji_con": [],
        "tag_con": [],
    },
        {
        "status_code": 163,
        "display_text": "Legal Agreement docs submitted",
        "order_priority": 9,
        "emoji_con": [],
        "tag_con": [{
            "condition": "count > 50",
            "slack_users": [
                DEFAULT_SLACK_USERS[4],
                DEFAULT_SLACK_USERS[5],
                DEFAULT_SLACK_USERS[6],
                DEFAULT_SLACK_USERS[2],
            ]
        }],
    },
        {
        "status_code": 180,
        "display_text": "Fund disbursal successful",
        "order_priority": 10,
        "emoji_con": [],
        "tag_con": [],
    },
    ]


class TimeLimitedPaginatorConstants:
    DEFAULT_TIMEOUT = 100  # ms
