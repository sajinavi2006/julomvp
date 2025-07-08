from django.core.exceptions import ImproperlyConfigured
from django.db.backends.postgresql_psycopg2.base import (
    DatabaseWrapper as OriginalDatabaseWrapper,
)
from django.db.backends.postgresql_psycopg2.base import psycopg2_version
from django.utils.safestring import SafeBytes, SafeText

from juloserver.julocore.customized_psycopg2.creation import CustomDatabaseCreation
from juloserver.julocore.customized_psycopg2.schema import CustomDatabaseSchemaEditor

try:
    import psycopg2 as Database
    import psycopg2.extensions
    import psycopg2.extras
except ImportError as e:
    raise ImproperlyConfigured("Error loading psycopg2 module: %s" % e)


PSYCOPG2_VERSION = psycopg2_version()

if PSYCOPG2_VERSION < (2, 4, 5):
    raise ImproperlyConfigured(
        "psycopg2_version 2.4.5 or newer is required; you have %s" % psycopg2.__version__
    )

DatabaseError = Database.DatabaseError
IntegrityError = Database.IntegrityError

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)
psycopg2.extensions.register_adapter(SafeBytes, psycopg2.extensions.QuotedString)
psycopg2.extensions.register_adapter(SafeText, psycopg2.extensions.QuotedString)
psycopg2.extras.register_uuid()

# Register support for inet[] manually so we don't have to handle the Inet()
# object on load all the time.
INETARRAY_OID = 1041
INETARRAY = psycopg2.extensions.new_array_type(
    (INETARRAY_OID,),
    'INETARRAY',
    psycopg2.extensions.UNICODE,
)
psycopg2.extensions.register_type(INETARRAY)


class DatabaseWrapper(OriginalDatabaseWrapper):
    SchemaEditorClass = CustomDatabaseSchemaEditor
    OriginalDatabaseWrapper.data_types.update({'BigAutoField': 'bigserial'})

    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)
        self.creation = CustomDatabaseCreation(self)
