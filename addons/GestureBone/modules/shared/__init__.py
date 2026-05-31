"""
shared/__init__.py — Registers the shared data layer: ChainDefinition, ArmatureProps, and utilities.
Must be loaded before the plotting and gesture modules.
"""
from . import chain, arm_props


def register():
    chain.register()
    arm_props.register()


def unregister():
    arm_props.unregister()
    chain.unregister()
