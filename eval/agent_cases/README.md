# Agent cases: what each file holds

Each folder is one client for the accountant chat (plan `docs/superpowers/plans/2026-11-02-accountant-chat.md`,
Task 8). `demo/northbridge/` follows the same format, with the differences listed at the end. Every figure was
worked by hand in the case's `notes.md`.

## `client.json`

A client as `POST /api/clients` takes it (`ClientFields`). Every case is a VAT-registered limited company with its
first year from 1 Apr 2026 to 31 Mar 2027, and one current account, which gets code 1200. The cases have no
opening balances.

## `documents/`

The files a person drops into the chat. Next to each one is `<file>.rows.json`: the rows as the existing
pipeline would read them, so the scripted run needs no model.

```json
{"file": "barclays-october.csv", "kind": "table", "bank_account": "1200", "transactions": [ ... ]}
```

- `kind` is what `intake` calls the file: `table` (CSV, XLSX), `text` (TXT), `pdf` or `image`.
- `bank_account` is the account a statement is read into, as the server passes it. It is `null` for anything else.
- `transactions` holds `Transaction` inputs: `date`, `description`, `direction`, `gross`, `vat`, `account_code`,
  `document_type`, `counterparty`, `document_number`, `document_total`, `document_net`, `supplier_vat_number`,
  `document_ref`, `source`, `method`, and `bank_account` on statement lines. They are
  `Transaction.model_validate`-ready.
  - The outputs `normalise` and `match` work out (`vat_posted`, `net`, `contra_account_code`, derived issues) are
    left out.
  - The one issue the adapter itself adds, `mixed_items` on a receipt kept whole, is included.
- `document_ref` is a fixed string instead of the adapter's random one, so the rows of one document share it
  and a run is repeatable.
- Every document has a `.rows.json`, not only the images and PDFs. The existing pipeline reads CSV, TXT and XLSX
  through the model too.
- A runner that uploads `documents/` as files must skip `*.rows.json`.

Quotes and text:
- Every evidence quote in `expected_decisions.json` is in the text `documents.text_of` returns for its file:
  CSV, TXT and XLSX as text, and PDFs from their text layer. So no quote needs the vision model.
- The PNGs are simple drawn receipts. No decision quotes them.

## `expected_trial_balance.json`

The posted trial balance after the case's decisions and answers: opening balances plus every posted entry. It
maps each account code to its net (debit minus credit, so a credit is negative), as `eval/jobs` does. Accounts
that net to nothing are left out.

## `expected_decisions.json`

```json
{"resolutions": [...], "automatic": [...], "from_answers": [...]}
```

- **`resolutions`:** what the agent should resolve, in the order to apply them through `resolutions.resolve`.
  - Each entry holds `action`, `rule` (the decision's expected rule), `row` (the `row_id` to pass), `arguments`,
    `evidence` (`file` + `quote`) and a `reason`.
  - Rows are named by `{"file", "description"}`, which is unique within a case. A split's parts are named
    `<file> (split)` by `add_split`, so a later step never names them.
  - `arguments` by action:
    - `keep_one`: `keep` and `drop` (a list of rows);
    - `use_primary`: `primary` and `other`;
    - `split_vat`: `parts`, as `SplitPart` fields;
    - `set_vat_from_document`: `vat`.
- **`automatic`:** what `record_automatic` records with no agent, with the bank line it should cite (R1 from the
  bank).
- **`from_answers`:** the decisions the case's answers make (R1 from the person).

## `expected_questions.json`

```json
{"before_answers": [{"kind": "date", "row": {"file": "...", "description": "..."}, "status": "open"}],
 "after_answers": [...]}
```

- `before_answers` lists the questions open or waiting after the review turn (`questions.refresh` after the
  decisions).
- `after_answers` lists them after the answers in `notes.md` are applied. It includes `waiting` ones, with their
  `answer`, because the client's questions route (`GET /api/clients/{id}/questions`, which the runner reads) lists
  both.
- A held row's question has `kind` equal to the rule's `needs` (`receipt_or_invoice` or `vat_invoice`).

## `notes.md`

Each row, its rule, its journal and the trial balance to the penny, then these sections:
- **Answers:** a fenced JSON list the runner applies in order, each item
  `{"question": {"kind", "row"}, "answer": {...}}`. The answer is a `questions.Answer` (`date`, `no_document`,
  `not_sure`), or `{"kind": "upload", "file": "<path from the case folder>"}` for a document given as the answer.
- **Needs a check:** where an existing check doesn't raise what the case needs, or the plan leaves it open.

## `demo/northbridge/`

The demo client. It differs from the cases in these ways:
- **`opening_balances.json`:** `OpeningBalances` for `PUT /api/clients/{id}/opening-balances` (`books.set_opening`),
  including the unpaid sales invoices behind Debtors.
- **`existing/*.json`:** September's rows as already-read uploads, `{"name", "kind", "bank_account",
  "transactions"}`. The demo reset loads them. They have no original file, so their uploads have no text.
- **`answers/`:** the Brightline invoice, uploaded in answer to the £240 question. It is not part of the review.
- **Two trial balances:** `expected_trial_balance_before_answers.json` (after the review turn) and
  `expected_trial_balance_after_answers.json`.
