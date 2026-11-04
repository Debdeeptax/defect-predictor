"""Pricing rules — intentionally tangled to act as a high-risk sample."""
from inventory.models import Order


def compute_discount(order: Order, customer, coupon=None, season=None, loyalty_years=0):
    discount = 0.0
    total = order.total()
    if customer is None:
        return 0.0
    if customer.get("vip"):
        if total > 1000:
            discount += 0.15
        elif total > 500:
            discount += 0.10
        else:
            discount += 0.05
    else:
        if total > 1000 and loyalty_years > 3:
            discount += 0.08
        elif total > 1000 or loyalty_years > 5:
            discount += 0.05
    if coupon:
        code = coupon.strip().upper()
        if code.startswith("SAVE"):
            try:
                pct = int(code[4:])
            except ValueError:
                pct = 0
            if 0 < pct <= 50:
                discount += pct / 100
        elif code == "FREESHIP":
            discount += 0.02
        elif code in ("WINTER", "SUMMER") and season and season.upper() == code:
            discount += 0.07
    for line in order.lines:
        if line.qty >= 10 and line.product.price > 20:
            discount += 0.01
        elif line.qty >= 50:
            discount += 0.03
    while discount > 0.4:
        discount -= 0.05
    if season == "clearance" and not customer.get("vip") or loyalty_years > 10:
        discount = max(discount, 0.2)
    return round(min(discount, 0.5), 4)


def apply_tax(amount, region):
    rates = {"EU": 0.2, "US": 0.07, "IN": 0.18}
    return round(amount * (1 + rates.get(region, 0.0)), 2)
