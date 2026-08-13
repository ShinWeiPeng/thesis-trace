---
spec_version: "1"
spec_id: SPEC-0003
revision: 8
status: confirmed
change_set: netdata-proxmox-monitoring
---

# Netdata monitoring UI for Proxmox

## Problem

The Proxmox host exposes CPU, NVMe, memory, and other temperatures through Linux hwmon, but the built-in Proxmox UI does not present these readings or temperature history.

## Solution

Install a bounded, local-only Netdata monitoring service directly on the Proxmox host, with three 768 MiB retention tiers and dashboard-only health alerts.

## User Stories

- As the host owner, I want a browser UI for current and historical temperature, load, frequency, memory, disk, and network data.
- As the administrator, I want monitoring to avoid exposing Proxmox or sensor data to untrusted networks.

## Requirements

| ID | Requirement |
| --- | --- |
| REQ-001 | The monitoring UI must display the Proxmox host's available CPU and NVMe temperature sensors together with CPU load and frequency. |
| REQ-002 | Monitoring access must be restricted to the verified home LAN, and Netdata Cloud connectivity must remain disabled. |
| REQ-003 | The monitoring service must not disrupt running VMs or replace the Proxmox management UI. |
| REQ-004 | Netdata must be installed directly on the Proxmox host from the official Netdata package source, and its service health, host overhead, package source, and rollback path must be validated. |
| REQ-005 | Netdata dbengine must use three storage tiers with a 768 MiB retention-size target for each tier; the time limits must remain 14 days for per-second data, 3 months for per-minute data, and 2 years for per-hour data, with rotation occurring when either the size or time limit is reached first. |
| REQ-006 | Health alarms must be visible in the local Netdata UI only; this change set must not configure Email, SMTP, cloud, webhook, or messaging notifications. |

## Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| DEC-001 | Permit direct Netdata UI access only from the verified home LAN; do not permit public-Internet or VPN sources. | This matches the existing Development VM access boundary and minimizes exposure while keeping browser access convenient at home. |
| DEC-002 | Install Netdata directly on the Proxmox host rather than in an LXC or separate UI guest. | Direct installation provides complete access to the host's Linux hwmon sensors with the least operational complexity for a single Proxmox node. |
| DEC-003 | Operate Netdata as a local-only deployment without claiming or connecting the node to Netdata Cloud. | This preserves the selected LAN-only boundary, keeps monitoring data local, and avoids requiring a Netdata account. |
| DEC-004 | Allocate 768 MiB to each of the three Netdata storage tiers, for an approximately 2.25 GiB total target, while retaining the official default time limits. | The user selected an equal per-tier custom size below the approximately 3 GiB official default. |
| DEC-005 | Display health alarms only in the local Netdata UI without configuring active external notifications. | This avoids adding accounts, SMTP credentials, or external notification dependencies to the initial installation. |

## Acceptance Criteria

| ID | Requirements | Scenario | Validation Method | Evidence |
| --- | --- | --- | --- | --- |
| AC-001 | REQ-001 REQ-003 REQ-004 | The owner opens the monitoring UI while Server and Development VMs remain running. | Verify bounded LAN access, temperature charts, CPU/load/frequency charts, Netdata service health, VM status, package source, rollback path, and host CPU/memory overhead. | PARTIAL (2026-08-13): LAN dashboard opened successfully; Netdata 2.11.0 is active from the official repository; CPU Tctl/Tccd1 and NVMe temperature metrics are collected; memory usage was approximately 167 MiB; `home-service` remained running and responsive. Final simultaneous validation remains pending because `home-service-dev` was stopped, and the submitted screenshot showed the Database rather than System temperature view. |
| AC-002 | REQ-002 | An unauthorized source attempts to reach the monitoring UI or the service attempts cloud connectivity. | Verify LAN-only network boundary, listening sockets, firewall behavior, unclaimed local-only cloud state, and absence of configured Netdata Cloud credentials. | PARTIAL (2026-08-13): Netdata listens only on loopback and `[REDACTED: personal data]:19999`; dashboard ACL permits localhost and `192.168.2.*`; management/config endpoints are localhost-only; node is unclaimed and ACLK is offline with no reconnect attempts. A connection attempt from a routed non-LAN source remains pending. |
| AC-003 | REQ-005 | Netdata records local metrics over time. | Verify dbengine mode, three tiers, 768 MiB configured per tier, official time limits, dashboard retention charts, and adequate free space on the Proxmox root filesystem. | PASS (2026-08-13): Submitted Database UI screenshot shows three dbengine tiers at 1 s, 1 min, and 1 h resolution; every tier is configured for 768 MiB, with 14 d, 3 mo, and 2 y limits. The host had approximately 74 GiB free. Early current/effective retention values are expected to grow as the new database accumulates samples. |
| AC-004 | REQ-006 | Netdata evaluates local health alarms. | Verify the UI health/alarm view is available and confirm that no Email, SMTP, cloud, webhook, or messaging notification integration is configured. | PARTIAL (2026-08-13): Health API reported 182 normal, 0 warning, and 0 critical alarms; all external notification senders are explicitly disabled. Final visual confirmation of the local Health/Alerts UI remains pending. |

## Relationships

| Source | Relation | Target |
| --- | --- | --- |
| REQ-001 | depends_on | REQ-002 |
| REQ-001 | depends_on | REQ-004 |
| REQ-005 | depends_on | REQ-004 |
| REQ-006 | depends_on | REQ-001 |

## Out of Scope

- Replacing the Proxmox management interface.
- Publishing Proxmox or Netdata directly to the public Internet.
- Connecting the node to Netdata Cloud.
- Configuring active external alerts or notification credentials.
- Changing CPU power mode as part of the monitoring installation.

## Discussion Context

### DISC-001: Monitoring UI access boundary

- **Situation:** Netdata adds a browser-accessible service on the Proxmox host, which contains infrastructure and hardware telemetry.
- **Question:** Which sources may access the Netdata UI?
- **Options and tradeoffs:** LAN-only minimizes exposure; LAN plus VPN supports off-site administration; localhost-only requires an SSH tunnel for every use.
- **User answer:** Option 1, home-LAN-only access.
- **Explicit rationale:** The user selected the recommended option; no additional rationale was provided.
- **Resulting impact:** REQ-002, DEC-001, and AC-002 require LAN-only access and exclude public and VPN sources.

### DISC-002: Netdata installation boundary

- **Situation:** Complete CPU and NVMe temperature monitoring requires access to the Proxmox host's hwmon sensors.
- **Question:** Should Netdata run directly on Proxmox, in an isolated LXC, or as a host collector with a separate UI guest?
- **Options and tradeoffs:** Direct-host installation has complete sensor access and minimal complexity but adds software to the hypervisor; LXC improves isolation but complicates and may limit sensor access; split collector/UI adds the most components and maintenance.
- **User answer:** Option 1, install Netdata directly on the Proxmox host.
- **Explicit rationale:** The user selected the recommended option; no additional rationale was provided.
- **Resulting impact:** REQ-004, DEC-002, AC-001, and the installation gate require an official direct-host installation with measured overhead and a rollback path.

### DISC-003: Netdata Cloud connectivity

- **Situation:** Netdata can operate locally or connect the node to Netdata Cloud for remote dashboards and cloud-mediated features.
- **Question:** Should this Proxmox node connect to Netdata Cloud?
- **Options and tradeoffs:** Local-only operation keeps data and access within the LAN without an account; Cloud connectivity adds remote access and cloud features but changes the network and privacy boundary.
- **User answer:** Option 1, operate completely locally without Netdata Cloud.
- **Explicit rationale:** The user selected the recommended option; no additional rationale was provided.
- **Resulting impact:** REQ-002, DEC-003, AC-002, and Out of Scope prohibit claiming or connecting this node to Netdata Cloud.

### DISC-004: Metrics retention storage budget

- **Situation:** Netdata stores metrics in three resolution tiers, each with an independent retention-size setting; the Proxmox root filesystem currently has approximately 75 GiB available.
- **Question:** What disk budget should be allocated to Netdata retention?
- **Options and tradeoffs:** The offered presets were approximately 768 MiB total, the official approximately 3 GiB default, or approximately 6 GiB expanded storage; the user subsequently requested a custom equal per-tier value.
- **User answer:** Configure every tier to `768 MiB`.
- **Explicit rationale:** No additional rationale was provided.
- **Resulting impact:** REQ-005, DEC-004, and AC-003 set all three tiers to 768 MiB, approximately 2.25 GiB total, while retaining the official time limits and first-limit-wins rotation behavior.

### DISC-005: Health alert delivery

- **Situation:** Netdata can show health alarms locally and can also integrate with external notification systems that require additional services or credentials.
- **Question:** Should the initial installation show alarms only in the UI or actively deliver them externally?
- **Options and tradeoffs:** UI-only alarms require no external accounts but are seen only when the dashboard is opened; Email or other active delivery adds timely notification but introduces credentials and dependencies.
- **User answer:** Option 1, show alerts only in the Netdata UI.
- **Explicit rationale:** No additional rationale was provided.
- **Resulting impact:** REQ-006, DEC-005, AC-004, and Out of Scope require local UI alarms and prohibit active external notification configuration in this change set.

## Open Decisions

None.

## Routing/Gates

- Security boundary: home-LAN-only and local-only operation selected.
- Installation architecture: direct-host installation selected.
- Retention: three 768 MiB tiers selected.
- Alert delivery: local UI only selected.
- Runtime validation: required during execution.
- Exact execution authorization:[REDACTED: credential] after materialization.

## Revision History

| Revision | Date | Status | Changes |
| --- | --- | --- | --- |
| 1 | 2026-08-13 | working | Started the Netdata monitoring UI decision interview. |
| 2 | 2026-08-13 | working | Restricted the Netdata UI to home-LAN-only access. |
| 3 | 2026-08-13 | working | Selected direct installation on the Proxmox host with official packages, overhead validation, and rollback evidence. |
| 4 | 2026-08-13 | working | Selected local-only operation without Netdata Cloud connectivity. |
| 5 | 2026-08-13 | working | Recorded the custom 2 GiB retention request and left its tier scope open. |
| 6 | 2026-08-13 | working | Set each of the three retention tiers to 768 MiB with official default time limits. |
| 7 | 2026-08-13 | working | Selected dashboard-only health alarms without active external notifications. |
| 8 | 2026-08-13 | confirmed | Recorded runtime and submitted dashboard evidence; AC-003 passed, while AC-001, AC-002, and AC-004 retain explicit final validation seams. |
