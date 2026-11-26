import pymupdf, sys
def pdf(name, lines):
    d = pymupdf.open(); p = d.new_page(); y = 60
    for ln in lines:
        p.insert_text((50, y), ln, fontsize=10); y += 15
    d.save(name)

# Starling current account, October 2026. Opening 8,200.00 (April-Sept statements deliberately missing).
rows = [
 ("01/10/2026","HMRC VAT","VAT Q2 104558321","FASTER PAYMENT",-2140.00),
 ("02/10/2026","Fenwick Builders Ltd","AJ-2041","FASTER PAYMENT",3400.00),
 ("03/10/2026","Screwfix Direct","Card 4471","CARD PAYMENT",-86.40),
 ("05/10/2026","Currys Business","CB-55120","CARD PAYMENT",-1450.00),
 ("07/10/2026","Hiscox Insurance","POL HX-778120","DIRECT DEBIT",-1260.00),
 ("09/10/2026","P ASHDOWN","Director","FASTER PAYMENT",-2000.00),
 ("10/10/2026","Shell Tonbridge","Card 4471","CARD PAYMENT",-38.50),
 ("12/10/2026","The Ivy Tunbridge Wells","Card 4471","CARD PAYMENT",-184.00),
 ("15/10/2026","Stripe Payments UK","STRIPE PAYOUT","FASTER PAYMENT",1163.10),
 ("18/10/2026","Adobe Systems","Card 4471","CARD PAYMENT",-24.71),
 ("20/10/2026","Ashdown Joinery Ltd","To savings","TRANSFER",-3000.00),
 ("22/10/2026","Netflix.com","Card 4471","CARD PAYMENT",-12.99),
 ("25/10/2026","HMRC PAYE","120PA00123456","FASTER PAYMENT",-612.40),
 ("28/10/2026","Starling Bank","Monthly fee","FEE",-7.00),
 ("30/10/2026","Jewson Ltd","JW-88812","FASTER PAYMENT",-342.00),
]
bal = 8200.00
out = ["Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP)"]
for d,c,r,t,a in rows:
    bal = round(bal + a, 2)
    out.append(f"{d},{c},{r},{t},{a:.2f},{bal:.2f}")
open("starling-current-oct-2026.csv","w").write("\n".join(out)+"\n")
print("closing", bal)

pdf("currys-invoice-CB-55120.pdf", [
 "Currys Business - VAT INVOICE", "VAT Reg No: GB 123 4567 89", "Invoice CB-55120   Date: 05/10/2026",
 "Bill to: Ashdown Joinery Ltd, 4 Mill Lane, Tonbridge TN9 1AA", "",
 "1 x Dell Latitude 5550 laptop (business use)      1,208.33", "Subtotal                                      1,208.33",
 "VAT @ 20%                                         241.67", "TOTAL PAID BY CARD                            1,450.00"])
pdf("hiscox-policy-schedule-HX-778120.pdf", [
 "Hiscox Insurance - Policy Schedule", "Policy HX-778120   Insured: Ashdown Joinery Ltd",
 "Cover: Public liability & tools, period 07/10/2026 to 06/10/2027 (12 months)", "",
 "Annual premium                                   1,125.00", "Insurance Premium Tax (IPT) @ 12%                  135.00",
 "Total payable by direct debit 07/10/2026         1,260.00", "Insurance is exempt from VAT. No VAT is charged."])
pdf("jewson-invoice-JW-88812.pdf", [
 "Jewson Ltd - Tax Invoice", "VAT No: GB 555 1212 34", "Invoice JW-88812  Date: 28/09/2026  Terms: 30 days",
 "Customer: Ashdown Joinery Ltd", "", "Treated softwood 47x100 x 40 lengths            285.00",
 "Net 285.00   VAT 20% 57.00   Total 342.00"])
pdf("sales-invoice-AJ-2041.pdf", [
 "Ashdown Joinery Ltd - INVOICE", "VAT Reg No: GB 777 8888 99   UTR 12345 67890",
 "Invoice AJ-2041   Date: 20/09/2026", "To: Fenwick Builders Ltd (CIS contractor), 12 Quarry Rd, Sevenoaks", "",
 "Labour - first fix joinery, Plot 4                 3,000.00", "Materials                                          1,000.00",
 "Net                                                4,000.00",
 "VAT: Reverse charge - customer to account to HMRC for the VAT. Domestic reverse charge applies.",
 "CIS deduction 20% on labour                        (600.00)", "Amount due                                         3,400.00"])
open("ivy-receipt-12-10.txt","w").write(
 "THE IVY TUNBRIDGE WELLS\nVAT No GB 987 6543 21\n12/10/2026 20:41  Table 9  Covers 4\n"
 "Food 118.00\nDrinks 35.33\nService 0.00\nTotal 184.00\nincl VAT 20% 30.67\nPaid VISA ****4471\n"
 "Thank you - Dinner with Fenwick Builders site team\n")
