"""Small supervised dataset used to train Intelispark's local intent model.

This is intentionally domain-specific: Kenyan commerce, electronics and WhatsApp sales.
The dataset is version-controlled so it can grow as real conversations are collected.
"""

TRAINING_EXAMPLES = [
    ("hi", "greeting"), ("hello", "greeting"), ("habari", "greeting"),
    ("mambo", "greeting"), ("good morning", "greeting"), ("hey there", "greeting"),
    ("how much is the phone", "price"), ("bei ya samsung", "price"),
    ("what is the price", "price"), ("how much does it cost", "price"),
    ("hii ni ngapi", "price"), ("is there a discount", "price"),
    ("do you have this phone", "availability"), ("is it in stock", "availability"),
    ("iko stock", "availability"), ("mna iphone 13", "availability"),
    ("is the samsung available", "availability"), ("do you still have it", "availability"),
    ("i want to buy it", "purchase"), ("i will take the phone", "purchase"),
    ("nataka kununua", "purchase"), ("place an order", "purchase"),
    ("how can i order", "purchase"), ("send me one", "purchase"),
    ("which phone has the best camera", "recommendation"),
    ("recommend a good samsung", "recommendation"), ("what do you recommend", "recommendation"),
    ("which one is better", "recommendation"), ("help me choose a phone", "recommendation"),
    ("best phone under 30000", "recommendation"),
    ("compare iphone and samsung", "comparison"), ("compare these phones", "comparison"),
    ("which is better between a15 and redmi", "comparison"),
    ("difference between these two", "comparison"), ("compare the cameras", "comparison"),
    ("can i pay in installments", "installment"), ("do you offer lipa polepole", "installment"),
    ("can i pay monthly", "installment"), ("is installment available", "installment"),
    ("i want a phone on installments", "installment"),
    ("where are you located", "location"), ("where is your shop", "location"),
    ("shop location", "location"), ("mko wapi", "location"),
    ("where can i collect it", "location"),
    ("can you deliver", "delivery"), ("do you deliver", "delivery"),
    ("delivery to kisumu", "delivery"), ("how much is delivery", "delivery"),
    ("can you send it to me", "delivery"),
    ("book an appointment", "appointment"), ("can i visit the shop", "appointment"),
    ("i want to come tomorrow", "appointment"),
    ("thank you", "thanks"), ("asante", "thanks"), ("thanks for your help", "thanks"),
    ("i have a question", "general"), ("tell me more", "general"),
    ("i need help", "general"), ("what do you sell", "general"),
]
