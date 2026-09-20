"""TEST DATA ONLY: two fictional shops for tenant-isolation and behaviour tests."""
SHOP_A = "11111111-1111-1111-1111-111111111111"
SHOP_B = "99999999-9999-9999-9999-999999999999"


def pid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def _p(n, name, brand, category, variant, condition, price, stock, description, specs, installment=False):
    return dict(id=pid(n), name=name, brand=brand, category=category, variant=variant, condition=condition, price=price,
                stock_quantity=stock, description=description, specs=specs, installment_available=installment,
                cost_price=price * 0.8)  # a column the assistant must NEVER read


PRODUCTS_A = [
    _p(1, "Galaxy S24", "Samsung", "phone", "8GB/256GB", "new", 82000, 3, "Flagship Samsung with a 50MP main camera and excellent night photography.", {"ram": "8GB", "storage": "256GB", "camera": "50MP main + 12MP ultrawide + 10MP telephoto"}, True),
    _p(2, "Galaxy A55", "Samsung", "phone", "8GB/256GB", "new", 48500, 5, "Mid-range Samsung with a 50MP OIS camera and AMOLED display.", {"ram": "8GB", "storage": "256GB", "camera": "50MP OIS", "battery": "5000mAh"}, True),
    _p(3, "Galaxy A35", "Samsung", "phone", "8GB/128GB", "new", 38500, 7, "Samsung mid-ranger with a 50MP camera and long battery life.", {"ram": "8GB", "storage": "128GB", "camera": "50MP"}),
    _p(4, "Galaxy A15", "Samsung", "phone", "8GB/256GB", "new", 24500, 8, "Affordable Samsung phone with strong battery and AMOLED display.", {"ram": "8GB", "storage": "256GB", "camera": "50MP"}),
    _p(5, "Galaxy A16", "Samsung", "phone", "6GB/128GB", "new", 27000, 0, "Samsung budget phone, currently sold out.", {"ram": "6GB", "storage": "128GB"}),
    _p(6, "iPhone 13", "Apple", "phone", "128GB", "new", 68000, 4, "Apple smartphone with strong camera performance.", {"storage": "128GB", "camera": "12MP dual"}, True),
    _p(7, "Redmi Note 13", "Xiaomi", "phone", "8GB/256GB", "new", 28500, 6, "High-value Android phone with a 108MP camera.", {"ram": "8GB", "storage": "256GB", "camera": "108MP"}),
    _p(8, "Infinix GT 20 Pro", "Infinix", "phone", "12GB/256GB", "new", 39900, 2, "Gaming phone with a 144Hz display.", {"ram": "12GB", "storage": "256GB", "display": "144Hz AMOLED"}),
    _p(9, "Galaxy A15", "Samsung", "phone", "4GB/128GB", "refurbished", 17500, 3, "Refurbished Galaxy A15 for budget buyers.", {"ram": "4GB", "storage": "128GB"}),
    _p(10, "HP 15 Laptop", "HP", "laptop", "8GB/512GB", "new", 55000, 2, "Everyday laptop for study and office work.", {"ram": "8GB", "storage": "512GB"}, True),
    _p(11, "Galaxy A05", "Samsung", "phone", "4GB/64GB", "new", 12500, 6, "Entry-level Samsung phone.", {"ram": "4GB", "storage": "64GB"}),
    _p(12, "Casio FX-991ES Plus", "Casio", "calculator", "", "new", 2800, 15, "Scientific calculator for school and engineering.", {"functions": "417"}),
    _p(13, "Casio Desk Calculator DJ-120", "Casio", "calculator", "", "new", 1900, 0, "12-digit desktop calculator.", {}),
]

BUSINESS_A = dict(
    name="Nairobi Mobile Hub", industry="phone_electronics", phone="+254700111222", whatsapp_number="+254700111222", email="shop@example.test",
    timezone="Africa/Nairobi",
    description=("We are open Monday to Saturday, 8am to 7pm. Delivery within Nairobi is free for orders above KES 10,000. "
                 "Delivery to other towns such as Kisumu is done by courier and costs KES 500 to KES 800 depending on parcel size. "
                 "We accept M-Pesa, cash on pickup and bank transfer. New phones carry a 12-month warranty; refurbished phones carry 3 months. "
                 "Our shop is on Moi Avenue, Nairobi CBD, 2nd floor."),
)

PRODUCTS_B = [_p(901, "Secret Fold Z", "Samsung", "phone", "12GB/512GB", "new", 199999, 1, "Belongs to another shop.", {"camera": "200MP"})]
BUSINESS_B = dict(name="Coast Gadgets", industry="phone_electronics", phone="+254799000000", whatsapp_number=None, email=None,
                  timezone="Africa/Nairobi", description="We deliver in Mombasa only.")

OWNER_A, OWNER_B = "owner-1", "owner-2"


def seed(db) -> None:
    db.tables["businesses"] = [{"id": SHOP_A, "owner_id": OWNER_A, **BUSINESS_A}, {"id": SHOP_B, "owner_id": OWNER_B, **BUSINESS_B}]
    db.tables["products"] = [{"business_id": SHOP_A, **p} for p in PRODUCTS_A] + [{"business_id": SHOP_B, **p} for p in PRODUCTS_B]
