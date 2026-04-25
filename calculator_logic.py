"""
Pure calculation helpers for the homeowner-calculator.

This mirrors the simplified logic used in `index.html` so we can unit-test
the math without relying on browser execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


SALT_CAP_2026_PLUS = 40_400
MORTGAGE_INTEREST_LOAN_CAP = 750_000  # federal/CA alignment in this model


def mortgage_monthly_payment(principal: float, annual_rate_percent: float, years: int) -> float:
    """
    Standard amortizing loan monthly payment.
    If annual_rate_percent == 0, payment is principal / N.
    """
    monthly_rate = (annual_rate_percent / 100.0) / 12.0
    n = years * 12
    if n <= 0:
        raise ValueError("years must be positive")
    if principal < 0:
        raise ValueError("principal must be non-negative")
    if monthly_rate == 0:
        return principal / n

    # P * (r(1+r)^N)/((1+r)^N-1)
    return principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)


def build_amortization_series(principal: float, annual_rate_percent: float, years: int) -> Dict[str, object]:
    """
    Returns monthly interest and principal arrays for each month in the term.

    Arrays are 0-based with length = years*12.
    """
    monthly_rate = (annual_rate_percent / 100.0) / 12.0
    payment = mortgage_monthly_payment(principal, annual_rate_percent, years)
    total_months = years * 12

    interest_series: List[float] = []
    principal_series: List[float] = []
    balance = principal

    for _ in range(total_months):
        interest = balance * monthly_rate
        principal_paid = payment - interest
        # Numerical safety: don't let principal-paid drift negative.
        if principal_paid < 0:
            principal_paid = 0.0
        interest_series.append(interest)
        principal_series.append(principal_paid)
        balance -= principal_paid

    return {
        "interestSeries": interest_series,
        "principalSeries": principal_series,
        "monthlyPayment": payment,
        "endingBalance": balance,
    }


def annual_mortgage_interest_first_year(principal: float, annual_rate_percent: float, years: int) -> float:
    """
    Sum of interest paid in months 1..12.
    """
    series = build_amortization_series(principal, annual_rate_percent, years)
    interest_series: List[float] = series["interestSeries"]  # type: ignore[assignment]
    if len(interest_series) < 12:
        raise ValueError("loan term must be at least 1 year in this model")
    return sum(interest_series[:12])


def year_interest(principal: float, annual_rate_percent: float, years: int, year_index_1_based: int) -> float:
    """
    Interest paid during a given year.
    year_index_1_based=1 => months 1..12, 2 => months 13..24, etc.
    """
    if year_index_1_based < 1:
        raise ValueError("year_index_1_based must be >= 1")
    series = build_amortization_series(principal, annual_rate_percent, years)
    interest_series: List[float] = series["interestSeries"]  # type: ignore[assignment]
    start = (year_index_1_based - 1) * 12
    end = start + 12
    if end > len(interest_series):
        raise ValueError("Requested year exceeds loan term")
    return sum(interest_series[start:end])


def deductible_mortgage_interest(
    loan_amount: float,
    annual_rate_percent: float,
    loan_term_years: int,
    interest_paid_in_year: float,
    mortgage_interest_loan_cap: float = MORTGAGE_INTEREST_LOAN_CAP,
) -> float:
    """
    Simplified model used in index.html:
    deductible interest is scaled by (cap / loan_amount) if loan_amount > cap,
    else full interest is deductible.
    """
    if loan_amount <= mortgage_interest_loan_cap:
        return interest_paid_in_year
    # Scale interest proportionally (simplification).
    return interest_paid_in_year * (mortgage_interest_loan_cap / loan_amount)


def compute_costs_and_tax_break(inputs: Dict[str, float]) -> Dict[str, float]:
    """
    Mirrors the simplified logic used for:
      - total monthly cost
      - total tax break (federal + state)
      - net monthly cost (clamped at >= 0)
    """
    # Inputs from the UI
    home_price = float(inputs["homePrice"])
    down_payment_percent = float(inputs["downPaymentPercent"])
    interest_rate = float(inputs["interestRate"])
    loan_term_years = int(inputs["loanTermYears"])

    property_tax_rate_percent = float(inputs["propertyTaxRate"])
    home_insurance_annual = float(inputs["homeInsurance"])
    pmi_monthly = float(inputs["pmi"])
    hoa_monthly = float(inputs["hoa"])
    utilities_monthly = float(inputs["utilities"])
    internet_monthly = float(inputs["internet"])
    maintenance_rate_percent = float(inputs["maintenanceRate"])
    landscaping_monthly = float(inputs["landscaping"])
    other_monthly = float(inputs["other"])

    federal_tax_rate_percent = float(inputs["federalTaxRate"])
    state_tax_rate_percent = float(inputs["stateTaxRate"])
    state_income_tax_annual = float(inputs.get("stateIncomeTax", 0) or 0)
    state_exemption_annual = float(inputs.get("stateExemption", 0) or 0)

    salt_cap = float(inputs.get("saltCap", SALT_CAP_2026_PLUS) or SALT_CAP_2026_PLUS)
    mortgage_interest_cap = float(inputs.get("mortgageInterestLoanCap", MORTGAGE_INTEREST_LOAN_CAP) or MORTGAGE_INTEREST_LOAN_CAP)

    down_payment_amount = home_price * (down_payment_percent / 100.0)
    loan_amount = home_price - down_payment_amount

    principal_interest_monthly = mortgage_monthly_payment(loan_amount, interest_rate, loan_term_years)
    property_tax_monthly = (home_price * (property_tax_rate_percent / 100.0)) / 12.0
    insurance_monthly = home_insurance_annual / 12.0
    maintenance_monthly = (home_price * (maintenance_rate_percent / 100.0)) / 12.0

    total_monthly = (
        principal_interest_monthly
        + property_tax_monthly
        + insurance_monthly
        + pmi_monthly
        + hoa_monthly
        + utilities_monthly
        + internet_monthly
        + maintenance_monthly
        + landscaping_monthly
        + other_monthly
    )
    total_annual = total_monthly * 12.0

    # Tax break model:
    # - interest deduction uses first-year interest only (simplification mirroring index.html)
    # - SALT deduction is capped at salt_cap and includes property tax + state income tax
    # - CA/state savings: deductible interest + state exemption only (no property tax on state return)
    federal_rate = federal_tax_rate_percent / 100.0
    state_rate = state_tax_rate_percent / 100.0

    annual_property_tax = home_price * (property_tax_rate_percent / 100.0)
    annual_interest_first_year = annual_mortgage_interest_first_year(loan_amount, interest_rate, loan_term_years)

    deductible_interest = deductible_mortgage_interest(
        loan_amount=loan_amount,
        annual_rate_percent=interest_rate,
        loan_term_years=loan_term_years,
        interest_paid_in_year=annual_interest_first_year,
        mortgage_interest_loan_cap=mortgage_interest_cap,
    )

    salt_deductible = min(annual_property_tax + state_income_tax_annual, salt_cap)

    federal_savings_annual = (deductible_interest + salt_deductible) * federal_rate
    state_savings_annual = (deductible_interest + state_exemption_annual) * state_rate
    tax_break_annual = federal_savings_annual + state_savings_annual
    tax_break_monthly = tax_break_annual / 12.0

    net_monthly_cost = max(0.0, total_monthly - tax_break_monthly)
    net_annual_cost = max(0.0, total_annual - tax_break_annual)

    return {
        "downPaymentAmount": down_payment_amount,
        "loanAmount": loan_amount,
        "principalInterestMonthly": principal_interest_monthly,
        "propertyTaxMonthly": property_tax_monthly,
        "insuranceMonthly": insurance_monthly,
        "maintenanceMonthly": maintenance_monthly,
        "totalMonthly": total_monthly,
        "totalAnnual": total_annual,
        "taxBreakAnnual": tax_break_annual,
        "taxBreakMonthly": tax_break_monthly,
        "federalSavingsAnnual": federal_savings_annual,
        "stateSavingsAnnual": state_savings_annual,
        "saltDeductibleAnnual": salt_deductible,
        "deductibleInterestAnnual": deductible_interest,
        "netMonthlyCost": net_monthly_cost,
        "netAnnualCost": net_annual_cost,
    }

