"""
celery_custom.py
Override DjangoWOrkerFixup to fix a bug celery libr
"""
from builtins import str
import os
import logging

from kombu.utils import cached_property, symbol_by_name

from celery.fixups.django import _maybe_close_fd
from celery.fixups.django import DjangoWorkerFixup, DjangoFixup

logger = logging.getLogger(__name__)



def fixup(app, env='DJANGO_SETTINGS_MODULE'):
    SETTINGS_MODULE = os.environ.get(env)
    if SETTINGS_MODULE and 'django' not in app.loader_cls.lower():
        try:
            import django  # noqa
        except ImportError:
            warnings.warn(FixupWarning(ERR_NOT_INSTALLED))
        else:
            return DjangoFixupCustom(app).install()

class DjangoFixupCustom(DjangoFixup):

    @cached_property
    def worker_fixup(self):
        if self._worker_fixup is None:
            self._worker_fixup = DjangoWorkerFixupCustom(self.app)
        return self._worker_fixup


class DjangoWorkerFixupCustom(DjangoWorkerFixup):
    """Fix bug interface error
    """
    def __init__(self, app):
        super(DjangoWorkerFixupCustom, self).__init__(app)
        self.interface_errors = (
            symbol_by_name('django.db.utils.InterfaceError'),
        )


    def on_worker_process_init(self, **kwargs):
        # Child process must validate models again if on Windows,
        # or if they were started using execv.
        if os.environ.get('FORKED_BY_MULTIPROCESSING'):
            self.validate_models()

        # close connections:
        # the parent process may have established these,
        # so need to close them.

        # calling db.close() on some DB connections will cause
        # the inherited DB conn to also get broken in the parent
        # process so we need to remove it without triggering any
        # network IO that close() might cause.
        try:
            for c in self._db.connections.all():
                if c and c.connection:
                    logger.info({
                        "action": "close_parent_connection",
                        "data":c.connection
                        })
                    self._maybe_close_db_fd(c.connection)
        except AttributeError:
            if self._db.connection and self._db.connection.connection:
                self._maybe_close_db_fd(self._db.connection.connection)

        # use the _ version to avoid DB_REUSE preventing the conn.close() call
        self._close_database()
        self.close_cache()


    def _maybe_close_db_fd(self, fd):
        try:
            _maybe_close_fd(fd)
        except self.interface_errors:
            pass
        except self.database_errors as exc:
            logger.error(exc)


    def _close_database(self):
        try:
            funs = [conn.close for conn in self._db.connections.all()]
        except AttributeError:
            if hasattr(self._db, 'close_old_connections'):  # django 1.6
                funs = [self._db.close_old_connections]
            else:
                # pre multidb, pending deprication in django 1.6
                funs = [self._db.close_connection]

        for close in funs:
            try:
                close()
            except self.interface_errors:
                pass
            except self.database_errors as exc:
                str_exc = str(exc)
                if 'closed' not in str_exc and 'not connected' not in str_exc:
                    raise
