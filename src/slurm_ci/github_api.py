import requests


class GithubAPI:
    def __init__(self, token) -> None:
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )

    def get_repo_contents(self, repo_full_name, path, ref):
        """Get contents of a file or directory in a repo."""
        url = f"https://api.github.com/repos/{repo_full_name}/contents/{path}"
        params = {"ref": ref}
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
