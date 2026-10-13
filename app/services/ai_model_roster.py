"""The platform's default AI model personas.

Every merchant draws from this one shared roster (ai_models has no merchant
column), so "five personas per merchant" means five active platform rows.
Provisioning is idempotent by slug: existing rows, including any admin edits
or uploaded poses, are never overwritten.
"""
from sqlalchemy.orm import Session
from app.models.ai_model import AiModel

DEFAULT_AI_MODELS = [
    # name, slug, gender, body_type, height, reference_size, description
    ("Arjun", "arjun", "male", "Athletic", "185 cm", "M", "Indian male model, fit build"),
    ("Meera", "meera", "female", "Slender", "172 cm", "S", "Indian female model, elegant look"),
    ("Kabir", "kabir", "male", "Average", "178 cm", "L", "Indian male model, casual lifestyle"),
    ("Ananya", "ananya", "female", "Petite", "165 cm", "XS", "Indian female model, vibrant modern style"),
    ("Kavya", "kavya", "female", "Curvy", "165 cm", "L", "Indian female model, curvy build. Best for ethnic and fusion wear"),
]

DEFAULT_SUPPORTED_CATEGORIES = ["men-t-shirts", "men-shirts", "sneakers"]


def ensure_default_ai_models(db: Session) -> list[AiModel]:
    """Create any missing default persona. Returns the rows it created."""
    created = []
    for order, (name, slug, gender, body, height, size, desc) in enumerate(DEFAULT_AI_MODELS):
        if db.query(AiModel).filter(AiModel.slug == slug).first():
            continue
        model = AiModel(
            name=name,
            slug=slug,
            gender=gender,
            body_type=body,
            height_cm=height,
            reference_size=size,
            description=desc,
            supported_categories=DEFAULT_SUPPORTED_CATEGORIES,
            is_active=True,
            sort_order=order,
        )
        db.add(model)
        created.append(model)
    db.flush()
    return created
