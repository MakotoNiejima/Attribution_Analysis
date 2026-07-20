"""文本分块：按段落边界切分，保留来源信息。"""

from dataclasses import dataclass


@dataclass
class Chunk:
    """一个文本片段。"""
    text: str
    source_file: str          # 文件名（不含路径）
    source_detail: str = ""   # 页码/工作表/段落等位置信息
    chunk_index: int = 0      # 在文档内的序号

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "source_file": self.source_file,
            "source_detail": self.source_detail,
            "chunk_index": self.chunk_index,
        }


def chunk_text(
    text: str,
    source_file: str,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[Chunk]:
    """将文本按段落边界切分为多个 Chunk。

    Args:
        text: 待切分的纯文本
        source_file: 来源文件名
        chunk_size: 每个 chunk 的最大字符数
        overlap: 相邻 chunk 的重叠字符数

    Returns:
        Chunk 列表
    """
    if not text.strip():
        return []

    # 先按双换行分段
    paragraphs = text.split("\n\n")
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[Chunk] = []
    current_parts: list[str] = []
    current_len = 0
    chunk_idx = 0

    # 检测段落中的位置标记（如 [第2页]、[工作表: Sheet1]）
    def extract_detail(paragraph: str) -> str:
        for line in paragraph.split("\n"):
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                return line
        return ""

    current_detail = ""

    for para in paragraphs:
        para_len = len(para)

        # 如果单个段落就超过 chunk_size，强制切成多段
        if para_len > chunk_size:
            # 先把当前积累的内容保存
            if current_parts:
                chunks.append(Chunk(
                    text="\n\n".join(current_parts),
                    source_file=source_file,
                    source_detail=current_detail,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1
                current_parts = []
                current_len = 0

            # 按字符硬切
            for start in range(0, para_len, chunk_size - overlap):
                segment = para[start:start + chunk_size]
                detail = extract_detail(segment) or current_detail
                chunks.append(Chunk(
                    text=segment,
                    source_file=source_file,
                    source_detail=detail,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1
            current_detail = ""
            continue

        # 加入当前段落后是否超限
        new_len = current_len + para_len + (2 if current_parts else 0)  # \n\n 分隔符

        if new_len > chunk_size and current_parts:
            # 保存当前 chunk
            chunks.append(Chunk(
                text="\n\n".join(current_parts),
                source_file=source_file,
                source_detail=current_detail,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1

            # overlap：保留最后一个段落（如果够短）
            if current_parts and len(current_parts[-1]) <= overlap:
                current_parts = [current_parts[-1]]
                current_len = len(current_parts[0])
            else:
                current_parts = []
                current_len = 0

        detail = extract_detail(para)
        if detail:
            current_detail = detail

        current_parts.append(para)
        current_len = len("\n\n".join(current_parts))

    # 收尾
    if current_parts:
        chunks.append(Chunk(
            text="\n\n".join(current_parts),
            source_file=source_file,
            source_detail=current_detail,
            chunk_index=chunk_idx,
        ))

    return chunks
