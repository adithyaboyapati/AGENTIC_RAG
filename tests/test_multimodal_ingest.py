"""Tests for Multimodal Ingestion (Tables and Figures)."""


from src.ingestion.multimodal import ExtractedFigure
from src.ingestion.tables import ExtractedTable, table_to_markdown


def test_table_to_markdown():
    raw_data = [
        ["Model", "Latency", "Score"],
        ["Baseline", "3.2s", "0.85"],
        ["CRAG", "8.5s", "0.95"],
    ]
    md = table_to_markdown(raw_data)
    expected_lines = [
        "| Model | Latency | Score |",
        "| --- | --- | --- |",
        "| Baseline | 3.2s | 0.85 |",
        "| CRAG | 8.5s | 0.95 |",
    ]
    assert md == "\n".join(expected_lines)


def test_table_to_markdown_handles_ragged_rows():
    raw_data = [
        ["Header A", "Header B"],
        ["Only one cell"],
        ["Col 1", "Col 2", "Extra ignored col"],
    ]
    md = table_to_markdown(raw_data)
    assert "| Header A | Header B |" in md
    assert "| Only one cell |  |" in md
    assert "| Col 1 | Col 2 |" in md


def test_extracted_table_to_document():
    tbl = ExtractedTable(
        table_id="tbl123",
        page=2,
        bbox=(50.0, 100.0, 500.0, 300.0),
        num_rows=3,
        num_cols=2,
        markdown="| A | B |\n|---|---|\n| 1 | 2 |",
        caption="Table 1: Performance Benchmarks",
    )

    doc = tbl.to_document(source="eval_report.pdf", section_path="3. Results")
    assert doc.metadata["chunk_type"] == "table"
    assert doc.metadata["page"] == 3  # 1-indexed
    assert doc.metadata["table_id"] == "tbl123"
    assert doc.metadata["section_path"] == "3. Results"
    assert "Table (Table 1: Performance Benchmarks):" in doc.page_content
    assert "| A | B |" in doc.page_content


def test_extracted_figure_to_document():
    fig = ExtractedFigure(
        figure_id="fig456",
        page=4,
        bbox=(40.0, 80.0, 450.0, 320.0),
        caption="Figure 2: Architecture of CRAG",
        description="Flowchart of routing and evaluator node.",
    )

    doc = fig.to_document(source="crag_paper.pdf", section_path="2. Architecture")
    assert doc.metadata["chunk_type"] == "figure"
    assert doc.metadata["page"] == 5
    assert doc.metadata["figure_id"] == "fig456"
    assert "Figure 2: Architecture of CRAG" in doc.page_content
    assert "Flowchart of routing" in doc.page_content
