"""Pruebas de Fase 0: Extractor Multimodal con respaldo OCR y compatibilidad FileParser."""

import io
import zipfile
from pathlib import Path

from app.services.multimodal_extractor import MultimodalExtractor
from app.utils.file_parser import FileParser


ROOT_DIR = Path(__file__).resolve().parents[2]
NEXO_FILES_DIR = ROOT_DIR / "backend" / "uploads" / "projects" / "proj_047fbadfa161" / "files"


def test_multimodal_extractor_handles_visual_pdf_da66e131():
    target = NEXO_FILES_DIR / "da66e131.pdf"
    assert target.exists(), f"No se encontró {target}"

    doc = MultimodalExtractor.extract(str(target))
    assert doc.char_count >= 200
    assert len(doc.text.strip()) >= 200
    assert doc.extraction_method != "pymupdf_empty"
    assert len(doc.pages) == 1

    via_file_parser = FileParser.extract_text(str(target))
    assert len(via_file_parser) >= 200


def test_multimodal_extractor_preserves_native_nexo_pdfs():
    for fname in ("fe5cd7ba.pdf", "3973ab26.pdf"):
        target = NEXO_FILES_DIR / fname
        assert target.exists(), f"No se encontró {target}"
        doc = MultimodalExtractor.extract(str(target))
        assert doc.char_count > 500
        assert "pymupdf_text" in doc.extraction_method


def test_multimodal_extractor_supports_csv_json_and_docx(tmp_path):
    csv_file = tmp_path / "precios.csv"
    csv_file.write_text("Ciudad,Estrato,Precio\nBogotá,3,70000\nCali,2,45000\n", encoding="utf-8")
    csv_doc = MultimodalExtractor.extract(str(csv_file))
    assert "| Ciudad | Estrato | Precio |" in csv_doc.text
    assert len(csv_doc.tables_markdown) == 1

    json_file = tmp_path / "nota.json"
    json_file.write_text('{"empresa": "Prospéctica", "pais": "co"}', encoding="utf-8")
    json_doc = MultimodalExtractor.extract(str(json_file))
    assert "Prospéctica" in json_doc.text

    docx_file = tmp_path / "brief.docx"
    with zipfile.ZipFile(docx_file, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Brief de mercado Colombia</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    docx_doc = MultimodalExtractor.extract(str(docx_file))
    assert "Brief de mercado Colombia" in docx_doc.text
