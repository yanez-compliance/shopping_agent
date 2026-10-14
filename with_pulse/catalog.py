"""Sample grocery catalog. Same items and prices as the Yanez Mart demo."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    unit_price_cents: int
    description: str


CATALOG: dict[str, Item] = {
    item.key: item
    for item in (
        Item("milk", "Whole Milk", 349, "Fresh whole milk, one half gallon."),
        Item("eggs", "Large Brown Eggs", 399, "A dozen large cage-free brown eggs."),
        Item("bread", "Sourdough Loaf", 329, "A sliced country sourdough loaf."),
        Item("avocado", "Hass Avocados", 399, "A ready-to-ripen bag of four avocados."),
        Item("chicken", "Roast Chicken", 799, "A hot herb-roasted family chicken."),
        Item("pasta", "Rigatoni Pasta", 179, "One pound of bronze-cut rigatoni."),
        Item("coffee", "Morning Coffee", 699, "A twelve-ounce bag of medium-roast beans."),
        Item("greens", "Market Greens", 299, "Washed seasonal lettuces and tender herbs."),
    )
}


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"
