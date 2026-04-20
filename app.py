"""Streamlit app: upload a CSV/XLSX and get an automatic data overview."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from analyzer import (
    basic_overview,
    check_pattern_consistency,
    check_special_characters,
    column_statistics,
    column_summary,
    data_quality,
    describe_columns,
    validate_types,
)


st.set_page_config(
    page_title="Data Overview Analyzer",
    page_icon="📊",
    layout="wide",
)


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _read_csv(content: bytes) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1255"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.BytesIO(content), encoding="utf-8", encoding_errors="replace")


@st.cache_data(show_spinner=False)
def _list_sheets(content: bytes) -> list[str]:
    return pd.ExcelFile(io.BytesIO(content)).sheet_names


@st.cache_data(show_spinner=False)
def _read_excel(content: bytes, sheet: str) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(content), sheet_name=sheet)


def load_dataframe(uploaded_file) -> pd.DataFrame | None:
    name = uploaded_file.name.lower()
    content = uploaded_file.getvalue()

    if name.endswith(".csv"):
        return _read_csv(content)

    if name.endswith((".xlsx", ".xls")):
        sheets = _list_sheets(content)
        if len(sheets) > 1:
            sheet = st.selectbox("Select a sheet", sheets)
        else:
            sheet = sheets[0]
        return _read_excel(content, sheet)

    st.error(f"Unsupported file type: {uploaded_file.name}")
    return None


# ---------------------------------------------------------------------------
# Helpers for rendering
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    st.success(f"✓ {msg}")


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _highlight_issue_rows(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    def style_row(row):
        return ["background-color: #fde2e1; color: #7a1f1a"] * len(row)
    return df.style.apply(style_row, axis=1)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def render_overview(df: pd.DataFrame) -> None:
    info = basic_overview(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{info['num_rows']:,}")
    c2.metric("Columns", f"{info['num_cols']:,}")
    c3.metric("Duplicate rows", f"{info['duplicate_rows']:,}")
    c4.metric("Memory", _human_bytes(info["memory_bytes"]))

    missing_pct = (
        info["total_missing_cells"] / info["total_cells"] * 100
        if info["total_cells"] else 0
    )
    st.write(
        f"**Missing cells:** {info['total_missing_cells']:,} "
        f"({missing_pct:.2f}% of {info['total_cells']:,} total)"
    )


def render_columns(df: pd.DataFrame) -> None:
    st.subheader("Column details")
    summary = column_summary(df)
    descriptions = describe_columns(df)
    summary.insert(
        1,
        "description",
        summary["column"].map(descriptions).fillna(""),
    )
    st.dataframe(summary, use_container_width=True, hide_index=True)


def render_validations(df: pd.DataFrame) -> None:
    st.subheader("Type validations")
    st.caption(
        "Columns whose name suggests a specific type (date, email, phone, "
        "numeric...) are checked. Values that don't match are flagged. A "
        "date-named column whose dtype is still text is also reported."
    )
    issues = validate_types(df)
    if issues.empty:
        _ok("No type mismatches detected based on column names.")
    else:
        st.dataframe(
            _highlight_issue_rows(issues),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Special characters")
    st.caption(
        "Currency symbols ($ \u20ac \u00a3 \u00a5 \u20aa), percent signs, "
        "thousand-separator commas, and stray symbols (*, #, @) inside "
        "text columns are flagged \u2014 they usually indicate values that "
        "need cleaning before numeric analysis."
    )
    special = check_special_characters(df)
    if special.empty:
        _ok("No suspicious special characters detected.")
    else:
        st.dataframe(
            _highlight_issue_rows(special),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Pattern anomalies")
    st.caption(
        "For each text column we build a shape pattern (digits \u2192 9, "
        "letters \u2192 A). If one pattern covers \u2265 90% of values, "
        "the rare outliers are flagged \u2014 e.g. 99% `9-99999` vs 1% `9999999`."
    )
    patterns = check_pattern_consistency(df)
    if patterns.empty:
        _ok("No pattern anomalies detected.")
    else:
        st.dataframe(
            _highlight_issue_rows(patterns),
            use_container_width=True,
            hide_index=True,
        )


def render_quality(df: pd.DataFrame) -> None:
    q = data_quality(df)

    st.subheader("Duplicates")
    if q["duplicate_rows_total"] == 0:
        _ok("No duplicate rows.")
    else:
        st.warning(
            f"{q['duplicate_rows_total']} duplicate rows. "
            f"First examples at indices: {q['duplicate_row_indices']}"
        )

    st.subheader("Empty / constant columns")
    if not q["empty_columns"] and not q["constant_columns"]:
        _ok("No empty or constant columns.")
    else:
        if q["empty_columns"]:
            st.warning(f"Empty columns (all null): {q['empty_columns']}")
        if q["constant_columns"]:
            st.warning(
                f"Constant columns (single value): {q['constant_columns']}"
            )

    st.subheader("Whitespace issues")
    if not q["whitespace_issues"]:
        _ok("No leading/trailing whitespace in text columns.")
    else:
        st.dataframe(
            _highlight_issue_rows(pd.DataFrame(q["whitespace_issues"])),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Inconsistent casing")
    if not q["casing_issues"]:
        _ok("No casing inconsistencies detected.")
    else:
        st.dataframe(
            _highlight_issue_rows(pd.DataFrame(q["casing_issues"])),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Numeric outliers (IQR rule)")
    if not q["outliers"]:
        _ok("No numeric outliers detected.")
    else:
        st.dataframe(
            pd.DataFrame(q["outliers"]),
            use_container_width=True,
            hide_index=True,
        )


def render_statistics(df: pd.DataFrame) -> None:
    stats = column_statistics(df)

    st.subheader("Numeric columns")
    if stats["numeric"].empty:
        st.caption("No numeric columns.")
    else:
        st.dataframe(stats["numeric"], use_container_width=True, hide_index=True)

    st.subheader("Text / categorical columns")
    if stats["categorical"].empty:
        st.caption("No text/categorical columns.")
    else:
        st.dataframe(
            stats["categorical"], use_container_width=True, hide_index=True
        )

    st.subheader("Datetime columns")
    if stats["datetime"].empty:
        st.caption("No datetime columns.")
    else:
        st.dataframe(stats["datetime"], use_container_width=True, hide_index=True)


def render_preview(df: pd.DataFrame) -> None:
    st.subheader("First 10 rows")
    st.dataframe(df.head(10), use_container_width=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("📊 Data Overview Analyzer")
    st.write(
        "Upload a **CSV** or **Excel** file and get an instant overview: "
        "shape, column types, validation issues, data quality, and statistics."
    )

    uploaded = st.file_uploader(
        "Upload a file", type=["csv", "xlsx", "xls"], accept_multiple_files=False
    )

    if uploaded is None:
        st.info("Waiting for a file...")
        return

    try:
        df = load_dataframe(uploaded)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the file: {exc}")
        return

    if df is None:
        return

    if df.empty:
        st.warning("The file was read but contains no data.")
        return

    st.success(
        f"Loaded **{uploaded.name}** — {df.shape[0]:,} rows × {df.shape[1]} columns"
    )

    tabs = st.tabs(
        ["Overview", "Columns", "Validations", "Data quality", "Statistics", "Preview"]
    )

    with tabs[0]:
        render_overview(df)
    with tabs[1]:
        render_columns(df)
    with tabs[2]:
        render_validations(df)
    with tabs[3]:
        render_quality(df)
    with tabs[4]:
        render_statistics(df)
    with tabs[5]:
        render_preview(df)


if __name__ == "__main__":
    main()
