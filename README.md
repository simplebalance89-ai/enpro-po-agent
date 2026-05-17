# EnPro PO Agent

![CI](https://github.com/simplebalance89-ai/enpro-po-agent/actions/workflows/ci.yml/badge.svg?branch=master)

Ariba/Coupa PO automation agent that ingests purchase orders, matches them to P21 via crosswalk + confidence scoring, and exposes a review portal for human approval before CISM/SO export.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy environment template
cp .env.example .env

# 3. Start the server
uvicorn server:app --reload
```

Open `http://localhost:8000` for the review queue dashboard.

## Running tests

```bash
pytest test_end_to_end.py -x -q
```
