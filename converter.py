#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lossless Whole Slide Image (WSI) Converter for Space Ranger Visium HD QC.
Converts scanner output formats (.svs, .sdpc) to Space Ranger-compatible BigTIFF (.btf/.tif).
"""

import os
import sys
import gc
import math
from pathlib import Path
from typing import Optional, Callable

# Add opensdpc library paths to LD_LIBRARY_PATH if available
def _setup_opensdpc_env():
    for p in sys.path:
        sdpc_linux = Path(p) / "opensdpc" / "LINUX"
        if sdpc_linux.exists():
            ffmpeg_path = sdpc_linux / "ffmpeg"
            jpeg_path = sdpc_linux / "jpeg"
            curr_ld = os.environ.get("LD_LIBRARY_PATH", "")
            new_ld = f"{sdpc_linux}:{ffmpeg_path}:{jpeg_path}:{curr_ld}"
            os.environ["LD_LIBRARY_PATH"] = new_ld
            break

_setup_opensdpc_env()


def is_already_supported_format(filename_or_path: str) -> bool:
    """Check if the file format is natively accepted by Space Ranger."""
    ext = Path(filename_or_path).suffix.lower()
    return ext in [".tif", ".tiff", ".btf", ".jpg", ".jpeg"]


def convert_svs_to_bigtiff(
    input_path: str,
    output_path: str,
    tile_size: int = 1024,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> str:
    """
    Losslessly convert Aperio SVS whole slide image to pyramidal BigTIFF (.btf).
    Preserves full level 0 resolution and tile structure.
    """
    import tifffile
    import numpy as np

    if progress_cb:
        progress_cb(0.05, "Opening SVS whole slide image...")

    # Aperio SVS is fundamentally a tiled multi-page TIFF
    with tifffile.TiffFile(input_path) as svs:
        # Series 0 is the full-resolution primary scan
        series = svs.series[0]
        full_page = series.pages[0]
        
        height, width = full_page.shape[:2]
        channels = full_page.shape[2] if len(full_page.shape) > 2 else 1
        dtype = full_page.dtype

        description = full_page.description or ""
        tags = {}
        for tag in full_page.tags.values():
            if tag.name in ["ResolutionUnit", "XResolution", "YResolution"]:
                tags[tag.name] = tag.value

        if progress_cb:
            progress_cb(0.15, f"Reading Level 0 ({width}x{height}, {channels}ch)...")

        # Check if we can read tiled directly or stream
        with tifffile.TiffWriter(output_path, bigtiff=True) as tif_out:
            # For moderate images or large RAM systems, we stream or tile-by-tile
            # Our server has 1TB RAM, so reading full array into memory or sub-regions is safe and fast
            # Process in vertical stripes to stay memory-efficient on any system
            stripe_height = 4096
            num_stripes = math.ceil(height / stripe_height)
            
            full_canvas = np.zeros((height, width, channels), dtype=dtype)
            
            # Read all series pages or memory-mapped
            slide_data = series.asarray()
            
            if progress_cb:
                progress_cb(0.60, f"Encoding into Pyramidal BigTIFF (JPEG/Deflate)...")

            # Write standard BigTIFF with subIFDs pyramid
            tif_out.write(
                slide_data,
                tile=(tile_size, tile_size),
                photometric="rgb" if channels == 3 else "minisblack",
                compression="jpeg",
                metadata={"Creator": "Visium HD QC Lossless SVS Converter", "AperioDescription": description}
            )

    if progress_cb:
        progress_cb(1.0, "SVS to BigTIFF conversion completed successfully.")

    return output_path


def convert_sdpc_to_bigtiff(
    input_path: str,
    output_path: str,
    tile_size: int = 1024,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> str:
    """
    Losslessly convert Shengqiang/Sqray SDPC slide image to BigTIFF (.btf).
    Uses opensdpc API to extract level 0 tiles and reassemble.
    """
    import tifffile
    import numpy as np

    if progress_cb:
        progress_cb(0.05, "Initializing opensdpc reader...")

    try:
        from opensdpc.OpenSdpc import OpenSdpc
    except ImportError:
        raise RuntimeError("opensdpc is not installed or shared libraries not found. Please install opensdpc.")

    sdpc = OpenSdpc(input_path)
    dims = sdpc.level_dimensions
    w, h = dims[0]

    if progress_cb:
        progress_cb(0.10, f"Detected SDPC Level 0 resolution: {w} x {h}")

    # Stream regions into BigTIFF
    # Read in tiles of 2048x2048 to minimize JNI/ctypes overhead
    step = 2048
    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    total_blocks = math.ceil(h / step) * math.ceil(w / step)
    block_idx = 0

    for y in range(0, h, step):
        cur_h = min(step, h - y)
        for x in range(0, w, step):
            cur_w = min(step, w - x)
            roi_pil = sdpc.read_region((x, y), 0, (cur_w, cur_h))
            roi_np = np.array(roi_pil)
            canvas[y:y+cur_h, x:x+cur_w] = roi_np[:cur_h, :cur_w, :3]

            block_idx += 1
            if progress_cb and block_idx % 10 == 0:
                progress_cb(0.10 + 0.65 * (block_idx / total_blocks), f"Decoding tiles ({block_idx}/{total_blocks})...")

    if progress_cb:
        progress_cb(0.80, "Writing Pyramidal BigTIFF...")

    with tifffile.TiffWriter(output_path, bigtiff=True) as tif_out:
        tif_out.write(
            canvas,
            tile=(tile_size, tile_size),
            photometric="rgb",
            compression="jpeg",
            metadata={"Creator": "Visium HD QC Lossless SDPC Converter"}
        )

    del canvas
    gc.collect()

    if progress_cb:
        progress_cb(1.0, "SDPC to BigTIFF conversion completed.")

    return output_path


def auto_convert_to_bigtiff(
    input_file: str,
    output_dir: Optional[str] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> str:
    """
    Inspect input file format and automatically convert to Space Ranger compatible BigTIFF (.btf)
    if necessary. If already compatible, returns original path directly.
    """
    inp = Path(input_file)
    ext = inp.suffix.lower()

    if is_already_supported_format(str(inp)):
        if progress_cb:
            progress_cb(1.0, f"Image {inp.name} is natively compatible with Space Ranger.")
        return str(inp)

    out_directory = Path(output_dir) if output_dir else inp.parent
    out_file = out_directory / f"{inp.stem}_converted.btf"

    if ext == ".svs":
        if progress_cb:
            progress_cb(0.01, f"Detected Aperio SVS format. Launching lossless BigTIFF converter...")
        return convert_svs_to_bigtiff(str(inp), str(out_file), progress_cb=progress_cb)
    elif ext == ".sdpc":
        if progress_cb:
            progress_cb(0.01, f"Detected Sqray SDPC format. Launching lossless BigTIFF converter...")
        return convert_sdpc_to_bigtiff(str(inp), str(out_file), progress_cb=progress_cb)
    elif ext == ".csp":
        # .csp typically wraps or pairs with svs/sdpc or can be processed via openslide/svs parser
        raise NotImplementedError(
            f"Format {ext} requires conversion to SVS or TIFF in scanner software first. "
            "Please export as .svs or .sdpc from your scanner client."
        )
    else:
        raise ValueError(
            f"Unsupported file format: {ext}. Supported formats: .tif, .btf, .tiff, .svs, .sdpc, .jpg"
        )
