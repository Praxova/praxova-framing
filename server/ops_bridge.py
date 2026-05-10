"""Blender operators to start/stop the in-Blender MCP bridge."""

import bpy

from . import bridge


class PRAXOVA_OT_start_bridge(bpy.types.Operator):
    """Start the localhost JSON-RPC bridge.

    The external Praxova Framing MCP server connects to this bridge to
    drive lumber/sheet placement, on-center duplication, and cut-list
    generation from an LLM client.
    """

    bl_idname = "praxova.start_bridge"
    bl_label = "Start MCP Bridge"
    bl_description = (
        "Start the localhost JSON-RPC bridge that the Praxova Framing MCP "
        "server connects to"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return not bridge.is_running()

    def execute(self, context):
        port = context.scene.praxova_framing.bridge_port
        try:
            host, actual_port = bridge.start("127.0.0.1", port)
        except bridge.BridgeAlreadyRunning as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}
        except OSError as e:
            self.report(
                {'ERROR'},
                f"Bridge failed to bind 127.0.0.1:{port} ({e}). "
                f"Try a different port.",
            )
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Praxova MCP bridge listening on {host}:{actual_port}",
        )
        return {'FINISHED'}


class PRAXOVA_OT_stop_bridge(bpy.types.Operator):
    """Stop the localhost JSON-RPC bridge."""

    bl_idname = "praxova.stop_bridge"
    bl_label = "Stop MCP Bridge"
    bl_description = "Stop the Praxova Framing MCP bridge"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bridge.is_running()

    def execute(self, context):
        bridge.stop()
        self.report({'INFO'}, "Praxova MCP bridge stopped")
        return {'FINISHED'}
