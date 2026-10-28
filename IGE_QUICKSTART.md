# IGE Climate Analyzer — reproducible research application

This is the integrated research application. It includes the existing EPW
analyzer and the historical/future generation routes. Python **3.12** is required.
No weather-provider account or API key is needed for the four saved examples.

## Install and start

Clone this research branch, then enter the repository directory:

```bash
git clone --depth 1 --single-branch --branch research/ige-i2-reproducible-app-20261028 https://github.com/dmitrievii/building-energy-tools.git
cd building-energy-tools
python ige.py setup
python ige.py run
```

On Windows, use `py -3.12` instead of `python`. On Linux, use `python3.12` if
`python` selects another version. No environment activation is necessary.

Open **http://127.0.0.1:8501**. On the climate source page, choose **Generate
climate**. The original **Upload EPW**, **Find climate**, and **GeoSphere Austria**
routes are also retained. The latter provider routes require internet access.

Setup creates a dedicated `.venv/ige` environment. It installs exact dependency
versions with SHA-256 checks, including transitive dependencies and build tools.
It does not change other Python installations. Setup needs internet once; the
saved example calculations then work without weather-provider requests.

## Four available examples

| In the interface | Result | How it is produced |
|---|---|---|
| Historical → Saved Graz 2023 pilot | Historical 2023, 8,760 hours | Rebuilt from the saved original ERA5-derived and POWER responses |
| Future → Graz / CanESM5 / SSP245 / 2040–2059 | Representative future year, 8,760 hours | Rebuilt using the 2023 hourly pattern and the separate 2002–2014 reference |
| Historical → Saved CH 2025 → Basel / Binningen | Historical research year, 8,760 hours | Loads the original verified station-temperature reconstruction |
| Historical → Saved CH 2025 → Altdorf | Historical research year, 8,760 hours | Loads the original verified station-temperature reconstruction |

Submit the form, then select **Explore this generated climate** to inspect the
result. Each route offers EPW, hourly data, a quality/provenance report and a
complete ZIP. Viewing charts does not request fresh weather data.

The historical **Coordinates — request provider data** option exists, but its
arbitrary-location live coverage and local accuracy are not qualified by the
offline examples. There is no general station interpolation or arbitrary-location
future generator in this milestone. The future selection remains the admitted
Graz pilot; unsupported scenarios are not substituted silently.

## Check the installation and export the examples

```bash
python ige.py doctor
python ige.py check
```

`doctor` checks exact dependency versions, dependency consistency and frozen
application/input hashes. `check` runs the combined application regressions,
exports all four examples, checks their original EPW hashes and complete ZIPs,
and starts a real local Streamlit server to check its health and page response.
AppTest exercises interface behavior; this is not a visual browser audit.
The acceptance suite excludes six V1/V2 acquisition/preregistration test modules
whose Git-history gates remain in their original research workflows. No research
test or result is modified. The application tests and relevant scientific
regressions are counted once by test ID.
The historical A1.2 exposure audit is checked against its frozen receipt; rebuilding
that audit from old Git objects remains a separate research-history task.
One legacy audit-wrapper overwrite test also requires Git history. The new I2
runtime separately tests refusal to overwrite an existing output directory.
A portable complete-download guard and unsafe-ZIP fixture replace one
POSIX-dependent audit fixture in this acceptance suite. The original E0 research
reader and tests remain unchanged; I2 checks raw ZIP names on both platforms.

The command prints the result directory. It contains `verification.json`, test
and server logs, and one folder per example with `climate.epw`, hourly CSV, reports
and `complete-product.zip`. Every run uses a new directory. To choose one:

```bash
python ige.py check --out ./ige-check-01
```

To export the four examples without running the regression suite:

```bash
python ige.py examples --out ./ige-examples-01
```

These commands require no Git history and also work in a complete source ZIP.
The research branch preserves committed file bytes across Windows/Linux checkouts;
do not apply automatic line-ending conversion to the frozen input files.
The Python environment itself is local to its checkout; recreate it after moving
the source directory. Do not copy a `.venv` between machines.

## Troubleshooting

- **Wrong Python:** install/select Python 3.12 and rerun setup.
- **Interrupted setup:** run setup again; existing results are not overwritten.
- **Environment differs from lock:** use the dedicated environment. If necessary,
  move `.venv/ige` aside and rerun setup. The launcher never deletes an environment.
- **Missing or changed input:** restore the checkout; do not disable hash checks.
- **Port already used:** `python ige.py run --port 8502`.
- **Existing output directory:** choose a new `--out` directory.

## Interpretation

This milestone makes the existing application reproducible and locally usable.
Historical background, station-temperature reconstruction and future morphing
remain distinct source types. Scientific methods, reference weather files and
their limitations are preserved. R1 remains experimental after V2-M4; its general
accuracy criterion failed. Independent regional accuracy, EnergyPlus qualification
of these files, unrestricted production use and public deployment are separate
milestones. This branch does not modify `main` or the public application.
