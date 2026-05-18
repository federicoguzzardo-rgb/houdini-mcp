import hou

def build_dune_network():
    target_path      = "/obj/geo_dunes"
    container_exists = True
    final_node_name  = "OUT_dunes"

    target_node = hou.node(target_path)
    if container_exists and target_node is None:
        raise RuntimeError(
            f"Spec said container exists at {target_path} but hou.node returned None."
        )

    for child in target_node.children():
        child.destroy()

    created = {}

    try:
        # ── Node 1: heightfield base canvas (1000×1000m, 4m spacing for taste-test) ──
        created["dune_base"] = target_node.createNode("heightfield", "dune_base")
        if created["dune_base"] is None:
            raise RuntimeError("createNode returned None for dune_base (type=heightfield)")
        created["dune_base"].setParms({"gridspacing": 4.0})

        # ── Node 2: large-scale FBM dune skeleton ─────────────────────────────
        created["dune_noise"] = target_node.createNode("heightfield_noise", "dune_noise")
        if created["dune_noise"] is None:
            raise RuntimeError("createNode returned None for dune_noise (type=heightfield_noise)")
        created["dune_noise"].setInput(0, created["dune_base"])
        created["dune_noise"].setParms({
            "amp":         15.0,
            "elementsize": 80.0,
            "rough":       0.55,
            "basis":       "perlin",
            "combine":     "add",
        })

        # ── Node 3: solver SOP — slipface avalanche ────────────────────────────
        created["solver_avalanche"] = target_node.createNode("solver", "solver_avalanche")
        if created["solver_avalanche"] is None:
            raise RuntimeError("createNode returned None for solver_avalanche (type=solver)")
        created["solver_avalanche"].setInput(0, created["dune_noise"])

        sol = created["solver_avalanche"]
        existing_spares = [p.name() for p in sol.spareParms()]
        if "repose_deg" not in existing_spares:
            sol.addSpareParmTuple(
                hou.FloatParmTemplate("repose_deg", "Repose Degrees", 1,
                                      default_value=(34.0,), min=25.0, max=45.0))

        sol.allowEditingOfContents()
        vw = sol.createNode("volumewrangle", "wrangle_avalanche")
        if vw is None:
            raise RuntimeError("createNode returned None for wrangle_avalanche (type=volumewrangle)")
        sol_inputs = sol.indirectInputs()
        if sol_inputs:
            vw.setInput(0, sol_inputs[0])

        vw.setParms({"snippet": """
/* Slipface avalanche — one pass per solver iteration */
float repose = radians(chf("../repose_deg"));
float voxdx  = volumevoxelsize(0, "height").x;
float max_dh = tan(repose) * voxdx;

vector vp = set(@ix, @iy, @iz);
float h_c = volumeindex(0, "height", vp);

int nx[] = array( 1, -1,  0,  0);
int nz[] = array( 0,  0,  1, -1);

float flux = 0.0;
for (int i = 0; i < 4; i++) {
    vector vn  = vp + set(nx[i], 0, nz[i]);
    float  h_n = volumeindex(0, "height", vn);
    float  dh  = h_c - h_n;
    if (dh > max_dh) {
        flux -= (dh - max_dh) * 0.25;
    }
}
setvolumesample(0, "height", vp, h_c + flux);
"""})
        sol.layoutChildren()

        # ── Node 4: wind distortion ─────────────────────────────────────────────
        # NOTE: heightfield_erode::2.0 fails with native volume format in 19.5.
        # Erode nodes omitted for taste test — investigate in HDA UI phase.
        created["distort_wind"] = target_node.createNode("heightfield_distort", "distort_wind")
        if created["distort_wind"] is None:
            raise RuntimeError("createNode returned None for distort_wind (type=heightfield_distort)")
        created["distort_wind"].setInput(0, created["solver_avalanche"])
        created["distort_wind"].setParms({"amp": 1.5, "element_size": 25.0})

        # ── Node 5: slope + occlusion masks ────────────────────────────────────
        created["mask_features"] = target_node.createNode("heightfield_maskbyfeature", "mask_features")
        if created["mask_features"] is None:
            raise RuntimeError("createNode returned None for mask_features (type=heightfield_maskbyfeature)")
        created["mask_features"].setInput(0, created["distort_wind"])

        # ── Node 6: convert to polygon mesh ────────────────────────────────────
        created["convert_mesh"] = target_node.createNode("convertheightfield", "convert_mesh")
        if created["convert_mesh"] is None:
            raise RuntimeError("createNode returned None for convert_mesh (type=convertheightfield)")
        created["convert_mesh"].setInput(0, created["mask_features"])
        try:
            created["convert_mesh"].setParms({"bakecolor": 1, "polysoup": 0})
        except hou.OperationFailed:
            pass

        # ── Node 7: output null ─────────────────────────────────────────────────
        created["OUT_dunes"] = target_node.createNode("null", "OUT_dunes")
        if created["OUT_dunes"] is None:
            raise RuntimeError("createNode returned None for OUT_dunes (type=null)")
        created["OUT_dunes"].setInput(0, created["convert_mesh"])

        # ── Layout + flags ──────────────────────────────────────────────────────
        target_node.layoutChildren()
        final_node = created[final_node_name]
        final_node.setDisplayFlag(True)
        final_node.setRenderFlag(True)

        # ── Cook + validate ─────────────────────────────────────────────────────
        final_node.cook(force=True)
        errs = final_node.errors()
        if errs:
            raise RuntimeError(f"Final node '{final_node_name}' has cook errors: {errs}")

        print(f"SUCCESS: Network built in {target_path}")

    except Exception as e:
        import traceback
        print(f"ERROR_TRACE: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        raise

build_dune_network()
