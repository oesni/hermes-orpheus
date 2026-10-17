"""Review fixture: totals >= 10_000 cents receive a 10% discount.

Inputs are nonnegative integer cents. Below the threshold, no discount applies.
The result is an integer number of cents, rounded down after discounting.
"""

def discounted_total(total_cents: int) -> int:
    if total_cents > 10_000:
        return total_cents * 90 // 100
    return total_cents
