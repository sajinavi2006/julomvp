from datetime import datetime, timedelta


def add_minutes_to_datetime(tm, mins):
    fulldate = datetime(100, 1, 1, tm.hour, tm.minute, tm.second)
    fulldate = fulldate + timedelta(minutes=mins)
    return fulldate.time()


def convert_gender(gender):
    if gender == 'Wanita':
        return 'female'
    elif gender == 'Pria':
        return 'male'
    else:
        return ''
