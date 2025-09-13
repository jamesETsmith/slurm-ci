## Design Goals

- Make it easier to run CI workflows locally
  - `nektos/act` essentially does this for us
- Support launching slurm jobs for running all workflows (and all matrix combinations)
  - We need to find workflows, break them down into the smallest jobs (i.e. single matrix comfix)
  - Create and submit slurm jobs that use `nektos/act` to run the jobs
- Monitor and trigger new jobs when a new commit is pushed to the repository
- Create a UI and database for managing the jobs and their results
  - Let's start with just the database and UI for local testing, we'll add the remote monitoring later

