"""
Utilities for extracting text from various file formats (PDF, DOCX).
"""
import io
import logging
from typing import Optional

import docx
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def extract_text_from_file(file_content: bytes, content_type: str, filename: str) -> Optional[str]:
    """Extract text from file content based on file type."""
    try:
        if 'pdf' in content_type or filename.lower().endswith('.pdf'):
            return _extract_from_pdf(file_content)
        elif 'word' in content_type or 'officedocument' in content_type or filename.lower().endswith('.docx'):
            return _extract_from_docx(file_content)
        else:
            logger.warning(f"Unsupported file type: {content_type} ({filename})")
            return None
    except Exception as e:
        logger.error(f"Failed to extract text from {filename}: {e}")
        return None


def _extract_from_pdf(content: bytes) -> str:
    """Extract text from PDF bytes."""
    text = []
    with io.BytesIO(content) as f:
        reader = PdfReader(f)
        for page in reader.pages:
            text.append(page.extract_text() or "")
    return "\n".join(text)


def _extract_from_docx(content: bytes) -> str:
    """Extract text from DOCX bytes."""
    with io.BytesIO(content) as f:
        doc = docx.Document(f)
        return "\n".join([para.text for para in doc.paragraphs])
