# Database configuration
DATABASE_URL = "sqlite:///./ci_builds.db"

# GitHub configuration
GITHUB_SECRET = "your_github_webhook_secret_here"
GITHUB_TOKEN = "your_personal_access_token_here"

# Path configuration for the cluster
# This MUST be the absolute path to the job_executor.py script
# on the filesystem accessible by the Slurm compute nodes.
EXECUTOR_PATH = "/path/on/cluster/to/job_executor.py"
