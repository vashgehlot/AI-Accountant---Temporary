# UK HMRC tax and VAT rules that make an expense item "material by nature" (current at November 2026)

Scope: the rules that decide how expense-claim lines, meals, staff costs, gifts, mileage, small equipment, prepayments and director items must be coded, whatever the amount, and the facts each rule needs. Research date: 17 November 2026. Primary sources are GOV.UK HMRC manuals and notices. Secondary sources are labelled where used.

## 1. VAT on business entertainment (input tax block, Notice 700/65, staff, mixed events, overseas customers, subsistence)

### Takeaway
VAT on entertaining anyone who is not an employee is blocked, unless the guest is an overseas customer. VAT on entertaining employees only is recoverable, but not for events for directors or partners only. Mixed events are apportioned per head. Subsistence for employees working away is not entertainment. To code a meal for VAT, the app must know who attended (employee or not, director-only or not, overseas customer or not), the purpose, and that a valid VAT invoice is held. Notice 700/65 was rewritten and last updated on 3 June 2026.

### Cited Findings
- Notice 700/65 "Business entertainment" was published 29 February 2012 and last updated 3 June 2026. It replaces the November 2011 version and was rewritten for readability with updated technical content (para 1.1). The 3 June 2026 update set out who is and is not an employee for these purposes (paras 2.3–2.4). — [HMRC Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Para 1.2: input tax on entertaining UK business contacts, and non-UK contacts who are not customers, is blocked "under a special legal provision". The notice page does not name the provision (see Gaps on art. 5). — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Definition (para 2.1): three conditions must all apply: (a) entertainment is provided, (b) to people who are not employees, (c) free of charge. "Entertainment" means "hospitality of any kind" (para 2.2): food and drink, accommodation, event tickets, and use of yachts or aircraft for entertaining. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Employees (para 2.3): people you employ; directors, anyone managing the business, and partners; self-employed people treated as employees, for subsistence only; helpers and stewards essential to sporting or similar events. Not employees (para 2.4): pensioners and former employees, job applicants and interviewees, and shareholders who are not also employees. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Staff entertainment (para 3.1): entertainment for employees, such as rewards or morale-building, is treated as wholly for business. VAT on staff parties, team-building and staff outings is input tax and is not blocked. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Directors or partners only (para 3.2): VAT on events for directors or partners only is not input tax, because the goods or services are "not used for a business purpose", so it cannot be recovered. If directors and partners attend a staff party with other employees, the VAT is accepted as input tax. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Mixed events (paras 3.3–3.4, 2.7): costs incurred solely to entertain a non-employee are blocked (3.3). For an event attended by both employees and non-employees, only the share spent on employees is recoverable and the rest is blocked (3.4). Apportionment under 2.7 blocks only the entertainment element; the rest is recoverable subject to partial exemption (Notice 706). — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Overseas customers (paras 2.1, 2.6): an overseas customer is one not ordinarily resident or carrying on business in the UK (the Isle of Man counts as UK). Entertaining them is not blocked. Input tax may be recovered if the entertainment is for business purposes and "reasonable in scale and character". But private benefit to the guest usually triggers an output tax charge that cancels the recovery. That charge can be ignored only where the spend is necessary and for strict business purposes. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Examples for overseas customers (para 2.6):
  - Basic refreshments in the office, such as sandwiches and soft drinks, attract no private use charge.
  - Meals or drinks outside the office, or alcohol, are unlikely to qualify, and a restaurant meal "is very likely to lead to a private use charge".
  - Golf days, track days, evening meals and nightclubs usually trigger output tax (Revenue & Customs Brief 44/10).
  - Hospitality given out of politeness, because it is expected, or to improve relationships fails the strict business purposes test.
  - The business may instead treat the VAT as non-deductible.
  - [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Exceptions (para 2.8): recognised sporting bodies giving necessary free accommodation and meals to amateur players and officials, and airlines providing catering or accommodation for delayed passengers, are not business entertainment, so the VAT is recoverable. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Subsistence (paras 2.5, 3.1): subsistence for employees and directors is not employee entertainment. Subsistence for employees working away from their normal place of business is not business entertainment. Both are dealt with in VAT Notice 700. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- Disposals (para 2.9): goods used wholly for business entertainment can be disposed of as exempt. Goods used partly for entertainment and partly for other business use attract VAT on the full selling price. — [Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)
- HMRC internal guidance on this topic is at VIT43200 "Specific issues: business entertainment" (found in search, not fetched). — [VIT43200](https://www.gov.uk/hmrc-internal-manuals/vat-input-tax/vit43200)
- Secondary: ICAEW has a commentary on when VAT on entertaining can be claimed. — [ICAEW](https://www.icaew.com/technical/business-resources/legal-regulatory-tax-governance/tax/let-me-entertain-you-when-can-vat-be-claimed)

### Inferences
- Facts the app must hold before coding a meal or hospitality line for VAT:
  1. The headcount split between employees (including directors and partners) and non-employees. This drives the 3.4 apportionment.
  2. Whether the attendees were directors or partners only. If so, the VAT cannot be recovered (3.2).
  3. Whether any guest is an overseas customer. If so, the VAT is potentially recoverable, but the app also needs what was provided (office sandwiches versus a restaurant or alcohol), because a private use charge is likely.
  4. Whether the meal was subsistence while working away rather than entertainment. If so, the VAT is recoverable under Notice 700.
  5. That a valid VAT invoice is held (see section 3).
- Because the block depends on who attended, not on cost, a £3 coffee with a client is "material by nature" in the same way as a £3,000 dinner.
- On the employee who hosts a guest: para 3.3 blocks "costs incurred solely to entertain a non-employee". For corporation tax, BIM45034 treats an employee's restaurant meal with a customer as wholly entertainment (section 2). The fetched summary of the 2026 notice did not show express wording on whether the host's own meal is blocked or apportioned for VAT. The safe default is to block it and ask the user.

### Gaps
- I did not fetch the text of the VAT (Input Tax) Order 1992 (SI 1992/3222), art. 5, on legislation.gov.uk in this session. Its article number and wording are from background knowledge and should be confirmed: https://www.legislation.gov.uk/uksi/1992/3222/article/5
- I did not retrieve the exact paragraph in VAT Notice 700 on employee subsistence, or the conditions HMRC sets for recovery, such as the invoice being addressed to the business.
- I did not confirm the 2026 notice's exact wording on employees acting as hosts.

## 2. Corporation tax and income tax: entertaining, subsistence, the £150 annual function, trivial benefits, P11D/PSA, the 2016 exemption

### Takeaway
Business entertaining and gifts are disallowed for corporation tax and income tax (CTA 2009 s1298, ITTOIA 2005 s45), except staff entertaining that is not incidental to entertaining others. Benefit-in-kind exemptions turn on facts, not just amounts:
- annual function: £150 per head, recurring, open to all staff;
- trivial benefit: £50 or less, not cash, not contractual, not a reward for services, with a £300 cap for directors of close companies;
- subsistence: benchmark rates of £5, £10 and £25 for qualifying travel.

### Cited Findings
- Business gifts are disallowed in the same way as business entertaining (BIM45010). BIM45065 cites S45 ITTOIA 2005 and S1298 CTA 2009 as the disallowance. — [BIM45065](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim45065)
- The staff-entertaining exception (ITTOIA s46 / CTA 2009 s1299) does not apply where the employees' entertainment is "incidental to the entertainment of customers or of other people who are not employees". The test is whether the employer would have paid for the event if no guests had been present (BIM45034). — [BIM45034](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim45034)
- BIM45034 examples:
  - Canteen lunch: an employee's free canteen lunch stays allowable when a customer joins, and the customer's lunch is disallowed.
  - Restaurant lunch: an employee taking a customer to a restaurant makes the whole cost, for both of them, disallowable entertainment.
  - Golf subscription: a golf subscription paid to encourage client contact is allowable to the employer but is a P11D benefit for the employee.
  - [BIM45034](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim45034)
- Annual functions (ITEPA s264, EIM21690):
  - No tax arises if the cost per head of the annual function(s) does not exceed £150.
  - The event must recur yearly (a one-off anniversary party does not qualify) and be open to employees generally, or generally at one location.
  - Cost per head includes VAT, transport and overnight accommodation, divided by everyone attending, including non-employees.
  - Several functions are added together; if the total is over £150, the functions that make best use of the £150 are exempt.
  - "The figure of £150 is not an allowance": a function outside the exemption is taxed on the full cost per head, not the excess, including guests from family or household.
  - Virtual functions can qualify.
  - [EIM21690](https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim21690)
- Trivial benefits (ITEPA s323A, from 6 April 2016, EIM21864). All four conditions must be met:
  1. Cost does not exceed £50. For a group benefit where the exact cost per person is impracticable to work out, the average per employee is used (EIM21865).
  2. Not cash or a cash voucher (EIM21866).
  3. Not contractual, including salary sacrifice (EIM21867).
  4. Not in recognition of, or in anticipation of, particular services (EIM21868).
  - For a close company, benefits to a director or other office holder, or their family or household, are capped at £300 total cost per tax year (EIM21869).
  - [EIM21864](https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim21864)
- Subsistence benchmark scale rates (EIM30240, Income Tax (Approved Expenses) Regulations 2015, SI 2015/1948):
  - Rates: £5 for 5+ hours; £10 for 10+ hours; £25 for 15+ hours and still travelling at 8pm. A £10 late-evening supplement can be added to the £5 or £10 rate where the journey runs past 8pm.
  - Conditions: travel in the performance of duties or to a temporary workplace, not substantially ordinary commuting; absence of more than 5 or 10 hours; a meal cost incurred after the journey started, with evidence kept.
  - Paying more needs a bespoke rate agreed with HMRC (EIM30250).
  - Since 6 April 2019 no checking system is needed. Instead, no one must know or suspect that the qualifying travel did not happen (EIM30225).
  - [EIM30240](https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim30240)
- The pre-2016 rates (5 hour £5, 10 hour £10, late evening £15, breakfast £5) applied from 6 April 2009 to 5 April 2016. From 2016–17 the rates were revised and folded into the exemption for amounts that would otherwise be deductible (EIM30200 onwards), which replaced dispensations. — [EIM05231](https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim05231)

### Inferences
- Facts the app must hold for a meal or staff-cost line:
  - attendees (staff only, or with guests), because the test is whether the employer would have paid without guests;
  - whether the event is annual and open to all staff, and its total cost per head across the year (s264);
  - for gifts to staff: the cost per head, whether it is cash or a voucher, and whether it rewards performance (s323A);
  - whether the recipient is a director of a close company (the £300 cap);
  - for subsistence: the journey, its duration and the place of work (temporary or permanent).
- A staff party over £150 per head flips from exempt to fully taxable, so cost per head must be computed, not assumed.

### Gaps
- I did not research the detail of PAYE Settlement Agreements (form PSA1, the deadline of 5 July after the tax year, the items they can cover). See EIM/PAYE manual "PSA" pages (not fetched).
- I did not fetch the text of ITEPA ss337–339 (travel to a temporary workplace; the 24-month rule; the 40% test). Both the section references and the 24-month/40% rule come from background knowledge and are unverified.
- I did not confirm whether mandatory payrolling of benefits, due from April 2027, changes P11D reporting for these items.
- I did not fetch the tax treatment of director-only events for corporation tax and benefits in kind.

## 3. VAT invoices: simplified invoices, required contents, claiming without a valid invoice

### Takeaway
A simplified VAT invoice is allowed up to £250 including VAT, and I found no change to that threshold. Above £250 a full or modified invoice is needed. Input tax without a valid invoice is allowed only at HMRC's discretion under reg 29(2), and only "in exceptional circumstances". The next big change is mandatory B2B e-invoicing from 1 April 2029.

### Cited Findings
- Full VAT invoice (Notice 700/21 s4.1) must show:
  - a unique sequential number, the time of supply, and the issue date if different;
  - the supplier's name, address and VAT number, and the customer's name and address;
  - for each line: description, quantity, VAT rate and net amount;
  - the total excluding VAT, any cash discount rate, total VAT in sterling, and the unit price.
  - [Notice 700/21](https://www.gov.uk/guidance/record-keeping-for-vat-notice-70021)
- Simplified invoice (s4.5): allowed where the total does not exceed £250 including VAT. It must show the supplier's name, address and VAT number, the time of supply, a description, and the total payable including VAT for each rate, with the rate charged. Exempt supplies must not be included. Above £250 a full or modified invoice is required; a modified invoice shows VAT-inclusive values. — [Notice 700/21](https://www.gov.uk/guidance/record-keeping-for-vat-notice-70021)
- Retailers (s4.4) need not issue an invoice unless the customer asks. — [Notice 700/21](https://www.gov.uk/guidance/record-keeping-for-vat-notice-70021)
- Notice 700/21 was last updated 18 March 2024. That update removed the requirement to show the reason for a zero rate or exemption. VAT invoices are the "primary evidence" for input tax (s3.2). — [Notice 700/21](https://www.gov.uk/guidance/record-keeping-for-vat-notice-70021)
- VIT31200 on alternative evidence:
  - Reg 29(2) VAT Regs 1995 (SI 1995/2518) requires a VAT invoice that meets reg 14. HMRC may accept other evidence, but "The use of alternative evidence to support input tax claims is allowed only in exceptional circumstances."
  - HMRC will not consider it where no VAT was charged or due.
  - The trader must first ask the supplier for an invoice.
  - Acceptable alternative evidence is evidence of the taxable supply, the VAT charged and payment. Lost invoices are considered case by case.
  - Routine reliance on alternative evidence can be refused.
  - HMRC's checklist asks how the goods or services were used in the business and how the supplier relationship was established.
  - [VIT31200](https://www.gov.uk/hmrc-internal-manuals/vat-input-tax/vit31200)
- E-invoicing: GOV.UK's e-invoicing roadmap, published 28 October 2026 according to secondary reporting, says that from 1 April 2029 VAT-registered businesses must be able to issue and receive VAT invoices as e-invoices for B2B and B2G supplies, unless exempt. — [GOV.UK e-invoicing roadmap](https://www.gov.uk/government/publications/e-invoicing-implementation-roadmap/roadmap-for-e-invoicing-implementation); [vatupdate summary](https://www.vatupdate.com/2026/11/01/united-kingdom-sets-2029-vat-e-invoicing-roadmap-with-hmrc-as-peppol-authority/)

### Inferences
- The app must know whether the receipt is a valid VAT invoice:
  - supplier VAT number present;
  - full invoice if over £250;
  - a VAT amount or rate shown.
- A card-terminal slip, or a receipt with no VAT number, should not support VAT recovery. Treating it as "VAT not recoverable, query client" follows VIT31200.
- Before 2029, a PDF or paper invoice remains valid. The app's invoice-validity rules will need revisiting for 2029.

### Gaps
- I did not fetch the full text of Notice 700/63 (electronic invoicing) or the 2029 mandate's specification.
- Modified invoice contents are not set out in Notice 700/21.

## 4. Capital vs revenue for small equipment: AIA, full expensing, 40% FYA, cash basis, capitalisation policy, FRS 102/105

### Takeaway
HMRC sets no monetary de minimis for capital versus revenue. Whether an item is capital depends on its nature and effect, not on its cost or its accounts treatment. In practice, low-value plant is relieved in full through the AIA (£1m, unchanged), or through full expensing or the new 40% FYA from 1 January 2026. Under the cash basis, which is the default for unincorporated businesses from 2024–25, most capital spend is simply deducted. From April 2026 the main pool writing-down allowance falls from 18% to 14%.

### Cited Findings
- It is not possible to draw up a list of items that are capital, or of items that are revenue (BIM35000 contents). The question is answered by the effect of the expenditure, not its purpose (BIM35320). Accounts treatment may be informative but is not decisive (BIM35205). — [BIM35000](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim35000)
- BIM35201: accountants focus on timing. A generally accepted accounting rule that applies, is not one of several equally applicable rules, and fits the facts must be followed unless legislation overrides it. Depreciation is not deductible. — [BIM35201](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim35201)
- HMRC says one should not "seek to argue that the accounting treatment is decisive in stamping expenditure as capital for tax purposes" (BIM42205). Separately, on de minimis grounds, officers should not seek to identify trivial disallowable items (search snippet, page not fetched). — [BIM42205](https://gov.uk/hmrc-internal-manuals/business-income-manual/bim42205); [BIM37030](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim37030)
- Replacing tools and similar items uses the replacement/renewals rules. No deduction is due for the initial cost of the items under the renewals allowance. — [BIM46960](https://gov.uk/hmrc-internal-manuals/business-income-manual/bim46960)
- Budget 2025:
  - a new 40% first-year allowance for main-rate plant and machinery on expenditure from 1 January 2026, not capped;
  - the main pool WDA cut from 18% to 14% from 1 April 2026 for companies and 6 April 2026 for unincorporated businesses;
  - the AIA remains £1m.
  - [GOV.UK Budget 2025 OOTLAR](https://www.gov.uk/government/publications/budget-2025-overview-of-tax-legislation-and-rates-ootlar/budget-2025-overview-of-tax-legislation-and-rates-ootlar); [ICAEW Taxline](https://www.icaew.com/technical/tax/tax-faculty/taxline/articles/2026/budget-changes-to-capital-allowances); [Menzies](https://www.menzies.co.uk/autumn-budget-2025-whats-changed-for-capital-allowances/)
- Cash basis:
  - From 6 April 2024 eligible unincorporated businesses use the cash basis by default unless they elect for accruals/GAAP. Guidance for 2024–25 onwards is at BIM72001 and BIM72005–72073.
  - Under the cash basis, capital expenditure is deductible unless excluded by ITTOIA s33A. Exclusions include cars (capital allowances still claimed) and land (secondary sources).
  - [BIM72001](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim72001); [BIM70000](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim70000); [ICAEW TAXguide 04/24](https://www.icaew.com/technical/tax/tax-faculty/taxguides/2024/taxguide-04-24)

### Inferences
- Facts the app must know for an equipment line:
  - what the item is and its expected life of more than a year (capital in nature);
  - the entity type: a company, or an unincorporated business on the cash basis or accruals;
  - whether it is a car, which is excluded from AIA and full expensing and from the cash basis deduction;
  - the client's capitalisation threshold.
- For a company, a laptop is capital in nature. Its net tax effect is usually the same as expensing (AIA at 100%), but the coding differs: a fixed asset plus a capital allowance claim, versus an expense.
- A written capitalisation policy, for example items under £X expensed and applied consistently, is accepted in practice because GAAP permits it on materiality grounds and HMRC will not chase trivial items. But no HMRC page states a monetary threshold.

### Gaps
- I did not confirm that full expensing (CAA 2001 s45S, companies, new and unused main-rate plant) is still in force, though it is understood to be permanent from Autumn Statement 2023.
- I did not fetch the exact BIM wording endorsing capitalisation policies for low-value items. No HMRC monetary de minimis was found.
- I did not research FRS 102 / FRS 105 rules on capitalisation thresholds and materiality, or Section 17 of FRS 102.
- I did not fetch the exact ITTOIA s33A exclusions.

## 5. Prepayments and accruals: GAAP requirement, cash basis exception, de minimis

### Takeaway
Companies, and unincorporated businesses that opt out of the cash basis, must compute profits under GAAP, which needs prepayments and accruals. The cash basis removes them. HMRC sets no monetary de minimis; materiality is a GAAP judgement.

### Cited Findings
- GAAP-compliant accounts are the starting point for computing taxable profits (BIM30510, cross-referenced from BIM35201). Expenditure relating to another period is covered at BIM31095. — [BIM35201](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim35201)
- Under the cash basis, year-end debtors, creditors, accruals and prepayments are not needed (secondary). Leaving the cash basis requires transitional adjustments (BIM72071–72073). — [ICAEW TAXguide 04/24](https://www.icaew.com/technical/tax/tax-faculty/taxguides/2024/taxguide-04-24); [BIM70000](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim70000)
- For deferred revenue expenditure, HMRC accepts "any reasonable method of identifying the revenue element provided it is consistently applied". — [BIM42215](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim42215)

### Inferences
- The app must know the entity's accounting basis (cash basis or GAAP/accruals) and, for GAAP entities, the service period of each invoice (start and end dates) before deciding whether a line is a prepayment. Annual insurance, software subscriptions and rent paid in advance are typical "period" items.
- A consistent client-level materiality threshold for prepayments is consistent with BIM42215's "reasonable method, consistently applied". This is an inference, not a stated HMRC de minimis.

### Gaps
- I did not fetch BIM31095 or any HMRC page stating a de minimis for prepayments or accruals. None was found.
- I did not research FRS 105 micro-entity treatment of prepayments.

## 6. Other items "material by nature": director's loan account (s455), personal spending, client gifts, mileage (AMAP), uniforms and PPE

### Takeaway
Several items need a specific fact whatever their size:
- Director's loan account debits: the s455 charge is 35.75% on loans made from 6 April 2026, up from 33.75%.
- Client gifts: the £50 per recipient conspicuous-advertisement rule; food, drink, tobacco and vouchers are always disallowed; VAT has a separate £50 rule.
- Mileage: AMAP rose to 55p for cars and vans from 6 April 2026, the first change since 2011.
- Clothing: only uniforms or protective clothing qualify.

### Cited Findings
- s455: the rate is tied to the dividend upper rate. Budget 2025 raised dividend rates by 2 percentage points from 6 April 2026 (ordinary 10.75%, upper 35.75%), so s455 is 35.75% on loans advanced on or after 6 April 2026 and 33.75% on earlier loans. HMRC's CT online service will not reflect the new rate until 6 April 2027, so some returns will need amending (secondary sources). HMRC also launched a new online tool for loans to participators in April 2026. — [Crowe](https://www.crowe.com/uk/insights/budget-2025-dividend-tax-rate); [Hillier Hopkins](https://hillierhopkins.co.uk/insight-posts/loans-to-directors-tax-rate-increased/); [ICAEW](https://www.icaew.com/insights/tax-news/2026/apr-2026/new-hmrc-tool-for-providing-details-of-directors-loans)
- Business gifts for CT/IT (BIM45070):
  - Allowed only if the gift carries a conspicuous advertisement for the trader, on the item itself and not just the wrapping, such as diaries, pens or mouse mats.
  - Not allowed: food, drink, tobacco, or a token or voucher exchangeable for goods.
  - Not allowed where the total cost to the same recipient in the period exceeds £50. The period is the accounting period for companies and the tax year for unincorporated businesses.
  - Legislation: ITTOIA s47, CTA 2009 s1300.
  - [BIM45070](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim45070)
- Other gift exceptions: trade samples given away in the ordinary course of trade (BIM45071), gifts to charities (BIM45072), and gifts to employees not incidental to gifts to others (BIM45074). — [BIM45065](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim45065)
- VAT on gifts: goods given as business gifts costing no more than £50 to the same person in a 12-month period are not a supply. Above that, output VAT is due on cost. By concession, a business may instead not reclaim the input VAT (VATSC03322; secondary summary). — [VATSC03322](https://gov.uk/hmrc-internal-manuals/vat-supply-and-consideration/vatsc03322); [Tax Insider](https://www.taxinsider.co.uk/tax-articles/the-vat-rules-on-business-gifts-what-you-can-claim)
- AMAP rates (GOV.UK, last updated 21 May 2026):
  - 2026–27: cars and vans 55p for the first 10,000 business miles, then 25p; motorcycles 24p; bicycles 20p.
  - 2025–26: cars and vans 45p, then 25p.
  - Passenger payment: 5p per passenger per business mile, for fellow employees on work journeys.
  - [GOV.UK travel, mileage and fuel rates](https://www.gov.uk/government/publications/rates-and-allowances-travel-mileage-and-fuel-allowances/travel-mileage-and-fuel-rates-and-allowances); [ATT](https://www.att.org.uk/technical/news/increased-hmrc-approved-mileage-rates-business-travel-announced)
- Uniforms:
  - Relief applies only to clothing that is recognisably a uniform, or part of one, required for the job (EIM32475). A detachable badge is not enough (EIM32477).
  - Employer-provided clothing is a benefit under ITEPA s201. It is taxable on its cash equivalent unless it would meet the s336 deduction test. Consider trivial benefits first (EIM32478).
  - Protective clothing is covered at EIM32470.
  - [EIM32475](https://gov.uk/hmrc-internal-manuals/employment-income-manual/eim32475); [EIM32478](https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim32478); [EIM32465 specialist clothing](https://gov.uk/hmrc-internal-manuals/employment-income-manual/eim32465)
- Personal expenditure: HMRC's "Private and personal expenditure toolkit" covers duality of purpose and private items. ICAEW reported in August 2025 that HMRC is targeting personal expenditure. — [HMRC toolkit](https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/795773/Private_and_personal_expenditure_toolkit_2018_to_2019.pdf); [ICAEW Aug 2025](https://www.icaew.com/insights/tax-news/2025/aug-2025/hmrc-targets-personal-expenditure)

### Inferences
- Facts the app must know:
  - DLA: whether a payment is for the director's personal benefit (a DLA debit) and when it was advanced. Advances before or after 6 April 2026 attract different s455 rates, and repayment within 9 months of the period end avoids the charge.
  - Gifts: the recipient (client or staff), the contents (food, drink or vouchers are always disallowed), whether it carries the logo, and the cumulative amount to that recipient in the period.
  - Mileage: business miles, vehicle type, the tax year (2025–26 at 45p versus 2026–27 at 55p), and cumulative miles in the year (for the 10,000 threshold).
  - Clothing: whether it is a uniform, protective equipment, or ordinary clothing. Hi-vis worn for safety is likely PPE rather than ordinary clothing, but this was not confirmed from EIM text.
- Mileage claims made after 6 April 2026 at 45p are under-reimbursed rather than taxable. An app still using 45p will misstate the tax-free amount.

### Gaps
- I did not fetch the PPE exemption text (believed to be ITEPA s320A; unverified, and the s326A in the brief could not be confirmed). I did not confirm the specific treatment of hi-vis.
- I did not fetch the legislation or CTM pages (CTM61500 onwards) for s455 repayment timing (9 months and 1 day) or the bed-and-breakfasting rules (CTA 2010 s464C).
- I did not fetch VAT Notice 700/35 (business gifts and samples) directly.
- I did not research VAT on fuel when mileage is reimbursed (an advisory fuel rate receipt is needed to reclaim VAT on the fuel element).
- Other 2024–2026 changes not researched: Making Tax Digital for Income Tax from April 2026, and payrolling of benefits from April 2027.
