from .git_orchestrator import GitBasedOrchestrator
from .local_orchestrator import LocalOrchestrator


class UnifiedOrchestrator:
    def __init__(self, config) -> None:
        self.git_orchestrator = GitBasedOrchestrator(config)
        self.local_orchestrator = LocalOrchestrator(config)

    def execute(self, mode: str, **kwargs):
        """Unified execution interface"""
        if mode == "git":
            return self.git_orchestrator.handle_webhook(
                event_type=kwargs.get("event_type"), event_data=kwargs.get("event_data")
            )
        elif mode == "local":
            return self.local_orchestrator.execute_local_workflow(**kwargs)
        else:
            raise ValueError(f"Unknown mode: {mode}")
