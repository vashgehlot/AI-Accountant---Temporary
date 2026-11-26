# AI-first bookkeeping and client-query tools: how they decide auto-code vs escalate vs ask the client

Research date: 17 Nov 2026. Almost every number below comes from the vendor itself. Independent verification is noted where it exists, and it rarely does. Some pages (Botkeeper knowledge base, Uncat press release) could not be fetched directly (404/403). Claims from them come from search-result excerpts and are marked as such.

## Q1. How does each product decide confidence, and what happens below it? Published accuracy or review-share figures

### Takeaway
Nearly every product uses the same pattern. A per-transaction confidence score is checked against a threshold, which is usually 90-98%. Items above it auto-post or are bulk-approvable. Items below it go to an accountant review queue, not straight to the client. Asking the client is a separate step that the accountant triggers. Published accuracy figures (97-99%) and automation rates (85-95%) are all self-reported. Independent reviewers and practitioners put real-world accuracy lower (about 80-95%).

### Cited Findings

**Botkeeper**
- Current knowledge base (seen in search excerpt, page not fetched) lists three confidence bands: high (98%+), medium (90-97.9%) and low (0-89.9%). All three are auto-categorised and pushed to the GL. Medium and low items appear in a "Needs Review" tab. Firms can choose, per client, to have the Botkeeper team review low-confidence items before they reach the GL. — [Botkeeper KB: Confidence rating](https://botkeeper.com/en/knowledge/confidence-rating) (via search excerpt; direct fetch returned 404)
- An older Botkeeper blog said the team reviews anything below 97% confidence. The threshold appears to have changed over time. — [Botkeeper blog: Transaction Manager](https://www.botkeeper.com/blog/botkeeper-introduces-the-new-transaction-manager-tool)
- The glossary says exceptions come from low confidence, missing data or "a break from learned patterns", and that review trains the system. — [Botkeeper glossary](https://www.botkeeper.com/en/knowledge/glossary-how-to-speak-botkeeper)
- Botkeeper claims 98% accuracy on AI-posted entries and more than 14 million transactions classified (vendor claim). — [Botkeeper blog](https://www.botkeeper.com/blog/8-ways-ai-bookkeeping-cuts-errors-and-data-entry)

**Docyt**
- "By default, anything under 90% confidence gets routed to your 'Accountant Review' queue." Firms can raise it (e.g. 95% for high-volume practices) or lower it (e.g. 85% for a solo practitioner). Confidence scores apply to "every categorization, every reconciliation match, every anomaly alert." — [Docyt: How to trust your AI](https://www.docyt.com/article/how-to-trust-your-ai-without-losing-your-mind/)
- The ERP page says the categorisation agent "only posts what it is sure of". Finance teams can set which accounts an agent may post to, the confidence it needs, and "what always goes to a human". — [Docyt AI-native ERP](https://www.docyt.com/docyt-ai-elevating-accounting-to-real-time-visibility-precision/)
- A "Wait For Approval Before Categorization" setting holds AI suggestions as "Pending Review" before they post. Items with no suggestion show as awaiting categorisation. — [Docyt Help Center](https://pages.docyt.com/knowledge/wait-for-approval-before-categorization)
- Docyt tracks verification outcomes "per workflow and per customer" to tune thresholds. — [Docyt AI agents](https://www.docyt.com/docyt-ai-agents-hpai/)

**Digits (Autonomous General Ledger, Accounting Agents)**
- In June 2025 Digits claimed its agents automate 95% of the bookkeeping workflow. In its own test against staff from 12 outsourcing firms, the AI was about 98% accurate and the humans about 80%. Accounting Today noted the test set had "fewer edge cases and more repeat types" than typical data. Items the AI is unsure about go to an inbox for human categorisation. Accruals and project accounting still need humans. — [Accounting Today, 25 Jun 2025](https://www.accountingtoday.com/news/digits-says-its-new-ai-agents-can-automate-95-of-bookkeeping-tasks)
- Digits also cites 97.8% categorisation accuracy against GAAP-accountant-reviewed ground truth, and "auto booking 93% of all transactions" on other pages. The figures are inconsistent and self-reported. — [CPA Practice Advisor, Mar 2025](https://www.cpapracticeadvisor.com/2025/03/11/digits-autonomous-general-ledger-will-take-on-quickbooks-company-says/157183/); [Digits: Introducing accounting agents](https://digits.com/blog/introducing-digits-accounting-agents/)
- CEO claim that the agents "never hallucinate" because LLMs only orchestrate and predictive models (18 mostly custom models) make the decisions. This is marketing. — [Accounting Today](https://www.accountingtoday.com/news/digits-says-its-new-ai-agents-can-automate-95-of-bookkeeping-tasks)
- Quality Control runs automated checks (missing fields, miscoding, duplicates, unusual activity, vendor changes) and surfaces them as checklist action items. Firms can write custom checks in plain English. — [Digits help: Quality control](https://help.digits.com/firms-home/quality-control)

**Vic.ai (AP invoices)**
- "Autopilot" means every invoice field is predicted with >95% confidence. Firms choose what Autopilot does: show an icon only, start the approval flow, or AutoPost. AutoPost happens only if every line matches with no deviation outside tolerance. Duplicates and other errors block posting. These configurations are changed through Vic.ai staff. — [Vic.ai Help: Autopilot](https://help.vic.ai/en/articles/5071874-autopilot)
- Vic.ai's FAQ says firms define confidence thresholds and decide whether to enable Autopilot. — [Vic.ai FAQ](https://www.vic.ai/faq)
- Vendor claims of 97-99% coding accuracy and an "85% no-touch rate by month 6" (other pages say 70% Autopilot within six months). — [Vic.ai news](https://www.vic.ai/news/vic-ai-raises-the-bar-in-artificial-intelligence-for-enterprise-finance-and-accounting-with-up-to-99-accuracy); [Why Vic.ai](https://vic.ai/why-vic-ai)
- A third-party review says 5-20% of invoices fall below threshold and go to humans, and a maturing deployment realistically lands at 85-95% coding accuracy. — [procurement-ai-agents review](https://procurement-ai-agents.pages.dev/blog/vic-ai-review-autonomous-invoice-processing)

**Booke.ai**
- The QBO page says it "brings low-confidence transactions to your team for review", offers suggestions on unclear items, and "uses each approval and correction to improve future categorizations". It claims "80% faster" categorisation but publishes no accuracy rate. — [Booke: QuickBooks Online](https://booke.ai/quickbooks-online)
- A search excerpt attributed a "below 90%" human-input threshold to Booke's listing. The fetched QBO page did not state it, so treat it as unverified. — [Booke: QuickBooks Online](https://booke.ai/quickbooks-online)

**Puzzle**
- Accuracy Review attaches a "reasoning trail" to each AI-categorised transaction and flags uncertain entries for review before close. Reviewers can bulk-approve, filter by confidence level and retrain from corrections. Every change is logged with a timestamp. Puzzle says partner firms process 98% of transactions automatically, and that 85-90% automated categorisation should be expected. — [Puzzle: AI accounting accuracy reviews](https://puzzle.io/blog/ai-accounting-accuracy-reviews)
- The feature is limited to the "Accounting + Advanced Automation" plan and above. A statement-level accuracy review was in alpha. — [Puzzle: AI accuracy review for accountants](https://puzzle.io/blog/ai-accuracy-review-for-accountants)

**Truewind**
- Each classification gets a confidence score and a short rationale. High-confidence items go to bulk approval. Low-confidence items go to a reviewer queue before posting (to Sage Intacct). The CEO says the loop cannot be fully closed without people. — [Truewind: transaction classification](https://truewind.ai/platform/transaction-classification); [Sacra interview](https://sacra.com/research/alex-lee-truewind-data-tech-enabled-bookkeeping/)

**Zeni**
- High-confidence transactions are auto-categorised and the rest wait in a review queue. Zeni says AI should get "at least 90%" right on its own and that "250+ Zeni experts" review the AI's work. — [Zeni for bookkeepers](https://www.zeni.ai/for/bookkeepers); [Zeni: best AI accounting software](https://www.zeni.ai/blog/best-ai-accounting-software)

**Pilot**
- The AI Accountant categorises and reconciles, flags uncertain items, and "occasionally" asks the customer to confirm a categorisation. An AI-only tier (reported from $99/month) has no human review. A critical forum post questions this. — [Pilot AI Accountant](https://pilot.com/platform/ai-accountant); [beancount.io forum](https://beancount.io/forum/t/pilot-just-launched-a-fully-autonomous-ai-accountant-is-this-the-end-of-bookkeeping-or-the-beginning-of-a-new-kind-of-risk/3666)

**Basis**
- Basis is an agent platform for CPA firms that works "somewhat like a junior accountant", with staff reviewing its output. It raised a $34M Series A (Dec 2024) and a $100M Series B at a $1.15B valuation (Feb 2026). It claims 20-50% efficiency gains, and Wiss reported up to 30% time savings. No public confidence or escalation mechanics were found. — [Accounting Today: Series A](https://www.accountingtoday.com/news/major-ai-players-back-basis-with-34-million-series-a); [SiliconANGLE, Feb 2026](https://siliconangle.com/2026/02/24/ai-accounting-startup-basis-secures-100m-1-15b-valuation-firms-adopt-agent-based-workflows/)

**Dext AI Assist (UK-relevant)**
- AI Assist only *suggests* rules (covering supplier, document type, keywords, delivery address, tax calculation), each with a plain-English explanation. The accountant must approve, adjust or discard each one before it applies. Guidance overrides supplier rules. Dext recommends starting with manual review before switching to auto-apply. It covers the Costs and Sales spaces only. — [Dext: Getting started with AI Assist](https://dext.com/en/blog/single/getting-started-with-dext-ai-assist-a-practical-guide); [Dext AI Assist product page](https://dext.com/uk/partner/product/dext-ai-assist-bookkeeping-agent)
- Dext claims >99% capture accuracy. A G2 reviewer says AI suggestions are "sometimes inaccurate". — [Dext blog](https://dext.com/en/blog/single/ai-assist-automate-document-categorisation-in-dext); [G2 Dext reviews](https://www.g2.com/products/Dext/reviews)

**Ledge**
- Ledge is reconciliation and close software, not bookkeeping. Unmatched items go to a structured exception workflow with an assigned owner rather than being force-matched. — [Ledge: best reconciliation software](https://www.ledge.co/content/best-reconciliation-software)

**Acting Office (UK)**
- AI is branded "AccaBot" (bookkeeping and bank reconciliation). Client queries are logged, tracked and traceable, with partner sign-off. Claims a 32% faster month-end close (vendor, anonymous testimonial). No confidence or escalation mechanics are published. — [AccountingWEB sponsored: AccaBot](https://www.accountingweb.co.uk/community/industry-insights/acting-office-is-transforming-accounting-and-bookkeeping-with-accabot); [ICAEW sponsored content](https://www.icaew.com/insights/sponsored-content/acting-office-defining-the-new-standard-of-fully-integrated-practice)

**Bench (shutdown and acquisition)**
- Bench shut down abruptly on 27 Dec 2024 and locked customers out. Employer.com announced it would acquire Bench on 30 Dec 2024. Digits reports the deal closed on 6 Jan 2025. Bench had over 600 staff, and only some were invited back. Customers had to consent to data transfer. — [GeekWire](https://www.geekwire.com/2024/bench-accounting-to-be-acquired-by-employer-com-following-abrupt-shutdown/); [Accounting Today](https://accountingtoday.com/news/bench-acquired-by-employer-com-after-sudden-shutdown); [Digits: Bench fallout](https://digits.com/blog/bench-fallout/); [American Banker](https://www.americanbanker.com/news/why-employer-com-bought-fintech-bench-days-after-it-shut-down)

**Cross-market estimate**
- A third-party guide estimates categorisation accuracy ranges from about 80% (standard platforms such as Xero JAX) to 97% (specialist tools), with 3-20% of transactions still needing human review. — [beancount.io 2026 guide](https://beancount.io/blog/2026/07/15/ai-bookkeeping-software-2026-docyt-zeni-rillet-guide)

### Inferences
- The common design has three outcomes: auto-post, accountant queue, and client question. The confidence threshold only decides between the first two. Asking the client is almost always a separate decision made by the accountant (or by a rule, as with uncategorised accounts), not an automatic result of low confidence.
- The defaults cluster around 90% (Docyt, Zeni, Booke if the excerpt is right, Botkeeper's medium band) and 95-98% (Vic.ai, Botkeeper high band). Thresholds are usually configurable per firm or client, and sometimes only by the vendor's staff (Vic.ai).
- There are two models: "post then review" (Botkeeper posts all bands to the GL and queues medium/low) and "hold until approved" (Docyt's wait-for-approval setting, Dext AI Assist, Truewind, Puzzle governed automation). The choice affects audit trail and how errors reach the reports.

### Gaps
- No independent audit of any vendor's accuracy or automation rate was found.
- Fyle: no sources found on its escalation and policy-violation thresholds.
- Fluidly: it is a cash-flow forecasting tool, not a categorisation tool ([Slashdot listing](https://slashdot.org/software/comparison/Fluidly-vs-LedgerSync/)). Nothing relevant was found on escalation.
- Basis and Acting Office do not publish confidence or escalation mechanics.
- Botkeeper's current KB page could not be fetched, so its band thresholds rely on a search excerpt.

## Q2. Materiality or "don't ask me below £x" settings, and ranking review items by monetary impact or risk

### Takeaway
I found no product that publicly documents a materiality setting ("don't escalate or ask below £x") or a review queue ranked by monetary impact. The controls on offer are confidence thresholds, account-level restrictions (Docyt), custom plain-English checks (Digits), and flags for large transactions (Client Hub). Dollar thresholds and risk tiers show up only in practitioner advice. This looks like a real gap in the market.

### Cited Findings
- Docyt lets teams set which accounts an agent may post to and "what always goes to a human". This is account-based, not amount-based. — [Docyt AI-native ERP](https://www.docyt.com/docyt-ai-elevating-accounting-to-real-time-visibility-precision/)
- Digits custom quality checks are written in plain English, so an amount rule could be expressed this way. No built-in dollar-weighted ordering is documented. — [Digits help: Quality control](https://help.digits.com/firms-home/quality-control)
- Client Hub (Xero/QBO app) surfaces "large transactions" alongside missing payees and attachments in one queue. No configurable threshold is documented. — [Xero App Store UK: Client Hub](https://apps.xero.com/uk/function/accountant-tools-extras/app/client-hub)
- Xenett advertises "50+ accuracy checks, AI accruals and anomaly detection", and its blog recommends human approval for high-risk accounts (payroll, revenue, tax, related party, accruals). No documented impact ranking. — [Xenett: AI in accounting](https://www.xenett.com/blog/ai-in-accounting)
- Double (formerly Keeper) file review compares each current-period expense with the past year's transactions and flags anomalies. This is pattern-based, not amount-ranked. — [Double/Keeper G2](https://www.g2.com/products/double-formerly-keeper); [Double: File Reviews](https://doublehq.com/?p=74)
- Puzzle filters review by confidence level only. No filter by amount or impact is mentioned. — [Puzzle: AI accounting accuracy reviews](https://puzzle.io/blog/ai-accounting-accuracy-reviews)
- Vic.ai Autopilot uses tolerances on PO mismatches, which acts like a per-line materiality setting for AP matching. — [Vic.ai Help: Autopilot](https://help.vic.ai/en/articles/5071874-autopilot)
- Practitioner advice: set a dollar threshold for second review, often $500-$2,500 for small businesses, with $2,500 a common rule of thumb for capitalisation. Revisit it each quarter ("If the queue was empty every week, the threshold is too high"). — [beancount.io: controls, approval limits](https://beancount.io/blog/2026/08/31/ai-finance-automation-controls-approval-limits-source-documents-audit-trail)
- A $200 transaction can still be high-risk if it touches payroll tax, a restricted fund, a related party or a customer deposit. So risk tiers by account type matter alongside amount. — [beancount.io guide](https://beancount.io/blog/2026/08/31/ai-finance-automation-controls-approval-limits-source-documents-audit-trail)
- Gartner warns that materiality thresholds streamline processes but "can hide small leakages and breaches that accumulate over time". Practitioners respond by sampling below the threshold (spot-checking 10-15% a month). — [Gartner abstract](https://www.gartner.com/en/documents/8238493); [beancount.io forum](https://beancount.io/forum/t/the-human-in-the-loop-sweet-spot-what-i-automate-fully-vs-what-i-review-manually-in-my-beancount-workflow/1579)
- One practitioner orders review by lowest confidence first. Another always reviews items over $5,000, fixed assets, owner draws and intercompany transfers manually. — [beancount.io forum](https://beancount.io/forum/t/ai-bookkeeping-tools-promise-98-accuracy-but-the-2-errors-compound-into-tax-penalties-how-do-you-validate-ai-categorization-at-scale/4031)

### Inferences
- A per-client materiality setting, combined with a queue ranked by amount and account-risk tier (plus sampling below the threshold), would set a product apart. None of the products found documents this.
- Vendors seem to prefer confidence over amount because confidence is model-native. Accountants' own heuristics are amount- and account-type-driven.

### Gaps
- No vendor docs found for "don't ask below £x" settings. They may exist in unpublished settings. Demos or help-centre access would confirm.
- No evidence any product infers materiality from client size or turnover.

## Q3. How they learn from corrections (per client vs across clients)

### Takeaway
Every vendor says corrections retrain the model. Few say whether learning is per client or shared across clients. Docyt (overnight, tuned per customer and per workflow) and Dext (per-practice patterns applied across the client base, with approval) are the most specific. Xero's bank-rule ML learns from accountant corrections at very large scale.

### Cited Findings
- Docyt: "Every time you correct something in that review queue, Docyt's AI learns from it". Learning happens overnight. Thresholds are tuned per workflow and per customer. — [Docyt: How to trust your AI](https://www.docyt.com/article/how-to-trust-your-ai-without-losing-your-mind/); [Docyt AI agents](https://www.docyt.com/docyt-ai-agents-hpai/)
- Botkeeper: reviewer corrections "teach our machines", and review trains the system over time. — [Botkeeper glossary](https://www.botkeeper.com/en/knowledge/glossary-how-to-speak-botkeeper)
- Booke: "Uses each approval and correction to improve future categorizations". No timeline or scope given. — [Booke: QuickBooks Online](https://booke.ai/quickbooks-online)
- Puzzle: reviewers can retrain the system from corrections. Scope (per client vs global) is not stated. — [Puzzle](https://puzzle.io/blog/ai-accounting-accuracy-reviews)
- Dext AI Assist learns how a practice handles suppliers and tax codes. It proposes rules "across the client base", each explained, "none of them applied until your expertise says so". — [Dext AI Assist](https://dext.com/uk/partner/product/dext-ai-assist-bookkeeping-agent)
- Vic.ai learns and replicates "how your team codes invoices". — [Vic.ai autonomous invoice processing](https://vic.ai/products/autonomous-invoice-processing)
- Xero's coding ML learns from accountant corrections, with about 3m corrections entered monthly (older AccountingWEB article, likely pre-2023). — [AccountingWEB](https://www.accountingweb.co.uk/node/148724)
- Digits says it keeps teaching agents new skills, and that the remaining 5% (e.g. splits) is still on the roadmap. — [Accounting Today](https://www.accountingtoday.com/news/digits-says-its-new-ai-agents-can-automate-95-of-bookkeeping-tasks)

### Inferences
- The Dext pattern is attractive for practices. It turns repeated corrections into explicit, explainable, approvable rules rather than silent model drift, which also helps the audit trail.
- Silent retraining makes it hard for accountants to know why a coding changed. This feeds the "black box" criticism.

### Gaps
- No vendor documents whether a correction for one client affects another client's predictions (cross-client contamination risk).

## Q4. How client-query tools batch and send questions, chase responses and write answers back. Response rates and time saved

### Takeaway
Client-query tools work the same way. They pull uncategorised or flagged transactions from QBO/Xero, the accountant sends them in one send, the client answers in a mobile-friendly, often password-free portal (choosing an account, adding notes or attaching receipts), and automatic reminders go out on a per-client cadence. Answers are written back to the ledger, usually after the accountant approves. Published response rates exist only as vendor case studies.

### Cited Findings

**Digits Transaction Review**
- Digits pre-fills questions per transaction, and the accountant can edit them. Nothing is sent until the accountant clicks "Review & Send". The client gets an email and answers in a mobile-optimised portal. Reminders go out automatically, weekly or monthly, set per client. Once the accountant confirms a classification it is saved to QBO along with the client's Q&A. Items can be removed from review. — [Digits: Introducing Transaction Review](https://digits.com/blog/introducing-digits-transaction-review/); [Digits community: step-by-step](https://community.digits.com/accountants-and-bookkeepers-84/transaction-review-in-digits-step-by-step-instructions-402)

**Double (formerly Keeper)**
- Questions are asked straight from the bank feed. Edits after a client reply sync back to QBO/Xero. Reminders go by email or text. The Aug 2025 changelog sends clients "a single email each morning with all their unanswered questions", which is daily batching. — [Keeper changelog 21 Aug 2025](https://keeperapp.canny.io/changelog/august-21-2025); [G2: Double](https://www.g2.com/products/double-formerly-keeper)
- Case study: REI Bookkeepers gets about 1.5k client questions answered a month, with a 90% response rate within one week of launch, later 100%. Reminders went twice weekly until the client responded (vendor case study). — [Double case study](https://www.casestudies.com/company/doublehq/case-study/489c-rei-bookkeepers-gets-15k-client-questions-answered-per-month-using-doubles-client-portal)
- Another vendor case study: BSFS saves over 50 hours a month with file review tools. — [Double case study BSFS](https://doublehq.com/?p=330)

**Uncat**
- Syncs with QBO, QB Desktop and Xero. Automatically notifies clients about uncategorised transactions (email, optional SMS), collects answers and receipts, and syncs them back after the accountant categorises. — [BusinessWire 2023](https://www.businesswire.com/news/home/20230112005186/en/Uncat-Helps-Accountants-and-Bookkeepers-Fix-More-Than-450-Million-Dollars-in-Uncategorized-Transactions-With-Their-Small-Business-Clients) (via search excerpt; fetch returned 403)
- Stat: more than 175,000 transactions worth over $450M updated (Jan 2023, vendor). — same source
- Notification can be pointed at any ledger account, with cadence set per client (weekly, monthly, custom). The public board shows response tracking is shipped, while client-initiated transaction sends are still in progress. — [Zoftware overview](https://zoftwarehub.com/en-ae/products/uncat/overview); [Uncat feature board](https://uncat.featureupvote.com)
- It integrates with Karbon, syncing client activity into Karbon work items. — [Karbon integrations: Uncat](https://karbonhq.com/en-GB/integrations/uncat/)
- Pricing is inconsistent: about $9 per client per month on G2, $5 cited on Capterra. — [G2](https://www.g2.com/products/Uncat/reviews)

**Financial Cents ReCats**
- Pulls uncategorised transactions from QBO. Clients add notes and documents in a portal. Auto-reminders run at intervals the accountant sets. Bulk categorisation is available. Class, tax code and billable status can be set. Updated transactions, notes and documents are pushed back to QBO. Costs $4 per client per month. No amount filter is documented. — [Financial Cents ReCats FAQ](https://help.financial-cents.com/en/articles/9565816-recats-faq-s); [Financial Cents: Introducing ReCats](https://financial-cents.com/resources/articles/introducing-recats-manage-uncategorized-transactions/)

**Karbon Client Requests**
- These are generic client tasks, not transaction-native. Reminder cadence can be gentle, urgent (daily) or custom, and stops when all requests are completed. Requests can be resent, and staff can be notified if a client is not responding. Uncategorised transactions come through integrations such as Uncat. — [Karbon help: Send client requests](https://intercom.help/karbon/en/articles/1524688-send-client-requests); [Karbon help: client not responding](https://help.karbonhq.com/en/articles/4837165-can-i-be-notified-if-a-client-isn-t-responding-to-client-tasks)

**QuickBooks Online Accountant (native)**
- The Books review / Transaction review tab flags uncategorised transactions, missing payees and unapplied payments. The accountant sends questions, and the client gets an email and answers under "My accountant". Requests due in a future year do not appear in Books review. — [Intuit: Month-end reviews](https://quickbooks.intuit.com/learn-support/en-us/help-article/manage-client/month-end-reviews-finish-clients-open-tasks/L4GubaqKy_US_en_US)

**Client Hub (Xero/QBO app)**
- Scans Xero every 10 minutes and puts expense inconsistencies, missing payees, missing attachments and large transactions in one queue. Sends questions and transaction tasks with automatic reminders when responses are late. Clients answer from a dropdown of accounts or with free text. The first sync covers the last 90 days of Spend Money. — [Xero App Store UK: Client Hub](https://apps.xero.com/uk/function/accountant-tools-extras/app/client-hub); [Client Hub QBO integration](https://www.clienthub.app/blog/client-hub-integration-with-quickbooks-resolving-uncategorized-expenses)

**Booke**
- The "Client Query Tool" asks clients about transactions with one click and tracks requests and reminders. A third-party guide describes the portal as white-labelled and password-free. — [Booke: QBO](https://booke.ai/quickbooks-online); [Booke: simplify your bookkeeping](https://www.booke.ai/simplify-your-bookkeeping)

**Acting Office**
- Client queries are logged and tracked, with real-time updates to client and staff and partner sign-off on answers. — [AccountingWEB sponsored](https://www.accountingweb.co.uk/community/industry-insights/acting-office-is-transforming-accounting-and-bookkeeping-with-accabot)

### Inferences
- Batching happens at two levels. The accountant sends many questions at once (Digits "Review & Send"), and the system sends digest reminders (Double's single morning email). Reminder cadence is per client.
- Write-back usually goes through the accountant: the client's answer is input, and the accountant (or AI plus accountant) posts it. Very few tools let a client answer post directly to the GL. Client Hub's account dropdown comes closest.
- No tool documented filtering client questions by amount, so clients can still be asked about trivial items unless the accountant curates the list.

### Gaps
- No independent or cross-customer response-rate data, only single-firm vendor case studies.
- No published data on how many questions per client per month is tolerable before response rates fall.

## Q5. Known failure modes and criticism from accountants

### Takeaway
The recurring complaints are confident wrong coding (high confidence scores on systematically wrong categories), review workloads that cancel out the time saved, unclear audit trails, and vendor fragility (Bench). Direct Reddit threads on "too many client questions" did not come up in search. The evidence is mostly forum anecdotes.

### Cited Findings
- A bookkeeper says AI coded every recurring Home Depot purchase as Office Supplies "with 94% confidence". Reviewing the output took about as long as doing it by hand. — [beancount.io forum](https://beancount.io/forum/t/i-adopted-ai-bookkeeping-for-time-savings-but-reviewing-every-transaction-takes-just-as-long/1823)
- Another reports the AI was right about 85% of the time, and still checks anything tax-deductible or over $1,000. — [beancount.io forum](https://beancount.io/forum/t/the-80-20-reality-ai-categorizes-80-but-i-still-review-100-of-transactions/3217)
- "We spent $12K on categorization AI, then reviewed every transaction anyway": the trust paradox. — [beancount.io forum](https://beancount.io/forum/t/the-ai-trust-paradox-we-spent-12k-on-categorization-ai-then-reviewed-every-transaction-anyway/3199)
- A thread on how confidence scores mislead when stakes are high ("80% sure"). — [beancount.io forum](https://beancount.io/forum/t/the-confidence-score-problem-when-ai-says-80-sure-but-stakes-are-high/2562)
- AccountingWEB thread asking how to stop "confident nonsense becoming posted transactions" and "where is the audit trail?" when using AI with QBO/Xero. — [AccountingWEB forum](https://www.accountingweb.co.uk/node/230115)
- A Dext survey of 500 UK accountants (Dec 2025): 77% have seen more clients using public AI tools for financial or tax advice, half know of businesses that lost money acting on wrong AI advice, and 31% see client mistakes from it weekly. — [Dext news](https://dext.com/news/uk-businesses-losing-money-to-chatgpt-style-tax-and-financial-advice-accountants-warn)
- Booke: a third-party guide notes it does not chase missing receipts or detect anomalies. A G2 reviewer complains about support access. — [beancount.io forum comparison](https://beancount.io/forum/t/booke-ai-vic-ai-docyt-which-ai-bookkeeping-tool-actually-works/136); [G2 Booke](https://www.g2.com/products/booke-ai/reviews)
- Botkeeper: a secondhand Reddit summary mentions a learning curve and high pricing (unverified roundup). — [thecfoclub review](https://thecfoclub.com/tools/botkeeper-review/)
- Digits' accuracy study relied on a favourable transaction mix, which inflated accuracy (Accounting Today's caveat). — [Accounting Today](https://www.accountingtoday.com/news/digits-says-its-new-ai-agents-can-automate-95-of-bookkeeping-tasks)
- Vendor fragility: Bench's overnight shutdown locked out customers' books. — [GeekWire](https://www.geekwire.com/2024/bench-accounting-to-be-acquired-by-employer-com-following-abrupt-shutdown/)
- Pilot's AI-only tier has no human review, a critical forum post argues. — [beancount.io forum](https://beancount.io/forum/t/pilot-just-launched-a-fully-autonomous-ai-accountant-is-this-the-end-of-bookkeeping-or-the-beginning-of-a-new-kind-of-risk/3666)
- Xero's 2025-26 "accountable intelligence" positioning stresses permissions and audit trail, which suggests vendors know audit trail is a sticking point. — [CFOtech UK](https://cfotech.co.uk/story/xero-unveils-accountable-intelligence-for-ai-in-finance)

### Inferences
- Confidence calibration is the core weakness. Systematic miscoding of a recurring vendor gets high confidence because the model is consistently wrong, so a confidence threshold alone does not catch it. Anomaly checks against history (Double), tax- and account-risk rules, and sampling are the countermeasures accountants use.
- Products that explain each decision and log it (Puzzle reasoning trail, Dext explanations, Truewind rationale) are answering the black-box and audit-trail criticism directly.

### Gaps
- Reddit r/Accounting and r/Bookkeeping threads did not surface directly in search, so direct quotes on "too many client questions" were not found.
- No AccountingWEB 2025-26 survey of UK accountants' trust in Xero or QBO auto-coding was found.
