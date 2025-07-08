import logging
from contextlib import contextmanager, ExitStack
from django.db import transaction, DatabaseError

logger = logging.getLogger(__name__)


@contextmanager
def db_transactions_atomic(databases):
    """
    Make DB queries in multiple transactions across multiple DBs effectively atomic.

    Args:
        databases (set): Set of database names to apply atomic transactions.

    Raises:
        DatabaseError: If any database operation fails.
    """
    try:
        with ExitStack() as stack:
            for db in databases:
                stack.enter_context(transaction.atomic(using=db))
            yield
    except DatabaseError as err:
        logger.error({
            'action': 'juloserver.julocore.context_manager.multi_db_transactions',
            'error': err,
        })
        raise
