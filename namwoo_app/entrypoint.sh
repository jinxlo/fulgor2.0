#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Database Health Check ---
# Use environment variables passed from docker-compose for reliability
host="$POSTGRES_HOST"
port="$POSTGRES_PORT"
user="$POSTGRES_USER"
password="$POSTGRES_PASSWORD"

echo "Waiting for database at $host:$port..."

# Export the password so pg_isready can use it automatically
export PGPASSWORD="$password"

# Wait until the database is accepting connections
until pg_isready -h "$host" -p "$port" -U "$user"; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

# Unset the password variable for security once we're done with it
unset PGPASSWORD

>&2 echo "Postgres is up - executing commands"

# --- Run Data Population Scripts ---
echo "Running database population scripts..."
python initial_data_scripts/populate_batteries.py
python initial_data_scripts/populate_vehicle_configurations.py
python initial_data_scripts/populate_battery_to_vehicle_links.py
echo "Database population complete."

# --- Execute the main command (passed from Dockerfile's CMD) ---
exec "$@"