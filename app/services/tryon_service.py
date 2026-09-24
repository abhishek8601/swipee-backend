import os
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
import httpx
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.ai_model import AiModel, ProductTryOn
from app.models.product import Product, ProductImage
from app.models.taxonomy import AttributeValue

class TryOnService:
    @staticmethod
    def get_output_dir() -> Path:
        output_dir = settings.STORAGE_DIR / "try-ons"
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    @staticmethod
    async def process_try_on(db: Session, try_on_id: int):
        try_on = db.query(ProductTryOn).filter(ProductTryOn.id == try_on_id).first()
        if not try_on:
            return

        try_on.status = "processing"
        db.commit()

        start_time = time.time()

        try:
            model = try_on.ai_model
            product = try_on.product
            colour = try_on.colour_value.label if try_on.colour_value else ""

            # Build prompt
            gender_word = "man" if model.gender == "male" else ("woman" if model.gender == "female" else "person")
            prompt = f"Editorial fashion studio photograph of an Indian {gender_word}, wearing {colour} {product.name}, clean solid studio background, 8k, photorealistic"

            # Execute driver
            driver = settings.TRYON_DRIVER.lower()

            filename = f"tryon_{try_on.id}_{int(time.time())}.jpg"
            dest_path = TryOnService.get_output_dir() / filename

            if driver == "pollinations":
                encoded_prompt = urllib.parse.quote(prompt)
                url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=768&height=1024&nologo=true"
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    with open(dest_path, "wb") as f:
                        f.write(resp.content)
                try_on.is_placeholder = True
                try_on.provider = "pollinations"
            else:
                # Stub / fallback: generate a clean preview canvas
                img = Image.new("RGB", (768, 1024), color=(240, 240, 245))
                draw = ImageDraw.Draw(img)
                draw.rectangle([(50, 50), (718, 974)], outline=(200, 200, 210), width=3)
                draw.text((100, 480), f"Try-On Preview\n{model.name}\n{product.name} ({colour})", fill=(50, 50, 60))
                img.save(dest_path, "JPEG")
                try_on.is_placeholder = True
                try_on.provider = "stub"

            elapsed_ms = int((time.time() - start_time) * 1000)

            try_on.status = "completed"
            try_on.result_path = f"try-ons/{filename}"
            try_on.thumb_path = f"try-ons/{filename}"
            try_on.latency_ms = elapsed_ms
            try_on.prompt_used = prompt
            db.commit()

        except Exception as e:
            db.rollback()
            try_on = db.query(ProductTryOn).filter(ProductTryOn.id == try_on_id).first()
            if try_on:
                try_on.status = "failed"
                try_on.error_message = str(e)
                db.commit()
