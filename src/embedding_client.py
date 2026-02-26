"""
Client for generating text embeddings using OpenAI.
"""
import os
import logging
from typing import List
from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Wrapper for OpenAI embedding API."""

    def __init__(self, model: str = "text-embedding-3-small"):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not set. Embeddings will not be generated.")
            self.client = None
        else:
            self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def generate_embedding(self, text: str) -> List[float]:
        """Generate vector embedding for a single text string."""
        if not self.client:
            return []
        try:
            text = text.replace("\n", " ")
            response = self.client.embeddings.create(input=[text], model=self.model)
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return []
