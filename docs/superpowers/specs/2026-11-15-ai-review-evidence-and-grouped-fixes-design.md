# AI review: the change in view, the document beside it, and one fix for many rows: design

## Why

On the AI review page a suggestion says its rule and its reason, but what it would change is behind a click, the
document it is about is on another page, and the same change suggested for six rows takes six clicks or "Apply all",
which applies everything. A person should be able to judge a suggestion from what is on the screen and settle a
repeated one at once. (Prompted by how Sumary shows a flag: the document beside it, the fix as before → after, one
approval for a repeated error.)

## Goals

1. Each suggestion shows what it changes, before → after, without being opened.
2. The document a card is about can be seen beside the card, without leaving the page.
3. Two or more suggestions that make the same change can be applied together, apart from the rest.

## Not in this change

- A confidence shown on a suggestion: there is no measured confidence to show.
- Showing a spreadsheet, or any file but a PDF or an image, in the page.
- The Transactions page and the chat. `DecisionLine` and `QuestionCard` stay as they are.
- A server route that applies several suggestions in one call.

## Must not happen

- A file other than a PDF or an image served for showing in the page: a hostile file must not run in the app.
- "Apply to all N" applying a suggestion of another kind, or one that is no longer on the list.
- A card losing a control it has today.

## Approaches considered

- **A. Build it on the page from what is already loaded (chosen).** A suggestion already carries its before and after
  and its quotes; a row already names its upload. Two rules in `frontend/src/lib` (the change lines, the groups) and
  one panel component; the file route learns to send a PDF or an image for showing. Grouped fixes are applied one
  after another, as "Apply all" is.
- **B. Open the document in a new tab.** Cheaper, but the document is then not beside the card.
- **C. A route that applies a group in one call.** Not needed: one refused suggestion already says why and the rest
  go on.

## Design

### 1. Before → after on the card

Under each suggestion on a card, one line for each field it changes, always visible, as its opened table writes them:

```
Date set from the receipt · The receipt is dated 2 Sep 2026.
Date: none → 2 Sep 2026
[Apply]
```

A change to more than one row says which row each line is for. More than four lines are cut to four with "and N
more" (the suggestion can still be opened for all of them).

### 2. The document beside the card

- A card whose row came from a file has **View document**. It opens a panel on the right of the list; on a narrow
  screen the panel takes the full width, over the list. The panel names the file and has Close and Download.
- A PDF or an image is shown as it is. Any other file shows the lines read from it (date, description, amount, with
  the card's own row marked), which the page already has.
- When a suggestion on the card quotes that file, the quotes are at the top of the panel.
- When the original file wasn't kept, the panel says so and shows the lines read.
- The file route sends a file for showing only when asked to and only when it is a PDF or an image; otherwise it
  sends it as a download, as now.

### 3. The same fix, once

Suggestions make the same change when they have the same kind and the same new values (the account changed to 7400;
the date is not the same change on two rows unless it is the same date). When two or more do, one line above the
list offers them together:

```
Change the account to 7400 on 6 rows   [Apply to all 6]
```

It applies those and no others, one after another; one the checks refuse says why on its card and the rest go on.
Each row keeps its own card and its own Apply. "Apply all N suggestions" stays.

## My calls, to check

- Only PDFs and images are shown in the page.
- A grouped fix is a line above the list, not a merged card.
- No confidence chip.

## Left to the builder

- Names and layout, following `src/lib` (rules, tested) and `src/components` (thin).
- How the panel is styled, in the page's own stylesheet block.
- The wording of a group's line for each kind of change, from the suggestion's own rule and new values.
- Tests: the change lines of a one-field, a several-field and a several-row suggestion, and the cut at four; groups
  of the same change, a kind with one suggestion making no group, the same kind with different values making two;
  the file route sending a PDF and an image for showing and anything else as a download.
