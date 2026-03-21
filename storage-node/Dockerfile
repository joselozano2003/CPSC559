# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port Flask runs on
EXPOSE 6000

# Command to run the app
CMD ["python", "-m", "flask", "--app", "app.app", "run", "--host=0.0.0.0", "--port=6000", "--debug"]