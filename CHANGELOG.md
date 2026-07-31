# Changelog

## 0.2.5 - 2026-08-01

- Reduce the default window width from 1120 to 934 pixels while keeping the window resizable.

## 0.2.4 - 2026-08-01

- Use one monotonic elapsed clock across preparation and every CFST stage so diagnostic timestamps no longer reset.
- Emit a ten-second CFST heartbeat and return stale numeric progress to an indeterminate animation after eight seconds.
- Keep an initial `0/N` frame labeled as latency testing instead of download testing.
- Synchronize the actual successful endpoint back to the UI and settings, and include it in exported CSV files.
- Retest two fastest candidates plus one low-latency candidate instead of selecting all finalists from a single speed sample.
- Remove the custom URL probe-bypass option and always apply the automatic safe ordering policy.
- Fall back to direct process termination if Windows `taskkill` itself times out.
- Increase retained diagnostic log capacity from 500 to 2000 lines.

## 0.2.3 - 2026-08-01

- Fix unreadable confirmation, update, error, and information dialogs by applying a complete application palette and explicit dialog colors.
- Use the successful Cloudflare mirror as the default endpoint and add two opt-in community endpoint presets.
- Move a custom URL behind known endpoints when its ordinary probe fails; skipping the probe keeps the custom URL first.
- Change the standard defaults to 300 ms latency, 25% loss, and 800 broad candidates, including migration from the previous broad defaults.
- Remove the editable URL clear button.
- Deepen the gray palette across the window, panels, inputs, tables, buttons, and dialogs.

## 0.2.2 - 2026-08-01

- Treat ordinary URL probing as advisory because CFST connects the URL host to each candidate IP without DNS.
- Use CFST with debug output to test the preferred URL, official speed endpoint, and mirror in order; retry automatically when speeds are all zero.
- Expand the download candidate pool to 30 and ask CFST to find up to 10 results above 0.01 MB/s, reducing failures caused by origin-only IPs.
- Make the official Cloudflare speed endpoint the default while retaining the mirror as a fallback.
- Keep progress in the latency stage until CFST explicitly announces download testing.
- Remove numeric stepper buttons, make form labels transparent, and reduce the brightness of the application palette.

## 0.2.1 - 2026-08-01

- Continue after CFST writes a complete CSV but does not exit, using a five-second grace period and bounded process cleanup.
- Close CFST standard input, bound output-reader shutdown, and add phase, PID, CSV-ready, exit-code, and cleanup diagnostics.
- Keep latency-only progress labeled correctly and use indeterminate progress until a real count advances.
- Match endpoint probes to a browser User-Agent, distinguish HTTP, DNS, TLS, and timeout failures, and allow probes to be skipped.
- Save final UTF-8 BOM CSV files to the desktop automatically without overwriting earlier runs.
- Add result-folder, Save As, copy-log, and save-log actions.
- Retain two valid Cloudflare IP-list snapshots and report the selected fallback source.
- Update official GitHub Actions to Node.js 24 generations.

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
