from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

CHINESE_SEPARATORS = ["\n\n", "\n", "。", "；", "，", " ", ""]


class DocumentParsingError(Exception):
    pass


def parse_document(path: Path, document_type: str) -> str:
    try:
        if document_type in {"markdown", "text", "faq"}:
            return path.read_text(encoding="utf-8-sig")
        if document_type == "pdf":
            reader = PdfReader(path)
            content = "\n".join(page.extract_text() or "" for page in reader.pages)
            if not content.strip():
                raise DocumentParsingError("PDF 中未提取到可用文本；扫描件暂不支持 OCR。")
            return content
    except OSError as error:
        raise DocumentParsingError("无法读取上传文件。") from error
    except Exception as error:
        if isinstance(error, DocumentParsingError):
            raise
        raise DocumentParsingError("文档解析失败。") from error
    raise DocumentParsingError("不支持的文档类型。")


def split_text(content: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    if not normalized:
        raise DocumentParsingError("文档内容为空。")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=CHINESE_SEPARATORS,
        keep_separator="end",
    )
    chunks = [chunk.strip() for chunk in splitter.split_text(normalized) if chunk.strip()]
    if not chunks:
        raise DocumentParsingError("文档内容为空。")
    return chunks
