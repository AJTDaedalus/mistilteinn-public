"""Refresh the committed disposable-email-domain snapshot.

Manual step, deliberately. The list is a *committed artifact* rather than a live fetch —
registration must stay deterministic and offline (a network call in the signup path is a
new failure mode), and a list that changes under us turns a reviewed decision into an
unreviewed one. Same reasoning as the L6/LU gates in the root CLAUDE.md.

Run it on purpose, review the diff, commit it on its own:

    cd backend && python -m scripts.refresh_disposable_domains
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import urllib.request

SOURCE = (
    "https://raw.githubusercontent.com/disposable-email-domains/"
    "disposable-email-domains/master/disposable_email_blocklist.conf"
)
TARGET = pathlib.Path(__file__).resolve().parents[1] / (
    "app/data/validation/disposable_email_domains.json"
)
# A collapse to a fraction of the previous size means the upstream file moved or an
# error page was served. Overwriting a good snapshot with that is worse than failing.
MIN_PLAUSIBLE_DOMAINS = 1000


def main() -> None:
    """Fetch the upstream list and rewrite the snapshot, refusing implausible results."""
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        raw = response.read().decode()

    domains = sorted(
        {line.strip().lower() for line in raw.splitlines() if line.strip() and line[0] != "#"}
    )
    if len(domains) < MIN_PLAUSIBLE_DOMAINS:
        print(
            f"Refusing to write: only {len(domains)} domains parsed "
            f"(expected >= {MIN_PLAUSIBLE_DOMAINS}). Upstream may have moved.",
            file=sys.stderr,
        )
        sys.exit(1)

    previous = json.loads(TARGET.read_text())["domains"] if TARGET.exists() else []
    payload = {
        "_source": "https://github.com/disposable-email-domains/disposable-email-domains",
        "_license": "CC0-1.0 / public domain",
        "_captured": datetime.datetime.now(datetime.UTC).date().isoformat(),
        "_regenerate": "cd backend && python -m scripts.refresh_disposable_domains",
        "_note": (
            "Committed snapshot, not a live fetch. Registration must stay deterministic "
            "and offline: a network call in the signup path is a new failure mode, and a "
            "list that changes under us turns a reviewed decision into an unreviewed one. "
            "Refresh deliberately, as its own commit, so additions arrive as a diff."
        ),
        "domains": domains,
    }
    TARGET.write_text(json.dumps(payload, indent=1))
    print(f"Wrote {len(domains)} domains ({len(domains) - len(previous):+d} vs previous)")


if __name__ == "__main__":
    main()
