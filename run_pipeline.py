#!/usr/bin/env python3
"""
NERC Dataset Citations Pipeline Orchestrator
Consolidates and automates execution loops previously handled across multiple Jupyter Notebooks.
"""

import argparse
import json
import os
import sys
from pathlib import Path
import pandas as pd

# Import your existing modularized logic
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

# Ensure output directories exist before running
INTERMEDIATE_DIR = Path("Results/intermediate_data")
FINAL_DIR = Path("Results/v3")
INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
FINAL_DIR.mkdir(parents=True, exist_ok=True)


def parse_arguments():
    """Parses command line arguments for configuring the pipeline run."""
    parser = argparse.ArgumentParser(
        description="Run the full NERC dataset citations harvesting and processing pipeline."
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Enable testing mode (caps records and API calls to prevent long runtimes)."
    )
    parser.add_argument(
        "--test-limit",
        type=int,
        default=20,
        help="Maximum number of dataset DOIs to pull and process when in test-mode (default: 20)."
    )
    return parser.parse_args()


def run_pipeline():
    args = parse_arguments()
    
    print("=" * 60)
    print(f"STARTING NERC CITATION PIPELINE (Test Mode: {args.test_mode})")
    print("=" * 60)

    # -------------------------------------------------------------------------
    # STEP 1: Harvest NERC Dataset DOIs (Replaces nerc_dataset_DOIs.ipynb)
    # -------------------------------------------------------------------------
    print("\n[Step 1/5] Extracting NERC Dataset DOIs from DataCite...")
    
    # Injecting test configurations dynamically
    if args.test_mode:
        print(f"--> Test Mode Active: Restricting extraction to {args.test_limit} DOIs.")
        # Assuming getNERCDataDOIs is updated to handle limits, otherwise slice the result array
        raw_dois = getNERCDataDOIs()
        raw_dois = raw_dois[:args.test_limit]
        # Re-save scaled down variant for test integrity
        with open(INTERMEDIATE_DIR / "nerc_datacite_dois.json", "w") as f:
            json.dump(raw_dois, f, indent=4)
    else:
        raw_dois = getNERCDataDOIs()

    nerc_dois_df = pd.DataFrame(raw_dois)
    print(f"--> Completed Step 1. Loaded {len(nerc_dois_df)} base dataset DOIs.")

    if nerc_dois_df.empty:
        print("[Error] No dataset DOIs found. Exiting pipeline.")
        sys.exit(1)

    # -------------------------------------------------------------------------
    # STEP 2: DataCite Events Harvesting (Replaces nerc_dataset_citations_dataCite.ipynb)
    # -------------------------------------------------------------------------
    print("\n[Step 2/5] Harvesting citations from DataCite Events API...")
    relation_types = ['is-referenced-by', 'is-cited-by']
    
    # Pull event relations
    datacite_events_df = getDataCiteCitations_relationTypes(relation_types)
    
    if not datacite_events_df.empty:
        # If in test mode, safely cap the metadata lookups to minimize remote hits
        if args.test_mode:
            datacite_events_df = datacite_events_df.head(args.test_limit)
            
        print(f"--> Fetching publication metadata details for {len(datacite_events_df)} items...")
        datacite_pub_info_df = getPublicationInfo(datacite_events_df)
        
        # Clean down structural columns to match your down-stream schema contract
        datacite_cols = [
            'data_doi', 'data_publisher', 'data_title', 'data_publication_year', 'data_authors',
            'relation_type', 'pub_doi', 'pub_title', 'pub_date', 'pub_authors', 'source_id', 'pub_publisher', 'pub_type'
        ]
        # Intersect keys gracefully in case columns change or fail upstream
        valid_datacite_cols = [c for c in datacite_cols if c in datacite_pub_info_df.columns]
        datacite_final_df = datacite_pub_info_df[valid_datacite_cols]
    else:
        print("--> No DataCite relationship events found.")
        datacite_final_df = pd.DataFrame()

    datacite_final_df.to_pickle(INTERMEDIATE_DIR / "latest_results_dataCite.pkl")

    # -------------------------------------------------------------------------
    # STEP 3: Scholix Harvesting (Replaces nerc_dataset_citations_scholix.ipynb)
    # -------------------------------------------------------------------------
    print("\n[Step 3/5] Harvesting citations from Scholix / OpenAIRE...")
    
    # Use the pipeline's active DOI footprint
    scholix_raw_df = getScholixCitations(nerc_dois_df)
    
    if not scholix_raw_df.empty:
        scholix_processed_df = process_citation_results(scholix_raw_df)
        
        if args.test_mode:
            scholix_processed_df = scholix_processed_df.head(args.test_limit)
            
        print(f"--> Fetching true publication classifications from Crossref for {len(scholix_processed_df)} records...")
        scholix_final_df = getPublicationType(scholix_processed_df)
    else:
        print("--> No Scholix citations found.")
        scholix_final_df = pd.DataFrame()

    scholix_final_df.to_pickle(INTERMEDIATE_DIR / "latest_results_scholex.pkl")

    # -------------------------------------------------------------------------
    # STEP 4: Overton Policy Harvesting (Replaces nerc_dataset_citations_overton.ipynb)
    # -------------------------------------------------------------------------
    print("\n[Step 4/5] Harvesting policy citations via Overton API...")
    
    overton_raw_results = getOvertonCitations(nerc_dois_df)
    if overton_raw_results:
        overton_final_df = processOvertonResults(overton_raw_results)
    else:
        print("--> No Overton citations discovered.")
        overton_final_df = pd.DataFrame()

    overton_final_df.to_pickle(INTERMEDIATE_DIR / "latest_results_overton.pkl")

    # -------------------------------------------------------------------------
    # STEP 5: Merge, Format, & Filter Results
    # -------------------------------------------------------------------------
    print("\n[Step 5/5] Merging and deduplicating cross-platform data streams...")
    
    df_list = [df for df in [datacite_final_df, scholix_final_df, overton_final_df] if not df.empty]
    
    if not df_list:
        print("[Warning] No data gathered across any open APIs. Final merge cancelled.")
        sys.exit(0)

    combined_df = merge_citation_dfs(df_list)
    print(f"--> Aggregated raw row count: {len(combined_df)} records.")

    if args.test_mode:
        # Cap the dataframe to ensure the network loop below doesn't run wild
        combined_df = combined_df.head(args.test_limit).copy()

    # Generate custom bibliographic string lines via Crossref formatting engine
    print("--> Resolving academic bibliography output strings (get_citation_str)...")
    
    citation_output = get_citation_str(combined_df)
    
    if isinstance(citation_output, pd.DataFrame):
        # If the function returned a whole modified DataFrame, adopt it
        combined_df = citation_output
        
        # Ensure the column naming matches downstream expectations
        if 'pub_citation_str' not in combined_df.columns and 'PubCitationStr' in combined_df.columns:
            combined_df = combined_df.rename(columns={'PubCitationStr': 'pub_citation_str'})
    else:
        # If it returned a list or Series, assign it directly
        combined_df['pub_citation_str'] = citation_output
    # ---------------------------------------------------------

    # Run clean rules (skipping pre-print replies, bad years, GBIF, etc.)
    print("--> Executing filtration rules...")
    kept_df, filtered_out_df = filterCitations(combined_df)
    
    # Save intermediate components for auditing
    kept_df.to_pickle(INTERMEDIATE_DIR / "nerc_citations_df_kept.pkl")
    filtered_out_df.to_pickle(INTERMEDIATE_DIR / "nerc_citations_df_filtered_out.pkl")

    # Write output final datasets
    today_str = pd.Timestamp.now().strftime('%Y-%m-%d')
    kept_df.to_csv(FINAL_DIR / "latest_results.csv", index=False)
    kept_df.to_csv(FINAL_DIR / f"results_{today_str}.csv", index=False)
    
    # Convert data structural frames to nested publisher JSON schema expected by consumers
    print("--> Formatting nested JSON structures grouped by data center...")
    nested_json_output = {}
    grouped = kept_df.groupby('data_publisher')
    for publisher, group in grouped:
        # Coerce records cleanly into row objects inside dictionary indexes
        nested_json_output[str(publisher)] = group.drop(columns=['data_publisher']).to_dict(orient='records')
        
    with open(FINAL_DIR / "latest_results.json", "w") as f:
        json.dump(nested_json_output, f, indent=4)

    print("\n" + "=" * 60)
    print(f"PIPELINE RUN COMPLETE.")
    print(f"Final Filtered Citations Count: {len(kept_df)}")
    print(f"Outputs written safely to: {FINAL_DIR.resolve()}")
    print("=" * 60)
