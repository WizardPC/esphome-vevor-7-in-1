import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import button

from .. import CONF_VEVOR_7IN1_ID, Vevor7in1, vevor_7in1_ns

# Diagnostic buttons, owned by the component.
#
# They used to be `platform: template` with a lambda in the YAML: the YAML carries only logs and
# declarations (owner's rule, design notes §10). "Re-apply radio config" calls EXACTLY the same
# re-arm as the watchdog, so the two can no longer drift apart.

DEPENDENCIES = ["vevor_7in1"]

CONF_TYPE = "type"

VevorBouton = vevor_7in1_ns.class_(
    "VevorBouton", button.Button, cg.Parented.template(Vevor7in1)
)

# Identifiant côté composant (voir VevorBouton dans vevor_bouton.h).
BOUTONS = {
    "dump_pulses": 0,
    "reapply_radio": 1,
}

CONFIG_SCHEMA = button.button_schema(VevorBouton).extend(
    {
        cv.GenerateID(CONF_VEVOR_7IN1_ID): cv.use_id(Vevor7in1),
        cv.Required(CONF_TYPE): cv.one_of(*BOUTONS, lower=True),
    }
)


async def to_code(config):
    var = await button.new_button(config)
    parent = await cg.get_variable(config[CONF_VEVOR_7IN1_ID])
    cg.add(var.set_parent(parent))
    cg.add(var.set_type(BOUTONS[config[CONF_TYPE]]))
