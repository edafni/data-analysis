# Data Overview Analyzer

A small Streamlit app that lets you upload a **CSV** or **Excel** file and
instantly get a full overview of its contents:

- Basic shape, memory footprint, duplicate/missing counts
- Per-column dtypes, null %, unique counts, **auto-generated descriptions**
- **Type-mismatch validations** based on column names — e.g. a `date`
  column with non-date values or still stored as text, an `email` column
  with invalid emails, a `phone` column with bad digit counts, numeric
  columns that contain text
- **Special-character detection** — flags currency symbols (`$ € £ ¥ ₪`),
  percent signs, thousand-separator commas, and stray symbols that need
  cleaning
- **Pattern-consistency detection** — catches the "99% look like `9-99999`
  but 1% look like `9999999`" case
- Data quality checks — empty / constant columns, leading or trailing
  whitespace, inconsistent casing (`"USA"` vs `"usa"`), IQR outliers
- Per-column statistics for numeric, text, and datetime columns
- Data preview (first 10 rows)

## Project layout

```
data-analysis/
├── app.py                    # Streamlit entry point
├── analyzer.py               # Pure-python analysis helpers
├── requirements.txt
├── .gitignore
├── .streamlit/
│   └── config.toml           # Upload size + theme
└── README.md
```

## Install

It is recommended to use a virtual environment.

```bash
cd data-analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally

```bash
streamlit run app.py
```

Streamlit will open the app in your browser at
[http://localhost:8501](http://localhost:8501). Drag a CSV or XLSX file
into the uploader and explore the tabs.

## How the validations work

Column names are inspected for hints:

| Column name contains          | Expected type      | Check                                               |
|-------------------------------|--------------------|-----------------------------------------------------|
| `date`, `time`, `timestamp`   | date / datetime    | `pd.to_datetime` must succeed **and** dtype must actually be datetime |
| `email`, `mail`               | email              | regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`                  |
| `phone`, `mobile`, `tel`      | phone              | 7–15 digits after stripping non-digits              |
| `price`, `amount`, `qty`, `count`, `age`, `id`, `total`, `sum`, `salary` | numeric | `pd.to_numeric` must succeed |
| *(any object column)*         | numeric (inferred) | flagged if ≥80% of values parse as numbers          |

Additionally, every text column is scanned for:

- **Suspicious characters** — `$`, `€`, `£`, `¥`, `₪`, `%`, thousand-separator
  commas, and `*`/`#`/`@` — reported in the *Special characters* subsection.
- **Pattern anomalies** — a "shape signature" is built for every value
  (digits → `9`, letters → `A`, punctuation preserved). When one pattern
  covers ≥ 90% of values, the rare odd ones are flagged.

Each flagged column appears in the **Validations** tab with the number
of bad values, a percentage, and example offending values with their
row indices.

## Deploy publicly (Streamlit Community Cloud — free)

Streamlit Community Cloud hosts the app for free and gives you a permanent
public URL. You only need a GitHub account.

### One-time setup

1. **Initialize git and commit the project:**

   ```bash
   cd /Users/dafni/AI/data-analysis
   git init
   git add .
   git commit -m "Initial data overview analyzer"
   ```

2. **Create a new public repository on GitHub.** Go to
   [github.com/new](https://github.com/new), name it something like
   `data-analysis`, leave it empty (no README), and create it.

3. **Push your local project to that repo.** GitHub will show you the
   exact commands; they look like:

   ```bash
   git branch -M main
   git remote add origin https://github.com/<your-username>/data-analysis.git
   git push -u origin main
   ```

4. **Deploy on Streamlit Community Cloud:**
   - Go to [share.streamlit.io](https://share.streamlit.io) and sign in
     with your GitHub account.
   - Click **New app**.
   - Pick your `data-analysis` repo, branch `main`, main file `app.py`.
   - Click **Deploy**. In ~1 minute you'll get a public URL like
     `https://<your-username>-data-analysis.streamlit.app`.

### Updating the deployed app

Any time you change code locally:

```bash
git add .
git commit -m "Describe your change"
git push
```

Streamlit Cloud automatically re-deploys from the latest commit.

### Notes

- The repo must be **public** for the free Streamlit Cloud tier.
- Keep any secrets out of the repo — use the Streamlit Cloud **Secrets**
  UI if you later add API keys.
- Max upload size is controlled by `.streamlit/config.toml`
  (`maxUploadSize = 200` MB).
