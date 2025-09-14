import tomllib
import os

from slurm_ci.slurm_launcher import STATUS_DIR

for file in os.listdir(STATUS_DIR):
    if file.endswith(".toml"):
        with open(os.path.join(STATUS_DIR, file), "rb") as f:
            status = tomllib.load(f)
        print(status)
