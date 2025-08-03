FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first and install
COPY requirements.txt .

RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

# Copy source files into container
COPY . .

# Run bot
CMD ["python3", "src/main.py"]

