import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import number

from .. import CONF_VEVOR_7IN1_ID, Vevor7in1, vevor_7in1_ns

# Watchdog settings, exposed in Home Assistant.
#
# This file holds NO policy: it declares two entities and hands the value to the component, which
# owns the logic on its own (Vevor7in1::surveiller_radio_(), see dev/docs/firmware-design-notes.md
# §8). The YAML only names and bounds the entity.

DEPENDENCIES = ["vevor_7in1"]

CONF_TYPE = "type"

VevorParametre = vevor_7in1_ns.class_(
    "VevorParametre", number.Number, cg.Parented.template(Vevor7in1)
)

# Identifiant côté composant (voir ParametreVeille dans vevor_7in1.h) et BORNES de chaque réglage.
# Les bornes vivent ici, avec la sémantique du paramètre : le YAML ne fait que nommer l'entité.
#   type: (identifiant, min, max, pas)
PARAMETRES = {
    "creneaux_avant_rearmement": (0, 1.0, 30.0, 1.0),
    "duree_max_avant_redemarrage": (1, 60.0, 3600.0, 20.0),
}

CONFIG_SCHEMA = number.number_schema(VevorParametre).extend(
    {
        cv.GenerateID(CONF_VEVOR_7IN1_ID): cv.use_id(Vevor7in1),
        cv.Required(CONF_TYPE): cv.one_of(*PARAMETRES, lower=True),
    }
)


async def to_code(config):
    identifiant, mini, maxi, pas = PARAMETRES[config[CONF_TYPE]]
    var = await number.new_number(config, min_value=mini, max_value=maxi, step=pas)
    parent = await cg.get_variable(config[CONF_VEVOR_7IN1_ID])
    cg.add(var.set_parent(parent))
    cg.add(var.set_parametre(identifiant))
