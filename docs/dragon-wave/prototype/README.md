# Snake Wiggle (Geometry Nodes, Blender 5.2) — v4, bone-pinned

Reference prototype for [the dragon wave plan](../PLAN.md). It's copied from the author's working folder `D:\Documents\04.Blender Addon Development\SnakeWiggleGN\`. That folder also holds the `.blend` files, which git doesn't track here.

`build_snake_wiggle.py` builds the node group **Snake Wiggle** on a demo object `Snake`. The axis comes from a demo armature `SnakeRig`, bone `Spine`.

- Generate the demo file: `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python build_snake_wiggle.py -- SnakeWiggle.blend`
- Upgrade an open file that has an older Snake Wiggle group, inside Blender: `ns = {"__name__": "snake_wiggle_lib"}; exec(open(r"<path>/build_snake_wiggle.py").read(), ns); ns["upgrade_live"]()`

**Input:** any mesh lying straight along its **local X** axis. The head is the **-X end**. The mesh needs enough loop cuts along X to bend smoothly.

**How the pins work:** the snake head sits on the **bone head**. The body point at **Pin At** sits on the **bone tail**. The wave swings on the bone's **Z** axis, so bone roll rotates the wave plane. Both pins stay fixed while Phase animates, and they follow the bone when it's posed, moved or scaled. The body between the pins stretches to span the bone exactly. The tail past Pin At continues the same wave beyond the bone tail.

| Panel | Input | Meaning |
|---|---|---|
| Bone | Armature / Bone | The bone that defines the axis. If it's missing, the mesh's own X line is used as the axis and the wave swings on local Z |
| Wave | Waves | Full waves between the two pins |
| | Phase | Moves the waves along the body (1 = one wave). The demo keys it 0→1 over frames 1–49, cycled |
| | Amplitude | Full size of the waves along bone Z, shaped from head to bone tail by the curve in **SW Envelope Curve** |
| Shape | Shape | **Meander**: the poles bulge and the necks overhang. **Sine**: a plain wave with rounded poles |
| | Roundness | How round or bulb-shaped the poles are |
| Pins | Pin At (0.5–1) | How much of the body (from the head) lies between the pins. The rest is tail |
| | Tail Follows Body | **On**: the wave crosses the bone tail at its natural slope and the tail carries on as one smooth wave. **Off**: the wave is squeezed flat onto the axis at the bone tail |
| | Pin Softness | How much of the body next to each pin bends to meet it. With Tail Follows Body off, it's also the width of the squeeze at the bone tail |
| Fade to Tail | Amplitude / Wavelength / Roundness / Thickness End | The value at the tail, as a 0–1 factor of the start value |
| Body | Thickness | Cross-section scale at the head |
| Settings | Resolution | Number of centerline points |

**Curves:** **SW Envelope Curve** shapes the amplitude from the head (x=0) to the bone tail (x=1): rise, plateau, fall. Past the bone tail, the tail holds the curve's end value, so drag the end to 0 for a still tail. **SW Fade Curve** shapes every End factor. To edit either one, open the node group with Tab.

**Animating Phase in 5.2:** key it with the UI (hover the field and press I), or from Python with the path `modifiers["Snake Wiggle"].properties.inputs.Socket_N.value`. Blender also accepts the subscript form `...inputs["Socket_N"]["value"]`, but then the modifier never re-evaluates during playback.

**To use your own rig:** set Armature and Bone on the modifier. Don't parent the snake to the bone, because the node group already places it.
