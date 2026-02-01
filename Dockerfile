FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install other dependencies from requirements.txt
RUN pip install -r requirements.txt

# Expose default port
EXPOSE 8000

# Command to run FastAPI app (PORT/WORKERS can be overridden by env)
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS:-3} --no-proxy-headers"]
