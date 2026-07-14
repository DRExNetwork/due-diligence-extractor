#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document categories and extraction schemas for due diligence documents.
Supports two-level categorization: Top-level category → Document type
"""

from __future__ import annotations

import html
import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Type
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ddx.classification.cnel_energy_bill import (
    CnelEnergyBillData,
    normalize_cnel_energy_bill,
)

# =============================================================================
# Top-Level Categories (Level 1)
# =============================================================================
DocumentLanguageAnswer = Literal["Spanish", "English", "Other"]
YesNoAnswer = Literal["Sí", "No"]
YES_NO_RESPONSE_INSTRUCTION = (
    "Return exactly one of: Sí, No. " "Do not return true/false or any other variant."
)
SOURCE_LANGUAGE_RESPONSE_INSTRUCTION = (
    "Return the response in the language indicated by document_language. "
    "If document_language is Spanish, answer entirely in Spanish. "
    "If document_language is English, answer entirely in English. "
    "Do not answer in English when document_language is Spanish. "
    "Do not translate unless document_language explicitly requires it."
)


class TopLevelCategory(str, Enum):
    """Top-level document categories."""

    COMPANY_INFORMATION = "Company Information"
    COMPANY_FINANCIALS = "Company Financials"
    FINANCIAL = "Financial"
    COMPANY_EXPERIENCE = "Company Experience"
    TECHNICAL = "Technical"
    ESG = "ESG"
    PERMITS = "Permits"
    LEGAL = "Legal"
    REGULATORY = "Regulatory"


# =============================================================================
# Document Types (Level 2)
# =============================================================================


class DocumentType(str, Enum):
    """Document type enum - second level classification."""

    # Company Information Documents
    CERTIFICATE_OF_LEGAL_EXISTENCE = "Certificate of Legal Existence"
    SHAREHOLDERS_DECLARATION = "Shareholders Declaration"
    LEGAL_REPRESENTATIVE_APPOINTMENT = "Legal Representative Appointment"
    ENERGY_CONSUMPTION_BILLS = "Energy Consumption Bills / Energy Reports"

    # Company Financials Documents
    FINANCIAL_STATEMENTS = "Financial Statements"
    INCOME_TAX_FILINGS = "Income Tax Filings"
    CASH_FLOW_STATEMENTS = "Cash Flow Statements"
    TAX_COMPLIANCE_CERTIFICATE = "Tax Compliance Certificate"
    ECONOMICAL_OFFER_BOQ = "Economical Offer / BOQ"

    # Company Experience Documents
    PROJECT_ACCEPTANCE_CERTIFICATES = "Project Acceptance Certificates"
    OAM_CONTRACTS = "O&M Contracts"

    # Technical Documents
    PROJECT_SIMULATION_REPORT = "Project Simulation Report"
    PROJECT_DATA_EQUIPMENT_SHEETS = "Project Data Main Equipment Sheets"
    MODULE_IEC_CERTIFICATE = "Module IEC Certificate"
    INVERTER_IEC_CERTIFICATE = "Inverter IEC Certificate"
    MODULE_BLOOMBERG_EVIDENCE = "Module Bloomberg Evidence"
    INVERTER_BLOOMBERG_EVIDENCE = "Inverter Bloomberg Evidence"
    PROJECT_BASIC_ENGINEERING = "Project Basic Engineering"
    PROJECT_VISIT_REPORT = "Project Visit Report"
    PROJECT_LAYOUT = "Project Layout"
    KMZ_POLIGON = "KMZ Poligon"
    CABLE_SIZING_CALCULATION = "Cable Sizing Calculation Report"
    GROUNDING_SYSTEM_DIAGRAM = "Grounding System"

    # ESG Documents
    ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN = "Environmental and Social Management Plan"
    QAQC_COMMISSIONING_PROCEDURES = "QA/QC & Commissioning Procedures"
    INDUSTRIAL_SAFETY_PLAN = "Industrial Safety Plan"
    ENVIRONMENTAL_LICENCE_EIA = "Environmental Licence / EIA"
    EMERGENCY_RESPONSE_SECURITY_PLAN = "Emergency Response & Security Plan"
    SITE_LEGAL_STATUS_SUMMARY = "Site Legal Status Summary"
    LIENS_CERTIFICATE = "Liens Certificate"
    NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE = "Non-overlap with Protected Areas Certificate"
    HR_POLICY_CODE_OF_CONDUCT = "HR Policy / Code of Conduct"

    # Permits Documents
    ELECTRICAL_UTILITY_FEASIBILITY_REPORT = "Electrical Utility Feasibility Report"
    LAND_USE_PERMIT = "Land Use Permit"

    # Energy Monitoring — Financial module (Epic PD-236 / PD-269, NOT Data Room).
    # The value slugs to "cnel_energy_bill" — the document_type the NestJS bill
    # pipeline sends to POST /api/v1/extract/validate. Do not rename.
    # Deliberately ABSENT from DOCUMENT_TYPE_TO_TOP_LEVEL: that registry feeds the
    # bulk-ingest classification prompts (build_classification_schema_for_category),
    # and this type must never become a Data Room classification candidate.
    CNEL_ENERGY_BILL = "CNEL Energy Bill"

    # Uncategorized
    UNCATEGORIZED = "Uncategorized Document"


# =============================================================================
# Category Mappings
# =============================================================================

DOCUMENT_TYPE_TO_TOP_LEVEL: dict[DocumentType, TopLevelCategory] = {
    # Company Information
    DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE: TopLevelCategory.COMPANY_INFORMATION,
    DocumentType.SHAREHOLDERS_DECLARATION: TopLevelCategory.COMPANY_INFORMATION,
    DocumentType.LEGAL_REPRESENTATIVE_APPOINTMENT: TopLevelCategory.COMPANY_INFORMATION,
    DocumentType.ENERGY_CONSUMPTION_BILLS: TopLevelCategory.COMPANY_INFORMATION,
    # Company Financials
    DocumentType.FINANCIAL_STATEMENTS: TopLevelCategory.COMPANY_FINANCIALS,
    DocumentType.INCOME_TAX_FILINGS: TopLevelCategory.COMPANY_FINANCIALS,
    DocumentType.CASH_FLOW_STATEMENTS: TopLevelCategory.COMPANY_FINANCIALS,
    DocumentType.TAX_COMPLIANCE_CERTIFICATE: TopLevelCategory.COMPANY_FINANCIALS,
    DocumentType.ECONOMICAL_OFFER_BOQ: TopLevelCategory.FINANCIAL,
    # Company Experience
    DocumentType.PROJECT_ACCEPTANCE_CERTIFICATES: TopLevelCategory.COMPANY_EXPERIENCE,
    DocumentType.OAM_CONTRACTS: TopLevelCategory.COMPANY_EXPERIENCE,
    # Technical
    DocumentType.PROJECT_SIMULATION_REPORT: TopLevelCategory.TECHNICAL,
    DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS: TopLevelCategory.TECHNICAL,
    DocumentType.MODULE_IEC_CERTIFICATE: TopLevelCategory.TECHNICAL,
    DocumentType.INVERTER_IEC_CERTIFICATE: TopLevelCategory.TECHNICAL,
    DocumentType.MODULE_BLOOMBERG_EVIDENCE: TopLevelCategory.TECHNICAL,
    DocumentType.INVERTER_BLOOMBERG_EVIDENCE: TopLevelCategory.TECHNICAL,
    DocumentType.PROJECT_BASIC_ENGINEERING: TopLevelCategory.TECHNICAL,
    DocumentType.PROJECT_VISIT_REPORT: TopLevelCategory.TECHNICAL,
    DocumentType.PROJECT_LAYOUT: TopLevelCategory.TECHNICAL,
    DocumentType.KMZ_POLIGON: TopLevelCategory.TECHNICAL,
    DocumentType.CABLE_SIZING_CALCULATION: TopLevelCategory.TECHNICAL,
    DocumentType.GROUNDING_SYSTEM_DIAGRAM: TopLevelCategory.TECHNICAL,
    # ESG
    DocumentType.ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN: TopLevelCategory.ESG,
    DocumentType.QAQC_COMMISSIONING_PROCEDURES: TopLevelCategory.ESG,
    DocumentType.INDUSTRIAL_SAFETY_PLAN: TopLevelCategory.ESG,
    DocumentType.ENVIRONMENTAL_LICENCE_EIA: TopLevelCategory.ESG,
    DocumentType.EMERGENCY_RESPONSE_SECURITY_PLAN: TopLevelCategory.ESG,
    DocumentType.SITE_LEGAL_STATUS_SUMMARY: TopLevelCategory.ESG,
    DocumentType.LIENS_CERTIFICATE: TopLevelCategory.ESG,
    DocumentType.NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE: TopLevelCategory.ESG,
    DocumentType.HR_POLICY_CODE_OF_CONDUCT: TopLevelCategory.ESG,
    DocumentType.LAND_USE_PERMIT: TopLevelCategory.ESG,
    # Permits
    DocumentType.ELECTRICAL_UTILITY_FEASIBILITY_REPORT: TopLevelCategory.PERMITS,
}

DOCUMENT_TYPE_DESCRIPTIONS: dict[DocumentType, str] = {
    # Company Information
    DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE: (
        "Government-issued tax registry or commercial registry certificate whose PRIMARY SUBJECT is the COMPANY's registration record — not the appointment of any individual. "
        "ISSUER is always a government authority: SRI (Servicio de Rentas Internas), Registro Mercantil, Superintendencia de Compañías, Cámara de Comercio, or equivalent. "
        "The document header prominently shows the issuing government body and contains fields such as: RUC / tax ID number, commercial activity code (e.g. L68200301), tax regime (GENERAL/RIMPE), date of registration, date of incorporation, business address, and open/closed establishments. "
        "A 'Representante legal' name may appear as ONE registered data field but the document is about the company record, NOT about designating that person. "
        "CRITICAL — DO NOT classify as this type if: (1) the document's core action is to designate or appoint a person; (2) the issuer is the company's own assembly, president, secretary, or notary certifying a corporate resolution; "
        "(3) the document is a 'Certificado Digital de Datos de Identidad' or 'Información Adicional del Ciudadano' from Registro Civil — those are PERSONAL IDENTITY documents, not company existence certificates; "
    ),
    DocumentType.SHAREHOLDERS_DECLARATION: "Declaration document listing shareholders/owners with their ownership percentages (>10% stake)",
    DocumentType.LEGAL_REPRESENTATIVE_APPOINTMENT: (
        "Document whose PRIMARY LEGAL PURPOSE is to APPOINT, DESIGNATE, CERTIFY, or CONFIRM a specific person as legal representative, administrator, apoderado, gerente, or authorized signatory of an entity. "
        "The CORE ACTION of the document is the designation of a person, not the registration status of the company. "
        "STRONG INDICATORS — classify as this type when ANY of these are present: "
        "phrases 'resolvieron designar', 'designar como ADMINISTRADOR', 'nombrar como Representante Legal', 'nombramiento', 'appoint as', 'se designa'; "
        "assembly or shareholder resolution language; "
        "Presidente + Secretario signatures on a corporate resolution; "
        "mandate duration such as 'por el periodo de CINCO AÑOS'; "
        "a named individual being granted authority over the entity. "
        "MULTI-PAGE BUNDLE RULE — These documents are routinely submitted as multi-page PDF bundles. "
        "The first 1–2 substantive pages contain the appointment resolution (Certificación, Nombramiento, Acta de Asamblea) "
        "and/or a notarial 'Diligencia de Reconocimiento de Firmas'. "
        "Later pages are supporting personal identity attachments of the appointed person: "
        "Certificado Digital de Datos de Identidad, Información Adicional del Ciudadano, cédulas de identidad, Certificado de Votación, RUC information. "
        "IF the first substantive pages contain appointment language or an assembly certification, "
        "classify the ENTIRE PDF as LEGAL_REPRESENTATIVE_APPOINTMENT — "
        "the presence of identity documents or RUC data on later pages does NOT change the classification. "
        "DO NOT classify as CERTIFICATE_OF_LEGAL_EXISTENCE merely because: "
        "a RUC number appears, the company name appears, the phrase 'Representante legal' appears, or identity documents are attached. "
        "THIS DOCUMENT TYPE TAKES PRIORITY over Certificate of Legal Existence whenever appointment language is present on the lead pages."
    ),
    DocumentType.ENERGY_CONSUMPTION_BILLS: "Energy consumption bills or energy reports from the electricity utility provider",
    # Company Financials
    DocumentType.FINANCIAL_STATEMENTS: "Audited or internal financial statements with balance sheet and income statement data including revenue, net income, EBIT, assets, liabilities, and equity (minimum 3 years)",
    DocumentType.INCOME_TAX_FILINGS: "SRI/Tax authority filings showing income tax paid per fiscal year (minimum 3 years)",
    DocumentType.CASH_FLOW_STATEMENTS: "Cash flow statements showing operating, investing, and financing cash flows",
    DocumentType.TAX_COMPLIANCE_CERTIFICATE: "Certificate from tax authority (SRI) confirming tax compliance status with no outstanding debts",
    # Company Experience
    DocumentType.PROJECT_ACCEPTANCE_CERTIFICATES: "Project acceptance certificates or completion certificates from previous solar/renewable energy projects, containing project title, certificate type (Provisional/Final), client name, certificate date, scope of work, and client signature confirmation",
    DocumentType.OAM_CONTRACTS: "Operations and Maintenance (O&M) contracts for solar installations, containing planned maintenance approach and service terms",
    # Technical
    DocumentType.PROJECT_SIMULATION_REPORT: "Technical simulation results and performance analysis for the solar project (PVsyst/Helioscope)",
    DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS: "Equipment specifications including solar modules, inverters, and mounting structures",
    DocumentType.MODULE_IEC_CERTIFICATE: "Third-party IEC certificate for a solar module. Extract the IEC standard code and certificate validity/expiry date.",
    DocumentType.INVERTER_IEC_CERTIFICATE: "Third-party IEC certificate for an inverter. Extract the IEC standard code and certificate validity/expiry date.",
    DocumentType.MODULE_BLOOMBERG_EVIDENCE: "BloombergNEF or Bloomberg evidence document for a solar module brand. Extract only the rating or qualification shown.",
    DocumentType.INVERTER_BLOOMBERG_EVIDENCE: "BloombergNEF or Bloomberg evidence document for an inverter brand. Extract only the rating or qualification shown.",
    DocumentType.PROJECT_BASIC_ENGINEERING: "Fundamental engineering design and technical specifications",
    DocumentType.PROJECT_VISIT_REPORT: "Field visit observations and assessment findings",
    DocumentType.PROJECT_LAYOUT: "Spatial arrangement and layout diagrams of the project",
    DocumentType.KMZ_POLIGON: "Geographic polygon data in KMZ format",
    DocumentType.CABLE_SIZING_CALCULATION: "Cable sizing calculations and electrical specifications",
    DocumentType.GROUNDING_SYSTEM_DIAGRAM: "Grounding system design and single line diagram",
    # ESG
    DocumentType.ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN: "Environmental and Social Management Plan (EMP/ESMP) or ESHS Policy. This document covers high-level corporate ESG commitments AND/OR field-level worker safety and health. It may include: validity periods, corporate monitoring indicators, mitigation strategies for biodiversity vs climate, AND/OR strict field procedures, PPE rules, worker rights, hazard handling, site waste disposal, and OHS principles. Often titled 'PGAS', 'EMP', 'ESMP', 'Health & Safety Plan', or 'ESHS Policy'.",
    DocumentType.QAQC_COMMISSIONING_PROCEDURES: "Quality Assurance/Quality Control and commissioning procedures document including visual inspection summary, electrical test results, and performance metrics",
    DocumentType.INDUSTRIAL_SAFETY_PLAN: "Industrial Safety Plan document containing IFC-aligned HR practices that should be summarized in the source document language",
    DocumentType.ENVIRONMENTAL_LICENCE_EIA: "Environmental licence or EIA documentation including licence metadata and ESG risk-screening findings for habitats, biodiversity, communities, heritage, and consultation.",
    DocumentType.EMERGENCY_RESPONSE_SECURITY_PLAN: "Emergency response and security plan covering climate and security risks, crisis protocols, adaptation actions, and authority coordination.",
    DocumentType.SITE_LEGAL_STATUS_SUMMARY: "Site legal status summary with land tenure, title/lease documentation, rights and claims, disputes, and expropriation risk context.",
    DocumentType.LIENS_CERTIFICATE: "Liens certificate detailing existing mortgages/lien encumbrances and whether lender consent is required.",
    DocumentType.NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE: "Certificate confirming non-overlap with protected areas, including geographic reference and issuance/validity details.",
    DocumentType.HR_POLICY_CODE_OF_CONDUCT: "HR policy and code of conduct covering human rights, labor standards, forced/child labor prohibition, non-discrimination, and supplier labor requirements.",
    DocumentType.LAND_USE_PERMIT: "Land use permit or zoning approval for the project site",
    # Permits
    DocumentType.ELECTRICAL_UTILITY_FEASIBILITY_REPORT: "Utility feasibility report from the electrical distribution company containing capacity requested, feasibility status, available hosting capacity, maximum permitted annual generation, regulatory framework, issue date, and validity period",
    # Energy Monitoring — Financial module (never a Data Room classification candidate)
    DocumentType.CNEL_ENERGY_BILL: "Monthly CNEL EP electricity bill for an SGDA subscriber (net-metered) — Energy Monitoring bill-upload pipeline (PD-269), extracted via extract/validate only",
    # Uncategorized
    DocumentType.UNCATEGORIZED: "Documents that do not fit into any of the predefined categories",
}


# =============================================================================
# Company Information Extraction Schemas (Section 1.1 - 1.3)
# =============================================================================


class LegalInformation(BaseModel):
    """Schema for Certificate of Legal Existence (Section 1.1)."""

    model_config = ConfigDict(extra="forbid")

    # Extracted fields
    legal_name: str = Field(description="Registered company name as stated in the certificate")
    tax_id_ruc: str = Field(description="Tax ID (RUC) - Ecuador RUC number")
    commercial_activity: str = Field(
        description="Commercial activity or business purpose as registered"
    )
    incorporation_date: str = Field(
        description="Date of company incorporation (format: YYYY-MM-DD if possible)"
    )

    # Computed field (will be calculated post-extraction)
    years_operating: Optional[int] = Field(
        default=None,
        description="Years operating - computed as current year minus incorporation year",
    )


class ShareholderEntry(BaseModel):
    """Individual shareholder information."""

    model_config = ConfigDict(extra="forbid")

    shareholder_name: str = Field(description="Full name of the shareholder")
    ownership_percentage: float = Field(description="Ownership percentage of the shareholder")


class ShareholderStructure(BaseModel):
    """Schema for Shareholders Declaration (Section 1.2)."""

    model_config = ConfigDict(extra="forbid")

    number_of_shareholders: int = Field(
        description="Total number of shareholders listed in the declaration"
    )
    shareholders: List[ShareholderEntry] = Field(
        description="List of shareholders with >10% ownership stake"
    )


class LegalRepresentation(BaseModel):
    """Schema for Legal Representative Appointment (Section 1.3)."""

    model_config = ConfigDict(extra="forbid")

    legal_representative_name: str = Field(
        description="Full name of the appointed legal representative"
    )
    date_of_appointment: str = Field(
        description="Date when the legal representative was appointed (format: YYYY-MM-DD if possible)"
    )
    years_of_validity: int = Field(description="Number of years the appointment is valid")


# =============================================================================
# Energy Consumption Bills / Energy Reports (Section 2.1)
# =============================================================================


class EnergyConsumptionBillsData(BaseModel):
    """
    Single monthly electricity bill extraction entry.

    One entry corresponds to one uploaded monthly bill document.
    Contains the full bill-level account/provider metadata and monthly consumption
    metrics for that billing period.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Utility Provider & Account Information (monthly bill context)
    # -------------------------------------------------------------------------
    electricity_utility_provider: Optional[str] = Field(
        default=None,
        description=(
            "Name of the electricity utility provider. "
            "Primary source: visual logo at the top-left corner of the bill (e.g., CNEL EP, EEQ). "
            "Fallback: first header line with the full legal provider name "
            "(e.g., 'Empresa Electrica Publica Estrategica Corporacion Nacional de Electricidad CNEL EP'). "
            "Return a normalized short name (e.g., 'CNEL EP', 'EEQ')."
        ),
    )
    razon_social: Optional[str] = Field(
        default=None,
        description=(
            "Legal business name of the account holder / offtaker as printed on the bill (Razon Social). "
            "Used for verification only."
        ),
    )
    ruc: Optional[str] = Field(
        default=None,
        description=(
            "RUC (Ecuador tax ID) of the account holder as printed on the bill. "
            "Used for verification only."
        ),
    )
    contract_number: Optional[str] = Field(
        default=None,
        description=(
            "Contract or supply point number as printed on the bill. " "Used for verification only."
        ),
    )
    account_number: Optional[str] = Field(
        default=None,
        description="Utility account number or client ID printed on the bill",
    )
    meter_number: Optional[str] = Field(
        default=None,
        description="Electric meter identifier printed on the bill",
    )
    service_address: Optional[str] = Field(
        default=None,
        description="Service address for the energy account as printed on the bill",
    )
    tariff_category: Optional[str] = Field(
        default=None,
        description=(
            "Tariff category / bill type as stated on the bill. "
            "Examples: Sin Demanda, Demanda Horaria, Demanda Horaria Diferenciada, Con Demanda, "
            "Industrial, Commercial, Residential."
        ),
    )
    power_factor: Optional[float] = Field(
        default=None,
        description=(
            "Power factor (FP) for the billing period as printed on the bill (e.g., 0.9784). "
            "Dimensionless value between 0 and 1."
        ),
    )

    # -------------------------------------------------------------------------
    # Billing Period Identification
    # -------------------------------------------------------------------------
    month: str = Field(
        description="Calendar month of the billing period as the full English month name (e.g., 'January', 'February'). Always return the month name, never a number."
    )
    year: Optional[int] = Field(
        default=None,
        description="Calendar year of the billing period (e.g., 2025)",
    )
    billing_period_start: Optional[str] = Field(
        default=None,
        description="Start date of the billing period shown on the bill (YYYY-MM-DD)",
    )
    billing_period_end: Optional[str] = Field(
        default=None,
        description="End date of the billing period shown on the bill (YYYY-MM-DD)",
    )

    # -------------------------------------------------------------------------
    # Energy Consumption
    # -------------------------------------------------------------------------
    energy_consumption_kwh: float = Field(
        description=(
            "Total energy consumed this billing period in kWh. "
            "In the detail table, sum 'Consumo Total' for every row whose Unidad Medida is kWh "
            "(Energia act. hor. A + B + C, and D if present). "
            "For bill type 4 (Con Demanda - single energy row), use that row's Consumo Total directly. "
            "Convert MWh or GWh to kWh."
        )
    )

    # -------------------------------------------------------------------------
    # Demand Values
    # -------------------------------------------------------------------------
    average_demand_kw: Optional[float] = Field(
        default=None,
        description=(
            "Billable demand for this billing period in kW. "
            "Read from the 'Demanda facturable' row, Consumo Total column (unit kW). "
            "Set to null if no 'Demanda facturable' row exists (bill type 1 - Sin Demanda). "
            "Convert MW to kW if needed."
        ),
    )

    # -------------------------------------------------------------------------
    # Tariff & Cost
    # -------------------------------------------------------------------------
    energy_tariff_usd_kwh: Optional[float] = Field(
        default=None,
        description=(
            "Computed monthly weighted energy tariff in USD/kWh for this billing period. "
            "Formula: total_bill_amount_usd / energy_consumption_kwh. "
            "Use values computed from kWh detail rows. "
            "Round to 4 decimal places."
        ),
    )
    total_bill_amount_usd: Optional[float] = Field(
        default=None,
        description=(
            "Total energy charge in USD for this billing period. "
            "Sum the 'Monto' column for all kWh rows in the detail table "
            "(Energia act. hor. A + B + C + D if present). "
            "For bill type 4 (single energy row), use that row's Monto directly."
        ),
    )


class EnergyConsumptionBillsCollection(BaseModel):
    """
    Top-level extraction schema for energy consumption bills.

    Users upload one document per month. Each month is represented as one
    entry in `monthly_consumption` (a List[EnergyConsumptionBillsData]).

    Annual aggregation is performed downstream after collecting all monthly entries.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Monthly Consumption Data (array; one entry = one uploaded monthly bill)
    # -------------------------------------------------------------------------
    monthly_consumption: List[EnergyConsumptionBillsData] = Field(
        description=(
            "Monthly bill entries extracted from uploaded documents. "
            "Each entry contains account/provider metadata, billing period, and consumption values."
        )
    )

    # -------------------------------------------------------------------------
    # Computed Annual Totals (populated downstream after all months collected)
    # -------------------------------------------------------------------------
    annual_energy_consumption_kwh: Optional[float] = Field(
        default=None,
        description=(
            "Total annual energy consumption in kWh - "
            "sum of energy_consumption_kwh across all monthly entries. "
            "Leave null for single-month extraction; compute downstream."
        ),
    )
    annual_average_demand_kw: Optional[float] = Field(
        default=None,
        description=(
            "Annual average demand in kW - "
            "sum of average_demand_kw across all 12 monthly entries divided by 12. "
            "Leave null if no monthly demand values are available; compute downstream."
        ),
    )

    def compute_annual_totals(self) -> "EnergyConsumptionBillsCollection":
        """Compute annual energy consumption and average demand from monthly entries."""
        if not self.monthly_consumption:
            return self

        # Sum annual consumption across all monthly entries
        total_consumption = sum(
            m.energy_consumption_kwh
            for m in self.monthly_consumption
            if m.energy_consumption_kwh is not None
        )
        self.annual_energy_consumption_kwh = (
            round(total_consumption, 2) if total_consumption else None
        )

        # Annual average demand: sum of monthly average_demand_kw / 12
        demand_values = [
            m.average_demand_kw for m in self.monthly_consumption if m.average_demand_kw is not None
        ]
        if demand_values:
            self.annual_average_demand_kw = round(sum(demand_values) / 12, 4)

        return self


# =============================================================================
# Company Financials Extraction Schemas (Section 1.2 - 1.5)
# =============================================================================


class EconomicalOfferBOQData(BaseModel):
    """
    Schema for Economical Offer / BOQ (Section 1.6).

    Economic offer or Bill of Quantities document containing project
    pricing, CAPEX breakdown, and equipment specifications for solar installations.
    Output structure: Project Economical Offer (Single values)
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Capacity Information (Extracted)
    # -------------------------------------------------------------------------
    total_dc_capacity_kwp: Optional[float] = Field(
        default=None,
        description="Total DC capacity in kWp or MWp (convert to kWp if in MWp)",
    )
    total_ac_capacity_kw: Optional[float] = Field(
        default=None,
        description="Total AC capacity in kW or MW (convert to kW if in MW)",
    )

    # -------------------------------------------------------------------------
    # Computed Ratio
    # -------------------------------------------------------------------------
    dc_ac_ratio: Optional[float] = Field(
        default=None,
        description="DC/AC Ratio - Computed as Total DC Capacity / Total AC Capacity",
    )

    # -------------------------------------------------------------------------
    # Equipment Quantities (Extracted)
    # -------------------------------------------------------------------------
    number_of_solar_modules: Optional[int] = Field(
        default=None,
        description="Total number of solar modules/panels in the system",
    )
    solar_module_capacity_wdc: Optional[float] = Field(
        default=None,
        description="Individual solar module capacity in Wdc",
    )
    number_of_inverters: Optional[int] = Field(
        default=None,
        description="Total number of inverters in the system",
    )
    inverter_capacity_kw: Optional[float] = Field(
        default=None,
        description="Individual inverter capacity in kW",
    )

    # -------------------------------------------------------------------------
    # Cost Information (Extracted)
    # -------------------------------------------------------------------------
    total_capex_excl_vat_usd: Optional[float] = Field(
        default=None,
        description="Total CAPEX excluding VAT in USD",
    )
    vat_cost_usd: Optional[float] = Field(
        default=None,
        description="VAT cost in USD",
    )
    total_capex_incl_vat_usd: Optional[float] = Field(
        default=None,
        description="Total CAPEX including VAT in USD",
    )

    # -------------------------------------------------------------------------
    # Derived KPI (Computed)
    # -------------------------------------------------------------------------
    capex_per_wp_usd: Optional[float] = Field(
        default=None,
        description="CAPEX per Wp in USD/Wp - Computed as Total CAPEX incl. VAT / (Total DC Capacity in W)",
    )

    # -------------------------------------------------------------------------
    # Document Metadata
    # -------------------------------------------------------------------------
    project_name: Optional[str] = Field(
        default=None,
        description="Project name as stated in the offer",
    )
    offer_date: Optional[str] = Field(
        default=None,
        description="Date of the economic offer (YYYY-MM-DD)",
    )
    offer_validity_days: Optional[int] = Field(
        default=None,
        description="Validity period of the offer in days",
    )
    currency: Optional[str] = Field(
        default=None,
        description="Currency used in the offer (default: USD)",
    )
    vendor_name: Optional[str] = Field(
        default=None,
        description="Name of the vendor/contractor providing the offer",
    )

    def compute_derived_fields(self) -> "EconomicalOfferBOQData":
        """Compute DC/AC ratio and CAPEX per Wp from extracted values."""
        # Compute DC/AC Ratio
        if self.total_dc_capacity_kwp and self.total_ac_capacity_kw:
            if self.total_ac_capacity_kw != 0:
                self.dc_ac_ratio = round(self.total_dc_capacity_kwp / self.total_ac_capacity_kw, 3)

        # Compute CAPEX per Wp
        if self.total_capex_incl_vat_usd and self.total_dc_capacity_kwp:
            # Convert kWp to Wp (multiply by 1000)
            total_dc_capacity_wp = self.total_dc_capacity_kwp * 1000
            if total_dc_capacity_wp != 0:
                self.capex_per_wp_usd = round(
                    self.total_capex_incl_vat_usd / total_dc_capacity_wp, 3
                )

        return self


class YearlyFinancialData(BaseModel):
    """
    Financial data for a single fiscal year.

    Contains both extracted values from financial statements and computed ratios.
    All monetary values should be in the same currency (typically USD or local currency).
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Identification
    # -------------------------------------------------------------------------
    year: int = Field(description="Fiscal year (e.g., 2023, 2022, 2021)")

    # -------------------------------------------------------------------------
    # Extracted Values - Balance Sheet (Assets)
    # -------------------------------------------------------------------------
    current_assets: float = Field(
        description="Total current assets for the fiscal year (cash, receivables, inventory, etc.)"
    )
    inventory: float = Field(description="Total inventory value for the fiscal year")
    total_assets: float = Field(
        description="Total assets (current + non-current) for the fiscal year"
    )

    # -------------------------------------------------------------------------
    # Extracted Values - Balance Sheet (Liabilities & Equity)
    # -------------------------------------------------------------------------
    current_liabilities: float = Field(
        description="Total current liabilities for the fiscal year (payables, short-term debt, etc.)"
    )
    total_liabilities: float = Field(
        description="Total liabilities (current + non-current) for the fiscal year"
    )
    equity: float = Field(description="Total shareholders' equity for the fiscal year")

    # -------------------------------------------------------------------------
    # Extracted Values - Income Statement
    # -------------------------------------------------------------------------
    revenue: float = Field(
        description="Total revenue/sales (ordinary activities) for the fiscal year"
    )
    net_income: float = Field(
        description="Net income/profit after all expenses and taxes for the fiscal year"
    )
    ebit: float = Field(
        description="Earnings Before Interest and Taxes (EBIT) / Operating Income for the fiscal year"
    )
    interest_expenses: float = Field(description="Total interest expenses for the fiscal year")

    # -------------------------------------------------------------------------
    # Computed Ratios - Liquidity
    # -------------------------------------------------------------------------
    current_ratio: Optional[float] = Field(
        default=None, description="Liquidity ratio: Current Assets / Current Liabilities"
    )
    quick_ratio: Optional[float] = Field(
        default=None,
        description="Liquidity ratio: (Current Assets - Inventory) / Current Liabilities",
    )

    # -------------------------------------------------------------------------
    # Computed Ratios - Leverage/Solvency
    # -------------------------------------------------------------------------
    leverage_ratio: Optional[float] = Field(
        default=None, description="Solvency ratio: Total Liabilities / Equity"
    )
    interest_coverage_ratio: Optional[float] = Field(
        default=None, description="Ability to meet interest obligations: EBIT / Interest Expenses"
    )

    # -------------------------------------------------------------------------
    # Computed Ratios - Profitability
    # -------------------------------------------------------------------------
    operating_margin: Optional[float] = Field(
        default=None,
        description="Profitability ratio: EBIT / Revenue (as decimal, e.g., 0.15 for 15%)",
    )
    return_on_assets_roa: Optional[float] = Field(
        default=None, description="Return on Assets: Net Income / Total Assets (as decimal)"
    )
    return_on_equity_roe: Optional[float] = Field(
        default=None, description="Return on Equity: Net Income / Equity (as decimal)"
    )

    def compute_ratios(self) -> "YearlyFinancialData":
        """Compute all financial ratios from extracted values."""
        # Liquidity ratios
        if self.current_liabilities and self.current_liabilities != 0:
            self.current_ratio = round(self.current_assets / self.current_liabilities, 4)
            self.quick_ratio = round(
                (self.current_assets - self.inventory) / self.current_liabilities, 4
            )

        # Leverage ratios
        if self.equity and self.equity != 0:
            self.leverage_ratio = round(self.total_liabilities / self.equity, 4)

        if self.interest_expenses and self.interest_expenses != 0:
            self.interest_coverage_ratio = round(self.ebit / self.interest_expenses, 4)

        # Profitability ratios
        if self.revenue and self.revenue != 0:
            self.operating_margin = round(self.ebit / self.revenue, 4)

        if self.total_assets and self.total_assets != 0:
            self.return_on_assets_roa = round(self.net_income / self.total_assets, 4)

        if self.equity and self.equity != 0:
            self.return_on_equity_roe = round(self.net_income / self.equity, 4)

        return self


def _coerce_year(value: Any) -> Optional[int]:
    """Convert extracted year-like values to integers when possible."""
    if isinstance(value, bool):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_financial_ratio_year(entry: Any) -> Optional[int]:
    """Read a year value from a financial ratio entry."""
    if isinstance(entry, BaseModel):
        return _coerce_year(getattr(entry, "year", None))

    if isinstance(entry, dict):
        return _coerce_year(entry.get("year"))

    return None


def _select_financial_statement_year_rows(
    financial_ratios: List[Any], fiscal_year: Optional[int]
) -> Tuple[List[int], Optional[int]]:
    """Pick the row indexes that belong to the document fiscal year."""
    if not financial_ratios:
        return [], _coerce_year(fiscal_year)

    target_year = _coerce_year(fiscal_year)
    if target_year is None:
        available_years = [
            year
            for year in (_get_financial_ratio_year(entry) for entry in financial_ratios)
            if year is not None
        ]
        if available_years:
            target_year = max(available_years)

    if target_year is None:
        return list(range(len(financial_ratios))), None

    selected_indexes = [
        index
        for index, entry in enumerate(financial_ratios)
        if _get_financial_ratio_year(entry) == target_year
    ]
    if not selected_indexes:
        return list(range(len(financial_ratios))), target_year

    return selected_indexes, target_year


class FinancialStatementsData(BaseModel):
    """
    Schema for Financial Statements (Section 1.2).

    Extracts only the financial data for the document's fiscal year from audited
    or internal financial statements. Comparative prior-year figures may appear
    in the source document, but they must not be returned as separate entries.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------------
    # company_name: Optional[str] = Field(
    #     default=None, description="Company name as stated in the financial statements"
    # )
    # currency: Optional[str] = Field(
    #     default=None,
    #     description="Currency used in the statements (e.g., USD, EUR, or local currency code)",
    # )
    # is_audited: Optional[bool] = Field(
    #     default=None,
    #     description="Whether the financial statements are audited (True) or internal/unaudited (False)",
    # )
    # auditor_name: Optional[str] = Field(
    #     default=None, description="Name of the auditing firm (if audited)"
    # )

    fiscal_year: Optional[int] = Field(
        default=None,
        description=(
            "Fiscal year of the document being extracted (for example, 2021 for a "
            "2021 statement that also shows 2020 comparatives)."
        ),
    )

    # -------------------------------------------------------------------------
    # Yearly Financial Data
    # -------------------------------------------------------------------------
    financial_ratios: List[YearlyFinancialData] = Field(
        description=(
            "Only the financial data for fiscal_year. Exclude comparative prior-year "
            "rows or columns such as year-1."
        )
    )

    @model_validator(mode="after")
    def normalize_to_document_fiscal_year(self) -> "FinancialStatementsData":
        """Keep only the row that belongs to the current document fiscal year."""
        selected_indexes, target_year = _select_financial_statement_year_rows(
            self.financial_ratios,
            self.fiscal_year,
        )

        if target_year is not None:
            self.fiscal_year = target_year

        if selected_indexes and len(selected_indexes) != len(self.financial_ratios):
            self.financial_ratios = [self.financial_ratios[index] for index in selected_indexes]

        return self.compute_all_ratios()

    def compute_all_ratios(self) -> "FinancialStatementsData":
        """Compute ratios for all years."""
        for year_data in self.financial_ratios:
            year_data.compute_ratios()
        return self


def normalize_financial_statements_extraction(
    extracted: Dict[str, Any],
    extraction_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Normalize extracted financial statements data to the document fiscal year."""
    financial_ratios = extracted.get("financial_ratios")
    if not isinstance(financial_ratios, list):
        return extracted, extraction_metadata

    selected_indexes, target_year = _select_financial_statement_year_rows(
        financial_ratios,
        extracted.get("fiscal_year"),
    )

    normalized_extracted = dict(extracted)
    if target_year is not None:
        normalized_extracted["fiscal_year"] = target_year

    if selected_indexes and len(selected_indexes) != len(financial_ratios):
        normalized_extracted["financial_ratios"] = [
            financial_ratios[index] for index in selected_indexes
        ]

    normalized_metadata = extraction_metadata
    if isinstance(extraction_metadata, dict):
        normalized_metadata = dict(extraction_metadata)
        metadata_rows = extraction_metadata.get("financial_ratios")
        if isinstance(metadata_rows, list):
            normalized_metadata["financial_ratios"] = [
                metadata_rows[index] for index in selected_indexes if index < len(metadata_rows)
            ]

    return normalized_extracted, normalized_metadata


def _get_annual_filing_year(entry: Any) -> Optional[int]:
    """Read a year value from an annual tax filing entry."""
    if isinstance(entry, BaseModel):
        return _coerce_year(getattr(entry, "fiscal_year", None))
    if isinstance(entry, dict):
        return _coerce_year(entry.get("fiscal_year"))
    return None


def _select_income_tax_filing_rows(
    annual_filings: List[Any], fiscal_year: Optional[int]
) -> Tuple[List[int], Optional[int]]:
    """Pick the row indexes that belong to the document fiscal year."""
    if not annual_filings:
        return [], _coerce_year(fiscal_year)

    target_year = _coerce_year(fiscal_year)
    if target_year is None:
        available_years = [
            year
            for year in (_get_annual_filing_year(entry) for entry in annual_filings)
            if year is not None
        ]
        if available_years:
            target_year = max(available_years)

    if target_year is None:
        return list(range(len(annual_filings))), None

    selected_indexes = [
        index
        for index, entry in enumerate(annual_filings)
        if _get_annual_filing_year(entry) == target_year
    ]
    if not selected_indexes:
        return list(range(len(annual_filings))), target_year

    # Keep at most one entry for the target year
    return selected_indexes[:1], target_year


def normalize_income_tax_filings_extraction(
    extracted: Dict[str, Any],
    extraction_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Normalize extracted income tax filings data to the document fiscal year."""
    annual_filings = extracted.get("annual_filings")
    if not isinstance(annual_filings, list):
        return extracted, extraction_metadata

    selected_indexes, target_year = _select_income_tax_filing_rows(
        annual_filings,
        extracted.get("fiscal_year"),
    )

    normalized_extracted = dict(extracted)
    if target_year is not None:
        normalized_extracted["fiscal_year"] = target_year

    if selected_indexes and len(selected_indexes) != len(annual_filings):
        normalized_extracted["annual_filings"] = [
            annual_filings[index] for index in selected_indexes
        ]

    normalized_metadata = extraction_metadata
    if isinstance(extraction_metadata, dict):
        normalized_metadata = dict(extraction_metadata)
        metadata_rows = extraction_metadata.get("annual_filings")
        if isinstance(metadata_rows, list):
            normalized_metadata["annual_filings"] = [
                metadata_rows[index] for index in selected_indexes if index < len(metadata_rows)
            ]

    return normalized_extracted, normalized_metadata


def _select_cash_flow_year_rows(
    annual_cash_flows: List[Any], fiscal_year: Optional[int]
) -> Tuple[List[int], Optional[int]]:
    """Pick the row indexes that belong to the document fiscal year."""
    if not annual_cash_flows:
        return [], _coerce_year(fiscal_year)

    target_year = _coerce_year(fiscal_year)
    if target_year is None:
        available_years = [
            year
            for year in (_get_annual_filing_year(entry) for entry in annual_cash_flows)
            if year is not None
        ]
        if available_years:
            target_year = max(available_years)

    if target_year is None:
        return list(range(len(annual_cash_flows))), None

    selected_indexes = [
        index
        for index, entry in enumerate(annual_cash_flows)
        if _get_annual_filing_year(entry) == target_year
    ]
    if not selected_indexes:
        return list(range(len(annual_cash_flows))), target_year

    # Keep at most one entry for the target year
    return selected_indexes[:1], target_year


def normalize_cash_flow_statements_extraction(
    extracted: Dict[str, Any],
    extraction_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Normalize extracted cash flow statements data to the document fiscal year."""
    annual_cash_flows = extracted.get("annual_cash_flows")
    if not isinstance(annual_cash_flows, list):
        return extracted, extraction_metadata

    selected_indexes, target_year = _select_cash_flow_year_rows(
        annual_cash_flows,
        extracted.get("fiscal_year"),
    )

    normalized_extracted = dict(extracted)
    if target_year is not None:
        normalized_extracted["fiscal_year"] = target_year

    if selected_indexes and len(selected_indexes) != len(annual_cash_flows):
        normalized_extracted["annual_cash_flows"] = [
            annual_cash_flows[index] for index in selected_indexes
        ]

    normalized_metadata = extraction_metadata
    if isinstance(extraction_metadata, dict):
        normalized_metadata = dict(extraction_metadata)
        metadata_rows = extraction_metadata.get("annual_cash_flows")
        if isinstance(metadata_rows, list):
            normalized_metadata["annual_cash_flows"] = [
                metadata_rows[index] for index in selected_indexes if index < len(metadata_rows)
            ]

    return normalized_extracted, normalized_metadata


_COORD_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _parse_coordinate_component(value: str, negative_directions: set) -> Optional[float]:
    """Parse a single lat or lon component from various notations."""
    cleaned = value.upper().replace("(", " ").replace(")", " ")
    direction = next(
        (d for d in ("N", "S", "E", "W") if d in cleaned),
        None,
    )
    numbers = [abs(float(m)) for m in _COORD_NUMBER_RE.findall(cleaned)]
    if not numbers:
        return None
    decimal = numbers[0]
    if len(numbers) > 1:
        decimal += numbers[1] / 60.0
    if len(numbers) > 2:
        decimal += numbers[2] / 3600.0
    if direction is not None:
        sign = -1.0 if direction in negative_directions else 1.0
    else:
        sign = -1.0 if cleaned.lstrip().startswith("-") else 1.0
    return sign * decimal


def _build_google_maps_link(raw_coordinates: Optional[str]) -> Optional[str]:
    """Build a Google Maps URL from extracted geographical coordinates."""
    if not raw_coordinates:
        return None
    parts = [p.strip() for p in raw_coordinates.split(",", 1)]
    if len(parts) == 2:
        lat = _parse_coordinate_component(parts[0], {"S"})
        lng = _parse_coordinate_component(parts[1], {"W"})
        if lat is not None and lng is not None:
            return f"https://www.google.com/maps?q={lat:.8f},{lng:.8f}"
    return f"https://www.google.com/maps/search/?api=1&query={quote(raw_coordinates)}"


def _decode_html_entities(value: Any) -> Any:
    """Recursively decode HTML entities in string values within dicts and lists."""
    if isinstance(value, str):
        return html.unescape(value)
    if isinstance(value, dict):
        return {k: _decode_html_entities(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_html_entities(item) for item in value]
    return value


def normalize_extracted_document(
    document_type: DocumentType | str,
    extracted: Dict[str, Any],
    extraction_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Apply document-type-specific normalization to extracted payloads."""
    doc_type_value = (
        document_type.value if isinstance(document_type, DocumentType) else document_type
    )

    # Decode HTML entities (e.g. &Oacute; → Ó) that OCR may produce
    extracted = _decode_html_entities(extracted)
    if isinstance(extraction_metadata, dict):
        extraction_metadata = _decode_html_entities(extraction_metadata)

    print(f"Normalizing extracted data for document type: {doc_type_value}")
    print(f"Initial extracted data keys: {extraction_metadata}")

    if doc_type_value == DocumentType.FINANCIAL_STATEMENTS.value:
        return normalize_financial_statements_extraction(extracted, extraction_metadata)

    if doc_type_value == DocumentType.INCOME_TAX_FILINGS.value:
        return normalize_income_tax_filings_extraction(extracted, extraction_metadata)

    if doc_type_value == DocumentType.CASH_FLOW_STATEMENTS.value:
        return normalize_cash_flow_statements_extraction(extracted, extraction_metadata)

    if doc_type_value == DocumentType.PROJECT_SIMULATION_REPORT.value:
        normalized = dict(extracted)
        normalized["google_maps_link"] = _build_google_maps_link(
            normalized.get("geographical_coordinates")
        )
        return normalized, extraction_metadata

    if doc_type_value == DocumentType.CNEL_ENERGY_BILL.value:
        # Capture-and-reduce: derive BillFacts from the verbatim detail_rows
        # (per-tariff reducer, invariants, grounding provenance — fails closed).
        return normalize_cnel_energy_bill(extracted, extraction_metadata)

    return extracted, extraction_metadata


class AnnualTaxFiling(BaseModel):
    """Tax filing data for a single fiscal year."""

    model_config = ConfigDict(extra="forbid")

    fiscal_year: int = Field(description="Fiscal year for the tax filing (e.g., 2023)")
    income_tax_paid: float = Field(description="Income tax paid for the year in local currency")
    filing_date: Optional[str] = Field(
        default=None, description="Date the tax filing was submitted (YYYY-MM-DD)"
    )


class IncomeTaxFilingsData(BaseModel):
    """
    Schema for Income Tax Filings (Section 1.3).

    Extracts tax payment information from a single SRI/Tax Authority filing.
    Each document covers exactly one fiscal year.
    """

    model_config = ConfigDict(extra="forbid")

    company_name: Optional[str] = Field(
        default=None, description="Company name as stated in the tax filings"
    )
    tax_id_ruc: Optional[str] = Field(default=None, description="Tax ID (RUC) number")
    # tax_authority: Optional[str] = Field(
    #     default=None, description="Tax authority name (e.g., SRI for Ecuador)"
    # )
    fiscal_year: Optional[int] = Field(
        default=None,
        description=(
            "Fiscal year of the document being extracted (e.g., 2021). "
            "Each document covers a single year."
        ),
    )
    annual_filings: List[AnnualTaxFiling] = Field(
        description=(
            "Tax filing data for the document's fiscal year only. "
            "Return exactly one entry matching the document year. "
            "Do not include prior-year or comparative data."
        )
    )

    @model_validator(mode="after")
    def normalize_to_document_fiscal_year(self) -> "IncomeTaxFilingsData":
        """Keep only the filing entry that belongs to the document's fiscal year."""
        if not self.annual_filings:
            return self

        target_year = _coerce_year(self.fiscal_year)

        if target_year is None:
            available_years = [
                _coerce_year(entry.fiscal_year)
                for entry in self.annual_filings
                if _coerce_year(entry.fiscal_year) is not None
            ]
            if available_years:
                target_year = max(available_years)

        if target_year is not None:
            self.fiscal_year = target_year
            matched = [
                entry
                for entry in self.annual_filings
                if _coerce_year(entry.fiscal_year) == target_year
            ]
            if matched:
                self.annual_filings = matched[:1]

        return self


class AnnualCashFlow(BaseModel):
    """Cash flow data for a single fiscal year."""

    model_config = ConfigDict(extra="forbid")

    fiscal_year: int = Field(description="Fiscal year for the cash flow statement")
    operating_cash_flow: Optional[float] = Field(
        default=None, description="Net cash from operating activities"
    )


class CashFlowStatementsData(BaseModel):
    """
    Schema for Cash Flow Statements (Section 1.4).

    Extracts cash flow data for the document's fiscal year only.
    Each document covers exactly one fiscal year.
    """

    model_config = ConfigDict(extra="forbid")

    company_name: Optional[str] = Field(
        default=None, description="Company name as stated in the cash flow statements"
    )
    currency: Optional[str] = Field(default=None, description="Currency used (e.g., USD, EUR)")
    fiscal_year: Optional[int] = Field(
        default=None,
        description=(
            "Fiscal year of the document being extracted (e.g., 2021). "
            "Each document covers a single year."
        ),
    )
    annual_cash_flows: List[AnnualCashFlow] = Field(
        description=(
            "Cash flow data for the document's fiscal year only. "
            "Return exactly one entry matching the document year. "
            "Do not include prior-year or comparative data."
        )
    )

    @model_validator(mode="after")
    def normalize_to_document_fiscal_year(self) -> "CashFlowStatementsData":
        """Keep only the cash flow entry that belongs to the document's fiscal year."""
        if not self.annual_cash_flows:
            return self

        target_year = _coerce_year(self.fiscal_year)

        if target_year is None:
            available_years = [
                _coerce_year(entry.fiscal_year)
                for entry in self.annual_cash_flows
                if _coerce_year(entry.fiscal_year) is not None
            ]
            if available_years:
                target_year = max(available_years)

        if target_year is not None:
            self.fiscal_year = target_year
            matched = [
                entry
                for entry in self.annual_cash_flows
                if _coerce_year(entry.fiscal_year) == target_year
            ]
            if matched:
                self.annual_cash_flows = matched[:1]

        return self


class TaxComplianceCertificateData(BaseModel):
    """
    Schema for Tax Compliance Certificate (Section 1.5).

    Certificate from tax authority confirming compliance status.
    """

    model_config = ConfigDict(extra="forbid")

    tax_id_ruc: str = Field(
        description="Tax ID (RUC) number - should be verified to match company RUC"
    )
    company_name: Optional[str] = Field(
        default=None, description="Company name as stated in the certificate"
    )
    issuance_date: str = Field(
        description="Date the certificate was issued (YYYY-MM-DD) - should correspond to current period"
    )
    tax_compliance_status: str = Field(
        description="Compliance status text (e.g., 'Compliant', 'No outstanding debts', 'Al día en obligaciones')"
    )
    has_outstanding_debts: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether there are outstanding tax debts. "
            "For a compliant status, the expected answer is No. " + YES_NO_RESPONSE_INSTRUCTION
        ),
    )
    validity_period: Optional[str] = Field(
        default=None, description="Period the certificate is valid for (if specified)"
    )


# =============================================================================
# Company Experience Extraction Schemas (Section 4.1 - 4.2)
# =============================================================================


class ProjectAcceptanceCertificateEntry(BaseModel):
    """
    Individual project acceptance certificate entry.

    Represents a single completed project with its acceptance/completion certificate.
    One row per project in the output table.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Project Identification
    # -------------------------------------------------------------------------
    project_title: str = Field(description="Title or name of the completed project")

    # -------------------------------------------------------------------------
    # Certificate Information
    # -------------------------------------------------------------------------
    certificate_type: Optional[str] = Field(
        default=None,
        description="Type of certificate: 'Provisional' or 'Final' acceptance",
    )
    client_name: Optional[str] = Field(
        default=None,
        description="Name of the client who issued the certificate",
    )
    certificate_date: Optional[str] = Field(
        default=None,
        description="Date of the certificate (YYYY-MM-DD)",
    )

    # -------------------------------------------------------------------------
    # Project Details
    # -------------------------------------------------------------------------
    scope_of_work: Optional[str] = Field(
        default=None,
        description="Description of the scope of work completed (e.g., 'Design, supply, and installation of 500kWp solar PV system')",
    )
    project_capacity_kw: Optional[float] = Field(
        default=None,
        description="Project capacity in kW (extracted from scope or separately stated)",
    )
    project_location: Optional[str] = Field(
        default=None,
        description="Location of the project (city, country)",
    )

    # -------------------------------------------------------------------------
    # Signature Confirmation
    # -------------------------------------------------------------------------
    signed_by_client: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether the certificate is signed by the client. "
        + YES_NO_RESPONSE_INSTRUCTION,
    )
    signatory_name: Optional[str] = Field(
        default=None,
        description="Name of the person who signed on behalf of the client",
    )
    signatory_title: Optional[str] = Field(
        default=None,
        description="Title/position of the signatory",
    )


class ProjectAcceptanceCertificatesData(BaseModel):
    """
    Schema for Project Acceptance Certificates (Section 4.1).

    Collection of project acceptance/completion certificates demonstrating
    the company's experience in solar/renewable energy projects.
    Output structure: Experience (Table with one row per project)
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Company Information
    # -------------------------------------------------------------------------
    company_name: Optional[str] = Field(
        default=None,
        description="Name of the company whose experience is being documented",
    )

    # -------------------------------------------------------------------------
    # Project Certificates (Table - one row per project)
    # -------------------------------------------------------------------------
    certificates: List[ProjectAcceptanceCertificateEntry] = Field(
        description="List of project acceptance certificates (one entry per project)"
    )


class OAMContractData(BaseModel):
    """
    Schema for O&M Contracts (Section 4.2).

    Operations and Maintenance contract information demonstrating
    the company's O&M capabilities and approach.
    Output structure: O&M (Single value)
    """

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    # -------------------------------------------------------------------------
    # Maintenance Approach
    # -------------------------------------------------------------------------
    planned_maintenance_approach: Optional[str] = Field(
        default=None,
        description=(
            "Description of the planned maintenance approach including frequency, scope, and methodology. "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    # -------------------------------------------------------------------------
    # Contract Details (Additional context)
    # -------------------------------------------------------------------------
    contract_reference: Optional[str] = Field(
        default=None,
        description="Contract reference number or ID",
    )
    client_name: Optional[str] = Field(
        default=None,
        description="Name of the client for the O&M contract",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Name of the project covered by the O&M contract",
    )
    contract_start_date: Optional[str] = Field(
        default=None,
        description="Contract start date (YYYY-MM-DD)",
    )
    contract_end_date: Optional[str] = Field(
        default=None,
        description="Contract end date (YYYY-MM-DD)",
    )
    contract_duration_years: Optional[int] = Field(
        default=None,
        description="Duration of the O&M contract in years",
    )

    # -------------------------------------------------------------------------
    # Maintenance Scope Details
    # -------------------------------------------------------------------------
    preventive_maintenance_frequency: Optional[str] = Field(
        default=None,
        description="Frequency of preventive maintenance visits (e.g., 'Monthly', 'Quarterly', 'Bi-annual')",
    )
    corrective_maintenance_response_time: Optional[str] = Field(
        default=None,
        description="Response time for corrective maintenance (e.g., '24 hours', '48 hours')",
    )
    performance_guarantee: Optional[str] = Field(
        default=None,
        description="Performance guarantee or availability commitment (e.g., '98% availability')",
    )
    services_included: Optional[List[str]] = Field(
        default=None,
        description="List of services included in the O&M contract",
    )

    # -------------------------------------------------------------------------
    # Project Specifications
    # -------------------------------------------------------------------------
    system_capacity_kw: Optional[float] = Field(
        default=None,
        description="Capacity of the system under O&M contract in kW",
    )
    system_type: Optional[str] = Field(
        default=None,
        description="Type of system (e.g., 'Ground-mounted PV', 'Rooftop PV', 'Carport')",
    )


# =============================================================================
# ESG Extraction Schemas (Section 3.1 - 3.3)
# =============================================================================


class ESHSESMSPoliciesData(BaseModel):
    """
    Schema for Environmental  and Social Management Plan (EMP) (Section 3.1).

    Environmental, Social, Health and Safety management policies
    aligned with IFC Performance Standards.
    """

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    # -------------------------------------------------------------------------
    # ESMS Aligned with IFC Performance Standards
    # -------------------------------------------------------------------------
    esms_aligned_with_ifc_performance_standards: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether the ESMS aligns with IFC Performance Standards. " + YES_NO_RESPONSE_INSTRUCTION
        ),
    )

    # -------------------------------------------------------------------------
    # OHS Procedures Summary
    # -------------------------------------------------------------------------
    ohs_procedures_summary: Optional[str] = Field(
        default=None,
        description=(
            "Summary of Occupational Health and Safety procedures (max 2-3 lines). "
            "Key safety protocols and procedures. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    # -------------------------------------------------------------------------
    # Hazardous Materials Handling
    # -------------------------------------------------------------------------
    hazardous_materials_handling: Optional[str] = Field(
        default=None,
        description=(
            "Summary of hazardous materials handling procedures (max 4 lines). "
            "How hazardous materials are managed and disposed. "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    # -------------------------------------------------------------------------
    # Labor Procedures & Workers Rights
    # -------------------------------------------------------------------------
    labor_procedures_workers_rights: Optional[str] = Field(
        default=None,
        description=(
            "Summary of labor procedures and workers rights policies (max 4 lines). "
            "Worker protections and labor compliance. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    # -------------------------------------------------------------------------
    # Waste Management Monitoring
    # -------------------------------------------------------------------------
    waste_management_monitoring: Optional[str] = Field(
        default=None,
        description=(
            "Summary of waste management and monitoring procedures (max 4 lines). "
            "Waste disposal and recycling practices. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    # -------------------------------------------------------------------------
    # Resource Use Controls
    # -------------------------------------------------------------------------
    resource_use_controls: Optional[str] = Field(
        default=None,
        description=(
            "Summary of resource use controls (max 4 lines). "
            "Energy efficiency, water usage, and resource conservation measures. "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    # -------------------------------------------------------------------------
    # Document Metadata
    # -------------------------------------------------------------------------
    valid_from: Optional[str] = Field(default=None, description="Validity start date (YYYY-MM-DD)")
    valid_to: Optional[str] = Field(default=None, description="Validity end date (YYYY-MM-DD)")
    scope_of_application: Optional[str] = Field(
        default=None,
        description="Scope of application/facilities covered",
    )
    environmental_aspects_covered: Optional[List[str]] = Field(
        default=None,
        description="Environmental aspects covered (emissions, waste, water, biodiversity)",
    )
    social_aspects_covered: Optional[List[str]] = Field(
        default=None,
        description="Social aspects covered (communities, workers)",
    )
    monitoring_indicators: Optional[List[str]] = Field(
        default=None,
        description=(
            "Monitoring indicators as a flat list of strings. "
            "Each string must combine the indicator name, unit, and frequency in the format: "
            "'<indicator> | <unit> | <frequency>'. "
            "If unit is not available, use 'N/A' in its place. "
            "Example: 'Nivel visible de polvo reducido | N/A | Diario'."
        ),
    )
    biodiversity_management_measures: Optional[str] = Field(
        default=None,
        description="Biodiversity management measures. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    community_impacts_management_measures: Optional[str] = Field(
        default=None,
        description="Community impacts management measures. "
        + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    climate_adaptation_measures: Optional[str] = Field(
        default=None,
        description="Climate adaptation measures. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )


class ElectricalTestEntry(BaseModel):
    """Individual electrical test result entry."""

    model_config = ConfigDict(extra="forbid")

    test_name: str = Field(
        description="Name of the electrical test (e.g., 'Insulation Resistance Test', 'Ground Continuity Test')"
    )
    test_result: Optional[str] = Field(
        default=None,
        description="Result of the test (Pass/Fail or measured value)",
    )
    measured_value: Optional[str] = Field(
        default=None,
        description="Measured value with units (e.g., '> 1 MΩ', '0.5 Ω')",
    )
    acceptance_criteria: Optional[str] = Field(
        default=None,
        description="Acceptance criteria for the test",
    )


class PerformanceMetricEntry(BaseModel):
    """Individual performance metric entry."""

    model_config = ConfigDict(extra="forbid")

    metric_name: str = Field(
        description="Name of the performance metric (e.g., 'System Efficiency', 'Energy Yield')"
    )
    measured_value: Optional[str] = Field(
        default=None,
        description="Measured value with units",
    )
    expected_value: Optional[str] = Field(
        default=None,
        description="Expected or target value",
    )
    variance: Optional[str] = Field(
        default=None,
        description="Variance from expected value (if applicable)",
    )


class QAQCCommissioningData(BaseModel):
    """
    Schema for QA/QC & Commissioning Procedures (Section 3.2).

    Quality assurance, quality control, and commissioning documentation.
    """

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    # -------------------------------------------------------------------------
    # Visual Inspection Summary
    # -------------------------------------------------------------------------
    visual_inspection_summary: Optional[str] = Field(
        default=None,
        description=(
            "Summary of visual inspection findings. Overall condition assessment (max 2-3 lines). "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )
    visual_inspection_passed: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether visual inspection passed. " + YES_NO_RESPONSE_INSTRUCTION,
    )

    # -------------------------------------------------------------------------
    # Electrical Test Results (Table)
    # -------------------------------------------------------------------------
    electrical_test_results: Optional[List[ElectricalTestEntry]] = Field(
        default=None,
        description="List of electrical test results from commissioning",
    )

    # -------------------------------------------------------------------------
    # Performance Metrics (Table)
    # -------------------------------------------------------------------------
    performance_metrics: Optional[List[PerformanceMetricEntry]] = Field(
        default=None,
        description="List of performance metrics measured during commissioning",
    )

    # -------------------------------------------------------------------------
    # Document Metadata
    # -------------------------------------------------------------------------
    commissioning_date: Optional[str] = Field(
        default=None,
        description="Date of commissioning (YYYY-MM-DD if available)",
    )
    inspector_name: Optional[str] = Field(
        default=None,
        description="Name of the inspector or commissioning engineer",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Project name as stated in the document",
    )


class IndustrialSafetyPlanData(BaseModel):
    """
    Schema for Industrial Safety Plan (Section 3.3).

    Extract only the IFC-aligned HR practices summary required by the stakeholder mapping.
    """

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    # -------------------------------------------------------------------------
    # Industrial Safety Plan Summary
    # -------------------------------------------------------------------------
    ifc_aligned_hr_practices_summary: Optional[str] = Field(
        default=None,
        description=(
            "Summary of IFC-aligned HR practices described in the Industrial Safety Plan (max 2-3 lines). "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )


class EnvironmentalLicenceEIAData(BaseModel):
    """Schema for Environmental Licence / EIA (Section 2.4)."""

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    issuing_authority: Optional[str] = Field(
        default=None,
        description=(
            "Issuing authority. Extract exactly as written in the document. "
            "Preserve the original document language."
        ),
    )
    license_number: Optional[str] = Field(
        default=None,
        description=("License number. Extract exactly as written in the document."),
    )
    issuing_date: Optional[str] = Field(
        default=None,
        description=("Issuing date in YYYY-MM-DD format."),
    )
    expiry_date: Optional[str] = Field(
        default=None,
        description=("Expiry date in YYYY-MM-DD format."),
    )

    sensitive_habitats_present: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether sensitive habitats are present. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    sensitive_habitats_description: Optional[str] = Field(
        default=None,
        description=(
            "Sensitive habitats description in 2-4 lines. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    biodiversity_impacts_identified: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether biodiversity impacts are identified. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    biodiversity_impacts_summary: Optional[str] = Field(
        default=None,
        description=(
            "Biodiversity impacts summary in 2-3 lines. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    ecosystem_services_impacted: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether ecosystem services are impacted. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    ecosystem_services_description: Optional[str] = Field(
        default=None,
        description=(
            "Ecosystem services description in 2-4 lines. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    mitigation_measures_summary: Optional[str] = Field(
        default=None,
        description=(
            "Mitigation measures summary in 2-3 lines. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    neighboring_populations_present: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether neighboring populations are present. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    neighboring_populations_description: Optional[str] = Field(
        default=None,
        description=(
            "Neighboring populations description in 2-4 lines. "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    critical_infrastructure_nearby: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether critical infrastructure is nearby. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    critical_infrastructure_description: Optional[str] = Field(
        default=None,
        description=(
            "Critical infrastructure description in 2-4 lines. "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    cultural_heritage_assets_present: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether cultural heritage assets are present. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    cultural_heritage_description: Optional[str] = Field(
        default=None,
        description=(
            "Cultural heritage description in 2-4 lines. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )
    cultural_heritage_protection_measures: Optional[str] = Field(
        default=None,
        description=(
            "Cultural heritage protection measures in 2-4 lines. "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )

    public_consultation_required: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether public consultation is required. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    public_consultation_summary: Optional[str] = Field(
        default=None,
        description=(
            "Public consultation summary in 2-3 lines. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )


class ESMPMonitoringIndicatorEntry(BaseModel):
    """Monitoring indicator entry in ESMP documents."""

    model_config = ConfigDict(extra="forbid")

    indicator: Optional[str] = Field(default=None, description="Monitoring indicator name")
    unit: Optional[str] = Field(default=None, description="Indicator unit")
    frequency: Optional[str] = Field(default=None, description="Monitoring frequency")


class EmergencyResponseSecurityPlanData(BaseModel):
    """Schema for Emergency Response & Security Plan (Section 2.6)."""

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    last_update_date: Optional[str] = Field(
        default=None,
        description="Last update date (YYYY-MM-DD)",
    )
    risks_covered: Optional[List[str]] = Field(
        default=None,
        description="Risks covered (e.g., flood, fire, drought)",
    )
    climate_extreme_events_covered: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether climate extreme events are covered. " + YES_NO_RESPONSE_INSTRUCTION,
    )
    climate_adaptation_actions: Optional[str] = Field(
        default=None,
        description="Climate adaptation actions. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    security_risks_covered: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether security risks are covered. " + YES_NO_RESPONSE_INSTRUCTION,
    )
    security_arrangements: Optional[str] = Field(
        default=None,
        description="Security arrangements. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    access_to_basic_resources_during_crisis: Optional[str] = Field(
        default=None,
        description="Access to basic resources during crisis. "
        + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    emergency_response_protocols: Optional[str] = Field(
        default=None,
        description="Emergency response protocols. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    coordination_with_authorities: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether there is coordination with authorities. "
        + YES_NO_RESPONSE_INSTRUCTION,
    )


class LandTitleDocumentEntry(BaseModel):
    """Land title document entry for site legal status."""

    model_config = ConfigDict(extra="forbid")

    document_type: Optional[str] = Field(default=None, description="Document type")
    document_number: Optional[str] = Field(default=None, description="Document number")
    document_date: Optional[str] = Field(default=None, description="Document date (YYYY-MM-DD)")
    document_holder: Optional[str] = Field(default=None, description="Document holder name")


class LeaseContractEntry(BaseModel):
    """Lease contract entry for site legal status."""

    model_config = ConfigDict(extra="forbid")

    lessor: Optional[str] = Field(default=None, description="Lessor name")
    term: Optional[str] = Field(default=None, description="Lease term")
    expiry: Optional[str] = Field(default=None, description="Lease expiry (YYYY-MM-DD)")


class SiteLegalStatusSummaryData(BaseModel):
    """Schema for Site Legal Status Summary (Section 2.7)."""

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    land_tenure_status: Optional[str] = Field(
        default=None,
        description="Land tenure status (owned/leased/concession). "
        + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    number_of_plots: Optional[int] = Field(default=None, description="Number of plots")
    land_title_documents_listed: List[str] = Field(
        default_factory=list,
        description=(
            "Land title documents as a flat list of strings. "
            "Each string must combine the document type, number, date, and holder in the format: "
            "'<document_type> | <document_number> | <document_date> | <document_holder>'. "
            "If a value is not available, use 'N/A' in its place. "
            "Example: 'Escritura Pública | 1234 | 2021-03-15 | Juan Pérez'. "
            "Return an empty list [] if no land title documents are found."
        ),
    )
    lease_contracts_listed: List[str] = Field(
        default_factory=list,
        description=(
            "Lease contracts as a flat list of strings. "
            "Each string must combine the lessor, term, and expiry in the format: "
            "'<lessor> | <term> | <expiry>'. "
            "If a value is not available, use 'N/A' in its place. "
            "Example: 'Municipio de Quito | 30 years | 2045-12-31'. "
            "Return an empty list [] if no lease contracts exist."
        ),
    )
    collective_rights_indigenous_claims: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether collective rights or indigenous claims exist. " + YES_NO_RESPONSE_INSTRUCTION
        ),
    )
    collective_rights_description: Optional[str] = Field(
        default=None,
        description="Collective rights description. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )
    known_property_disputes: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether known property disputes exist. " + YES_NO_RESPONSE_INSTRUCTION,
    )
    property_disputes_summary: Optional[str] = Field(
        default=None,
        description=(
            "Property disputes summary (max 2-3 lines). " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )
    expropriation_risk_identified: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether expropriation risk is identified. " + YES_NO_RESPONSE_INSTRUCTION,
    )
    expropriation_risk_description: Optional[str] = Field(
        default=None,
        description="Expropriation risk description. " + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION,
    )


class ExistingMortgageEntry(BaseModel):
    """Existing mortgage entry for liens certificates."""

    model_config = ConfigDict(extra="forbid")

    bank: Optional[str] = Field(default=None, description="Bank name")
    amount: Optional[float] = Field(default=None, description="Mortgage amount")
    date: Optional[str] = Field(default=None, description="Mortgage date (YYYY-MM-DD)")


class LiensCertificateData(BaseModel):
    """Schema for Liens Certificate (Section 2.8)."""

    model_config = ConfigDict(extra="forbid")

    existing_mortgages: Optional[List[ExistingMortgageEntry]] = Field(
        default=None,
        description="Existing mortgages (bank, amount, date)",
    )
    need_for_lender_consent: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether lender consent is needed. " + YES_NO_RESPONSE_INSTRUCTION,
    )


class NonOverlapProtectedAreasCertificateData(BaseModel):
    """Schema for Non-overlap with Protected Areas Certificate (Section 2.10)."""

    model_config = ConfigDict(extra="forbid")

    protected_area_presence: Optional[YesNoAnswer] = Field(
        default=None,
        description="Whether protected area presence is indicated. " + YES_NO_RESPONSE_INSTRUCTION,
    )
    geographic_reference: Optional[str] = Field(
        default=None,
        description="Geographic reference (coordinates or location reference)",
    )
    issuing_authority: Optional[str] = Field(default=None, description="Issuing authority")
    issuance_date: Optional[str] = Field(
        default=None,
        description="Date of issuance (YYYY-MM-DD)",
    )
    validity_date: Optional[str] = Field(
        default=None,
        description="Validity date (YYYY-MM-DD)",
    )


class HRPolicyCodeOfConductData(BaseModel):
    """Schema for HR Policy / Code of Conduct (Section 2.11)."""

    model_config = ConfigDict(extra="forbid")

    document_language: Optional[DocumentLanguageAnswer] = Field(
        default=None,
        description=(
            "Primary language of the source document. "
            "Return exactly one of: Spanish, English, Other."
        ),
    )

    human_rights_policy_exists: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether a human rights policy exists. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    labor_standards_policy_exists: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether a labor standards policy exists. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    prohibition_of_forced_labor: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether forced labor is explicitly prohibited. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    prohibition_of_child_labor: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether child labor is explicitly prohibited. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    non_discrimination_policy: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether a non-discrimination policy exists. "
            "Return exactly one of: Yes, No. "
            "Do not return true/false or any other variant."
        ),
    )
    supplier_labor_requirements: Optional[str] = Field(
        default=None,
        description=(
            "Brief summary (2-4 sentences) of the labor and safety requirements that apply to "
            "suppliers, contractors, and subcontractors — e.g. mandatory compliance with OHS/E&S "
            "policies, contractual clauses, PPE obligations, and monitoring mechanisms. "
            "Do NOT copy raw paragraphs from the document; write a concise summary. "
            + SOURCE_LANGUAGE_RESPONSE_INSTRUCTION
        ),
    )


# =============================================================================
# Permits Extraction Schemas (Section 2.1)
# =============================================================================


class ElectricalUtilityFeasibilityReportData(BaseModel):
    """
    Schema for Electrical Utility Feasibility Report (Section 2.1).

    Utility feasibility report from the electrical distribution company
    confirming grid connection capacity and regulatory compliance.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Extracted Fields - Capacity Information
    # -------------------------------------------------------------------------
    capacity_requested_kw: Optional[float] = Field(
        default=None,
        description="Capacity requested in kW or MW (convert to kW if in MW)",
    )
    feasibility_issued: Optional[YesNoAnswer] = Field(
        default=None,
        description=(
            "Whether feasibility has been issued or approved. " + YES_NO_RESPONSE_INSTRUCTION
        ),
    )
    available_hosting_capacity_kw: Optional[float] = Field(
        default=None,
        description="Available hosting capacity at the connection point in kW or MW (convert to kW if in MW)",
    )
    max_permitted_annual_generation_kwh: Optional[float] = Field(
        default=None,
        description="Maximum permitted annual generation in kWh or MWh (convert to kWh if in MWh)",
    )

    # -------------------------------------------------------------------------
    # Extracted Fields - Regulatory & Validity
    # -------------------------------------------------------------------------
    regulatory_framework: Optional[str] = Field(
        default=None,
        description="Regulatory framework or legal basis cited (e.g., 'ARCONEL 003/18', 'Regulation XYZ')",
    )
    issue_date: Optional[str] = Field(
        default=None,
        description="Date the feasibility report was issued (YYYY-MM-DD)",
    )
    validity_period_months: Optional[int] = Field(
        default=None,
        description="Validity period of the feasibility report in months",
    )

    # -------------------------------------------------------------------------
    # Computed Field
    # -------------------------------------------------------------------------
    validity_expiry_date: Optional[str] = Field(
        default=None,
        description="Computed expiry date (Issue Date + Validity Period). Format: YYYY-MM-DD",
    )

    # -------------------------------------------------------------------------
    # Document Metadata
    # -------------------------------------------------------------------------
    utility_company_name: Optional[str] = Field(
        default=None,
        description="Name of the electrical utility company that issued the report",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Project name as stated in the feasibility report",
    )
    connection_point: Optional[str] = Field(
        default=None,
        description="Grid connection point or substation name",
    )
    voltage_level_kv: Optional[float] = Field(
        default=None,
        description="Voltage level for connection in kV",
    )
    report_reference_number: Optional[str] = Field(
        default=None,
        description="Reference number or document ID of the feasibility report",
    )

    def compute_expiry_date(self) -> "ElectricalUtilityFeasibilityReportData":
        """Compute validity expiry date from issue date and validity period."""
        if self.issue_date and self.validity_period_months:
            try:
                from datetime import datetime
                from dateutil.relativedelta import relativedelta

                issue = datetime.strptime(self.issue_date, "%Y-%m-%d")
                expiry = issue + relativedelta(months=self.validity_period_months)
                self.validity_expiry_date = expiry.strftime("%Y-%m-%d")
            except Exception:
                pass  # If parsing fails, leave as None
        return self


class LandUsePermitData(BaseModel):
    """
    Schema for Land Use Permit.

    Zoning or land use authorization for the project site.
    """

    model_config = ConfigDict(extra="forbid")

    issue_date: Optional[str] = Field(
        default=None,
        description="Date the permit was issued (YYYY-MM-DD)",
    )
    municipality_issuing_body: Optional[str] = Field(
        default=None,
        description="Municipality issuing body",
    )
    allowed_land_use_category: Optional[str] = Field(
        default=None,
        description="Allowed land use category",
    )
    validity_period: Optional[str] = Field(
        default=None,
        description="Validity period (months/years)",
    )


# =============================================================================
# Combined Category Schemas
# =============================================================================


class CompanyInformationData(BaseModel):
    """Combined schema for all Company Information extractions."""

    model_config = ConfigDict(extra="forbid")

    legal_information: Optional[LegalInformation] = Field(
        default=None, description="Legal existence and tax information (Section 1.1)"
    )
    shareholder_structure: Optional[ShareholderStructure] = Field(
        default=None, description="Shareholders and ownership structure (Section 1.2)"
    )
    legal_representation: Optional[LegalRepresentation] = Field(
        default=None, description="Legal representative information (Section 1.3)"
    )


class CompanyFinancialsData(BaseModel):
    """Combined schema for all Company Financials extractions."""

    model_config = ConfigDict(extra="forbid")

    financial_statements: Optional[FinancialStatementsData] = Field(
        default=None, description="Financial statements with ratios (Section 1.2)"
    )
    income_tax_filings: Optional[IncomeTaxFilingsData] = Field(
        default=None, description="Income tax filings data (Section 1.3)"
    )
    cash_flow_statements: Optional[CashFlowStatementsData] = Field(
        default=None, description="Cash flow statements data (Section 1.4)"
    )
    tax_compliance_certificate: Optional[TaxComplianceCertificateData] = Field(
        default=None, description="Tax compliance certificate data (Section 1.5)"
    )
    economical_offer_boq: Optional[EconomicalOfferBOQData] = Field(
        default=None, description="Economical offer / BOQ data (Section 1.6)"
    )


class CompanyExperienceData(BaseModel):
    """Combined schema for all Company Experience extractions."""

    model_config = ConfigDict(extra="forbid")

    project_acceptance_certificates: Optional[ProjectAcceptanceCertificatesData] = Field(
        default=None, description="Project acceptance certificates data (Section 4.1)"
    )
    oam_contracts: Optional[OAMContractData] = Field(
        default=None, description="O&M contracts data (Section 4.2)"
    )


class ESGData(BaseModel):
    """Combined schema for all ESG extractions."""

    model_config = ConfigDict(extra="forbid")

    ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN: Optional[ESHSESMSPoliciesData] = Field(
        default=None, description="ESHS/ESMS policies data (Section 3.1)"
    )
    qaqc_commissioning: Optional[QAQCCommissioningData] = Field(
        default=None, description="QA/QC and commissioning data (Section 3.2)"
    )
    INDUSTRIAL_SAFETY_PLAN: Optional[IndustrialSafetyPlanData] = Field(
        default=None, description="Industrial safety plan data (Section 3.3)"
    )
    environmental_licence_eia: Optional[EnvironmentalLicenceEIAData] = Field(
        default=None,
        description="Environmental Licence / EIA data (Section 2.4)",
    )
    emergency_response_security_plan: Optional[EmergencyResponseSecurityPlanData] = Field(
        default=None,
        description="Emergency Response & Security Plan data (Section 2.6)",
    )
    site_legal_status_summary: Optional[SiteLegalStatusSummaryData] = Field(
        default=None,
        description="Site Legal Status Summary data (Section 2.7)",
    )
    liens_certificate: Optional[LiensCertificateData] = Field(
        default=None,
        description="Liens Certificate data (Section 2.8)",
    )
    non_overlap_with_protected_areas_certificate: Optional[
        NonOverlapProtectedAreasCertificateData
    ] = Field(
        default=None,
        description="Non-overlap with Protected Areas Certificate data (Section 2.10)",
    )
    hr_policy_code_of_conduct: Optional[HRPolicyCodeOfConductData] = Field(
        default=None,
        description="HR Policy / Code of Conduct data (Section 2.11)",
    )
    land_use_permit: Optional[LandUsePermitData] = Field(
        default=None,
        description="Land use permit data (Section 2.9)",
    )


class PermitsData(BaseModel):
    """Combined schema for all Permits extractions."""

    model_config = ConfigDict(extra="forbid")

    electrical_utility_feasibility: Optional[ElectricalUtilityFeasibilityReportData] = Field(
        default=None, description="Electrical utility feasibility report data (Section 2.1)"
    )


class IECCertificateEvidenceData(BaseModel):
    """Schema for a standalone IEC certificate uploaded for module or inverter evidence."""

    model_config = ConfigDict(extra="forbid")

    standard_code: Optional[str] = Field(
        default=None,
        description=(
            "IEC standard code explicitly confirmed in the certificate, e.g. IEC 61215, "
            "IEC 61730, IEC TS 62804, IEC 62716, IEC 61701, IEC 62109, IEC 61727, IEC 61000. "
            "Return null if the document does not confirm an IEC standard."
        ),
    )
    validity_date: Optional[str] = Field(
        default=None,
        description=(
            "Certificate validity or expiry date in YYYY-MM-DD format. "
            "Return null if the document does not state a validity or expiry date."
        ),
    )


class BloombergEvidenceData(BaseModel):
    """Schema for a standalone Bloomberg evidence document uploaded for module or inverter."""

    model_config = ConfigDict(extra="forbid")

    rating: Optional[str] = Field(
        default=None,
        description=(
            "BloombergNEF or Bloomberg qualification or rating explicitly shown in the document, "
            "for example AAA, AA, A, or Tier 1. Return null if no rating is confirmed."
        ),
    )


# =============================================================================
# Classification Result Schema
# =============================================================================


class ClassificationResult(BaseModel):
    """Schema for two-level document classification."""

    model_config = ConfigDict(extra="forbid")

    top_level_category: TopLevelCategory = Field(
        description="The top-level category (Company Information, Company Financials, Financial, Technical, etc.)"
    )
    document_type: DocumentType = Field(
        description="The specific document type within the top-level category"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score for the classification (0.0 to 1.0)"
    )
    reasoning: str = Field(description="Brief explanation of why this classification was chosen")
    key_indicators: List[str] = Field(
        description="Key indicators found in the document that support this classification"
    )


# =============================================================================
# Model Registry
# =============================================================================

PYDANTIC_MODELS: dict[DocumentType, Type[BaseModel]] = {
    # Company Information
    DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE: LegalInformation,
    DocumentType.SHAREHOLDERS_DECLARATION: ShareholderStructure,
    DocumentType.LEGAL_REPRESENTATIVE_APPOINTMENT: LegalRepresentation,
    DocumentType.ENERGY_CONSUMPTION_BILLS: EnergyConsumptionBillsCollection,
    # Company Financials
    DocumentType.FINANCIAL_STATEMENTS: FinancialStatementsData,
    DocumentType.INCOME_TAX_FILINGS: IncomeTaxFilingsData,
    DocumentType.CASH_FLOW_STATEMENTS: CashFlowStatementsData,
    DocumentType.TAX_COMPLIANCE_CERTIFICATE: TaxComplianceCertificateData,
    DocumentType.ECONOMICAL_OFFER_BOQ: EconomicalOfferBOQData,
    # Company Experience
    DocumentType.PROJECT_ACCEPTANCE_CERTIFICATES: ProjectAcceptanceCertificatesData,
    DocumentType.OAM_CONTRACTS: OAMContractData,
    # ESG
    DocumentType.ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN: ESHSESMSPoliciesData,
    DocumentType.QAQC_COMMISSIONING_PROCEDURES: QAQCCommissioningData,
    DocumentType.INDUSTRIAL_SAFETY_PLAN: IndustrialSafetyPlanData,
    DocumentType.ENVIRONMENTAL_LICENCE_EIA: EnvironmentalLicenceEIAData,
    DocumentType.EMERGENCY_RESPONSE_SECURITY_PLAN: EmergencyResponseSecurityPlanData,
    DocumentType.SITE_LEGAL_STATUS_SUMMARY: SiteLegalStatusSummaryData,
    DocumentType.LIENS_CERTIFICATE: LiensCertificateData,
    DocumentType.NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE: NonOverlapProtectedAreasCertificateData,
    DocumentType.HR_POLICY_CODE_OF_CONDUCT: HRPolicyCodeOfConductData,
    DocumentType.LAND_USE_PERMIT: LandUsePermitData,
    # Permits
    DocumentType.ELECTRICAL_UTILITY_FEASIBILITY_REPORT: ElectricalUtilityFeasibilityReportData,
    # Equipment evidence (standalone uploads)
    DocumentType.MODULE_IEC_CERTIFICATE: IECCertificateEvidenceData,
    DocumentType.INVERTER_IEC_CERTIFICATE: IECCertificateEvidenceData,
    DocumentType.MODULE_BLOOMBERG_EVIDENCE: BloombergEvidenceData,
    DocumentType.INVERTER_BLOOMBERG_EVIDENCE: BloombergEvidenceData,
    # Energy Monitoring — Financial module (extract/validate only; see the enum note)
    DocumentType.CNEL_ENERGY_BILL: CnelEnergyBillData,
}

# Add Technical + Uncategorized schemas from landing_ai_poc_sdk2
# to keep a single canonical model registry across classification/extraction flows.
try:
    from ddx.classification.landing_ai_poc_sdk2 import (
        ProjectSimulationReportData,
        ProjectDataMainEquipmentSheetsData,
        ProjectBasicEngineeringData,
        ProjectVisitReportData,
        ProjectLayoutData,
        KmzPoligonData,
        CableSizingCalculationReportData,
        GroundingSystemSingleLineDiagramData,
        UncategorizedDocumentData,
    )

    PYDANTIC_MODELS.update(
        {
            DocumentType.PROJECT_SIMULATION_REPORT: ProjectSimulationReportData,
            DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS: ProjectDataMainEquipmentSheetsData,
            DocumentType.PROJECT_BASIC_ENGINEERING: ProjectBasicEngineeringData,
            DocumentType.PROJECT_VISIT_REPORT: ProjectVisitReportData,
            DocumentType.PROJECT_LAYOUT: ProjectLayoutData,
            DocumentType.KMZ_POLIGON: KmzPoligonData,
            DocumentType.CABLE_SIZING_CALCULATION: CableSizingCalculationReportData,
            DocumentType.GROUNDING_SYSTEM_DIAGRAM: GroundingSystemSingleLineDiagramData,
            DocumentType.UNCATEGORIZED: UncategorizedDocumentData,
        }
    )
except Exception:
    pass


# =============================================================================
# Sub-type → Parent Requirement Mapping
# =============================================================================

# These document types are used only for targeted extraction schema selection.
# They have no independent entry in the requirements database and must be
# reported back to NestJS as their parent requirement type.
DOCUMENT_TYPE_PARENT_REQUIREMENT: dict[DocumentType, DocumentType] = {
    DocumentType.MODULE_IEC_CERTIFICATE: DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS,
    DocumentType.INVERTER_IEC_CERTIFICATE: DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS,
    DocumentType.MODULE_BLOOMBERG_EVIDENCE: DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS,
    DocumentType.INVERTER_BLOOMBERG_EVIDENCE: DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS,
}


def get_extraction_model(document_type: DocumentType) -> Optional[Type[BaseModel]]:
    """Get the Pydantic model for a given document type."""
    return PYDANTIC_MODELS.get(document_type)


def get_top_level_category(document_type: DocumentType) -> Optional[TopLevelCategory]:
    """Get the top-level category for a given document type."""
    return DOCUMENT_TYPE_TO_TOP_LEVEL.get(document_type)


def get_document_types_for_category(top_level: TopLevelCategory) -> List[DocumentType]:
    """Get all document types that belong to a top-level category."""
    return [
        doc_type
        for doc_type, category in DOCUMENT_TYPE_TO_TOP_LEVEL.items()
        if category == top_level
    ]
