from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("slurm-ci")
except PackageNotFoundError:
    # package is not installed
    pass
