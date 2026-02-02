# Data Profiling Microservice

A **scalable, asynchronous data profiling microservice** built using Python that analyzes database tables and generates statistical insights such as schema details, null distributions, uniqueness, and column-level metrics.
The service uses **RabbitMQ** and background workers to handle profiling tasks efficiently without blocking the API.

> Designed as a **production-style backend system** demonstrating microservice architecture, async processing, and clean separation of concerns.

---

## 📌 Table of Contents

* [Overview](#-overview)
* [Architecture](#-architecture)
* [Features](#-features)
* [Tech Stack](#-tech-stack)
* [Project Structure](#-project-structure)
* [Setup & Installation](#-setup--installation)
* [Running the Services](#-running-the-services)
* [API Endpoints](#-api-endpoints)
* [Example Requests](#-example-requests)
* [Configuration](#-configuration)
* [Design Decisions](#-design-decisions)
* [Future Enhancements](#-future-enhancements)

---

## Overview

This microservice allows clients to submit **data profiling requests** for database tables via a REST API.
Requests are processed **asynchronously** using RabbitMQ and worker processes to ensure scalability and responsiveness.

The system is suitable for:

* Data quality analysis
* Schema exploration
* Pre-analytics validation
* Integration into ETL / analytics pipelines

---

## Architecture

```
Client
  │
  │  POST /profiles
  ▼
API Service (FastAPI)
  │
  │  Publish job
  ▼
RabbitMQ (Message Broker)
  │
  │  Consume job
  ▼
Worker Service
  │
  │  Run profiling logic
  ▼
Profiling Engine
  │
  ▼
Result Store / API Response
```

### Key Ideas

* **API layer** is lightweight and non-blocking
* **Workers** handle CPU / IO heavy profiling tasks
* **Message queue** decouples producers and consumers
* Optional **AI enrichment** can be enabled per request

---

## Features

* Table-level data profiling
* Column statistics (null count, uniqueness, distributions)
* Schema analysis
* Asynchronous job execution
* Background workers using RabbitMQ
* Request tracking via unique request IDs
* Optional AI-based enrichment (toggleable)
* Clean REST API design

---

## Tech Stack

* **Language:** Python
* **API Framework:** FastAPI
* **Messaging:** RabbitMQ
* **Workers:** Python background consumers
* **Data Access:** PostrgreSQL
* **Environment:** Virtualenv

---

## Project Structure

```
data-profiling-microservice/
│
├── app/
│   ├── api/
│   │   ├── main.py            # FastAPI entry point
│   │   ├── dependencies.py
│   │   └── models.py
│   │
│   ├── core/
│   │   ├── table_profiler.py
│   │   ├── schema_profiler.py
│   │   ├── statistics_profiler.py
│   │   └── ai_enrichment.py
│   │
│   ├── worker/
│   │   ├── worker.py
│   │   ├── rabbitmq_connection.py
│   │   ├── job_store.py
│   │   └── models.py
│   │
│   └── requirements.txt
│
├── test_postgres.py
├── .gitignore
└── README.md
```

This structure clearly separates:

* API logic
* Core profiling logic
* Worker & messaging logic

---

## Setup & Installation

### 1️. Clone the repository

```bash
git clone https://github.com/arya-bhakte/data-profiling-microservice.git
cd data-profiling-microservice
```

### 2️. Create and activate virtual environment

```bash
python -m venv venv
source venv/bin/activate      # Linux / macOS
venv\Scripts\activate         # Windows
```

### 3️. Install dependencies

```bash
pip install -r app/requirements.txt
```

---

## Running the Services

### Start RabbitMQ

You can run RabbitMQ locally or using Docker.

```bash
docker run -d --hostname rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  rabbitmq:3-management
```

### Start API Service

```bash
uvicorn app.api.main:app --reload
```

### Start Worker Service

```bash
python app/worker/worker.py
```

---

## API Endpoints

| Method | Endpoint                 | Description                    |
| ------ | ------------------------ | ------------------------------ |
| POST   | `/profiles`              | Submit a profiling request     |
| GET    | `/profiles/{request_id}` | Fetch profiling status/results |
| GET    | `/health`                | Health check                   |

---

## 📌 Example Requests

### Submit profiling request

```bash
curl -X POST http://localhost:8000/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "table_name": "users",
    "enable_ai_enrichment": false
  }'
```

### Get profiling result

```bash
curl http://localhost:8000/profiles/{request_id}
```

---

## Configuration

Configuration is handled via environment variables:

```
RABBITMQ_URL=
DATABASE_URL=
LOG_LEVEL=
```

(Values are loaded securely and excluded from version control.)

---

## Design Decisions

* **Asynchronous architecture** to avoid blocking API threads
* **Message queue** for reliability and scalability
* **Worker isolation** for heavy computation
* **Toggleable AI enrichment** to control cost and performance
* **Clean module separation** for maintainability

---

## Future Enhancements

* Persist results in PostgreSQL
* Support for multiple data sources
* Horizontal worker scaling
* Metrics & monitoring 


