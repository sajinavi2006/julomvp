DEFAULT_SECONDS_DELAY = 20 * 60


def calculate_countdown(total_row):
    """
    30k rows delay 20 minutes to report
    """

    seconds_delay = (total_row * DEFAULT_SECONDS_DELAY) / 30000
    return max(seconds_delay, DEFAULT_SECONDS_DELAY)
