# Card Marketplace Listing Optimizer

A Streamlit web app for comparing TCGPlayer Direct versus Manapool listing outcomes and generating a clean Excel workbook with optimized listing sheets.

## What the app does

- Uploads a TCGPlayer CSV export.
- Uploads a TCGPlayer Direct fee structure file in CSV or XLSX format.
- Calculates Manapool net using editable fees and shipping inputs.
- Uses the Direct fee table as the source of truth for Direct net returns.
- Finds the lowest Direct price that can meet or beat Manapool net.
- Applies the Direct bump cap and the $3.00-$3.40 pricing cliff rule.
- Produces a new workbook with:
  - `Manapool Sheet`
  - `TCGPlayer Direct Sheet`
  - `Analysis`
  - `Errors`

## Project files

- `app.py`: Streamlit UI, password gate, uploads, dashboard, previews, download flow.
- `pricing_logic.py`: CSV parsing, fee table handling, pricing calculations, sheet assignment logic, analysis summary.
- `workbook_writer.py`: Excel workbook generation and formatting.
- `test_pricing_logic.py`: Small automated tests for the pricing engine.
- `.streamlit/config.toml`: Streamlit app configuration.
- `Dockerfile`: Container deployment support.

## Required input files

### 1. TCGPlayer CSV export

The app detects fields by header name instead of column letter. It expects the CSV to include headers matching these fields:

- `TCGplayer Id`
- `Product Line`
- `Set Name`
- `Product Name` or `Title`
- `TCG Market Price`
- `TCG Direct Low`
- `TCG Low Price`
- `Total Quantity`

Optional fields that are used when present:

- `Add to Quantity`
- `Number`
- `Rarity`
- `Condition`

### 2. TCGPlayer Direct fee structure

- Can be `.csv` or `.xlsx`
- Column A must contain Direct listing price
- Column J must contain Direct net return after fees

The fee table is the source of truth for Direct net lookups.

## Local run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Password protection

Optional app password protection is supported.

If `APP_PASSWORD` is set, the app requires a password before use.

### Local environment example

PowerShell:

```powershell
$env:APP_PASSWORD="your-password"
streamlit run app.py
```

### Streamlit Community Cloud

Set `APP_PASSWORD` in app secrets if you want the app locked down:

```toml
APP_PASSWORD="your-password"
```

If `APP_PASSWORD` is not set, the app stays open-access.

## Testing

Run the small pricing logic test suite:

```bash
pytest
```

The tests cover:

- Manapool net calculation
- Manapool $0.25 minimum enforcement
- Direct fee lookup using the closest fee-table price less than or equal to the proposed listing price
- Required Direct Price search
- Direct bump % calculation
- Sheet assignment using the 20% bump rule
- The $3.00-$3.40 Direct cliff rule
- Missing data rows going to the Errors sheet

## Streamlit Community Cloud deployment

1. Push this project to a GitHub repository.
2. In Streamlit Community Cloud, create a new app from that repo.
3. Set the main file path to `app.py`.
4. Optionally add `APP_PASSWORD` to Streamlit secrets.
5. Deploy.

## Docker deployment

### Build the image

```bash
docker build -t card-marketplace-listing-optimizer .
```

### Run the container

```bash
docker run --rm -p 8501:8501 card-marketplace-listing-optimizer
```

### Run with password protection

```bash
docker run --rm -p 8501:8501 -e APP_PASSWORD=your-password card-marketplace-listing-optimizer
```

The app will be available at [http://localhost:8501](http://localhost:8501).

## Render deployment

You can deploy this project on Render either as a Docker service or a Python web service.

### Option 1: Docker service

1. Push the repo to GitHub.
2. Create a new Web Service in Render.
3. Choose the repository.
4. Select Docker as the environment.
5. Render will build from the included `Dockerfile`.
6. Optionally set the `APP_PASSWORD` environment variable.

### Option 2: Python web service

Use:

- Build command:

```bash
pip install -r requirements.txt
```

- Start command:

```bash
streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
```

## Railway / Fly.io notes

The included Dockerfile also works well for Railway, Fly.io, and similar platforms that support container deployment.

## Workbook behavior

- Uploaded files are processed in memory.
- A brand-new workbook is generated on every run.
- Original uploads are never overwritten or mutated.
- Invalid rows are added to the `Errors` sheet instead of crashing the app.
- Valid rows continue processing even when some rows fail.

## Workbook formatting

The generated workbook includes:

- Frozen header rows
- Bold headers
- Auto-sized columns
- Filters on all sheets
- Currency formatting
- Percentage formatting
- Alphabetical sorting by `Product Name`
- Highlighting for Manapool minimum-price rows
- Highlighting for bump-limit exceptions
- Highlighting for Direct cliff-affected rows

## Pricing notes

- Manapool price defaults to `max(TCG Low Price, 0.25)`, or `TCG Market Price` when `TCG Low Price` is blank.
- Direct base price defaults to `max(TCG Market Price, TCG Direct Low)`.
- Direct net uses the nearest fee-table listing price less than or equal to the proposed Direct price.
- The app searches the fee table for the lowest Direct listing price whose Direct net meets or beats Manapool net.
- If the required Direct bump exceeds the allowed maximum, the card is assigned to Manapool.
- If the initial Direct target falls inside the low-price cliff range, the app tries the pre-cliff price first, then the next price above the cliff.
