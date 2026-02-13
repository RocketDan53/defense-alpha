# Defense Alpha Intelligence Engine

A defense-focused intelligence platform that creates proprietary datasets by integrating DoD procurement data, startup funding flows, and operational military context.

## Overview

Defense Alpha aggregates and analyzes data from multiple sources to identify:
- Emerging defense technology startups
- Funding patterns (VC rounds, SBIR/STTR awards)
- DoD contract awards and procurement trends
- Investment signals and market indicators

## Project Structure

```
defense-alpha/
├── scrapers/          # Data collection modules
├── processing/        # Entity resolution & data cleaning
├── intelligence/      # Signal detection & analysis
├── api/              # Query interface (future)
├── data/             # Database storage
├── config/           # Configuration
├── scripts/          # Utility scripts
├── tests/            # Tests
├── alembic/          # Database migrations
└── requirements.txt
```

## Setup

### Prerequisites
- Python 3.11+
- SQLite (development) / PostgreSQL (production)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd defense-alpha
```

2. Create and activate virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your API keys and settings
```

5. Initialize the database:
```bash
alembic upgrade head
```

## Database Schema

### Core Tables

- **entities**: Companies, agencies, and investors with entity resolution
- **funding_events**: VC rounds, SBIR awards, acquisitions
- **contracts**: DoD and federal contract awards
- **signals**: Detected intelligence signals

### Entity Types
- `startup`: Defense technology startups
- `prime`: Prime defense contractors
- `investor`: VC firms and investors
- `agency`: Government agencies

## Usage

```python
from processing.database import SessionLocal, init_db
from processing.models import Entity, EntityType

# Initialize database
init_db()

# Create a session
db = SessionLocal()

# Query entities
startups = db.query(Entity).filter(Entity.entity_type == EntityType.STARTUP).all()
```

## Data Sources

- USAspending.gov - Federal contract data
- SAM.gov - Entity registration and contracts
- SBIR.gov - SBIR/STTR awards
- Crunchbase - Startup funding data
- SEC EDGAR - Investment filings

## Development

### Running Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## License

Proprietary - All rights reserved
