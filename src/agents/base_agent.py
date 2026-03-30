"""Base domain agent with the DISCOVER → FILTER → MAP → ANALYZE → ACT → REMEMBER pipeline."""

import logging
from abc import ABC

from src.apis.jira_client import JiraClient
from src.apis.sippy_client import SippyClient
from src.apis.github_client import GitHubClient
from src.filter.chaos_filter import filter_bugs
from src.knowledge.chromadb_store import ChromaStore
from src.knowledge.component_map import get_components_for_agent
from src.knowledge.scenario_index import ScenarioInfo
from src.models import (
    ActionType,
    AgentResult,
    Bug,
    Confidence,
    FilterResult,
    GapAnalysis,
    MatchResult,
    ScenarioMatch,
)

logger = logging.getLogger(__name__)


class BaseDomainAgent(ABC):
    """Base class for domain-specific chaos coverage agents."""

    def __init__(
        self,
        agent_name: str,
        jira: JiraClient,
        sippy: SippyClient,
        github: GitHubClient,
        chroma: ChromaStore,
        scenarios: list[ScenarioInfo],
        release: str,
    ):
        self.agent_name = agent_name
        self.jira = jira
        self.sippy = sippy
        self.github = github
        self.chroma = chroma
        self.scenarios = scenarios
        self.release = release
        self.components = get_components_for_agent(agent_name)

    def run(self) -> AgentResult:
        """Execute the full pipeline: DISCOVER → FILTER → MAP → ANALYZE → ACT → REMEMBER."""
        logger.info("=== %s agent starting ===", self.agent_name)

        # DISCOVER
        bugs = self._discover()
        logger.info("DISCOVER: found %d bugs", len(bugs))

        # FILTER
        relevant, skipped = self._filter(bugs)
        logger.info("FILTER: %d relevant, %d skipped", len(relevant), len(skipped))

        # MAP
        matched, unmatched = self._map(relevant)
        logger.info("MAP: %d matched, %d unmatched", len(matched), len(unmatched))

        # ANALYZE
        gaps = self._analyze(unmatched)
        logger.info("ANALYZE: %d gaps identified", len(gaps))

        result = AgentResult(
            agent_name=self.agent_name,
            bugs_discovered=bugs,
            bugs_filtered_out=skipped,
            bugs_matched=matched,
            gaps=gaps,
        )

        logger.info("=== %s agent complete ===", self.agent_name)
        return result

    def _discover(self) -> list[Bug]:
        """DISCOVER: Query JIRA and Sippy for bugs and regressions."""
        bugs = self.jira.get_bugs_by_components(self.components)
        return bugs

    def _filter(self, bugs: list[Bug]) -> tuple[list[FilterResult], list[FilterResult]]:
        """FILTER: Determine chaos relevance of each bug."""
        return filter_bugs(bugs)

    def _map(self, relevant: list[FilterResult]) -> tuple[list[ScenarioMatch], list[ScenarioMatch]]:
        """MAP: Match bugs against existing krkn scenarios."""
        matched = []
        unmatched = []

        for filter_result in relevant:
            bug = filter_result.bug
            match = self._find_scenario_match(bug)
            if match.match_result == MatchResult.FULL_MATCH:
                matched.append(match)
            else:
                unmatched.append(match)

        return matched, unmatched

    def _find_scenario_match(self, bug: Bug) -> ScenarioMatch:
        """Search for existing krkn scenarios that match a bug."""
        # Search ChromaDB for related scenarios
        query = f"{bug.component} {bug.summary}"
        chroma_results = self.chroma.search_scenarios(query, n_results=5)

        # Search local scenario index
        component_lower = bug.component.lower()
        matching_scenarios = [
            s for s in self.scenarios
            if component_lower in s.name.lower()
            or component_lower in s.scenario_type.lower()
            or component_lower in s.description.lower()
        ]

        if matching_scenarios and chroma_results:
            best = matching_scenarios[0]
            distance = chroma_results[0].get("distance", 1.0) if chroma_results else 1.0
            if distance < 0.3:
                return ScenarioMatch(
                    bug=bug,
                    match_result=MatchResult.FULL_MATCH,
                    matched_scenario=best.file_path,
                    matched_repo="krkn-chaos/krkn",
                    similarity_score=1.0 - distance,
                )
            return ScenarioMatch(
                bug=bug,
                match_result=MatchResult.PARTIAL_MATCH,
                matched_scenario=best.file_path,
                matched_repo="krkn-chaos/krkn",
                similarity_score=1.0 - distance,
            )

        if matching_scenarios:
            return ScenarioMatch(
                bug=bug,
                match_result=MatchResult.PARTIAL_MATCH,
                matched_scenario=matching_scenarios[0].file_path,
                matched_repo="krkn-chaos/krkn",
            )

        return ScenarioMatch(bug=bug, match_result=MatchResult.NO_MATCH)

    def _analyze(self, unmatched: list[ScenarioMatch]) -> list[GapAnalysis]:
        """ANALYZE: Score confidence and determine action for each gap."""
        gaps = []

        for match in unmatched:
            bug = match.bug
            score = 0
            reasoning_parts = []

            # Clear repro steps? (+20)
            if bug.description and len(bug.description) > 200:
                score += 20
                reasoning_parts.append("Clear repro steps (+20)")

            # Existing scenario to extend? (+25)
            if match.match_result == MatchResult.PARTIAL_MATCH:
                score += 25
                reasoning_parts.append(f"Partial match: {match.matched_scenario} (+25)")

            # Known failure mode? (+20)
            if any(kw in bug.summary.lower() for kw in ["timeout", "crash", "unavailable", "degraded"]):
                score += 20
                reasoning_parts.append("Known failure mode (+20)")

            # Agent domain match? (+10)
            if bug.component.lower() in " ".join(self.components).lower():
                score += 10
                reasoning_parts.append("Domain match (+10)")

            # Determine confidence level and action
            if score >= 70:
                confidence = Confidence.HIGH
                action = ActionType.DRAFT_PR
            elif score >= 40:
                confidence = Confidence.MEDIUM
                action = ActionType.GITHUB_ISSUE
            else:
                confidence = Confidence.LOW
                action = ActionType.GITHUB_ISSUE

            modifications = []
            if match.match_result == MatchResult.PARTIAL_MATCH and match.matched_scenario:
                modifications.append(f"Extend {match.matched_scenario}")

            gaps.append(
                GapAnalysis(
                    bug=bug,
                    confidence_score=score,
                    confidence_level=confidence,
                    action_type=action,
                    reasoning="; ".join(reasoning_parts),
                    base_scenario=match.matched_scenario,
                    modifications=modifications,
                )
            )

        return gaps
