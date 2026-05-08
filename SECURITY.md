# Security Policy

## Supported Versions

Onion Core is currently in Beta. Security fixes are provided for the latest
published minor/pre-release line.

| Version | Supported |
| ------- | --------- |
| 1.1.x   | Yes       |
| 1.0.x   | Best effort |

## Reporting a Vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub private vulnerability reporting:

<https://github.com/0z2w2j1/onion-core/security/advisories/new>

If private reporting is unavailable, open a minimal public issue asking for a
private maintainer contact channel, but do not include exploit details.

Include:

- Affected version or commit
- Reproduction steps
- Impact and affected components
- Suggested fix, if known

We aim to acknowledge reports within 7 days. Because this project is in Beta,
timelines for fixes depend on severity and maintainer availability.

Please allow the maintainers reasonable time to investigate and publish a fix
before public disclosure.

## Scope

In scope:

- Middleware bypasses that expose blocked content, PII, or forbidden tools
- Cache key isolation failures across providers, models, tenants, or governance policies
- Unbounded memory or resource growth reachable through public APIs
- Unsafe default behavior in rate limit, budget, retry, fallback, or circuit breaker logic

Out of scope:

- Vulnerabilities in upstream LLM providers, model behavior, or hosted APIs
- Prompt injection claims without a concrete Onion Core bypass
- Denial-of-service scenarios requiring unrealistic local control or unlimited local resources
