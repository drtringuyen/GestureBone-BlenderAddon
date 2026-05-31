"""
plotting/ops_bind_mesh.py — Steps 12a, 12b, 12c: bind mesh operators.
Adapted from rig_generation/ops_actions.py; reads from arm.gesturebone_props chains.
"""
import bpy
import bmesh
from bpy.props import StringProperty
from .utils import _active_plotting_arm


def _bind_resolve(context, bone_name):
    """Return (arm, chain) or raise ValueError."""
    arm = _active_plotting_arm(context)
    if arm is None:
        raise ValueError("Active object is not a PLOTTING rig")
    chain = arm.gesturebone_props.chains.get(bone_name)
    if chain is None:
        raise ValueError(f"No chain for bone '{bone_name}'")
    if not chain.bind_mesh:
        raise ValueError("Bind Mesh not set on this chain")
    if not chain.sample_mesh:
        raise ValueError("Sample Mesh not set — run Steps 1–9 first")
    return arm, chain


class GESTUREBONE_OT_BindStepMoveCollection(bpy.types.Operator):
    bl_idname      = "gesturebone.bind_step_move_collection"
    bl_label       = "12a. Move Bind Mesh to Collection"
    bl_description = "Create (or find) 'Original Mesh' collection and move the bind mesh there"
    bl_options     = {'REGISTER', 'UNDO'}

    bone_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        try:
            arm, chain = _bind_resolve(context, self.bone_name)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        bind_mesh = chain.bind_mesh
        coll      = bpy.data.collections.get("Original Mesh")
        if coll is None:
            legacy = bpy.data.collections.get("Mesh")
            coll   = legacy if legacy else bpy.data.collections.new("Original Mesh")
            if legacy:
                coll.name = "Original Mesh"
            else:
                context.scene.collection.children.link(coll)

        for c in list(bind_mesh.users_collection):
            if c != coll:
                c.objects.unlink(bind_mesh)
        if bind_mesh.name not in coll.objects:
            coll.objects.link(bind_mesh)

        props = arm.gesturebone_props
        props.last_step      = self.bl_idname
        props.completed_step = 12
        self.report({'INFO'}, f"'{bind_mesh.name}' → 'Original Mesh'")
        return {'FINISHED'}


class GESTUREBONE_OT_BindStepSyncMaterials(bpy.types.Operator):
    bl_idname      = "gesturebone.bind_step_sync_materials"
    bl_label       = "12b. Sync Materials to Sample"
    bl_description = "Clear sample mesh material slots then copy from bind mesh"
    bl_options     = {'REGISTER', 'UNDO'}

    bone_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        try:
            arm, chain = _bind_resolve(context, self.bone_name)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        bind_mesh   = chain.bind_mesh
        sample_mesh = chain.sample_mesh
        sample_mesh.data.materials.clear()
        for mat in bind_mesh.data.materials:
            sample_mesh.data.materials.append(mat)

        props = arm.gesturebone_props
        props.last_step      = self.bl_idname
        props.completed_step = 13
        self.report({'INFO'}, f"Materials: {[m.name for m in bind_mesh.data.materials]} → '{sample_mesh.name}'")
        return {'FINISHED'}


class GESTUREBONE_OT_BindStepCopyGeometry(bpy.types.Operator):
    bl_idname      = "gesturebone.bind_step_copy_geometry"
    bl_label       = "12c. Copy Geometry to Sample"
    bl_description = "Transform bind mesh vertices into sample mesh local space via bmesh"
    bl_options     = {'REGISTER', 'UNDO'}

    bone_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        try:
            arm, chain = _bind_resolve(context, self.bone_name)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        bind_mesh   = chain.bind_mesh
        sample_mesh = chain.sample_mesh
        world_to_local = sample_mesh.matrix_world.inverted() @ bind_mesh.matrix_world
        bm = bmesh.new()
        bm.from_mesh(bind_mesh.data)
        bmesh.ops.transform(bm, matrix=world_to_local, verts=bm.verts)
        bm.to_mesh(sample_mesh.data)
        bm.free()
        sample_mesh.data.update()

        props = arm.gesturebone_props
        props.last_step      = self.bl_idname
        props.completed_step = 14
        chain.rig_completed_step = 14
        self.report({'INFO'}, f"Geometry: '{bind_mesh.name}' → '{sample_mesh.name}'")
        return {'FINISHED'}


class GESTUREBONE_OT_BindToMesh(bpy.types.Operator):
    bl_idname      = "gesturebone.bind_to_mesh"
    bl_label       = "Bind to Mesh"
    bl_description = "Run 12a + 12b + 12c in one shot (used by Auto Rig)"
    bl_options     = {'REGISTER', 'UNDO'}

    bone_name: StringProperty()

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        chain = arm.gesturebone_props.chains.get(self.bone_name)
        if chain is None:
            self.report({'ERROR'}, f"No chain for bone '{self.bone_name}'")
            return {'CANCELLED'}
        if chain.bind_mesh is None:
            return {'FINISHED'}  # silent no-op

        for idname in (
            "gesturebone.bind_step_move_collection",
            "gesturebone.bind_step_sync_materials",
            "gesturebone.bind_step_copy_geometry",
        ):
            ns, name = idname.split('.', 1)
            if 'CANCELLED' in getattr(getattr(bpy.ops, ns), name)(bone_name=self.bone_name):
                return {'CANCELLED'}

        self.report({'INFO'}, f"Bound '{chain.bind_mesh.name}' → '{chain.sample_mesh.name}'")
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_BindStepMoveCollection,
    GESTUREBONE_OT_BindStepSyncMaterials,
    GESTUREBONE_OT_BindStepCopyGeometry,
    GESTUREBONE_OT_BindToMesh,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
