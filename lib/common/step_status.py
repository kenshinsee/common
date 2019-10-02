from enum import Enum, unique

@unique
class StepStatus(Enum):
    SUCCESS = 0
    ERROR = 1
    CANCEL = 2
    RUNNING = 3
    FORCE = 4
