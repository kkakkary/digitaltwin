# Analysis notebooks

Python / Jupyter notebooks for analyzing the digital-twin BigQuery data.

## One-time setup

```bash
# from the repo root
python -m venv .venv && source .venv/bin/activate      # or reuse the existing venv
pip install -r notebooks/requirements.txt

# authenticate BigQuery for the Python client (opens a browser)
gcloud auth application-default login
```

## Run

```bash
cd notebooks
jupyter lab        # or: jupyter notebook
```

Open **`glucose_hrv_analysis.ipynb`** and run the cells top to bottom.

## Notebooks

| Notebook | What it does |
|---|---|
| `glucose_hrv_analysis.ipynb` | Pulls glucose + overnight HRV for one subject, interpolates HRV onto the dense glucose timeline (see `queries/glucose_hrv_interpolated.sql`), and plots/relates the two. |

Change the subject by editing the `USER` variable at the top of the notebook
(`vincent`, `kevin`, or `christian`).

> Note: Garmin HRV is measured only during sleep, so daytime HRV values in the
> joined table are interpolated across overnight gaps — treat them as bridged,
> not as real waking HRV.
