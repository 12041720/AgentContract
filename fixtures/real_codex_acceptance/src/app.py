"""Sample application for Codex acceptance scenario."""

def calculate_total(prices: list[float], tax_rate: float = 0.05) -> float:
    """Return the tax-inclusive sum of ``prices``, rounded to two decimals.

    Args:
        prices: Item prices to add together.
        tax_rate: Tax rate expressed as a decimal fraction.

    Returns:
        The total price after tax.
    """
    subtotal = sum(prices)
    return round(subtotal * (1 + tax_rate), 2)
