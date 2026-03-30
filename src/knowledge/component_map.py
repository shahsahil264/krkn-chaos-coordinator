"""Component-to-agent mapping using team_component_map.json from openshift-eng/ai-helpers."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Agent name → list of OCPBUGS component names
AGENT_COMPONENTS: dict[str, list[str]] = {
    "upgrade_lifecycle": [
        "Cluster Version Operator",
        "Machine Config Operator",
        "Installer / openshift-installer",
    ],
    "control_plane": [
        "kube-apiserver",
        "Etcd",
        "kube-controller-manager",
        "kube-scheduler",
        "openshift-apiserver",
    ],
    "node_machine": [
        "Node / Kubelet",
        "Cloud Compute",
        "Machine API",
    ],
    "networking": [
        "Networking / ovn-kubernetes",
        "Networking / cluster-network-operator",
        "Networking / DNS",
        "Networking / router",
    ],
    "storage": [
        "Storage / kubernetes-csi-driver-manila",
        "Image Registry",
    ],
    "operators_platform": [
        "OLM",
        "Console",
        "Authentication",
        "Monitoring",
    ],
}


def get_components_for_agent(agent_name: str) -> list[str]:
    """Get the OCPBUGS component names for a given agent."""
    components = AGENT_COMPONENTS.get(agent_name)
    if components is None:
        raise ValueError(f"Unknown agent: {agent_name}. Valid: {list(AGENT_COMPONENTS.keys())}")
    return list(components)


def get_all_agents() -> list[str]:
    """Get all agent names."""
    return list(AGENT_COMPONENTS.keys())


def load_team_component_map(path: Path) -> dict:
    """Load the full team component map from JSON file."""
    with open(path) as f:
        return json.load(f)


def update_agent_components_from_map(map_path: Path) -> None:
    """Update AGENT_COMPONENTS using the authoritative team_component_map.json.

    This reads the team mapping and updates the module-level AGENT_COMPONENTS
    dict with the actual component names from the JSON.
    """
    data = load_team_component_map(map_path)
    teams = data.get("teams", {})

    # Map our agent names to source teams
    agent_to_teams = {
        "upgrade_lifecycle": ["Installer"],
        "control_plane": ["API Server", "etcd"],
        "node_machine": ["Node"],
        "networking": ["Networking"],
        "storage": ["Storage"],
        "operators_platform": ["OLM", "Monitoring", "Console", "Authentication"],
    }

    for agent_name, team_names in agent_to_teams.items():
        components = []
        for team_name in team_names:
            team_data = teams.get(team_name, {})
            if isinstance(team_data, dict):
                components.extend(team_data.get("components", []))
            elif isinstance(team_data, list):
                components.extend(team_data)
        if components:
            AGENT_COMPONENTS[agent_name] = components
            logger.info("Updated %s with %d components from map", agent_name, len(components))
