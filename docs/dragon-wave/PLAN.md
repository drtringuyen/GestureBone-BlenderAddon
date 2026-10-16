# Dragon wave deformer: plan

**Status:** planned, not implemented. Written 2026-10-16 with the rig author (Nguyen Duc Tri) for colleagues who will implement it, possibly in a different Claude account.
**Scope of this plan:** the Blender side only. The game-engine port is described as a data contract (§8) so the Blender work stays engine-ready, but no engine is chosen yet.

## 0. Decisions already made by the author

| Topic | Decision |
|---|---|
| Engine route | **A + B fallback.** A: a custom wave deformer in the engine (vertex shader using the same formula as Blender). B: a Blender button that bakes the wave into dense bone chains for the standard skinning pipeline. |
| Body + Pelvis + Tail | **Two waves (Body, Tail) on one shared axis, cross-faded across the pelvis.** No pin at the pelvis, so no seam, but each part has its own Phase and Amplitude. |
| How strands bend | **Cubic Bézier from ordinary control bones** (2–4 per strand), *not* real Blender B-Bones. B-Bones don't export, and their curve math is internal to Blender. |
| Order of work | Blender first, engine-neutral. The engine is chosen later. |

The author's concern behind route A: in Unity and Godot, plain bone skinning (linear blend skinning) doesn't hold the mesh form well. Volume collapses on tight bends and twists. The wave deformer keeps every cross-section rigid, exactly as in Blender.

## 1. Background: the Snake Wiggle prototype

`prototype/build_snake_wiggle.py` (v4) is a working Geometry Nodes group, verified in Blender 5.2.2. Read `prototype/README.md` for its inputs. What it does:

- **Input mesh:** a straight mesh along local X; the head is at −X. Body parameter: `u = (x − xmin) / length`.
- **Axis:** a bone, read with the **Bone Info** node (`GeometryNodeBoneInfo`, transform space RELATIVE, `Pose` matrix and `Rest Length`).
  - Pin 1 = bone head.
  - Pin 2 = bone tail, sitting at `u = Pin At`.
  - The wave swings on the bone's Z axis.
- **Centerline:** built in axis coordinates, with `t ∈ [0,1]`.
  - `phi(t) = 2π·(Waves · Acc(t)/Acc(PinAt) − Phase)`, where `Acc` is the running sum of `1/lambda(t)`. This puts exactly `Waves` waves between the pins, even when the wavelength fades.
  - `x_lin = t · BoneLength / PinAt`
  - Envelope: `win(t) = Envelope(min(t/PinAt, 1)) · [TailFollowsBody ? 1 : smoothstep(|t − PinAt| / PinSoftness)]`
  - Meander: `x = x_lin − win·r·c·sin(2phi)·min(1, A/c)`, `y = win·A·sin(phi)`. Here `c = dx/dphi`; this term makes the bulb-shaped poles and overhanging necks.
  - Sine: `x = x_lin`, `y = win·A·sign(s)·|s|^(1/(1+3r))`, with `s = sin(phi)`.
  - **Local pin correction:** subtract the curve's offset at each pin, but only within `PinSoftness` of that pin (smoothstep). Past pin 2 the offset is held constant. Result: both pins land exactly, the tail continues the wave, and the middle of the body is untouched, so peaks don't slide up and down as Phase moves.
- **Mesh mapping:** sample the centerline **by point index, not arc length**, so the pins are exact.
  - Each cross-section is offset along the in-plane wave normal (mesh local Z) and the bone X axis (mesh local Y).
  - Thickness fades toward the tail.
- **End factors:** each one fades as `value(u) = start · lerp(1, End, Fade(u))`.
- **Curves:** one shared Float Curve in node group `SW Fade Curve`; the amplitude envelope is in `SW Envelope Curve`.

**Verified numbers (headless, demo mesh with 300 rings):**
- Head error 0.0000 m. Pin 2 error ≤ 6 mm, which is ring spacing, not math error. Same with the bone posed, rotated and scaled.
- With the local correction, the peak extremes over a full Phase cycle are symmetric (+1.80…2.07 / −1.80…−2.07). The old linear correction tilted the whole body (spread 0.47 m, peaks sliding).

## 2. Target: TranDragon

- **File:** `H:\My Drive\12.BudhaKing\01.Development\00.3D\zz.in progress\TranDragon_rig.blend` (a GestureBone rig).
- **⚠ The saved file on disk is stale** (last saved 2026-10-14 09:02). It has a metarig `CHR_Dragon` with bones `Body`, `Tail`, `Hair-head`, `Hair-Arm.L/R`, `Hair-Leg.L/R`, but none of the generated `DEF-` bones from the author's screenshots. The current rig only existed in an unsaved open session on 2026-10-16. **Ask the author to save, then run step P0.**
- **Bones in the author's screenshots** (generated rig):
  - Strands: `DEF-HairHead`, `DEF-HairArm.R`, `DEF-HairArm.L`, `DEF-ArmLeg.R`, `DEF-ArmLeg.L`
  - Body chain: `DEF-body` → `DEF-Pelvis` → `DEF-Tail`
  - Also present: `DEF-neck`
  - The author called the leg strands "HairLeg". The metarig says `Hair-Leg`, the screenshot says `DEF-ArmLeg`. **Confirm the names.**
- **Mesh size** (from the stale file): game-mesh candidates `Straighten` (6,707 verts) and `Retopology` (4,946 verts). A related session (2026-10-14) described `CHR_Dragon-Sculpt.mesh` as a mirror-applied copy of `Straighten`, so expect roughly 7–14k vertices. The sculpts `Ly_DUCTRI*` (~950k verts) are reference only and should never be deformed.
- **Existing deform stack** on the dragon, from that 2026-10-14 session; re-verify:
  - `CHR_Dragon-Sculpt.mesh` is driven by 42 `SKIN-{part}.001–.004/.EndL/.EndR` bones on `CHR_Dragon.Gesture`, each with Copy Transforms from its STR sampler.
  - Weights come from 7 `SKIN weights <part>` GN modifiers (`Bone-weight-Linear`, prefix `SKIN-`) plus `SKIN_Fallback_Weight`.
  - The SKIN layer exists because STR/DEF bones are not at rest orientation in the neutral pose.
  - Code: `weight_nodes.ensure_prefix_branch(tree, "SKIN-")` on branch `feature/gn-skin-weights` (unmerged at the time of writing).
  - **Consequence for this plan:** the wave layer must sit on top of whatever skinning the dragon finally uses (SKIN- or DEF-), and the wave's *rest* frames must come from the same neutral pose that the skinning treats as rest.

## 3. Strand inventory

| Strand id | Axis | Control bones (proposed, §4.2) | Pins | Notes |
|---|---|---|---|---|
| 0 HairHead | `DEF-HairHead` | `WAVE-HairHead.root/.h1/.h2/.tip` | root only (tip free) | |
| 1 HairArm.R | `DEF-HairArm.R` | `WAVE-HairArm.R.*` | root | |
| 2 HairArm.L | `DEF-HairArm.L` | `WAVE-HairArm.L.*` | root | Mirror of 1 |
| 3 ArmLeg.R | `DEF-ArmLeg.R` | `WAVE-ArmLeg.R.*` | root | Name to confirm |
| 4 ArmLeg.L | `DEF-ArmLeg.L` | `WAVE-ArmLeg.L.*` | root | Name to confirm |
| 5 Body+Tail | spline through `DEF-body` head → `DEF-Pelvis` head → `DEF-Tail` head → `DEF-Tail` tail | `WAVE-Body.*` (4+ points) | body head + tail tip (or Pin At) | Two param sets (Body, Tail), cross-faded at the pelvis |

Pins for hair strands: the prototype pins head and bone tail. For free hair, the author likely wants only the root pinned with the tip free (Pin At = 1, no pin-2 correction). **Ask the author** (Q3 in §10).

## 4. Blender architecture

### 4.1 Layers and modifier order

```
[Armature / SKIN skinning]  →  [Dragon Wave (GN, one modifier)]  →  (Mirror etc. must come BEFORE both)
 standard bones, LBS            overrides strand vertices by weight
```

- Strand vertices still get normal skin weights, rigid to their root bone, so a fallback exists if the wave is off.
- The wave modifier replaces their position with `lerp(skinned, wave_result, wave_w)`. `wave_w` is 1 along the strand and fades to 0 over the root zone, so the root blends into the body.
- The game engine uses the same order: GPU skinning, then the vertex shader (§8). **This order is the parity guarantee.** Keep it.

### 4.2 Axis: a cubic Bézier from control bones (no B-Bones)

- **Each hair strand:** four non-deforming control bones. Their heads are the Bézier points P0 (root), P1 and P2 (handles) and P3 (tip). They are exported as ordinary bones, and the animator bends the strand by moving the handles.
  - Rig them so the defaults reproduce the straight DEF bone: P1 and P2 at ⅓ and ⅔ along it, parented so they follow the bone.
- **Body+Tail:** one spline through 4+ points (`DEF-body` head, `DEF-Pelvis` head, `DEF-Tail` head, `DEF-Tail` tail). Use either Catmull-Rom converted to Bézier segments or explicit handle bones per joint. Rotating the body bones bends the spline.
- **Arc length:** the wave needs arc-length position along the axis. Per frame, compute a small arc-length lookup table (16–32 samples per strand) and map `x_along → Bézier t`. In GN this is a resampled curve plus Sample Index, as in the prototype. In the engine the CPU computes the table once per frame and sends it to the shader.
- **Wave plane (frame along the curve):** use the **root control bone's Z axis**, projected perpendicular to the local tangent. It's analytic and easy to reproduce in a shader.
  - It degenerates only where the tangent is parallel to that Z. Document the limitation; don't use a rotation-minimizing frame, because it needs an integral the shader can't reproduce cheaply.
  - **Why it matters:** every quantity must be computable both in GN and in a shader from the same inputs, or Blender and the engine will drift apart.
- **5.1 compatibility:** the add-on targets Blender 5.1 *and* 5.2 (see repo `ARCHITECTURE.md`). **Check that `GeometryNodeBoneInfo` exists in 5.1.** If it doesn't, read control-bone positions through helper Empties with Copy Transforms and the Object Info node.

### 4.3 Param bones: animatable wave parameters that survive export

Animated custom properties don't reliably reach Unity or Godot. So each wave gets one hidden, non-deforming **param bone** `PARAM-{strand}` (two for Body+Tail: `PARAM-Body`, `PARAM-Tail`). Wave parameters are its local channels:

| Channel | Parameter |
|---|---|
| location X | Phase |
| location Y | Amplitude (m) |
| location Z | Roundness (0–1) |
| scale X | Waves (rounded) |
| scale Y / Z | spare (e.g. Pin Softness, Body/Tail cross-fade position) |

- The GN reads them with Bone Info (`Local Pose` matrix, translation and scale). The engine reads the bone's local transform.
- The animator keys bones as usual, and animation blending in the engine blends wave parameters for free.
- **5.2 pitfall:** if a parameter must instead be a keyed modifier input, the fcurve path must be the attribute form `modifiers["X"].properties.inputs.Socket_N.value`. The subscript form `...inputs["Socket_N"]["value"]` keys fine but the modifier never re-evaluates. This was verified in the prototype.

### 4.4 Rest bake: per-vertex data computed once

An operator **Bake Wave Rest Data** runs at the neutral/rest pose and writes these point attributes. They also go to UV channels or vertex groups for export (§8).

| Attribute | Type | Meaning |
|---|---|---|
| `wave_strand` | INT | Strand id 0–5, −1 = not affected |
| `wave_u` | FLOAT | Position along the strand axis, 0 at the root, arc-length normalized. Found by projecting the vertex onto the rest axis curve (resample, then Sample Nearest and its factor) |
| `wave_s` | FLOAT | Normalized phase coordinate `Acc(u)/Acc(PinAt)`. Pre-baking it makes Wavelength End a rig-time setting rather than an animated one; accepted for runtime cost |
| `wave_off` | FLOAT_VECTOR | Rest offset of the vertex from the axis point, in the rest axis frame (tangent, wave normal, binormal). This is what lets **curved** rest strands work: the prototype assumed a straight mesh along X |
| `wave_w` | FLOAT | Blend weight. Default: smoothstep over a "root zone" of `wave_u`, multiplied by an optional painted vertex group `WAVE-{strand}` |

**Strand membership:** the author paints or assigns vertex groups `WAVE-{strand}`, or they're derived from existing DEF/SKIN weights over a threshold. A vertex belongs to the strand with the highest weight.

### 4.5 Per-frame deform: closed form per vertex

Rewrite the prototype's centerline into a **per-vertex closed form**, so GN and the shader run literally the same math:

1. `phi = 2π·(Waves·wave_s − Phase)`, read from the strand's param bone.
2. Envelope and fade: sample the baked lookup tables (`SW Envelope Curve` and `SW Fade Curve` → 64-sample float arrays) at `wave_u`.
3. Wave in axis coordinates: `x(u), y(u)` as in §1. The tangent `(dx/du, dy/du)` is analytic. For the envelope and fade, use finite differences of the tables.
4. Pin correction: needs the wave offsets at the pins. Evaluate the same closed form at `u=0` and `u=PinAt` (per strand, per frame: CPU in the engine, a field-free sub-evaluation in GN).
5. Place on the posed axis: `P = Bezier(arclen⁻¹(x)) + wave normal·y`. Then add the cross-section `wave_off`, rotated by the local wave-frame rotation and scaled by thickness.
6. Normals: rotate the rest normal by the same local frame rotation. GN recomputes normals itself, but the shader must do it explicitly, so compute it in GN too for parity testing.
7. Body+Tail: evaluate both parameter sets and **blend the displacements** (not the phases): `y = lerp(y_body, y_tail, smoothstep(pelvis_u − w, pelvis_u + w, wave_u))`. Blending phases compresses waves locally.

**Parity test:** export positions for a pose and Phase, re-evaluate the formula in plain Python or NumPy, and compare to the GN result. The tolerance is float32 noise (< 1e-4 m). Do this in P1 before touching the dragon.

### 4.6 One modifier for all strands

- One GN group, **Dragon Wave**. Per-strand parameters are chosen per vertex with **Index Switch on `wave_strand`**, not six stacked modifiers. Stacking means six full-mesh passes plus six centerline resamples.
- The modifier's inputs: Armature, the control bones' naming prefix, and the baked lookup tables (or the curve groups).
- **Expected cost:** the prototype's per-modifier work (512-point resample plus per-vertex index sampling) is small. At about 7–14k vertices the closed form should run well under 2 ms per frame; if an extra ×6 resample path is needed it might reach a few ms. **Measure on the real mesh in P5**, with headless timing of `evaluated_get()` over 48 frames.

### 4.7 Route B fallback: bake the wave to bones

An operator **Bake Wave to Bones** for the standard pipeline:

- Per strand, generate `N` bones (default 24; ~8 per wave is the minimum for clean meander loops) along the rest axis. Weights come from `wave_u` (linear between the two nearest bones, max 2 influences).
- Bake each frame's wave centerline frames (position, tangent, wave normal) into an action on those bones.
- Reuse the export module's prefix machinery (`weight_nodes.ensure_prefix_branch`, BDEF-/SKIN- branches) instead of inventing a new weight path.
- Expect plain skinning to lose some volume at tight meander poles; that's the documented trade-off of route B.

### 4.8 Where the code goes

- A new add-on module `addons/GestureBone/modules/wave/`, following the existing module layout (see `ARCHITECTURE.md` §3):
  - node-group builder (from the prototype's builder DSL)
  - operators: Add Wave Strand, Bake Rest Data, Bake Wave to Bones
  - a compact UI panel (the author prefers dense, refined panels)
- Node groups are built by code, as the prototype does, so they can be rebuilt and diffed. Don't hand-edit them.

## 5. Bendy bones: summary of the advice given

- Real B-Bones: fine in Blender, but **they don't export**. FBX and glTF carry only plain bones, so the engine can't reproduce the B-Bone curve. Use them only as hidden mechanism (as in the single-rig research, `docs/single-rig-design.md`) or for parts that never go to the engine.
- Wave strands and the body chain use the **Bézier-from-control-bones** axis (§4.2). The animator gets the bendy-bone workflow (move the handles) and the engine gets exact data.

## 6. Engine routes compared (for the record)

| | A. Custom wave shader (chosen) | B. Dense bone chains (fallback) | C. Vertex animation texture (not chosen) |
|---|---|---|---|
| Holds the mesh form | Exact Blender match; rigid cross-sections | Good on gentle bends; plain skinning loses volume on tight loops and twists | Exact |
| Waves changeable at runtime | Yes; parameters blend in the state machine | Baked only | No |
| Animation data size | Tiny | Heavy (~6 × 24–32 bones × every frame) | Very heavy |
| Engine work | Large: shader, driver script, normals and tangents, bounds; physics doesn't see the wave | Small | Medium |
| GPU cost | Low (< 0.1 ms at 100k verts on desktop) | Trivial | Low |
| CPU cost | Negligible (~6 × 10 parameters + 6 arc-length tables per frame) | ~0.1 ms per dragon for animation sampling | Negligible |

## 7. Phased tasks and acceptance criteria

- [ ] **P0. Facts.** The author saves TranDragon. Run a headless read-only inspection (see §9) and record: mesh object and vertex count, modifier stack, exact DEF/SKIN bone names, rest vs neutral pose, and whether `GeometryNodeBoneInfo` exists in 5.1. Update §2 and §3 of this file.
- [ ] **P1. Closed form on the snake demo.** Rewrite the prototype centerline as the per-vertex closed form (§4.5) with baked `wave_s`. Accept when it visually matches v4 and a NumPy re-evaluation matches the GN positions to < 1e-4 m.
- [ ] **P2. Bézier axis.** Replace the single-bone axis with control bones P0–P3 plus an arc-length table. Accept when pins stay exact (head error < 1 mm) with handles moved, and the wave plane follows root-bone roll.
- [ ] **P3. Rest bake on a curved strand.** Use a curved test tube (not straight X). Accept when, at Phase 0 and Amplitude 0, the deformed mesh equals the rest mesh (< 1e-4 m), and with waves on, cross-sections stay rigid.
- [ ] **P4. Dragon setup** on a *copy* of TranDragon. Never save tests into the production file; snapshot, test, restore, as in earlier sessions. Add 6 strands, Body/Tail cross-fade, param bones. Accept with the author's visual review in the live file plus a screenshot.
- [ ] **P5. Single pass and performance.** One Dragon Wave modifier. Report ms per frame (headless, 48 frames) with and without the modifier.
- [ ] **P6. Route B.** Bake Wave to Bones. Accept when the max vertex distance between baked-bone skinning and the GN result is reported per strand, so the author can judge the volume loss.
- [ ] **P7. Data contract.** Write `docs/dragon-wave/ENGINE_CONTRACT.md` (§8). Export a test with glTF and FBX and confirm the attributes and param bones survive. Inspect with the glTF JSON, and Unity/Godot import if available.

## 8. Engine data contract (for P7; engine not chosen)

- **Skeleton:** standard bones, plus `WAVE-*` control bones (positions only) and `PARAM-*` param bones (local transforms carry parameters, §4.3).
- **Mesh channels:**
  - glTF: custom attributes `_WAVE_STRAND`, `_WAVE_U`, `_WAVE_S`, `_WAVE_OFF`, `_WAVE_W`. Godot maps custom attributes to CUSTOM0–3.
  - FBX/Unity: UV2 = (u, s, w, strand), UV3 = offset xyz.
- **Lookup tables:** envelope and fade as 64-float arrays per strand (a JSON sidecar or a 1D texture).
- **Runtime per frame (CPU):** read control-bone world positions and param-bone local transforms, build arc-length tables, compute pin offsets, upload around 10 floats plus a 16–32 table per strand.
- **Shader:** runs after skinning; applies §4.5 steps 1–7 to vertices with `wave_w > 0`. Widen renderer bounds by the maximum amplitude.

## 9. Pitfalls already paid for (read before coding)

- **5.2 GN modifier inputs:**
  - Raw `mod["Socket_N"]` is dead; use `mod.properties.inputs["Socket_N"]["value"]`.
  - Setting values from Python doesn't tag re-evaluation: call `ob.update_tag()` before reading evaluated data.
  - For animation, use the attribute path (§4.3).
- **Swapping a modifier's node group** keeps old values keyed by socket identifier, so a new socket can inherit an unrelated old value. Reset new-only inputs to their defaults, then restore user values by *name* (see `upgrade_live()` in the prototype).
- **Sample Index** `Index` is an int socket; pass `0`, not `0.0`.
- **Menu Switch:** two Menu Switches linked to one group menu input empties the menu for every modifier using the group. Enum values are saved by index.
- **Rendering for verification:** keyed modifier inputs override values set from Python at render time. To test animated values, use `scene.frame_set()`.
- **Live production file:** test on copies. With the author's open session, snapshot, mutate, restore and never save, unless asked. Save a backup copy (`save_as_mainfile(copy=True)`) before any upgrade.
- **Blender MCP:** this machine runs Blender's official lab MCP extension on port 9876; use the `mcp__Blender__*` tools. The other `blender` MCP server speaks a different protocol and returns "Incomplete JSON". Only one Blender instance can own the port.
- **Headless inspection:** `blender.exe --background --factory-startup <file> --python script.py`. User add-ons are skipped, so add-on node groups that are stored in the file still evaluate.

## 10. Open questions for the author

1. Leg strand bone names: `DEF-ArmLeg.*` (screenshot) or `Hair-Leg.*` (metarig)? Rename?
2. Which mesh is the game mesh that should carry the wave: `CHR_Dragon-Sculpt.mesh`, `Straighten`, or a new retopo?
3. Hair strands: pin the root only (tip free), or also pin at the bone tail like the prototype?
4. Is Wavelength End allowed to be a rig-time-only setting (baked into `wave_s`)? Animating it costs a per-frame integral.
5. Should the body/tail cross-fade position be fixed at the pelvis or animatable (spare param channel)?
6. Final skinning layer under the wave: SKIN- (current sculpt setup) or DEF-?
