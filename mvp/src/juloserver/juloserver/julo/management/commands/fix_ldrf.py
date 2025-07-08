import psycopg2
import re
#import sdanalytics
from django.conf import settings
from django.core.management.base import BaseCommand


def fix_rows(rows, cur, conn):
    for row in rows:
        if row[2] == "LDRF":
            cur.execute("UPDATE docs_logs SET page_id='LDRSF' WHERE docs_logs_id='{}'".format(row[0]))


def fix_ldrsf(apps=None, schema_editor=None):
    """
    Fix these rows in analytics db  nav_id table to have LDRSF instead of LDRF
    2017-04-25 13:10:15.98 | LDRF | Screen opened
    2017-04-25 13:10:18.05 | LDRF | Button: "KONFIRMASI LOKASI RUMAH" clicked
    2017-04-25 13:10:18.15 | LDRF | Geo, Lat: -6.2537989, Long: 106.7788113
    2017-04-25 13:10:18.19 | LDRF | Geo, Lat: -6.2537989, Long: 106.7788113
    2017-04-25 13:10:21.49 | LDRF | Button: "SIMPAN" clicked
    2017-04-25 13:10:21.87 | LDRF | Screen closed

    Queries to validate data before and after script is run:
    SELECT * FROM docs_logs WHERE page_id='LDRF' and (action_taken LIKE 'Button: "KONFIRMASI LOKASI RUMAH"%' or action_taken LIKE 'Geo%');
    SELECT * FROM docs_logs WHERE page_id='LDRSF' and (action_taken LIKE 'Button: "KONFIRMASI LOKASI RUMAH"%' or action_taken LIKE 'Geo%');
    SELECT * FROM docs_logs WHERE page_id='LDRSF' and action_taken NOT LIKE 'Button: "SIMPAN" clicked' and action_taken NOT LIKE 'Screen opened' and action_taken NOT LIKE 'Screen closed' and action_taken NOT LIKE 'Button: "KONFIRMASI LOKASI RUMAH"%' and action_taken NOT LIKE 'Geo%';

    """

    analytics_db_str = "postgresql://%s:%s@%s:%s/%s" % (
        settings.POSTGRESQL_ANALYTICS_USER,
        settings.POSTGRESQL_ANALYTICS_PWD,
        settings.POSTGRESQL_ANALYTICS_HOSTNAME,
        settings.POSTGRESQL_ANALYTICS_PORT,
        settings.POSTGRESQL_ANALYTICS_DATABASE
    )
    # sdanalytics.create_tables(analytics_db_str)
    conn = psycopg2.connect("dbname='{}' user='{}' host='{}' password='{}' port='{}'".format(
                            settings.POSTGRESQL_ANALYTICS_DATABASE,
                            settings.POSTGRESQL_ANALYTICS_USER,
                            settings.POSTGRESQL_ANALYTICS_HOSTNAME,
                            settings.POSTGRESQL_ANALYTICS_PWD,
                            settings.POSTGRESQL_ANALYTICS_PORT))
    cur = conn.cursor()
    cur.execute("""SELECT docs_logs_id, action_taken, page_id FROM docs_logs""")
    status = "open"
    rows2change = []

    # 'd220_apid_2000000469' order by running number and then by application id
    # to get a consecutive actions for each apid
    rows = cur.fetchall()
    rows = sorted(rows, key=lambda x: int(re.search(r'\d+', x[0]).group()))
    rows = sorted(rows, key=lambda x: int(x[0][-10:]))
    backlog = []

    for row in rows:

        backlog.insert(0, row)
        if len(backlog) > 10:
            backlog.pop()

        if row[1] == "Screen opened" and row[2] == "LDRF":
            action_list = [x[1] for x in rows2change]
            if any("KONFIRMASI LOKASI RUMAH" in x for x in action_list) or any("Geo" in x for x in action_list):
                fix_rows(rows2change, cur, conn)
            rows2change = []
            rows2change.append(row)
            status = "close"

        elif status == "close" and ("KONFIRMASI LOKASI RUMAH" in row[1] or
                                    "Geo" in row[1] or
                                    'Button: "SIMPAN"' in row[1]):
            rows2change.append(row)

        elif status == "open" and ("KONFIRMASI LOKASI RUMAH" in row[1] or
                                   "Geo" in row[1]):
            try:
                ind = [(x[1], x[2]) for x in backlog].index(("Screen opened", "LDRF"))
                for add in backlog[:ind]:
                    rows2change.append(add)
            except ValueError:
                pass
            status = "close"
            rows2change.append(row)

        elif status == "close" and row[1] == "Screen closed":
            rows2change.append(row)
            action_list = [x[1] for x in rows2change]
            if any("KONFIRMASI LOKASI RUMAH" in x for x in action_list) or any("Geo" in x for x in action_list):
                fix_rows(rows2change, cur, conn)
            status = "open"
            rows2change = []

        else:
            action_list = [x[1] for x in rows2change]
            if any("KONFIRMASI LOKASI RUMAH" in x for x in action_list) or any("Geo" in x for x in action_list):
                fix_rows(rows2change, cur, conn)

            status = "open"
            rows2change = []

    conn.commit()
    cur.close()
    conn.close()


class Command(BaseCommand):
    help = 'One time fix for the the analytics database docs_logs data (LDRF => LDRSF)'

    def handle(self, *args, **options):
        fix_ldrsf()
