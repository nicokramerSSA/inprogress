"""
sample.py — synthetic vendor proposal text for demos and tests.

Real proposals are not due until July 2. To make the whole app demonstrable today,
this module returns a realistic but FABRICATED proposal narrative for each of the five
vendors, deliberately shaped to mirror that vendor's real-world strengths/weaknesses
(from the external-research dossier) so the offline 'mock' engine produces differentiated,
plausible scores. These are NOT real vendor statements — they are illustrative fixtures.

When real proposals arrive, ingest.extract_many() replaces this entirely.
"""
from __future__ import annotations

# Shared boilerplate every vendor "submits" — covers the common table-stakes language
# so the term-coverage mock engine sees baseline signal for most requirements.
_COMMON = """
Our platform supports work order creation from inbound calls, emails, customer portal,
and IoT alerts with auto-populated customer, site, and equipment context. Work orders
support configurable types, parent-child and multi-visit structures, and gated completion
for time, materials, scope, and signature capture. Dispatch and scheduling include skills-based
assignment, map and route optimization, and crew management. Preventive maintenance contracts
generate scheduled work automatically. Quoting and estimating, inventory and parts management,
and billing and invoicing are supported with standard configuration. Reporting and analytics
provide dashboards and KPI drill-down. The platform exposes a REST API and webhooks for
event-driven integration, supports SSO/SAML, MFA, TLS 1.3 encryption, role-based access,
and immutable audit trails. We provide data export at no additional cost.
"""

_PROFILES = {
    "ServiceTitan": _COMMON + """
ServiceTitan is the proven system of record for the trades, with deep, out-of-the-box and
native field service management, mobile, and dispatch. Our native iOS and Android mobile app
provides robust offline capability with automatic sync, and is the most widely adopted
technician experience in the industry — adoption is our hallmark. We deliver strong out-of-the-box
work-to-cash: gated work order completion, electronic signature capture, NTE threshold alerts,
and rapid invoicing that closes the billing lag. Pricebook and good/better/best flat-rate quoting
are best-in-class for residential and light commercial. Titan Intelligence brings proven AI for
scheduling, call booking, and marketing. We support certified payroll and prevailing wage.
Commercial and multi-entity capabilities are growing; large multi-division project accounting with
AIA G702/G703 progress billing and ASC 606 percentage-of-completion WIP are partially supported and
in some areas on our roadmap. Single-tenant dedicated deployment is available for enterprise.
""",
    "BuildOps": _COMMON + """
BuildOps is purpose-built for commercial specialty and mechanical contractors. We provide strong,
out-of-the-box project management and service management on one platform: work orders, dispatch,
native offline mobile for technicians, preventive maintenance, and proven project financials
including AIA G702/G703 progress billing, WIP, change orders, and percentage-of-completion. We
understand HVAC and mechanical contracting deeply. Our open API and modern cloud architecture
support event-driven integration and customer data access. AI features for scheduling and
back-office automation are available and expanding. We support certified payroll and prevailing
wage workflows. As a newer platform, our largest multi-entity deployments are smaller in scale
than legacy ERPs; we are investing heavily in governance for portfolios with many legal entities.
""",
    "IFS": _COMMON + """
IFS Cloud natively unifies ERP, EAM, and field service management on a single platform — unique
among the field. We bring proven enterprise scale across many legal entities, strong multi-entity
governance, and full project accounting and job costing. Out-of-the-box service management,
AI-powered scheduling optimization, and a native mobile application with offline support are core.
IFS.ai and the IFS Copilot bring agentic AI with autonomous digital workers; the platform is open
with extensive APIs, event framework, and data access. We support single-tenant dedicated cloud
deployment with SOC 2 Type II, and US/Canada data residency. Certified-payroll and CBA-specific
prevailing-wage handling is delivered through configuration and partners. AIA G702/G703 itemized
progress billing is supported through our project invoicing framework. Breadth requires a
structured implementation.
""",
    "Salesforce": _COMMON + """
Salesforce Field Service extends the world's leading CRM with field service management, dispatch,
and a native mobile app with offline capability. Agentforce delivers cutting-edge agentic AI and
autonomous agents, and the platform is fully open with comprehensive APIs, events, and data access
through Data Cloud. We provide proven two-way integration with Salesforce Sales Cloud. Multi-entity
operations are supported through configuration and a vast partner ecosystem. Project financials such
as AIA progress billing, WIP, and ASC 606 percentage-of-completion are delivered via certified
partners and custom development rather than out of the box. Certified payroll and prevailing wage
are typically delivered through partner solutions. Implementation is partner-led and configurable.
Single-tenant isolation is addressed through our enterprise architecture.
""",
    "ServiceMax": _COMMON + """
ServiceMax provides asset-centric field service management with strong equipment and installed-base
management, preventive maintenance, work order management, and a native mobile application with
offline capability. We have deep experience in complex equipment service and multi-entity operations.
The platform offers APIs for integration and data access. AI capabilities for service optimization
are available. Project-based construction financials such as AIA G702/G703 progress billing and
ASC 606 WIP are not a core focus and are typically addressed via partners or roadmap. Certified
payroll and prevailing wage are delivered through configuration and partners. We support enterprise
deployment options; please refer to our roadmap for several enterprise governance enhancements.
""",
}


def sample_proposal_text(vendor: str) -> str:
    """Return the synthetic proposal for a vendor (case-insensitive); generic if unknown."""
    for name, text in _PROFILES.items():
        if name.lower() == (vendor or "").strip().lower():
            return f"[SYNTHETIC SAMPLE PROPOSAL — {name} — illustrative, not a real submission]\n" + text
    return f"[SYNTHETIC SAMPLE PROPOSAL — {vendor}]\n" + _COMMON
