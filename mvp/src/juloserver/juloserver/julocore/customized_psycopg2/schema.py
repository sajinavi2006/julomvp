from django.db.backends.postgresql_psycopg2.schema import DatabaseSchemaEditor


class CustomDatabaseSchemaEditor(DatabaseSchemaEditor):
    sql_set_sequence_owner = 'ALTER SEQUENCE %(sequence)s OWNED BY %(table)s.%(column)s'

    def _alter_column_type_sql(self, table, old_field, new_field, new_type):
        """
        Make ALTER TYPE with SERIAL make sense.
        References from:
        Django 4.0 https://github.com/django/django/commit/f944cb3d3bc17a97216f8990ff3bb4bee14b6f6b
        """
        if new_type.lower() in ("serial", "bigserial"):
            column = new_field.column
            sequence_name = "%s_%s_seq" % (table, column)
            col_type = "integer" if new_type.lower() == "serial" else "bigint"
            return (
                (
                    self.sql_alter_column_type
                    % {
                        "column": self.quote_name(column),
                        "type": col_type,
                    },
                    [],
                ),
                [
                    (
                        self.sql_delete_sequence
                        % {
                            "sequence": self.quote_name(sequence_name),
                        },
                        [],
                    ),
                    (
                        self.sql_create_sequence
                        % {
                            "sequence": self.quote_name(sequence_name),
                        },
                        [],
                    ),
                    (
                        self.sql_alter_column
                        % {
                            "table": self.quote_name(table),
                            "changes": self.sql_alter_column_default
                            % {
                                "column": self.quote_name(column),
                                "default": "nextval('%s')" % self.quote_name(sequence_name),
                            },
                        },
                        [],
                    ),
                    (
                        self.sql_set_sequence_max
                        % {
                            "table": self.quote_name(table),
                            "column": self.quote_name(column),
                            "sequence": self.quote_name(sequence_name),
                        },
                        [],
                    ),
                    (
                        self.sql_set_sequence_owner
                        % {
                            'table': self.quote_name(table),
                            'column': self.quote_name(column),
                            'sequence': self.quote_name(sequence_name),
                        },
                        [],
                    ),
                ],
            )
        else:
            return super(CustomDatabaseSchemaEditor, self)._alter_column_type_sql(
                table, old_field, new_field, new_type
            )
