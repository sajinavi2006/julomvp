
class SendingRecordingConfig(object):
    RECORDING_RESOURCES = [
        ('SME', 'SME'),
        ('AiRudder', 'AiRudder')
    ]
    RECORDING_DURATION_TYPE = (
        ('', '---------'), ('lte', 'Less Than'),
        ('gte', 'Greater Than'), ('between', 'Between')
    )


class QAAirudderResponse(object):
    SUCCESS = 'Success'
    FAILURE = 'Failure'
    OVERTIME = 'Overtime'
    OK = 'OK'


class QAAirudderTaskAction(object):
    START = 'Start'
    CANCEL = 'Cancel'


class QAAirudderAPIPhase(object):
    INITIATED = 'INITIATED'
    OBTAIN_TOKEN = 'OBTAIN TOKEN'
    CREATING_TASK = 'CREATING TASK'
    UPLOAD_RECORDING = 'UPLOAD RECORDING'
    START_TASK = 'START TASK'
    CANCEL_TASK = 'CANCEL TASK'
