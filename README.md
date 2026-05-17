# Card Marketplace Listing Optimizer

A Streamlit web app for comparing TCGPlayer Direct versus Manapool listing outcomes and generating a clean Excel workbook with optimized listing sheets.

## What the app does

- Uploads a TCGPlayer CSV export.
- Pulls live Mana Pool card prices from the official Mana Pool API.
- Calculates Manapool net using editable fees and shipping inputs.
- Uses the built-in TCGPlayer Direct fee formula for Direct net returns.
- Finds the lowest Direct price that can meet or beat Manapool net.
- Applies the Direct bump cap.
- Produces a new workbook with:
  - `Manapool Sheet`
  - `TCGPlayer Direct Sheet`
  - `Analysis`
  - `Errors`
- Produces separate upload-ready CSV downloads for:
  - Manapool
  - TCGPlayer Direct

## Current TCGPlayer Direct fee formula

- Less than `$2.50`: Direct net is `50%` of item value
- Greater than or equal to `$2.50`: Direct fees are:
  - `$1.12`
  - `8.95%` marketplace commission
  - `2.5%` credit card processing fee

That means for cards at or above `$2.50`:

- `Direct Net = Listing Price - (1.12 + Listing Price x 0.0895 + Listing Price x 0.025)`

## Mana Pool pricing source

The app uses the official Mana Pool API as its primary Manapool price source.

- It searches Mana Pool by card name in batches.
- It matches returned cards by `Product Name`, `Set Name`, and `Number` when available.
- It uses `from_price_cents` from the API response as the Mana Pool comparison price.
- If Mana Pool does not return a usable match for a row, the app falls back to TCG pricing for that row.

## Project files

- `app.py`: Streamlit UI, password gate, uploads, dashboard, previews, and download flow.
- `pricing_logic.py`: CSV parsing, Mana Pool API lookup, pricing calculations, sheet assignment logic, analysis summary, and upload-ready CSV shaping.
- `workbook_writer.py`: Excel workbook generation and formatting.
- `test_pricing_logic.py`: Small automated tests for the pricing engine.
- `.streamlit/config.toml`: Streamlit app configuration.
- `Dockerfile`: Container deployment support.

## Required input file

### TCGPlayer CSV export

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

- `TCG Marketplace Price`
- `Add to Quantity`
- `Number`
- `Rarity`
- `Condition`

## Mana Pool API secrets

For live Mana Pool pricing in Streamlit Community Cloud, add these secrets:

```toml
MANAPOOL_EMAIL="your-manapool-email@example.com"
MANAPOOL_API_KEY="your-manapool-access-token"
```

If those secrets are not available or the API does not return a usable match, the app will continue with TCG fallback pricing instead of crashing.

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
- New Direct net calculation below `$2.50`
- New Direct net calculation at or above `$2.50`
- Required Direct Price search
- Direct bump % calculation
- Sheet assignment using the bump rule
- Missing required columns going to the Errors sheet
- Missing data rows going to the Errors sheet

## Streamlit Community Cloud deployment

1. Push this project to a GitHub repository.
2. In Streamlit Community Cloud, create a new app from that repo.
3. Set the main file path to `app.py`.
4. Add `MANAPOOL_EMAIL` and `MANAPOOL_API_KEY` to Streamlit secrets for live Mana Pool pricing.
5. Optionally add `APP_PASSWORD` to Streamlit secrets.
6. Deploy.

## Docker deployment

### Build the image

```bash
docker build -t card-marketplace-listing-optimizer .
```

### Run the container

```bash
docker run --rm -p 8501:8501 card-marketplace-listing-optimizer
```

### Run with secrets

```bash
docker run --rm -p 8501:8501 \
  -e MANAPOOL_EMAIL=your-manapool-email@example.com \
  -e MANAPOOL_API_KEY=your-manapool-access-token \
  -e APP_PASSWORD=your-password \
  card-marketplace-listing-optimizer
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
6. Optionally set the `APP_PASSWORD`, `MANAPOOL_EMAIL`, and `MANAPOOL_API_KEY` environment variables.

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
- Results stay on-screen after generation, including after download clicks.

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

## Pricing notes

- Manapool price uses the Mana Pool API price first, then falls back to `TCG Low Price`, or `TCG Market Price` when `TCG Low Price` is blank.
- Direct base price defaults to `max(TCG Market Price, TCG Direct Low)`.
- Direct net uses the built-in fee formula instead of a fee-table workbook.
- The app searches for the lowest Direct listing price whose Direct net meets or beats Manapool net.
- If the required Direct bump exceeds the allowed maximum, the card is assigned to Manapool.
- Separate upload-ready CSV downloads are available for Manapool and TCGPlayer Direct.
