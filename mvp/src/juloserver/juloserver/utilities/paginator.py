from django.core.paginator import Paginator
from django.db import connection, transaction, OperationalError
from django.utils.functional import cached_property

from juloserver.utilities.constants import TimeLimitedPaginatorConstants


class TimeLimitedPaginator(Paginator):
    """
    Paginator that enforced a timeout on the count operation.
    When the timeout is reached a "fake" large value is returned instead,
    """

    def __init__(self, object_list, per_page, orphans=0, allow_empty_first_page=True, **kwargs):
        self.timeout = kwargs.get('timeout', TimeLimitedPaginatorConstants.DEFAULT_TIMEOUT)
        super(TimeLimitedPaginator, self).__init__(
            object_list, per_page, orphans, allow_empty_first_page
        )

    @cached_property
    def count(self):
        """
        We set the timeout in a db transaction to prevent it from
        affecting other transactions.
        """
        with transaction.atomic(), connection.cursor() as cursor:
            sql = 'SET LOCAL statement_timeout TO %s;'
            params = [self.timeout]
            cursor.execute(sql, params)
            try:
                return super(TimeLimitedPaginator, self).count
            except OperationalError:
                return 999999999999


class FixPaginator(Paginator):
    """
    Paginator that prevent count query.
    """
    @cached_property
    def count(self):
        return 1000
