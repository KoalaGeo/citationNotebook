"""Small, pure transforms shared by the sources (no I/O -- fully unit-testable)."""

DOI_URL_PREFIXES = ("https://doi.org/", "http://doi.org/",
                    "https://dx.doi.org/", "http://dx.doi.org/")


def strip_doi_url(value):
    """'https://doi.org/10.1/x' -> '10.1/x'; non-URL values pass through."""
    if not isinstance(value, str):
        return value
    for prefix in DOI_URL_PREFIXES:
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def normalize_publisher(publisher):
    """Map the many DataCite publisher spellings onto one name per data centre.

    Ported verbatim from getNERCDataDOIs / processScholixCitations (they had two
    copies of this; now there is one). May need reviewing periodically as new
    variants appear.
    """
    if publisher is None or isinstance(publisher, float):
        return publisher
    lower = publisher.lower()
    if "polar" in lower:
        return "Polar Data Centre (PDC)"
    if "atmospheric" in lower or "badc" in lower or "earth" in lower:
        return "Centre for Environmental Data Analysis (CEDA)"
    if "oceanographic" in lower:
        return "British Oceanographic Data Centre (BODC)"
    if "geological" in lower or "geoscience" in lower:
        return "National Geoscience Data Centre (NGDC)"
    if "environmental information" in lower:
        return "Environmental Information Data Centre (EIDC)"
    if "environmental data" in lower:
        return "Centre for Environmental Data Analysis (CEDA)"
    return publisher


def creator_names(creators):
    """Scholix Creator list [{'name': ...}, ...] -> ['name', ...]."""
    names = []
    for individual in creators or []:
        if isinstance(individual, dict) and individual.get("name"):
            names.append(individual["name"])
    return names


def pub_year_splitter(date):
    """Extract a publication year string from the pipeline's mixed date formats.

    Ported from the merge notebook: 'd/m/YYYY' -> 'YYYY' (split('/')[2]),
    'YYYY-MM-DD' -> 'YYYY' (split('-')[0]), 'Info not given'/unparseable -> None.
    """
    if date == "Info not given" or date is None:
        return None
    try:
        return date.split("/")[2]
    except (AttributeError, IndexError):
        try:
            return date.split("-")[0]
        except AttributeError:
            return None


def merge_publication_types(t1, t2):
    """Choose between the Scholix-supplied type and the doi.org-derived type.

    Ported verbatim from getPublicationType_forScholex.merge_publication_types.
    """
    if t1 == t2:
        return t1
    if t1 in ("unknown", "not a doi"):
        return t2
    if t2 in ("unknown", "not a doi"):
        return t1
    if t1 == "literature":
        return t2
    if t2 == "literature":
        return t1
    if t1 == "dataset":
        return t2
    if t2 == "dataset":
        return t1
    return t2
