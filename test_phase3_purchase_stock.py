"""Phase 3 parser/mapping tests — isolated fixture data only.

Uses LegacyDump.from_text and the pure mapping helpers; no database is
opened, created, or modified by any test in this module.
"""

import unittest

FIXTURE = """CREATE TABLE `invoicevhheader` (
  `ID` int(11) NOT NULL AUTO_INCREMENT,
  `AcYearID` int(11) NOT NULL,
  `VhType` varchar(15) NOT NULL,
  `VhNo` int(11) NOT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(8) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL,
  `SuppID` int(11) DEFAULT NULL,
  `InvoiceNo` varchar(10) DEFAULT NULL,
  `InvoiceDate` date DEFAULT NULL,
  `DueDate` date DEFAULT NULL,
  `GrossAmount` double DEFAULT NULL,
  `DiscountEntered` varchar(10) DEFAULT NULL,
  `DiscountPer` double DEFAULT NULL,
  `DiscountAmt` double DEFAULT NULL,
  `RoundOff` double DEFAULT NULL,
  `LessDNAmount` double DEFAULT NULL,
  `AddCNAmount` double DEFAULT NULL,
  `AddTaxAmount` double DEFAULT NULL,
  `PaidAmount` double DEFAULT NULL,
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
CREATE TABLE `invoiceitemdetail` (
  `ID` int(11) NOT NULL AUTO_INCREMENT,
  `VhID` int(11) DEFAULT NULL,
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(20) DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `ExpiryDate` date DEFAULT NULL,
  `PayPackQty` smallint(6) DEFAULT NULL,
  `FreePackQty` smallint(6) DEFAULT NULL,
  `RcvdPackQty` int(11) DEFAULT NULL,
  `TotalLooseQty` int(11) DEFAULT NULL,
  `Rate` double DEFAULT NULL,
  `MRP` double DEFAULT NULL,
  `DiscEntered` varchar(10) DEFAULT NULL,
  `DiscPer` double DEFAULT NULL,
  `DiscAmt` double DEFAULT NULL,
  `Amount` double DEFAULT NULL,
  `TaxPer` float DEFAULT NULL,
  `TaxAmt` double DEFAULT NULL,
  `PurRate` double DEFAULT NULL,
  `NetRate` double DEFAULT NULL,
  `SaleRate` double DEFAULT NULL,
  `ChallanID` int(11) DEFAULT '0',
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
CREATE TABLE `stockbalance` (
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(20) DEFAULT NULL,
  `ExpiryDate` date DEFAULT NULL,
  `MRP` double DEFAULT NULL,
  `Rate` double DEFAULT NULL,
  `NetPurRate` double DEFAULT NULL,
  `TotalPurchaseQty` int(11) DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `NetSalesRate` double DEFAULT NULL,
  `TotalSalesQty` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
INSERT INTO `invoicevhheader` VALUES (1,1,'Credit',1,'2016-01-05','10:00 AM','',100,8,'A1','2016-01-05','0001-01-01',100,'',0,0,0,0,0,0,0),(2,3,'Credit',7,'2018-03-02','10:00 AM','',200,9,'B2','2018-03-02','0001-01-01',200,'',0,0,0,0,0,0,0),(3,3,'Credit',7,'2018-03-02','10:00 AM','',50,99,'B3','2018-03-02','0001-01-01',50,'',0,0,0,0,0,0,0);
INSERT INTO `invoiceitemdetail` VALUES (1,1,101,'B1',10,'2020-01-31',5,1,6,60,10,12,'0%',0,0,50,5.5,1,9,9,0,0),(2,2,102,'B2',10,'2020-01-31',4,0,4,40,20,24,'0%',0,0,80,12,5,18,18,0,0),(3,99,103,'B3',10,'2020-01-31',1,0,1,10,5,6,'0%',0,0,5,5,0,4,4,0,0);
INSERT INTO `stockbalance` VALUES (101,'B1','2020-01-31',12,10,9,6,10,0,6),(102,'B2','2020-01-31',24,20,18,4,10,0,1);
CREATE TABLE `ledger` (
  `ID` int(11) NOT NULL AUTO_INCREMENT,
  `LedHead` varchar(100) DEFAULT NULL,
  `SGpID` int(11) DEFAULT NULL,
  `AdminCreated` char(1) DEFAULT 'N',
  `OpeningBal` double DEFAULT NULL,
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
CREATE TABLE `acyear` (
  `ID` int(11) NOT NULL AUTO_INCREMENT,
  `FromDate` date NOT NULL,
  `ToDate` date NOT NULL,
  `FinancialYear` varchar(9) NOT NULL,
  `AcClosed` char(1) DEFAULT 'N',
  `FromYear` varchar(4) DEFAULT NULL,
  `ToYear` varchar(4) DEFAULT NULL,
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
INSERT INTO `ledger` VALUES (8,'SUP A',25,'N',0),(9,'SUP B',25,'N',0);
INSERT INTO `acyear` VALUES (1,'2015-04-01','2016-03-31','2015-2016','N','2015','2016'),(3,'2017-04-01','2018-03-31','2017-2018','N','2017','2018');
CREATE TABLE `itemmst` (
  `ID` int(11) NOT NULL AUTO_INCREMENT,
  `ItemName` varchar(30) NOT NULL,
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
INSERT INTO `itemmst` VALUES (101,'ITEM A'),(102,'ITEM B');
"""


class EraTests(unittest.TestCase):
    def test_cutoff_boundaries(self):
        from tools.phase3_purchase_stock_dryrun import classify_tax_era

        self.assertEqual(classify_tax_era("2017-06-30", 12), "VAT")
        self.assertEqual(classify_tax_era("2017-07-01", 12), "GST")
        self.assertEqual(classify_tax_era("2020-01-01", 12.5), "VAT")
        self.assertEqual(classify_tax_era("2016-01-01", 5), "VAT")
        self.assertEqual(classify_tax_era("", 12), "VAT")
        self.assertEqual(classify_tax_era("2020-01-01", 0), "GST")

    def test_sales_packs_conversion(self):
        from tools.phase3_purchase_stock_dryrun import sales_packs

        self.assertEqual(sales_packs(1200.0, 10.0), 120.0)
        self.assertIsNone(sales_packs(5.0, 0.0))

    def test_voucher_composition(self):
        from tools.phase3_purchase_stock_dryrun import compose_voucher

        self.assertEqual(compose_voucher("2018-2019", "Credit", 7), "2018-2019-Credit-7")

    def test_pack_text(self):
        from tools.phase3_purchase_stock_dryrun import pack_text

        self.assertEqual(pack_text(10), "10")
        self.assertEqual(pack_text(None), "")


class FixtureMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from database.legacy_migration import LegacyDump

        cls.dump = LegacyDump.from_text(FIXTURE, name="phase3-fixture")

    def test_expected_counts(self):
        counts = self.dump.count_rows()
        self.assertEqual(counts.get("invoicevhheader"), 3)
        self.assertEqual(counts.get("invoiceitemdetail"), 3)
        self.assertEqual(counts.get("stockbalance"), 2)

    def test_missing_refs_detected(self):
        items = {101, 102}
        suppliers = {8, 9}
        headers = list(self.dump.iter_rows("invoicevhheader"))
        lines = list(self.dump.iter_rows("invoiceitemdetail"))
        self.assertEqual(sorted({r[8] for r in headers} - suppliers), [99])
        self.assertEqual(sorted({r[2] for r in lines} - items), [103])
        header_ids = {r[0] for r in headers}
        self.assertEqual([r[0] for r in lines if r[1] not in header_ids], [3])

    def test_duplicate_voucher_detected(self):
        from collections import Counter

        headers = list(self.dump.iter_rows("invoicevhheader"))
        dups = {k: v for k, v in
                Counter((r[1], r[2], r[3]) for r in headers).items() if v > 1}
        self.assertEqual(dups, {(3, "Credit", 7): 2})

    def test_reconciliation_math(self):
        # header 2 (GST-era, TaxPer 12): line packs 4 -> stock net 4-1=3
        sb = {(r[0], r[1]): r[6] - r[9] for r in self.dump.iter_rows("stockbalance")}
        self.assertEqual(sb[(102, "B2")], 3)
        # header 1 is VAT-era: packs 6 present in purchases but era VAT
        from tools.phase3_purchase_stock_dryrun import classify_tax_era

        self.assertEqual(classify_tax_era("2016-01-05", 5.5), "VAT")
        self.assertEqual(classify_tax_era("2018-03-02", 12), "GST")

    def test_report_builds_offline(self):
        from tools.phase3_purchase_stock_dryrun import build_report

        rep = build_report(self.dump)
        self.assertEqual(rep["expected"]["purchase_headers"], 3)
        self.assertEqual(rep["expected"]["purchase_lines"], 3)
        self.assertEqual(rep["missing_suppliers"], [99])
        self.assertEqual(rep["missing_items"], [103])
        self.assertEqual(len(rep["orphan_lines"]), 1)
        self.assertTrue(rep["duplicate_vouchers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
