# Receipts without a VAT invoice: book the VAT when sure, ask for the invoice (design, 2026-11-18)

## Why

The user, 18 November, building this for UK practice accountants: "when we add a receipt of anything, which should
have a vat invoice but it is not provided, I want it to nudge to get a vat invoice but book it with correct details
it should have."

The same morning, an accountant ruled on hotel stays: "if the VAT is obvious add it, and then you can get the
invoice". Another session is building that hotel rule now (`checks.hotel_vat`, not yet committed). This design
makes the rule general.

The user's choices:

- **Only when sure.** VAT is added only when the app is sure the receipt carries it. When it can't tell, it asks
  instead.
- **Approach A.** "Sure" is decided by what the reader sees on the receipt, backed by evidence in the books.

Today the same situation gets four different answers (see the
[audit, section 2](../../2026-11-18-uk-accountant-audit.md)):

- A line of an expense claim with no receipt is reclaimed, and the row asks for a VAT invoice.
- A hotel stay (in progress) is reclaimed at 20%, and the row asks for the property's invoice.
- A receipt on its own that shows no VAT is booked gross, and nothing asks.
- A receipt over £250 that prints its VAT is held whole in Suspense.

The live books show why "sure" can't come from the account's usual rate. 35 of 68 purchase receipts show no VAT,
and 28 of those are Travel, which mostly carries none: zero-rated fares, on-street parking, taxi drivers who aren't
registered.

## Goals

1. **Book it as the VAT invoice would show it.** A receipt that should have come with a VAT invoice and didn't is
   booked on its account, with the net and the VAT at the right rate. The VAT is reclaimed now, but only when the
   app is sure.
2. **Ask for the invoice by the seller's name:** "Get the VAT invoice from Shell". The to-do list shows these asks,
   and the person can copy them as one list to send the client.
3. **Say so when it can't tell.** The receipt is booked without VAT, and a note says how much VAT its invoice could
   reclaim. This is not a to-do card.
4. **Let the VAT invoice settle the receipt when it arrives.** The receipt takes the invoice's VAT. Nothing is
   booked twice, the bank still agrees with its statement, and the ask closes.
5. **Show the VAT still waiting on invoices.** The VAT figures say how much of box 4 is waiting on VAT invoices, and
   closing a year lists those rows.
6. **One rule for every route:** a receipt on its own, a receipt on a claim line, and a hotel stay.

## Non-goals

- **Bank lines with no receipt.** Today's rules stand: under £50 a note; £50 to £250 held for a receipt; over £250
  held for a full VAT invoice.
- **Documents that already are VAT invoices.** These stay unchanged:
  - invoices;
  - a receipt of £250 or less that prints its VAT;
  - a receipt of £250 or less that prints the VAT number or says VAT is included (`checks.vat_implied`). Only
    where its rate comes from changes (see "The never lists").
- **Reading old uploads again.** There is no "Read again" button. A row read before this ships has none of the new
  reader fields, so it is judged by the lists in the code alone.
- **Remembering a person's answer for each seller** (approach C). That comes later, with remembered corrections.
- **Wider VAT work:** checking VAT numbers, VAT schemes, the car lease, fuel scale and partial exemption items in
  the audit.
- **Fuel cards.** A slip paid with a fuel card (Allstar, Keyfuels, UK Fuels, Shell Card, BP Plus, Esso Card and the
  like) has the card company's monthly invoice as its VAT invoice, and that invoice covers many slips. Pairing them is
  left for later. Until then, no VAT is added from such a slip.
- **Emailing the client.** The list is for the person to copy.

## Anti-goals: failures even if it works

- **VAT added to a receipt that carries none:**
  - a fare;
  - on-street parking;
  - stamps;
  - water;
  - a seller that isn't registered for VAT, such as a private host on Airbnb, or a small café.
- **A to-do list flooded with "maybe VAT" receipts for a pound or two.**
- **A purchase booked twice once its VAT invoice comes in,** or a bank account that no longer agrees with its
  statement.
- **A person's own choice overruled.** That includes:
  - a rate they picked;
  - VAT they entered or confirmed;
  - a row booked without its receipt;
  - "It's fine";
  - "No VAT on it".

## Decided

### Which receipts want their VAT invoice

The rule covers a receipt that meets all of these conditions:

- money out, with document type `receipt`;
- in pounds;
- not supplied abroad (`abroad`) and not under the reverse charge;
- on an account the client reclaims VAT on, on the receipt's date (`checks.reclaims_vat`): registered by then, and
  not entertainment, a car or Suspense.

It must also not be a VAT invoice in its own right, which means one of these is true:

- it prints no VAT amount, and `vat_implied` doesn't apply to it;
- it says it is not a VAT invoice;
- it is over £250, so only a full VAT invoice backs its VAT, whether or not it prints the VAT.

### When the app is sure

**A receipt that prints a VAT amount above nil is sure:** the seller charged the VAT, and the amount is what it
prints.

**A receipt that prints no VAT** needs both of these:

1. **The rate.** The reader says which UK VAT rate the receipt's items carry: standard (20%), reduced (5%), zero,
   exempt, none (outside the scope, or not charged), or "can't tell". Items that carry different rates count as
   "can't tell". A row read before this ships has no rate from the reader: only the "always" kinds below give it
   one, and anything else is "can't tell".
2. **Evidence that the seller charges VAT.** Any one of these:
   - this receipt prints the seller's VAT number, or says VAT is charged or included;
   - another document from the same seller in the client's books prints a VAT number (`matching.same_supplier`).
     This is worked out afresh on every pass, so a later invoice from that seller settles its earlier receipts;
   - the seller always charges VAT: it is on a list of sellers in the code (petrol stations, hotel groups, national
     retailers, the main utilities and phone companies), or the reader says it is a business that must be
     registered (a national chain, a petrol station, a hotel group, a utility, a public company).

**The "always" kinds** give a rate, and count as evidence, with no reader judgement:

- fuel at a filling station (Fuel and Oil), at 20%;
- a hotel stay in the UK (Hotels), at 20%. This keeps the accountant's ruling of 18 November, except where the host
  is a private person on a booking platform, or the receipt says the seller isn't registered.

**The never lists.** There are two:

- **Kinds that never carry VAT.** No VAT is added to these by this rule or by `vat_implied`, and a claim's VAT figure
  on them isn't reclaimed. VAT that the receipt or invoice itself prints still stands: a ticket seller prints VAT on
  its own booking fee. Only VAT a person enters or confirms in the app beats this list (my call). The kinds are:
  - fares (`checks.is_fare`);
  - postage stamps;
  - water and sewerage;
  - insurance and the other exempt or outside-the-scope accounts;
  - on-street parking, penalty charges, and congestion and clean-air charges;
  - council and government fees (DVLA, Companies House, MOT test fees);
  - a slip paid with a fuel card (see Non-goals).
- **Sellers that aren't registered.** This covers a seller the receipt says isn't registered for VAT, and one the
  reader says is a private person or a private host on a booking platform (Airbnb, Vrbo). It applies only when the
  document shows no VAT. A VAT number, VAT wording or a VAT amount on the document beats the reader's judgement (my
  call). So a booking site's confirmation that says "20% VAT is included" counts as showing VAT.

**`vat_implied` follows the same lists** (my call). Take a receipt of £250 or less that prints a VAT number but no
VAT amount:
- on a kind that never carries VAT, it gets no VAT;
- otherwise, its VAT is worked out at the reader's rate when the reader gives one: none for zero, exempt or none,
  and 5% for reduced;
- the account's rate is used only when the reader gives no rate.

Its note is unchanged, and it still doesn't ask for anything. The fix stops VAT being added at 20% to an MOT-only
receipt or to Post Office stamps.

### What is booked

**Sure.** The receipt is booked on its account. The VAT is the amount the receipt prints; if it prints none, the VAT
is worked out of the total at the reader's rate (`vat_in_gross`). The document rules reclaim it, as they reclaim a
claim's VAT (`vat_from_claim`). The row says, for example:

- "VAT £4.17 booked at 20%: Shell's receipt isn't a VAT invoice. Get the VAT invoice from Shell. If part of it
  carries no VAT, enter the VAT it does carry."
- Over £250: "VAT £50.00 booked as the receipt shows it, but a purchase over £250 needs a full VAT invoice. Get it
  from Currys."

This replaces two things:

- today's hold in Suspense of a receipt over £250 that prints its VAT;
- today's Book VAT offer on a receipt that says it is not a VAT invoice (`matching._claim_vat`).

**How loud it is** (my call, following the materiality design of 17 November). This applies to every row waiting
on a VAT invoice, claims included (see "What counts as waiting on a VAT invoice"):

- **A warning, and so a to-do card,** when the VAT booked is at or above the client's trivial level, or the client
  has no levels yet.
- **A note** when the VAT is under the trivial level.

Either way, the receipt is in the list to copy.

**Sure that no VAT applies.** The receipt is booked whole, and nothing is said, as today.

**Can't tell.** The receipt is booked whole, as today, with a note rather than a to-do card: "No VAT reclaimed: the
receipt shows none. If Joe's Café charged VAT, get its VAT invoice to reclaim up to £1.50." It offers three fixes:

- Add the document.
- VAT was charged: the person enters the VAT (`vat_confirmed`).
- No VAT on it.

This takes over today's `vat_unclaimed` note on a receipt.

**The fixes on a sure row:**

- Add the document.
- It's fine without one: the VAT stays reclaimed, and the row stops asking.
- No VAT on it: the receipt is booked whole.

**Issue codes.** There is one code for "sure" (say `vat_invoice_wanted`), which takes over `hotel_vat`; answers
already given to `hotel_vat` count for it. There is one code for "can't tell".

### Expense claims

When a receipt is on a claim line, the claim's VAT figure wins if the claim shows one. It is booked as today
(`vat_from_claim`, and `claim_vat` saying "Get a VAT invoice for this"), and this rule's figure gives way, so the
receipt asks once. `matching._with_claim_vat` already does this for `hotel_vat`.

When the claim line shows no VAT and this rule is sure about the receipt, this rule books the VAT and asks.

A claim's VAT figure on a kind that never carries VAT is not reclaimed, and the row says why. Today only fares are
stopped (`matching._claim_vat`).

### What counts as waiting on a VAT invoice

One set of rows drives five things: the "VAT invoices" tag, the loudness rule, the Copy list, the box 4 note and the
close warning (my call, from goal 6). The set is:

- receipts this rule is sure about, whose VAT it reclaimed;
- receipts whose VAT is their claim line's (`vat_from_claim`, the "Get a VAT invoice" message of `claim_vat`);
- claim lines with no receipt that reclaim VAT (`document_wanted` with VAT).

`claim_vat` has a second message, "the claim shows VAT £X; the receipt shows only £Y". That is a disagreement between
two records, and it stays under "Records disagree".

Not in the set:

- **Can't-tell receipts.** They reclaim nothing, so they stay off the client's list and out of the box 4 figure. They
  are still notes on their rows, and a VAT invoice that comes in still settles them.
- **Rows a person has answered.** These leave the to-do list and the Copy list:
  - rows answered "It's fine without one";
  - VAT a person entered or confirmed on a document that isn't a VAT invoice (`vat_confirmed`).

  Their VAT still has no invoice behind it, so the box 4 note counts it on a line of its own.

### When the VAT invoice comes in

**The receipt stays the booked row, on its own date** (my call). Its VAT was already reclaimed in that period, so
the VAT invoice is the evidence for that VAT, not a new purchase. This means:
- the VAT stays in the quarter it was claimed in;
- the bank still agrees with its statement;
- a person's choices on the receipt are kept.

A document is taken as the VAT invoice of a waiting receipt (sure, or can't tell) when it meets all of these
conditions (the window is my call):

- **It is a VAT invoice in its own right:** an invoice, or a receipt or hotel folio that prints the seller's VAT
  number and its VAT, however the reader typed it.
- **It is from the same seller,** compared with `matching.names_match`, which allows the seller's legal name
  ("Premier Inn Hotels Ltd" for "Premier Inn"). `same_supplier` is too strict here.
- **It is for the same total.**
- **It is dated between 3 days before the receipt and 90 days after it.**

**A stay booked through a booking site** (Booking.com, Expedia, Hotels.com, Airbnb and the like) is matched on Hotels
by its total and the window alone, whoever the invoice is from. Its ask names the property when the receipt does.
Otherwise it says "Get the VAT invoice from the property you stayed at (booked through Booking.com)".

Once a VAT invoice is matched:

- The receipt takes the invoice's VAT figure. If a person chose the VAT or the rate, or said "No VAT on it", the
  figure isn't taken: the row only says what the invoice shows.
- The invoice is kept as the receipt's evidence and not booked again. It is listed as "the VAT invoice for" the
  receipt.
- The two are not flagged as possible duplicates of each other, and the ask closes.
- In a closed year, nothing is rebooked: the ask closes, and a different VAT figure is only mentioned.
- The app doesn't know which VAT quarters are filed. So a different VAT figure changes the receipt's quarter, as any
  edit to an older row does.

When more than one receipt fits, the app asks which one (Link), as it does for payments.

### Where the asks show

- **On the row**, as every issue does.
- **On the to-do list (the AI review page):** the waiting rows appear as cards under a "VAT invoices" tag, as loud as
  the loudness rule says.
- **A "Copy list" button** gives the seller, date, amount and VAT of every waiting row, grouped by seller, ready to
  paste into an email to the client.
- **In the VAT figures, a note:** "£X of box 4 is VAT reclaimed with no VAT invoice in: £A waiting on N invoices, £B
  accepted without one or entered by a person."
- **In the close-year warnings:** "N rows are still waiting on a VAT invoice (£X VAT reclaimed)". This doesn't stop
  the year being closed.
- **In the chat prompt:** these are asks the books make, as with `document_wanted`, so the agent doesn't ask them
  again.

### The reader

Two new fields go on each transaction (`extractor.AccountingTransaction`, rule 7 of the instructions), validated as
`bought` is:

- **The UK VAT rate the items carry**, judged from what they are: standard, reduced, zero, exempt, none, or null when
  the reader can't tell or the items carry different rates. It is a judgement of the kind of goods, never an amount
  worked out.
- **Whether the seller must be registered:** "large" for a national chain, a petrol station, a hotel group, a
  utility or a public company; "no" when the document or the seller shows it isn't registered (it says so, or it is
  a private person or a host on a booking platform); otherwise null.

Live tests (`-m llm`) run on six receipts, from the public fixtures and `eval/private/jenny/`:

- a card-payment slip from a filling station's pump (not a fuel card);
- a UK hotel booking confirmation;
- an Airbnb receipt;
- a TfL fare;
- a cold sandwich;
- a café with no VAT number.

**Where they come from** (the user's choice, 18 November):
- the TfL fare and a cold sandwich (the Bagel Factory), from `eval/private/jenny/`;
- the live clients' Booking.com receipts, for the hotel booking confirmation. Copy them from the live store into
  `eval/private/`, which is git-ignored and never committed. One of them says "20% VAT is included".
- the pump slip with no VAT, the Airbnb receipt and the café with no VAT number, made up in `eval/eval_cases.py`.

Copying is the build's first step, not part of this design. The live tests send those receipts to the model provider
again, which the user accepted.

### Who wins

1. A person's choice: a rate picked, VAT entered or confirmed, a row booked without its receipt, a warning
   accepted, or "No VAT on it".
2. Then what the document prints: its VAT figure, VAT number or VAT wording. A VAT figure it prints is never
   replaced by one worked out, and its words beat the reader's judgement.
3. Then the kinds that never carry VAT, which stop VAT that is worked out or taken from a claim.
4. Then a claim's VAT figure.
5. Then this rule.

## Approaches considered

| | How "sure" is decided | Trade-off | |
|---|---|---|---|
| **A** | The reader gives the rate and whether the seller must be registered. The books back it up with a VAT number from the same seller. Lists in the code act as guardrails. | Right on most receipts, including an independent shop once one of its invoices is in. The reader changes, live tests spend model credit, and old rows get the lists only. | **Picked** |
| B | Fixed lists only: what always carries VAT, and from whom, and what never does. | Predictable, tested without the model, and works on every row today. Misses every seller not on the list, and the lists need upkeep. | |
| C | Ask once per seller, then remember the answer. | Always right once answered. Many questions in the first month, and the app has no memory per seller yet. | Later |

## Constraints

- **The hotel rule in progress.** `hotel_vat` and `abroad` are uncommitted in `checks.py`, `evidence_rules.py`,
  `matching.py`, `extractor.py`, `models.py`, `adapter.py` and the frontend. Build on them once they are committed:
  `abroad` is reused, `hotel_vat` folds into the new code, and its accepted answers carry over.
- **Several sessions edit this checkout at once.** Make targeted edits, and commit only your own files.
- **Issues are worked out afresh on every pass.** Nothing stored needs migrating except `accepted` codes.
- **The app doesn't know which VAT quarters are filed.** A change to an older row changes its quarter's figures.
- **The test database is on Atlas's free tier.** Run targeted test files one at a time, never with `-n 4`. To run
  with no database at all, set `LEDGERSYNC_TEST_MONGODB_URI=` (empty).
- **Live reader tests spend model credit.** Keep them to the six above.
- **The firm's rulings stand.** VAT that a receipt of up to £250 prints is reclaimed, with or without a VAT number,
  and the hotel ruling holds.

## Left to the builder

- Field and code names, and the wording of messages, in the app's voice.
- What goes on the sellers list and the never lists, starting from the examples above.
- How the evidence from the same seller's other documents reaches the step that works out the VAT: a pass over every
  row before `normalise`, or inside matching.
- How the invoice is kept as the receipt's evidence: a field of its own, or the way a bank line is booked from its
  receipt (`recorded_by`).

## Done when

- **Replaying the live clients' saved rows** (all read before this ships, so the lists alone decide):
  - none of the 28 Travel receipts that show no VAT gets VAT;
  - each UK hotel stay gets 20% and an ask, unless its host is a private person on a booking platform;
  - nothing else gets VAT added without evidence;
  - every VAT change that the kinds that never carry VAT make to a live claim line is listed, for the person to
    check;
  - the trial balance still balances, and every bank account still agrees with its statement.
- **Offline tests cover:**
  - each case under "When the app is sure";
  - the "never" list;
  - the claim-line order of who wins;
  - the over-£250 receipt booked, not held;
  - an invoice settling its receipt: its VAT taken, the invoice not booked again, no duplicate flag, the bank still
    agreeing, the ask closed;
  - a booking site's stay settled by the property's own invoice;
  - the VAT figures' note;
  - the close warning;
  - the to-do tag and Copy list.
- **The live reader tests pass** on the six receipts.
- **The accountant cases (`eval/accountant_cases`)** gain a fuel card slip and a hotel booking confirmation, each
  with the expectation an accountant would write.
