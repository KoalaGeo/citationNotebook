# NERC Data Centre Citations
V3.0

This code collects citation information from open API sources (Scholix, Crossref, Datacite, and Overton) for datasets published by NERC data centres. 

The code combines the data from these sources, removes duplicates, and filters out types of citations that we don't want to count (e.g., GBIF downloads, Wikipedia mentions, pre-print comments). The data centre names (i.e., publishers) are also normalized to a consistent standard.

Note: The harvested data is not an exhaustive list of all citations and may still contain some edge-case inaccuracies inherent to open metadata.

## Usage (Python Script - Recommended)

The pipeline has been consolidated into a single orchestrator script. This is the recommended way to run the code for both production and CI/CD environments.

To run the full pipeline (takes several hours due to API rate limits):
    python run_pipeline.py

To run a rapid test using a subset of DOIs (completes in ~5 minutes):
    python run_pipeline.py --test-mode --test-limit 20

## Testing (Integration & Unit Tests)

We use `pytest` to run integration tests that verify external API schemas (DataCite, Scholix) remain consistent and that internal deduplication and filtering rules work correctly against known datasets.

To run the test suite:
1. Ensure pytest is installed: `pip install pytest`
2. Run the tests from the root directory: `pytest tests/test_pipeline.py`

## Usage (Jupyter Notebooks - Legacy / Interactive)

The core logic is also split across five Jupyter notebooks for step-by-step interactive debugging. These can be executed manually or orchestrated via `papermill`. 
1. nerc_dataset_DOIs.ipynb
2. nerc_dataset_citations_dataCite.ipynb
3. nerc_dataset_citations_scholix.ipynb
4. nerc_dataset_citations_overton.ipynb
5. nerc_dataset_citations_merge_results.ipynb

## Outputs

The Results/v3/ folder contains the outputs of the code in CSV and JSON format. 
The latest results are found in the file latest_results.json. The JSON is organised with each Data Centre as a top-level key.

## Authors:
Matthew Nichols (UKCEH)
Edward Lewis (BGS)