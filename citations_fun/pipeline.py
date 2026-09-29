# Pipeline stages, one per scheduled GitHub Action. Each stage is a straight
# port of the notebook it replaces (named in its docstring) and reads/writes
# the same files, so the published results are unchanged. The only format
# change is that the intermediate .pkl files are now .parquet (see storage.py).
#
# Run from the repository root: python -m citations_fun run <stage|all>

import json
from datetime import date

import pandas as pd

from citations_fun.storage import read_parquet, write_parquet

INTERMEDIATE = "Results/intermediate_data/"
RESULTS = "Results/v3/"

NERC_DATACITE_DOIS_JSON = INTERMEDIATE + "nerc_datacite_dois.json"


def _load_nerc_datacite_dois_df():
    with open(NERC_DATACITE_DOIS_JSON) as f:
        nerc_datacite_dois = json.load(f)
    return pd.DataFrame(nerc_datacite_dois)


def run_dois():
    """Collect NERC dataset DOIs from DataCite (was nerc_dataset_DOIs.ipynb)."""
    from citations_fun.getNERCDataDOIs import getNERCDataDOIs

    # this takes approx ~10 mins; writes nerc_datacite_dois.json itself
    getNERCDataDOIs()


def run_datacite():
    """DataCite citation events (was nerc_dataset_citations_dataCite.ipynb)."""
    from citations_fun.getDataCiteCitations_relationTypes import getDataCiteCitations_relationTypes
    from citations_fun.getPublicationInfo_forDataCite import getPublicationInfo

    relation_type_id_list = ['is-cited-by', 'is-referenced-by', 'is-supplement-to', 'IsPartOf', 'IsContinuedBy', 'IsDescribedBy', 'IsDocumentedBy', 'IsDerivedFrom', 'IsRequiredBy']
    dataCite_df_relationTypes = getDataCiteCitations_relationTypes(relation_type_id_list)

    # join events data with dataset DOI metadata
    nerc_datacite_dois_df = _load_nerc_datacite_dois_df()

    datacite_doi_events_df = dataCite_df_relationTypes.merge(
        nerc_datacite_dois_df,
        left_on='data_doi',
        right_on='data_doi',
        how='left'  # left-join as dataCite_df_relationTypes is a subset of nerc_datacite_dois_df
    )

    datacite_doi_events_df_drop = datacite_doi_events_df.drop(['data_page_number', 'data_self_link'], axis=1)

    # re-order
    datacite_doi_events_df_drop = datacite_doi_events_df_drop[[
        'data_doi', 'data_publisher', 'data_title', 'data_publication_year', 'data_authors',
        'relation_type', 'pub_doi', 'source_id'
    ]]

    # takes 15 mins
    # get pub title, authors and date
    dataCite_df_pubInfo = getPublicationInfo(datacite_doi_events_df_drop)

    dataCite_df_pubInfo_names = dataCite_df_pubInfo[[
        'data_doi', 'data_publisher', 'data_title', 'data_publication_year', 'data_authors',
        'relation_type', 'pub_doi', 'pub_title', 'pub_date', 'pub_authors', 'source_id', 'pub_publisher', 'pub_type'
    ]]

    dataCite_df_pubInfo_names.to_csv(INTERMEDIATE + "latest_results_dataCite.csv", index=False)
    write_parquet(dataCite_df_pubInfo_names, INTERMEDIATE + "latest_results_dataCite.parquet")


def run_scholix():
    """Scholexplorer citations (was nerc_dataset_citations_scholix.ipynb)."""
    from citations_fun.getScholixCitations import getScholixCitations
    from citations_fun.processScholixCitations import process_citation_results
    from citations_fun.getPublicationType_forScholex import getPublicationType

    nerc_datacite_dois_df = _load_nerc_datacite_dois_df()

    # this takes about 17 - 28 mins
    scholex_df = getScholixCitations(nerc_datacite_dois_df)

    # process the citation results
    if len(scholex_df) > 0:
        scholex_df_processed = process_citation_results(scholex_df)
    else:
        scholex_df_processed = scholex_df

    # check the DOIs at DOI.org to determine the type of publication
    # took 74 mins - previously very long 3+ hours
    if len(scholex_df_processed) > 0:
        scholex_df_processed_pubType = getPublicationType(scholex_df_processed)
    else:
        scholex_df_processed_pubType = scholex_df_processed

    scholex_df_processed_pubType.to_csv(INTERMEDIATE + "latest_results_scholex.csv", index=False)
    write_parquet(scholex_df_processed_pubType, INTERMEDIATE + "latest_results_scholex.parquet")


def run_overton():
    """Overton policy citations (was nerc_dataset_citations_overton.ipynb)."""
    from citations_fun.getOvertonCitations import getOvertonCitations, processOvertonResults

    nerc_datacite_dois_df = _load_nerc_datacite_dois_df()

    # this takes 95-134 minutes
    results = getOvertonCitations(nerc_datacite_dois_df)

    # process and write latest_results_overton.csv/.parquet
    processOvertonResults(results)


def pub_year_splitter(date):
    # create publicationYear column from pub_date
    if date == "Info not given":
        return None
    else:
        try:
            return date.split('/')[2]
        except:
            try:
                return date.split('-')[0]
            except:
                print(date)
                return None


def run_merge(today=None):
    """Merge sources, filter, add citation strings and write Results/v3
    (was nerc_dataset_citations_merge_results.ipynb)."""
    from citations_fun.mergeCitations import merge_citation_dfs
    from citations_fun.getCitationString import get_citation_str
    from citations_fun.filterCitations import filterCitations

    today = today or date.today()

    # load results - datacite, scholex and overton
    dataCite_df = read_parquet(INTERMEDIATE + "latest_results_dataCite.parquet")
    scholex_df = read_parquet(INTERMEDIATE + "latest_results_scholex.parquet")
    overton_df = read_parquet(INTERMEDIATE + "latest_results_overton.parquet")

    # merge all results
    df_list = [dataCite_df, scholex_df, overton_df]
    nerc_citations_df = merge_citation_dfs(df_list)

    # remove doi.org for
    nerc_citations_df['pub_doi'] = nerc_citations_df['pub_doi'].str.replace(
        'https://doi.org/', '', regex=False
    )

    nerc_citations_df['publicationYear'] = nerc_citations_df['pub_date'].apply(pub_year_splitter)

    # filtering - keep the results that are filtered out for later checks
    # returns list of 2 dataframes, first is the main df, second is everything that has been filtered out
    results = filterCitations(nerc_citations_df)
    nerc_citations_df_filtered = results[0]
    filtered_out_df = results[1]

    # write to file for a record
    filtered_out_df.to_csv(RESULTS + "filtered_out_df.csv", index=False)

    # get citation string - takes about 2 hours
    nerc_citations_df = get_citation_str(nerc_citations_df_filtered)

    # add 'doi.org/' to data and pub dois in new columns
    nerc_citations_df['data_doi_url'] = 'doi.org/' + nerc_citations_df['data_doi']
    # need extra logic here as overton pub_doi column usually just a normal url
    nerc_citations_df['publication_doi_url'] = nerc_citations_df['pub_doi'].apply(
        lambda x: f"doi.org/{x}" if x.startswith("10.") else x
    )

    # map to expected column names for API schema
    cols = {
        'relation_type': 'relation_type_id',
        'pub_doi': 'publication_doi', 'pub_title': 'publication_title', 'pub_date': 'publication_date',
        'pub_authors': 'publication_authors', 'source_id': 'citation_event_source', 'pub_type': 'publication_type',
        'pub_citation_str': 'PubCitationStr'
    }
    nerc_citations_df_renamed = nerc_citations_df.rename(columns=cols)

    # add index date_added
    # read last week's result
    old_results = pd.read_csv(RESULTS + "latest_results.csv")

    # Prepare a mapping of old pairs and date_added
    date_map = (
        old_results[['data_doi', 'publication_doi', 'date_added']]
        .drop_duplicates(subset=['data_doi', 'publication_doi'])
        .set_index(['data_doi', 'publication_doi'])['date_added']
    )

    # map old dates onto new df
    nerc_citations_df_renamed['date_added'] = nerc_citations_df_renamed.set_index(['data_doi', 'publication_doi']).index.map(date_map)

    # Fill in today's date where no old date exists
    nerc_citations_df_renamed['date_added'] = nerc_citations_df_renamed['date_added'].fillna(str(today))

    # write to csv and json file
    nerc_citations_df_renamed.to_csv(RESULTS + 'latest_results.csv', index=False, encoding="utf-8-sig")

    # write data to 'latest_results' json file with data publisher as top level key
    # Group by 'data_publisher' and convert the DataFrame to a nested dictionary
    nested_dict = nerc_citations_df_renamed.groupby('data_publisher').apply(
        lambda x: x.drop('data_publisher', axis=1).to_dict(orient='records')
    ).to_dict()

    json_object = json.dumps(nested_dict, ensure_ascii=False)

    with open(RESULTS + 'latest_results.json', 'w', encoding='utf-8') as f:
        f.write(json_object)


# In dependency order: dois feeds the three sources, which all feed merge.
STAGES = {
    "dois": run_dois,
    "datacite": run_datacite,
    "scholix": run_scholix,
    "overton": run_overton,
    "merge": run_merge,
}


def run_all():
    """Run every stage in order, stopping at the first one that fails."""
    for name, stage in STAGES.items():
        print(f"=== Running stage: {name}")
        stage()
