# Parquet read/write for the intermediate results passed between pipeline stages
# (replaces the old .pkl files).
#
# The intermediate frames hold mixed Python values in object columns -- e.g.
# pub_authors is a list for some rows and a string ("Info not given") for others,
# and missing values are sometimes None and sometimes NaN. Parquet can't store
# mixed columns natively, and a native round trip would turn lists into numpy
# arrays and NaN into None, which changes how the merge step writes
# latest_results.csv/json. So every object column is stored as JSON text (one
# JSON document per cell) and decoded back to the same Python values on read.
# Numeric/bool columns are stored natively.

import json
import math

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Schema metadata key listing the columns stored as JSON text.
JSON_COLUMNS_KEY = b"citations_fun.json_columns"


def _to_json_native(value):
    """json.dumps default hook for numpy scalars/arrays."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Can't store {type(value).__name__} value in parquet: {value!r}")


def _encode(value):
    # Keep NaN distinct from None: json.dumps writes NaN as the token NaN.
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    return json.dumps(value, default=_to_json_native, ensure_ascii=False)


def write_parquet(df, path):
    """Write df to path, storing object columns as JSON text."""
    json_columns = [c for c in df.columns if df[c].dtype == object]
    encoded = df.copy()
    for c in json_columns:
        encoded[c] = pd.Series([_encode(v) for v in df[c]], index=df.index, dtype=object)

    # preserve_index=None keeps a RangeIndex as metadata and stores any other index
    table = pa.Table.from_pandas(encoded, preserve_index=None)
    metadata = dict(table.schema.metadata or {})
    metadata[JSON_COLUMNS_KEY] = json.dumps(json_columns).encode()
    pq.write_table(table.replace_schema_metadata(metadata), path)


def read_parquet(path):
    """Read a file written by write_parquet, decoding the JSON columns."""
    table = pq.read_table(path)
    metadata = table.schema.metadata or {}
    json_columns = json.loads(metadata.get(JSON_COLUMNS_KEY, b"[]"))

    df = table.to_pandas()
    for c in json_columns:
        # Build with dtype=object directly: Series.map would re-infer the dtype
        # and turn e.g. a column of ints and NaN into floats.
        df[c] = pd.Series([json.loads(v) for v in df[c]], index=df.index, dtype=object)
    return df
