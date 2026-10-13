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
    def still_inputs(try_on: ProductTryOn) -> dict:
        """Plain values render_still needs, read while the session is open."""
        return {
            "try_on_id": try_on.id,
            "model_name": try_on.ai_model.name,
            "model_gender": try_on.ai_model.gender,
            "product_name": try_on.product.name,
            "colour": try_on.colour_value.label if try_on.colour_value else "",
        }

    @staticmethod
    async def render_still(inputs: dict, scene: str = "clean solid studio background") -> dict:
        """Render the model-wearing-product image with TRYON_DRIVER.

        Takes plain values, not ORM objects, so callers can commit before this
        network call instead of holding a transaction open across it.
        """
        colour = inputs["colour"]

        # Build prompt
        gender_word = "man" if inputs["model_gender"] == "male" else ("woman" if inputs["model_gender"] == "female" else "person")
        prompt = f"Editorial fashion studio photograph of an Indian {gender_word}, wearing {colour} {inputs['product_name']}, {scene}, 8k, photorealistic"

        # Execute driver
        driver = settings.TRYON_DRIVER.lower()

        filename = f"tryon_{inputs['try_on_id']}_{int(time.time())}.jpg"
        dest_path = TryOnService.get_output_dir() / filename

        if driver == "pollinations":
            encoded_prompt = urllib.parse.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=768&height=1024&nologo=true"
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
            provider = "pollinations"
        else:
            # Stub / fallback: generate a clean preview canvas
            img = Image.new("RGB", (768, 1024), color=(240, 240, 245))
            draw = ImageDraw.Draw(img)
            draw.rectangle([(50, 50), (718, 974)], outline=(200, 200, 210), width=3)
            draw.text((100, 480), f"Try-On Preview\n{inputs['model_name']}\n{inputs['product_name']} ({colour})", fill=(50, 50, 60))
            img.save(dest_path, "JPEG")
            provider = "stub"

        # Both drivers are placeholders: neither uses the merchant's garment image.
        return {"path": f"try-ons/{filename}", "provider": provider, "is_placeholder": True, "prompt": prompt}

    @staticmethod
    async def process_try_on(db: Session, try_on_id: int):
        try_on = db.query(ProductTryOn).filter(ProductTryOn.id == try_on_id).first()
        if not try_on:
            return

        try_on.status = "processing"
        inputs = TryOnService.still_inputs(try_on)
        db.commit()

        start_time = time.time()

        try:
            still = await TryOnService.render_still(inputs)

            elapsed_ms = int((time.time() - start_time) * 1000)

            try_on.status = "completed"
            try_on.result_path = still["path"]
            try_on.thumb_path = still["path"]
            try_on.provider = still["provider"]
            try_on.is_placeholder = still["is_placeholder"]
            try_on.latency_ms = elapsed_ms
            try_on.prompt_used = still["prompt"]
            db.commit()

        except Exception as e:
            db.rollback()
            try_on = db.query(ProductTryOn).filter(ProductTryOn.id == try_on_id).first()
            if try_on:
                try_on.status = "failed"
                try_on.error_message = str(e)
                db.commit()
