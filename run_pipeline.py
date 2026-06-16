#!/usr/bin/env python3
"""
NERC Dataset Citations Pipeline Orchestrator (Notebook-Faithful Version)
This script perfectly mimics the execution flow of the 5 individual Jupyter notebooks.
"""

import argparse
import json
import sys
from pathlib import Path
import pandas as pd

# Import modules exactly as the notebooks do
from citations_fun.getNERCDataDOIs import getNERCDataDOIs
from citations_fun.getDataCiteCitations_relationTypes import getDataCiteCitations_relationTypes
from citations_fun.getPublicationInfo_forDataCite import getPublicationInfo
from citations_fun.getScholixCitations import getScholixCitations
from citations_fun.processScholixCitations import process_citation_results
from citations_fun.getPublicationType_forScholex import getPublicationType
from citations_fun.getOvertonCitations import getOvertonCitations, processOvertonResults
from citations_fun.mergeCitations import merge_citation_dfs
from citations_fun.getCitationString import get_citation_str
from citations_fun.filterCitations import filterCitations

INTERMEDIATE_DIR = Path("Results/intermediate_data")
FINAL_DIR = Path("Results/v3")
INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
FINAL_DIR.mkdir(parents=True, exist_ok=True)

def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-mode", action="store_true", help="Enable testing mode.")
    parser.add_argument("--test-limit", type=int, default=3, help="Max items to process in slow network loops.")
    return parser.parse_args()

def run_pipeline():
    args = parse_arguments()
    
    print("=" * 60)
    print(f"STARTING NERC CITATION PIPELINE (Test Mode: {args.test_mode})")
    print("=" * 60)

    # -------------------------------------------------------------------------
    # NOTEBOOK 1: nerc_dataset_DOIs.ipynb
    # -------------------------------------------------------------------------
    print("\n[Notebook 1/5] Extracting NERC Dataset DOIs...")
    getNERCDataDOIs() # This internally writes to Results/intermediate_data/nerc_datacite_dois.json

    if args.test_mode:
        print("--> Test Mode Active: Injecting 'Golden DOIs' to avoid BAS server timeouts.")
        golden_dois = [
            {"data_publisher": "British Oceanographic Data Centre (BODC)", "data_doi": "10.5285/463ea06f-6c49-4d6e-a80b-21c88a71c3da", "data_title": "Test BODC Dataset", "data_publication_year": 2020, "data_authors": ["Smith, J."], "data_page_number": 1, "data_self_link": ""},
            {"data_publisher": "National Geoscience Data Centre (NGDC)", "data_doi": "10.5285/47d0718d-7146-44d3-965c-60e62a48b8cc", "data_title": "Test NGDC Dataset", "data_publication_year": 2018, "data_authors": ["Jones, A."], "data_page_number": 1, "data_self_link": ""},
            {"data_publisher": "Centre for Environmental Data Analysis (CEDA)", "data_doi": "10.5285/551a10ae-b8ed-4ebd-ab38-033dd597a374", "data_title": "Test CEDA Dataset", "data_publication_year": 2019, "data_authors": ["Davis, R."], "data_page_number": 1, "data_self_link": ""}
        ]
        with open(INTERMEDIATE_DIR / "nerc_datacite_dois.json", "w") as f:
            json.dump(golden_dois, f, indent=4)

    # Load the base DOIs (Notebooks 2, 3, and 4 all start by loading this file)
    with open(INTERMEDIATE_DIR / "nerc_datacite_dois.json") as f:
        nerc_datacite_dois_df = pd.DataFrame(json.load(f))

    # -------------------------------------------------------------------------
    # NOTEBOOK 2: nerc_dataset_citations_dataCite.ipynb
    # -------------------------------------------------------------------------
    print("\n[Notebook 2/5] Harvesting DataCite Events...")
    datacite_events_df = getDataCiteCitations_relationTypes(['is-referenced-by', 'is-cited-by'])
    
    if not datacite_events_df.empty:
        # Merge with base DOIs exactly as Notebook 2 does
        datacite_doi_events_df_merged = datacite_events_df.merge(nerc_datacite_dois_df, on='data_doi', how='left')
        
        # Safe drop columns without crashing if they are missing
        cols_to_drop = [c for c in ['data_page_number', 'data_self_link'] if c in datacite_doi_events_df_merged.columns]
        datacite_doi_events_df_drop = datacite_doi_events_df_merged.drop(columns=cols_to_drop)

        if args.test_mode:
            # Filter the 2,700 records down to ONLY the events related to our 3 Golden DOIs
            test_dois_list = nerc_datacite_dois_df['data_doi'].tolist()
            datacite_doi_events_df_drop = datacite_doi_events_df_drop[datacite_doi_events_df_drop['data_doi'].isin(test_dois_list)]
            datacite_doi_events_df_drop = datacite_doi_events_df_drop.head(args.test_limit)

        dataCite_df_pubInfo = getPublicationInfo(datacite_doi_events_df_drop)
        
        # Keep specific columns exactly as Notebook 2 does
        desired_cols = ['data_doi', 'data_publisher', 'data_title', 'data_publication_year', 'data_authors', 
                        'relation_type', 'pub_doi', 'pub_title', 'pub_date', 'pub_authors', 'source_id', 'pub_publisher', 'pub_type']
        valid_cols = [c for c in desired_cols if c in dataCite_df_pubInfo.columns]
        dataCite_df_pubInfo_names = dataCite_df_pubInfo[valid_cols]
    else:
        dataCite_df_pubInfo_names = pd.DataFrame()

    dataCite_df_pubInfo_names.to_pickle(INTERMEDIATE_DIR / "latest_results_dataCite.pkl")

    # -------------------------------------------------------------------------
    # NOTEBOOK 3: nerc_dataset_citations_scholix.ipynb
    # -------------------------------------------------------------------------
    print("\n[Notebook 3/5] Harvesting Scholix Citations...")
    scholex_df = getScholixCitations(nerc_datacite_dois_df)
    
    if not scholex_df.empty:
        scholex_df_processed = process_citation_results(scholex_df)
        if args.test_mode:
            scholex_df_processed = scholex_df_processed.head(args.test_limit)
        scholex_final = getPublicationType(scholex_df_processed)
    else:
        scholex_final = pd.DataFrame()

    scholex_final.to_pickle(INTERMEDIATE_DIR / "latest_results_scholex.pkl")

    # -------------------------------------------------------------------------
    # NOTEBOOK 4: nerc_dataset_citations_overton.ipynb
    # -------------------------------------------------------------------------
    print("\n[Notebook 4/5] Harvesting Overton Policy Citations...")
    overton_raw = getOvertonCitations(nerc_datacite_dois_df)
    if overton_raw:
        overton_final = processOvertonResults(overton_raw)
    else:
        overton_final = pd.DataFrame()

    overton_final.to_pickle(INTERMEDIATE_DIR / "latest_results_overton.pkl")

    # -------------------------------------------------------------------------
    # NOTEBOOK 5: nerc_dataset_citations_merge_results.ipynb
    # -------------------------------------------------------------------------
    print("\n[Notebook 5/5] Merging and Deduplicating...")
    # Load exactly like the notebook does
    dataCite_df = pd.read_pickle(INTERMEDIATE_DIR / "latest_results_dataCite.pkl")
    scholex_df = pd.read_pickle(INTERMEDIATE_DIR / "latest_results_scholex.pkl")
    overton_df = pd.read_pickle(INTERMEDIATE_DIR / "latest_results_overton.pkl")

    df_list = [df for df in [dataCite_df, scholex_df, overton_df] if not df.empty]
    if not df_list:
        print("[Warning] No data gathered across any APIs. Exiting.")
        sys.exit(0)

    nerc_citations_df = merge_citation_dfs(df_list)

    if args.test_mode:
        nerc_citations_df = nerc_citations_df.head(args.test_limit).copy()

    # Get formatted citation strings
    print("--> Resolving academic bibliography strings (get_citation_str)...")
    citation_output = get_citation_str(nerc_citations_df)
    
    # Safely handle the string output without touching the module
    if isinstance(citation_output, pd.DataFrame):
        nerc_citations_df = citation_output
        if 'PubCitationStr' in nerc_citations_df.columns:
            nerc_citations_df = nerc_citations_df.rename(columns={'PubCitationStr': 'pub_citation_str'})
    else:
        nerc_citations_df['pub_citation_str'] = citation_output

    # --- THE HACK: Fix the filterCitations module without editing the file ---
    # filterCitations.py explicitly looks for 'publicationYear'. We create it here.
    if 'pub_date' in nerc_citations_df.columns and 'publicationYear' not in nerc_citations_df.columns:
        nerc_citations_df['publicationYear'] = nerc_citations_df['pub_date']

    print("--> Executing filtration rules...")
    kept_df, filtered_out_df = filterCitations(nerc_citations_df)

    # Save to final outputs
    today_str = pd.Timestamp.now().strftime('%Y-%m-%d')
    kept_df.to_csv(FINAL_DIR / "latest_results.csv", index=False)
    kept_df.to_csv(FINAL_DIR / f"results_{today_str}.csv", index=False)

    nested_json = {}
    for publisher, group in kept_df.groupby('data_publisher'):
        nested_json[str(publisher)] = group.drop(columns=['data_publisher']).to_dict(orient='records')
        
    with open(FINAL_DIR / "latest_results.json", "w") as f:
        json.dump(nested_json, f, indent=4)

    print("\n" + "=" * 60)
    print(f"PIPELINE RUN COMPLETE. (Filtered Citations Count: {len(kept_df)})")
    print("=" * 60)

if __name__ == "__main__":
    run_pipeline()