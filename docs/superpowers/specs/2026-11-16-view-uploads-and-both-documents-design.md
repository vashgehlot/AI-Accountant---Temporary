# View uploads, both documents on a two-row card, photos read larger

Approved by the user on 2026-11-16. A small change: this is the short design.

## Why

- On the Documents page an upload can only be removed; the user wants to look at what was uploaded.
- On the AI review page, a card about two rows (are these the same transaction?) opens only the first row's
  document, so the person can't compare the two.
- Receipts that print a VAT number had their VAT left in the cost. Two of Jenny's Southgate car park photos print
  "V.A.T No. 870 487 106"; the reader missed it in 8 reads of 8 at 1200 pixels, and read it in 3 of 3 at 2000.

## What gets built

1. **View on the Documents page.** Each upload in the Uploads list gets View, which opens the file beside the list
   in the same panel the AI review page uses (`DocumentPanel.tsx`): a PDF or an image in place, any other file as
   the lines read from it, under a note saying why there is no file (pasted as text; split off another upload, which
   holds the file; or not kept). A hand-typed upload has nothing to view.
2. **Both documents on a two-row card.** When a card's issues (`related`), suggestions or questions (`row_ids`) name
   rows from more than one upload, View document opens every one of those documents stacked in the panel, each under
   its own name, with that document's own row marked in its lines. One document: as today.
3. **Photos read larger.** `prepare_image` sends photos and scanned pages at most 2000 pixels on the long side
   (was 1200), with a live test on the Southgate receipt that its VAT number is read.

## Approaches

- Both documents: stacked in one panel (picked: both visible at once, no new controls) / tabs in the panel (one at a
  time, defeats comparing) / two panels side by side (too narrow beside the list).
- VAT: read photos larger (picked: fixes the cause) / reclaim on a printed VAT amount without a number (would wrongly
  reclaim the Amazon order summary, which shows "Estimated VAT" and no number) / a second transcription pass (more
  calls, more cost, no better than reading larger).

## Not in it

- The document rules are unchanged.
- Saved rows aren't re-read: the two Southgate rows change only when their photos are added again, or a person
  presses Reclaim it.

## Left to the builder

- Where View sits in an upload's line, and how the panel shares the page with the Uploads list (as the AI review page
  does: beside it on a wide screen, over it on a narrow one).
- Which issue codes count as "about another row" for item 2: any issue with `related`, plus the card's suggestions'
  and questions' `row_ids`.
- Cost: a 2000-pixel image is about 2.8 times the pixels of a 1200-pixel one; text PDFs are unaffected.
