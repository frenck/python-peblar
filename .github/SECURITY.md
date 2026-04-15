# Security Policy

We take the security of this project seriously. We appreciate your efforts to
responsibly disclose your findings and will make every effort to acknowledge
your contributions.

## Supported Versions

Only the latest released version of the Peblar Python client receives security
updates. Older versions will not be patched; please upgrade to the latest
release to receive fixes.

| Version        | Supported          |
| -------------- | ------------------ |
| Latest release | :white_check_mark: |
| Older releases | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability, please report it privately using
GitHub's private vulnerability reporting at
<https://github.com/frenck/python-peblar/security/advisories/new>.

Alternatively, you can email
[opensource@frenck.dev](mailto:opensource@frenck.dev) directly.

When reporting, please include:

1. A description of the vulnerability and its potential impact.
2. Steps to reproduce the issue or a proof of concept.
3. The affected version(s) of this package.
4. Any known mitigations or workarounds.

## Disclosure Timeline

- **Acknowledgement:** we aim to acknowledge receipt of your report within
  **7 days**.
- **Initial assessment:** we aim to provide an initial assessment within
  **14 days**, including whether we consider the report to be a valid
  vulnerability.
- **Fix and disclosure:** we aim to ship a fix and publish the advisory within
  **90 days** of the initial report. For severe issues we may move faster; for
  complex issues we may request a reasonable extension and keep you informed.

## Out of Scope

The following are explicitly **not** covered by this security policy:

- Vulnerabilities in unsupported (older) versions of this package. Please
  upgrade to the latest release first.
- Vulnerabilities in third-party dependencies. These are tracked and updated
  automatically via Renovate and should be reported upstream to the relevant
  project.
- Vulnerabilities in the Peblar charger firmware itself. Please report those
  to Peblar directly.
- Denial-of-service issues that require an attacker to already have network
  access to your Peblar charger.

Thank you for helping keep this project secure!
