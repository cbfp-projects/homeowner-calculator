import math
import unittest

from calculator_logic import (
    SALT_CAP_2026_PLUS,
    MORTGAGE_INTEREST_LOAN_CAP,
    annual_mortgage_interest_first_year,
    build_amortization_series,
    compute_costs_and_tax_break,
    deductible_mortgage_interest,
    year_interest,
)


def assert_close(testcase: unittest.TestCase, a: float, b: float, *, rel: float = 1e-6, abs_tol: float = 1e-2):
    testcase.assertTrue(
        math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol),
        msg=f"Expected {a} ~= {b}",
    )


class TestMortgageMath(unittest.TestCase):
    def test_zero_interest_monthly_payment(self):
        principal = 100_000.0
        payment = compute_costs_and_tax_break(
            {
                "homePrice": 100_000.0,
                "downPaymentPercent": 0.0,
                "interestRate": 0.0,
                "loanTermYears": 1,
                "propertyTaxRate": 0.0,
                "homeInsurance": 0.0,
                "pmi": 0.0,
                "hoa": 0.0,
                "utilities": 0.0,
                "internet": 0.0,
                "maintenanceRate": 0.0,
                "landscaping": 0.0,
                "other": 0.0,
                "federalTaxRate": 0.0,
                "stateTaxRate": 0.0,
            }
        )["principalInterestMonthly"]
        self.assert_close_approx = self.assertTrue
        # For 0% rate, monthly = principal / 12
        assert_close(self, payment, principal / 12.0, rel=0, abs_tol=1e-9)

    def test_amortization_invariant_interest_plus_principal_equals_payment(self):
        principal = 1_050_000.0
        rate = 6.14
        years = 30
        series = build_amortization_series(principal, rate, years)
        interest_series = series["interestSeries"]
        principal_series = series["principalSeries"]
        monthly_payment = series["monthlyPayment"]

        for i in [0, 1, 6, 12, 60, 180, 359]:
            assert_close(self, interest_series[i] + principal_series[i], monthly_payment, rel=1e-9, abs_tol=1e-2)

        # Ending balance should be very close to 0 (floating error tolerance)
        self.assertLess(abs(series["endingBalance"]), 5.0)

    def test_first_year_interest_matches_sum(self):
        principal = 900_000.0
        rate = 5.0
        years = 30
        first_year_interest = annual_mortgage_interest_first_year(principal, rate, years)
        series = build_amortization_series(principal, rate, years)
        interest_series = series["interestSeries"]
        assert_close(self, first_year_interest, sum(interest_series[:12]), rel=1e-9, abs_tol=1e-2)


class TestTaxBreakMath(unittest.TestCase):
    def base_inputs(self, **overrides):
        """
        Baseline scenario: CA-like values, focusing on math invariants.
        """
        inputs = {
            "homePrice": 1_400_000.0,
            "downPaymentPercent": 25.0,  # loan = 1.05M
            "interestRate": 6.0,
            "loanTermYears": 30,
            "propertyTaxRate": 1.2,  # ~16.8k annual prop tax
            "homeInsurance": 12_000.0,
            "pmi": 0.0,
            "hoa": 0.0,
            "utilities": 800.0,
            "internet": 200.0,
            "maintenanceRate": 1.0,
            "landscaping": 100.0,
            "other": 0.0,
            "federalTaxRate": 32.0,
            "stateTaxRate": 9.3,
            "stateIncomeTax": 35_000.0,
            "stateExemption": 900.0,
        }
        inputs.update(overrides)
        return inputs

    def test_mortgage_interest_cap_scaling(self):
        rate = 6.0
        years = 30

        # Loan below cap: deductibleInterest == first-year interest
        loan_below = 700_000.0
        first_year = annual_mortgage_interest_first_year(loan_below, rate, years)
        deductible = deductible_mortgage_interest(
            loan_amount=loan_below,
            annual_rate_percent=rate,
            loan_term_years=years,
            interest_paid_in_year=first_year,
            mortgage_interest_loan_cap=MORTGAGE_INTEREST_LOAN_CAP,
        )
        assert_close(self, deductible, first_year, rel=1e-9, abs_tol=1e-2)

        # Loan above cap: deductibleInterest scales by cap/loan
        loan_above = 1_050_000.0
        first_year_above = annual_mortgage_interest_first_year(loan_above, rate, years)
        deductible_above = deductible_mortgage_interest(
            loan_amount=loan_above,
            annual_rate_percent=rate,
            loan_term_years=years,
            interest_paid_in_year=first_year_above,
            mortgage_interest_loan_cap=MORTGAGE_INTEREST_LOAN_CAP,
        )
        expected = first_year_above * (MORTGAGE_INTEREST_LOAN_CAP / loan_above)
        assert_close(self, deductible_above, expected, rel=1e-9, abs_tol=1e-2)

    def test_salt_cap_applies_to_property_plus_state_income(self):
        # Case 1: below cap => deductible equals sum
        prop_tax = 20_000.0
        state_income = SALT_CAP_2026_PLUS - prop_tax - 1000.0  # still below cap
        # Convert propertyTaxRate so annual property tax matches prop_tax for this home price
        home_price = 1_400_000.0
        property_tax_rate = (prop_tax / home_price) * 100.0

        r = compute_costs_and_tax_break(
            {
                **self.base_inputs(),
                "homePrice": home_price,
                "propertyTaxRate": property_tax_rate,
                "stateIncomeTax": state_income,
            }
        )
        self.assertLessEqual(r["saltDeductibleAnnual"], SALT_CAP_2026_PLUS + 1e-6)
        self.assertAlmostEqual(r["saltDeductibleAnnual"], prop_tax + state_income, delta=1e-1)

        # Case 2: above cap => deductible equals cap
        r2 = compute_costs_and_tax_break(
            {
                **self.base_inputs(),
                "propertyTaxRate": property_tax_rate,
                "stateIncomeTax": 200_000.0,  # push above cap
            }
        )
        self.assertAlmostEqual(r2["saltDeductibleAnnual"], SALT_CAP_2026_PLUS, delta=1e-6)

    def test_tax_break_total_is_federal_plus_state(self):
        r = compute_costs_and_tax_break(self.base_inputs())
        assert_close(self, r["taxBreakAnnual"], r["federalSavingsAnnual"] + r["stateSavingsAnnual"], rel=1e-9, abs_tol=1e-2)

    def test_state_savings_does_not_use_property_tax_amount(self):
        # Changing property tax rate should not affect state savings in this model,
        # because state savings uses only (deductibleInterest + stateExemption).
        r1 = compute_costs_and_tax_break(self.base_inputs(propertyTaxRate=0.8))
        r2 = compute_costs_and_tax_break(self.base_inputs(propertyTaxRate=2.0))
        assert_close(self, r1["stateSavingsAnnual"], r2["stateSavingsAnnual"], rel=1e-9, abs_tol=1e-2)

    @unittest.expectedFailure
    def test_tax_break_should_use_interest_paid_in_year_not_first_year(self):
        """
        Known gap in the current model:
        - tax break calculation uses first-year interest only.
        This test assumes it should use year-2 interest instead.
        """
        inputs = self.base_inputs()
        home_price = inputs["homePrice"]
        down_amount = home_price * (inputs["downPaymentPercent"] / 100.0)
        loan_amount = home_price - down_amount

        # Compute deductible interest for year 2 using amortization schedule
        rate = inputs["interestRate"]
        years = inputs["loanTermYears"]
        interest_year2 = year_interest(loan_amount, rate, years, year_index_1_based=2)
        deductible_year2 = deductible_mortgage_interest(
            loan_amount=loan_amount,
            annual_rate_percent=rate,
            loan_term_years=years,
            interest_paid_in_year=interest_year2,
            mortgage_interest_loan_cap=MORTGAGE_INTEREST_LOAN_CAP,
        )

        # SALT is modeled as constant annual property tax + state income tax (no growth here)
        annual_prop_tax = home_price * (inputs["propertyTaxRate"] / 100.0)
        salt_deductible = min(annual_prop_tax + inputs["stateIncomeTax"], SALT_CAP_2026_PLUS)

        federal_rate = inputs["federalTaxRate"] / 100.0
        state_rate = inputs["stateTaxRate"] / 100.0

        federal_savings_year2 = (deductible_year2 + salt_deductible) * federal_rate
        state_savings_year2 = (deductible_year2 + inputs["stateExemption"]) * state_rate
        tax_break_year2 = federal_savings_year2 + state_savings_year2

        # Current model result (first-year interest)
        r = compute_costs_and_tax_break(inputs)

        # This assertion should fail because current model uses first-year interest.
        assert_close(self, r["taxBreakAnnual"], tax_break_year2, rel=1e-6, abs_tol=1e-2)


if __name__ == "__main__":
    unittest.main()

