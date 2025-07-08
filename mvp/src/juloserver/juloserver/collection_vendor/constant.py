from builtins import object
from argparse import Namespace


class CollectionVendorCodes(object):
    VENDOR_TYPES = {
        'special': 'Special',
        'general': 'General',
        'final': 'Final',
        'b4': 'B4',
    }


class CollectionVendorAssignmentConstant(object):
    SKIPTRACE_CALL_STATUS_ASSIGNED_CRITERIA = (
        'RPC - Regular',
        'RPC - PTP',
        'RPC - HTP',
        'RPC - Broken Promise',
        'Whatsapp - Text',
    )
    MINIMUM_PAY_PER_BUCKET = Namespace(
        **{
            'sub_1': 50000,
            'sub_2': 1000,
            'sub_3': 1500,
        }
    )
    EXPIRATION_DAYS_BY_VENDOR_TYPE = Namespace(
        **{
            'special': 30,
            'general': 90,
            'final': 180,
        }
    )


class AgentAssignmentConstant(object):
    MAXIMUM_THRESHOLD = Namespace(
        **{
            'sub_1': 750,
            'sub_2': 1000,
            'sub_3': 1500,
        }
    )


class Bucket5Threshold(object):
    DPD_REACH_BUCKET_5 = 91


class CollectionAssignmentConstant(object):
    ASSIGNMENT_REASONS = {
        'RPC_ELIGIBLE_CALLING_STATUS': 'Account has RPC Eligible calling status',
        'ASSIGNMENT_EXPIRED_GTE_30_DAYS': 'Assignment expired because it has passed 30 days',
        'ASSIGNMENT_EXPIRED_END_OF_BUCKET': 'Assignment expired because it has '
                                            'reached the end of bucket',
        'ACCOUNT_MOVED_VENDOR_EXCEEDS_THRESHOLD': 'Account moved to Vendor because {} of '
                                                  'agent account exceeds threshold',
        'ACCOUNT_MOVED_VENDOR_PAYMENT_LTE_50K': 'Account moved to Vendor because payment '
                                                'amount <= 50,000',
        'ACCOUNT_MOVED_VENDOR_LAST_CONTACTED_GTE_30_DAYS': 'Account moved to Vendor because '
                                                           'last contacted date >= 30 days',
        'ACCOUNT_MOVED_VENDOR_LAST_PAYMENT_GTE_60_DAYS': 'Account moved to Vendor because last '
                                                         'payment date >= 60 days',
        'ASSIGNMENT_EXPIRED_VENDOR_END': 'Assignment expired at Vendor end',
        'ACCOUNT_SYSTEM_TRANSFERRED_AGENT': 'Account automatically transferred to agent',
        'ACCOUNT_SYSTEM_TRANSFERRED_VENDOR': 'Account automatically transferred to vendor',
        'ACCOUNT_SYSTEM_TRANSFERRED_INHOUSE': 'Account automatically transferred to inhouse',
        'ACCOUNT_MANUALLY_TRANSFERRED_AGENT': 'Account manually transferred to agent',
        'ACCOUNT_MANUALLY_TRANSFERRED_VENDOR': 'Account manually transferred to vendor',
        'ACCOUNT_MANUALLY_TRANSFERRED_INHOUSE': 'Account manually transferred to inhouse',
        'PAID': 'Customer already paid payment or account payment',
    }
