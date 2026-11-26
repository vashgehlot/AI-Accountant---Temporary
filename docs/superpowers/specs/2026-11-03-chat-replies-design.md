# Chat replies: design

2026-11-03 · branch `ai-accountant-demo` · amends `2026-11-02-accountant-chat-design.md` where they differ

## Why

You opened a chat for a client and asked for one thing. The reply also gave you a list of things to do. Every later reply in that chat showed the list again, and so did a new chat on the same client, though you hadn't asked.

The chat should behave like Claude's: it answers what was asked, each chat is its own conversation, and a reply shows what that reply did. Nothing is pushed at you that you didn't ask for.

Today four things cause the repeat:
- Every turn ends with a summary of every open question on the client's year, whatever was asked.
- The summary isn't part of the reply. It sits at the bottom of the chat, the next one replaces it, and reopening the chat refreshes it with every question raised anywhere.
- A new chat fetches the client's open questions and shows "N things still need you from earlier" with their cards.
- The agent is told to open each chat by mentioning anything still open from earlier chats.

## Decided by you (3 Nov)

- Things only you can answer appear **once, in the reply that raised them**.
- The Sorted list and the Posted card follow the same rule: **only in a reply that did that, or when you ask**.
- Approach **A: results belong to the reply that produced them** (not a patched bottom summary, and not cards chosen by the model).
- The four sections below were approved as presented.

## What a reply carries

A turn ends with a **result** that holds only what that turn did:

- **Files:** the files this message carried, each with how its reading went ("Read barclays-october.csv (9 rows)", "Couldn't read scan.png: …").
- **Sorted:** the decisions applied in this chat since this message was sent. This is what Sorted already holds.
- **Needs you:** the questions that are open or waiting when the turn ends but weren't open or waiting when it began. These are the ones this turn raised or reopened: the agent's own questions, and the questions the rules work out after this turn's changes. When the agent lists the open items because you asked (it calls `list_questions` in this turn), the items it listed are shown too.
- **Posted:** the posted trial balance, only when this turn's posting wrote something (new entries or reversals), or when the agent fetched the trial balance in this turn (`get_trial_balance`).

A turn that did none of these has an empty result. The reply is then its text alone, with no cards.

The turn's stream ends with a `result` event instead of `summary`, then `done`. Steps, tokens and errors stream as now.

## The agent

- The prompt drops "at the start of a chat, call list_questions and mention anything still open from earlier chats".
- The finishing rule becomes: two or three sentences on what you did in this turn; the system adds a card for each thing this turn sorted, raised or posted.
- A new rule: when the person asks what needs their attention, call `list_questions`; the system shows the items as cards.
- `ask_user` says its question is shown as a card in this reply.
- No other tool changes.

## Keeping replies, and reloading a chat

- Each turn is recorded on its chat: the id of the person's message (set when it is sent), the files it carried, and the result. This replaces the single "last summary" kept on the chat today.
- Opening a chat returns its messages in order. The person's message carries its files. The last assistant text of each turn carries that turn's result. A turn that has a result but no assistant text (it failed, or was stopped before the model replied) gets an assistant entry with no text.
- Every card is drawn from the question's current record, by its id. A question answered later, or settled by a document in another chat, shows as answered, waiting or resolved, never as a stale to-do.
- Reopening a chat never adds questions raised elsewhere.
- Chats saved before this change have no turn records: they show their messages without cards. There is no migration.
- The "Answered: …" note written into the agent's memory when you answer a card is for the agent. It isn't shown in the history as a message from you, because the card already shows the answer.

## Answering a card

- **A date, an upload, "I don't have it", "Not sure":** the answer and document routes return the question's current record and the answer's own effect: the decisions it applied, the posted trial balance when its posting wrote something, and the post result. They don't return a summary of anything else.
- The page updates every card for that question in the chat, collapsed to a one-line state ("Answered: 9 Oct 2026", "Waiting for the invoice", "Resolved: read brightline-invoice-BP-2210.pdf"), with one line under it saying what changed in the books ("Posted · balanced", "£240.00 moved out of Suspense").
- **An upload that doesn't match:** the card stays open with the reason, as now ("Read <name>, but it doesn't match: …").
- **A question that needs words** (the agent's own questions): you answer in the message box, as now. That is a normal turn, so its reply follows "What a reply carries".
- The agent's memory still records the answer, so later messages in the chat know about it.

## New chat, and the client page

- **New chat:** after you pick a client you see the header (client and year), the three suggested prompts and the message box. There is no "N things still need you from earlier" and there are no cards. The page no longer fetches the client's questions when a chat opens.
- The suggested prompts stay: "Review the documents I'm adding", "What needs my attention?", "Show the trial balance".
- **Client Overview:** "N things need you", with its list, stays as the one standing place for open items. Its link opens a new chat on the client and sends "What needs my attention?", so the items arrive as answerable cards. It no longer links to the client's latest chat, which would not show them.

## Errors and Stop

As now: the steps stay, the banner shows, Retry and New chat, "Stopped after N steps" with Continue. A stopped or failed turn still keeps a result when it sorted, raised or posted anything: the system's steps after the agent run as they do today.

## What stays the same

- Open items stay on the client, not the chat, and the Overview counts and lists them.
- An invoice uploaded in any chat on the client is matched against the open Documentation required items.
- A chat never sees another chat's conversation.
- The rules, the evidence checks, the tools other than the wording above, and posting.

## What this amends

In `2026-11-02-accountant-chat-design.md`:
- **What you see, step 3 ("The summary, all in one reply when it has finished"):** a reply shows the result of that turn only, as above.
- **Answering the questions, "replies with an updated short summary and trial balance":** the card updates in place, with one line saying what changed.
- **Open items outlive the chat, "A new chat on that client opens by mentioning them":** a new chat starts empty. You ask "What needs my attention?", or use the Overview's link.
- **My calls, "Open items show on the client's Overview and are mentioned when a new chat opens":** they show on the Overview and when you ask.
- **My calls, "The summary leads with what the new files changed, then anything else still open":** a reply shows what its turn did; other open items come when you ask.
- **The demo, step 7 ("Start a new chat on Northbridge: it mentions any items still open"):** start a new chat on Northbridge and ask "What needs my attention?"; the items still open come back as cards.

In `docs/superpowers/plans/2026-11-02-accountant-chat.md`: the Task 9 prompt rules, Task 10's `ReviewSummary`, thread detail and answer routes, Task 12's new-chat questions, summary and answering behaviour, and Task 13's Overview link follow this document.

## Tests

With the scripted model:
- A plain message after a review: its result has no questions, no sorted decisions and no trial balance.
- A review that raises two questions: they are in that reply's result, and the next message's result has none.
- A first message in a new chat, on a client with open questions: no cards unless the agent lists them.
- "What needs my attention?", scripted to call `list_questions`: the reply's cards are the open items.
- `get_trial_balance` called: the reply has the trial balance. A turn that posts nothing and doesn't ask: it has none.
- Reload: each turn's result sits on its reply and its files on the person's message; a card answered after the reply shows as answered; a question raised in another chat never appears; a chat with no turn records loads with plain messages.
- The answer routes return the question's current record and only that answer's effect.
- The "Answered: …" memory note is not in the visible history.

Frontend: tests for attaching results to replies, for a card's state by question id, and for the effect line. A browser check of the scenario you reported, on the scripted model. The evaluation runner and the live test read `result` instead of `summary`; their scores come from the routes, so they don't change.

## Left to the builder

- The names of the new models and their fields (for example a turn result and an answer result).
- How the turn notices that the agent called `list_questions` or `get_trial_balance`.
- The exact wording of the one-line card states and effect lines, within the style above.

## Out of scope

- A count or badge in the chat header. You chose "once, in that reply".
- Memory shared across chats, and any change to which questions exist or when the rules raise them.
