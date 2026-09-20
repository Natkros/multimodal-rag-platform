# Acme Corporation — IT Security Incident Response Runbook (v3)

## 1. Severity Classification

Every reported security incident is triaged into one of four severity levels within
15 minutes of initial report:

| Severity | Definition | Initial Response Time | Executive Notification |
|----------|------------|------------------------|-------------------------|
| SEV-1 (Critical) | Active data breach, ransomware, or full production outage caused by an attack | 15 minutes | Immediate (CTO + CEO) |
| SEV-2 (High) | Confirmed unauthorized access with no evidence of data exfiltration yet | 1 hour | Within 4 hours (CTO) |
| SEV-3 (Medium) | Suspicious activity requiring investigation, no confirmed compromise | 4 hours | Daily digest |
| SEV-4 (Low) | Policy violation or misconfiguration with no exploitation evidence | 1 business day | Weekly digest |

## 2. On-Call Escalation

The on-call Security Engineer is the first responder for any SEV-1 or SEV-2 incident.
If the on-call engineer does not acknowledge a SEV-1 page within 10 minutes, PagerDuty
automatically escalates to the Security Team Lead, and then to the CTO after a further
10 minutes with no acknowledgment. SEV-3 and SEV-4 incidents are handled during normal
business hours via the security team's shared queue, not paged.

## 3. Containment Procedures

For a confirmed SEV-1 breach involving a compromised production credential, the
on-call engineer must, in order: (1) revoke the compromised credential within 5
minutes of confirmation, (2) isolate the affected host or service from the network,
(3) preserve a forensic snapshot of the affected system before any remediation, and
(4) rotate any secrets the compromised credential could have accessed. Containment
must begin before root-cause analysis, never after.

## 4. Communication Requirements

Under Acme's customer data processing agreements, any incident confirmed to involve
customer personal data must be reported to affected customers within 72 hours of
confirmation, matching GDPR's notification window. Internal stakeholders receive a
status update every 2 hours for the duration of any active SEV-1 incident, posted to
the #incident-response channel.

## 5. Post-Incident Review

Every SEV-1 and SEV-2 incident requires a blameless post-incident review within 5
business days of resolution, producing a written root-cause report and at least one
concrete remediation action with an assigned owner and due date. SEV-3 and SEV-4
incidents receive a post-incident review only if requested by the security team lead.

## 6. Tooling

Incident detection relies on Acme's SIEM (Datadog Security Monitoring), with PagerDuty
handling on-call escalation and Jira Service Management tracking remediation tasks.
Forensic snapshots are stored in a dedicated, access-restricted S3 bucket with a
7-year retention period to satisfy Acme's longest regulatory retention obligation.
