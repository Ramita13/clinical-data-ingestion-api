# Running the MDA API with Docker

No Python or PostgreSQL installation needed. Docker handles everything.

---

## Step 1 — Install Docker Desktop

Download from: https://www.docker.com/products/docker-desktop

Install and start Docker Desktop. Wait for it to show "Docker is running" in the system tray.

---

## Step 2 — Get the code

If you have Git installed:
```cmd
git clone https://github.com/Ramita13/clinical-data-ingestion-api.git
cd clinical-data-ingestion-api
```

Or download the ZIP from GitHub → Code → Download ZIP, then extract it.

---

## Step 3 — Start the system

Open Command Prompt, navigate to the project folder, and run:

```cmd
docker-compose up
```

The first time this runs it will download and build everything — takes 2-5 minutes.
You will see log output from both the database and the API starting up.

When you see this line, it is ready:
```
mda_api  | INFO: Application startup complete.
```

---

## Step 4 — Use the API

Open your browser and go to:

```
http://localhost:8000/docs
```

You will see the interactive API documentation where you can upload files and run queries.

---

## Stopping the system

Press `Ctrl+C` in the terminal where docker-compose is running.

To start again later:
```cmd
docker-compose up
```

Your data is preserved between restarts.

---

## Troubleshooting

**Port 5432 already in use:**
You have PostgreSQL installed locally. Either stop your local PostgreSQL service,
or change the port in docker-compose.yml from "5432:5432" to "5433:5432".

**Port 8000 already in use:**
Change "8000:8000" to "8001:8000" in docker-compose.yml and access via http://localhost:8001/docs

**Starting fresh (wipe all data):**
```cmd
docker-compose down -v
docker-compose up
```
