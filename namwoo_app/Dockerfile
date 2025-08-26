# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Install postgresql-client for pg_isready in the entrypoint script
RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /usr/src/app
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container
COPY . .

# Make the entrypoint script executable
RUN chmod +x /usr/src/app/entrypoint.sh

# Set the entrypoint script to be executed when the container starts
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]

# --- THIS IS THE FIX ---
# Define the default command to run when the container starts.
# Point to the 'app' object inside the '__init__.py' file.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "__init__:app"]