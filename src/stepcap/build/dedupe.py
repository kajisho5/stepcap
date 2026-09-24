"""Detect consecutive identical screens so their screenshot can be reused.

Similarity = share of screen *area* that did not change. The screenshot is
downsampled to grayscale, split into a grid of blocks (about 45 px on a
1440 px wide screen) and a block counts as changed if any sample in it
changed noticeably. Measuring area rather than pixels keeps a white menu
opened over a white page from looking "identical". 1.0 means identical.
Only consecutive steps are merged; the step itself is always kept.
"""

from __future__ import annotations

from PIL import Image, ImageChops

DEFAULT_THRESHOLD = 0.98
SAMPLE_WIDTH = 320
PIXEL_TOLERANCE = 4  # 0-255 grayscale noise ignored (compression, subpixel AA)
BLOCK = 10  # block size in sample pixels


def _thumb(img: Image.Image) -> Image.Image:
    h = max(1, round(img.height * SAMPLE_WIDTH / img.width))
    return img.convert("L").resize((SAMPLE_WIDTH, h), Image.Resampling.BOX)


def similarity(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        return 0.0
    ta, tb = _thumb(a), _thumb(b)
    changed = ImageChops.difference(ta, tb).point(lambda v: 255 if v > PIXEL_TOLERANCE else 0)
    bw = max(1, -(-changed.width // BLOCK))
    bh = max(1, -(-changed.height // BLOCK))
    blocks = changed.resize((bw, bh), Image.Resampling.BOX)
    n_changed = sum(blocks.histogram()[1:])
    return 1.0 - n_changed / (bw * bh)


def group_consecutive(
    shot_ids: list[str | None],
    load,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, str]:
    """Map every screenshot id to the id that should be used for it.

    ``load(id) -> PIL.Image`` is called lazily. Screenshots are compared with
    the first screenshot of the current run of identical screens, so slow drift
    cannot chain many different screens together.
    """
    mapping: dict[str, str] = {}
    base_id: str | None = None
    base_thumb_src: Image.Image | None = None
    for sid in shot_ids:
        if sid is None:
            continue
        if sid in mapping:
            continue
        img = load(sid)
        if (
            base_thumb_src is not None
            and base_id is not None
            and img is not None
            and similarity(base_thumb_src, img) > threshold
        ):
            mapping[sid] = base_id
            continue
        mapping[sid] = sid
        base_id, base_thumb_src = sid, img
    return mapping
