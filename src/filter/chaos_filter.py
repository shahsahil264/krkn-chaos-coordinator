"""Chaos relevance filter — determines if a bug needs a chaos test."""

import logging

from src.models import Bug, FilterResult

logger = logging.getLogger(__name__)

# Keywords that indicate a bug is NOT chaos-relevant
NON_CHAOS_KEYWORDS = [
    "CVE-",
    "security tracking",
    "vulnerability",
    "flaky test",
    "test infrastructure",
    "documentation",
    "typo",
    "UI ",
    "console ",
    "button",
    "render",
]

# Keywords that indicate a bug IS chaos-relevant
CHAOS_KEYWORDS = [
    "crash",
    "timeout",
    "unavailable",
    "degraded",
    "unhealthy",
    "quorum",
    "leader election",
    "node drain",
    "node reboot",
    "node delete",
    "node replace",
    "network partition",
    "latency",
    "oom",
    "out of memory",
    "disk full",
    "pod eviction",
    "connection refused",
    "certificate expired",
    "failover",
    "recovery",
    "restart loop",
    "crashloop",
    "not ready",
    "upgrade fail",
    "rollback",
    "stuck",
    "deadlock",
    "resource pressure",
    "throttl",
    "scale",
    "missing",
    "not cleared",
    "stale",
    "static pod",
    "member",
    "outage",
    "disruption",
    "failure",
    "failed",
    "fail",
    "kill",
    "lost",
    "corrupt",
    "split brain",
]

# krkn injection capabilities for Part 2 of the filter
KRKN_CAPABILITIES = [
    "pod failures (kill, restart, CPU/memory hog)",
    "node failures (drain, reboot, shutdown, network isolate)",
    "network chaos (partition, latency via tc netem, packet loss, DNS failure)",
    "resource stress (CPU, memory, disk fill, I/O pressure)",
    "time skew (NTP drift, clock jumps)",
    "container chaos (kill containers, corrupt mounts)",
    "cloud provider (detach volumes, stop VMs, AZ outage)",
    "cluster state (delete CRDs, corrupt configmaps, scale to 0)",
]


def filter_bug(bug: Bug) -> FilterResult:
    """Determine if a bug is chaos-relevant using keyword heuristics.

    Part 1: Is this a failure mode? (vs code bug, CVE, UI issue)
    Part 2: Can krkn inject this? (match against capabilities)
    """
    text = f"{bug.summary} {bug.description}".lower()

    # Part 1: Check for non-chaos indicators
    for keyword in NON_CHAOS_KEYWORDS:
        if keyword.lower() in text:
            return FilterResult(
                bug=bug,
                chaos_relevant=False,
                skip_reason=f"Not chaos-relevant: matches non-chaos keyword '{keyword}'",
            )

    # Part 1: Check for chaos indicators
    matched_keywords = [kw for kw in CHAOS_KEYWORDS if kw.lower() in text]
    if not matched_keywords:
        return FilterResult(
            bug=bug,
            chaos_relevant=False,
            skip_reason="No chaos-relevant failure mode keywords found in bug description",
        )

    # Part 2: Determine injection method
    failure_mode = _extract_failure_mode(text, matched_keywords)
    injection_method = _match_injection_method(text)

    if injection_method is None:
        return FilterResult(
            bug=bug,
            chaos_relevant=False,
            failure_mode=failure_mode,
            skip_reason="Failure mode identified but no matching krkn injection capability",
        )

    return FilterResult(
        bug=bug,
        chaos_relevant=True,
        failure_mode=failure_mode,
        injection_method=injection_method,
    )


def filter_bugs(bugs: list[Bug]) -> tuple[list[FilterResult], list[FilterResult]]:
    """Filter a list of bugs into chaos-relevant and non-relevant.

    Returns (relevant, skipped) tuples.
    """
    relevant = []
    skipped = []

    for bug in bugs:
        result = filter_bug(bug)
        if result.chaos_relevant:
            relevant.append(result)
            logger.info(
                "PASS %s: %s (injection: %s)",
                bug.key, result.failure_mode, result.injection_method,
            )
        else:
            skipped.append(result)
            logger.info("SKIP %s: %s", bug.key, result.skip_reason)

    logger.info(
        "Filter result: %d relevant, %d skipped out of %d total",
        len(relevant), len(skipped), len(bugs),
    )
    return relevant, skipped


def _extract_failure_mode(text: str, matched_keywords: list[str]) -> str:
    """Build a failure mode description from matched keywords."""
    return f"Failure indicators: {', '.join(matched_keywords[:5])}"


def _match_injection_method(text: str) -> str | None:
    """Match bug description against krkn's injection capabilities.

    Priority order matters — more specific matches first to avoid
    'node delete' matching 'pod' because 'delete' isn't in pod keywords.
    """
    # Ordered from most specific to least specific
    injection_rules: list[tuple[str, list[str]]] = [
        ("node", [
            "node delete", "node replace", "node drain", "node reboot",
            "node shutdown", "node fail", "node not ready", "kubelet",
            "machine api", "node outage", "nodestatuses",
        ]),
        ("network", [
            "network partition", "network chaos", "latency", "packet loss",
            "dns fail", "connection refused", "ingress", "ovn",
            "network outage", "network disruption",
        ]),
        ("resource_stress", [
            "cpu", "memory pressure", "disk full", "disk pressure",
            "throttl", "resource pressure", "api server load",
            "resource stress", "hog", "i/o pressure",
        ]),
        ("pod", [
            "pod kill", "pod delete", "pod disruption", "pod eviction",
            "container restart", "crashloop", "oom", "out of memory",
            "static pod", "pod fail", "pod outage",
        ]),
        ("cluster_state", [
            "crd", "configmap", "operator", "upgrade fail", "rollback",
            "scale", "quorum", "leader election", "member", "etcd",
            "split brain", "cluster state", "corrupt",
        ]),
        ("time_skew", [
            "clock", "ntp", "time skew", "certificate expired",
        ]),
        ("cloud_provider", [
            "instance", "volume detach", "stop vm", "az outage",
            "availability zone",
        ]),
    ]

    for capability, keywords in injection_rules:
        for kw in keywords:
            if kw in text:
                return capability

    # Fallback: generic failure keywords
    generic_failure = ["fail", "crash", "unavailable", "degraded", "unhealthy", "disruption", "outage"]
    for kw in generic_failure:
        if kw in text:
            return "cluster_state"

    return None
