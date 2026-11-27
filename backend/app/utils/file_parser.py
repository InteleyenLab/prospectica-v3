"""
文件解析工具
支持PDF、Markdown、TXT文件的文本提取
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text_with_fallback(file_path: str) -> str:
    """Lee texto con detección multi-nivel de codificación."""
    from ..services.multimodal_extractor import read_text_with_fallback

    return read_text_with_fallback(file_path)


class FileParser:
    """Parser de documentos unificado con respaldo OCR multimodal."""

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".md",
        ".markdown",
        ".txt",
        ".csv",
        ".json",
        ".xlsx",
        ".docx",
    }

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        from ..services.multimodal_extractor import MultimodalExtractor

        return MultimodalExtractor.is_supported(file_path)

    @classmethod
    def extract_with_audit(cls, file_path: str) -> Dict[str, Any]:
        """Extrae texto y metadatos de auditoría por página."""
        from ..services.multimodal_extractor import MultimodalExtractor

        doc = MultimodalExtractor.extract(file_path)
        return {"text": doc.text, "audit": doc.to_audit_dict()}

    @classmethod
    def extract_text(cls, file_path: str) -> str:
        """Extrae el texto completo del documento (con respaldo OCR si aplica)."""
        from ..services.multimodal_extractor import MultimodalExtractor

        return MultimodalExtractor.extract(file_path).text

    @staticmethod
    def _extract_from_pdf(file_path: str) -> str:
        from ..services.multimodal_extractor import MultimodalExtractor

        return MultimodalExtractor.extract(file_path).text

    @staticmethod
    def _extract_from_md(file_path: str) -> str:
        return _read_text_with_fallback(file_path)

    @staticmethod
    def _extract_from_txt(file_path: str) -> str:
        return _read_text_with_fallback(file_path)
    
    @classmethod
    def extract_from_multiple(cls, file_paths: List[str]) -> str:
        """
        从多个文件提取文本并合并
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            合并后的文本
        """
        all_texts = []
        
        for i, file_path in enumerate(file_paths, 1):
            try:
                text = cls.extract_text(file_path)
                filename = Path(file_path).name
                all_texts.append(f"=== 文档 {i}: {filename} ===\n{text}")
            except Exception as e:
                all_texts.append(f"=== 文档 {i}: {file_path} (提取失败: {str(e)}) ===")
        
        return "\n\n".join(all_texts)


def split_text_into_chunks(
    text: str, 
    chunk_size: int = 500, 
    overlap: int = 50
) -> List[str]:
    """
    将文本分割成小块
    
    Args:
        text: 原始文本
        chunk_size: 每块的字符数
        overlap: 重叠字符数
        
    Returns:
        文本块列表
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # 尝试在句子边界处分割
        if end < len(text):
            # 查找最近的句子结束符
            for sep in ['。', '！', '？', '.\n', '!\n', '?\n', '\n\n', '. ', '! ', '? ']:
                last_sep = text[start:end].rfind(sep)
                if last_sep != -1 and last_sep > chunk_size * 0.3:
                    end = start + last_sep + len(sep)
                    break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # 下一个块从重叠位置开始
        start = end - overlap if end < len(text) else len(text)
    
    return chunks

