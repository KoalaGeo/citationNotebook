import pytest
import pandas as pd
from citations_fun.getNERCDataDOIs import getNERCDataDOIs
from citations_fun.getDataCiteCitations_relationTypes import getDataCiteCitations_relationTypes
from citations_fun.filterCitations import filterCitations
from citations_fun.processScholixCitations import process_citation_results

# --- FIXTURES ---
# A small, hardcoded list of known NERC DOIs that have different citation profiles
@pytest.fixture
def sample_nerc_dois():
    return pd.DataFrame([
        {"data_doi": "10.5285/463ea06f-6c49-4d6e-a80b-21c88a71c3da", "data_publisher": "BODC"},
        {"data_doi": "10.5285/47d0718d-7146-44d3-965c-60e62a48b8cc", "data_publisher": "NGDC"},
        {"data_doi": "10.5285/some-zero-citation-doi", "data_publisher": "CEDA"}
    ])

@pytest.fixture
def mock_unfiltered_citations():
    """Mock dataframe containing citations that should be filtered out."""
    return pd.DataFrame([
        # 1. Valid citation (Should be kept)
        {"pub_doi": "10.1000/valid-paper", "pub_title": "A great paper", "pub_type": "journal-article", "pub_date": 2023, "data_publication_year": 2020},
        
        # 2. GBIF Download (Should be removed - 10.15468)
        {"pub_doi": "10.15468/dl.12345", "pub_title": "GBIF Occurrence Download", "pub_type": "dataset", "pub_date": 2023, "data_publication_year": 2020},
        
        # 3. Pre-print reply (Should be removed based on title)
        {"pub_doi": "10.1000/reply", "pub_title": "Reply to comment by Smith et al.", "pub_type": "journal-article", "pub_date": 2023, "data_publication_year": 2020},
        
        # 4. Peer review (Should be removed based on type)
        {"pub_doi": "10.1000/review", "pub_title": "Review of dataset", "pub_type": "peer-review", "pub_date": 2023, "data_publication_year": 2020},
    ])


# --- TESTS ---

def test_datacite_extraction_schema():
    """Integration test: Verify DataCite API returns the expected schema for NERC."""
    # We use a test limit of 3 to prevent hitting the API too hard during CI
    raw_dois = getNERCDataDOIs(test_mode=True, test_limit=3)
    
    assert len(raw_dois) > 0, "Failed to retrieve any DOIs from DataCite"
    
    first_record = raw_dois[0]
    expected_keys = ["data_publisher", "data_doi", "data_title", "data_authors", "data_publication_year"]
    
    for key in expected_keys:
        assert key in first_record, f"Missing expected key '{key}' in DataCite response."


def test_publisher_normalization():
    """Unit test: Ensure variations of publisher names map to the correct Data Centre."""
    mock_df = pd.DataFrame([
        {"data_doi": "1", "data_publisher": "British Oceanographic Data Centre"},
        {"data_doi": "2", "data_publisher": "NERC Earth Observation Data Centre"},
        {"data_doi": "3", "data_publisher": "Polar Data Centre"}
    ])
    
    # Run through the processor
    processed_df = process_citation_results(mock_df)
    
    publishers = processed_df['data_publisher'].tolist()
    assert "British Oceanographic Data Centre (BODC)" in publishers
    assert "Centre for Environmental Data Analysis (CEDA)" in publishers
    assert "Polar Data Centre (PDC)" in publishers


def test_citation_filtering(mock_unfiltered_citations):
    """Unit test: Ensure unwanted citations (GBIF, replies, peer-reviews) are dropped."""
    kept_df, filtered_df = filterCitations(mock_unfiltered_citations)
    
    # We started with 4 mock rows. 3 should be filtered out, 1 kept.
    assert len(kept_df) == 1, f"Expected 1 valid citation to be kept, got {len(kept_df)}"
    assert len(filtered_df) == 3, f"Expected 3 citations to be filtered out, got {len(filtered_df)}"
    
    # Verify the correct one was kept
    assert kept_df.iloc[0]['pub_doi'] == "10.1000/valid-paper"