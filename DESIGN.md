---
name: ZeoAuction
description: Live auctions set as a security-printed note, every safeguard printed on the face.
colors:
  green: "#1F4A3D"
  green-deep: "#14342A"
  green-soft: "#2C5E4E"
  on-green: "#EEF3F1"
  on-green-soft: "#C3D6CB"
  paper: "#EEF3F1"
  tint: "#DFE9E6"
  ink: "#121816"
  ink-soft: "#43514B"
  rule: "#A9BDB2"
  rule-strong: "#5D776B"
  serial: "#B3261E"
  plum: "#6E2A55"
  alert: "#8C1C13"
typography:
  display:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "2.6rem / 3.6rem (sm) / 3.9rem (lg)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 66"
  headline:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "2.25rem / 2.75rem (sm)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.005em"
    fontVariation: "'wdth' 66"
  denomination:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "2.5rem / 3rem (sm)"
    fontWeight: 800
    lineHeight: 0.9
    letterSpacing: "-0.005em"
    fontFeature: "'tnum' 1, 'lnum' 1"
    fontVariation: "'wdth' 66"
  price:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "3.25rem / 3.75rem (sm)"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.01em"
    fontFeature: "'tnum' 1, 'lnum' 1"
    fontVariation: "'wdth' 66"
  title:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.375
    fontVariation: "'wdth' 82"
  body:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.625
    fontVariation: "'wdth' 100"
  label:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: "1rem"
    letterSpacing: "0.06em"
    fontVariation: "'wdth' 82"
  button:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: "1.25rem"
    letterSpacing: "0.01em"
    fontVariation: "'wdth' 92"
  micro:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "0.4375rem"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.08em"
    fontVariation: "'wdth' 118"
rounded:
  none: "0"
spacing:
  keyline-inset: "5px"
  gutter-sm: "16px"
  gutter-md: "24px"
  gutter-lg: "40px"
  section: "80px"
  section-lg: "112px"
  measure: "68ch"
  sheet: "78rem"
components:
  button-primary:
    backgroundColor: "{colors.green}"
    textColor: "{colors.on-green}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "0 20px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.green-deep}"
    textColor: "{colors.on-green}"
  button-primary-disabled:
    backgroundColor: "{colors.rule-strong}"
    textColor: "{colors.on-green}"
  button-paper:
    backgroundColor: "{colors.on-green}"
    textColor: "{colors.green}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "0 20px"
    height: "44px"
  button-paper-hover:
    backgroundColor: "{colors.tint}"
    textColor: "{colors.green}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.on-green}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "0 20px"
    height: "44px"
  button-ghost-hover:
    backgroundColor: "{colors.green-soft}"
    textColor: "{colors.on-green}"
  text-field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "0 14px"
    height: "48px"
  text-field-focus:
    backgroundColor: "{colors.tint}"
    textColor: "{colors.ink}"
  corner-cell:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.green}"
    typography: "{typography.denomination}"
    rounded: "{rounded.none}"
    padding: "20px"
  note-field:
    backgroundColor: "{colors.tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "24px"
  window-band:
    backgroundColor: "{colors.green}"
    textColor: "{colors.on-green}"
    typography: "{typography.label}"
    padding: "6px 6px 6px 16px"
  status-mark:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "4px 10px"
  link:
    textColor: "{colors.plum}"
---

# Design System: ZeoAuction

## Overview

**Creative North Star: "Security Print"**

ZeoAuction is set like the face of a banknote or a bank cheque: the most-trusted printed instrument people handle. Everything is type, rules and figures. There is no photography and no illustration; trust comes from intaglio green fields, double fine-line frames, corner value cells, a microtext rule line and tabular numerals that never shift. The live auction sits in the note's portrait window, and the safeguards are printed around it rather than promised in copy.

Density is that of a financial instrument: tight, ruled, legible at arm's length. Hierarchy is carried by the width axis of a single variable face (Archivo): denominations and display set condensed, labels semi-condensed, body at normal width, microtext wide. Colour is a printer's ink set, not a UI palette: one dominant green, one black, one second ink (aubergine), and serial red used as sparingly as on a real note.

Motion is quiet and mechanical: a figure re-sets when a new bid lands, the live dot breathes, the time track drains. Under reduced motion, figures still update but nothing animates.

**Key Characteristics:**
- Intaglio green owns the masthead, the note's frame field, the stub and the closing band.
- Cool watermark-pale ground; never cream.
- Square corners everywhere; depth is frame-within-frame, never shadow.
- Archivo variable on its width axis; tabular lining figures wherever money, time or sequence appears.
- Hairline, dashed and double rules do the structural work that cards and shadows do elsewhere.
- Every surface that mentions money states that payments are test mode and escrow is simulated.

## Colors

A printer's ink set: one dominant intaglio green on cool paper, black ink, a second ink in aubergine, and serial red as a rare signal.

### Primary
- **Intaglio Green** (#1F4A3D): the note's frame field, masthead, demo window band, auth stub, closing band, primary buttons, display headlines on paper, and the corner-cell denominations and settlement ordinals.
- **Deep Intaglio** (#14342A): the masthead's microtext strip and the primary button's hover state.
- **Soft Intaglio** (#2C5E4E): hairlines inside green fields (masthead and stub dividers) and the ghost-button hover fill.

### Secondary
- **Aubergine Second Ink** (#6E2A55): links, focus outlines, the text caret, the anti-snipe guard hatch, the countdown inside the guard zone, and the extension notice. It marks "rule in force" and "you can act here".

### Tertiary
- **Serial Red** (#B3261E): bid sequence numbers (the "No. 000142" serial in the bid list, the leader line and the Server Order corner) and the live dot. Nothing else.
- **Alert Oxide** (#8C1C13): form errors only: field borders, inline error text, the form-alert frame. Deliberately darker than serial red so an error never reads as a sequence number.

### Neutral
- **Watermark Paper** (#EEF3F1): the page ground, corner cells, inputs, the demo window body. Cool: blue is never below red.
- **Note Tint** (#DFE9E6): the note interior field, input focus fill, the time-track base, simulation notices, paper-button hover. Darker and cooler than paper.
- **Black Ink** (#121816): all body text, prices, the status-mark frame, the signature line.
- **Soft Ink** (#43514B): supporting copy, field hints, data labels, placeholders, timestamps.
- **Fine Rule** (#A9BDB2): decorative hairlines: the inner keyline of every double frame, bid-list dashes, section row dividers.
- **Control Rule** (#5D776B): borders that must be seen (inputs, time track, settlement column dashes, disabled buttons); at least 3:1 on paper.
- **Paper on Green** (#EEF3F1) and **Soft Paper on Green** (#C3D6CB): primary and secondary text inside green fields.

### Named Rules
**The Serial Red Rule.** Serial red marks bid sequence numbers and the live dot, and nothing else. Errors use alert oxide; emphasis uses weight or green.

**The Cool Paper Rule.** The ground is watermark-pale and cool (blue at or above red). Never cream, never warm off-white, never pure white.

**The Second Ink Rule.** Aubergine is reserved for links, focus and the anti-snipe guard. If it is decorating, it is wrong.

## Typography

**Display Font:** Archivo Variable (with system-ui, sans-serif)
**Body Font:** Archivo Variable at normal width
**Label/Mono Font:** none distinct; labels are Archivo semi-condensed, figures are Archivo with tabular lining numerals

**Character:** One grotesque used the way a note printer uses it: condensed and heavy for denominations, upright and plain for the small print. Hierarchy comes from width before size.

### Hierarchy
- **Display** (800, 2.6rem / 3.6rem / 3.9rem, 0.95, condensed 66%): the landing headline on the note face, in green.
- **Headline** (800, 2.25rem / 2.75rem, 0.95, condensed 66%): section heads and the auth stub headline; page titles on Log in and Create account step up to 2.5rem / 3rem at line-height 1.
- **Denomination** (800, 2.5rem / 3rem, 0.9, condensed 66%, tabular, uppercase): the value in each corner cell ("KYC", "$25.00", "7 DAYS", "000142"). Smaller siblings: settlement ordinals at 2rem in green, stub facts at 1.75rem on green, role names at 1.75rem bold.
- **Price** (700, 3.25rem / 3.75rem, 1, condensed 66%, tabular): the live current bid in the demo window, in black ink.
- **Title** (600, 1.125rem, 1.375, semi-condensed 82%): item names, settlement stage titles, role leads.
- **Body** (400, 1rem, 1.625, normal width): running copy, capped at 68ch; supporting text at 0.875rem.
- **Label** (600-700, 0.75rem, 0.06em, uppercase, semi-condensed 82%): data labels ("Current bid"), corner captions, the window band, the status mark.
- **Micro** (500, 0.4375rem, 0.08em, uppercase, wide 118%): the microtext rule line only. Decorative and aria-hidden.

### Named Rules
**The Denomination Rule.** Every figure of money, time or sequence is set with tabular lining numerals, so a ticking value never shifts its neighbours. Large figures are condensed.

**The Width Axis Rule.** Condensed for display and denominations, semi-condensed for labels and titles, normal for reading, wide only for microtext and the test-mode disclosure caption. Condensed text and buttons carry 0.08em word spacing so narrow words do not run together.

## Layout

A single sheet, max 78rem wide, with gutters of 16px (phone), 24px (sm) and 40px (lg). Sections are separated by open paper, 80px on phones and 112px from lg, not by bands or cards; the only full-bleed bands are the masthead and the green closing field.

The landing hero is the **note face**: a green frame field (8-12px) around a tint interior with a 6px inset keyline, holding a grid. From 1024px it is three columns (3fr / 6.4fr / 3fr): headline band across the top, four corner value cells pinned to the corners, the demo window in the centre, and the call to action on a signature line under the window. Below 1024px it reflows to headline, window, action, then corners in pairs; below 480px, a single column.

The auth pages use a **counterfoil**: one framed sheet split 5fr / 7fr from lg, green stub on the left with the context, the form on paper to the right behind a dashed control-rule seam. On phones the form comes first and the stub follows.

Lists of facts are ruled tables, not cards: settlement is a six-column strip between two green rules with dashed column seams (2 columns at sm, 1 on phones); roles are a three-column definition list with fine-rule row dividers.

## Elevation & Depth

The system is printed flat. Nothing floats and nothing casts a shadow. Depth comes from frame-within-frame: a green field, a hairline border, and an inner keyline inset by 5-6px, the way a note's value panel sits inside its border. The only `box-shadow` in the codebase draws the second line of a double rule.

### Shadow Vocabulary
- **Double rule** (`border-top: 1px solid currentColor; box-shadow: 0 3px 0 -2px currentColor`): a second hairline 2px under the first, used above totals. A line, not an elevation.

### Named Rules
**The Printed-Flat Rule.** No drop shadows and no elevation levels. To separate a surface, frame it: border, inset keyline, or a green field.

## Shapes

Every corner is square; the radius scale has one value, zero. Form language is the engraver's: 1px hairlines, double frames (1px green border plus a 1px fine-rule outline inset 5px), dashed rules for list and column seams, a 135-degree hatch of 1px aubergine lines every 5px for the anti-snipe guard zone, and a square live dot. Icons are drawn on a 20px grid at 1.5 stroke with square caps and mitre joins so they match the rules. The mark is a framed Z: a square with an inner keyline, the same double frame at 32px.

## Components

### Buttons
Solid, square and plain: the weight comes from the green, not from effects.
- **Shape:** square (0), minimum height 44px, 48px for page-level actions, 20px side padding (28px on page-level actions).
- **Primary:** intaglio green fill and border, paper text, 600 weight at 92% width. Hover deepens to deep intaglio. Disabled goes to control rule.
- **Paper (on green):** paper fill with green text, used for Create account inside green fields; hover to note tint.
- **Ghost (on green):** transparent with a soft-paper border; hover fills soft intaglio and lifts the border to paper.
- **Focus:** 2px aubergine outline offset 3px; inside green fields the outline turns paper.
- **Transitions:** colours only, 150ms, cubic-bezier(0.16, 1, 0.3, 1). A trailing arrow icon marks the forward action.

### Inputs / Fields
- **Style:** 48px tall, paper fill, 1px control-rule border, square, 14px side padding, tabular figures; label above in semi-condensed 600, optional hint in soft ink.
- **Hover / Focus:** border to black ink on hover; on focus the fill turns note tint and a 2px aubergine outline sits flush.
- **Error:** border and message in alert oxide, message prefixed by the alert icon and wired to the input by aria-describedby. Password fields carry a show/hide toggle.
- **Form alert:** a paper panel framed in alert oxide with the alert icon, the recovery message, and the server error code in small uppercase tabular soft ink.

### Navigation
- **Masthead:** a 64px green bar with the wordmark (condensed 800 uppercase, "Auction" in 500) left; Log in as a paper text link and Create account as a paper button right; signed in, the display name and a ghost Log out. Under it, a deep-intaglio microtext strip.
- **Footer:** paper, a fine-rule top border, a control-rule microtext line, then the simulation statement and course credit.

### Corner Value Cell
The note's denomination panel: a double frame on paper, 16-20px padding, a condensed denomination in green (serial red for the sequence number), a semi-condensed uppercase label in black, and one sentence of soft-ink explanation.

### Demo Window
The note's portrait window: a green-bordered paper panel with a green band carrying the "synthetic data" label and Pause/Resume. Inside: item title, a square-cornered status mark (black frame, live dot), the price in the Price role with a settle animation (420ms, a 0.14em drop and 1.5px blur resolving), a fee ledger closed by a double rule, a time track (12px, control-rule frame, tint base, green fill, aubergine hatch over the guard zone), and the latest bids as dashed-ruled rows led by red serials.

### Microtext Rule Line
A line of repeated "ZEOAUCTION · LIVE AUCTIONS · ESCROW SIMULATION · TEST MODE" at 7px wide uppercase, used as a rule under the masthead, under the note, along the auth stub and over the footer. It is texture only: aria-hidden, unselectable, and never carries information that is not printed elsewhere at reading size.

### Simulation Notice
A tint panel with a control-rule border, an aubergine alert icon and a bold "Simulation." lead. It appears wherever money moves.

## Do's and Don'ts

### Do:
- **Do** use palette and type tokens by name in screen code: no raw hex and no font names.
- **Do** set every money, time and sequence figure with tabular lining numerals (`'tnum' 1, 'lnum' 1`).
- **Do** frame surfaces with a 1px green border and a fine-rule keyline inset 5px instead of lifting them.
- **Do** reserve serial red for bid sequence numbers and the live dot.
- **Do** keep text pairs at WCAG 2.1 AA and control borders at 3:1 or more on paper (control rule #5D776B, not fine rule).
- **Do** say "test mode" and "simulated escrow" in plain words on any surface that shows money.
- **Do** honour prefers-reduced-motion: figures update, nothing animates.

### Don't:
- **Don't** round corners; the radius scale is zero.
- **Don't** add drop shadows, glows or elevation; `box-shadow` only draws the second line of a double rule.
- **Don't** use photography, device mockups or stock illustration; the world is set type, rules and figures.
- **Don't** warm the ground toward cream or ivory.
- **Don't** use serial red for errors, emphasis or decoration; errors use alert oxide.
- **Don't** use tonal or colour gradients; a repeating linear gradient is allowed only as 1px hatch line-work.
- **Don't** use icon fonts, emoji or text glyphs as icons; extend the authored 20px, 1.5-stroke, square-cap set.
- **Don't** put information in microtext; it is decorative and hidden from assistive tech.
