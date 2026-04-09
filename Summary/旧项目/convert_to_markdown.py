    #!/usr/bin/env python3
    """
    将 Word（.doc/.docx）和 PDF 文件批量转换为 Markdown。

    依赖：
        mammoth   — .docx → markdown（保留标题、列表、粗体等格式）
        pymupdf   — .pdf  → markdown
        markitdown— .doc  回退方案

    用法：
        .venv/bin/python convert_to_markdown.py
    """

    import subprocess
    import sys
    from pathlib import Path

    # ── 配置 ──────────────────────────────────────────────────────────────────────

    INPUT_DIRS = [
        "部处文档总结-十四五",
        "学发处工作总结",
    ]

    OUTPUT_DIR = "markdown_output"          # 统一输出根目录
    SUPPORTED_EXT = {".docx", ".doc", ".pdf"}

    # ── 转换函数 ──────────────────────────────────────────────────────────────────

    def convert_docx(path: Path) -> str:
        """使用 mammoth 将 .docx 转为 markdown，保留文档结构。"""
        import mammoth
        with open(path, "rb") as fh:
            result = mammoth.convert_to_markdown(fh)
        warnings = [str(m.message) for m in result.messages]
        if warnings:
            print(f"     mammoth 提示: {'; '.join(warnings[:3])}")
        return result.value


    def convert_pdf(path: Path) -> str:
        """使用 PyMuPDF 将 PDF 逐页提取为 markdown。"""
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        parts: list[str] = []
        for i, page in enumerate(doc, start=1):
            try:
                text = page.get_text("markdown")   # PyMuPDF 1.24+ 支持 markdown 模式
            except Exception:
                text = page.get_text("text")
            if text.strip():
                parts.append(f"<!-- 第 {i} 页 -->\n\n{text.strip()}")
        doc.close()
        return "\n\n---\n\n".join(parts)


    def convert_doc(path: Path) -> str:
        """
        .doc（Word 97-2003 二进制格式）转换策略（依次尝试）：
        1. markitdown
        2. antiword（命令行工具）
        3. catdoc（命令行工具）
        """
        # ① markitdown
        try:
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(str(path))
            content = result.text_content
            if content and content.strip():
                return content
        except Exception as e:
            print(f"     markitdown 失败: {e}")

        # ② antiword / catdoc
        for tool in ("antiword", "catdoc"):
            try:
                proc = subprocess.run(
                    [tool, str(path)],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout
            except FileNotFoundError:
                continue

        # ③ 降级提示
        return (
            f"> ⚠️ 无法自动解析 `{path.name}`（旧版 .doc 格式）。\n"
            "> 建议安装 LibreOffice 后运行：\n"
            "> ```\n"
            f"> soffice --headless --convert-to docx \"{path}\" --outdir \"{path.parent}\"\n"
            "> ```\n"
            "> 再重新执行本脚本。\n"
        )


    def convert_file(path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".docx":
            return convert_docx(path)
        elif ext == ".pdf":
            return convert_pdf(path)
        elif ext == ".doc":
            return convert_doc(path)
        else:
            raise ValueError(f"不支持的格式：{ext}")


    # ── 主流程 ────────────────────────────────────────────────────────────────────

    def main() -> None:
        base = Path(__file__).parent
        out_root = base / OUTPUT_DIR
        out_root.mkdir(exist_ok=True)

        ok, fail = 0, 0

        for dir_name in INPUT_DIRS:
            src_dir = base / dir_name
            if not src_dir.exists():
                print(f"⚠️  目录不存在，跳过：{dir_name}")
                continue

            files = sorted(
                f for f in src_dir.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
            )
            if not files:
                print(f"ℹ️  目录为空：{dir_name}")
                continue

            print(f"\n📁 {dir_name}  ({len(files)} 个文件)")
            out_sub = out_root / dir_name
            out_sub.mkdir(exist_ok=True)

            for fp in files:
                print(f"  📄 {fp.name} ...", end=" ", flush=True)
                try:
                    body = convert_file(fp)
                    content = f"# {fp.stem}\n\n{body}"
                    out_path = out_sub / (fp.stem + ".md")
                    out_path.write_text(content, encoding="utf-8")
                    rel = out_path.relative_to(base)
                    print(f"✅  →  {rel}")
                    ok += 1
                except Exception as exc:
                    print(f"❌  错误：{exc}")
                    fail += 1

        print(f"\n{'─'*50}")
        print(f"完成：{ok} 成功 / {fail} 失败")
        print(f"输出目录：{out_root}")


    if __name__ == "__main__":
        main()
