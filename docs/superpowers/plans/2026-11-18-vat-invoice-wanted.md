# Receipts without a VAT invoice: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A receipt that should have come with a VAT invoice is booked as that invoice would show it when the app is
sure it carries VAT. It asks for the invoice by the seller's name, and the invoice settles it when it arrives.

**Architecture:**
- **The reader** adds two judgements to each row: the UK VAT rate of its items, and whether the seller must be
  registered.
- **`checks.normalise`** decides each receipt alone: sure, can't tell, or none. It goes on those judgements, on what
  the document prints, and on word lists in a new `ledgersync/vat_kinds.py`.
- **Matching** adds what only the client's other rows show:
  - a VAT number on the same seller's other documents;
  - a claim's VAT on a kind that carries none;
  - a VAT invoice that settles its receipt.
- **The document rules** reclaim what normalise is sure of.
- **Books** sets how loud each ask is by the client's trivial level, and notes in the VAT figures how much of box 4
  is waiting on an invoice.
- **The page** tags the asks, copies them as a list, and warns at close.

One issue code, `vat_invoice_wanted`, takes over `hotel_vat` and the claims' "Get a VAT invoice" messages.

**Tech Stack:**
- Backend: Python 3.11, Pydantic 2, FastAPI, MongoDB, pytest.
- Frontend: Next.js and TypeScript, tested with `node:test`.

**Spec:** `docs/superpowers/specs/2026-11-18-vat-invoice-wanted-design.md`

## Global Constraints

- **Base:** `robust-ledger` at 2db355b or later, so the hotel rule (e12a559) and the `abroad` fix (2db355b) are in.
- **Another session's uncommitted files are never edited or staged:** `ledgersync/ledger.py`,
  `ledgersync/records.py`, `ledgersync/reviews.py`, `server.py` and `tests/test_reviews_api.py`. Commit only your
  own paths, with `git add <paths> && git commit -m "…" -- <paths>`.
- **Tests without the database:** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q <files>`.
- **Database tests:** run one file at a time, one after another, never with `-n 4`, and never with a `timeout`
  wrapper. The Atlas free tier allows 100 databases and 500 collections.
- **Frontend checks:** `cd frontend && npm test && npx tsc --noEmit`.
- **Model calls (credit):** only in Task 9, on the six receipts named there.
- **Saving:** every new reader field goes into `rows.INPUTS`, or
  `tests/test_checks.py::test_every_field_the_reader_gives_a_row_is_kept_when_it_is_saved` fails.
- **Wording:** plain words in the app's voice. Money is written `£1,234.56`, and the seller is named as printed
  ("Get the VAT invoice from Shell").
- **The firm's rulings stand:**
  - VAT that a receipt of £250 or less prints is reclaimed, with or without a VAT number;
  - a UK hotel stay is booked at 20%, unless its host is a private person on a booking platform.
- **Commit messages:** `feat:` or `fix:` and a plain sentence, ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

| # | Input or condition | What a person would expect | Pinned in |
|---|---|---|---|
| 1 | A VAT invoice printing the same number as its receipt (a hotel folio numbered like its booking), which `_without_copies` makes a copy | It still settles the receipt and closes the ask | Task 6 |
| 2 | Two receipts from one seller for the same amount, and one invoice | Neither is settled, and the invoice says which receipts it could be for | Task 6 |
| 3 | An undated receipt | No invoice settles it on its own, and its ask stays | Task 6 |
| 4 | A receipt the person moved to an exempt account (Insurance) after the reader judged it standard-rated | No VAT is added and nothing is asked | Task 3 |
| 5 | A receipt over £250 that prints VAT, for a client not yet registered on its date (`vat_from` after it) | Booked whole: no ask, nothing in Suspense | Task 4 |

---

## Shared interfaces

These are defined once and used across the tasks.

```python
# ledgersync/models.py
VatRate = Literal["standard", "reduced", "zero", "exempt", "none"]
VAT_RATES: tuple[str, ...] = ("standard", "reduced", "zero", "exempt", "none")
SellerRegistered = Literal["large", "no"]
# Transaction, inputs from the reader (saved):
vat_rate: Optional[VatRate] = None                     # the UK rate the items carry; None: can't tell, or mixed
seller_registered: Optional[SellerRegistered] = None   # "large": must be registered; "no": isn't
# Transaction, set by matching (never saved, never in rows.INPUTS):
seller_vat_seen: bool = False                 # the same seller printed a VAT number on another document in the books
vat_invoice: Optional[Settlement] = None      # the VAT invoice that settles this receipt

# ledgersync/checks.py
class VatInvoiceCase(NamedTuple):
    sure: bool       # True: book `vat` and reclaim it; False: can't tell, book none
    vat: Decimal     # sure: the VAT booked; can't tell: the most its VAT invoice could reclaim
    seller: str      # who to ask: the counterparty, or "the property you stayed at (booked through Booking.com)"
    printed: bool    # the VAT is the amount the receipt itself prints
VAT_INVOICE_ASKED: frozenset[str] = frozenset({"vat_invoice_wanted", "hotel_vat", "claim_vat", "document_wanted"})
def never_vat(tx: Transaction) -> Optional[str]: ...
def vat_invoice_case(tx: Transaction, settings: BusinessSettings) -> Optional[VatInvoiceCase]: ...
def waiting_vat(tx: Transaction) -> Optional[Literal["waiting", "answered"]]: ...
```

`VAT_INVOICE_ASKED` lists the accepted codes that answer the ask. Old answers count: `hotel_vat` on a stay,
`claim_vat` where the VAT is the claim's, and `document_wanted` on a claim line.

**New issue codes:**

| Code | Severity | Set by | What it says |
|---|---|---|---|
| `vat_invoice_wanted` | warning; info under the trivial level | normalise, matching, books | VAT reclaimed; get the VAT invoice (acceptable) |
| `vat_invoice_maybe` | info | normalise | Can't tell; the invoice could reclaim up to £X |
| `vat_invoice_in` | info | matching | The VAT invoice settled it |
| `vat_invoice_unclear` | warning | matching | An invoice that fits several receipts |
| `claim_vat_none` | info | normalise, matching | A claim's VAT on a kind that carries none |

All five go in `checks._DERIVED`. The last three also go in `checks.MATCHING_ISSUES`. `hotel_vat` stays in `_DERIVED`
so saved copies of it drop, and stays in `ACCEPTABLE` so old answers still count.

---

### Task 0: Record the baseline (nothing is committed)

**Files:**
- Create: `<scratchpad>/replay_vat.py`, kept out of the repository.

- [ ] **Step 1: Check the base.**
  - `git log --oneline -3` shows 2db355b.
  - `git status --short` lists only `ledgersync/ledger.py`, `ledgersync/records.py`, `ledgersync/reviews.py`,
    `server.py` and `tests/test_reviews_api.py`.
- [ ] **Step 2: Write `replay_vat.py`.** It opens `MongoStore(Settings.from_env().mongodb_uri, …mongodb_db_name)`;
  `books.ledger`, `trial_balance`, `vat_figures` and `bank_checks` only read. For each client and year it writes JSON
  holding:
  - for every row, its id, account, gross, `vat_posted`, `vat_not_reclaimed`, and its issue codes with severities;
  - each trial balance line's net;
  - boxes 1 to 7 and the notes, for a VAT-registered client;
  - each bank check's difference.

  It prints no names. Its argument is the output path.
- [ ] **Step 3: Run it.** `.venv/bin/python <scratchpad>/replay_vat.py <scratchpad>/replay-before.json`. Expected: a
  file exists for the 3 clients, and the 134 rows are listed.

### Task 1: The word lists (`vat_kinds.py`)

**Files:**
- Create: `ledgersync/vat_kinds.py`, which imports only `models` and `re`.
- Test: `tests/test_vat_kinds.py`.

**Interfaces:**
- Produces:
  - `never_kind(tx: Transaction) -> Optional[str]`: one of "postage stamps", "water and sewerage", "on-street
    parking", "a penalty charge", "a congestion or clean-air charge", "a government fee", "a fuel card slip"; or None.
    Fares are `checks.is_fare`'s.
  - `always_registered(name: Optional[str]) -> bool`
  - `booking_site(tx: Transaction) -> Optional[str]`: the site's own name ("Booking.com", …), or None.
  - `private_host(tx: Transaction) -> bool`
  - `fuel_card(tx: Transaction) -> bool`

  Each looks at `f"{tx.counterparty or ''} {tx.description}"`, and `never_kind` also at `tx.account_code` (7202 is
  water).

- [ ] **Step 1: Write the failing tests.**
  - `test_kinds_that_never_carry_vat` is parametrized over:
    - ("Post Office", "6 first class stamps") gives "postage stamps";
    - account 7202 "Thames Water" gives "water and sewerage";
    - "Westminster City Council pay by phone parking, on-street" gives "on-street parking";
    - "Penalty charge notice PCN" gives "a penalty charge";
    - "TfL Congestion Charge" and "ULEZ" give "a congestion or clean-air charge";
    - "DVLA vehicle tax", "Companies House confirmation statement" and "MOT test" give "a government fee";
    - "Allstar fuel card, Shell Watford" gives "a fuel card slip";
    - "NCP car park", "Shell Watford" and "Premier Inn" give None.
  - `test_sellers_that_always_charge_vat`: Shell, BP, Esso, Texaco, Tesco, Sainsbury's, Currys, Argos, Screwfix,
    Toolstation, B&Q, Ryman, Premier Inn, Travelodge, Hilton, NCP, Q-Park, BT, Vodafone, British Gas, Costa, Pret and
    Greggs are True; "Joe's Cafe", "A1 Taxis", "Amazon Marketplace" and None are False.
  - `test_booking_sites_and_private_hosts`:
    - "Booking.com - Bermonds Locke" gives "Booking.com";
    - "Expedia" and "Hotels.com" give their names;
    - `private_host` is True for "Airbnb" and "Vrbo", and False for "Booking.com".
- [ ] **Step 2: Run the tests.** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q tests/test_vat_kinds.py`.
  Expected: an ImportError.
- [ ] **Step 3: Implement the module.** Use word-boundary regexes, case-insensitive. Keep the lists in one place, and
  give each a comment saying why it belongs: the UK VAT rule, or "always registered".
- [ ] **Step 4: Run the tests again.** Expected: they pass.
- [ ] **Step 5: Commit:** `feat: the kinds that never carry VAT and the sellers that always charge it`.

### Task 2: The reader's two judgements, read and saved

**Files:**
- Modify:
  - `ledgersync/models.py`: add the types, and the four `Transaction` fields in Shared interfaces.
  - `ledgersync/extractor.py`: in `AccountingTransaction`, add the fields `vat_rate` and `seller_registered`, each
    with a `mode="before"` validator like `_bought`'s. Append to rule 7, and add both to the answer shape.
  - `ledgersync/adapter.py`: in `to_transactions`, map both fields. Statement rows get None.
  - `ledgersync/rows.py`: add `"vat_rate"` and `"seller_registered"` to `INPUTS`.
- Test: `tests/test_extractor.py`, `tests/test_adapter.py`.

**Interfaces:**
- Produces: `Transaction.vat_rate` and `Transaction.seller_registered`, as in Shared interfaces.

**The text added to rule 7:**

> Give vat_rate, the UK VAT rate of what was bought, judged from the items: "standard" (20%: fuel, a hotel room,
> equipment, hot food or drinks), "reduced" (5%: home energy, children's car seats), "zero" (cold food to take away,
> groceries, books, children's clothes, fares), "exempt" (insurance, stamps, finance), "none" (outside the scope of
> VAT: fines, council charges, wages), or null when you can't tell or the items carry different rates. Never work out
> an amount. Give seller_registered "large" when the seller is a business that must be VAT registered (a national
> chain, a petrol station, a hotel group, a utility, a public company), "no" when the document says it isn't
> registered for VAT or the seller is a private person or a host on a booking platform, and null otherwise.

- [ ] **Step 1: Write the failing tests.**
  - `test_extractor.py::test_the_reader_gives_the_items_vat_rate_and_whether_the_seller_must_be_registered`:
    - the schema has both fields;
    - " Standard " validates to "standard", and "twenty percent" to None;
    - "LARGE" validates to "large";
    - the prompt contains "vat_rate" and "seller_registered".
  - `test_adapter.py::test_the_readers_rate_and_seller_reach_the_row_and_a_bank_line_keeps_neither`:
    - `adapt({**ROW, "vat_rate": "zero", "seller_registered": "large"})` gives `("zero", "large")`;
    - the same keys on a `document_type: "statement"` row give `(None, None)`.
- [ ] **Step 2: Run the tests.** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q tests/test_extractor.py
  tests/test_adapter.py tests/test_checks.py -k "reader or saved"`. Expected: the new tests fail.
- [ ] **Step 3: Implement it** in the four files listed.
- [ ] **Step 4: Run the tests again.** Expected: they pass, including
  `test_every_field_the_reader_gives_a_row_is_kept_when_it_is_saved`.
- [ ] **Step 5: Commit:** `feat: the reader says what VAT rate a purchase's items carry and whether its seller must be
  registered`.

### Task 3: Sure, can't tell, or none (`checks.py`)

**Files:**
- Modify: `ledgersync/checks.py`. The work:
  - add `never_vat`, `VatInvoiceCase`, `vat_invoice_case` and `VAT_INVOICE_ASKED`;
  - in `normalise`, the branch `elif vat is None and tx.vat_treatment is None:` and the over-£250 hotel block take
    `vat_invoice_case`;
  - `_vat_in_total` and `vat_implied` follow the reader's rate and `never_vat`;
  - remove `hotel_vat`, and update the `_DERIVED` and `ACCEPTABLE` sets.
- Test: `tests/test_checks.py`. Its hotel section's codes and messages move to `vat_invoice_wanted`; its cases stay.

**Interfaces:**
- Consumes: Task 1's functions; Task 2's fields.
- Produces: `never_vat`, `vat_invoice_case` and `VAT_INVOICE_ASKED` (Shared interfaces).

**What `never_vat(tx)` returns:**
- `"a fare"` when `is_fare(tx)`;
- else `vat_kinds.never_kind(tx)`;
- else the account's name when `_carries_no_vat(account)`;
- else None.

**When `vat_invoice_case(tx, settings)` gives None:**
- the row isn't a purchase receipt (money out, `document_type == "receipt"`) in GBP;
- `tx.abroad` or `tx.reverse_charge` is set;
- `not reclaims_vat(tx, settings)`;
- a person chose the VAT: `tx.vat_treatment`, `tx.vat_confirmed`, `tx.without_document`, or `tx.vat == 0`;
- the receipt is already a VAT invoice: it prints VAT, it is £250 or less, and it doesn't say "not a VAT invoice";
  or `vat_implied` holds;
- the receipt prints no VAT, and any of these is true:
  - `never_vat(tx)`;
  - `tx.vat_rate` is "zero", "exempt" or "none";
  - `fuel_card(tx)`;
  - the seller isn't registered: `seller_registered == "no"` or `private_host(tx)`, and the document shows no VAT
    number and no VAT wording.

**When it is sure, and the VAT it books:**
- the receipt prints VAT above nil: `vat = tx.vat` and `printed=True`;
- otherwise it needs a rate and seller evidence, with `vat = vat_in_gross(tx.gross, rate)`:
  - **Rate:** `tx.vat_rate` "standard" or "reduced". On an old row with no rate, only the "always" kinds give one:
    7300 Fuel and Oil, or 7402 Hotels with no booking platform's private host. Both give standard.
  - **Seller evidence:**
    - `supplier_vat_number` or `vat_stated`;
    - or `tx.seller_vat_seen`;
    - or `always_registered(counterparty)`;
    - or `seller_registered == "large"`;
    - or the row is one of the "always" kinds.

**Can't tell** is everything else: `VatInvoiceCase(sure=False, vat=vat_in_gross(gross, rate or STANDARD), …)`.

**Who to ask** (`seller`): when `booking_site(tx)` names a site, "the property you stayed at (booked through
{site})"; otherwise the counterparty; failing that, "the seller".

**What `normalise` does with the case:**
- **Sure:** `posted = case.vat`. Unless `any(c in tx.accepted for c in VAT_INVOICE_ASKED)`, it adds a
  `vat_invoice_wanted` warning with exactly this text:
  - nothing printed: `"VAT £{vat:,.2f} booked at {20% or 5%}: {possessive} receipt isn't a VAT invoice. Get the VAT
    invoice from {seller}. If part of it carries no VAT, enter the VAT it does carry."`
  - printed, over £250: `"VAT £{vat:,.2f} booked as the receipt shows it, but a purchase over £250 needs a full VAT
    invoice. Get it from {seller}."`
  - printed, saying it isn't a VAT invoice: `"VAT £{vat:,.2f} booked as the receipt shows it, but it says it isn't a
    VAT invoice. Get the VAT invoice from {seller}."`

  `{possessive}` is `"{counterparty}'s"`, or "the" when there is no counterparty or it is a booking site.
- **Can't tell:** `posted = ZERO`, and a `vat_invoice_maybe` info note: `"No VAT reclaimed: the receipt shows none.
  If {seller} charged VAT, get its VAT invoice to reclaim up to £{vat:,.2f}."`

- [ ] **Step 1: Write the failing tests.** Use `tx()` with `document_type="receipt"`. Each line below is one test:
  - `test_a_fuel_receipt_that_shows_no_vat_books_20_percent_and_asks_shell_for_the_vat_invoice`: Shell, 7300,
    `gross="60.00"`, gives `vat_posted` 10.00, `codes == [("vat_invoice_wanted", "warning")]` and the message
    contains "Get the VAT invoice from Shell".
  - `test_the_readers_rate_and_a_large_seller_make_it_sure`: 7504, "Ryman", 12.00, standard and large, gives 2.00
    and the warning.
  - `test_a_reduced_rate_books_5_percent`: `vat_rate="reduced"`, 21.00, gives 1.00.
  - `test_the_reader_saying_zero_rated_adds_no_vat_and_asks_nothing`: gives 0.00 and `codes == []`.
  - `test_a_seller_with_nothing_to_show_it_is_registered_is_cant_tell`: 7406, "Joe's Cafe", 9.00, standard, gives
    0.00, `[("vat_invoice_maybe", "info")]` and "up to £1.50".
  - `test_a_vat_number_on_the_sellers_other_documents_makes_it_sure`: the same with `seller_vat_seen=True` gives
    1.50 and the warning.
  - `test_kinds_that_never_carry_vat_get_none` is parametrized over the fare, stamps, water, PCN, congestion charge,
    DVLA and fuel card rows from Task 1: no `vat_invoice_*` code, and 0.00.
  - `test_a_ticket_sellers_printed_booking_fee_vat_still_stands`: "Trainline", 7400, vat 0.17, gives 0.17.
  - `test_a_private_host_gets_no_vat_unless_the_document_shows_it`:
    - Airbnb, 7402, `seller_registered="no"`, gives 0.00 and no code;
    - with `vat_stated=True`, it is sure and raises the warning.
  - `test_a_booking_sites_stay_asks_for_the_propertys_invoice`: the message contains "the property you stayed at
    (booked through Booking.com)".
  - `test_old_rows_without_the_readers_rate_use_the_always_kinds`: "Premier Inn", 7402, with no `vat_rate`, is sure.
    "Ryman", 7504, with no `vat_rate`, is `vat_invoice_maybe`.
  - `test_an_answered_ask_keeps_its_vat_and_stops_asking`: `accepted=["vat_invoice_wanted"]`, and `["hotel_vat"]` on
    a stay, keep 10.00 with `codes == []`.
  - `test_a_receipt_moved_to_an_exempt_account_gets_no_vat` (Review Focus 4): 8204, `vat_rate="standard"`, gives
    0.00 and no code.
  - `test_vat_implied_follows_the_readers_rate_and_the_never_kinds` covers a receipt of £250 or less with
    `supplier_vat_number`:
    - `vat_rate="zero"` gives 0.00;
    - "MOT test" on 7301 gives 0.00;
    - "Post Office stamps" gives 0.00;
    - `vat_rate="reduced"` on 10.50 gives 0.50.
  - `test_nothing_is_added_for_a_client_not_registered_or_before_its_registration`.
- [ ] **Step 2: Run the tests.** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q tests/test_checks.py`.
  Expected: the new tests fail.
- [ ] **Step 3: Implement it as described above.** Then replace `hotel_vat` imports in
  `ledgersync/evidence_rules.py` and `ledgersync/matching.py` with `vat_invoice_case`, so they still import. Their
  behaviour changes in Tasks 4 and 5.
- [ ] **Step 4: Run all the non-database tests.** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q`.
  Expected: `tests/test_checks.py` passes. Failures elsewhere name only `hotel_vat`, Book VAT, or a receipt over £250
  that is held in Suspense; Tasks 4 and 5 deal with those. List them.
- [ ] **Step 5: Commit:** `feat: a receipt without its VAT invoice books the VAT it surely carries, and says when it
  can't tell`.

### Task 4: The document rules reclaim it (`evidence_rules.py`)

**Files:**
- Modify: `ledgersync/evidence_rules.py`. In `document_rule`, a `vat_invoice_case` branch takes the place of the
  `hotel_vat` branch, and a branch is added for `tx.vat_invoice`.
- Test: `tests/test_evidence_rules.py`.

**Interfaces:**
- Consumes: `checks.vat_invoice_case`; `Transaction.vat_invoice`, which Task 6 sets.

**The two new branches,** checked before the `without_document` waiver:
- **Sure:** when `case.sure`, `(tx.vat_posted or ZERO) > 0` and `not rule.reclaim_vat`, give
  `DocumentRule(action="book", reclaim_vat=True, reason="VAT the receipt surely carries: reclaimed, with the VAT
  invoice still wanted.")`.
- **Settled:** when `tx.vat_invoice is not None` and `(tx.vat_posted or ZERO) > 0`, give `DocumentRule(action="book",
  reclaim_vat=True, reason="VAT as its VAT invoice shows it: reclaimed.")`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_sure_receipt_has_its_vat_reclaimed`: Shell on 7300 at 60.00 is `("book", True, None)`, with journal
    lines 7300 50.00 and 2201 10.00.
  - `test_a_receipt_over_250_that_prints_its_vat_is_booked_and_reclaimed_not_held`: `receipt("447.28", vat="74.55",
    account="0030", counterparty="Currys")` is `("book", True, None)`, with no 9998 line.
  - `test_a_cant_tell_receipt_is_booked_whole`: `("book", False, None)`, with no 2201 line.
  - `test_a_receipt_settled_by_its_vat_invoice_reclaims_its_vat`: `vat_invoice=Settlement(ref="inv", amount=…)` with
    `vat_posted` set is `("book", True, None)`.
  - `test_a_receipt_over_250_before_the_registration_is_booked_whole_and_asks_nothing` (Review Focus 5): use settings
    with `vat_from` after the receipt. It is `("book", False, None)`, has no `vat_invoice_*` code, and has no 9998
    line.
  - Change `test_a_receipt_over_250_that_shows_no_vat_is_booked_whole_and_one_that_shows_vat_is_held`. Its
    `receipt("447.28", vat="74.55")` line becomes `("book", True, None)`. Its `statement_line` stays held.
- [ ] **Step 2: Run the tests.** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q
  tests/test_evidence_rules.py`. Expected: the new tests fail.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the tests again.** Expected: they pass.
- [ ] **Step 5: Commit:** `feat: the VAT a receipt surely carries is reclaimed, and a receipt over £250 that prints
  its VAT is booked, not held`.

### Task 5: The seller's other documents, and claims (`matching.py`)

**Files:**
- Modify:
  - `ledgersync/matching.py`: add `_with_seller_evidence`. In `_claim_vat`, handle the never kinds, turn the "Get a VAT
    invoice" message into `vat_invoice_wanted`, and let the not-a-VAT-invoice offer book its VAT. In `_with_claim_vat`,
    drop `vat_invoice_wanted` and `vat_invoice_maybe`.
  - `ledgersync/checks.py`: in `normalise`, a claim line on a `never_vat` kind books none of its VAT.
- Test: `tests/test_matching.py`.

**Interfaces:**
- Consumes: `checks.never_vat`, `vat_invoice_case` and `normalise`; `same_supplier`.
- Produces: `_with_seller_evidence(rows: list[Transaction], settings: BusinessSettings) -> list[Transaction]`, called
  first in `match_documents`, before `_without_copies`.
  - It gives every can't-tell receipt whose seller (`same_supplier`) printed a `supplier_vat_number` on another
    booked row `normalise(tx.model_copy(update={"seller_vat_seen": True}), settings)`.
  - Every other row is returned as it is.

**The claim changes:**
- **`_claim_vat` on a never kind:** when `never_vat(first)`, it returns `[issue("claim_vat_none", f"The claim shows
  VAT {_gbp(line.vat)} on {kind}, which carries no VAT: not reclaimed.", "info")]` and `{}`. This takes the place of
  today's fares-only check.
- **A claim line with no receipt** on a `never_vat` kind: `normalise` books none of its VAT, with the same
  `claim_vat_none` note.
- **VAT from the claim:** the "booked as the claim shows it … Get a VAT invoice for this" issue's code becomes
  `vat_invoice_wanted`, with the same text. The disagreement message keeps `claim_vat`.
- **The not-a-VAT-invoice offer:** the branch that returned `not_vat_invoice` with `{"vat_found": …}` now books it. It
  returns `{"vat_posted": line.vat, "net": first.gross - line.vat, "vat_from_claim": True}` and a
  `vat_invoice_wanted` warning: `f"VAT {_gbp(line.vat)} booked from its prices ({prices}), but it says it isn't a VAT
  invoice. Get the VAT invoice from {seller}."`

- [ ] **Step 1: Write the failing tests** (`helpers.normalise_and_match`):
  - `test_a_vat_number_on_the_sellers_invoice_makes_its_receipts_sure`:
    - an invoice from "Joe's Cafe" printing `supplier_vat_number`, and a 9.00 receipt from "Joe's Cafe",
      `vat_rate="standard"`;
    - the receipt gives `vat_posted` 1.50, with `vat_invoice_wanted`.
  - `test_another_sellers_vat_number_proves_nothing`: a different seller gives `vat_invoice_maybe`.
  - `test_a_claim_line_on_a_kind_that_carries_no_vat_reclaims_none`: a claim line "Parking, Westminster council,
    on-street" with `vat="1.00"` gives 0.00 and `claim_vat_none`.
  - `test_the_claims_vat_on_a_kind_that_carries_none_is_not_reclaimed_on_its_receipt`: a receipt for stamps with a
    claim line showing VAT gives 0.00 and `claim_vat_none`.
  - Change `test_prices_that_do_not_show_the_claims_vat_book_it_as_claimed_and_ask_for_an_invoice`, so that it
    expects `vat_invoice_wanted`.
  - Change `test_vat_on_a_receipt_that_says_it_is_not_a_vat_invoice_is_offered_not_booked`, and rename it
    `…_is_booked_and_asks_for_the_vat_invoice`: `vat_posted` 3.00, `codes == [("vat_invoice_wanted", "warning")]`.
- [ ] **Step 2: Run the tests.** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q tests/test_matching.py`.
  Expected: the new tests fail.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run all the non-database tests.** Expected: everything passes, except the Task 3 failures that Task 6
  or 7 covers.
- [ ] **Step 5: Commit:** `feat: a seller's VAT number on one document vouches for its receipts, and a claim's VAT on
  what carries none isn't reclaimed`.

### Task 6: A VAT invoice settles its receipt (`matching.py`, `books.py`)

**Files:**
- Modify:
  - `ledgersync/matching.py`: add `_with_vat_invoices`, and the `locked` parameter on `match_documents`.
  - `ledgersync/books.py`: `_matched` passes `locked=[b.years[p].closed for p in b.placed]`.
- Test: `tests/test_matching.py`, and one database test in `tests/test_books.py`.

**Interfaces:**
- Consumes: `checks.vat_invoice_case`, `names_match`, `vat_kinds.booking_site` and `long_date`.
- Produces:
  - `match_documents(…, locked: Optional[list[bool]] = None)`;
  - `_with_vat_invoices(rows: list[Transaction], settings: BusinessSettings, apart: list[set[int]], locked:
    list[bool]) -> list[Transaction]`.

  `match_documents` calls `_with_vat_invoices` right after `_with_claims` and before `_checked_totals`, so a settled
  invoice is never an open document.

**How `_with_vat_invoices` decides:**
- **A waiting receipt:** a booked receipt document with a date, where `vat_invoice_case` of its first row is not None.
- **A candidate invoice:** an `invoice`, or a `receipt` whose rows print VAT and a `supplier_vat_number`. It is
  booked, or a copy (`copy_of`) of the receipt itself. It goes the same way and has the same total. It is dated from 3
  days before the receipt to 90 days after it. It isn't kept apart from the receipt. Its seller is the receipt's,
  compared with `names_match`; when `booking_site` names the receipt's seller, any seller on 7402 counts.
- **Exactly one each way:**
  - the invoice's rows get `recorded_by=Settlement(ref=receipt.document_ref, amount=receipt total, date, description,
    kind="receipt")`;
  - the receipt's first row gets `vat_invoice=Settlement(ref=invoice ref, amount=invoice total, date, description,
    kind=document_type)`;
  - `vat_invoice_wanted` and `vat_invoice_maybe` drop off it;
  - a `vat_invoice_in` note is added.

  The invoice's VAT (the sum of its rows' `vat`) replaces the receipt's `vat_posted` and `net` only when all of these
  hold: the receipt is one row, it isn't `locked`, and no person chose anything (`vat_treatment`, `vat_confirmed`,
  `without_document`, or `vat` 0.00). The note's text then depends:
  - replaced: `f"VAT {_gbp(v)} as its VAT invoice shows it ({what}, {long_date(d)})."`
  - otherwise: `f"Its VAT invoice ({what}, {long_date(d)}) shows VAT {_gbp(v)}."`
- **More than one fit:** nothing is settled. The invoice's first row gets `vat_invoice_unclear`: `f"This could be the
  VAT invoice for {n} receipts from {seller} for {_gbp(total)}. Say Not the same on the ones it isn't for."`, with
  `related` set to those receipts' rows.

  This is the plan's mechanism for the spec's "asks which": "Not the same" (`apart_from`) is the existing way to tell
  two documents apart. Link exists only for bank lines.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_vat_invoice_from_the_same_seller_settles_its_receipt`: a Shell receipt, 60.00, no VAT, and an invoice
    from "Shell UK Oil Products Ltd" for 60.00 with VAT 10.00, dated one day later. After matching:
    - the receipt's `vat_invoice.ref` is the invoice's ref, `vat_invoice_wanted` has gone, and `vat_invoice_in` is
      there;
    - the invoice's `recorded_by.ref` is the receipt's ref, and `booked(invoice)` is False.
  - `test_the_invoices_vat_replaces_the_worked_out_vat`: with invoice VAT 9.17, the receipt's `vat_posted` is 9.17.
  - `test_a_persons_choice_on_the_receipt_stands_when_its_invoice_comes`: with `vat_treatment="zero"`, the VAT is
    0.00 and the note reads "shows VAT £10.00".
  - `test_a_booking_sites_stay_is_settled_by_the_propertys_own_invoice`: a Booking.com receipt for 785.60 and a
    "Bermonds Locke" invoice for 785.60 with VAT 130.93, dated 20 days later.
  - `test_an_invoice_late_or_for_another_total_or_seller_settles_nothing` is parametrized over: 91 days later, 59.00,
    and "BP".
  - `test_one_invoice_two_receipts_settles_neither_and_says_so` (Review Focus 2).
  - `test_an_undated_receipt_is_not_settled` (Review Focus 3).
  - `test_an_invoice_with_the_receipts_number_still_settles_it` (Review Focus 1): both have the same
    `document_number`.
  - `test_a_receipt_in_a_closed_year_keeps_its_vat_and_stops_asking`: `locked` is `[True, False]`.
  - `test_books.py::test_a_vat_invoice_added_later_settles_its_receipt_and_nothing_is_booked_twice` (database): add a
    receipt upload, then an invoice upload. The trial balance has 7300 at 50.00 and 2201 at 10.00, no 2100 balance,
    and no `possible_duplicate` on either row.
- [ ] **Step 2: Run the tests.** `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q tests/test_matching.py`,
  then `.venv/bin/python -m pytest -q tests/test_books.py -k vat_invoice`. Expected: the new tests fail.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the tests again,** both commands. Expected: they pass.
- [ ] **Step 5: Commit:** `feat: a VAT invoice settles the receipt waiting for it, and is not booked again`.

### Task 7: How loud each ask is, the box 4 note and the chat (`books.py`, `checks.py`, `agent/`)

**Files:**
- Modify:
  - `ledgersync/checks.py`: add `waiting_vat`.
  - `ledgersync/books.py`:
    - in `_saved_rows`, the claim line's VAT variant of `document_wanted` becomes `vat_invoice_wanted`;
    - the receipt's `large_no_vat` note ("No VAT reclaimed: the receipt shows none…") is no longer added, since the
      receipt's own case now says it (sure, can't tell, or none);
    - loudness is applied after `decide`;
    - `vat_figures` gets a note.
  - `ledgersync/agent/tools.py`: `FAMILIES["vat_invoice_wanted"] = "documents"`, and `hotel_vat` is removed.
  - `ledgersync/agent/prompt.py`: the hotel sentence becomes the general rule, below.
- Test: `tests/test_checks.py` (`waiting_vat`), and `tests/test_books.py` (database).

**Interfaces:**
- Produces: `waiting_vat(tx)`:
  - `"waiting"` when the row has a `vat_invoice_wanted` issue, whatever its severity;
  - `"answered"` when `vat_posted > 0`, `vat_invoice is None`, the row is a receipt or a claim line, and either
    `tx.vat_confirmed` or one of `VAT_INVOICE_ASKED` is in `tx.accepted`;
  - None otherwise.

**Loudness:** a `vat_invoice_wanted` warning becomes info when the row's year has levels and `vat_posted <
levels.trivial`. With no levels, it stays a warning.

**The VAT figures note:** sum `vat_posted` over the period's covered rows by `waiting_vat`. Join only the parts that
aren't nil:

`f"{_gbp(waiting + answered)} of box 4 is VAT reclaimed with no VAT invoice in: {_gbp(waiting)} waiting on {n}
invoice{'s' if n != 1 else ''}, {_gbp(answered)} accepted without one or entered by a person."`

**The prompt sentence:**

> A receipt the books are sure carries VAT but that isn't a VAT invoice (it shows no VAT, says it isn't a VAT invoice,
> or is over £250) is booked with its VAT reclaimed and asks for the VAT invoice (issue vat_invoice_wanted); one they
> can't tell about is booked without VAT and says so (vat_invoice_maybe). Don't ask for these documents; say the row
> is waiting for one if asked.

- [ ] **Step 1: Write the failing tests.**
  - `test_checks.py::test_waiting_vat_tells_an_ask_from_one_answered`.
  - `test_books.py::test_an_ask_for_a_vat_invoice_under_the_trivial_level_is_a_note`: with
    `ClientPatch(materiality=D("1500"))` (trivial £45), a Shell receipt of 60.00 has `vat_invoice_wanted` at "info".
  - `test_books.py::test_with_no_levels_the_ask_is_a_warning`.
  - `test_books.py::test_the_vat_figures_say_how_much_of_box_4_waits_on_vat_invoices`: two receipts, one waiting
    (10.00) and one accepted (2.00). The note is "£12.00 of box 4 is VAT reclaimed with no VAT invoice in: £10.00
    waiting on 1 invoice, £2.00 accepted without one or entered by a person."
  - `test_books.py::test_a_claim_line_with_no_receipt_that_reclaims_vat_asks_for_its_vat_invoice`: the code is
    `vat_invoice_wanted`.
- [ ] **Step 2: Run the tests,** each file on its own. Expected: the new tests fail.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run all the non-database tests,** then `tests/test_books.py`, `tests/test_accountant_cases.py` and
  `tests/test_agent.py`, one at a time. Expected: they pass.
- [ ] **Step 5: Commit:** `feat: an ask for a VAT invoice is as loud as the client's materiality, and the VAT figures
  say how much waits on one`.

### Task 8: The page

**Files:**
- Modify:
  - `frontend/src/lib/ledger.ts`:
    - `ISSUE_TITLES`: `vat_invoice_wanted` 'VAT invoice needed', `vat_invoice_maybe` 'VAT invoice?',
      `vat_invoice_in` 'VAT invoice in', `vat_invoice_unclear` "Which receipt's invoice?", `claim_vat_none` 'No VAT on
      this';
    - `ACCEPTABLE` and `acceptLabel`: add `vat_invoice_wanted`, labelled "It's fine without one";
    - `issueFixes`, handled before its early return for info:
      - `vat_invoice_wanted`: Add the document (`documents: true`), and No VAT on it (`change: { vat: '0.00' }`);
      - `vat_invoice_maybe`: Add the document, VAT was charged (`edit: true`), and No VAT on it;
    - remove the `hotel_vat` entries;
    - add `export const waitingOnVatInvoice = (tx: Transaction): boolean`, true when any of the row's issues is
      `vat_invoice_wanted`. It decides whether the Copy list button shows and which rows it lists, and what
      `closeWarnings` counts.
  - `frontend/src/lib/todo.ts`:
    - `TAGS['VAT invoices'] = ['vat_invoice_wanted']`, and `hotel_vat` leaves Documents;
    - add `export function vatInvoiceList(rows: SavedRow[]): string`.
  - `frontend/src/lib/sections.ts`: `closeWarnings` takes rows with `issues` and `vat_posted`, and adds the line
    below.
  - `frontend/src/components/AiReviewSection.tsx`: a "Copy list" button that shows only when a row is waiting, calls
    `navigator.clipboard.writeText(vatInvoiceList(rows))`, and then reads "Copied".
- Test: `frontend/src/lib/ledger.test.ts`, `todo.test.ts` and `sections.test.ts`.

**What `vatInvoiceList` returns:**
- Its first line is `VAT invoices still to get:`.
- Then the rows are grouped by counterparty, in order of their first date: a line with the seller's name, then one
  line per row, `- 12 Oct 2026, £60.00 (VAT £10.00)`.

**The close warning:** `` `${n} ${n === 1 ? 'row is' : 'rows are'} still waiting on a VAT invoice (${money} VAT
reclaimed).` ``

- [ ] **Step 1: Write the failing tests.**
  - `a VAT invoice ask has its title, its fixes and It's fine without one`.
  - `a can't-tell note offers Add the document, VAT was charged and No VAT on it`.
  - `asks for a VAT invoice are tagged VAT invoices`.
  - `the copied list names each seller once with its receipts under it`: two Shell rows and one Premier Inn row; the
    exact string is asserted.
  - `closing a year says how many rows wait on a VAT invoice`.
- [ ] **Step 2: Run the tests.** `cd frontend && npm test`. Expected: the new tests fail.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Check the code.** `npm test && npx tsc --noEmit`. Expected: both pass.
- [ ] **Step 5: Check it in the browser.**
  - Start `api-site-preview-8092` and `web-site-preview-3005` from `.claude/launch.json` with `preview_start`. They
    run on their own database, `ledgersync_site_preview`.
  - Seed a client from a script (`store.add_upload` of a Shell receipt at 60.00, a Joe's Cafe receipt at 9.00 with
    `vat_rate` standard, and a Premier Inn stay).
  - On the AI review page, check:
    - one "VAT invoices" card each for Shell and Premier Inn;
    - Joe's Cafe as a note only;
    - Copy list copies the three lines;
    - It's fine without one clears the card.
  - Take a screenshot.
- [ ] **Step 6: Commit:** `feat: the to-do list tags asks for VAT invoices, copies them as a list for the client,
  and closing a year counts them`.

### Task 9: The reader's live tests, and the accountant cases

**Files:**
- Create: `eval/private/<client>/` holding the live clients' Booking.com receipts. It is git-ignored. Copy the
  originals with the code behind `GET /api/clients/{id}/uploads/{upload_id}/file` in `server.py`, read only.
- Modify:
  - `eval/eval_cases.py`: three made-up receipts, drawn with `_receipt_png` (`T_…` and `Case(…,
    document_type="receipt")`):
    - `img-pump-slip-no-vat`: "SHELL WATFORD / CARD PAYMENT / PUMP 4 / AMOUNT 60.00";
    - `img-airbnb-receipt`: "Airbnb / Your stay with Sarah / 2 nights 180.00";
    - `img-cafe-no-vat-number`: "Joe's Cafe / Latte 3.20 / Toastie 5.80 / Total 9.00".
  - `eval/fixtures/`: regenerate it with `.venv/bin/python eval/make_fixtures.py`.
  - `tests/test_live_llm.py`: six tests, each reading its receipt 3 times. At least 2 of the 3 reads must agree:
    - the pump slip gives ("standard", "large");
    - a live Booking.com confirmation printing "20% VAT is included" gives `vat_stated` True;
    - the Airbnb receipt gives `seller_registered == "no"`;
    - the TfL fare (`eval/private/jenny/Transport_for_London-2026-10-31_00_00_00.pdf`) gives "zero" or "none";
    - the Bagel Factory receipt (`eval/private/jenny/`) gives "zero";
    - the café gives "standard" with `seller_registered` None.
  - `eval/accountant_cases/builder-sole-trader.json`: add a pump slip row (7300, Shell, 60.00, `vat_rate`
    standard). It `asks` `["vat_invoice_wanted"]`.
  - `eval/accountant_cases/consultancy-limited-company.json`: add a Booking.com row (7402, 547.84, `vat_stated`). It
    `asks` `["vat_invoice_wanted"]` and `never` `["needs_document"]`.

- [ ] **Step 1: Copy the Booking.com receipts** into `eval/private/`. Check `git status` doesn't list them.
- [ ] **Step 2: Add the three cases and regenerate the fixtures.** Then run
  `LEDGERSYNC_TEST_MONGODB_URI= .venv/bin/python -m pytest -q tests/test_eval_fixtures.py`. Expected: it passes, so
  the fixtures match `eval_cases.py`.
- [ ] **Step 3: Add the accountant cases.** Run `.venv/bin/python -m pytest -q tests/test_accountant_cases.py`.
  Expected: it passes.
- [ ] **Step 4: Write the six live tests.** Run `.venv/bin/python -m pytest -m llm -q tests/test_live_llm.py -k
  "vat_rate or seller"`, which costs model credit. Expected: 6 pass. If one fails, tighten rule 7's wording (Task 2)
  and run it again, at most twice; then report what the reads gave.
- [ ] **Step 5: Commit** the tests, `eval_cases.py`, `eval/fixtures/` and the accountant cases, never
  `eval/private/`: `test: the reader judges VAT rates and sellers on six real-shaped receipts`.

### Task 10: Replay the live books, and check the whole

- [ ] **Step 1: Run the replay again.** `.venv/bin/python <scratchpad>/replay_vat.py
  <scratchpad>/replay-after.json`, then diff it against `replay-before.json` row by row.
- [ ] **Step 2: Check the spec's "Done when".**
  - None of the 28 Travel receipts that show no VAT gains VAT.
  - Each UK hotel stay has 20% and `vat_invoice_wanted`, unless a private host.
  - No other row gains VAT without evidence.
  - Every trial balance balances.
  - No bank check's difference changed.
  - List every VAT change on a claim line (the never kinds) for the user.
- [ ] **Step 3: Run everything.**
  - All the non-database tests.
  - Then, one at a time: `tests/test_books.py`, `tests/test_matching.py`, `tests/test_accountant_cases.py`,
    `tests/test_clients_api.py`, `tests/test_eval_cases.py` and `tests/test_eval_fixtures.py`.
  - Then `cd frontend && npm test && npx tsc --noEmit`.

  Expected: everything passes. A failure in a file that another session changed is theirs; check with `git log` and
  file times.
- [ ] **Step 4: Report** the diff summary to the user. Restarting their API on 8085 is theirs to do.
