"""Control Plane domain agent — covers etcd, API server, scheduler, controller manager."""

from src.agents.base_agent import BaseDomainAgent


class ControlPlaneAgent(BaseDomainAgent):
    """Domain agent for Control Plane components (etcd, kube-apiserver, etc.)."""

    def __init__(self, **kwargs):
        super().__init__(agent_name="control_plane", **kwargs)
