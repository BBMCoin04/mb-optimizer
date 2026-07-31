# Changelog

## 0.2.0 - 2026-07-31

- Replace the failed upstream test URL with validated Cloudflare mirror and official presets.
- Refresh IPv4 and IPv6 ranges from Cloudflare with fresh-cache, stale-cache, and bundled fallbacks.
- Sample 800 exact candidates and make the broad pass latency-only.
- Download-test 10 shortlisted IPs and retest only the top 3.
- Parse CFST carriage-return progress into live status, counts, and elapsed time.
- Add a draggable and expandable log area with normalized progress messages.
- Soften the light interface palette.
- Add the MB Deer logo to the window, taskbar, package, and Windows executable.
- Warn when implausibly low latency suggests transparent proxy interception.

## 0.1.0 - 2026-07-31

- Add the Windows desktop optimizer interface.
- Download and verify official CloudflareSpeedTest v2.3.5 on first use.
- Run broad selection followed by three stability retest rounds.
- Rank IPs by reliability, loss, median speed, latency, and jitter.
- Add copy and CSV export actions.
- Add SHA-256-verified updates from GitHub Releases.
- Add Windows single-file build and release workflow.
