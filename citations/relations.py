"""Relation vocabulary: every source's relation, seen from the dataset's side, and its class.

All relations are stored in the DataCite vocabulary (CamelCase) as they apply to
the *dataset*: "IsCitedBy" means the other work cites the dataset. A source that
states the link from the citing work's side ("article references dataset") is
inverted. Relations where the dataset is the one doing the citing or deriving
("dataset References article", "dataset IsDerivedFrom X") are *outgoing*: they
are not links to the dataset and are dropped at harvest.
"""

from __future__ import annotations

import re

# DataCite relationType pairs (https://datacite-metadata-schema.readthedocs.io/en/4.5/appendices/appendix-1/relationType/)
_PAIRS = [
    ("IsCitedBy", "Cites"),
    ("IsSupplementTo", "IsSupplementedBy"),
    ("IsContinuedBy", "Continues"),
    ("IsDescribedBy", "Describes"),
    ("HasMetadata", "IsMetadataFor"),
    ("HasVersion", "IsVersionOf"),
    ("IsNewVersionOf", "IsPreviousVersionOf"),
    ("IsPartOf", "HasPart"),
    ("IsReferencedBy", "References"),
    ("IsDocumentedBy", "Documents"),
    ("IsCompiledBy", "Compiles"),
    ("IsVariantFormOf", "IsOriginalFormOf"),
    ("IsIdenticalTo", "IsIdenticalTo"),
    ("IsReviewedBy", "Reviews"),
    ("IsDerivedFrom", "IsSourceOf"),
    ("IsRequiredBy", "Requires"),
    ("IsObsoletedBy", "Obsoletes"),
    ("IsCollectedBy", "Collects"),
    ("IsTranslationOf", "HasTranslation"),
    ("IsPublishedIn", "IsPublishedIn"),
]
SIMILARITY = "HasAmongTopNSimilarDocuments"

INVERSE: dict[str, str] = {}
for a, b in _PAIRS:
    INVERSE[a], INVERSE[b] = b, a
INVERSE[SIMILARITY] = SIMILARITY

VOCABULARY = {name.lower(): name for name in INVERSE}

# Dataset-side relation -> class. Anything not listed is outgoing.
CLASS_OF = {
    "IsCitedBy": "citation",
    "IsReferencedBy": "citation",
    # Supplements are direction-agnostic: data centres write "dataset IsSupplementTo
    # article", while DataCite counts "X is-supplement-to dataset" as a citation.
    "IsSupplementTo": "supplement",
    "IsSupplementedBy": "supplement",
    "IsDocumentedBy": "documentation",
    "IsDescribedBy": "documentation",
    "IsReviewedBy": "documentation",
    "IsRequiredBy": "other",
    "IsSourceOf": "other",          # the other work is derived from the dataset
    "Compiles": "other",            # the dataset is used to compile the other work
    "IsPartOf": "version-or-part",
    "HasPart": "version-or-part",
    "IsNewVersionOf": "version-or-part",
    "IsPreviousVersionOf": "version-or-part",
    "HasVersion": "version-or-part",
    "IsVersionOf": "version-or-part",
    "Continues": "version-or-part",
    "IsContinuedBy": "version-or-part",
    "IsVariantFormOf": "version-or-part",
    "IsOriginalFormOf": "version-or-part",
    "Obsoletes": "version-or-part",
    "IsObsoletedBy": "version-or-part",
    "IsIdenticalTo": "version-or-part",
    SIMILARITY: "similarity",
}

CLASSES = ("citation", "supplement", "documentation", "other", "dataset-link", "version-or-part", "similarity")
# When two sources disagree about one pair, the most specific evidence wins.
PRIORITY = {"citation": 6, "supplement": 5, "documentation": 4, "other": 3, "version-or-part": 2, "similarity": 1}
COUNTED_CLASSES = {"citation", "supplement"}
# Classes for which "the work pre-dates the dataset" means the link is doubtful.
USE_CLASSES = {"citation", "supplement", "documentation", "other"}


def canonical(relation: str | None) -> str | None:
    """A relation name in the DataCite vocabulary, however it was spelled.

    Args:
        relation: A relation such as ``"is-referenced-by"``, ``"isreferencedby"``
            or ``"IsReferencedBy"``.

    Returns:
        The DataCite CamelCase name (``"IsReferencedBy"``), or None when the
        relation is empty or unknown.
    """
    if not relation:
        return None
    key = re.sub(r"[^a-z]", "", str(relation).lower())
    return VOCABULARY.get(key)


def dataset_side(relation: str | None, dataset_is: str) -> str | None:
    """A relation as it applies to the dataset.

    Every relation is stated subject to object. If the dataset is the subject the
    relation is already dataset-side; if it is the object, the relation is
    inverted (``Cites`` becomes ``IsCitedBy``).

    Args:
        relation: The relation as the source stated it, in any spelling.
        dataset_is: ``"subject"`` or ``"object"``: where the dataset sits.

    Returns:
        The dataset-side relation in the DataCite vocabulary, or None when the
        relation is unknown.

    Raises:
        ValueError: If `dataset_is` is neither ``"subject"`` nor ``"object"``.
    """
    name = canonical(relation)
    if name is None:
        return None
    if dataset_is == "subject":
        return name
    if dataset_is == "object":
        return INVERSE.get(name)
    raise ValueError(f"dataset_is must be 'subject' or 'object', not {dataset_is!r}")


def relation_class(dataset_relation: str | None) -> str | None:
    """The class of a dataset-side relation.

    Args:
        dataset_relation: A relation from `dataset_side`.

    Returns:
        ``citation``, ``supplement``, ``documentation``, ``other``,
        ``version-or-part`` or ``similarity``; or None when the relation is
        outgoing (the dataset cites or derives from the other work).
    """
    if dataset_relation is None:
        return None
    return CLASS_OF.get(dataset_relation)


def is_incoming(dataset_relation: str | None) -> bool:
    """Whether a dataset-side relation is a link *to* the dataset.

    Args:
        dataset_relation: A relation from `dataset_side`.

    Returns:
        True when the relation has a class; False when it is outgoing or unknown.
    """
    return relation_class(dataset_relation) is not None


def to_kebab(name: str) -> str:
    """A DataCite relation name in the DataCite events API's spelling.

    Args:
        name: A CamelCase relation, such as ``"IsReferencedBy"``.

    Returns:
        The kebab-case form, such as ``"is-referenced-by"``.
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
