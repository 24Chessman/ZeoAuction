# ZeoAuction: Screen Descriptions

This file describes every screen in the planned ZeoAuction application: what each screen is for and what is on it.
It covers the whole project, including screens that haven't been built yet. The screens are grouped by who uses
them: everyone, buyers, account holders, sellers and administrators. A final group covers system and error pages.

---

## Parts that appear on every screen

### Top bar
A dark blue bar across the top of every page.
- **Left:** the "ZeoAuction" name, which goes back to the home page. In the seller area it reads "ZeoAuction — Seller",
  and in the admin area "ZeoAuction Admin".
- **Right, when signed out:** links to Browse and Sell, and a Sign in button.
- **Right, when signed in:** Browse, Sell, a bell icon with the number of unread notifications (up to "9+"), and the
  user's name with a drop-down menu containing Profile, My bids, My orders, Seller dashboard and Sign out.
- **Right, for administrators:** KYC Queue, Listings, Disputes, Audit, Metrics, the bell, and the admin's name.
- On tablets and phones the links fold into a menu button (☰) that opens a side drawer. The bell stays visible.

### Banners under the top bar
Strips that appear only when they're needed, in this order:
1. Connection problems, such as "Reconnecting… prices will resume automatically".
2. Account problems, such as "Your account is suspended. You can browse but not bid or list."
3. Announcements from the administrators, which the user can dismiss.

### Footer
The line "ZeoAuction is a coursework simulation. Payments run in test mode; no real funds move.", with links to Help,
Terms and Privacy.

### Simulation notice
A yellow box with a warning sign explaining that payments run in test mode and escrow is simulated, so no real money
moves. It appears on every screen where someone might think real money is involved: account creation, bid
confirmation, order detail, the seller dashboard and seller order detail.

---

# Public and buyer screens

## 1. Browse and search (home page)

The first screen visitors see, where they find auctions to bid on. Anyone can open it without signing in.

**Search row (top)**
- A wide search box: "Search auctions by title, description or category…".
- A Search button.
- A Sort drop-down: Ending soonest (the default), Newest, Price low to high, Price high to low.

**Filter panel (left side; a "Filters" button on tablets and phones)**
- Category checkboxes: Cameras & Optics, Watches, Collectibles, Audio Equipment, Vintage Computing and others.
- Price range: Minimum and Maximum boxes.
- Status: Open now, Ending in 1 hour, Scheduled.
- An Apply filters button and a Clear all link.
- Active filters also show above the results as small removable tags, for example "Watches ✕" or "Under $500 ✕".

**Results grid**
One card per auction: two cards per row on a computer, three on very wide screens, one on a phone. Each card has:
- the item's photo
- the item title (up to two lines)
- a status label such as Open, Scheduled or Hot
- a seller line with the seller's name, star rating and a green "Verified" badge
- the price: "Current $1,250.00 · 14 bids" for open auctions, "Starting $100.00" for scheduled ones, plus "Reserve not
  met" when that applies
- the time: a live countdown such as "Ends in 00:14:22", or "Opens tomorrow 09:00"
- a small grey line: "+ flat $25.00 convenience fee on win"
- a View & Bid button and a ☆ Watch button, which changes to ★ Watching
- for ended auctions, "Sold for $1,450.00" and a plain View button in place of the bid button

**Under the results:** page numbers and a line like "Showing 1–20 of 236 results".

**Other states**
- Placeholder grey cards while results load.
- "No auctions match your search." with a Clear filters button.
- "No auctions yet. Check back soon." when the site has no auctions at all.

---

## 2. Auction detail and live bidding

This page shows one auction with its live price, fee and total, and it's where bidding happens. Anyone can view it,
but bidding requires signing in.

**Layout:** on a computer, the photos are on the left and the price and bid form on the right, with tabs underneath.
On a phone everything is stacked, and the bid box and Bid button are fixed to the bottom of the screen so they're
always within reach.

**Photo gallery:** one large image with four thumbnails below it.

**Title area**
- The item title.
- The seller's name, star rating and a "KYC Verified" label.
- A status label: Open, Extended, Scheduled, Closing or Closed.
- A countdown: "⏱ Time remaining 00:14:22 (auto-extends if a bid lands in the final 2 min)". After an extension it
  adds "Extended 3 of 10 times". The countdown turns amber in the last two minutes.

**Live price panel** (a light blue box)
- The heading "CURRENT PRICE (live)" with a green "● live" dot, or an amber "Reconnecting" label when the connection
  drops.
- The current price in large bold numbers.
- "Convenience fee if you win: + $25.00 (flat, disclosed before you bid)".
- "You would pay in total: $1,275.00", which updates as the user types a bid amount.
- A green "You're the highest bidder" label when the user is winning.
- Before anyone has bid: "Starting price $100.00 · No bids yet".

**Bid form**
- A helper line: "Minimum next bid: $1,260.00 · increment rises with bid velocity".
- A bid amount box with a currency sign in front.
- Quick-fill buttons, "+1 increment", "+2" and "+5", which fill the box without placing the bid.
- A large Place Bid button.
- A red message line under the form when something is wrong, such as a bid that's too low or an auction that has
  closed. The error code is shown next to the message.
- Signed-out visitors see "Sign in to bid" in place of the button.
- A seller looking at their own auction sees "This is your auction. You can't bid on it."
- A suspended user sees the form greyed out with "Your account is suspended and cannot bid."

**Tabs below**
- **Description:** the seller's text, the category, the starting price, and whether the reserve has been met (the
  reserve amount itself isn't shown).
- **Bid History** (open by default): a live list of bids. Each row has the bidder's nickname (such as "bidder_8f2",
  never a real name), the amount and how long ago it was placed. The top bid is marked "leading" and the user's own
  bids are marked "You". New bids slide in at the top, and older bids load with "Load older".
- **Seller Info:** the seller's name, when they were verified, their rating and number of completed sales.
- **Shipping & Returns:** the seller's shipping text and an explanation of the 7-day buyer protection window.

**Side alerts** (next to the history on a computer, above it on a phone)
- Outbid alert (amber): "You were outbid on this auction — counter-bid before 00:14:22", with a Bid again button.
- Connection notice: "Reconnecting… price updates resume automatically".
- Pop-up message when an auction is extended: "Auction extended by 2 minutes — a bid arrived in the final 2 minutes."

**Other states**
- **Scheduled:** "Opens in 1d 02:10 · Starting $100.00", with the bid form disabled ("Bidding opens at 09:00").
- **Closing:** "Bidding has closed. Finalising the winner…".
- **Won:** a green banner, "🎉 You won this auction for $1,450.00. Total due $1,475.00 (incl. $25.00 fee).", and a Go
  to your order button.
- **Lost, or viewed by a visitor:** "Auction ended. Winning bid $1,450.00" or "Ended with no bids".
- **Cancelled:** "This auction was cancelled by the seller."

---

## 3. Bid confirmation (pop-up window)

A small window that opens after the user presses Place Bid, as a last check before the bid is placed.
- Title: "Confirm your bid".
- Three lines: Your bid $1,260.00 · Convenience fee if you win $25.00 (flat) · Total if you win $1,275.00.
- A note: "Bids can't be withdrawn. If you're outbid, you pay nothing. Losing bidders are never charged a fee."
- A short simulation notice.
- A "Don't ask again this session" checkbox.
- Cancel and Confirm bid buttons. Confirm bid shows "Placing bid…" while it works.
- **When the bid succeeds,** the window closes and a message says "Bid placed — you're the highest bidder".
- **When the bid fails,** the window stays open and shows the problem. For example, if someone outbid the user in the
  meantime it says "minimum next bid is now $1,270.00" and offers a one-click "Bid $1,270.00" button.

---

## 4. My bids

A list of every auction the user has bid on, showing whether they're winning.
- Tabs: Active, Won, Lost and All.
- One row per auction with the item photo and title, the user's highest bid, the current price, a status label
  (Leading, Outbid, Won or Lost), a countdown to the end, and an action button (Bid again or View order).
- When the list is empty: "You haven't bid on anything yet. Browse auctions".

---

## 5. My orders

A list of the auctions the user has won, which they can follow through payment, shipping and release of funds.
- One row per order: the item, the winning amount, the fee, the total charged, a status label and a "Next step" line.
- The "Next step" text depends on the order's stage:
  - "Payment is being captured (test mode)"
  - "Waiting for the seller to ship"
  - "Confirm receipt or raise a dispute by 21 Sep"
  - "Dispute under review"
  - "Complete"
  - "Refunded $1,275.00"
- Buttons: View on every row. Orders that have shipped also get Confirm receipt and Raise dispute.
- Status labels: Awaiting payment, Payment retrying, Paid, Held (not yet shipped), Held (window open), Frozen (dispute
  open), Released, Refunded, Cancelled.

---

## 6. Order detail (buyer)

The full story of one order: what was paid, where the money is now, and what the buyer can do next.

**Order summary card:** the item, the seller, the winning bid, the flat convenience fee, the total charged, the fee
version (small grey text), the shipping date, and the date the protection window closes.

**Escrow timeline:** a vertical list of steps with dates, with the current step highlighted: Won → Paid → Held in
escrow → Shipped (window opens) → Released, Refunded or Frozen (dispute).

**Window banner** (once the item has shipped): "Protection window open — 4 days 12 hours left. After it closes, funds
are released to the seller.", with a countdown.

**Buttons** (only the ones that make sense for the order's current stage are shown)
- **Confirm receipt.** Opens a confirmation: "Confirming releases $1,250.00 to the seller now. You can't raise a
  dispute afterwards." The confirm button reads "Yes, release funds".
- **Raise a dispute** (red outline). Opens the dispute form.
- **View dispute.** Shown when a dispute is already open.

**Bottom of the page:** a "How escrow works" section that expands to explain the process, and the simulation notice.

---

## 7. Raise a dispute

The form a buyer uses to report a problem with an order. It's only available while the protection window is open.

**Window banner (top, amber):** "⏳ Protection window OPEN — 4 days 12 hours remaining. After it closes, funds release to
the seller and this form is permanently disabled."

**"What went wrong?" form (left)**
- A required Reason drop-down: Item not received, Item not as described, Item damaged in transit, Counterfeit or
  misrepresented, Other.
- A required "Describe the issue" box with a character counter (up to 4000 characters). The placeholder reads "What
  you expected, what arrived, and any contact you've already had with the seller".
- An evidence upload area: "Upload photos or documents (JPG, PNG, PDF — max 10 MB each)". Each uploaded file is listed
  with a tick or a cross and a remove button.

**Order summary card (right)**
- The item, winning bid, convenience fee, total charged, shipping date and window closing date.
- "What happens next":
  1. Funds are frozen immediately.
  2. An administrator reviews the evidence and the seller's response.
  3. The buyer is told the outcome through notifications.
- A fee note: "If the seller or the platform is at fault, the $25.00 fee is refunded in full. If the dispute is
  resolved against you, the fee is kept."

**Buttons:** Cancel, and a red Submit Dispute button.

**Other states**
- **Window closed:** the form can't be edited and a grey banner says "This order is closed — the protection window
  ended on 21 Sep 2026." There's no submit button.
- **Submitted:** a confirmation page says "Dispute opened. Escrow is frozen for this order.", shows Open and Escrow
  frozen labels, and has a View dispute button.

---

## 8. Dispute status (buyer and seller)

The page where both sides follow a dispute, and where the seller responds to it.
- **Header:** "Dispute — Order #00123", with a status label (Open, Under review, Resolved for buyer or Resolved for
  seller) and an "Escrow frozen" label.
- **Case summary:** the reason, the description, the date it was opened, and who opened it (the buyer, or the
  platform's fraud detection).
- **Evidence gallery:** thumbnails of the uploaded photos and documents.
- **Timeline:** Opened → Under review → Resolved, with times.
- **Seller view only:** a "Your response" text box, an upload area for evidence such as a shipping receipt or photos,
  and a Submit response button.
- **After resolution:** an outcome card such as "Resolved for buyer — refund $1,275.00 (fee refunded: seller at
  fault)" or "Resolved for seller — funds released".

---

# Account screens

## 9. Sign in

A simple card in the centre of the page.
- The title "Sign in".
- Email address and Password boxes. The password box has a show/hide eye button.
- A "Remember this device" checkbox.
- A full-width Sign in button.
- Links: "Forgot password?" and "Create an account".
- A wrong email or password shows "Email or password is incorrect". The password box is cleared and the cursor
  moves back to it.

---

## 10. Create account

The sign-up form for new users.
- Display name, Email, Password (with a strength hint) and Confirm password boxes.
- An "I want to" drop-down: Buy only, or Buy and sell. The helper text says "Selling requires identity verification.
  You can complete it now or later." People who choose Buy and sell go to the seller verification screen after
  signing up.
- A required checkbox: "I accept the terms and the simulation notice".
- A Create account button.
- The simulation notice.
- No identity documents are asked for here. A new account can browse and bid straight away.
- If the email is already registered, an error appears under the email box with a "Sign in instead" link.

---

## 11. Profile

The user's account page.
- **Account card:** the display name (editable, with Save and Cancel), the email (read-only), the role, and the date
  the user joined.
- **Verification card:** a KYC status label with one explanatory line, such as "Verified — you can list auctions",
  "Under review — usually within 2 days" or "Rejected — see the reason". A Go to verification button opens the seller
  verification screen.
- **Account status:** a red banner with "Contact support" when the account is suspended.
- **Security:** Sign out, and Sign out of all devices.
- **Notification preferences:** a switch for each type of notification.

---

## 12. Notifications (bell drop-down and full page)

Opened from the bell in the top bar. There is also a full-page version with all notifications.

**Drop-down panel** (a full-screen sheet on phones)
- The heading "Notifications" and a Mark all read button.
- A scrolling list of notifications.
- A "See all" link at the bottom.

**Each notification** has an icon, a bold title, one line of detail, how long ago it arrived, and a dot if it's
unread. Unread rows have a light blue background. Clicking a notification opens the related page.

| Type | Icon | Example |
|---|---|---|
| Outbid | ⚠ | "You were outbid: Vintage Camera Lot #4521, current price $1,270.00, ends in 00:14:22" |
| Verification result | ✅ / ✕ | "KYC approved: you're now verified and can list auctions" / "KYC needs attention: your documents were rejected" |
| Dispute | ⚖ | "Dispute resolved: Order #00123 resolved in your favour. Fee refunded in full." |
| Payout | 💰 | "Funds released: payout $1,250.00 released to your account (simulated)" |
| Auction won | 🎉 | "You won: Mechanical Watch, 1968 for $1,450.00" |
| Platform notice | 📣 | "Scheduled maintenance window announced by an administrator" |
| Seller reminder | 📦 | "Ship your item: mark it shipped to start the protection window" |

- An outbid notification also appears as a pop-up message when the user is on a different page.
- When there's nothing to show: "You're all caught up."

---

# Seller screens

## 13. Seller verification (KYC)

Where a user uploads identity documents to become a verified seller, and follows the review. It also explains why
they can't list items yet.

**Step indicator (top):** 1 Account (done) · 2 Identity documents (current) · 3 Payout details (greyed out, coming
later).

**Main card**
- The title "Submit identity verification documents".
- An explanation: "Verification is required before you can list an auction. Documents are encrypted at rest and are
  never written to our logs."
- A status strip, "Submitted → Under Review → Verified", with the current step highlighted and a status label on the
  right.
- Upload boxes (drag and drop, or browse), side by side on a computer and stacked on a phone:
  - Government photo ID (required)
  - Proof of address (required)
  - Selfie (optional)
- Under each box, a line for the file, such as "id_front.jpg · 1.8 MB · uploaded ✓" or "No file selected", with a
  progress bar while it uploads.
- A format note: "Accepted formats: JPG, PNG, PDF · maximum 10 MB per file".
- A security note: "🔒 Stored encrypted; retrievable only through a time-limited signed link, viewed only by reviewers."
- Buttons: Save draft, and Submit for Review. Submit is only active once both required files are chosen.
- If a file is refused, a message appears on that box, such as "Only JPEG, PNG and PDF are accepted", "Each document
  must be at most 10 MB" or "The file's content doesn't match its type".

**"Why can't I list yet?" panel (below the card)**

The panel's text depends on the verification status:

| Status | Panel text |
|---|---|
| Not submitted | "Listing is blocked until you're verified." |
| Submitted or under review | "Your account is under review. You'll be notified in the notification tray." |
| Rejected | "Your documents were rejected. Upload new ones to resubmit." |
| Suspended | The suspension reason |
| Verified | Turns green: "You're verified. Create your first listing →" |

**How the screen looks at each stage**

| Status | Screen |
|---|---|
| Not submitted | Empty upload boxes |
| Submitted | Upload boxes are locked and show the file details. A selfie can still be added. |
| Under review | Locked, with "Usually reviewed within 2 working days" |
| Rejected | A red box quotes the administrator's reason, the upload boxes open again, and the button reads Resubmit for Review |
| Verified | A green success view with a Create a listing button |
| Suspended | A red notice with the reason and a "Contact support" link. No uploads are possible. |

The seller never sees their own uploaded documents displayed back to them.

---

## 14. Create or edit a listing

The form a seller uses to put an item up for auction. They can save it as a draft first and publish it later.

**Layout:** the form is on the left. On a computer, a live preview on the right shows the card exactly as buyers will
see it on the browse page.

**Form sections**
1. **Item:** Title (3–200 characters, with a counter), Category drop-down, and a Description box.
2. **Photos:** up to 8 images, which can be dragged into a different order. The first image is the cover photo.
3. **Pricing:** Starting price; an optional Reserve price, which must be at least the starting price (helper text:
   "Hidden from buyers; if not met, you're not obliged to sell"); and the currency, which is fixed.
4. **Schedule:** Opens at and Closes at (date and time). Helper text: "If a bid arrives in the last 2 minutes, the
   auction extends by 2 minutes, up to 10 times."
5. **Fees:** read-only text: "A flat $25.00 convenience fee is paid by the winning buyer. Losing bidders pay nothing."

**Buttons:** Save draft, Publish, and, for drafts and scheduled listings, a red Cancel listing button that asks for
confirmation first.

**Other states**
- **Seller not verified:** the form is replaced by the "Why can't I list yet?" panel and a Verify now button.
- **Account suspended:** a red banner, with the form disabled.
- **Mistakes in the form:** messages next to the field, for example a reserve below the starting price, a closing time
  before the opening time, or an opening time in the past.
- **After publishing:** "Scheduled. Opens 15 Sep at 09:00.", with View listing and Create another buttons.

---

## 15. Seller dashboard

The seller's home page. Its main job is to answer "when will I be paid?".

**Top bar:** "ZeoAuction — Seller" with Dashboard, Listings, Payouts, the bell and the seller's name.

**Five summary tiles** (in two columns on a phone). Each tile opens the table below with a matching filter:
- Active listings (e.g. 7)
- Awaiting shipment (e.g. 2)
- Held in escrow (amount)
- Released this month (amount)
- Open disputes (e.g. 1)

**"Orders and escrow status" table**, with a filter drop-down (All, Awaiting shipment, Held, Released, Disputed):

| Column | Example |
|---|---|
| Listing | "Vintage Camera Lot #4521" |
| Sold for | $1,250.00 |
| Fee | $25.00 (paid by the buyer; shown for transparency) |
| Your payout | $1,250.00 |
| Escrow status | Held (window open), Released, Frozen (dispute open), or Held (not yet shipped) |
| Expected release | "21 Sep 2026 (in 4 d 12 h)", "(paid)", "on adjudication", or "starts on shipment" |
| Action | View, plus Mark shipped for orders that haven't shipped yet |

**Mark shipped** opens a confirmation, "Mark as shipped? The 7-day protection window starts now.", with an optional
tracking number box.

**Two notes at the bottom**
- An escrow explanation: "Funds are captured at auction close and held by the platform. They release automatically 7
  days after you mark the item shipped, unless the buyer raises a dispute. Confirmed receipt releases immediately."
- The simulation notice.

**Empty state:** "When an auction you list ends with a winner, the order appears here."

---

## 16. My listings

Every auction the seller has created.
- Tabs: Drafts, Scheduled, Live, Ended and Cancelled.
- One row per listing: the item, a status label, the current or final price, the number of bids, the open and end
  times, and the number of extensions used (e.g. "3/10").
- Buttons depend on the listing's status:

  | Status | Buttons |
  |---|---|
  | Draft | Edit, Publish, Delete |
  | Scheduled | Cancel |
  | Live | View |
  | Ended | View order |
- A Create listing button at the top of the page.

---

## 17. Seller order detail

The seller's view of one sold item.
- The buyer's nickname, the item, the sale price, the fee, and the seller's payout.
- An escrow timeline, the same as on the buyer's order page.
- The expected release date.
- A Mark shipped button, with a tracking number box, when the item hasn't shipped yet.
- When there is a dispute, a link to it and a Respond button that opens the seller's view of the dispute.
- The simulation notice.

---

# Administrator screens

## 18. Admin home and metrics

The administrator's starting page.
- **Top bar:** "ZeoAuction Admin" with KYC Queue, Listings, Disputes, Audit and Metrics.
- **Work-queue tiles:** each tile opens its queue.
  - KYC waiting (e.g. 12)
  - Reported listings (e.g. 4)
  - Open disputes (e.g. 6)
  - Fraud alerts (e.g. 2)
- **Daily metrics:** small charts with a date picker, showing auctions opened and closed, bids, total sales value
  (simulated), disputes opened and resolved, and fraud alerts.
- **System health strip:** a green or red indicator with a label for each part of the platform.

---

## 19. Admin KYC review queue

Where administrators review sellers' identity documents and approve, reject, suspend or reinstate them.

**Tabs at the top:** KYC submissions (12), Reported listings (4), Suspension requests (1).

**Left panel: "Pending review — oldest first"**
- One row per submission: the user's name, when they submitted ("submitted 2 h ago"), a status label (Submitted or
  Under Review), a red "Was rejected" tag for resubmissions, and an Open button.
- A status filter, and pages of 25.

**Right panel: submission detail**
- A header such as "kenji_optics — submission detail", with "Account created … · 0 prior submissions · 0 prior
  suspensions".
- A tile for each document (ID, proof of address, selfie) showing its type, file format, size and a shortened
  fingerprint code that can be copied. Each tile has a View document button and the note "signed URL, expires in 60 s".
- A notice: "🔒 Opening a document is itself an audited action. Document bytes are never logged and the link expires
  automatically."
- Buttons that depend on the submission's status:

  | Status | Buttons |
  |---|---|
  | Submitted | Start review (must be pressed before approving or rejecting) |
  | Under review | Approve — grant VERIFIED, and a red Reject |
  | Verified | Suspend account |
  | Suspended | Reinstate |
- A reason field. When rejecting it's free text (10–500 characters) that the seller will see. When suspending it's a
  drop-down: Document forgery, Identity mismatch, Fraud suspected, Policy violation, Other.
- An internal "Reviewer note" box.
- Every decision asks for confirmation first. For example, approving says "The seller can list immediately".

**Other states**
- **Empty queue:** "No submissions waiting. 🎉".
- **Another admin acted first:** "This submission changed while you were reviewing it", with a reload button.
- **After a decision:** a confirmation message appears, the row leaves the queue, and the detail panel shows the new
  status and who decided it, and when.

On phones and tablets the list and the detail are separate screens, with a Back button.

---

## 20. Admin moderation: reported listings and user suspensions

**Reported listings tab**
- One row per report: the listing title, who reported it, the reason, the time, and where the report came from (a new
  listing check or a user report).
- Opening a report shows a preview of the listing, the report text and the seller's history.
- Buttons: Keep listing, and Remove listing. Removing requires a reason code, and removing a live listing cancels it.

**Users and suspensions tab**
- A user search. Each result shows the user's account status, verification status and recent activity.
- Buttons: Suspend user (with a reason code and a note), and Lift suspension.
- An explanation: "Suspension blocks new listings and new bids. It's reversible and enforced by the gateway, not just
  this screen."

Every action on this screen shows the reminder "This action is written to the audit log."

---

## 21. Admin dispute adjudication console

Where administrators decide disputes, with all the evidence on one screen.

**Left panel: "Open disputes (6)"**
- A filter: All, Buyer, Fraud-flagged, Under review.
- One row per dispute, for example "Order #00123 — not as described · buyer · 2 h". Fraud cases show a red tag such as
  "SHILL RING FLAG · fraud service · 1 d".
- The selected dispute is highlighted in light blue.

**Right panel: case detail**
- **Header:** "Case detail — Order #00123", with labels for who opened it (the buyer or fraud detection), "Escrow
  frozen", and the time left in the window ("Window: 4 d left").
- **Parties and amounts:**
  - the buyer's nickname, number of orders and prior disputes
  - the seller's name, verification status and prior disputes
  - the reason
  - the amounts: bid, fee and amount captured
- **Evidence:** a thumbnail grid of the buyer's photos and documents.
- **Seller response:** the seller's text and attachments, or "No response yet — requested 1 d ago".
- **Bid trace** (fraud cases only, amber card): a summary such as "14 bids · 3 accounts sharing a device fingerprint ·
  ring confidence 0.91", with an expandable table of the bids.
- **Audit trail:** a button such as "Audit trail · 14 entries" that opens a side drawer listing every action taken on
  the case.

**Decision area**
- Two outcome buttons: Release to Seller, and a red Refund Buyer.
- A Fault drop-down (Buyer, Seller or Platform), required when refunding. A live explanation underneath says: "Seller
  or Platform fault → the $25.00 fee is refunded in full. Buyer fault → the fee is retained."
- A Request more evidence button.
- A required adjudication note, marked "written to the immutable audit log".
- A confirmation window summarising the decision, for example "Buyer receives $1,275.00 · fee refunded", with a
  Confirm decision button.

---

## 22. Admin audit log

A read-only record of every administrative action.
- **Filters:** date range, who did it, the type of action (KYC approve, KYC reject, KYC document viewed, user
  suspended, dispute resolved, and so on), what kind of record it affected, and that record's ID.
- **Table columns:**
  - the time
  - who did it (name and role)
  - which part of the system
  - the action
  - the affected record, as a link
  - the status before and after
  - the reason code
  - the note
  - a request ID
- There are no edit or delete buttons anywhere. The log can only grow.
- An Export CSV button downloads the currently filtered list.

---

## 23. Admin broadcasts

Where administrators send an announcement to all users.
- A form with a Title and a Body (up to 500 characters).
- A live preview of how the announcement will look in the notification list and as the banner at the top of the site.
- A Send to all users button, which asks for confirmation.
- A history table of past broadcasts with the title, who sent it and when.

---

# System and error screens

## 24. System and error pages

| Screen | When it appears | What it shows |
|---|---|---|
| Not found | The page or item doesn't exist | "We couldn't find that page.", with a Browse auctions button |
| Not permitted | The user isn't allowed to see the page | "You don't have access to this page.", with a Go home button |
| Session ended | The user's sign-in has expired | A message "Your session ended. Sign in again.", then the sign-in page |
| Service unavailable | Part of the system is briefly down | "Part of ZeoAuction is briefly unavailable. Your data is safe.", a Try again button and a reference code |
| Offline | The device has lost its internet connection | An amber banner: "You're offline. Live prices will resume when you reconnect." |
| Something went wrong | An unexpected problem on the page | "Something went wrong on this page.", a Reload button, and a reference code with a copy button |
| Help | Footer link | Explains how bidding, fees, auction extensions and escrow work |
| Terms | Footer link | The platform's terms of use |
| Privacy | Footer link | How identity documents and personal data are handled and how long they're kept |
