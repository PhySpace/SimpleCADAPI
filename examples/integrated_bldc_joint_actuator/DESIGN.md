# Case 20: Integrated 50 mm BLDC Joint Actuator

## Classification

Product-level kinematic assembly. The actuator contains separately manufactured
electrical, magnetic, bearing, gear, housing, and output parts. The fixed housing
is the ground; the rotor, two carriers, and six planets are rotating components.

## Design Intent

- Fit a real inner-rotor brushless motor, a 20:1 reducer, a circular controller
  PCB, and serviceable wiring terminals into one coaxial 50 mm package.
- Eliminate the separate motor-to-reducer coupler. The rotor shaft and stage-1
  sun are one steel solid.
- Preserve a short load path from the output flange through two adjacent output
  bearings into a separate front bearing cap.
- Keep the stator and both ring gears as replaceable press-fit inserts instead of
  hiding them inside an impossible one-piece enclosure.
- Reserve rear-facing connector apertures and PCB mounting holes so electronics
  are not represented by an empty cosmetic volume.

## Envelope And Performance

| Item | Value |
|---|---:|
| Motor / housing outside diameter | 50.0 mm |
| Structural axial envelope | 75.8 mm |
| Terminal protrusion included | 77.3 mm |
| Motor topology | 12-slot / 14-pole inner rotor |
| Stator active length | 16.0 mm |
| Rotor magnetic length | 17.5 mm |
| Radial air gap | 0.30 mm |
| Stage 1 | 15/15/45 teeth, 4:1 |
| Stage 2 | 18/27/72 teeth, 5:1 |
| Total reduction | 20:1 |
| Reducer housing minimum cylindrical wall | 2.20 mm |

The two stages intentionally use different modules. Stage 1 uses module 0.80 to
leave enough root section around the 8 mm direct-drive shaft. Stage 2 uses module
0.55 to fit the 72-tooth, 5:1 ring inside the 50 mm housing. Both tooth sets obey
the three-planet equal-spacing condition `(sun teeth + ring teeth) mod 3 = 0`.

## Bill Of Materials

| Part / subassembly | Manufacturing intent | Material / connection |
|---|---|---|
| Main reducer housing | One machined fixed part | 6061-T6 aluminum |
| Motor shell | One machined fixed part | 6061-T6, six M3 front screws |
| Rear bearing spider | Separate machined part | 7075-T6, four M2.5 screws |
| Rear electronics cover | Separate machined part with PCB bosses | 6061-T6, four M2.5 screws |
| Output bearing cap | Separate machined part | 7075-T6, six M3 screws |
| Stator core | 12-slot laminated stack | Electrical steel, thermal press fit |
| Windings | Twelve separately represented coil packs | Copper, varnish/potting retained |
| Rotor shaft + stage-1 sun | One integrated machined solid | Hardened alloy steel |
| Rotor magnets | Fourteen bonded inserts | NdFeB |
| PCB | Circular controller board with real holes/notches | FR-4/copper |
| Phase terminal | Three-position rear-access terminal | High-temperature polymer |
| Power/CAN terminal | Four-position rear-access terminal | High-temperature polymer |
| Fixed ring gears | Two replaceable press-fit inserts | Case-hardened steel |
| Planet gears | Six gears with standard bearing seats | Case-hardened steel |
| Stage-1 carrier + stage-2 sun | One integrated interstage part | 7075 carrier / modeled as steel-duty part |
| Output carrier + flange | One integrated output part | 7075-T6 aluminum |
| Motor bearings | 8x16x5 and 8x19x6 | Standard ball bearings |
| Interstage bearing | 5x10x3 | Thin radial ball bearing in fixed divider |
| Planet bearings | Six 3x6x3 bearings | Standard ball bearings |
| Output bearings | Two 16x24x5 bearings | Standard ball bearings |

Fasteners are represented by matching holes and documented interfaces rather
than individual screw solids. This keeps the graph focused while retaining
manufacturable attachment geometry.

## Interface Table

| Constraint / interface | Motion meaning | Real connection | Geometry and clearance |
|---|---|---|---|
| `motor_shell_to_reducer_housing` | Fixed | Six M3 screws | 43.0 mm PCD, 3.2 mm holes |
| `rear_spider_to_motor_shell` | Fixed | Four M2.5 screws | 40.6 mm PCD, 2.7 mm holes; face-to-face column/spider joint |
| `rear_cover_to_motor_shell` | Fixed | Four M2.5 screws | Shared rear columns and holes |
| `stator_to_motor_shell` | Fixed | Thermal press fit + potting | Nominal line-to-line CAD fit; tolerance sets interference |
| `electronics_to_rear_cover` | Fixed | Four M2 PCB screws | 33.0 mm PCD and integrated standoffs |
| `rotor_revolute` | Motor input rotation | Front/rear radial bearings | 8 mm shaft, 0.30 mm magnetic air gap |
| `stage1_ring_fixed` | Fixed ring | Interference fit and axial clamp | 0.04 mm diametral modeled interference |
| `stage1_carrier_revolute` | First reduction output | 5x10x3 radial bearing | Integrated 5 mm stage-2 sun shaft |
| `stage2_ring_fixed` | Fixed ring | Interference fit and axial clamp | 0.04 mm diametral modeled interference |
| `output_carrier_revolute` | Joint output rotation | Paired output bearings | 16 mm shaft in two 16x24x5 bearings |
| Planet revolutes | Planet spin | 3x6x3 bearings on 3 mm pins | 0.05 mm radial gear-seat clearance |
| Output cap to housing | Fixed | Six M3 screws | 43.0 mm PCD, 3.2 mm holes |
| Output link | External fixed attachment | Six M3 screws | 34.0 mm PCD tapped holes, Ø15.96 locating pilot |

Bearing rolling elements are decorative geometry fused into each outer-ring Part.
Each bearing subassembly therefore exposes only the outer ring and inner ring as
solver bodies, with one revolute joint between them. This intentionally omits
ball/cage contact kinematics while ensuring the visible balls follow the bearing
through FreeCAD assembly simulation instead of becoming unconstrained bodies.

## Electronics Packaging

The controller PCB is a 44.4 mm circular board behind the rear motor bearing. It
has a 10 mm center service bore, four M2 mounting holes, four large edge notches
for the rear structural columns, three phase-terminal pin holes, and four
power/CAN pin holes. Two rear-cover apertures expose the terminal bodies without
removing the controller. The board remains removable after the rear cover and
terminal screws are released.

## Assembly Order

1. Press the stator stack into the motor shell and pot the twelve winding packs.
2. Install the rear bearing into the four-arm spider and bolt the spider to the
   shell's rear columns.
3. Insert the rotor/shaft from the reducer side and support it with the front
   motor bearing in the reducer bulkhead.
4. Bolt the motor shell to the reducer housing with the six-hole front interface.
5. Insert the first fixed ring and planetary stage, the 5x10x3 interstage
   bearing, then the second fixed ring and planetary stage from the open front.
6. Install the paired output bearings in the removable output cap, then bolt the
   cap to the reducer housing.
7. Install the PCB and terminals on the rear-cover standoffs, connect phases and
   sensors, and attach the rear cover.

This sequence avoids the trapped 43 mm ring-gear problem in Case 16: both ring
inserts and carriers enter through the open reducer front before the bearing cap
is installed.

## File Layout

Every part is a marimo notebook with one feature block per cell. The stator,
rotor and controller are sub-assembly notebooks, and the product is an assembly
notebook that composes all of them with `scad.use`. Shared numbers and helpers
live in plain modules that the notebooks import, so the cell cache tracks them.

| File | Kind | Role |
| --- | --- | --- |
| `integrated_bldc_joint_actuator.py` | assembly notebook | product: components, bearings, public datums, constraints, strict solve |
| `bldc_stator.py`, `bldc_rotor.py`, `integrated_controller.py` | sub-assembly notebooks | stator core + 12 winding packs; rotor/shaft/sun + 14 magnets; PCB + 6 MOSFETs + 2 terminals |
| `reducer_housing.py`, `motor_shell.py`, `rear_bearing_spider.py`, `rear_electronics_cover.py`, `output_bearing_cap.py` | part notebooks | fixed housing stack |
| `stator_core.py`, `slot_winding.py`, `rotor_core_shaft_sun.py`, `rotor_magnet.py` | part notebooks | motor parts; one winding and one magnet definition are reused at every slot and pole |
| `ring_gear.py`, `planet_gear.py` | part families | used once per stage: `scad.use("planet_gear.py", id="stage2_reusable_planet", STAGE="stage2")` |
| `stage1_carrier_sun.py`, `output_carrier_flange.py` | part notebooks | stage-1 carrier with the stage-2 sun; stage-2 carrier with the output flange |
| `controller_pcb.py`, `power_mosfet.py` | part notebooks | controller board; one MOSFET reused at all six bridge positions |
| `terminal_block.py` | part family | rear terminals: `scad.use("terminal_block.py", id="power_can_terminal", PIN_COUNT=4, TERMINAL_NAME=...)` |
| `dimensions.py` | plain module | envelope, `StageSpec` per stage, `BearingSpec` per bearing size, `validate_design_dimensions()` |
| `common.py`, `materials.py`, `bearings.py` | plain modules | geometry, placement and connector helpers; materials; standard-bearing factory and placements |
| `export.py` | script | runs the notebook and writes `out/integrated_bldc_joint_actuator.scadpkg` |
| `export_step.py`, `export_fcstd.py`, `export_mjcf.py`, `export_all.py` | scripts | AP242 STEP, FCStd, MuJoCo MJCF; `export_all.py` captures once and runs the three in parallel |
| `render_showcase.py` | script | assembled, front and exploded studio renders plus the exploded GIF |

## Strength And Thermal Notes

- The motor shell retains 1.80 mm radial wall around the stator and the reducer
  shell retains 2.20 mm around the steel ring inserts.
- The 43 mm PCD case holes pass through 18.5 mm-radius end lands, retaining
  1.4 mm of continuous aluminum ligament on the bore side of each M3 clearance
  hole instead of clipping only the thin cylindrical shell.
- The front reducer bulkhead is 8 mm long around the 19 mm motor bearing.
- Two adjacent output bearings form a 10 mm stack with 5 mm center spacing to
  distribute overturning load.
- The output flange leaves 4.15 mm radial ligament beyond the M3 tapped-hole edges.
- The output face carries a 1.5 mm-high, Ø15.96 locating pilot. Mating links use
  the pilot for concentric location and six Ø3.3 clearance holes with Ø6 socket-
  head counterbores; the screws provide clamp load rather than radial location.
- External robot structure clamps the continuous Ø50 reducer sleeve at the
  `case_clamp_axis` datum (`Z = 20.0`) instead of sharing the internal output-cap
  retention screws.
- The stator yoke contacts the aluminum shell over its full active length for a
  direct thermal path; controller heat can flow through the rear standoffs and
  cover.
- Detailed tooth stress, bearing life, winding thermal limits, rotor retention,
  and fastener preload still require engineering calculation and prototype test.
