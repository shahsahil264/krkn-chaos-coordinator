"""Streamlit web dashboard for krkn-chaos-coordinator."""

import json
import sys
import datetime
from collections import Counter
from pathlib import Path

import streamlit as st
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.filter.chaos_filter import filter_bugs
from src.knowledge.chromadb_store import ChromaStore, DocChunk
from src.knowledge.scenario_index import index_scenarios_from_repo
from src.knowledge.component_map import AGENT_COMPONENTS, get_all_agents
from src.coordinator.orchestrator import deduplicate_gaps
from src.agents.act import build_issue_title, build_issue_body
from src.models import (
    ActionType, Bug, Confidence, FilterResult,
    GapAnalysis, MatchResult, ScenarioMatch,
)

HISTORY_FILE = Path("/tmp/krkn_coordinator_history.json")


def load_bugs_from_json(path: str) -> list[Bug]:
    """Load bugs from saved JIRA JSON."""
    with open(path) as f:
        data = json.load(f)
    bugs = []
    for issue in data.get("issues", {}).get("nodes", []):
        fields = issue["fields"]
        components = fields.get("components", [])
        comp_name = components[0]["name"] if components else "Unknown"
        desc = fields.get("description", "") or ""
        bugs.append(Bug(
            key=issue["key"], summary=fields.get("summary", ""),
            description=desc, component=comp_name,
            priority=fields.get("priority", {}).get("name", "Unknown"),
            status=fields.get("status", {}).get("name", "Unknown"),
            created=fields.get("created", ""),
            url=f"https://redhat.atlassian.net/browse/{issue['key']}",
        ))
    return bugs


def run_pipeline(bugs: list[Bug], krkn_path: str) -> tuple:
    """Run the pipeline and return all results."""
    relevant, skipped = filter_bugs(bugs)
    scenarios = index_scenarios_from_repo(Path(krkn_path))
    chroma = ChromaStore(persist_dir="/tmp/krkn_chroma_streamlit")
    chunks = [
        DocChunk(
            text=f"{s.scenario_type}: {s.file_path} ({s.description})",
            component=s.plugin_name, doc_type="scenario", source="krkn",
        )
        for s in scenarios
    ]
    chroma.add_scenario_docs(chunks)

    matched, unmatched = [], []
    for fr in relevant:
        bug = fr.bug
        query = f"{bug.component} {bug.summary}"
        chroma_results = chroma.search_scenarios(query, n_results=5)
        comp_lower = bug.component.lower()
        matching = [
            s for s in scenarios
            if comp_lower in s.name.lower()
            or comp_lower in s.scenario_type.lower()
            or any(kw in s.file_path.lower() for kw in comp_lower.split())
        ]
        if matching and chroma_results and chroma_results[0]["distance"] < 0.3:
            matched.append(ScenarioMatch(
                bug=bug, match_result=MatchResult.FULL_MATCH,
                matched_scenario=matching[0].file_path, matched_repo="krkn-chaos/krkn",
            ))
        elif matching:
            unmatched.append(ScenarioMatch(
                bug=bug, match_result=MatchResult.PARTIAL_MATCH,
                matched_scenario=matching[0].file_path, matched_repo="krkn-chaos/krkn",
            ))
        else:
            unmatched.append(ScenarioMatch(bug=bug, match_result=MatchResult.NO_MATCH))

    gaps = []
    for match in unmatched:
        bug = match.bug
        score, reasons = 0, []
        if bug.description and len(bug.description) > 200:
            score += 20; reasons.append("Clear repro (+20)")
        if match.match_result == MatchResult.PARTIAL_MATCH:
            score += 25; reasons.append(f"Partial: {match.matched_scenario} (+25)")
        if any(kw in bug.summary.lower() for kw in [
            "timeout", "crash", "unavailable", "degraded", "unhealthy",
            "not cleared", "failure", "failed",
        ]):
            score += 20; reasons.append("Known failure mode (+20)")
        score += 10; reasons.append("Domain match (+10)")
        confidence = Confidence.HIGH if score >= 70 else Confidence.MEDIUM if score >= 40 else Confidence.LOW
        action = ActionType.DRAFT_PR if score >= 70 else ActionType.GITHUB_ISSUE
        modifications = [f"Extend {match.matched_scenario}"] if match.matched_scenario else []
        gaps.append(GapAnalysis(
            bug=bug, confidence_score=score, confidence_level=confidence,
            action_type=action, reasoning="; ".join(reasons),
            base_scenario=match.matched_scenario, modifications=modifications,
        ))

    return relevant, skipped, matched, unmatched, gaps, scenarios


def save_run_history(bugs: list[Bug], relevant: list, skipped: list, gaps: list) -> None:
    """Append current run to history file."""
    history = []
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            history = json.load(f)

    history.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "total_bugs": len(bugs),
        "relevant": len(relevant),
        "skipped": len(skipped),
        "gaps": len(gaps),
        "high": sum(1 for g in gaps if g.confidence_level == Confidence.HIGH),
        "medium": sum(1 for g in gaps if g.confidence_level == Confidence.MEDIUM),
        "low": sum(1 for g in gaps if g.confidence_level == Confidence.LOW),
    })

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_run_history() -> list[dict]:
    """Load run history."""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


# === STREAMLIT APP ===

st.set_page_config(page_title="krkn-chaos-coordinator", page_icon="🔥", layout="wide")

st.title("krkn-chaos-coordinator")
st.caption("AI-driven chaos test coverage expansion for OpenShift")

# Sidebar
with st.sidebar:
    st.header("Configuration")
    release = st.text_input("OCP Release", value="4.21")
    krkn_path = st.text_input("krkn Repo Path", value="/Users/sahil/krkn")
    jira_path = st.text_input("JIRA Data (JSON)", value="tests/fixtures/jira_etcd_bugs.json")

    st.divider()
    st.header("Agents")
    for agent in get_all_agents():
        display = agent.replace("_", " ").title()
        components = AGENT_COMPONENTS.get(agent, [])
        with st.expander(display):
            for c in components:
                st.text(f"  {c}")

    st.divider()
    run_button = st.button("Run Pipeline", type="primary", use_container_width=True)

# Main content
if run_button or st.session_state.get("has_run"):
    st.session_state["has_run"] = True

    if not Path(jira_path).exists():
        st.error(f"JIRA data file not found: {jira_path}")
        st.stop()

    bugs = load_bugs_from_json(jira_path)

    with st.status("Running pipeline...", expanded=True) as status:
        st.write(f"**DISCOVER:** Loading {len(bugs)} bugs from JIRA...")
        relevant, skipped, matched, unmatched, gaps, scenarios = run_pipeline(bugs, krkn_path)
        st.write(f"**FILTER:** {len(relevant)} relevant, {len(skipped)} skipped")
        st.write(f"**MAP:** {len(scenarios)} scenarios indexed, {len(matched)} matched, {len(unmatched)} unmatched")
        st.write(f"**ANALYZE:** {len(gaps)} gaps identified")
        status.update(label="Pipeline complete!", state="complete")

    # Save to history
    save_run_history(bugs, relevant, skipped, gaps)

    # Metrics row
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Bugs Scanned", len(bugs))
    col2.metric("Chaos Relevant", len(relevant))
    col3.metric("Skipped", len(skipped))
    col4.metric("Gaps Found", len(gaps))
    prs = sum(1 for g in gaps if g.action_type == ActionType.DRAFT_PR)
    issues = sum(1 for g in gaps if g.action_type == ActionType.GITHUB_ISSUE)
    col5.metric("Draft PRs", prs)
    col6.metric("Issues", issues)

    st.divider()

    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Approval Queue", "Bug Details", "Filter Breakdown",
        "Coverage Heatmap", "Injection Methods",
        "Scenario Coverage", "Run History",
    ])

    # === TAB 1: APPROVAL QUEUE ===
    with tab1:
        st.subheader("Approval Queue")
        if not gaps:
            st.success("No chaos test coverage gaps identified!")
        else:
            for i, gap in enumerate(gaps):
                level = gap.confidence_level.value.upper()
                color = "green" if gap.confidence_score >= 70 else "orange" if gap.confidence_score >= 40 else "red"
                action = "DRAFT PR" if gap.action_type == ActionType.DRAFT_PR else "ISSUE"

                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 6, 2])
                    with c1:
                        st.markdown(f"### #{i+1}")
                    with c2:
                        st.markdown(f"**[{gap.bug.key}]({gap.bug.url})**: {gap.bug.summary[:80]}")
                        st.caption(f"Component: {gap.bug.component} | Priority: {gap.bug.priority}")
                        st.caption(f"Reasoning: {gap.reasoning}")
                        if gap.base_scenario:
                            st.caption(f"Base: `{gap.base_scenario}`")
                    with c3:
                        st.markdown(f":{color}[**{level}** {gap.confidence_score}/100]")
                        st.markdown(f"**{action}**")
                        col_a, col_b = st.columns(2)
                        col_a.button("Approve", key=f"approve_{i}", type="primary")
                        col_b.button("Reject", key=f"reject_{i}")

    # === TAB 2: BUG DETAILS ===
    with tab2:
        st.subheader("Bug Details")
        st.caption("Click a bug to see the full JIRA description")

        all_filter_results = list(relevant) + list(skipped)
        for fr in all_filter_results:
            bug = fr.bug
            chaos_badge = "🟢 Chaos Relevant" if fr.chaos_relevant else "🔴 Skipped"
            with st.expander(f"{chaos_badge} | {bug.key}: {bug.summary[:70]}"):
                col_a, col_b, col_c = st.columns(3)
                col_a.markdown(f"**Component:** {bug.component}")
                col_b.markdown(f"**Priority:** {bug.priority}")
                col_c.markdown(f"**Status:** {bug.status}")

                if fr.chaos_relevant:
                    st.info(f"**Failure Mode:** {fr.failure_mode}  \n**Injection:** {fr.injection_method}")
                else:
                    st.warning(f"**Skip Reason:** {fr.skip_reason}")

                st.markdown("---")
                st.markdown("**Full Description:**")
                desc = bug.description or "*No description*"
                if len(desc) > 2000:
                    st.markdown(desc[:2000] + "...")
                else:
                    st.markdown(desc)

                st.markdown(f"[Open in JIRA]({bug.url})")

    # === TAB 3: FILTER BREAKDOWN ===
    with tab3:
        st.subheader("Filter Breakdown")

        col_chart, col_detail = st.columns([1, 1])

        with col_chart:
            # Skip reason breakdown
            skip_reasons = []
            for s in skipped:
                reason = s.skip_reason or "Unknown"
                if "CVE" in reason:
                    skip_reasons.append("CVE / Security")
                elif "No chaos-relevant" in reason:
                    skip_reasons.append("No failure keywords")
                elif "injection" in reason.lower():
                    skip_reasons.append("No krkn injection")
                else:
                    skip_reasons.append("Other")

            if skip_reasons:
                reason_counts = Counter(skip_reasons)
                df_reasons = pd.DataFrame(
                    {"Reason": list(reason_counts.keys()), "Count": list(reason_counts.values())}
                )
                st.markdown("#### Why Bugs Were Skipped")
                st.bar_chart(df_reasons.set_index("Reason"))

            # Relevant vs skipped pie
            st.markdown("#### Chaos Relevance")
            filter_df = pd.DataFrame({
                "Category": ["Chaos Relevant", "Skipped"],
                "Count": [len(relevant), len(skipped)],
            })
            st.bar_chart(filter_df.set_index("Category"))

        with col_detail:
            # Injection method breakdown for relevant bugs
            if relevant:
                st.markdown("#### Injection Methods Needed")
                methods = [r.injection_method or "unknown" for r in relevant]
                method_counts = Counter(methods)
                df_methods = pd.DataFrame(
                    {"Method": list(method_counts.keys()), "Count": list(method_counts.values())}
                )
                st.bar_chart(df_methods.set_index("Method"))

            # Priority distribution
            st.markdown("#### Bug Priority Distribution")
            priorities = [b.priority for b in bugs]
            prio_counts = Counter(priorities)
            df_prio = pd.DataFrame(
                {"Priority": list(prio_counts.keys()), "Count": list(prio_counts.values())}
            )
            st.bar_chart(df_prio.set_index("Priority"))

    # === TAB 4: COVERAGE HEATMAP ===
    with tab4:
        st.subheader("Component Coverage Heatmap")
        st.caption("Which OCP components have chaos test coverage vs gaps")

        # Build coverage data per agent
        all_agents = get_all_agents()
        heatmap_data = []

        # Count scenarios per component keyword
        scenario_components = Counter()
        for s in scenarios:
            scenario_components[s.plugin_name] += 1
            # Also count by file path keywords
            for part in s.file_path.lower().split("/"):
                if part not in ("scenarios", "openshift", "kube", "kind", "kubevirt"):
                    scenario_components[part] += 1

        for agent_name in all_agents:
            components = AGENT_COMPONENTS.get(agent_name, [])
            display_name = agent_name.replace("_", " ").title()

            # Count bugs for this agent
            agent_bugs = [b for b in bugs if b.component in components]
            agent_relevant = [r for r in relevant if r.bug.component in components]
            agent_gaps = [g for g in gaps if g.bug.component in components]

            # Count scenarios matching this agent
            agent_scenarios = 0
            for comp in components:
                comp_lower = comp.lower()
                for key, count in scenario_components.items():
                    if key in comp_lower or comp_lower in key:
                        agent_scenarios += count

            has_coverage = agent_scenarios > 0
            has_gaps = len(agent_gaps) > 0
            has_bugs = len(agent_bugs) > 0

            if has_gaps:
                coverage_status = "GAP"
            elif has_coverage:
                coverage_status = "COVERED"
            elif has_bugs:
                coverage_status = "NO COVERAGE"
            else:
                coverage_status = "NO BUGS"

            heatmap_data.append({
                "Agent": display_name,
                "Components": len(components),
                "Bugs (14d)": len(agent_bugs),
                "Chaos Relevant": len(agent_relevant),
                "Scenarios": agent_scenarios,
                "Gaps": len(agent_gaps),
                "Status": coverage_status,
            })

        df_heat = pd.DataFrame(heatmap_data)
        st.dataframe(
            df_heat.style.apply(
                lambda row: [
                    "background-color: #ff4444" if row["Status"] == "GAP"
                    else "background-color: #44aa44" if row["Status"] == "COVERED"
                    else "background-color: #ffaa00" if row["Status"] == "NO COVERAGE"
                    else "background-color: #666666"
                ] * len(row),
                axis=1,
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("""
        **Legend:**
        - 🟢 **COVERED** — has chaos scenarios, no new gaps
        - 🔴 **GAP** — has bugs that need new chaos tests
        - 🟡 **NO COVERAGE** — has bugs but no matching scenarios
        - ⚫ **NO BUGS** — no recent bugs in this area
        """)

    # === TAB 5: INJECTION METHODS ===
    with tab5:
        st.subheader("Injection Method Analysis")

        if relevant:
            col_a, col_b = st.columns([1, 1])

            with col_a:
                st.markdown("#### Required Injection Types")
                methods = [r.injection_method or "unknown" for r in relevant]
                method_counts = Counter(methods)

                for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
                    capability_desc = {
                        "node": "Node failures (drain, reboot, shutdown, delete)",
                        "pod": "Pod failures (kill, restart, eviction)",
                        "network": "Network chaos (partition, latency, DNS)",
                        "resource_stress": "Resource stress (CPU, memory, disk, I/O)",
                        "cluster_state": "Cluster state (CRDs, operators, upgrades)",
                        "time_skew": "Time skew (NTP, clock jumps)",
                        "cloud_provider": "Cloud provider (VMs, volumes, AZ outage)",
                    }.get(method, method)

                    st.markdown(f"**{method}** ({count} bugs)")
                    st.caption(capability_desc)
                    st.progress(count / len(relevant))

            with col_b:
                st.markdown("#### krkn Plugin Mapping")
                plugin_map = {
                    "node": ["node_actions", "shut_down"],
                    "pod": ["pod_disruption", "application_outage", "container"],
                    "network": ["network_chaos", "network_chaos_ng", "native"],
                    "resource_stress": ["hogs"],
                    "cluster_state": ["pod_disruption", "pvc", "service_disruption"],
                    "time_skew": ["time_actions"],
                    "cloud_provider": ["node_actions", "zone_outage"],
                }
                for method in method_counts:
                    plugins = plugin_map.get(method, ["unknown"])
                    st.markdown(f"**{method}** → `{', '.join(plugins)}`")

        else:
            st.info("No chaos-relevant bugs found — no injection methods needed.")

    # === TAB 6: SCENARIO COVERAGE ===
    with tab6:
        st.subheader(f"krkn Scenario Coverage ({len(scenarios)} scenarios)")

        # Group by type
        type_counts = Counter(s.scenario_type for s in scenarios)
        st.markdown("#### Scenarios by Type")
        df_types = pd.DataFrame(
            {"Type": list(type_counts.keys()), "Count": list(type_counts.values())}
        ).sort_values("Count", ascending=False)
        st.bar_chart(df_types.set_index("Type"))

        # Full table
        st.markdown("#### All Scenarios")
        scenario_data = [
            {
                "File": s.file_path,
                "Type": s.scenario_type,
                "Plugin": s.plugin_name,
                "Description": s.description or "—",
            }
            for s in scenarios
        ]
        st.dataframe(scenario_data, use_container_width=True)

        # Issue previews
        st.markdown("#### Generated Issue Previews")
        for gap in gaps:
            title = build_issue_title(gap)
            body = build_issue_body(gap, "control_plane")
            with st.expander(f"{gap.bug.key}: {gap.bug.summary[:60]}"):
                st.markdown(f"**Title:** {title}")
                st.divider()
                st.markdown(body)

    # === TAB 7: RUN HISTORY ===
    with tab7:
        st.subheader("Run History")
        history = load_run_history()

        if not history:
            st.info("No previous runs recorded yet.")
        else:
            df_hist = pd.DataFrame(history)
            df_hist["timestamp"] = pd.to_datetime(df_hist["timestamp"])
            df_hist = df_hist.sort_values("timestamp", ascending=False)

            # Summary table
            st.dataframe(
                df_hist[["timestamp", "total_bugs", "relevant", "skipped", "gaps", "high", "medium", "low"]],
                use_container_width=True,
                hide_index=True,
            )

            # Gaps over time chart
            if len(df_hist) > 1:
                st.markdown("#### Gaps Over Time")
                chart_df = df_hist.set_index("timestamp")[["gaps", "relevant", "skipped"]]
                st.line_chart(chart_df)

                st.markdown("#### Confidence Distribution Over Time")
                conf_df = df_hist.set_index("timestamp")[["high", "medium", "low"]]
                st.area_chart(conf_df)

else:
    st.info("Click **Run Pipeline** in the sidebar to start analyzing bugs.")

    # Show agent architecture
    st.subheader("Architecture")
    st.code("""
    Orchestrator
    ├── Upgrade & Lifecycle    (CVO, MCO, Installer)
    ├── Control Plane          (etcd, kube-apiserver, scheduler)
    ├── Node & Machine         (kubelet, Machine API, Cloud Compute)
    ├── Networking             (OVN-K, DNS, router, ingress)
    ├── Storage                (CSI, Image Registry)
    └── Operators & Platform   (OLM, Console, Auth, Monitoring)

    Pipeline: DISCOVER → FILTER → MAP → ANALYZE → ACT → REMEMBER
    """)

    # Agent comparison placeholder
    st.subheader("Agent Coverage Summary")
    agent_data = []
    for agent in get_all_agents():
        display = agent.replace("_", " ").title()
        components = AGENT_COMPONENTS.get(agent, [])
        agent_data.append({
            "Agent": display,
            "Components": len(components),
            "Component List": ", ".join(components),
        })
    st.dataframe(agent_data, use_container_width=True, hide_index=True)
