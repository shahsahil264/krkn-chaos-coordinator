"""Tests for component mapping."""

import pytest

from src.knowledge.component_map import get_components_for_agent, get_all_agents


class TestComponentMap:
    def test_control_plane_components(self):
        components = get_components_for_agent("control_plane")
        assert "Etcd" in components
        assert "kube-apiserver" in components

    def test_networking_components(self):
        components = get_components_for_agent("networking")
        assert any("ovn" in c.lower() for c in components)

    def test_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            get_components_for_agent("nonexistent")

    def test_get_all_agents(self):
        agents = get_all_agents()
        assert "control_plane" in agents
        assert "networking" in agents
        assert "upgrade_lifecycle" in agents
        assert len(agents) == 6

    def test_components_are_copies(self):
        c1 = get_components_for_agent("control_plane")
        c2 = get_components_for_agent("control_plane")
        assert c1 == c2
        assert c1 is not c2  # should be a copy
