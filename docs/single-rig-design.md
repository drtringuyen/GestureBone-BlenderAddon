# Single rig (curvechain) — design and research results

Branch `research/single-rig`, October 2026. Research build: it lives next to
the two-rig system and doesn't replace it.

## Why

The two-rig setup routes every chain through two armatures, two curves and two
Geometry Nodes passes:

```
Gesture CTRL bones ──Bone Info──▶ PlottingSpline (GN: bezier → Resample 13 → instances)
        ▲                                   │ GEOMETRY_ATTRIBUTE instance_transform
        │ (muted) GEOMETRY_ATTRIBUTE        ▼
GestureSpline (GN "TOB-Gesture_drawing")   MetaPlot STR → AXIS → SIZE (+ cross-rig copies) → DEF
```

That causes three problems:

1. **Linking has many failure points.** Every shot has to match 2 armatures,
   12 curves and their GN groups, and a Purge kills the groups.
2. **Evaluation crosses objects four times per chain.**
3. **Twist comes from curve normals.** The old rig worked around this with its
   "3 Bones plane" fix.

## What replaces it

Everything below lives inside **one armature**. The MCH bones are hidden,
non-deforming, and kept in the `MCH-CurveChain` bone collection.

| Bone | Role |
|---|---|
| `CTRL-{part}_{i}` / `.hA` / `.hB` / `.scale` | Animator controls, unchanged. Handles were renamed hL→hA and hR→hB (in/out, not left/right). |
| `MCH-{part}_{i}.dirB` / `.dirA` | Copy Location + Damped Track. Y = the curve direction leaving / arriving at the point. |
| `MCH-{part}.SEG_{k}` | One **B-Bone span** per pair of points, with TANGENT custom handles = dirB/dirA. |
| `MCH-{part}.SEG_{k}.q1..q3` | Points at ¼, ½ and ¾ of the span. Used to measure its arc length. |
| `MCH-{part}.Up` | Far out along the chain-plane normal. Up-vector for the samplers. |
| `MCH-{part}.rad_{s}` | Radius carrier for sampler `s`. |

The existing **STR bones become the samplers**. Each one's GEOMETRY_ATTRIBUTE
constraint is replaced, in place, by:

1. Copy Transforms on the span (`use_bbone_shape`, head_tail driven).
2. Locked Track on `Up` (X = plane normal, the old "3 Bones plane" frame).
3. A Transformation constraint that gives a uniform radius.

**AXIS → SIZE → DEF and every DEF name are untouched, so mesh weights and the
game export see the same skeleton.** No deforming bone uses B-Bone segments.

### Exactness

- **Each span is the old cubic.** A B-Bone handle's length is
  `ease × chord / (1.5 · (1 + cos θ/2))` (Blender's
  `cubic_tangent_factor_circle_v3`, θ = angle between the two handle
  directions). The ease drivers invert this from the *real* handle distances,
  so span k is exactly the bezier (P, hB, hA′, P′) the GN curve built.
  Measured: 0.2–0.4 % of chord, with C1 joints (0 gap, 0° tangent jump).
- **θ is measured from positions** (two unit tips, `2·L0·sin(θ/2)`), so it
  stays correct when a chain bends out of its plane.
- **Even spacing.** Resample Curve spread the 13 samples evenly over the
  *whole* chain. Per-span arc lengths come from the q-probes with a
  Richardson-corrected chord sum, and simple-expression drivers place every
  sampler by global arc length. Fixed per-span spacing was measured too
  (up to 6.5 cm drift on Leg.L), and it isn't the default.
- **Every driver is a simple expression.** There are 406 on LittlePig. They
  run without Python and without auto-run, and they work on library
  overrides.

### Twist

- **Planar mode.** Every MCH/SEG bone is rolled so local X = the plane
  normal, so in-plane motion is a pure rotation about X and nothing can
  twist. Measured `|X·n| = 1.000`, including a 200° fold inside one span.
- **3D (later).** Twist then comes from the handle bones' roll, interpolated
  linearly per span. That was measured too: rolling a handle 45° twists its
  span smoothly from 0° to 45°.
- **Plane choice, per chain:** `plane_space` = `ROOT` (follows
  `CTRL-{part}.Rotation`; the default for new rigs) or `ARMATURE` (fixed
  front plane, which is what the GN did). The converter uses `ARMATURE` so
  existing animation keeps its look.

### Drawing

Drawing uses the **Annotate tool in Pose mode**, on the scene annotation layer
`GB:{part}`. There's no curve, no Edit mode, and nothing linked has to be
made local. Apply does the following:

1. Takes the newest stroke on the current frame.
2. Lifts it onto the chain plane (along the view ray when a 3D view is
   known).
3. Smooths it and auto-orients it, so the stroke starts at the chain's first
   point.
4. Places N points at equal arc length.
5. Least-squares fits the handle lengths.
6. Writes the pose and keys points and handles, leaving locked channels
   untouched.

The stroke is then cleared.

## Converter (`gesturebone.cc_convert`)

The converter merges the MetaPlot **into** the Gesture rig, because that's
what the animation, Expression Sheet drivers and other rigs already point at.
It runs in this order:

1. Copy the chain definitions to the gesture rig.
2. Re-point **every** user of the MetaPlot: Armature modifiers, parents, GN
   Object inputs (the meshes' `Bone-weight-Linear` reads its *Deform
   Armature* there), driver targets and addon PropertyGroup pointers. It then
   refuses to continue if `user_map` still finds a reference.
3. `object.join()`, then **restore the action slot**. `join()` clears
   `animation_data.action_slot`, which silently stops the animation.
4. Rename `.hL/.hR/.End.L/.End.R` → `.hA/.hB/.End.A/.End.B`. Blender fixes
   fcurve paths, constraints and drivers itself.
5. Build the span machinery and rebind the samplers.
6. Delete the 12 chain curves and their collections.

Auto Rig gets a **Single Rig** toggle (the icon next to Auto Rig) that ends
the pipeline with the same conversion. Re-rigging a part afterwards needs the
two-rig setup.

## Results (CHR_LittlePig, Blender 5.2.2; `zz.research/`)

Old vs. converted, over every frame from 0 to 50:

| Chain | DEF pos p95 / max | DEF rot p95 / max | Mesh vertex max |
|---|---|---|---|
| Body | 0.01 / 0.01 mm | 0 / 0° | 0.02 mm |
| Tail | 0.002 / 0.003 mm | 0 / 0° | 0.004 mm |
| Arm.L | 0.13 / 0.38 mm | 0.13 / 0.47° | 0.46 mm |
| Leg.L | 0.16 / 0.50 mm | 0.13 / 0.73° | 0.23 mm |
| Leg.R | 0.22 / 0.97 mm | 0.21 / 1.6° | 0.50 mm |
| Arm.R | 0.71 / 2.3 mm | 0.39 / 7.9° | 3.3 mm |

The remaining Arm.R difference is at frames 38–40. The arm points almost
straight into the view axis there (|Y·n| = 0.95), so the old and new
up-vectors are both undefined.

### Sample direction: chord bisector, not the true tangent

The GN resampled the curve to a polyline, so each sample's "tangent" was the
bisector of the two chords to its neighbours. A first version used the
B-Bone's exact tangent instead. Where short handles make a sharp corner, that
tangent snaps up to ~155° between two samples and folds a thick band inward:
CHR_RU's hip showed 24 flipped faces, against 0 on the old rig. Now each
sample's position lives on a hidden `MCH-{part}.pos_{s}` helper. The sampler
copies that position, Damped-Tracks the next helper, then Damped-Tracks away
from the previous helper at 50 % influence. That gives the same bisector,
with no dependency cycle. On the CHR_RU hip pose, the turns per sample are
61.9° / 71.6° (old rig: 60.0° / 73.3°).

### Layer Depth (Root Bone plane)

Projection makes a chain exactly coplanar, so where it overlaps itself the
faces z-fight. That shows up as two legs passing each other, or both feet
together giving a dark notch. `layer_depth` (default 1 cm) ramps the
samplers and end bones toward the camera along the plane normal, from 0 at
the first point to the full value at the last. It's a live slider and needs
no rebuild.

Speed and linking:

| | Two rigs | Single rig |
|---|---|---|
| Objects linked into a shot | 80 (24 curves) | 52 (0 curves) |
| Override creation | 0.05 s | 0.08 s |
| Shot playback, rig only | 2.85 ms | 2.24 ms |
| Shot playback, full | 8.6 ms | 8.0 ms |
| Rig evaluation without animation | — | 0.47 ms |
| One Python bone tweak + update | 2.6 ms | 5.7 ms |

- **Playback** is dominated by the 1,679-fcurve, 6-track NLA animation in
  both versions.
- **The tweak microbenchmark is slower.** One 961-bone armature is re-copied
  on every RNA write, versus a 205-bone one before. Muting all drivers only
  saves 1.2 ms of that. Real G-key dragging wasn't measured.

The annotation API differs between versions. Blender 5.1's
`AnnotationFrame.strokes` has no `new()` or `remove()`, so clearing removes
the chain layer's frame instead. The read path is identical in 5.1 and 5.2,
and the end-to-end test gives identical results on 5.1.2 and 5.2.2.

## Export module (`modules/export/`)

This module adds an **Export** box under the chain cards of a single rig. It
has three independent steps.

**1. Bake Weights / Live** (`weights.py`). For every mesh whose
Bone-weight-Linear modifier reads this rig, Bake does three things:

- It evaluates the stack up to that modifier.
- It writes the result into the vertex groups.
- It **mutes** the modifier, keeping all its settings, so **Live** brings it
  back for tuning.

When a node adds geometry (sprite hands/feet), Bake swaps in the evaluated
mesh and keeps the original as `gb_weights_source`, so Live can restore it.

Bake skips, with a report:

- inputs that are animated or driven (RU's sprite `Hand_*`/`Feet_*` follow
  `exp_index`);
- mesh data shared with another object;
- linked or overridden meshes.

Result on LittlePig: 12.9 → 2.55 ms/frame.

**2. Optimize: Blender Optimized** (`optimize.py`). It first writes a
`<file>_beforeBDEF.blend` backup, then:

- **Bones:** deletes the template STR/AXIS/SIZE/DEF and sampler machinery. The
  B-Bone spans themselves become the deformers: `BDEF-{part}.001…`, with
  `.EndL/.EndR` caps, CURVED mapping, and thickness from bbone scale drivers.
- **Rest pose:** each span's rest ease is the exact bezier ease, and the pose
  drivers subtract it, so the rest pose is identity (0.002 mm in-plane).
- **Weights:** `weight_nodes.ensure_bdef_branch` adds a `BDEF-` prefix to the
  Bone-weight-Linear node. It copies the STR branch, following reroutes.
  `retarget_weights` sets Bone Count = spans and pre-creates the BDEF vertex
  groups, because GN only writes groups that already exist.

Result on RU: 441 → 191 bones, 610 → 246 constraints, 232 → 48 drivers,
~17 → ~10 ms.

**3. Game export** (`gamerig.py`). Game engines can't read B-Bones, so the
export rig is a **temporary** armature built in the exporting file
(`EXPORT-{rig}`, collection `GB_EXPORT`):

- Each B-Bone span becomes *Segments* plain bones. Each bone Copy Transforms
  and Stretch To the span with `use_bbone_shape`, and its rest comes from the
  B-Bone's own `bbone_segment_matrix(i, rest=True)` joints.
- The deformed meshes are copied onto it. Weights are either **Match
  B-Bones** or **Weight Node**:
  - **Match B-Bones** splits each span weight between the two segments that
    bracket the vertex on the rest curve, which is exactly what Blender does.
  - **Weight Node** has the node weight the segments live, so they can be
    tuned on the preview.
- **Preview** keeps the rig so you can inspect and tweak it. **Unity FBX** /
  **Godot glTF** bakes the rig (`nla.bake`), writes the file and removes
  everything temporary.

Measured on RU at 4 segments: 37 export bones. Copies match the shot with a
rest pose within 0.01 mm and a posed median of 0.7–1.4 mm; a few crotch
vertices are off by up to ~9 cm. FBX and GLB re-import with skin and
animation.

**Repair ANIM File.** An ANIM file that overrides the CHR keeps its own
actions, and those still key `.hL/.hR/.End.L/.End.R`. After the CHR is
converted, the Export box shows *Repair ANIM File (n keys)*. Repair renames the
paths in local actions only (the active action plus NLA strip actions). It
renames a path only when the old bone is gone and the new one exists. The
renames go by suffix, so `LIMIT-*_0.hL` is covered too.

### Linking test (copy of ANIM_LAKESCENE → converted CHR_RU)

The test used copies only. `CHR_RU.blend` was retargeted to `ru_new` (Sampler)
or `ru_bdef` (Optimized), and the copy was reopened so the overrides resync.
Results, identical in both modes:

- **Resync is clean.** The MetaPlot and spline overrides are gone. The meshes'
  `Armature.object`, GN *Deform Armature* and parent all resync to
  `CHR_RU.Gesture`, and object transforms stay identity.
- **Repair** renamed 606 keys (202 in each of S1/S2/S3), leaving 0 stale and
  0 dangling keys in the local actions. The library `ANIM_HeadTurn.*` actions
  key `Eye.L/R` and `Head.Antenne.L/R`, which are not on the old rig either.
- The body, head, 2D parts and stick match the original shot to 0.00 mm.
- Unity FBX and Godot glTF export from the ANIM file works and leaves no
  temporary objects.
- The legs and arms differ by about 0.1 m (≈0.5 % of the 20-unit character).
  Playing the same action inside the CHR copies, with no linking, gives the
  same numbers, so this is the rig and not the linking.
  - **Cause: facing.** In the converted rig the DEF Z (plane normal)
    rigidly follows `CTRL-{part}.Rotation`. The old GN rig kept it on one
    world side.
  - The shot has both Rotation bones turned 180° on ~88 % of its frames, so
    there the new rig shows the limbs from the other side.
  - The Arms' 2D Outline vertex count then differs too (+6 verts).

Pre-existing and unrelated: the cycles from the ENV `pink_glow_off` driver,
and the invalid `Socket_41 value[0]` driver on `CHR_RU-Arms.mesh`.

## Known limits / next steps

- **Old curves on Auto Rig.** On LittlePig, Auto Rig + Single Rig left the
  *original* `CHR_LittlePig-*` curves in place, because `clear_rig` doesn't
  remove them. The old pipeline does the same.
- **Not exercised yet:** `plane_space='ROOT'` on existing animation (the tilt
  of the `.Rotation` bones becomes visible), the 3D toggle, and PT_2 chains.
- **Bone count.** The armature is larger (961 bones on LittlePig). Two ways
  to trim it: drop the per-sampler `rad_` carriers (78 bones), or replace
  the q-probes with an analytic arc-length estimate.
