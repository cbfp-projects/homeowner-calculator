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
PMI_LTV_THRESHOLD = 0.80  # PMI while loan balance exceeds 80% of original home value


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


def annual_step_growth_factor(year_index_0_based: int, non_mortgage_growth: float) -> float:
    """Non-mortgage costs grow at year boundaries: (1+g)^year_index."""
    if year_index_0_based < 0:
        raise ValueError("year_index_0_based must be >= 0")
    return (1.0 + non_mortgage_growth) ** year_index_0_based


def compute_annual_tax_savings(
    loan_amount: float,
    annual_rate_percent: float,
    loan_term_years: int,
    year_index_1_based: int,
    *,
    home_price: float,
    property_tax_rate_percent: float,
    federal_tax_rate_percent: float,
    state_tax_rate_percent: float,
    state_income_tax_annual: float = 0.0,
    state_exemption_annual: float = 0.0,
    non_mortgage_growth: float = 0.0,
    salt_cap: float = SALT_CAP_2026_PLUS,
    mortgage_interest_cap: float = MORTGAGE_INTEREST_LOAN_CAP,
) -> Dict[str, float]:
    """
    Estimated itemized tax savings for a single calendar year of homeownership.
    Uses actual interest paid that year (not first-year only).
    """
    interest_paid = year_interest(
        loan_amount, annual_rate_percent, loan_term_years, year_index_1_based
    )
    deductible_interest = deductible_mortgage_interest(
        loan_amount=loan_amount,
        annual_rate_percent=annual_rate_percent,
        loan_term_years=loan_term_years,
        interest_paid_in_year=interest_paid,
        mortgage_interest_loan_cap=mortgage_interest_cap,
    )
    year_idx0 = year_index_1_based - 1
    annual_property_tax = (
        home_price
        * (property_tax_rate_percent / 100.0)
        * annual_step_growth_factor(year_idx0, non_mortgage_growth)
    )
    salt_deductible = min(annual_property_tax + state_income_tax_annual, salt_cap)
    federal_rate = federal_tax_rate_percent / 100.0
    state_rate = state_tax_rate_percent / 100.0
    federal_savings = (deductible_interest + salt_deductible) * federal_rate
    state_savings = (deductible_interest + state_exemption_annual) * state_rate
    tax_savings_annual = federal_savings + state_savings
    return {
        "interestPaidAnnual": interest_paid,
        "deductibleInterestAnnual": deductible_interest,
        "annualPropertyTax": annual_property_tax,
        "saltDeductibleAnnual": salt_deductible,
        "federalSavingsAnnual": federal_savings,
        "stateSavingsAnnual": state_savings,
        "taxSavingsAnnual": tax_savings_annual,
        "taxSavingsMonthly": tax_savings_annual / 12.0,
    }


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


def compute_cost_over_time_series(
    loan_amount: float,
    annual_rate_percent: float,
    years: int,
    home_price: float,
    *,
    property_tax_monthly: float,
    insurance_monthly: float,
    pmi_monthly: float,
    hoa_monthly: float,
    utilities_monthly: float,
    internet_monthly: float,
    maintenance_monthly: float,
    landscaping_monthly: float,
    other_monthly: float,
    non_mortgage_growth: float = 0.0,
    cumulative: bool = False,
    down_payment_amount: float = 0.0,
    include_tax_break: bool = False,
    federal_tax_rate_percent: float = 0.0,
    state_tax_rate_percent: float = 0.0,
    state_income_tax_annual: float = 0.0,
    state_exemption_annual: float = 0.0,
    property_tax_rate_percent: float = 0.0,
    salt_cap: float = SALT_CAP_2026_PLUS,
    mortgage_interest_cap: float = MORTGAGE_INTEREST_LOAN_CAP,
) -> Dict[str, object]:
    """
    Monthly series for the cost-over-time chart (gross, not after-tax).

    Returns positive magnitudes for equity (down payment, principal) and for cost
    components (interest, other). Use signed_cost_over_time_display() for chart signs.

    PMI is charged only while balance exceeds PMI_LTV_THRESHOLD * home_price.
    """
    series = build_amortization_series(loan_amount, annual_rate_percent, years)
    interest_series: List[float] = series["interestSeries"]  # type: ignore[assignment]
    principal_series: List[float] = series["principalSeries"]  # type: ignore[assignment]
    months = len(interest_series)

    base_without_pmi = (
        property_tax_monthly
        + insurance_monthly
        + hoa_monthly
        + utilities_monthly
        + internet_monthly
        + maintenance_monthly
        + landscaping_monthly
        + other_monthly
    )
    pmi_threshold_balance = home_price * PMI_LTV_THRESHOLD

    other_series: List[float] = []
    balance = loan_amount
    monthly_rate = (annual_rate_percent / 100.0) / 12.0
    payment = series["monthlyPayment"]

    tax_benefit_series: List[float] = [0.0] * months

    for idx in range(months):
        year_idx0 = idx // 12
        growth_factor = annual_step_growth_factor(year_idx0, non_mortgage_growth)
        pmi_this_month = pmi_monthly if balance > pmi_threshold_balance else 0.0
        other_series.append(base_without_pmi * growth_factor + pmi_this_month)

        if include_tax_break:
            year_1_based = year_idx0 + 1
            tax_benefit_series[idx] = compute_annual_tax_savings(
                loan_amount,
                annual_rate_percent,
                years,
                year_1_based,
                home_price=home_price,
                property_tax_rate_percent=property_tax_rate_percent,
                federal_tax_rate_percent=federal_tax_rate_percent,
                state_tax_rate_percent=state_tax_rate_percent,
                state_income_tax_annual=state_income_tax_annual,
                state_exemption_annual=state_exemption_annual,
                non_mortgage_growth=non_mortgage_growth,
                salt_cap=salt_cap,
                mortgage_interest_cap=mortgage_interest_cap,
            )["taxSavingsMonthly"]

        interest = balance * monthly_rate
        principal_paid = float(payment) - interest
        if principal_paid < 0:
            principal_paid = 0.0
        balance -= principal_paid

    total_series = [
        interest_series[i] + principal_series[i] + other_series[i] for i in range(months)
    ]

    if cumulative:

        def cum(arr: List[float]) -> List[float]:
            out: List[float] = []
            running = 0.0
            for v in arr:
                running += v
                out.append(running)
            return out

        principal_series = cum(principal_series)
        interest_series = cum(interest_series)
        other_series = cum(other_series)
        total_series = cum(total_series)
        if include_tax_break:
            tax_benefit_series = cum(tax_benefit_series)

    down_payment_series: List[float] = [0.0] * months
    if down_payment_amount > 0 and cumulative:
        down_payment_series = [down_payment_amount] * months

    return {
        "interestSeries": interest_series,
        "principalSeries": principal_series,
        "otherSeries": other_series,
        "downPaymentSeries": down_payment_series,
        "taxBenefitSeries": tax_benefit_series,
        "totalSeries": total_series,
        "monthlyPayment": series["monthlyPayment"],
        "months": months,
    }


def signed_cost_over_time_display(
    loan_amount: float,
    annual_rate_percent: float,
    years: int,
    home_price: float,
    *,
    down_payment_amount: float = 0.0,
    cumulative: bool = False,
    include_tax_break: bool = False,
    property_tax_rate_percent: float = 0.0,
    federal_tax_rate_percent: float = 0.0,
    state_tax_rate_percent: float = 0.0,
    state_income_tax_annual: float = 0.0,
    state_exemption_annual: float = 0.0,
    **monthly_costs: float,
) -> Dict[str, object]:
    """
    Chart-ready signed series: equity (down payment, principal) >= 0; costs <= 0.

    Negative values are only interest and other (tax, insurance, HOA, PMI, etc.).
    """
    raw = compute_cost_over_time_series(
        loan_amount,
        annual_rate_percent,
        years,
        home_price,
        cumulative=cumulative,
        down_payment_amount=down_payment_amount,
        include_tax_break=include_tax_break,
        property_tax_rate_percent=property_tax_rate_percent,
        federal_tax_rate_percent=federal_tax_rate_percent,
        state_tax_rate_percent=state_tax_rate_percent,
        state_income_tax_annual=state_income_tax_annual,
        state_exemption_annual=state_exemption_annual,
        **monthly_costs,
    )
    interest_display = [-v for v in raw["interestSeries"]]  # type: ignore[arg-type]
    other_display = [-v for v in raw["otherSeries"]]  # type: ignore[arg-type]
    down_display: List[float] = raw["downPaymentSeries"]  # type: ignore[assignment]
    principal_display: List[float] = raw["principalSeries"]  # type: ignore[assignment]
    tax_benefit_display: List[float] = raw.get("taxBenefitSeries", [0.0] * len(down_display))  # type: ignore[assignment]

    for v in interest_display + other_display:
        if v > 1e-6:
            raise ValueError("Cost components must be non-positive on the chart")
    for v in tax_benefit_display:
        if v < -1e-6:
            raise ValueError("Tax benefit must be non-negative on the chart")

    equity_top = [down_display[i] + principal_display[i] for i in range(len(down_display))]
    net_display = [
        equity_top[i] + interest_display[i] + other_display[i] + tax_benefit_display[i]
        for i in range(len(down_display))
    ]

    return {
        **raw,
        "downPaymentDisplay": down_display,
        "principalDisplay": principal_display,
        "interestDisplay": interest_display,
        "otherDisplay": other_display,
        "taxBenefitDisplay": tax_benefit_display,
        "equityTopDisplay": equity_top,
        "netDisplay": net_display,
    }


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

    # Tax break model (year 1): per-year interest, SALT cap, CA state rules
    tax_year1 = compute_annual_tax_savings(
        loan_amount,
        interest_rate,
        loan_term_years,
        1,
        home_price=home_price,
        property_tax_rate_percent=property_tax_rate_percent,
        federal_tax_rate_percent=federal_tax_rate_percent,
        state_tax_rate_percent=state_tax_rate_percent,
        state_income_tax_annual=state_income_tax_annual,
        state_exemption_annual=state_exemption_annual,
        non_mortgage_growth=0.0,
        salt_cap=salt_cap,
        mortgage_interest_cap=mortgage_interest_cap,
    )
    tax_break_annual = tax_year1["taxSavingsAnnual"]
    tax_break_monthly = tax_year1["taxSavingsMonthly"]
    federal_savings_annual = tax_year1["federalSavingsAnnual"]
    state_savings_annual = tax_year1["stateSavingsAnnual"]
    salt_deductible = tax_year1["saltDeductibleAnnual"]
    deductible_interest = tax_year1["deductibleInterestAnnual"]

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

