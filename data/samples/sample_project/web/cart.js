// Shopping cart helpers (sample JavaScript file).
export function cartTotal(items) {
  let total = 0;
  for (const item of items) {
    if (item.qty > 0 && item.price >= 0) {
      total += item.qty * item.price;
    }
  }
  return total;
}

export function formatPrice(value, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);
}
