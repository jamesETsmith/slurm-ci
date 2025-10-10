import os

import tomllib

from slurm_ci.config import STATUS_DIR


for file in os.listdir(STATUS_DIR):
    if file.endswith(".toml"):
        with open(os.path.join(STATUS_DIR, file), "rb") as f:
            status = tomllib.load(f)
        print(status)
