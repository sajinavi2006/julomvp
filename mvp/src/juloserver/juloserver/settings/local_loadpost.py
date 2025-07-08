import os

"""
Load the env variables from postactivate script
"""

BASE_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), os.pardir, os.pardir)

with open(os.path.join(BASE_DIR, "envvars"), 'r') as envvars:
    for line in envvars:
        words = line.split()
        if words and words[0] == 'export':
            key, value = words[1].split('=', 1)
            value = value.replace('"', '')
            os.environ[key] = value

# Check if it's in docker environment by looking at the root dir (hackish).
# If yes, then also load the required env vars
if os.getcwd().startswith('/service'):
    with open(os.path.join(BASE_DIR, "postactivate_docker"), 'r') as envvars:
        for line in envvars:
            words = line.split()
            if words and words[0] == 'export':
                key, value = words[1].split('=', 1)
                value = value.replace('"', '')
                os.environ[key] = value

from .local import *
