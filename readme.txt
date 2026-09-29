NERC Data Centre Citations
V1.1 25/07/23

This code collects citation information from open API sources (Scholix, Crossref and Datacite) for datasets published by NERC data centres. 

The code combines the data from the three sources, removes duplicates and types of citations that we don't want to count, e.g. gbif or wikipedia mentions etc.
The data centre names (i.e. publishers) are made consistent.

The harvested data is not an exhaustive list of all the citations, and still contains some citations that are incorrect.

Usage
The pipeline is plain Python in the citations_fun package. Install the dependencies with
    pip install -r requirements.txt
and run from the repository root, either one stage at a time or everything in order:
    python -m citations_fun run <stage>
    python -m citations_fun run all

Stages (each runs as its own weekly GitHub Action, in this order):
    dois      NERC dataset DOIs from DataCite  -> Results/intermediate_data/nerc_datacite_dois.json
    datacite  DataCite citation events         -> Results/intermediate_data/latest_results_dataCite.csv/.parquet
    scholix   Scholexplorer citations          -> Results/intermediate_data/latest_results_scholex.csv/.parquet
    overton   Overton policy citations         -> Results/intermediate_data/latest_results_overton.csv/.parquet
    merge     merge, filter, citation strings  -> Results/v3/latest_results.csv/.json, Results/v3/filtered_out_df.csv

The .parquet files pass data between stages; read them with citations_fun.storage.read_parquet
(object columns are stored as JSON text so mixed values round-trip exactly).
The full run takes several hours. inspect_results.ipynb is a notebook for checking results by hand.
The Results/v3/ folder contains the outputs of the code in csv and json format. The json is organised by each Data Centre as the top level keys.

The latest results are found in the file latest_results.json

Top level key:
data_Publisher	
Nested keys:
data_doi	data_Title	data_Authors	relation_type_id	publication_doi	publication_type	publication_title	publication_authors	citation_event_source	PubCitationStr


Authors:
Matthew Nichols (UKCEH)

Acknowledgments/references:
The functions to extract data from Crossref have been modified from the demo notebooks on the Crossref github (https://github.com/CrossRef/rest-api-doc)


