import bpy


class EXAMPLE_OT_HelloWorld(bpy.types.Operator):
    bl_idname = "example.hello_world"
    bl_label = "Hello World"

    def execute(self, context):
        print("Hello from Example Module!")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(EXAMPLE_OT_HelloWorld)


def unregister():
    bpy.utils.unregister_class(EXAMPLE_OT_HelloWorld)
