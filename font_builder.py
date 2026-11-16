"""Append CJK SDF glyphs to ROB RUN's existing static TMP fallback font.

Only writes the requested output bundle. Dependencies: UnityPy and Pillow.
"""
from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont
import UnityPy


FALLBACK_NAME = "LibertinusSerifDisplay-Regular SDF"


def _edt_line(values):
    """Squared Euclidean distance transform of one row (lower envelopes)."""
    n = len(values)
    vertices = [0] * n
    cuts = [-math.inf] + [math.inf] * n
    result = [0.0] * n
    last = 0
    for q in range(1, n):
        p = vertices[last]
        cut = ((values[q] + q*q) - (values[p] + p*p)) / (2*(q-p))
        while cut <= cuts[last]:
            last -= 1
            p = vertices[last]
            cut = ((values[q] + q*q) - (values[p] + p*p)) / (2*(q-p))
        last += 1
        vertices[last] = q
        cuts[last] = cut
        cuts[last+1] = math.inf
    last = 0
    for q in range(n):
        while cuts[last+1] < q:
            last += 1
        p = vertices[last]
        result[q] = (q-p)*(q-p) + values[p]
    return result


def _distances(mask, foreground):
    w, h = mask.size
    pixels = list(mask.getdata())
    rows = [_edt_line([0 if (x >= 128) == foreground else 1e9
                       for x in pixels[y*w:(y+1)*w]]) for y in range(h)]
    result = [0.0] * (w*h)
    for x in range(w):
        column = _edt_line([rows[y][x] for y in range(h)])
        for y in range(h):
            result[y*w+x] = column[y]
    return result


def _sdf(mask, padding):
    to_ink = _distances(mask, True)
    to_air = _distances(mask, False)
    result = bytearray(len(to_ink))
    for i, (a, b) in enumerate(zip(to_air, to_ink)):
        distance = math.sqrt(a) - math.sqrt(b)
        distance -= 0.5 if distance > 0 else -0.5
        result[i] = max(0, min(255, round(127.5 + distance * 127.5/(padding+1))))
    image = Image.new("L", mask.size)
    image.frombytes(bytes(result))
    return image


def patch_font(source_bundle: Path, output_bundle: Path, characters: str,
               font_path: Path) -> dict:
    source_bundle, output_bundle, font_path = map(Path, (source_bundle, output_bundle, font_path))
    if source_bundle.resolve() == output_bundle.resolve():
        raise ValueError("Source and output must be different files")
    env = UnityPy.load(str(source_bundle))
    objects = {o.path_id: o for o in env.objects}
    fonts = [(o, o.read_typetree()) for o in env.objects if o.type.name == "MonoBehaviour"]
    fonts = [(o, t) for o, t in fonts if "m_AtlasPopulationMode" in t]
    candidates = [(o, t) for o, t in fonts if t.get("m_Name") == FALLBACK_NAME]
    if len(candidates) != 1:
        raise ValueError("Expected ROB RUN's single Libertinus TMP font asset")
    fallback_obj, tree = candidates[0]
    existing = {c["m_Unicode"] for c in tree["m_CharacterTable"]}
    requested = sorted({ord(c) for c in characters if ord(c) >= 0x2000} - existing)
    if not requested:
        raise ValueError("No new CJK or punctuation characters were supplied")
    # Keep atlas texels, glyph metrics and SDF padding in the same face units.
    size = round(float(tree["m_FaceInfo"]["m_PointSize"]))
    padding = int(tree["m_AtlasPadding"])
    cell = size + padding*2 + 4
    texture_obj = objects[tree["m_AtlasTextures"][0]["m_PathID"]]
    texture = texture_obj.read()
    original = texture.image
    old_w, old_h = original.size
    atlas_size = 2048
    while True:
        positions = [(x, y) for y in range(0, atlas_size-cell+1, cell)
                     for x in range(0, atlas_size-cell+1, cell)
                     if x >= old_w or y >= old_h]
        if len(positions) >= len(requested):
            break
        atlas_size *= 2
        if atlas_size > 8192:
            raise ValueError("Too many characters for a single 8192 TMP atlas")
    atlas = Image.new("L", (atlas_size, atlas_size), 0)
    alpha = original.getchannel("A") if "A" in original.getbands() else original.convert("L")
    atlas.paste(alpha, (0, atlas_size-old_h))
    font = ImageFont.truetype(str(font_path), size)
    try:
        axes = font.get_variation_axes()
        font.set_variation_by_axes([min(axis["maximum"], max(axis["minimum"], 500))
                                    if axis["name"] == b"Weight" else axis["default"]
                                    for axis in axes])
    except OSError:  # Static TTF fonts do not expose variation axes.
        pass
    glyph_id = max(g["m_Index"] for g in tree["m_GlyphTable"]) + 1
    glyph_scale = float(tree["m_FaceInfo"]["m_PointSize"]) / size
    added_rects = []
    for codepoint, (x, y) in zip(requested, positions):
        character = chr(codepoint)
        left, top, right, bottom = font.getbbox(character, anchor="ls")
        width, height = right-left, bottom-top
        if width + 2*padding > cell or height + 2*padding > cell:
            raise ValueError(f"Glyph U+{codepoint:04X} exceeds the atlas cell")
        mask = Image.new("L", (width+2*padding, height+2*padding), 0)
        ImageDraw.Draw(mask).text((padding-left, padding-top), character,
                                 font=font, fill=255, anchor="ls")
        sdf = _sdf(mask, padding)
        atlas.paste(sdf, (x, atlas_size-y-sdf.height))
        rect = {"m_X": x+padding, "m_Y": y+padding,
                "m_Width": width, "m_Height": height}
        tree["m_GlyphTable"].append({
            "m_Index": glyph_id,
            # TMP uses Glyph.scale for rendered line bounds but omits it in
            # part of preferred-size calculation. Store metrics in face units.
            "m_Metrics": {"m_Width": float(width) * glyph_scale,
                          "m_Height": float(height) * glyph_scale,
                          "m_HorizontalBearingX": float(left) * glyph_scale,
                          "m_HorizontalBearingY": float(-top) * glyph_scale,
                          "m_HorizontalAdvance": float(font.getlength(character)) * glyph_scale},
            "m_GlyphRect": rect, "m_Scale": 1.0,
            "m_AtlasIndex": 0, "m_ClassDefinitionType": 0})
        tree["m_CharacterTable"].append({"m_ElementType": 1, "m_Unicode": codepoint,
                                          "m_GlyphIndex": glyph_id, "m_Scale": 1.0})
        added_rects.append({"m_X": x, "m_Y": y, "m_Width": cell, "m_Height": cell})
        glyph_id += 1
    tree["m_CharacterTable"].sort(key=lambda c: c["m_Unicode"])
    tree["m_AtlasWidth"] = tree["m_AtlasHeight"] = atlas_size
    tree["m_CreationSettings"]["atlasWidth"] = atlas_size
    tree["m_CreationSettings"]["atlasHeight"] = atlas_size
    tree["m_UsedGlyphRects"].extend(added_rects)
    tree["m_FreeGlyphRects"] = []
    fallback_obj.save_typetree(tree)
    texture.set_image(Image.merge("RGBA", [Image.new("L", atlas.size, 255)]*3+[atlas]), target_format=1)
    texture.save()
    material = objects[tree["m_Material"]["m_PathID"]]
    material_tree = material.read_typetree()
    material_tree["m_SavedProperties"]["m_Floats"] = [
        (name, float(atlas_size) if name in ("_TextureWidth", "_TextureHeight") else value)
        for name, value in material_tree["m_SavedProperties"]["m_Floats"]]
    material.save_typetree(material_tree)
    patched_fonts = []
    for font_obj, font_tree in fonts:
        if font_obj.path_id == fallback_obj.path_id:
            continue
        references = font_tree["m_FallbackFontAssetTable"]
        if not any(ref["m_FileID"] == 0 and ref["m_PathID"] == fallback_obj.path_id for ref in references):
            references.append({"m_FileID": 0, "m_PathID": fallback_obj.path_id})
            font_obj.save_typetree(font_tree)
        patched_fonts.append(font_tree["m_Name"])
    output_bundle.parent.mkdir(parents=True, exist_ok=True)
    output_bundle.write_bytes(env.file.save(packer="lz4"))
    # One read-back check verifies glyph serialization and preserves the old atlas.
    verify = UnityPy.load(str(output_bundle))
    verify_objects = {o.path_id: o for o in verify.objects}
    restored = verify_objects[fallback_obj.path_id].read_typetree()
    assert set(requested) <= {c["m_Unicode"] for c in restored["m_CharacterTable"]}
    glyphs = {g["m_Index"]: g for g in restored["m_GlyphTable"]}
    assert all(glyphs[c["m_GlyphIndex"]]["m_Scale"] == 1.0
               for c in restored["m_CharacterTable"] if c["m_Unicode"] in requested)
    rendered = verify_objects[texture_obj.path_id].read().image.getchannel("A")
    assert rendered.crop((0, atlas_size-old_h, old_w, atlas_size)).tobytes() == alpha.tobytes()
    return {"added_characters": len(requested), "atlas_size": atlas_size,
            "fallback_font": FALLBACK_NAME, "patched_fonts": patched_fonts,
            "output": str(output_bundle)}


def self_check():
    assert _edt_line([0, 1e9, 1e9, 0]) == [0, 1, 1, 0]
    mask = Image.new("L", (7, 7), 0)
    ImageDraw.Draw(mask).rectangle((2, 2, 4, 4), fill=255)
    sdf = _sdf(mask, 2)
    assert sdf.getpixel((3, 3)) > 127 > sdf.getpixel((0, 0))


if __name__ == "__main__":
    self_check()
    print("Font SDF self-check passed")
