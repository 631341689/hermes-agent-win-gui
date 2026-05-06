"""Regression: smart segmenter must not spin on LaTeX lines with ``|``."""

from hermes_cli.knowledge_text import _segment_block_smart, chunk_structure_smart


def test_segment_single_pipe_heavy_latex_line_not_infinite_loop():
    block = (
        "Some prose.\n"
        "A _ { \\mathrm { f u s e d } } = { \\frac { 1 } { | \\vartheta | } } "
        "\\sum _ { k \\in \\vartheta } { \\mathrm { S o f t m a x } }\n"
        "More prose after.\n"
    )
    segs = _segment_block_smart(block)
    assert len(segs) >= 2
    joined = "".join(segs)
    assert "|" in joined
    assert "More prose" in joined


def test_chunk_structure_smart_icvrv_like_block_completes():
    text = "## Methods\n" + (
        "Intro paragraph.\n\n"
        "$$\n"
        "A = \\frac{1}{|\\vartheta|} \\sum_k \\mathrm{Softmax}\\left(\\frac{A^k}{\\sqrt{d}}\\right)\\tag{5}\n"
        "$$\n\n"
        "Following text.\n"
    )
    chunks = chunk_structure_smart(text, max_chars=2000, overlap_chars=64)
    assert len(chunks) >= 1
    assert "Following text" in "\n".join(chunks)
