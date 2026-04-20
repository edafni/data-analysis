"""Analysis helpers for the data overview Streamlit app.

All functions accept a pandas ``DataFrame`` and return plain Python
structures (dict / list / DataFrame) so the UI layer stays thin.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DATE_NAME_HINTS = ("date", "time", "timestamp", "datetime", "תאריך")
EMAIL_NAME_HINTS = ("email", "mail", "אימייל", "מייל")
PHONE_NAME_HINTS = ("phone", "mobile", "tel", "טלפון", "נייד")
NUMERIC_NAME_HINTS = (
    "price", "amount", "qty", "quantity", "count", "age",
    "salary", "score", "rate", "sum", "total", "id",
    "מחיר", "סכום", "כמות", "גיל",
)


# ---------------------------------------------------------------------------
# Basic overview
# ---------------------------------------------------------------------------

def basic_overview(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "num_rows": int(df.shape[0]),
        "num_cols": int(df.shape[1]),
        "memory_bytes": int(df.memory_usage(deep=True).sum()),
        "duplicate_rows": int(df.duplicated().sum()),
        "total_missing_cells": int(df.isna().sum().sum()),
        "total_cells": int(df.size),
    }


# ---------------------------------------------------------------------------
# Per-column summary
# ---------------------------------------------------------------------------

def column_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = len(df)
    for col in df.columns:
        s = df[col]
        non_null = int(s.notna().sum())
        null = total - non_null
        sample = s.dropna().head(3).astype(str).tolist()
        rows.append({
            "column": col,
            "dtype": str(s.dtype),
            "non_null": non_null,
            "null": null,
            "null_%": round((null / total * 100) if total else 0, 2),
            "unique": int(s.nunique(dropna=True)),
            "sample_values": ", ".join(sample),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Type-mismatch validations
# ---------------------------------------------------------------------------

def _name_matches(col_name: str, hints: tuple[str, ...]) -> bool:
    name = str(col_name).lower()
    return any(h in name for h in hints)


def _bad_examples(series: pd.Series, mask: pd.Series, limit: int = 5) -> list[str]:
    bad = series[mask].dropna().astype(str).head(limit).tolist()
    return bad


def validate_types(df: pd.DataFrame) -> pd.DataFrame:
    """Detect values that don't match the type implied by the column name.

    Returns a DataFrame with one row per detected issue.
    """
    issues: list[dict[str, Any]] = []

    for col in df.columns:
        s = df[col]
        non_null = s.dropna()
        if non_null.empty:
            continue

        expected: str | None = None
        mismatch_mask: pd.Series | None = None

        if _name_matches(col, DATE_NAME_HINTS):
            expected = "date/datetime"
            if not pd.api.types.is_datetime64_any_dtype(s):
                parsed = pd.to_datetime(non_null, errors="coerce")
                bad = parsed.isna()
                if not bad.any():
                    issues.append({
                        "column": col,
                        "expected_type": expected,
                        "bad_count": 0,
                        "bad_%": 0.0,
                        "example_bad_values": (
                            f"(dtype is {s.dtype}; all values parse, "
                            "but column should be converted to datetime)"
                        ),
                        "example_rows": "-",
                    })
                    continue
                mismatch_mask = pd.Series(False, index=s.index)
                mismatch_mask.loc[parsed.index[bad]] = True

        elif _name_matches(col, EMAIL_NAME_HINTS):
            expected = "email"
            str_vals = non_null.astype(str).str.strip()
            valid = str_vals.apply(lambda v: bool(EMAIL_RE.match(v)))
            mismatch_mask = pd.Series(False, index=s.index)
            mismatch_mask.loc[valid.index[~valid]] = True

        elif _name_matches(col, PHONE_NAME_HINTS):
            expected = "phone (7-15 digits)"
            digit_counts = non_null.astype(str).str.replace(r"\D", "", regex=True).str.len()
            valid = digit_counts.between(7, 15)
            mismatch_mask = pd.Series(False, index=s.index)
            mismatch_mask.loc[valid.index[~valid]] = True

        elif _name_matches(col, NUMERIC_NAME_HINTS):
            expected = "numeric"
            if not pd.api.types.is_numeric_dtype(s):
                parsed = pd.to_numeric(non_null, errors="coerce")
                mismatch_mask = pd.Series(False, index=s.index)
                mismatch_mask.loc[parsed.isna().index[parsed.isna()]] = True

        elif s.dtype == object:
            numeric_parsed = pd.to_numeric(non_null, errors="coerce")
            numeric_ratio = numeric_parsed.notna().mean()
            if numeric_ratio >= 0.8 and numeric_ratio < 1.0:
                expected = "numeric (inferred)"
                mismatch_mask = pd.Series(False, index=s.index)
                mismatch_mask.loc[numeric_parsed.index[numeric_parsed.isna()]] = True

        if expected is None or mismatch_mask is None:
            continue

        bad_count = int(mismatch_mask.sum())
        if bad_count == 0:
            continue

        examples = _bad_examples(s, mismatch_mask)
        bad_indices = s.index[mismatch_mask].tolist()[:5]

        issues.append({
            "column": col,
            "expected_type": expected,
            "bad_count": bad_count,
            "bad_%": round(bad_count / len(s) * 100, 2),
            "example_bad_values": ", ".join(examples) if examples else "(all null)",
            "example_rows": ", ".join(str(i) for i in bad_indices),
        })

    return pd.DataFrame(issues)


# ---------------------------------------------------------------------------
# Special-character detection
# ---------------------------------------------------------------------------

CURRENCY_CHARS = "$€£¥₪"
STRAY_CHARS = "*#@"


def check_special_characters(df: pd.DataFrame) -> pd.DataFrame:
    """Flag object-dtype columns whose values contain contaminating
    non-alphanumeric characters (currency symbols, percent signs,
    thousand-separator commas, stray symbols like ``*``/``#``/``@``).
    """
    issues: list[dict[str, Any]] = []

    for col in df.columns:
        s = df[col]
        if s.dtype != object:
            continue
        str_s = s.dropna().astype(str)
        if str_s.empty:
            continue

        found_chars: dict[str, int] = {}
        affected_mask = pd.Series(False, index=str_s.index)

        for ch in CURRENCY_CHARS:
            mask = str_s.str.contains(re.escape(ch), regex=True)
            n = int(mask.sum())
            if n:
                found_chars[ch] = n
                affected_mask |= mask

        pct_mask = str_s.str.contains("%", regex=False)
        if pct_mask.any():
            found_chars["%"] = int(pct_mask.sum())
            affected_mask |= pct_mask

        thousand_mask = str_s.str.contains(r"\d,\d", regex=True)
        if thousand_mask.any():
            found_chars[", (thousand separator)"] = int(thousand_mask.sum())
            affected_mask |= thousand_mask

        for ch in STRAY_CHARS:
            mask = str_s.str.contains(re.escape(ch), regex=True)
            n = int(mask.sum())
            if n:
                found_chars[ch] = n
                affected_mask |= mask

        if not found_chars:
            continue

        affected_count = int(affected_mask.sum())
        examples = str_s[affected_mask].head(3).tolist()

        issues.append({
            "column": col,
            "chars_found": ", ".join(f"{c} (x{n})" for c, n in found_chars.items()),
            "affected_rows": affected_count,
            "affected_%": round(affected_count / len(s) * 100, 2),
            "example_values": ", ".join(repr(v) for v in examples),
        })

    return pd.DataFrame(issues)


# ---------------------------------------------------------------------------
# Pattern-consistency detection
# ---------------------------------------------------------------------------

def _value_pattern(v: Any) -> str:
    """Convert a value into a shape pattern: digits -> 9, letters -> A,
    punctuation and whitespace preserved as-is."""
    out = []
    for ch in str(v):
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A")
        else:
            out.append(ch)
    return "".join(out)


def check_pattern_consistency(
    df: pd.DataFrame,
    min_dominance: float = 0.9,
    min_values: int = 10,
) -> pd.DataFrame:
    """Flag object columns where one pattern dominates (>= ``min_dominance``)
    but a minority of values have a different shape — e.g. 99% ``9-99999``
    and 1% ``9999999``.
    """
    issues: list[dict[str, Any]] = []

    for col in df.columns:
        s = df[col]
        if s.dtype != object:
            continue
        str_s = s.dropna().astype(str)
        if len(str_s) < min_values:
            continue

        patterns = str_s.map(_value_pattern)
        counts = patterns.value_counts()
        if len(counts) < 2:
            continue

        dominant_pattern = counts.index[0]
        dominant_count = int(counts.iloc[0])
        dominance = dominant_count / len(str_s)

        if dominance < min_dominance:
            continue

        odd_mask = patterns != dominant_pattern
        odd_patterns = counts.iloc[1:].head(3)
        odd_examples = str_s[odd_mask].head(3).tolist()
        odd_indices = str_s.index[odd_mask].tolist()[:3]

        issues.append({
            "column": col,
            "dominant_pattern": dominant_pattern,
            "dominant_%": round(dominance * 100, 2),
            "odd_patterns": ", ".join(
                f"{p!r} (x{c})" for p, c in odd_patterns.items()
            ),
            "example_odd_values": ", ".join(repr(v) for v in odd_examples),
            "example_rows": ", ".join(str(i) for i in odd_indices),
        })

    return pd.DataFrame(issues)


# ---------------------------------------------------------------------------
# Data quality checks
# ---------------------------------------------------------------------------

def data_quality(df: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}

    dup_mask = df.duplicated(keep=False)
    result["duplicate_rows_total"] = int(dup_mask.sum())
    result["duplicate_row_indices"] = df.index[dup_mask].tolist()[:10]

    empty_cols = [c for c in df.columns if df[c].isna().all()]
    constant_cols = [
        c for c in df.columns
        if df[c].nunique(dropna=True) <= 1 and c not in empty_cols
    ]
    result["empty_columns"] = empty_cols
    result["constant_columns"] = constant_cols

    whitespace_issues = []
    casing_issues = []
    for col in df.columns:
        s = df[col]
        if s.dtype != object:
            continue
        str_s = s.dropna().astype(str)
        if str_s.empty:
            continue

        ws_mask = str_s != str_s.str.strip()
        ws_count = int(ws_mask.sum())
        if ws_count:
            whitespace_issues.append({
                "column": col,
                "count": ws_count,
                "examples": ", ".join(
                    repr(v) for v in str_s[ws_mask].head(3).tolist()
                ),
            })

        normalized = str_s.str.strip().str.lower()
        groups = (
            pd.DataFrame({"orig": str_s, "norm": normalized})
            .groupby("norm")["orig"]
            .nunique()
        )
        conflicts = groups[groups > 1]
        if not conflicts.empty:
            examples_parts = []
            for norm_val in conflicts.index[:3]:
                variants = str_s[normalized == norm_val].unique().tolist()
                examples_parts.append(
                    f"{norm_val!r} -> {variants[:4]}"
                )
            casing_issues.append({
                "column": col,
                "conflicting_groups": int(len(conflicts)),
                "examples": "; ".join(examples_parts),
            })

    result["whitespace_issues"] = whitespace_issues
    result["casing_issues"] = casing_issues

    outliers = []
    for col in df.select_dtypes(include=[np.number]).columns:
        s = df[col].dropna()
        if len(s) < 4:
            continue
        q1, q3 = s.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            continue
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        mask = (s < low) | (s > high)
        count = int(mask.sum())
        if count:
            outliers.append({
                "column": col,
                "count": count,
                "lower_bound": float(low),
                "upper_bound": float(high),
                "min_flagged": float(s[mask].min()),
                "max_flagged": float(s[mask].max()),
            })
    result["outliers"] = outliers

    return result


# ---------------------------------------------------------------------------
# Per-column statistics
# ---------------------------------------------------------------------------

def column_statistics(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return three DataFrames: numeric, categorical, datetime stats."""

    numeric_rows = []
    for col in df.select_dtypes(include=[np.number]).columns:
        s = df[col].dropna()
        if s.empty:
            continue
        numeric_rows.append({
            "column": col,
            "min": float(s.min()),
            "q1": float(s.quantile(0.25)),
            "median": float(s.median()),
            "mean": float(s.mean()),
            "q3": float(s.quantile(0.75)),
            "max": float(s.max()),
            "std": float(s.std()) if len(s) > 1 else 0.0,
        })

    categorical_rows = []
    for col in df.select_dtypes(include=["object", "category", "bool"]).columns:
        s = df[col].dropna()
        if s.empty:
            continue
        top = s.value_counts().head(5)
        top_str = ", ".join(f"{v!r} ({c})" for v, c in top.items())
        categorical_rows.append({
            "column": col,
            "unique": int(s.nunique()),
            "top_5": top_str,
        })

    datetime_rows = []
    for col in df.select_dtypes(include=["datetime", "datetimetz"]).columns:
        s = df[col].dropna()
        if s.empty:
            continue
        datetime_rows.append({
            "column": col,
            "min": str(s.min()),
            "max": str(s.max()),
            "range_days": int((s.max() - s.min()).days),
        })

    return {
        "numeric": pd.DataFrame(numeric_rows),
        "categorical": pd.DataFrame(categorical_rows),
        "datetime": pd.DataFrame(datetime_rows),
    }


# ---------------------------------------------------------------------------
# Auto descriptions per column
# ---------------------------------------------------------------------------

def _infer_role(col: str) -> str | None:
    if _name_matches(col, DATE_NAME_HINTS):
        return "date/datetime"
    if _name_matches(col, EMAIL_NAME_HINTS):
        return "email"
    if _name_matches(col, PHONE_NAME_HINTS):
        return "phone"
    if _name_matches(col, NUMERIC_NAME_HINTS):
        return "numeric"
    return None


def describe_columns(df: pd.DataFrame) -> dict[str, str]:
    """Produce a one-sentence description for every column."""
    descriptions: dict[str, str] = {}
    total = len(df)

    for col in df.columns:
        s = df[col]
        non_null = s.dropna()
        null_count = total - len(non_null)
        unique = int(non_null.nunique())
        role = _infer_role(col)

        if non_null.empty:
            descriptions[col] = "Empty column (all values are null)."
            continue

        if pd.api.types.is_datetime64_any_dtype(s):
            parts = [
                f"Datetime column, range {non_null.min()} to {non_null.max()}",
                f"{unique} unique values",
            ]

        elif pd.api.types.is_bool_dtype(s):
            top = non_null.value_counts()
            parts = [
                f"Boolean column ({dict(top)})",
            ]

        elif pd.api.types.is_numeric_dtype(s):
            parts = [
                f"Numeric column ({s.dtype})",
                f"range {non_null.min():g}\u2013{non_null.max():g}",
                f"{unique} unique values",
            ]

        else:
            str_s = non_null.astype(str)
            if role == "date/datetime":
                parsed = pd.to_datetime(non_null, errors="coerce")
                bad = int(parsed.isna().sum())
                good = int(parsed.notna().sum())
                piece = (
                    f"Date-like text column; {good} parseable"
                )
                if good:
                    piece += (
                        f" ({parsed.min().date()} \u2192 {parsed.max().date()})"
                    )
                if bad:
                    piece += f", {bad} unparseable"
                parts = [piece, f"{unique} unique values"]

            elif role == "email":
                valid = str_s.str.strip().apply(lambda v: bool(EMAIL_RE.match(v)))
                parts = [
                    "Email column",
                    f"{int(valid.sum())} valid / {int((~valid).sum())} invalid",
                    f"{unique} unique values",
                ]

            elif role == "phone":
                digits = str_s.str.replace(r"\D", "", regex=True).str.len()
                valid = digits.between(7, 15)
                parts = [
                    "Phone column",
                    f"{int(valid.sum())} valid / {int((~valid).sum())} invalid",
                    f"{unique} unique values",
                ]

            elif role == "numeric":
                parsed = pd.to_numeric(non_null, errors="coerce")
                good = int(parsed.notna().sum())
                bad = int(parsed.isna().sum())
                piece = f"Numeric-looking text column; {good} numeric"
                if good:
                    piece += (
                        f" (range {parsed.min():g}\u2013{parsed.max():g})"
                    )
                if bad:
                    piece += f", {bad} non-numeric"
                parts = [piece, f"{unique} unique values"]

            else:
                top = non_null.value_counts().head(1)
                if not top.empty:
                    top_val, top_count = top.index[0], int(top.iloc[0])
                    parts = [
                        f"Text column with {unique} unique values",
                        f"most frequent: {top_val!r} (x{top_count})",
                    ]
                else:
                    parts = [f"Text column with {unique} unique values"]

        if null_count:
            parts.append(
                f"{null_count} null "
                f"({null_count / total * 100:.1f}%)"
            )

        descriptions[col] = "; ".join(parts) + "."

    return descriptions
