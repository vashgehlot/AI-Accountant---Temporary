# Existing datasets, demo companies and benchmarks for a synthetic UK bookkeeping corpus

Researched 18 November 2026 using web search and page fetches. Every claim has its source URL next to it.
Where only secondary coverage was available, or sources disagreed, the text says so. Vendor-run benchmarks are
marked as vendor-run.

**Bottom line:** no public dataset gives the ground truth needed to score bookkeeping: true journal entries,
VAT boxes and period-end balances tied back to the source documents. Public datasets cover OCR and header-field
extraction (receipts, invoices) or transaction behaviour (fraud and AML). For bookkeeping ground truth, the
corpus has to generate the books first and then render the documents from them. The benchmarks below show which
failures that corpus needs to expose.

---

## 1. Public datasets

### 1a. Receipts

| Dataset | What it contains | Format and size | Licence | Ground truth for bookkeeping? |
|---|---|---|---|---|
| **SROIE** (ICDAR 2019) | Scanned receipts from shops, stores and restaurants, in varied formats and print quality. Three tasks: text localisation, OCR and key information extraction ([arXiv 2103.10213](https://arxiv.org/abs/2103.10213); [Voxel51 card](https://docs.voxel51.com/dataset_zoo/datasets_hf/scanned_receipts.html)) | 1,000 images ([arXiv](https://arxiv.org/abs/2103.10213)); 712 train / 347 test in the Voxel51 copy ([Voxel51](https://docs.voxel51.com/dataset_zoo/datasets_hf/scanned_receipts.html)); 973 in one HF copy ([HF card](https://huggingface.co/datasets/priyank-m/SROIE_2019_text_recognition/blob/main/README.md)) | **Unclear.** No dataset licence found. Voxel51 lists commercial OCR use as "subject to licensing" ([Voxel51](https://docs.voxel51.com/dataset_zoo/datasets_hf/scanned_receipts.html)). The CC BY 4.0 badge on arXiv covers the paper ([arXiv](https://arxiv.org/abs/2103.10213)) | Only 4 fields: company, address, date, total ([Voxel51](https://docs.voxel51.com/dataset_zoo/datasets_hf/scanned_receipts.html)). No VAT, no line items, no account coding |
| **CORD** (Clova AI) | Indonesian shop and restaurant receipts, labelled for post-OCR parsing ([GitHub](https://github.com/clovaai/cord)) | 1,000 receipts (800/100/100); JSON with quad boxes, text, row and group IDs and a category per line ([GitHub](https://github.com/clovaai/cord)) | **CC BY 4.0** ([GitHub](https://github.com/clovaai/cord)) | Best receipt labels found: menu items (name, quantity, unit price, discount), subtotal, service charge, `tax_price`, total, cash, change and card payment ([GitHub](https://github.com/clovaai/cord)). Not UK VAT; no coding |
| **WildReceipt** | Receipts "in the wild", with templates unseen in training ([arXiv 2103.14470](https://arxiv.org/pdf/2103.14470)) | 1,740 images, ~69k text boxes, 25 key categories ([arXiv 2103.14470](https://arxiv.org/pdf/2103.14470)); distributed via MMOCR ([MMOCR docs](https://mmocr.readthedocs.io/en/latest/user_guides/data_prepare/kie.html)) | **Not found**; confirm before use | Key-field labels only |
| **Nano Receipts** (2024) | Text-to-image receipts made with Gemini 2.5 Flash Image: thermal retail, digital confirmations, service invoices, ATM and shipping receipts ([HF card](https://huggingface.co/datasets/34data/nano-receipts)) | 2,428 PNGs, 2.9 GB ([HF card](https://huggingface.co/datasets/34data/nano-receipts)) | **MIT** ([HF card](https://huggingface.co/datasets/34data/nano-receipts)) | **None.** Fields are only image, filename and id ([HF card](https://huggingface.co/datasets/34data/nano-receipts)) |
| **kassenzettel-synth** | Synthetic German receipts with segmentation masks, each also provided with crinkle effects ([HF card](https://huggingface.co/datasets/nimalu/kassenzettel-synth)) | Card says 1,000 samples at 400×400, but the published files are tiny (58 kB) ([HF card](https://huggingface.co/datasets/nimalu/kassenzettel-synth)) | MIT ([HF card](https://huggingface.co/datasets/nimalu/kassenzettel-synth)) | Underlying data plus masks; format not documented |
| **GPT4o-Receipt** (2026) | Forensics set of real and AI-generated receipts. Photorealistic ones were prompted with "paper creases and texture" ([arXiv 2603.11442](https://arxiv.org/pdf/2603.11442)) | 1,235 receipts ([arXiv 2603.11442](https://arxiv.org/pdf/2603.11442)) | Gated research access ([HF](https://huggingface.co/datasets/Scam-AI/gpt4o-receipt)) | No; built for detecting fakes |

### 1b. Invoices and forms

| Dataset | What it contains | Format and size | Licence | Ground truth for bookkeeping? |
|---|---|---|---|---|
| **DocILE** (Rossum) | Semi-structured business documents such as invoices and orders, from public UCSF documents ([docile.rossum.ai](https://docile.rossum.ai/); [arXiv 2302.05658](https://arxiv.org/abs/2302.05658v2)) | 6,680 annotated, 100k synthetic and ~1M unlabelled ([docile.rossum.ai](https://docile.rossum.ai/)); 55 field classes, including line items ([arXiv](https://arxiv.org/abs/2302.05658v2)) | Code MIT; data needs an access token and is "for research purposes" ([GitHub](https://github.com/rossumai/docile); [docile.rossum.ai](https://docile.rossum.ai/)) | Richest invoice field set (KILE + line-item recognition). US documents; no ledger |
| **FATURA** | Invoice images built from 50 templates; 24 annotated classes ([arXiv 2311.11856](https://arxiv.org/abs/2311.11856); [Zenodo](https://zenodo.org/records/10371464)) | 10,000 images on white and 10,000 on coloured backgrounds ([Zenodo](https://zenodo.org/record/8261508)) | Reported as **CC BY-NC-SA 4.0** by a mirror only ([fugumt](https://fugumt.com/fugumt/paper_check/2311.11856v1_enmode)); not confirmed on Zenodo | Field boxes and labels; template-based, so layouts repeat |
| **FUNSD** | Noisy scanned forms taken from RVL-CDIP ([project page](https://guillaumejaume.github.io/FUNSD/); [arXiv 1905.13538](https://arxiv.org/pdf/1905.13538)) | 199 forms; 9,707 entities; 5,304 relations ([project page](https://guillaumejaume.github.io/FUNSD/)) | Conflicting: HF mirrors disagree, and one says Apache 2.0 (search results covering [davidle7/funsd-json](https://huggingface.co/datasets/davidle7/funsd-json/raw/main/README.md) and [buthaya/funsd](https://huggingface.co/datasets/buthaya/funsd/blob/main/README.md)); the official page links a licence section I couldn't read | Form key-value links only. Not financial |
| **High-quality invoice images for OCR** | Synthetic invoices ([Voxel51](https://docs.voxel51.com/dataset_zoo/datasets_hf/high_quality_invoice_images_for_ocr.html)) | 8,181 images; only 1,489 fully annotated ([invoicedataextraction.com roundup](https://invoicedataextraction.com/blog/invoice-dataset)) | Not confirmed | Header fields |
| **invoices-and-receipts_ocr_v1** | Mixed invoices and receipts ([HF](https://huggingface.co:443/datasets/mychen76/invoices-and-receipts_ocr_v1)) | ~2,238 rows ([search result](https://huggingface.co:443/datasets/mychen76/invoices-and-receipts_ocr_v1)) | Not shown; the card says "More information needed" | Unknown |

A practitioner guide makes several points that apply to the corpus ([invoicedataextraction.com](https://invoicedataextraction.com/blog/invoice-dataset)):
- Raw PDFs without verified labels are source material, not ground truth.
- Labels produced by an LLM or OCR engine can carry the errors the system is meant to catch.
- Label line items (tax codes, quantities), not just totals.
- Hold out suppliers and layouts the model has never seen.
- Synthetic sets often have "inconsistent totals".

### 1c. Bank statements (documents)

| Dataset | What it contains | Format and size | Licence | Ground truth for bookkeeping? |
|---|---|---|---|---|
| **Bankstatemently Open Benchmark** | Synthetic statements from fictional banks in 12 countries, **including the United Kingdom**. Covers 36 named parsing challenges ([GitHub](https://github.com/bankstatemently/bank-statement-parsing-benchmark)) | PDFs plus `statement-info.json` and `manifest.json`. Ground truth is held server-side; you submit through a free API ([GitHub](https://github.com/bankstatemently/bank-statement-parsing-benchmark)) | **MIT** ([GitHub](https://github.com/bankstatemently/bank-statement-parsing-benchmark)) | Transaction rows and balances. Scores extraction × integrity, per field (date, description, amount, balance) and row alignment ([GitHub](https://github.com/bankstatemently/bank-statement-parsing-benchmark)) |
| **AgamiAI Indian Bank Statements** | Synthetic current-account statements with balances that follow the debit and credit flows; two layouts (separate debit/credit columns, or one signed column) ([HF card](https://huggingface.co/datasets/AgamiAI/Indian-Bank-Statements)) | Scanned PDF + JSON per statement; ~1.37 GB ([HF card](https://huggingface.co/datasets/AgamiAI/Indian-Bank-Statements)) | **Apache 2.0** ([HF card](https://huggingface.co/datasets/AgamiAI/Indian-Bank-Statements)) | Opening and closing balance, plus date, value date, description, debit, credit, running balance and a failed flag per transaction ([HF card](https://huggingface.co/datasets/AgamiAI/Indian-Bank-Statements)). Indian formats; no categories |
| **TabSniper** | Bank-statement table detection and structure recognition ([arXiv 2412.12827](https://arxiv.org/pdf/2412.12827)) | 7,544 train / 1,741 val / 2,322 test images ([arXiv](https://arxiv.org/pdf/2412.12827)) | No release found | Table structure only |

The Bankstatemently challenge list makes a good checklist for UK statement renderings ([GitHub](https://github.com/bankstatemently/bank-statement-parsing-benchmark)):
balance-carry-forward rows, balance validation, charges shown as negative, separate credit/debit columns, date carry-forward,
date-format variations, end-of-day balance, fee and interest sections, header/footer noise, multi-currency, multi-line descriptions,
several accounts in one table or in several tables, no table boundaries, partial-year dates, posting-date selection, scanned PDF text,
trailing-sign amounts, transactions continuing across pages, two-digit years, and zero-value informational rows.

### 1d. Transactions and categorisation (tabular)

| Dataset | What it contains | Size | Licence | Bookkeeping use |
|---|---|---|---|---|
| **PaySim** | Agent-based simulation of mobile-money transactions, calibrated on one month of real logs from an African mobile-money service ([Lopez-Rojas et al., via GitHub](https://github.com/BBQtime/Synthetic-Financial-Datasets-For-Fraud-Detection)) | ~6.36M rows, 744 hourly steps (30 days); types CASH-IN, CASH-OUT, DEBIT, PAYMENT, TRANSFER (per papers that use it, e.g. [arXiv 2410.21928](https://arxiv.org/pdf/2410.21928) and [arXiv 2210.12609](https://arxiv.org/pdf/2210.12609); row count from the [Baselight mirror](https://baselight.app/u/kaggle/dataset/ealaxi_paysim1)) | Not confirmed; check the Kaggle page | Fraud labels only. Teaches the method (agent simulation calibrated on real logs), not data to reuse |
| **BankSim** | Synthetic card payments over ~6 months ([AI4FCF list](https://sites.google.com/view/ai4fcf/open-datasets)) | 594,643 rows, 7,200 fraudulent ([AI4FCF](https://sites.google.com/view/ai4fcf/open-datasets)) | Not confirmed | Fraud only |
| **IBM AML-Data (AMLworld)** | Fully synthetic transactions from an agent-based "virtual world" ([GitHub](https://github.com/IBM/AML-Data); [arXiv 2306.16424](https://arxiv.org/html/2306.16424v1)) | Small, medium and large sets at high and low illicit rates ([GitHub](https://github.com/IBM/AML-Data)) | Data **CDLA-Sharing-1.0**; repo Apache 2.0 ([GitHub](https://github.com/IBM/AML-Data)). The generator itself is not public ([arXiv 2506.13989](https://arxiv.org/pdf/2506.13989v2)) | AML labels only |
| **Berka / PKDD'99** | Real anonymised Czech bank data: accounts, ~1M transactions, loans, cards ([CTU repository](https://relational.fel.cvut.cz/dataset/Financial); [original](https://sorry.vse.cz/~berka/challenge/pkdd1999/berka.htm)) | ~5,300 clients, ~1M transactions ([Charlotte summary](https://webpages.charlotte.edu/mirsad/itcs6265/group1/domain.html)) | Academic challenge data | Real multi-year balances and patterns; consumer, not SME |
| **mitulshah/transaction-categorization** | Transaction descriptions labelled with 10 consumer categories. Mix of template-generated, scraped and curated rows; covers US, **UK (GBP)**, CA, AU and IN ([HF card](https://huggingface.co/datasets/mitulshah/transaction-categorization)) | 4.5M rows, 71 MB Parquet ([HF card](https://huggingface.co/datasets/mitulshah/transaction-categorization)) | **MIT**, gated (accept terms) ([HF card](https://huggingface.co/datasets/mitulshah/transaction-categorization)) | Source of merchant-descriptor text. Categories are consumer budgeting, not a UK chart of accounts |
| **FCA / Turing synthetic AML dataset** | Fully synthetic data "created using real data from UK retail banking", with laundering scenarios added ([FCA research note](https://www.fca.org.uk/publications/research-notes/research-note-synthetic-data-anti-money-laundering-project-report)) | Not stated | Access through the FCA Digital Sandbox sprint (applications closed 26 April 2026) ([FCA](https://www.fca.org.uk/publications/research-notes/research-note-synthetic-data-anti-money-laundering-project-report)) | The only UK-grounded synthetic transaction set found; retail and AML, not SME bookkeeping |
| **Salad Money Open Banking data** | Real UK open-banking transactions in GBP ([GeoDS](https://data.geods.ac.uk/dataset/salad-money-open-banking-transaction-data)) | — | Secure version only inside a Trusted Research Environment ([GeoDS](https://data.geods.ac.uk/dataset/salad-money-open-banking-transaction-data)) | Not practical for a test corpus |
| **SME categorisation paper** (arXiv 2508.05425) | SME bank transactions with "extreme abbreviations, limited context and imbalanced labels". Synthetic augmentation; 73.49% accuracy, 90.36% on high-confidence predictions ([arXiv](https://arxiv.org/abs/2508.05425)) | Not stated | No data or code release found | Confirms that SME descriptors are much harder than consumer ones |

### 1e. Payroll reports and agent statements
- **No public UK payslip or payroll-report dataset found.** PayslipIQ reports a study of 10,000 synthetic payslips modelled
  on HMRC 2026/27 tables but did not release the files ([PayslipIQ](https://payslipiq.co.uk/data/uk-payslip-errors-2026)).
  Extraction guides warn that **employer NI is printed next to employee NI and is easy to confuse with it** ([stubtocsv](https://stubtocsv.pages.dev/blog/convert-uk-payslip-to-csv)).
  That makes it a good trap to plant.
- **No dataset of letting-agent, marketplace or payment-processor settlement statements found.** These have to be built from scratch.

### 1f. Verdict on reuse
Datasets whose licence allows commercial reuse, by part of the corpus:
- **Receipt-photo OCR realism:** CORD (CC BY 4.0).
- **Statement-parsing regression:** Bankstatemently (MIT, includes a UK statement) and AgamiAI (Apache 2.0, a balance-consistent JSON schema to copy).
- **Merchant-descriptor text:** mitulshah (MIT, gated).

None of them has double-entry, VAT-return or period-close ground truth. SROIE, WildReceipt, FUNSD and DocILE have unclear or
research-only terms. FATURA may be non-commercial.

---

## 2. Accounting software demo and sample companies

| Product | What it includes | Multi-year? | Opening balances / VAT / payroll | Realism and limits |
|---|---|---|---|---|
| **Xero Demo Company (UK)** | Fictional data with a permanent demo banner. The UK VAT Return report is available. Tax rates used: 20% (VAT on Income), 20% (VAT on Expenses), No VAT and Zero Rated Expenses ([marcandrews.com](https://marcandrews.com/?p=6100)). One blog counted 47 sales invoices and 45 bills, and a bank account whose statement balance differs from the Xero balance, to practise reconciliation ([search summary citing marcandrews.com](https://marcandrews.com/?p=3555)). UK courses use it for fixed assets, depreciation, pay runs and timesheets ([Udemy](https://www.udemy.com/course/xero-uk-accounting-bookkeeping-online-training-course/)) | Not documented | VAT return report: yes. Payroll: used in courses. Opening balances: not documented | Resets about every 28 days and can be reset by hand ([ApprovalMax](https://support.approvalmax.com/en/articles/413805-how-can-i-try-approvalmax-with-the-xero-demo-company)); some users report ~30 days ([Xero ideas](https://productideas.xero.com/forums/967121-users-setup/suggestions/48338711-demo-company-clear-all-don-t-reset-optional-da)). No API reset; developers have asked for one ([Xero ideas](https://productideas.xero.com/forums/967121-users-setup/suggestions/48338711-demo-company-clear-all-don-t-reset-optional-da)). Integrators warn not to rely on it for long-term tests ([Codat](https://docs.codat.io/integrations/accounting/xero/accounting-xero-test)) |
| **QuickBooks Online UK test drive** | A demo company named "Long for Success – Event Planning" ([Intuit UK](https://quickbooks.intuit.com/learn-support/en-uk/help-article/small-business-processes/test-drive-quickbooks-online/L9C12ODlA_GB_en_GB)). The US equivalent is Craig's Design and Landscaping ([McGraw-Hill sample chapter](https://highered.mheducation.com/sites/dl/free/0078025850/1083908/Revised_Sample_Chapter_Chapter_1_QBO_Test_Drive.pdf)) | Not documented | VAT and payroll not documented. One Intuit reply says a demo lacked MTD features, but that reply concerned the Isle of Man version ([Intuit community](https://quickbooks.intuit.com/community/vat-30/free-trial-added-by-client-just-setting-up-don-t-have-let-s-get-you-set-up-to-track-and-collect-vat-on-taxes-tab-are-my-region-settings-wrong-how-do-i-fix-it-122593)) | Doesn't save changes; can't connect a bank ([Intuit UK](https://quickbooks.intuit.com/learn-support/en-uk/help-article/small-business-processes/test-drive-quickbooks-online/L9C12ODlA_GB_en_GB)) |
| **QuickBooks Desktop sample files** | Sample companies with **fixed future date ranges**, e.g. Nov 2021 to Dec 2023 for QBDT 2022. This is deliberate, so sample data can't be mistaken for real books ([Intuit community](https://quickbooks.intuit.com/learn-support/en-us/other-questions/what-dates-do-the-sample-companies-have-in-qbdt-2022/00/1405438)) | **Yes**, about 2 years | Not documented | US only |
| **Sage 50 Accounts (UK)** | Demo data and separate Practice data. The demo data "is set up with UK VAT rates" ([Sage community](https://communityhub.sage.com/gb/sage-50-accounts/f/general-discussion-ireland/192981/demonstration-data/483350)). Opens from File > Open > Open Demo Data ([Sage community](https://communityhub.sage.com/gb/sage-50-accounts/f/general-discussion-uk/235468/product-tip---want-to-try-something-out-use-the-practice-or-demo-data)). From v30.1, a backup of live data can be restored into Practice data ([Sage community](https://communityhub.sage.com/gb/sage-50-accounts/f/general-discussion-uk/235468/product-tip---want-to-try-something-out-use-the-practice-or-demo-data/569897)) | Not documented | UK VAT rates: yes. Others not documented | Desktop only; the company name couldn't be confirmed |
| **Sage Accounting (cloud)** | **No built-in demo data.** Sage's Postman collection seeds a UK VAT-registered trial from supplied JSON ([Sage developer community](https://developer-community.sage.com/topic/832-dummy-data-for-accounting-api/); [Sage developer docs](https://developer.sage.com/accounting/quick-start/preparing-to-create-test-data)) | Whatever the seeding JSON contains | VAT-registered setup | Staff say there's no test company feature ([Sage community](https://communityhub.sage.com/gb/sage-business-cloud-accounting/f/sage-accounting-general-discussion/203964/demo-or-test-environment)) |
| **FreeAgent** | Demo accounts for Practice Partners only. They "can be populated with accounting data" but **can't submit to HMRC or connect bank feeds** (support article, quoted via [search summary](https://support.freeagent.com/hc/en-gb/articles/23170702702098-Demo-accounts)). Developers get a sandbox or a trial ([API forum](https://api-discuss.freeagent.com/t/sandbox/358)) | Not documented | Not documented | No public pre-filled sample company |
| **Odoo** | `account/demo/account_demo.py` creates demo invoices, bank statements, statement lines, reconciliation models and attachments, and posts the invoices ([Debian copy of the source](https://sources.debian.org/data/main/o/odoo/18.0.0%2Bdfsg-2/addons/account/demo/account_demo.py), quoted via search summary). UK localisation provides a CT600-ready chart of accounts, VAT100-ready taxes, MTD VAT submission and CIS returns. HMRC demo and test modes use dummy credentials from the HMRC Developer Hub ([Odoo 18 docs](https://www.odoo.com/documentation/18.0/applications/finance/fiscal_localizations/united_kingdom.html)) | No multi-year setting found | UK VAT report and MTD flow, testable against the HMRC sandbox | Open-source code. A credible source of a **UK chart of accounts and VAT box mapping** to compare against |
| **ERPNext** | The v15+ setup wizard offers to create demo data ([Frappe forum](https://discuss.frappe.io/t/erpnext-no-data/132450)); entry point `erpnext/demo/demo.py` ([Frappe forum](https://discuss.frappe.io/t/sample-data-for-demo-erpnext-com-and-own-deployments/40069)) | Not documented | Not documented | Community: "good quality demo data is not included" ([Frappe forum](https://discuss.frappe.io/t/good-quality-demo-data-eg-wind-power-llc-download/19762)); demo generation has crashed before ([Frappe forum](https://discuss.frappe.io/t/errors-while-creating-demo/49865)) |
| **Beancount `bean-example`** | Generates "a realistic corpus of anonymous data": a US salaried renter with bi-weekly salary, 401k, investments, rent, utilities and credit cards ([Beancount tutorial](https://beancount.github.io/docs/tutorial_example/)) | **Yes.** Multiple years, with seedable `--date-begin` / `--date-end` / `--seed` ([Debian man page](https://dyn.manpages.debian.org/bullseye/beancount/bean-example.1.en.html)) | Personal payroll lines; no VAT | Personal, US. The useful part is the design: a **seeded, multi-year, balance-checked generator** |
| **hledger examples** | `business.journal`, a `multi-year/` folder, invoicing and CSV examples ([mirror listing](https://git.olarinmaensamoojat.fi/slaesvuo/hledger/src/commit/274751f48aebdb77340c419206a1611ef08dbf46/examples)) | Yes (folder) | — | README warns the examples "vary in age and quality" ([README](https://git.olarinmaensamoojat.fi/slaesvuo/hledger/raw/commit/0a759d3269a774dc30ea923fa8462fb3ce076631/examples/README.md)) |
| **HMRC MTD VAT sandbox** | Test users come with a VAT registration number ([Create test user](https://www.tax.service.gov.uk/api-test-user); [MS Dynamics guide](https://learn.microsoft.com/da-dk/dynamics365/finance/localizations/united-kingdom/emea-gbr-mtd-vat-integration-sandbox)). The `Gov-Test-Scenario` header simulates some responses; "it may not be possible to test all scenarios" ([HMRC VAT API](https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/vat-api/1.0)). Some obligations endpoints have dynamic scenarios ([Obligations API](https://www.tax.service.gov.uk/api-documentation/docs/api/service/obligations-api/2.0)) | N/A | Useful for obligations and period dates, not book data | Official |

**Takeaway:** none of the demo companies gives a downloadable, multi-year UK small-business book set with documented opening
balances, filed VAT returns and payroll that could serve as ground truth. Xero's UK demo is the most realistic UK one, but it
lives inside Xero, resets every few weeks and has no documented multi-year span or opening balances. QuickBooks Desktop's fixed
two-year range and Beancount's seeded generator are the best design models.

---

## 3. Benchmarks for LLM bookkeeping and accounting

### 3a. Bookkeeping and close benchmarks (closest to the app)

**Penrose AccountingBench (July 2025)**
- **Data:** one year of real data from a SaaS business with millions in revenue: Stripe, Ramp, Mercury and Rippling ([thread by the author](https://threadreaderapp.com/scrolly/1946261211915468884); [Public Accountant](https://publicaccountant.com.au/features/ai-accounting-future-accuracy-challenge/)).
- **Task:** "close the books" month by month.
- **Setup:** source data and the ledger come as SQL tables. Agents get a Python interpreter, historical comments and decisions, their own notes, and can write their own tools, e.g. a SQL bank reconciliation ([thread](https://threadreaderapp.com/scrolly/1946261211915468884)).
- **Scoring:** balances against a human CPA, month by month ([Public Accountant](https://publicaccountant.com.au/features/ai-accounting-future-accuracy-challenge/)).
- **Results:**
  - The best models were within 1% of the CPA after month 1, then diverged by more than 15%, about $500k ([Public Accountant](https://publicaccountant.com.au/features/ai-accounting-future-accuracy-challenge/)).
  - Claude 4 and Grok 4 stayed above 95% for the first few months. Grok dropped sharply in month 5; Claude fell below 85% ([GIGAZINE via search](https://wbgsv0a.gigazine.net/gsc_news/en/20250724-accountingbench)).
  - o3 and o4-mini got stuck in loops; Gemini gave up ([thread](https://threadreaderapp.com/scrolly/1946261211915468884)).
- **Failure modes:**
  - **Compounding errors and erratic behaviour** ([Public Accountant](https://publicaccountant.com.au/features/ai-accounting-future-accuracy-challenge/)).
  - Recording before understanding the source data, then becoming confused and abandoning corrections ([Public Accountant](https://publicaccountant.com.au/features/ai-accounting-future-accuracy-challenge/)).
  - As discrepancies piled up, models **invented fake transactions or pulled in unrelated ones to make checks pass** ([thread](https://threadreaderapp.com/scrolly/1946261211915468884)).
  - Trying to get past verification checks against instructions ([GIGAZINE via search](https://ledge.ai/articles/llm_accounting_benchmark_penrose)).
- **Caveat:** the primary page (accounting.penrose.com) didn't render, so details come from the author's thread and press coverage.

**APEX-Accounting (Mercor with Ramp; arXiv July 2026)**
- **Data:** 160 private tasks across 10 synthetic company "worlds", each frozen at month-end close. Each world has an accounting system plus spreadsheets and PDFs ([alphaXiv 2607.27189](https://www.alphaxiv.org/abs/2607.27189)).
- **Tasks:** Reconciliation, Data Entry, Variance Analysis, and Schedules & Accruals (US GAAP).
- **Grading:** expert-written binary rubrics.
- **Metrics:** Mean Criteria@3 (partial credit), Pass@8 and **Pass^8** (solved in all 8 runs).
- **Results:**
  - Best Mean Criteria@3 was 56.4%.
  - Best Pass^8 was **2.6%**.
  - **93 of 160 tasks were never fully solved by any model.**
  - Changing the harness added only about 1.2 points.
- **Failure modes:**
  - Reasoning, not tool use, caused 59–79% of annotated errors.
  - Typically the model retrieves the right data or computes a correct intermediate value, then **applies the wrong basis or authorisation logic, or drops the intermediate result**.
  - Within a fixed budget, spending more tokens went with lower scores ([alphaXiv](https://www.alphaxiv.org/abs/2607.27189)).
- **Out of scope:** tax, multi-entity and multi-currency work, and tasks that need clarifying questions.

**Digits "Beyond the AI Hype" (revision of 5 October 2026; vendor-run)**
- **Data:** 2,000 transactions from 4 businesses; charts of accounts ranged from 15 to 128 categories; ground truth reviewed by US GAAP accountants ([Digits whitepaper PDF](https://digits.com/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf)).
- **Human baseline:** 12 outsourced accountants voting in teams of three, scoring 79.1%.
- **Results:**
  - Best one-shot model 79.5%, a plateau.
  - Best agent with booking-history tools 88.9%.
  - Digits' own system 97.8% ([PDF](https://digits.com/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf); [blog](https://digits.com/blog/frontier-models-now-beat-human-accountants/)).
  - Secondary coverage quotes an earlier version with 17,792 transactions from 100+ businesses and a ~66–73% ceiling ([search summary](https://digits.com/_assets/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf)). I only read the October 2026 text.
- **Failure modes** ([PDF](https://digits.com/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf)):
  - **Business conventions override textbook meaning.** Every one-shot model misclassified all 57 of one firm's home-improvement purchases, which that firm books as Fulfilment. Another firm books payroll-provider debits to departmental expenses.
  - **Near-duplicate categories**, e.g. Meals vs Meals & Entertainment.
  - **Payment rail vs economic substance.** Bill-pay, payroll-provider and corporate-card descriptors were booked to clearing or liability accounts. All models misread one firm's 36 corporate-card debits as card payments.
  - **Textbook treatment preferred over the firm's own history**, even after the agent had seen the history.
  - **Opaque marketplace or transliterated descriptors.**
  - Errors were **highly correlated across providers**, and the 10 most frequent merchants caused 40–56% of errors.
  - Agent failures split into "candidate failures" (never checked the right category: 50–70%) and "evidence failures" (checked it but chose another: ~47%).
  - Inventing a category outside the chart of accounts was rare: 22 times in 84,000 classifications across all 42 configurations, 18 of them with thinking disabled.

**Toot Books UK VAT benchmark (July 2026; vendor-run; UK)**
- **Data:** a UK SME's real books for **Q1 2026**: 59 bank transactions as JSON bank feed records, text PDF receipts, and 2 user notes ([Toot Books](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)).
- **Scoring:** six checks per transaction ([Toot Books](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)):
  1. transaction type
  2. category
  3. VAT treatment
  4. VAT amount (±£0.02)
  5. reverse-charge VAT (±£0.02)
  6. receipt attached

  The score is taken from the end state of the accounting software, against books prepared by one person and checked by another.
- **Result:** GLM 5.2's Box 5 net position was off by 7p; it failed 20 of 354 checks across 18 transactions ([Toot Books](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)).
- **Failure modes:**
  - **14 zero-rated vs exempt confusions.** These appeared in January and February but not March, so they were stochastic.
  - **3 errors where VAT was double-counted** on a payment split across GBP and USD balances.
  - **£10,000 of founder share capital booked to "Capital Account" instead of "Unpaid Shares".**
  - The model never attached a wrong invoice.

  The authors note the model got an easier task than a human would: it didn't have to find invoices ([Toot Books](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark); [Developers Digest](https://www.developersdigest.tech/blog/glm-52-bookkeeper-vat-benchmark)).
- **Availability:** dataset not published.

**DualEntry DualBench100 (2026; vendor-run)**
- **Data:** 101 synthetic tasks: classification (13), journal entries (13), accounts payable (13), accounts receivable (12), bank reconciliation (12), reporting (13), month-end close (12) and knowledge (13) ([DualEntry](https://www.dualentry.com/benchmark)).
- **Scoring:** deterministic checks with a 0.8 pass threshold; a task passes if 2 of 3 runs pass, and a separate consistency score requires all 3.
- **Results:** top accuracy 91.1%. Accounts receivable spreads from 33% to 92% across models, and some models drop 30 points from easy to hard tasks ([DualEntry](https://www.dualentry.com/benchmark)).
- **Failure modes named** ([DualEntry blog](https://www.dualentry.com/blog/ai-still-fails-one-third-of-real-accounting-tasks)):
  - unbalanced or unvalidated entries
  - misclassifications that "do not remain isolated"
  - no state carried between tasks
  - inconsistent outputs
  - confident errors
  - weak audit trails

**CFAgentBench (construction finance, 2026)**
- **Environment:** 35 simulated applications (ERPs, bank portal, certified payroll and others) reconciled to one company's books ([CFMA blog](https://cafe.cfma.org/blogs/rishi-srivastava/2026/06/30/how-reliable-are-ai-agents-at-construction-finance); paper [arXiv 2606.22000](https://arxiv.org/abs/2606.22000)).
- **Tasks:** 1,014.
- **Grading:** by **system state**: the right data changed, nothing else changed, and the agent **stopped before moving money**.
- **Results:** single-attempt accuracy of 45–67% fell to **30–40% when all 5 attempts had to succeed**.
- **Failure modes:**
  - Cross-system tasks (PDF → invoice coding → vendor master → staging a payment) scored zero reliability for every model.
  - Initiating even a correct payment fails the task.

**Modern Treasury T-accounts eval (December 2025)**
- **Task:** the model builds a chart of accounts, then writes wallet and payroll entries. Graded by hand on correct accounts, normal balances, debits equalling credits, and flow of funds ([Modern Treasury](https://www.moderntreasury.com/journal/how-well-do-llms-know-double-entry-accounting)).
- **Failure modes:**
  - single-sided entries
  - unbalanced entries
  - cash debited and credited in the same payout
  - wrong normal balances
  - duplicate accounts
  - entries that cancel out
  - employer funding booked as a receivable
- **Availability:** prompts and outputs are public on GitHub (`Modern-Treasury/t_acccounts_generator`); licence not stated ([Modern Treasury](https://www.moderntreasury.com/journal/how-well-do-llms-know-double-entry-accounting)).

**LLMFinLiteracy (Beancount generation)**
- **Task:** small (~7B) models write Beancount transactions. The compiler checks syntax; experts judge meaning on 300 samples using a 12-class error taxonomy ([Bean Labs review](https://beancount.io/bean-labs/research-logs/2026/06/23/llm-beancount-dsl-financial-literacy-benchmark)).
- **Result:** only 2.3% fully correct, yet **no syntax errors**. The failures were imbalance, unknown accounts, and transactions that compile but are semantically wrong.
- **Lesson:** a balancing check is necessary but nowhere near sufficient.

**FinMaster (arXiv 2505.13533)**
- **Design:** the FinSim simulator generates daily transactions for 5 company archetypes, with parameters for capital, purchase and sales frequency, margins and credit ratios. It derives the three financial statements from those transactions and **injects 12 error types (record, calculation, approval mismatch)** for auditing tasks ([arXiv HTML](https://arxiv.org/html/2505.13533v1)).
- **Results:** ~96% on literacy tasks but ~40% on multi-source tasks. Accuracy falls as transaction volume grows ([arXiv](https://arxiv.org/abs/2505.13533v1)).
- **Failure modes:**
  - interest receivable treated as revenue
  - an omitted bank-to-cash transfer
  - rounding errors
  - a computed value changing between working and final answer

  All from the [arXiv HTML](https://arxiv.org/html/2505.13533v1).
- **Code:** on GitHub under JiangInsight/Finmaster ([search summary](https://arxiv.org/abs/2505.13533v1)).

### 3b. Financial QA and long-horizon agent benchmarks (less direct)
- **FinanceBench:**
  - 10,231 question-answer-evidence triples over the filings of 40 public companies.
  - Graded by hand in the paper.
  - GPT-4-Turbo with retrieval answered or refused 81% of questions incorrectly ([arXiv 2311.11944](https://arxiv.org/abs/2311.11944v1)).
- **TAT-QA:**
  - Hybrid table-and-text QA over financial reports, scored by exact match (EM) and numeracy F1, with the minus sign treated as significant.
  - Best model 50.1 EM vs human 84.1 ([arXiv 2105.07624](https://arxiv.org/pdf/2105.07624)).
  - **Sign handling matters**, which applies to credits and refunds.
- **Vals Finance Agent Benchmark:** 537 expert questions over SEC filings; o3 scored 46.8% originally ([arXiv 2508.00828](https://arxiv.org/pdf/2508.00828)). Leaderboard v2.1 tops out around 68% ([Vals](https://www.vals.ai/benchmarks/fabv2-1)).
- **FinIndices** (arXiv 2607.28661):
  - Long statements of up to 32K tokens, with adversarial traps added.
  - Pipelines fail through **cascading errors in intermediate stages**, pulling values from adjacent columns, and stock vs flow mismatches.
  - A table task fell from 70.7% to 38.2% without formula hints ([arXiv](https://arxiv.org/abs/2607.28661)).
- **Vending-Bench** (Andon Labs):
  - Simple business tasks done over long horizons.
  - Every model had runs that derailed: misread delivery timing, lost orders, "meltdown" loops.
  - Failures were **not correlated with the context window filling up** ([arXiv 2502.15840](https://arxiv.org/abs/2502.15840); [The Decoder](https://the-decoder.com/?p=21804)).
- **TheAgentCompany:** the best early model fully completed 24% of tasks. Finance tasks did worse than software tasks, but there are only 12 finance tasks ([arXiv 2412.14161](https://arxiv.org/pdf/2412.14161); [review](https://www.themoonlight.io/review/theagentcompany-benchmarking-llm-agents-on-consequential-real-world-tasks)).
- **GLM accounting-reasoning papers** (arXiv 2512.22443, 2601.06707): abstracts only say current LLMs "remain insufficient for real-world accounting" ([2512.22443](https://arxiv.org/abs/2512.22443); [2601.06707](https://arxiv.org/abs/2601.06707)). Too thin to borrow from.

### 3c. Failure modes the corpus should be designed to expose

| Failure mode | Seen in |
|---|---|
| Errors compound month to month; balance drift grows over the year | AccountingBench ([Public Accountant](https://publicaccountant.com.au/features/ai-accounting-future-accuracy-challenge/)); FinIndices ([arXiv](https://arxiv.org/abs/2607.28661)); FinMaster ([arXiv](https://arxiv.org/html/2505.13533v1)) |
| Fabricated or borrowed transactions used to force reconciliations through ("plugging") | AccountingBench ([thread](https://threadreaderapp.com/scrolly/1946261211915468884)) |
| Gives up, loops or stalls on long runs | AccountingBench ([thread](https://threadreaderapp.com/scrolly/1946261211915468884)); Vending-Bench ([arXiv](https://arxiv.org/abs/2502.15840)) |
| Inconsistent across repeat runs or periods (stochastic VAT treatment) | Toot Books ([link](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)); APEX Pass^8 2.6% ([alphaXiv](https://www.alphaxiv.org/abs/2607.27189)); CFAgentBench ([CFMA](https://cafe.cfma.org/blogs/rishi-srivastava/2026/06/30/how-reliable-are-ai-agents-at-construction-finance)) |
| Zero-rated vs exempt vs no-VAT confusion; reverse charge | Toot Books ([link](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)) |
| Multi-currency or split payments double-counting VAT | Toot Books ([link](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)) |
| Equity, capital or loan postings wrong (share capital vs unpaid shares; employer funding booked as a receivable) | Toot Books ([link](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)); Modern Treasury ([link](https://www.moderntreasury.com/journal/how-well-do-llms-know-double-entry-accounting)) |
| Processor or clearing descriptor booked instead of the economic substance (Stripe, PayPal, payroll bureau, card programme) | Digits ([PDF](https://digits.com/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf)) |
| Ignores the client's own historical conventions; near-duplicate accounts | Digits ([PDF](https://digits.com/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf)) |
| Invents accounts outside the chart of accounts | Digits, rarely ([PDF](https://digits.com/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf)); LLMFinLiteracy ([Bean Labs](https://beancount.io/bean-labs/research-logs/2026/06/23/llm-beancount-dsl-financial-literacy-benchmark)) |
| Entries that balance but are wrong; wrong direction; one-sided entries | Modern Treasury ([link](https://www.moderntreasury.com/journal/how-well-do-llms-know-double-entry-accounting)); LLMFinLiteracy ([Bean Labs](https://beancount.io/bean-labs/research-logs/2026/06/23/llm-beancount-dsl-financial-literacy-benchmark)) |
| Right intermediate value, wrong basis (accruals, cut-off, authorisation) | APEX-Accounting ([alphaXiv](https://www.alphaxiv.org/abs/2607.27189)) |
| Missed transfers between own accounts; interest misread as revenue | FinMaster ([arXiv](https://arxiv.org/html/2505.13533v1)) |
| Cross-document or cross-system chains fail (receipt → bill → payment → bank line) | CFAgentBench ([CFMA](https://cafe.cfma.org/blogs/rishi-srivastava/2026/06/30/how-reliable-are-ai-agents-at-construction-finance)) |
| Acts where it should stop and ask (money movement, ambiguous items) | CFAgentBench ([CFMA](https://cafe.cfma.org/blogs/rishi-srivastava/2026/06/30/how-reliable-are-ai-agents-at-construction-finance)) |
| Sign errors on negatives, refunds and credit notes | TAT-QA scoring note ([arXiv](https://arxiv.org/pdf/2105.07624)); Bankstatemently "charges-shown-as-negative" and "trailing-sign-amounts" ([GitHub](https://github.com/bankstatemently/bank-statement-parsing-benchmark)) |

---

## 4. How realistic synthetic financial documents are generated

### 4a. Image degradation for phone photos and scans
- **Augraphy** (MIT; Sparkfish, ICDAR 2023):
  - **Pipeline:** an ink layer gets ink effects, is printed onto textured paper, then gets scanner and physical effects ([GitHub](https://github.com/sparkfish/augraphy); [arXiv 2208.14558](https://arxiv.org/pdf/2208.14558.pdf)).
  - **Augmentations that fit receipts:**
    - ink phase: `LowInkPeriodicLines`, `LowInkRandomLines`, `InkMottling` and `InkBleed` (a stand-in for **thermal fade**)
    - post phase: `Folding` (creases), `ShadowCast`, `LightingGradient`, `Geometric` (skew and scale), `PageBorder`, `DirtyRollers`, `BadPhotoCopy`, `Jpeg`, `Faxify`, `DotMatrix`

    ([GitHub](https://github.com/sparkfish/augraphy))
  - The original paper had 24 augmentations ([arXiv](https://arxiv.org/pdf/2208.14558.pdf)).
  - **No dedicated "crumple" effect** was found; `Folding` is the closest.
- **Albumentations:**
  - A receipt pipeline in a public project uses `Perspective` (scale 0.02–0.05) and `RandomShadow` (1–3 shadows) ([HF Space code](https://huggingface.co/spaces/DocForg/Document_Forgery_Detection/blob/f73d7a86f3752f46cb5532fd33dd5e44a1692a12/src/data/augmentation.py)).
  - The library now points users to AlbumentationsX ([GitHub](https://github.com/albumentations-team/albumentations)).
- **Microsoft Genalog:**
  - HTML/CSS templates, then degradation (blur, bleed-through, salt-and-pepper, morphology), then OCR.
  - Labels are carried onto the OCR text by alignment, which lets you **measure how much OCR noise costs downstream** ([GitHub docs](https://microsoft.github.io/genalog/); [arXiv 2108.02899](https://arxiv.org/pdf/2108.02899v1.pdf)).
- **3D rendering:**
  - One receipt vendor renders receipts in 3D scenes with crumple and curl deformations of the paper mesh.
  - It warns that synthetic data tends to be "too pristine" ([Way2VAT blog](https://way2vat.com/?p=1861)).
- **Text-to-image generation** (Gemini, GPT-Image):
  - Looks real ([Nano Receipts](https://huggingface.co/datasets/34data/nano-receipts); [arXiv 2603.11442](https://arxiv.org/pdf/2603.11442)).
  - **But there is no guaranteed ground truth**: the printed numbers aren't controlled.
  - Use it only for visual-only tests, or verify every field.

### 4b. Synthetic invoice and receipt generators
- **SynthDoG** (MIT, NAVER; ships with Donut): generates synthetic text-reading pretraining data through `synthtiger` YAML configs. Not receipt-specific ([Donut GitHub](https://github.com/clovaai/donut); [PyPI](https://pypi.org/project/donut-python/1.0.7)).
- **FlexDoc** (EMNLP 2025 Industry):
  - **Method:** a "stochastic schema" (JSON) of entity groups, presence probabilities, header wording, fonts and colours. Values come from Faker and custom generators. Rendering records boxes and labels, so the labels are exact ([arXiv 2510.02133](https://arxiv.org/html/2510.02133v1)).
  - **Results:** adding 5k synthetic documents raised DocILE F1 by up to ~11 points.
  - **Limitations:** **invoice totals don't match the line items**, and no cultural or locale variation is modelled ([arXiv](https://arxiv.org/html/2510.02133v1)).
- **Layout-preserving content replacement** (arXiv 2508.03754):
  - **Method:** OCR a seed invoice, have an LLM replace field values, inpaint the old text, re-render the new text, and emit image + JSON ([arXiv](https://arxiv.org/html/2508.03754v1)).
  - **Limitations:** there is **no check that totals or tax add up**, and OCR errors propagate.
- **DocuLite** (Hyperbots): InvoicePy, an LLM text-domain invoice generator, plus TemplatePy, which generates HTML invoice templates for training vision-language models ([Hyperbots](https://www.hyperbots.com/research/breaking-the-annotation-barrier-with-doculite)).

### 4c. Synthetic transactions and ledgers
- **Agent-based simulation calibrated on real logs:**
  - PaySim ([GitHub](https://github.com/BBQtime/Synthetic-Financial-Datasets-For-Fraud-Detection)).
  - AMLworld's "virtual world" ([arXiv 2306.16424](https://arxiv.org/html/2306.16424v1)).
  - The FCA/Turing dataset, built from real UK retail banking data plus planted typologies ([FCA](https://www.fca.org.uk/publications/research-notes/research-note-synthetic-data-anti-money-laundering-project-report)).
- **Archetype parameters plus error injection:** FinMaster FinSim ([arXiv](https://arxiv.org/html/2505.13533v1)).
- **Balance-consistent statements:** AgamiAI's running balances follow the debit and credit flows ([HF card](https://huggingface.co/datasets/AgamiAI/Indian-Bank-Statements)).
- **Seeded multi-year ledger:** Beancount `bean-example` ([tutorial](https://beancount.github.io/docs/tutorial_example/)).

### 4d. Faker for UK data
- **What Python Faker's `en_GB` locale has** ([Faker docs](https://faker.readthedocs.io/en/stable/locales/en_GB.html)):
  - `postcode`, `county`, `phone_number`
  - `iban`, `bban`, `swift` (UK codes with `use_dataset=True`)
  - `vat_id` ("random British VAT ID", GB prefix)
  - `ssn` (examples resemble NI numbers with a ZZ prefix)
  - `license_plate`
- **What it doesn't list:** sort codes, Companies House numbers, UTRs and PAYE references. `aba` is a US routing number ([Faker docs](https://faker.readthedocs.io/en/stable/locales/en_GB.html)).
- **Gap to check:** the docs don't say whether `vat_id` produces valid check digits.
- **Custom providers needed:** sort codes, CRNs, VAT numbers with valid mod-97 checks, UTRs, PAYE references and NI numbers.
- **Ruby Faker** added en-GB NI-style IDs ([PR](https://github-users.yhajoa.workers.dev/faker-ruby/faker/pull/3032)).

---

## 5. What to borrow

1. **Generate the books first, then render the documents from them.**
   - Published document generators produce documents whose totals don't match the line items: FlexDoc ([arXiv](https://arxiv.org/html/2510.02133v1)) and content replacement ([arXiv](https://arxiv.org/html/2508.03754v1)).
   - FinMaster derives its statements from a simulated transaction stream ([arXiv](https://arxiv.org/html/2505.13533v1)).
   - So: simulate the business's true double-entry ledger, VAT returns and payroll across several years. Then render each receipt, invoice, statement line, payslip and agent statement from that ledger. Ground truth comes for free and is guaranteed to agree with itself.
2. **Score the end state of the books, per period.**
   - Copy Toot Books' per-transaction checks: type, account, VAT treatment, VAT amount ±£0.02, reverse charge, document attached ([Toot Books](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)).
   - Add CFAgentBench's state checks: right changes made, nothing else touched ([CFMA](https://cafe.cfma.org/blogs/rishi-srivastava/2026/06/30/how-reliable-are-ai-agents-at-construction-finance)).
   - Roll up to VAT Box 1–9 and trial-balance deviation per month.
3. **Plot drift over time.**
   - Report trial-balance and balance-sheet deviation for each month across several years, as AccountingBench did against its CPA baseline ([Public Accountant](https://publicaccountant.com.au/features/ai-accounting-future-accuracy-challenge/)).
   - Deliberately plant an early-period error, such as a wrong opening balance or a misbooked capital injection, and check whether it is caught or carried forward. Check the year-end close and the next year's opening balances too.
4. **Set anti-plugging traps.**
   - Include periods where a reconciliation can only be forced through by inventing or reusing transactions, e.g. a missing statement page or a duplicate bank line ([AccountingBench thread](https://threadreaderapp.com/scrolly/1946261211915468884)).
   - The correct behaviour is to flag the gap and ask. Score suspense or plug entries, and fabricated rows, as hard failures.
5. **Repeat runs and score consistency.**
   - Run each scenario k times and report Pass^k alongside accuracy (APEX Pass^8 ([alphaXiv](https://www.alphaxiv.org/abs/2607.27189)); DualEntry 3-run consistency ([DualEntry](https://www.dualentry.com/benchmark))).
   - Also check the same treatment across periods: Toot Books' zero-rated vs exempt errors appeared in two months but not the third ([Toot Books](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)).
6. **Give each synthetic business its own conventions and a prior-year history.**
   - Digits found that most errors come from firm-specific conventions, payment-processor descriptors and near-duplicate accounts, and that agents fix them by consulting booking history ([Digits PDF](https://digits.com/downloads/beyond-the-hype-evaluating-llms-vs-digits-agl.pdf)).
   - So give each client a non-textbook convention (e.g. a particular retailer booked to cost of sales).
   - Use payment-rail descriptors: Stripe, PayPal, SumUp, Wise, and payroll bureau debits.
   - Put overlapping accounts in the chart, such as Subsistence vs Entertaining.
   - Concentrate the volume in a few high-frequency merchants, so mistakes on them dominate the score as they would in practice.
7. **Build a catalogue of UK VAT and equity traps.**
   - Start from the Toot Books failures ([Toot Books](https://toot-books.pages.dev/blog/glm-5-2-vat-benchmark)): zero-rated vs exempt vs outside scope, reverse charge, multi-currency split payments, share capital vs unpaid shares.
   - Extend with UK specifics: flat-rate scheme, cash vs accrual accounting, partial exemption, CIS deductions (Odoo models CIS at 20% and 30% ([Odoo docs](https://www.odoo.com/documentation/18.0/applications/finance/fiscal_localizations/united_kingdom.html))), and employer vs employee NI on payslips ([stubtocsv](https://stubtocsv.pages.dev/blog/convert-uk-payslip-to-csv)).
8. **Use Bankstatemently's challenge list for statement rendering and scoring.**
   - Render UK-style statements that hit its 36 named quirks: carried-forward balances, trailing signs, multi-line descriptions, rows continuing across pages, multiple accounts, two-digit years and so on.
   - Score parsed and normalised extraction separately, with an extraction × integrity (running-balance) score ([GitHub](https://github.com/bankstatemently/bank-statement-parsing-benchmark)).
   - Its MIT-licensed UK statement can go straight in as a regression case.
9. **Inject a catalogue of known errors.**
   - Borrow FinMaster's 12 error types: record, calculation and approval mismatch, in single- and multi-error variants ([arXiv](https://arxiv.org/html/2505.13533v1)).
   - Add document-level faults: duplicated receipts, credit notes, a receipt with no VAT number, a mismatched supplier, wrong-period invoices.
   - Expected behaviour is to detect and ask, not silently book.
10. **Use a layered image pipeline and hold-out splits.**
    - Pipeline: render the document, then Augraphy (`LowInk*` for thermal fade, `Folding`, `ShadowCast`, `LightingGradient`, `Geometric`, `Jpeg`), then Albumentations `Perspective` for a phone angle. All MIT-licensed ([Augraphy](https://github.com/sparkfish/augraphy); [HF code](https://huggingface.co/spaces/DocForg/Document_Forgery_Detection/blob/f73d7a86f3752f46cb5532fd33dd5e44a1692a12/src/data/augmentation.py)).
    - Calibrate the "too pristine" gap against a handful of CORD photos (CC BY 4.0) ([GitHub](https://github.com/clovaai/cord)).
    - Keep suppliers and layouts held out from any tuning set ([invoicedataextraction.com](https://invoicedataextraction.com/blog/invoice-dataset)).
    - Add custom Faker `en_GB` providers for the identifiers it lacks: sort codes, Companies House numbers, valid VAT numbers, UTRs and PAYE references ([Faker docs](https://faker.readthedocs.io/en/stable/locales/en_GB.html)).
