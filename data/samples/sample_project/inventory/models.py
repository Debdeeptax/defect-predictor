"""Inventory domain model (sample code for the defect-prediction demo)."""
from dataclasses import dataclass, field
from datetime import date


class Entity:
    def __init__(self, ident):
        self.ident = ident

    def __eq__(self, other):
        return isinstance(other, Entity) and other.ident == self.ident

    def __hash__(self):
        return hash(self.ident)


class Product(Entity):
    def __init__(self, ident, name, price, stock=0):
        super().__init__(ident)
        self.name = name
        self.price = price
        self.stock = stock

    def is_available(self, qty=1):
        return self.stock >= qty

    def restock(self, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self.stock += qty


class PerishableProduct(Product):
    def __init__(self, ident, name, price, expires: date, stock=0):
        super().__init__(ident, name, price, stock)
        self.expires = expires

    def is_available(self, qty=1, today=None):
        today = today or date.today()
        return super().is_available(qty) and self.expires > today


@dataclass
class OrderLine:
    product: Product
    qty: int

    def total(self):
        return self.product.price * self.qty


@dataclass
class Order:
    ident: str
    lines: list = field(default_factory=list)

    def add(self, product, qty):
        if not product.is_available(qty):
            raise ValueError(f"{product.name} unavailable")
        self.lines.append(OrderLine(product, qty))

    def total(self):
        return sum(line.total() for line in self.lines)
