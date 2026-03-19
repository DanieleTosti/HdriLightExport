# HDRI Light Rig Importer for Gaffer  v2.15  

**Author:** Daniele Tosti (2021) | Vanilla port: 2026-03

Converts Nuke's HDRI Light Extract metadata into a Gaffer lighting rig.
Supports **USD lights** (default) and **Arnold lights**.

## Requirements

- Gaffer (vanilla from gafferhq.org)
- GafferArnold + GafferOSL (for Arnold lights) or USD support (for USD lights)
- HDRI EXR with Nuke "HDRI Light Extract" metadata

## Installation

Copy `Gaffer_HDRILightExtract_importer.py` to Gaffer's `python` folder inside your Gaffer installation:

```
<GAFFER_INSTALL>/python/Gaffer_HDRILightExtract_importer.py
```

Example:
```
gaffer-1.6.10.0-windows/python/Gaffer_HDRILightExtract_importer.py
```

Restart Gaffer.

## Usage

1. Create an `ImageReader` node pointing to your HDRI EXR
2. Select the node
3. In Gaffer's Python Editor, run:

```python
import importlib
import Gaffer_HDRILightExtract_importer
importlib.reload(Gaffer_HDRILightExtract_importer)

# Using USD lights (default)
Gaffer_HDRILightExtract_importer.buildLightRig(root)

# Or explicitly specify USD
Gaffer_HDRILightExtract_importer.buildLightRig(root, "usd")

# Or use Arnold lights
Gaffer_HDRILightExtract_importer.buildLightRig(root, "arnold")
```

## What It Creates

A Box node containing:
- **Environment light** (USD `DomeLight` or Arnold `skydome_light`) with HDRI texture
- **Area lights** (USD `RectLight` or Arnold `quad_light`) with per-light textures
- **Sun lights** (USD `DistantLight` or Arnold `distant_light`) for distant/sun sources
- **Aim constraints** targeting the environment light
- **Exposure_compensation** global control with per-light offset expressions
- **Enable_z_translate** toggle to enable/disable local Z-axis offset for all lights
- **ZTranslate_lights** offset control (active only when Enable_z_translate is on)
- **Per-light Transform nodes** for manual position adjustments
- **Per-light ZTransform nodes** (separate chain) for Z-axis translation
- **LightGroup naming** (`_LGT<n>`) read from Nuke metadata per light
- **BoxIn/BoxOut passthrough** for clean node bypass

## Expected Metadata

```
nuke/HDRI_CROP_Name: <environment_name>
nuke/HDRI_CROP_LGT1_Name: <light_name>
nuke/HDRI_CROP_LGT1_EV: <exposure_value>
nuke/HDRI_CROP_LGT1_Scale: (width, height)
nuke/HDRI_CROP_LGT1_Pos3D: (x, y, z)
nuke/HDRI_CROP_LGT1_OutputPath: <texture_path>
nuke/HDRI_CROP_LGT1_ExtractModeType: <mode>
nuke/HDRI_CROP_LGT1_IsSun: <0.0 or 1.0>
nuke/HDRI_CROP_LGT1_LightGroup: <group_number>
nuke/HDRI_CROP_LGT1_Distance: <meters>
```

## Troubleshooting

**"No HDRI Light Extract metadata found"**
- EXR doesn't have Nuke metadata. Check the ImageReader's Metadata tab.

**"Please select an ImageReader"**
- Select a `GafferImage::ImageReader` node before running.

**Lights too bright/dim**
- Adjust `Exposure_compensation` on the rig box. Default conversion: `strength = 2^(EV/4)`

**Lights not responding to Z offset**
- Make sure `Enable_z_translate` is checked on the rig box.

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
