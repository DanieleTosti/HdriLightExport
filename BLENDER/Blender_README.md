# HDRI Light Rig Importer for Blender  v1.0

**Author:** Daniele Tosti (2021) | Blender port: 2026-03

Converts Nuke's HDRI Light Export metadata into a Blender lighting rig
using native Blender lights (AREA, SUN, World Environment Texture).

## Requirements

- Blender 3.0+ (uses `id_properties_ui` API)
- No external Python dependencies (EXR metadata parsed with stdlib `struct`)
- HDRI EXR with Nuke "HDRI Light Extract" metadata

## Installation

Copy `Blender_HDRILightExtract_importer.py` to any folder on disk, for example:

```
C:\Users\<you>\Documents\blender_scripts\Blender_HDRILightExtract_importer.py
```

Or place it anywhere accessible from Blender's Python path.

## Usage

1. Open Blender
2. In the Python Console (or Text Editor), run:

```python
import importlib, sys
sys.path.append(r"H:\Desktop\Tosti\SOFTWARE\RnD\NUKE\Tosti - HDRI extract WorkArea 20260316\BLENDER")
import Blender_HDRILightExtract_importer
importlib.reload(Blender_HDRILightExtract_importer)

Blender_HDRILightExtract_importer.build_light_rig(r"C:\tmp\blue_photo_studio_4k_CLN.exr")
```

The function returns the `bpy.types.Collection` containing the rig.

## What It Creates

A Collection (`HDRI_RIG__<name>__<timestamp>`) containing:
- **World Environment Texture** with the HDRI, including a Mapping node for rotation
- **AREA lights** (rectangle shape) for extracted rectangular light sources, with size from metadata
- **SUN lights** for distant/sun sources
- **Track To constraints** aiming each light at the rig centre
- **Exposure_compensation** global control (custom property on the rig empty) with per-light drivers
- **Enable_z_translate** toggle to enable/disable Z-axis offset for all lights
- **ZTranslate_lights** offset control (active only when Enable_z_translate is on), driven via `delta_location`
- **LightGroup naming** (`_LGT<n>`) read from Nuke metadata per light
- **Per-light custom properties**: `lightgroup`, `base_exposure`, `texture_path` (for pipeline reference)
- **Y-up to Z-up coordinate conversion** applied automatically

## Rig Controls

Select the `HDRIRig_<name>` empty and open its Custom Properties panel:

| Property | Type | Description |
|---|---|---|
| `Exposure_compensation` | float | Global exposure offset added to every light. Each light's energy = `2^(base_exposure + compensation)` |
| `Enable_z_translate` | int (0/1) | Toggle Z-axis offset for all lights |
| `ZTranslate_lights` | float | Z offset applied to all lights when enabled |

## Expected Metadata

The EXR must contain these header attributes (with or without `nuke/` prefix):

```
HDRI_CROP_Name: <environment_name>
HDRI_CROP_LGT1_Name: <light_name>
HDRI_CROP_LGT1_EV: <exposure_value>
HDRI_CROP_LGT1_Scale: (width, height)
HDRI_CROP_LGT1_Pos3D: (x, y, z)
HDRI_CROP_LGT1_OutputPath: <texture_path>
HDRI_CROP_LGT1_ExtractModeType: <mode>
HDRI_CROP_LGT1_IsSun: <0.0 or 1.0>
HDRI_CROP_LGT1_LightGroup: <group_number>
HDRI_CROP_LGT1_Distance: <meters>
```

## Troubleshooting

**"No HDRI Light Extract metadata found"**
- The EXR doesn't contain Nuke HDRI_CROP metadata. Verify the file was exported from the HDRI Light Extract tool.

**"Not a valid OpenEXR file"**
- The file is not a valid EXR. Check the path and file integrity.

**Lights too bright/dim**
- Adjust `Exposure_compensation` on the `HDRIRig_<name>` empty. Default conversion: `energy = 2^(EV/4)`

**Lights not responding to Z offset**
- Make sure `Enable_z_translate` is set to `1` on the rig empty.

**Textures not visible on area lights**
- Light textures use Cycles shader nodes. Switch your render engine to **Cycles** to see them. EEVEE does not evaluate custom light node trees.
- If the texture file was not found on disk at import time, only the `texture_path` custom property is stored. Ensure the texture EXRs are in the same folder as the HDRI.

## Non-Resale Software License

Copyright (c) 2021-2026 Daniele Tosti. All rights reserved.

Permission is hereby granted, free of charge or for a fee, to any person or
organization obtaining a copy of this software and associated documentation
files (the "Software"), to use, copy, modify, and distribute the Software,
including for internal commercial and production use, subject to the following
conditions:

1. **Attribution**
All copies or substantial portions of the Software, whether modified or
unmodified, must retain this copyright notice, this permission notice, and
identification of Daniele Tosti as the original author.

2. **No Resale or Standalone Commercial Distribution**
The Software may not be sold, sublicensed, relicensed, or redistributed as a
standalone commercial product, or as a substantial or primary component of a
paid product, service, or offering, without prior written permission from
Daniele Tosti.

Use of the Software in internal studio pipelines, production
environments, or client work is permitted, provided the Software itself is not
being sold, licensed, or marketed as the product or a paid feature.

3. **Third-Party Rights and Compliance**
You are solely responsible for ensuring that your use of the Software complies
with all applicable laws, regulations, and third-party rights, including but
not limited to software license terms, intellectual property rights, and any
rights associated with input images, HDRIs, exported data, or external tools
used with the Software.

4. **No Warranty**
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, TITLE, AND NONINFRINGEMENT.

5. **Limitation of Liability**
IN NO EVENT SHALL THE AUTHOR OR COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM,
DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR
OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE
OR OTHER DEALINGS IN THE SOFTWARE.

6. **Termination**
Any rights granted under this license automatically terminate if you fail to
comply with its terms.
