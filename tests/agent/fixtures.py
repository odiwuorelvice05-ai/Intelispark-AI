"""TEST DATA ONLY. Two fictional shops for tenant-isolation and agent tests."""
from __future__ import annotations

from app.agent.repository import InMemoryStore

SHOP_A = "11111111-1111-1111-1111-111111111111"
SHOP_B = "99999999-9999-9999-9999-999999999999"


def _id(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


PRODUCTS_A = [
    dict(id=_id(1), name="Galaxy S24", brand="Samsung", category="phone", variant="8GB/256GB", condition="new", price=82000, stock_quantity=3,
         description="Flagship Samsung with a 50MP main camera and excellent night photography.", specs={"ram": "8GB", "storage": "256GB", "camera": "50MP main + 12MP ultrawide + 10MP telephoto", "battery": "4000mAh"}, installment_available=True),
    dict(id=_id(2), name="Galaxy A55", brand="Samsung", category="phone", variant="8GB/256GB", condition="new", price=48500, stock_quantity=5,
         description="Mid-range Samsung with a 50MP OIS camera, AMOLED display and premium build.", specs={"ram": "8GB", "storage": "256GB", "camera": "50MP OIS", "battery": "5000mAh"}, installment_available=True),
    dict(id=_id(3), name="Galaxy A35", brand="Samsung", category="phone", variant="8GB/128GB", condition="new", price=38500, stock_quantity=7,
         description="Samsung mid-ranger with a 50MP camera and long battery life.", specs={"ram": "8GB", "storage": "128GB", "camera": "50MP", "battery": "5000mAh"}, installment_available=False),
    dict(id=_id(4), name="Galaxy A15", brand="Samsung", category="phone", variant="8GB/256GB", condition="new", price=24500, stock_quantity=8,
         description="Affordable Samsung phone with strong battery and AMOLED display.", specs={"ram": "8GB", "storage": "256GB", "camera": "50MP", "battery": "5000mAh"}, installment_available=False),
    dict(id=_id(5), name="Galaxy A16", brand="Samsung", category="phone", variant="6GB/128GB", condition="new", price=27000, stock_quantity=0,
         description="Samsung budget phone, currently sold out.", specs={"ram": "6GB", "storage": "128GB"}, installment_available=False),
    dict(id=_id(6), name="iPhone 13", brand="Apple", category="phone", variant="128GB", condition="new", price=68000, stock_quantity=4,
         description="Apple smartphone with strong camera performance.", specs={"storage": "128GB", "camera": "12MP dual"}, installment_available=True),
    dict(id=_id(7), name="Redmi Note 13", brand="Xiaomi", category="phone", variant="8GB/256GB", condition="new", price=28500, stock_quantity=6,
         description="High-value Android phone with a 108MP camera.", specs={"ram": "8GB", "storage": "256GB", "camera": "108MP"}, installment_available=False),
    dict(id=_id(8), name="Infinix GT 20 Pro", brand="Infinix", category="phone", variant="12GB/256GB", condition="new", price=39900, stock_quantity=2,
         description="Gaming phone with Dimensity 8200 chip and 144Hz display.", specs={"ram": "12GB", "storage": "256GB", "display": "144Hz AMOLED"}, installment_available=False),
    dict(id=_id(9), name="Tecno Pova 6 Pro", brand="Tecno", category="phone", variant="8GB/256GB", condition="new", price=36500, stock_quantity=4,
         description="Gaming-oriented phone with big battery and 120Hz display.", specs={"ram": "8GB", "storage": "256GB", "battery": "6000mAh"}, installment_available=False),
    dict(id=_id(10), name="Nokia C32", brand="Nokia", category="phone", variant="4GB/128GB", condition="new", price=14500, stock_quantity=10,
         description="Budget phone for customers prioritising affordability.", specs={"ram": "4GB", "storage": "128GB"}, installment_available=False),
    dict(id=_id(11), name="Galaxy A15", brand="Samsung", category="phone", variant="4GB/128GB", condition="refurbished", price=17500, stock_quantity=3,
         description="Refurbished Galaxy A15 for budget buyers.", specs={"ram": "4GB", "storage": "128GB"}, installment_available=False),
    dict(id=_id(12), name="HP 15 Laptop", brand="HP", category="laptop", variant="8GB/512GB", condition="new", price=55000, stock_quantity=2,
         description="Everyday laptop for study and office work.", specs={"ram": "8GB", "storage": "512GB"}, installment_available=True),
]

BUSINESS_A = dict(
    name="Nairobi Mobile Hub", industry="phone_electronics", phone="+254700111222", whatsapp_number="+254700111222", email="shop@example.test", timezone="Africa/Nairobi",
    description=("We are open Monday to Saturday, 8am to 7pm. Delivery within Nairobi is free for orders above KES 10,000. "
                 "Delivery to other towns such as Kisumu is done by courier and costs KES 500 to KES 800 depending on parcel size. "
                 "We accept M-Pesa, cash on pickup and bank transfer. New phones carry a 12-month warranty; refurbished phones carry 3 months. "
                 "Our shop is on Moi Avenue, Nairobi CBD, 2nd floor."),
)

PRODUCTS_B = [dict(id=_id(901), name="Secret Fold Z", brand="Samsung", category="phone", variant="12GB/512GB", condition="new", price=199999, stock_quantity=1,
                   description="Belongs to another shop.", specs={"camera": "200MP"}, installment_available=False)]
BUSINESS_B = dict(name="Coast Gadgets", industry="phone_electronics", phone="+254799000000", whatsapp_number=None, email=None, timezone="Africa/Nairobi", description="We deliver in Mombasa only.")

CONV = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def make_store() -> InMemoryStore:
    store = InMemoryStore()
    store.add_business(SHOP_A, BUSINESS_A, PRODUCTS_A)
    store.add_business(SHOP_B, BUSINESS_B, PRODUCTS_B)
    return store
