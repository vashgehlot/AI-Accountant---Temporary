# UK bank formats and tax facts for the synthetic test corpus

Researched 18 November 2026 with web search and page fetches. Every fact has a source link beside it.

**How reliable each source is.** The bank-format facts come from sources of mixed quality, so each is tagged:

- **[Official]** comes from the bank, HMRC, GOV.UK or a regulator.
- **[Tool]** comes from an open-source importer config or parser that someone wrote against real exports.
- **[Community]** is a user report on a forum.
- **[Vendor]** is a converter or marketing site. These are the least reliable and are kept only where nothing better was found.

Banks change their export formats without notice: HSBC changed its CSV in March 2019, and Monzo has changed its export at least twice. A realistic corpus should therefore include more than one layout per bank where the sources show variants.

---

## 1. UK bank statement export formats

### 1.1 CSV layout by bank

| Bank | Header row (in order) | Date format | Amounts | Running balance | Quirks | Sources |
|---|---|---|---|---|---|---|
| **Barclays** | `Number,Date,Account,Amount,Subcategory,Memo` | dd/mm/yyyy | One signed `Amount` column | **No.** The CSV shows only the transaction amount ([Community](https://forums.moneysavingexpert.com/discussion/6417245/anyone-recommend-the-best-bank-which-offers-good-online-transaction-reporting-and-csv-downloads)) | `Number` is the cheque number and is 0 on almost every row. `Subcategory` holds Barclays' type, e.g. "Direct Debit", "Contactless Card Purchase", "Counter Credit". `Memo` is padded to a fixed width with literal tab characters. Whole-pound amounts can have no decimal point (`-110000`). An unescaped comma in a payee name splits the row into 7 fields. The mobile app has no CSV export. Online CSV goes back only about 2 months ([Vendor](https://beancount.io/tools/csv-to-beancount/barclays)). The financier tool reverses Barclays rows, which suggests they come newest first ([Tool](https://raw.githubusercontent.com/Samathy/financier/HEAD/financier/formats/barclays.json)). One user saw a 5-column variant with no `Number` column ([Community](https://community.quickfile.co.uk/t/csv-import-missing-columns/303)) | Header: [Tool](https://raw.githubusercontent.com/Samathy/financier/HEAD/financier/formats/barclays.json); column roles and d/m/Y dates: [Tool](https://raw.githubusercontent.com/firefly-iii/import-configurations/main/gb/barclays/default.json) |
| **HSBC (current/business, since March 2019)** | `Date,Type,Description,Amount,Balance` | `15 Mar 2019` (dd Mon yyyy) | One signed column (`-80.78`) | Yes, and negative when overdrawn | Decimal places vary (`-70.0`, `1010.0`, `276.1`). `Type` holds DD, BP, CR, VIS. The layout before March 2019 had 5 columns: Date / Description / Paid Out / Paid In / Balance. The old credit-card CSV had no header and was date, description, amount. This was reported from the "new" business portal ([Community](https://community.quickfile.co.uk/t/hsbc-change-to-csv-format-march-2019/26354)) | [Community](https://community.quickfile.co.uk/t/hsbc-change-to-csv-format-march-2019/26354) |
| **Lloyds** (personal / business online) | `Transaction Date,Transaction Type,Sort Code,Account Number,Transaction Description,Debit Amount,Credit Amount,Balance,` with a **trailing comma** | dd/mm/yyyy | Separate Debit and Credit columns | Yes | Because of the trailing comma, importers see 9 columns ([Tool](https://raw.githubusercontent.com/firefly-iii/import-configurations/main/gb/lloyds/default.json)). Types seen include DEB, CPT, DD, TFR, PAY, DEP, SO, OTH ([Tool](https://github.com/ggirtsou/lloyds)). One vendor claims exports are limited to the last 12 months and 150 transactions each ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/lloyds-bank)) | [Tool](https://github.com/ggirtsou/lloyds), [Tool](https://raw.githubusercontent.com/Samathy/financier/HEAD/financier/formats/lloyds.json) |
| **Lloyds commercial** (LloydsLink-style) | Example: `Account,Date,Type,Narrative,Value Date,Payments,Receipts,Balance`. The first line names the fields | — | Payments and Receipts columns | Yes | Comes from Lloyds' own commercial CSV PDF, seen only as a search snippet because the page returned an error | [Official](https://www.lloydsbank.com/assets/commercial/pdfs/csv.pdf) |
| **NatWest / RBS / Ulster** (online banking) | `Date, Type, Description, Value, Balance, Account Name, Account Number` | dd/mm/yyyy ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/natwest)) | One signed `Value` column ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/natwest)) | Yes | `Type` examples are BAC and DPC. One user reports up to 12 months per export from a 7-year history ([Community](https://forums.moneysavingexpert.com/discussion/6417245/anyone-recommend-the-best-bank-which-offers-good-online-transaction-reporting-and-csv-downloads)). A 2023 post says only the previous 3 months of transactions, with 7 years of PDFs ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)) | [Community](https://forums.moneysavingexpert.com/discussion/6417245/anyone-recommend-the-best-bank-which-offers-good-online-transaction-reporting-and-csv-downloads) |
| **NatWest Bankline** (business, `Acc_Stmt_dd-mm-yy_HH-MM-SS.csv`) | 18 fields: sort code, account number, account alias, short name, currency, account type, BIC, bank name, branch name, **date of transaction**, **narrative lines 1–5** (25 characters each), **transaction type** (3 characters), **Debit value**, **Credit value** | DD/MM/YYYY | Separate signed debit and credit values | Not in this file. A separate balance export gives ledger and cleared balances | The first row is the column headings. Fields containing commas are quoted. One other export replaces commas with spaces. The guide is dated January 2025 | [Official](https://www.natwest.com/content/dam/natwest_com/Business_and_Content/PDFs/Export-file-layout-guide-Bankline-CSV-format.pdf) |
| **Santander** | Download formats are chosen from a drop-down. Business accounts offer Excel, Quicken, Adobe PDF and Microsoft Money. The limit is **3,000 transactions per download for business and 600 for personal**, and there is a "Since last download" option | — | — | The xls has separate money in, money out and balance columns ([Community](https://forums.moneysavingexpert.com/discussion/6417245/anyone-recommend-the-best-bank-which-offers-good-online-transaction-reporting-and-csv-downloads)) | The "Excel" file is really an **HTML table with an .xls extension**. The **TXT** export has `From:` and `Account:` header lines, then blocks of `Date:` / `Description:` / `Amount:` / `Balance:` lines. It is encoded **ISO-8859-1**, uses **non-breaking spaces** as separators, and adds a `GBP` suffix to amounts only some of the time. The "Midata" CSV is **semicolon-separated** and was incomplete in one test ([Community](https://ro-che.info/articles/2018-03-04-santander-export-transactions)) | [Official](https://business.santander.co.uk/Estatico/ALP_SBBI_Templates/Html/help50000003.html) |
| **Nationwide** (current account) | `Date,Transaction type,Description,Paid out,Paid in,Balance` | — | Separate Paid out and Paid in columns, **with a "£" symbol in the amounts** | Yes | There are **4 preamble lines before the header** ([Community](https://community.quickfile.co.uk/t/nationwide-bank-import/3724)). The credit-card CSV is `Date,Transactions,Location,Paid out,Paid in` ([Tool](https://raw.githubusercontent.com/Samathy/financier/HEAD/financier/formats/nationwide_credit.json)). Statements go back up to 15 months ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)) | [Tool](https://raw.githubusercontent.com/Samathy/financier/HEAD/financier/formats/nationwide.json) |
| **Monzo** (personal and Business) | 2020 staff list: `Transaction ID, Date, Time, Type, Name, Emoji, Category, Amount, Currency, Local amount, Local currency, Notes and #tags, Address, Receipt, Description` ([Official](https://community.monzo.com/t/csv-exports/89487/69)). Later exports add `Category split, Money Out, Money In`, for 18 columns ([Tool](https://raw.githubusercontent.com/Samathy/financier/HEAD/financier/formats/monzo.json)) | dd/mm/yyyy with a separate Time column ([Tool](https://raw.githubusercontent.com/firefly-iii/import-configurations/main/gb/monzo/default.json)). Earlier exports used ISO timestamps `2019-02-07T09:33:50Z` ([Community](https://community.monzo.com/t/csv-exports/89487)) and `%Y-%m-%d %H:%M:%S +0000` with file name `MonzoDataExport_<Month><Year>_<date>_<time>.csv` ([Tool](https://raw.githubusercontent.com/bank2ynab/bank2ynab/master/bank2ynab.conf)) | A signed `Amount` plus separate Money Out and Money In columns | No | `Type` is the payment scheme (pot transfer, card, direct debit and so on), and `Name` covers pots and contacts ([Official](https://community.monzo.com/t/csv-exports/89487/69)). Business accounts on the web export **PDF, CSV or QIF** for custom date ranges ([Official](https://monzo.com/blog/2020/05/19/monzo-business-for-web-upgrade)). Xero, FreeAgent and Sage syncs go back 12 months, and **re-syncing already-uploaded transactions creates duplicates** ([Official](https://monzo.com/help/business-accounts/historic-transactions-in-accounting-tools)) | as cited |
| **Starling** | `Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP)` ([Tool](https://github.imc.re/mafonso/starling2freeagent/blob/master/README.md)), plus a 7th column `Spending Category` in some exports ([Community](https://lists.gnucash.org/pipermail/gnucash-user/2021-November/098446.html), [Tool](https://raw.githubusercontent.com/firefly-iii/import-configurations/main/gb/starling/default.json)) | dd/mm/yyyy | One signed column, negative for money out ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/starling-bank)) | Yes | The reference is in **field 3, not 2**, which broke one importer's default mapping ([Community](https://community.quickfile.co.uk/t/starling-csv-account-statement-import-incorrect-fields/40318)). The file may start with an opening-balance row that is not a transaction ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/starling-bank)). Foreign spend appears in GBP ([Vendor](https://beancount.io/tools/csv-to-beancount/starling)). Exports are CSV, and monthly statements carry a "True Copy" stamp ([Official](https://www.starlingbank.com/features/statements/)) | as cited |
| **Revolut Business** | `Date started (UTC), Date completed (UTC), ID, Type, Description, Reference, Payer, Card number, Orig currency, Orig amount, Payment currency, Amount, Fee, Balance, Account, Beneficiary account number, Beneficiary sort code/routing, Beneficiary IBAN, Beneficiary BIC` ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/revolut)) | ISO `YYYY-MM-DD HH:MM:SS`, **UTC by default**. The CSV can show UTC and local time ([Official](https://help.revolut.com/business/help/managing-my-business/viewing-my-account-statements/how-to-get-a-monthly-statement/)) | One signed column plus a **separate Fee column** | Yes | Statements come as **PDF, CSV, XML (camt.053) or TXT (MT940)**, and only the PDF can be signed and stamped ([Official](https://help.revolut.com/business/help/managing-my-business/viewing-my-account-statements/how-to-get-a-monthly-statement/)). **CSVs have had no exchange-rate column since October 2021** ([Community](https://community.revolut.com/t/since-october-2021-csv-exports-stopped-including-exchange-rate-information/210423)). Pending rows can have a blank completed date. Personal exports are `Type, Product, Started Date, Completed Date, Description, Amount, Fee, Currency, State, Balance`, with State values COMPLETED, PENDING, REVERTED or DECLINED ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/revolut)) | as cited |
| **Tide** | Column names not confirmed | — | — | Only with the option "Standard – Cleared only (including running balance)" | Transactions export as **CSV only**, either a standard layout or an accounting-provider layout, and statements as **PDF only**. Monthly statements are issued on the **4th of the following month**. A custom-range statement must end at least 3 days ago and cover at most 6 months, and statements with more than 2,000 lines are emailed as a link | [Official](https://www.tide.co/help-centre/download-tide-account-statements-and-transactions/) |
| **Metro Bank** (business) | `Booking Date, Value Date, Transaction Type, Transaction Reference, Payer/Payee Name, Payment Reference, Money In/Out, Balance` | `16-Apr-15` (dd-Mon-yy) | One signed `Money In/Out` column (`-0.20`) | Yes | Transaction type example: "Account to Account Transfer". Reference example: `FT151068NJG2`. The file is named `[customer number].[account number].[currency].[file type]`. "Download" gives a PDF of the **last 32 days**. The guide is from 2016 ([Official](https://www.metrobankonline.co.uk/globalassets/documents/customer_documents/business-and-commercial/user-guide-exporting-transaction-data.pdf)). Export is one month at a time, via "Export transactions to CSV" ([Vendor](https://support.clearbooks.co.uk/support/solutions/articles/33000274569-metro-bank-statement-import-guide)) | [Official](https://www.metrobankonline.co.uk/globalassets/documents/customer_documents/business-and-commercial/user-guide-exporting-transaction-data.pdf) |
| **American Express UK** | `Date, Description, Amount, Extended Details, Appears On Your Statement As, Address, City/State, Zip Code, Country, Reference, Category`, from a May 2022 download ([Tool](https://github.com/jmcameron/amex2qif)). The UK file may use UK labels such as Town/City and Postcode, which is **unconfirmed** | — | One column: **charges positive, credits and payments negative** ([Vendor](https://reconcile-bvs.pages.dev/blogAmexPdfToCsv)) | No | Extended Details appears only if ticked at export. Foreign charges are already converted to GBP ([Vendor](https://reconcile-bvs.pages.dev/blogAmexPdfToCsv)). A 2025 user lists CSV, Excel, QuickBooks, Quicken, Money and QIF, with up to 2 years of history ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)). One tool says Amex dropped QIF ([Tool](https://github.com/jmcameron/amex2qif)) | as cited |
| **Barclaycard** (personal) | **No header row.** Columns are Date, Description, then 2–3 unused columns, Category, credit amount, debit amount. The two importers disagree: 7 columns ([Tool](https://raw.githubusercontent.com/firefly-iii/import-configurations/main/gb/barclaycard/default.json)) versus 8 ([Tool](https://raw.githubusercontent.com/bank2ynab/bank2ynab/master/bank2ynab.conf)) | `12 Mar 24` (`%d %b %y`) | Separate credit and debit columns | No | File name is `statement_1.csv`. Formats are CSV, OFX and QIF, covering the last 12 statements ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)). Barclaycard Online Servicing closed, and the export moved into Barclays online banking ([Community](https://forums.moneysavingexpert.com/discussion/6679452/barclaycard-csv-exports)) | as cited |
| **Barclaycard Business** (`Recent-dd-mm-yyyy.csv`) | `Cardholder Name, Account Number, Transaction Date, Merchant Name, Amount, Currency, Original Amount, Original Currency, Conversion Rate, Posted Date, Transaction Time, Authorisation Code, Transaction ID, Merchant Category, Transaction Type, MCC Description, Merchant Town/City, Merchant County/State, Merchant Post code/Zipcode, MCC, Statement Cycle` | dd/mm/yyyy | `Amount` is positive for spend | No | The masked card number looks like `****9940`. Transaction Date and Posted Date differ (10/04 against 12/04). Transaction Type example: `PURCHASE` | [Tool](https://raw.githubusercontent.com/bank2ynab/bank2ynab/master/bank2ynab.conf) |

### 1.2 OFX and QIF availability

| Bank | What the sources say |
|---|---|
| Barclays | The export dialog offers CSV as well as OFX and QIF ([Vendor](https://beancount.io/tools/csv-to-beancount/barclays)) |
| HSBC | One user could download transactions as CSV, OFX and QIF in 2021 ([Community](https://forums.moneysavingexpert.com/discussion/6297815/banks-that-offer-statements-in-csv)). HSBC UK Business downloads OFX or CSV ([Community](https://quickbooks.intuit.com/learn-support/en-uk/banking/hsbc-web-connect-desktop/00/730716)). Statements have been PDF-only since 2021 ([Tool](https://github.com/shuckster/obis)) |
| Lloyds / Halifax | Lloyds exports CSV and QIF ([Vendor](https://imagetotable.ai/blog/convert-lloyds-statement-to-excel)). One user found Lloyds QIF rows in the wrong order ([Community](https://community.quickfile.co.uk/t/lloyds-bank-qif-import-issue/13517)). Lloyds also offers a QFX file ([Community](https://community.quickfile.co.uk/t/lloyds-qfx-not-qif-how-to-import/29430)). Halifax offered CSV and QIF and the last 6 statements in 2023 ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)) |
| NatWest | One user says NatWest "used to do OFX" ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)). Bankline also exports SWIFT and BAI layouts ([Official](https://tools.natwest.com/content/dam/natwest_com/Business_and_Content/PDFs/Export-file-layout-guide-SWIFT-format.pdf)) |
| Santander | Quicken (QIF) and Microsoft Money (OFX) are offered ([Official](https://business.santander.co.uk/Estatico/ALP_SBBI_Templates/Html/help50000003.html)). One tester's parsers rejected the QIF with "Unknown header format" ([Community](https://ro-che.info/articles/2018-03-04-santander-export-transactions)) |
| Monzo | QIF is available, OFX is not mentioned ([Official](https://monzo.com/blog/2020/05/19/monzo-business-for-web-upgrade)) |
| Revolut Business | No OFX or QIF. Offers camt.053 and MT940 instead ([Official](https://help.revolut.com/business/help/managing-my-business/viewing-my-account-statements/how-to-get-a-monthly-statement/)) |
| Metro Bank | No QIF or QFX ([Vendor](https://support.clearbooks.co.uk/support/solutions/articles/33000274569-metro-bank-statement-import-guide)) |
| Barclaycard | CSV, OFX and QIF ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)) |
| Amex UK | Conflicting reports. One user says only PDF or CSV in 2025 ([Community](https://infinitekind.tenderapp.com/discussions/online-banking/1250712-uk-and-downloading-csv-files)). Another 2025 user lists Quicken, Money and QIF ([Community](https://forums.moneysavingexpert.com/discussion/6477826/which-credit-cards-offer-csv-transaction-downloads-and-for-how-many-months-years)) |

### 1.3 Transaction-type codes on statements and in CSVs

| Code | Meaning | Bank or source |
|---|---|---|
| BAC / BACS | Automated credit, e.g. salary, pension or benefits. Takes 3 working days | NatWest ([Official](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html)), MSE ([source](https://www.moneysavingexpert.com/banking/bank-statement-codes)) |
| BGC | Bank Giro Credit: cash or cheque paid in at a branch | Lloyds ([Official](https://www.lloydsbank.com/help-guidance/customer-support/payment-codes.asp), snippet only), NatWest ([Official](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html)) |
| BP / BBP | Bill payment | Lloyds and HSBC ([MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes)) |
| CHAPS / CHP | CHAPS same-day transfer. Barclays shows "CHAPS", NatWest shows "CHP" | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes) |
| CHG / "Charge" | Bank fee. NatWest now shows "Charge" where it used to show CHG | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| CHQ | Cheque, in either direction | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html), [HSBC](https://hsbc.co.uk/help/banking-made-easy/understanding-your-statement) |
| CPT / C/L / ATM | Cash machine withdrawal. Lloyds uses CPT ("Cashpoint"), NatWest uses C/L ("Cashline") | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes), [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| CDM | Cash and deposit machine | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| COR | Correction to an earlier transaction | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes) |
| CR / DR | Credit / debit. A DR beside a balance can mean the account is overdrawn | [HSBC](https://hsbc.co.uk/help/banking-made-easy/understanding-your-statement) |
| CUI / UNP | Unpaid cheque | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html), [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes) |
| DD / D/D / DDR | Direct Debit. NatWest writes "D/D", HSBC and Lloyds write "DD" | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html), [HSBC](https://hsbc.co.uk/help/banking-made-easy/understanding-your-statement) |
| DEB | Debit card payment (Lloyds) | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes), [Tool](https://github.com/ggirtsou/lloyds) |
| DEP | Deposit | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes) |
| DPC | Payment made through online banking ("Direct Banking by PC"), NatWest | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| FPI / FPO / FP | Faster Payment in / out | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes), Lloyds ([snippet](https://www.lloydsbank.com/help-guidance/customer-support/payment-codes.asp)) |
| INT | Interest paid or charged | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| ITL | International | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| MPI / MPO | Mobile payment in / out | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes) |
| N-S TRN FEE | **Non-sterling transaction fee** | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| ERTF | Card fee for foreign use | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes) |
| NON-STG PURCH FEE / NON-STG TRANS FEE | Non-sterling purchase fee lines | [myPOS](https://www.mypos.com/en-gb/what-to-do-when-you-see-non-stg-purch-and-trans-fee-on-your-statement) |
| VRATE | Visa scheme exchange rate line | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| OTR | Online banking transaction | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| PAY / OTH | Payment / other (seen in Lloyds CSVs) | [Tool](https://github.com/ggirtsou/lloyds) |
| POS | Point of sale (debit card) transaction, NatWest | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| REM / REV | Barclays only: cheque paid in elsewhere / reversed or recalled payment | [MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes) |
| SO / S/O / STO | Standing order | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html), [HSBC](https://hsbc.co.uk/help/banking-made-easy/understanding-your-statement) |
| TFR / TRF | Transfer. **HSBC writes "TRF"**, others write "TFR" | [HSBC](https://hsbc.co.uk/help/banking-made-easy/understanding-your-statement), [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |
| VIS | Visa card payment (HSBC) | [HSBC](https://www.hsbc.co.uk/configuration/modals/check-our-most-frequently-disputed-transactions), [Community](https://community.quickfile.co.uk/t/hsbc-change-to-csv-format-march-2019/26354) |
| TEL / TLR / SBT / IBP / BSP | Telephone banking / teller / screen-based / inter-branch / branch single payment | [NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html) |

For a fintech type column, Monzo uses scheme names (pot transfer, Faster Payment, direct debit, card payment and so on) rather than 3-letter codes ([Official](https://community.monzo.com/t/csv-exports/89487/69)). Metro uses phrases such as "Account to Account Transfer" ([Official](https://www.metrobankonline.co.uk/globalassets/documents/customer_documents/business-and-commercial/user-guide-exporting-transaction-data.pdf)). Barclays uses phrases such as "Contactless Card Purchase" ([Vendor](https://beancount.io/tools/csv-to-beancount/barclays)).

### 1.4 Foreign card spend

- **Separate fee lines.** Big-bank statements show the non-sterling fee as its own line, coded N-S TRN FEE ([NatWest](https://natwest.com/support-centre/view-or-change-your-details/view-statements/do-you-have-a-list-of-statement-abbreviations.html)), ERTF ([MSE](https://www.moneysavingexpert.com/banking/bank-statement-codes)), or "NON-STG PURCH FEE" / "NON-STG TRANS FEE" ([myPOS](https://www.mypos.com/en-gb/what-to-do-when-you-see-non-stg-purch-and-trans-fee-on-your-statement)).
- **Typical fee levels** (third-party figures, so check each tariff):
  - Barclays: 2.75% on business debit cards and 2.99% on business credit cards ([Airwallex](https://www.airwallex.com/uk/blog/barclays-foreign-transaction-fees-explained)).
  - Lloyds: 2.99% plus £0.50 per purchase. HSBC and NatWest: 2.75% ([Wise](https://wise.com/gb/blog/non-sterling-transaction-fee)).
- **Fintechs:**
  - Monzo shows the original currency in `Local amount` and `Local currency`, charges no fee, and uses the Mastercard rate ([Community](https://community.monzo.com/t/no-notification-for-pending-transaction-settling-at-a-different-amount/114327)).
  - Revolut Business shows `Orig currency`, `Orig amount` and a `Fee` column ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/revolut)), but has given no exchange rate since October 2021 ([Community](https://community.revolut.com/t/since-october-2021-csv-exports-stopped-including-exchange-rate-information/210423)).
  - Barclaycard Business shows Original Amount, Original Currency and Conversion Rate ([Tool](https://raw.githubusercontent.com/bank2ynab/bank2ynab/master/bank2ynab.conf)).
  - Amex exports amounts already converted to GBP ([Vendor](https://reconcile-bvs.pages.dev/blogAmexPdfToCsv)).
- **Santander card lines** look like "CARD PAYMENT TO [merchant] ON [date]" ([statement excerpt](https://www.scribd.com/document/987493875)). Santander's terms say the scheme exchange rate and the sterling amount appear on the statement ([Official](https://www.santander.co.uk/assets/s3fs-public/AD_documents/business_credit_card_kfd_anb90352aug23.pdf)). The exact layout of a foreign-currency "RATE … /GBP" line was **not confirmed**.

### 1.5 What PDF statements show

- **HSBC.** A summary box gives IBAN, BIC, opening balance, payments in, payments out, closing balance and overdraft limit, plus sort code, account number and a **sheet number** on each page ([Official](https://hsbc.co.uk/help/banking-made-easy/understanding-your-statement)).
- **Barclays (from real statements, not an official template).** A summary of start balance, money out, money in and end balance. The columns are Date, Description, Money out, Money in, Balance. Each page break carries a "brought forward" line at the top of the next page and a "carried forward" line at the bottom of the previous one ([example](https://opencharities.uk/ew/1115652/files/2025-07-31-accounts.md), [search notes](https://ringshall-pc.gov.uk/assets/Parish-Council-Documents/Additional-Information/2023-2024/March-21st-2024/Business-Account-transactions-feb-march-24.pdf)).
- **Starling.** Each page carries a "True Copy" stamp, and fees from overdrafts or loans are shown ([Official](https://www.starlingbank.com/features/statements/)).
- **Revolut.** Only PDF statements can be signed and stamped ([Official](https://help.revolut.com/business/help/managing-my-business/viewing-my-account-statements/how-to-get-a-monthly-statement/)).
- **Tide.** Statements show the legal name, trading name and registered address. A sole trader's shows their full personal name ([Official](https://www.tide.co/help-centre/download-tide-account-statements-and-transactions/)).
- **Metro.** "Download" produces a PDF transaction report covering the last 32 days ([Official](https://www.metrobankonline.co.uk/globalassets/documents/customer_documents/business-and-commercial/user-guide-exporting-transaction-data.pdf)).
- **CSV and PDF totals can disagree.** A CSV can differ from the PDF statement totals for the same calendar month ([Vendor](https://reconcile-bvs.pages.dev/blogHSBCPdfToCsv)).

### 1.6 Pending versus settled transactions

- **Revolut.** Rows carry a State of COMPLETED, PENDING, REVERTED or DECLINED. Pending rows can have a blank completed date, and the advice is to filter to COMPLETED ([Vendor](https://ledgerbridge-2ja.pages.dev/convert/revolut)).
- **Tide.** One export option is "Cleared only" ([Official](https://www.tide.co/help-centre/download-tide-account-statements-and-transactions/)).
- **NatWest Bankline.** Separate ledger and cleared balances are exported, including last night's and today's figures ([Official](https://www.natwest.com/content/dam/natwest_com/Business_and_Content/PDFs/Export-file-layout-guide-Bankline-CSV-format.pdf)).
- **Card pre-authorisations change.** Hotel, fuel and car-hire holds often settle at a different amount. The final charge can post as a separate payment while the hold lingers; one user had a £150 hold stuck while £121.45 was charged ([Community](https://community.monzo.com/t/hotel-authorisations/142771), [explainer](https://intercom.help/exa-app/en/articles/11498255-why-your-final-transaction-amount-might-differ-from-the-initial-value-for-card-purchases)).
- **Pending authorisations in bank feeds.** A pending authorisation can stay in a feed alongside the final charge ([Community](https://quickbooks.intuit.com/learn-support/en-au/banking/duplicate-credit-card-pending-authorization-charge-in-bank-feed/00/641281)). Some banks show the authorisation at once and then change its description and date when it settles ([Community](https://community.quickfile.co.uk/t/barclaycard-credit-card-auto-feed/22122)).
- **Xero.** Feeds reportedly import only cleared transactions ([Vendor](https://www.saasant.com/blog/xero-bank-feed-late-missing-transactions-fix)).

### 1.7 HMRC as a payee in bank narratives

| Tax | Account name | Sort code / account | Payment reference | Source |
|---|---|---|---|---|
| VAT | **HMRC VAT** | 08 32 00 / 11963155 | 9-digit VAT number with no spaces. Penalties use a 14-character reference starting with X | [GOV.UK](https://www.gov.uk/pay-vat/pay-using-another-payment-method) |
| Corporation Tax | **HMRC Cumbernauld** or **HMRC Shipley** | 08 32 10 / 12001039 or 12001020 | 17-character CT payment reference, which changes each accounting period | [GOV.UK](https://www.gov.uk/pay-corporation-tax/bank-details) |
| PAYE / CIS | **HMRC Cumbernauld** | 08 32 10 / 12001039 | 13-character Accounts Office reference, with 4 extra digits for early or late payments | [GOV.UK](https://www.gov.uk/pay-paye-tax/pay-using-another-payment-method) |
| Self Assessment | **HMRC Cumbernauld** or **HMRC Shipley** | 08 32 10 / 12001039 or 12001020 | 10-digit UTR followed by **K** (11 characters) | [GOV.UK](https://www.gov.uk/pay-self-assessment-tax-bill/bank-details) |

- **VAT Direct Debit.** It is collected **3 working days after** the return's payment deadline, so the bank date falls after the deadline ([GOV.UK](https://www.gov.uk/pay-vat/direct-debit)).
- **PAYE deadline.** PAYE is due by the **22nd of the next tax month**, or the 19th if paying by cheque ([GOV.UK](https://www.gov.uk/pay-paye-tax/bank-details)).

---

## 2. UK VAT facts, 2023 to 2027

### 2.1 Rates

| Rate | % | Common examples | Source |
|---|---|---|---|
| Standard | 20% | Most goods and services: alcohol, catering, hot takeaways, pet food, UK freight | [GOV.UK](https://www.gov.uk/vat-rates), [GOV.UK](https://www.gov.uk/guidance/rates-of-vat-on-different-goods-and-services) |
| Reduced | 5% | Domestic fuel and power, children's car seats, mobility aids for older people, nicotine patches and gum | [GOV.UK](https://www.gov.uk/guidance/rates-of-vat-on-different-goods-and-services) |
| Zero | 0% | Most food (not catering, alcohol, confectionery, crisps, hot food, soft drinks), books and newspapers, children's clothes, sanitary products, passenger transport in vehicles carrying 10 or more, household water. **Energy-saving materials in homes are zero-rated until 31 March 2027** | [GOV.UK](https://www.gov.uk/guidance/rates-of-vat-on-different-goods-and-services) |
| Exempt | — | Insurance, finance, residential rent (a lease or licence to occupy), Royal Mail universal postal service, education by eligible bodies (not private schools) | [GOV.UK](https://www.gov.uk/guidance/rates-of-vat-on-different-goods-and-services) |
| **Temporary 5%** | 5% | **25 June 2026 to 1 September 2026 inclusive.** Covers eat-in children's meals, child and family admissions to cinemas, theatres, concerts and exhibitions, and all admissions to family attractions such as zoos, soft play, theme parks and museums. Excludes takeaway meals, sports events and facilities, and any meal that includes alcohol. It was announced 21 May 2026 | [GOV.UK](https://www.gov.uk/government/publications/temporary-reduced-rate-of-vat-for-childrens-meals-tickets-and-family-attractions/temporary-reduced-rate-of-vat-for-childrens-meals-and-family-attractions), [ICAEW](https://www.icaew.com/insights/tax-news/2026/may-2026/vat-rate-reduced-for-families-over-the-summer-holidays) |

### 2.2 Registration thresholds

| Period | Register if taxable turnover over | Deregister if under | Source |
|---|---|---|---|
| 1 April 2017 to 31 March 2024 | £85,000 | £83,000 | [GOV.UK policy paper](https://gov.uk/government/publications/vat-increasing-the-registration-and-deregistration-thresholds/increasing-the-vat-registration-threshold), [SI 2024/307](https://www.legislation.gov.uk/uksi/2024/307/pdfs/uksi_20240307_en.pdf) |
| From 1 April 2024, unchanged through 2026/27 | **£90,000** | **£88,000** | [GOV.UK](https://www.gov.uk/how-vat-works/vat-thresholds), [Notice 700/11 supplement](https://www.gov.uk/government/publications/vat-notice-70011-cancelling-your-registration/vat-notice-70011-supplement) |

### 2.3 VAT invoices (Notice 700, section 16)

- **Full VAT invoice (16.3.1).** It must show:
  - a sequential number and the time of supply;
  - your name, address and VAT number, and the customer's name and address;
  - a description, quantity and unit price for each line, with its VAT rate and amount;
  - the total excluding VAT, any cash discount, and the **total VAT in sterling**.
  
  It must be issued to a VAT-registered customer for standard- or reduced-rated supplies, normally **within 30 days of the tax point** (16.2.3) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Simplified (less detailed) invoice (16.6.1).**
  - Allowed only if the supply is **£250 or less** and the customer agrees.
  - It needs the supplier's name, address and VAT number, the time of supply, a description, and for each rate the VAT-inclusive total and the rate.
  - **It does not show a VAT amount**, so the buyer works the VAT out with the VAT fraction (20/120 = 1/6) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Retailers' invoices (16.6.2).** The same £250 ceiling and contents apply, but exempt supplies cannot be included. Above £250, or whenever the customer asks, a full invoice is needed. Card vouchers can be adapted as the invoice, but only one document per sale may be a VAT invoice ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)). The older term "modified VAT invoice" (VAT-inclusive line values with net, VAT and gross totals) **did not appear** in the current Notice 700 text that was fetched.
- **Till rolls** count as VAT invoices only for cash-and-carry wholesalers (17.2). Otherwise a full invoice must be issued on request ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Pro-forma invoices** cannot be used to reclaim input tax and should be marked "not a VAT invoice" (17.3) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Rounding** ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)):
  - Invoice traders may round the total VAT on an invoice **down** to a whole penny.
  - Line-level VAT may be rounded to the nearest 0.1p, or to the nearest 1p or 0.5p, applied consistently (17.5).
  - Retailers must not round down systematically (17.6).
- **Foreign currency** ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)):
  - The net amount can be in any currency, but **the VAT must be converted to sterling** (16.3.1, 16.4).
  - Allowed rates are the UK market selling rate at the time of supply, the HMRC period rate, or a rate HMRC has agreed in writing.
  - **Forward rates are not acceptable** (7.6).
- **Credit notes (18.2.3, 18.2.5–18.2.6).** A credit note must reflect a genuine error, overcharge or agreed reduction. It must quote the original invoice number and date, and show the VAT rate and amount in sterling. It uses the VAT rate at the original tax point, and output tax is adjusted in the period the refund is paid ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)). After a rate change, a credit note should be issued within 45 days (30.7.5) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Electronic invoices** must carry the same information as paper ones (17.7) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).

### 2.4 Tax point, deposits and part payments (Notice 700, section 14)

- **Basic tax point.** For goods it is the dispatch or collection date. For services it is when the work is finished (14.2.1) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Actual tax point.** A VAT invoice issued, or a payment received, **before** the basic tax point creates a tax point for that amount. Book entries such as contra settlements count as payment (14.2.2(a)) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **14-day rule.** An invoice issued within 14 days **after** the basic tax point moves the tax point to the invoice date, unless the business has opted out in writing. After 14 days without HMRC approval, the basic tax point stands (14.2.2(b)) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Deposits.** Most deposits are advance payments and create a tax point **when received**. Refundable security deposits do not (14.2.3) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).
- **Continuous supplies.** Each invoice or payment, whichever comes first, creates a tax point. One invoice can cover up to a year of scheduled payments (14.3) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)).

### 2.5 Flat Rate Scheme (Notice 733)

**Thresholds and special rules**

- **Join and leave.** A business can join with expected taxable turnover of **£150,000 or less (excluding VAT)**. It must leave when VAT-inclusive income goes over **£230,000** ([Notice 733](https://www.gov.uk/government/publications/vat-notice-733-flat-rate-scheme-for-small-businesses/vat-notice-733-flat-rate-scheme-for-small-businesses)).
- **Turnover base.** The flat rate applies to **VAT-inclusive** turnover (8.1) ([Notice 733](https://www.gov.uk/government/publications/vat-notice-733-flat-rate-scheme-for-small-businesses/vat-notice-733-flat-rate-scheme-for-small-businesses)).
- **First year.** The rate is reduced by 1% in the first year of registration ([GOV.UK](https://www.gov.uk/vat-flat-rate-scheme/how-much-you-pay)).
- **Limited cost trader, 16.5%.** This rate applies if spending on "relevant goods" is under 2% of turnover, or under £1,000 a year.
  - Relevant goods **exclude** food and drink for the owner or staff, vehicle costs and fuel (unless in the transport sector), capital goods, and all services ([Notice 733](https://www.gov.uk/government/publications/vat-notice-733-flat-rate-scheme-for-small-businesses/vat-notice-733-flat-rate-scheme-for-small-businesses)).
- **Capital goods of £2,000 or more** (including VAT, single purchase). The VAT is reclaimed in box 4, outside the flat rate ([Notice 733](https://www.gov.uk/government/publications/vat-notice-733-flat-rate-scheme-for-small-businesses/vat-notice-733-flat-rate-scheme-for-small-businesses)).
- **Postponed import VAT.** Since 1 June 2022 it is accounted for separately, outside flat-rate turnover ([GOV.UK](https://www.gov.uk/guidance/complete-your-vat-return-to-account-for-import-vat)).
- **Reverse charge.** Reverse-charge supplies are excluded from the flat-rate calculation ([GOV.UK](https://www.gov.uk/guidance/vat-reverse-charge-technical-guide)).

**Rates for common trades**

| Trade | % | Trade | % |
|---|---|---|---|
| Accountancy or book-keeping | 14.5 | Labour-only building or construction (materials under 10% of turnover) | 14.5 |
| Computer and IT consultancy | 14.5 | General building or construction | 9.5 |
| Management consultancy | 14 | Hairdressing or beauty | 13 |
| Lawyer or legal services | 14.5 | Photography | 11 |
| Architect, surveyor, engineer | 14.5 | Transport, couriers, taxis | 10 |
| Estate agency or property management | 12 | Catering and takeaways (from 1 April 2022) | 12.5 |
| Business services not listed elsewhere | 12 | Pubs (from 1 April 2022) | 6.5 |
| Retailing not listed elsewhere | 7.5 | Hotel or accommodation (from 1 April 2022) | 10.5 |
| Retailing food, confectionery, newspapers | 4 | Repairing vehicles | 8.5 |
| Advertising | 11 | **Limited cost business** | **16.5** |

Source: [GOV.UK FRS rates](https://www.gov.uk/vat-flat-rate-scheme/how-much-you-pay)

### 2.6 Cash accounting

- **Thresholds.** A business can join with taxable turnover of **£1.35m or less** and must leave above **£1.6m** ([GOV.UK](https://www.gov.uk/vat-cash-accounting-scheme), [GOV.UK eligibility](https://www.gov.uk/vat-cash-accounting-scheme/eligibility)).
- **Timing.** VAT on sales is due when the customer pays, and VAT on purchases is reclaimed when the supplier is paid ([GOV.UK](https://www.gov.uk/vat-cash-accounting-scheme)).
- **Excluded transactions.** Invoices with payment terms of 6 months or more, invoices raised in advance, lease purchase, hire purchase, conditional sale and credit sale, EU imports into Northern Ireland, and goods leaving a customs warehouse ([GOV.UK eligibility](https://www.gov.uk/vat-cash-accounting-scheme/eligibility)).
- **No cash accounting for reverse-charge supplies**, whether made or received ([GOV.UK](https://www.gov.uk/guidance/vat-reverse-charge-technical-guide)).
- **No bad debt relief is needed** under cash accounting ([Notice 700/18](https://www.gov.uk/guidance/relief-from-vat-on-bad-debts-notice-70018)).

### 2.7 Domestic reverse charge for construction (CIS)

Source for this section: [GOV.UK technical guide](https://www.gov.uk/guidance/vat-reverse-charge-technical-guide).

- **Start.** It applies to invoices with a tax point **on or after 1 March 2021**.
- **Scope.** Standard- and reduced-rated building services between VAT-registered businesses where the payment is reported under CIS.
- **Not covered.** Services to **end users** or **intermediary suppliers** who have notified in writing, zero-rated work (e.g. new-build housing), and materials-only orders outside CIS.
- **5% disregard.** If the reverse-charge element is 5% or less of the whole contract, it can be disregarded. This is agreed up front at contract level, not invoice by invoice.
- **Invoice wording.** The invoice must say "reverse charge", e.g. "VAT Act 1994 Section 55A applies" or "Customer to pay the VAT to HMRC".
- **VAT return.**
  - The **supplier** records no output tax, only the net value of the sale.
  - The **customer** adds the VAT to output tax and reclaims it as input tax on the same return.

### 2.8 Imports and services from abroad

- **Postponed import VAT (PIVA).** Using it needs no approval ([GOV.UK](https://www.gov.uk/guidance/check-when-you-can-account-for-import-vat-on-your-vat-return)). Figures come from the **monthly online statement**, and are entered as follows ([GOV.UK](https://www.gov.uk/guidance/complete-your-vat-return-to-account-for-import-vat)):
  - **Box 1:** the import VAT due.
  - **Box 4:** the same VAT reclaimed.
  - **Box 7:** the value of imports excluding VAT.
- **B2B general-rule services from overseas suppliers.** The UK customer accounts for the VAT ([Notice 741A, 5.1–5.2](https://www.gov.uk/guidance/vat-place-of-supply-of-services-notice-741a)):
  - **Box 1:** output tax.
  - **Box 4:** input tax.
  - **Boxes 6 and 7:** the full value of the supply.
  - This still applies if the overseas supplier shows a UK VAT number (5.17).

### 2.9 Road fuel scale charges (VAT-inclusive charge / VAT element, £)

The new table applies from the **first VAT period starting on or after 1 May** each year. CO2 figures are rounded **down** to the nearest 5 ([GOV.UK 2026](https://www.gov.uk/guidance/vat-road-fuel-scale-charges-from-1-may-2026-to-30-april-2027)).

| CO2 g/km | Period | 2023/24 ([src](https://www.gov.uk/guidance/vat-road-fuel-scale-charges-from-1-may-2023-to-30-april-2024)) | 2024/25 ([src](https://www.gov.uk/guidance/vat-road-fuel-scale-charges-from-1-may-2024-to-30-april-2025)) | 2025/26 ([src](https://www.gov.uk/guidance/vat-road-fuel-scale-charges-from-1-may-2025-to-30-april-2026)) | 2026/27 ([src](https://www.gov.uk/guidance/vat-road-fuel-scale-charges-from-1-may-2026-to-30-april-2027)) |
|---|---|---|---|---|---|
| 120 or less | 12 months | 737 / 122.83 | 702 / 117.00 | 661 / 110.17 | 657 / 109.50 |
| | 3 months | 183 / 30.50 | 174 / 29.00 | 164 / 27.33 | 163 / 27.17 |
| | 1 month | 61 / 10.17 | 58 / 9.67 | 54 / 9.00 | 54 / 9.00 |
| 140 | 3 months | 331 / 55.17 | 315 / 52.50 | 297 / 49.50 | 294 / 49.00 |
| 160 | 3 months | 405 / 67.50 | 385 / 64.17 | 363 / 60.50 | 361 / 60.17 |
| 180 | 3 months | 478 / 79.67 | 455 / 75.83 | 429 / 71.50 | 426 / 71.00 |
| 200 | 3 months | 552 / 92.00 | 526 / 87.67 | 496 / 82.67 | 492 / 82.00 |
| 225 or more | 12 months | 2,578 / 429.67 | 2,454 / 409.00 | 2,314 / 385.67 | 2,297 / 382.83 |
| 225 or more | 3 months | 644 / 107.33 | 613 / 102.17 | 578 / 96.33 | 574 / 95.67 |

The VAT element is the charge ÷ 6 ([GOV.UK](https://www.gov.uk/guidance/vat-road-fuel-scale-charges-from-1-may-2026-to-30-april-2027)).

### 2.10 Motoring and entertainment

Source for cars and fuel: [Notice 700/64](https://www.gov.uk/guidance/vat-on-motoring-expenses-notice-70064).

- **Car leasing.** **50% of the VAT on leasing a car with any private use is blocked** (4.2). The block does not apply to:
  - taxis and driving instruction (4.3);
  - hire of **10 days or less** used specifically for business, where no company car is being replaced (4.4).
  
  Maintenance charged separately is recoverable.
- **Buying a car.** Input VAT is generally not recoverable unless the car is used exclusively for business (pool cars), is stock, or is used as a taxi, for driving instruction or for self-drive hire.
- **Fuel.** There are four options:
  - reclaim all the VAT and pay the scale charge;
  - reclaim only business fuel, using mileage records;
  - reclaim none;
  - reclaim all if there is no private use.
- **Mileage allowances.** The reclaimable VAT is the fuel element × 1/6, backed by fuel receipts. Advisory fuel rates are acceptable for working out the fuel element.
- **Business entertainment** ([Notice 700/65](https://www.gov.uk/guidance/business-entertainment-and-vat-notice-70065)):
  - VAT on entertaining **non-employees** (UK clients) is blocked.
  - Staff parties and staff entertainment are recoverable.
  - Mixed events are apportioned.
  - Entertainment for directors or partners alone is not recoverable, but it is when they attend a staff party.
  - Entertaining overseas customers may be recoverable if reasonable.
  - Employee subsistence while travelling is not entertainment.

### 2.11 Return periods, deadlines and MTD

- **Quarterly staggers** (Notice 700, 20.3.1) ([GOV.UK](https://www.gov.uk/guidance/vat-guide-notice-700)):
  - Group 1: quarters ending Mar / Jun / Sep / Dec.
  - Group 2: quarters ending Jan / Apr / Jul / Oct.
  - Group 3: quarters ending Feb / May / Aug / Nov.
  - Monthly returns are available to repayment traders.
  - Non-standard period ends are allowed within ±14 days (monthly) or ±20 days (quarterly) of a standard date.
- **Deadline.** The return and the payment are due **1 calendar month and 7 days** after the period end. The deadline does **not** move for weekends or bank holidays ([GOV.UK](https://www.gov.uk/vat-returns/deadlines)).
- **Making Tax Digital for VAT.** It is mandatory for **all VAT-registered businesses from 1 April 2022**, regardless of turnover ([GOV.UK press release](https://www.gov.uk/government/news/less-than-one-week-to-go-for-mtd), [GOV.UK](https://www.gov.uk/guidance/check-when-a-business-must-follow-the-rules-for-making-tax-digital-for-vat)).
  - The rule applies from the first VAT period starting on or after 1 April 2022 ([Avalara](https://www.avalara.com/vatlive/en/vat-news/extension-of-the-uks-making-tax-digital-for-vat-from-april-2022.html)).
  - Digital links are required, and copy-and-paste does not count as one ([Notice 700/22](https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat/vat-notice-70022-making-tax-digital-for-vat)).
  - The digital records must hold the tax point, net value and rate for each sale, and the tax point, value and input tax for each purchase ([Notice 700/22](https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat/vat-notice-70022-making-tax-digital-for-vat)).
- **Bad debt relief** ([Notice 700/18](https://www.gov.uk/guidance/relief-from-vat-on-bad-debts-notice-70018)):
  - The debt must be at least **6 months** past the later of the due date and the supply date.
  - It must be written off to a separate bad-debt account, and claimed within **4 years 6 months**.
  - The claim goes in **box 4**. Money later recovered is repaid in **box 1**.
  - Part payments are allocated to the **earliest supply** unless the customer specifies otherwise.
  - A customer who hasn't paid within 6 months must repay the input tax they claimed.

---

## 3. UK tax and payroll facts by tax year

### 3.1 Payroll, NI and income tax

| Item | 2023/24 | 2024/25 | 2025/26 | 2026/27 |
|---|---|---|---|---|
| Personal allowance | £12,570 | £12,570 | £12,570 | £12,570 |
| Basic rate band / additional rate starts | £37,700 / £125,140 | same | same | same |
| Employee Class 1 main rate (category A) | **12% to 5 January 2024, 10% from 6 January 2024** | 8% | 8% | 8% |
| Employee rate above UEL | 2% | 2% | 2% | 2% |
| LEL / PT / UEL (yearly) | £6,396 / £12,570 / £50,270 | £6,396 / £12,570 / £50,270 | £6,500 / £12,570 / £50,270 | £6,708 / £12,570 / £50,270 |
| **Employer secondary threshold** | £9,100 | £9,100 | **£5,000** | £5,000 |
| **Employer Class 1 / 1A / 1B rate** | 13.8% | 13.8% | **15%** | 15% |
| **Employment Allowance** | £5,000 | £5,000 | **£10,500** | £10,500 |
| Class 4 main / upper rate | 9% / 2% | **6%** / 2% | 6% / 2% | 6% / 2% |
| Class 2 weekly rate / small profits threshold | £3.45 / £6,725 | £3.45 / £6,725 | £3.50 / £6,845 | £3.65 / £7,105 |
| **Approved mileage, car** (first 10,000 miles, then above) | 45p / 25p | 45p / 25p | 45p / 25p | **55p / 25p** (retrospective to 6 April 2026) |
| Approved mileage, motorcycle / bicycle | 24p / 20p | 24p / 20p | 24p / 20p | 24p / 20p |
| National Living Wage (top band) | **£10.42 (age 23+)**; £10.18 (21–22) | **£11.44 (21+)** | £12.21 | £12.71 |
| NMW age 18–20 | £7.49 | £8.60 | £10.00 | £10.85 |
| NMW under 18 / apprentice | £5.28 | £6.40 | £7.55 | £8.00 |
| SSP weekly | £109.40 | £116.75 | £118.75 | £123.25 **or 80% of average weekly earnings if lower** |
| SMP / SPP standard weekly rate | £172.48 | £184.03 | £187.18 | £194.32 |
| Apprenticeship Levy | 0.5% of pay bill over £3m (£15k allowance) | same | same | same |

**Sources for the table**

- Payroll pages by year: [2023/24](https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2023-to-2024), [2024/25](https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2024-to-2025), [2025/26](https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2025-to-2026), [2026/27](https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027).
- Class 2 and Class 4: [GOV.UK NI rates](https://www.gov.uk/government/publications/rates-and-allowances-national-insurance-contributions/rates-and-allowances-national-insurance-contributions).
- Income tax bands: [GOV.UK income tax rates](https://www.gov.uk/government/publications/rates-and-allowances-income-tax/income-tax-rates-and-allowances-current-and-past).

**Notes on the table**

- **55p mileage rate.** It was announced 21 May 2026 and added to the GOV.UK payroll page on 5 June 2026. It covers cars and vans, and the self-employed simplified mileage rate also rises to 55p from 6 April 2026 ([policy paper, 17 June 2026](https://www.gov.uk/government/publications/increase-to-approved-mileage-allowance-payments-amaps-and-self-employed-simplified-mileage-rates/increasing-mileage-rates)). Employers who paid 45p can top up to 55p tax-free ([ATT](https://www.att.org.uk/technical/news/increased-hmrc-approved-mileage-rates-business-travel-announced)).
- **Employment Allowance.** From April 2025, employers with more than £100,000 of Class 1 liabilities can claim. A company whose only director is its only employee liable for secondary Class 1 still cannot ([GOV.UK](https://www.gov.uk/claim-employment-allowance/eligibility)).
- **Class 2.** From 2024/25, people with profits at or above the small profits threshold are treated as having paid Class 2. Below it, contributions are voluntary ([GOV.UK](https://www.gov.uk/self-employed-national-insurance-rates)). The 6 April 2024 start date comes from the reform history and was **not stated** on the page that was fetched.
- **April 2027.** The National Living Wage rises to **£13.21**, 18–20s to £11.27, and under-18s and apprentices to £8.31, just after the corpus window ([GOV.UK](https://www.gov.uk/government/news/lpc-recommendations-take-the-national-living-wage-to-1321)).

### 3.2 Company and investor taxes

| Item | 2023/24 | 2024/25 | 2025/26 | 2026/27 | Source |
|---|---|---|---|---|---|
| Corporation tax: small profits / main rate | 19% / 25% (FY2023) | 19% / 25% | 19% / 25% | 19% / 25% (FY2026) | [GOV.UK](https://www.gov.uk/government/publications/rates-and-allowances-corporation-tax/rates-and-allowances-corporation-tax) |
| Marginal relief band, standard fraction | £50k–£250k, 3/200 | same | same | same | [GOV.UK](https://www.gov.uk/government/publications/rates-and-allowances-corporation-tax/rates-and-allowances-corporation-tax) |
| Dividend allowance | £1,000 | £500 | £500 | £500 | [GOV.UK](https://www.gov.uk/government/publications/rates-and-allowances-income-tax/income-tax-rates-and-allowances-current-and-past) |
| Dividend rates: ordinary / upper / additional | 8.75 / 33.75 / 39.35% | same | same | **10.75 / 35.75 / 39.35%** | [GOV.UK](https://www.gov.uk/tax-on-dividends), [HMT technical note](https://www.gov.uk/government/publications/changes-to-tax-rates-for-property-savings-and-dividend-income/change-to-tax-rates-for-property-savings-and-dividend-income-technical-note) |
| s455 on overdrawn director loans | 33.75% (loans made from 6 April 2022) | 33.75% | 33.75% | **35.75%**, tied to the dividend upper rate | [HMT technical note](https://www.gov.uk/government/publications/changes-to-tax-rates-for-property-savings-and-dividend-income/change-to-tax-rates-for-property-savings-and-dividend-income-technical-note), [Hillier Hopkins](https://hillierhopkins.co.uk/insight-posts/loans-to-directors-tax-rate-increased/) |

**Notes on the table**

- **Associated companies and short periods.** The marginal relief limits are divided by the number of associated companies plus one, and pro-rated for periods shorter than 12 months. With 3 associates the limits are £12,500 and £62,500 ([GOV.UK](https://www.gov.uk/guidance/corporation-tax-marginal-relief)).
- **s455 detail.**
  - The GOV.UK guide for directors still says 33.75%, or 32.5% for loans made before 6 April 2022 ([GOV.UK](https://www.gov.uk/directors-loans/you-owe-your-company-money)).
  - Commentators disagree on whether 35.75% applies by **loan date** (on or after 6 April 2026) or by **accounting period**.
  - A search result reported that HMRC's CT online service won't support the new rate until 6 April 2027, so returns filed before then would need amending. This is **unverified**: the page that said it was not pinned down, though [Tax Insider](https://www.taxinsider.co.uk/tax-articles/loans-to-participators-an-increase-in-the-section-455-charge) covers the rate rise.
  - The tax is repayable 9 months and 1 day after the end of the period in which the loan is repaid ([GOV.UK](https://www.gov.uk/directors-loans/you-owe-your-company-money)).
- **Director loan anti-avoidance and benefits** ([GOV.UK](https://www.gov.uk/directors-loans/you-owe-your-company-money)):
  - **30-day rule:** repaying over £5,000 and re-borrowing £5,000 or more within 30 days.
  - **Arrangements rule:** a loan of £15,000 or more with arrangements to re-borrow.
  - **Benefit in kind:** owing over **£10,000** at any time in the year is a benefit, taxed at the official interest rate.

### 3.3 Self-employed, partnerships and property

**Basis period reform**

- Profits are taxed on a **tax-year basis from 2024/25**. 2023/24 was the **transition year**: the normal 12 months plus a transition component running to 5 April 2024.
- Overlap relief was used up in 2023/24.
- Extra transition profit is **spread over 5 years by default** ([GOV.UK](https://www.gov.uk/government/publications/basis-period-reform/basis-period-reform)), at 20% a year, and any remainder is accelerated if the business ceases ([Kingsley Napley](https://www.kingsleynapley.co.uk/insights/blogs/dispute-resolution-law-blog/basis-period-adjustments)).

**Cash basis**

- **The default from 2024/25.** The £150k entry and £300k exit limits, the £500 interest cap and the loss-relief restrictions were all removed ([GOV.UK](https://gov.uk/government/publications/expanding-the-income-tax-cash-basis-for-self-employed-individuals-and-partnerships/expanding-the-cash-basis)).
- **Who can't use it.** Companies, **LLPs** and partnerships with corporate members ([BIM72010](https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim72010)).
- **For the corpus.** The **LLP client must use accruals**, while the sole trader and the partnership of individuals will probably be on the cash basis.

**Making Tax Digital for Income Tax**

- **Who must join, and when** ([GOV.UK](https://www.gov.uk/guidance/check-if-youre-eligible-for-making-tax-digital-for-income-tax)):
  - From **6 April 2026** if qualifying income in 2024/25 was over **£50,000**.
  - From 6 April 2027 if over £30,000 in 2025/26.
  - From 6 April 2028 if over £20,000 in 2026/27.
- **Partnerships** will follow later, with no date yet ([GOV.UK](https://www.gov.uk/guidance/check-if-youre-eligible-for-making-tax-digital-for-income-tax)).
- **Qualifying income** is the gross turnover from self-employment and property, including a share of jointly owned property. It excludes partnership profit shares, PAYE pay and dividends ([GOV.UK](https://www.gov.uk/guidance/work-out-your-qualifying-income-for-making-tax-digital-for-income-tax)).
- **Quarterly updates** are cumulative from 6 April and due by **7 August, 7 November, 7 February and 7 May**. Businesses can instead elect calendar quarters (1 April to 30 June and so on), with the same deadlines ([GOV.UK](https://www.gov.uk/guidance/use-making-tax-digital-for-income-tax/send-quarterly-updates)).

**Other self-employed and property points**

- **Use of home flat rates** for the self-employed: **£10, £18 or £26 a month** for 25–50, 51–100 or 101+ hours ([GOV.UK](https://www.gov.uk/simpler-income-tax-simplified-expenses/working-from-home)).
- **Mixed-use costs.** Only the business part is allowable, and money taken for personal use is not an expense. The £1,000 trading allowance replaces actual expenses ([GOV.UK](https://www.gov.uk/expenses-if-youre-self-employed)).
- **Section 24 (residential finance costs)** ([GOV.UK](https://www.gov.uk/guidance/changes-to-tax-relief-for-residential-landlords-how-its-worked-out-including-case-studies)):
  - Finance costs give no deduction. Instead there is a **20% tax reduction** on the lowest of finance costs, property profits and adjusted total income above the personal allowance.
  - Any unused amount carries forward.
  - It has been fully in force since 2020/21.
- **From 6 April 2027** (just after the window), property income rates become 22%, 42% and 47%, and the finance-cost credit rises to 22% ([HMT technical note](https://www.gov.uk/government/publications/changes-to-tax-rates-for-property-savings-and-dividend-income/change-to-tax-rates-for-property-savings-and-dividend-income-technical-note)).
- **Furnished holiday lettings regime abolished** from 6 April 2025 for income tax and from 1 April 2025 for corporation tax ([PIM4190](https://www.gov.uk/hmrc-internal-manuals/property-income-manual/pim4190), [Deloitte](https://taxscape.deloitte.com/measures-spring-budget-2024/furnished-holiday-lettings-tax-regime-abolished-from-6-april-2025.aspx)).

### 3.4 Capital allowances

| Measure | Rule | Source |
|---|---|---|
| Annual Investment Allowance | **£1m** since 1 January 2019, pro-rated for short periods. Not for cars | [GOV.UK](https://www.gov.uk/capital-allowances/annual-investment-allowance) |
| Full expensing | **Companies only.** 100% on new, unused main-pool plant and 50% first-year allowance on special-rate plant, from 1 April 2023, made permanent in November 2023. Excludes cars and assets for leasing | [GOV.UK](https://gov.uk/government/publications/capital-allowances-permanent-full-expensing/capital-allowances-permanent-full-expensing-for-companies-investing-in-plant-and-machinery), [ACCA](https://www.accaglobal.com/uk/en/technical-activities/technical-resources-search/2023/november/Capital-allowances-and-full-expensing.html) |
| 40% first-year allowance | Main-rate spending **from 1 January 2026**, including by unincorporated businesses and on leased assets. Excludes second-hand assets and cars | [GOV.UK](https://www.gov.uk/government/publications/new-first-year-allowance-and-main-rate-of-writing-down-allowances/capital-allowances-new-first-year-allowance-and-reducing-main-rate-writing-down-allowances), [Deloitte](https://taxscape.deloitte.com/measures-autumn-budget-2025/capital-allowances--writing-down-allowances-rate-reduction-and-new-first-year-allowance.aspx) |
| Main-pool writing-down allowance | **18% → 14%** from 1 April 2026 (corporation tax) and 6 April 2026 (income tax), with hybrid rates for periods that straddle the date. Special-rate pool stays at 6% | [Deloitte](https://taxscape.deloitte.com/measures-autumn-budget-2025/capital-allowances--writing-down-allowances-rate-reduction-and-new-first-year-allowance.aspx), [GOV.UK](https://www.gov.uk/government/publications/reduce-the-main-rate-writing-down-allowance-and-increase-the-main-rate-first-year-allowance/capital-allowances-reduce-the-main-rate-writing-down-allowance-and-increase-the-main-rate-first-year-allowance) |
| Budget 28 October 2026 proposal | First-year allowance to **50% from 1 January 2027**. Main writing-down allowance to **12%** for periods starting from 1 April 2027 (corporation tax) and 6 April 2027 (income tax). This is in Finance Bill 2026-27 and **not yet confirmed as enacted** | [GOV.UK](https://www.gov.uk/government/publications/reduce-the-main-rate-writing-down-allowance-and-increase-the-main-rate-first-year-allowance/capital-allowances-reduce-the-main-rate-writing-down-allowance-and-increase-the-main-rate-first-year-allowance) |

### 3.5 Pensions, benefits and CIS

**Auto-enrolment**

- The earnings trigger is **£10,000**, and qualifying earnings run from **£6,240 to £50,270**. These figures held in every year from 2023/24 to 2026/27 ([TPR](https://www.thepensionsregulator.gov.uk/employers/new-employers/im-an-employer-who-has-to-provide-a-pension/declare-your-compliance/ongoing-duties-for-employers/earnings-thresholds)). They were frozen for 2026/27 ([GOV.UK review](https://www.gov.uk/government/publications/review-of-the-automatic-enrolment-earnings-trigger-and-qualifying-earnings-band-for-202627/review-of-the-automatic-enrolment-earnings-trigger-and-qualifying-earnings-band-for-202627)) and reportedly for 2027/28 ([LexisNexis](https://www.lexisnexis.co.uk/legal/news/automatic-enrolment-thresholds-to-remain-unchanged-for-2027-28)).
- Minimum contributions are **8% in total, with at least 3% from the employer** ([GOV.UK](https://www.gov.uk/workplace-pensions/what-you-your-employer-and-the-government-pay)).

**Trivial benefits**

- A benefit is trivial if it costs **£50 or less**, is not cash or a cash voucher, is not a reward for work, and is not contractual.
- Directors of **close companies** are capped at **£300 a tax year** ([GOV.UK](https://www.gov.uk/expenses-and-benefits-trivial-benefits/whats-exempt)).

**Construction Industry Scheme (CIS)**

- **Deduction rates:** **20%** for registered subcontractors, **30%** for unregistered ones, and **0%** for those with gross payment status ([GOV.UK](https://www.gov.uk/what-you-must-do-as-a-cis-contractor/make-deductions-and-pay-subcontractors)).
- **Deduction base:** the gross invoice minus VAT, materials, equipment hire, fuel (other than for travel) and prefabrication ([GOV.UK](https://www.gov.uk/what-you-must-do-as-a-cis-contractor/make-deductions-and-pay-subcontractors)).
- **Paperwork:**
  - A deduction statement goes to the subcontractor within 14 days of the tax month end, i.e. by the 19th ([GOV.UK](https://www.gov.uk/what-you-must-do-as-a-cis-contractor/make-deductions-and-pay-subcontractors)).
  - Monthly returns are due **by the 19th** for the tax month running 6th to 5th. A nil return is required when nothing was paid, unless the contractor has told HMRC it is inactive ([GOV.UK](https://www.gov.uk/what-you-must-do-as-a-cis-contractor/file-your-monthly-returns)).
- **Late-return penalties:** £100, then £200 at 2 months, then the greater of £300 or 5% at 6 and 12 months ([GOV.UK](https://www.gov.uk/what-you-must-do-as-a-cis-contractor/file-your-monthly-returns)).
- **Link to VAT:** CIS work also triggers the VAT domestic reverse charge (see 2.7).

---

## 4. Bookkeeping edge cases UK accountants warn about

Each item says what to plant in the corpus and why software trips on it.

1. **Bank feed duplicates.**
   - Reconnecting a feed can re-pull about 90 days of transactions that are already in the books ([Intuit community](https://accountants.intuit.com/community/intuit-tax-advisor-14/duplicate-transactions-in-the-bank-feed-after-the-bank-reconnected-best-way-to-clean-up-without-breaking-reconciliation-96912)).
   - A manually entered bill and the feed's payment can both end up in the ledger ([SaasAnt](https://www.saasant.com/blog/xero-bank-feed-late-missing-transactions-fix)).
   - Xero removed duplicates caused by an outage at its feed provider, Tink ([Xero status](https://status.xero.com/incidents/5x1l5d78pvtf)).
   - Monzo warns that re-syncing transactions already uploaded creates duplicates ([Monzo](https://monzo.com/help/business-accounts/historic-transactions-in-accounting-tools)).
   - AAT forum members describe bank entries keyed twice ([AAT forum](https://forums.aat.org.uk/Forum/discussion/444228/dealing-with-clearing-down-unreconciled-bank-transactions-from-2014-15-accounts-in-sage-50)).
   - **Plant:** the same transaction twice, once from CSV and once from the feed, sometimes with slightly different descriptions or dates. Also plant **genuine** identical repeat payments, such as two £4.50 coffees on the same day, which must not be merged.
2. **Pending authorisations that change.**
   - Hotel, fuel and car-hire holds settle at a different amount, or the final charge posts separately while the hold stays ([Monzo community](https://community.monzo.com/t/hotel-authorisations/142771)).
   - Some banks change the description and date of a transaction when it settles ([QuickFile](https://community.quickfile.co.uk/t/barclaycard-credit-card-auto-feed/22122)).
3. **A feed match is not a reconciliation.**
   - Matching proves a transaction exists, not that the books are complete. Timing differences are unpresented cheques and outstanding lodgements. Transposition errors leave a gap divisible by 9 ([summary of guides](https://www.pastpaperhero.com/resources/acca-fa1-bank-reconciliation-fundamentals-timing-differences-and-unpresented-items)).
   - Rolling unreconciled items forward month after month is a common mistake ([AAT Comment](https://www.aatcomment.org.uk/audience/members/month-end-accounting-mistakes-common-errors-and-how-to-avoid-them/)).
   - Unknown payments get parked in suspense, and bank charges are often left out ([ACCA](https://www.accaglobal.com/gb/en/student/exam-support-resources/foundation-level-study-resources/ffa/ffa-technical-articles/suspense-accounts-error-correction.html)).
   - **Plant:** a cheque issued in March that clears in April across a year end, a cash deposit made on 31 March that clears on 1 April, and bank-charge lines with no invoice.
4. **Payment processor payouts arrive net.**
   - Stripe, PayPal and SumUp deposits are net of fees. Sales should be recorded gross, with the fee as an expense, through a clearing account. Booking the net amount understates turnover and VAT ([QuickFile](https://support.quickfile.co.uk/t/accounting-for-income-from-a-payment-service-provider/8870), [beancount guide](https://beancount.io/blog/2026/05/18/reconciling-payment-processor-payouts-gross-sales-fees-refunds-chargebacks-rolling-reserves-clearing-account-guide)).
   - Processor fees are usually VAT-exempt, but check the provider's invoice ([QuickFile](https://support.quickfile.co.uk/t/accounting-for-income-from-a-payment-service-provider/8870)).
5. **Chargebacks are not refunds.**
   - The customer's bank reverses the payment, and the merchant pays a non-refundable fee (£10–£25 quoted) whether or not it wins ([Merchant Savvy](https://www.merchantsavvy.co.uk/card-processing-fees/chargebacks/), [Xero guide](https://www.xero.com/uk/guides/chargeback/)).
   - If the chargeback stands, reverse the sale and its VAT with a credit note. If the merchant wins, the VAT is unchanged ([zmartly](https://zmartly.co.uk/news-insights/woocommerce-refunds-chargebacks-vat-reversal), [QuickBooks community](https://quickbooks.intuit.com/learn-support/en-uk/transactions/chargebacks-from-merchant-services-provider/00/1504196)).
6. **Refunds and credit notes.**
   - A common error is recording a customer refund as a new cost rather than reduced income ([i24](https://i24app.com/uk/blog/what-are-the-most-common-accounting-mistakes-made-by-small-uk-businesses-1312), [1st Formations](https://help.1stformations.co.uk/accounting-service/common-bookkeeping-mistakes-to-avoid); it was not pinned down which of these blogs makes the point).
   - A credit note must reference the original invoice and use the original VAT rate, and the adjustment falls in the period of the refund ([Notice 700, 18.2](https://www.gov.uk/guidance/vat-guide-notice-700)).
   - Unmatched credit notes and unallocated deposits leave customer balances wrong ([i24](https://i24app.com/uk/blog/what-are-the-most-common-accounting-mistakes-made-by-small-uk-businesses-1312), [1st Formations](https://help.1stformations.co.uk/accounting-service/common-bookkeeping-mistakes-to-avoid)).
7. **Deposits and year-end cut-off.**
   - A deposit creates a VAT tax point when received, but a refundable security deposit does not ([Notice 700, 14.2.3](https://www.gov.uk/guidance/vat-guide-notice-700)).
   - In the accounts, a deposit taken before year end for work done afterwards is **deferred income** ([Trade2Base](https://www.trade2base.com/blog/trade-business-accruals-and-prepayments-uk)).
   - Missed accruals and prepayments, prior-month accruals not reversed (which double-counts), and income or costs booked to the wrong month are common errors ([AAT Comment](https://www.aatcomment.org.uk/audience/members/month-end-accounting-mistakes-common-errors-and-how-to-avoid-them/)).
8. **Part payments and bad debts.**
   - For VAT bad debt relief, part payments go to the earliest invoice. Relief starts 6 months after the later of the due date and the supply date, is claimed in box 4, and anything later recovered is repaid in box 1 ([Notice 700/18](https://www.gov.uk/guidance/relief-from-vat-on-bad-debts-notice-70018)).
   - **Plant:** an invoice paid in two instalments, and one written off after 7 months then partly paid.
9. **HMRC payment allocation.**
   - HMRC allocates payments to the **oldest debt first** unless told otherwise at the time of payment ([DMBM210120](https://www.gov.uk/hmrc-internal-manuals/debt-management-and-banking/dmbm210120), [HMRC community](https://community.hmrc.gov.uk/customerforums/sa/47e8d20c-d191-ee11-a81c-0022481a2027)).
   - VAT payments are often mis-posted as corporation tax ([AAT Comment](https://www.aatcomment.org.uk/audience/members/month-end-accounting-mistakes-common-errors-and-how-to-avoid-them/)).
   - **Plant:** payments to "HMRC CUMBERNAULD" whose reference shows whether they are PAYE (13-character reference), corporation tax (17 characters) or Self Assessment (UTR + K). "HMRC VAT" payments go to 08 32 00 / 11963155. Direct Debits are taken 3 working days after the deadline (see 1.7).
10. **Director's loan account and personal spending.**
    - In a company, personal costs paid from the business account go to the director's loan account. An overdrawn account triggers s455 if not cleared within 9 months, and owing over £10,000 is a benefit in kind ([GOV.UK](https://www.gov.uk/directors-loans/you-owe-your-company-money), [TaxAssist](https://www.taxassist.co.uk/resources/articles/seven-common-director-s-loan-account-mistakes-to-avoid)).
    - Mixing personal and business accounts is the most common mistake ([i24](https://i24app.com/uk/blog/what-are-the-most-common-accounting-mistakes-made-by-small-uk-businesses-1312)).
    - For a sole trader, money taken for personal use is not an allowable expense ([GOV.UK](https://www.gov.uk/expenses-if-youre-self-employed)).
    - **Plant:** repay-and-re-borrow patterns around year end to test the 30-day £5,000 rule.
11. **Foreign currency.**
    - VAT must be shown in sterling, at the UK market rate at the time of supply or the HMRC period rate. Forward rates are not allowed ([Notice 700, 7.6](https://www.gov.uk/guidance/vat-guide-notice-700)).
    - Bank lines carry a separate non-sterling fee (see 1.4), and Revolut CSVs give no exchange rate.
    - **Plant:** a USD software subscription with a reverse charge (boxes 1, 4, 6, 7; see 2.8), a EUR sales invoice, and a card spend with a separate N-S TRN FEE line.
12. **Assets, loans and payroll coded wrongly.**
    - Common errors include capital purchases expensed, vehicle loan repayments posted wholly to motor costs, and payroll (PAYE, NI and pension) posted straight to profit and loss without control accounts ([AAT Comment](https://www.aatcomment.org.uk/audience/members/month-end-accounting-mistakes-common-errors-and-how-to-avoid-them/)).
13. **Receipts that are not VAT invoices.**
    - A simplified invoice (£250 or less) has no VAT amount. Till rolls are generally not VAT invoices. Pro-formas can't support a claim. Reverse-charge construction invoices show no VAT but carry the reverse-charge wording ([Notice 700](https://www.gov.uk/guidance/vat-guide-notice-700), [reverse charge guide](https://www.gov.uk/guidance/vat-reverse-charge-technical-guide)).
    - Business entertainment VAT is blocked, staff parties are recoverable, and 50% of car-lease VAT is blocked (see 2.10).
14. **Rates that change part-way through a period.**
    - Employee NI changed on **6 January 2024**, not 6 April (see 3.1).
    - The temporary 5% VAT rate ran **25 June to 1 September 2026** (see 2.1).
    - Fuel scale charges change from the first VAT period starting on or after **1 May** (see 2.9).
    - Mileage moved to 55p **retrospectively** from 6 April 2026, announced 21 May 2026 (see 3.1).
    - The writing-down allowance is a hybrid rate for periods straddling 1 April 2026 (see 3.4).
    - The VAT registration threshold changed on **1 April 2024**, while the tax year starts on 6 April (see 2.2).

---

## 5. Format details that could not be confirmed

- **Barclays.** No official column list. The `Account` field's format (sort code and account number together) is unconfirmed. Whether rows run newest first is inferred from a tool option.
- **HSBC.** No official current CSV specification. The 2019 layout comes from a forum thread, and personal and business layouts may differ.
- **Lloyds.** The official payment-codes page and the commercial CSV PDF returned errors on fetch, so those details rely on search snippets. Halifax and Bank of Scotland were assumed to share the layout, which is unconfirmed.
- **NatWest online banking.** The 7-column CSV comes from one forum post. The date format and sign convention come only from a vendor.
- **Nationwide.** The exact wording of the 4 preamble lines and the **file encoding** (UTF-8 or Windows-1252 for "£") are unconfirmed.
- **Santander.** No column list for its CSV or "Excel" files beyond a 2018 blog. Whether the TXT export still exists is unconfirmed.
- **Starling.** When the `Spending Category` column and the opening-balance row appear is unconfirmed.
- **Revolut Business.** The column list comes from a vendor. Whether Business exports have a `State` column is unconfirmed.
- **Tide.** CSV column names not found.
- **Metro.** The only spec is from 2016, and the personal export may differ.
- **Amex UK.** Exact UK header labels are unconfirmed (the tool shows US-style "City/State" and "Zip Code"). The charges-positive convention comes from a vendor. OFX and QIF availability is disputed.
- **Barclaycard personal.** Column count differs between sources (7 or 8), and there are no header names.
- **Card narratives.** Exact text patterns such as "CARD PAYMENT TO … ON 12 MAR", and how a bank prints the foreign-currency rate line, were not confirmed for any bank.
- **Encoding and byte-order marks.** Apart from Santander TXT (Latin-1), no bank's encoding or BOM was confirmed.
- **OFX and QIF structure.** No bank's OFX or QIF content was examined, only whether the format is offered.
- **s455 at 35.75%.** Whether it applies by loan date or by accounting period is disputed among commentators.
