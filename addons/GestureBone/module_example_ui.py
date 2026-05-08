import bpy


class EXAMPLE_UTILS_Draw:

    @staticmethod
    def draw_ui(layout):
        layout.label(text="Example Module UI")
        layout.operator("example.hello_world")


def register():
    pass


def unregister():
    pass
