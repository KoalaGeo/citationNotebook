# functions to harvest nerc dataset citations from Overton
import requests, time, json
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from citations_fun.storage import write_parquet

def getOvertonCitations(nerc_datacite_dois_df):
    api_key = "3c7b1a-849d90-77f9da"
    
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"] # Added POST to allowed methods for retries
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))

    # 1. Extract DOIs and generate the set
    dois_list = nerc_datacite_dois_df['data_doi'].dropna().tolist()
    dois_payload = "\n".join(dois_list)
    
    set_url = f"https://app.overton.io/generate_id_set.php?format=json&api_key={api_key}"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    print("Generating Overton DOI set...")
    try:
        set_response = session.post(set_url, headers=headers, data={'dois': dois_payload}, timeout=30)
        set_response.raise_for_status()
        set_data = set_response.json()
    except requests.RequestException as e:
        print(f"Failed to generate set: {e}")
        return []

    if 'set' not in set_data:
        print(f"Error generating set: {set_data.get('error', 'Unknown error')}")
        if 'warnings' in set_data:
            print(f"Warnings: {set_data['warnings']}")
        return []

    overton_set_id = set_data['set']
    print(f"Successfully generated set ID: {overton_set_id}")

    # 2. Fetch the paginated results using the generated set_id
    results = []
    search_url = f"https://app.overton.io/documents.php?plain_dois_cited={overton_set_id}&format=json&api_key={api_key}"
    
    while search_url:
        start = time.time()
        
        try:
            r = session.get(search_url, timeout=30)
            r.raise_for_status()
            page_data = r.json()
            
            page_results = page_data.get('results', [])
            if page_results:
                # Appending the list of results keeps the nested list structure 
                # required by processOvertonResults (list of lists)
                results.append(page_results)
                
            current_page = page_data.get('query', {}).get('current_page', 'Unknown')
            total_pages = page_data.get('query', {}).get('pages', 'Unknown')
            print(f"Processed page {current_page} of {total_pages}")
            
            search_url = page_data.get('query', {}).get('next_page_url')
            
        except requests.RequestException as e:
            print(f"Error fetching page data: {e}")
            break

        elapsed = time.time() - start
        
        # Enforce at least 1s between requests to respect the rate limit
        if elapsed < 1:
            time.sleep(1.05 - elapsed)
            
    return results


def processOvertonResults(results):
    flat_results = [d for sublist in results for d in sublist]
    overton_df = pd.DataFrame(flat_results)
    # overton_df.to_csv("results/overton_list.csv", index= False )

    # extract columns we're interested in
    overton_df_sub = overton_df[['title', 'authors', 'published_on', 'document_url', 'highlights', 'source', 'overton_policy_document_series']]


    # extract relation type and data doi from highlights column dictionaries
    extracted_highlights = overton_df_sub["highlights"].apply(
        lambda x: {
            "type": x[0]["type"] if isinstance(x, list) and len(x) > 0 else None,
            "doi": x[0]["doi"] if isinstance(x, list) and len(x) > 0 else None,
        }
    )
    # Turn the Series of dicts into a DataFrame and join to the original
    extracted_highlights_df = pd.DataFrame(extracted_highlights.tolist())
    overton_df_sub = overton_df_sub.join(extracted_highlights_df)

    # extract title from source dictionary to get pub_publisher
    overton_df_sub["pub_publisher"] = overton_df_sub["source"].apply(
        lambda x: x.get("title") if isinstance(x, dict) else None
    )

    # drop highlights and source columns - no longer needed
    overton_df_sub = overton_df_sub.drop(['highlights', 'source'], axis = 1)

    # rename columns
    cols = {"title":"pub_title", 'authors':'pub_authors', 'published_on':'pub_date', 'document_url':'pub_doi', 'type':'relation_type', 'doi':'data_doi', 'overton_policy_document_series':'pub_type'}
    overton_df_sub = overton_df_sub.rename(columns = cols)

    # merge with nerc_datacite_dois_df before writing to latest_results_overton.csv
    with open("Results/intermediate_data/nerc_datacite_dois.json") as f:
        nerc_datacite_dois = json.load(f)
    nerc_datacite_dois_df = pd.DataFrame(nerc_datacite_dois)

    overton_df_merged = overton_df_sub.merge(
        nerc_datacite_dois_df,
        left_on='data_doi',
        right_on='data_doi',
        how='left'
    )

    overton_df_merged = overton_df_merged.drop(['data_page_number', 'data_self_link'], axis = 1)

    # add column source-id
    source_id = ['overton'] * len(overton_df_merged)
    overton_df_merged['source_id'] = source_id

    # re-oder columns
    overton_df_merged = overton_df_merged[[
        'data_doi', 'data_publisher', 'data_title', 'data_publication_year', 'data_authors',
        'relation_type', 'pub_doi', 'pub_title', 'pub_date', 'pub_authors', 'pub_type', 'pub_publisher', 'source_id'
    ]]

    # Sort rows to minimize git diffs and reset the index
    overton_df_merged = overton_df_merged.sort_values(by=['data_doi', 'pub_doi']).reset_index(drop=True)
    
    # write to file
    overton_df_merged.to_csv("Results/intermediate_data/latest_results_overton.csv", index= False)
    write_parquet(overton_df_merged, "Results/intermediate_data/latest_results_overton.parquet")


    return overton_df_merged
