# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies for PDF processing and OCR
RUN apt-get update && apt-get install -y \
    # For pdftotext
    poppler-utils \
    # For OCR support with pdf2image
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    # Required for pdf2image
    poppler-utils \
    # Build dependencies
    gcc \
    python3-dev \
    # Cleanup to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata files first (for better caching)
COPY pyproject.toml ./

# Install pip-tools and the package


# Copy the source code
COPY src ./src

# RUN mkdir -p /usr/src/app/config

# COPY ddx ./ddx
# Copy config if it exists
COPY config ./config

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV LOG_LEVEL=INFO

# Create store directory for outputs
RUN mkdir -p /usr/src/app/store

# Expose the FastAPI port
EXPOSE 8000

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "ddx.api.main:app", "--host", "0.0.0.0", "--port", "8000"]