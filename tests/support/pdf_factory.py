"""测试用 PDF 生成：手写最小 PDF，不引入额外依赖。"""

from __future__ import annotations

from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path: str | Path, pages: list[list[str]]) -> Path:
    """写一份每页若干行文字的最小 PDF，返回路径。

    文本用 Helvetica 逐行摆放，PDF 的文本层因此可以被 pdfplumber 抽出。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    objects: list[bytes] = []
    page_count = len(pages)
    # 对象编号：1=Catalog 2=Pages，然后每页一个 Page 与一个 Contents，末尾是 Font
    font_number = 3 + page_count * 2
    kids = " ".join(f"{4 + index * 2} 0 R" for index in range(page_count))

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii")
    )

    for lines in pages:
        body = ["BT", "/F1 12 Tf", "72 720 Td"]
        for index, line in enumerate(lines):
            if index:
                body.append("0 -20 Td")
            body.append(f"({_escape(line)}) Tj")
        body.append("ET")
        stream = "\n".join(body).encode("latin-1", errors="replace")
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {len(objects) + 2} 0 R "
                f"/Resources << /Font << /F1 {font_number} 0 R >> >> >>"
            ).encode("ascii")
        )
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")

    target.write_bytes(bytes(out))
    return target
