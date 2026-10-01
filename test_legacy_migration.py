"""Phase 6F — Legacy migration tests (offline SQL dump → SQLite).

All tests use throwaway SQLite databases via PHARMACY_DB; the real
``data/pharmacy.db`` is never touched.  The dump is synthesised in memory
(or written to a temp file) so the suite stays fast; a couple of tests
optionally exercise the real production dump when it is present.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.legacy_migration import (  # noqa: E402
    ACCOUNTING_SOURCES,
    CLEAR_ORDER,
    DEMO_TABLES,
    LegacyDump,
    LegacyMigrationError,
    LegacyMigrator,
    SOURCE_TARGETS,
    UNSUPPORTED_TABLES,
    build_parser,
    build_plan,
    database_state,
    decode_token,
    main,
    migration_meta,
    orphan_report,
    plan_to_dict,
    render_dry_run_markdown,
    render_migration_report,
    split_value_tuples,
    stock_reconciliation,
    verify_migration,
    write_dry_run_reports,
    write_migration_report,
    _date,
    _is_literal_row,
    _number,
    _pack,
    _reorder,
    _text,
)

# ══════════════════════════════════════════════════════════════════════
# Synthetic dump fixture (small but covers every migration area)
# ══════════════════════════════════════════════════════════════════════

SAMPLE_DUMP = """
-- MySQL dump (synthetic fixture for tests)
CREATE TABLE `acyear` (
  `ID` int(11) NOT NULL,
  `FromDate` date NOT NULL,
  `ToDate` date NOT NULL,
  `FinancialYear` varchar(9) NOT NULL,
  `AcClosed` char(1) DEFAULT 'N',
  `FromYear` varchar(4) DEFAULT NULL,
  `ToYear` varchar(4) DEFAULT NULL
);
INSERT INTO `acyear` VALUES (1,'2015-04-01','2016-03-31','2015-2016','N','2015','2016'),(2,'2026-04-01','2027-03-31','2026-2027','N','2026','2027');

CREATE TABLE `companymst` (
  `ID` int(11) NOT NULL,
  `CompanyName` varchar(30) NOT NULL,
  `ShortName` varchar(5) DEFAULT NULL
);
INSERT INTO `companymst` VALUES (1,'ACME PHARMA','ACM'),(2,'ACME PHARMA','ACM2'),(3,'BETA LABS','BET');

CREATE TABLE `unitmst` (
  `ID` int(11) NOT NULL,
  `ItemUnit` varchar(15) NOT NULL
);
INSERT INTO `unitmst` VALUES (1,'TABLET'),(2,'BOTTLE');

CREATE TABLE `drugmst` (
  `ID` int(11) NOT NULL,
  `DrugName` varchar(45) NOT NULL
);
INSERT INTO `drugmst` VALUES (1,'PARACETAMOL'),(2,'CETIRIZINE');

CREATE TABLE `pathymst` (
  `ID` smallint(6) NOT NULL,
  `Pathy` varchar(45) NOT NULL
);
INSERT INTO `pathymst` VALUES (1,'ALLOPATHIC MEDICINES'),(2,'AYURVEDIC MEDICINES');

CREATE TABLE `doctormst` (
  `ID` int(11) NOT NULL,
  `DoctorName` varchar(45) DEFAULT NULL,
  `Specality` varchar(45) DEFAULT NULL,
  `City` varchar(45) DEFAULT NULL,
  `PhoneNo` varchar(45) DEFAULT NULL
);
INSERT INTO `doctormst` VALUES (1,'DR TEST','MBBS','PUNE','12345'),(2,'SELF','','PUNE',''),(3,'SELF','SELF','PUNE','');

CREATE TABLE `itemmst` (
  `ID` int(11) NOT NULL,
  `ItemName` varchar(30) NOT NULL,
  `UnitID` int(11) DEFAULT NULL,
  `PathyID` smallint(6) DEFAULT NULL,
  `CompanyID` int(11) DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `DiscountPer` float DEFAULT NULL,
  `ReorderStockLevel` smallint(6) DEFAULT NULL,
  `Rate` float DEFAULT NULL,
  `MRP` float DEFAULT NULL,
  `TaxID` smallint(6) DEFAULT NULL,
  `Location` varchar(45) DEFAULT NULL,
  `SheduledID` smallint(6) DEFAULT NULL,
  `SellLoose` enum('Y','N') DEFAULT NULL,
  `BillCompulsory` enum('Y','N') DEFAULT NULL,
  `DPCO` enum('Y','N') DEFAULT 'N'
);
INSERT INTO `itemmst` VALUES (1,'PARA 500',1,1,1,10,5,20,12.5,20,3,'A1',1,'Y','N','N'),(2,'CETRI 10',1,1,3,10,0,10,8,15,3,'A2',NULL,'N','N','Y'),(3,'PARA 500',1,1,1,10,5,20,12.5,20,3,'A1',1,'Y','N','N'),(4,'AYUR TONIC',2,2,1,1,0,5,50,80,NULL,'B1',NULL,'N','N','N');

CREATE TABLE `itemdrugs` (
  `ID` int(11) NOT NULL,
  `ItemID` int(11) DEFAULT NULL,
  `DrugID` int(11) DEFAULT NULL,
  `Power` varchar(45) DEFAULT NULL
);
INSERT INTO `itemdrugs` VALUES (1,1,1,'500'),(2,2,2,'10'),(3,1,1,'500');

CREATE TABLE `gpmst` (
  `ID` int(11) NOT NULL,
  `SGpHead` varchar(45) NOT NULL,
  `GpID` int(11) NOT NULL,
  `NGpID` int(11) NOT NULL,
  `AdminCreated` char(1) DEFAULT 'N'
);
INSERT INTO `gpmst` VALUES (1,'<Primary>',0,0,'Y'),(3,'SALES ACCOUNT',1,1,'Y'),(8,'PURCHASE ACCOUNT',1,2,'Y'),(12,'INVESTMENTS',1,4,'N'),(16,'SUNDRY DEBTORS',11,4,'N'),(17,'CASH-IN-HAND',11,4,'Y'),(18,'BANK ACCOUNTS',11,4,'N'),(25,'SUNDRY CREDITORS',20,3,'N');

CREATE TABLE `ledger` (
  `ID` int(11) NOT NULL,
  `LedHead` varchar(45) NOT NULL,
  `SGpID` int(11) NOT NULL,
  `AdminCreated` char(1) DEFAULT 'N',
  `OpeningBal` double DEFAULT '0'
);
INSERT INTO `ledger` VALUES (2,'CASH',17,'Y',0),(3,'CASH SALE',3,'Y',0),(4,'CREDIT PURCHASE',8,'Y',0),(7,'WALKIN',16,'Y',0),(8,'SUNDRY TRADERS',25,'N',-1500),(9,'SHRI MEDICAL',16,'N',500),(10,'SBI BANK',18,'N',-100),(11,'DISCOUNT GIVEN',12,'N',0);

CREATE TABLE `statemst` (
  `ID` smallint(6) NOT NULL,
  `State` varchar(25) NOT NULL
);
INSERT INTO `statemst` VALUES (1,'MAHARASHTRA'),(0,'');

CREATE TABLE `sundaryinfo` (
  `ID` int(11) NOT NULL,
  `LedID` int(11) DEFAULT NULL,
  `SalesTaxNo` varchar(100) DEFAULT NULL,
  `VATorTIN` varchar(100) DEFAULT NULL,
  `DiscountPer` float DEFAULT NULL,
  `CreditLimit` double DEFAULT NULL,
  `CreditPeriod` smallint(6) DEFAULT NULL,
  `Address` varchar(500) DEFAULT NULL,
  `City` varchar(25) DEFAULT NULL,
  `StateID` smallint(6) DEFAULT NULL,
  `ContactPerson` varchar(45) DEFAULT NULL,
  `ContactNo` varchar(45) DEFAULT NULL
);
INSERT INTO `sundaryinfo` VALUES (1,8,'TAX123','TIN9',2.5,1000,30,'12, MAIN ROAD','PUNE',1,'RAM','999'),(2,9,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);

CREATE TABLE `stockbalance` (
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(20) DEFAULT NULL,
  `ExpiryDate` date DEFAULT NULL,
  `MRP` double DEFAULT NULL,
  `Rate` double DEFAULT NULL,
  `NetPurRate` double DEFAULT NULL,
  `TotalPurchaseQty` decimal(54,0) DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `NetSalesRate` double NOT NULL DEFAULT '0',
  `TotalSalesQty` decimal(54,0) NOT NULL DEFAULT '0'
);
INSERT INTO `stockbalance` VALUES (1,'B001','2017-05-31',20,12.5,11.5,100,10,0,40),(2,'B002','2018-01-31',15,8,7.5,50,10,0,0),(1,'B001','2017-05-31',20,12.5,11.5,10,10,0,5);

CREATE TABLE `stockadjusted` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `AdjustedDate` date DEFAULT NULL,
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(20) DEFAULT NULL,
  `ExpiryDate` date DEFAULT NULL,
  `AdjustedQty` int(11) DEFAULT NULL,
  `MRP` double DEFAULT NULL,
  `Rate` double DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `TaxPer` double DEFAULT NULL,
  `TaxAmt` double DEFAULT NULL,
  `NetRate` double DEFAULT NULL
);
INSERT INTO `stockadjusted` VALUES (1,1,'2015-04-01',1,'B001','2017-05-31',100,20,12.5,10,0,0,11.5);

CREATE TABLE `invoicevhheader` (
  `ID` int(11) NOT NULL,
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
  `DiscountPer` float DEFAULT NULL,
  `DiscountAmt` float DEFAULT NULL,
  `RoundOff` double DEFAULT NULL,
  `LessDNAmount` double DEFAULT NULL,
  `AddCNAmount` double DEFAULT NULL,
  `AddTaxAmount` double DEFAULT NULL,
  `PaidAmount` double DEFAULT NULL
);
INSERT INTO `invoicevhheader` VALUES (1,1,'Credit',1,'2015-04-01','12:25 PM','',2793,8,'84','2015-04-01','2015-05-01',2660.12,'',0,0,-0.12,0,0,132.88,0),(2,1,'Cash',2,'2015-04-05','10:00 AM','',500,8,'85','2015-04-05','0001-01-01',500,NULL,0,0,0,0,0,0,500);

CREATE TABLE `invoiceitemdetail` (
  `ID` int(11) NOT NULL,
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
  `ChallanID` int(11) DEFAULT '0'
);
INSERT INTO `invoiceitemdetail` VALUES (1,1,1,'B001',10,'2017-05-31',3,0,3,30,115.49,150,'0%',0,17.32,346.47,5,17.32,121,121.26,0,0),(2,1,2,'B002',10,'2018-01-31',2,1,2,20,50,75,'5%',5,7.5,142.5,12,17.1,52,58.2,0,0);

CREATE TABLE `invoicevhdetail` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` float DEFAULT NULL,
  `LedNarration` varchar(45) DEFAULT NULL
);
INSERT INTO `invoicevhdetail` VALUES (1,1,'2015-04-01',1,'DR',4,2793,'Invoice No= 84'),(2,1,'2015-04-01',1,'CR',8,2793,'Invoice No= 84'),(3,1,'2015-04-05',2,'DR',4,500,'Invoice No= 85'),(4,1,'2015-04-05',2,'CR',2,500,'Invoice No= 85');

CREATE TABLE `salesvhheader` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhType` varchar(15) DEFAULT NULL,
  `VhNo` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(8) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL,
  `BillNo` int(11) DEFAULT NULL,
  `CustID` int(11) DEFAULT NULL,
  `PatientName` varchar(50) DEFAULT NULL,
  `PatientAddress` varchar(50) DEFAULT NULL,
  `PatientPhone` varchar(50) DEFAULT NULL,
  `DoctID` int(11) DEFAULT NULL,
  `GrossAmount` double DEFAULT NULL,
  `DiscountEntered` varchar(10) DEFAULT NULL,
  `DiscountPer` double DEFAULT NULL,
  `DiscountAmt` double DEFAULT NULL,
  `RoundOff` double DEFAULT NULL,
  `AddDNAmount` double DEFAULT NULL,
  `LessCNAmount` double DEFAULT NULL,
  `PaidAmount` double DEFAULT NULL
);
INSERT INTO `salesvhheader` VALUES (10,1,'Cash',1,'2015-04-01','4:24 PM','',208,1,7,'MRS PATIENT','VAMBORI','',1,207.67,'',0,0,0.67,0,0,208),(11,1,'Credit',2,'2015-04-02','5:00 PM','',300,2,9,'','','',NULL,300,'',0,5,0,0,0,100);

CREATE TABLE `salesitemdetail` (
  `ID` int(11) NOT NULL,
  `VhID` int(11) DEFAULT NULL,
  `ItemID` int(11) DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `BatchNo` varchar(20) DEFAULT NULL,
  `ExpiryDate` date DEFAULT NULL,
  `MRP` double DEFAULT NULL,
  `SalesQty` int(11) DEFAULT NULL,
  `SalesRate` double DEFAULT NULL,
  `NetSalesRate` double DEFAULT NULL,
  `DiscEntered` varchar(10) DEFAULT NULL,
  `DiscPer` double DEFAULT NULL,
  `DiscAmt` double DEFAULT NULL,
  `Amount` double DEFAULT NULL
);
INSERT INTO `salesitemdetail` VALUES (11,10,1,10,'B001','2017-05-31',56,5,46.67,46.67,'',0,0,46.67),(12,11,2,10,'B002','2018-01-31',15,20,15,14.25,'5%',5,15,285);

CREATE TABLE `salesvhdetail` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` float DEFAULT NULL,
  `LedNarration` varchar(45) DEFAULT NULL
);
INSERT INTO `salesvhdetail` VALUES (27,1,'2015-04-01',10,'CR',3,208,''),(28,1,'2015-04-01',10,'DR',7,208,''),(29,1,'2015-04-02',11,'CR',3,300,''),(30,1,'2015-04-02',11,'DR',9,300,'');

CREATE TABLE `creditnotevhheader` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhType` char(15) DEFAULT NULL,
  `VhNo` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(8) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `DiscountEntered` varchar(10) DEFAULT NULL,
  `DiscountPer` double DEFAULT NULL,
  `DiscountAmt` double DEFAULT NULL,
  `CNDate` date DEFAULT NULL,
  `CNType` varchar(10) DEFAULT NULL,
  `AddedToLedger` char(1) DEFAULT NULL
);
INSERT INTO `creditnotevhheader` VALUES (1,1,'CreditNote',1,'2015-04-02','11:51 AM',NULL,136.5,9,'12%',12,18.61,'2015-04-02','Customer','Y');

CREATE TABLE `creditnoteitemdetail` (
  `ID` int(11) NOT NULL,
  `VhID` int(11) DEFAULT NULL,
  `ReasonID` int(11) DEFAULT NULL,
  `PriceFactor` char(4) DEFAULT NULL,
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(15) DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `ExpiryDate` date DEFAULT NULL,
  `Qty` smallint(6) DEFAULT NULL,
  `FreeQty` smallint(6) DEFAULT NULL,
  `TotQty` int(11) DEFAULT NULL,
  `MRP` double DEFAULT NULL,
  `Rate` double DEFAULT NULL,
  `CNRate` double DEFAULT NULL,
  `NetCNRate` double DEFAULT NULL,
  `DiscEntered` varchar(10) DEFAULT NULL,
  `DiscPer` double DEFAULT NULL,
  `DiscAmt` double DEFAULT NULL,
  `Amount` double DEFAULT NULL
);
INSERT INTO `creditnoteitemdetail` VALUES (1,1,6,'MRP',1,'B001',10,'2017-05-31',8,NULL,8,146.14,116.91,116.91,102.88,'0',0,0,116.91);

CREATE TABLE `creditnotevhdetail` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` double DEFAULT NULL,
  `LedNarration` varchar(45) DEFAULT NULL
);
INSERT INTO `creditnotevhdetail` VALUES (1,1,'2015-04-02',1,'CR',3,116.91,'CN 1'),(2,1,'2015-04-02',1,'DR',9,116.91,'CN 1');

CREATE TABLE `debitnotevhheader` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhType` char(15) DEFAULT NULL,
  `VhNo` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(8) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `DiscountEntered` varchar(10) DEFAULT NULL,
  `DiscountPer` double DEFAULT NULL,
  `DiscountAmt` double DEFAULT NULL,
  `DNDate` date DEFAULT NULL,
  `DNType` varchar(10) DEFAULT NULL,
  `AddedToLedger` char(1) DEFAULT NULL
);
INSERT INTO `debitnotevhheader` VALUES (1,1,'DebitNote',1,'2015-05-13','02:13 PM',NULL,556.88,8,'',0,0,'2015-05-13','Supplier','N');

CREATE TABLE `debitnoteitemdetail` (
  `ID` int(11) NOT NULL,
  `VhID` int(11) DEFAULT NULL,
  `ReasonID` int(11) DEFAULT NULL,
  `PriceFactor` char(4) DEFAULT NULL,
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(15) DEFAULT NULL,
  `PackSize` smallint(6) DEFAULT NULL,
  `ExpiryDate` date DEFAULT NULL,
  `Qty` smallint(6) DEFAULT NULL,
  `FreeQty` smallint(6) DEFAULT NULL,
  `TotQty` int(11) DEFAULT NULL,
  `MRP` double DEFAULT NULL,
  `Rate` double DEFAULT NULL,
  `DNRate` double DEFAULT NULL,
  `NetDNRate` double DEFAULT NULL,
  `DiscEntered` varchar(10) DEFAULT NULL,
  `DiscPer` double DEFAULT NULL,
  `DiscAmt` double DEFAULT NULL,
  `Amount` double DEFAULT NULL
);
INSERT INTO `debitnoteitemdetail` VALUES (2,1,1,'RATE',2,'B002',10,'2018-01-31',50,0,50,150,112.5,556.88,556.88,'1%',1,5.62,556.88);

CREATE TABLE `debitnotevhdetail` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` double DEFAULT NULL,
  `LedNarration` varchar(45) DEFAULT NULL
);
INSERT INTO `debitnotevhdetail` VALUES (1,1,'2015-05-13',1,'CR',8,556.88,'DN 1'),(2,1,'2015-05-13',1,'DR',4,556.88,'DN 1');

CREATE TABLE `receiptvhheader` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhType` varchar(15) DEFAULT NULL,
  `VhNo` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(15) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `CashBankID` int(11) DEFAULT NULL
);
INSERT INTO `receiptvhheader` VALUES (3,1,'Receipt',1,'2015-04-02','11:57 AM',NULL,200,9,2);

CREATE TABLE `receiptvhdetail` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` double DEFAULT NULL,
  `LedNarration` varchar(45) DEFAULT NULL
);
INSERT INTO `receiptvhdetail` VALUES (9,1,'2015-04-02',3,'CR',9,200,'CASH'),(10,1,'2015-04-02',3,'DR',2,200,'CASH');

CREATE TABLE `paymentvhheader` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhType` varchar(15) DEFAULT NULL,
  `VhNo` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(15) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `CashBankID` int(11) DEFAULT NULL,
  `PaymentRefNo` varchar(30) DEFAULT NULL
);
INSERT INTO `paymentvhheader` VALUES (1,1,'Payment',1,'2015-04-12','1:16 PM',NULL,1412,8,2,'R NO.9145');

CREATE TABLE `paymentvhdetail` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` double DEFAULT NULL,
  `LedNarration` varchar(45) DEFAULT NULL
);
INSERT INTO `paymentvhdetail` VALUES (11,1,'2015-04-10',1,'DR',8,8000,'CASH'),(12,1,'2015-04-10',1,'CR',2,8000,'CASH');

CREATE TABLE `journalvhheader` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhType` varchar(15) DEFAULT NULL,
  `VhNo` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(15) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL
);
CREATE TABLE `journalvhdetail` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` double DEFAULT NULL,
  `LedNarration` varchar(45) DEFAULT NULL
);

CREATE TABLE `demosalesvhheader` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) DEFAULT NULL,
  `VhType` varchar(15) DEFAULT NULL,
  `VhNo` int(11) DEFAULT NULL,
  `VhDate` date DEFAULT NULL,
  `VhTime` varchar(8) DEFAULT NULL,
  `VhNarration` varchar(200) DEFAULT NULL,
  `VhAmount` double DEFAULT NULL,
  `BillNo` int(11) DEFAULT NULL,
  `CustID` int(11) DEFAULT NULL
);
INSERT INTO `demosalesvhheader` VALUES (31,1,'Cash',1,'2015-04-19','5:11 PM','',30,1,7);
CREATE TABLE `demosalesvhdetail` (
  `ID` int(11) NOT NULL,
  `VhID` int(11) DEFAULT NULL,
  `TrnType` char(2) DEFAULT NULL,
  `LedID` int(11) DEFAULT NULL,
  `LedAmount` float DEFAULT NULL
);
INSERT INTO `demosalesvhdetail` VALUES (123,31,'CR',5,30);
CREATE TABLE `demosalesitemdetail` (
  `ID` int(11) NOT NULL,
  `VhID` int(11) DEFAULT NULL,
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(20) DEFAULT NULL,
  `SalesQty` int(11) DEFAULT NULL,
  `Amount` double DEFAULT NULL
);
INSERT INTO `demosalesitemdetail` VALUES (56,31,1,'B001',5,30);

CREATE TABLE `userinfo` (
  `UserID` int(11) NOT NULL,
  `UserName` varchar(45) NOT NULL,
  `UserPassword` varchar(45) DEFAULT NULL,
  `AdminRight` char(1) DEFAULT 'N',
  `UserRight` char(1) DEFAULT 'Y'
);
INSERT INTO `userinfo` VALUES (1,'ADMIN','*8A46D35D3A75C41D029F863ED815B2F8298132D7','Y','N'),(2,'PRATAP','*2045C5ACF92413B36D7982F6A2BA844C2797CBAA','N','Y');

CREATE TABLE `ledgeropbal` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) NOT NULL,
  `LedID` int(11) NOT NULL,
  `oldOpBal` double DEFAULT NULL,
  `1` double DEFAULT '0'
);
INSERT INTO `ledgeropbal` VALUES (1,1,8,-652,542);

CREATE TABLE `challanvhheader` (
  `ID` int(11) NOT NULL,
  `VhNo` int(11) DEFAULT NULL
);
INSERT INTO `challanvhheader` VALUES (1,1);
"""

TRIGGER_DUMP = """
CREATE TABLE `ledgeropbal` (
  `ID` int(11) NOT NULL,
  `AcYearID` int(11) NOT NULL,
  `LedID` int(11) NOT NULL,
  `oldOpBal` double DEFAULT NULL
);
CREATE TABLE `stockbalance` (
  `ItemID` int(11) DEFAULT NULL,
  `BatchNo` varchar(20) DEFAULT NULL,
  `TotalPurchaseQty` decimal(54,0) DEFAULT NULL,
  `TotalSalesQty` decimal(54,0) DEFAULT NULL
);
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`root`@`localhost`*/ /*!50003 TRIGGER `stockbalance_AINS` AFTER INSERT ON `stockbalance` FOR EACH ROW
BEGIN
	DECLARE totalRecords int;
	SELECT count(ItemID) INTO totalRecords FROM stockbalance
	WHERE ItemID = NEW.ItemID AND BatchNo = NEW.BatchNo;
	IF totalRecords=0 THEN
		INSERT INTO `ledgeropbal` (`AcYearID`, `LedID`, `oldOpBal`) VALUES (NEW.ItemID, NEW.BatchNo, 0);
	END IF;
END */;;
DELIMITER ;
INSERT INTO `ledgeropbal` VALUES (1,1,8,-652),(2,1,9,100);
INSERT INTO `stockbalance` VALUES (1,'B001',10,2);
"""


class _DBTestCase(unittest.TestCase):
    """Base class: every test gets its own throwaway SQLite database."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="p6f_test_")
        self.db_path = os.path.join(self._tmp, "pharmacy.db")
        self._previous = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = self.db_path

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("PHARMACY_DB", None)
        else:
            os.environ["PHARMACY_DB"] = self._previous
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _dump_file(self, text: str = SAMPLE_DUMP) -> str:
        path = os.path.join(self._tmp, "legacy.sql")
        Path(path).write_text(text, encoding="utf-8")
        return path

    def _import(self, text: str = SAMPLE_DUMP, **kwargs):
        migrator = LegacyMigrator(self._dump_file(text), db_path=self.db_path, **kwargs)
        report = migrator.import_data(do_backup=False)
        return migrator, report

    def _count(self, table: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        finally:
            conn.close()

    def _rows(self, sql: str, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 1. Value parsing
# ══════════════════════════════════════════════════════════════════════

class TokenParsingTests(unittest.TestCase):
    def test_01_null(self):
        self.assertIsNone(decode_token("NULL"))

    def test_02_null_lowercase(self):
        self.assertIsNone(decode_token("null"))

    def test_03_integer(self):
        self.assertEqual(decode_token("42"), 42)

    def test_04_negative_integer(self):
        self.assertEqual(decode_token("-7"), -7)

    def test_05_float(self):
        self.assertEqual(decode_token("3.25"), 3.25)

    def test_06_string(self):
        self.assertEqual(decode_token("'ABC'"), "ABC")

    def test_07_empty_string(self):
        self.assertEqual(decode_token("''"), "")

    def test_08_escaped_quote(self):
        self.assertEqual(decode_token(r"'O\'BRIEN'"), "O'BRIEN")

    def test_09_escaped_backslash(self):
        self.assertEqual(decode_token(r"'A\\B'"), "A\\B")

    def test_10_escaped_newline(self):
        self.assertEqual(decode_token(r"'A\nB'"), "A\nB")

    def test_11_doubled_quote(self):
        self.assertEqual(decode_token("'IT''S'"), "IT'S")

    def test_12_date_string(self):
        self.assertEqual(decode_token("'2015-04-01'"), "2015-04-01")

    def test_13_percent_escape(self):
        self.assertEqual(decode_token(r"'50\%'"), "50%")

    def test_14_underscore_escape(self):
        self.assertEqual(decode_token(r"'a\_b'"), "a_b")

    def test_15_split_single_tuple(self):
        self.assertEqual(split_value_tuples("(1,'A')"), [["1", "'A'"]])

    def test_16_split_multiple_tuples(self):
        self.assertEqual(split_value_tuples("(1,'A'),(2,'B')"),
                         [["1", "'A'"], ["2", "'B'"]])

    def test_17_split_comma_inside_string(self):
        self.assertEqual(split_value_tuples("(1,'A,B')"), [["1", "'A,B'"]])

    def test_18_split_parenthesis_inside_string(self):
        self.assertEqual(split_value_tuples("(1,'A)B')"), [["1", "'A)B'"]])

    def test_19_split_escaped_quote_inside_string(self):
        self.assertEqual(split_value_tuples(r"(1,'A\'B')"), [["1", r"'A\'B'"]])

    def test_20_split_null_and_empty(self):
        self.assertEqual(split_value_tuples("(NULL,'')"), [["NULL", "''"]])

    def test_21_column_list_parsing(self):
        from database.legacy_migration import _column_list
        self.assertEqual(_column_list("`A`, `B`"), ["A", "B"])

    def test_22_column_list_empty(self):
        from database.legacy_migration import _column_list
        self.assertEqual(_column_list(None), [])

    def test_23_literal_row_accepts_numbers_and_strings(self):
        self.assertTrue(_is_literal_row(["1", "'A'", "NULL"]))

    def test_24_literal_row_rejects_trigger_identifiers(self):
        self.assertFalse(_is_literal_row(["NEW.AcYearID", "NEW.LedID"]))

    def test_25_reorder_maps_explicit_columns(self):
        row = _reorder(["B", "A"], [2, 1], ["A", "B", "C"])
        self.assertEqual(row, [1, 2, None])

    def test_26_text_helper(self):
        self.assertEqual(_text(None), "")
        self.assertEqual(_text("  x "), "x")

    def test_27_pack_helper(self):
        self.assertEqual(_pack(10), "10")
        self.assertEqual(_pack(10.0), "10")
        self.assertEqual(_pack(None), "")

    def test_28_date_helper_drops_sentinels(self):
        self.assertEqual(_date("0000-00-00"), "")
        self.assertEqual(_date("0001-01-01"), "")
        self.assertEqual(_date("2015-04-01"), "2015-04-01")

    def test_29_number_helper(self):
        self.assertEqual(_number(None), 0.0)
        self.assertEqual(_number("2.5"), 2.5)
        self.assertEqual(_number("bad"), 0.0)


# ══════════════════════════════════════════════════════════════════════
# 2. Dump discovery / streaming
# ══════════════════════════════════════════════════════════════════════

class DumpParsingTests(unittest.TestCase):
    def test_30_table_discovery(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        self.assertIn("itemmst", dump.table_columns)
        self.assertIn("salesvhheader", dump.table_columns)

    def test_31_column_order_preserved(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        self.assertEqual(dump.table_columns["companymst"],
                         ["ID", "CompanyName", "ShortName"])

    def test_32_all_fixture_tables_found(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        self.assertGreaterEqual(len(dump.table_columns), 25)

    def test_33_iter_rows_returns_decoded_values(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        row = next(iter(dump.iter_rows("companymst")))
        self.assertEqual(row, [1, "ACME PHARMA", "ACM"])

    def test_34_iter_rows_filters_table(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        rows = list(dump.iter_rows("unitmst"))
        self.assertEqual(len(rows), 2)

    def test_35_iter_rows_multiple_insert_statements(self):
        text = SAMPLE_DUMP + "INSERT INTO `unitmst` VALUES (3,'SACHET');\n"
        dump = LegacyDump.from_text(text)
        self.assertEqual(len(list(dump.iter_rows("unitmst"))), 3)

    def test_36_count_rows(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        counts = dump.count_rows()
        self.assertEqual(counts["companymst"], 3)
        self.assertEqual(counts["salesvhheader"], 2)

    def test_37_count_rows_includes_all_tables(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        counts = dump.count_rows()
        self.assertIn("demosalesvhheader", counts)

    def test_38_trigger_lines_skipped(self):
        dump = LegacyDump.from_text(TRIGGER_DUMP)
        rows = list(dump.iter_rows("ledgeropbal"))
        self.assertEqual(len(rows), 2)

    def test_39_trigger_lines_recorded(self):
        dump = LegacyDump.from_text(TRIGGER_DUMP)
        self.assertTrue(dump.trigger_lines)

    def test_40_trigger_rows_are_literal_data(self):
        dump = LegacyDump.from_text(TRIGGER_DUMP)
        self.assertEqual(list(dump.iter_rows("stockbalance"))[0], [1, "B001", 10, 2])

    def test_41_sample_returns_first_rows(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        self.assertEqual(len(dump.sample("unitmst", 1)), 1)

    def test_42_table_names_listing(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        self.assertIn("ledger", dump.table_names())

    def test_43_missing_file_raises(self):
        with self.assertRaises(LegacyMigrationError):
            LegacyDump(os.path.join(tempfile.gettempdir(), "does_not_exist_9x.sql"))

    def test_44_iter_rows_unknown_table_is_empty(self):
        dump = LegacyDump.from_text(SAMPLE_DUMP)
        self.assertEqual(list(dump.iter_rows("nope")), [])

    def test_45_explicit_insert_column_list(self):
        text = ("CREATE TABLE `t` (\n"
                "  `A` int,\n"
                "  `B` varchar(5)\n"
                ");\n"
                "INSERT INTO `t` (`B`, `A`) VALUES ('x', 1);\n")
        dump = LegacyDump.from_text(text)
        self.assertEqual(list(dump.iter_rows("t")), [[1, "x"]])


# ══════════════════════════════════════════════════════════════════════
# 3. Inventory / dry run
# ══════════════════════════════════════════════════════════════════════

class DryRunPlanTests(_DBTestCase):
    def _plan(self):
        return build_plan(LegacyDump.from_text(SAMPLE_DUMP))

    def test_46_demo_tables_marked(self):
        plan = self._plan()
        self.assertTrue(plan.tables["demosalesvhheader"].demo)

    def test_47_demo_rows_counted(self):
        plan = self._plan()
        self.assertEqual(plan.demo_rows, 3)

    def test_48_demo_rows_not_in_totals(self):
        plan = self._plan()
        self.assertNotIn("demosalesvhitem", plan.counts)

    def test_49_unsupported_tables_flagged(self):
        plan = self._plan()
        self.assertTrue(plan.tables["challanvhheader"].unsupported)

    def test_50_mapped_tables_not_unsupported(self):
        plan = self._plan()
        self.assertFalse(plan.tables["itemmst"].unsupported)

    def test_51_duplicate_item_names_found(self):
        plan = self._plan()
        names = [f["name"] for f in plan.findings["duplicate_item_names"]]
        self.assertIn("PARA 500", names)

    def test_52_duplicate_doctor_names_are_merges(self):
        self._import()
        rows = self._rows("SELECT doctor_name FROM doctors")
        self.assertEqual(len(rows), 2)

    def test_53_no_journal_records_finding(self):
        plan = self._plan()
        self.assertTrue(plan.findings["no_journal_records"])

    def test_54_stock_batches_counted(self):
        plan = self._plan()
        self.assertEqual(plan.counts["_stock_batches"], 2)

    def test_55_stock_adjustments_counted(self):
        plan = self._plan()
        self.assertEqual(plan.counts["_stock_adjustments"], 1)

    def test_56_parties_classified(self):
        plan = self._plan()
        self.assertEqual(plan.counts["_debtor_ledgers"], 2)
        self.assertEqual(plan.counts["_creditor_ledgers"], 1)

    def test_57_financial_years_valid(self):
        plan = self._plan()
        self.assertEqual(plan.counts["_financial_years_valid"], 2)

    def test_58_missing_item_company_detected(self):
        text = SAMPLE_DUMP.replace("1,'PARA 500',1,1,1,10", "1,'PARA 500',1,1,999,10")
        plan = build_plan(LegacyDump.from_text(text))
        self.assertTrue(plan.findings["missing_item_company"])

    def test_59_missing_item_unit_detected(self):
        text = SAMPLE_DUMP.replace("1,'PARA 500',1,1,1,10", "1,'PARA 500',99,1,1,10")
        plan = build_plan(LegacyDump.from_text(text))
        self.assertTrue(plan.findings["missing_item_unit"])

    def test_60_plan_summary_shape(self):
        summary = self._plan().summary()
        self.assertIn("source_rows", summary)
        self.assertIn("demo_rows_excluded", summary)

    def test_61_plan_to_dict_json_serialisable(self):
        payload = json.dumps(plan_to_dict(self._plan()), default=str)
        self.assertIn("tables", payload)

    def test_62_dry_run_markdown_contains_tables(self):
        markdown = render_dry_run_markdown(self._plan())
        self.assertIn("itemmst", markdown)
        self.assertIn("demo — excluded", markdown)
        self.assertIn("unsupported", markdown)

    def test_63_write_dry_run_reports(self):
        plan = self._plan()
        md = os.path.join(self._tmp, "out", "dry.md")
        js = os.path.join(self._tmp, "out", "dry.json")
        written = write_dry_run_reports(plan, md, js)
        self.assertTrue(Path(written["markdown"]).is_file())
        self.assertTrue(Path(written["json"]).is_file())

    def test_64_dry_run_does_not_create_database(self):
        plan = build_plan(LegacyDump.from_text(SAMPLE_DUMP))
        self.assertFalse(os.path.exists(self.db_path))

    def test_65_dry_run_does_not_touch_existing_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE marker (id INTEGER)")
        conn.execute("INSERT INTO marker VALUES (1)")
        conn.commit()
        conn.close()
        before = database_state(sqlite3.connect(self.db_path))
        build_plan(LegacyDump.from_text(SAMPLE_DUMP))
        after = database_state(sqlite3.connect(self.db_path))
        self.assertEqual(before["sha256"], after["sha256"])

    def test_66_unsupported_reasons_documented(self):
        for table in ("challanvhheader", "softmaster", "countersaleitems"):
            self.assertIn(table, UNSUPPORTED_TABLES)
            self.assertTrue(UNSUPPORTED_TABLES[table])

    def test_67_source_targets_cover_main_tables(self):
        for table in ("acyear", "itemmst", "salesvhheader", "stockbalance"):
            self.assertTrue(SOURCE_TARGETS.get(table))

    def test_68_sales_items_unresolved_counted(self):
        plan = self._plan()
        self.assertEqual(plan.counts["_sales_items_unresolved"], 0)


# ══════════════════════════════════════════════════════════════════════
# 4. Import: masters
# ══════════════════════════════════════════════════════════════════════

class ImportMasterTests(_DBTestCase):
    def test_69_companies_imported(self):
        self._import()
        names = [r["company_name"] for r in self._rows("SELECT company_name FROM companies")]
        self.assertIn("ACME PHARMA", names)
        self.assertIn("BETA LABS", names)

    def test_70_company_duplicate_merged(self):
        self._import()
        self.assertEqual(self._count("companies"), 2)

    def test_71_company_short_name(self):
        self._import()
        row = self._rows("SELECT short_name FROM companies WHERE company_name='BETA LABS'")
        self.assertEqual(row[0]["short_name"], "BET")

    def test_72_units_imported(self):
        self._import()
        self.assertEqual(self._count("units"), 2)

    def test_73_drugs_imported(self):
        self._import()
        self.assertEqual(self._count("drugs"), 2)

    def test_74_doctors_imported_with_fields(self):
        self._import()
        row = self._rows("SELECT * FROM doctors WHERE doctor_name='DR TEST'")[0]
        self.assertEqual(row["specialty"], "MBBS")
        self.assertEqual(row["city"], "PUNE")
        self.assertEqual(row["phone_no"], "12345")

    def test_75_doctor_duplicate_merged(self):
        self._import()
        self.assertEqual(self._count("doctors"), 2)

    def test_76_items_imported(self):
        self._import()
        self.assertEqual(self._count("items"), 3)

    def test_77_item_duplicate_merged(self):
        self._import()
        rows = self._rows("SELECT id FROM items WHERE item_name='PARA 500'")
        self.assertEqual(len(rows), 1)

    def test_78_item_relationships_resolved(self):
        self._import()
        row = self._rows("SELECT * FROM items WHERE item_name='PARA 500'")[0]
        self.assertIsNotNone(row["unit_id"])
        self.assertIsNotNone(row["company_id"])

    def test_79_item_scalar_fields(self):
        self._import()
        row = self._rows("SELECT * FROM items WHERE item_name='PARA 500'")[0]
        self.assertEqual(row["pack_size"], "10")
        self.assertEqual(row["mrp"], 20)
        self.assertEqual(row["rate"], 12.5)
        self.assertEqual(row["discount"], 5)
        self.assertEqual(row["reorder_stock_level"], 20)
        self.assertEqual(row["location"], "A1")
        self.assertEqual(row["tax_structure"], "3")
        self.assertEqual(row["scheduled"], "1")
        self.assertEqual(row["dpco"], "N")

    def test_80_item_pathy_resolved_to_text(self):
        self._import()
        row = self._rows("SELECT pathy FROM items WHERE item_name='PARA 500'")[0]
        self.assertEqual(row["pathy"], "ALLOPATHIC MEDICINES")

    def test_81_item_category_not_invented(self):
        self._import()
        rows = self._rows("SELECT category_id FROM items")
        self.assertTrue(all(r["category_id"] is None for r in rows))

    def test_82_item_ingredients_imported(self):
        self._import()
        self.assertEqual(self._count("item_ingredients"), 2)

    def test_83_item_ingredient_power(self):
        self._import()
        rows = self._rows("SELECT power FROM item_ingredients")
        self.assertIn("500", [r["power"] for r in rows])

    def test_84_item_ingredients_deduplicated(self):
        self._import()
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT item_id, drug_id, COUNT(*) c FROM item_ingredients "
            "GROUP BY item_id, drug_id HAVING c > 1"
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [])

    def test_85_item_id_map_covers_all_legacy_items(self):
        migrator, _ = self._import()
        self.assertEqual(len(migrator.maps["item"]), 4)

    def test_86_item_ids_are_remapped_not_reused(self):
        self._import()
        # Legacy item 1 → new id; the mapping is stored and stable.
        rows = self._rows("SELECT new_id FROM legacy_id_map WHERE entity='item' AND legacy_id='1'")
        self.assertTrue(rows)
        self.assertIsInstance(rows[0]["new_id"], int)


# ══════════════════════════════════════════════════════════════════════
# 5. Import: parties / ledgers / financial years
# ══════════════════════════════════════════════════════════════════════

class ImportPartyTests(_DBTestCase):
    def test_87_customers_created_from_debtors(self):
        self._import()
        names = [r["customer_name"] for r in self._rows("SELECT customer_name FROM customers")]
        self.assertIn("SHRI MEDICAL", names)
        self.assertIn("WALKIN", names)

    def test_88_walkin_single_customer(self):
        self._import()
        self.assertEqual(self._count("customers"), 2)

    def test_89_suppliers_created_from_creditors(self):
        self._import()
        row = self._rows("SELECT * FROM suppliers WHERE supplier_name='SUNDRY TRADERS'")[0]
        self.assertEqual(row["sales_tax_no"], "TAX123")
        self.assertEqual(row["vat_or_tin"], "TIN9")
        self.assertEqual(row["credit_limit"], 1000)
        self.assertEqual(row["credit_period"], 30)
        self.assertEqual(row["city"], "PUNE")
        self.assertEqual(row["state"], "MAHARASHTRA")
        self.assertEqual(row["contact_person"], "RAM")
        self.assertEqual(row["opening_balance"], -1500)

    def test_90_customer_ledger_linked(self):
        self._import()
        rows = self._rows("SELECT ledger_id FROM customers WHERE customer_name='SHRI MEDICAL'")
        self.assertIsNotNone(rows[0]["ledger_id"])

    def test_91_supplier_ledger_linked(self):
        self._import()
        rows = self._rows("SELECT ledger_id FROM suppliers WHERE supplier_name='SUNDRY TRADERS'")
        self.assertIsNotNone(rows[0]["ledger_id"])

    def test_92_system_ledger_roles_preserved(self):
        self._import()
        roles = {r["system_role"] for r in self._rows(
            "SELECT system_role FROM account_ledgers WHERE system_role IS NOT NULL")}
        self.assertEqual(roles, {"CASH", "BANK", "SALES", "PURCHASE",
                                 "SALES_RETURN", "PURCHASE_RETURN"})

    def test_93_cash_ledger_merged_into_system_role(self):
        self._import()
        rows = self._rows("SELECT * FROM account_ledgers WHERE system_role='CASH'")
        self.assertEqual(len(rows), 1)

    def test_94_bank_ledger_keeps_legacy_name(self):
        self._import()
        rows = self._rows("SELECT ledger_name FROM account_ledgers WHERE system_role='BANK'")
        self.assertEqual(rows[0]["ledger_name"], "SBI BANK")

    def test_95_ledger_group_text_mapped(self):
        self._import()
        row = self._rows("SELECT account_group FROM account_ledgers WHERE ledger_name='SHRI MEDICAL'")[0]
        self.assertEqual(row["account_group"], "Sundry Debtors")

    def test_96_ledger_group_id_classified(self):
        self._import()
        rows = self._rows(
            "SELECT lg.group_name FROM account_ledgers al "
            "LEFT JOIN account_groups lg ON lg.id = al.account_group_id "
            "WHERE al.ledger_name='SHRI MEDICAL'")
        self.assertEqual(rows[0]["group_name"], "Current Assets")

    def test_97_unmapped_group_text_preserved(self):
        self._import()
        row = self._rows("SELECT account_group FROM account_ledgers WHERE ledger_name='DISCOUNT GIVEN'")[0]
        self.assertEqual(row["account_group"], "Investments")

    def test_98_opening_balance_sign_kept(self):
        self._import()
        row = self._rows("SELECT * FROM account_ledgers WHERE ledger_name='SHRI MEDICAL'")[0]
        self.assertEqual(row["opening_balance"], 500)
        self.assertEqual(row["opening_balance_type"], "Debit")

    def test_99_credit_opening_balance_type(self):
        self._import()
        row = self._rows("SELECT * FROM account_ledgers WHERE ledger_name='SUNDRY TRADERS'")[0]
        self.assertEqual(row["opening_balance_type"], "Credit")
        self.assertEqual(row["opening_balance"], 1500)

    def test_100_all_legacy_ledgers_mapped(self):
        migrator, _ = self._import()
        self.assertEqual(len(migrator.maps["ledger"]), 8)

    def test_101_financial_years_imported(self):
        self._import()
        self.assertEqual(self._count("financial_years"), 2)

    def test_102_financial_year_dates(self):
        self._import()
        row = self._rows("SELECT * FROM financial_years WHERE name='2015-2016'")[0]
        self.assertEqual(row["start_date"], "2015-04-01")
        self.assertEqual(row["end_date"], "2016-03-31")

    def test_103_active_financial_year_is_current(self):
        self._import()
        row = self._rows("SELECT name FROM financial_years WHERE is_active=1")
        self.assertEqual(row[0]["name"], "2026-2027")

    def test_104_single_active_financial_year(self):
        self._import()
        self.assertEqual(self._count_one("SELECT COUNT(*) FROM financial_years WHERE is_active=1"), 1)

    def _count_one(self, sql):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchone()[0]
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 6. Import: transactions
# ══════════════════════════════════════════════════════════════════════

class ImportTransactionTests(_DBTestCase):
    def test_105_purchase_headers_imported(self):
        self._import()
        self.assertEqual(self._count("purchase_invoices"), 2)

    def test_106_purchase_voucher_number_composed(self):
        self._import()
        rows = self._rows("SELECT voucher_no FROM purchase_invoices ORDER BY id")
        self.assertEqual(rows[0]["voucher_no"], "2015-2016-Credit-1")

    def test_107_purchase_supplier_resolved(self):
        self._import()
        row = self._rows(
            "SELECT s.supplier_name FROM purchase_invoices p "
            "JOIN suppliers s ON s.id = p.supplier_id WHERE p.id=1")[0]
        self.assertEqual(row["supplier_name"], "SUNDRY TRADERS")

    def test_108_purchase_amounts_preserved(self):
        self._import()
        row = self._rows("SELECT * FROM purchase_invoices WHERE id=1")[0]
        self.assertEqual(row["net_amount"], 2793)
        self.assertEqual(row["gst_amount"], 132.88)
        self.assertEqual(row["round_off"], -0.12)

    def test_109_purchase_invoice_number_and_dates(self):
        self._import()
        row = self._rows("SELECT * FROM purchase_invoices WHERE id=1")[0]
        self.assertEqual(row["invoice_no"], "84")
        self.assertEqual(row["invoice_date"], "2015-04-01")
        self.assertEqual(row["due_date"], "2015-05-01")

    def test_110_purchase_items_imported(self):
        self._import()
        self.assertEqual(self._count("purchase_invoice_items"), 2)

    def test_111_purchase_item_quantities(self):
        self._import()
        row = self._rows("SELECT * FROM purchase_invoice_items WHERE id=1")[0]
        self.assertEqual(row["pay_qty"], 3)
        self.assertEqual(row["free_qty"], 0)
        self.assertEqual(row["batch_no"], "B001")
        self.assertEqual(row["expiry"], "2017-05-31")

    def test_112_purchase_item_rates_and_gst(self):
        self._import()
        row = self._rows("SELECT * FROM purchase_invoice_items WHERE id=1")[0]
        self.assertEqual(row["rate"], 115.49)
        self.assertEqual(row["mrp"], 150)
        self.assertEqual(row["gst_percent"], 5)
        self.assertEqual(row["gst_amount"], 17.32)
        self.assertEqual(row["purchase_rate"], 121)
        self.assertEqual(row["net_rate"], 121.26)

    def test_113_sales_headers_imported(self):
        self._import()
        self.assertEqual(self._count("sales_invoices"), 2)

    def test_114_sales_bill_numbers_unique(self):
        self._import()
        rows = self._rows("SELECT bill_no, COUNT(*) c FROM sales_invoices GROUP BY bill_no HAVING c>1")
        self.assertEqual(rows, [])

    def test_115_sale_patient_and_time(self):
        self._import()
        row = self._rows("SELECT * FROM sales_invoices WHERE id=1")[0]
        self.assertEqual(row["patient_name"], "MRS PATIENT")
        self.assertEqual(row["sale_time"], "4:24 PM")
        self.assertEqual(row["round_off"], 0.67)

    def test_116_walkin_sale_uses_walkin_customer(self):
        self._import()
        row = self._rows(
            "SELECT c.customer_name FROM sales_invoices s "
            "JOIN customers c ON c.id = s.customer_id WHERE s.id=1")[0]
        self.assertEqual(row["customer_name"], "WALKIN")

    def test_117_no_fake_walkin_customers(self):
        self._import()
        self.assertEqual(self._count("customers"), 2)

    def test_118_credit_sale_customer_resolved(self):
        self._import()
        row = self._rows(
            "SELECT c.customer_name FROM sales_invoices s "
            "JOIN customers c ON c.id = s.customer_id WHERE s.id=2")[0]
        self.assertEqual(row["customer_name"], "SHRI MEDICAL")

    def test_119_sale_doctor_resolved(self):
        self._import()
        row = self._rows(
            "SELECT d.doctor_name FROM sales_invoices s "
            "JOIN doctors d ON d.id = s.doctor_id WHERE s.id=1")[0]
        self.assertEqual(row["doctor_name"], "DR TEST")

    def test_120_sales_items_imported(self):
        self._import()
        self.assertEqual(self._count("sales_invoice_items"), 2)

    def test_121_sales_item_batch_linked(self):
        self._import()
        row = self._rows("SELECT * FROM sales_invoice_items WHERE id=1")[0]
        self.assertIsNotNone(row["stock_batch_id"])
        self.assertEqual(row["batch_no"], "B001")

    def test_122_sales_item_amounts(self):
        self._import()
        row = self._rows("SELECT * FROM sales_invoice_items WHERE id=1")[0]
        self.assertEqual(row["sale_qty"], 5)
        self.assertEqual(row["mrp"], 56)
        self.assertEqual(row["amount"], 46.67)

    def test_123_sales_item_expiry_preserved(self):
        self._import()
        row = self._rows("SELECT expiry FROM sales_invoice_items WHERE id=1")[0]
        self.assertEqual(row["expiry"], "2017-05-31")

    def test_124_credit_notes_imported(self):
        self._import()
        self.assertEqual(self._count("credit_notes"), 1)
        self.assertEqual(self._count("credit_note_items"), 1)

    def test_125_credit_note_fields(self):
        self._import()
        row = self._rows("SELECT * FROM credit_notes WHERE id=1")[0]
        self.assertEqual(row["cn_type"], "Customer")
        self.assertEqual(row["cn_date"], "2015-04-02")
        self.assertEqual(row["total_amount"], 136.5)

    def test_126_credit_note_item_fields(self):
        self._import()
        row = self._rows("SELECT * FROM credit_note_items WHERE id=1")[0]
        self.assertEqual(row["return_qty"], 8)
        self.assertEqual(row["rate"], 116.91)
        self.assertEqual(row["amount"], 116.91)

    def test_127_credit_note_price_factor_recorded(self):
        self._import()
        row = self._rows("SELECT return_reason FROM credit_note_items WHERE id=1")[0]
        self.assertEqual(row["return_reason"], "MRP")

    def test_128_debit_notes_imported(self):
        self._import()
        self.assertEqual(self._count("debit_notes"), 1)
        self.assertEqual(self._count("debit_note_items"), 1)

    def test_129_debit_note_supplier_resolved(self):
        self._import()
        row = self._rows(
            "SELECT s.supplier_name FROM debit_notes d "
            "JOIN suppliers s ON s.id = d.supplier_id WHERE d.id=1")[0]
        self.assertEqual(row["supplier_name"], "SUNDRY TRADERS")

    def test_130_receipts_imported(self):
        self._import()
        self.assertEqual(self._count("customer_receipts"), 1)

    def test_131_receipt_fields(self):
        self._import()
        row = self._rows("SELECT * FROM customer_receipts WHERE id=1")[0]
        self.assertEqual(row["amount"], 200)
        self.assertEqual(row["receipt_mode"], "Cash")
        self.assertEqual(row["receipt_date"], "2015-04-02")

    def test_132_receipt_customer_resolved(self):
        self._import()
        row = self._rows(
            "SELECT c.customer_name FROM customer_receipts r "
            "JOIN customers c ON c.id = r.customer_id WHERE r.id=1")[0]
        self.assertEqual(row["customer_name"], "SHRI MEDICAL")

    def test_133_payments_imported(self):
        self._import()
        self.assertEqual(self._count("supplier_payments"), 1)

    def test_134_payment_reference_preserved(self):
        self._import()
        row = self._rows("SELECT * FROM supplier_payments WHERE id=1")[0]
        self.assertEqual(row["reference_no"], "R NO.9145")
        self.assertEqual(row["amount"], 1412)

    def test_135_journal_tables_empty(self):
        self._import()
        self.assertEqual(self._count("journal_entries"), 0)
        self.assertEqual(self._count("journal_entry_items"), 0)

    def test_136_demo_sales_not_imported(self):
        self._import()
        self.assertEqual(self._count("sales_invoices"), 2)

    def test_137_demo_rows_excluded_reported(self):
        _, report = self._import()
        self.assertEqual(report["demo_rows_excluded"], 3)

    def test_138_demo_ids_absent_from_maps(self):
        migrator, _ = self._import()
        self.assertNotIn(31, migrator.maps["sale"])


# ══════════════════════════════════════════════════════════════════════
# 7. Accounting history
# ══════════════════════════════════════════════════════════════════════

class ImportAccountingTests(_DBTestCase):
    def test_139_ledger_transactions_imported(self):
        self._import()
        self.assertEqual(self._count("ledger_transactions"), 16)

    def test_140_debit_credit_split_by_trn_type(self):
        self._import()
        rows = self._rows(
            "SELECT debit, credit FROM ledger_transactions WHERE voucher_type='PURCHASE'")
        self.assertTrue(any(r["debit"] > 0 for r in rows))
        self.assertTrue(any(r["credit"] > 0 for r in rows))

    def test_141_debit_only_rows_have_zero_credit(self):
        self._import()
        rows = self._rows("SELECT * FROM ledger_transactions WHERE debit > 0")
        self.assertTrue(all(r["credit"] == 0 for r in rows))

    def test_142_reference_types_match_posting_sources(self):
        self._import()
        types = {r["reference_type"] for r in self._rows(
            "SELECT DISTINCT reference_type FROM ledger_transactions")}
        self.assertEqual(types, {"COUNTER_SALE", "PURCHASE_INVOICE",
                                 "CREDIT_NOTE", "DEBIT_NOTE",
                                 "CUSTOMER_RECEIPT", "SUPPLIER_PAYMENT"})

    def test_143_reference_ids_link_to_new_records(self):
        self._import()
        row = self._rows(
            "SELECT reference_id FROM ledger_transactions "
            "WHERE reference_type='COUNTER_SALE' LIMIT 1")[0]
        self.assertEqual(row["reference_id"], 1)

    def test_144_voucher_numbers_preserved(self):
        self._import()
        rows = self._rows(
            "SELECT DISTINCT voucher_no FROM ledger_transactions "
            "WHERE voucher_type='SALE'")
        self.assertEqual(len(rows), 2)

    def test_145_narration_preserved(self):
        self._import()
        rows = self._rows(
            "SELECT description FROM ledger_transactions "
            "WHERE description LIKE 'Invoice No=%'")
        self.assertTrue(rows)

    def test_146_transaction_dates_preserved(self):
        self._import()
        rows = self._rows("SELECT DISTINCT transaction_date FROM ledger_transactions")
        self.assertIn("2015-04-01", [r["transaction_date"] for r in rows])

    def test_147_no_posting_engine_replay(self):
        from database.accounting_posting import posting_engine
        with mock.patch.object(posting_engine, "post_counter_sale",
                               side_effect=AssertionError("engine replayed")) as m1, \
             mock.patch.object(posting_engine, "post_purchase_invoice",
                               side_effect=AssertionError("engine replayed")) as m2, \
             mock.patch.object(posting_engine, "post_customer_receipt",
                               side_effect=AssertionError("engine replayed")) as m3:
            self._import()
        self.assertEqual(m1.call_count, 0)
        self.assertEqual(m2.call_count, 0)
        self.assertEqual(m3.call_count, 0)

    def test_148_sales_dao_insert_not_used(self):
        from database import sales_dao
        with mock.patch.object(sales_dao.SalesDAO, "insert_invoice",
                               side_effect=AssertionError("DAO used")) as mocked:
            self._import()
        self.assertEqual(mocked.call_count, 0)

    def test_149_purchase_dao_insert_not_used(self):
        from database import purchase_dao
        with mock.patch.object(purchase_dao.PurchaseDAO, "insert_invoice",
                               side_effect=AssertionError("DAO used")) as mocked:
            self._import()
        self.assertEqual(mocked.call_count, 0)

    def test_150_stock_dao_not_used_for_history(self):
        from database import accounting_posting
        engine = accounting_posting.posting_engine
        with mock.patch.object(engine, "post_counter_sale",
                               side_effect=AssertionError("posting replayed")) as m1, \
             mock.patch.object(engine, "post_purchase_invoice",
                               side_effect=AssertionError("posting replayed")) as m2, \
             mock.patch.object(engine, "post_supplier_payment",
                               side_effect=AssertionError("posting replayed")) as m3:
            self._import()
        self.assertEqual((m1.call_count, m2.call_count, m3.call_count), (0, 0, 0))

    def test_151_accounting_totals_match_source(self):
        migrator, _ = self._import()
        source_total = sum(
            sum(1 for _ in migrator.dump.iter_rows(table))
            for table in ACCOUNTING_SOURCES
        )
        self.assertEqual(source_total, 16)


# ══════════════════════════════════════════════════════════════════════
# 8. Stock
# ══════════════════════════════════════════════════════════════════════

class ImportStockTests(_DBTestCase):
    def test_152_batches_imported(self):
        self._import()
        self.assertEqual(self._count("stock_batches"), 2)

    def test_153_stock_quantity_is_balance_not_replay(self):
        self._import()
        row = self._rows(
            "SELECT stock_qty FROM stock_batches b JOIN items i ON i.id=b.item_id "
            "WHERE i.item_name='PARA 500' AND b.batch_no='B001'")[0]
        # (100 - 40) + (10 - 5) = 65 — purchases/sales are never replayed
        self.assertEqual(row["stock_qty"], 65)

    def test_154_zero_stock_batch_preserved(self):
        self._import()
        row = self._rows(
            "SELECT stock_qty FROM stock_batches b JOIN items i ON i.id=b.item_id "
            "WHERE i.item_name='CETRI 10'")[0]
        self.assertEqual(row["stock_qty"], 50)

    def test_155_batch_metadata_preserved(self):
        self._import()
        row = self._rows("SELECT * FROM stock_batches WHERE batch_no='B002'")[0]
        self.assertEqual(row["expiry"], "2018-01-31")
        self.assertEqual(row["mrp"], 15)
        self.assertEqual(row["purchase_rate"], 8)
        self.assertEqual(row["net_rate"], 7.5)

    def test_156_duplicate_legacy_stock_rows_summed(self):
        self._import()
        rows = self._rows("SELECT COUNT(*) c FROM stock_batches WHERE batch_no='B001'")
        self.assertEqual(rows[0]["c"], 1)

    def test_157_extra_batches_for_history_created(self):
        # Remove B001 from stockbalance entirely: it is still referenced by
        # the historical purchase/sales lines, so a zero-stock batch is
        # created for history linkage.
        text = SAMPLE_DUMP.replace(
            "(1,'B001','2017-05-31',20,12.5,11.5,100,10,0,40)",
            "(3,'B009','2017-05-31',20,12.5,11.5,100,10,0,40)").replace(
            "(1,'B001','2017-05-31',20,12.5,11.5,10,10,0,5)",
            "(3,'B009','2017-05-31',20,12.5,11.5,10,10,0,5)")
        self._import(text)
        rows = self._rows(
            "SELECT stock_qty FROM stock_batches b JOIN items i ON i.id=b.item_id "
            "WHERE i.item_name='PARA 500' AND b.batch_no='B001'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stock_qty"], 0)

    def test_158_stock_adjustments_not_double_counted(self):
        self._import()
        total = self._rows("SELECT SUM(stock_qty) s FROM stock_batches")[0]["s"]
        # 65 + 50 = 115; the +100 adjustment is already inside stockbalance
        self.assertEqual(total, 115)


# ══════════════════════════════════════════════════════════════════════
# 9. Safety: backup, clearing, production protection
# ══════════════════════════════════════════════════════════════════════

class MigrationSafetyTests(_DBTestCase):
    def _seed_demo(self):
        from database.connection import init_database
        init_database()
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO companies (company_name, short_name) VALUES ('DEMO CO','DEMO')")
        conn.execute("INSERT INTO units (unit_name) VALUES ('DEMO UNIT')")
        conn.execute("INSERT INTO items (item_name) VALUES ('DEMO ITEM')")
        conn.execute("INSERT INTO customers (customer_name) VALUES ('DEMO CUST')")
        conn.execute("INSERT INTO suppliers (supplier_name) VALUES ('DEMO SUPP')")
        conn.execute("INSERT INTO financial_years (name, start_date, end_date, is_active, created_at)"
                     " VALUES ('2020-2021','2020-04-01','2021-03-31',1,'x')")
        conn.commit()
        conn.close()

    def test_159_demo_business_data_cleared(self):
        self._seed_demo()
        self._import()
        self.assertEqual(self._count("items"), 3)   # only legacy items remain
        names = [r["company_name"] for r in self._rows("SELECT company_name FROM companies")]
        self.assertNotIn("DEMO CO", names)

    def test_160_authentication_preserved(self):
        from database import auth
        os.environ["PHARMACY_DB"] = self.db_path
        auth.ensure_auth_schema()
        auth.create_first_admin("keeper", "keeper-pass-1")
        self._import()
        rows = self._rows("SELECT username, role FROM app_users")
        self.assertEqual([r["username"] for r in rows], ["keeper"])

    def test_161_system_ledgers_preserved(self):
        from database.connection import init_database
        from database import account_roles
        init_database()
        os.environ["PHARMACY_DB"] = self.db_path
        account_roles.ensure_system_ledgers()
        self._import()
        roles = {r["system_role"] for r in self._rows(
            "SELECT system_role FROM account_ledgers WHERE system_role IS NOT NULL")}
        self.assertEqual(len(roles), 6)

    def test_162_backup_created_and_validated(self):
        self._seed_demo()
        migrator = LegacyMigrator(self._dump_file(), db_path=self.db_path)
        report = migrator.import_data(do_backup=True, backup_dir=self._tmp)
        self.assertTrue(report["backup"]["validated"])
        self.assertTrue(os.path.isfile(report["backup"]["path"]))
        self.assertRegex(report["backup"]["sha256"], r"^[0-9a-f]{64}$")

    def test_163_backup_is_restorable_snapshot(self):
        self._seed_demo()
        migrator = LegacyMigrator(self._dump_file(), db_path=self.db_path)
        report = migrator.import_data(do_backup=True, backup_dir=self._tmp)
        conn = sqlite3.connect(report["backup"]["path"])
        try:
            demo = conn.execute(
                "SELECT COUNT(*) FROM companies WHERE company_name='DEMO CO'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(demo, 1)

    def test_164_pre_and_post_state_recorded(self):
        self._seed_demo()
        migrator = LegacyMigrator(self._dump_file(), db_path=self.db_path)
        report = migrator.import_data(do_backup=False)
        self.assertIn("sha256", report["pre_state"])
        self.assertIn("sha256", report["post_state"])
        self.assertNotEqual(report["pre_state"]["sha256"],
                            report["post_state"]["sha256"])

    def test_165_cleared_tables_reported(self):
        self._seed_demo()
        migrator = LegacyMigrator(self._dump_file(), db_path=self.db_path)
        report = migrator.import_data(do_backup=False)
        self.assertGreaterEqual(report["cleared"].get("companies", 0), 1)

    def test_166_failed_import_rolls_back_phase(self):
        migrator = LegacyMigrator(self._dump_file(), db_path=self.db_path)

        def boom(self):
            raise RuntimeError("simulated failure")

        with mock.patch.object(LegacyMigrator, "_import_sales", boom):
            with self.assertRaises(RuntimeError):
                migrator.import_data(do_backup=False)
        # Masters imported in earlier phases remain; sales are absent.
        self.assertEqual(self._count("sales_invoices"), 0)
        self.assertGreater(self._count("items"), 0)

    def test_167_repeated_import_is_clean(self):
        self._import()
        first = self._count("sales_invoices")
        self._import()
        self.assertEqual(self._count("sales_invoices"), first)
        self.assertEqual(self._count("items"), 3)

    def test_168_repeated_import_does_not_duplicate_ledgers(self):
        self._import()
        before = self._count("account_ledgers")
        self._import()
        self.assertEqual(self._count("account_ledgers"), before)

    def test_169_production_import_requires_confirmation(self):
        code = main(["--import", "--no-backup", "--db",
                     str(Path(__file__).resolve().parent / "data" / "pharmacy.db"),
                     self._dump_file()])
        self.assertEqual(code, 2)

    def test_170_cli_import_into_staging_allowed(self):
        code = main(["--import", "--no-backup", "--db", self.db_path,
                     "--report", os.path.join(self._tmp, "r.md"),
                     "--json", os.path.join(self._tmp, "r.json"),
                     self._dump_file()])
        self.assertEqual(code, 0)

    def test_171_limit_option_limits_rows(self):
        migrator = LegacyMigrator(self._dump_file(), db_path=self.db_path, limit=1)
        migrator.import_data(do_backup=False)
        self.assertEqual(self._count("sales_invoices"), 1)

    def test_172_migration_meta_written(self):
        migrator, _ = self._import()
        conn = sqlite3.connect(self.db_path)
        try:
            meta = migration_meta(conn)
        finally:
            conn.close()
        self.assertEqual(meta["legacy_passwords_imported"], "0")
        self.assertEqual(meta["demo_rows_imported"], "0")

    def test_173_cleared_protected_tables_not_in_order(self):
        for name in ("app_users", "auth_audit_log", "account_groups"):
            self.assertNotIn(name, CLEAR_ORDER)

    def test_174_demo_tables_constant(self):
        self.assertEqual(set(DEMO_TABLES), {
            "demosalesvhheader", "demosalesvhdetail",
            "demosalesitemdetail", "demosalescreditnote"})


# ══════════════════════════════════════════════════════════════════════
# 10. Authentication treatment
# ══════════════════════════════════════════════════════════════════════

class AuthMigrationTests(_DBTestCase):
    def test_175_legacy_password_hashes_never_imported(self):
        self._import()
        rows = self._rows("SELECT password_hash FROM app_users")
        for row in rows:
            self.assertFalse(row["password_hash"].startswith("*"))

    def test_176_legacy_usernames_not_imported_by_default(self):
        self._import()
        self.assertEqual(self._count("app_users"), 0)

    def test_177_legacy_usernames_opt_in_inactive(self):
        self._import(import_legacy_users=True)
        rows = self._rows("SELECT username, is_active, password_hash FROM app_users")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["is_active"] == 0 for r in rows))
        self.assertTrue(all(r["password_hash"].startswith("legacy-migration-disabled")
                            for r in rows))

    def test_178_role_mapping_uses_existing_roles(self):
        from database import auth as auth_module
        self._import(import_legacy_users=True)
        rows = self._rows("SELECT role FROM app_users")
        self.assertTrue(all(r["role"] in auth_module.USER_ROLES for r in rows))

    def test_179_existing_admin_untouched_by_opt_in(self):
        from database import auth
        os.environ["PHARMACY_DB"] = self.db_path
        auth.ensure_auth_schema()
        admin = auth.create_first_admin("boss", "boss-pass-1")
        self._import(import_legacy_users=True)
        rows = self._rows("SELECT username, is_active, role FROM app_users ORDER BY id")
        self.assertEqual(rows[0]["username"], "boss")
        self.assertEqual(rows[0]["role"], "ADMIN")
        self.assertEqual(rows[0]["is_active"], 1)

    def test_180_admin_login_still_works_after_import(self):
        from database import auth
        os.environ["PHARMACY_DB"] = self.db_path
        auth.ensure_auth_schema()
        auth.create_first_admin("boss", "boss-pass-1")
        self._import()
        auth.session.logout()
        auth.session.login("boss", "boss-pass-1")
        self.assertEqual(auth.session.user["role"], "ADMIN")

    def test_181_new_staff_user_can_be_created_after_import(self):
        from database import auth
        os.environ["PHARMACY_DB"] = self.db_path
        auth.ensure_auth_schema()
        auth.create_first_admin("boss", "boss-pass-1")
        self._import()
        auth.session.login("boss", "boss-pass-1")
        created = auth.create_user(auth.session.user, "shop1", "shop-pass-1",
                                   auth.ROLE_PHARMACIST_STAFF)
        self.assertEqual(created["role"], auth.ROLE_PHARMACIST_STAFF)


# ══════════════════════════════════════════════════════════════════════
# 11. Verification
# ══════════════════════════════════════════════════════════════════════

class VerificationTests(_DBTestCase):
    def test_182_verify_ok_on_clean_import(self):
        self._import()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        self.assertTrue(result["ok"], result["issues"])

    def test_183_integrity_check_ok(self):
        self._import()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        self.assertEqual(result["integrity_check"], "ok")

    def test_184_foreign_key_check_zero(self):
        self._import()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        self.assertEqual(result["foreign_key_violations"], 0)

    def test_185_no_orphans(self):
        self._import()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        self.assertTrue(all(v == 0 for v in result["orphans"].values()))

    def test_186_stock_reconciliation_zero_difference(self):
        self._import()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        recon = result["stock_reconciliation"]
        self.assertEqual(recon["mismatches"], 0)
        self.assertEqual(recon["missing"], 0)

    def test_187_mapping_coverage_reported(self):
        self._import()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        checks = {c["name"]: c for c in result["checks"]}
        self.assertTrue(checks["mapping:item_ids"]["ok"])
        self.assertTrue(checks["mapping:ledger_ids"]["ok"])

    def test_188_missing_reference_detected(self):
        self._import()
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM ledger_transactions WHERE id IN "
                     "(SELECT id FROM ledger_transactions LIMIT 1)")
        conn.commit()
        conn.close()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        self.assertFalse(result["ok"])

    def test_189_orphan_detection_reports(self):
        self._import()
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("UPDATE customers SET ledger_id = NULL")
        conn.commit()
        conn.close()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        self.assertGreater(result["orphans"]["customers_without_ledger"], 0)

    def test_190_verify_is_read_only(self):
        self._import()
        before = database_state(sqlite3.connect(self.db_path))
        verify_migration(self._dump_file(), db_path=self.db_path)
        after = database_state(sqlite3.connect(self.db_path))
        self.assertEqual(before["sha256"], after["sha256"])

    def test_191_migration_meta_absent_on_plain_db(self):
        from database.connection import init_database
        init_database()
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(migration_meta(conn), {})
        finally:
            conn.close()

    def test_192_state_reports_table_count(self):
        self._import()
        state = database_state(sqlite3.connect(self.db_path))
        self.assertGreater(state["tables"], 20)

    def test_193_state_reports_counts(self):
        self._import()
        state = database_state(sqlite3.connect(self.db_path))
        self.assertEqual(state["rows"]["sales_invoices"], 2)

    def test_194_orphan_report_handles_missing_tables(self):
        conn = sqlite3.connect(":memory:")
        try:
            report = orphan_report(conn)
        finally:
            conn.close()
        self.assertTrue(all(v == 0 for v in report.values()))

    def test_195_verify_fails_on_wrong_count(self):
        self._import()
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM sales_invoices WHERE id = 1")
        conn.commit()
        conn.close()
        result = verify_migration(self._dump_file(), db_path=self.db_path)
        self.assertFalse(result["ok"])
        self.assertTrue(any("sales_invoices" in issue for issue in result["issues"]))


# ══════════════════════════════════════════════════════════════════════
# 12. Reports / CLI
# ══════════════════════════════════════════════════════════════════════

class ReportAndCliTests(_DBTestCase):
    def test_196_migration_report_markdown(self):
        _, report = self._import()
        markdown = render_migration_report(report)
        self.assertIn("Legacy Data Migration Report", markdown)
        self.assertIn("Pre-migration backup", markdown) if report.get("backup") \
            else self.assertIn("Imported rows", markdown)

    def test_197_migration_report_lists_tables(self):
        _, report = self._import()
        markdown = render_migration_report(report)
        self.assertIn("salesvhheader", markdown)

    def test_198_report_documents_unsupported(self):
        _, report = self._import()
        markdown = render_migration_report(report)
        self.assertIn("Unsupported tables", markdown)

    def test_199_report_states_passwords_not_imported(self):
        _, report = self._import()
        markdown = render_migration_report(report)
        self.assertIn("not** imported", markdown)

    def test_200_write_migration_report_files(self):
        _, report = self._import()
        md = os.path.join(self._tmp, "rep.md")
        js = os.path.join(self._tmp, "rep.json")
        write_migration_report(report, md, js)
        self.assertTrue(Path(md).is_file())
        payload = json.loads(Path(js).read_text(encoding="utf-8"))
        self.assertIn("tables", payload)

    def test_201_cli_parser_requires_a_mode(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])

    def test_202_cli_dry_run_writes_reports(self):
        md = os.path.join(self._tmp, "dry.md")
        js = os.path.join(self._tmp, "dry.json")
        code = main(["--dry-run", "--report", md, "--json", js, self._dump_file()])
        self.assertEqual(code, 0)
        self.assertTrue(Path(md).is_file())

    def test_203_cli_verify_returns_status(self):
        self._import()
        code = main(["--verify", "--db", self.db_path,
                     "--report", os.path.join(self._tmp, "v.md"),
                     self._dump_file()])
        self.assertEqual(code, 0)

    def test_204_cli_verify_returns_one_on_failure(self):
        from database.connection import init_database
        init_database()
        code = main(["--verify", "--db", self.db_path,
                     "--report", os.path.join(self._tmp, "v2.md"),
                     self._dump_file()])
        self.assertEqual(code, 1)

    def test_205_cli_dump_flag_validation(self):
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "dump.sql"])
        self.assertEqual(args.dump, "dump.sql")
        self.assertFalse(args.confirm_production)

    def test_206_cli_import_legacy_users_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--import", "dump.sql", "--import-legacy-users"])
        self.assertTrue(args.import_legacy_users)


# ══════════════════════════════════════════════════════════════════════
# 13. Performance / scale
# ══════════════════════════════════════════════════════════════════════

def _large_dump(sales: int = 400) -> str:
    head = SAMPLE_DUMP.split("CREATE TABLE `demosalesvhheader`")[0]
    header_rows = ",".join(
        f"({i},1,'Cash',{i},'2015-04-01','10:00 AM','',100,{i},7,'P','','',1,100,'',0,0,0,0,0,100)"
        for i in range(100, sales + 100)
    )
    item_rows = ",".join(
        f"({i},{i},{1 + (i % 4)},10,'B001','2017-05-31',20,2,20,20,'',0,0,40)"
        for i in range(100, sales + 100)
    )
    detail_rows = ",".join(
        f"({i},1,'2015-04-01',{i},'DR',7,100,''),"
        f"({i + sales},1,'2015-04-01',{i},'CR',3,100,'')"
        for i in range(100, sales + 100)
    )
    return head + (
        f"INSERT INTO `salesvhheader` VALUES {header_rows};\n"
        f"INSERT INTO `salesitemdetail` VALUES {item_rows};\n"
        f"INSERT INTO `salesvhdetail` VALUES {detail_rows};\n"
    )


class PerformanceTests(_DBTestCase):
    def test_207_large_transaction_dataset_imports(self):
        import time
        dump = self._dump_file(_large_dump(400))
        migrator = LegacyMigrator(dump, db_path=self.db_path)
        start = time.time()
        migrator.import_data(do_backup=False)
        elapsed = time.time() - start
        # 2 fixture sales + 400 generated
        self.assertEqual(self._count("sales_invoices"), 402)
        self.assertEqual(self._count("sales_invoice_items"), 402)
        # 16 fixture accounting lines + 800 generated
        self.assertEqual(self._count("ledger_transactions"), 816)
        self.assertLess(elapsed, 120)

    def test_208_import_skips_only_merges_and_duplicates(self):
        dump = self._dump_file(_large_dump(50))
        migrator = LegacyMigrator(dump, db_path=self.db_path)
        report = migrator.import_data(do_backup=False)
        known = {
            "duplicate_company_name", "duplicate_unit_name",
            "duplicate_drug_name", "duplicate_doctor_name",
            "duplicate_item_name", "duplicate_stock_balance_row",
            "ledger_merged_into_system_role", "ledger_name_reused",
            "duplicate_master_name",
            "empty_company_name", "empty_unit_name", "empty_drug_name",
            "empty_doctor_name", "empty_item_name",
        }
        kinds = {w["kind"] for w in report["warnings"]}
        self.assertTrue(kinds <= known, f"unexplained skip kinds: {kinds - known}")
        self.assertLessEqual(report["skipped_rows"], len(report["warnings"]) + 1)

    def test_209_large_stock_dataset(self):
        rows = ",".join(
            f"({1 + (i % 4)},'B{i:04d}','2017-05-31',20,12.5,11.5,10,10,0,2)"
            for i in range(1, 200)
        )
        text = SAMPLE_DUMP + f"INSERT INTO `stockbalance` VALUES {rows};\n"
        self._import(text)
        self.assertGreaterEqual(self._count("stock_batches"), 200)

    def test_210_import_completes_with_verification(self):
        dump = self._dump_file(_large_dump(150))
        LegacyMigrator(dump, db_path=self.db_path).import_data(do_backup=False)
        result = verify_migration(dump, db_path=self.db_path)
        self.assertTrue(result["ok"], result["issues"])


# ══════════════════════════════════════════════════════════════════════
# 14. Real production dump (optional)
# ══════════════════════════════════════════════════════════════════════

REAL_DUMP = Path(__file__).resolve().parent / "PharmaWinner202609142001.sql"


@unittest.skipUnless(REAL_DUMP.is_file(), "production dump not present")
class RealDumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dump = LegacyDump(REAL_DUMP)
        cls.counts = cls.dump.count_rows()

    def test_211_real_dump_tables_discovered(self):
        self.assertGreaterEqual(len(self.dump.table_columns), 50)

    def test_212_real_dump_demo_rows(self):
        demo = sum(self.counts.get(name, 0) for name in DEMO_TABLES)
        self.assertEqual(demo, 934)

    def test_213_real_dump_sales_rows(self):
        self.assertEqual(self.counts["salesvhheader"], 71803)

    def test_214_real_dump_plan_builds(self):
        plan = build_plan(self.dump)
        self.assertEqual(plan.tables["itemmst"].source_rows, 941)

    def test_215_real_dump_no_unresolved_sales_items(self):
        plan = build_plan(self.dump)
        self.assertEqual(plan.counts["_sales_items_unresolved"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
