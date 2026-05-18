# Procedural Sand Dune HDA — Houdini 19.5

Reference for Claude Code when constructing a procedural sand dune HDA inside
Houdini 19.5 via an MCP-Houdini server (e.g. `houdini-mcp`).

This document specifies the exact node graph, parameters, VEX, and HDA
metadata needed. Build the network top-down in the order given. All node
types and parameter names are 19.5-correct.

---

## 1. Target & assumptions

- **Houdini version:** 19.5.x (any patch level). Do **not** use 21.0-only
  parameter names (`Erosion Rate`, `Flow Force`, `Weathering Force` etc.).
- **Context:** SOP network inside a Geometry HDA (`Object/Sop` subnet).
- **Primary representation:** Heightfield (2D volume primitive on the XZ plane).
- **Solver strategy:** Built-in `HeightField Erode` for the heavy lift, plus a
  custom VEX `Volume Wrangle` inside a `Solver SOP` for slipface avalanche.
  Optional OpenCL path noted at the end for performance.
- **No Copernicus.** Copernicus is 20.5+. Use COPs (legacy COP2) or bake `Cd`
  on converted geometry for texturing.

---

## 2. HDA metadata

When creating the HDA wrapper:

| Field | Value |
|---|---|
| Operator Name | `proc_sand_dune` |
| Operator Label | `Procedural Sand Dune` |
| Operator Category | `Sop` |
| Save To | `$HOUDINI_USER_PREF_DIR/otls/proc_sand_dune.hda` |
| Min Inputs | `0` |
| Max Inputs | `2` |
| Input 0 label | `Bedrock Heightfield (optional)` |
| Input 1 label | `Initial Mask (optional)` |
| Outputs | `1` |

---

## 3. Node graph (build in this order)

All nodes live inside the HDA's SOP network. Use `null` nodes named
`OUT_*` at major stages so other tools can reference them.

```
[input0: bedrock]    [input1: mask]
       |                  |
       v                  v
   heightfield1  ----  (used as mask input on erode steps)
       |
   heightfield_noise1     # FBM base, large-scale dune skeleton
       |
   heightfield_layer1     # creates 'sand' layer from sand_depth
       |
   solver_avalanche       # Solver SOP wrapping a Volume Wrangle
       |
   heightfield_erode1     # aeolian pass (built-in)
       |
   heightfield_distort1   # break up regularity
       |
   heightfield_erode2     # detail/ripple-scale pass
       |
   heightfield_mask_by_feature1   # slope / occlusion masks
       |
   convert_heightfield1   # to polys, optional, with Bake Point Colors on
       |
   OUT
```

---

## 4. Node-by-node specification

### 4.1 `heightfield` (base canvas)

Node type: `heightfield`

| Parm | Value |
|---|---|
| `size` | `1000, 1000` (metres) |
| `gridspacing` | `1.0` (start; raise for detail) |
| `useinputbounds` | `1` if bedrock input wired, else `0` |

### 4.2 `heightfield_noise` (large-scale dune skeleton)

Node type: `heightfield_noise`

| Parm | Value |
|---|---|
| `noisetype` | `pnoise` (Perlin) or `xnoise` (simplex) |
| `amp` | promoted → `dune_amplitude` (default `15.0`) |
| `elementsize` | promoted → `dune_size` (default `80.0`) |
| `roughness` | `0.55` |
| `turbulence` | `4` |
| `combinemode` | `add` |
| `seed` | promoted → `seed` (default `1`) |

For ridge-like dune crests, switch to `noisetype = pnoise_ridged` or apply an
absolute-value remap downstream.

### 4.3 `heightfield_layer` (sand depth layer)

Node type: `heightfield_layer` set to **Create / Set** mode.

| Parm | Value |
|---|---|
| `mode` | `setlayer` |
| `name` | `sand` |
| `fillvalue` | promoted → `sand_depth` (default `5.0`) |

This creates a named `sand` layer on top of the implicit `height` layer.
The bedrock + sand model is what every published dune solver uses.

### 4.4 `solver_avalanche` (Solver SOP — slipface avalanche pass)

Node type: `solver`

Inside the Solver subnet, build:

```
Prev_Frame --> volumewrangle_avalanche --> output
```

The Volume Wrangle:

- **Run Over:** `Volume`
- **Bind to:** `height` (primary), `sand` (read/write)
- **Iterations:** promoted → `avalanche_iters` (default `30`)

VEX snippet (paste into the Volume Wrangle's `snippet` parameter):

```vex
// Slipface avalanche — clamps local slope to angle of repose.
// Runs per-voxel on the 'height' volume. Reads/writes 'sand' layer.

int   iters    = chi("iters");
float repose   = radians(chf("repose_deg"));   // ~33-34 for dry sand
float dx       = volumevoxelsize(0, "height").x;
float max_dh   = tan(repose) * dx;             // max height diff between neighbours

vector vp = set(@ix, @iy, @iz);

for (int it = 0; it < iters; it++) {
    float h_c = volumeindex(0, "height", vp);
    float s_c = volumeindex(0, "sand",   vp);

    // 4-neighbour offsets in voxel space (heightfield is 2D, iz = 0)
    int2 offs[] = array(set(1,0), set(-1,0), set(0,1), set(0,-1));

    float flux = 0;
    foreach (int2 o; offs) {
        vector vn = vp + set(o.x, o.y, 0);
        float h_n = volumeindex(0, "height", vn);
        float dh  = h_c - h_n;
        if (dh > max_dh) {
            // move excess sand from centre to neighbour
            float move = (dh - max_dh) * 0.25;   // 0.25 = 1/neighbours
            flux -= move;
        }
    }

    // Only move what the sand layer actually has
    flux = max(flux, -s_c);

    setvolumesample(0, "height", vp, h_c + flux);
    setvolumesample(0, "sand",   vp, s_c + flux);
}
```

Promoted Solver-level channels: `iters` → `chi("../iters")`, `repose_deg` →
`chf("../repose_deg")` (default `34.0`).

**Note:** `setvolumesample` writes are not perfectly thread-safe across
voxels in a single wrangle pass. For production quality, port this to an
OpenCL SOP (see section 8). For preview / lookdev, the wrangle is fine.

### 4.5 `heightfield_erode` #1 (aeolian wind pass)

Node type: `heightfield_erode` (the 19.5 SOP, **not** Erode 3.0).

Key 19.5 parameters to set:

| Parm | Value |
|---|---|
| `freeze` | `1` |
| `freezeframe` | promoted → `wind_frames` (default `30`) |
| `Main ▸ Hydro ▸ Erosion Rate` | `0.0` (disable hydro — dunes are aeolian) |
| `Main ▸ Hydro ▸ Bank Angle` | `0.0` |
| `Main ▸ Thermal ▸ Force` | `1.0` |
| `Advanced ▸ Debris flow ▸ Repose angle` | promoted → `repose_deg` (default `34.0`) |
| `Advanced ▸ Debris flow ▸ Removal rate` | small negative, e.g. `-0.02`, to simulate wind carrying sand (deposition > removal builds dunes) |
| `Advanced ▸ Debris post smooth` | `1` |
| `seed` | linked to top-level `seed` |

### 4.6 `heightfield_distort`

Node type: `heightfield_distort`

| Parm | Value |
|---|---|
| `amp` | `1.5` |
| `elementsize` | `25.0` |
| `dir_x` | promoted → `wind_dir_x` (default `1.0`) |
| `dir_z` | promoted → `wind_dir_z` (default `0.0`) |

Distortion direction biased along wind direction gives dune trails their
characteristic asymmetric drift.

### 4.7 `heightfield_erode` #2 (ripple-scale detail)

Same node type, but tuned for fine detail:

| Parm | Value |
|---|---|
| `freezeframe` | `10` |
| `Erosion Feature Size` | small (e.g. `3.0`) |
| `Repose angle` | `33.0` |
| `Debris flow ▸ Removal rate` | `0.0` |

### 4.8 `heightfield_mask_by_feature`

Generates downstream-useful masks. Set these on by default:

- `Mask by Slope` on → produces `mask` layer of slipface candidates
- `Mask by Occlusion` on → produces interdune shadow areas
- Output channel names: `slope_mask`, `occlusion_mask`

### 4.9 `convert_heightfield`

For mesh output to renderers / Unreal:

| Parm | Value |
|---|---|
| `bakecolor` | `1` (writes Cd from layers) |
| `polysoup` | `0` (keep as polys for clean UVs) |

---

## 5. Promoted parameters (HDA top-level UI)

Group these in the HDA's Parameter Interface in this order:

**Folder: Shape**
- `seed` (Integer, 1)
- `dune_size` (Float, 80.0, range 10–500)
- `dune_amplitude` (Float, 15.0, range 0–100)
- `sand_depth` (Float, 5.0, range 0–50)

**Folder: Wind**
- `wind_dir_x` (Float, 1.0, range -1–1)
- `wind_dir_z` (Float, 0.0, range -1–1)
- `wind_frames` (Integer, 30, range 1–200) — sim iterations for erode pass

**Folder: Physics**
- `repose_deg` (Float, 34.0, range 25–40)
- `avalanche_iters` (Integer, 30, range 1–200)

**Folder: Output**
- `output_polygons` (Toggle, 1) — switch between heightfield and mesh output
- `bake_masks` (Toggle, 1)

---

## 6. Build checklist for the MCP agent

When executing through the MCP server, follow this order. Each step should
be a separate tool call to keep error reporting clean.

1. `create_node` Geometry SOP at `/obj/proc_sand_dune1`.
2. Dive inside; delete the default `file1`.
3. Create nodes in the order listed in §3.
4. Wire them in a linear chain.
5. Set parameters per §4.
6. For each promoted parameter in §5: open the node's `Edit Parameter
   Interface` dialog and drag the relevant channel to the top level
   (via the `opparm` / `hou.HDADefinition.addParmTemplate` Python path).
7. Save the subnet as an HDA: `hou.Node.createDigitalAsset()` with the
   metadata in §2.
8. Test by setting `seed = 1..5` and confirming visually distinct dunes.

---

## 7. Common 19.5 pitfalls

1. **Don't use 21.0 parameter names.** `Erosion Rate`, `Flow Force`,
   `Weathering Force` do not exist in 19.5's HeightField Erode. Use `Hydro
   Erosion Rate`, `Bank Angle`, `Repose Angle`, `Debris flow ▸ Removal rate`.
2. **`turbulence()` does not exist in VEX** — it's a VOP node only. For
   custom FBM displacement, manually sum `noise()` octaves.
3. **`round()` does not exist in VEX** — use `rint()`.
4. **`@P` in a Volume Wrangle is voxel-centre position**, not a point.
5. **HeightField Erode is iterative** — must play the timeline or use
   `Freeze at Frame` to bake. Without freeze, downstream caching is unstable.
6. **`setvolumesample` in a Volume Wrangle** is not race-safe across
   neighbouring voxels. Acceptable for preview; for final, use OpenCL with
   a ping-pong buffer (read from `height_in`, write to `height_out`).
7. **`HeightField Layer` SOP defaults to `combine` mode** — explicitly set
   it to `setlayer` when initialising the `sand` layer or it'll add to
   existing values.
8. **Wind direction in HeightField Distort** is in heightfield-space
   (XZ plane). The Y component is ignored.

---

## 8. Optional: OpenCL avalanche kernel

For production-grade performance, replace the Volume Wrangle in §4.4 with
an `OpenCL` SOP. Stub kernel:

```c
#bind layer height   float read_write
#bind layer sand     float read_write
#bind parm  repose   float
#bind parm  voxsize  float

@KERNEL
{
    float h_c = @height.read(@ix, @iy);
    float s_c = @sand.read(@ix, @iy);

    float max_dh = tan(radians(@repose)) * @voxsize;

    float flux = 0.0f;
    int dx[4] = {1, -1, 0, 0};
    int dy[4] = {0,  0, 1, -1};

    for (int i = 0; i < 4; i++) {
        float h_n = @height.read(@ix + dx[i], @iy + dy[i]);
        float dh  = h_c - h_n;
        if (dh > max_dh) flux -= (dh - max_dh) * 0.25f;
    }
    flux = max(flux, -s_c);

    @height.set(@ix, @iy, h_c + flux);
    @sand.set  (@ix, @iy, s_c + flux);
}
```

Wrap the OpenCL SOP inside the Solver SOP exactly as in §4.4. The
performance gain over the VEX path is typically 10× on a heightfield
≥ 1024² (matches the DNEG Dune solver's reported speedup ratio).

---

## 9. External references

- SideFX HeightField Erode (19.5 docs):
  `https://www.sidefx.com/docs/houdini19.5/nodes/sop/heightfield_erode.html`
- SideFX Heightfield erosion guide (19.5):
  `https://www.sidefx.com/docs/houdini19.5/heightfields/erosion.html`
- Barrett Meeker — Dune Solver (OpenCL, public release):
  `https://80.lv/articles/create-your-own-sand-dunes-in-houdini-with-dune-solver`
- DNEG Dune (2021) FX breakdown:
  `https://www.sidefx.com/community/dneg-the-sands-of-dune/`
- Luis Mathison — Aeolian VEX solver (2026):
  `https://80.lv/articles/impressive-custom-sand-dune-tool-made-with-houdini`
- Brett Shields — Full VEX erosion (FBM + thermal + hydraulic):
  `https://www.brettshields.com/blog/2019/4/3/houdini-vex-exercise-erosion`
- Tutorial: Desert Terrain HDA → UE4:
  `https://www.youtube.com/watch?v=1oeVSYlWn5w`

---

## 10. Smoke test

After building, sanity-check the HDA with these parameter sweeps:

| Test | Expected outcome |
|---|---|
| `seed` from 1 → 5 | Visually distinct dune fields, no zero-output |
| `wind_dir_x = 1, z = 0` then `x = 0, z = 1` | Dune ridges reorient ~90° |
| `repose_deg = 25` vs `40` | Steeper slipfaces visible at higher values |
| `sand_depth = 0` | Bedrock geometry showing through (no dunes form) |
| `avalanche_iters = 0` | Sharp, unstable peaks; with default 30, smooth slipfaces |
| `wind_frames = 1` vs `100` | Progressively elongated, drifted dune trails |

If any sweep fails, the most likely culprits in order are: missing
`Freeze at Frame` on HeightField Erode, wrong `Run Over` on the Volume
Wrangle, or `HeightField Layer` left in `combine` mode instead of `setlayer`.
