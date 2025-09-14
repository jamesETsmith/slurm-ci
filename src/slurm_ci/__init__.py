from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("slurm-ci")
except PackageNotFoundError:
    # package is not installed
    pass
