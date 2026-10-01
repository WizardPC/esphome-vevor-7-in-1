import esphome.automation as automation
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import remote_base, remote_receiver
from esphome.const import CONF_ID

# Composant d'extraction de trames Vevor 7-en-1 depuis le flux démodulé du CC1101.
#
# Rôle volontairement limité : convertir des impulsions en octets et remettre la trame brute au
# YAML (trigger `on_frame`). La logique de protocole (en-tête, checksum, compteur, plages de
# valeurs) vit dans `includes/vevor_protocol.h`, du C++ pur testable sans matériel
# (`tools/run_tests.sh`). Cette séparation permet de tester le décodage à froid et de ne
# reflasher que pour la partie radio.
#
# ⚠️ AUCUN ACCÈS SPI. Ce composant déclarait autrefois un second périphérique sur le bus SPI du
# CC1101 pour lire ses registres de diagnostic. Mesuré le 01/10/2026, en alternance avec un
# firmware de référence sur la même carte et dans les mêmes fenêtres d'émission : 0 capture et
# 0 trame AVEC ce second périphérique, 5 trames/60 s SANS lui. La puce doit rester le seul
# périphérique de son bus — l'instrumentation a donc été supprimée, pas désactivée.

CODEOWNERS = ["@projet-vevor-7in1"]
DEPENDENCIES = ["remote_receiver"]

CONF_RECEIVER_ID = "receiver_id"
CONF_BIT_PERIOD = "bit_period"
CONF_ON_FRAME = "on_frame"

vevor_7in1_ns = cg.esphome_ns.namespace("vevor_7in1")
Vevor7in1 = vevor_7in1_ns.class_(
    "Vevor7in1",
    cg.Component,
    remote_base.RemoteReceiverDumperBase,
)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(Vevor7in1),
            cv.Required(CONF_RECEIVER_ID): cv.use_id(
                remote_receiver.RemoteReceiverComponent
            ),
            # Période bit nominale : 90 µs (valeur du protocole publiée et du montage témoin qui
            # décode) — le composant essaie de toute façon plusieurs périodes voisines à chaque
            # capture, ce paramètre n'est qu'un point de départ pour les logs.
            cv.Optional(CONF_BIT_PERIOD, default="90us"): cv.positive_time_period_microseconds,
            cv.Optional(CONF_ON_FRAME): automation.validate_automation(single=True),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    receiver = await cg.get_variable(config[CONF_RECEIVER_ID])
    cg.add(var.set_receiver(receiver))
    cg.add(var.set_bit_period(int(config[CONF_BIT_PERIOD].total_microseconds)))

    if CONF_ON_FRAME in config:
        await automation.build_automation(
            var.get_frame_trigger(),
            [(cg.std_vector.template(cg.uint8), "x")],
            config[CONF_ON_FRAME],
        )
