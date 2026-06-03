import math
import unittest

from calculator_logic import (
    SALT_CAP_2026_PLUS,
    MORTGAGE_INTEREST_LOAN_CAP,
    annual_mortgage_interest_first_year,
    annual_step_growth_factor,
    build_amortization_series,
    compute_annual_tax_savings,
    compute_cost_over_time_series,
    compute_costs_and_tax_break,
    deductible_mortgage_interest,
    signed_cost_over_time_display,
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


class TestCostOverTimeSeries(unittest.TestCase):
    def _series_kwargs(self, **overrides):
        base = {
            "loan_amount": 900_000.0,
            "annual_rate_percent": 6.0,
            "years": 30,
            "home_price": 1_000_000.0,
            "property_tax_monthly": 1000.0,
            "insurance_monthly": 200.0,
            "pmi_monthly": 150.0,
            "hoa_monthly": 0.0,
            "utilities_monthly": 300.0,
            "internet_monthly": 100.0,
            "maintenance_monthly": 500.0,
            "landscaping_monthly": 50.0,
            "other_monthly": 0.0,
            "non_mortgage_growth": 0.0,
            "cumulative": False,
        }
        base.update(overrides)
        return base

    def test_month_one_total_matches_headline_total_monthly(self):
        home_price = 1_000_000.0
        down_pct = 10.0
        loan_amount = home_price * (1 - down_pct / 100.0)
        r = compute_costs_and_tax_break(
            {
                "homePrice": home_price,
                "downPaymentPercent": down_pct,
                "interestRate": 6.0,
                "loanTermYears": 30,
                "propertyTaxRate": 1.2,
                "homeInsurance": 2400.0,
                "pmi": 150.0,
                "hoa": 0.0,
                "utilities": 300.0,
                "internet": 100.0,
                "maintenanceRate": 0.6,
                "landscaping": 50.0,
                "other": 0.0,
                "federalTaxRate": 0.0,
                "stateTaxRate": 0.0,
            }
        )
        series = compute_cost_over_time_series(
            loan_amount,
            6.0,
            30,
            home_price,
            property_tax_monthly=r["propertyTaxMonthly"],
            insurance_monthly=r["insuranceMonthly"],
            pmi_monthly=150.0,
            hoa_monthly=0.0,
            utilities_monthly=300.0,
            internet_monthly=100.0,
            maintenance_monthly=r["maintenanceMonthly"],
            landscaping_monthly=50.0,
            other_monthly=0.0,
            non_mortgage_growth=0.0,
        )
        assert_close(self, series["totalSeries"][0], r["totalMonthly"], rel=1e-9, abs_tol=1e-2)

    def test_pmi_drops_when_balance_at_or_below_80_percent_ltv(self):
        home_price = 1_000_000.0
        loan_amount = 900_000.0
        series = compute_cost_over_time_series(**self._series_kwargs())
        other = series["otherSeries"]
        # PMI active at start
        self.assertGreater(other[0], 1000.0 + 200.0 + 300.0 + 100.0 + 500.0 + 50.0)
        # Eventually PMI goes away (other drops by pmi amount)
        pmi_active = [v for v in other if v > 2150.0]
        pmi_inactive = [v for v in other if v <= 2150.0 + 1e-6]
        self.assertTrue(len(pmi_active) > 0)
        self.assertTrue(len(pmi_inactive) > 0)
        # Last month has no PMI component
        assert_close(self, other[-1], 1000.0 + 200.0 + 300.0 + 100.0 + 500.0 + 50.0, rel=1e-9, abs_tol=1e-2)

    def test_non_mortgage_growth_increases_other_over_time(self):
        s0 = compute_cost_over_time_series(**self._series_kwargs(non_mortgage_growth=0.0, pmi_monthly=0.0))
        s3 = compute_cost_over_time_series(**self._series_kwargs(non_mortgage_growth=0.03, pmi_monthly=0.0))
        assert_close(self, s3["otherSeries"][0], s0["otherSeries"][0], rel=1e-9, abs_tol=1e-2)
        self.assertGreater(s3["otherSeries"][60], s0["otherSeries"][60])

    def test_cumulative_mode_running_totals(self):
        monthly = compute_cost_over_time_series(**self._series_kwargs(cumulative=False, pmi_monthly=0.0))
        cumulative = compute_cost_over_time_series(**self._series_kwargs(cumulative=True, pmi_monthly=0.0))
        assert_close(
            self,
            cumulative["totalSeries"][11],
            sum(monthly["totalSeries"][:12]),
            rel=1e-9,
            abs_tol=1e-2,
        )

    def test_down_payment_only_in_cumulative_mode(self):
        down = 100_000.0
        monthly = compute_cost_over_time_series(**self._series_kwargs(down_payment_amount=down, cumulative=False))
        cumulative = compute_cost_over_time_series(**self._series_kwargs(down_payment_amount=down, cumulative=True))
        self.assertEqual(sum(monthly["downPaymentSeries"]), 0.0)
        self.assertAlmostEqual(cumulative["downPaymentSeries"][0], down)
        self.assertAlmostEqual(cumulative["downPaymentSeries"][-1], down)

    def test_signed_display_only_interest_and_other_are_negative(self):
        down = 100_000.0
        kw = self._series_kwargs(down_payment_amount=down)
        display = signed_cost_over_time_display(
            kw["loan_amount"],
            kw["annual_rate_percent"],
            kw["years"],
            kw["home_price"],
            down_payment_amount=down,
            property_tax_monthly=1000.0,
            insurance_monthly=200.0,
            pmi_monthly=150.0,
            hoa_monthly=0.0,
            utilities_monthly=300.0,
            internet_monthly=100.0,
            maintenance_monthly=500.0,
            landscaping_monthly=50.0,
            other_monthly=0.0,
        )
        for v in display["interestDisplay"]:
            self.assertLessEqual(v, 1e-6)
        for v in display["otherDisplay"]:
            self.assertLessEqual(v, 1e-6)
        for v in display["downPaymentDisplay"]:
            self.assertGreaterEqual(v, -1e-6)
        for v in display["principalDisplay"]:
            self.assertGreaterEqual(v, -1e-6)

    def test_annual_step_growth_jumps_at_year_boundary(self):
        s = compute_cost_over_time_series(**self._series_kwargs(non_mortgage_growth=0.12, pmi_monthly=0.0))
        other = s["otherSeries"]
        base = 1000.0 + 200.0 + 300.0 + 100.0 + 500.0 + 50.0
        assert_close(self, other[0], base, rel=1e-9, abs_tol=1e-2)
        assert_close(self, other[11], base, rel=1e-9, abs_tol=1e-2)
        assert_close(self, other[12], base * annual_step_growth_factor(1, 0.12), rel=1e-9, abs_tol=1e-2)

    def test_tax_benefit_reduces_net_when_enabled(self):
        kw = self._series_kwargs()
        display = signed_cost_over_time_display(
            kw["loan_amount"],
            kw["annual_rate_percent"],
            kw["years"],
            kw["home_price"],
            cumulative=False,
            include_tax_break=True,
            federal_tax_rate_percent=32.0,
            state_tax_rate_percent=9.3,
            state_income_tax_annual=35_000.0,
            state_exemption_annual=900.0,
            property_tax_rate_percent=1.2,
            property_tax_monthly=1000.0,
            insurance_monthly=200.0,
            pmi_monthly=0.0,
            hoa_monthly=0.0,
            utilities_monthly=0.0,
            internet_monthly=0.0,
            maintenance_monthly=0.0,
            landscaping_monthly=0.0,
            other_monthly=0.0,
        )
        gross = signed_cost_over_time_display(
            kw["loan_amount"],
            kw["annual_rate_percent"],
            kw["years"],
            kw["home_price"],
            cumulative=False,
            include_tax_break=False,
            property_tax_monthly=1000.0,
            insurance_monthly=200.0,
            pmi_monthly=0.0,
            hoa_monthly=0.0,
            utilities_monthly=0.0,
            internet_monthly=0.0,
            maintenance_monthly=0.0,
            landscaping_monthly=0.0,
            other_monthly=0.0,
        )
        self.assertGreater(display["taxBenefitDisplay"][0], 0.0)
        self.assertGreater(display["netDisplay"][0], gross["netDisplay"][0])

    def test_net_equals_equity_plus_costs(self):
        kw = self._series_kwargs(down_payment_amount=100_000.0)
        display = signed_cost_over_time_display(
            kw["loan_amount"],
            kw["annual_rate_percent"],
            kw["years"],
            kw["home_price"],
            down_payment_amount=100_000.0,
            property_tax_monthly=1000.0,
            insurance_monthly=200.0,
            pmi_monthly=0.0,
            hoa_monthly=0.0,
            utilities_monthly=0.0,
            internet_monthly=0.0,
            maintenance_monthly=0.0,
            landscaping_monthly=0.0,
            other_monthly=0.0,
        )
        for i in range(12):
            expected = (
                display["equityTopDisplay"][i]
                + display["interestDisplay"][i]
                + display["otherDisplay"][i]
                + display["taxBenefitDisplay"][i]
            )
            assert_close(self, display["netDisplay"][i], expected, rel=1e-9, abs_tol=1e-2)

    def test_twenty_percent_down_no_pmi_in_series(self):
        home_price = 1_000_000.0
        loan_amount = 800_000.0
        series = compute_cost_over_time_series(
            loan_amount,
            6.0,
            30,
            home_price,
            property_tax_monthly=1000.0,
            insurance_monthly=200.0,
            pmi_monthly=150.0,
            hoa_monthly=0.0,
            utilities_monthly=0.0,
            internet_monthly=0.0,
            maintenance_monthly=0.0,
            landscaping_monthly=0.0,
            other_monthly=0.0,
        )
        base_other = 1200.0
        for v in series["otherSeries"]:
            assert_close(self, v, base_other, rel=1e-9, abs_tol=1e-2)


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

    def test_chart_tax_uses_interest_paid_in_each_year(self):
        inputs = self.base_inputs()
        home_price = inputs["homePrice"]
        loan_amount = home_price * (1 - inputs["downPaymentPercent"] / 100.0)
        year2 = compute_annual_tax_savings(
            loan_amount,
            inputs["interestRate"],
            inputs["loanTermYears"],
            2,
            home_price=home_price,
            property_tax_rate_percent=inputs["propertyTaxRate"],
            federal_tax_rate_percent=inputs["federalTaxRate"],
            state_tax_rate_percent=inputs["stateTaxRate"],
            state_income_tax_annual=inputs["stateIncomeTax"],
            state_exemption_annual=inputs["stateExemption"],
        )
        series = compute_cost_over_time_series(
            loan_amount,
            inputs["interestRate"],
            inputs["loanTermYears"],
            home_price,
            property_tax_monthly=home_price * inputs["propertyTaxRate"] / 100 / 12,
            insurance_monthly=inputs["homeInsurance"] / 12,
            pmi_monthly=0.0,
            hoa_monthly=0.0,
            utilities_monthly=inputs["utilities"],
            internet_monthly=inputs["internet"],
            maintenance_monthly=home_price * inputs["maintenanceRate"] / 100 / 12,
            landscaping_monthly=inputs["landscaping"],
            other_monthly=0.0,
            include_tax_break=True,
            federal_tax_rate_percent=inputs["federalTaxRate"],
            state_tax_rate_percent=inputs["stateTaxRate"],
            state_income_tax_annual=inputs["stateIncomeTax"],
            state_exemption_annual=inputs["stateExemption"],
            property_tax_rate_percent=inputs["propertyTaxRate"],
        )
        assert_close(self, series["taxBenefitSeries"][12], year2["taxSavingsMonthly"], rel=1e-9, abs_tol=1e-2)
        self.assertLess(series["taxBenefitSeries"][24], series["taxBenefitSeries"][12])


if __name__ == "__main__":
    unittest.main()

