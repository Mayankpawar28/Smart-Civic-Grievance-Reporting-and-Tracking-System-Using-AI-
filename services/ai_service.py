
from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer('all-MiniLM-L6-v2')

def is_duplicate(new_complaint, existing_complaints):
    new_embedding = model.encode(new_complaint, convert_to_tensor=True)
    for complaint in existing_complaints:
        existing_embedding = model.encode(complaint, convert_to_tensor=True)
        similarity = util.cos_sim(new_embedding, existing_embedding)
        if similarity > 0.85:
            return True
    return False

def is_valid_complaint(text):
    if len(text.strip()) < 10:
        return False
    spam_words = ["asdf", "test", "1234"]
    for word in spam_words:
        if word in text.lower():
            return False
    return True

def summarize_complaint(text):
    return text[:100] + "..." if len(text) > 100 else text

def classify_complaint(text):
    text = text.lower()
    if "road" in text:
        return "Road"
    elif "water" in text:
        return "Water"
    elif "electricity" in text:
        return "Electricity"
    elif "garbage" in text:
        return "Garbage"
    else:
        return "Other"
