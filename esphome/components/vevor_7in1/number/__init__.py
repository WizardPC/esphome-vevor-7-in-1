import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import number

from .. import CONF_VEVOR_7IN1_ID, Vevor7in1, vevor_7in1_ns

# Watchdog settings, exposed in Home Assistant.
#
# This file holds NO policy: it declares two entities and hands the value to the component, which
# owns the logic on its own (Vevor7in1::watch_radio_(), see dev/docs/firmware-design-notes.md
# §8). The YAML only names and bounds the entity.

DEPENDENCIES = ["vevor_7in1"]

CONF_TYPE = "type"

VevorParameter = vevor_7in1_ns.class_(
    "VevorParameter", number.Number, cg.Parented.template(Vevor7in1)
)

# Component-side identifier (see WatchdogParam in vevor_7in1.h) and BOUNDS of each setting.
# Bounds live here, with the parameter's semantics: the YAML only names the entity.
#   type: (slug, min, max, step)
PARAMETERS = {
    "rearm_after_slots": (0, 1.0, 30.0, 1.0),
    "max_restart_delay": (1, 60.0, 3600.0, 20.0),
    # Station identity: decimal, like the "Station ID" sensor publishes it (33995 = 0x84cb).
    # 0 = learn the first station seen; any other value pins it and drops every other ID.
    "station_id": (2, 0.0, 65535.0, 1.0),
    # Below this many pulses a capture cannot hold a burst: it is a fragment (70-96, normal) or
    # silence (2-7, a deaf chip). The watchdog re-arms the radio on two consecutive silent captures.
    "pulse_threshold": (3, 10.0, 200.0, 5.0),
}

CONFIG_SCHEMA = number.number_schema(VevorParameter).extend(
    {
        cv.GenerateID(CONF_VEVOR_7IN1_ID): cv.use_id(Vevor7in1),
        cv.Required(CONF_TYPE): cv.one_of(*PARAMETERS, lower=True),
    }
)


async def to_code(config):
    slug, low, high, step = PARAMETERS[config[CONF_TYPE]]
    var = await number.new_number(config, min_value=low, max_value=high, step=step)
    parent = await cg.get_variable(config[CONF_VEVOR_7IN1_ID])
    cg.add(var.set_parent(parent))
    cg.add(var.set_parameter(slug))
