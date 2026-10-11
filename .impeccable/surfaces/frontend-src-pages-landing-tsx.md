---
version: 1
slug: "frontend-src-pages-landing-tsx"
primary_target: "frontend/src/pages/Landing.tsx"
related_targets: ["frontend/src/pages/Login.tsx","frontend/src/pages/Register.tsx"]
---

## Scope

Landing page (`/`, Persuade) plus Log in (`/login`) and Create account (`/register`), both Operate, inside the same
world. First build of the Security Print world: no photography anywhere, everything is set type, rules and figures.
Visitors: prospective buyers, sellers, and demo evaluators. Action: create an account (secondary: log in). Proof:
the four safeguards shown working on a synthetic, clearly labelled demo auction. Constraints: PRODUCT.md (simulation
honesty, server is the authority, nicknames only, WCAG 2.1 AA). Auth contract: `services/auth-user/app/api.py`.

## Direction contract

THESIS: The page is the face of a banknote, the most-trusted printed instrument people handle, carrying a live
auction in its portrait window. It refuses the auction-site split hero (photo left, blue button right) and the
fintech gradient-plus-device-mockup.

OWN-WORLD: Intaglio green owns the masthead and the note's frame field; a cool watermark-pale ground (never cream);
black ink for text; serial-number red only for sequence numbers and the live dot; aubergine as the second ink for
links and focus. Hairline and double fine-line rules, corner value cells, a microtext rule line. Archivo variable:
condensed widths for denominations and display, normal width for body, tabular figures everywhere money or time
appears. Square corners.

STORY: In one glance the visitor sees an auction moving and every safeguard printed around it; they believe the
rules are enforced, not promised; they open an account.

FIRST VIEWPORT: Green masthead (wordmark, Log in, Create account). Below, one wide framed note field: headline set
across the top band; centre window with the demo auction (item, live price, fee, total, countdown, serial no. ticking
in red); the four corners hold Verified sellers, $25.00 flat fee, 7-day escrow, Server order; Create account sits on
the signature line under the window.

FORM: The Note Face, position 5 of 7 on the structural list; direction seed a9787569 (Security Print, pick); surface
seed b26eb92a.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md,
and every shipping raster carrying its provenance

## Signature interaction

The demo window is live: a new synthetic bid lands every few seconds, the serial number advances in both corners,
the price and total re-set, and a bid inside the last two minutes visibly adds an extension ("Extended 2 of 10").
Under prefers-reduced-motion the figures still update but nothing animates.

## Open decisions

Currency is USD in the demo, following `config/settlement-policy.yaml`, until ADR-0009 settles it.
