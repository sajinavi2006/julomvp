from django.db import connections

def ensure_grab_restructure_history_log_table_exists():
    check_query = """
    select
        exists (
        select
            *
        from
            information_schema.tables
        where
            table_name = 'grab_restructure_history_log'
    );
    """

    create_query = """
    CREATE TABLE grab_restructure_history_log (
        cdate timestamptz NOT NULL,
        udate timestamptz NOT NULL,
        grab_restructure_history_log_id BIGSERIAL PRIMARY KEY,
        loan_id int8 NULL,
        is_restructured bool NULL,
        restructure_date timestamptz NULL
    );
    """

    connection = connections["partnership_grab_db"]
    with connection.cursor() as cursor:
        cursor.execute(check_query)
        table_exists = cursor.fetchone()[0]
        if not table_exists:
            cursor.execute(create_query)
