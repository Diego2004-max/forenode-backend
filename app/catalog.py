from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    code: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Product:
    code: str
    name: str


REGIONS = {
    item.code: item
    for item in (
        Region("pasto", "Pasto", 1.2136, -77.2811),
        Region("ipiales", "Ipiales", 0.8248, -77.5846),
        Region("tuquerres", "Túquerres", 1.0844, -77.6236),
        Region("la-union", "La Unión", 1.6058, -77.1331),
        Region("buesaco", "Buesaco", 1.3703, -77.1583),
    )
}

PRODUCTS = {
    item.code: item
    for item in (
        Product("coffee-arabica", "Café de altura arábigo"),
        Product("papa-pastusa", "Papa Pastusa"),
        Product("lulo-andino", "Lulo andino"),
        Product("quinoa-real", "Quinoa real de Nariño"),
    )
}

