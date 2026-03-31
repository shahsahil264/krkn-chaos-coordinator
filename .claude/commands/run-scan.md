---
description: Run krkn-chaos-coordinator scan against JIRA bugs
allowed-tools: Bash, Read, Write, mcp__jira__searchJiraIssuesUsingJql, mcp__github__create_issue
---

# Run krkn-chaos-coordinator

You are the chaos relevance filter for krkn-chaos-coordinator. Run the full pipeline: DISCOVER → FILTER → MAP → ANALYZE → ACT.

## Step 1: DISCOVER

Query JIRA for recent bugs using the MCP tool:

```
mcp__jira__searchJiraIssuesUsingJql with:
  cloudId: https://redhat.atlassian.net
  jql: project = OCPBUGS AND component IN (Etcd, "kube-apiserver", "kube-controller-manager", "kube-scheduler", "openshift-apiserver", "Cluster Version Operator", "Machine Config Operator", "Installer / openshift-installer", "Node / Kubelet", "Cloud Compute", "Machine API", "Networking / ovn-kubernetes", "Networking / cluster-network-operator", "Networking / DNS", "Networking / router", "OLM", "Console", "Authentication", "Monitoring", "Image Registry") AND created >= -14d ORDER BY created DESC
  maxResults: 30
  fields: ["summary", "description", "status", "priority", "components", "created"]
  responseContentFormat: markdown
```

Save the results to `tests/fixtures/latest_scan.json`.

## Step 2: FILTER (You are the filter)

For each bug, determine chaos relevance by asking:

**Part 1: Is this a failure mode?**
- Component fails under stress/load → YES
- Component fails when another component dies → YES
- Recovery doesn't work after disruption → YES
- Race condition during upgrade/rollout → YES
- Code bug / logic error → NO
- CVE / security vulnerability → NO
- UI/console bug → NO
- Flaky test → NO
- Version-specific migration issue → NO

**Part 2: Can krkn inject this?**
- Pod failures, node failures, network chaos, resource stress, time skew, cloud provider chaos, cluster state chaos

Output your filter decisions clearly:
```
PASS: OCPBUGS-XXXXX — [failure mode] (injection: [method])
SKIP: OCPBUGS-XXXXX — [reason]
```

## Step 3: MAP + ANALYZE

Run the Python pipeline on the filtered bugs:
```bash
cd /Users/sahil/krkn-chaos-coordinator
PYTHONPATH=. ./venv/bin/python3 -m src.run_pipeline tests/fixtures/latest_scan.json
```

## Step 4: Review and Present

Present the approval queue to the user. For each gap:
- Show the bug key, summary, confidence score
- Explain why it's a gap (what existing scenarios DON'T cover)
- Recommend specific krkn injection method
- Ask: Approve (create issue) or Reject?

When the user approves, create the GitHub issue using the MCP tool on `shahsahil264/krkn`.
