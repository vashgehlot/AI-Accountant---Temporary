# Chat replies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat reply shows only what its own turn did and keeps it; answering a card updates that card in place; a new chat starts empty.

**Architecture:** Each turn ends with a `TurnResult` (decisions applied this turn, questions it raised or listed, the posted trial balance only when it posted or fetched it) streamed as a `result` event and saved on the thread as a turn record keyed by the person's message id. Thread detail attaches each record to its reply, with every question read live by id. The answer and document routes return an `AnswerResult` (the question as it stands, plus that answer's own effect). The page renders each result inside its reply and stops fetching the client's questions for a new chat.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, LangChain v1 `create_agent` with the MongoDB checkpointer, pytest (scripted chat model); Next.js 16, React, TypeScript, `node:test`.

**Spec:** `docs/superpowers/specs/2026-11-03-chat-replies-design.md` (amends `docs/superpowers/specs/2026-11-02-accountant-chat-design.md`)

## Global Constraints

- Work on branch `ai-accountant-demo`. Never push. Never stage `frontend/next-env.d.ts`, `docs/superpowers/specs/2026-10-23-chat-agent-design.md` or `eval/results/`.
- Never read `.env`; never print the MongoDB URI or keys. Never run tests marked `llm` or `eval/run_agent_eval.py` (they spend OpenRouter credit).
- Backend tests: `.venv/bin/python -m pytest -q`, run serially (Atlas M0: one MongoClient per process); mongo tests need the sandbox off. Frontend: `cd frontend && npm test && ./node_modules/.bin/tsc --noEmit -p .`.
- The turn's stream ends `result` then `done`; the `summary` event and `ReviewSummary` are gone.
- A reply shows only what its turn did: decisions applied in this chat since its message was sent; questions open or waiting at the end of the turn that weren't open or waiting when it began, plus every open item when the agent called `list_questions` in the turn; the posted trial balance only when the turn's posting wrote something (`batch_id` not None) or the agent called `get_trial_balance`.
- Cards show each question's current record, read by id. Reopening a chat never adds questions raised elsewhere.
- Chats saved before this change (no turn records) show their messages without cards. No migration.
- The suggested prompts stay exactly: "Review the documents I'm adding", "What needs my attention?", "Show the trial balance".
- Copy is plain British English: £ with two decimals, dates like "9 Oct 2026", no markdown in agent text.
- A chat never sees another chat's conversation.

## Review Focus

- **A turn that ends with no assistant text** (model unavailable, failed, or stopped before the model replied) but whose files raised questions: on reload its result appears as an assistant entry with no text, not lost. Test: Task 1, `test_a_turn_with_no_reply_keeps_its_result`.
- **A question settled after its reply was written** (answered later, or resolved by a document in another chat): the old reply's card shows it answered or resolved, with no controls. Tests: Task 1, `test_a_card_shows_the_question_as_it_stands_now`; Task 4, `questionState` cases.
- **One question shown twice in a chat** (raised in a review, then listed by "What needs my attention?"): answering either card updates both. Test: Task 4, `withQuestion updates every card for the question`.
- **A chat saved before this change**, with the old `summary` field and no `turns`: it loads, shows its messages, and shows no cards. Test: Task 1, `test_a_chat_from_before_this_change_shows_its_messages_without_cards`.
- **The Overview's link opened in development** (React runs effects twice) or reloaded: "What needs my attention?" is sent once, and a reload doesn't send it again. Checked in Task 6's browser step: one person message only, and the `ask` parameter is gone from the address after sending.

---

### Task 1: A turn's result, kept with its reply

**Files:**
- Modify: `ledgersync/agent/chat.py` (models at 52-77; `_messages` 156-168; `_say` 186-190; `detail` 292-301; `turn` 337-358; `_read_all` 360-374; module docstring 1-8)
- Modify: `ledgersync/agent/run.py` (`ChatEvent` 28-40; `stream_turn` 66-113)
- Modify: `ledgersync/records.py` (`_KEPT_APART` 23; new turn functions after 169-176)
- Modify: `server.py` (messages route docstring 459-479)
- Test: `tests/test_chat_api.py`, `tests/test_live_agent.py` (update only; do not run it)

**Interfaces:**
- Consumes: `sorted_since(records, thread, since)`, `since_now(records, client_id)`, `records.questions(client_id, year_start)`, `records.question(id)`, `ledger_book.posted_trial_balance(...)`, `PostResult.batch_id`.
- Produces (in `ledgersync/agent/chat.py`):
  - `class FileRead(BaseModel): name: str; state: Literal["done", "failed"]; rows: Optional[int] = None; reason: Optional[str] = None`
  - `class TurnResult(BaseModel): sorted: list[Decision] = []; questions: list[Question] = []; trial_balance: Optional[PostedTrialBalance] = None; post: Optional[PostResult] = None`, with `def is_empty(self) -> bool` (no sorted, no questions, no trial balance, no post)
  - `class TurnRecord(BaseModel): message_id: str; files: list[FileRead] = []; result: TurnResult`
  - `class ChatMessage(BaseModel): role: Literal["user", "assistant"]; text: str; files: list[FileRead] = []; result: Optional[TurnResult] = None`
  - `class ThreadDetail(BaseModel): thread: ChatThread; messages: list[ChatMessage]` (no `summary`)
  - `def _say(agent, thread_id: str, text: str, *, message_id: Optional[str] = None, note: bool = False) -> None` (a note is written as `HumanMessage(text, id=..., additional_kwargs={"note": True})`)
- Produces (in `ledgersync/agent/run.py`): `ChatEvent.type` is `Literal["status", "step", "token", "result", "error", "done"]`; `def stream_turn(agent, ctx: ChatContext, text: str, *, message_id: Optional[str] = None, called: Optional[set[str]] = None) -> Iterator[ChatEvent]` (the person's message is `HumanMessage(content=text, id=message_id)`; each tool name seen in the `updates` stream, from the `ToolMessage.name` under node `"tools"`, is added to `called`).
- Produces (in `ledgersync/records.py`): `def add_turn(self, thread_id: str, turn: dict) -> None` (`$push` onto `turns`), `def turns(self, thread_id: str) -> list[dict]`; `_KEPT_APART` gains `"turns"` and keeps `"summary"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_chat_api.py`. Replace `summary_of` with `result_of` (the one `result` event) and use it wherever `summary_of` was used; `net(found, code)` keeps working on any dict with `trial_balance`.

```python
def result_of(events) -> dict:
    [result] = [data for kind, data in events if kind == "result"]
    return result

EMPTY = {"sorted": [], "questions": [], "trial_balance": None, "post": None}

def test_message_streams_steps_then_result_then_done(make, client_id):
    # as test_message_streams_steps_then_summary_then_done, with:
    assert kinds[0] == "status" and kinds[-2:] == ["result", "done"]
    assert max(k for k, kind in enumerate(kinds) if kind == "step") < kinds.index("token") < kinds.index("result")

def test_a_review_result_holds_its_questions_and_posting(make, client_id):
    # STATEMENT read; say("One payment needs its invoice.")
    assert [(q["kind"], q["status"]) for q in result["questions"]] == [("receipt_or_invoice", "open")]
    assert result["questions"][0]["text"] == "Can you upload the receipt or invoice?"
    assert [(s["gross"], s["needs"]) for s in result["trial_balance"]["suspense"]] == [("240.00", "receipt_or_invoice")]
    assert net(result, "9998") == "240.00" and result["post"]["batch_id"] and result["sorted"] == []

def test_a_plain_message_after_a_review_has_an_empty_result(make, client_id):
    # make(say("One payment needs its invoice."), say("You're welcome.")); review STATEMENT, then "Thanks."
    assert result_of(send(api, thread["id"], "Thanks.")) == EMPTY

def test_listing_the_open_items_shows_them_as_cards(make, client_id):
    # make(say("One payment needs its invoice."), call("list_questions"), say("One thing needs you."))
    first = result_of(send(api, thread["id"], "Review October.", STATEMENT))
    listed = result_of(send(api, thread["id"], "What needs my attention?"))
    assert [q["id"] for q in listed["questions"]] == [q["id"] for q in first["questions"]]
    assert listed["trial_balance"] is None and listed["sorted"] == []

def test_fetching_the_trial_balance_shows_it(make, client_id):
    # make(say("Hi."), call("get_trial_balance"), say("Here it is.")); send "Hello" first, so that turn's
    # posting is done and the second turn has nothing new to post
    shown = result_of(send(api, thread["id"], "Show the trial balance"))
    assert shown["trial_balance"]["is_balanced"] and shown["post"] is None and shown["questions"] == []

def test_a_new_chat_does_not_bring_up_earlier_items(make, client_id):
    # make(say("One payment needs its invoice."), say("Hello.")); chat A reviews STATEMENT (a question is raised),
    # then a new chat B on the same client sends "Hello"
    assert result_of(send(api, b["id"], "Hello")) == EMPTY

def test_reload_keeps_each_reply_with_its_result(make, client_id):
    # review STATEMENT ("One payment needs its invoice."), then "Thanks." ("You're welcome.")
    messages = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"]
    assert [(m["role"], m["text"]) for m in messages] == [
        ("user", "Review October."), ("assistant", "One payment needs its invoice."),
        ("user", "Thanks."), ("assistant", "You're welcome.")]
    assert messages[0]["files"] == [{"name": "barclays-october.csv", "state": "done", "rows": 1, "reason": None}]
    assert [q["kind"] for q in messages[1]["result"]["questions"]] == ["receipt_or_invoice"]
    assert messages[2]["files"] == [] and messages[3]["result"] is None

def test_a_turn_with_no_reply_keeps_its_result(make, client_id):
    # model unavailable (no OpenRouter key), STATEMENT sent: the turn still reads, refreshes and posts
    messages = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"]
    assert [(m["role"], m["text"]) for m in messages] == [("user", "Review October."), ("assistant", "")]
    assert [q["kind"] for q in messages[1]["result"]["questions"]] == ["receipt_or_invoice"]

def test_a_card_shows_the_question_as_it_stands_now(make, client_id):
    # TAXI receipt raises the date question; answer {"kind": "date", "date": "2026-10-09"} through the route
    [card] = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"][1]["result"]["questions"]
    assert (card["status"], card["answer"]) == ("resolved", "9 Oct 2026")

def test_a_reply_never_gains_questions_from_another_chat(make, client_id):
    # make(say("One payment needs its invoice."), say("The taxi has no date."),
    #      reads=[transactions_json(PAYMENT), transactions_json(TAXI)])
    # chat A reviews STATEMENT (receipt question); chat B reviews TAXI_RECEIPT (date question)
    [card] = api.get(f"/api/chat/threads/{a['id']}").json()["messages"][1]["result"]["questions"]
    assert card["kind"] == "receipt_or_invoice"

def test_a_chat_from_before_this_change_shows_its_messages_without_cards(make, client_id, mongo_store):
    # seed: a thread document with an old "summary" field and no "turns", and a checkpoint with
    # HumanMessage("Hello") + AIMessage("Hi.") written as in test_a_tool_call_left_by_a_crash_is_closed_before_the_next_turn
    detail = api.get(f"/api/chat/threads/{thread['id']}").json()
    assert [(m["role"], m["text"], m["files"], m["result"]) for m in detail["messages"]] == [
        ("user", "Hello", [], None), ("assistant", "Hi.", [], None)]
```

Also change: `test_new_thread_belongs_to_client` expects `{"thread": thread, "messages": []}`; `test_without_the_openrouter_key_a_turn_says_the_model_is_unavailable` expects `kinds[-2:] == ["result", "done"]` and reads the suspense from `result_of`; `test_stop_ends_the_run_before_its_next_model_call` expects `["result", "done"]`; `test_thread_history_survives_restart` asserts the reloaded messages carry the same `result` as before the restart; `test_answer_date_returns_updated_summary` drops its `detail["summary"]` assertion (Task 2 rewrites the rest). In `tests/test_live_agent.py`, read `[result] = [data for kind, data in events if kind == "result"]` and assert `result["questions"] == []` and `result["trial_balance"]["is_balanced"] and result["trial_balance"]["suspense"] == []`.

- [ ] **Step 2: Run the tests to see them fail.** Run `.venv/bin/python -m pytest tests/test_chat_api.py -q`. Expected: FAIL (no `result` event; `ThreadDetail` still has `summary`).

- [ ] **Step 3: Implement.**
  - `stream_turn`: build the person's message with `id=message_id`; in the `updates` branch for node `"tools"`, add each `ToolMessage.name` to `called` when `called` is not None.
  - `_read_all(self, client, year_start, files, read: list[FileRead])`: append one `FileRead` per file as its final step is yielded (`done` with `rows`, or `failed` with `reason`).
  - `turn`: make `message_id = uuid4().hex`; take `before = {q.id for q in self.records.questions(client.id, thread.year_start)}` right after `since`; pass `message_id` to `stream_turn` (and to `_say` on the unavailable path) with a `called: set[str]`; after `_write`, build the result:

```python
open_now = self.records.questions(thread.client_id, thread.year_start)
raised = open_now if "list_questions" in called else [q for q in open_now if q.id not in before]
wrote = post.batch_id is not None
result = TurnResult(sorted=sorted_since(self.records, thread, since), questions=raised,
                    trial_balance=ledger_book.posted_trial_balance(...) if wrote or "get_trial_balance" in called else None,
                    post=post if wrote or post.problems else None)
```

    then `self.records.add_turn(thread.id, TurnRecord(message_id=message_id, files=read, result=result).model_dump(mode="json"))` and `yield ChatEvent("result", result.model_dump(mode="json"))`. The turn no longer calls `_summarised`.
  - `detail`: walk the checkpoint's messages in order. A `HumanMessage` whose `additional_kwargs` has `"note"` is skipped. Every other `HumanMessage` starts a turn: its `ChatMessage` takes the files of the turn record with that `message_id`. AI texts join into one assistant message per turn, as `_messages` does now. When a turn ends (at the next shown person message, or the end), its record's result goes on its last assistant message; if the turn has no assistant text and the result isn't empty, append `ChatMessage(role="assistant", text="", result=...)`. Before attaching, replace each question in the result with `self.records.question(q.id)` (drop any not found). A record whose message isn't in the memory is shown after the messages the same way. Empty results are attached as `None`.
  - Update the module docstring, `ChatEvent`'s docstring and the messages route docstring to say `result`.

- [ ] **Step 4: Run the tests.** Run `.venv/bin/python -m pytest tests/test_chat_api.py tests/test_agent.py -q`. Expected: PASS.

- [ ] **Step 5: Run the full suite.** Run `.venv/bin/python -m pytest -q`. Expected: PASS (llm tests deselected).

- [ ] **Step 6: Commit.**

```bash
git add ledgersync/agent/chat.py ledgersync/agent/run.py ledgersync/records.py server.py tests/test_chat_api.py tests/test_live_agent.py
git commit -m "feat: a chat reply carries only what its turn did, and keeps it"
```

### Task 2: Answering returns only its own effect

**Files:**
- Modify: `ledgersync/agent/chat.py` (`answer` 399-415, `document` 417-439; remove `ReviewSummary`, `summary()`, `_summarised`)
- Modify: `ledgersync/records.py` (remove `save_summary` and `summary`; keep `"summary"` in `_KEPT_APART`)
- Modify: `server.py` (imports at 19; answer and document routes 481-491)
- Test: `tests/test_chat_api.py`

**Interfaces:**
- Consumes: Task 1's `TurnResult` shape rules, `_say(..., note=True)`, `sorted_since`.
- Produces: `class AnswerResult(BaseModel): question: Question; sorted: list[Decision] = []; trial_balance: Optional[PostedTrialBalance] = None; post: Optional[PostResult] = None` in `ledgersync/agent/chat.py`; `Chat.answer(...) -> AnswerResult`; `Chat.document(...) -> AnswerResult`; both routes use `response_model=AnswerResult`.

- [ ] **Step 1: Write the failing tests** (rewrite the answer and document tests):

```python
def test_answer_date_returns_the_question_and_its_effect(make, client_id):
    answered = api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
                        json={"kind": "date", "date": "2026-10-09"}).json()
    assert (answered["question"]["status"], answered["question"]["answer"]) == ("resolved", "9 Oct 2026")
    assert [d["rule"] for d in answered["sorted"]] == ["R1 Date from the person"]
    assert answered["trial_balance"]["is_balanced"] and answered["post"]["batch_id"]
    assert set(answered) == {"question", "sorted", "trial_balance", "post"}

def test_the_answer_note_is_for_the_agent_not_the_history(make, client_id):
    # after the answer: the model's next call sees ("human", "Answered: When was this Leeds City Cabs taxi? → 9 Oct 2026")
    # (as test_the_next_turn_sees_the_answer), and the thread detail has no message with that text
    assert not any(m["text"].startswith("Answered:") for m in detail["messages"])

def test_upload_answer_moves_out_of_suspense(make, client_id):
    assert answered["question"]["status"] == "resolved"
    assert answered["trial_balance"]["suspense"] == [] and net(answered, "9998") == "0.00"

def test_upload_that_does_not_fit_says_why(...):  # parametrized as now
    assert answered["question"]["status"] == "open" and answered["question"]["why"] == expected_why
    assert answered["trial_balance"] is None or answered["trial_balance"]["suspense"][0]["gross"] == "240.00"

def test_no_document_leaves_the_question_waiting(make, client_id):
    answered = api.post(..., json={"kind": "no_document"}).json()
    assert (answered["question"]["status"], answered["question"]["answer"]) == ("waiting", "I don't have it")
```

Also update `test_questions_survive_restart` (the answer response's `question` is resolved, `trial_balance.suspense == []`, `post.reversals_added > 0`), `test_an_answer_waits_for_the_message_running_on_its_chat` (`answered[0].json()["question"]["status"] == "waiting"`), and `test_client_routes_list_questions_decisions_and_posted_trial_balance` / `test_posted_trial_balance_reports_unposted_changes` (questions from `result_of`).

- [ ] **Step 2: Run the tests to see them fail.** Run `.venv/bin/python -m pytest tests/test_chat_api.py -q`. Expected: FAIL (routes still return `ReviewSummary`).

- [ ] **Step 3: Implement.** `answer`: write the "Answered: …" note with `_say(..., note=True)`; return `AnswerResult(question=self.records.question(question_id), sorted=sorted_since(self.records, thread, since), trial_balance=<posted TB> if answered.post.batch_id is not None else None, post=answered.post if answered.post.batch_id is not None or answered.post.problems else None)`. `document`: the same, with the post from `_write`, after the mismatch `why` is set. Remove `ReviewSummary`, `summary()`, `_summarised`, `records.save_summary` and `records.summary`.

- [ ] **Step 4: Run the tests.** Run `.venv/bin/python -m pytest tests/test_chat_api.py -q`, then `.venv/bin/python -m pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add ledgersync/agent/chat.py ledgersync/records.py server.py tests/test_chat_api.py
git commit -m "feat: answering a card returns that question and its own effect"
```

### Task 3: The agent no longer brings up earlier items

**Files:**
- Modify: `ledgersync/agent/prompt.py` (line 13; lines 45-47)
- Modify: `ledgersync/agent/tools.py` (`ask_user` docstring 316-318 only: the spec allows no other tool change)
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: Task 1's rule that `list_questions` and `get_trial_balance` calls put cards in the reply.
- Produces: no code interfaces.

- [ ] **Step 1: Write the failing test** in `tests/test_agent.py`:

```python
def test_the_prompt_answers_what_was_asked():
    assert "earlier chats" not in SYSTEM_PROMPT
    assert "When the person asks what needs their attention, call list_questions." in SYSTEM_PROMPT
    assert "adds a card for each thing this turn sorted, raised or posted" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run it to see it fail.** Run `.venv/bin/python -m pytest tests/test_agent.py::test_the_prompt_answers_what_was_asked -q`. Expected: FAIL.

- [ ] **Step 3: Edit the prompt and docstrings.**
  - Delete line 13 ("At the start of a chat, call list_questions and mention anything still open from earlier chats.").
  - In "How you work", add: "- When the person asks what needs their attention, call list_questions. The system shows the open items as cards."
  - Replace the Finishing lines with: "- The system posts the books and adds a card for each thing this turn sorted, raised or posted. Finish with two or three plain sentences about what you did in this turn. Don't list the cards' contents again, and don't use markdown."
  - `ask_user`: "It is shown as a card in this reply, and stays open on the client until it is answered."

- [ ] **Step 4: Run the tests.** Run `.venv/bin/python -m pytest tests/test_agent.py -q`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add ledgersync/agent/prompt.py ledgersync/agent/tools.py tests/test_agent.py
git commit -m "feat: the agent answers what was asked and lists open items only on request"
```

### Task 4: The chat library speaks results

**Files:**
- Modify: `frontend/src/lib/chat.ts` (types 85-103 and 120-130; `answerQuestion`/`uploadForQuestion` 274-282)
- Test: `frontend/src/lib/chat.test.ts`

**Interfaces:**
- Consumes: Tasks 1-2's JSON shapes.
- Produces (exported from `frontend/src/lib/chat.ts`):
  - `interface FileRead { name: string; state: 'done' | 'failed'; rows: number | null; reason: string | null }`
  - `interface TurnResult { sorted: Decision[]; questions: Question[]; trial_balance: PostedTrialBalance | null; post: PostResult | null }`
  - `interface AnswerResult { question: Question; sorted: Decision[]; trial_balance: PostedTrialBalance | null; post: PostResult | null }`
  - `interface ChatMessage { role: 'user' | 'assistant'; text: string; files: FileRead[]; result: TurnResult | null }`; `interface ThreadDetail { thread: ChatThread; messages: ChatMessage[] }`
  - `ChatEvent` has `{ type: 'result'; data: TurnResult }` in place of `summary`; `EVENT_TYPES` likewise
  - `answerQuestion(...): Promise<AnswerResult>`; `uploadForQuestion(...): Promise<AnswerResult>`
  - `function hasResult(r: TurnResult | null): r is TurnResult` (true when any of sorted, questions, trial_balance, post is present)
  - `function withQuestion<T extends { result: TurnResult | null }>(items: T[], q: Question): T[]` (every question with `q.id` in every item's result becomes `q`)
  - `function questionState(q: Question): string | null`
  - `function effectLine(a: AnswerResult): string | null`
  - `function readStatus(f: FileRead): { state: FileState; label: string }` (same labels as `fileStatus`)
  - `ReviewSummary` is removed.

- [ ] **Step 1: Write the failing tests** in `frontend/src/lib/chat.test.ts` (update `summaryJson` to a `TurnResult`/`AnswerResult` fixture and the `event: summary` test to `event: result`):

```ts
test('withQuestion updates every card for the question', () => {
  const card = question('date'), answered = { ...card, status: 'resolved' as const, answer: '9 Oct 2026' }
  const result = { sorted: [], questions: [card], trial_balance: null, post: null }
  const items = [{ result }, { result: null }, { result: { ...result } }]
  const next = withQuestion(items, answered)
  assert.deepEqual([next[0].result?.questions[0].status, next[1].result, next[2].result?.questions[0].answer],
                   ['resolved', null, '9 Oct 2026'])
})

test('a question says where it stands', () => {
  assert.equal(questionState(question('date')), null)
  assert.equal(questionState({ ...question('date'), status: 'resolved', answer: '9 Oct 2026' }), 'Answered: 9 Oct 2026')
  assert.equal(questionState({ ...question('receipt_or_invoice'), status: 'resolved', answer: null }), 'Resolved')
  assert.equal(questionState({ ...question('receipt_or_invoice'), status: 'waiting', answer: "I don't have it" }),
               'Waiting for the receipt or invoice')
  assert.equal(questionState({ ...question('vat_invoice'), status: 'waiting', answer: "I don't have it" }),
               'Waiting for the VAT invoice')
  assert.equal(questionState({ ...question('date'), status: 'waiting', answer: 'Not sure' }), 'Waiting: not sure of the date yet')
})

test("an answer's effect is one line", () => {
  const tb = (n: number) => ({ is_balanced: true, suspense: Array(n).fill({}) }) as unknown as PostedTrialBalance
  const a = (over: Partial<AnswerResult>): AnswerResult => ({ question: question('date'), sorted: [], trial_balance: null, post: null, ...over })
  assert.equal(effectLine(a({})), null)
  assert.equal(effectLine(a({ trial_balance: tb(0) })), 'Posted · balanced · nothing in Suspense')
  assert.equal(effectLine(a({ trial_balance: tb(1) })), 'Posted · balanced · 1 item in Suspense')
  assert.equal(effectLine(a({ post: { problems: ['Row 3 has no date.'] } as PostResult })), 'Nothing was posted: Row 3 has no date.')
})

test('hasResult and readStatus', () => {
  assert.equal(hasResult({ sorted: [], questions: [], trial_balance: null, post: null }), false)
  assert.equal(hasResult({ sorted: [decision('R1')], questions: [], trial_balance: null, post: null }), true)
  assert.deepEqual(readStatus({ name: 'a.csv', state: 'done', rows: 9, reason: null }), { state: 'done', label: 'Read (9 rows)' })
  assert.deepEqual(readStatus({ name: 'b.png', state: 'failed', rows: null, reason: 'Unreadable.' }), { state: 'failed', label: 'Failed: Unreadable.' })
})
```

Update `an answer is posted as JSON with the header and returns the new summary` to assert the `AnswerResult` it returns (`answered.question.id === 'q1'`).

- [ ] **Step 2: Run them to see them fail.** Run `cd frontend && npm test`. Expected: FAIL (functions not exported).

- [ ] **Step 3: Implement** the types, event list, return types and helpers in `frontend/src/lib/chat.ts`. `questionState`: `open` → `null`; `resolved` with an answer → `Answered: <answer>`, without → `Resolved`; `waiting` with "I don't have it" → `Waiting for the receipt or invoice` / `Waiting for the VAT invoice` by kind; `waiting` with "Not sure" → `Waiting: not sure of the date yet`; any other waiting answer → `Waiting: <answer>`. `effectLine`: post problems first (`Nothing was posted: ` + problems joined by a space); else a trial balance → `Posted · balanced|not balanced · nothing in Suspense|1 item in Suspense|N items in Suspense`; else `null`.

- [ ] **Step 4: Run the tests.** Run `cd frontend && npm test`. Expected: PASS. (`tsc` will fail until Task 5 updates the page; that is expected at this step.)

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/chat.ts frontend/src/lib/chat.test.ts
git commit -m "feat: the chat library reads a reply's result and an answer's effect"
```

### Task 5: Each reply shows its own cards

**Files:**
- Create: `frontend/src/components/chat/ReplyResult.tsx`
- Delete: `frontend/src/components/chat/ReviewSummary.tsx`
- Modify: `frontend/src/components/chat/QuestionCard.tsx` (props 4-43; render 45-82)
- Modify: `frontend/src/app/chat/[threadId]/page.tsx` (imports 1-21; `Turn` 23-34; state 36-54; `load` 56-79; `send` 86-122; render 153-226)

**Interfaces:**
- Consumes: Task 4's `TurnResult`, `AnswerResult`, `hasResult`, `withQuestion`, `questionState`, `effectLine`, `readStatus`.
- Produces: `export default function ReplyResult({ result, threadId, onAnswered, onSay }: { result: TurnResult; threadId: string; onAnswered: (a: AnswerResult) => void; onSay: (text: string) => void })`; `QuestionCard` props `{ question: Question; number: number; threadId: string; onAnswered: (a: AnswerResult) => void; onSay: (text: string) => void }`.

- [ ] **Step 1: Build `ReplyResult`.** It renders, in order and each only when present: Sorted (the `DecisionLine` list, heading "✓ Sorted"), Needs you (heading "Needs you" with the count, one `QuestionCard` per question), the post problems notice ("Nothing was posted: …"), and Posted (`PostedTrialBalance`). Delete `ReviewSummary.tsx`.

- [ ] **Step 2: Update `QuestionCard`.** Show `questionState(question)` under the why (class `question-state`) when it isn't null. A resolved question shows no controls. A waiting question keeps its controls, so the document can still come. After a successful answer or upload, show `effectLine(result)` under the card (class `question-effect`) when it isn't null, and call `onAnswered(result)`.

- [ ] **Step 3: Update the thread page.**
  - `Turn` gains `result: TurnResult | null` (starts `null`); the `result` event sets it.
  - Remove the `summary` and `earlier` state, the `clientQuestions` call in `load`, the bottom `ReviewSummary`, and the "things still need you from earlier" block.
  - History: a person's message shows its text and its file chips from `m.files` (`readStatus`). An assistant message shows its text, then `ReplyResult` when `hasResult(m.result)`.
  - A live turn shows `ReplyResult` after its reply text when `hasResult(t.result)`.
  - `onAnswered = (a) => { setHistory(h => withQuestion(h, a.question)); setTurns(ts => withQuestion(ts, a.question)) }`.

- [ ] **Step 4: Run the checks.** Run `cd frontend && npm test && ./node_modules/.bin/tsc --noEmit -p .`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/components/chat/ReplyResult.tsx frontend/src/components/chat/ReviewSummary.tsx frontend/src/components/chat/QuestionCard.tsx "frontend/src/app/chat/[threadId]/page.tsx"
git commit -m "feat: each chat reply shows its own cards, and a new chat starts empty"
```

### Task 6: The Overview's link asks what needs you

**Files:**
- Modify: `frontend/src/lib/chat.ts` (add `ATTENTION`, `attentionHref`)
- Modify: `frontend/src/components/OverviewSection.tsx` (24-36, 95-97)
- Modify: `frontend/src/app/chat/page.tsx` (13-49)
- Modify: `frontend/src/app/chat/[threadId]/page.tsx` (`SUGGESTIONS` at 21; `ask` handling)
- Test: `frontend/src/lib/chat.test.ts`

**Interfaces:**
- Consumes: Task 5's thread page `send(text, files, bankAccounts)`.
- Produces: `export const ATTENTION = 'What needs my attention?'`; `export const attentionHref = (clientId: number) => string` returning `/chat?client=<id>&ask=What%20needs%20my%20attention%3F`.

- [ ] **Step 1: Write the failing test.**

```ts
test('the Overview link starts a chat that asks what needs attention', () => {
  assert.equal(attentionHref(7), '/chat?client=7&ask=What%20needs%20my%20attention%3F')
})
```

- [ ] **Step 2: Run it to see it fail.** Run `cd frontend && npm test`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - `OverviewSection`: the "N things need you" link goes to `attentionHref(client.id)`; remove the `listThreads` call and `chatHref` state.
  - `app/chat/page.tsx`: read `client` and `ask` with `useSearchParams` (wrap the page body in `<Suspense>`). When `client` names one of the shell's clients, pick it once (a `useRef` guard), then go to `/chat/<id>?ask=<ask>`.
  - Thread page: `SUGGESTIONS` uses `ATTENTION`. Read `ask`; once the thread has loaded with no messages and no turns, send `ask` once (a `useRef` guard) and `router.replace('/chat/<id>')` so a reload doesn't send it again.

- [ ] **Step 4: Run the checks.** Run `cd frontend && npm test && ./node_modules/.bin/tsc --noEmit -p .`. Expected: PASS.

- [ ] **Step 5: Browser check (the controller runs it).** Use a server in demo mode with the scripted model and the Northbridge files read from their `.rows.json`, as in the Task 12 browser check. Check, at desktop and 375 px, with the console free of errors:
  - Ask something plain: the reply has no cards.
  - Review the October files: the reply has its cards. The next message's reply has none.
  - Reload: each reply keeps its cards.
  - Answer the taxi's date on the card: it collapses to "Answered: 9 Oct 2026" with the effect line, and nothing else changes.
  - A new chat on the client shows only the header, the suggestions and the message box.
  - "What needs my attention?" shows the open items as cards.
  - The Overview link: exactly one person message is sent, and the address loses `ask`.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/lib/chat.ts frontend/src/lib/chat.test.ts frontend/src/components/OverviewSection.tsx frontend/src/app/chat/page.tsx "frontend/src/app/chat/[threadId]/page.tsx"
git commit -m "feat: the Overview's link starts a chat that asks what needs you"
```
