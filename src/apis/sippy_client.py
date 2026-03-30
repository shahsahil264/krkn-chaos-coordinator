"""Sippy API client for querying regressions and health data."""

import json
import logging
import urllib.request
import urllib.error

from src.models import Regression

logger = logging.getLogger(__name__)

SIPPY_BASE_URL = "https://sippy.dptools.openshift.org/api"


class SippyClient:
    """Query Sippy public APIs for regression and health data."""

    def get_regressions(
        self, release: str, components: list[str] | None = None
    ) -> list[Regression]:
        """Fetch regressions for a release, optionally filtered by components."""
        url = f"{SIPPY_BASE_URL}/component_readiness/regressions?release={release}"
        logger.info("Fetching regressions from: %s", url)

        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.error("Sippy regressions query failed: %s", e)
            return []

        if not isinstance(data, list):
            logger.warning("Unexpected response format from Sippy")
            return []

        regressions = []
        for item in data:
            component = item.get("component", "")
            if not component:
                continue

            if components:
                components_lower = [c.lower() for c in components]
                if component.lower() not in components_lower:
                    continue

            closed = item.get("closed")
            if isinstance(closed, dict):
                closed = closed.get("Time") if closed.get("Valid") else None

            regressions.append(
                Regression(
                    regression_id=item.get("id", 0),
                    test_name=item.get("test_name", ""),
                    component=component,
                    opened=item.get("opened", ""),
                    closed=closed,
                    triaged=bool(item.get("triages")),
                )
            )

        logger.info("Found %d regressions for %s", len(regressions), release)
        return regressions

    def get_health(self, release: str) -> dict:
        """Fetch health indicators for a release."""
        url = f"{SIPPY_BASE_URL}/health?release={release}"
        logger.info("Fetching health from: %s", url)

        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.error("Sippy health query failed: %s", e)
            return {}
