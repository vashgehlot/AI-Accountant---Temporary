# Test books: the edge cases (companion to `2026-11-18-test-books-design.md`)

These are the cases planted in the test books. Each one becomes an entry in the catalogue, with its files and lines,
once it is built.

- **"An accountant expects"** is a UK accountant's treatment. It is not the app's.
- **Sources.** Rates and rules come from `research_notes/test-corpus/uk-banks-and-tax-facts.md` and HMRC guidance.
  Where a case needs a figure that the simulation decides, the key's working shows it.
- **Builder's details.** The builder chooses the exact amounts, names and dates, as long as the case keeps its point.

**Where:**

| Code | Client |
|---|---|
| AG | agency (Ltd) |
| BU | builder (sole trader) |
| CA | café (partnership) |
| SH | shop (new Ltd) |
| LL | landlord |
| LP | LLP |
| PK | only in a standalone pack, because no client fits it |
| all | every client the case applies to |

**Stakes:**

| Stakes | Meaning |
|---|---|
| Tax | changes the tax: VAT, capital or revenue, business or personal |
| Accounts | changes the accounts' figures |
| Presentation | changes only where something is shown |
| Process | the right question asked, or the file handled; no figures change |

**Audit findings.** The 18 November audit's open findings are among these cases:

| Audit finding | Case |
|---|---|
| Car lease VAT | EC-0334 |
| No VAT schemes | EC-0325, EC-0326, EC-0390 to EC-0393 |
| Receipt over £250 held in Suspense | EC-0346 |
| No-VAT receipts not asked about | EC-0901, EC-0383 |
| VAT quarters off the year end | EC-0513 |
| Construction reverse charge | EC-0320, EC-0322 |

## 01 Reading the paper

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0101 | Receipt photographed at an angle on a patterned table | AG BU PK | Read in full: date, seller, total, VAT | Accounts |
| EC-0102 | Crumpled receipt, a fold line through the total | BU PK | Total read; a figure that can't be read is asked, not guessed | Accounts |
| EC-0103 | Faded thermal receipt, VAT summary barely legible | BU CA PK | What is legible booked; unreadable VAT not reclaimed and a copy asked for | Tax |
| EC-0104 | A phone's shadow across the receipt | PK | Read in full | Accounts |
| EC-0105 | Long supermarket receipt in two photos sent together | CA PK | One receipt, one total | Accounts |
| EC-0106 | Long receipt folded, middle items hidden; total and VAT summary visible | BU | Booked from the total and VAT summary | Accounts |
| EC-0107 | Two receipts (fuel, café) in one photo | BU PK | Two documents, booked apart | Accounts |
| EC-0108 | Card slip stapled over the item list | AG | Booked from the slip's total; VAT only if the summary shows it | Tax |
| EC-0109 | Receipt photographed upside down; another rotated 90° | PK | Read in full | Accounts |
| EC-0110 | Motion-blurred photo, still legible | PK | Read in full | Accounts |
| EC-0111 | Photo compressed by a messaging app to 600 px wide | BU | Read, or asked; digits never invented | Accounts |
| EC-0112 | Flash glare over the VAT line | PK | Total booked; VAT asked | Tax |
| EC-0113 | Handwritten note on a receipt: "client lunch – Sarah P, Brightwater" | AG | Client entertainment from the note: VAT blocked, disallowable | Tax |
| EC-0114 | Handwritten receipt from a receipt book, no VAT number | BU CA | Booked gross, no VAT | Tax |
| EC-0115 | Card slip with a tip and new total written in by hand | AG LP | The handwritten total that matches the bank; no VAT on the tip | Accounts |
| EC-0116 | Screenshot of an app ride receipt, phone status bar showing another date | AG PK | The receipt's date, not the screenshot's | Accounts |
| EC-0117 | Photo of an invoice on a computer screen (moiré) | LP | Read in full | Accounts |
| EC-0118 | HEIC photo from an iPhone | AG PK | Read, or refused with a clear reason | Process |
| EC-0119 | German receipt in EUR, "MwSt 19%", at a trade fair | AG | Sterling from the card line; no UK VAT; the German VAT is part of the cost | Tax |
| EC-0120 | Receipt total more than the card paid (gift card used for part) | CA | Cost is the total; two payments | Accounts |
| EC-0121 | Image-only PDF invoice, skewed 3° | LP LL PK | Read in full | Accounts |
| EC-0122 | Several receipts scanned onto one A4 page | LL PK | Each receipt its own document | Accounts |
| EC-0123 | PDF with one page rotated | PK | Read in full | Accounts |
| EC-0124 | Invoice over three pages, lines running across pages, total on page 3 | SH | Every line read, one total | Accounts |
| EC-0125 | PDF whose hidden text layer disagrees with its image (a bad scan's OCR) | PK | The image's figures; the disagreement flagged | Accounts |
| EC-0126 | Password-protected PDF statement | LL PK | Asks for the password, or says it can't open it | Process |
| EC-0127 | A year of statements in one 45-page PDF | LL | Every line read, or refused with a clear reason | Process |
| EC-0128 | PDF statement with balances brought and carried forward on each page and two-line descriptions | LP | Lines not doubled; balances chain | Accounts |
| EC-0129 | Invoice and its remittance in one PDF | AG | Invoice booked; remittance is evidence of payment | Accounts |
| EC-0130 | Twelve utility bills merged in one PDF | LL | Twelve documents | Accounts |
| EC-0131 | CSV re-saved by Excel: days 1–12 flipped to US dates, later days left as text | SH PK | Right dates (the order and balances show them), or flagged | Accounts |
| EC-0132 | Amounts as "£1,250.00" text, negatives as "(45.00)" | CA PK | Right amounts and signs | Accounts |
| EC-0133 | One statement as Windows-1252 with £, UTF-8 with BOM, and UTF-16 TSV | PK | All three read alike | Process |
| EC-0134 | CSV with account details before the header (Nationwide-style) | LL PK | Header found; preamble not booked | Process |
| EC-0135 | CSV ending in a totals row | PK | Totals row not booked | Accounts |
| EC-0136 | Running balance on each line, no opening balance | SH | Opening worked back from the first line | Accounts |
| EC-0137 | Long references turned into 1.23457E+15 by Excel | AG | Line booked; reference lost, not invented | Process |
| EC-0138 | XLSX with a sheet per month and merged header cells | CA | Every sheet read | Accounts |
| EC-0139 | The client's own cashbook spreadsheet (colours, comments, formulas) | CA | The client's record, checked against the bank, not booked as well | Accounts |
| EC-0140 | Mileage log spreadsheet | AG BU | Miles at each date's rate (45p; 55p from 6 Apr 2026) | Tax |
| EC-0141 | Email (.eml) with the invoice typed in its body | LP | Read as an invoice | Accounts |
| EC-0142 | Email forwarded twice with replies and the PDF invoice attached | AG | One invoice | Accounts |
| EC-0143 | Word (.docx) invoice from a sole-trader supplier | BU | Read as an invoice | Accounts |
| EC-0144 | ZIP of 30 receipt photos | AG | 30 documents, or refused with a clear reason | Process |
| EC-0145 | OFX and QIF exports of months also sent as CSV | SH LP | Same lines as the CSV, booked once | Accounts |
| EC-0146 | Photo of a two-page paper statement | BU | Lines and balances read; balances chain | Accounts |
| EC-0147 | "receipt.pdf" that is a bank statement | PK | Recognised as a statement | Accounts |
| EC-0148 | A ".pdf" that is really a JPEG; a zero-byte file | PK | Handled, or refused clearly | Process |
| EC-0149 | The same file twice under different names | AG SH | Read once; the copy noticed | Accounts |
| EC-0150 | Platform exports: Stripe payouts, Amazon settlement, Shopify payouts, PayPal activity, SumUp payouts, delivery-platform statements | AG SH CA | Read in their own layouts | Accounts |
| EC-0151 | Lloyds-layout CSV whose header ends in a trailing comma | BU | Read | Process |
| EC-0152 | HSBC-layout dates "15 Mar 2024" and amounts like "-70.0" | AG | Read | Accounts |
| EC-0153 | Santander "Excel" download that is really HTML | LL | Read, or refused clearly | Process |
| EC-0154 | Revolut-layout CSV with times in UTC: a card payment at 00:20 UK summer time on 1 July shows 30 June, the LLP's year end; fees in their own column | LP | UK date, so it falls in the new year; fee booked | Accounts |
| EC-0155 | Metro-layout dates "16-Apr-24" | LP | Read | Accounts |
| EC-0156 | Card export with no header row (Barclaycard-layout) | SH | Read | Process |

## 02 What is it, and should it be booked?

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0201 | The builder's own quote to a householder | BU | Not booked | Accounts |
| EC-0202 | Pro forma, then the invoice for the same job | LP | Only the invoice | Accounts |
| EC-0203 | The shop's purchase order to a supplier | SH | Not booked | Accounts |
| EC-0204 | Delivery note with no prices | CA | Not booked; can support cut-off | Process |
| EC-0205 | Customer's remittance advice | AG | Evidence; the payment clears the invoice | Process |
| EC-0206 | Supplier statement of five invoices, one never received | CA | Not booked; the missing invoice asked for and in creditors at year end | Accounts |
| EC-0207 | Reminder repeating an invoice already booked | AG LP | Not booked again | Accounts |
| EC-0208 | Order confirmation marked "not a VAT invoice", then the VAT invoice a week later | AG | One cost; VAT only from the VAT invoice | Tax |
| EC-0209 | Supplier credit note for part of an invoice | CA SH | Cost and VAT reduced, against that invoice | Tax |
| EC-0210 | Credit note to a customer for a disputed invoice | AG | Sales and output VAT reduced | Tax |
| EC-0211 | "VOID" invoice in the client's sales numbering | AG | Not booked; the gap explained | Accounts |
| EC-0212 | Invoice addressed to the director personally for a company cost | AG | The company's cost; VAT at risk, a re-issued invoice asked for | Tax |
| EC-0213 | Invoice addressed to the director's other company | AG | Not booked; asked | Accounts |
| EC-0214 | A receipt in another business's name (another client of the firm) | CA | Not booked; flagged | Accounts |
| EC-0215 | Council parking penalty notice | AG BU | Disallowable fine, no VAT | Tax |
| EC-0216 | Personal purchase in the pile (children's clothes) | BU | Drawings | Tax |
| EC-0217 | An employee's payslip sent by mistake | AG | Not booked; the payroll report is the source | Accounts |
| EC-0218 | P60 and P45 | AG | Not booked | Process |
| EC-0219 | HMRC VAT return receipt | AG | Not booked; confirms the VAT owed | Process |
| EC-0220 | HMRC statement with a late-filing penalty | BU | Penalty booked, disallowable, no VAT | Tax |
| EC-0221 | Bank letter about new overdraft charges | LP | Not booked | Process |
| EC-0222 | Insurance renewal schedule: premium plus Insurance Premium Tax | LP | No VAT; the tax is part of the cost | Tax |
| EC-0223 | £50 shop gift cards for each member of staff | AG | Staff cost, no VAT reclaimed; the trivial-benefit point noted | Tax |
| EC-0224 | 50% deposit invoice for the café's kitchen refit | CA | Prepayment until the work is done, then an asset | Accounts |
| EC-0225 | Annual software invoice running past the year end | AG LP | The months after year end prepaid | Accounts |
| EC-0226 | Rail booking: fare plus booking fee | AG | Fare zero-rated; fee standard-rated | Tax |
| EC-0227 | Tenancy agreement | LL | Not booked; gives the rent and deposit | Process |
| EC-0228 | Van hire purchase agreement | BU | Asset and HP liability; interest over the term | Accounts |
| EC-0229 | Bounce Back Loan statement | CA | Capital reduces the loan; interest a cost | Accounts |
| EC-0230 | Board minutes declaring an interim dividend | AG | Booked when paid (an interim dividend); the minutes support it | Accounts |
| EC-0231 | Incorporation papers: 100 £1 shares, unpaid | SH | Share capital, with called-up capital not paid until it is | Accounts |
| EC-0232 | Monthly postponed import VAT statement | SH | Not a payment: boxes 1, 4 and 7 | Tax |
| EC-0233 | Freight forwarder's invoice: freight, duty paid for the shop, admin fee | SH | Each line at the VAT shown; duty a cost; import VAT from the postponed statement or C79, not this invoice | Tax |
| EC-0234 | Business rates bill with small business rate relief | CA | Cost, no VAT | Accounts |
| EC-0235 | Council tax bill for a let property standing empty | LL | Allowable while empty | Tax |
| EC-0236 | Pension provider's contribution schedule | AG | Not booked; checks the payment | Process |
| EC-0237 | A menu, a flyer, a photo of the van | CA BU | Not booked | Process |
| EC-0238 | Savings interest certificate | AG | Confirms interest income | Process |
| EC-0239 | Image of a cheque paid in | LP | Evidence of a receipt | Process |
| EC-0240 | Supplier letter announcing new bank details | SH | Not booked; flagged (EC-0806) | Process |
| EC-0241 | Holiday-let platform statement: bookings, cleaning fees, host fee, payout | LL | Rent and fees gross; payout net | Accounts |
| EC-0242 | Letting agent's monthly statement: rent, fees, a repair paid, payout | LL | Rent gross; fees and repair as costs; payout net | Accounts |
| EC-0243 | Contractor's CIS payment and deduction statement | BU | Confirms the CIS deducted, matched to the invoices | Tax |
| EC-0244 | Payroll bureau summary | AG CA SH LP | Wages, NI and pension through control accounts | Accounts |
| EC-0245 | Service charge on account, ground rent, and a year-end balancing charge for the leasehold flat | LL | Costs of that flat, not counted twice | Accounts |
| EC-0246 | Service charge balancing credit | LL | Reduces the cost | Accounts |

## 03 Coding, VAT, payroll and CIS

**Capital or revenue**

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0301 | Laptop £1,299 | AG | Computer equipment (asset); VAT reclaimed | Tax |
| EC-0302 | Laptop repair £180 | AG | Repairs | Tax |
| EC-0303 | £480 monitor and £520 chair either side of the £500 policy | AG LP | Under: cost; over: asset | Accounts |
| EC-0304 | Van on hire purchase | BU | Asset; VAT on the price reclaimed (once registered); HP liability | Tax |
| EC-0305 | Double-cab pickup bought in 2025 | BU | Vehicle asset; VAT reclaimable if payload is 1 tonne or more; a car for capital allowances from April 2025 (noted for the return) | Tax |
| EC-0306 | Boiler replaced like for like in a let | LL | Repair, allowable | Tax |
| EC-0307 | New kitchen that improves a let | LL | Capital, not allowable against rent | Tax |
| EC-0308 | Replacement sofa in a furnished let; first furnishing of a newly bought flat | LL | Sofa: replacement relief; first furnishing: not allowable | Tax |
| EC-0309 | £3,600 coffee machine while on the flat rate scheme | CA | Asset; its VAT reclaimed outside the flat rate (capital goods of £2,000 or more) | Tax |

**VAT**

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0310 | Supermarket receipt: zero-rated food and standard-rated cleaning products | CA | VAT only on the standard-rated part | Tax |
| EC-0311 | Hotel bill: room, breakfast, bar | AG | Room and breakfast subsistence; bar personal; VAT on the business part | Tax |
| EC-0312 | Hotel abroad with a city tax | LP | No UK VAT; city tax part of the cost | Tax |
| EC-0313 | Stamps (exempt) and a courier (standard-rated) | SH | VAT only on the courier | Tax |
| EC-0314 | Insurance premium with Insurance Premium Tax | all | No VAT | Tax |
| EC-0315 | Card-processor fees | AG CA SH | No VAT unless the provider's invoice shows it | Tax |
| EC-0316 | Software from an overseas supplier charging no VAT | AG LP | Reverse charge: boxes 1 and 4; net in 6 and 7 | Tax |
| EC-0317 | Overseas supplier with no UK establishment shows a UK VAT number and charges UK VAT | AG | Reverse charge still applies (Notice 741A, 5.17); the VAT charged not reclaimed; a corrected invoice asked for | Tax |
| EC-0318 | US software billed in USD by card, with a non-sterling fee line | AG | Reverse charge on the sterling amount; the fee a bank charge | Tax |
| EC-0319 | Annual software bill in USD paid through Wise | SH | Reverse charge at the rate on the tax point; FX on payment | Tax |
| EC-0320 | Builder's invoice to a VAT-registered contractor, "reverse charge: customer to pay the VAT to HMRC" | BU | No output VAT; net in box 6 | Tax |
| EC-0321 | Builder's invoice to a householder | BU | Standard-rated output VAT | Tax |
| EC-0322 | Builder (as contractor) buys plastering from a VAT-registered firm under the reverse charge | BU | Builder accounts for the VAT: boxes 1 and 4 | Tax |
| EC-0323 | Job done before VAT registration, paid after | BU | No VAT | Tax |
| EC-0324 | Builder passed £90,000 two months before registering | BU | VAT due from when he should have registered, out of what he charged; asked | Tax |
| EC-0325 | Café sales on the flat rate scheme | CA | VAT is 12.5% of VAT-inclusive turnover; no input VAT except capital goods | Tax |
| EC-0326 | Café leaves the flat rate scheme on passing £230,000 income | CA | Standard VAT from the date the rules set | Tax |
| EC-0327 | Café on standard VAT: eat-in and hot takeaway standard, cold takeaway food zero | CA | Sales split by the till's VAT codes | Tax |
| EC-0328 | Children's eat-in meals, 25 Jun – 1 Sep 2026 | CA | 5% in that window, 20% outside it; takeaway and meals with alcohol excluded | Tax |
| EC-0329 | Consultant on the flat rate scheme whose goods are under 2% of turnover | PK | Limited cost trader: 16.5% | Tax |
| EC-0330 | Client entertainment dinner | AG LP | VAT blocked; disallowable | Tax |
| EC-0331 | Staff Christmas party | AG | Staff entertainment; VAT reclaimed | Tax |
| EC-0332 | Event for staff and clients | AG | VAT apportioned; the client share blocked | Tax |
| EC-0333 | Branded gifts under £50 to clients; a case of wine to a client | AG | Branded gifts allowable; the wine disallowable | Tax |
| EC-0334 | Company car lease with private use | AG | Half the VAT blocked | Tax |
| EC-0335 | Fuel for the company car, with the fuel scale charge | AG | Fuel VAT reclaimed; scale charge output VAT each quarter; new scale rates from the first VAT period starting on or after 1 May | Tax |
| EC-0336 | Staff mileage paid at 45p in Apr–May 2026, topped up to 55p after June | AG | 55p from 6 Apr 2026; the top-up booked when paid | Tax |
| EC-0337 | Mileage claims with fuel receipts | AG | VAT on the fuel element only | Tax |
| EC-0338 | Builder's phone bill, partly personal | BU | Personal share disallowed | Tax |
| EC-0339 | Builder works from home | BU | Use-of-home allowance in the key's working | Tax |
| EC-0340 | Builder's lunches near local sites | BU | Asked whether it was outside his normal pattern; the answer decides | Tax |
| EC-0341 | Hi-vis and boots; a pair of jeans | BU | Protective clothing allowable; jeans not | Tax |
| EC-0342 | Invoice whose VAT is 1p out from rounding each line | LP | The VAT shown reclaimed | Tax |
| EC-0343 | Supplier charges VAT but isn't registered (no number) | BU | No VAT reclaimed; the whole amount is the cost | Tax |
| EC-0344 | VAT number that fails its check digits | SH | Asked; VAT not reclaimed until confirmed | Tax |
| EC-0345 | VAT charged on books (zero-rated) | LP | VAT not reclaimable; credit asked of the supplier | Tax |
| EC-0346 | £320 till receipt printing VAT but not a full invoice | AG | Cost booked; VAT held until a full invoice comes | Tax |
| EC-0347 | Modified invoice over £250 (VAT-inclusive lines, VAT total) | LP | Valid; VAT reclaimed | Tax |
| EC-0348 | Imports under postponed VAT | SH | Boxes 1 and 4 from the monthly statement; value in box 7 | Tax |
| EC-0349 | Import where the courier paid the import VAT and charges a fee | SH | Import VAT reclaimed on the C79; the fee standard-rated | Tax |
| EC-0350 | Export to a US customer; goods sent to a consumer in France | SH | Zero-rated exports, box 6 | Tax |
| EC-0351 | Marketplace seller fees with UK VAT | SH | VAT reclaimed | Tax |
| EC-0352 | Office rent from a landlord who opted to tax | AG LP | VAT reclaimed | Tax |
| EC-0353 | Agent fees with VAT on lets | LL | Not registered: costs gross | Accounts |
| EC-0354 | Stock photos bought and recharged; a planning fee paid as the client's agent | AG LP | Recharge: VAT on it as part of the supply; true disbursement: outside VAT | Tax |
| EC-0355 | Old laptop sold; old van part-exchanged | AG BU | Disposal; output VAT where VAT was reclaimed on it (pre-registration claims included) | Tax |
| EC-0356 | Second-hand van under the margin scheme | BU | No VAT to reclaim | Tax |
| EC-0357 | Electricity at 5% (low use) one quarter and 20% another | CA | VAT at the rate charged | Tax |
| EC-0358 | Company pays a director's pension contribution directly | AG | Allowable cost, outside payroll, no VAT | Accounts |
| EC-0359 | Company pays the director's personal self-assessment | AG | Director's loan | Tax |
| EC-0360 | Corporation tax, VAT and PAYE payments | AG SH | Liabilities cleared, not costs | Accounts |
| EC-0361 | VAT repayment received | SH | Clears the VAT owed by HMRC | Accounts |
| EC-0362 | HMRC late-payment interest and a penalty | BU | Neither allowable for a sole trader | Tax |
| EC-0363 | Invoice written off after 7 months, then partly paid | AG | Bad debt relief in box 4; the part repaid in box 1 | Tax |
| EC-0364 | Prompt payment discount taken | LP | VAT on the amount actually paid | Tax |
| EC-0365 | 5% retention held by a contractor, released a year later | BU | Debtor until released; VAT by the tax point rules | Tax |
| EC-0366 | Deposit for a private party at the café | CA | Tax point on receipt; deferred income if the party is after year end | Tax |
| EC-0367 | Café gift vouchers sold and redeemed | CA | No VAT on sale (multi-purpose); VAT when redeemed; unredeemed ones owed | Tax |
| EC-0368 | Tenant's refundable deposit | LL | Not income; held for the tenant | Accounts |
| EC-0369 | Takings used to pay a casual supplier before banking | CA | Takings in full; the payment a cost | Accounts |
| EC-0370 | Stock and services bought before the shop's VAT registration | SH | Goods still held, and services within 6 months, reclaimed on the first return | Tax |
| EC-0371 | Stock invoiced in USD | SH | Cost at the invoice date's rate; FX difference on payment | Accounts |

**Payroll and CIS**

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0372 | Monthly payroll, directors and staff | AG | Gross to wages (directors apart), employer NI and pension costs; net pay, PAYE/NI and pension to control accounts | Accounts |
| EC-0373 | Employee NI 12% to 10% on 6 Jan 2024, 8% from Apr 2024 | AG CA | The books follow the reports | Accounts |
| EC-0374 | Employer NI from 6 Apr 2025: 15% above £5,000; Employment Allowance £10,500 | AG CA | NI cost net of the allowance until used up | Accounts |
| EC-0375 | Employment Allowance shown on the employer payment record, not the payroll report | AG | HMRC paid less than the report; the difference reduces the NI cost | Accounts |
| EC-0376 | Statutory maternity pay, recovered under small employers' relief | AG | SMP in wages; the recovery reduces what is paid to HMRC | Accounts |
| EC-0377 | Leaver's final pay with holiday pay; a joiner mid-month | AG | From the report | Accounts |
| EC-0378 | Card tips passed to staff through payroll (all tips from 1 Oct 2024) | CA | Not sales; owed to staff until paid | Accounts |
| EC-0379 | Director the only employee above the threshold, then a packer joins | SH | No Employment Allowance until the packer is paid above the threshold | Accounts |
| EC-0380 | Pension paid the month after the payroll | AG | Pension owed at month end | Accounts |
| EC-0381 | Net pay in one BACS from the bureau | LP | Clears net wages | Accounts |
| EC-0382 | Net pay to each person by name | CA | Clears net wages; not drawings | Accounts |
| EC-0383 | Fuel card slip with no VAT shown, from a VAT-registered station | BU | Gross, no VAT reclaimed; the VAT receipt asked for | Tax |
| EC-0384 | Invoice of labour and materials; contractor deducts 20% CIS on labour only | BU | Invoice at full value; CIS booked as tax already paid | Tax |
| EC-0385 | CIS at 30% by a contractor who couldn't verify him | BU | Booked at 30%; asked | Tax |
| EC-0386 | Builder as contractor deducts 20% from his labourer and pays HMRC monthly | BU | Labour cost gross; CIS owed to HMRC until paid | Tax |
| EC-0387 | A labourer paid with no CIS deducted | BU | Asked; the deduction was due | Tax |
| EC-0388 | CIS suffered at the sole trader's year end | BU | Moved to drawings (it is his personal tax paid) | Accounts |

**VAT cash accounting (LLP)**

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0390 | Fee invoiced in one quarter, paid in the next | LP | Output VAT in the quarter paid | Tax |
| EC-0391 | Invoice raised in advance (outside cash accounting) | LP | VAT by invoice | Tax |
| EC-0392 | Plotter on hire purchase (outside cash accounting) | LP | VAT on the invoice | Tax |
| EC-0393 | A fee never paid | LP | Never in output VAT; no bad debt relief needed | Tax |

## 04 Bank and matching

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0401 | Card payment and its receipt, the bank a day later | all | Booked once, from the receipt | Accounts |
| EC-0402 | Bank line says "ON 12 MAR" and posts on the 14th | AG | Matched; the receipt's date | Accounts |
| EC-0403 | Restaurant tip added after the hold | AG | The bank amount is the cost | Accounts |
| EC-0404 | £99 fuel hold pending in an export, settles at £63.40 | BU | Only the settled line | Accounts |
| EC-0405 | Hotel hold released and the final charge as a new line | LP | Only the final charge | Accounts |
| EC-0406 | EUR card spend with a separate non-sterling fee line | LP | Spend at the bank's sterling amount; fee a bank charge | Accounts |
| EC-0407 | Card refund for a returned item | SH | Cost reduced, or matched to the credit note | Accounts |
| EC-0408 | Partial refund | CA | As above, in part | Accounts |
| EC-0409 | Chargebacks with a £20 fee: one lost, one won | SH | Lost: sale and its VAT reversed; won: VAT unchanged; fee a cost either way | Tax |
| EC-0410 | Invoice paid in two instalments | LP | Cleared on the second | Accounts |
| EC-0411 | Customer pays twice; refunded next month | AG | Owed to the customer until refunded | Accounts |
| EC-0412 | Contractor pays three invoices in one BACS, less CIS | BU | All three cleared; the CIS deducted booked as tax already paid | Tax |
| EC-0413 | Foreign customer pays by SWIFT less a receiving fee | AG | Invoice cleared; fee a bank charge | Accounts |
| EC-0414 | EUR invoice paid into the GBP account | AG | FX gain or loss | Accounts |
| EC-0415 | Parent company pays its subsidiary's invoice | LP | Matched by reference; asked if unclear | Accounts |
| EC-0416 | Direct debit returned unpaid, then taken again | CA | One payment in the end | Accounts |
| EC-0417 | Cheque paid in, then returned unpaid | LP | Debtor back | Accounts |
| EC-0418 | Current to savings transfer, both statements in | AG | Booked once; no income or cost | Accounts |
| EC-0419 | Transfer between banks across the year end (out 31 Mar, in 2 Apr) | AG | Cash in transit at year end | Accounts |
| EC-0420 | Credit card paid off from the current account | AG SH | A transfer, not spending | Accounts |
| EC-0421 | Card statement from the 18th to the 17th | SH | Lines in their own months | Accounts |
| EC-0422 | Stripe payouts: sales less fees and refunds, 2–7 days later, one across the year end | AG | Sales gross through a clearing account; fees a cost; clearing balance at year end | Accounts |
| EC-0423 | Amazon settlement: sales, fees, refunds, reserve held and released, advertising | SH | Each on its account; the reserve an asset | Accounts |
| EC-0424 | PayPal balance pays a supplier, never reaching the bank | SH | PayPal kept as an account | Accounts |
| EC-0425 | SumUp daily payouts net of fees | CA | Card takings gross; fees a cost | Accounts |
| EC-0426 | Delivery-platform weekly statement: orders, commission with VAT, adjustments | CA | Sales gross; commission a cost; VAT by the scheme | Tax |
| EC-0427 | Daily Z-reads, weekly cash banking, cash spent in between | CA | Takings from the Z-reads; banking reconciled with the cash paid out | Accounts |
| EC-0428 | Cash machine withdrawals | BU CA | Petty cash (café) or drawings (builder); asked if unclear | Accounts |
| EC-0429 | Overlapping exports (1–15 Mar and 10–31 Mar) | SH | The overlap once | Accounts |
| EC-0430 | Two £4.50 coffees on the same day | AG | Both booked; not a duplicate | Accounts |
| EC-0431 | No statement for August | CA | Asked for; nothing invented | Process |
| EC-0432 | Opening balance not equal to the last closing | LP | Flagged; not plugged | Process |
| EC-0433 | Statement page 2 of 3 missing; it arrives in a later batch | LP | Unreconciled until it comes; no rows invented | Process |
| EC-0434 | Bank duplicates a line, then reverses it | SH | Net nil | Accounts |
| EC-0435 | Savings interest received | AG | Interest income, not sales | Accounts |
| EC-0436 | Overdraft interest and an arrangement fee | CA | Finance costs | Accounts |
| EC-0437 | Monthly bank charges with no invoice | all | Bank charges, no VAT | Accounts |
| EC-0438 | HMRC payments told apart by reference: PAYE, CT, self-assessment, VAT | AG BU | Each to its liability | Accounts |
| EC-0439 | HMRC puts a VAT payment against an older penalty | BU | As HMRC's statement allocates | Accounts |
| EC-0440 | Pension direct debit | AG | Clears pension owed | Accounts |
| EC-0441 | Loan repayments in one line, the lender's statement splitting them | CA | Capital reduces the loan; interest a cost | Accounts |
| EC-0442 | Van HP instalments | BU | Capital and interest by the schedule | Accounts |
| EC-0443 | Two mortgages: interest-only and repayment | LL | Interest a cost; capital reduces the loan | Accounts |
| EC-0444 | Agent pays over net rent | LL | Matched to the agent statement | Accounts |
| EC-0445 | Tenant pays late and short (self-managed) | LL | Income when received (cash basis); arrears noted | Accounts |
| EC-0446 | Tenant's deposit received and passed to a deposit scheme | LL | Not income | Accounts |
| EC-0447 | Cash from a householder job, part banked | BU | Sale in full; unbanked cash drawings; asked | Tax |
| EC-0448 | Personal lines in the builder's mixed account: groceries, his mortgage, child benefit in | BU | Drawings and capital introduced | Tax |
| EC-0449 | Director pays a supplier with a personal card | AG | Cost; owed to the director | Accounts |
| EC-0450 | Builder moves from Lloyds to Tide; a month of overlap | BU | Transfers once; both accounts reconcile | Accounts |
| EC-0451 | Wise: GBP to USD, then a USD supplier payment | SH | Conversion a transfer with FX; fees a cost | Accounts |
| EC-0452 | USD balance at the year end | SH | Revalued at the closing rate; FX gain or loss | Accounts |
| EC-0453 | Revolut EUR spend from a EUR balance | LP | Sterling at the rate when spent | Accounts |
| EC-0454 | Supermarket receipt including £20 cashback | CA | £20 is cash, not a cost | Accounts |
| EC-0455 | Part gift card, part card; part cash, part card | CA | One document, two payments | Accounts |
| EC-0456 | Same supplier, same amount, twice in a week, two receipts | BU | Both booked | Accounts |
| EC-0457 | Supplier invoices in its legal name; the bank shows its trading name | SH | Matched | Accounts |
| EC-0458 | One payment for "INV 1043 1044", short of both | LP | Oldest first; the rest still owed; asked | Accounts |
| EC-0459 | Faster Payment returned for wrong details and sent again | AG | Paid once | Accounts |
| EC-0460 | Card descriptors "SQ *", "SUMUP *", "PAYPAL *", "AMZNMKTPLACE" | all | Booked to what was bought, not the processor | Accounts |
| EC-0461 | Daily TfL charge for several journeys | AG | One zero-rated cost a day | Accounts |
| EC-0462 | "HMRC" direct debit with no clue which tax | BU | Asked; his self-assessment is drawings | Tax |
| EC-0463 | Unknown money in: "FP FROM J SMITH £500" | BU | Suspense; asked | Accounts |
| EC-0464 | Unknown payment out: "K PATEL £350" | BU | Suspense; asked (labour under CIS? personal?) | Tax |
| EC-0465 | Money from a relative into the business account | CA | Asked: a loan or capital; not income | Accounts |
| EC-0466 | Bounce Back Loan paid off early | CA | Loan cleared | Accounts |
| EC-0467 | Card fraud and the bank's refund | AG | Net nil | Accounts |
| EC-0468 | Cheque written in June, cleared in July (LLP year end 30 Jun) | LP | Unpresented cheque in the reconciliation | Accounts |
| EC-0469 | Cash paid in on 31 Dec, credited on 2 Jan | CA | Lodgement in transit | Accounts |
| EC-0470 | Petty cash book with top-ups from the bank | CA | Petty cash an account; top-ups transfers | Accounts |
| EC-0471 | A pending line whose amount and description change when it settles | SH | The settled line, once | Accounts |
| EC-0472 | The same months re-exported with descriptions changed and dates a day out | AG | Booked once | Accounts |

## 05 Periods and years

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0501 | Statement 15 Mar – 14 Apr across the year end | AG | Lines split between the years by date | Accounts |
| EC-0502 | Invoice dated March for April's retainer | AG | Deferred income | Accounts |
| EC-0503 | Subscription paid in February for February to January | AG | Months after year end prepaid | Accounts |
| EC-0504 | Professional indemnity insurance paid each September | LP | Prepaid at year end | Accounts |
| EC-0505 | January–March electricity billed in April | AG | Accrued | Accounts |
| EC-0506 | The year's accountancy fee | all | Accrued | Accounts |
| EC-0507 | An accrued bill arrives the next year | AG | Not counted twice (the accrual reverses) | Accounts |
| EC-0508 | Invoice raised in July for June's work (LLP year end 30 Jun) | LP | Accrued income | Accounts |
| EC-0509 | Bonus agreed at year end, paid next month | AG | Accrued | Accounts |
| EC-0510 | A missing invoice for a closed year arrives | AG | Reopened and adjusted if material, otherwise booked now with a note; the key says which | Accounts |
| EC-0511 | A cost booked twice in a closed year is found | CA | Corrected as the key says (prior-year adjustment if material) | Accounts |
| EC-0512 | Previous accountant's opening VAT liability £312 too low; the first VAT payment shows it | AG | Found, corrected by journal, asked | Accounts |
| EC-0513 | VAT quarters off the year end | AG BU LP | VAT owed at year end includes part of a quarter | Accounts |
| EC-0514 | VAT registration part-way through a year | BU | No VAT before, VAT after | Tax |
| EC-0515 | Leaving the flat rate scheme part-way through a year | CA | The scheme changes on its date | Tax |
| EC-0516 | Year end moved to 31 March: an 11-month period | BU | 11 months; nothing lost or doubled at the joins | Accounts |
| EC-0517 | 17-month first period | SH | One set of accounts; CT worked for 12 and 5 months | Tax |
| EC-0518 | Transactions on 29 Feb 2024 | all | A real date; day counts include it | Accounts |
| EC-0519 | Good Friday 29 Mar and Easter Monday 1 Apr 2024 around the agency's 31 Mar year end (a Sunday) | AG | Payments on the next working day fall in the next year | Accounts |
| EC-0520 | Rates changing part-way through a period: employee NI Jan 2024, VAT threshold 1 Apr 2024, employer NI Apr 2025, the summer 2026 5% rate, mileage 55p backdated | AG BU CA | Each from its own date | Tax |
| EC-0521 | PAYE due on the 22nd and pension next month at year end | AG | Creditors at year end | Accounts |
| EC-0522 | The current year, to 31 Oct 2026 | all | Books to date, no year-end adjustments | Accounts |
| EC-0523 | A closed year reopened, changed and closed again | AG | The next year's opening balances follow | Accounts |
| EC-0524 | VAT invoice that arrives a quarter late | LP | Reclaimed in the return for when it is held | Tax |
| EC-0525 | Furnished holiday let loses its status from April 2025 | LL | Records kept by property; the change noted | Tax |
| EC-0526 | Making Tax Digital for income tax from 6 Apr 2026 (builder and landlord, income over £50,000) | BU LL | The key gives the first two quarterly updates' totals by category | Process |

## 06 Owners

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0601 | Director's streaming subscription and groceries on the company card | AG | Director's loan | Tax |
| EC-0602 | Director pays company costs personally | AG | Owed to the director | Accounts |
| EC-0603 | Loan overdrawn at 31 Mar 2026; repaid 28 Mar, redrawn 15 Apr | AG | s455 flagged at 33.75% (loan before 6 Apr 2026); the 30-day rule voids the repayment | Tax |
| EC-0604 | Director owes over £10,000 during the year | AG | Benefit in kind flagged | Tax |
| EC-0605 | Dividend paid that the reserves don't cover | AG | Flagged as unlawful; asked; treated as the key says | Accounts |
| EC-0606 | Monthly dividends with no minutes | AG | Asked; dividends once confirmed | Accounts |
| EC-0607 | Profit shares 60/40, then 50/50 from 1 Jul 2025 | CA | Profit split by time | Accounts |
| EC-0608 | Partner's monthly drawings and personal tax from the partnership account | CA | That partner's drawings | Accounts |
| EC-0609 | Partner puts in £10,000 | CA | That partner's capital | Accounts |
| EC-0610 | Partner pays a partnership bill personally | CA | Cost; that partner's capital credited | Accounts |
| EC-0611 | Member joins 1 Jan 2025 with £20,000 capital | LP | Member's capital; profit share from the join | Accounts |
| EC-0612 | Member draws more than their share | LP | Owed by the member | Accounts |
| EC-0613 | Builder's personal income into the business account | BU | Capital introduced, not sales | Tax |
| EC-0614 | Builder's own car on simplified mileage, 45p then 55p from 6 Apr 2026 | BU | Rate by date | Tax |
| EC-0615 | Builder pays his self-assessment from the business account | BU | Drawings | Tax |
| EC-0616 | Husband pays for a repair on the joint flat from his own account | LL | Half the cost in her share | Tax |
| EC-0617 | Rent paid into her personal account with her salary | LL | Rent income; salary not part of it | Tax |
| EC-0618 | Director lends the new company £15,000 | SH | Owed to the director | Accounts |
| EC-0619 | Costs paid personally before incorporation | SH | Company costs owed to the director, where for the company | Tax |
| EC-0620 | Director's salary paid with no payroll report that month | SH | Report asked for | Process |

## 07 Year end

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0701 | Depreciation | AG BU CA SH LP | By the policy | Accounts |
| EC-0702 | Van part-exchanged for a new one on HP | BU | Old: disposal, profit or loss; new: asset and HP | Accounts |
| EC-0703 | Café stock sheet | CA | Closing stock | Accounts |
| EC-0704 | Shop inventory with seasonal lines that won't sell | SH | Lower of cost and estimated selling price less costs | Accounts |
| EC-0705 | Customer in administration | AG | Written off; VAT relief after 6 months | Tax |
| EC-0706 | Retainers billed in advance | AG | Deferred income | Accounts |
| EC-0707 | Corporation tax charge (full expensing, marginal relief) | AG SH | As the working | Tax |
| EC-0708 | Last year's CT over-provided | AG | The difference in this year's charge | Accounts |
| EC-0709 | Partnership profit split | CA | By the shares and dates | Accounts |
| EC-0710 | LLP members' allocation | LP | By the agreement | Accounts |
| EC-0711 | Close and carry forward | all | Opening equals last closing | Accounts |
| EC-0712 | Previous accountant's opening balances out by £100 | CA | Suspense, asked, cleared when found | Accounts |
| EC-0713 | HP liability under and over one year | BU | Split | Presentation |
| EC-0714 | Loans under and over one year | CA | Split | Presentation |
| EC-0715 | VAT control against the last return and the part quarter | AG BU CA SH LP | Agrees | Accounts |
| EC-0716 | Suspense after the answers | all | Empty | Accounts |
| EC-0717 | Flat rate scheme surplus | CA | Turnover net of the flat rate VAT owed | Accounts |
| EC-0718 | Landlord on the cash basis | LL | No accruals; mortgage capital not a cost | Tax |

## 08 Suspicious

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0801 | One receipt claimed by two staff | AG | One allowed; flagged | Process |
| EC-0802 | Receipt whose items don't add up to its (altered) total | AG | Flagged | Process |
| EC-0803 | Round-sum claims (£50, £100) with no receipts | LP | Asked | Process |
| EC-0804 | Toys bought online, coded by the client as office supplies | AG | Director's loan; asked | Tax |
| EC-0805 | One trip claimed as mileage and as fuel receipts | AG | One allowed; flagged | Tax |
| EC-0806 | "New bank details" letter, then a payment to the new account | SH | Flagged | Process |
| EC-0807 | One supplier invoice twice under two numbers | CA | One paid; flagged | Accounts |
| EC-0808 | Restaurant bill on Christmas Day | AG | Asked | Process |
| EC-0809 | Invoice whose VAT number fails its check digits, from a company not on the Companies House register | SH | Flagged; no VAT reclaimed | Tax |
| EC-0810 | Receipt dated before the employee joined | AG | Flagged | Process |
| EC-0811 | Mileage log with impossible distances | AG | Flagged | Tax |

## 09 The client's own mess

| ID | Case | Where | An accountant expects | Stakes |
|---|---|---|---|---|
| EC-0901 | Receipts never sent (about 5% agency, 25% builder) | all | Bank line booked with no VAT; the receipt asked for | Tax |
| EC-0902 | One receipt photographed twice, days apart | BU | Booked once | Accounts |
| EC-0903 | One invoice as a PDF and in an email | AG | Booked once | Accounts |
| EC-0904 | A year's papers in one late batch | LL BU | Each in its own year | Accounts |
| EC-0905 | Files named "scan0001.pdf", "IMG_4432.jpg" | all | Read by content | Process |
| EC-0906 | The client's spreadsheet disagrees with the bank | CA | The bank wins; differences asked | Accounts |
| EC-0907 | Unhelpful answers ("no idea, ask Dave") | BU | The accountant's fallback, as the key says | Tax |
| EC-0908 | An answer that contradicts the papers | AG | The papers win; asked again | Process |
| EC-0909 | Last year's statements sent again | CA | Not booked twice | Accounts |
| EC-0910 | Personal statements sent instead of business ones | SH | Not booked; the right ones asked for | Process |
| EC-0911 | "Ignore the last one, here's the right file" | LP | The replacement used | Process |
| EC-0912 | Papers for a closed year arrive late | AG | As EC-0510 | Accounts |

## Cases that need a run of years

Every case gets its own standalone pack, except these. They exist only in the client books:

| Topic | Cases |
|---|---|
| Cut-off and carry-forward | EC-0419, EC-0501, EC-0507, EC-0510, EC-0511, EC-0512, EC-0523, EC-0711, EC-0912 |
| Periods that aren't twelve months | EC-0516, EC-0517 |
| Schemes and status changing | EC-0514, EC-0515, EC-0525 |
| Debts that run past six months | EC-0363, EC-0365, EC-0705 |
| A page or answer that comes later | EC-0433, EC-0907, EC-0908 |
| Owners across dates | EC-0603, EC-0607, EC-0611 |
| Tax and opening balances | EC-0708, EC-0712 |
