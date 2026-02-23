#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document categories and extraction schemas for due diligence documents.
Supports two-level categorization: Top-level category → Document type
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Top-Level Categories (Level 1)
# =============================================================================


class TopLevelCategory(str, Enum):
    """Top-level document categories."""

    COMPANY_INFORMATION = "Company Information"
    COMPANY_FINANCIALS = "Company Financials"
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
    PROJECT_BASIC_ENGINEERING = "Project Basic Engineering"
    PROJECT_VISIT_REPORT = "Project Visit Report"
    PROJECT_LAYOUT = "Project Layout"
    KMZ_POLIGON = "KMZ Poligon"
    CABLE_SIZING_CALCULATION = "Cable Sizing Calculation Report"
    GROUNDING_SYSTEM_DIAGRAM = "Grounding System"

    # ESG Documents
    ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN = "Environmental  and Social Management Plan (EMP)"
    QAQC_COMMISSIONING_PROCEDURES = "QA/QC & Commissioning Procedures"
    INDUSTRIAL_SAFETY_PLAN = "Industrial Safety Plan"
    ENVIRONMENTAL_LICENCE_EIA = "Environmental Licence / EIA"
    ENVIRONMENTAL_SOCIAL_MANAGEMENT_PLAN_ESMP = "Environmental & Social Management Plan (ESMP)"
    EMERGENCY_RESPONSE_SECURITY_PLAN = "Emergency Response & Security Plan"
    SITE_LEGAL_STATUS_SUMMARY = "Site Legal Status Summary"
    LIENS_CERTIFICATE = "Liens Certificate"
    NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE = "Non-overlap with Protected Areas Certificate"
    HR_POLICY_CODE_OF_CONDUCT = "HR Policy / Code of Conduct"

    # Permits Documents
    ELECTRICAL_UTILITY_FEASIBILITY_REPORT = "Electrical Utility Feasibility Report"
    LAND_USE_PERMIT = "Land Use Permit"

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
    DocumentType.ECONOMICAL_OFFER_BOQ: TopLevelCategory.COMPANY_FINANCIALS,
    # Company Experience
    DocumentType.PROJECT_ACCEPTANCE_CERTIFICATES: TopLevelCategory.COMPANY_EXPERIENCE,
    DocumentType.OAM_CONTRACTS: TopLevelCategory.COMPANY_EXPERIENCE,
    # Technical
    DocumentType.PROJECT_SIMULATION_REPORT: TopLevelCategory.TECHNICAL,
    DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS: TopLevelCategory.TECHNICAL,
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
    DocumentType.ENVIRONMENTAL_SOCIAL_MANAGEMENT_PLAN_ESMP: TopLevelCategory.ESG,
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
    DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE: "Official certificate containing company legal name, tax ID (RUC), commercial activity, and incorporation date",
    DocumentType.SHAREHOLDERS_DECLARATION: "Declaration document listing shareholders/owners with their ownership percentages (>10% stake)",
    DocumentType.LEGAL_REPRESENTATIVE_APPOINTMENT: "Official appointment document for the company's legal representative including validity period",
    DocumentType.ENERGY_CONSUMPTION_BILLS: "Energy bills or energy reports from the electricity utility provider (e.g., CNEL) showing monthly energy consumption, demand, and tariffs for 12 months. Used to create consumption profile with monthly and annual statistics.",
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
    DocumentType.PROJECT_BASIC_ENGINEERING: "Fundamental engineering design and technical specifications",
    DocumentType.PROJECT_VISIT_REPORT: "Field visit observations and assessment findings",
    DocumentType.PROJECT_LAYOUT: "Spatial arrangement and layout diagrams of the project",
    DocumentType.KMZ_POLIGON: "Geographic polygon data in KMZ format",
    DocumentType.CABLE_SIZING_CALCULATION: "Cable sizing calculations and electrical specifications",
    DocumentType.GROUNDING_SYSTEM_DIAGRAM: "Grounding system design and single line diagram",
    # ESG
    DocumentType.ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN: "Environmental, Social, Health and Safety (ESHS) or Environmental and Social Management System (ESMS) policies document covering IFC performance standards, OHS procedures, hazardous materials handling, labor procedures, waste management, and resource use controls",
    DocumentType.QAQC_COMMISSIONING_PROCEDURES: "Quality Assurance/Quality Control and commissioning procedures document including visual inspection summary, electrical test results, and performance metrics",
    DocumentType.INDUSTRIAL_SAFETY_PLAN: "Human Resources manual or Code of Conduct document containing IFC-aligned HR practices and company policies",
    DocumentType.ENVIRONMENTAL_LICENCE_EIA: "Environmental licence or EIA documentation including licence metadata and ESG risk-screening findings for habitats, biodiversity, communities, heritage, and consultation.",
    DocumentType.ENVIRONMENTAL_SOCIAL_MANAGEMENT_PLAN_ESMP: "Environmental and Social Management Plan (ESMP) with validity period, scope, environmental/social aspects, monitoring indicators, and mitigation/adaptation measures.",
    DocumentType.EMERGENCY_RESPONSE_SECURITY_PLAN: "Emergency response and security plan covering climate and security risks, crisis protocols, adaptation actions, and authority coordination.",
    DocumentType.SITE_LEGAL_STATUS_SUMMARY: "Site legal status summary with land tenure, title/lease documentation, rights and claims, disputes, and expropriation risk context.",
    DocumentType.LIENS_CERTIFICATE: "Liens certificate detailing existing mortgages/lien encumbrances and whether lender consent is required.",
    DocumentType.NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE: "Certificate confirming non-overlap with protected areas, including geographic reference and issuance/validity details.",
    DocumentType.HR_POLICY_CODE_OF_CONDUCT: "HR policy and code of conduct covering human rights, labor standards, forced/child labor prohibition, non-discrimination, and supplier labor requirements.",
    DocumentType.LAND_USE_PERMIT: "Land use permit or zoning approval for the project site",
    # Permits
    DocumentType.ELECTRICAL_UTILITY_FEASIBILITY_REPORT: "Utility feasibility report from the electrical distribution company containing capacity requested, feasibility status, available hosting capacity, maximum permitted annual generation, regulatory framework, issue date, and validity period",
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
    ownership_percentage: Optional[float] = Field(
        default=None, description="Ownership percentage (only shareholders with >10% stake)"
    )
    shareholder_type: Optional[str] = Field(
        default=None, description="Type of shareholder (Individual/Corporate/Institutional)"
    )


class ShareholderStructure(BaseModel):
    """Schema for Shareholders Declaration (Section 1.2)."""

    model_config = ConfigDict(extra="forbid")

    number_of_shareholders: int = Field(
        description="Total number of shareholders listed in the declaration"
    )
    shareholders: List[ShareholderEntry] = Field(
        description="List of shareholders with >10% ownership stake"
    )
    total_declared_percentage: Optional[float] = Field(
        default=None, description="Sum of all declared ownership percentages"
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
    appointment_expiry_date: Optional[str] = Field(
        default=None, description="Computed expiry date (appointment date + years of validity)"
    )


# =============================================================================
# Energy Consumption Bills / Energy Reports (Section 2.1)
# =============================================================================


class MonthlyEnergyConsumptionEntry(BaseModel):
    """
    Monthly energy consumption data entry.

    Represents one month of energy billing data from utility provider.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Month Identification
    # -------------------------------------------------------------------------
    month: str = Field(description="Month name (January, February, etc.) or month number (1-12)")
    year: Optional[int] = Field(
        default=None,
        description="Year of the billing period (e.g., 2024)",
    )
    billing_period_start: Optional[str] = Field(
        default=None,
        description="Start date of the billing period (YYYY-MM-DD)",
    )
    billing_period_end: Optional[str] = Field(
        default=None,
        description="End date of the billing period (YYYY-MM-DD)",
    )

    # -------------------------------------------------------------------------
    # Energy Consumption (Extracted)
    # -------------------------------------------------------------------------
    energy_consumption_kwh: float = Field(
        description="Monthly energy consumption in kWh, MWh, or GWh (convert to kWh)"
    )

    # -------------------------------------------------------------------------
    # Demand Values (Extracted)
    # -------------------------------------------------------------------------
    average_demand_kw: Optional[float] = Field(
        default=None,
        description="Monthly average demand in kW or MW (convert to kW)",
    )
    peak_demand_kw: Optional[float] = Field(
        default=None,
        description="Monthly peak demand in kW or MW (convert to kW)",
    )

    # -------------------------------------------------------------------------
    # Tariff Information (Extracted)
    # -------------------------------------------------------------------------
    energy_tariff_usd_kwh: Optional[float] = Field(
        default=None,
        description="Energy tariff in $/kWh for the month",
    )
    total_bill_amount_usd: Optional[float] = Field(
        default=None,
        description="Total bill amount in USD for the month",
    )


class EnergyConsumptionBillsData(BaseModel):
    """
    Schema for Energy Consumption Bills / Energy Reports (Section 2.1).

    Energy bills from the electricity utility provider (e.g., CNEL) showing
    monthly energy consumption, demand, and tariffs for 12 months.
    Output structure: Consumption Profile (Table + Single values + Graph)
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Utility Provider Information (Extracted)
    # -------------------------------------------------------------------------
    electricity_utility_provider: Optional[str] = Field(
        default=None,
        description="Name of the electricity utility provider (e.g., CNEL, EEQ)",
    )
    account_number: Optional[str] = Field(
        default=None,
        description="Utility account number or client ID",
    )
    meter_number: Optional[str] = Field(
        default=None,
        description="Electric meter number",
    )
    service_address: Optional[str] = Field(
        default=None,
        description="Service address for the energy account",
    )
    tariff_category: Optional[str] = Field(
        default=None,
        description="Tariff category (e.g., Industrial, Commercial, Residential)",
    )

    # -------------------------------------------------------------------------
    # Monthly Consumption Data (Table - 12 months)
    # -------------------------------------------------------------------------
    monthly_consumption: List[MonthlyEnergyConsumptionEntry] = Field(
        description="Monthly energy consumption data for 12 months"
    )

    # -------------------------------------------------------------------------
    # Computed Annual Totals
    # -------------------------------------------------------------------------
    annual_energy_consumption_kwh: Optional[float] = Field(
        default=None,
        description="Total annual energy consumption in kWh - Computed as sum of monthly consumption",
    )
    annual_energy_tariff_usd_kwh: Optional[float] = Field(
        default=None,
        description="Weighted average annual energy tariff in $/kWh - Computed from monthly consumption and tariffs",
    )

    # -------------------------------------------------------------------------
    # Consumption Profile Graph Data (Computed)
    # -------------------------------------------------------------------------
    consumption_profile_graph_data: Optional[dict] = Field(
        default=None,
        description="Data for generating monthly consumption and demand bar charts (line/bar charts)",
    )

    def compute_annual_totals(self) -> "EnergyConsumptionBillsData":
        """Compute annual energy consumption and weighted average tariff."""
        if self.monthly_consumption:
            # Sum annual consumption
            total_consumption = sum(
                m.energy_consumption_kwh
                for m in self.monthly_consumption
                if m.energy_consumption_kwh is not None
            )
            self.annual_energy_consumption_kwh = (
                round(total_consumption, 2) if total_consumption else None
            )

            # Compute weighted average tariff
            weighted_sum = 0.0
            total_weight = 0.0
            for m in self.monthly_consumption:
                if m.energy_consumption_kwh and m.energy_tariff_usd_kwh:
                    weighted_sum += m.energy_consumption_kwh * m.energy_tariff_usd_kwh
                    total_weight += m.energy_consumption_kwh

            if total_weight > 0:
                self.annual_energy_tariff_usd_kwh = round(weighted_sum / total_weight, 4)

            # Generate graph data
            self.consumption_profile_graph_data = {
                "months": [m.month for m in self.monthly_consumption],
                "consumption_kwh": [m.energy_consumption_kwh for m in self.monthly_consumption],
                "average_demand_kw": [m.average_demand_kw for m in self.monthly_consumption],
                "peak_demand_kw": [m.peak_demand_kw for m in self.monthly_consumption],
            }

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


class FinancialStatementsData(BaseModel):
    """
    Schema for Financial Statements (Section 1.2).

    Extracts financial data for minimum 3 years from audited or internal
    financial statements. Includes both extracted values and computed ratios.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------------
    company_name: Optional[str] = Field(
        default=None, description="Company name as stated in the financial statements"
    )
    currency: Optional[str] = Field(
        default=None,
        description="Currency used in the statements (e.g., USD, EUR, or local currency code)",
    )
    is_audited: Optional[bool] = Field(
        default=None,
        description="Whether the financial statements are audited (True) or internal/unaudited (False)",
    )
    auditor_name: Optional[str] = Field(
        default=None, description="Name of the auditing firm (if audited)"
    )

    # -------------------------------------------------------------------------
    # Yearly Financial Data (minimum 3 years)
    # -------------------------------------------------------------------------
    financial_ratios: List[YearlyFinancialData] = Field(
        description="Financial data and ratios for each fiscal year"
    )

    def compute_all_ratios(self) -> "FinancialStatementsData":
        """Compute ratios for all years."""
        for year_data in self.financial_ratios:
            year_data.compute_ratios()
        return self


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

    Extracts tax payment information from SRI/Tax Authority filings
    for minimum 3 years.
    """

    model_config = ConfigDict(extra="forbid")

    company_name: Optional[str] = Field(
        default=None, description="Company name as stated in the tax filings"
    )
    tax_id_ruc: Optional[str] = Field(default=None, description="Tax ID (RUC) number")
    tax_authority: Optional[str] = Field(
        default=None, description="Tax authority name (e.g., SRI for Ecuador)"
    )
    annual_filings: List[AnnualTaxFiling] = Field(
        description="Tax filing data for each fiscal year"
    )


class AnnualCashFlow(BaseModel):
    """Cash flow data for a single fiscal year."""

    model_config = ConfigDict(extra="forbid")

    fiscal_year: int = Field(description="Fiscal year for the cash flow statement")
    operating_cash_flow: Optional[float] = Field(
        default=None, description="Net cash from operating activities"
    )
    investing_cash_flow: Optional[float] = Field(
        default=None, description="Net cash from investing activities"
    )
    financing_cash_flow: Optional[float] = Field(
        default=None, description="Net cash from financing activities"
    )
    net_change_in_cash: Optional[float] = Field(
        default=None, description="Net change in cash and cash equivalents"
    )


class CashFlowStatementsData(BaseModel):
    """
    Schema for Cash Flow Statements (Section 1.4).

    Note: Per requirements, this may only be provided for 1 year.
    """

    model_config = ConfigDict(extra="forbid")

    company_name: Optional[str] = Field(
        default=None, description="Company name as stated in the cash flow statements"
    )
    currency: Optional[str] = Field(default=None, description="Currency used (e.g., USD, EUR)")
    annual_cash_flows: List[AnnualCashFlow] = Field(
        description="Cash flow data for each fiscal year"
    )


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
    has_outstanding_debts: Optional[bool] = Field(
        default=None,
        description="Whether there are outstanding tax debts (should be False for compliant status)",
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
    signed_by_client: Optional[bool] = Field(
        default=None,
        description="Whether the certificate is signed by the client (Yes/No)",
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

    # -------------------------------------------------------------------------
    # Summary Statistics (computed)
    # -------------------------------------------------------------------------
    total_projects: Optional[int] = Field(
        default=None,
        description="Total number of projects with acceptance certificates",
    )
    total_capacity_kw: Optional[float] = Field(
        default=None,
        description="Total capacity of all projects in kW (sum of project capacities)",
    )
    provisional_certificates_count: Optional[int] = Field(
        default=None,
        description="Number of provisional acceptance certificates",
    )
    final_certificates_count: Optional[int] = Field(
        default=None,
        description="Number of final acceptance certificates",
    )

    def compute_summary(self) -> "ProjectAcceptanceCertificatesData":
        """Compute summary statistics from certificates."""
        if self.certificates:
            self.total_projects = len(self.certificates)

            # Sum capacities
            capacities = [c.project_capacity_kw for c in self.certificates if c.project_capacity_kw]
            self.total_capacity_kw = sum(capacities) if capacities else None

            # Count certificate types
            self.provisional_certificates_count = sum(
                1
                for c in self.certificates
                if c.certificate_type and c.certificate_type.lower() == "provisional"
            )
            self.final_certificates_count = sum(
                1
                for c in self.certificates
                if c.certificate_type and c.certificate_type.lower() == "final"
            )
        return self


class OAMContractData(BaseModel):
    """
    Schema for O&M Contracts (Section 4.2).

    Operations and Maintenance contract information demonstrating
    the company's O&M capabilities and approach.
    Output structure: O&M (Single value)
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Maintenance Approach
    # -------------------------------------------------------------------------
    planned_maintenance_approach: Optional[str] = Field(
        default=None,
        description="Description of the planned maintenance approach including frequency, scope, and methodology",
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

    # -------------------------------------------------------------------------
    # ESMS Aligned with IFC Performance Standards
    # -------------------------------------------------------------------------
    esms_aligned_with_ifc_performance_standards: Optional[str] = Field(
        default=None,
        description="Summary of how the ESMS aligns with IFC Performance Standards (max 4 lines). Include Yes/No indication and brief description.",
    )

    # -------------------------------------------------------------------------
    # OHS Procedures Summary
    # -------------------------------------------------------------------------
    ohs_procedures_summary: Optional[str] = Field(
        default=None,
        description="Summary of Occupational Health and Safety procedures (max 4 lines). Key safety protocols and procedures.",
    )

    # -------------------------------------------------------------------------
    # Hazardous Materials Handling
    # -------------------------------------------------------------------------
    hazardous_materials_handling: Optional[str] = Field(
        default=None,
        description="Summary of hazardous materials handling procedures (max 4 lines). How hazardous materials are managed and disposed.",
    )

    # -------------------------------------------------------------------------
    # Labor Procedures & Workers Rights
    # -------------------------------------------------------------------------
    labor_procedures_workers_rights: Optional[str] = Field(
        default=None,
        description="Summary of labor procedures and workers rights policies (max 4 lines). Worker protections and labor compliance.",
    )

    # -------------------------------------------------------------------------
    # Waste Management Monitoring
    # -------------------------------------------------------------------------
    waste_management_monitoring: Optional[str] = Field(
        default=None,
        description="Summary of waste management and monitoring procedures (max 4 lines). Waste disposal and recycling practices.",
    )

    # -------------------------------------------------------------------------
    # Resource Use Controls
    # -------------------------------------------------------------------------
    resource_use_controls: Optional[str] = Field(
        default=None,
        description="Summary of resource use controls (max 4 lines). Energy efficiency, water usage, and resource conservation measures.",
    )

    # -------------------------------------------------------------------------
    # Document Metadata
    # -------------------------------------------------------------------------
    document_date: Optional[str] = Field(
        default=None,
        description="Date of the policy document (YYYY-MM-DD if available)",
    )
    document_version: Optional[str] = Field(
        default=None,
        description="Version number or revision of the policy document",
    )
    company_name: Optional[str] = Field(
        default=None,
        description="Company name as stated in the document",
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

    # -------------------------------------------------------------------------
    # Visual Inspection Summary
    # -------------------------------------------------------------------------
    visual_inspection_summary: Optional[str] = Field(
        default=None,
        description="Summary of visual inspection findings. Overall condition assessment.",
    )
    visual_inspection_passed: Optional[bool] = Field(
        default=None,
        description="Whether visual inspection passed (True/False)",
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


class HRManualCodeOfConductData(BaseModel):
    """
    Schema for Industrial Safety Plan (Section 3.3).

    Human resources policies and code of conduct aligned with IFC standards.
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # IFC-aligned HR Practices Summary
    # -------------------------------------------------------------------------
    ifc_aligned_hr_practices_summary: Optional[str] = Field(
        default=None,
        description="Summary of IFC-aligned HR practices. Key HR policies that align with international standards.",
    )

    # -------------------------------------------------------------------------
    # Key Policy Areas (extracted summaries)
    # -------------------------------------------------------------------------
    non_discrimination_policy: Optional[str] = Field(
        default=None,
        description="Summary of non-discrimination and equal opportunity policies",
    )
    grievance_mechanism: Optional[str] = Field(
        default=None,
        description="Summary of grievance mechanism and complaint procedures",
    )
    working_conditions: Optional[str] = Field(
        default=None,
        description="Summary of working conditions policies (hours, overtime, leave)",
    )
    child_labor_policy: Optional[str] = Field(
        default=None,
        description="Summary of child labor prevention policy",
    )
    forced_labor_policy: Optional[str] = Field(
        default=None,
        description="Summary of forced labor prevention policy",
    )
    health_safety_policy: Optional[str] = Field(
        default=None,
        description="Summary of occupational health and safety policies for workers",
    )

    # -------------------------------------------------------------------------
    # Document Metadata
    # -------------------------------------------------------------------------
    document_date: Optional[str] = Field(
        default=None,
        description="Date of the HR manual or code of conduct (YYYY-MM-DD if available)",
    )
    document_version: Optional[str] = Field(
        default=None,
        description="Version number or revision",
    )
    company_name: Optional[str] = Field(
        default=None,
        description="Company name as stated in the document",
    )


class EnvironmentalLicenceEIAData(BaseModel):
    """Schema for Environmental Licence / EIA (Section 2.4)."""

    model_config = ConfigDict(extra="forbid")

    issuing_authority: Optional[str] = Field(default=None, description="Issuing authority")
    license_number: Optional[str] = Field(default=None, description="License number")
    issuing_date: Optional[str] = Field(
        default=None,
        description="Issuing date (YYYY-MM-DD)",
    )
    expiry_date: Optional[str] = Field(
        default=None,
        description="Expiry date (YYYY-MM-DD)",
    )
    sensitive_habitats_present: Optional[bool] = Field(
        default=None,
        description="Whether sensitive habitats are present (Yes/No)",
    )
    sensitive_habitats_description: Optional[str] = Field(
        default=None,
        description="Sensitive habitats description (2-4 lines)",
    )
    biodiversity_impacts_identified: Optional[bool] = Field(
        default=None,
        description="Whether biodiversity impacts are identified (Yes/No)",
    )
    biodiversity_impacts_summary: Optional[str] = Field(
        default=None,
        description="Biodiversity impacts summary (2-4 lines)",
    )
    ecosystem_services_impacted: Optional[bool] = Field(
        default=None,
        description="Whether ecosystem services are impacted (Yes/No)",
    )
    ecosystem_services_description: Optional[str] = Field(
        default=None,
        description="Ecosystem services description (2-4 lines)",
    )
    mitigation_measures_summary: Optional[str] = Field(
        default=None,
        description="Mitigation measures summary (2-4 lines)",
    )
    neighboring_populations_present: Optional[bool] = Field(
        default=None,
        description="Whether neighboring populations are present (Yes/No)",
    )
    neighboring_populations_description: Optional[str] = Field(
        default=None,
        description="Neighboring populations description (2-4 lines)",
    )
    critical_infrastructure_nearby: Optional[bool] = Field(
        default=None,
        description="Whether critical infrastructure is nearby (Yes/No)",
    )
    critical_infrastructure_description: Optional[str] = Field(
        default=None,
        description="Critical infrastructure description (2-4 lines)",
    )
    cultural_heritage_assets_present: Optional[bool] = Field(
        default=None,
        description="Whether cultural heritage assets are present (Yes/No)",
    )
    cultural_heritage_description: Optional[str] = Field(
        default=None,
        description="Cultural heritage description (2-4 lines)",
    )
    cultural_heritage_protection_measures: Optional[str] = Field(
        default=None,
        description="Cultural heritage protection measures (2-4 lines)",
    )
    public_consultation_required: Optional[bool] = Field(
        default=None,
        description="Whether public consultation is required (Yes/No)",
    )
    public_consultation_summary: Optional[str] = Field(
        default=None,
        description="Public consultation summary (2-4 lines)",
    )


class ESMPMonitoringIndicatorEntry(BaseModel):
    """Monitoring indicator entry in ESMP documents."""

    model_config = ConfigDict(extra="forbid")

    indicator: Optional[str] = Field(default=None, description="Monitoring indicator name")
    unit: Optional[str] = Field(default=None, description="Indicator unit")
    frequency: Optional[str] = Field(default=None, description="Monitoring frequency")


class EnvironmentalSocialManagementPlanESMPData(BaseModel):
    """Schema for Environmental & Social Management Plan (ESMP) (Section 2.5)."""

    model_config = ConfigDict(extra="forbid")

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
    monitoring_indicators: Optional[List[ESMPMonitoringIndicatorEntry]] = Field(
        default=None,
        description="Monitoring indicators with unit and frequency",
    )
    biodiversity_management_measures: Optional[str] = Field(
        default=None,
        description="Biodiversity management measures",
    )
    community_impacts_management_measures: Optional[str] = Field(
        default=None,
        description="Community impacts management measures",
    )
    climate_adaptation_measures: Optional[str] = Field(
        default=None,
        description="Climate adaptation measures",
    )


class EmergencyResponseSecurityPlanData(BaseModel):
    """Schema for Emergency Response & Security Plan (Section 2.6)."""

    model_config = ConfigDict(extra="forbid")

    last_update_date: Optional[str] = Field(
        default=None,
        description="Last update date (YYYY-MM-DD)",
    )
    risks_covered: Optional[List[str]] = Field(
        default=None,
        description="Risks covered (e.g., flood, fire, drought)",
    )
    climate_extreme_events_covered: Optional[bool] = Field(
        default=None,
        description="Whether climate extreme events are covered (Yes/No)",
    )
    climate_adaptation_actions: Optional[str] = Field(
        default=None,
        description="Climate adaptation actions",
    )
    security_risks_covered: Optional[bool] = Field(
        default=None,
        description="Whether security risks are covered (Yes/No)",
    )
    security_arrangements: Optional[str] = Field(
        default=None,
        description="Security arrangements",
    )
    access_to_basic_resources_during_crisis: Optional[str] = Field(
        default=None,
        description="Access to basic resources during crisis",
    )
    emergency_response_protocols: Optional[str] = Field(
        default=None,
        description="Emergency response protocols",
    )
    coordination_with_authorities: Optional[bool] = Field(
        default=None,
        description="Whether there is coordination with authorities (Yes/No)",
    )


class LandTitleDocumentEntry(BaseModel):
    """Land title document entry for site legal status."""

    model_config = ConfigDict(extra="forbid")

    document_type: Optional[str] = Field(default=None, description="Document type")
    document_number: Optional[str] = Field(default=None, description="Document number")
    document_date: Optional[str] = Field(default=None, description="Document date (YYYY-MM-DD)")


class LeaseContractEntry(BaseModel):
    """Lease contract entry for site legal status."""

    model_config = ConfigDict(extra="forbid")

    lessor: Optional[str] = Field(default=None, description="Lessor name")
    term: Optional[str] = Field(default=None, description="Lease term")
    expiry: Optional[str] = Field(default=None, description="Lease expiry (YYYY-MM-DD)")


class SiteLegalStatusSummaryData(BaseModel):
    """Schema for Site Legal Status Summary (Section 2.7)."""

    model_config = ConfigDict(extra="forbid")

    land_tenure_status: Optional[str] = Field(
        default=None,
        description="Land tenure status (owned/leased/concession)",
    )
    number_of_plots: Optional[int] = Field(default=None, description="Number of plots")
    land_title_documents_listed: Optional[List[LandTitleDocumentEntry]] = Field(
        default=None,
        description="Land title documents (type, number, date)",
    )
    lease_contracts_listed: Optional[List[LeaseContractEntry]] = Field(
        default=None,
        description="Lease contracts (lessor, term, expiry)",
    )
    collective_rights_indigenous_claims: Optional[bool] = Field(
        default=None,
        description="Whether collective rights or indigenous claims exist (Yes/No)",
    )
    collective_rights_description: Optional[str] = Field(
        default=None,
        description="Collective rights description",
    )
    known_property_disputes: Optional[bool] = Field(
        default=None,
        description="Whether known property disputes exist (Yes/No)",
    )
    property_disputes_summary: Optional[str] = Field(
        default=None,
        description="Property disputes summary",
    )
    expropriation_risk_identified: Optional[bool] = Field(
        default=None,
        description="Whether expropriation risk is identified (Yes/No)",
    )
    expropriation_risk_description: Optional[str] = Field(
        default=None,
        description="Expropriation risk description",
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
    need_for_lender_consent: Optional[bool] = Field(
        default=None,
        description="Whether lender consent is needed (Yes/No)",
    )


class NonOverlapProtectedAreasCertificateData(BaseModel):
    """Schema for Non-overlap with Protected Areas Certificate (Section 2.10)."""

    model_config = ConfigDict(extra="forbid")

    protected_area_presence: Optional[bool] = Field(
        default=None,
        description="Whether protected area presence is indicated (Yes/No)",
    )
    geographic_reference: Optional[str] = Field(
        default=None,
        description="Geographic reference (coordinates or location reference)",
    )
    issuing_authority: Optional[str] = Field(default=None, description="Issuing authority")
    date_of_issuance: Optional[str] = Field(
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

    human_rights_policy_exists: Optional[bool] = Field(
        default=None,
        description="Whether a human rights policy exists (Yes/No)",
    )
    labor_standards_policy_exists: Optional[bool] = Field(
        default=None,
        description="Whether a labor standards policy exists (Yes/No)",
    )
    prohibition_of_forced_labor: Optional[bool] = Field(
        default=None,
        description="Whether forced labor is explicitly prohibited (Yes/No)",
    )
    prohibition_of_child_labor: Optional[bool] = Field(
        default=None,
        description="Whether child labor is explicitly prohibited (Yes/No)",
    )
    non_discrimination_policy: Optional[bool] = Field(
        default=None,
        description="Whether a non-discrimination policy exists (Yes/No)",
    )
    supplier_labor_requirements: Optional[str] = Field(
        default=None,
        description="Supplier labor requirements (extracted text)",
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
    feasibility_issued: Optional[bool] = Field(
        default=None,
        description="Whether feasibility has been issued/approved (Yes/No)",
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

    permit_number: Optional[str] = Field(
        default=None,
        description="Land use permit number or reference",
    )
    issue_date: Optional[str] = Field(
        default=None,
        description="Date the permit was issued (YYYY-MM-DD)",
    )
    expiry_date: Optional[str] = Field(
        default=None,
        description="Permit expiry date (YYYY-MM-DD)",
    )
    issuing_authority: Optional[str] = Field(
        default=None,
        description="Authority that issued the permit",
    )
    land_use_classification: Optional[str] = Field(
        default=None,
        description="Zoning or land use classification",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Project name as stated in the permit",
    )
    parcel_id: Optional[str] = Field(
        default=None,
        description="Land parcel ID or cadastral reference",
    )
    area_m2: Optional[float] = Field(
        default=None,
        description="Permitted area in square meters",
    )
    permit_status: Optional[str] = Field(
        default=None,
        description="Current status of the permit (Active/Expired/Pending)",
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
    INDUSTRIAL_SAFETY_PLAN: Optional[HRManualCodeOfConductData] = Field(
        default=None, description="HR manual and code of conduct data (Section 3.3)"
    )
    environmental_licence_eia: Optional[EnvironmentalLicenceEIAData] = Field(
        default=None,
        description="Environmental Licence / EIA data (Section 2.4)",
    )
    environmental_social_management_plan_esmp: Optional[
        EnvironmentalSocialManagementPlanESMPData
    ] = Field(
        default=None,
        description="Environmental & Social Management Plan (ESMP) data (Section 2.5)",
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


# =============================================================================
# Classification Result Schema
# =============================================================================


class ClassificationResult(BaseModel):
    """Schema for two-level document classification."""

    model_config = ConfigDict(extra="forbid")

    top_level_category: TopLevelCategory = Field(
        description="The top-level category (Company Information, Company Financials, Technical, etc.)"
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
    DocumentType.ENERGY_CONSUMPTION_BILLS: EnergyConsumptionBillsData,
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
    DocumentType.INDUSTRIAL_SAFETY_PLAN: HRManualCodeOfConductData,
    DocumentType.ENVIRONMENTAL_LICENCE_EIA: EnvironmentalLicenceEIAData,
    DocumentType.ENVIRONMENTAL_SOCIAL_MANAGEMENT_PLAN_ESMP: EnvironmentalSocialManagementPlanESMPData,
    DocumentType.EMERGENCY_RESPONSE_SECURITY_PLAN: EmergencyResponseSecurityPlanData,
    DocumentType.SITE_LEGAL_STATUS_SUMMARY: SiteLegalStatusSummaryData,
    DocumentType.LIENS_CERTIFICATE: LiensCertificateData,
    DocumentType.NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE: NonOverlapProtectedAreasCertificateData,
    DocumentType.HR_POLICY_CODE_OF_CONDUCT: HRPolicyCodeOfConductData,
    DocumentType.LAND_USE_PERMIT: LandUsePermitData,
    # Permits
    DocumentType.ELECTRICAL_UTILITY_FEASIBILITY_REPORT: ElectricalUtilityFeasibilityReportData,
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
